# P0 Remediation Design — sne.space

**Approved:** 2026-10-31 (user decision: B+A+C; provenance merge; no max-counts).  
**Baseline:** `docs/audit/` and `docs/audit/prod_truth_evidence/` preserved.

## Problems

1. **P0A:** Production event JSON can hold photometry while `/api/transients` reports `phot: 0` because page-1 merge prefers stale `recent-catalog` stubs over CatalogStore.
2. **P0B:** Most pre-2025 indexed events serve `X-Catalog-Stub` — historical JSON absent from the volume; index counts ≠ servable arrays.
3. **Security:** Hardcoded operator password in server/tests/docs.

## P0A design

- Stamp every catalog publish with `publish_revision` (monotonic unix float from publish time / publication generation).
- API merge: when both recent and store have a name, **choose the higher `publish_revision`**. If only one has a revision, prefer it. If neither has a revision, **prefer CatalogStore** (never let unrevisioned recent stubs win).
- After enrich, rewrite recent-catalog rows via `event_to_catalog_item` (det+lim in `photolink`).
- Tests cover: stub cannot hide enriched store; legitimate correction that **lowers** counts wins when it has a newer revision.

## P0B design

- Baseline restore source: official AstroCats GitHub year partitions (pin SHAs).
- Supplemental: laptop corpus (A), Vultr backup when accessible (C).
- Manifest before sync; provenance-aware merge in staging; never overwrite richer/newer enriched production files blindly with `cp -n` alone.
- Report recovery % and gaps before production sync.

## Security

- Auth secret only from `SNE_HEALTH_AUTH` (no hardcoded default in runtime).
- Tests set the env var explicitly.
- Scrub operational docs; rotate secret on next production deploy (ops action).
