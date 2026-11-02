# P0 Remediation Status — 2026-11-01 (rev 3)

Audit baseline preserved. Staging acceptance: [`STAGING_ACCEPTANCE_REPORT.md`](STAGING_ACCEPTANCE_REPORT.md).  
**Production not remediated. P0A deploy blocked on credential rotation.**

## Done (code / staging)

### Security (code only)
- `SNE_HEALTH_AUTH` env-only.
- **FAIL:** old production credential still authenticates (SSH denied).

### P0A
- Serialized + time-space + **high-water-mark** `publish_revision` (CatalogStore/overlays authoritative).
- Tests: **15/15 PASS** (incl. `test_publish_revision_high_water`).
- **Outstanding:** ops rotation → deploy P0A-only → live agub/10-event/restart/rollback smoke.

### P0B (staging only — not promoted)
- Count class: 99,664 complete / 8 partial.
- **33 collision groups:** both casings preserved on Linux volume (66 files); all distinct content; host case-escaped export for merge.
- **2 malformed records:** flagged missing `time`; no invented timestamps.
- Merge dry-run vs local clone + collision source: +99,623 add, 66 materialized, 0 held, live untouched.

## Not done
- Production credential rotation (ops)
- Production P0A deploy + live acceptance
- P0B dry-run vs **production volume clone** (blocked on host access)
- P0B promote to production archive
- Enrichment-queue durability

## Deploy order (unchanged)
1. Rotate `SNE_HEALTH_AUTH` → old 401.
2. Deploy **P0A only** with merge-aware rollback tag.
3. Obtain production volume clone → P0B dry-run → reconcile → then promote.
4. Then enrichment-queue durability.
