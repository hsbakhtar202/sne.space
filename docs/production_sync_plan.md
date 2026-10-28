# Production synchronization plan — recovered 2025 photometry

**Status:** design only. Do **not** deploy or overwrite production until this plan is reviewed and a dry-run report is approved.

## Goal

Move locally recovered ALeRCE photometry onto production’s durable volumes without:

- clobbering production-only newer writes,
- duplicating measurements,
- racing concurrent production ingest,
- treating unverified associations as scientific fact.

## Shared coordination prerequisites

| Concern | Requirement |
|---------|-------------|
| Discovery vs backfill priority | Both web and backfill containers mount **`sne_runtime`** (`SNE_RUNTIME_DIR=/data/sne-runtime`) so `fcntl` locks share one filesystem |
| Optional override | `SNE_INGEST_LOCK_DIR` may point at any shared POSIX mount |
| Separate hosts without shared FS | `fcntl` **cannot** coordinate — do not run historical backfill against production APIs from an isolated host; run backfill **inside** the production compose network with the runtime volume, or use a queue/lease service |
| Lock behaviour | `pull_recent` holds `recent_ingest_priority()` for the **entire** cycle; backfill **never** holds that lock during HTTP/429 waits — it only polls and yields |

Verify before sync:

```bash
python3 -c "from ingest.provider_quota import lock_coordination_ok, snapshot; print(lock_coordination_ok()); print(snapshot())"
```

`on_data_mount` should be true in containers; locally it may be false (dev assets path) which is expected.

## Sync procedure (high level)

1. **Freeze window (short):** pause production historical backfill if any; allow `pull_recent` to continue.
2. **Backup production corpus:** snapshot `sne_data` volume (or `tar` of `SNE_DATA_DIR`).
3. **Dry-run compare** (`python3 -m ingest.sync_corpus --dry-run`): for each local event JSON present on production path:
   - classify: local-only / production-only / both
   - for both: merge photometry by stable keys (`candid` else `(kind,time,band,telescope)`)
   - never delete production points
   - preserve newer production `_backfill` / spectra if local is older
   - report conflicts (same key, different magnitude)
4. **Human review** of conflict report + year-mismatched quarantine list.
5. **Apply** with atomic per-file writes into a staging directory, then rename into place (or write via `atomic_write_json` on production).
6. **Post-sync verification:** recount 0/1/2+ outburst photometry; spot-check 20 events; ensure discovery `pull_recent` still succeeds.
7. **Rollback:** restore volume snapshot if verification fails.

## Merge rules

1. **Union photometry** by `photometry_dedupe_key` (candid preferred).
2. If keys collide and magnitudes differ beyond 0.05 mag → **conflict**, keep production value, log local as `sync_conflict_rejected`.
3. Candidate/unverified points (`association_status=unverified`) sync as candidates; they remain excluded from derived claims.
4. Spectra / redshift / claimedtype: keep production if set; fill from local only when production empty.
5. Do not rewrite `recent-events.json` from the laptop corpus; let production ingest own that file.

## Concurrency with production ingest

**Event-file RMW lock:** `ingest.event_file_lock.event_file_lock` is shared by
`pull_recent`, `backfill_photometry`, `manager.enrich_event`, and `sync_corpus`
apply. Atomic `os.replace` alone does **not** prevent lost updates; every
reload→merge→write must hold this lock on the shared runtime volume.

During apply:

- Sync worker takes `recent_ingest_priority()` **only** for the brief rename/commit of a batch, **or** runs between `pull_recent` cycles by waiting until `discovery_priority_held()` is false.
- Prefer: run sync as a one-shot container on the same compose project with `sne_data` + `sne_runtime` mounted, after stopping the historical backfill supervisor.
- Use `--backup-remote` before `--apply --i-understand`. Prefer `--staging` first, then promote.

## Post-sync catalog publication (required)

After event-file merge, `sync_corpus --apply` calls `ingest.catalog_publish`:

1. Batch-convert updated events → catalog-shaped items (`photolink`, `verified_phot`)
2. Atomically merge into runtime `published-updates.min.json` (name-keyed, idempotent)
3. `CatalogStore.upsert_catalog_items` — incremental SQLite update, **no** full 110k rebuild
4. Live `/catalog` merges overlay **by name** over `catalog.min.json` (mtime-cached)

Quarantine is preserved: candidate/unverified photometry is never auto-promoted.

| Surface | Behaviour |
|---------|-----------|
| Event HTML | `mtime_ns+size` invalidation |
| Catalog listings | Overlay name-replace |
| CatalogStore search | Upserted `phot` / `meta_json` |

## Dry-run outputs

- `sync_dry_run_summary.json` — counts
- `sync_conflicts.jsonl` — per-point conflicts
- `sync_would_add.jsonl` — measurements that would be added

## What this plan does *not* do

- Does not start 2026 backfill
- Does not auto-deploy
- Does not promote unverified associations to scientific peaks
