# Internal catalog briefing — AstroCats vs sne.space

Audience: us. Not public marketing copy.

This is what the system **is**, what it **inherits**, what every event page **should** show, and where we still lie to ourselves.

---

## 1. Lineage

### Old AstroCats / Open Supernova Catalog (OSC)

- Research project (Guillochon et al. 2017, ApJ 835, 64) that defined a **shared JSON schema** for supernovae: aliases, coords, claimed type, redshift, host, photometry arrays, spectra arrays, sources/provenance.
- Data lived as per-event JSON under year buckets (`sne-YYYY-YYYY/NAME.json`), plus aggregate catalogs (`catalog.min.json`, etc.).
- Ingestion was largely **batch / harvest / contribution** oriented: literature + survey dumps into AstroCats, not a 15‑minute live TNS loop with a modern web UI.
- The “product” was the open dataset + schema. The classic sne.space site was a thin viewer on top of that corpus.

### This repo (sne.space today)

- **Same AstroCats event JSON** on disk as the source of truth for an object.
- **Live layer** on top:
  - TNS poll (`pull_recent`) every ~15 minutes → recent list + stubs
  - Enrichment: ALeRCE/ZTF light curves, TNS photometry/spectra, WISeREP spectra
  - `CatalogStore` (SQLite) + `recent-catalog.min.json` for the homepage table
  - Python event cockpit + story pages (`event_render`), FAQ, radar, APIs, MCP
- We still ship / sync the historical OSC corpus; we are not a clean-room catalog. We are OSC schema + continuous ingest + a stricter scientific UI.

**One-liner:** AstroCats defined the file format and the archive. sne.space is the live service that must keep that archive honest under modern survey cadence.

---

## 2. Data sources (what feeds what)

| Source | What it gives us | Where it lands | Notes |
| --- | --- | --- | --- |
| **Legacy OSC / AstroCats JSON** | Historical photometry, spectra, hosts, z, literature sources | Event files; bulk `catalog.min.json` → CatalogStore | Backbone of the 110k |
| **TNS search (classified + discovery lanes)** | Name, coords, type, discoverer, discovery date/mag, sometimes host/z | `recent-events.json`, `recent-catalog.min.json`, new/updated event stubs, CatalogStore upsert | Discovery lane is why AT2026\* shows before classification |
| **TNS object page / photometry** | Detections + upper limits (time, mag, err, band, instrument) | `event["photometry"]`, `photometry_ingest.tns` | Preferred structured endpoint; HTML table is fallback |
| **ALeRCE / ZTF** | Dense optical LC + non-detections when OID exists | Merged into `photometry` (deduped) | Empty ALeRCE ≠ no observations exist |
| **WISeREP / TNS spectra** | Calibrated spectra | `event["spectra"]` | Enrichment, not guaranteed at discovery |
| **NED / VizieR / dust (IRSA)** | Host name, offsets, MW E(B−V), cosmology helpers | Often **render-time** on the event page | Easy to show on cockpit and **never** write into CatalogStore — table then shows `—` |

### Two indexes that must not disagree

1. **Homepage SSR** — PHP reads runtime `recent-catalog.min.json` (TNS pull).
2. **Homepage JS / `/api/transients`** — CatalogStore (+ recent merge).

If (1) has AT2026ahaw and (2) does not, the UI flashes correct then snaps to stale. Fix path: upsert recent rows into CatalogStore on every `_publish`, and merge recent into page‑1 API results.

---

## 3. What every supernova / AT page should show

These are **product requirements**, not “always populated.” Empty must mean *unknown / not fetched / not inferred*, never invented.

### Always present (chrome + identity)

| UI block | Backing fields | Rule |
| --- | --- | --- |
| Designation + aliases | `name`, `alias` | Include TNS + survey IDs (e.g. ZTF\*) when known |
| Coordinates | `ra`, `dec` | Sexagesimal + decimal available via APIs |
| Discovery date | `discoverdate` | From TNS / OSC |
| Claimed type | `claimedtype` | `unclassified` if none — never blank |
| Sources list | `sources` | Provenance for every derived field |
| Download links | JSON / photometry CSV / spectra | Same data the page claims |

### Photometry / brightness

| UI block | Backing fields | Rule |
| --- | --- | --- |
| Light curve | `photometry[]` | Detections vs `upperlimit` / `kind=non_detection` plotted differently |
| Observation counts | Derived from array (+ `photolink` must match) | `photolink` / table “📈 N” = persisted detections, **not** days since discovery |
| Discovery magnitude | `discoverymag` (kind=`discovery`) | OK with 1 point |
| Peak / max apparent mag | `maxappmag` only if peak established (≥2 detections or explicit fitted peak) | **Never** label discovery mag as “Peak” |
| Brightest observed | `brightest_observed_mag` or honest copy from LC | Distinct from fitted peak |
| Ingest coverage | `photometry_ingest.{alerce,tns}` | `ok` / `empty` / `unavailable` / `error` — do not conflate |

### Spectroscopy & host / distance

| UI block | Backing fields | Rule |
| --- | --- | --- |
| Spectra | `spectra[]` | Count in table = persisted spectra |
| Redshift | `redshift` | Often absent until classification; table must use CatalogStore fields we actually publish |
| Host galaxy | `host` (+ offsets if present) | Prefer persisted TNS/OSC host; render-time NED is a bonus that must be written back if we want the **table** to show it |
| Distance / cosmology | derived from z + cosmology helpers | Only when z exists |
| MW dust E(B−V) | dust cache / IRSA | Cache-first; no fabricating extinction |

### Scientific narrative (cockpit / story / FAQ)

| Claim | Minimum evidence |
| --- | --- |
| “Peak magnitude” | Multi-epoch peak or independent cataloged peak |
| Brightness trend / fading | ≥2 same-band detections in window |
| Decline rate, energy, “tonight” model mag | Event-specific fit or stated as unavailable |
| Host association text | Host name or explicit “unidentified” |
| Velocity / spectral features | Spectrum present |

**Single detection:** discovery mag + upper limits OK; peak / trend / decline **not established**.

---

## 4. Homepage table columns (what they mean)

| Column | Meaning | Common failure |
| --- | --- | --- |
| Designation | Catalog name | — |
| Type | `claimedtype` | Blank → should be `unclassified` |
| Discovery date | `discoverdate` | Sort/index lag vs recent list |
| Redshift z | CatalogStore `z` from published `redshift` | Event JSON had z but publish path omitted it (fixed in catalog item builder) |
| Peak Mag | CatalogStore `mag` from `maxappmag` / discovery fallback | Often empty if never upserted; label still says “Peak” even when kind is discovery — UI debt |
| Coordinates | `ra`/`dec` | — |
| Host Galaxy | CatalogStore `host` | Render-time host ≠ table host |
| Spectra / Light Curve | Counts from `spectralink` / `photolink` | `1` often means discovery-only stub, not “survey only took one image ever” |

**Light-curve count of 1:** normal for a fresh AT/SN stub (discovery point only). Abnormal if the object is weeks old, has a ZTF OID, and ALeRCE/TNS still show richer data we never merged.

---

## 5. Pipeline states (do not conflate)

For photometry (and similarly spectra):

1. **Exists upstream** (TNS/ALeRCE has rows)
2. **Fetched** (our client got a response)
3. **Stored** (`photometry[]` on the event JSON)
4. **Inferrable** (enough points for peak/trend/fit)

Catalog UX must distinguish (2)/(3) via `photometry_ingest` and must not treat (1) as (4).

---

## 6. What old AstroCats did *not* do (that we now own)

- Continuous TNS discovery + classified polling into a live homepage
- Idempotent multi-source photometry merge (ALeRCE + TNS) with upper-limit semantics
- CatalogStore / `/api/transients` as the interactive table backend
- Scientific guardrails in UI (no fabricated peak/tonight mag from one point)
- MCP / agent endpoints on the same corpus

What we still depend on from AstroCats: **schema + historical event files + citation culture**.

---

## 7. Known integrity failure modes (watch list)

1. **SSR vs API split** — recent list ahead of CatalogStore → flash then stale table.
2. **Orphan scalar mags** — `maxappmag` / discovery mag with empty `photometry[]`.
3. **Fake availability** — `photolink` or “1 photometry” advertising without points (or the reverse: rich file, table still shows 1 until republish).
4. **Discovery labeled as peak** — UI or catalog column says Peak for a single epoch.
5. **Host/z on page, `—` on table** — render-time enrichment not published to CatalogStore.
6. **ALeRCE empty ⇒ give up** — skips TNS photometry for fresh ZTF/ATLAS objects.

---

## 8. Quick “is this event healthy?” checklist

Open `/sne/<NAME>/` and the raw JSON:

- [ ] `photometry[]` length matches light-curve plot and table count after publish
- [ ] Upper limits not drawn as detections; not used as peak
- [ ] `discoverymag` vs `maxappmag` kinds make sense for point count
- [ ] `photometry_ingest.tns` / `.alerce` status present and believable
- [ ] `redshift` / `host` in JSON if the cockpit shows them
- [ ] `/api/transients?q=<NAME>` returns same mag/z/host/phot as the file (after upsert)
- [ ] No peak/trend/fit language with `< 2` scientific detections

---

## 9. Pointers in this repo

| Path | Role |
| --- | --- |
| `ingest/pull_recent.py` | TNS → recent list + stubs + CatalogStore upsert |
| `ingest/tns.py` / `ingest/tns_photometry.py` | Event build + TNS photometry merge |
| `ingest/catalog_publish.py` | Event/recent → overlay + SQLite (`host`/`redshift`/`maxappmag`) |
| `serve/catalog_store.py` / `serve/catalog_engine.py` | Table API backend + recent merge |
| `serve/event_render.py` | Cockpit / story scientific UI |
| `serve/astro_engine.py` | Host/dust/cosmology helpers (often request-time) |
| `docs/production_sync_plan.md` | Deploy / corpus sync caution |

---

*Last updated to match the Oct 2026 P0 photometry + catalog-table field work. Update this file when ingest semantics change; do not let About/FAQ drift into a second source of truth.*
