# SNE.SPACE — Independent Data Integrity Audit — Executive Summary

**Audit mode:** investigative only (no code changes, no production mutations, no backfills).  
**Audit host:** developer workspace `/Users/haseeb/Desktop/WorkingDev/sne.space` + public `https://sne.space` GET requests.  
**Started (UTC):** see `AUDIT_EVIDENCE/AUDIT_STARTED_UTC.txt`.  
**Report pack completed (UTC):** see `AUDIT_EVIDENCE/AUDIT_COMPLETED_UTC.txt`.  
**Baseline artifacts frozen under:** `docs/audit/` (do not “fix then erase” this baseline).

**Deliverables:** `AUDIT_EXECUTIVE_SUMMARY.md` · `CATALOG_INTEGRITY.csv` · `UPSTREAM_RECONCILIATION.csv` · `PIPELINE_EXECUTION_AUDIT.md` · `SCIENTIFIC_ACCURACY_AUDIT.md` · `REMEDIATION_PLAN.md` · `AUDIT_EVIDENCE/`.

---

## Verdict

**sne.space is presently a partially functional catalog: a large inherited AstroCats/OSC archive plus a live TNS discovery interface, with incomplete and uneven retrieval/publication of underlying observations.**

It is **not** (on available evidence) a fully reliable, continuously updated scientific observation warehouse for the whole catalog. Live discovery **names** clearly update; live **photometry/spectroscopy enrichment and CatalogStore agreement** are only partially proven and often lag or never complete for new ATs.

---

## Five most serious deficiencies (proven scope)

### 1. P0 — CatalogStore / API under-reports photometry for live objects (publish lag / stub index)

- **Evidence:** `AT2026agub` local event JSON has **1 detection + 1 upper limit** matching live TNS fetch; production `/api/transients?q=AT2026agub` returns **`phot: 0`**. Same pattern for `SN2026aeiv` (`local det=1`, `api phot=0`). See `UPSTREAM_RECONCILIATION.csv`, `AUDIT_EVIDENCE/phase3_raw/`.
- **Scope:** Confirmed on mandatory fixture + mid-age modern SN in sample. Recent AT\* on `/api/recent` also show `photo_count: 0` while TNS object photometry often has ≥1 detection (sample).
- **Implication:** Homepage/API can advertise “no light curve” while event JSON (when present) or upstream TNS has observations — false incompleteness / dual-source disagreement.

### 2. P0 — Production event-JSON volume unverifiable from audit host; index ≠ files here

- **Evidence:** Workspace has **2,718** event `*.json` files; `catalog.min.json` has **110,222** rows; local SQLite `events` count **110,534**; production API `total` **≈110,703**. Phase 1 notes production volume mounts **UNVERIFIABLE** without server/volume access (`AUDIT_EVIDENCE/phase1_architecture.md`).
- **Scope:** Systemic — cannot independently prove how many of 110k API rows have real on-disk photometry arrays in production.
- **Implication:** Any claim that “the catalog stores observations for X% of events” at array level for all 110k is **not fully verifiable** from this audit seat. Aggregate `photolink` stats are available; array-level truth is only verified on the thin local file subset.

### 3. P0 — Majority of catalog rows are single-photometry (or zero) by advertised `photolink`

- **Evidence:** Stream of `catalog.min.json` (`AUDIT_EVIDENCE/phase2_catalog_min_scan.json`):
  - `phot=0`: **13,503 / 110,222 (12.3%)**
  - `phot=1`: **71,829 / 110,222 (65.2%)**
  - `phot≥2`: **24,890 / 110,222 (22.6%)**
- **Caveat (mandatory):** These counts are from **published `photolink` fields**, not a full re-parse of every event’s `photometry[]` array in production.
- **Implication:** Even taking the index at face value, multi-epoch light curves are a minority. Combined with (1), new objects often sit at advertised 0 until enrich/publish catches up.

### 4. P1 — Host / redshift largely absent from the public table index

- **Evidence:** `catalog.min.json` scan: host missing **80.5%**; redshift missing **60.4%**. Production API samples for recent events frequently `host: "—"`, `z: null` even when event pages/JSON may later show values (render-time enrichment vs published index — Phase 1).
- **Implication:** Table columns systematically under-inform; cockpit can look richer than the catalog API.

### 5. P1 — Scientific semantics: discovery/single-epoch magnitudes stored as derived “maxappmag”

- **Evidence:** Local `SN2026aeiv` and `SN2024ggi` have **`maxappmag.derived=true`** with **only 1 detection** (`AUDIT_EVIDENCE/phase6_scientific_sample.json`). Local scan flagged **86** possible peak-mislabel cases in the 2.7k file subset.
- **Implication:** “Peak mag” table/UI language can overclaim measurement support.

---

## What *does* work (with evidence)

| Claim | Evidence | Classification |
| --- | --- | --- |
| TNS discovery polling reaches public site | `/api/recent` and `/api/transients` show same-day AT\* (2026-10-29) | **VERIFIED RUNNING** |
| Historical rich events retain large photometry in index + local files | `SN2011fe` local 3371 det / API phot 3371; `SN1987A` 3332/3332 | **VERIFIED** (sample) |
| TNS photometry fetch code can retrieve real rows | Live fetch for `AT2026agub` → 1 det + 1 limit; stored locally after prior enrich | **PARTIALLY FUNCTIONAL** |
| ALeRCE fetch can return dense LCs | `SN2023ixf` ALeRCE 111 det; local 110 stored | **PARTIALLY FUNCTIONAL** |
| CatalogStore serves `/api/transients` | Prod total ~110k, query latency seconds | **VERIFIED RUNNING** |

---

## Explicit answers (required)

1. **What percentage of catalog records contain genuine persisted observations?**  
   - **By advertised `photolink` in `catalog.min.json`:** **87.7%** have `phot≥1` (96,719/110,222); **22.6%** have `phot≥2`.  
   - **Array-level proof for all 110k production event files:** **UNVERIFIED** (event volume not accessible).  
   - **Local event JSON (n=2,718):** **99.3%** have ≥1 detection array entry — **biased sample** (mostly modern stubs + selected historical files), not representative of full production disk.

2. **How much data was inherited from AstroCats versus acquired by live ingestion?**  
   - **Events by discoverdate year in `catalog.min.json`:** pre-2010 11.8%; 2010–2019 34.4%; 2020–2024 47.4%; **2025+ 6.4% (7,003)**.  
   - **Live-ingest markers** (`photometry_ingest` / ALeRCE sources) on local files: concentrated in `sne-2025-2029`; older folders generally lack those markers.  
   - **Conclusion:** Catalog **cardinality** is overwhelmingly inherited/historical aggregate; **live system** mainly adds recent AT/SN stubs and selectively enriches. Exact byte-share of photometry points inherited vs newly fetched across 110k: **UNVERIFIED** without full production event scan.

3. **What percentage of independently accessible upstream observations are stored (audited sample)?**  
   - Sample n=**22** (documented in `AUDIT_EVIDENCE/phase3_sample_method.json`; target was ≥30 — mid-age API page undersupplied distinct names; shortfall noted).  
   - Among events with **local JSON + TNS status=ok** (e.g. agub, aeiv, 2023ixf): TNS detection counts were **≤ stored** (missing_tns_dets=0).  
   - Among **recent AT\*** without local JSON: TNS often has 1 det (+limit) while **prod API phot=0** → **0% of those TNS detections reflected in CatalogStore phot field** at audit time.  
   - Where ALeRCE returned data for recent ZTF ATs (e.g. ahba/ahcd: 2 dets) but API phot=0: **upstream available, not published to index**.  
   - **Do not extrapolate sample % to 110k.**

4. **Are TNS, ALeRCE, WISeREP ingestion pipelines genuinely functional in production?**  
   - **TNS search → recent list / catalog names:** **YES (VERIFIED)**.  
   - **TNS photometry → persisted + indexed:** **PARTIAL** (code + some local successes; prod index often 0 for new objects).  
   - **ALeRCE:** **PARTIAL** (works when enrich runs; many recent empty/skipped; WISeREP explicitly `enrich_wiserep=False` on `pull_recent`).  
   - **WISeREP on the 15‑minute pull path:** **NOT effectively running** (disabled in pull). EnrichQueue path **IMPLEMENTED, NOT VERIFIED** in production (no accessible job logs / health 401).

5. **Does live ingestion retain observations it retrieves?**  
   - **When enrich writes event JSON locally:** YES for audited successes (agub TNS rows retained; 2023ixf ALeRCE retained).  
   - **Retention into production CatalogStore / public phot counts:** **NOT reliably** for new ATs (API phot=0).  
   - Crash durability of prod volume: **UNVERIFIED** (no restart test executed — forbidden to mutate prod).

6. **Does the API accurately represent underlying event files?**  
   - **When local file exists and is historical/rich:** often **YES** (2011fe, 1987A).  
   - **When local file exists and is recently enriched:** **NO** for agub/aeiv phot counts vs API.  
   - **When only prod stub exists:** API represents the **stub index**, not upstream completeness.

7. **Does the website accurately represent its scientific data?**  
   - **PARTIALLY.** Identity/discovery feed is real. Observation counts and host/z columns frequently disagree with upstream or with event JSON. Event pages can show render-time host/dust not present in the table API. UI consistency for full sample marked **NOT_CHECKED** at HTML level for all 22 (timeboxed); spot checks and prior P0 work documented separately.

8. **Which scientific statements/fields are demonstrably wrong or overclaimed (sample)?**  
   - Single-epoch **`maxappmag` with `derived: true`** and no discovery kind (`SN2026aeiv`, `SN2024ggi`).  
   - Table label “Peak Mag” fed by scalars that are discovery/listing magnitudes.  
   - Advertising photometry availability via UI when API phot=0 while TNS has detections (recent ATs).

9. **Highest-impact causes of missing/incorrect data**  
   1. Enrichment not completing or not publishing into CatalogStore for new TNS objects.  
   2. Reliance on `photolink` in inherited `catalog.min.json` without continuous array-level reconciliation for 110k files.  
   3. Host/z enrich often request-time only, not indexed.  
   4. WISeREP off on pull; spectra coverage ~6% by `spectralink`.  
   5. Dual homepage sources historically (SSR recent vs API) — mitigated in code recently; prod still shows phot=0 stubs.

10. **Reliable continuously updated scientific catalog vs partial vs historical archive + live discovery UI?**  
    **Partially functional catalog — predominantly a historical AstroCats-derived archive with a live TNS discovery front door; observation ingestion/publication is real but incomplete and not proven continuous at photometry/spectra fidelity for new events.**

---

## What this audit could not verify (access required)

| Missing | Needed |
| --- | --- |
| Production container logs (7d/30d job history) | Log volume / `docker logs` / APM |
| Production event-file volume file counts | Shell on prod or read-only mount |
| EnrichQueue success/fail rates | Internal health auth or metrics |
| Full array-level photometry audit of 110k JSON | Prod filesystem scan job (read-only) |
| Controlled crash/restart persistence test | Isolated staging env (Phase 5 partial only) |
| WISeREP production hit rate | Enablement + logs |

---

## Baseline preservation

All raw findings under `docs/audit/AUDIT_EVIDENCE/` and summary CSVs/MD in `docs/audit/` constitute the **pre-remediation baseline**. Remediation must not rewrite these files in place; add dated follow-up dirs if re-auditing after fixes.

---

## Audit completeness checklist

| Required question | Status |
| --- | --- |
| Q1 % with genuine persisted observations | Answered (index-level + local array; prod arrays UNVERIFIED) |
| Q2 AstroCats vs live ingest share | Answered (cardinality/year bins; byte-share UNVERIFIED) |
| Q3 Upstream stored % (sample) | Answered for n=22 (shortfall vs ≥30 documented) |
| Q4 TNS / ALeRCE / WISeREP functional? | Answered (YES / PARTIAL / NOT on pull) |
| Q5 Retain retrieved observations? | Answered (local YES; CatalogStore often NO for new ATs) |
| Q6 API vs event files | Answered (historical YES; recent enriched FAIL) |
| Q7 Website vs scientific data | Answered (PARTIAL) |
| Q8 Wrong scientific fields | Answered (sample + index) |
| Q9 Highest-impact causes | Answered |
| Q10 Catalog character verdict | Answered: **partially functional — historical archive + live discovery UI** |

Phase 5 crash/restart tests and full HTML UI checks remain **explicit gaps**, not silent passes.
