# sne.space Architecture Report

**Open Supernova Catalog (OSC) — rebuild planning document**  
**Date:** 2026-09-23 (revised: Step 1 = scientific system @ original namespace)  
**Status:** Domain acquired; live site and `api.sne.space` are down (Sav.com coming-soon DNS).  
**Goal:** Reconstruct the **historical OSC catalog system** (AstroCats object model, webcat outputs, catalog UI, OACAPI) **at the original public namespace** from day one. Then (separately) build OSC 2.0 / MSystem.

---

## 1. Executive summary

`sne.space` was the **Open Supernova Catalog** — not a brochure site with pretty URLs. The product was AstroCats’ scientific data model: per-event JSON (aliases, types, hosts, photometry, spectra, provenance), generated aggregates (`catalog`, names, hosts, conflicts, dupes, bibliography), Bokeh event pages, Transient Table for browsing, and OACAPI for programmatic access. WordPress was only a shell.

**Wrong framing (discarded):** “Rebuild URLs / reconnect old addresses later.”  
**Right framing:** Reconstruct the **machine** (corpus + AstroCats + webcat + catalog UI + API) **already living at the historical public namespace**. Backlinks recover because the system occupies the same addresses. The ~14.4k URL list is **automated proof** we implemented that namespace correctly — not a separate SEO project and not the architecture.

### Two steps (do not conflate)

| | **Step 1 — Historical OSC parity** | **Step 2 — OSC 2.0** |
| --- | --- | --- |
| What | Same objects + same structure + same outputs + **same addresses** + same API behavior | New ingest, MSystem, live feeds, new product |
| Input | Historical `sne-*` JSON (+ module/schema/runtime deps) | Upstream sources after diligence |
| Live TNS / Fink / Rubin / MSystem / Postgres? | **No** | Later |
| Proof | Catalog/API behave correctly; ~14.4k URL suite is the verifier | §§14–15 |

**Key insight:** Do **not** re-run old ingestion to restore the site — the dataset already exists. Do **run** AstroCats/`webcat` so the per-object JSON → aggregate transformation is verified and understood before MSystem replaces it. Do **not** build a new catalog and later map old paths onto it.

Corpus freeze: **72,145** events in `catalog.json`; year-repo pushes ~**2022-04**; `supernovae` through **2023-03**.

### 1.1 Step 1 build specification (one architectural target)

```text
Historical OSC corpus (sne-* event JSON)
        ↓
AstroCats-compatible object structure (+ schema, module)
        ↓
webcat-derived outputs
  catalog.json / catalog.min.json
  names.min.json / names-by.min.json
  hosts, dupes, conflicts, bibliography, …
  per-event JSON + plots/pages
        ↓
┌──────────────────────────────────────────────┐
│ Exact historical public namespace (day one)  │
│                                              │
│ /  → Transient Table over catalog.min.json   │
│ /sne/{name}/  /event/{name}  (native resolve)│
│ /sne/{name}.json                             │
│ /astrocats/.../output/...                    │
│ api.sne.space/{object}/...                   │
│ /about/ /download/ /statistics/ … (slugs)    │
└──────────────────────────────────────────────┘
```

**Native resolver behavior from day one** (from `event.php` — not a bolt-on):

| Request | Resolves to |
| --- | --- |
| `/sne/2011fe/` | SN2011fe |
| `/sne/SN2011fe/` | SN2011fe |
| `/sne/sn2011fe/` | SN2011fe |
| known alias | canonical object |
| SN↔AT equivalent | canonical object |
| near-miss (Levenshtein &lt; 4) | closest + warning (original behavior) |

### 1.2 What Step 1 needs

| Need | Role |
| --- | --- |
| Full historical event JSON (`sne-*`, plus runtime refs as required) | Scientific corpus |
| AstroCats + `supernovae` module + schema | Object model; reproducible `webcat` |
| **`webcat` over historical objects** | Regenerates aggregates + per-event HTML **not in git** |
| Transient Table | Catalog UX over `catalog.min.json` |
| OACAPI | Same scientific system, programmatic |
| Original path + API grammar | Public namespace — **spec from line one**, not phase “later” |
| Thin IA pages at old slugs | Rewrite OK; no WordPress |

**Why rebuild the machine, not just serve `catalog.json`:** We must verify object → catalog transformation still works and learn how OSC represented aliases, multi-types, conflicting redshifts, hosts, photometry, spectra, and provenance — **before** replacing that machinery with MSystem. URLs teach almost nothing about that; the AstroCats object model does.

### 1.3 What Step 1 does **not** need

Live TNS · updated 2023–2026 objects · MSystem · Postgres · semantic reconciliation · forecasting · Rubin/Fink/ALeRCE · magazine/editorial stack · re-running full historical **import** from upstream scrapers.

### 1.4 Acceptance (scientific system + namespace proof)

**Done when:**

1. AstroCats/`webcat` successfully regenerates aggregates and event outputs from the historical corpus.  
2. Catalog UI (Transient Table) + secondary tables + object pages + downloads work on those products.  
3. OACAPI serves the same corpus with documented routes.  
4. The system is deployed **on the historical public namespace**; the ~**14,446**-URL crawl suite (plus API examples) passes as **proof** — every meaningful historical address returns the object/data or canonical equivalent.

Engineering may be sequenced (corpus → webcat → UI/API on that tree). Architecturally it is **one** thing: historical OSC parity.

---

## 2. Current state (Sep 2026)

| Asset | State |
| --- | --- |
| `sne.space` DNS | Parked: `ns1/ns2-coming-soon.sav.com` |
| Website / `api.sne.space` | Down |
| Sibling OAC sites | Mostly down; `kilonova.space` still returns 200 |
| GitHub data | Intact under [`astrocatalogs`](https://github.com/astrocatalogs) |
| `catalog.json` | Present (~53 MB) in `astrocatalogs/supernovae` |
| Per-event JSON | Year repos `sne-pre-1990` … `sne-2020-2024` (~12.3 GB GitHub size aggregate) |
| Generated HTML plots | **Not in git** — must regenerate with `webcat` |
| Local inventory | `sne_space_crawled_pages*.csv` (~14.4k unique URLs), `sne_space_backlinks.csv` (wiki/CC **sample only**) |

---

## 3. Original system architecture

### 3.1 Logical diagram

```
                    ┌─────────────────────────────────────────┐
                    │             Public internet             │
                    └───────────────┬─────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
   sne.space (HTTPS)         api.sne.space              GitHub links
          │                         │                  (download zips)
          │                         │
   ┌──────┴──────┐           ┌──────┴──────┐
   │  WordPress  │           │   OACAPI    │
   │  (Parabola  │           │   Flask     │
   │  + child)   │           │  gunicorn   │
   └──────┬──────┘           └──────┬──────┘
          │                         │
   ┌──────┴─────────────────────────┴──────┐
   │     Shared filesystem (AstroCats)     │
   │  /root/astrocats/astrocats/supernovae │
   │    output/catalog.min.json            │
   │    output/names.min.json              │
   │    output/html/{Event}.html           │
   │    output/json/{Event}.json           │
   │    output/hosts.min.json, …           │
   └──────────────────┬────────────────────┘
                      │ produced by
           ┌──────────┴──────────┐
           │ AstroCats import +  │
           │ scripts.webcat      │
           │ (year sne-* JSON)   │
           └─────────────────────┘
```

**Production path conventions (from source):**

- OACAPI: `/root/astrocats/astrocats/{module}/output/`
- Event template `file_exists`: `/root/` + `astrocats/astrocats/supernovae/output/html/`
- WP name maps: `/var/www/html/sne/astrocats/astrocats/supernovae/output/names*.json`
- Public URL mirror: `https://sne.space/astrocats/astrocats/supernovae/output/...`

### 3.2 Layer A — Data plane (AstroCats)

**Repos**

| Repo | Role |
| --- | --- |
| [`astrocatalogs/astrocats`](https://github.com/astrocatalogs/astrocats) | Framework |
| [`astrocatalogs/supernovae`](https://github.com/astrocatalogs/supernovae) | OSC module, `catalog.json`, schema, import tasks |
| `sne-pre-1990` … `sne-2020-2024` | Per-event JSON by discovery year |
| `sne-internal`, `sne-external*`, `sne-boneyard` | Inputs / graveyard |

**Pipelines**

1. **Import:** `python -m astrocats supernovae import`  
   Aggregates dozens of sources (tasks in `input/tasks.json`: internal, SIMBAD, VizieR, WISeREP spectra, radio, X-ray, …). Writes/updates per-event JSON in year folders.
2. **Web catalog:** `python -m astrocats.scripts.webcat -c sne`  
   Writes catalog aggregates and optional per-event Bokeh HTML.

**Important `webcat` flags**

| Flag | Effect |
| --- | --- |
| (default) | Write catalog + HTML |
| `--no-write-html` | Catalog/names only (faster path to homepage) |
| `--no-write-catalog` | Skip catalog files |
| `--force-html` | Regenerate HTML even if present |
| `--event-list …` | Subset of events |

**Artifacts written when `writecatalog` is on** (from `webcat.py`):  
`catalog.json`, `catalog.min.json`, `bones.json`, `bones.min.json`, `names.min.json`, `names-by.min.json`, `md5s.json`, `hostimgs.json`, `iaucs.json`, plus related tables (`hosts`, `dupes`, `conflicts`, `biblio`, `frbs`, `sentinel`, …).

**Event JSON shape (example `SN2011fe`, ~25 MB):**  
Top-level key = event name; quantities include `alias`, `claimedtype`, `ra`/`dec`, `photometry` (thousands of points), `spectra`, `sources`, distances, host fields, etc. Schema: [`astrocatalogs/schema`](https://github.com/astrocatalogs/schema).

### 3.3 Layer B — Static public tree

Publicly mirrored as:

```
/astrocats/astrocats/supernovae/output/
  catalog.min.json          ← homepage DataTables ajax
  bones.min.json            ← graveyard table
  names.min.json            ← alias → canonical
  names-by.min.json
  hosts.min.json
  dupes.json, conflicts.json, biblio.json, frbs.json, sentinel.json, errata.json
  html/{Event}.html         ← Bokeh event page (iframe target)
  html/{Event}-host.jpg     ← host thumbnails
  json/{Event}.json         ← per-event download (also via API)
```

Filename rule: `/` in names → `_` (`nameToFilename` in Transient Table).

### 3.4 Layer C — Catalog UI (Transient Table)

Repo: [`astrocatalogs/transient-table`](https://github.com/astrocatalogs/transient-table)  
WordPress plugin (~150 KB PHP embedding DataTables config + JS).

**Data loading (not the API):**

```javascript
var ajaxURL = '/../../astrocats/astrocats/' + modu + '/output/' +
              ((bones) ? 'bones' : 'catalog') + '.min.json';
// DataTables ajax: { url: ajaxURL, ... }
```

**Config file `tt.sne.dat`:**

```
sne
supernovae
sne
sne
alias,maxdate,...          # invisible columns
maxdate,discoverdate       # ...
...
SNe
Supernova
```

**Pages that enqueue the plugin:** front page, find-duplicates, bibliography, sentinel, find-conflicts, errata, host-galaxies, graveyard, atel, frbs, mosfit (and search).

**Homepage query permalinks** (client-side filters; must keep working):

| Param | Role |
| --- | --- |
| `claimedtype` | Type filter (supports `OR`, `!`, quotes) |
| `event` | Name filter (comma lists) |
| `visible` | Column visibility list |
| `sort`, `direction` | Sort column / asc|desc |
| `instruments`, `redshift`, `maxabsmag`, `spectralink`, … | Advanced filters |
| `p={id}` | Legacy WordPress page IDs → redirect to canonical slugs |

Row links: `https://sne.space/sne/{nameToFilename(name)}/`  
Download icon: `https://sne.space/sne/{name}.json` (download attribute; needs rewrite or static map to `output/json/`).

### 3.5 Layer D — Event pages (`/sne/`, `/event/`)

Repo: [`astrocatalogs/astrocats-child-theme`](https://github.com/astrocatalogs/astrocats-child-theme)

**Rewrites (`functions.php`):**

- `^event/(.+)/?` → WP page_id **1320** + `eventname`
- `^sne/(.+)/?` → same  
- Config `tt.sne.dat`: stem=`sne`, module=`supernovae`, page=`1320`, title=`Supernova`

**`event.php` resolution (compatibility-critical):**

1. URL-decode; strip `.html`
2. If name looks like year-letter (`2011fe`, `1979C`) → prepend `SN`
3. Normalize `sn` → `SN`, `SN ` → `SN`, case rules for letter suffix
4. Lookup exact alias in `names.min.json` / `names-by.min.json` (also try SN↔AT swap)
5. Else Levenshtein closest match if distance &lt; 4 (show orange warning)
6. Load iframe:  
   `https://sne.space/astrocats/astrocats/supernovae/output/html/{canonical}.html`  
   (supports `.html.gz`)

**This logic must be ported verbatim** for backlink/alias survival — independent of WordPress.

### 3.6 Layer E — OACAPI

Repo: [`astrocatalogs/OACAPI`](https://github.com/astrocatalogs/OACAPI)  
Paper: [arXiv:1804.10847](https://arxiv.org/abs/1804.10847)

- Flask + flask-restful + CORS + compression
- Loads `catalog.min.json` (and graveyard `bones.min.json`) from disk at startup
- Deep object queries fall through to `output/json/{name}.json`
- Hosted historically at `https://api.sne.space/` (also `api.astrocats.space`, etc.)

**Route pattern:**

```
/{catalog_or_object}/{quantity?}/{attribute?}?args
```

Examples still cited in literature/software:

- `https://api.sne.space/catalog?format=csv`
- `https://api.sne.space/SN2014J/photometry/magnitude+e_magnitude+band`
- Cone search via `ra`, `dec`, `radius`

Wayback confirms `api.sne.space` was live through at least early 2023.

**Frontend did not depend on OACAPI.** It remains mandatory for external backlinks from papers, notebooks, and packages (e.g. AstroDASH, MOSFiT, snpy patterns).

### 3.7 Layer F — Content / IA (WordPress pages)

Nav (from archived Download page + homepage):

| Path | Purpose |
| --- | --- |
| `/` | Main catalog table |
| `/about/` | About |
| `/contribute/` | How to add data |
| `/contribute/find-duplicates/` | Dupe finder table |
| `/contribute/find-conflicts/` | Conflict finder |
| `/mosfit/` | MOSFiT |
| `/derivations/` | Derived quantities |
| `/statistics/` | Census |
| `/statistics/host-galaxies/` | Hosts table |
| `/statistics/sky-locations/` | Sky locations |
| `/download/` | Links to GitHub year-repo zip archives |
| `/bibliography/`, `/errata/`, `/sentinel/` | Sources |
| `/graveyard/` | Non-SNe (`bones`) |
| `/atel/` | Astronomer’s Telegrams |
| `/frbs/` | FRB associations |
| `/links/` | External links |
| `/event/` | Event entry / alias of event flow |

Archived sitemap also lists individual `/sne/...` URLs (including names with spaces, e.g. `PSN J2336140+020924`).

No WordPress DB dump is available → keep **URL slugs**; **rewrite** informational prose (Wayback is a structure reference only — see §14.6).

---

## 4. Request flows (what to preserve)

### 4.1 Homepage catalog

```
GET /  or  GET /?claimedtype=ib%20OR%20ic&visible=...
  → HTML shell with Transient Table
  → XHR GET /astrocats/astrocats/supernovae/output/catalog.min.json
  → Client-side filter/sort/export/permalink
  → Click row → /sne/{name}/
```

### 4.2 Event page

```
GET /sne/2011fe/   or  /sne/SN2011fe/  or  /event/SN2011fe
  → Name normalize + alias resolve (names*.json)
  → Shell page + iframe → /astrocats/.../output/html/SN2011fe.html
```

### 4.3 Secondary tables

Same Transient Table machinery against `bones.min.json`, `hosts.min.json`, `dupes.json`, etc., on their WP (or static) pages.

### 4.4 API (external)

```
GET https://api.sne.space/catalog?format=csv
GET https://api.sne.space/{Object}/{quantity}/...
  → Flask reads catalog.min.json / output/json/
```

### 4.5 Download hub

`/download/` pointed users at GitHub archives:

- `https://github.com/astrocatalogs/sne-pre-1990/archive/master.zip`
- … through `sne-2020-2024`

---

## 5. Historical public namespace (day-one contract, not a later phase)

The path grammar below is part of the Step 1 **build spec** from the first route. Backlinks are recovered by occupying these addresses — not by a separate restoration project. The crawl inventory is the **proof suite**.

### 5.1 Scope

| Inventory | Count | Use |
| --- | --- | --- |
| Unique archived URLs (local crawl) | ~14,446 | Primary compatibility suite |
| Event name variants under `/sne/` | ~9,058 | Must resolve |
| `/astrocats/` static paths | ~4,907 | Must serve or regenerate |
| Content/nav paths | ~30 | Same slugs |
| Homepage query variants seen | ~31 | Param semantics |
| Estimated inbound links | **15,000+** | Real backlink universe |
| `sne_space_backlinks.csv` | ~150 / 51 targets | **Sample only** (Wikipedia + CC domain graph) |

### 5.2 Hard requirements

1. **Path grammar unchanged:** `/sne/{name}/`, `/sne/{name}`, `/event/{name}`, content IA, `/astrocats/.../output/**`
2. **Name resolution:** Port `event.php` rules (SN prepend, SN↔AT, aliases, Levenshtein)
3. **Query permalinks:** Transient Table GET params continue to filter the table
4. **Schemes:** `http://` → `https://`; accept with/without trailing slash where historically mixed
5. **API host:** `api.sne.space` with OACAPI route compatibility
6. **Downloads:** `/sne/{name}.json` and/or `output/json/{name}.json` reachable
7. **Spaces / encoding:** e.g. `/sne/SN%202213-1745/`, `/sne/PSN J2336140+020924` (sitemap)

### 5.3 Event naming mix in crawl

| Pattern | Approx. count |
| --- | --- |
| Year-letter without `SN` (`2011fe`, `1979C`) | ~3,646 |
| Survey / other (`iPTF…`, `ASASSN-…`) | ~2,677 |
| `AT…` | ~1,706 |
| `SN…` | ~1,187 |
| Trailing slash vs not | ~9,005 vs ~216 |

---

## 6. GitHub assets map

| Repo | Rebuild role |
| --- | --- |
| `supernovae` | Module + `catalog.json` + SCHEMA + tasks |
| `astrocats` | Import + **`webcat.py`** |
| `sne-*` year repos | Full event JSON corpus (~12+ GB) |
| `OACAPI` | Deploy as `api.sne.space` |
| `transient-table` | Extract JS/CSS/PHP table logic into static pages |
| `astrocats-child-theme` | **Spec** for rewrites + `event.php` resolver |
| `schema` | Validation |
| `sne-internal` / `sne-external*` | Optional full re-import |
| `astrocats-webpage` | Sibling hub only |

**Gap:** `output/html/` in git is templates only — not the live Bokeh corpus.

---

## 7. Step 1 target — one system, original namespace

WordPress **not used**. No live import. Public path grammar is **not** a later mapping layer.

```
Historical sne-* JSON
        ↓
AstroCats object model + schema + supernovae module
        ↓
webcat
        ↓
aggregates + per-event JSON/plots
        ↓
┌──────────────────────────────────────────────┐
│ Historical public namespace (native)         │
│  Transient Table  |  object router           │
│  /astrocats/.../output/**  |  OACAPI         │
└──────────────────────────────────────────────┘
```

**Not this:** build new catalog → later map old URLs onto it.

### Step 1 done means

- 72,145-object corpus + deep event JSON load under AstroCats expectations  
- `webcat` regenerates catalog/names/hosts/conflicts/dupes/biblio + event pages  
- Transient Table + secondary tables + object pages + downloads work  
- OACAPI works on the same tree  
- Deployed at original addresses; ~14.4k URL suite is the **verifier**

**Out of scope for Step 1:** post-2022 updates, brokers, MSystem, ontology redesign.

---

## 8. Engineering sequence (same architecture throughout)

Order of *building*, not separate products. Namespace rules apply from the first object route.

| Phase | Work | Exit |
| --- | --- | --- |
| **S1.0** | Staging host + disk | TLS staging |
| **S1.1** | Clone corpus + AstroCats + module + schema; pin env; run `webcat` | Aggregates + event outputs regenerate |
| **S1.2** | Serve output tree at `/astrocats/.../output/`; Transient Table on `/` | Catalog UX works |
| **S1.3** | Object router with **native** `event.php` rules at `/sne/` and `/event/` | Naming/alias behavior correct |
| **S1.4** | OACAPI on `api.sne.space` | Documented API routes work |
| **S1.5** | Rewrite thin IA pages at historical slugs | `/about/`, `/download/`, … |
| **S1.6** | Run ~14.4k URL + API proof suite | **§1.4 met** |
| **S1.7** | Production DNS | Historical OSC live again |

**Step 1 rights:** public GitHub OSC corpus + derived webcat artifacts. Live-ingest legal matrix (§14.2) is Step 2.

### Step 2 — after S1.6

Diligence §§14–15 → live feeds → MSystem (only after we understand OSC’s representation from Step 1) → brokers per interviews.

---

## 9. Verification

| Layer | What we verify |
| --- | --- |
| **Core (primary)** | `webcat` outputs match expected structure; catalog/UI/API scientific behavior |
| **Namespace proof** | Cleaned ~14.4k crawl URLs + OACAPI examples |
| **Resolver unit tests** | SN prepend, aliases, SN↔AT, encoding (from `event.php`) |

The URL suite does **not** define the architecture; it proves the public namespace was implemented with the catalog system.

Gold-set / MSystem tests = Step 2.

---

## 10. Risks

| Risk | Mitigation |
| --- | --- |
| Full HTML generation time/disk | Catalog first; HTML prioritized by backlink value (§14.5) |
| No WP database | Rewrite pages at same slugs; do not assume Wayback = license |
| Stale catalog (pushes ~2022–2023) | Phase −1 source audit *before* new ingest architecture |
| Incomplete local backlink list | Paid/crawl census before regenerating all ~9k HTML |
| Levenshtein false positives | Match original threshold (&lt;4) and warning UX |
| Data-rights overreach | Per-source matrix (§14.2); never treat MIT code license as data license |
| Beautiful wrong ontology | Gold set (§14.3) before MSystem |
| Rebuild for 2018 workflows | Researcher interviews (§14.7) |

---

## 11. Size / ops notes

| Item | Scale |
| --- | --- |
| Year-repo GitHub size sum | ~12.3 GB (git size field) |
| `catalog.json` | ~53 MB / **72,145** events |
| Sample event `SN2011fe.json` | ~25 MB |
| `conflicts.json` | 1,674 conflict rows |
| `dupes.json` | 2,303 candidate pairs |
| Multi-`claimedtype` events | 3,562 (4.9%); ~525 cross-family conflicts |
| Archived unique URLs | ~14.4k |
| Event HTML pages | ~9k+ to regenerate |

---

## 12. Decision log

| Decision | Choice | Rationale |
| --- | --- | --- |
| Step 1 target | OSC scientific system **at original namespace** | One product, not catalog-then-URLs |
| Public path grammar | **Day-one spec** | Backlinks recover natively |
| ~14.4k URLs | **Proof suite**, not the work | Verifies namespace + system |
| Serve only `catalog.json`? | **No** — run AstroCats/`webcat` | Learn object→aggregate transform before MSystem |
| Re-run historical import? | **No** for Step 1 | Dataset already exists |
| WordPress | **Not used** | Shell only |
| Live feeds / MSystem | **Step 2** | After we understand OSC representation |
| §§14–15 | Step 2 diligence | Not Step 1 gate |

---

## 13. Immediate next actions (Step 1)

1. Clone `sne-*` + `astrocats` + `supernovae` + schema; pin Python env.  
2. Run `webcat` — prove aggregates + event outputs regenerate.  
3. Serve that tree at `/astrocats/.../output/` with Transient Table on `/` and **native** `/sne/` routing.  
4. Stand up OACAPI on the same volume.  
5. Green scientific checks + ~14.4k URL proof suite → DNS.

Step 2 diligence (§§14–15) starts after S1.6.

---

## 14. Phase −1 diligence (Step 2 — after historical parity)

> **Scope note:** §§14–15 do **not** gate Step 1. Step 1 serves the already-public GitHub OSC corpus. This diligence turns “old OSC restored” into “credible OSC 2.0 we can operate for years.”

### 14.1 Source-by-source 2026 viability matrix

**Inventory:** `input/tasks.json` in [`astrocatalogs/supernovae`](https://github.com/astrocatalogs/supernovae) contains **67 tasks** (metadata, photometry, spectra, models, cleanup). Last catalog data pushes: year repos **2022-04-11**; module commits through **2023-03**. Staleness is real — do not design new ingestion around “it still works” assumptions.

**Endpoint probe (2026-09-23):** TNS, WISeREP, SIMBAD, VizieR, ASAS-SN, Gaia Alerts, CRTS, Rochester Latest SN, NED, MAST, ALeRCE, Fink, ZTF all returned HTTP 200. Liveness ≠ permission ≠ importer compatibility.

#### Tier summary (research status)

| Tier | Meaning | Example tasks | 2026 notes |
| --- | --- | --- | --- |
| **A — Live, API-capable** | Official API / service; rebuild ingest here first | `tns`, `tns_photo`, `tns_spectra`, `wiserep2_spectra`, `simbad`, `vizier`, `nedd`, `mast_spectra`, `swift`, `hst` | TNS requires **bot + api_key + `tns_marker` User-Agent** and **60s rolling rate limits** (429 + `x-rate-limit-*`); cone searches tighter. WISeREP v2 has bulk APIs + public vs proprietary split ([getting started](https://www.wiserep.org/content/wiserep-getting-started)). SIMBAD: free under ODbL-style use with citation. VizieR: scientific use OK with citation; commercial rules per catalogue. |
| **B — Live site, scrape/legacy** | Site up; old OSC scraper likely brittle | `asassn`, `gaia`, `rochester`, `crts`, `ogle`, `ptf`, `des`, `psalerts` / `psthreepi` / `psmds`, `snhunt`, `cpcs`, `fermi`, `smt` | Expect URL/HTML drift since 2018–2022 importers. Prefer official APIs (e.g. ASAS-SN transcients portal) over resurrecting scrapers. CRTS/legacy surveys: historical freeze may be enough. |
| **C — Archived / static dumps** | One-shot catalogues in `sne-external*` | `pessto-dr1`, `csp_*`, `cfa_*`, `sdss_photo`, `snls_*`, `essence_*`, `suspect_*`, `ascii`, `sousa`, `lennarz`, `batse`, many `*_spectra` | Still valuable for **historical depth**. Marked `archived: true` in tasks: `cccp`, `ptss`, `grb`, `asasatels`, `snf`, `wiserep_spectra` (v1). |
| **D — Community / derived** | User/GitHub driven | `internal`, `donated_photo`, `donated_spectra`, `mosfit`, `sncosmo` (inactive), `merge_duplicates` (inactive), `cleanup` | Keep as contribution path; not a live survey feed. |
| **E — Replace for 2026** | Not in original tasks but now essential | ZTF alert brokers, **Fink**, **ALeRCE**, Rubin/LSST precursors, Astro-COLIBRI, etc. | Interviews (§14.7) will rank these. Old OSC never ingested modern broker streams as first-class citizens. |

#### Per-task worksheet columns (complete in a living spreadsheet)

For every task name in `tasks.json`, fill:

`task | active | archived | access (API/scrape/static) | auth | update cadence | schema stability | rate limits | old importer works? (Y/N/unknown) | replacement | rights row ID`

**Provisional feed-liveness estimate (not yet importer-validated):** roughly **~25–35%** of tasks map to Tier A services that can be made live with credentials; **~30–40%** are static/historical dumps that remain useful offline; **~20–30%** are scrapers needing rewrite or retirement; **~10%** process/merge only. **Hard number for “% of feeds live again” requires running each importer or rewriting it** — that is a Phase −1 deliverable, not a guess to freeze yet.

References: [TNS getting started / rate limits](https://www.wis-tns.org/content/tns-getting-started), [TNS API manual PDF](https://www.wis-tns.org/sites/default/files/api/tns2_manuals/TNS2.0_APIs_manual.pdf), [WISeREP](https://www.wiserep.org/), [VizieR usage rules](https://cds.u-strasbg.fr/vizier-org/licences_vizier.html).

---

### 14.2 Data-rights / redistribution matrix

**Principle:** MIT on AstroCats/`supernovae` covers **software**, not automatically every ingested photometric point or spectrum. OSC’s own schema requires per-datum `sources[]` with optional `acknowledgment` — that exists because redistribution is ethically and often legally source-specific.

| Source / class | Ingest for internal index? | Cache locally? | Redistribute metadata? | Redistribute raw files? | Attribution | Commercial-use posture |
| --- | --- | --- | --- | --- | --- | --- |
| **OSC JSON already on GitHub (MIT repos)** | Yes | Yes | **Yes** (already public under project norms + MIT packaging) | Yes (as published in year repos) | Cite Guillochon+2017 + per-event `sources` | Generally OK for serving the open catalog; still respect embedded `acknowledgment` strings |
| **WISeREP public spectra** | Yes (with account/API) | Yes (public only) | Metadata: yes with citation | Raw public spectra: **download allowed for research**; re-hosting entire archive needs **explicit policy check / permission** | Cite [2012PASP..124..668Y](https://ui.adsabs.harvard.edu/abs/2012PASP..124..668Y) + acknowledge wiserep.org | Proprietary/group data: **do not ingest or redistribute** |
| **WISeREP proprietary / group** | No (unless we join groups) | No | No | No | N/A | Forbidden |
| **TNS** | Yes via bot APIs | Yes (respect rate limits) | Object metadata commonly reused with credit | Files via Get-file API: follow TNS terms; don’t hammer | Credit TNS / reporters | Bot credentials required; quotas apply |
| **SIMBAD** | Yes | Yes (reasonable volume) | Derived cross-IDs OK with acknowledgment | N/A (meta DB) | Wenger et al. 2000; CDS acknowledgment | Free service; not a dump-everything CDN |
| **VizieR catalogues** | Yes | Yes | Scientific redistribution with **author/publisher citation** | Associated files: per catalogue ReadMe | Catalogue authors + VizieR DOI 10.26093/cds/vizier | **Commercial use restricted / per-origin** — CDS rules |
| **Published paper tables (ADS/journals)** | Yes if already machine-readable in OSC | Yes | Cite paper | Raw: journal/publisher policy | Bibcode/DOI | Often non-commercial scientific norms |
| **Survey portals (ASAS-SN, Gaia Alerts, ZTF, …)** | Case-by-case | Case-by-case | Usually OK for metadata with credit | Light curves/spectra: **check each ToS** | Survey papers + portal | Many allow science use; mirroring full survey may be disallowed |
| **NED / NED-D** | Yes | Yes | With NED acknowledgment | N/A | NED citation rules | Scientific use |
| **MAST / HST / Swift archives** | Yes via APIs | Yes | Metadata OK | Data products: mission archive licenses (often open for science) | Mission acknowledgments | Usually non-issue for science portal; confirm bulk rehost |
| **User donations (`sne-internal`)** | Yes | Yes | Per contributor terms | Per contributor | Contributor + sources | Need contribution license checkbox going forward |
| **Hugging Face OSC remix** | N/A (downstream) | N/A | Shows demand for shallow table | Does **not** grant us rights; we are upstream | Their dataset cites OSC | Competitive signal only |

**Action:** Produce a counsel-reviewed spreadsheet with a row per Tier A/B source before enabling live mirrors of raw spectra/photometry. Safe launch posture: **serve the already-public GitHub OSC corpus + generate HTML/API from it**, while new WISeREP/TNS pulls start in **metadata-first** mode until letters of permission return.

---

### 14.3 Gold set (100–500 objects) before MSystem / ontology

**Why:** Burhanudin & Maund (MNRAS 2023) pulled OSC light curves, **discarded conflicting spectroscopic labels**, and still had to standardize heterogeneous instruments/filters — direct evidence that naive schema mapping fails scientifically ([doi:10.1093/mnras/stac3672](https://doi.org/10.1093/mnras/stac3672); [arXiv:2208.01328](https://arxiv.org/abs/2208.01328)). Habergham-related work also found OSC/TNS classification disagreements for IIn samples.

**Corpus hooks for sampling:**

| Bucket | Source of nastiness | Approx. pool |
| --- | --- | --- |
| Quantity conflicts | `conflicts.json` | 1,674 rows |
| Likely duplicates | `dupes.json` | 2,303 pairs |
| Multi-type | catalog `claimedtype` length &gt; 1 | 3,562 |
| Cross-family type clash | heuristic on type prefixes | ~525 |
| Multi-redshift | multiple `redshift` entries | 4,265 |
| Alias-rich | ≥5 aliases | 886 |
| Spectra-rich | `spectralink` present | 10,479 |
| Photo-rich / deep file | e.g. SN2011fe ~25 MB, 3483 phot points | hand-pick |
| Historical | pre-1990 / SN1572A, SN1987A, … | year repo |
| Weird names | spaces, `+`, survey IDs | sitemap / backlinks |

**Seed list (expand to ≥100 with astronomer review; target 250–400 for ontology lock):**

| Object | Why it’s in the gold set |
| --- | --- |
| SN2011fe | Extremely rich photometry/spectra; many instruments/systems (Vega/AB) |
| SN1987A | Historical + modern; host/distance complexity |
| SN1993J / SN1994D / SN1998bw | Classic typed benchmarks; wiki-linked |
| SN2007bi / SN2015bn / iPTF14hls | SLSN / odd LC; classification debates |
| SN2009ip / SN2010jl | IIn / impostor boundary |
| AT2018cow / AT2018pw | Modern AT names; fast/exotic |
| SN2014J | Nearby Ia; extinction/host mess |
| SN2006gy | Interaction / luminous |
| PTF10hgi / Gaia16apd | Multi-survey alias stacks |
| CSS/PSN names with spaces | Filename + URL encoding edge cases |
| Objects appearing in `conflicts.json` for `redshift` and `claimedtype` | Proven multi-valued fields |
| Random stratified sample of Candidates vs Ia vs II | Avoid over-fitting famous SNe |

**Protocol:** For each gold object, a competent transient astronomer records: canonical name, accepted aliases, preferred type(s) with provenance, preferred z/host, whether conflicting values should be retained as a *set* vs suppressed, and filter/time-system notes. **No MSystem mapping ships until ≥100 objects are signed off.**

---

### 14.4 Exact semantic inventory of the old corpus

#### Catalog-level (`catalog.json`, n = 72,145)

| Field | Coverage |
| --- | --- |
| `name`, `alias` | ~100% |
| `ra`, `dec` | 94.8% |
| `discoverdate` | 93.7% |
| `photolink` | 85.9% |
| `maxappmag` / `maxdate` | ~83% |
| `claimedtype` | 79.2% (top value: **Candidate** 31,623) |
| `discoverer` | 75.2% |
| `references` | 69.0% |
| `instruments` | 53.5% |
| `ebv` | 51.5% |
| `redshift` / `velocity` / `lumdist` | ~40% |
| `host*` family | 15–28% |
| `spectralink` | 14.5% |
| `radiolink` / `xraylink` | ≪1% |

**144 distinct `claimed_type` strings** appear in the HF remix of this same catalog — taxonomy is already messy.

#### Event-file quantities (union from SN2011fe + SN1987A samples)

`alias`, `claimedtype`, `ra`, `dec`, `discoverdate`, `discoverer`, `ebv`, `host*`, `lumdist`, `comovingdist`, `max*`, `photometry`, `spectra`, `sources`, `redshift`, `velocity`, `explosiondate`, `errors`, `schema`, …

#### Photometry attributes (observed in sample)

`time`, `u_time` (**MJD** in sample), `band`, `magnitude`, `e_magnitude`, `e_upper_magnitude`, `e_lower_magnitude`, `telescope`, `instrument`, `system` (**Vega / AB / SDSS**), `bandset`, `source`, `upperlimit`, `upperlimitsigma`, `zeropoint`, `countrate` / fluxes / `fluxdensity` / `frequency`, X-ray-ish `photonindex`, `nhmw`, `unabsorbedflux`, …

#### Spectra attributes (observed)

`time`, `u_time`, `filename`, `data`, `u_wavelengths`, `u_fluxes`, `u_errors`, `instrument`, `telescope`, `observatory`, `observer`, `reducer`, `reduction`, `redshift`, `survey`, `snr`, `source`

#### Provenance

`sources[]` with `name`, `alias`, `bibcode`, `reference`, `url`, `secondary`, plus schema’s `doi` / `arxivid` / `acknowledgment` fields.

**Still required for a complete census:** a Spark/job over all year-repo JSON files counting every nested key, unit string, band, instrument, and reference frame — catalog.json alone **omits** deep photometry/spectra keys. Treat the above as the **minimum ontology surface**; full census is a Phase −1 compute ticket (~12 GB git corpus).

Reference schema: [astrocatalogs/schema](https://github.com/astrocatalogs/schema).

---

### 14.5 Surviving value of the old URL graph + competitive signal

**What we have today**

| Dataset | What it measures | Limitation |
| --- | --- | --- |
| Crawl unique URLs | ~14.4k historical paths | Not “links to us” |
| `sne_space_backlinks.csv` | Wiki + CC domain-graph sample | **Not** 15k inbound |
| Wayback API CDX | `api.sne.space` used through ≥2023 | Endpoint popularity unknown |

**Before regenerating all ~9k Bokeh HTML pages for SEO**, run:

1. Ahrefs / Majestic / Site Explorer for `sne.space` + `api.sne.space`  
2. Expand Common Crawl domain graph to **page-level** backlinks  
3. Wikipedia/Wikidata exturlusage dump (partially started)  
4. GitHub code search for `sne.space`, `api.sne.space`, `astrocats.space`  
5. ADS/fulltext mentions of sne.space  

**Prioritize HTML generation for:** Wikipedia-linked events, top referring domains, API-famous objects (SN2014J, SN2011fe, …), then long tail.

#### Competitive evidence — Hugging Face remix

[`juliensimon/open-supernova-catalog`](https://huggingface.co/datasets/juliensimon/open-supernova-catalog): **72,145 rows**, ~metadata columns (name, RA/Dec, z, type, host, peak mag, …), **not** deep photometry/spectra/provenance. Same row count as GitHub `catalog.json`. This proves:

- Demand for convenient OSC-shaped tables still exists in 2026  
- **Shallow metadata is already commoditized**  
- Differentiation must be **deep observations + provenance + live integration + reasoning** — exactly the gap HF does not fill

#### ML validation of semantic pain

Burhanudin & Maund (2023) used OSC through 2019 (~80k listed), dropped non-SN and **conflicting labels**, and engineered GP-uniform light curves across surveys — confirming both label conflict and photometric heterogeneity as first-class product problems.

---

### 14.6 Rights to old editorial / site content

| Asset | Likely rights holder | Recommendation |
| --- | --- | --- |
| AstroCats / OSC **code** | MIT (`supernovae`, `astrocats`, `OACAPI`) | Reuse freely with license notice |
| OSC **event JSON** on GitHub | Project + embedded source attributions | Reuse; keep `sources` / acknowledgments |
| **Website prose** (About, Contribute text) | Authors (Guillochon, Parrent, et al.) — **not transferred by buying expired domain** | Prefer **rewrite**; or obtain written permission |
| **Logo / banner imagery** | Unknown / photographers / theme | Replace or clear rights |
| **Parabola WP theme** | GPL (Cryout Creations) | OK if we used WP; irrelevant if we don’t |
| **Child theme / Transient Table** | No GitHub license file found | Treat as needs clarification before verbatim ship |
| Wayback HTML as source for copy-paste | Archive ≠ license grant | Use as **reference for structure**, not as copyright shield |
| Third-party images (host DSS thumbs, etc.) | Survey/archive terms | Prefer regenerate or link out |

**Policy for Phase 5:** keep **URLs**; ship **new** informational copy; retain scientific citation to Guillochon+2017; contact authors for blessing / optional text donation.

---

### 14.7 Researcher workflow interviews (protocol)

**Goal:** Discover where 2026 time is lost — not whether people “like OSC.”

**n = 10–15** transient astronomers spanning: SN Ia cosmology, CC SNe, SLSNe/TDEs, brokers (Fink/ALeRCE), WISeREP/TNS power users, observers doing night-level follow-up.

**Scenario script (watch screen if possible):**

1. *Build a cohort* of SNe Ia with z &lt; 0.05 and public spectra since 2018.  
2. *Investigate one event* tonight (give a fresh AT name): decide spectrograph trigger.  
3. *Reconcile* two conflicting types + three redshifts for a named object.  
4. *Export* photometry in a homogeneous filter set for ML.  

**Capture:** tools opened (TNS, WISeREP, Fritz/SkyPortal, TOM Toolkit, YSE, Fink, ALeRCE, NED, SIMBAD, local scripts), copy-paste steps, trust breaks, “I wish X existed.”

**Success metric:** ranked list of workflows where a restored+extended sne.space saves ≥10 minutes or reduces error — those become OSC 2.0 P0 features.

---

## 15. Four critical questions (provisional answers)

> **What percentage of old OSC can we restore exactly?**  
> **~90–100% of the GitHub-published corpus** (catalog + year JSON + regenerable HTML/API) is technically restorable. **Exact bit-for-bit HTML** depends on `webcat`/dependency versions — expect visual/plot parity, not guaranteed byte identity. **Informational WP pages:** restore URLs, not necessarily exact prose (§14.6).

> **What percentage of its feeds can we make live again?**  
> **Unknown until importers are run.** Plausible band: **~25–40%** of `tasks.json` entries have a live Tier-A service path (TNS, WISeREP v2, CDS, MAST, …); another **~30–40%** remain valuable as **static historical** inputs; the rest need rewrite or retirement. Modern value may come more from **new** broker feeds than from resurrecting every 2016 scraper.

> **What data can we legally redistribute?**  
> **Safe now:** MIT-licensed repos’ published JSON + derived catalog/API/HTML with full `sources` provenance. **Conditional:** WISeREP **public** data (cite; confirm bulk rehost), TNS metadata (bot ToS), VizieR (scientific + per-catalogue; commercial caution), survey portals case-by-case. **Forbidden without agreement:** WISeREP proprietary, uncleared journal supplements, uncleared WP editorial/branding. Counsel sign-off required before marketing “we mirror everything.”

> **What new thing will make researchers choose sne.space in 2026?**  
> Not another 72k-row metadata CSV (already on Hugging Face). Differentiator: **conflict-aware provenance** (keep disagreements visible), **normalized photometry/spectra across instruments**, **live TNS/WISeREP/broker integration**, and a **reasoning/cohort layer** grounded in the gold set — solving the exact pains documented by Burhanudin & Maund and by OSC’s own `conflicts.json` / `dupes.json`.

**Go/no-go:**

- **Step 1:** Proceed now on GitHub corpus + webcat + public contract. Gate = §1.3 URL/API suite.  
- **Step 2:** Proceed only if Phase −1 shows Tier-A feeds + clear redistribution for *new* mirrors + interview demand for deep+live features. If rights block raw rehosting of new pulls, still run Step 1; keep Step 2 metadata-first.

---

## Appendix A — Key source references

- OSC paper: https://arxiv.org/abs/1605.01054  
- OACAPI note: https://arxiv.org/abs/1804.10847  
- Org: https://github.com/astrocatalogs  
- Schema: https://github.com/astrocatalogs/schema  
- Archived homepage (example): https://web.archive.org/web/20211025203525/https://sne.space/  
- WISeREP: https://www.wiserep.org/ · Getting started: https://www.wiserep.org/content/wiserep-getting-started  
- TNS: https://www.wis-tns.org/ · FAQ/getting started: https://www.wis-tns.org/content/tns-getting-started  
- VizieR usage: https://cds.u-strasbg.fr/vizier-org/licences_vizier.html  
- HF remix: https://huggingface.co/datasets/juliensimon/open-supernova-catalog  
- Burhanudin & Maund 2023: https://doi.org/10.1093/mnras/stac3672 · https://arxiv.org/abs/2208.01328  

## Appendix B — Local inputs used for this report

- `sne_space_backlinks.csv` — sample inbound links  
- `sne_space_crawled_pages.csv` / `_unique.csv` — Wayback/CC URL inventory  
- Live DNS check (Sav parking)  
- GitHub API inspection of `astrocatalogs/*`  
- Source review of `transient-table.php`, `event.php`, `OACAPI/api.py`, `webcat.py`  
- Full `catalog.json` field-frequency census (72,145 rows)  
- Deep attribute samples: `SN2011fe.json`, `SN1987A.json`  
- `conflicts.json` (1,674), `dupes.json` (2,303)  
- HTTP probes of major 2026 astronomy endpoints  

---

*End of report.*
