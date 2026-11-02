# ROOT_CAUSE_AND_REMEDIATION_PLAN — 2026-11-01

Defects mapped to broken system invariants, ranked by severity × downstream impact.
Not a fix list for the latest symptom — the interacting failures as a whole.

## Defect 1 — Publication durability covers only the publish stage, not enrichment
**Invariant broken:** *Every accepted ingestion job completes or remains durably retryable.*
- Publication (`publication.py`) is now durable and recovery-tested (5/5).
- The enrichment queue (`_ENRICH_QUEUE`) is in-memory: drops on overflow (max 256),
  drops on cooldown, and loses all pending work on restart. `sync_cron` is not wired
  into the container; `_recent_tns_loop` only revisits the trailing 40-day window.
- Evidence: `SYSTEM_DEPENDENCY_GRAPH` §7; 53 enrich-triggered 404s in 3.2 h.
**Remediation:** persist queue state (or drive enrichment from `publication_state.json`
pending set); wire a catch-up pass for events aged out of the recent window.

## Defect 2 — Published catalog rows disagree with event JSON (stale counts)
**Invariant broken:** *Advertised == persisted == served observations at one revision.*
- 3,121 of 99,676 reconciled files have store phot/spec ≠ JSON arrays.
- Worst: `CSS130912:025702-001844` store=181 vs JSON=7,363.
- Evidence: `PRODUCTION_INTEGRITY_SNAPSHOT.full.json`.
**Remediation:** run `reconcile_catalog_store --apply` on the production volume;
then enforce count agreement as a post-publish check in the state machine.

## Defect 3 — Historical 2021 events advertised but not retrievable
**Invariant broken:** *If we claim observations, they are retrievable locally.*
- 8 traced 2021 events: index advertises 4–72 phot, production JSON ≈1, API serves 1.
- P0B staging corpus is validated (99,664 count-complete) but **not promoted**.
- Evidence: `EVENT_LIFECYCLE_TRACES.csv`; P0B staging reports.
**Remediation:** complete P0B promotion on a production-volume clone (case-sensitive,
33 collision pairs preserved), then rebuild CatalogStore; represent index-only/
non-retrievable observations explicitly until then.

## Defect 4 — No single authoritative catalog count
**Invariant broken:** *All surfaces represent the same snapshot/revision.*
- Homepage headline 110,222 vs API total 111,577 (and 110,356 elsewhere on the page).
- Evidence: Phase 3 probe; `PIPELINE_OPERATIONS_REPORT`.
**Remediation:** drive every count from CatalogStore at a published revision; expose
that revision on the homepage/API and cache-bust on publish.

## Defect 5 — Reconciliation is manual, not a continuous monitor
**Invariant broken:** *Discrepancies are detected automatically, not by users.*
- `reconcile_catalog_store` runs on demand only.
**Remediation:** schedule it (sidecar/cron) with a metrics endpoint and alert on
nonzero missing/stale; persist results per run for the scorecard.

## Defect 6 — Operations security gate open
**Invariant broken:** *Exposed credentials are rotated.*
- Old ops credential still returns HTTP 200.
**Remediation:** rotate `SNE_HEALTH_AUTH` in Easypanel env; verify old → 401; move
off query-string auth.

## Suggested order
1. Rotate credential (ops; blocks nothing else).
2. Run reconciler on production volume (Defect 2) — low risk, add-only upserts.
3. Make enrichment durable + aged-out catch-up (Defect 1) — the root cause of the
   recurring "JSON exists but not served" class.
4. P0B promotion from staging (Defect 3) — separate window, volume snapshot first.
5. Single authoritative count + continuous reconciliation monitor (Defects 4–5).

## Acceptance gate (all must hold)
- JSON→CatalogStore consistency = 100% for committed index-eligible records.
- 0 lost accepted ingestion jobs; 0 unrecoverable publication failures.
- API == stored observations at the same published revision.
- Homepage stats agree with authoritative count within the refresh window.
- Old credential → 401.
