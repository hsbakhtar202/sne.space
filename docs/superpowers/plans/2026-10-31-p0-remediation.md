# P0 Remediation Plan — 2026-10-31

## Files

| File | Change |
| --- | --- |
| `serve/server.py` | Env-only ops auth |
| `serve/acceptance_test.py`, `serve/test_persistence.py` | Set `SNE_HEALTH_AUTH` in tests |
| `docs/audit/PRODUCTION_TRUTH_REPORT.md` | Scrub secret from commands |
| `ingest/catalog_publish.py` | Stamp `publish_revision` |
| `serve/catalog_engine.py` | Provenance merge; recent rewrite helpers |
| `ingest/pull_recent.py` | Publish recent from `event_to_catalog_item` |
| `serve/test_api_recent_merge_p0a.py` | New failing→passing regression |
| `ingest/astrocats_restore_inventory.py` | P0B upstream inventory |
| `docs/audit/P0B_RESTORE_MANIFEST.md` | Inventory results (when run) |

## Tasks

1. Security scrub + env auth (tests first for auth helper if needed).
2. P0A: write failing merge tests → fix merge + publish_revision → fix pull_recent photolink.
3. P0B: inventory script against GitHub partitions; write manifest; no prod sync.
4. Run unit tests; document staging acceptance criteria.
