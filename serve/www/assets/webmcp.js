/**
 * sne.space WebMCP Standard Implementation
 * Uses standard W3C WebML / Chrome WebMCP API (document.modelContext.registerTool).
 * No mocks, no monkeypatching, no private shim registries.
 */
(function() {
  'use strict';

  var mc = (typeof document !== 'undefined' && document.modelContext) || 
           (typeof navigator !== 'undefined' && navigator.modelContext);

  if (!mc || typeof mc.registerTool !== 'function') {
    // Native browser WebMCP API is not active in this environment
    return;
  }

  function register(tool) {
    try {
      var p = mc.registerTool(tool);
      if (p && typeof p.then === 'function') {
        p.then(function() {
          console.log("[WebMCP registered]", tool.name);
        }).catch(function(err) {
          console.error("[WebMCP registration failed]", tool.name, err);
        });
      } else {
        console.log("[WebMCP registered]", tool.name);
      }
    } catch (err) {
      console.error("[WebMCP registration threw synchronously]", tool.name, err);
    }
  }

  // 1. search_supernovae
  register({
    name: "search_supernovae",
    title: "Search Supernovae",
    description: "Search 110,000+ supernovae and transients by IAU designation, name, or survey alias (e.g. SN 2023ixf, SN 1987A, SN 2011fe, AT2024nrb).",
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
      if (!q) return JSON.stringify({ error: "Missing required query parameter" });
      var res = await fetch("/api/search?q=" + encodeURIComponent(q.trim()));
      return JSON.stringify(await res.json());
    }
  });

  // 2. get_supernova
  register({
    name: "get_supernova",
    title: "Get Supernova Data",
    description: "Retrieve complete astrophysical dossier for a supernova, including classification, redshift, coordinates, host galaxy, discovery date, peak magnitude, and bibliography.",
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
      if (!name) return JSON.stringify({ error: "Missing required supernova name" });
      var res = await fetch("/sne/" + encodeURIComponent(name.trim()) + ".json");
      return JSON.stringify(await res.json());
    }
  });

  // 3. search_by_coordinates (Cone Search)
  register({
    name: "search_by_coordinates",
    title: "Search by Coordinates (Cone Search)",
    description: "Cone search for supernovae and transients within an angular radius around J2000 celestial coordinates (Right Ascension and Declination in decimal degrees).",
    inputSchema: {
      type: "object",
      properties: {
        ra: {
          type: "number",
          description: "Right Ascension in decimal degrees (0.0 to 360.0)"
        },
        dec: {
          type: "number",
          description: "Declination in decimal degrees (-90.0 to +90.0)"
        },
        radius_arcmin: {
          type: "number",
          description: "Search radius in arcminutes (default: 5.0, max: 60.0)"
        }
      },
      required: ["ra", "dec"]
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      if (!args || typeof args.ra !== 'number' || typeof args.dec !== 'number') {
        return JSON.stringify({ error: "Missing required 'ra' and 'dec' coordinate arguments" });
      }
      var rad = args.radius_arcmin || 5.0;
      var res = await fetch("/api/cone?ra=" + encodeURIComponent(args.ra) + "&dec=" + encodeURIComponent(args.dec) + "&radius=" + encodeURIComponent(rad) + "&format=json");
      return JSON.stringify(await res.json());
    }
  });

  // 4. search_by_type
  register({
    name: "search_by_type",
    title: "Search by Astrophysical Type",
    description: "Find supernovae matching a specific astrophysical classification type (e.g. 'Ia', 'II-P', 'IIn', 'SLSN-I', 'Ia-91T', 'TDE').",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          description: "Astrophysical classification type (e.g. Ia, II-P, IIn, SLSN)"
        },
        limit: {
          type: "number",
          description: "Maximum results to return (default: 25, max: 100)"
        }
      },
      required: ["type"]
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var t = (args && args.type) || "";
      var limit = (args && args.limit) || 25;
      if (!t) return JSON.stringify({ error: "Missing required 'type' argument" });
      var res = await fetch("/api/by-type?type=" + encodeURIComponent(t) + "&limit=" + encodeURIComponent(limit));
      return JSON.stringify(await res.json());
    }
  });

  // 5. get_recent_discoveries
  register({
    name: "get_recent_discoveries",
    title: "Get Recent Discoveries",
    description: "Fetch latest discovered supernovae and active transient alerts from the last 30 days, sorted by discovery date.",
    inputSchema: {
      type: "object",
      properties: {
        limit: {
          type: "number",
          description: "Maximum number of recent transients to return (default: 25)"
        }
      }
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var limit = (args && args.limit) || 25;
      var res = await fetch("/api/recent?limit=" + encodeURIComponent(limit));
      if (!res.ok) res = await fetch("/api/radar.json");
      return JSON.stringify(await res.json());
    }
  });

  // 6. get_photometry
  register({
    name: "get_photometry",
    title: "Get Photometric Light Curve",
    description: "Retrieve calibrated multi-band photometric light curve observations (time, magnitude, error, filter band, telescope/observer) for a supernova.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Supernova name or IAU designation (e.g. SN 2023ixf, SN 2011fe)"
        },
        format: {
          type: "string",
          description: "Response format ('json' or 'csv', default: 'json')",
          enum: ["json", "csv"]
        }
      },
      required: ["name"]
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var name = (args && (args.name || args.q)) || "";
      var fmt = (args && args.format) || "json";
      if (!name) return JSON.stringify({ error: "Missing required supernova name" });
      var endpoint = "/" + encodeURIComponent(name.trim()) + "/photometry" + (fmt === "csv" ? "?format=csv" : "");
      var res = await fetch(endpoint);
      if (fmt === "csv") {
        return await res.text();
      }
      return JSON.stringify(await res.json());
    }
  });

  // 7. get_spectra
  register({
    name: "get_spectra",
    title: "Get Calibrated Spectra",
    description: "Retrieve calibrated 1D optical spectra (wavelength in Angstroms, flux, epoch/phase, instrument) for a supernova.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Supernova name or IAU designation (e.g. SN 2023ixf, SN 1987A)"
        }
      },
      required: ["name"]
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var name = (args && (args.name || args.q)) || "";
      if (!name) return JSON.stringify({ error: "Missing required supernova name" });
      var res = await fetch("/" + encodeURIComponent(name.trim()) + "/spectra");
      return JSON.stringify(await res.json());
    }
  });

})();
