# PRODUCTION_TRUTH_REPORT

**Mode:** read-only. No code changes, no production mutations, no baseline overwrite.  
**Public production host:** `https://sne.space` → `45.63.15.75` (The Constant Company / Vultr).  
**Evidence directory (new):** `docs/audit/prod_truth_evidence/`  
**Prior audit baseline (unchanged):** `docs/audit/AUDIT_*`, `CATALOG_INTEGRITY.csv`, `UPSTREAM_RECONCILIATION.csv`, etc.

**Not the same process as local Docker `sne-space` on `:8080`.** Local container revision `0f243e6`, API total ≈110477, agub `phot:1`. Production revision `unknown`, API total ≈110667–110715 during this work, agub API `phot:0`.

---

## Access map (what we could and could not open)

| Asset | Production path / URL | Access method | Result |
| --- | --- | --- | --- |
| Event JSON directory | `/data/astrocats/astrocats/supernovae/output` (`data_dir` in health) | SSH to `45.63.15.75` | **DENIED** (`Permission denied (publickey,password)` for root/ubuntu/debian/haseeb/deploy) |
| Named volumes (`sne_data`, `sne_runtime`, `sne_logs`) | compose contract | SSH / docker on prod | **UNVERIFIABLE** without host login |
| CatalogStore SQLite | `/data/astrocats/astrocats/supernovae/output/.index/catalog.db` | health metadata only | **Partial:** size/events via `/api/internal/health?auth=…`; file bytes not downloadable |
| `catalog.min.json` | `/astrocats/astrocats/supernovae/output/catalog.min.json` | public GET | **OK** (53 350 686 bytes, **110 565** rows) — saved as `prod_catalog.min.json` |
| Event JSON bodies | `/sne/{name}.json` | public GET/HEAD | **OK**; may be on-disk file **or** `X-Catalog-Stub: 1` synthetic catalog payload |
| Runtime overlay `published-updates.min.json` | expected under `SNE_RUNTIME_DIR=/data/sne-runtime` | public URL | **404** (not web-exported); only `catalog_store.overlay_mtime` visible |
| `recent-events.json` / `recent-catalog.min.json` | `/assets/…` | public GET | **OK but stale** vs `/api/recent` (Oct‑5 SNe vs Oct‑29 ATs) |
| Access logs | `/logs?download=1` (auth) | GET | **OK**; only covers **current container uptime** (~hours), not 7 days of ingest stdout |
| Ingest scheduler stdout (`TNS recent pull…`) | docker logs / journal | SSH | **UNAVAILABLE** |
| Local laptop `sne-space` volumes | `snespace_sne_data` etc. | `docker inspect` | Inspected for comparison only — **not production** |

**Auth used for ops endpoints:** `SNE_HEALTH_AUTH` (env). The previously hardcoded operator password has been removed from application code; **rotate that credential on production deploy**. Do not paste secrets into this baseline.

### Commands used (representative)

```bash
dig +short sne.space A
# 45.63.15.75

ssh -o BatchMode=yes root@45.63.15.75 'hostname'   # Permission denied

curl -sS "https://sne.space/api/internal/health?auth=${SNE_HEALTH_AUTH}" | jq .
curl -sSI 'https://sne.space/sne/AT2026agub.json'
curl -sS 'https://sne.space/sne/AT2026agub.json' -o agub.json
curl -sS 'https://sne.space/astrocats/astrocats/supernovae/output/catalog.min.json' -o prod_catalog.min.json
curl -sS -H "Cookie: sne_logs_auth=${SNE_HEALTH_AUTH}" 'https://sne.space/logs?download=1' -o prod_access.log
```

Inventory/reconciliation scripts wrote:  
`prod_truth_evidence/PRODUCTION_RECONCILIATION.csv`, `prod_inventory_v2.json`, `prod_inventory_v2_summary.json`.

**Invalidated:** `prod_inventory_stratified.json` — contaminated by **HTTP 502** bodies (`bytes=2871`) during a production restart. See `INVALIDATED_prod_inventory_stratified_NOTE.txt`. Use **v2**.

---

## Priority 1 — Production inventory vs 110k index

### Index / store cardinalities (measured)

| Source | Count | Evidence |
| --- | --- | --- |
| Production `catalog.min.json` rows | **110 565** | `prod_catalog.min.json` |
| CatalogStore `events` (health) | **110 322–110 373** (moved during restarts) | `prod_health*.json` |
| Public `/api/transients` `total` | **110 667–110 715** | live probes |
| Local Docker API total (not prod) | ≈110 477 | comparison only |

**Reconciliation:** API total ≳ catalog.min.json ≳ CatalogStore events. Exact equality **not** observed; upserts and overlays widen the gap. Full on-disk `find … -name '*.json' | wc -l` on the volume remains **UNVERIFIABLE** without SSH.

### Index-level photometry/spectroscopy (`catalog.min.json` fields — not arrays)

| Metric | Count | % of 110 565 |
| --- | --- | --- |
| `photolink` parse → 0 | 13 851 | 12.5% |
| `photolink` → 1 | 71 815 | 65.0% |
| `photolink` → ≥2 | 24 899 | 22.5% |
| `spectralink` → 0 | 103 928 | 94.0% |
| `spectralink` → ≥1 | 6 637 | 6.0% |

### On-disk vs stub (HTTP HEAD `X-Catalog-Stub`, HTTP 200 only) — `prod_inventory_v2`

Targets: famous anchors + stratified pre‑2025 samples + **all 2025+ names in catalog.min.json**.  
Results after discarding non-200 / exhausted retries:

| Cohort | n (HTTP 200) | Stub % | Real files | Notes |
| --- | --- | --- | --- | --- |
| pre-2010 | 205 | **98.5%** | 3 | Famous rich files only in this slice |
| 2010–2019 | 255 | **99.2%** | 2 | Nearly all index rows lack event files |
| 2020–2024 | 301 | **99.7%** | 1 | Same |
| **2025+ (all in catalog)** | **2584** | **0.0%** | **2584** | Files exist; median size **2318 B** |
| **Overall ok200** | **3385** | **23.5% stub (795)** | **2590** | **14** real files &gt;100 KB; **5** &gt;1 MB |

**Implication:** Production is **not** holding ~110k rich event JSON files. The index advertises photometry counts for historical objects whose `/sne/{name}.json` responses are often **`X-Catalog-Stub: 1`** (catalog metadata only, empty photometry arrays). A minority of well-known SNe retain multi‑MB on-disk JSON (e.g. SN2011fe 24 995 072 B).

### Array-level parse (selective GET, n=92 including anchors)

| Metric | Count |
| --- | --- |
| Parsed OK | 92 |
| `array_det == 0` | 5 |
| `array_det == 1` | 80 |
| `array_det ≥ 2` | 7 |
| `array_spec ≥ 1` | 8 |
| `photolink ≠ array_det` (non-stub) | 3 |

**Do not extrapolate the 92-row parse mix to all 110k.** It is biased toward small modern files + anchors. Combined with HEAD sizes, the durable volume appears dominated by **tiny 2025+ files** plus **sparse historical giants**, while most historical index rows are **stubs**.

---

## Priority 2 — AT2026agub end-to-end on production

### Timeline of measured production states

| When (UTC) | Prod JSON | Phot arrays | `photometry_ingest.tns` | API `phot` |
| --- | --- | --- | --- | --- |
| 2026-10-29 ~22:43 | exists, 2159 B, **not** stub | **0 det, 0 lim** | `unavailable`, error **`tns rate limited`**, `fetched_at=2026-10-29T21:31:34Z` | **0** |
| 2026-10-29 ~23:50 (post-restart) | exists, 2847 B, **not** stub | **1 det, 1 lim** | `ok`, `source=tns_html`, `fetched_at=2026-10-28T16:24:36Z` | **0** |

Independent upstream (auditor fetch): TNS **1 det + 1 lim** (`status=ok`). ALeRCE empty for `ZTF26accvezn`.

### Checklist answers

1. **Prod event JSON exists?** **YES** (on-disk; no `X-Catalog-Stub`).
2. **Last modification time?** HTTP provides **no `Last-Modified`**. Best proxy: `photometry_ingest.tns.fetched_at` (see table). Volume mtime **UNVERIFIABLE** without SSH.
3. **Detection / upper-limit counts in prod JSON?** Later state: **1 / 1**. Earlier same-day state: **0 / 0**.
4. **TNS ingest status / last fetch?** Both recorded in JSON; later state `ok` @ `2026-10-28T16:24:36Z`; earlier failure `tns rate limited` @ `2026-10-29T21:31:34Z`.
5. **Enrichment executed in production?** **YES** — ingest block present; enrich queue also active globally (`enrich_available: true`).
6. **Publish/upsert attempted & succeeded?** Overlay mtime updates in health, but **API `phot` remained 0** while JSON held 1 detection → upsert either **did not publish photolink** or **published 0**.
7. **SQLite / overlay records?** SQLite path known; row contents **not readable** remotely. Overlay file **not HTTP-exposed**. Store event count ≠ API total.
8. **Production API?** `phot: 0`, `spec: 0`, `mag: 19.4603`, host `—`.

### Confirmed first failure stage (agub)

**Do not treat “local laptop JSON vs prod API” as the diagnosis.**

Using **production JSON vs production API** only:

- When JSON had **0** detections (rate-limited fetch): first break = **`INGEST_FETCH_FAILED_BEFORE_PERSIST`** (TNS photometry not retained). API correctly showed 0.
- When JSON later had **1** detection: first break = **`PUBLISH_INDEX_MISMATCH_AFTER_JSON_OK`** (observations on disk; CatalogStore/API phot field still 0).

**Current dominant break for agub:** publish/index path after successful JSON persistence.

Evidence files: `prod_truth_evidence/raw/AT2026agub_*`, `PRODUCTION_RECONCILIATION.json`, live re-probe notes above.

---

## Priority 3 — Upstream coverage (sample ≥30)

**Sample n = 33** (documented in `prod_truth_evidence/sample_method.json`): mandatory agub, `/api/recent`, deeper API pages, mid-age anchors, 10 historical.

Full table: `prod_truth_evidence/PRODUCTION_RECONCILIATION.csv`.

### Recent cohort (n=13: mandatory + recent buckets)

| Quantity | Sum |
| --- | --- |
| Upstream TNS detections (independent) | **12** |
| Upstream TNS limits | **9** |
| Upstream ALeRCE detections (where probed) | **4** |
| Production JSON detections | **14** |
| Production JSON limits | **25** |
| Production API `phot` sum | **0** |

**Stage mix (recent):** publish mismatch **10**, ingest-fetch failure **2**, upstream empty **1**.

Interpretation: for many same-day ATs, **TNS/ALeRCE data reached production JSON**, but **CatalogStore/`/api/transients` still reports phot=0**. That is stronger production evidence for a **publish bug** than the earlier baseline’s local-vs-API comparison.

### Full sample stage counts (n=33)

| Stage | n |
| --- | --- |
| `PUBLISH_INDEX_MISMATCH_AFTER_JSON_OK` | 11 |
| `OK_END_TO_END_FOR_COUNTS` | 8 |
| `NONE_OR_UPSTREAM_EMPTY` / stub historical | 6 |
| `PROD_HAS_DATA_UPSTREAM_EMPTY_OR_INACCESSIBLE` (rich OSC; TNS empty) | 6 |
| `INGEST_FETCH_FAILED_BEFORE_PERSIST` | 2 |

Historical note: several famous SNe (`SN2002bo`, `SN2013dy`, `SN2009ip`, `SN2010jl`, `SN2006gy`) return **`X-Catalog-Stub: 1`** with empty arrays while API advertises hundreds of points from the **index**, not from arrays on disk.

---

## Priority 4 — Scheduler / ops (runtime evidence only)

### What exists

| Signal | Evidence | Interpretation |
| --- | --- | --- |
| TNS **name** polling | `/api/recent` & `/api/transients` show same-day `AT2026ah*` | Discovery ingest **running** |
| Enrich queue | health `enrich_queue` | **Running but saturated** |
| Access log | `prod_access.log` | HTTP only; **no** `TNS recent pull stored…` lines |
| Container longevity | health `uptime_seconds`; log start ≈ uptime | **Restarts observed** during audit (~3 h uptime, then ~0.02 h, then ~0.24 h) |

### Enrich queue snapshot (example after a restart)

From `prod_health_report_time.json` (uptime ≈0.24 h):

- `enqueued` 322, `completed` 37, `timed_out` 19, `dropped` **13 788**, `pending` 256 (at cap), `failed` 0  
Earlier ~3 h uptime snapshot: `dropped` **~75 000**, `completed` ~1600, `timed_out` 145.

**Spectroscopy / WISeREP job counts:** **not present** in accessible logs. Code disables WISeREP on `pull_recent`; runtime success/fail counts for spectra **UNVERIFIABLE**.

**ALeRCE job counts:** no dedicated counters; only outbound host tallies + per-event `photometry_ingest.alerce` in JSON.

**7-day scheduler history:** **UNVERIFIABLE.** Access logs do not retain 7 days across restarts; docker/journal requires SSH. Do **not** substitute `SNE_TNS_POLL_SECONDS` config for execution proof beyond “names appear today.”

---

## Confirmed failure-stage diagnosis (system-level)

Ordered by **demonstrated production impact** (this investigation):

1. **P0 — CatalogStore / API phot under-report after JSON enrich**  
   Many recent events: prod JSON has detections (`tns`/`alerce` ok) but API `phot=0` (agub current; ahba/ahch/etc.).

2. **P0 — Historical event files largely absent on volume**  
   ~99% stubs in pre‑2025 HEAD samples; API/index still show large `phot` from `catalog.min.json`. Users downloading JSON or relying on arrays get empty stubs.

3. **P1 — Enrich queue overload / drop storm**  
   Tens of thousands of drops per few hours of uptime; pending stuck at max 256.

4. **P1 — TNS photometry rate limits**  
   Documented on agub (`tns rate limited`); causes empty arrays until a later successful fetch.

5. **P1 — Dual recent feeds**  
   `/assets/recent-*.json` stale vs live API recent list.

6. **P2 — Ops opacity**  
   No auditor-accessible 7‑day ingest stdout; SSH denied; overlay file not exported.

---

## What this authorizes next (fixes still gated)

Remediation should be ordered by the above **production** evidence, not by the laptop corpus:

1. Fix **publish/upsert of `photolink` from event arrays** (acceptance: agub API `phot` equals JSON detection count within one poll).  
2. **Inventory + restore** missing historical event JSON (or stop advertising array-level photometry for stubs).  
3. **Enrich queue capacity / drop metrics** and TNS rate-limit backoff.  
4. Align `/assets/recent-*` with CatalogStore.  
5. Provide read-only SSH or exported volume inventory + docker logs for continuous ops audit.

**Do not** start fixes until this report is accepted as the production baseline addendum. Keep `docs/audit/` baseline files immutable; append only under `prod_truth_evidence/` or dated follow-ups.

---

## Explicit gaps remaining

| Gap | Required access |
| --- | --- |
| Exact `find` file count on `sne_data` | SSH or read-only volume mount |
| 7‑day `pull_recent` / ALeRCE / WISeREP success tables | `docker logs` / journal retention |
| SQLite row for agub (`photolink` column) | DB file read or authenticated SQL endpoint |
| `published-updates.min.json` contents | runtime volume read |
| Array-level parse of all 110k files | volume-local job (HTTP full scrape unsafe/incomplete) |
