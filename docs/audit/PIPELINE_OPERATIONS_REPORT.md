# PIPELINE_OPERATIONS_REPORT — 2026-11-01

Window measured: production access log `2026-10-29 19:34 → 22:44 UTC` (~3.2 h),
49,717 requests (`docs/audit/prod_truth_evidence/prod_access.log`).

## Throughput / status

| Metric | Value |
| --- | ---: |
| Total requests | 49,717 |
| 200 | 41,965 |
| 404 | 7,523 (15.1%) |
| 302/301 | 225 |
| 401 | 4 |
| Requests >5 s | 25,069 (~50%) |

Worst observed render latencies were multi-second to multi-minute on large
event pages (e.g. `DES17X2blx` ~5.2M ms recorded in the log line = provider/queue
wait inside a cold render path). This is the enrichment/render contention already
documented; it is a latency symptom, not a correctness invariant.

## Enrichment demand (request-driven)

| Metric | Value |
| --- | ---: |
| Event views carrying `?enrich=1` | 7,090 |
| Distinct events requested for enrichment | 5,421 |
| `enrich=1` → 200 | 7,037 |
| `enrich=1` → 404 (no local event JSON) | **53** |

53 enrichment-triggered views 404'd: a user requested an event that production had
**no JSON for at all** — demand the in-memory queue then had to materialise.

## What this window cannot show

- Queue drop/rate-limit counters are in-process (`_ENRICH_QUEUE.stats()`), not
  logged per-request; the window pre-dates any metrics endpoint exposure.
- `sync_cron.py` is not wired into the container CMD; the only automated ingest
  loop observed in code is `_recent_tns_loop` (15 min). No cron telemetry exists.
- No durable publication-latency timestamps are logged per event.

## Gaps for sustained measurement

1. No persistent per-event instrumentation (discovery→fetch→commit→publish→visible).
2. Queue stats are lost on restart (in-memory only).
3. No dead-letter log for failed enrichment/publication.
4. Homepage stat counters derive from a different source than `/api/transients`
   (110,222 vs 111,577 observed) — no single authoritative count.
