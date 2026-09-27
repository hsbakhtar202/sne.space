# sne.space Master Strategic Plan & Technical Roadmap

> **Objective:** Restore and elevate `sne.space` (The Open Supernova Catalog) from a resurrected historical archive into the definitive, modern, AI-native platform for transient astrophysics and space science (1000 AD through 2026+).

---

## Executive Summary: How We Beat the Modern Landscape

When the original Open Supernova Catalog went offline around 2021, transient astronomy fragmented into siloed systems:

- **TNS (IAU):** The official registry, but has an archaic UI, strict API hurdles, and no unified multi-band light curves or calibrated spectra.
- **Alert Brokers (ALeRCE, Fink, Lasair):** Provide real-time alert streams, but only cover post-2018 alerts (zero historical depth), isolate data to their own survey streams, and have complex, developer-unfriendly query layers.
- **WISeREP:** Maintains spectra, but zero multi-color light curves, zero discovery tracking, and archaic tables.

**`sne.space` has the unique competitive moat:**

1. **Unrivaled Temporal & Scientific Scope:** 110,222+ events spanning 1,000+ years of human astronomy, unified under one standard schema.
2. **True Data Synthesis:** We merge discovery circulars, ZTF/ATLAS broker alerts, space telescopes (Swift, HST, JWST), ground spectra, and published literature into one living file per event.
3. **Dual Audience Mastery:** We bridge the gap between hard-core astrophysicists (raw data, FITS, MJD, $\Lambda\text{CDM}$ cosmology, ADS bibcodes) and the consumer/amateur space community (plain-English field guides, light-year distances, backyard telescope visibility, before/after discovery photos).
4. **Frictionless Developer & Astronomer Access:** Zero-token REST APIs, instant CSV exports, OACAPI legacy compatibility, and AI-native MCP tooling.

---

## 1. Target Audiences & The Dual-Experience Architecture

A fundamental failure of modern astronomical databases is designing solely for one audience. `sne.space` serves two distinct groups with different needs and intents:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           sne.space Event Architecture                          │
│                     Canonical Entity: /sne/{event}/                             │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────────────┐
│        🔭 PRO / ASTRONOMER COCKPIT    │  │       📖 STORY / OBSERVER DOSSIER    │
│        URL: /sne/{event}/            │  │       URL: /sne/{event}/story        │
├──────────────────────────────────────┤  ├──────────────────────────────────────┤
│ • Heliocentric & CMB velocities (v)  │  │ • Plain-English explosion narrative  │
│ • Cosmological dist modulus (μ) & d_L│  │ • Distance in Light-Years & Lookback │
│ • Multi-epoch calibrated spectra     │  │ • "Can I see it tonight?" guide      │
│ • Full multi-band MJD light curves   │  │ • Required backyard telescope size   │
│ • NASA ADS bibcodes & LaTeX BibTeX   │  │ • Before/After discovery blink slider│
│ • IVOA VOTable, AstroCats JSON, CSV  │  │ • Constellation & sky finding chart  │
│ • Schema.org: "Dataset" (Google DS)  │  │ • Schema.org: "Article" (Discover)   │
└──────────────────────────────────────┘  └──────────────────────────────────────┘
```

### 1.1. The Professional Astronomer (5% of users, 100% of academic authority)
- **Goal:** Rapid data retrieval for research papers, telescope proposals, and code pipelines (`astropy`, `sncosmo`).
- **Needs:** Uncompressed AstroCats JSON, MJD time bases, rest-frame wavelengths, filter transmission curves, photometric uncertainties, and Harvard ADS literature links.
- **Delivered via:** `/sne/{event}/` (Canonical Pro Cockpit).

### 1.2. The Amateur, Astrophotographer & Curious Public (95% of web traffic)
- **Goal:** Learn what exploded, how far away it is, what star caused it, and whether they can photograph or observe it with binoculars or a backyard telescope.
- **Needs:** Plain-English story, distance in millions of light-years, constellation locator, before/after blink photos, and clear telescope aperture requirements.
- **Delivered via:** `/sne/{event}/story` (Companion Observer Dossier).

---

## 2. UI Layout & Visual Experience (Modern Cockpit vs. Story View)

The historical site used heavy, static Bokeh 0.11 iframes that frequently broke and were hostile to mobile devices. We will replace them with modern, client-side, hardware-accelerated interactive components featuring an instant toggle between **Pro Mode** and **Story Mode**.

### 2.1. Pro Cockpit Layout (`/sne/{event}/`)

```
+---------------------------------------------------------------------------------------------------+
|  [sne.space logo]  Open Supernova Catalog       [Search 110,000+ transients...]       [Downloads] |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  SN 2024nrb                                   [ Type Ia-norm ]   [ Discovered: 2024-09-12 by ATLAS]
|  Aliases: AT 2024nrb, ZTF24abcqato, ATLAS24kdf, GOTO24drx                                         |
|                                                                                                   |
|  [⚡ Re-Enrich]  [📥 Download JSON]  [📊 Photometry CSV]  [📋 Copy BibTeX]  [📖 Switch to Story Mode] |
|---------------------------------------------------------------------------------------------------|
|                                                   |                                               |
|  LEFT COLUMN: Astrophysical Context & Imagery     | RIGHT COLUMN: Interactive WebGL Visualizers   |
|                                                   |                                               |
|  ┌─ Host Galaxy Deep Optical Cutout ────────────┐ | ┌─ Interactive Multi-Band Light Curve ──────┐ |
|  │                                              │ | │  [All] [g] [r] [i] [z]   [MJD | Rest-Day] │ |
|  │   [DESI Legacy Survey DR10 Optical Cutout]   │ | │  Mag                                      │ |
|  │   Reticle crosshair on transient (α, δ)      │ | │  14 |         * g-band detection          │ |
|  │   0.26 arcsec/pix - Host: NGC 3489           │ | │  16 |        * *   *  r-band              │ |
|  │   [Toggle: Legacy DR10 / DSS2 / Pan-STARRS1] │ | │  18 |       *   *    *                    │ |
|  └──────────────────────────────────────────────┘ | │  20 |     v   v        v (upper limits)   │ |
|                                                   | │     +---------------------------------    │ |
|  ┌─ Core Astrophysical Parameters ──────────────┐ | │     0     20    40    60    80 (Days)      │ |
|  │ • Coordinates:  11h 00m 36.8s, +12°34'02.1"  │ | └───────────────────────────────────────────┘ |
|  │ • Redshift (z): 0.0339 (spectroscopic)       │ |                                               |
|  │ • Rec. Velocity: 10,012 km/s (relativistic)  │ | ┌─ Stacked Interactive Spectra Viewer ──────┐ |
|  │ • Lum. Distance: 153.8 Mpc (μ = 35.93 mag)   │ | │  [Normalize] [De-redshift z] [Smooth]     │ |
|  │ • Milky Way E(B-V): 0.031 mag (SF11 Dust)    │ | │  Flux                                     │ |
|  │ • Host Galaxy:  NGC 3489                     │ | │   |           Si II λ6355                 │ |
|  │ • Host Offset:  14.2 arcsec (4.4 kpc)        │ | │   |     /\        |                       │ |
|  │ • Peak App. Mag: 13.82 mag (r-band)          │ | │   |____/  \______/ \________ Epoch +3     │ |
|  │ • Peak Abs. Mag: -19.12 mag                  │ | │   +---------------------------------      │ |
|  └──────────────────────────────────────────────┘ | │   4000     5000     6000     7000 (Å)     │ |
|                                                   | └───────────────────────────────────────────┘ |
|  ┌─ Tonight's Sky & Air Mass Planner ───────────┐ |                                               |
|  │  Observatory: [ Keck ▼ ]  Air Mass: X(t)     │ | ┌─ Research Literature & Data Sources ──────┐ |
|  │  Peak: 02:15 UTC (X=1.12) | Moon: 78° away   │ | │  [1] Tonry et al. (2024) [2024TNSTR2222]  │ |
|  └──────────────────────────────────────────────┘ | │  [2] ePESSTO+ Spectra [2015A&A...579A..40I]│ |
|                                                   | └───────────────────────────────────────────┘ |
+---------------------------------------------------------------------------------------------------+
```

### 2.2. Story / Magazine Mode Layout (`/sne/{event}/story`)

```
+---------------------------------------------------------------------------------------------------+
|  [sne.space logo]  Open Supernova Catalog       [Search 110,000+ transients...]       [Downloads] |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  SN 2024nrb: A Thermonuclear Explosion 500 Million Light-Years Away                               |
|  Discovered on September 12, 2024 in the Constellation Leo | [🔭 Switch to Pro Astronomer Cockpit] |
|                                                                                                   |
|---------------------------------------------------------------------------------------------------|
|                                                                                                   |
|  ┌─ Discovery Blink Comparison (Before vs. After) ──────────────────────────────────────────────┐ |
|  │                                                                                              │ |
|  │   [ PRE-EXPLOSION BASELINE ]          ◄───[ SLIDER ]───►          [ DISCOVERY SCIENCE IMAGE ]│ |
|  │   Quiet host galaxy NGC 3489                                      Blazing white point source │ |
|  │                                                                                              │ |
|  └──────────────────────────────────────────────────────────────────────────────────────────────┘ |
|                                                                                                   |
|  ┌─ Quick Facts Card (Plain English) ───────────────────────────────────────────────────────────┐ |
|  │ • What happened: A carbon-oxygen white dwarf exceeded critical mass and detonated completely. │ |
|  │ • Distance: 501 Million Light-Years (Light left when complex multi-cellular life arose).     │ |
|  │ • Peak Brightness: Magnitude 13.8 (Visible with an 8-inch backyard telescope under dark sky).│ |
|  │ • Location: In constellation Leo, 14,000 light-years from the center of galaxy NGC 3489.     │ |
|  │ • Classification: Type Ia Supernova (The cosmic "Standard Candle" used to measure dark energy).│
|  └──────────────────────────────────────────────────────────────────────────────────────────────┘ |
|                                                                                                   |
|  ┌─ The Plain-English Narrative ────────────────────────────────────────────────────────────────┐ |
|  │ On September 12, 2024, the ATLAS survey telescope in Hawaii flagged a sudden brightening in  │ |
|  │ the outskirts of the lenticular galaxy NGC 3489. Follow-up spectroscopy by the European      │ |
|  │ Southern Observatory's NTT telescope confirmed it as a classic Type Ia supernova...         │ |
|  └──────────────────────────────────────────────────────────────────────────────────────────────┘ |
|                                                                                                   |
|  ┌─ Backyard Observer Guide ("Can I See It Tonight?") ──────────────────────────────────────────┐ |
|  │ • Current Status: Fading (Now mag 19.2 — no longer visible in amateur equipment).            │ |
|  │ • Peak Window: September 15–28, 2024 (Best viewed with 200mm+ aperture).                     │ |
|  │ • Sky Coordinates: Right Ascension 04h 45m, Declination -16° 22'                            │ |
|  └──────────────────────────────────────────────────────────────────────────────────────────────┘ |
+---------------------------------------------------------------------------------------------------+
```

### 2.3. Interactive Multi-Band Light Curve Engine
- **Technology:** Fast WebGL/Canvas rendering (using Plotly.js or ECharts).
- **Features:**
  - **Band Filtering:** Multi-select interactive toggles for standard optical/NIR bands ($U, B, V, R, I, u, g, r, i, z, Y, J, H, K$) and survey-specific bands (ATLAS $c/o$, Gaia $G$).
  - **Upper Limits & Detections:** Distinct glyphs for detections ($\bullet$) with error bars vs. non-detection upper limits ($\triangledown$).
  - **Dual Time Bases:** Toggle between:
    - **Observer Frame:** Time in MJD or Calendar Date (UTC).
    - **Rest Frame:** Days from Maximum brightness: $\Delta t_{\text{rest}} = (t - t_{\max}) / (1 + z)$.
  - **Dual Magnitude Modes:**
    - **Apparent Magnitude ($m$):** Directly observed brightness.
    - **Absolute Magnitude ($M_{\text{abs}}$):** Distance- and extinction-corrected intrinsic luminosity:
      $$M = m - 5\left(\log_{10}(d_L) + 5\right) + 2.5\log_{10}(1 + z) - A_V$$
  - **Interactive Hover Cards:** Point inspection displaying exact MJD, magnitude, uncertainty, filter, telescope/instrument, and source bibcode.

### 2.4. Stacked Interactive Spectra Viewer
- **Technology:** Responsive SVG/Canvas spectral visualizer.
- **Features:**
  - **Epoch Stacking:** Vertical stacking of multi-epoch spectra to visualize spectral evolution over time.
  - **Rest-Frame De-redshifting:** Instant toggle to shift wavelength $\lambda_{\text{obs}} \to \lambda_{\text{rest}} = \lambda_{\text{obs}} / (1 + z)$.
  - **Interactive Smoothing & Binning:** Real-time Savitzky-Golay or Gaussian kernel slider to filter noise on low-SNR spectra.
  - **Atomic Feature Identification Overlays:** One-click toggle to highlight benchmark supernova absorption/emission lines:
    - **Type Ia:** Si II $\lambda 6355$, Ca II H&K, S II "W" feature.
    - **Type II:** Balmer lines ($\text{H}\alpha\ \lambda 6563$, $\text{H}\beta\ \lambda 4861$).
    - **Type Ib/Ic:** He I $\lambda 5876$, O I $\lambda 7774$.

### 2.5. Astronomical Observing Planning Widget (Tonight's Sky)
- **Target Air Mass & Elevation Plot:** Astronomers plan observations in the afternoon. Given an observatory location (Keck, VLT, Palomar, La Silla, or user GPS), plot target airmass $X(t)$ and visibility through the coming night.
- **Lunar Separation & Phase:** Real-time Moon angle and illumination percentage to check for sky brightness interference.

### 2.6. One-Click Publication & Scientific Export Toolbar
- **Publication-Ready Figures:** Download high-resolution vector SVG or 300 DPI PDF light curves and spectra formatted for academic journals (*ApJ*, *MNRAS*, *A&A*).
- **BibTeX Exporter:** Instant `[ Copy BibTeX ]` button aggregating all primary references for the specific event.
- **Direct Data Downloads:** Direct buttons for AstroCats JSON, Photometry CSV, and Spectra ASCII.

---

## 3. Photos, Optical Cutouts & Deep Imagery Pipeline

Astronomers require imagery to locate the host galaxy, verify transient morphology, and confirm coordinates.

### 3.1. Dual-Layer Pre-Explosion Deep Field Cutouts
Every event page will embed a high-resolution optical cutout centered on the transient's coordinates $(\alpha, \delta)$:
1. **Primary Layer: DESI Legacy Imaging Surveys (DR10)**
   - Ultra-deep, high-resolution optical imaging ($g, r, z$ composites) covering $>20,000\deg^2$ of the extragalactic sky.
   - Cutout API:
     `https://www.legacysurvey.org/viewer/cutout.jpg?ra={ra_deg}&dec={dec_deg}&layer=ls-dr10&pixscale=0.262&size=300`
2. **Fallback Layer: NASA SkyView (Digitized Sky Survey - DSS2 Color)**
   - Universal all-sky fail-safe ensuring no supernova in our database ever has a broken image.
   - Cutout API:
     `https://skyview.gsfc.nasa.gov/cgi-bin/images?survey=DSS2+Color&position={ra_str},{dec_str}&pixels=300&size=0.1&return=jpeg`

### 3.2. The "Blink Comparison" (Discovery Before/After Slider)
- Interactive side-by-side or drag-slider comparing the quiescent host galaxy baseline against the science/difference image during peak explosion.
- For modern events (2018–2026+), pull discovery science and template stamps directly from ALeRCE and Fink alert APIs.

### 3.3. Interactive Multi-Wavelength Sky Map (Aladin Lite)
- Embed **Aladin Lite v3 (WebGL)** directly on the event page.
- Allows astronomers to seamlessly pan, zoom, and toggle between:
  - Optical (Legacy Survey, Pan-STARRS1, SDSS, DSS2).
  - Infrared (2MASS, WISE).
  - Ultraviolet (GALEX).
- Permanent reticle/crosshair pinpointing the exact transient coordinates with precision astrometric error circles.

### 3.4. Space Telescope Deep Galleries (Hubble, JWST, APOD)
- For benchmark historical and near-universe events (`SN 1987A`, `SN 1993J`, `SN 2011fe`, `SN 2023ixf`, `SN 2024ggi`), surface curated high-resolution imagery from the **NASA MAST archive** and **NASA APOD**.

### 3.5. Host Galaxy Morphology & Offset Visualizer
- Visual vector diagram plotting the host galaxy nucleus $(\alpha_h, \delta_h)$ and the transient position, displaying physical offset in both angular separation (arcseconds) and projected kiloparsecs ($\text{kpc}$).

### 3.6. Transient Detection Stamp Triplet (Alert Brokers)
For modern survey events (ZTF / ATLAS / Rubin LSST):
- Display the canonical discovery triplet:
  1. **Science Image** (transient present).
  2. **Template Image** (host galaxy baseline).
  3. **Difference Image** (subtracted point source).
- Pull stamps dynamically from ALeRCE and Fink broker alert APIs.

### 3.7. Dedicated Image Cutout Endpoints
Expose standardized image endpoints on our server:
- `GET /sne/{event}/host.jpg`: Returns the cached, high-resolution host galaxy cutout.
- `GET /api/{event}/cutout?size=500&layer=optical`: Programmable image endpoint for automated pipelines.

---

## 4. Comprehensive Scientific Data & Context (Data Parity & Beyond)

We must ensure that every supernova entry contains the complete parameter set expected by professional astrophysicists:

### 4.1. Complete Primary & Secondary Parameters
| Parameter Domain | Field Name | Description & Standard |
| :--- | :--- | :--- |
| **Astrometry** | `ra`, `dec` | J2000 sexagesimal coordinates and decimal degrees, with astrometric uncertainties. |
| **Classification** | `claimedtype` | Spectral type (Ia, Ia-91T, Ia-91bg, Iax, Ib, Ic, II-P, II-L, IIn, IIb, SLSN-I, SLSN-II, TDE, etc.) with classification source. |
| **Chronology** | `discoverdate`, `maxdate` | Discovery date and date of peak brightness (in ISO UTC and MJD). |
| **Explosion Epoch** | `explosiondate` | Constrained first-light / explosion date from pre-discovery non-detections. |
| **Light Curve Metrics** | `maxappmag`, `maxabsmag` | Brightest detected magnitude and filter, with intrinsic absolute peak magnitude. |
| **Decay Parameters** | $\Delta m_{15}$ | Decline in magnitudes 15 days past maximum (crucial for Type Ia distance calibration). |
| **Cosmology** | `redshift`, `velocity` | Spectroscopic redshift $z$, heliocentric and CMB-frame recession velocities ($v = c \frac{(1+z)^2-1}{(1+z)^2+1}$). |
| **Distances** | `lumdist`, `comovingdist` | Planck 2015 $\Lambda\text{CDM}$ ($H_0 = 67.8, \Omega_M = 0.308$) luminosity and comoving distances in Mpc. |
| | $\mu$ (Distance Modulus) | $\mu = m - M = 5\log_{10}(d_L \times 10^5)$ with propagation of cosmological uncertainties. |
| **Extinction** | `ebv` | Line-of-sight Galactic Milky Way color excess $E(B-V)$ from Schlafly & Finkbeiner (2011) via NASA/IPAC IRSA dust query. |
| **Host Galaxy** | `host` | Host galaxy identification (NGC, UGC, IC, Messier, 2MASX). |
| | `hostra`, `hostdec` | Host galaxy nuclear coordinates. |
| | `hostoffsetang`, `hostoffsetdist` | Angular separation ($\text{arcsec}$) and physical projected offset ($\text{kpc}$) from galactic center. |
| | `hostvelocity`, `hostredshift` | Host systemic redshift and recession velocity from NED / HyperLEDA. |
| **Multi-Messenger** | `radio`, `xray`, `gamma` | Radio flux densities, X-ray detections, and gravitational wave / neutrino associations. |
| **Provenance** | `sources` | Full academic bibliography with Harvard ADS bibcodes, URLs, and attribution aliases. |

---

## 5. Academic Literature, Research Papers & Bibliographic Engine

Astronomers do not trust anonymous numbers—they demand to know which paper, author, and telescope produced every data point.

### 5.1. Hosting vs. Linking: Legal Realities & Astronomical Norms
- **We must NOT host publisher PDFs:** Academic astronomy publishers (*ApJ*, *MNRAS*, *A&A*, *Nature*) hold copyright over final published PDFs. Hosting raw PDFs on `sne.space` creates copyright liability and DMCA takedowns.
- **Astronomers Standardize on NASA ADS:** Professional astronomers never expect third-party websites to host PDFs. The entire field operates on **19-character NASA ADS bibcodes** (e.g., `2020MNRAS.492.4325S`), which link directly to the publisher DOI and free open-access arXiv preprints.
- **What We Host:** Rich paper metadata cards (title, author list, journal, abstract), direct NASA ADS links, arXiv preprint links, and 1-click BibTeX exports.

### 5.2. What the Historical Site Had
The old `sne.space` had an extensive bibliographic architecture:
- **Per-Value Provenance Superscripts:** Every measurement ($m_{\max}$, $z$, $d_L$, individual photometry points, each spectrum) had a numbered citation superscript (e.g. `153.76 Mpc`<sup>[6]</sup>) linking to a primary source.
- **NASA ADS Integration:** Built on NASA Astrophysics Data System (ADS) 19-character bibcodes (e.g., `2016A&A...594A..13P`, `2020MNRAS.492.4325S`).
- **The Master Bibliography Database (`biblio.json`):** The catalog maintained a 446,000-line relational bibliography database (`output/biblio.json` generated by `bibliocat.py`), indexing every paper written about every supernova, author lists, and event cross-references.
- **Direct ADS Links:** Every source row linked directly to the Harvard ADS abstract service (`http://adsabs.harvard.edu/abs/{bibcode}`).

### 5.3. How We Modernize Research Articles for the 2026 Market
1. **Automated NASA ADS REST API Pipeline (`api.adsabs.harvard.edu`):**
   - Query NASA ADS in real time for any paper mentioning the supernova's IAU name or aliases in its title, abstract, or body.
   - Automatically pull paper titles, author lists, publication date, and journal reference (*ApJ*, *MNRAS*, *A&A*, *Nature*, *Science*).
2. **Preprint & Circular Aggregation:**
   - **arXiv Preprints:** Instant links to `arxiv.org/abs/...` before formal peer-reviewed journal publication.
   - **TNS AstroNotes & Discovery Reports:** Links to official discovery circulars and classification telegrams.
   - **ATels (The Astronomer's Telegram):** Direct integration with ATel notices (`astronomerstelegram.org`) reporting rapid spectroscopic classifications or unusual outbursts.
3. **One-Click BibTeX Citation Exporter:**
   - A single `[ Copy BibTeX ]` button on each event page that copies the perfectly formatted citation block for all papers that observed that specific supernova, saving astronomers hours when writing papers.

---

## 6. Real-Time Transient Astrophysics & Open-Source Triage

Modern astronomers don't just study dead stars—they actively hunt live explosions to trigger ground and space telescopes (Keck, VLT, James Webb Space Telescope, Hubble, Swift). We separate real-time into **immediate lightweight wins** and **heavy streaming infrastructure to defer**.

### 6.1. The 5 Core Real-Time Capabilities Observers Care About
1. **Live Rising Supernovae Radar ("Catch It on the Rise"):**
   - The most scientifically valuable phase of a supernova is the first 72 hours after explosion (probing the progenitor star's radius and circumstellar shock breakout).
   - A dedicated **"Supernovae Rising Tonight"** feed filtering for transients with positive flux derivatives ($dm/dt < 0$) in active survey streams.
2. **Bright Unclassified Target Radar ($m < 18$ Mag):**
   - Observers with 1-meter to 4-meter telescopes constantly search for bright transients that still lack a spectroscopic classification (designated as candidate `AT...` rather than confirmed `SN...`).
   - A real-time filter: *"Bright Unclassified Candidates Observable Tonight"* allows observers to secure target spectra and claim classification discovery credit on TNS.
3. **Target Observability & Air Mass Engine ("Can I Shoot This Tonight?"):**
   - Observers sit down in the afternoon to design their telescope queue.
   - Given an observatory preset (Keck, VLT, Palomar, Gemini, Lick, La Palma, or user geolocation), calculate:
     - Real-time air mass curve $X(t)$ from dusk to dawn.
     - Moon separation angle and illumination phase (checking for sky background wash).
     - Hour angle and meridian transit time.
4. **Target of Opportunity (ToO) Rapid Alerts:**
   - Direct webhook/feed integration for unusual astronomical triggers:
     - Extremely young Type Ia (within hours of explosion).
     - Superluminous Supernovae (SLSNe).
     - Relativistic transients and Fast Optical Transients (FBOTs like AT2018cow).
5. **Multi-Messenger Coincidence Matching:**
   - When **LIGO/Virgo/KAGRA** detects gravitational wave chirps (neutron star mergers) or **IceCube** detects ultra-high-energy cosmic neutrinos, astronomers frantically search optical catalogs.
   - Spatial-temporal cone matching against gravitational wave probability sky maps (HEALPix / Skymap FITS) to flag potential optical counterparts.

### 6.2. Open-Source Ecosystem for Real-Time Astronomy
Instead of reinventing the wheel, we leverage battle-tested open-source astronomy packages:
- **`astroplan` (Astropy-affiliated Python):** High-precision observatory airmass, rise/set, and twilight calculations in $< 10\text{ ms}$.
- **`astronomy-engine` (Pure JavaScript npm):** Instant topocentric alt/az and air mass calculated entirely client-side in the user's browser with zero server compute.
- **`TOM Toolkit` (Las Cumbres Observatory):** Proven schemas and connectors for transient telescope management.
- **`alerce` & `fink-client` (Alert Broker Python SDKs):** Python connectors querying machine-learning classifiers over simple REST endpoints.

### 6.3. Feature Triage: Instant Wins vs. Deferred Infrastructure

| Real-Time Feature | Complexity | Approach | Status |
| :--- | :--- | :--- | :--- |
| **Nightly Observability & Air Mass Widget** | **Very Low** | Pure client-side JS (`astronomy-engine`) or 10 lines of `astroplan` | **Phase 2 (Immediate)** |
| **Bright Unclassified Target Feed** | **Low** | On-demand REST query to ALeRCE / Fink API ($m < 18$, unclassified) | **Phase 2 (Immediate)** |
| **Rising Supernova Radar** | **Low** | REST filter for $dm/dt < 0$ alerts in past 72 hrs | **Phase 2 (Immediate)** |
| **Full Kafka Streaming Broker Cluster** | **Massive** | Running Apache Spark/Kafka clusters ingesting millions of alerts/night | **Deferred / Never build** |
| **Automated User Email/SMS Alerting** | **High** | Requires user accounts, database subscriptions, Celery queues | **Deferred to Phase 5+** |
| **Live Gravitational Wave Skymap Cross-matching** | **Medium-High** | Real-time HEALPix parsing (`healpy`) against GCN Kafka feeds | **Deferred to Phase 5+** |

---

## 7. The Programmatic Content Engine & Viral SEO Strategy

### 7.1. The Massive Content Vacuum in Transient Astronomy
- Wikipedia only has articles for ~350 supernovae. The other 110,000 events have zero readable pages anywhere on the internet.
- IAU TNS is an unformatted technical registry unusable by students, amateurs, and science reporters.
- Google receives tens of thousands of monthly searches for supernova names, bright transients, and galaxy explosions.

### 7.2. Google's Scaled Content Abuse Policy (The Trap to Avoid)
- **The Failure Mode:** Prompting an LLM to generate 100,000 generic 600-word blog posts with repetitive fluff (*"Stars are wonders of the cosmic ballet..."*). Google's Helpful Content System will flag the domain for Scaled Content Abuse and de-index the site.
- **The Winning Formula (The Zillow / IMDb / FlightAware Model):** Google rewards sites that display **dense, unique, structured facts, verified physics, and real visual media**.

### 7.3. The 3-Tier Programmatic Architecture
To dominate search while guaranteeing elite domain authority, the 110,000+ catalog is split into three tiers:

```
                       ▲
                      / \     Tier 1: ~500 "Blockbuster" Events
                     /   \    (Journalistic depth, Hubble/JWST, discovery story)
                    /─────\
                   /       \   Tier 2: ~15,000 "Observational Dossiers"
                  /         \  (Light curves, host cutouts, "Can I see it tonight?")
                 /───────────\
                /             \ Tier 3: ~95,000 "Catalog Data Records"
               /               \(Pure scientific data page only — no fake fluff)
              ───────────────────
```

1. **Tier 1: The "Blockbuster" Events (~500 events):**
   - Events with $>50$ citations, naked-eye/binocular visibility, or historic significance (e.g., `SN 1987A`, `SN 2011fe`, `SN 2023ixf`, `SN 2024ggi`).
   - Rich narrative with verified discovery stories, Hubble/JWST images, and `NewsArticle` Schema.org markup.
2. **Tier 2: The "Observational Dossiers" (~15,000 events):**
   - Supernovae with $\ge 5$ photometry points and confirmed host/type.
   - Programmatically structured field guide: light curve in days from peak, distance in light-years, constellation locator, host cutout, and telescope requirements.
3. **Tier 3: The Faint Data Archive (~95,000 events):**
   - Faint survey detections (e.g. 21st-mag single detections).
   - **No fake story generated.** Kept as clean, blazing-fast data records (`/sne/{event}/`) with `Dataset` JSON-LD, preserving site quality scores.

### 7.4. URL Architecture & Backlink Optimization
- **Canonical Pro Page:** `https://sne.space/sne/SN2024nrb/`
- **Story / Magazine Page:** `https://sne.space/sne/SN2024nrb/story` (or `/mag`)
- **Why Subpath AFTER Event Is Superior:**
  - **Topical Hierarchy:** Google groups `SN2024nrb` as the parent entity and `story` as its child attribute.
  - **No Keyword Cannibalization:** Prevents a separate `/mag/` directory from competing against `/sne/` for the exact same search term.
  - **Backlink Equity Consolidation:** External links to either the story or raw data flow equity into the same directory cluster.

### 7.5. Dual Schema.org Strategy (Dominating Two Google Search Indexes)
- `/sne/{event}/` carries **`Dataset` JSON-LD** $\to$ Dominates **Google Dataset Search & Google Scholar**.
- `/sne/{event}/story` carries **`Article` / `NewsArticle` JSON-LD** $\to$ Dominates **Google Web Search, Top Stories & Google Discover**.

---

## 8. AI-Native Infrastructure (What Google & LLM Agents Expect)

Modern search engines and AI assistants (Google Gemini, OpenAI ChatGPT, Anthropic Claude, Perplexity, Cursor) require structured machine-readable interfaces to crawl, understand, and cite astronomical data.

### 8.1. Standardized `llms.txt` and `llms-full.txt`
Place `/llms.txt` and `/llms-full.txt` in the root of `sne.space`:
- Explains the API architecture, data models, and direct endpoints.
- Allows AI models to instantly answer complex user queries with verified facts and citations from `sne.space`.

### 8.2. Native Model Context Protocol (MCP) Server: `sne-space-mcp`
Provide a dedicated MCP server enabling any AI agent in Cursor, Claude Desktop, or LangChain to directly interface with the catalog:
- `get_supernova(name)`: Retrieves complete event metadata, distances, and classification.
- `search_supernovae(type, min_z, max_z, max_mag, year)`: Fast filtering across 110,000+ events.
- `get_lightcurve(name, format)`: Returns formatted photometry for analysis.
- `get_spectrum(name, epoch)`: Returns calibrated 1D spectrum arrays.
- `calculate_cosmology(z)`: Runs Planck 2015 cosmological calculator.

### 8.3. Schema.org & Science-on-Schema.org JSON-LD
Inject Google-compliant JSON-LD structured data into the `<head>` of every event page:
```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "Supernova SN2024nrb Optical Photometry and Spectroscopy",
  "description": "Calibrated multi-band light curves, classification spectra, and derived cosmological parameters for Type Ia supernova SN2024nrb in the Open Supernova Catalog.",
  "url": "https://sne.space/sne/SN2024nrb/",
  "identifier": "https://doi.org/10.3847/1538-4357/835/1/64",
  "keywords": ["supernova", "Type Ia", "cosmology", "astrophysics", "light curve", "spectrum"],
  "creator": {
    "@type": "Organization",
    "name": "Open Supernova Catalog",
    "url": "https://sne.space"
  },
  "variableMeasured": ["Apparent Magnitude", "Flux", "Luminosity Distance", "Redshift"],
  "spatialCoverage": {
    "@type": "Place",
    "geo": {
      "@type": "GeoCoordinates",
      "longitude": 71.370079,
      "latitude": -16.374925
    }
  },
  "distribution": [
    {
      "@type": "DataDownload",
      "encodingFormat": "application/json",
      "contentUrl": "https://sne.space/api/SN2024nrb"
    },
    {
      "@type": "DataDownload",
      "encodingFormat": "text/csv",
      "contentUrl": "https://sne.space/SN2024nrb/photometry?format=csv"
    }
  ]
}
</script>
```

### 8.4. Google Dataset Search & Scholar Optimization
By formatting our metadata via Science-on-Schema.org standards, all 110,000+ events become automatically indexed in **Google Dataset Search** (`datasetsearch.research.google.com`), positioning `sne.space` as an authoritative citable data repository.

---

## 9. SEO, Crawlability & Indexing Infrastructure

To maximize search visibility and domain authority:

### 9.1. XML Sitemap Sharding
- Google caps individual sitemaps at 50,000 URLs.
- Implement a hierarchical sitemap index:
  - `/sitemap.xml` (Index pointing to chunked sitemaps)
  - `/sitemap_historical_1.xml` & `_2.xml` (Pre-1990 to 2019 events, ~70,000 URLs split into 2 files)
  - `/sitemap_modern.xml` (2020–2024 events, ~35,000 URLs)
  - `/sitemap_current.xml` (2025–2026+ active events, high update frequency)
  - `/sitemap_stories.xml` (Tier 1 & Tier 2 plain-English articles)

### 9.2. Semantic Meta Tags & Social Cards
- **OpenGraph & Twitter Cards (`summary_large_image`):**
  - Title: `{Name} ({Type}) — Open Supernova Catalog`
  - Description: `Discovered on {Date} by {Discoverer}. Peak mag {m_max}, Redshift z={z}, Distance {d_L} Mpc.`
  - Image: Pointing directly to the deep optical host cutout (`/sne/{name}/host.jpg`).
- **Canonical URLs:** Strict `rel="canonical"` tags to eliminate duplicate content penalties across aliases (e.g. `/sne/SN2024nrb/`, `/sne/AT2024nrb/`, and `/event/SN2024nrb` all canonicalize to `https://sne.space/sne/SN2024nrb/`).

### 9.3. Sub-100ms Fast Server-Side Rendering (SSR)
- Search engine spiders (Googlebot, Bingbot) will not wait for slow client-side JavaScript.
- Event metadata tables, citations, and download links are pre-rendered into static semantic HTML on the server.
- Interactive plots hydrate asynchronously without delaying initial page render or crawler indexing.

---

## 10. JSON, REST API & Data Standards

Astronomers automate their workflows using Python libraries (`astroquery`, `sncosmo`, `astropy`). Our API must be fast, reliable, and completely backwards-compatible.

### 10.1. OACAPI Full Drop-In Restoration
Restore 100% compatibility with the Open Astronomy Catalog API specification:
- `/api/catalog` or `/catalog.json`: Global catalog index.
- `/catalog.csv`: Streaming CSV catalog.
- `/api/{event}` or `/{event}.json`: Complete AstroCats event JSON.
- `/{event}/photometry`: Photometry points in JSON.
- `/{event}/photometry?format=csv`: Clean CSV light curve (`time,magnitude,e_magnitude,band,instrument,telescope,source`).
- `/{event}/spectra`: Calibrated spectral arrays.
- `/{event}/spectra/data`: Direct CSV spectral download.

### 10.2. On-Demand Enrichment API
- `GET /api/{event}/enrich`: Forces server-side re-enrichment from ALeRCE, WISeREP, and IRSA, returning the freshly generated JSON.
- Respects the 24-hour (active) / 7-day (plateau) / infinite (historical) TTL caching strategy.

### 10.3. Virtual Observatory (IVOA) Compliance
- **Simple Cone Search (SCS):** Implement IVOA cone search endpoint:
  `GET /api/cone?ra={deg}&dec={deg}&radius={arcsec}`
- **VOTable Format:** Provide option `?format=votable` for seamless integration into desktop tools like TOPCAT and Aladin Desktop.

### 10.4. Bulk Catalog Distribution
- Host pre-packaged, compressed tarballs for researchers doing bulk demographic studies:
  - `sne-pre-1990.tar.gz`
  - `sne-1990-1999.tar.gz`
  - `sne-2000-2004.tar.gz`
  - `sne-2005-2009.tar.gz`
  - `sne-2010-2014.tar.gz`
  - `sne-2015-2019.tar.gz`
  - `sne-2020-2024.tar.gz`
  - `sne-2025-2029.tar.gz`
  - `catalog.min.json.gz` (Complete current master index)

---

## 11. Scientific Accuracy & Verification Protocol (Zero Assumptions Policy)

To ensure that `sne.space` maintains absolute scientific fidelity, every parameter, calculation, and data point adheres to a strict zero-assumption empirical protocol:

### 11.1. Ground-Truth Data Provenance (No Synthetic or Fabricated Values)
- **Primary Source Attribution:** No data point is ingested without a verifiable upstream source (`wis-tns.org`, `alerce.online`, `wiserep.org`, or published literature).
- **Explicit Derivation Flags:** In strict compliance with the AstroCats object model, any value calculated by our software (cosmological distance, recession velocity, absolute magnitude) has `"derived": true` attached, attributing the calculation method and bibcode (e.g. Planck Collaboration 2016).
- **Graceful Absence:** If an astronomical parameter cannot be empirically measured or derived from verified physics, it remains blank/null (`—`). We never fabricate or guess parameters.

### 11.2. Deterministic Cosmological & Astrophysical Formulations
All scientific derivations use exact, peer-reviewed mathematical formulations:
1. **Cosmological Distance & Expansion:**
   - Standard flat $\Lambda\text{CDM}$ numerical integration:
     $$E(z) = \sqrt{\Omega_M (1+z)^3 + \Omega_\Lambda}$$
     $$d_C = \frac{c}{H_0} \int_0^z \frac{dz'}{E(z')}, \quad d_L = (1+z) d_C$$
   - Fixed cosmological parameters: $H_0 = 67.8\text{ km s}^{-1}\text{ Mpc}^{-1}$, $\Omega_M = 0.308$, $\Omega_\Lambda = 0.692$ (Planck Collaboration 2016, `2016A&A...594A..13P`).
2. **Relativistic Recession Velocity:**
   - Exact Doppler relation (no low-redshift approximation $cz$):
     $$v = c \cdot \frac{(1+z)^2 - 1}{(1+z)^2 + 1}$$
3. **Line-of-Sight Dust Extinction:**
   - Interrogates the NASA/IPAC Infrared Science Archive (IRSA) dust service at the target coordinates, querying the Schlafly & Finkbeiner (2011) re-calibration of the Schlegel, Finkbeiner & Davis (1998) Galactic dust map (`2011ApJ...737..103S`).
4. **Distance-Corrected Absolute Magnitude:**
   - Corrected for cosmological dimming and luminosity distance:
     $$M_{\text{abs}} = m_{\max} - 5\left(\log_{10}(d_L \times 10^6) - 1\right) + 2.5\log_{10}(1+z)$$

### 11.3. Automated Scientific Test Suite & Invariant Checking
Every pipeline build and on-demand enrichment runs through automated validation tests:
- **Historical Benchmark Regression:** Continuous regression checking against gold-standard benchmark supernovae (`SN 1987A`, `SN 1993J`, `SN 1998bw`, `SN 2011fe`) ensuring coordinate precision, photometry point counts, and spectra match published literature.
- **Physical Invariant Sanity Checks:**
  - $0 \le z \le 10$ (redshift within physical cosmological bounds).
  - $0 \le E(B-V) \le 10\text{ mag}$ (Milky Way dust reddening).
  - $-24 \le M_{\text{abs}} \le -10\text{ mag}$ (optical supernova luminosity range).
  - $0 \le \text{RA} < 360^\circ$, $-90^\circ \le \text{Dec} \le +90^\circ$ (coordinate space bounds).
- **Schema Validation:** Every JSON write must strictly pass the AstroCats JSON schema specification (`SCHEMA.md`).

---

## 12. Master Phased Implementation Roadmap

### Phase 1: Modern Visuals & Media Foundation (Days 1–3)
- [x] **1.1 Image Link Protocols & Host Cutouts**: Wire DESI Legacy Survey DR10 (`ls-dr10`) & NASA SkyView DSS2 optical cutouts into event pages with interactive layer toggling. *(Completed)*
- [x] **1.2 Embedded Sky Map**: Embed Aladin Lite v3 interactive crosshair sky viewer centered on transient coordinates. *(Completed)*
- [x] **1.3 Interactive Light Curve Engine**: Replace static HTML tables with modern WebGL/Canvas multi-band Light Curve plot (band toggles, detection glyphs, upper limits, rest-frame time, hover cards). *(Completed)*
- [x] **1.4 Stacked Interactive Spectra Viewer**: Epoch stacking, rest-frame de-redshifting, smoothing slider, and atomic feature overlays. *(Completed)*
- [x] **1.5 Discovery Blink Comparison Slider**: Before/after interactive blink comparison alternating host galaxy baseline against peak transient detection. *(Completed)*

### Phase 2: Dual Experience & Content Engine (Days 4–6)
- [x] **2.1 Story Mode / Observer Dossier**: Build the consumer/amateur view at `/sne/{event}/story` with plain-English summaries, lookback distances, and "Can I see it tonight?". *(Completed)*
- [ ] **2.2 3-Tier Programmatic Content Engine**: Tier 1 Blockbusters, Tier 2 Field Guides, Tier 3 Pure Data Archives.
- [x] **2.3 Academic Literature & NASA ADS API**: Real-time paper discovery, author lists, arXiv links, and 1-Click BibTeX export. *(BibTeX export completed; live ADS query pipeline pending)*
- [x] **2.4 Host Galaxy Offset Physics**: Calculate physical projected offset (kpc) and angular separation (arcseconds) from NED/HyperLEDA or catalog coordinates. *(Completed)*
- [x] **2.5 Tonight's Sky & Air Mass Planner**: Observatory air mass curve $X(t)$, transit times, and Moon separation angle via `astronomy-engine` / astronomical ephemeris. *(Completed)*

### Phase 3: Real-Time Transient Feeds & Observers Radar (Days 7–8)
- [x] **3.1 Supernovae Rising Tonight Radar**: Real-time feed filtering for $dm/dt < 0$ alerts in active survey streams (ALeRCE/Fink) and catalog transients. *(Completed)*
- [x] **3.2 Bright Unclassified Target Radar**: Filter for unclassified candidates with $m < 18\text{ mag}$ observable tonight. *(Completed)*
- [x] **3.3 Dedicated Image Cutout Endpoints**: Standardized server routes `/sne/{event}/host.jpg` and `/api/{event}/cutout`. *(Completed)*

### Phase 4: AI-Native & Semantic Web (Days 9–10)
- [x] **4.1 Root `llms.txt` & `llms-full.txt`**: Standardized AI crawlers guide to catalog data and endpoints. *(Completed)*
- [x] **4.2 Science-on-Schema.org Dataset JSON-LD**: Rich structured data injected on canonical `/sne/{event}/` pages for Google Dataset Search. *(Completed)*
- [x] **4.3 NewsArticle / Article JSON-LD**: Structured data injected on `/sne/{event}/story` pages for Google Discover and Top Stories. *(Completed)*
- [ ] **4.4 Native Model Context Protocol (MCP) Server**: Deploy `sne-space-mcp` for direct AI tool calling.

### Phase 5: SEO, Scale & IVOA Standards (Days 11–12)
- [x] **5.1 Sharded XML Sitemaps**: Hierarchical sitemaps index split to stay below 50,000 URLs per shard (`/sitemap.xml`, `/sitemap_current.xml`, `/sitemap_stories.xml`, etc.). *(Completed)*
- [x] **5.2 OpenGraph & Twitter Social Cards**: Dynamic cards embedding host optical cutouts. *(Completed)*
- [ ] **5.3 Automated Cron Synchronization**: Nightly delta ingest from TNS, ALeRCE, and WISeREP.
- [x] **5.4 IVOA Simple Cone Search & VOTable**: Virtual Observatory endpoints (`/api/cone`, `?format=votable`). *(Completed)*

---

*Authored for the sne.space Open Supernova Catalog Revival Initiative.*
