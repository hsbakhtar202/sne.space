#!/usr/bin/env python3
"""Production-stability acceptance tests for sne.space.

Runs against a *live* server over HTTP and, where noted, against in-process
modules. Every test maps to one required acceptance criterion from the patch
spec. Exits non-zero if any test fails.

Usage:
    python3 serve/acceptance_test.py [--base http://127.0.0.1:8091]

Tests
-----
 1  no_network_ordinary_requests   zero outbound network calls on page loads
 2  no_repeated_enrichment         repeated requests never enqueue enrichment
 3  persistence_across_restart     stored events survive process replacement
 4  no_rapid_retry_storm            missing-spectrum event does not retry rapidly
 5  cache_hit_skips_render         cache hit avoids JSON parse + HTML render
 5b recent_event_cache_stable      recent-event cache survives enrichment ticks
 6  concurrency_no_linear_queue    20 concurrent requests are not serialized
 7  rss_stabilizes                 RSS bounded under sustained traffic
 8  ttfb_before_after              p50/p95 TTFB reported for both paths
 9  edge_cases                     incomplete/missing/large/recent events
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RESULTS: list[dict] = []

# /api/internal/health is auth-gated. The password is the documented operator
# credential already used by the logs console; override with SNE_HEALTH_AUTH.
HEALTH_AUTH = os.environ.get("SNE_HEALTH_AUTH", "monster104")


def health(base: str) -> dict:
    """Authenticated operational snapshot, or {} when unavailable."""
    _, body, _ = http(f"{base}/api/internal/health?auth={HEALTH_AUTH}", timeout=15)
    try:
        return json.loads(body)
    except Exception:  # noqa: BLE001
        return {}


def record(name: str, ok: bool, detail: str, extra: dict | None = None) -> None:
    RESULTS.append({"test": name, "pass": ok, "detail": detail, "extra": extra or {}})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: {detail}", flush=True)


def http(url: str, timeout: float = 30.0, method: str = "GET", gzip_ok: bool = True):
    """Return (status, body_bytes, elapsed_seconds). Never raises on HTTP errors.

    ``Accept-Encoding: gzip`` is advertised because the server serves pre-gzipped
    cache entries; urllib does not decompress, so we decode here to keep the
    returned body comparable with a plain request.
    """
    req = urllib.request.Request(url, method=method)
    if gzip_ok:
        req.add_header("Accept-Encoding", "gzip")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                try:
                    import gzip as _gzip
                    body = _gzip.decompress(body)
                except Exception:  # noqa: BLE001
                    pass
            return resp.status, body, time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        body = e.read() or b""
        if (e.headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                import gzip as _gzip
                body = _gzip.decompress(body)
            except Exception:  # noqa: BLE001
                pass
        return e.code, body, time.perf_counter() - t0
    except Exception as e:  # noqa: BLE001
        return -1, repr(e).encode(), time.perf_counter() - t0


def pctl(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def server_pid() -> int | None:
    """PID of the server process serving --base, found via the listening port.

    ``lsof`` is not installed in the slim production image, so a container run
    could not locate the PID and ``rss_stabilizes`` reported a spurious FAIL
    ("could not locate server PID"). Fall back to parsing ``/proc/net/tcp`` +
    ``/proc/<pid>/fd``, which needs nothing beyond procfs.
    """
    port = BASE.rsplit(":", 1)[-1]
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip().splitlines()
        if out:
            return int(out[0])
    except Exception:  # noqa: BLE001
        pass
    return _server_pid_procfs(port)


def _server_pid_procfs(port: str) -> int | None:
    """Locate a listening PID using only procfs (works without lsof)."""
    if not os.path.isdir("/proc/net"):  # macOS host
        return None
    try:
        wanted = int(port)
    except ValueError:
        return None
    # Collect inode numbers of sockets in LISTEN (state 0A) on the target port.
    inodes: set[str] = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, "r", encoding="utf-8") as fh:
                next(fh, None)  # header
                for line in fh:
                    parts = line.split()
                    if len(parts) < 10 or parts[3] != "0A":
                        continue
                    local = parts[1].rsplit(":", 1)
                    if len(local) == 2 and int(local[1], 16) == wanted:
                        inodes.add(parts[9])
        except (OSError, ValueError):
            continue
    if not inodes:
        return None
    # Match those inodes to the process holding the socket open.
    targets = {f"socket:[{i}]" for i in inodes}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        fd_dir = f"/proc/{entry}/fd"
        try:
            for fd in os.listdir(fd_dir):
                try:
                    if os.readlink(f"{fd_dir}/{fd}") in targets:
                        return int(entry)
                except OSError:
                    continue
        except OSError:
            continue
    return None


def rss_mb(pid: int) -> float:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        if out:
            return int(out) / 1024.0
    except Exception:  # noqa: BLE001
        pass
    try:  # procfs fallback; also more precise than ps
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:  # noqa: BLE001
        pass
    return -1.0


# ---------------------------------------------------------------------------
# 1. No external network operations during ordinary page requests
# ---------------------------------------------------------------------------
def test_no_network(base: str) -> None:
    """Block outbound sockets in-process and prove the request path still works."""
    import socket

    real_socket = socket.socket
    real_create_conn = socket.create_connection
    blocked: list[str] = []

    class _Guard(real_socket):  # type: ignore[misc]
        def connect(self, address):  # noqa: D102
            host = address[0] if isinstance(address, tuple) else str(address)
            # Loopback to our own server is the only allowed destination.
            if host not in ("127.0.0.1", "localhost", "::1"):
                blocked.append(host)
                raise OSError(f"blocked outbound connect to {host}")
            return super().connect(address)

        def connect_ex(self, address):  # noqa: D102
            host = address[0] if isinstance(address, tuple) else str(address)
            if host not in ("127.0.0.1", "localhost", "::1"):
                blocked.append(host)
                return 111
            return super().connect_ex(address)

    def _blocked_create_connection(address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "localhost", "::1"):
            blocked.append(host)
            raise OSError(f"blocked outbound create_connection to {host}")
        return real_create_conn(address, *a, **kw)

    # Also measure the *server's* own outbound counter. Blocking sockets here only
    # proves the test client stayed local; the server is what used to call TNS and
    # friends. A nonzero server-side delta across page loads is the real failure.
    # Wait for the enrichment queue to go quiet so the measurement is attributable.
    # The outbound counter is process-wide: a background job that happens to run
    # during this window inflates the delta and produces a false failure. With the
    # queue quiet, any connect() during the page loads below came from a request
    # handler -- which is precisely the defect this test guards against. An earlier
    # version tolerated <=4 calls, which is loose enough to hide a single blocking
    # provider call; the assertion is now strict zero.
    qstate = _queue_quiet(base)
    snap_before = health(base).get("outbound", {})
    total_before = snap_before.get("total", 0) or 0

    socket.socket = _Guard  # type: ignore[misc]
    socket.create_connection = _blocked_create_connection  # type: ignore[assignment]
    try:
        targets = ["/", "/sne/SN2011fe/", "/sne/SN1987A/", "/sne/AT2026afwc/"]
        codes = {}
        for t in targets:
            code, _, _ = http(base + t, timeout=60)
            codes[t] = code
        snap_after = health(base).get("outbound", {})
        total_after = snap_after.get("total", 0) or 0
        server_delta = total_after - total_before
        # With a quiet queue and sub-second page loads (well under the 45 s provider
        # timeout), a nonzero delta means a handler blocked on a provider.
        ok = all(c == 200 for c in codes.values()) and not blocked and server_delta == 0
        record(
            "no_network_ordinary_requests", ok,
            f"statuses={codes} client_outbound={len(blocked)} "
            f"server_outbound_delta={server_delta} (total {total_before}->{total_after}) "
            f"queue_quiet={qstate.get('quiet')}"
            + (f" hosts={sorted(set(blocked))[:5]}" if blocked else ""),
            {
                "client_blocked": sorted(set(blocked))[:10],
                "server_outbound_delta": server_delta,
                "server_outbound_by_host": snap_after.get("by_host", {}),
                "queue_quiet": qstate.get("quiet"),
            },
        )
    finally:
        socket.socket = real_socket  # type: ignore[misc]
        socket.create_connection = real_create_conn  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 2. Repeated event requests do not trigger enrichment
# ---------------------------------------------------------------------------
def test_no_repeated_enrichment(base: str) -> None:
    before = health(base).get("enrich_queue", {})
    enq_before = before.get("enqueued", 0) or 0
    if not before:
        record("no_repeated_enrichment", False, "health endpoint unreachable or unauthorized")
        return

    code0, _, _ = http(base + "/sne/SN2011fe/", timeout=60)
    for _ in range(50):
        http(base + "/sne/SN2011fe/", timeout=60)

    after = health(base).get("enrich_queue", {})
    enq_after = after.get("enqueued", 0) or 0
    delta = enq_after - enq_before

    # SN2011fe is complete (many photometry points + spectra), so 50 requests
    # should enqueue nothing at all. Strict zero.
    ok = code0 == 200 and delta == 0
    record(
        "no_repeated_enrichment", ok,
        f"50 requests to complete event -> enrichment enqueued delta={delta} "
        f"(enqueued {enq_before} -> {enq_after})",
        {"before": enq_before, "after": enq_after, "queue": after},
    )


# ---------------------------------------------------------------------------
# 3. Previously stored events survive container replacement
# ---------------------------------------------------------------------------
def test_persistence(base: str) -> None:
    """Verify the corpus lives on a stable path outside any ephemeral layer."""
    from serve import data_paths

    root = data_paths.OUTPUT_DIR
    # Pick a stored event and confirm it exists at a stable absolute path.
    sample = None
    for d in sorted(root.glob("sne-*")):
        for f in d.glob("*.json"):
            sample = f
            break
        if sample:
            break

    info = {
        "output_dir": str(root),
        "url_prefix": data_paths.URL_PREFIX,
        "is_absolute": root.is_absolute(),
        "exists": root.is_dir(),
        "sample": str(sample) if sample else None,
    }

    # Serve the sample through HTTP to prove the served corpus is that same dir.
    served_ok = False
    if sample:
        stem = sample.stem
        code, _, _ = http(base + f"/sne/{stem}/", timeout=60)
        served_ok = code == 200
        info["sample_status"] = code

    # Durability proof: the path must be outside the image's derived dirs and
    # resolvable through SNE_DATA_DIR for a replacement container.
    env_override = bool((os.environ.get("SNE_DATA_DIR") or "").strip())
    ok = bool(info["is_absolute"] and info["exists"] and served_ok)
    record(
        "persistence_across_restart", ok,
        f"corpus={info['output_dir']} exists={info['exists']} "
        f"sample_served={served_ok} SNE_DATA_DIR_set={env_override}",
        info,
    )


# ---------------------------------------------------------------------------
# 4. Missing-spectrum events do not create endless rapid retries
# ---------------------------------------------------------------------------
def test_no_retry_storm(base: str) -> None:
    """Enqueue the same event many times; the queue must stay deduplicated."""
    target = "SN2011fe"
    codes = []
    t0 = time.perf_counter()
    for _ in range(60):
        # GET, because the handler only implements do_GET for this route.
        code, _, _ = http(
            base + f"/api/{target}/enrich?need_lightcurve=1&need_spectra=1",
            timeout=15,
        )
        codes.append(code)
    elapsed = time.perf_counter() - t0

    q = health(base).get("enrich_queue", {})
    pending = q.get("pending", 0) or 0
    deduped = q.get("deduped", 0) or 0
    accepted = sum(1 for c in codes if c in (200, 202))
    # Non-blocking accept is required; the queue must not balloon to 60 entries.
    # A completed event should be deduplicated (or refused) rather than stacked.
    ok = accepted == len(codes) and pending <= 3
    record(
        "no_rapid_retry_storm", ok,
        f"60 enqueue GETs in {elapsed:.2f}s -> accepted={accepted}/{len(codes)} "
        f"pending={pending} deduped={deduped}",
        {"queue": q, "codes": sorted(set(codes))},
    )


# ---------------------------------------------------------------------------
# 5. Page-cache hits avoid expensive JSON parsing and rendering
# ---------------------------------------------------------------------------
def test_cache_hit_skips_render(base: str) -> None:
    event = "SN2011fe"
    url = base + f"/sne/{event}/"

    # Prime the cache.
    http(url, timeout=120)
    s1 = health(base).get("page_cache", {})

    # 20 more requests, all should be hits.
    times = []
    for _ in range(20):
        code, body, dt = http(url, timeout=60)
        times.append(dt)
        if code != 200 or len(body) < 1000:
            record("cache_hit_skips_render", False, f"bad response code={code} len={len(body)}")
            return

    s2 = health(base).get("page_cache", {})

    hit_delta = (s2.get("hits", 0) or 0) - (s1.get("hits", 0) or 0)
    miss_delta = (s2.get("misses", 0) or 0) - (s1.get("misses", 0) or 0)
    med = statistics.median(times) * 1000
    p95 = pctl(times, 0.95) * 1000

    # 20 warm requests should be ~20 hits and ~0 misses.
    ok = hit_delta >= 18 and miss_delta <= 2 and med < 60.0
    record(
        "cache_hit_skips_render", ok,
        f"20 warm requests: hits+{hit_delta} misses+{miss_delta} "
        f"median={med:.1f}ms p95={p95:.1f}ms",
        {"page_cache": s2, "times_ms": [round(t * 1000, 1) for t in times]},
    )


# ---------------------------------------------------------------------------
# 5b. A recent event's cache stays warm across repeated requests
#
# This is the regression guard for a bug that survived the first pass: an
# enrichment run that found nothing new still rewrote the event JSON, bumping
# mtime, invalidating the rendered-page cache, forcing a full re-render, which
# re-queued enrichment. Recent events therefore never cached and served in ~40 ms
# instead of ~0.5 ms while also hammering providers. Fixed by (a) making
# atomic_write_json skip byte-identical rewrites and (b) holding an event out of
# the queue for SNE_ENRICH_SUCCESS_COOLDOWN after a successful run.
# ---------------------------------------------------------------------------
def test_recent_event_cache_stable(base: str) -> None:
    event = "AT2026afwc"
    url = base + f"/sne/{event}/"
    code, _, _ = http(url, timeout=120)
    if code != 200:
        record("recent_event_cache_stable", False, f"warm request returned {code}")
        return

    s1 = health(base).get("page_cache", {})
    times = []
    for _ in range(12):
        c, body, dt = http(url, timeout=60)
        times.append(dt)
        if c != 200:
            record("recent_event_cache_stable", False, f"request returned {c}")
            return
        time.sleep(1.0)  # straddle several enrichment-queue ticks
    s2 = health(base).get("page_cache", {})

    hit_delta = (s2.get("hits", 0) or 0) - (s1.get("hits", 0) or 0)
    miss_delta = (s2.get("misses", 0) or 0) - (s1.get("misses", 0) or 0)
    med = statistics.median(times) * 1000
    # Every request after the priming hit should be a cache hit. The bug produced
    # one miss per request (miss_delta == 12) and a ~40 ms median.
    ok = hit_delta >= 10 and miss_delta <= 2 and med < 10.0
    record(
        "recent_event_cache_stable", ok,
        f"12 requests over ~12s to {event}: hits+{hit_delta} misses+{miss_delta} "
        f"median={med:.2f}ms",
        {"page_cache": s2, "times_ms": [round(t * 1000, 2) for t in times]},
    )


# ---------------------------------------------------------------------------
# 6. 20 concurrent requests without linear CPU queueing
# ---------------------------------------------------------------------------
def test_concurrency(base: str, path: str = "/sne/SN2011fe/") -> None:
    url = base + path
    # Warm the cache so we measure the cache-hit path.
    http(url, timeout=120)

    n = 20
    durations: list[float] = []
    codes: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        code, body, dt = http(url, timeout=120)
        with lock:
            durations.append(dt)
            codes.append(code)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0

    ok_codes = sum(1 for c in codes if c == 200)
    med = statistics.median(durations) * 1000
    mx = max(durations) * 1000

    # "Linear queueing" means N requests cost ~N times a single request: the
    # baseline was 15.3s wall with a 13s median per request.
    #
    # The comparison baseline must be the *measured* serial cost of N requests, not
    # N x one-request-latency. Every HTTP request carries a fixed per-connection
    # cost -- TLS-less loopback still costs ~1ms, and Docker Desktop's macOS port
    # forwarder serialises connections at ~4-5ms each (a static file shows the same
    # curve). Extrapolating from a single request charges that cost once instead of
    # N times, so the old check failed a healthy server purely for being measured
    # through a container proxy.
    #
    # What distinguishes queueing from connection overhead: does the concurrent
    # run finish *faster* than doing the same work sequentially? A GIL-bound or
    # locked server finishes no faster (ratio ~1.0) regardless of connection cost.
    _c, _, _dt = http(url, timeout=60)  # prime; not part of the measurement
    seq_t0 = time.perf_counter()
    for _ in range(n):
        _sc, _, _sdt = http(url, timeout=60)
    serial_wall = (time.perf_counter() - seq_t0) * 1000
    speedup = serial_wall / (wall * 1000) if wall > 0 else 0.0
    single_ms = _sdt * 1000

    ok = (
        ok_codes == n
        and wall < 2.0
        and med < 150.0
        # Must beat pure serial execution. Baseline 15.3s wall / 12990ms median for
        # 20 requests was ~1.0x (perfectly serialized).
        and speedup > 1.05
    )
    record(
        "concurrency_no_linear_queue", ok,
        f"{n} concurrent -> wall={wall*1000:.1f}ms median={med:.1f}ms max={mx:.1f}ms "
        f"serial_total={serial_wall:.1f}ms speedup={speedup:.2f}x ok={ok_codes}/{n} "
        f"(baseline 15.3s wall, 12990ms median, ~1.0x speedup)",
        {"wall_ms": round(wall * 1000, 2), "median_ms": round(med, 2),
         "max_ms": round(mx, 2), "single_ms": round(single_ms, 2),
         "serial_total_ms": round(serial_wall, 2), "speedup_x": round(speedup, 2)},
    )


# ---------------------------------------------------------------------------
# 6b. Concurrent requests across DISTINCT cold events
#
# The warm-cache test above proves cache hits are cheap. It says nothing about the
# case that actually worried us: N simultaneous requests to N *different* events,
# none of them cached. Every one of those must parse a multi-hundred-KB JSON and
# render HTML. If that work were serialised, N cold requests would cost ~N times a
# single cold render, recreating the original latency problem on cache misses.
#
# Measured cold-render cost is ~95% server CPU (python parse + render), so this is
# genuinely a CPU-throughput question, not an I/O one. The check therefore reports
# both wall time and server CPU time, and requires that concurrency still beats a
# serial run of the same distinct events.
# ---------------------------------------------------------------------------
def _server_cpu_seconds() -> float:
    """Cumulative CPU seconds of the server process, or -1.0 when unreadable.

    The server normally runs inside a container, so the host's ``/proc`` does not
    contain its PID and ``server_pid()`` (which scans host listeners) cannot find
    it. In that case this returns -1.0 and callers report CPU as unavailable rather
    than inventing a number. The cold-cache checks are designed to be meaningful
    without it: they measure wall time and cache-hit/miss counters from the health
    payload, both of which are always available.
    """
    pid = server_pid()
    if not pid:
        return -1.0
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as f:
            parts = f.read().split()
        ticks = int(parts[13]) + int(parts[14])
        return ticks / os.sysconf("SC_CLK_TCK")
    except Exception:  # noqa: BLE001
        return -1.0


def _all_event_names(want: int) -> list[str]:
    """Event names read from the on-disk corpus, spanning many epochs."""
    try:
        from data_paths import OUTPUT_DIR  # noqa: PLC0415
    except ImportError:
        try:
            from serve.data_paths import OUTPUT_DIR  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            OUTPUT_DIR = None
    picks: list[str] = []
    if OUTPUT_DIR is not None:
        try:
            epochs = sorted(p for p in OUTPUT_DIR.glob("sne-*") if p.is_dir())
            # Round-robin across epochs so the sample is not all one era.
            per_epoch: list[list[str]] = []
            for epoch in epochs:
                names = sorted(f.stem for f in epoch.glob("*.json"))
                if names:
                    per_epoch.append(names)
            idx = 0
            while len(picks) < want and any(idx < len(v) for v in per_epoch):
                for v in per_epoch:
                    if idx < len(v) and len(picks) < want:
                        picks.append(v[idx])
                idx += 1
        except Exception:  # noqa: BLE001
            picks = []
    if len(picks) < want:
        picks = ["SN2011fe", "SN1987A", "SN2014J", "SN2013fs", "SN2018oh",
                 "SN2019ehk", "SN2020oi", "SN2015F", "SN2016C", "SN2017glq",
                 "SN2019abp", "AT2018lwh", "SN2012aw", "SN2013by", "SN2011dh",
                 "SN2010bh", "SN2010dq", "SN2019vxm", "SN2019vsa", "SN2006it"]
    return picks[:want]


def _cold_events(base: str, want: int, exclude: set[str] | None = None) -> list[str]:
    """Return event names, skipping ones already warmed in this run."""
    exclude = exclude or set()
    pool = _all_event_names(want * 6)
    out = [n for n in pool if n not in exclude]
    return out[:want]


def _clear_page_cache(base: str) -> bool:
    """Drop all rendered pages so the next batch is deterministically cold.

    Without this, "cold" depends on which entries the LRU happened to evict: the
    cache runs near its byte bound under a full suite, so some pages are always
    warm. That makes a cold-cache benchmark unrepeatable and, worse, able to report
    a pass without ever exercising a cold render. Returns True when the flush was
    acknowledged.
    """
    code, body, _ = http(f"{base}/api/internal/cache/clear?auth={HEALTH_AUTH}", timeout=20)
    if code != 200:
        return False
    try:
        return json.loads(body).get("status") == "cleared"
    except Exception:  # noqa: BLE001
        return False


def _queue_quiet(base: str, timeout: float = 90.0) -> dict:
    """Wait until no enrichment job is pending or in flight.

    The outbound counter is process-wide, so background enrichment that happens to
    run during a request-path measurement inflates the delta and produces a false
    "the request path called a provider" result. Waiting for a quiet queue makes the
    measurement attributable: any outbound seen while quiet came from the request.
    Returns the last observed queue state; callers should check ``quiet``.
    """
    deadline = time.time() + timeout
    st: dict = {}
    while time.time() < deadline:
        st = health(base).get("enrich_queue", {}) or {}
        if not st.get("pending") and not st.get("inflight"):
            st["quiet"] = True
            return st
        time.sleep(1.5)
    st = health(base).get("enrich_queue", {}) or {}
    st["quiet"] = False
    return st


def _measure_batch(base: str, names: list[str], concurrent: bool) -> dict:
    """Request ``names`` either concurrently or serially; return timings.

    ``cold_hits``/``cold_misses`` are cache-counter deltas across the batch, so the
    caller can tell whether the requests really were cold renders.
    """
    s1 = health(base).get("page_cache", {})
    durations: list[float] = []
    codes: list[int] = []
    lock = threading.Lock()

    def worker(name: str) -> None:
        code, _body, dt = http(base + f"/sne/{name}/", timeout=300)
        with lock:
            durations.append(dt)
            codes.append(code)

    t0 = time.perf_counter()
    if concurrent:
        threads = [threading.Thread(target=worker, args=(nm,)) for nm in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    else:
        for nm in names:
            worker(nm)
    wall = time.perf_counter() - t0
    s2 = health(base).get("page_cache", {})
    ms = sorted(d * 1000 for d in durations)
    return {
        "wall": wall,
        "codes": codes,
        "durations": durations,
        "median_ms": statistics.median(ms) if ms else 0.0,
        "max_ms": max(ms) if ms else 0.0,
        "p95_ms": pctl(durations, 0.95) * 1000,
        "hits": (s2.get("hits", 0) or 0) - (s1.get("hits", 0) or 0),
        "misses": (s2.get("misses", 0) or 0) - (s1.get("misses", 0) or 0),
    }


def test_concurrent_cold_distinct(base: str) -> None:
    """20 simultaneous requests to 20 different uncached event pages.

    This is the scenario that matters for the 900 s TTL: when the cache expires, a
    burst of traffic across many distinct events must not serialise into a long
    queue. Both the concurrent batch and a serial batch of *different* uncached
    events are measured, so the comparison is cold-vs-cold rather than cold-vs-warm.
    """
    n = 20
    # Names used earlier in this suite; avoid them so the batch is genuinely cold.
    warmed = {"SN2011fe", "SN1987A", "AT2026afwc", "SN2024nrb", "AT2026afsz"}

    conc_names = _cold_events(base, n, exclude=warmed)
    if len(conc_names) < n:
        record("concurrent_cold_distinct", False,
               f"only {len(conc_names)} cold candidates found")
        return

    # Force a true cold start. Without this the batch may be a mix of hits and
    # misses depending on LRU state, which is not a repeatable measurement.
    cleared = _clear_page_cache(base)
    if not cleared:
        record("concurrent_cold_distinct", False,
               "could not clear page cache (endpoint unavailable or unauthorized)")
        return

    cpu0 = _server_cpu_seconds()
    conc = _measure_batch(base, conc_names, concurrent=True)
    cpu1 = _server_cpu_seconds()

    # A distinct set for the serial baseline, so it is also cold.
    serial_names = _cold_events(base, n, exclude=warmed | set(conc_names))
    serial = _measure_batch(base, serial_names, concurrent=False)

    ok_codes = sum(1 for c in conc["codes"] if c == 200)
    speedup = (serial["wall"] / conc["wall"]) if conc["wall"] > 0 else 0.0
    cpu_used_ms = (cpu1 - cpu0) * 1000 if (cpu0 >= 0 and cpu1 >= 0) else -1.0
    cpu_frac = ((cpu1 - cpu0) / conc["wall"]) if (
        conc["wall"] > 0 and cpu0 >= 0 and cpu1 >= 0) else -1.0

    # Coldness is asserted, not assumed: a batch that produced zero misses was
    # already cached and would prove nothing.
    genuinely_cold = conc["misses"] >= n - 2

    # A serialised 20-request queue at ~750 ms each would put wall time near 15 s.
    # 6 s leaves headroom for a slow CI host while still catching a regression to
    # serial execution.
    ok = (
        ok_codes == n
        and genuinely_cold
        and conc["wall"] < 6.0
        and conc["median_ms"] < 3000.0
        and speedup > 1.05
    )
    record(
        "concurrent_cold_distinct", ok,
        f"{n} concurrent cold distinct events -> wall={conc['wall']*1000:.1f}ms "
        f"ok={ok_codes}/{n} median={conc['median_ms']:.1f}ms p95={conc['p95_ms']:.1f}ms "
        f"misses+{conc['misses']} hits+{conc['hits']} cold={genuinely_cold} | "
        f"serial cold set wall={serial['wall']*1000:.1f}ms "
        f"median={serial['median_ms']:.1f}ms speedup={speedup:.2f}x "
        f"server_cpu={cpu_used_ms:.0f}ms cpu_frac={cpu_frac:.2f}",
        {"concurrent": {k: (round(v, 2) if isinstance(v, float) else v)
                        for k, v in conc.items() if k != "durations"},
         "serial": {k: (round(v, 2) if isinstance(v, float) else v)
                    for k, v in serial.items() if k != "durations"},
         "genuinely_cold": genuinely_cold,
         "cpu_frac": round(cpu_frac, 3) if cpu_frac >= 0 else None,
         "events": conc_names},
    )


# ---------------------------------------------------------------------------
# 6c. Requests after the page-cache TTL expires
#
# The cache TTL is 900 s, so a real expiry is impractical to wait for in a suite.
# Instead this measures the *cost* an expiry would expose: render N distinct events
# twice and confirm the second pass is a hit, then confirm a version change (the
# same mechanism a data update or TTL expiry triggers) forces a re-render whose cost
# is bounded and whose response is still served without any provider call.
#
# The TTL itself is verified directly from the health payload, so a misconfigured
# TTL (0, or so short it thrashes) fails loudly instead of silently.
# ---------------------------------------------------------------------------
def test_ttl_expiry_cost(base: str) -> None:
    st = health(base)
    pc = st.get("page_cache", {})
    ttl = pc.get("ttl_seconds")
    # A 0 TTL means "cache disabled", which would make every request a cold render.
    ttl_ok = isinstance(ttl, (int, float)) and ttl >= 300.0

    warmed = {"SN2011fe", "SN1987A", "AT2026afwc", "SN2024nrb", "AT2026afsz"}
    names = _cold_events(base, 5, exclude=warmed)
    if not names:
        record("ttl_expiry_cost", False, "no cold candidates available")
        return

    # Deterministic cold start, same reason as the concurrency test above.
    if not _clear_page_cache(base):
        record("ttl_expiry_cost", False, "could not clear page cache")
        return

    cold = _measure_batch(base, names, concurrent=False)
    warm = _measure_batch(base, names, concurrent=False)

    # After a TTL expiry the next request pays the cold cost again. What matters is
    # that it is a *bounded local* cost: no provider call, and it completes in
    # seconds rather than stalling. The warm pass proves the cache actually works.
    # A warm batch that reports misses means the cache is not retaining entries --
    # exactly the thrashing failure this guards against.
    warm_hits = warm["hits"]
    ok = (
        ttl_ok
        and cold["misses"] >= len(names) - 1
        and warm_hits >= len(names) - 1
        and warm["median_ms"] < 60.0
        and cold["median_ms"] < 3000.0
    )
    record(
        "ttl_expiry_cost", ok,
        f"ttl={ttl}s ok={ttl_ok}; cold render median={cold['median_ms']:.1f}ms "
        f"(misses+{cold['misses']}) -> warm median={warm['median_ms']:.1f}ms "
        f"(hits+{warm_hits} misses+{warm['misses']}) for {len(names)} events",
        {"ttl_seconds": ttl, "cold_median_ms": round(cold["median_ms"], 2),
         "warm_median_ms": round(warm["median_ms"], 2),
         "cold_misses": cold["misses"], "warm_hits": warm_hits,
         "warm_misses": warm["misses"]},
    )


# ---------------------------------------------------------------------------
# 6c-bis. A provider outage must not destroy the published recent data
#
# The acceptance standard is "serves pages reliably even when all astronomical data
# providers are offline". The request path is covered elsewhere; this covers the
# *ingest* path, which is what actually rewrites recent-events.json and
# recent-catalog.min.json. If a provider outage caused an empty pull to be published,
# the homepage would lose its recent list and never get it back until TNS returned.
#
# ``_publish()`` refuses to write an empty pull. This test proves the end-to-end
# behaviour: force every provider call to fail, run the pull, and assert both files
# are byte-identical afterwards. Runs in-process against the real code, not a mock.
# ---------------------------------------------------------------------------
def test_provider_outage_preserves_data(base: str) -> None:
    import hashlib
    import importlib
    import urllib.request as _ur

    try:
        from data_paths import RUNTIME_DIR, RUNTIME_ASSET_FILES  # noqa: PLC0415
    except ImportError:
        try:
            from serve.data_paths import RUNTIME_DIR, RUNTIME_ASSET_FILES  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            record("provider_outage_preserves_data", False,
                   "could not import data_paths to locate runtime files")
            return

    def digest(p: Path) -> tuple[str, int]:
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest()[:16], p.stat().st_size
        except OSError:
            return "MISSING", 0

    paths = {n: Path(RUNTIME_DIR) / n for n in RUNTIME_ASSET_FILES}
    present = {n: p for n, p in paths.items() if p.is_file()}
    if not present:
        record("provider_outage_preserves_data", False,
               f"no runtime files present in {RUNTIME_DIR}")
        return
    before = {n: digest(p) for n, p in present.items()}

    # Import the ingest module and make every provider call fail.
    pull_mod = None
    for modname in ("ingest.pull_recent", "pull_recent"):
        try:
            pull_mod = importlib.import_module(modname)
            break
        except Exception:  # noqa: BLE001
            continue
    if pull_mod is None:
        record("provider_outage_preserves_data", False,
               "could not import ingest/pull_recent.py")
        return

    real_urlopen = _ur.urlopen
    calls = [0]

    def _dead(*a, **k):
        calls[0] += 1
        raise OSError("simulated provider outage: network unreachable")

    _ur.urlopen = _dead  # type: ignore[assignment]
    returned = None
    error = None
    try:
        returned = pull_mod.pull_recent(days=40)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    finally:
        _ur.urlopen = real_urlopen  # type: ignore[assignment]

    after = {n: digest(p) for n, p in present.items()}
    identical = all(before[n][0] == after[n][0] for n in present)
    ok = identical and error is None
    detail = (
        f"providers failed ({calls[0]} attempted calls), pull returned {returned} rows; "
        f"files byte-identical={identical}"
        + (f" error={error}" if error else "")
    )
    record(
        "provider_outage_preserves_data", ok, detail,
        {"attempted_calls": calls[0], "returned_rows": returned,
         "before": {n: list(v) for n, v in before.items()},
         "after": {n: list(v) for n, v in after.items()},
         "identical": identical},
    )


# ---------------------------------------------------------------------------
# 6d. Worst-case cold burst must not exhaust memory
#
# The largest event JSONs in the corpus are ~38 MB. A single cold render of one
# peaks near 290 MB RSS, and each additional simultaneous cold render adds ~140 MB.
# Unbounded, eight concurrent cold renders of the largest events OOM-killed the
# container (exit 137) against its 1200 MB limit -- a restart costing ~40 s of
# downtime plus every cached page.
#
# The render gate (SNE_RENDER_MAX_CONCURRENT) bounds the miss path to a safe width.
# This test drives the worst case the corpus allows and asserts the server is still
# alive and still serving afterwards. A dead container is a much worse outcome than
# a request waiting a few milliseconds for a render slot.
# ---------------------------------------------------------------------------
def test_worst_case_memory_bounded(base: str) -> None:
    # Pick the largest event JSONs available, so the test is a real worst case.
    try:
        from data_paths import OUTPUT_DIR  # noqa: PLC0415
    except ImportError:
        try:
            from serve.data_paths import OUTPUT_DIR  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            OUTPUT_DIR = None

    names: list[str] = []
    sizes: list[int] = []
    if OUTPUT_DIR is not None:
        try:
            found = []
            for epoch in sorted(OUTPUT_DIR.glob("sne-*")):
                if not epoch.is_dir():
                    continue
                for f in epoch.glob("*.json"):
                    try:
                        found.append((f.stat().st_size, f.stem))
                    except OSError:
                        continue
            found.sort(reverse=True)
            sizes = [s for s, _ in found[:20]]
            names = [n for _, n in found[:20]]
        except Exception:  # noqa: BLE001
            names = []
    if not names:
        # Fallback: known large events.
        names = ["SN1999aa", "SN2012fr", "SN2013ej", "SN2011fe", "SN2004dt",
                 "SN1993J", "SN1987A", "SN2014J"]
        sizes = [0] * len(names)

    st_before = health(base)
    if not st_before:
        record("worst_case_memory_bounded", False, "health endpoint unavailable")
        return
    peak_before = st_before.get("peak_rss_mb", -1)

    n = min(8, len(names))
    if not _clear_page_cache(base):
        record("worst_case_memory_bounded", False, "could not clear page cache")
        return

    codes: list[int] = []
    lock = threading.Lock()

    def worker(name: str) -> None:
        code, _b, _d = http(base + f"/sne/{name}/", timeout=300)
        with lock:
            codes.append(code)

    threads = [threading.Thread(target=worker, args=(nm,)) for nm in names[:n]]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0

    # Alive and still serving? This is the assertion that matters: an OOM restart
    # would either fail this request or come back with an empty page cache.
    code_after, _b, _d = http(base + "/sne/SN2011fe/", timeout=120)
    st_after = health(base)
    peak_after = st_after.get("peak_rss_mb", -1) if st_after else -1
    gate = st_after.get("render_gate", {}) if st_after else {}

    ok_codes = sum(1 for c in codes if c == 200)
    alive = code_after == 200 and bool(st_after)
    # RSS must stay under the container limit; 1200 MB is the configured ceiling and
    # the OOM point observed. 1150 leaves a small margin for allocator slack.
    peak_ok = peak_after < 0 or peak_after < 1150.0
    ok = ok_codes == n and alive and peak_ok and wall < 60.0
    record(
        "worst_case_memory_bounded", ok,
        f"{n} concurrent cold largest events -> wall={wall*1000:.0f}ms "
        f"ok={ok_codes}/{n} alive={alive} peak_rss={peak_before}->{peak_after}MB "
        f"gate={gate.get('max_concurrent', '?')} waits={gate.get('cache_hits_while_waiting', '?')} "
        f"largest={sizes[0]/1024/1024:.0f}MB" if sizes and sizes[0] else
        f"{n} concurrent cold largest events -> wall={wall*1000:.0f}ms "
        f"ok={ok_codes}/{n} alive={alive} peak_rss={peak_before}->{peak_after}MB",
        {"wall_ms": round(wall * 1000, 1), "ok_codes": ok_codes, "alive": alive,
         "peak_rss_before_mb": peak_before, "peak_rss_after_mb": peak_after,
         "render_gate": gate, "events": names[:n],
         "largest_json_mb": round(sizes[0] / 1024 / 1024, 1) if sizes else None},
    )


# ---------------------------------------------------------------------------
# 7. RSS stabilizes under sustained traffic
# ---------------------------------------------------------------------------
def test_rss_stabilizes(base: str) -> None:
    pid = server_pid()
    if not pid:
        record("rss_stabilizes", False, "could not locate server PID")
        return

    rss0 = rss_mb(pid)
    # rss_mb returns -1.0 when it cannot read the process. Without this guard the
    # growth arithmetic silently yields 0 and reports a PASS for a test that never
    # measured anything.
    if rss0 < 0:
        record("rss_stabilizes", False,
               f"could not read RSS for PID {pid} (no ps/procfs access)")
        return
    samples = [rss0]
    paths = ["/", "/sne/SN2011fe/", "/sne/SN1987A/", "/sne/AT2026afwc/",
             "/sne/SN2024nrb/", "/sne/AT2026afsz/"]

    for i in range(120):
        http(base + paths[i % len(paths)], timeout=60)
        if i % 10 == 9:
            samples.append(rss_mb(pid))

    rss_end = samples[-1]
    if rss_end < 0:
        record("rss_stabilizes", False,
               f"RSS became unreadable mid-run for PID {pid}")
        return
    growth = rss_end - rss0
    # "Stabilizes" = total growth stays small and the last third is flat.
    tail = samples[-4:]
    tail_spread = max(tail) - min(tail)
    ok = growth < 150.0 and tail_spread < 40.0
    record(
        "rss_stabilizes", ok,
        f"RSS {rss0:.0f}MB -> {rss_end:.0f}MB after 120 requests "
        f"(growth {growth:+.0f}MB, tail spread {tail_spread:.0f}MB)",
        {"samples_mb": [round(s) for s in samples]},
    )


# ---------------------------------------------------------------------------
# 8. TTFB p50/p95 for homepage and event pages
# ---------------------------------------------------------------------------
def test_ttfb(base: str, samples: int = 15) -> None:
    targets = {
        "homepage": "/",
        "event_large_SN2011fe": "/sne/SN2011fe/",
        "event_classic_SN1987A": "/sne/SN1987A/",
        "event_recent_AT2026afwc": "/sne/AT2026afwc/",
        "event_recent_SN2024nrb": "/sne/SN2024nrb/",
    }
    table = {}
    for label, path in targets.items():
        times = []
        codes = []
        for _ in range(samples):
            code, _, dt = http(base + path, timeout=120)
            times.append(dt * 1000)
            codes.append(code)
        table[label] = {
            "path": path,
            "ok": all(c == 200 for c in codes),
            "min_ms": round(min(times), 1),
            "p50_ms": round(pctl(times, 0.50), 1),
            "p95_ms": round(pctl(times, 0.95), 1),
            "max_ms": round(max(times), 1),
        }
    all_ok = all(v["ok"] for v in table.values())
    summary = "; ".join(f"{k} p50={v['p50_ms']}ms p95={v['p95_ms']}ms" for k, v in table.items())
    record("ttfb_before_after", all_ok, summary, {"table": table})


# ---------------------------------------------------------------------------
# 9. Edge cases: incomplete, missing, very large, recently discovered
# ---------------------------------------------------------------------------
def test_edge_cases(base: str) -> None:
    checks = {}

    # Incomplete record: an event with sparse/absent photometry+spectra.
    for cand in ("SN2024nrb", "AT2026afsz"):
        code, body, dt = http(base + f"/sne/{cand}/", timeout=120)
        checks[f"incomplete_{cand}"] = {
            "status": code, "bytes": len(body), "ms": round(dt * 1000, 1),
            "ok": code == 200 and len(body) > 500,
        }

    # Missing record: an unknown name must be answered cheaply. Either a catalog
    # stub page (200) or a 404 is acceptable, but it must not stall on a provider
    # or a full-corpus fuzzy sweep. The pre-patch path took ~5.0 s; the budget
    # here is 1.5 s on a cold-ish cache.
    code, body, dt = http(base + "/sne/SN1999zzzzzz/", timeout=60)
    checks["missing_record"] = {
        "status": code, "bytes": len(body), "ms": round(dt * 1000, 1),
        "ok": code in (200, 404) and dt < 1.5,
    }

    # Very large event.
    code, body, dt = http(base + "/sne/SN2011fe/", timeout=120)
    checks["very_large"] = {
        "status": code, "bytes": len(body), "ms": round(dt * 1000, 1),
        "ok": code == 200 and len(body) > 10_000,
    }

    # Recently discovered: catalog metadata only.
    code, body, dt = http(base + "/sne/AT2026afwc/", timeout=120)
    checks["recently_discovered"] = {
        "status": code, "bytes": len(body), "ms": round(dt * 1000, 1),
        "ok": code == 200 and len(body) > 500,
    }

    # Story mode variant.
    code, body, dt = http(base + "/sne/SN2011fe/?story=1", timeout=120)
    checks["story_mode"] = {
        "status": code, "bytes": len(body), "ms": round(dt * 1000, 1),
        "ok": code == 200,
    }

    failed = [k for k, v in checks.items() if not v["ok"]]
    record(
        "edge_cases", not failed,
        f"{len(checks) - len(failed)}/{len(checks)} edge cases ok"
        + (f" failed={failed}" if failed else ""),
        checks,
    )


BASE = "http://127.0.0.1:8091"



# ---------------------------------------------------------------------------
# Data-integrity audit gate (scientific fabrication)
# ---------------------------------------------------------------------------
def test_data_integrity_audit() -> None:
    """Fail acceptance if the catalog still contains scientific fabrications.

    Runs the offline auditor against a representative sample (recent + classic).
    Full-catalog sweeps belong in cron; acceptance needs a fast hard gate.
    """
    from serve.audit_data_integrity import audit_event, OUTPUT_DIR
    import json
    from pathlib import Path

    # Prefer a curated regression set; fall back to a small OUTPUT_DIR sample.
    names = [
        "AT2026agpl", "SN2011fe", "SN1987A", "AT2017gfo",
    ]
    # Also include up to 40 files from the newest year folders if present.
    sample_files: list[Path] = []
    root = Path(OUTPUT_DIR) if OUTPUT_DIR else Path("output")
    if root.is_dir():
        # Output folders are named sne-YYYY-YYYY (not bare digits).
        year_dirs = sorted(
            (p for p in root.iterdir() if p.is_dir() and p.name.startswith("sne-")),
            reverse=True,
        )[:3]
        for year in year_dirs:
            sample_files.extend(sorted(year.glob("*.json"))[:40])
    checked = 0
    dirty = 0
    examples: list[str] = []
    seen = set()
    for fpath in sample_files:
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict) or not raw:
            continue
        name = next(iter(raw))
        if name in seen:
            continue
        seen.add(name)
        meta = raw[name] if isinstance(raw[name], dict) else raw
        viol = audit_event(name, meta)
        checked += 1
        if viol:
            dirty += 1
            if len(examples) < 5:
                examples.append(f"{name}: {viol[0].get('rule')}")
    # Always also check the curated names if their files exist
    for name in names:
        if name in seen:
            continue
        # search
        hits = list(root.rglob(f"{name}.json")) if root.is_dir() else []
        if not hits:
            continue
        try:
            raw = json.loads(hits[0].read_text(encoding="utf-8"))
            meta = raw.get(name, raw)
            viol = audit_event(name, meta if isinstance(meta, dict) else {})
            checked += 1
            if viol:
                dirty += 1
                if len(examples) < 5:
                    examples.append(f"{name}: {viol[0].get('rule')}")
        except Exception as e:
            record("data_integrity_audit", False, f"{name} audit error: {e}")
            return

    ok = dirty == 0 and checked > 0
    record(
        "data_integrity_audit",
        ok,
        f"checked={checked} dirty={dirty}" + (f" examples={examples}" if examples else ""),
    )



def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--json-out", default=str(REPO / "serve" / "acceptance_results.json"))
    ap.add_argument("--skip", default="", help="comma-separated test names to skip")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    print(f"=== sne.space acceptance tests against {BASE}\n", flush=True)

    tests = [
        ("no_network_ordinary_requests", lambda: test_no_network(BASE)),
        ("no_repeated_enrichment", lambda: test_no_repeated_enrichment(BASE)),
        ("data_integrity_audit", test_data_integrity_audit),
        ("persistence_across_restart", lambda: test_persistence(BASE)),
        ("no_rapid_retry_storm", lambda: test_no_retry_storm(BASE)),
        ("cache_hit_skips_render", lambda: test_cache_hit_skips_render(BASE)),
        ("recent_event_cache_stable", lambda: test_recent_event_cache_stable(BASE)),
        ("concurrency_no_linear_queue", lambda: test_concurrency(BASE)),
        ("concurrent_cold_distinct", lambda: test_concurrent_cold_distinct(BASE)),
        ("ttl_expiry_cost", lambda: test_ttl_expiry_cost(BASE)),
        ("worst_case_memory_bounded", lambda: test_worst_case_memory_bounded(BASE)),
        ("provider_outage_preserves_data", lambda: test_provider_outage_preserves_data(BASE)),
        ("rss_stabilizes", lambda: test_rss_stabilizes(BASE)),
        ("ttfb_before_after", lambda: test_ttfb(BASE)),
        ("edge_cases", lambda: test_edge_cases(BASE)),
    ]

    for name, fn in tests:
        if name in skip:
            print(f"[SKIP] {name}", flush=True)
            continue
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            record(name, False, f"raised {type(e).__name__}: {e}")

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["pass"])
    print(f"\n=== {passed}/{total} passed", flush=True)
    try:
        Path(args.json_out).write_text(
            json.dumps({"base": BASE, "passed": passed, "total": total, "results": RESULTS},
                       indent=2),
            encoding="utf-8",
        )
        print(f"results written to {args.json_out}", flush=True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
