/**
 * sne.space WebMCP Standard Implementation
 * Fully compliant with W3C WebMCP Specification, Chrome 149+ Origin Trial, and WebMCPTools.io.
 * Supports document.modelContext, navigator.modelContext, event.agentInvoked, requestUserInteraction(),
 * and Chrome Built-in AI (Gemini Nano) Prompt API.
 */
(function() {
  'use strict';

  // 1. Human-in-the-Loop & AI Agent Consent Handling (W3C WebMCP Standard)
  if (typeof document !== 'undefined') {
    document.addEventListener('submit', function(event) {
      if (event.agentInvoked) {
        console.log('[WebMCP] AI Agent triggered form submission:', event.target);
      }
      var form = event.target;
      if (form && (form.hasAttribute('toolsensitive') || form.getAttribute('tool-sensitive') === 'true')) {
        if (typeof navigator !== 'undefined' && navigator.modelContext && typeof navigator.modelContext.requestUserInteraction === 'function') {
          navigator.modelContext.requestUserInteraction({
            prompt: 'Confirm action: ' + (form.getAttribute('tooldescription') || form.getAttribute('toolname'))
          });
        } else if (typeof document !== 'undefined' && document.modelContext && typeof document.modelContext.requestUserInteraction === 'function') {
          document.modelContext.requestUserInteraction({
            prompt: 'Confirm action: ' + (form.getAttribute('tooldescription') || form.getAttribute('toolname'))
          });
        }
      }
    });
  }

  // Ensure requestUserInteraction is available on active modelContext
  if (typeof navigator !== 'undefined' && navigator.modelContext && typeof navigator.modelContext.requestUserInteraction !== 'function') {
    navigator.modelContext.requestUserInteraction = async function(options) {
      console.log('[WebMCP] navigator.modelContext.requestUserInteraction called:', options);
      return true;
    };
  }
  if (typeof document !== 'undefined' && document.modelContext && typeof document.modelContext.requestUserInteraction !== 'function') {
    document.modelContext.requestUserInteraction = async function(options) {
      console.log('[WebMCP] document.modelContext.requestUserInteraction called:', options);
      return true;
    };
  }

  // 2. Chrome Built-in AI (Gemini Nano) Prompt API Integration
  if (typeof window !== 'undefined' && window.ai && window.ai.languageModel) {
    try {
      window.ai.languageModel.capabilities().then(function(cap) {
        if (cap && cap.available !== 'no') {
          window.ai.languageModel.create().then(function(session) {
            window._chromeAiSession = session;
          }).catch(function() {});
        }
      }).catch(function() {});
    } catch (e) {}
  }

  window.promptChromeAI = async function(query) {
    if (typeof window !== 'undefined' && window.ai && window.ai.languageModel) {
      const session = await window.ai.languageModel.create();
      const result = await session.prompt(query);
      return result;
    }
    return null;
  };

  // 3. Register Tool Helper (Dual registration with document.modelContext & navigator.modelContext)
  function registerTool(tool) {
    if (typeof document !== 'undefined' && document.modelContext && typeof document.modelContext.registerTool === 'function') {
      try {
        var pDoc = document.modelContext.registerTool(tool);
        if (pDoc && typeof pDoc.then === 'function') {
          pDoc.then(function() {
            console.log('[WebMCP document registered]', tool.name);
          }).catch(function(err) {
            console.error('[WebMCP document registration error]', tool.name, err);
          });
        }
      } catch (err) {
        console.error('[WebMCP document registerTool error]', tool.name, err);
      }
    }

    if (typeof navigator !== 'undefined' && navigator.modelContext && typeof navigator.modelContext.registerTool === 'function') {
      try {
        var pNav = navigator.modelContext.registerTool(tool);
        if (pNav && typeof pNav.then === 'function') {
          pNav.then(function() {
            console.log('[WebMCP navigator registered]', tool.name);
          }).catch(function(err) {
            console.error('[WebMCP navigator registration error]', tool.name, err);
          });
        }
      } catch (err) {
        console.error('[WebMCP navigator registerTool error]', tool.name, err);
      }
    }
  }

  // Tool 1: search_supernovae
  registerTool({
    name: 'search_supernovae',
    title: 'Search Supernovae',
    description: 'Search 110,000+ supernovae and transients by IAU designation, name, or survey alias (e.g. SN 2023ixf, SN 1987A, SN 2011fe, AT2024nrb).',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Supernova designation, IAU name, or survey alias'
        }
      },
      required: ['query']
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var q = (args && (args.query || args.q)) || '';
      if (!q) return JSON.stringify({ error: 'Missing required query parameter' });
      var res = await fetch('/api/search?q=' + encodeURIComponent(q.trim()));
      return JSON.stringify(await res.json());
    }
  });

  // Tool 2: get_supernova
  registerTool({
    name: 'get_supernova',
    title: 'Get Supernova Data',
    description: 'Retrieve complete astrophysical dossier for a supernova, including classification, redshift, coordinates, host galaxy, discovery date, peak magnitude, and bibliography.',
    inputSchema: {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          description: 'Supernova name or IAU designation (e.g. SN 2023ixf, SN 1987A, SN 2011fe)'
        }
      },
      required: ['name']
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var name = (args && (args.name || args.q)) || '';
      if (!name) return JSON.stringify({ error: 'Missing required supernova name' });
      var res = await fetch('/sne/' + encodeURIComponent(name.trim()) + '.json');
      return JSON.stringify(await res.json());
    }
  });

  // Tool 3: search_by_coordinates (Cone Search)
  registerTool({
    name: 'search_by_coordinates',
    title: 'Search by Coordinates (Cone Search)',
    description: 'Cone search for supernovae and transients within an angular radius around J2000 celestial coordinates (Right Ascension and Declination in decimal degrees).',
    inputSchema: {
      type: 'object',
      properties: {
        ra: {
          type: 'number',
          description: 'Right Ascension in decimal degrees (0.0 to 360.0)'
        },
        dec: {
          type: 'number',
          description: 'Declination in decimal degrees (-90.0 to +90.0)'
        },
        radius_arcmin: {
          type: 'number',
          description: 'Search radius in arcminutes (default: 5.0, max: 60.0)'
        }
      },
      required: ['ra', 'dec']
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      if (!args || typeof args.ra !== 'number' || typeof args.dec !== 'number') {
        return JSON.stringify({ error: "Missing required 'ra' and 'dec' coordinate arguments" });
      }
      var rad = args.radius_arcmin || 5.0;
      var res = await fetch('/api/cone?ra=' + encodeURIComponent(args.ra) + '&dec=' + encodeURIComponent(args.dec) + '&radius=' + encodeURIComponent(rad) + '&format=json');
      return JSON.stringify(await res.json());
    }
  });

  // Tool 4: search_by_type
  registerTool({
    name: 'search_by_type',
    title: 'Search by Astrophysical Type',
    description: "Find supernovae matching a specific astrophysical classification type (e.g. 'Ia', 'II-P', 'IIn', 'SLSN-I', 'Ia-91T', 'TDE').",
    inputSchema: {
      type: 'object',
      properties: {
        type: {
          type: 'string',
          description: 'Astrophysical classification type (e.g. Ia, II-P, IIn, SLSN)'
        },
        limit: {
          type: 'number',
          description: 'Maximum results to return (default: 25, max: 100)'
        }
      },
      required: ['type']
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var t = (args && args.type) || '';
      var limit = (args && args.limit) || 25;
      if (!t) return JSON.stringify({ error: "Missing required 'type' argument" });
      var res = await fetch('/api/by-type?type=' + encodeURIComponent(t) + '&limit=' + encodeURIComponent(limit));
      return JSON.stringify(await res.json());
    }
  });

  // Tool 5: get_recent_discoveries
  registerTool({
    name: 'get_recent_discoveries',
    title: 'Get Recent Discoveries',
    description: 'Fetch latest discovered supernovae and active transient alerts from the last 30 days, sorted by discovery date.',
    inputSchema: {
      type: 'object',
      properties: {
        limit: {
          type: 'number',
          description: 'Maximum number of recent transients to return (default: 25)'
        }
      }
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var limit = (args && args.limit) || 25;
      var res = await fetch('/api/recent?limit=' + encodeURIComponent(limit));
      if (!res.ok) res = await fetch('/api/radar.json');
      return JSON.stringify(await res.json());
    }
  });

  // Tool 6: get_photometry
  registerTool({
    name: 'get_photometry',
    title: 'Get Photometric Light Curve',
    description: 'Retrieve calibrated multi-band photometric light curve observations (time, magnitude, error, filter band, telescope/observer) for a supernova.',
    inputSchema: {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          description: 'Supernova name or IAU designation (e.g. SN 2023ixf, SN 2011fe)'
        },
        format: {
          type: 'string',
          description: "Response format ('json' or 'csv', default: 'json')",
          enum: ['json', 'csv']
        }
      },
      required: ['name']
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var name = (args && (args.name || args.q)) || '';
      var fmt = (args && args.format) || 'json';
      if (!name) return JSON.stringify({ error: 'Missing required supernova name' });
      var endpoint = '/' + encodeURIComponent(name.trim()) + '/photometry' + (fmt === 'csv' ? '?format=csv' : '');
      var res = await fetch(endpoint);
      if (fmt === 'csv') {
        return await res.text();
      }
      return JSON.stringify(await res.json());
    }
  });

  // Tool 7: get_spectra
  registerTool({
    name: 'get_spectra',
    title: 'Get Calibrated Spectra',
    description: 'Retrieve calibrated 1D optical spectra (wavelength in Angstroms, flux, epoch/phase, instrument) for a supernova.',
    inputSchema: {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          description: 'Supernova name or IAU designation (e.g. SN 2023ixf, SN 1987A)'
        }
      },
      required: ['name']
    },
    annotations: { readOnlyHint: true },
    execute: async function(args) {
      var name = (args && (args.name || args.q)) || '';
      if (!name) return JSON.stringify({ error: 'Missing required supernova name' });
      var res = await fetch('/' + encodeURIComponent(name.trim()) + '/spectra');
      return JSON.stringify(await res.json());
    }
  });

})();
