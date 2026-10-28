"""Cross-process exclusive lock for event JSON read-modify-write cycles.

``os.replace`` makes a single write atomic, but does **not** prevent:

  1. A reads event
  2. B reads event
  3. A writes merge
  4. B writes merge  → A's updates lost

``pull_recent``, historical backfill, and corpus sync must all take this lock
for the full RMW window (reload → merge → atomic write). Lock files live on the
same shared runtime filesystem as ``provider_quota`` locks
(``SNE_RUNTIME_DIR`` / ``SNE_INGEST_LOCK_DIR``).
"""
from __future__ import annotations

import hashlib
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Tuple

_local = threading.local()


def _lock_dir() -> Path:
    try:
        from ingest.provider_quota import _runtime_lock_dir
        return _runtime_lock_dir()
    except Exception:
        p = Path(__file__).resolve().parent.parent / "serve" / "www" / "assets"
        p.mkdir(parents=True, exist_ok=True)
        return p


def lock_path_for(event_path: Path) -> Path:
    key = hashlib.sha1(str(Path(event_path).resolve()).encode("utf-8")).hexdigest()[:24]
    d = _lock_dir() / "event_locks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.lock"


def _holders() -> Dict[str, Tuple[object, int]]:
    if not hasattr(_local, "holders"):
        _local.holders = {}
    return _local.holders  # type: ignore[return-value]


@contextmanager
def event_file_lock(event_path: Path) -> Iterator[None]:
    """Hold an exclusive ``fcntl`` lock for one event file path (reentrant per thread)."""
    import fcntl

    path = Path(event_path)
    key = str(path.resolve())
    holders = _holders()
    if key in holders:
        fh, depth = holders[key]
        holders[key] = (fh, depth + 1)
        try:
            yield
        finally:
            fh, depth = holders[key]
            if depth <= 1:
                holders.pop(key, None)
            else:
                holders[key] = (fh, depth - 1)
        return

    lock_file = lock_path_for(path)
    fh = open(lock_file, "a+", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} path={path}\n")
    fh.flush()
    holders[key] = (fh, 1)
    try:
        yield
    finally:
        holders.pop(key, None)
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass
