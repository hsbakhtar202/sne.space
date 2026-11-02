# Scientific Accuracy Audit

Scope: audited sample + catalog-wide advertised-field statistics. Read-only.

Evidence: `AUDIT_EVIDENCE/phase6_scientific.md`, `phase2_catalog_scan.json`, reconciliation CSV, code paths in `ingest/astronomy.py`, `serve/event_render.py`, `ingest/catalog_publish.py`.

---

## 1. Discovery magnitude vs peak magnitude

### Confirmed defect (semantic)

**Code intent (post-P0):** fitted / “peak” requires `peak_established` with ≥2 photometric detections (`ingest/astronomy.py` / render path). Discovery magnitude must not be labeled as peak.

### Catalog-wide evidence of residual misrepresentation risk

From `catalog.min.json` scan (`phase2_catalog_scan.json`):

| Metric | Count | % of 110,703 |
| --- | --- | --- |
| `photometrycount == 1` | ~71,700 | ~65% |
| `maxappmag` present with `photometrycount ≤ 1` | large (see CSV) | high |

**Interpretation:** A single discovery magnitude (or single detection stub) is the modal “photometry” footprint. Any UI/API that surfaces `maxappmag` / “peak” without an explicit `peak_established` gate will present **discovery brightness as peak**.

### Sample findings

| Event | Issue | Classification |
| --- | --- | --- |
| AT2026agub | Upstream/local: 1 det + 1 limit. Not a physical peak. Prod API advertises phot=0 (under-report), not a false peak. | Confirmed: no peak support |
| Recent AT2026ah\* | Often phot=0 or 1 on API | Suspected stub / under-publish |
| 2011fe / 1987A | Multi-epoch photometry; peak semantics more defensible if fitted from dense LC | Not flagged as false peak in this pass |

**Rule applied:** two detections alone are **not** accepted as a physical peak without provenance or model support.

---

## 2. Observation time / MJD / JD

- TNS HTML/API paths convert observation times into AstroCats-style fields in `tns_photometry.py`.
- Sample check (agub): local persisted time aligns with TNS scrape evidence files under `phase3_raw/`.
- **No catalog-wide MJD audit executed** (would require parsing every photometry array). Status for corpus: **UNVERIFIED**.

---

## 3. Filters and magnitude systems

- ALeRCE/ZTF bands generally retained when photometry merges succeed (e.g. 2023ixf).
- Events with missing band/source metadata: present in integrity CSV as “source/band missing” counts where detectable from JSON keys.
- Catalog-wide filter-system consistency: **PARTIALLY VERIFIED** (sample only).

---

## 4. Upper limits vs detections

| Finding | Evidence |
| --- | --- |
| agub stores 1 upper limit locally | local JSON + phase3 |
| Prod API `phot` often counts detections only / shows 0 | API probes — **limit visibility on index unclear** |
| Risk | UI may omit non-detections even when stored |

Treat “API phot=0 while upstream has limit” as **publication/index incompleteness**, not proof limits are scientifically wrong when present in event JSON.

---

## 5. Redshift, velocity, distances, dust

| Quantity | Status | Notes |
| --- | --- | --- |
| Host / redshift on table | Often empty (~80% host missing in catalog.min.json scan) | Publish path historically omitted fields; enrichment uneven |
| Redshift → velocity | Code exists in astronomy helpers | **Not validated** against independent host redshifts for full sample |
| Luminosity distance / lookback | Computed when z present | Generic cosmology; **not event-specific model** — must not be labeled “measured” |
| Dust / extinction | Render-time / dust maps | Provenance depends on map version; **not audited corpus-wide** |
| Absolute magnitude | Requires peak + distance + extinction | Invalid if peak is discovery stub |

**Confirmed scientific risk:** presenting extinction-corrected absolute magnitude when peak is a single discovery mag.

---

## 6. Host galaxy association

- Catalog index: large fraction missing host.
- Sample historical SNe: hosts often present from AstroCats inheritance.
- Recent ATs: hosts frequently absent on API even when TNS object page may list a host — **suspected enrichment/publish gap** (need per-event TNS host scrape to confirm; not completed for all 30).

---

## 7. Spectroscopic classification provenance

- Classifications on index frequently present for historical / classified TNS objects.
- **Source-provided classification ≠ independent verification.**
- WISeREP spectra largely **not** pulled on live path (`enrich_wiserep=False`) → many classed events without local spectra arrays (integrity CSV).

---

## 8. Rest-frame phase / class models

- Event pages may show phases relative to discovery or claimed peak.
- If peak is unsupported, **rest-frame phase is scientifically unsupported**.
- FAQ / marketing claims that imply continuous multi-survey light curves for all recent ATs are **not supported** by photometry distributions (~65% single-point or stub-level in index).

---

## 9. Instances in audit sample where inferred values may appear as measured

| Presentation | Sample events | Verdict |
| --- | --- | --- |
| “Peak” / maxappmag with ≤1 detection | Many recent AT\* | **Demonstrably unsupported** as physical peak |
| Photometry count > 0 while arrays empty | Check advertised vs stored (API vs JSON) | Confirmed for agub: API under-reports vs local |
| Classification without spectrum file | Classified ATs with spectra=0 | Provenance is TNS report, not local spectrum |
| Distance moduli without secure z | Events with blank z | Must not be shown as measured |

---

## 10. Summary judgment (scientific layer)

The site can correctly display **inherited multi-epoch AstroCats light curves** for famous historical SNe. For the live AT stream, the dominant scientific product is **discovery metadata**, not validated photometric time series or fitted peaks. Treating discovery magnitudes as peaks, or advertising photometry counts that do not match persisted arrays, are the primary scientific integrity failures identified.
