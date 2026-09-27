"""Render the Master Frequently Asked Questions (FAQ) Page for sne.space."""
from __future__ import annotations

import json
from typing import Dict, List, Tuple

FAQ_CATEGORIES: List[Tuple[str, str, List[Dict[str, str]]]] = [
    (
        "About the Open Supernova Catalog",
        "Historical origins, modernization, and scientific mission.",
        [
            {
                "q": "What is the Open Supernova Catalog (sne.space)?",
                "a": "The Open Supernova Catalog is an open-access, community-curated astrophysical repository containing comprehensive data for over 110,222 supernovae and cosmic transients from 1000 AD to 2026+. It unifies multi-band optical, ultraviolet, and infrared light curves, calibrated spectra, host galaxy associations, cosmological distance parameters, and NASA ADS literature citations into a single standardized schema."
            },
            {
                "q": "Why was sne.space restored and modernized?",
                "a": "The original Open Supernova Catalog went offline around 2021, scattering transient astronomy data across fragmented silos. We rebuilt sne.space from first principles into a high-performance, modern platform that combines deep historical records with real-time survey streams (TNS, ZTF, ATLAS), AI-native discovery tools (MCP and WebMCP), and a dual-experience architecture serving both professional astrophysicists and amateur stargazers."
            },
            {
                "q": "How does sne.space differ from IAU TNS, WISeREP, and Alert Brokers?",
                "a": "The IAU Transient Name Server (TNS) is the official discovery registry, but lacks unified multi-band light curves or calibrated spectral time series. WISeREP stores spectra but does not aggregate multi-color photometry. Alert brokers (ALeRCE, Fink, Lasair) stream modern alerts but lack deep historical archives before 2018. sne.space bridges these systems by synthesizing discovery circulars, broker alert streams, space telescope observations (Hubble, JWST, Swift), and peer-reviewed literature into one living entity per event."
            }
        ]
    ),
    (
        "Astrophysics & Observational Science",
        "Supernova classification, distance scales, and backyard viewing.",
        [
            {
                "q": "What are the primary types of supernovae in the catalog?",
                "a": "Supernovae are broadly categorized into two fundamental physical mechanisms: Thermonuclear Detonations (Type Ia), where a carbon-oxygen white dwarf in a tight binary system accretes mass to the Chandrasekhar limit (~1.4 solar masses) and completely obliterates itself; and Core-Collapse Supernovae (Types II, Ib, Ic), where a massive supergiant star (≥8 solar masses) exhausts its nuclear fuel, collapsing into a neutron star or black hole while rebounding its outer envelope into space."
            },
            {
                "q": "How does sne.space calculate distances in light-years and Mpc?",
                "a": "For events with measured spectroscopic redshifts (z), cosmological distances are calculated using standard Flat Lambda-CDM cosmology (H0 = 70 km/s/Mpc, Ω_M = 0.3, Ω_Λ = 0.7). Relativistic velocity is computed as v = c * ((1+z)² - 1) / ((1+z)² + 1). Luminosity distance (d_L) is derived via numerical integration of the comoving distance, and converted to light-years via 1 Mpc = 3,261,560 light-years."
            },
            {
                "q": "Can I observe supernovae in the catalog with a backyard telescope?",
                "a": "Yes, when they are at or near peak brightness! Supernovae in nearby galaxies (within ~50 million light-years) frequently reach apparent magnitudes between 10.0 and 13.5, making them visible in 4-inch to 10-inch amateur telescopes. However, optical transients fade rapidly along radioactive decay tails (typically fading 2 to 5 magnitudes over 30 to 60 days). Every event page on sne.space includes an automated transient lifecycle indicator telling you whether the object is currently active or extinguished."
            }
        ]
    ),
    (
        "APIs, Data Formats & Integrations",
        "Direct downloads, REST endpoints, and astronomical protocols.",
        [
            {
                "q": "How do I download data for an individual supernova?",
                "a": "Data is available in multiple machine-readable formats: Complete JSON schema at /sne/{name}.json, calibrated multi-band photometry CSV table at /{name}/photometry?format=csv, and calibrated optical spectra at /{name}/spectra?format=json. All endpoints are open-access, zero-token, and support CORS for direct client-side integration."
            },
            {
                "q": "Does sne.space support coordinate cone search (IVOA standard)?",
                "a": "Yes! sne.space implements an IVOA Simple Cone Search endpoint at /api/cone?RA={deg}&DEC={deg}&SR={deg}&format=votable (or format=json). It runs against a spatial 3D Cartesian index over 110,000+ catalog objects, returning sub-millisecond coordinate cross-matches."
            },
            {
                "q": "How can I retrieve high-resolution optical cutouts of host galaxies?",
                "a": "sne.space provides direct image endpoints: /sne/{name}/host.jpg returns a 302 redirect to the highest available optical cutout. You can also specify survey layers via /api/{name}/cutout?layer=panstarrs|desi|wise|2mass|dss2&size=500."
            }
        ]
    ),
    (
        "AI Agents, WebMCP & ARD Discovery",
        "Standards for autonomous AI assistants and search engines.",
        [
            {
                "q": "Does sne.space provide a Model Context Protocol (MCP) server?",
                "a": "Yes! sne.space includes a native FastMCP server (serve/mcp_server.py) exposing tools for AI assistants (Cursor, Claude, agents): search_supernovae, get_supernova, get_lightcurve, get_spectrum, calculate_cosmology, and spatial_cone_search."
            },
            {
                "q": "What is WebMCP and how does sne.space implement it?",
                "a": "WebMCP is an emerging browser standard enabling websites to expose structured tools directly to AI browsing agents. sne.space implements declarative WebMCP on all search forms (toolname and tooldescription attributes with fully described input parameters) and imperatively registers search_supernovae, get_supernova_photometry, and cone_search via navigator.modelContext."
            },
            {
                "q": "Where is the Agentic Resource Discovery (ARD) catalog published?",
                "a": "sne.space publishes ARD v0.91 capability manifests at /.well-known/ai-catalog.json and /.well-known/ard.json, linked via robots.txt Agentmap directives, HTML <link rel='ai-catalog'> tags, and HTTP Link headers."
            }
        ]
    ),
    (
        "Citations & Academic Attribution",
        "How to cite sne.space and original literature in research papers.",
        [
            {
                "q": "How should I cite the Open Supernova Catalog in research papers?",
                "a": "When using sne.space in academic publications, please cite Guillochon et al. (2017), 'An Open Supernova Catalog', The Astrophysical Journal Letters, 835(1), L64 (Bibcode: 2017ApJ...835L..64G). Every event page also provides a 'Copy BibTeX' button aggregating the primary discovery and data citations specific to that object."
            }
        ]
    )
]


def render_faq_page() -> str:
    """Render the master FAQ hub HTML with Schema.org FAQPage JSON-LD."""
    all_faqs = []
    category_blocks = []

    for cat_title, cat_sub, questions in FAQ_CATEGORIES:
        item_htmls = []
        for q_item in questions:
            all_faqs.append(q_item)
            q = q_item["q"]
            a = q_item["a"]
            item_htmls.append(f"""
            <details class="faq-item">
              <summary class="faq-question">{q}</summary>
              <div class="faq-answer"><p>{a}</p></div>
            </details>
            """)

        category_blocks.append(f"""
        <div class="faq-cat-block">
          <h2 class="faq-cat-title">{cat_title}</h2>
          <p class="faq-cat-sub">{cat_sub}</p>
          <div class="faq-accordion">
            {"".join(item_htmls)}
          </div>
        </div>
        """)

    # Build Schema.org FAQPage JSON-LD
    schema_entities = []
    for f in all_faqs:
        clean_q = f["q"].replace('"', '\\"')
        clean_a = f["a"].replace('"', '\\"').replace('\n', ' ')
        schema_entities.append(f'''    {{
      "@type": "Question",
      "name": "{clean_q}",
      "acceptedAnswer": {{
        "@type": "Answer",
        "text": "{clean_a}"
      }}
    }}''')

    faq_jsonld_str = ",\n".join(schema_entities)
    faq_jsonld = f"""<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
{faq_jsonld_str}
  ]
}}
</script>"""

    cat_blocks_html = "".join(category_blocks)
    webmcp_script = """<script>
  (function() {
    function registerWebMCP() {
      const ctx = (window.navigator && window.navigator.modelContext) || 
                  (window.document && window.document.modelContext) || null;
      if (!ctx || typeof ctx.registerTool !== 'function') return;

      try {
        ctx.registerTool({
          name: "search_supernovae",
          description: "Search 110,000+ supernovae by IAU designation, name, or survey alias",
          inputSchema: {
            type: "object",
            properties: {
              q: {
                type: "string",
                description: "Supernova name, IAU designation (e.g. SN2023ixf, SN 1987A), or alias"
              }
            },
            required: ["q"]
          },
          execute: async function(args) {
            if (!args || !args.q) return { error: "Missing query parameter 'q'" };
            return { status: "success", query: args.q, url: "/sne/" + encodeURIComponent(args.q) };
          }
        });
      } catch (e) {}
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', registerWebMCP);
    } else {
      registerWebMCP();
    }
  })();
  </script>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Frequently Asked Questions — Open Supernova Catalog (sne.space)</title>
  <meta name="description" content="Comprehensive astrophysics, API, AI agent (MCP/WebMCP), and observational astronomy FAQs for the Open Supernova Catalog (sne.space).">
  <link rel="stylesheet" href="/assets/ia.css">
  <link rel="ai-catalog" href="/.well-known/ai-catalog.json" type="application/ai-catalog+json">
  <link rel="ard" href="/.well-known/ard.json" type="application/json">
  {faq_jsonld}
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: #121929;
      --border: #1e293b;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.6;
    }}
    header.cockpit-hdr {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      padding: 0.75rem 1.5rem;
      background: #070a12;
      border-bottom: 1px solid var(--border);
    }}
    .brand-group {{
      display: flex;
      align-items: center;
      gap: 1rem;
    }}
    .brand-title {{
      font-weight: 700;
      font-size: 1.25rem;
      color: #fff;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 0.55rem;
    }}
    .brand-logo-img {{
      height: 38px;
      width: auto;
      vertical-align: middle;
      filter: drop-shadow(0 0 10px rgba(56, 189, 248, 0.4));
      transition: transform 0.2s ease, filter 0.2s ease;
    }}
    .brand-logo-img:hover {{
      transform: scale(1.04);
      filter: drop-shadow(0 0 16px rgba(56, 189, 248, 0.7));
    }}
    .brand-badge {{
      font-size: 0.75rem;
      background: #1e3a8a;
      color: #93c5fd;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-weight: 600;
    }}
    .hdr-search-form {{
      display: flex;
      align-items: center;
      background: rgba(15, 23, 42, 0.75);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      max-width: 340px;
      flex: 1;
      margin: 0 1rem;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }}
    .hdr-search-form:focus-within {{
      border-color: #38bdf8;
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
    }}
    .hdr-search-form input {{
      background: transparent;
      border: none;
      outline: none;
      color: #f1f5f9;
      font-size: 0.85rem;
      padding: 0.35rem 0.65rem;
      width: 100%;
    }}
    .hdr-search-form button {{
      background: transparent;
      border: none;
      color: #94a3b8;
      padding: 0.35rem 0.6rem;
      cursor: pointer;
    }}
    .faq-hero {{
      text-align: center;
      padding: 3.5rem 1.5rem 2rem;
      background: radial-gradient(circle at 50% 20%, rgba(56, 189, 248, 0.12), transparent 70%);
      border-bottom: 1px solid var(--border);
    }}
    .faq-hero h1 {{
      font-size: 2.2rem;
      font-weight: 800;
      margin: 0 0 0.75rem;
      color: #fff;
      letter-spacing: -0.02em;
    }}
    .faq-hero p {{
      max-width: 680px;
      margin: 0 auto;
      color: var(--text-muted);
      font-size: 1.05rem;
    }}
    .faq-container {{
      max-width: 900px;
      margin: 2.5rem auto 5rem;
      padding: 0 1.5rem;
    }}
    .faq-cat-block {{
      margin-bottom: 3rem;
    }}
    .faq-cat-title {{
      font-size: 1.4rem;
      font-weight: 700;
      color: #38bdf8;
      margin: 0 0 0.25rem;
    }}
    .faq-cat-sub {{
      color: var(--text-muted);
      font-size: 0.9rem;
      margin: 0 0 1rem;
    }}
    .faq-accordion {{
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }}
    .faq-item {{
      background: rgba(18, 25, 41, 0.85);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      transition: all 0.15s ease;
    }}
    .faq-item:hover {{
      border-color: rgba(56, 189, 248, 0.45);
      background: rgba(22, 32, 54, 0.95);
    }}
    .faq-item summary {{
      padding: 0.95rem 1.25rem;
      font-weight: 600;
      font-size: 0.95rem;
      color: #f1f5f9;
      cursor: pointer;
      user-select: none;
      display: flex;
      align-items: center;
      justify-content: space-between;
      list-style: none;
    }}
    .faq-item summary::-webkit-details-marker {{
      display: none;
    }}
    .faq-item summary::after {{
      content: "+";
      font-size: 1.25rem;
      font-weight: 600;
      color: #38bdf8;
      line-height: 1;
      margin-left: 0.75rem;
      transition: transform 0.2s ease;
    }}
    .faq-item[open] summary::after {{
      content: "−";
    }}
    .faq-item[open] summary {{
      border-bottom: 1px solid var(--border);
      color: #38bdf8;
      background: rgba(56, 189, 248, 0.08);
    }}
    .faq-answer {{
      padding: 1.1rem 1.25rem;
      font-size: 0.92rem;
      line-height: 1.7;
      color: #cbd5e1;
    }}
    .faq-answer p {{ margin: 0 0 0.6rem; }}
    .faq-answer p:last-child {{ margin-bottom: 0; }}
  </style>
</head>
<body>
  <header class="cockpit-hdr">
    <div class="brand-group">
      <a class="brand-title" href="/" title="sne.space — The Open Supernova Catalog">
        <img src="/assets/img/logo-color.png" alt="sne.space" class="brand-logo-img">
      </a>
      <span class="brand-badge">Open Supernova Catalog</span>
    </div>
    <form class="hdr-search-form" action="/" method="GET" toolname="search_supernovae" tooldescription="Search 110,000+ supernovae by IAU designation, name, or survey alias">
      <input type="text" name="q" placeholder="Search 110,000+ transients..." autocomplete="off" toolparamdescription="Supernova name, IAU designation (e.g. SN2023ixf, SN 1987A), or survey alias" aria-label="Search supernovae">
      <button type="submit" aria-label="Submit Search">🔍</button>
    </form>
    <div style="display:flex;align-items:center;gap:1rem;">
      <a href="/" style="color:var(--text-muted);text-decoration:none;font-size:0.85rem;font-weight:600;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='var(--text-muted)'">← Back to Catalog</a>
      <a href="/radar" style="color:var(--accent);text-decoration:none;font-size:0.85rem;font-weight:600;">📡 Observer Radar</a>
    </div>
  </header>

  <div class="faq-hero">
    <h1>Frequently Asked Questions</h1>
    <p>Everything you need to know about the Open Supernova Catalog: astrophysical methodology, APIs, AI agents (MCP &amp; WebMCP), and observational tools.</p>
  </div>

  <main class="faq-container">
    {cat_blocks_html}
  </main>

  <!-- WebMCP Agentic Tools Script -->
  {webmcp_script}
</body>
</html>"""
    return html
