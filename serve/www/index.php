<?php
/**
 * Open Supernova Catalog — local Transient Table homepage (S1.2).
 * No WordPress; loads vendor Transient Table with historical paths.
 */
declare(strict_types=1);

$ttPath = __DIR__ . '/wp-content/plugins/transient-table/tt.dat';
if (!is_file($ttPath)) {
    $ttPath = __DIR__ . '/wp-content/plugins/transient-table/tt.sne.dat';
}
if (!is_file($ttPath)) {
    $ttPath = dirname(__DIR__, 2) . '/vendor/transient-table/tt.sne.dat';
}
if (!is_file($ttPath)) {
    $raw = "sne\nsupernovae\nsne\nsne\nalias,maxdate,velocity,maxabsmag,masses,hostra,hostdec,hostoffsetang,hostoffsetdist,references,instruments,ebv,lumdist,altitude,azimuth,airmass,skybrightness,discoverer\nmaxdate,discoverdate\ndownload,spectralink,photolink,radiolink,xraylink\nphotolink,spectralink,radiolink,xraylink\nphotolink\n10,50,250\nSNe\nSupernova";
} else {
    $raw = (string)file_get_contents($ttPath);
}
$tt = explode("\n", $raw);
$stem = trim($tt[0]);
$modu = trim($tt[1]);
$subd = trim($tt[2]);
$ghpr = trim($tt[3]);
$invi = '"' . implode('","', explode(",", trim($tt[4]))) . '"';
$nowr = '"' . implode('","', explode(",", trim($tt[5]))) . '"';
$nwnm = '"' . implode('","', explode(",", trim($tt[6]))) . '"';
$revo = '"' . implode('","', explode(",", trim($tt[7]))) . '"';
$ocol = trim($tt[8]);
$plen = trim($tt[9]);
$shrt = trim($tt[10]);
$sing = trim($tt[11]);
$outp = 'astrocats/astrocats/' . $modu . '/output/';

// Stub WP helpers used by the plugin enqueue block (unused here).
if (!function_exists('is_front_page')) {
    function is_front_page(): bool { return true; }
}
if (!function_exists('is_page')) {
    function is_page($x = null): bool { return false; }
}
if (!function_exists('is_search')) {
    function is_search(): bool { return false; }
}
if (!function_exists('plugins_url')) {
    function plugins_url(string $path = '', string $file = ''): string {
        return '/wp-content/plugins/transient-table/' . ltrim($path, '/');
    }
}
if (!function_exists('wp_enqueue_style')) {
    function wp_enqueue_style(...$args): void {}
}
if (!function_exists('wp_enqueue_script')) {
    function wp_enqueue_script(...$args): void {}
}
if (!function_exists('add_action')) {
    function add_action(...$args): void {}
}

require __DIR__ . '/wp-content/plugins/transient-table/transient-table.php';

?><!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open Supernova Catalog — sne.space</title>
<meta name="description" content="Comprehensive astrophysical archive containing multi-band light curves, calibrated spectra, and metadata for over 110,000 supernovae from 1000 AD to 2026+.">
<link rel="ai-catalog" href="/.well-known/ai-catalog.json" type="application/ai-catalog+json">
<link rel="describedby" href="/llms.txt" type="text/markdown">
<link rel="stylesheet" href="https://cdn.datatables.net/1.10.16/css/jquery.dataTables.min.css" media="print" onload="this.media='all'">
<link rel="stylesheet" href="https://cdn.datatables.net/v/dt/b-1.5.2/b-colvis-1.5.2/b-html5-1.5.2/r-2.2.2/sc-1.5.0/sl-1.2.6/datatables.min.css" media="print" onload="this.media='all'">
<link rel="stylesheet" href="/wp-content/plugins/transient-table/transient-table.sne.css" media="print" onload="this.media='all'">
<noscript>
<link rel="stylesheet" href="https://cdn.datatables.net/1.10.16/css/jquery.dataTables.min.css">
<link rel="stylesheet" href="https://cdn.datatables.net/v/dt/b-1.5.2/b-colvis-1.5.2/b-html5-1.5.2/r-2.2.2/sc-1.5.0/sl-1.2.6/datatables.min.css">
<link rel="stylesheet" href="/wp-content/plugins/transient-table/transient-table.sne.css">
</noscript>
<style>
  :root {
    --bg-space: #070a12;
    --surface-card: #0d1424;
    --border-subtle: #1e293b;
    --border-bright: #334155;
    --accent-cyan: #38bdf8;
    --accent-blue: #2563eb;
    --accent-gold: #f59e0b;
    --text-white: #f8fafc;
    --text-slate: #94a3b8;
    --text-muted: #64748b;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    background: var(--bg-space);
    background-image: 
      radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.04) 0%, transparent 40%),
      radial-gradient(circle at 85% 80%, rgba(139, 92, 246, 0.04) 0%, transparent 40%);
    color: var(--text-white);
    min-height: 100vh;
  }
  /* Top Navigation Bar */
  header.global-nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.85rem 1.75rem;
    background: rgba(7, 10, 18, 0.9);
    border-bottom: 1px solid var(--border-subtle);
    position: sticky;
    top: 0;
    z-index: 1000;
    backdrop-filter: blur(14px);
  }
  .brand-group {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .brand-title {
    font-size: 1.35rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: #fff;
    text-decoration: none;
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }
  .brand-logo-img {
    height: 42px;
    width: auto;
    display: inline-block;
    vertical-align: middle;
    filter: drop-shadow(0 0 12px rgba(56, 189, 248, 0.45));
    transition: transform 0.2s ease, filter 0.2s ease;
  }
  .brand-logo-img:hover {
    transform: scale(1.04);
    filter: drop-shadow(0 0 18px rgba(56, 189, 248, 0.75));
  }
  .brand-pill {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 3px 8px;
    border-radius: 9999px;
    background: rgba(56, 189, 248, 0.15);
    color: var(--accent-cyan);
    border: 1px solid rgba(56, 189, 248, 0.35);
  }
  .nav-menu {
    display: flex;
    align-items: center;
    gap: 1.25rem;
  }
  .nav-menu a {
    color: var(--text-slate);
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 500;
    transition: color 0.15s ease;
  }
  .nav-menu a:hover, .nav-menu a.active {
    color: #fff;
  }
  .nav-action-btn {
    padding: 5px 12px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
    color: #fff !important;
  }
  .nav-action-btn:hover {
    background: rgba(255, 255, 255, 0.14);
  }

  /* Catalog Hero Section */
  .catalog-hero {
    padding: 2.25rem 1.75rem 1.5rem;
    max-width: 1400px;
    margin: 0 auto;
  }
  .hero-headline {
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -0.035em;
    margin: 0 0 0.5rem;
    color: #ffffff;
  }
  .hero-subtext {
    font-size: 1.05rem;
    color: var(--text-slate);
    max-width: 820px;
    margin: 0 0 1.5rem;
    line-height: 1.5;
  }
  .stats-telemetry-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 1rem;
    margin-bottom: 1.75rem;
  }
  .telemetry-card {
    background: var(--surface-card);
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    padding: 1rem 1.25rem;
  }
  .telemetry-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #cbd5e1;
    margin-bottom: 0.25rem;
  }
  .telemetry-val {
    font-size: 1.55rem;
    font-weight: 800;
    color: #fff;
    letter-spacing: -0.02em;
  }
  .telemetry-desc {
    font-size: 0.75rem;
    color: #cbd5e1;
    margin-top: 0.2rem;
  }

  /* Landmark Quick Jumps */
  .landmark-bar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 1.5rem;
    padding: 0.75rem 1rem;
    background: rgba(13, 20, 36, 0.6);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    font-size: 0.85rem;
  }
  .landmark-label {
    color: var(--accent-gold);
    font-weight: 700;
    margin-right: 0.25rem;
  }
  .landmark-chip {
    padding: 3px 9px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: #cbd5e1;
    text-decoration: none;
    font-size: 0.82rem;
    font-weight: 500;
    transition: all 0.15s ease;
  }
  .landmark-chip:hover {
    background: rgba(56, 189, 248, 0.15);
    border-color: rgba(56, 189, 248, 0.4);
    color: var(--accent-cyan);
  }

  /* DataTables Container Styling & Theme Overrides */
  .catalog-table-wrap {
    max-width: 1400px;
    margin: 0 auto;
    padding: 0 1.75rem 5rem;
  }
  .lci, .sci, .rci, .xci, .dci, .eci {
    filter: invert(0.9) hue-rotate(180deg) brightness(1.2);
    border-radius: 4px;
    background-color: transparent !important;
  }
  #example tbody td {
    color: #e2e8f0;
  }
  #example_wrapper {
    background: var(--surface-card);
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    padding: 1.25rem;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
  }
  table.dataTable thead th, table.dataTable tfoot th {
    background: #090e1a !important;
    color: #cbd5e1 !important;
    border-color: var(--border-subtle) !important;
    font-size: 0.85rem;
  }
  table.dataTable tbody tr {
    background-color: #0b1120 !important;
    color: #e2e8f0 !important;
  }
  table.dataTable tbody tr:hover {
    background-color: #131c33 !important;
  }
  table.dataTable tbody tr.odd {
    background-color: #0d1424 !important;
  }
  table.dataTable tbody td {
    border-color: rgba(255, 255, 255, 0.04) !important;
    font-size: 0.88rem;
  }
  .dataTables_filter input, .dataTables_length select, .colsearch {
    background: #070a12 !important;
    border: 1px solid var(--border-bright) !important;
    color: #f1f5f9 !important;
    border-radius: 6px !important;
    padding: 5px 8px !important;
    font-size: 0.82rem !important;
  }
  .dataTables_filter input:focus, .colsearch:focus {
    outline: none !important;
    border-color: var(--accent-cyan) !important;
  }
  .dt-button {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    color: #cbd5e1 !important;
    border-radius: 6px !important;
    font-size: 0.8rem !important;
    padding: 6px 12px !important;
  }
  .dt-button:hover {
    background: #334155 !important;
    color: #fff !important;
  }
  .dataTables_info, .dataTables_paginate {
    color: var(--text-slate) !important;
    font-size: 0.85rem;
    margin-top: 0.75rem;
  }
  .paginate_button {
    background: #0d1424 !important;
    border: 1px solid var(--border-subtle) !important;
    color: #cbd5e1 !important;
    border-radius: 4px !important;
  }
  .paginate_button.current {
    background: var(--accent-blue) !important;
    color: #fff !important;
    border-color: var(--accent-blue) !important;
  }
  #advancedtab {
    background: #090e1a !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px;
    margin-top: 1rem;
    color: var(--text-slate) !important;
  }
  #advancedtab td {
    border-color: var(--border-subtle) !important;
  }
  .coordfield, .obssel {
    background: #070a12 !important;
    border: 1px solid var(--border-bright) !important;
    color: #f1f5f9 !important;
    border-radius: 4px;
    padding: 3px 6px;
  }
  #locbutt {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    color: #cbd5e1 !important;
    border-radius: 4px;
    cursor: pointer;
  }
  #locbutt:hover {
    background: #334155 !important;
    color: #fff !important;
  }
  a { color: var(--accent-cyan); text-decoration: none; }
  a:hover { text-decoration: underline; }
  html, body { max-width: 100%; overflow-x: hidden; }
  .nav-toggle-input { position: absolute; opacity: 0; pointer-events: none; }
  .nav-toggle {
    display: none;
    background: #1e293b;
    color: #fff;
    border: 1px solid var(--border-bright);
    border-radius: 6px;
    padding: 0.4rem 0.75rem;
    font-weight: 700;
    cursor: pointer;
  }
  .recent-block { margin-bottom: 1.5rem; }
  .recent-head { margin: 0 0 0.35rem; font-size: 1.15rem; }
  .recent-note { margin: 0 0 0.85rem; color: var(--text-slate); font-size: 0.88rem; }
  .recent-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.75rem;
  }
  .recent-card {
    display: block;
    background: var(--surface-card);
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    padding: 0.9rem 1rem;
    color: inherit;
    text-decoration: none;
  }
  .recent-card:hover { border-color: rgba(56, 189, 248, 0.55); text-decoration: none; }
  .recent-name { font-weight: 800; font-size: 1.05rem; }
  .recent-age { color: #7dd3fc; font-size: 0.78rem; font-weight: 700; }
  .recent-meta { color: #cbd5e1; font-size: 0.82rem; margin-top: 0.35rem; }
  .hdr-search-form {
    display: flex;
    align-items: center;
    background: rgba(15, 23, 42, 0.75);
    border: 1px solid var(--border-bright);
    border-radius: 6px;
    overflow: hidden;
    max-width: 340px;
    flex: 1;
    margin: 0 1rem;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }
  .hdr-search-form:focus-within {
    border-color: #38bdf8;
    box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
  }
  .hdr-search-form input {
    background: transparent;
    border: none;
    outline: none;
    color: #f1f5f9;
    font-size: 0.85rem;
    padding: 0.35rem 0.65rem;
    width: 100%;
  }
  .hdr-search-form button {
    background: transparent;
    border: none;
    color: #94a3b8;
    padding: 0.35rem 0.6rem;
    cursor: pointer;
  }
  @media (max-width: 860px) {
    header.global-nav { flex-wrap: wrap; padding: 0.7rem 0.9rem; gap: 0.5rem; }
    .brand-pill { display: none; }
    .nav-toggle { display: inline-flex; margin-left: auto; }
    .nav-menu {
      display: none;
      width: 100%;
      flex-direction: column;
      align-items: flex-start;
      gap: 0.7rem;
      padding: 0.35rem 0 0.2rem;
    }
    .nav-toggle-input:checked ~ .nav-menu { display: flex; }
    .catalog-hero, .catalog-table-wrap { padding-left: 0.9rem; padding-right: 0.9rem; }
    .hero-headline { font-size: 1.7rem; }
    .catalog-table-wrap, #example_wrapper { max-width: 100%; overflow-x: auto; }
  }
</style>
</head>
<body>
  <header class="global-nav">
    <div class="brand-group">
      <a href="/" class="brand-title" title="sne.space — The Open Supernova Catalog">
        <img src="/assets/img/logo-color.webp" alt="sne.space" class="brand-logo-img" width="125" height="42" decoding="async">
      </a>
      <span class="brand-pill">Open Supernova Catalog</span>
    </div>
    <form class="hdr-search-form" action="/" method="GET" 
          toolname="search_supernovae" 
          tool-name="search_supernovae" 
          tooldescription="Search 110,000+ supernovae and transients by IAU designation, name, or survey alias" 
          tool-description="Search 110,000+ supernovae and transients by IAU designation, name, or survey alias" 
          role="search" 
          onsubmit="event.preventDefault(); var q=this.q.value.trim(); if(q) window.location.href='/sne/'+encodeURIComponent(q)+'/';">
      <input type="search" name="q" 
             placeholder="Search 110k+ supernovae (e.g. SN 2023ixf)..." 
             aria-label="Search supernovae" 
             toolparamdescription="Supernova IAU designation, catalog name, or survey alias (e.g. SN 2023ixf, SN 1987A, SN 2011fe, AT2024nrb)" 
             tool-param-description="Supernova IAU designation, catalog name, or survey alias (e.g. SN 2023ixf, SN 1987A, SN 2011fe, AT2024nrb)" 
             autocomplete="off" required>
      <button type="submit" aria-label="Submit search">🔍</button>
    </form>
    <input class="nav-toggle-input" type="checkbox" id="home-nav">
    <label class="nav-toggle" for="home-nav">Menu</label>
    <nav class="nav-menu">
      <a href="/" class="active">Catalog</a>
      <a href="/radar">Radar</a>
      <a href="/faq">FAQs</a>
      <a href="/api/docs">API & Docs</a>
      <a href="/about/">About</a>
      <a href="/download/">Download</a>
      <a href="/statistics/">Stats</a>
    </nav>
  </header>

  <main>
    <section class="catalog-hero">
      <h1 class="hero-headline">The Open Supernova Catalog</h1>
      <p class="hero-subtext">A community-curated astronomical repository indexing 110,222+ explosive transients, multi-band optical light curves, and calibrated spectra from 1000 AD to 2026+.</p>

      <div class="stats-telemetry-row">
        <div class="telemetry-card">
          <div class="telemetry-label">Total Transients</div>
          <div class="telemetry-val">110,222</div>
          <div class="telemetry-desc">Historical & modern survey events</div>
        </div>
        <div class="telemetry-card">
          <div class="telemetry-label">Calibrated Spectra</div>
          <div class="telemetry-val">20,965</div>
          <div class="telemetry-desc">Multi-epoch spectroscopic time series</div>
        </div>
        <div class="telemetry-card">
          <div class="telemetry-label">Photometric Epochs</div>
          <div class="telemetry-val">673,154</div>
          <div class="telemetry-desc">Multi-band UV, optical & NIR observations</div>
        </div>
        <div class="telemetry-card">
          <div class="telemetry-label">API & Integrations</div>
          <div class="telemetry-val">REST + MCP</div>
          <div class="telemetry-desc">Zero-token API, IVOA cone search & AI tools</div>
        </div>
      </div>

      <?php
        $recentPath = __DIR__ . '/assets/recent-events.json';
        $recent = is_file($recentPath) ? json_decode((string)file_get_contents($recentPath), true) : [];
        $today = new DateTimeImmutable('today');
      ?>
      <div class="recent-block">
        <h2 class="recent-head">Newest classified supernovae on file</h2>
        <p class="recent-note">Ages are counted from today, <?php echo $today->format('F j, Y'); ?>, using each event's discovery date from the Transient Name Server.</p>
        <div class="recent-grid">
          <?php if (is_array($recent)) foreach ($recent as $ev):
            $when = DateTimeImmutable::createFromFormat('!Y-m-d', (string)$ev['date']) ?: $today;
            $age = $today->diff($when)->days;
            $nm = htmlspecialchars((string)$ev['name'], ENT_QUOTES);
            $ty = htmlspecialchars((string)$ev['type'], ENT_QUOTES);
            $who = htmlspecialchars((string)$ev['discoverer'], ENT_QUOTES);
          ?>
          <a class="recent-card" href="/sne/<?php echo rawurlencode((string)$ev['name']); ?>/">
            <div class="recent-name"><?php echo $nm; ?></div>
            <div class="recent-age"><?php echo (int)$age; ?> days ago</div>
            <div class="recent-meta">Type <?php echo $ty; ?> · <?php echo htmlspecialchars((string)$ev['date'], ENT_QUOTES); ?><br><?php echo $who; ?></div>
          </a>
          <?php endforeach; ?>
        </div>
      </div>

      <div class="landmark-bar">
        <span class="landmark-label">⭐ Benchmark Landmarks:</span>
        <a class="landmark-chip" href="/sne/SN2023ixf/">SN 2023ixf (Pinwheel)</a>
        <a class="landmark-chip" href="/sne/SN1987A/">SN 1987A (LMC)</a>
        <a class="landmark-chip" href="/sne/SN2011fe/">SN 2011fe (Type Ia)</a>
        <a class="landmark-chip" href="/sne/SN2014J/">SN 2014J (M82)</a>
        <a class="landmark-chip" href="/sne/SN1054/">SN 1054 (Crab Nebula)</a>
        <a class="landmark-chip" href="/sne/SN1572/">SN 1572 (Tycho)</a>
        <a class="landmark-chip" href="/sne/SN1604/">SN 1604 (Kepler)</a>
        <a class="landmark-chip" href="/sne/SN2024nrb/">SN 2024nrb (ATLAS)</a>
      </div>
    </section>

    <div class="catalog-table-wrap">
      <?php transient_catalog(false); ?>
    </div>
  </main>
<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
<script src="https://cdn.datatables.net/1.10.16/js/jquery.dataTables.min.js"></script>
<script src="https://cdn.datatables.net/v/dt/b-1.5.2/b-colvis-1.5.2/b-html5-1.5.2/r-2.2.2/sc-1.5.0/sl-1.2.6/datatables.min.js"></script>
<script src="/wp-content/plugins/transient-table/transient-table.js"></script>
<script src="/wp-content/plugins/transient-table/suncalc.js"></script>
<?php datatables_functions(); ?>
<script>
(function() {
  function registerWebMCP() {
    var ctx = (window.document && window.document.modelContext) || 
              (window.navigator && window.navigator.modelContext) || null;
    if (!ctx || typeof ctx.registerTool !== 'function') return;

    try {
      ctx.registerTool({
        name: "search_supernovae",
        description: "Search 110,000+ supernovae and transients by IAU designation, name, or survey alias (e.g. SN 2023ixf, SN 1987A, SN 2011fe, AT2024nrb)",
        inputSchema: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description: "Supernova designation, IAU name, or survey alias"
            }
          },
          required: ["query"]
        },
        annotations: { readOnlyHint: true },
        execute: async function(args) {
          var q = (args && (args.query || args.q)) || "";
          if (!q) return { error: "Missing required query parameter" };
          return { status: "success", query: q, url: "/sne/" + encodeURIComponent(q.trim()) + "/" };
        }
      });

      ctx.registerTool({
        name: "get_supernova_data",
        description: "Fetch complete astrophysical metadata, coordinates, classification, redshift, and discovery details for a specific supernova in JSON format",
        inputSchema: {
          type: "object",
          properties: {
            name: {
              type: "string",
              description: "Supernova name or IAU designation (e.g. SN 2023ixf, SN 1987A, SN 2011fe)"
            }
          },
          required: ["name"]
        },
        annotations: { readOnlyHint: true },
        execute: async function(args) {
          var name = (args && (args.name || args.q)) || "";
          if (!name) return { error: "Missing required supernova name" };
          try {
            var res = await fetch("/sne/" + encodeURIComponent(name.trim()) + ".json");
            if (!res.ok) return { error: "Supernova not found", name: name };
            var data = await res.json();
            return { status: "success", name: name, data: data };
          } catch (err) {
            return { error: String(err) };
          }
        }
      });

      ctx.registerTool({
        name: "cone_search",
        description: "Spatial cone search for supernovae within an angular radius around celestial coordinates (Right Ascension & Declination in degrees, J2000)",
        inputSchema: {
          type: "object",
          properties: {
            ra: {
              type: "number",
              description: "Right Ascension in decimal degrees (0 to 360)"
            },
            dec: {
              type: "number",
              description: "Declination in decimal degrees (-90 to +90)"
            },
            radius_arcsec: {
              type: "number",
              description: "Search radius in arcseconds (default: 300)"
            }
          },
          required: ["ra", "dec"]
        },
        annotations: { readOnlyHint: true },
        execute: async function(args) {
          if (!args || typeof args.ra !== 'number' || typeof args.dec !== 'number') {
            return { error: "Missing required 'ra' and 'dec' coordinate arguments" };
          }
          var rad = args.radius_arcsec || 300;
          try {
            var res = await fetch("/api/cone?ra=" + encodeURIComponent(args.ra) + "&dec=" + encodeURIComponent(args.dec) + "&radius=" + encodeURIComponent(rad));
            if (!res.ok) return { error: "Cone search request failed" };
            return await res.json();
          } catch (err) {
            return { error: String(err) };
          }
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
</script>
</body>
</html>
