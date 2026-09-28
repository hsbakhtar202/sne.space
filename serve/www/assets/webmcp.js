/**
 * sne.space WebMCP (Model Context Protocol for Web) Standard Implementation
 * Compatible with Chrome 149+ WebMCP Origin Trial and W3C WebMCP Community Group Draft.
 * Exposes canonical document.modelContext and navigator.modelContext compatibility alias.
 */
(function() {
  'use strict';

  var registeredTools = [];

  function initModelContext(target) {
    if (!target) return;
    if (!target.modelContext) {
      target.modelContext = {};
    }
    var mc = target.modelContext;
    var nativeRegister = typeof mc.registerTool === 'function' ? mc.registerTool : null;

    mc.registerTool = async function(toolDesc, options) {
      if (nativeRegister) {
        try { await nativeRegister.call(mc, toolDesc, options); } catch(e) {}
      }
      var existingIdx = registeredTools.findIndex(function(t) { return t.name === toolDesc.name; });
      var toolObj = Object.assign({
        origin: (typeof window !== 'undefined' && window.location) ? window.location.origin : 'https://sne.space',
        window: typeof window !== 'undefined' ? window : null,
        parameters: toolDesc.inputSchema || toolDesc.parameters || { type: "object", properties: {} },
        inputSchema: toolDesc.inputSchema || toolDesc.parameters || { type: "object", properties: {} },
        returnType: toolDesc.outputSchema ? (toolDesc.outputSchema.type || "object") : "object"
      }, toolDesc);

      if (existingIdx >= 0) {
        registeredTools[existingIdx] = toolObj;
      } else {
        registeredTools.push(toolObj);
      }
      return toolObj;
    };

    if (typeof mc.getTools !== 'function') {
      mc.getTools = async function(options) {
        return registeredTools.slice();
      };
    }

    if (typeof mc.listTools !== 'function') {
      mc.listTools = async function() {
        return registeredTools.slice();
      };
    }

    if (typeof mc.executeTool !== 'function') {
      mc.executeTool = async function(toolOrName, input, options) {
        var name = typeof toolOrName === 'string' ? toolOrName : (toolOrName && toolOrName.name);
        var tool = registeredTools.find(function(t) { return t.name === name; });
        if (!tool || typeof tool.execute !== 'function') {
          throw new Error("WebMCP Tool '" + name + "' not found or not executable");
        }
        var args = typeof input === 'string' ? JSON.parse(input) : (input || {});
        return await tool.execute(args);
      };
    }
  }

  if (typeof document !== 'undefined') initModelContext(document);
  if (typeof navigator !== 'undefined') initModelContext(navigator);
  if (typeof window !== 'undefined') initModelContext(window);

  var targetCtx = (typeof document !== 'undefined' && document.modelContext) || 
                  (typeof navigator !== 'undefined' && navigator.modelContext);

  if (targetCtx && typeof targetCtx.registerTool === 'function') {

    // Helper to format response into standard MCP Content array
    function mcpResult(data) {
      return {
        content: [
          {
            type: "text",
            text: typeof data === 'string' ? data : JSON.stringify(data, null, 2)
          }
        ]
      };
    }

    // 1. search_supernovae
    targetCtx.registerTool({
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
        if (!q) return mcpResult({ error: "Missing required query parameter" });
        try {
          var res = await fetch("/api/search?q=" + encodeURIComponent(q.trim()));
          if (!res.ok) {
            return mcpResult({
              query: q,
              url: "/sne/" + encodeURIComponent(q.trim()) + "/",
              status: "fallback"
            });
          }
          var data = await res.json();
          return mcpResult(data);
        } catch (err) {
          return mcpResult({
            query: q,
            url: "/sne/" + encodeURIComponent(q.trim()) + "/",
            error: String(err)
          });
        }
      }
    });

    // 2. get_supernova
    targetCtx.registerTool({
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
        if (!name) return mcpResult({ error: "Missing required supernova name" });
        try {
          var res = await fetch("/sne/" + encodeURIComponent(name.trim()) + ".json");
          if (!res.ok) return mcpResult({ error: "Supernova not found: " + name, status: res.status });
          var data = await res.json();
          return mcpResult(data);
        } catch (err) {
          return mcpResult({ error: String(err) });
        }
      }
    });

    // 3. search_by_coordinates (Cone Search)
    targetCtx.registerTool({
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
          return mcpResult({ error: "Missing required 'ra' and 'dec' coordinate arguments" });
        }
        var rad = args.radius_arcmin || 5.0;
        try {
          var res = await fetch("/api/cone?ra=" + encodeURIComponent(args.ra) + "&dec=" + encodeURIComponent(args.dec) + "&radius=" + encodeURIComponent(rad) + "&format=json");
          if (!res.ok) return mcpResult({ error: "Cone search request failed", status: res.status });
          var data = await res.json();
          return mcpResult(data);
        } catch (err) {
          return mcpResult({ error: String(err) });
        }
      }
    });

    // 4. search_by_type
    targetCtx.registerTool({
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
        if (!t) return mcpResult({ error: "Missing required 'type' argument" });
        try {
          var res = await fetch("/api/by-type?type=" + encodeURIComponent(t) + "&limit=" + encodeURIComponent(limit));
          if (!res.ok) return mcpResult({ error: "Type search failed", status: res.status });
          var data = await res.json();
          return mcpResult(data);
        } catch (err) {
          return mcpResult({ error: String(err) });
        }
      }
    });

    // 5. get_recent_discoveries
    targetCtx.registerTool({
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
        try {
          var res = await fetch("/api/recent?limit=" + encodeURIComponent(limit));
          if (!res.ok) {
            res = await fetch("/api/radar.json");
          }
          if (!res.ok) return mcpResult({ error: "Failed to fetch recent discoveries", status: res.status });
          var data = await res.json();
          return mcpResult(data);
        } catch (err) {
          return mcpResult({ error: String(err) });
        }
      }
    });

    // 6. get_photometry
    targetCtx.registerTool({
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
        if (!name) return mcpResult({ error: "Missing required supernova name" });
        try {
          var endpoint = "/" + encodeURIComponent(name.trim()) + "/photometry" + (fmt === "csv" ? "?format=csv" : "");
          var res = await fetch(endpoint);
          if (!res.ok) return mcpResult({ error: "Photometry not found for " + name, status: res.status });
          if (fmt === "csv") {
            var text = await res.text();
            return mcpResult(text);
          } else {
            var data = await res.json();
            return mcpResult(data);
          }
        } catch (err) {
          return mcpResult({ error: String(err) });
        }
      }
    });

    // 7. get_spectra
    targetCtx.registerTool({
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
        if (!name) return mcpResult({ error: "Missing required supernova name" });
        try {
          var res = await fetch("/" + encodeURIComponent(name.trim()) + "/spectra");
          if (!res.ok) return mcpResult({ error: "Spectra not found for " + name, status: res.status });
          var data = await res.json();
          return mcpResult(data);
        } catch (err) {
          return mcpResult({ error: String(err) });
        }
      }
    });

  }
})();
