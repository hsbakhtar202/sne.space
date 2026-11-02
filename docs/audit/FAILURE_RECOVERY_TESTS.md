# FAILURE_RECOVERY_TESTS — 2026-11-01

Suite: `serve/test_system_failure_recovery.py` (isolated temp dirs, no production).
Result: **5/5 PASS.**

| Injected fault | Mechanism | Expected invariant | Result |
| --- | --- | --- | --- |
| SQLite upsert failure | `SNE_PUBLISH_FAIL_SQLITE=1` | state → `failed`; recoverable; not lost | PASS — `pending_names()` holds it, `recover_pending()` publishes, row `phot=2` |
| Crash between overlay and SQLite | `SNE_PUBLISH_CRASH_AFTER=overlay` | `publishing` state recoverable after crash | PASS — recovery publishes row |
| Duplicate publish | publish same file twice | idempotent; same `upserted`, row stable | PASS |
| Valid correction lowering counts | rewrite event 5→1 det, republish | store reflects lower count (counts≠version) | PASS — row becomes 1 |
| Container restart with pending work | `mark_ingested` then `recover_pending` | durable pending survives; auto-recovers | PASS |

## Not yet injected (require staging host / longer harness)

- Upstream HTTP 429 (TNS) — covered indirectly by cooldown logic, not fault-tested end-to-end.
- ALeRCE outage — `build_event_dict` exception path, not isolated.
- Queue saturation (>256) — drop counter exists; not driven to overflow in staging.
- Concurrent enrichment workers racing the same event — single-flight dedupe exists; not stressed.
- Published-overlay corruption — JSON parse fallback exists; not injected.

## Invariant demonstrated

Accepted publication work is durably registered before mutation, survives
SQLite failure and process crash, replays automatically, and preserves the
downward-correction semantics P0A requires. This covers the **publication**
stage's durability. It does **not** prove enrichment-queue durability (still
in-memory, drops on overflow/restart) — that remains an open defect.
