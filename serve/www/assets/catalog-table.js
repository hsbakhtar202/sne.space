/**
 * sne.space — Native Modern Catalog Table Controller
 * Zero-dependency, fast client-side controller powered by /api/transients.
 */
(function() {
  'use strict';

  var state = {
    q: '',
    type: 'all',
    has_spectra: null,
    has_photo: null,
    sort: 'discoverdate',
    order: 'desc',
    page: 1,
    limit: 50,
    total: 0,
    pages: 1
  };

  var searchTimer = null;

  function init() {
    var searchInput = document.getElementById('catalog-search');
    var clearBtn = document.getElementById('search-clear-btn');
    var typeButtons = document.querySelectorAll('#type-filters .filter-chip');
    var specCheck = document.getElementById('filter-has-spectra');
    var photCheck = document.getElementById('filter-has-photo');
    var perPageSelect = document.getElementById('per-page-select');
    var sortHeaders = document.querySelectorAll('#transient-catalog-table th.th-sortable');

    // Parse URL params on initial load
    var urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('q')) {
      state.q = urlParams.get('q');
      if (searchInput) searchInput.value = state.q;
      if (clearBtn && state.q) clearBtn.style.display = 'block';
    }
    if (urlParams.has('type')) {
      state.type = urlParams.get('type');
      typeButtons.forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-type') === state.type);
      });
    }
    if (urlParams.has('has_spectra')) {
      state.has_spectra = urlParams.get('has_spectra') === '1' || urlParams.get('has_spectra') === 'true';
      if (specCheck) specCheck.checked = state.has_spectra;
    }
    if (urlParams.has('has_photo')) {
      state.has_photo = urlParams.get('has_photo') === '1' || urlParams.get('has_photo') === 'true';
      if (photCheck) photCheck.checked = state.has_photo;
    }
    if (urlParams.has('sort')) state.sort = urlParams.get('sort');
    if (urlParams.has('order')) state.order = urlParams.get('order');
    if (urlParams.has('page')) state.page = parseInt(urlParams.get('page'), 10) || 1;
    if (urlParams.has('limit')) {
      state.limit = parseInt(urlParams.get('limit'), 10) || 50;
      if (perPageSelect) perPageSelect.value = String(state.limit);
    }

    // Search input handler
    if (searchInput) {
      searchInput.addEventListener('input', function() {
        var val = searchInput.value.trim();
        if (clearBtn) clearBtn.style.display = val ? 'block' : 'none';
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function() {
          state.q = val;
          state.page = 1;
          fetchData();
        }, 220);
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener('click', function() {
        if (searchInput) {
          searchInput.value = '';
          searchInput.focus();
        }
        clearBtn.style.display = 'none';
        state.q = '';
        state.page = 1;
        fetchData();
      });
    }

    // Type filter buttons
    typeButtons.forEach(function(btn) {
      btn.addEventListener('click', function() {
        typeButtons.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        state.type = btn.getAttribute('data-type');
        state.page = 1;
        fetchData();
      });
    });

    // Spectra & Photo toggles
    if (specCheck) {
      specCheck.addEventListener('change', function() {
        state.has_spectra = specCheck.checked ? true : null;
        state.page = 1;
        fetchData();
      });
    }
    if (photCheck) {
      photCheck.addEventListener('change', function() {
        state.has_photo = photCheck.checked ? true : null;
        state.page = 1;
        fetchData();
      });
    }

    // Per-page select
    if (perPageSelect) {
      perPageSelect.addEventListener('change', function() {
        state.limit = parseInt(perPageSelect.value, 10) || 50;
        state.page = 1;
        fetchData();
      });
    }

    // Sortable headers
    sortHeaders.forEach(function(th) {
      th.addEventListener('click', function() {
        var col = th.getAttribute('data-sort');
        if (state.sort === col) {
          state.order = state.order === 'asc' ? 'desc' : 'asc';
        } else {
          state.sort = col;
          // default dates, mags, counts to desc; strings to asc
          state.order = (col === 'name' || col === 'claimedtype') ? 'asc' : 'desc';
        }
        state.page = 1;
        updateHeaderSortVisuals();
        fetchData();
      });
    });

    // Pagination buttons
    var btnFirst = document.getElementById('btn-first');
    var btnPrev = document.getElementById('btn-prev');
    var btnNext = document.getElementById('btn-next');
    var btnLast = document.getElementById('btn-last');

    if (btnFirst) btnFirst.addEventListener('click', function() { if (state.page > 1) { state.page = 1; fetchData(); } });
    if (btnPrev) btnPrev.addEventListener('click', function() { if (state.page > 1) { state.page--; fetchData(); } });
    if (btnNext) btnNext.addEventListener('click', function() { if (state.page < state.pages) { state.page++; fetchData(); } });
    if (btnLast) btnLast.addEventListener('click', function() { if (state.page < state.pages) { state.page = state.pages; fetchData(); } });

    // Sync visual headers
    updateHeaderSortVisuals();

    // If query params were present in URL on arrival, perform initial fetch to match params
    if (urlParams.toString()) {
      fetchData();
    }
  }

  function updateHeaderSortVisuals() {
    var headers = document.querySelectorAll('#transient-catalog-table th.th-sortable');
    headers.forEach(function(th) {
      var col = th.getAttribute('data-sort');
      var indicator = th.querySelector('.sort-indicator');
      if (state.sort === col) {
        th.classList.add('active');
        th.classList.toggle('desc', state.order === 'desc');
        th.classList.toggle('asc', state.order === 'asc');
        if (indicator) indicator.textContent = state.order === 'desc' ? '▼' : '▲';
      } else {
        th.classList.remove('active', 'desc', 'asc');
        if (indicator) indicator.textContent = '';
      }
    });
  }

  function buildApiUrl(format) {
    var p = new URLSearchParams();
    if (state.q) p.set('q', state.q);
    if (state.type && state.type !== 'all') p.set('type', state.type);
    if (state.has_spectra !== null) p.set('has_spectra', state.has_spectra ? '1' : '0');
    if (state.has_photo !== null) p.set('has_photo', state.has_photo ? '1' : '0');
    if (state.sort) p.set('sort', state.sort);
    if (state.order) p.set('order', state.order);
    if (format) p.set('format', format);
    p.set('page', state.page);
    p.set('limit', state.limit);
    return '/api/transients?' + p.toString();
  }

  function syncUrl() {
    var p = new URLSearchParams();
    if (state.q) p.set('q', state.q);
    if (state.type && state.type !== 'all') p.set('type', state.type);
    if (state.has_spectra !== null) p.set('has_spectra', state.has_spectra ? '1' : '0');
    if (state.has_photo !== null) p.set('has_photo', state.has_photo ? '1' : '0');
    if (state.sort !== 'discoverdate') p.set('sort', state.sort);
    if (state.order !== 'desc') p.set('order', state.order);
    if (state.page > 1) p.set('page', state.page);
    if (state.limit !== 50) p.set('limit', state.limit);

    var qs = p.toString();
    var newUrl = window.location.pathname + (qs ? '?' + qs : '');
    window.history.replaceState(null, '', newUrl);

    // Update export buttons href
    var btnCsv = document.getElementById('btn-export-csv');
    var btnJson = document.getElementById('btn-export-json');
    if (btnCsv) btnCsv.href = buildApiUrl('csv');
    if (btnJson) btnJson.href = buildApiUrl('json');
  }

  function fetchData() {
    var loadingBar = document.getElementById('table-loading-bar');
    if (loadingBar) loadingBar.style.display = 'block';

    var startTime = performance.now();
    var url = buildApiUrl('json');

    fetch(url)
      .then(function(res) {
        if (!res.ok) throw new Error('API response error ' + res.status);
        return res.json();
      })
      .then(function(data) {
        var duration = Math.round(performance.now() - startTime);
        state.total = data.total || 0;
        state.pages = data.pages || 1;
        state.page = data.page || 1;

        renderRows(data.items || []);
        updatePagination(duration);
        syncUrl();
      })
      .catch(function(err) {
        console.error('[sne.space] Catalog load error:', err);
      })
      .finally(function() {
        if (loadingBar) loadingBar.style.display = 'none';
      });
  }

  function renderRows(items) {
    var tbody = document.getElementById('catalog-tbody');
    if (!tbody) return;

    if (!items || items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:3rem 1rem;color:#94a3b8;">No matching supernovae found. Try clearing your filters or search term.</td></tr>';
      return;
    }

    var html = [];
    for (var i = 0; i < items.length; i++) {
      var r = items[i];
      var nm = r.name;
      var c_type = r.type || '—';
      var badge_class = r.type_badge || 'badge-unknown';
      var disc_date = r.date || '—';
      var age = r.age || '';
      var mag_str = r.mag !== null && r.mag !== undefined ? Number(r.mag).toFixed(2) : '—';
      var z_str = r.z !== null && r.z !== undefined ? String(r.z) : '—';
      var ra = r.ra || '—';
      var dec = r.dec || '—';
      var host = r.host || '—';
      var spec = r.spec || 0;
      var phot = r.phot || 0;

      var spec_html = spec > 0
        ? '<a href="/sne/' + encodeURIComponent(nm) + '/#spectra" class="pill-badge pill-spec" title="' + spec + ' calibrated spectra">✨ ' + spec + '</a>'
        : '<span class="pill-dim">—</span>';

      var phot_html = phot > 0
        ? '<a href="/sne/' + encodeURIComponent(nm) + '/#lightcurve" class="pill-badge pill-phot" title="' + phot + ' photometry points">📈 ' + phot + '</a>'
        : '<span class="pill-dim">—</span>';

      var age_badge = age ? '<span class="sub-age">' + age + '</span>' : '';

      html.push('<tr data-name="' + nm + '">\n' +
        '  <td class="cell-name"><a href="/sne/' + encodeURIComponent(nm) + '/" class="name-link">' + escapeHtml(nm) + '</a></td>\n' +
        '  <td class="cell-type"><span class="type-pill ' + badge_class + '">' + escapeHtml(c_type) + '</span></td>\n' +
        '  <td class="cell-date"><span class="val-date">' + escapeHtml(disc_date) + '</span>' + age_badge + '</td>\n' +
        '  <td class="cell-num">' + escapeHtml(z_str) + '</td>\n' +
        '  <td class="cell-num">' + escapeHtml(mag_str) + '</td>\n' +
        '  <td class="cell-coords"><span class="coord-tag" title="Click to copy coordinates" onclick="navigator.clipboard.writeText(\'' + ra + ' ' + dec + '\'); this.classList.add(\'copied\'); setTimeout(()=>this.classList.remove(\'copied\'),1200);">' + escapeHtml(ra) + ', ' + escapeHtml(dec) + '</span></td>\n' +
        '  <td class="cell-host">' + escapeHtml(host) + '</td>\n' +
        '  <td class="cell-spec">' + spec_html + '</td>\n' +
        '  <td class="cell-phot">' + phot_html + '</td>\n' +
        '  <td class="cell-actions">\n' +
        '    <a href="/sne/' + encodeURIComponent(nm) + '/" class="btn-action btn-pro" title="Professional Cockpit">🔭 Pro</a>\n' +
        '    <a href="/sne/' + encodeURIComponent(nm) + '/story" class="btn-action btn-story" title="Story Dossier">📖 Story</a>\n' +
        '  </td>\n' +
        '</tr>');
    }
    tbody.innerHTML = html.join('\n');
  }

  function updatePagination(durationMs) {
    var start = (state.page - 1) * state.limit + 1;
    var end = Math.min(state.page * state.limit, state.total);
    if (state.total === 0) start = 0;

    var infoStart = document.getElementById('info-start');
    var infoEnd = document.getElementById('info-end');
    var infoTotal = document.getElementById('info-total');
    var indicator = document.getElementById('page-indicator');
    var timeBadge = document.getElementById('query-time-badge');

    if (infoStart) infoStart.textContent = start.toLocaleString();
    if (infoEnd) infoEnd.textContent = end.toLocaleString();
    if (infoTotal) infoTotal.textContent = state.total.toLocaleString();
    if (indicator) indicator.textContent = 'Page ' + state.page.toLocaleString() + ' of ' + state.pages.toLocaleString();
    if (timeBadge && durationMs !== undefined) timeBadge.textContent = '⚡ ' + durationMs + 'ms';

    var btnFirst = document.getElementById('btn-first');
    var btnPrev = document.getElementById('btn-prev');
    var btnNext = document.getElementById('btn-next');
    var btnLast = document.getElementById('btn-last');

    if (btnFirst) btnFirst.disabled = state.page <= 1;
    if (btnPrev) btnPrev.disabled = state.page <= 1;
    if (btnNext) btnNext.disabled = state.page >= state.pages;
    if (btnLast) btnLast.disabled = state.page >= state.pages;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Self initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
