# SYSTEM_RELIABILITY_SCORECARD — 2026-11-01

Baselines from Phase 2 (full-corpus reconcile) + Phase 3 (lifecycle traces) +
Phase 4 (access-log ops). Re-run after every deployment.

| Metric | Required | Measured | Status | Evidence |
| --- | --- | --- | --- | --- |
| JSON → CatalogStore consistency (committed, index-eligible) | 100% | 96,550/99,676 OK; 0 real missing; 3,121 stale | **FAIL** | `PRODUCTION_INTEGRITY_SNAPSHOT.full.json` |
| Missing historical event files (genuine) | measured/classified | 0 genuine missing (5 HTML-anchor artifacts) | PASS | same |
| Stale phot/spec counts | 0 | 3,121 (up to 181→7,363) | **FAIL** | same |
| Advertised vs served observations (trace set) | 100% | 15/29 complete | **FAIL** | `EVENT_LIFECYCLE_TRACES.csv` |
| Events with JSON but never published to API | 0 | 0 in trace set (agub since reconciled) | PASS* | trace set; *needs prod-volume rerun |
| Lost accepted ingestion jobs | 0 | 5/5 publication recovery tests pass | PASS (publication) | `test_system_failure_recovery` |
| Unrecoverable publication failures | 0 | 0 in injection tests | PASS (publication) | same |
| Enrichment queue durability | durable | in-memory; drops on overflow/restart | **FAIL** | `SYSTEM_DEPENDENCY_GRAPH` §7 |
| Homepage stats vs authoritative count | 0 beyond refresh window | 110,222 vs 111,577 (two sources) | **FAIL** | Phase 3 probe |
| Enrich-triggered views with no event JSON | 0 | 53 (of 7,090) in 3.2 h | **FAIL** | `PIPELINE_OPERATIONS_REPORT` |
| Old credential rejected | yes | still HTTP 200 | **FAIL** | security gate |
| Discovery-magnitude mislabeled as peak | 0 | fixed in code; unverified on live pages | NOT VERIFIED | — |

\* agub was republished and now serves `phot:1`, but this was a manual repair; the
production-volume-wide reconciler run is still outstanding.

## Verdict on the final acceptance question

**NO.**

The system can ingest, persist, and serve correct data for well-formed recent
events, and the publication stage now recovers automatically from injected
faults. But it does not yet do so **continuously and without human
intervention** for the whole catalog, because:

1. 3,121 published catalog rows disagree with their event JSON (stale counts).
2. Historical 2021 events advertise far more than their retrievable files hold
   (P0B corpus not yet promoted).
3. The enrichment queue is not durable and drops work under load/restart.
4. Homepage and API report different catalog totals (no single authoritative count).
5. Reconciliation is a manual tool, not a continuous monitor.

Each maps to a broken system invariant, not a single source line — see
`ROOT_CAUSE_AND_REMEDIATION_PLAN.md`.
