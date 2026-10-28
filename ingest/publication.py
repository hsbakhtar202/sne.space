"""Durable publication state: ingested ≠ published until index/overlay/UI agree.

State machine per event (durably fsynced at every transition):

  (absent) → committed+pending → publishing → published
                                 ↘ failed  → (retry) → publishing → …

Crash points that MUST remain recoverable:
  - after event JSON commit, before pending marker
  - after pending marker, before/during overlay+SQLite
  - after overlay write, before published marker
  - SQLite upsert failure after JSON commit

UI may keep the previous published view while status is pending/failed;
it must never claim ``published`` for a mixed/partial generation.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


# Test/injection hooks (set via env). Empty = disabled.
# SNE_PUBLISH_CRASH_AFTER = committed|pending|publishing|overlay|sqlite|published
# SNE_PUBLISH_FAIL_SQLITE = 1  → raise during CatalogStore upsert


def _state_path() -> Path:
    try:
        from serve.data_paths import resolve_runtime_dir
        d = resolve_runtime_dir()
    except Exception:
        d = Path(__file__).resolve().parent.parent / "serve" / "www" / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d / "publication_state.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic replace + best-effort fsync so a crash cannot leave half-written state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    payload = json.dumps(data, indent=2, sort_keys=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    # fsync directory entry on POSIX
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def load_state() -> Dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"events": {}, "updated_utc": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("events"), dict):
            return raw
    except Exception:
        pass
    return {"events": {}, "updated_utc": None}


def save_state(state: Dict[str, Any]) -> None:
    state = dict(state)
    state["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_write_json(_state_path(), state)


def _maybe_crash(point: str) -> None:
    want = (os.environ.get("SNE_PUBLISH_CRASH_AFTER") or "").strip().lower()
    if want and want == point:
        # Durable state for this transition must already be on disk.
        raise SystemExit(f"SNE_PUBLISH_CRASH_AFTER={point}")


def _file_fingerprint(path: Path) -> Dict[str, Any]:
    data = path.read_bytes()
    st = path.stat()
    return {
        "sha1": hashlib.sha1(data).hexdigest(),
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
        "path": str(path),
    }


def _update_entry(name: str, **fields: Any) -> dict:
    state = load_state()
    events = state.setdefault("events", {})
    entry = dict(events.get(name) or {"name": name, "generation": 0})
    entry.update(fields)
    entry["name"] = name
    entry["updated_at"] = time.time()
    events[name] = entry
    save_state(state)
    return entry


def mark_ingested(name: str, event_path: Path, *, generation: Optional[int] = None) -> dict:
    """Durable: event JSON committed; publication not yet attempted."""
    state = load_state()
    prev = (state.get("events") or {}).get(name) or {}
    gen = generation if generation is not None else int(prev.get("generation") or 0) + 1
    entry = _update_entry(
        name,
        generation=gen,
        ingest_status="committed",
        publish_status="pending",
        ingested_at=time.time(),
        published_at=None,
        error=None,
        fingerprint=_file_fingerprint(event_path) if event_path.is_file() else None,
    )
    _maybe_crash("committed")
    _maybe_crash("pending")
    return entry


def mark_publishing(name: str) -> dict:
    """Durable: publication attempt in progress (overlay/SQLite)."""
    entry = _update_entry(name, publish_status="publishing", error=None)
    _maybe_crash("publishing")
    return entry


def mark_published(name: str, *, details: Optional[dict] = None) -> dict:
    fields: Dict[str, Any] = {
        "publish_status": "published",
        "published_at": time.time(),
        "error": None,
    }
    if details:
        fields["publish_details"] = details
    entry = _update_entry(name, **fields)
    _maybe_crash("published")
    return entry


def mark_publish_failed(name: str, error: str) -> dict:
    return _update_entry(
        name,
        publish_status="failed",
        error=str(error)[:500],
    )


def pending_names() -> List[str]:
    """Names that need (re)publication — pending, failed, or interrupted publishing."""
    state = load_state()
    out = []
    for name, entry in (state.get("events") or {}).items():
        if entry.get("publish_status") in {"pending", "failed", "publishing"}:
            out.append(name)
    return sorted(out)


def is_fully_published(name: str) -> bool:
    entry = (load_state().get("events") or {}).get(name) or {}
    return entry.get("publish_status") == "published" and entry.get("ingest_status") == "committed"


def publish_event_paths(paths: Iterable[Path], *, catalog_db: Optional[Path] = None) -> dict:
    """Publish event files and update durable state. Idempotent.

    Pending marker is written BEFORE the publication attempt. SQLite/overlay
    failures leave ``failed`` (or crash leaves ``publishing``/``pending``) for recovery.
    """
    from ingest.catalog_publish import (
        atomic_write_json_array,
        event_to_catalog_item,
        load_event_file,
        merge_overlay,
        overlay_path,
    )
    from ingest.manager import SUPERNOVAE_OUTPUT

    path_list = [Path(p) for p in paths if Path(p).is_file()]
    pairs: List[tuple[str, Path]] = []
    for p in path_list:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw:
                pairs.append((next(iter(raw)), p))
        except Exception:
            continue

    # 1) Durable pending BEFORE any derived-index mutation
    for name, p in pairs:
        mark_ingested(name, p)
        mark_publishing(name)

    names = [n for n, _ in pairs]
    try:
        db = catalog_db
        if db is None:
            db = Path(SUPERNOVAE_OUTPUT) / ".index" / "catalog.db"

        # Split overlay write and SQLite upsert so failure modes are distinct.
        items = []
        for name, p in pairs:
            loaded = load_event_file(p)
            if loaded:
                items.append(event_to_catalog_item(loaded[0], loaded[1]))

        op = overlay_path()
        existing: List[dict] = []
        if op.is_file():
            try:
                raw = json.loads(op.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    existing = [x for x in raw if isinstance(x, dict)]
            except Exception:
                existing = []
        merged = merge_overlay(existing, items)
        atomic_write_json_array(op, merged)
        _maybe_crash("overlay")

        upserted = 0
        if (os.environ.get("SNE_PUBLISH_FAIL_SQLITE") or "").strip() in {"1", "true", "yes"}:
            _maybe_crash("sqlite")
            raise RuntimeError("injected SQLite/catalog publication failure")
        if db.is_file():
            from serve.catalog_store import CatalogStore
            store = CatalogStore(db)
            store.load_existing()
            upserted = store.upsert_catalog_items(items)
        _maybe_crash("sqlite")

        result = {
            "items": len(items),
            "overlay_path": str(op),
            "upserted": upserted,
            "overlay_size": len(merged),
            "published_names": names,
            "state": "published",
        }
        for name in names:
            mark_published(name, details={"upserted": upserted})
        return result
    except SystemExit:
        raise
    except Exception as exc:
        for name in names:
            mark_publish_failed(name, str(exc))
        return {"state": "failed", "error": str(exc), "names": names}


def recover_pending(*, catalog_db: Optional[Path] = None) -> dict:
    """Re-publish any pending/failed/publishing events found on disk."""
    from ingest.manager import SUPERNOVAE_OUTPUT

    root = Path(SUPERNOVAE_OUTPUT)
    paths = []
    for name in pending_names():
        hits = list(root.glob(f"sne-*/{name}.json"))
        paths.extend(hits)
    if not paths:
        return {"recovered": 0}
    # Clear injection hooks during recovery unless explicitly kept
    result = publish_event_paths(paths, catalog_db=catalog_db)
    result["recovered"] = len(paths)
    return result
