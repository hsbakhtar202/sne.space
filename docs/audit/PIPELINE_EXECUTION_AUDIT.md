# Pipeline Execution Audit

Read-only. Evidence roots: `AUDIT_EVIDENCE/phase1_architecture.md`, docker excerpt, public API probes, reconciliation CSV.

---

## 1. Architecture (actual, not aspirational)

```
TNS search CSV (classified + discovery)
    → ingest/pull_recent.py::_pull_recent_body
        → recent-events.json + recent-catalog.min.json
        → publish_catalog_items → CatalogStore upsert + published-updates overlay
        → selective build_event_dict (ALeRCE on; WISeREP off; TNS spectra optional)
            → event JSON under sne-YYYY-YYYY/
            → TNS photometry merge (tns_photometry.py)
            → ALeRCE merge (alerce.py)
        → republish paths → CatalogStore again

catalog.min.json (+ recent + published-updates)
    → CatalogStore.build / upsert
    → CatalogEngine.query → GET /api/transients

Homepage SSR: PHP reads recent-catalog.min.json
Homepage JS: fetch /api/transients (must agree with store)

Event page: load event JSON → event_render (+ optional astro_engine host/dust)
```

Scheduler: `serve/server.py` starts daemon thread `_recent_tns_loop` (default **15 minutes**, `SNE_TNS_POLL_SECONDS`). EnrichQueue is separate request-driven background enrichment.

Docker: `docker-compose.yml` defines persistent data/runtime volumes (see `AUDIT_EVIDENCE/phase4_docker_compose_excerpt.txt`). **Production mount contents not inspected.**

---

## 2. Subsystem classifications (summary)

| Subsystem | Status | Basis |
| --- | --- | --- |
| TNS search → public recent/API names | VERIFIED RUNNING | Same-day AT\* on prod API |
| TNS photometry fetch/merge | PARTIALLY FUNCTIONAL | Live fetch OK; index often phot=0 |
| ALeRCE | PARTIALLY FUNCTIONAL | Works for some ZTF; many empty/skipped |
| WISeREP on pull_recent | NOT EFFECTIVELY RUNNING | `enrich_wiserep=False` |
| TNS spectra on pull | IMPLEMENTED NOT VERIFIED in prod logs | Code path exists |
| CatalogStore /api/transients | VERIFIED RUNNING | total≈110703 |
| catalog_publish upsert | PARTIALLY FUNCTIONAL | Code+local; prod lag on fixtures |
| EnrichQueue | IMPLEMENTED NOT VERIFIED | No accessible execution history |
| Host/dust astro_engine | PARTIALLY FUNCTIONAL | Render-time; weak table publish |
| Historical AstroCats corpus serve | VERIFIED RUNNING (index) | catalog.min.json + API |
| Prod event-file volume | UNVERIFIABLE | Not on audit host |

Detail with path:line citations: `AUDIT_EVIDENCE/phase1_architecture.md`.

---

## 3. Production operations history (7d / 30d)

**UNVERIFIABLE.** No production container logs, metrics scrapes, or scheduler history were available from the audit host. `/api/internal/health` returned **401** (Phase 1).

**What can be inferred without logs (weak):**

- Discovery names dated **2026-10-29** appear on `/api/recent` and top of `/api/transients` → some form of TNS pull has succeeded **recently**.
- That does **not** prove photometry enrichment cadence equals 15 minutes.

---

## 4. End-to-end observations (read-only / non-mutating)

| Scenario | Result | Evidence |
| --- | --- | --- |
| New TNS AT, no/weak ALeRCE | Names on API with **phot=0**; TNS HTML often has 1 det | phase3 rows for AT2026ah\* |
| TNS det + non-detection | agub: upstream 1/1; local stored 1/1; **API phot=0** | phase3 + phase6 |
| TNS + ALeRCE overlap | 2023ixf: ALeRCE 111, local 110, API 110 | phase3 |
| Dense ALeRCE LC | Same | phase3 |
| Historical OSC event | 2011fe/1987A rich local+API match | phase3 |
| WISeREP spectra path on pull | Disabled | pull_recent source |
| TNS timeout/error handling | Code has 429 backoff; **not fault-injected** this audit | phase1 |
| Duplicate discovery | Not exercised (would mutate) | skipped |
| Crash mid publish | Not exercised | skipped |
| Container restart persistence | Not exercised on prod | skipped |
| SSR vs API | Recent names align on prod API probes; phot counts still stubby | phase4 probes |
| Failed enrich then retry | Not exercised | skipped |

Phase 5 “controlled isolated environment with crash tests” was **not fully executed** to comply with no-mutation / no-staging-provision constraints. Treat Phase 5 as **PARTIAL**.

---

## 5. Publishing lag (critical operational finding)

Measured chain for `AT2026agub`:

1. Upstream TNS: status=ok, 1 det, 1 limit (`phase3_raw/AT2026agub_tns_phot.json`).
2. Local event JSON: 1 det, 1 limit, `photometry_ingest.tns.status=ok`.
3. Production API: **`phot: 0`**.

Therefore: **retrieve+persist (somewhere) ≠ publish to CatalogStore that drives the public table/API.**

---

## 6. Freshness summary

| Surface | Freshness signal | Observation |
| --- | --- | --- |
| `/api/recent` | Discovery dates | Current (same UTC day as audit) |
| `/api/transients` sort discoverdate | Top names | Current AT\* |
| `/api/transients` phot field | Observation counts | Often 0 for those same AT\* |
| Event JSON on audit host | File mtimes / ingest stamps | Incomplete corpus |
| Event pages | HTML | Spotty timeouts noted in Phase 1 for some names |

---

## 7. Conclusion for operations

The **only continuously verified production loop** is TNS **name/metadata** publication into the catalog index. Observation pipelines exist and sometimes succeed, but **production evidence does not show reliable continuous photometry/spectroscopy publication** at the same cadence.
