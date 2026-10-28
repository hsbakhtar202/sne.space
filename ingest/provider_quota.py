"""Shared rate-limit / quota policy for TNS and ALeRCE.

Historical backfill and the 15-minute ``pull_recent`` loop must not stampede the
same upstream APIs, and discovery must outrank historical recovery.

Coordination is **cross-process** via lock files under the persistent runtime
directory (``SNE_RUNTIME_DIR`` / ``sne_runtime`` volume). ``fcntl`` only works
when every participant mounts the **same** filesystem path. If the web server
and backfill run in separate containers, both must mount ``sne_runtime`` (or
set ``SNE_INGEST_LOCK_DIR`` to a shared mount). Without that, this module
cannot coordinate them — see ``lock_coordination_ok()``.

Priority order (intended):
  1. Recent discovery / ``pull_recent``  (holds exclusive priority lock for the
     *entire* cycle, including enrichment longer than 120s)
  2. Recent enrichment triggered by discovery
  3. Historical backfill (yields before every provider acquire; never holds the
     priority lock while waiting on HTTP / 429 backoff)
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

_lock = threading.RLock()
_next_ok: dict[str, float] = {"tns": 0.0, "alerce": 0.0}
_min_interval: dict[str, float] = {"tns": 0.6, "alerce": 0.35}
_counters: dict[str, int] = {
    "tns_requests": 0,
    "alerce_requests": 0,
    "tns_429": 0,
    "alerce_429": 0,
    "tns_backoff_s_total": 0,
    "alerce_backoff_s_total": 0,
    "backfill_yields": 0,
}
_backfill_depth: int = 0
_priority_fh = None  # type: ignore
_priority_local_holders = 0


def _runtime_lock_dir() -> Path:
    """Directory for cross-process locks — must be on a shared volume in prod."""
    override = (os.environ.get("SNE_INGEST_LOCK_DIR") or "").strip()
    if override:
        p = Path(override).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    try:
        from serve.data_paths import runtime_write_path
        # runtime_write_path returns a file path; use its parent (RUNTIME_DIR).
        return runtime_write_path(".lockdir_placeholder").parent
    except Exception:
        p = Path(__file__).resolve().parent.parent / "serve" / "www" / "assets"
        p.mkdir(parents=True, exist_ok=True)
        return p


def _lock_paths() -> tuple[Path, Path, Path]:
    d = _runtime_lock_dir()
    return (
        d / "ingest_recent_priority.lock",
        d / "ingest_recent_priority.lease",
        d / "ingest_provider_gate.lock",
    )


def lock_coordination_ok() -> dict:
    """Diagnostics: whether this process can participate in shared coordination."""
    priority, lease, gate = _lock_paths()
    d = priority.parent
    return {
        "lock_dir": str(d),
        "writable": os.access(d, os.W_OK),
        "SNE_RUNTIME_DIR": os.environ.get("SNE_RUNTIME_DIR") or "",
        "SNE_INGEST_LOCK_DIR": os.environ.get("SNE_INGEST_LOCK_DIR") or "",
        "on_data_mount": str(d).startswith("/data/"),
        "priority_lock": str(priority),
        "note": (
            "Web server and backfill MUST share this directory via the sne_runtime "
            "volume (or SNE_INGEST_LOCK_DIR). Separate hosts without a shared FS "
            "cannot use fcntl coordination."
        ),
    }


def mark_recent_ingest_active(hold_seconds: float = 120.0) -> None:
    """Deprecated timer lease. Prefer ``recent_ingest_priority()``.

    Kept as crash-safety floor only; it is NOT sufficient for cycles > hold_seconds.
    """
    _, lease, _ = _lock_paths()
    lease.write_text(str(time.time() + hold_seconds), encoding="utf-8")


def _fcntl():
    import fcntl
    return fcntl


@contextmanager
def recent_ingest_priority() -> Iterator[None]:
    """Hold discovery priority for the entire ``pull_recent`` cycle (cross-process).

    Uses an exclusive ``fcntl`` lock on the shared runtime volume. Nested-safe
    within one process. Backfill never holds this lock — it only waits on it.
    """
    global _priority_fh, _priority_local_holders
    fcntl = _fcntl()
    priority, _, _ = _lock_paths()
    priority.parent.mkdir(parents=True, exist_ok=True)
    fh = open(priority, "a+", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} ts={time.time():.3f}\n")
    fh.flush()
    with _lock:
        _priority_local_holders += 1
        if _priority_fh is None:
            _priority_fh = fh
        else:
            fh.close()
            fh = _priority_fh
    try:
        yield
    finally:
        with _lock:
            _priority_local_holders = max(0, _priority_local_holders - 1)
            if _priority_local_holders == 0:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
                try:
                    fh.close()
                except Exception:
                    pass
                _priority_fh = None


def _lease_active() -> bool:
    _, lease, _ = _lock_paths()
    if not lease.is_file():
        return False
    try:
        return time.time() < float(lease.read_text().strip())
    except Exception:
        return False


def discovery_priority_held() -> bool:
    """Non-blocking check: is discovery currently holding the priority lock?"""
    fcntl = _fcntl()
    priority, _, _ = _lock_paths()
    priority.parent.mkdir(parents=True, exist_ok=True)
    fh = open(priority, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
        return _lease_active()
    except BlockingIOError:
        fh.close()
        return True
    except Exception:
        try:
            fh.close()
        except Exception:
            pass
        return _lease_active()


def wait_for_recent_priority(poll: float = 0.5) -> None:
    """Block while discovery holds priority. Does **not** hold any lock itself.

    Safe to call from backfill between / during provider backoff sleeps so a
    historical job cannot monopolize the provider lane once discovery starts.
    """
    while discovery_priority_held():
        with _lock:
            _counters["backfill_yields"] = int(_counters.get("backfill_yields", 0)) + 1
        time.sleep(poll)


@contextmanager
def backfill_mode() -> Iterator[None]:
    """Mark this section as historical backfill so acquire() yields to discovery."""
    global _backfill_depth
    with _lock:
        _backfill_depth += 1
    try:
        yield
    finally:
        with _lock:
            _backfill_depth = max(0, _backfill_depth - 1)


def _interruptible_sleep(seconds: float, *, yield_to_discovery: bool) -> None:
    """Sleep in short slices; if discovery takes priority, return early."""
    end = time.time() + max(0.0, seconds)
    while True:
        if yield_to_discovery and discovery_priority_held():
            return
        remaining = end - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.5, remaining))


def acquire(provider: str, *, is_backfill: bool = False) -> None:
    """Block until ``provider`` may send another request.

    Backfill callers yield to discovery **before** taking a rate-limit slot and
    never hold the discovery priority lock during the subsequent HTTP wait.
    """
    provider = provider.lower().strip()
    as_backfill = is_backfill or _backfill_depth > 0
    if as_backfill:
        wait_for_recent_priority()
    with _lock:
        interval = _min_interval.get(provider, 0.5)
        nxt = _next_ok.get(provider, 0.0)
        now = time.time()
        delay = max(0.0, nxt - now)
        _next_ok[provider] = max(nxt, now) + interval
        _counters[f"{provider}_requests"] = int(_counters.get(f"{provider}_requests", 0)) + 1
    if delay > 0:
        _interruptible_sleep(delay, yield_to_discovery=as_backfill)
        if as_backfill:
            wait_for_recent_priority()


def record_success(provider: str) -> None:
    return None


def record_429(provider: str, reset_seconds: Optional[float] = None) -> None:
    provider = provider.lower().strip()
    wait = float(reset_seconds) if reset_seconds and reset_seconds > 0 else 20.0
    wait = min(max(wait, 5.0), 300.0)
    with _lock:
        _next_ok[provider] = max(_next_ok.get(provider, 0.0), time.time() + wait)
        _counters[f"{provider}_429"] = int(_counters.get(f"{provider}_429", 0)) + 1
        _counters[f"{provider}_backoff_s_total"] = int(
            _counters.get(f"{provider}_backoff_s_total", 0)
        ) + int(wait)
        sibling = "alerce" if provider == "tns" else "tns"
        _next_ok[sibling] = max(_next_ok.get(sibling, 0.0), time.time() + min(wait * 0.25, 15.0))
    # Sleep happens on the next acquire() via _next_ok — interruptible for backfill.


def snapshot() -> dict:
    with _lock:
        now = time.time()
        priority, _, _ = _lock_paths()
        return {
            "tns_wait_s": max(0.0, _next_ok.get("tns", 0.0) - now),
            "alerce_wait_s": max(0.0, _next_ok.get("alerce", 0.0) - now),
            "priority_lock_path": str(priority),
            "priority_local_holders": _priority_local_holders,
            "discovery_priority_held": discovery_priority_held(),
            "lease_active": _lease_active(),
            "backfill_depth": _backfill_depth,
            "coordination": lock_coordination_ok(),
            "counters": dict(_counters),
        }
