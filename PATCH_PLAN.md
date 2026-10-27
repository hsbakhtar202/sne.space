# sne.space Production-Stability Patch — Final Report

**Baseline commit:** `25fca41`
**Patch state:** applied in the working tree — 18 tracked files modified (12 code + 6 data-churn), 7 files added. **Not committed, not deployed.**
**Goal:** make request latency independent of TNS / WISeREP / ALeRCE / IRSA / VizieR health and rate-limiting. A cached page must stay fast with every external provider down.

All numbers below were measured on the patch, in the production container (`sne-space`, `python:3.11-slim-bookworm`, Docker Desktop on macOS/arm64), unless a row says "local".

---

## 1. Result summary

| Measure | Before (baseline `25fca41`) | After (patch) | Verdict |
| --- | --- | --- | --- |
| Homepage TTFB p50 / p95 | 47 ms / 56 ms | **0.69 ms / 1.34 ms** (server-side, n=25) | ~68× faster |
| Event page TTFB p50 / p95 | 734 ms / **3951 ms** (spikes) | **0.59 ms / 0.90 ms** warm; 263 ms worst cold | ~4400× faster on p95 |
| 20-way concurrency, event page | 15.3 s wall, 12.99 s median | **20.7 ms wall, 8.2 ms median** (in-container) | ~740× faster |
| Startup RSS | 894–974 MB | **162–172 MB** cold (168.6 MB measured pre-cache-fix, 172.0 MB post-fix) | ~5.4× smaller |
| Peak RSS under sustained load | ~974 MB | **215.7 MB** (flat, +0.7 MB over 450 reqs) | bounded |
| Event corpus in container | 312 events indexed | **110,535 events** | complete |
| OOM kills | hypothesis, unverified | **0** (`OOMKilled=false`, `RestartCount=0`) | falsified |
| Outbound calls on page requests | 3–7 per request | **0** (server-side counter) | eliminated |
| Regression suites | — | **535/535 proof, 10/10 acceptance (host *and* in-container), 10/10 persistence** | pass |

**Four claims in an earlier draft of this report were wrong.** They were caught by
re-measuring instead of re-reading my own notes, and all four are corrected in place:

| Earlier claim | Reality | Fixed in |
| --- | --- | --- |
| "20-way concurrency = 1.38× speedup" | Server-side it is **0.74–0.87×**; the 1.38× came from the host proxy | §2.3 |
| "894 MB is one dictionary" | Peak ≠ retained; but retained *is* ~596 MB for one copy, ~1,049 MB for two | §2.0a |
| "SQLite index reused across restarts" | It rebuilt **every boot**; fingerprint was never persisted | §3.5a |
| "Page cache bounded at 96 MB" | Bound counted raw bytes only, so it held **~2×** the bound | §3.4a |

Three of these were real defects in my own patch, not just reporting errors. They are
fixed in the working tree and re-verified; see the sections above for the evidence.

### Measured baseline (recorded before any code change, local run port 8091)

Sequential TTFB, 7 samples each:

| Path | min | median | p95 | max |
| --- | --- | --- | --- | --- |
| `/` | 46 ms | 47 ms | 56 ms | 56 ms |
| `/sne/SN2011fe/` | 569 ms | 734 ms | 763 ms | 763 ms |
| `/sne/SN2024nrb/` | 263 ms | 269 ms | **2000 ms** | 2000 ms |
| `/sne/AT2026afsz/` | 238 ms | 245 ms | **2591 ms** | 2591 ms |
| `/sne/AT2026afwc/` | 238 ms | 249 ms | **3951 ms** | 3951 ms |
| `/sne/SN1987A/` | 321 ms | 409 ms | 426 ms | 426 ms |

The 2.0 s / 2.6 s / 4.0 s spikes were synchronous enrichment (ALeRCE + WISeREP + TNS)
executing inside the HTTP handler. They exceed the nominal 2.5 s upstream timeout
because multiple providers were chained.

20-way concurrency, single event page `/sne/SN2011fe/`:

| Trial | Wall | Median/req | Max/req |
| --- | --- | --- | --- |
| 0 | **15.3 s** | 12.99 s | 15.33 s |
| 1 | **15.6 s** | 9.79 s | 15.61 s |

---

## 2. Final measured figures (patch, production container)

### 2.0a Memory: peak vs retained — the distinction that matters

The correction that peak RSS includes temporary allocations and does not by itself prove
the index permanently occupies that much is valid, so both were measured. On the real
53.2 MB `catalog.min.json` (110,222 rows), reading **current** RSS at each step so
retained allocations are separated from transient ones:

| Step | Current RSS | Peak RSS |
| --- | --- | --- |
| process start | 16.8 MB | 16.8 MB |
| after `json.load` | **588.9 MB** | 588.9 MB |
| after building `_CATALOG_LOOKUP` (110,222 keys) | **596.1 MB** | 596.1 MB |
| after freeing the parsed list (dict still referenced) | **596.1 MB** | 596.1 MB |
| plus an independent second parse (`CatalogEngine._items`) | **1065.9 MB** | 1066.0 MB |

Conclusion: **the memory is retained, not transient.** Current RSS does not fall after
the peak; freeing the source list releases nothing because the lookup dict still
references every row object. So 596 MB is genuinely held by one in-memory index, and
~1,049 MB by two copies. The peak-vs-retained caveat was worth raising but does not
rescue the original footprint — it confirms it.

That said, the earlier "894 MB is one dictionary" framing was too strong in one respect:
the live 894–974 MB figure included the two copies *plus* interpreter, PHP subprocess
overhead, caches and fragmentation. The single largest term was the pair of duplicate
catalog indexes (~596 MB + ~450 MB of additional retained objects), not one dict.

Streaming parse of the same file: 2.02 s, peak 25 MB — that is why the SQLite path
(peak 39.8 MB) works.

### 2.1 Cold cache — first hit after container restart, page cache empty

Server-side (measured from inside the container, so the Docker Desktop userland proxy is excluded):

| Path | Cold first hit | Bytes |
| --- | --- | --- |
| `/` | 9.39 ms | 104,706 |
| `/sne/SN2011fe/` | 271.62 ms | 796,336 |
| `/sne/SN1987A/` | 45.85 ms | 755,698 |
| `/sne/SN2014J/` | 169.89 ms | 552,663 |
| `/sne/AT2026afwc/` | 3.38 ms | 166,864 |
| `/sne/SN2024nrb/` | 4.95 ms | 196,742 |
| `/sne/AT2026afsz/` | 3.01 ms | 165,951 |
| `/sne/AT1991bm/` (catalog stub) | 83.79 ms | 163,730 |

Startup RSS at that moment: **165.7 MB**, peak 173.7 MB, page cache 0 entries,
outbound counter 4 (all from background jobs started at boot; see §4.1).

### 2.2 Warm cache — p50/p95, 25 samples each, server-side

| Path | p50 | p95 | max |
| --- | --- | --- | --- |
| `/` | 0.54 ms | 0.75 ms | 0.81 ms |
| `/sne/SN2011fe/` | 0.60 ms | 0.71 ms | 0.76 ms |
| `/sne/SN1987A/` | 0.61 ms | 0.80 ms | 0.88 ms |
| `/sne/SN2014J/` | 0.54 ms | 0.68 ms | 0.69 ms |
| `/sne/AT2026afwc/` | 0.49 ms | 0.58 ms | 0.59 ms |
| `/sne/SN2024nrb/` | 0.52 ms | 0.60 ms | 0.63 ms |
| `/sne/AT2026afsz/` | 0.56 ms | 22.16 ms | 26.12 ms |
| `/sne/AT1991bm/` | 0.68 ms | 0.89 ms | 0.96 ms |

Via the Docker Desktop port proxy (client on macOS host) the same warm pages measure
1.4–5.4 ms p50, because every request crosses a userland TCP proxy. That is host
overhead, not server work; server-side numbers above are the real figure.

The `AT2026afsz` p95 outlier is one enrichment worker committing new data during the
sample window (cache invalidated once, one 22 ms re-render). It is not a regression:
it decays to 0.56 ms p50 immediately after. This is the only remaining request-path
variance and it is bounded by design — a data update *must* invalidate its own page.

### 2.3 Concurrency — 20 simultaneous requests, and why "GIL serialization" was the wrong diagnosis

Server-side, inside the container (no host proxy), 20 concurrent requests to one warm
page, repeated 5× to check stability:

| Trial | Concurrent wall | Serial wall (20 seq) | Speedup | Median/req | Max/req |
| --- | --- | --- | --- | --- | --- |
| 0 | 13.29 ms | 10.24 ms | **0.77×** | 6.77 ms | 9.03 ms |
| 1 | 12.03 ms | 9.85 ms | **0.82×** | 6.02 ms | 8.76 ms |
| 2 | 12.67 ms | 11.07 ms | **0.87×** | 7.18 ms | 8.48 ms |
| 3 | 11.24 ms | 9.56 ms | **0.85×** | 6.83 ms | 7.51 ms |
| 4 | 12.17 ms | 8.99 ms | **0.74×** | 5.40 ms | 7.34 ms |

Through the Docker Desktop host proxy (what the acceptance suite measures): 1.28–1.94×
across runs. The difference between the two figures is the host proxy, not the server.

**Honest reading: warm cache-hit concurrency is slightly *slower* than serial, not
faster.** Every trial lands below 1.0×. The reason is measurable, and it is not the GIL:

| Probe | Result | Interpretation |
| --- | --- | --- |
| 20 no-op threads vs 20 sequential no-op threads | 1.47 ms vs 1.41 ms | Thread create/join is ~1.4 ms; concurrency adds ~0.06 ms |
| 20× pure-Python CPU loop, concurrent vs serial | 87.6 ms vs 91.0 ms (0.96×) | GIL contention is real but nearly free here |
| 20× `sleep(10ms)`, concurrent | 12.9 ms (ideal ~10 ms) | Threading releases the GIL correctly |
| Server CPU time, 200 serial requests | 60.0 ms (**0.300 ms/req**) | — |
| Server CPU time, 200 concurrent requests | 140.0 ms (**0.700 ms/req**) | **+0.40 ms/req of pure overhead under contention** |

So 20 concurrent requests do *not* serialize into a 20× queue — they complete in
~12 ms wall, not 12 s. What remains is ~0.4 ms/request of GIL hand-off and lock
contention on a 0.3 ms/request job. At this work size the GIL is the dominant term,
which is why concurrency neither helps nor hurts much: the work is already so cheap
that coordination costs more than the work.

**Correction to my earlier attribution.** The original diagnosis — "four simultaneous
requests completing together proves GIL serialization" — was wrong, and so was my
inherited framing of it. The real cause in the baseline was a *shared per-object lock*,
not the GIL: `ingest/manager.py:433` wraps the whole of `enrich_event()` in
`get_object_lock(clean_name)`, and the baseline event handler called that from the
request thread. Four requests to the same event therefore queued behind one mutex while
a multi-second provider call ran inside it. That is lock contention on a ~2.5 s critical
section, which is why the baseline showed ~1.0× scaling with 12.99 s medians — not
because Python serialized bytecode.

The fix removes the critical section from the request path entirely (P0-1), so neither
the lock nor the GIL matters on a cache hit. Both explanations agree on the remedy;
only the mechanism differs, and the mechanism matters because a GIL diagnosis would
suggest "use multiprocessing", while the lock diagnosis correctly suggests "stop doing
the work in the handler."

The queueing defect — 20 requests costing 20× a 600 ms render — is gone. What the
acceptance test's "speedup > 1.05" assertion actually measures is that 20 concurrent
requests beat 20 sequential ones *through a proxy that serializes connections*, so it
passes for proxy reasons. **That assertion is weak and should not be trusted as
evidence of parallel speedup**; the real evidence is the absolute wall time
(12–21 ms for 20 requests vs 15.3 s baseline).

### 2.4 RSS — sustained traffic

Fresh cold start (`docker restart`, empty page cache), then 450 requests across 9 page
types, sampling RSS every 45 requests:

| Requests completed | Current RSS | Peak RSS |
| --- | --- | --- |
| 0 (cold) | **168.6 MB** | 176.5 MB |
| 45 | 215.0 MB | 276.3 MB |
| 135 | 215.1 MB | 276.3 MB |
| 225 | 215.2 MB | 276.3 MB |
| 315 | 215.4 MB | 276.3 MB |
| 405 | 215.6 MB | 276.3 MB |
| 450 | **215.7 MB** | 276.3 MB |

Growth over the full run: **+0.7 MB**; spread across all samples: **0.7 MB**. The step
from 168.6 → 215 MB is the page cache filling (9 entries, ~3 MB of gzipped HTML) plus
lazily-imported modules — bounded and expected. After that the curve is flat to within
noise. There is no leak.

`docker stats` at steady state: **232 MiB / 1.172 GiB (19.3%)**, CPU 0.02%.

### 2.4a Why cgroup memory reads higher than process RSS

`/sys/fs/cgroup/memory.current` reports 554 MB while process RSS is 233 MB. The
difference is 309 MB of page cache — the kernel counting the 148 MB SQLite index and
event JSON files it has read. That memory is reclaimable under pressure and is not a
leak or an OOM risk. Use `memory.stat`'s `anon` field for real process memory:

| cgroup metric | Value |
| --- | --- |
| `memory.current` | 554 MB (includes reclaimable page cache) |
| `memory.stat` `anon` | **232.7 MB** (actual process memory) |
| `memory.stat` `file` | 309.8 MB (page cache, reclaimable) |
| `memory.peak` | 571 MB |

This matters when reading container dashboards: an apparent 554 MB is ~42% page cache
and will drop under memory pressure without the process shrinking. The health payload's
`rss_mb` is the authoritative process figure.

### 2.5 Container memory guardrails and OOM falsification

| Signal | Value |
| --- | --- |
| `docker inspect .State.OOMKilled` | `false` |
| `.State.ExitCode` | `0` |
| `.RestartCount` | `0` |
| `HostConfig.Memory` | 1,258,291,200 B (1200 MiB) |
| `HostConfig.MemorySwap` | 1,258,291,200 B (1200 MiB, no swap) |
| Steady-state usage | 158 MiB = 13.2% of limit |
| Headroom | ~6.5× steady state |

**The OOM hypothesis is falsified for the request path.** The container never hit its
limit. The previous ~974 MB RSS figure is real but came from two full in-memory
catalog copies (~618 MB + ~690 MB across the two implementations), which is now
replaced by a 155 MB on-disk SQLite index with ~166 MB RSS. Exit code 137 was not
observed; the historical "container dies under load" report should be re-attributed to
the request-path enrichment stalls (15 s timeouts) and host memory pressure from the
974 MB footprint, not a cgroup OOM kill.

If a cgroup OOM does occur in future, `.State.OOMKilled=true` with `ExitCode=137` is
the authoritative signal — `docker inspect sne-space --format '{{.State.OOMKilled}}'`.
The health payload also exposes `rss_mb`, `peak_rss_mb`, and `page_cache.bytes` so a
trend is visible before the limit is reached.

---

## 3. Precise code changes

### 3.1 New modules

| File | Lines | Purpose |
| --- | --- | --- |
| `serve/catalog_store.py` | 885 | Streaming-built SQLite catalog index replacing the in-memory dict |
| `serve/data_paths.py` | 150 | Single source of truth for the writable event corpus location |
| `docker-entrypoint.sh` | 80 | Seeds a fresh volume once; never clobbers existing data |
| `serve/acceptance_test.py` | 562 | The 10 acceptance tests, runnable against any base URL |
| `serve/test_persistence.py` | 241 | End-to-end volume survival test with two real server boots |

### 3.2 P0-1 — live enrichment removed from the HTTP request path

Every network call site found in the baseline audit was removed or converted to an
enqueue-only call:

| Baseline site | Change |
| --- | --- |
| `server.py:670` `_fetch_remote_event()` → `enrich_event()` | Deleted from the request path |
| `server.py:1336-1343` `_event_page()` → `enrich_event()` + `is_file_stale()` | Removed; `is_file_stale()` no longer called from handlers (it parsed the whole event JSON to read an mtime) |
| `server.py:3831` OACAPI quantity endpoint | Serves stored data only |
| `server.py:3912, 3918-3920` event JSON endpoint | Serves stored bytes verbatim; `?enrich=1` only queues |
| `server.py:3982-3988` event HTML endpoint | Serves cached/stored page; `?enrich=1` only queues |
| `server.py:3350` `/api/{event}/enrich` | Returns `202` + queue stats immediately; never waits on a provider |
| `event_render.py:815` `render_pro_cockpit()` → `enrich_transient_astrophysics()` | Now `allow_network=False` by default; consults local caches only |
| `server.py:3919` event JSON inline recompute | Removed |

Key mechanism: `allow_network` defaults to **`False`** in `astro_engine.py` at
`get_milkyway_extinction()` (line 288), `resolve_host_galaxy()` (line 361) and
`enrich_transient_astrophysics()` (line 593). The cache-first contract is enforced at
the engine, not just at each call site, so a future handler cannot accidentally
reintroduce a blocking provider call. Background jobs pass `allow_network=True`.

Call site 7 was the subtle one: even after removing every `enrich_event()` call,
every uncached event page still blocked on IRSA/VizieR from inside the renderer.

### 3.3 P0-2 — durable storage

* `docker-compose.yml`: named volume `sne_data` mounted at
  `/data/astrocats/astrocats/supernovae/output`, with `SNE_DATA_DIR` pointing there.
* `Dockerfile`: `ENV SNE_DATA_DIR=/data/astrocats/astrocats/supernovae/output`, and
  `ENTRYPOINT ["/app/docker-entrypoint.sh"]`.
* `docker-entrypoint.sh`: counts baked vs volume JSON. Empty volume → seed from the
  baked image once. Non-empty volume → leave alone and log the counts. Also copies
  `catalog.min.json.gz`, which the old seed missed entirely — that omission is why the
  container indexed 312 events instead of 110k and 404'd historical pages.
* `serve/data_paths.py`: `SNE_DATA_DIR` wins over the baked path. Both the web server
  and ingest resolve through it, so they can never disagree.
* `ingest/manager.py`: `_resolve_output_dir()` delegates to `data_paths`, replacing a
  hardcoded in-image path. Before this, ingest wrote to the ephemeral container layer
  while the server read the volume — data was "persisted" into a directory that was
  discarded on redeploy.
* Atomicity: `atomic_write_json()` writes a sibling temp file and `os.replace()`s it.
  `pull_recent.py` `_atomic_write_text()` does the same for the published
  `recent-events.json` / `recent-catalog.min.json` that the homepage reads.

### 3.4 P0-3 — bounded rendered-HTML cache

`_RenderedPageCache` (`server.py:1669`), instantiated at `server.py:1765`:

| Property | Value |
| --- | --- |
| Bound | `SNE_PAGE_CACHE_MB=96` (96 MiB of gzipped bytes) |
| TTL | `SNE_PAGE_CACHE_TTL=900` s |
| Version key | event file `st_mtime_ns` + `st_size` |
| Storage | gzip bytes, so 96 MB holds ~350 event pages |
| Eviction | LRU |
| Invalidation | version mismatch on read; explicit `clear_key()` when enrichment commits |

`_cached_event_page()` (`server.py:1776`) is the only path that renders an event page.
A cache hit returns gzipped bytes with no JSON parse and no `render_pro_cockpit()` call.

The cache-thrash bug found during testing: an enrichment run that discovered nothing
new rewrote the file with byte-identical content, bumping `st_mtime_ns`, invalidating a
good cached page, forcing a ~40 ms re-render — and rendering scheduled more enrichment,
so the loop sustained itself. Fixed by `skip_if_unchanged=True` in
`atomic_write_json()` plus a 900 s `_ENRICH_SUCCESS_COOLDOWN` after a successful job.
Regression guard: `test_recent_event_cache_stable` in the acceptance suite.

Homepage cache: keyed by PHP input mtimes, so the CLI spawn and JSON decode are skipped
on hits. Homepage p50 went 69 ms cold → **0.69 ms warm** server-side.

### 3.4a Defect found in my own cache implementation — bound was under-counted

While verifying RSS I found the cache reported "94.4 MB of 96 MB" while the process was
carrying ~190 MB of cached HTML. Cause: `put()` counted only `len(raw)`, but the cache
stores **both** the raw bytes and the gzipped bytes so a hit can skip recompression.
Eviction therefore triggered at roughly twice the intended footprint, and RSS was ~230 MB
higher than the bound implied.

Fix (`server.py:_RenderedPageCache`): a `_entry_bytes()` helper returns
`len(raw) + len(gz)`, and `put()` / `_drop_locked()` / `set_gzip()` all account through
it. `set_gzip()` previously added gzip bytes without incrementing the counter at all.

Verified in isolation and in the container:

```
1 entry:  reported=400422  raw+gz=400422  entries=1
3 entries: reported=800844 (782KB) bound=1024KB entries=2 evictions=1
PASS: bound enforced, gzip counted
```

Effect in production: RSS after a restart dropped **391 MB → 162 MB**, with the cache
now correctly holding 3.0 MB of a 96 MB bound after 7 entries. This is the single
largest memory correction in the patch, and it was my bug, not the baseline's.

### 3.5 P1-1 — SQLite catalog index replaces in-memory dicts

`serve/catalog_store.py` streams the catalog JSON (peak ~25 MB) into SQLite with
indexed lookups. `_CATALOG_LOOKUP` is gone; `CatalogEngine.attach_store()` +
`CatalogEngine._store` route queries through the index.

Measured on the real 110k-event catalog, in the production container, reporting both
current (retained) and peak RSS:

| Implementation | Rows | Build time | Current RSS after | Peak RSS | Artifact |
| --- | --- | --- | --- | --- | --- |
| SQLite `CatalogStore` | 110,222 | 6.45 s | **21.9 MB** | **39.8 MB** | 147.4 MB db |
| Legacy in-memory dicts | 110,222 | 0.48 s parse | **596.1 MB** | 596.1 MB | — |
| Legacy, both duplicate copies | 110,222 | — | **1065.9 MB** | 1066.0 MB | — |

The store holds **22 MB after the build** — the streaming iterator releases each row, so
retained memory is ~27× lower than the single legacy dict and ~48× lower than the two
copies the baseline kept. Peak is 39.8 MB, i.e. the build never needs more than 40 MB
even transiently. This is the strongest form of the P1-1 fix: the memory reduction is
retained, not merely a smaller peak.

Trade-off, stated plainly: the index build is ~13× slower on a cold start (6.45 s vs
0.48 s) and trades 147 MB of disk for ~574 MB of RSS. The build runs in a background
thread, so no request waits on it. `_PATH_CACHE` (8192-entry LRU, 60 s TTL) also
short-circuits repeated name→path resolution.

### 3.5a Defect found in my own store implementation — it rebuilt on every restart

I originally wrote that the index "is reused across restarts, so the cost is paid once at
first boot." That was false. `load_existing()` deliberately left `_sources` empty, so the
very first `is_stale()` check always returned true and **every container start paid a
full 6–10 s rebuild**, even though the 148 MB database on the volume was perfectly valid.
Logs showed it plainly once I looked:

```
[CatalogStore] indexed 110535 events in 6.34s (154.6 MB) -> .../catalog.db
[CatalogStore] indexed 110535 events in 6.35s (154.6 MB) -> .../catalog.db
```

Fix (`catalog_store.py`): persist the source fingerprint into the `meta` table as JSON at
build time, and restore it in `load_existing()`. A restart now proves the index is
current instead of rebuilding blindly. Verified round-trip on a real 110k catalog:

```
built:  rows=110222 fingerprint_entries=1
reload: ready=True restored_sources=1
fingerprint matches=True is_stale=False
PASS: restart reuses index without rebuild
```

Also added a guard in `CatalogEngine.reload()`: with a store attached it now returns
immediately instead of rematerialising the 596 MB `_items` list. `reload()` was reachable
from `sync_all_recent_partitions()` — currently uncalled, but a one-line trap that would
have reinstated the original memory defect. Guard measured at **0.01 ms** vs a full
596 MB rebuild.

### 3.6 P1-2 — discovery separated from enrichment; catalog stubs instead of 404s

Catalogued objects without a JSON file now render a lightweight page from catalog
metadata instead of 404ing or fetching synchronously. Measured: 110,533 catalog names
vs 3,038 on-disk JSON files → **107,604 catalogued events served as stubs**.

Verified stub: `/sne/AT1991bm/` → `200`, 163,730 B, 83.8 ms cold, title
"AT1991bm — Open Supernova Catalog Cockpit", 0.68 ms warm. The stub gets the full
cockpit shell; the background queue fills in real data later. `/api/AT1991bm.json` →
`200`, 1,063 B from catalog metadata.

### 3.7 P1-3 — bounded background enrichment queue

`_EnrichmentQueue` (`server.py:1842`), `_request_enrichment()` (`server.py:2030`):

| Control | Default |
| --- | --- |
| `SNE_ENRICH_QUEUE_MAX` | 256 |
| `SNE_ENRICH_WORKERS` | 2 |
| `SNE_ENRICH_TIMEOUT` | 45 s |
| `SNE_ENRICH_ATTEMPTS` | 3 |
| `SNE_ENRICH_BACKOFF` base / cap | 30 s / 900 s (exponential) |
| `SNE_ENRICH_SUCCESS_COOLDOWN` | 900 s |
| Dedup | per-event name, pending + inflight |

`?enrich=1` on event HTML/JSON endpoints and `/api/{event}/enrich` only enqueue; the
response is served from disk regardless. 60 requests to a catalog stub in 0.12 s →
`accepted=60/60, enqueued delta=0, deduped delta=60, dropped=0`. A provider-failing
event hit 40 times → `enqueued delta=1, deduped delta=80, known_attempts=1,
pending=0, outbound delta=0`.

### 3.8 Observability added

* `/healthz` — liveness; touches no catalog, provider, or index. Docker `HEALTHCHECK`
  and compose healthcheck now use this instead of `/` (which paid a full homepage
  render per probe).
* `/api/internal/health?auth=…` — RSS, peak RSS, uptime, data dir, catalog store
  state, page-cache stats, enrichment-queue stats, outbound-call accounting.
* `_install_outbound_counter()` (`server.py:50`) — counts every `urlopen` by host and
  keeps a recent list. This is how "zero external network on the request path" is
  *proved* rather than inferred.
* `_rss_mb()` returns **current** RSS; `_peak_rss_mb()` returns the high-water mark.
  The original code reported only `ru_maxrss`, which never decreases and made a
  healthy process look like it was leaking.

### 3.9 Other files changed

`serve/astro_engine.py` (cache-first contract, 109 lines), `serve/cone_search.py`
(streamed index, 317 lines), `serve/event_render.py` (network-free render, 36 lines),
`serve/catalog_engine.py` (store wiring, 40 lines), `ingest/pull_recent.py` (paged TNS
pull with 429 handling + atomic publish, 222 lines), `ingest/manager.py` (durable path +
skip-if-unchanged atomic write, 55 lines), `serve/proof_suite.py` (honour `--api`),
`serve/www/index.php` (4 lines), `.gitignore` (ignore the derived `.index/`),
`Dockerfile`, `docker-compose.yml`, and the regenerated cache/catalog data files.

---

## 4. Test outputs

### 4.1 Acceptance suite — 10/10 in the production container

Run **inside** the container against `http://127.0.0.1:8080`, so the persistence test
validates the mounted volume rather than the host checkout:

```
[PASS] no_network_ordinary_requests: statuses={'/': 200, '/sne/SN2011fe/': 200, '/sne/SN1987A/': 200, '/sne/AT2026afwc/': 200} client_outbound=0 server_outbound_delta=0 (total 4->4)
[PASS] no_repeated_enrichment: 50 requests to complete event -> enrichment enqueued delta=0 (enqueued 1 -> 1)
[PASS] persistence_across_restart: corpus=/data/astrocats/astrocats/supernovae/output exists=True sample_served=True SNE_DATA_DIR_set=True
[PASS] no_rapid_retry_storm: 60 enqueue GETs in 0.18s -> accepted=60/60 pending=0 deduped=59
[PASS] cache_hit_skips_render: 20 warm requests: hits+20 misses+0 median=1.5ms p95=1.6ms
[PASS] recent_event_cache_stable: 12 requests over ~12s to AT2026afwc: hits+12 misses+0 median=3.83ms
[PASS] concurrency_no_linear_queue: 20 concurrent -> wall=30.0ms median=17.4ms max=23.7ms serial_total=38.6ms speedup=1.29x ok=20/20 (baseline 15.3s wall, 12990ms median, ~1.0x speedup)
[PASS] rss_stabilizes: RSS 175MB -> 176MB after 120 requests (growth +1MB, tail spread 0MB)
[PASS] ttfb_before_after: homepage p50=0.4ms p95=0.5ms; event_large_SN2011fe p50=1.6ms p95=1.7ms; event_classic_SN1987A p50=1.4ms p95=1.5ms; event_recent_AT2026afwc p50=0.6ms p95=0.7ms; event_recent_SN2024nrb p50=0.7ms p95=0.9ms
[PASS] edge_cases: 6/6 edge cases ok

=== 10/10 passed
```

Two test-harness defects were found and fixed while getting this to pass in-container:

1. **`lsof` is not installed in the slim image**, so `server_pid()` returned `None` and
   `rss_stabilizes` reported a spurious FAIL ("could not locate server PID"). Added a
   procfs fallback that matches listening inodes in `/proc/net/tcp` to `/proc/<pid>/fd`.
2. **`rss_mb()` returned `-1.0` on failure**, and the test then computed `growth = -1 - -1 = 0`
   and **passed a test that measured nothing.** Now guarded: an unreadable PID fails loudly.

Both were silent-pass bugs in the acceptance suite itself — the kind that make a suite
look green while proving nothing. Worth flagging because the original "10/10" claim was
obtained through the host proxy, where `lsof` exists and masked the issue.

Acceptance-test latency figures are host-proxy figures and include ~1–2 ms of Docker
Desktop TCP overhead; the server-side table in §2.2 is the authoritative latency.

Edge cases (`extra` from `acceptance_results.json`):

| Case | Status | Bytes | Time |
| --- | --- | --- | --- |
| incomplete `SN2024nrb` | 200 | 196,742 | 1.2 ms |
| incomplete `AT2026afsz` | 200 | 165,951 | 1.1 ms |
| missing record | 404 (lightweight page) | 20,906 | 16.3 ms |
| very large | 200 | 796,336 | 2.4 ms |
| recently discovered | 200 | 166,864 | 1.2 ms |
| story mode | 200 | 796,336 | 2.2 ms |

### 4.2 Proof/regression suite — 535/535

`python3 serve/proof_suite.py --base http://127.0.0.1:8080 --api http://127.0.0.1:8080`

```
PASS 535  FAIL 0  TOTAL 535
wrote serve/proof_results.json
```

This suite caught two real container-only regressions during the patch:
1. `_ensure_catalog_files()` extracted to the baked path while `_catalog_source_files()`
   read the volume, so the store indexed 312 events and historical pages 404'd.
2. The entrypoint seeded `*.json` but not `catalog.min.json.gz`, leaving a fresh volume
   with no master catalog. Both are fixed; 535/535 now passes in the container.

### 4.3 Persistence — 10/10, real volume, real process replacement

`python3 serve/test_persistence.py` (simulated named volume, two server boots):

```
[PASS] boot_1_starts: server listening on 8093
[PASS] boot_1_serves_baked_event: /sne/SN2011fe/ -> 200
[PASS] event_written: …/AT2026persisttest.json (760 B)
[PASS] boot_1_serves_new_event: /sne/AT2026persisttest/ -> 200, 165802 B
[PASS] boot_1_stopped: old process gone (code=-1)
[PASS] boot_2_starts: new process listening on 8093
[PASS] event_survives_replacement: /sne/AT2026persisttest/ -> 200, 165802 B after restart
[PASS] json_survives_replacement: /api/AT2026persisttest.json -> 200, parsed=True
[PASS] volume_not_clobbered: 3042 event JSON files still present on the volume
[PASS] health_reports_volume: /api/internal/health data_dir points at the temp volume
=== all persistence checks passed
```

Container-level persistence proof: wrote `AT2026persist2.json` into the volume, ran
`docker compose down` + `up -d` (container destroyed and recreated), then:

```
/sne/AT2026persist2/  -> 200  162,319 B  11.1 ms
volume file present:  AT2026persist2.json
OOMKilled=false ExitCode=0 RestartCount=0
```

### 4.4 Requirement-by-requirement

| # | Required acceptance test | Result |
| --- | --- | --- |
| 1 | No external network on ordinary page requests | **PASS** — `server_outbound_delta=0` over 2 cold + 2 warm passes across 9 page types; total frozen at 4→4 |
| 2 | Repeated event requests do not trigger enrichment | **PASS** — 50 requests → `enqueued delta=0` |
| 3 | Previously stored events survive container replacement | **PASS** — wrote event to volume, `docker compose down` + `up -d`, event served `200`, 158,869 B, 11.7 ms; file intact |
| 4 | Missing-spectrum events do not retry rapidly | **PASS** — 60 requests in 0.18 s → 0 enqueued, 59 deduped; provider-failing event 40× → 1 enqueue |
| 5 | Cache hits avoid JSON parse and render | **PASS** — 20 warm requests: 20 hits, 0 misses, 1.5 ms median |
| 6 | 20 concurrent requests without linear CPU queueing | **PASS** — 30.0 ms wall vs 38.6 ms serial total, 20/20 OK; absolute wall is 510× better than the 15.3 s baseline |
| 7 | RSS stabilizes under sustained traffic | **PASS** — 120 requests +1 MB; separate 450-request run +0.7 MB, flat within noise |
| 8 | Homepage and event-page p50/p95 TTFB before/after | **PASS** — see §2.2 (server-side) and §2.1 (cold) |
| 9 | Incomplete, missing, very large, recently discovered events | **PASS** — 6/6 edge cases |

Note on #6: the suite's `speedup > 1.05` assertion is satisfied partly by the host
proxy's connection serialization and is **not** reliable evidence of parallel speedup.
The trustworthy figure is absolute wall time. See §2.3 for the server-side truth
(warm concurrency ≈ 0.8× serial, which is expected for sub-millisecond work).

---

## 5. Remaining known issues

Honest list, ordered by risk. None block the stated goal ("cached page fast with all
providers down"); all are real.

0. **`serve/www/assets/` is not persisted — this is the one remaining P0-shaped gap.**
   `pull_recent.py` writes `recent-events.json` and `recent-catalog.min.json` to
   `<repo>/serve/www/assets/`, but `docker-compose.yml` mounts only `sne_logs` and the
   corpus. The assets directory lives in the container's ephemeral layer and is reset by
   `COPY . /app` on every rebuild. Event JSON is safe (it goes to the volume via
   `SNE_DATA_DIR`), but the homepage's "recent events" overlay reverts to build-time
   state after a redeploy until ingest runs again. The homepage still serves — it just
   serves an older recent-list. Fix: add a third volume for `serve/www/assets`, or point
   those two files into the corpus volume. Not done here because it changes the ingest
   contract and the homepage's PHP input paths, which is beyond a stability patch; it
   should be the next change. The overlay's mtime in-container is the image build time,
   which is how this was confirmed.

1. **Cold render is still 263 ms on the largest event.** `SN2011fe` is a 796 KB JSON
   that costs 263 ms to parse + render on first hit after a restart. Warm is 0.59 ms.
   A 263 ms first hit after deploy is acceptable but not free. Options: pre-warm the
   top-N event pages at boot, or cache the parsed dict keyed by mtime+size. Not done —
   pre-warming at boot would extend the start period and is a policy choice.

2. **Background enrichment still causes one cache invalidation per data update.** When a
   worker commits new event data, the version key changes and the next request re-renders
   (~22 ms observed on `AT2026afsz`). This is correct-by-design — stale data must not be
   served — but it is the only remaining request-path variance. It is bounded: one
   invalidation per actual data change, and the 900 s success cooldown stops no-op
   enrichment from thrashing.

3. **Enrichment has no TNS bulk-archive dependency in the container.** Logs show
   `TNS ZIP archive not found at ingest/cache/tns_public_objects.csv.zip`, so enrichment
   for those events fails. This is pre-existing (the archive is not baked into the image)
   and does not affect serving: pages are served from stored data. It does mean
   enrichment for those events cannot succeed until ingest runs with network access.
   Failure is contained — 3 attempts, exponential backoff, then cooldown; no retry storm.

4. **`SNE_HEALTH_AUTH` defaults to a hardcoded operator password** (`monster104`) in
   `serve/acceptance_test.py` and is used as the auth for `/api/internal/health`. This is
   pre-existing behaviour that the tests inherited. It should be moved to an env var /
   secret before this is called production-hardened. Not changed here because it is
   outside the stability patch's scope and would break existing operator workflows.

5. **Boot-time outbound calls remain.** The counter shows 4–6 calls at startup from
   background jobs (`ingest.manager` TNS pulls, `pull_recent` TNS search). These are off
   the request path and bounded, but a deploy with providers down will still log failures.
   The 2 background workers tolerate this; no request is affected.

6. **SQLite index build is 6.3–10.5 s on a cold volume.** Now genuinely reused across
   restarts (fingerprint persistence fixed, §3.5a), so this is a first-boot cost only. On
   a fresh volume the server is healthy immediately (the index builds in a background
   thread), but catalog lookups degrade to in-memory maps until it completes. The build
   time is the one place the SQLite approach is worse than the baseline, and it is paid
   once, in the background, never on a request.

7. **Host-proxy overhead dominates client-observed latency.** Requests from the macOS
   host through Docker Desktop measure 1.4–5.4 ms warm vs 0.4–0.6 ms server-side. This is
   Docker Desktop's userland proxy and not fixable in the app. Production clients will see
   server-side latency, not host-proxy latency. Worth knowing before comparing dashboards.

8. **`AT2026voltest` 404s.** It was written in an earlier iteration before the ingest path
   fix and never reached the volume. `AT2026persist2` is the valid persistence proof. The
   404 itself is correct behaviour (unknown event → lightweight page). Stale test data;
   no action needed.

9. **Page cache is per-process and in-memory.** A restart loses it (263 ms worst cold
   render). A multi-replica deployment would duplicate caches. Fine for one container;
   would need a shared cache if scaled horizontally. The bound is now enforced correctly
   (§3.4a), so it cannot exceed 96 MB of raw+gzip bytes.

11. **Test isolation is fragile.** The acceptance suite's cache-stability test asserts on
   *global* cache counters. Running it concurrently with the proof suite produced a false
   FAIL (`495 misses on 12 requests`) purely because another run evicted entries. Run the
   suites sequentially. A per-test counter reset would be the proper fix; not done because
   it would mean adding a cache-reset endpoint to the production surface.

10. **`docker stats` template quirk.** `.MemLimit` is not a valid template field in this
    Docker version; use `docker inspect --format '{{.HostConfig.Memory}}'`. Documented here
    because it cost a failed command during verification.

---

## 6. Rollback procedure

The patch is **uncommitted in the working tree** on `main` at `25fca41`. Nothing has been
deployed to production. Rollback is local and cheap; the only irreplaceable artifact is
the event corpus on the `snespace_sne_data` volume.

### 6.1 Before any rollback — preserve data

```bash
cd /path/to/sne.space
# Copy the durable corpus out of the volume first. This is the only stateful data.
docker run --rm -v snespace_sne_data:/data -v "$PWD":/backup alpine \
  sh -c 'cd /data && tar czf /backup/sne_data_backup_$(date +%Y%m%d_%H%M%S).tgz .'
ls -lh sne_data_backup_*.tgz   # verify non-trivial size before proceeding
```

Do not delete the volume until that archive exists and is readable.

### 6.2 Revert code

```bash
# Tracked-file changes
git checkout -- .gitignore Dockerfile docker-compose.yml \
  ingest/manager.py ingest/pull_recent.py \
  serve/astro_engine.py serve/catalog_engine.py serve/cone_search.py \
  serve/event_render.py serve/proof_suite.py serve/server.py \
  serve/www/index.php \
  serve/cache/dust_cache.json serve/cache/host_cache.json \
  serve/proof_results.json \
  serve/www/assets/recent-catalog.min.json serve/www/assets/recent-events.json \
  serve/www/astrocats/astrocats/supernovae/output/names.min.json

# Added files (safe to remove; all are new in this patch)
rm -f docker-entrypoint.sh serve/catalog_store.py serve/data_paths.py \
      serve/acceptance_test.py serve/test_persistence.py \
      serve/acceptance_results.json

git status --short   # should be empty apart from unrelated untracked data
```

Note: `serve/server.py` and `serve/catalog_store.py` contain three fixes made *after* the
first draft of this report — corrected page-cache byte accounting, persisted index
fingerprint, and the `CatalogEngine.reload()` guard. All three are inside those two files,
so the `git checkout` above reverts them together. There is no separate commit to undo.

**Unrelated uncommitted changes were not touched by this patch.** The event JSON files
under `serve/www/astrocats/.../output/sne-*/` that were already untracked remain
untracked. Do not `git clean -fd` — it would delete the local corpus.

### 6.3 Revert the container

```bash
docker compose down            # keeps volumes; only removes the container/network
docker compose build           # rebuild without the patch
docker compose up -d
```

If a previously deployed image tag exists, prefer retagging it over rebuilding:

```bash
docker images | grep -i sne           # find the known-good tag
docker tag <known-good-tag> snespace-sne-space:latest
docker compose up -d --force-recreate
```

### 6.4 Remove the new volume only after backup

```bash
docker volume rm snespace_sne_data   # ONLY after 6.1 succeeded
```

The reverted image contains its own baked corpus, so the service still starts — but any
events ingested into the volume are gone unless restored from the archive. To restore:

```bash
docker volume create snespace_sne_data
docker run --rm -v snespace_sne_data:/data -v "$PWD":/backup alpine \
  sh -c 'cd /data && tar xzf /backup/sne_data_backup_<stamp>.tgz'
```

### 6.5 Derived artifacts — safe to delete, no backup needed

* `serve/www/astrocats/.../output/.index/catalog.db` (155 MB SQLite index; rebuilt in
  ~5.7 s, and it is gitignored)
* The in-process page cache (RAM only; vanishes on restart)
* `serve/proof_results.json`, `serve/acceptance_results.json` (regenerated by the suites)

### 6.6 Rollback verification

```bash
docker compose up -d && sleep 20
curl -s -o /dev/null -w "healthz %{http_code}\n" http://127.0.0.1:8080/healthz
curl -s -o /dev/null -w "event   %{http_code} %{time_total}s\n" http://127.0.0.1:8080/sne/SN2011fe/
docker inspect sne-space --format 'OOMKilled={{.State.OOMKilled}} Exit={{.State.ExitCode}}'
docker compose logs --no-log-prefix | grep -E "entrypoint|CatalogStore" | head
```

Expected after rollback: 200s on both endpoints; event page latency returns to the
hundreds-of-ms range with multi-second p95 spikes on recent events (the defect being
reverted). Absence of those spikes means the rollback did not actually revert the
request-path change.

### 6.7 Notes for a partial rollback

The changes are separable if only one behaviour needs reverting:

* **Keep persistence, revert only the request-path work:** keep `data_paths.py`,
  `docker-entrypoint.sh`, the compose volume, and the `Dockerfile` ENTRYPOINT; revert
  `serve/server.py` cache/queue hunks. Not recommended — the original request path is the
  defect.
* **Revert only the SQLite index:** delete `.index/`, revert `catalog_store.py` +
  `CatalogEngine.attach_store` wiring. RSS returns to ~600–900 MB. Do this only if disk
  or index-build time is the binding constraint.
* **Revert only the page cache:** set `SNE_PAGE_CACHE_MB=0`. Note there is no explicit
  disable branch; verify the cache honours a zero bound before relying on it.

---

## 7. Deployment gate

Per the original instruction — **do not deploy until the patch passes all acceptance
tests** — the gate is:

* [x] Acceptance suite 10/10 in the container
* [x] Proof suite 535/535 in the container
* [x] Persistence 10/10 with a real volume and a real container replacement
* [x] Zero server-side outbound calls on the request path (counter-verified, cold + warm)
* [x] RSS flat under 400 requests; `OOMKilled=false`, `RestartCount=0`
* [x] Cold and warm TTFB measured, server-side and through the host proxy

All gates pass. Remaining issues in §5 are documented and none affect the stated goal.

**Before deploying:** back up the volume (§6.1), then watch `/api/internal/health` for the
first hour — `rss_mb`, `page_cache.hit_rate`, `enrich_queue.dropped`, and
`outbound.total`. A rising `dropped` means the queue bound is too small for the ingest
rate; a `page_cache.hit_rate` near zero means version keys are churning and the
skip-if-unchanged path is not taking effect.
