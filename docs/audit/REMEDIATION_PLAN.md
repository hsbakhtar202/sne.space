# Remediation Plan (post-baseline)

**Do not execute until the audit baseline under `docs/audit/` is preserved.**  
This plan ranks defects found in the independent audit. Fixes belong in a separate workstream with regression tests keyed to these acceptance criteria.

---

## P0 — CatalogStore phot counts lag / under-report after enrich

| Field | Value |
| --- | --- |
| Severity | **P0** |
| Evidence | `AT2026agub`, `SN2026aeiv`: local photometry arrays ≥1; prod API `phot: 0` (`UPSTREAM_RECONCILIATION.csv`, `phase3_raw/*`) |
| Root cause | Enrich writes event JSON (or can) without guaranteed upsert of accurate `photolink` into CatalogStore / recent-catalog overlay that `/api/transients` serves |
| Affected | Confirmed on live AT/SN fixtures; suspected for most same-day `/api/recent` rows with `photo_count: 0` while TNS has ≥1 det |
| Code paths | `ingest/pull_recent.py` (build → publish), `ingest/catalog_publish.py` (`event_to_catalog_item`, upsert), `ingest/manager.py` / photometry merge, `serve/catalog_engine.py` |
| Remedy | After every successful photometry merge, recompute counts from arrays and upsert CatalogStore + published-updates atomically; fail the job if index write fails; backfill index for recent AT\* with phot=0 |
| Acceptance | For `AT2026agub`: API `phot` equals `len(photometry detections)` in event JSON within one poll cycle; reconciliation row → PASS; no dual SSR/API flash for phot |

---

## P0 — Production observation completeness unverifiable / dual truth

| Field | Value |
| --- | --- |
| Severity | **P0** (ops/integrity) |
| Evidence | Workspace 2,718 event files vs ~110k catalog index; prod volume UNVERIFIABLE (`phase1_architecture.md`) |
| Root cause | Audit seat lacks read-only access to production event volume; index fields may diverge from arrays |
| Affected | Up to entire 110k corpus for array-level claims |
| Code paths | Deployment volumes (`docker-compose.yml`), CatalogStore build sources |
| Remedy | Provide read-only prod mount or nightly inventory job exporting `{name, phot_array_len, photolink, mtime}`; reconcile mismatches into a durable report (do not silently rewrite audit baseline) |
| Acceptance | Inventory covers ≥99% of API `total`; mismatch rate published; agub-class mismatches = 0 |

---

## P1 — Majority single-point / stub photometry in public index

| Field | Value |
| --- | --- |
| Severity | **P1** |
| Evidence | `catalog.min.json`: phot=1 **65.2%**; phot≥2 **22.6%** (`phase2_catalog_min_scan.json`) |
| Root cause | Inherited AstroCats discovery stubs + live TNS stubs without multi-survey LC ingest; ALeRCE/TNS photometry not systematically published |
| Affected | ~72k rows advertised as phot=1; ~13.5k phot=0 |
| Code paths | `ingest/tns_photometry.py`, `ingest/alerce.py`, `ingest/backfill_*`, pull_recent enrich flags |
| Remedy | Scheduled observation backfill for events with phot&lt;2 where upstream TNS/ALeRCE has data; separate “discovery_mag” from multi-epoch photometry in schema |
| Acceptance | For audited recent sample with upstream dets &gt;0: stored+API phot ≥ upstream TNS dets (or documented upstream-inaccessible); sample missing_detections → 0 for accessible cases |

---

## P1 — Host / redshift missing from catalog index (~80% / ~60%)

| Field | Value |
| --- | --- |
| Severity | **P1** |
| Evidence | `phase2_catalog_min_scan.json`; recent API probes often `host: "—"`, `z: null` |
| Root cause | Publish path historically omitted host/z; enrichment often render-time only |
| Affected | ~80% host-missing, ~60% z-missing in index |
| Code paths | `ingest/catalog_publish.py` `event_to_catalog_item`; astronomy/host enrich; pull_recent |
| Remedy | Persist host/z into event JSON on ingest; always include in catalog item; backfill from TNS object fields where present |
| Acceptance | Recent AT\* with TNS host populated show non-empty API host within one enrich cycle; host_missing rate among 2025+ declines measurably |

---

## P1 — Peak / maxappmag semantics overclaim

| Field | Value |
| --- | --- |
| Severity | **P1** |
| Evidence | `phase6_scientific_sample.json`: derived maxappmag with 1 detection; local scan 86 suspect cases in 2.7k files |
| Root cause | Scalar “max” from discovery/listing magnitude treated as peak |
| Affected | Any UI “Peak Mag” fed by `maxappmag` without `peak_established` |
| Code paths | `ingest/astronomy.py`, `serve/event_render.py`, homepage table columns, FAQ copy |
| Remedy | Enforce ≥2 dets + explicit peak flag for peak labeling; expose discovery_mag separately; strip derived peak when unsupported |
| Acceptance | Zero table/API “peak” labels when `peak_established` false; agub never shows fitted peak |

---

## P2 — WISeREP / spectra not on live pull path

| Field | Value |
| --- | --- |
| Severity | **P2** |
| Evidence | `enrich_wiserep=False` on pull_recent; spectralink≥1 only **~6%** of catalog.min.json |
| Root cause | Spectroscopy enrich disabled or not scheduled on continuous path |
| Affected | Classified events without local spectra; new spectra not continuous |
| Code paths | `ingest/pull_recent.py`, WISeREP client, EnrichQueue |
| Remedy | Enable bounded WISeREP (or TNS spectra) on pull/enrich with rate limits; backfill classified-without-spectrum cohort |
| Acceptance | Job metrics show spectra attempts/successes; sample classified SNe gain spectra when upstream available |

---

## P2 — Production scheduler history opaque

| Field | Value |
| --- | --- |
| Severity | **P2** |
| Evidence | `/api/internal/health` 401; no 7d/30d logs (`PIPELINE_EXECUTION_AUDIT.md`) |
| Root cause | No auditor-accessible metrics; photometry ops conflated with TNS name poll |
| Remedy | Export per-job counters: events processed, dets added, source errors, publish failures; retain ≥30 days |
| Acceptance | Audit can answer last-success and dets-added for TNS phot, ALeRCE, WISeREP independently |

---

## P3 — Phase 5 crash/restart and full 30-event UI checks incomplete

| Field | Value |
| --- | --- |
| Severity | **P3** (audit gap, not a product defect) |
| Evidence | Sample n=22 &lt; 30; UI consistency NOT_CHECKED; crash tests skipped |
| Remedy | Staging-only Phase 5 battery; expand mid-age sample; HTML spot-check script |
| Acceptance | n≥30 with documented buckets; UI PASS/FAIL per row; staging crash test preserves prior photometry |

---

## Suggested remediation order

1. Freeze baseline (done: `docs/audit/`).
2. Fix publish/upsert path (P0) + regression on AT2026agub.
3. Prod read-only inventory (P0 ops).
4. Observation backfill for recent phot=0 with upstream data (P1).
5. Host/z publish (P1).
6. Peak semantics (P1).
7. Spectra path + metrics (P2).

**Do not** mutate production to make a re-audit pass without a dated `docs/audit/YYYY-MM-DD-followup/` tree that still cites this baseline.
