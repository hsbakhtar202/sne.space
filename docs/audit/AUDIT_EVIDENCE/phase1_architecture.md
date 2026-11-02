# Phase 1 — Architecture & Data Pipeline Map

**Audit host:** `/Users/haseeb/Desktop/WorkingDev/sne.space`  
**UTC started:** see `AUDIT_STARTED_UTC.txt`  
**Scope:** read-only code + local filesystem + public `https://sne.space` HTTP (GET only).  
**Constraint:** This host holds ~**2721** event `*.json` files under the corpus output tree, **not** the full ~110k production event-file volume. Production catalog size is verified via public API (`total: 110701` on 2026-10-29); production **event JSON volume on disk** remains **UNVERIFIED** from this host.

Classification legend (used only with repo + public API evidence):

| Label | Meaning |
|-------|---------|
| **VERIFIED RUNNING** | Code path exists and public/local evidence shows live operation |
| **IMPLEMENTED NOT VERIFIED** | Code path exists; no direct runtime proof from this audit |
| **PARTIALLY FUNCTIONAL** | Works for some cases / paths; gaps or failures observed |
| **BROKEN** | Evidence of non-function against intended behavior |
| **NOT IMPLEMENTED** | No code path found |
| **UNVERIFIABLE** | Cannot determine from available evidence |

---

## 0. Corpus layout (AstroCats historical + runtime)

### Paths

| Role | Path / resolver | Lines |
|------|-----------------|-------|
| Epoch dirs | `sne-pre-1990` … `sne-2025-2029` | `serve/data_paths.py:36-45` |
| Output root resolution | `SNE_DATA_DIR` → baked WWW → `/data/...` | `serve/data_paths.py:69-97` |
| Ingest output | `SUPERNOVAE_OUTPUT` via `data_paths.OUTPUT_DIR` | `ingest/manager.py:36-61` |
| Year → folder | `get_target_repo_folder` | `ingest/manager.py:193-210` |
| Primary catalog array | `…/output/catalog.min.json` (+ `.gz`) | `serve/server.py:1579-1584` |
| Runtime recent list | `recent-events.json` via `runtime_write_path` | `ingest/pull_recent.py:27-38`, `serve/data_paths.py:127-202` |
| Runtime recent catalog | `recent-catalog.min.json` | `ingest/pull_recent.py:246-249` |
| Publish overlay | `published-updates.min.json` | `ingest/catalog_publish.py:38-52` |
| SQLite index | `{OUTPUT}/.index/catalog.db` | `serve/server.py:1565`, `ingest/catalog_publish.py:224-226` |

### Local host snapshot (2026-10-29)

- Event JSON files under output: **~2721** (`find … -name '*.json' | wc -l`).
- Epoch content skewed: `sne-2025-2029` ≈ **2694** files; older epochs sparse.
- `catalog.min.json` present (**53 212 351** bytes) — bulk listing, not full event bodies.
- Local `catalog.db` meta: `schema_version=4`, `event_count=110534`.
- Local bake of `recent-events.json` stale relative to production (one card `AT2026ahaw`); production `/api/recent` shows eight **2026-10-29** discoveries.

**Classification — historical corpus paths:** **PARTIALLY FUNCTIONAL** on this host (catalog aggregates present; event-file corpus incomplete). Production catalog **serving** is **VERIFIED RUNNING** via API `total=110701`. Full production event-file volume: **UNVERIFIABLE** from this host.

---

## 1. CatalogStore build from corpus sources

**Module:** `serve/catalog_store.py` (`CatalogStore`, schema v4).

### Build inputs (server)

```1570:1593:serve/server.py
def _catalog_source_files() -> list[Path]:
    ...
    primary = DATA_OUT / "catalog.min.json"
    ...
    recent = _runtime_asset("recent-catalog.min.json")
    ...
    published = _runtime_asset("published-updates.min.json")
```

### Merge policy inside `build()`

```492:528:serve/catalog_store.py
#   primary catalog   → seed
#   recent-catalog    → insert/update names absent from primary
#   published-updates → always replace (enriched event JSON wins)
```

Streaming decode: `_iter_json_array` (`serve/catalog_store.py:318-359`).  
Row shape: `_row_from_catalog_item` (`:272-315`).  
Incremental path: `upsert_catalog_items` (`:928-1027`) — used by publish without full rebuild.

Warmup at boot: `_warm_catalog_store` → `_get_catalog_store` (`serve/server.py:5182-5202`, `1620-1676`, `5335`).

**Public evidence:** `GET https://sne.space/api/transients?limit=3` → `total:110701`, newest names `AT2026ahch` / `AT2026ahba` / `AT2026ahcd` dated `2026/10/29`.

**Classification:** **VERIFIED RUNNING** (production API + code). Local DB count (110534) trails production API (110701) — expected if local index not freshly rebuilt after recent TNS upserts.

---

## 2. TNS — `pull_recent` / `fetch_classified` / `fetch_recent_discoveries` / `tns_photometry`

### Search lanes

| Function | File | Behavior |
|----------|------|----------|
| `fetch_classified` | `ingest/pull_recent.py:100-135` | `classified_sne=1`, trailing `days`, paginated CSV |
| `fetch_recent_discoveries` | `ingest/pull_recent.py:138-174` | all discoveries, default 7 days |
| `_fetch_page` | `ingest/pull_recent.py:71-97` | quota + 429 backoff |
| `pull_recent` / `_pull_recent_body` | `ingest/pull_recent.py:271-497` | merge lanes → `_publish` → enrich → re-publish |

Flow in `_pull_recent_body`:

1. `fetch_classified(days)` then merge `fetch_recent_discoveries(days=7)` (`:313-328`).
2. Build cards + `_publish(written)` → `recent-events.json` + `recent-catalog.min.json` + `publish_catalog_items` upsert (`:204-268`, `:355`).
3. Selective enrich via `build_event_dict(..., enrich_alerce=True, enrich_wiserep=False, enrich_tns_spectra=…)` (`:454-459`).
4. Second `_publish` + `_auto_publish_paths` (`:488-495`).

### TNS photometry

| Function | File |
|----------|------|
| `fetch_tns_photometry` | `ingest/tns_photometry.py:379-523` (API then HTML scrape) |
| `apply_tns_photometry_to_event` | `ingest/tns_photometry.py:526+` |
| Called from | `ingest/tns.py:338-345` inside `build_event_dict` |

### Public evidence

- `GET https://sne.space/api/recent` → eight `2026-10-29` AT\* cards (discovery lane live).
- Same names appear at top of `/api/transients`.
- Newest cards: `photo_count: 0`, `spectra_count: 0` — stubs published before / without completed enrich.

**Local enrichment sample:** `AT2026arf.json` has `photometry_ingest.alerce.status=ok` (68 pts) and `tns.status=ok` — proves merge code has succeeded on this corpus historically.

**Classification:**

| Subsystem | Status |
|-----------|--------|
| TNS search + `pull_recent` publish | **VERIFIED RUNNING** |
| `tns_photometry` merge | **PARTIALLY FUNCTIONAL** (code + local successes; production newest rows still `phot=0`) |

---

## 3. ALeRCE lightcurve fetch and merge

| Piece | Location |
|-------|----------|
| Cone search | `ingest/alerce.py:23-75` → `api.alerce.online/ztf/v1/objects/` |
| Lightcurve | `ingest/alerce.py:78+` → `.../objects/{oid}/lightcurve` |
| Convert + merge | `ingest/tns.py:291-336` (`get_alerce_lightcurve`, `convert_alerce_to_astrocats_photometry`, `photometry_merge`) |
| Recent pull flag | `enrich_alerce=True` at `ingest/pull_recent.py:456` |
| EnrichQueue path | `ingest/manager.py:enrich_event` (~429+) |

Local cache tree: `ingest/cache/alerce` (present; ~2325 cache files under `ingest/cache` total).

**Classification:** **IMPLEMENTED NOT VERIFIED** on production live fetches (no public ALeRCE telemetry). Local event evidence of successful `photometry_ingest.alerce=ok` → treat operational capability as **PARTIALLY FUNCTIONAL** at corpus level (works when ZTF OID/coords resolve; not every recent card shows photometry yet).

---

## 4. WISeREP / TNS spectra

| Piece | Location |
|-------|----------|
| TNS spectra scrape | `ingest/tns_spectra.py:57+` (`search_tns_spectra`) |
| Convert | `ingest/tns_spectra.py` + use in `ingest/tns.py:382-390` |
| WISeREP search | `ingest/wiserep.py:32-89` (TSV zip from wiserep.org) |
| Convert | `ingest/wiserep.py` + `ingest/tns.py:392-408` |
| Recent pull | `enrich_tns_spectra=not skip_spec`, **`enrich_wiserep=False`** (`ingest/pull_recent.py:457-458`) |
| On-demand enrich | `enrich_event` can fetch both (`ingest/manager.py`) |

**Classification:**

| Path | Status |
|------|--------|
| TNS spectra in `build_event_dict` / EnrichQueue | **IMPLEMENTED NOT VERIFIED** (no public spectra proof for today's AT\* stubs; `spec:0` on API) |
| WISeREP on discovery poll | **PARTIALLY FUNCTIONAL** — implemented but **disabled** on `pull_recent` (`enrich_wiserep=False`) |
| WISeREP via `enrich_event` | **IMPLEMENTED NOT VERIFIED** |

---

## 5. Host / redshift / dust (`astro_engine`)

**Module:** `serve/astro_engine.py`.

| Capability | Entry | Notes |
|------------|-------|-------|
| Cosmology | `calc_cosmology` / used in `enrich_transient_astrophysics` (`:675+`) | Flat ΛCDM H0=70, Om=0.3 |
| MW dust | `get_milkyway_extinction` (`:325-395`) | IRSA only if `allow_network=True`; else analytical disk model |
| Host resolve | `resolve_host_galaxy` (`:398+`) | landmarks + meta host + optional VizieR when networked |
| Render hook | `serve/server.py:2182-2196` | **`allow_network=False`** on HTTP path |
| TNS host/z into event | `ingest/tns.py:232-248` | written when TNS CSV provides them |
| Catalog table fields | `ingest/catalog_publish.py:event_to_catalog_item` (`:64-123`) | `host` / `redshift` / `maxappmag` |

**Public evidence:** newest `/api/transients` rows often `host:"—"`, `z:null`. Historical `SN2011fe` query shows `host:"M101"`, `z:0.000804` — catalog fields work when present in published metadata.

**Classification:** **PARTIALLY FUNCTIONAL** — derivation engine implemented; request path is cache/analytical-only; table host/z often empty for fresh discoveries; render-time host ≠ always published into CatalogStore (documented debt in `docs/INTERNAL_CATALOG.md`).

---

## 6. `catalog_publish` / CatalogStore / recent-catalog

| Step | Location |
|------|----------|
| Event → catalog item | `ingest/catalog_publish.py:64-123` |
| Overlay merge | `merge_overlay` / `overlay_path` (`:140-169`, `:41-52`) |
| Upsert SQLite | `publish_catalog_items` (`:188-237`) |
| Event files batch | `publish_event_files` (`:240-256`) |
| API query + recent merge | `CatalogEngine.query` → `_merge_recent_into_query_result` (`serve/catalog_engine.py:599-643`, `:259-294`) |
| HTTP handler | `serve/server.py:4508-4559` |
| Homepage JS | `serve/www/assets/catalog-table.js:159-163` → `/api/transients` |

**Public evidence:** API total **110701**; page-1 includes today's AT\* names; `/api/recent` aligned.

**Classification:** **VERIFIED RUNNING**.

---

## 7. Schedulers (`_recent_tns_loop`, EnrichQueue) and docker-compose volumes

### `_recent_tns_loop`

```5160:5179:serve/server.py
def _recent_tns_loop() -> None:
    ...
    poll_s = float(os.environ.get("SNE_TNS_POLL_SECONDS") or str(15 * 60))
    ...
    from ingest.pull_recent import pull_recent
    count = pull_recent()
```

Started in `main()` (`serve/server.py:5340`).

**Evidence:** production recent list dated **today** ⇒ poll loop (or equivalent ingest) **VERIFIED RUNNING**.

### EnrichQueue (`_EnrichmentQueue`)

- Class: `serve/server.py:1935-2118`
- Env bounds: `SNE_ENRICH_QUEUE_MAX/WORKERS/TIMEOUT/ATTEMPTS` (`:1921-1932`, mirrored in `docker-compose.yml:24-27`)
- Start: `_ENRICH_QUEUE.start()` (`:5339`)
- Worker calls `enrich_event` (`:2055`)
- Enqueue from `_event_page` when sparse photometry/spectra and year ≥ 2024 (`:2198-2205`)

`/api/internal/health` → **401** from this host → queue counters **UNVERIFIABLE** publicly.

**Classification:** EnrichQueue code **IMPLEMENTED NOT VERIFIED** (runtime stats gated); enqueue hooks present.

### docker-compose volumes

```37:47:docker-compose.yml
volumes:
  - sne_logs:/app/serve/logs
  - sne_data:/data/astrocats/astrocats/supernovae/output
  - sne_runtime:/data/sne-runtime
```

Env: `SNE_DATA_DIR`, `SNE_RUNTIME_DIR` (`docker-compose.yml:17-21`).  
Optional backfill sidecar comments require same volumes (`:67-78`).

**Classification:** compose contract **IMPLEMENTED** (repo). Whether production deploy mounts these named volumes: **UNVERIFIABLE** from this host (API durability is consistent with mounts but not proof).

---

## 8. Event render path

```
HTTP /sne/{name}/
  → Handler do_GET (serve/server.py ~4890+)
  → _cached_event_page (:1855+)
  → _event_page (:2151+)
       load JSON / catalog stub
       enrich_transient_astrophysics(..., allow_network=False)
       maybe _request_enrichment(...)
       render_pro_cockpit (serve/event_render.py:1292+)
```

Homepage: `/` → `_cached_homepage` → PHP `index.php` (`serve/server.py:663-682`, `:4241-4243`).

### Public probes (this audit)

| URL | Result |
|-----|--------|
| `https://sne.space/` | **200**, ~101 KB, ~0.4–1.5 s |
| `https://sne.space/healthz` | **200** `status:ok` |
| `https://sne.space/sne/SN2024ggi/` | **200**, ~405 KB, ~4 s |
| `https://sne.space/sne/AT2026ahch/` | **timeout**, 0 bytes (12–25 s) |
| `https://sne.space/sne/SN2011fe/` | **timeout**, 0 bytes (15 s) — large historical page |

**Classification:** **PARTIALLY FUNCTIONAL** — render pipeline implemented and serves some event pages; brand-new stubs and at least one large historical page hung with **zero bytes** from this audit network. Not classified BROKEN globally because `SN2024ggi` succeeded.

---

## Example flow: TNS discovery → homepage

Concrete production example: **AT2026ahch** (seen on `https://sne.space` 2026-10-29).

```
1. _recent_tns_loop (server.py:5160)
     └─ pull_recent() (pull_recent.py:271)
2. fetch_classified + fetch_recent_discoveries (pull_recent.py:313-328)
     └─ TNS CSV row Name=AT 2026ahch (or similar)
3. _row → written card (pull_recent.py:177-201, 332-354)
4. _publish (pull_recent.py:204-268)
     ├─ recent-events.json  (homepage SSR cards)
     ├─ recent-catalog.min.json
     └─ publish_catalog_items → CatalogStore.upsert_catalog_items
           + published-updates overlay (catalog_publish.py:188-237)
5. Optional enrich (pull_recent.py:443-476)
     └─ build_event_dict → ALeRCE + TNS phot + TNS spectra
           → sne-2025-2029/AT2026ahch.json (manager.get_target_repo_folder)
     └─ _auto_publish_paths → overlay + upsert again
6. Homepage
     ├─ SSR: index.php reads recent-events / recent-catalog (server _homepage_inputs)
     └─ JS: catalog-table.js fetchData() → GET /api/transients
7. /api/transients
     └─ CatalogEngine.query → CatalogStore.query
           → _merge_recent_into_query_result (catalog_engine.py:633)
8. User click → /sne/AT2026ahch/
     └─ _event_page → stub or JSON → render_pro_cockpit
           (+ EnrichQueue if sparse)
```

**Observed at step 6–7:** name present in `/api/recent` and `/api/transients` with `phot:0`, `spec:0`, `type:unclassified`.  
**Observed at step 8:** page fetch timed out from audit host (stub/cold-render risk).

---

## Classification summary (subsystems)

| # | Subsystem | Classification |
|---|-----------|----------------|
| 1 | Historical AstroCats paths + CatalogStore build | **VERIFIED RUNNING** (prod catalog API); local event JSON corpus **PARTIALLY FUNCTIONAL** / incomplete (~2.7k vs ~110k) |
| 2 | TNS `pull_recent` / classified / discoveries | **VERIFIED RUNNING** |
| 2b | `tns_photometry` | **PARTIALLY FUNCTIONAL** |
| 3 | ALeRCE fetch + merge | **PARTIALLY FUNCTIONAL** (local ok samples; prod newest often empty) |
| 4a | TNS spectra | **IMPLEMENTED NOT VERIFIED** |
| 4b | WISeREP | **PARTIALLY FUNCTIONAL** (off on `pull_recent`; on in `enrich_event`) |
| 5 | Host/redshift/dust `astro_engine` | **PARTIALLY FUNCTIONAL** |
| 6 | `catalog_publish` / CatalogStore / recent-catalog / `/api/transients` | **VERIFIED RUNNING** |
| 7a | `_recent_tns_loop` | **VERIFIED RUNNING** |
| 7b | EnrichQueue | **IMPLEMENTED NOT VERIFIED** |
| 7c | docker-compose volume wiring | **IMPLEMENTED** (config); prod mount **UNVERIFIABLE** |
| 8 | Event render path | **PARTIALLY FUNCTIONAL** |

### Explicit non-claims

- Production durable volume size for event JSON: **UNVERIFIABLE** from this host.
- EnrichQueue counters / IRSA live dust: **UNVERIFIABLE** (`/api/internal/health` 401; render uses `allow_network=False`).
- No subsystem marked **NOT IMPLEMENTED** among the eight requested areas — all have code paths.
- No subsystem marked globally **BROKEN**; event-page hangs for some names are recorded under **PARTIALLY FUNCTIONAL**.

---

## Evidence index (public HTTP)

| Probe | Outcome |
|-------|---------|
| `GET /healthz` | `{"status":"ok",...}` |
| `GET /api/transients?limit=3` | `total:110701`, today's AT\* |
| `GET /api/transients?q=SN2011fe&limit=1` | rich historical row |
| `GET /api/recent` | 8 cards, date `2026-10-29` |
| `GET /` | 200 HTML |
| `GET /sne/SN2024ggi/` | 200 HTML |
| `GET /sne/AT2026ahch/` | timeout / 0 bytes |
| `GET /api/internal/health` | 401 |

---

*End of phase 1 architecture evidence.*
