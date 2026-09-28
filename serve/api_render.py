"""Render the sne.space Developer & API Documentation Page."""
from __future__ import annotations

def render_api_docs_page() -> str:
    """Return standalone HTML for the interactive API Documentation page."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <!-- Google tag (gtag.js) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-P1SCVZ0V7T"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());

    gtag('config', 'G-P1SCVZ0V7T');
  </script>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>API Documentation & Developer Protocols — Open Supernova Catalog (sne.space)</title>
  <meta name="description" content="Official documentation for sne.space Open Supernova Catalog REST APIs, OACAPI endpoints, IVOA Cone Search, WebMCP, and FastMCP servers.">
  <link rel="stylesheet" href="/assets/ia.css">
  <link rel="ai-catalog" href="/.well-known/ai-catalog.json" type="application/json">
  <link rel="ard" href="/.well-known/ard.json" type="application/json">
  <style>
    :root {
      --bg-dark: #070a12;
      --card-bg: #0f172a;
      --card-border: #1e293b;
      --accent-cyan: #38bdf8;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-purple: #c084fc;
      --text-main: #f1f5f9;
      --text-dim: #94a3b8;
    }
    body {
      margin: 0;
      background: var(--bg-dark);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      line-height: 1.6;
    }
    header.cockpit-hdr {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      padding: 0.85rem 1.75rem;
      background: rgba(7, 10, 18, 0.95);
      border-bottom: 1px solid var(--card-border);
      position: sticky;
      top: 0;
      z-index: 1000;
      backdrop-filter: blur(12px);
    }
    .brand-link {
      font-size: 1.25rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      color: #fff;
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }
    .brand-logo-img {
      height: 38px;
      width: auto;
      vertical-align: middle;
      filter: drop-shadow(0 0 10px rgba(56, 189, 248, 0.4));
      transition: transform 0.2s ease, filter 0.2s ease;
    }
    .brand-logo-img:hover {
      transform: scale(1.04);
      filter: drop-shadow(0 0 16px rgba(56, 189, 248, 0.7));
    }
    .brand-badge {
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 2px 7px;
      border-radius: 4px;
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent-cyan);
      border: 1px solid rgba(56, 189, 248, 0.3);
    }
    .nav-links {
      display: flex;
      align-items: center;
      gap: 1.25rem;
    }
    .nav-links a {
      color: var(--text-dim);
      text-decoration: none;
      font-size: 0.9rem;
      font-weight: 500;
      transition: color 0.15s ease;
    }
    .nav-links a:hover, .nav-links a.active {
      color: #fff;
    }
    .docs-container {
      max-width: 1050px;
      margin: 0 auto;
      padding: 2.5rem 1.5rem 5rem;
    }
    .docs-hero {
      text-align: center;
      margin-bottom: 3.5rem;
    }
    .docs-hero h1 {
      font-size: 2.5rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      margin: 0 0 0.8rem;
      background: linear-gradient(135deg, #ffffff 40%, #94a3b8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .docs-hero p {
      font-size: 1.15rem;
      color: var(--text-dim);
      max-width: 700px;
      margin: 0 auto 1.5rem;
    }
    .hero-badges {
      display: flex;
      justify-content: center;
      flex-wrap: wrap;
      gap: 0.6rem;
    }
    .hero-badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 0.8rem;
      padding: 4px 12px;
      border-radius: 9999px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: #cbd5e1;
    }
    .endpoint-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 2rem;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }
    .endpoint-header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.75rem;
    }
    .method-badge {
      font-size: 0.75rem;
      font-weight: 800;
      padding: 3px 8px;
      border-radius: 4px;
      letter-spacing: 0.05em;
    }
    .method-get {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-emerald);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .endpoint-url {
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      font-size: 1.05rem;
      font-weight: 600;
      color: #fff;
    }
    .endpoint-desc {
      color: var(--text-dim);
      font-size: 0.95rem;
      margin: 0 0 1rem;
    }
    .code-block {
      background: #060911;
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 1rem 1.25rem;
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      font-size: 0.88rem;
      color: #e2e8f0;
      overflow-x: auto;
      margin-bottom: 1rem;
      position: relative;
    }
    .code-block code {
      background: none;
      padding: 0;
      color: inherit;
      font-family: inherit;
    }
    .code-comment {
      color: #64748b;
    }
    .code-param {
      color: var(--accent-cyan);
    }
    .code-val {
      color: var(--accent-emerald);
    }
    .section-title {
      font-size: 1.45rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin: 2.5rem 0 1rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      color: #fff;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 0.5rem;
    }
    .badge-protocol {
      font-size: 0.7rem;
      padding: 2px 8px;
      border-radius: 4px;
      background: rgba(192, 132, 252, 0.15);
      color: var(--accent-purple);
      border: 1px solid rgba(192, 132, 252, 0.3);
      font-weight: 600;
    }
    .specs-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
      margin-bottom: 1rem;
    }
    .specs-table th {
      text-align: left;
      padding: 0.6rem 0.8rem;
      background: rgba(255, 255, 255, 0.03);
      border-bottom: 1px solid var(--card-border);
      color: #cbd5e1;
    }
    .specs-table td {
      padding: 0.6rem 0.8rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      color: var(--text-dim);
    }
    .specs-table td code {
      font-size: 0.85rem;
      background: rgba(255, 255, 255, 0.05);
      padding: 2px 5px;
      border-radius: 4px;
      color: var(--accent-cyan);
    }
  </style>
</head>
<body>
  <header class="cockpit-hdr">
    <a href="/" class="brand-link" title="sne.space — The Open Supernova Catalog">
      <img src="/assets/img/logo-color.webp" alt="sne.space" class="brand-logo-img">
      <span class="brand-badge">Open Supernova Catalog</span>
    </a>
    <div class="nav-links">
      <a href="/">Catalog</a>
      <a href="/radar">Radar</a>
      <a href="/faq">FAQs</a>
      <a href="/api/docs" class="active">API & Docs</a>
      <a href="/about/">About</a>
      <a href="/download/">Download</a>
    </div>
  </header>

  <main class="docs-container">
    <div class="docs-hero">
      <h1>Developer APIs & Astronomical Protocols</h1>
      <p>High-cadence, zero-token REST, IVOA Cone Search, OACAPI endpoints, and FastMCP agents over 110,000+ supernovae from 1000 AD to 2026+.</p>
      <div class="hero-badges">
        <span class="hero-badge">⚡ Zero-Token Open Access</span>
        <span class="hero-badge">🌐 CORS Enabled</span>
        <span class="hero-badge">🔭 IVOA Simple Cone Search</span>
        <span class="hero-badge">🤖 AI Agent (FastMCP & WebMCP)</span>
      </div>
    </div>

    <!-- SECTION 1: CORE REST & INDIVIDUAL EVENT -->
    <h2 class="section-title">1. Single-Event REST Endpoints</h2>

    <div class="endpoint-card">
      <div class="endpoint-header">
        <span class="method-badge method-get">GET</span>
        <span class="endpoint-url">/sne/{event}.json &nbsp;or&nbsp; /api/{event}</span>
      </div>
      <p class="endpoint-desc">Fetches the complete canonical AstroCats JSON schema for a target event, including all aliases, photometry points, calibrated spectra arrays, host galaxy data, and ADS citations.</p>
      <table class="specs-table">
        <thead><tr><th>Parameter</th><th>Type</th><th>Description</th></tr></thead>
        <tbody>
          <tr><td><code>enrich</code></td><td>boolean</td><td>Pass <code>?enrich=1</code> to trigger real-time on-demand ingest from TNS, ZTF, and WISeREP before returning.</td></tr>
        </tbody>
      </table>
      <div class="code-block">
        <code><span class="code-comment"># Example: Fetch complete JSON for SN 2023ixf</span><br>
curl -s https://sne.space/sne/SN2023ixf.json | jq .</code>
      </div>
    </div>

    <div class="endpoint-card">
      <div class="endpoint-header">
        <span class="method-badge method-get">GET</span>
        <span class="endpoint-url">/{event}/photometry &nbsp;or&nbsp; /api/{event}/photometry</span>
      </div>
      <p class="endpoint-desc">Retrieves calibrated multi-band photometric time series. Supports both JSON schema and raw CSV table download via <code>?format=csv</code>.</p>
      <div class="code-block">
        <code><span class="code-comment"># Example: Download calibrated light curve as a Pandas-ready CSV table</span><br>
curl -s "https://sne.space/SN2023ixf/photometry?format=csv" > SN2023ixf_photometry.csv</code>
      </div>
    </div>

    <div class="endpoint-card">
      <div class="endpoint-header">
        <span class="method-badge method-get">GET</span>
        <span class="endpoint-url">/{event}/spectra &nbsp;and&nbsp; /{event}/spectra/data</span>
      </div>
      <p class="endpoint-desc">Extracts calibrated optical and NIR spectra. Use <code>/spectra/data</code> to get a pure two-column CSV stream of <code>wavelength,flux</code>.</p>
      <div class="code-block">
        <code><span class="code-comment"># Example: Stream raw spectral fluxes</span><br>
curl -s "https://sne.space/SN2023ixf/spectra/data" | head -n 10</code>
      </div>
    </div>

    <div class="endpoint-card">
      <div class="endpoint-header">
        <span class="method-badge method-get">GET</span>
        <span class="endpoint-url">/api/{event}/cutout &nbsp;or&nbsp; /sne/{event}/host.jpg</span>
      </div>
      <p class="endpoint-desc">Resolves celestial coordinates and issues a 302 redirect to high-resolution optical host galaxy cutouts (DESI Legacy DR10, Pan-STARRS1, or DSS2 Archival).</p>
      <div class="code-block">
        <code><span class="code-comment"># Example: Fetch 500x500 optical deep-field cutout</span><br>
curl -I "https://sne.space/api/SN2023ixf/cutout?layer=panstarrs&size=600"</code>
      </div>
    </div>

    <!-- SECTION 2: SPATIAL CONE SEARCH -->
    <h2 class="section-title">2. Spatial Index & IVOA Cone Search <span class="badge-protocol">IVOA SCS v1.4</span></h2>

    <div class="endpoint-card">
      <div class="endpoint-header">
        <span class="method-badge method-get">GET</span>
        <span class="endpoint-url">/api/cone &nbsp;or&nbsp; /cone</span>
      </div>
      <p class="endpoint-desc">Executes sub-millisecond 3D Cartesian spherical dot-product cone search over 110,000+ catalog objects. Returns standard IVOA VOTable XML or JSON.</p>
      <table class="specs-table">
        <thead><tr><th>Parameter</th><th>Type</th><th>Required</th><th>Description</th></tr></thead>
        <tbody>
          <tr><td><code>RA</code></td><td>float</td><td>Yes</td><td>Right Ascension in decimal degrees (0 to 360).</td></tr>
          <tr><td><code>DEC</code></td><td>float</td><td>Yes</td><td>Declination in decimal degrees (-90 to +90).</td></tr>
          <tr><td><code>SR</code></td><td>float</td><td>No</td><td>Search radius in decimal degrees (default: 0.1, clamped 0.0001 to 10.0).</td></tr>
          <tr><td><code>format</code></td><td>string</td><td>No</td><td><code>json</code> for JSON response, or <code>votable</code> / <code>xml</code> for standard IVOA VOTable.</td></tr>
        </tbody>
      </table>
      <div class="code-block">
        <code><span class="code-comment"># Example: Search 0.2° around M101 / SN 2023ixf</span><br>
curl -s "https://sne.space/api/cone?RA=210.77&DEC=54.27&SR=0.2&format=json" | jq .</code>
      </div>
    </div>

    <!-- SECTION 3: REAL-TIME RADAR API -->
    <h2 class="section-title">3. Real-Time Radar & Nightsky Observability API</h2>

    <div class="endpoint-card">
      <div class="endpoint-header">
        <span class="method-badge method-get">GET</span>
        <span class="endpoint-url">/api/radar.json</span>
      </div>
      <p class="endpoint-desc">Computes real-time observability telemetry, airmass curves, and photometric rate-of-change (dm/dt) across recent transients for major research observatories.</p>
      <div class="code-block">
        <code><span class="code-comment"># Example: Targets observable tonight from Keck Observatory</span><br>
curl -s "https://sne.space/api/radar.json?obs=keck&filter=rising" | jq .</code>
      </div>
    </div>

    <!-- SECTION 4: AI AGENTS & FAST MCP -->
    <h2 class="section-title">4. AI Agents & Model Context Protocol (MCP) <span class="badge-protocol">Anthropic / FastMCP</span></h2>

    <div class="endpoint-card">
      <div class="endpoint-header">
        <span class="method-badge method-get">FastMCP</span>
        <span class="endpoint-url">serve/mcp_server.py</span>
      </div>
      <p class="endpoint-desc">Native FastMCP server enabling AI assistants (Cursor, Claude Desktop, autonomous agents) to invoke catalog search, spectrum extraction, and cosmological distance integration directly.</p>
      <div class="code-block">
        <code><span class="code-comment"># In Claude Desktop or Cursor Settings (mcpServers configuration):</span><br>
{<br>
&nbsp;&nbsp;<span class="code-param">"mcpServers"</span>: {<br>
&nbsp;&nbsp;&nbsp;&nbsp;<span class="code-param">"sne-space"</span>: {<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="code-param">"command"</span>: <span class="code-val">"python3"</span>,<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="code-param">"args"</span>: [<span class="code-val">"/path/to/sne.space/serve/mcp_server.py"</span>]<br>
&nbsp;&nbsp;&nbsp;&nbsp;}<br>
&nbsp;&nbsp;}<br>
}</code>
      </div>
    </div>

    <!-- SECTION 5: REAL-TIME TELEMETRY & STATS -->
    <h2 class="section-title">5. Real-Time Telemetry & API Usage Stats</h2>

    <div class="endpoint-card">
      <div class="endpoint-header">
        <span class="method-badge method-get">GET</span>
        <span class="endpoint-url">/api/stats &nbsp;and&nbsp; /api-count.php</span>
      </div>
      <p class="endpoint-desc">Live observational telemetry tracking active API throughput, unique callers, top queried supernovae, and user agent distributions. <code>/api-count.php</code> provides drop-in compatibility with the original OACAPI badge counter.</p>
      <div class="code-block">
        <code><span class="code-comment"># Example: Inspect live traffic telemetry and top queried supernovae</span><br>
curl -s https://sne.space/api/stats | jq .</code>
      </div>
    </div>
  </main>
  <!-- WebMCP In-Browser Agentic Tools -->
  <script src="/assets/webmcp.js"></script>
</body>
</html>
"""
