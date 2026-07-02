/**
 * جستجوی سریع داشبورد + سابقه جستجو (سبک دیوار) — بدون reload کامل.
 */
(function () {
  'use strict';

  var searchAbort = null;
  var searchPromise = null;
  var historyHideTimer = 0;
  var historyUiBound = false;
  var historyPanelOpen = false;

  var STORAGE_KEY = 'vinor_dash_search_history';
  var MAX_HISTORY = 8;

  function isDashboardPage() {
    try {
      var p = (window.location.pathname || '').replace(/\/+$/, '') || '/';
      return p === '/express/partner/dashboard';
    } catch (_) {
      return false;
    }
  }

  function getForm() {
    return document.getElementById('searchForm');
  }

  function getInput() {
    return document.getElementById('searchInput');
  }

  function getSearchPill() {
    var form = getForm();
    return form ? form.querySelector('.vinor-dash-search-pill') : null;
  }

  function loadHistory() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map(function (item) { return String(item || '').trim(); })
        .filter(function (item) { return item.length > 0; })
        .slice(0, MAX_HISTORY);
    } catch (_) {
      return [];
    }
  }

  function saveHistory(items) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)));
    } catch (_) {}
  }

  function addToHistory(query) {
    var q = String(query || '').trim();
    if (!q) return;
    var items = loadHistory().filter(function (item) { return item !== q; });
    items.unshift(q);
    saveHistory(items);
  }

  function removeFromHistory(query) {
    var q = String(query || '').trim();
    if (!q) return;
    saveHistory(loadHistory().filter(function (item) { return item !== q; }));
  }

  function clearHistory() {
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
  }

  function buildSearchUrl(form, qOverride) {
    if (!form) return null;
    var params = new URLSearchParams();
    try {
      new FormData(form).forEach(function (value, key) {
        if (value != null && String(value).trim() !== '') {
          params.set(key, String(value).trim());
        }
      });
    } catch (_) {}
    if (typeof qOverride === 'string') {
      var trimmed = qOverride.trim();
      if (trimmed) params.set('q', trimmed);
      else params.delete('q');
    }
    var action = form.getAttribute('action') || '/express/partner/dashboard';
    try {
      var u = new URL(action, window.location.origin);
      u.search = params.toString();
      return u.pathname + u.search;
    } catch (_) {
      return action.split('?')[0] + (params.toString() ? '?' + params.toString() : '');
    }
  }

  function setCardsLoading(on) {
    var track = document.getElementById('cardsTrack');
    var grid = document.getElementById('cardsGrid');
    var opacity = on ? '0.68' : '1';
    var transition = 'opacity 0.18s ease';
    if (track) {
      track.style.opacity = opacity;
      track.style.transition = transition;
    }
    if (grid) {
      grid.style.opacity = opacity;
      grid.style.transition = transition;
    }
  }

  function swapSection(id, doc) {
    var cur = document.getElementById(id);
    var neu = doc.getElementById(id);
    if (cur && neu) cur.innerHTML = neu.innerHTML;
    return !!(cur && neu);
  }

  function swapDesktopColumn(doc) {
    var cur = document.querySelector('#expressDashboardMain .lg\\:col-span-9');
    var neu = doc.querySelector('#expressDashboardMain .lg\\:col-span-9');
    if (cur && neu) cur.innerHTML = neu.innerHTML;
    return !!(cur && neu);
  }

  function ensureHistoryPanel() {
    var form = getForm();
    if (!form) return null;
    var panel = document.getElementById('dashboardSearchHistory');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'dashboardSearchHistory';
      panel.className = 'vinor-dash-search-history';
      panel.setAttribute('role', 'listbox');
      panel.setAttribute('aria-label', 'سابقه جستجو');
      panel.hidden = true;
      form.appendChild(panel);
    }
    return panel;
  }

  function filterHistory(query) {
    var items = loadHistory();
    var q = String(query || '').trim().toLowerCase();
    if (!q) return items;
    return items.filter(function (item) {
      return item.toLowerCase().indexOf(q) !== -1;
    });
  }

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderHistoryPanel(filter) {
    var panel = ensureHistoryPanel();
    if (!panel) return;
    var items = filterHistory(filter);
    if (!items.length) {
      panel.hidden = true;
      panel.classList.remove('is-open');
      panel.innerHTML = '';
      historyPanelOpen = false;
      var pill = getSearchPill();
      if (pill) pill.classList.remove('is-history-open');
      return;
    }

    var head = '<div class="vinor-dash-search-history__head">' +
      '<span class="vinor-dash-search-history__title">جستجوهای اخیر</span>' +
      '<button type="button" class="vinor-dash-search-history__clear" data-vinor-history-clear="1">پاک کردن</button>' +
      '</div>';

    var list = items.map(function (item) {
      var enc = encodeURIComponent(item);
      return '<div class="vinor-dash-search-history__item" role="option" data-vinor-history-item="' + enc + '">' +
        '<span class="vinor-dash-search-history__icon" aria-hidden="true"><i class="fa-regular fa-clock"></i></span>' +
        '<span class="vinor-dash-search-history__text">' + escapeHtml(item) + '</span>' +
        '<button type="button" class="vinor-dash-search-history__remove" data-vinor-history-remove="' + enc + '" aria-label="حذف از سابقه">' +
        '<i class="fa-solid fa-xmark text-[10px]" aria-hidden="true"></i>' +
        '</button>' +
        '</div>';
    }).join('');

    panel.innerHTML = head + '<div class="vinor-dash-search-history__list">' + list + '</div>';
    panel.hidden = false;
  }

  function showHistoryPanel() {
    if (!isDashboardPage()) return;
    var input = getInput();
    if (!input || document.activeElement !== input) return;
    renderHistoryPanel(input.value);
    var panel = document.getElementById('dashboardSearchHistory');
    if (!panel || panel.hidden) return;
    panel.classList.add('is-open');
    historyPanelOpen = true;
    var pill = getSearchPill();
    if (pill) pill.classList.add('is-history-open');
  }

  function hideHistoryPanel() {
    window.clearTimeout(historyHideTimer);
    var panel = document.getElementById('dashboardSearchHistory');
    if (panel) {
      panel.classList.remove('is-open');
      panel.hidden = true;
    }
    historyPanelOpen = false;
    var pill = getSearchPill();
    if (pill) pill.classList.remove('is-history-open');
  }

  function scheduleHideHistoryPanel() {
    window.clearTimeout(historyHideTimer);
    historyHideTimer = window.setTimeout(hideHistoryPanel, 140);
  }

  function onHistoryPanelPointerDown(e) {
    e.preventDefault();
  }

  function historyValueFromAttr(raw) {
    try {
      return decodeURIComponent(raw || '');
    } catch (_) {
      return raw || '';
    }
  }

  function onHistoryPanelClick(e) {
    var clearBtn = e.target.closest && e.target.closest('[data-vinor-history-clear]');
    if (clearBtn) {
      e.preventDefault();
      e.stopPropagation();
      clearHistory();
      hideHistoryPanel();
      return;
    }

    var removeBtn = e.target.closest && e.target.closest('[data-vinor-history-remove]');
    if (removeBtn) {
      e.preventDefault();
      e.stopPropagation();
      removeFromHistory(historyValueFromAttr(removeBtn.getAttribute('data-vinor-history-remove')));
      var input = getInput();
      renderHistoryPanel(input ? input.value : '');
      if (!loadHistory().length) hideHistoryPanel();
      else showHistoryPanel();
      if (input) {
        try { input.focus(); } catch (_) {}
      }
      return;
    }

    var item = e.target.closest && e.target.closest('[data-vinor-history-item]');
    if (!item) return;
    e.preventDefault();
    e.stopPropagation();
    var q = historyValueFromAttr(item.getAttribute('data-vinor-history-item'));
    var form = getForm();
    if (!form || !q) return;
    hideHistoryPanel();
    runFromForm(form, q, { fromHistory: true });
  }

  function onInputFocus() {
    window.clearTimeout(historyHideTimer);
    showHistoryPanel();
  }

  function onInputInput() {
    if (!historyPanelOpen && document.activeElement === getInput()) {
      showHistoryPanel();
      return;
    }
    renderHistoryPanel(getInput() ? getInput().value : '');
    var panel = document.getElementById('dashboardSearchHistory');
    if (panel && !panel.hidden) {
      panel.classList.add('is-open');
      historyPanelOpen = true;
    } else {
      historyPanelOpen = false;
    }
  }

  function onInputBlur() {
    scheduleHideHistoryPanel();
  }

  function onInputKeydown(e) {
    if (e.key === 'Escape') {
      hideHistoryPanel();
      return;
    }
    if (e.key === 'Enter') return;
  }

  function onDocumentPointerDown(e) {
    if (!historyPanelOpen) return;
    var form = getForm();
    var panel = document.getElementById('dashboardSearchHistory');
    if (!form || !panel) return;
    if (form.contains(e.target)) return;
    hideHistoryPanel();
  }

  function bindHistoryUi() {
    if (!isDashboardPage()) return;
    ensureHistoryPanel();
    var input = getInput();
    var panel = document.getElementById('dashboardSearchHistory');
    if (!input || !panel) return;

    if (!input.dataset.vinorHistoryInputBound) {
      input.dataset.vinorHistoryInputBound = '1';
      input.addEventListener('focus', onInputFocus);
      input.addEventListener('input', onInputInput);
      input.addEventListener('blur', onInputBlur);
      input.addEventListener('keydown', onInputKeydown);
    }

    if (!panel.dataset.vinorHistoryPanelBound) {
      panel.dataset.vinorHistoryPanelBound = '1';
      panel.addEventListener('mousedown', onHistoryPanelPointerDown);
      panel.addEventListener('click', onHistoryPanelClick);
    }

    if (!historyUiBound) {
      historyUiBound = true;
      document.addEventListener('pointerdown', onDocumentPointerDown, true);
    }
  }

  function applySearchHtml(html, targetUrl) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    swapSection('dashboardMobileCardsRoot', doc);
    swapDesktopColumn(doc);
    swapSection('dashboardSearchStrip', doc);

    try {
      history.pushState(
        { vinorExpress: true, tabKey: 'dashboard', depth: 0 },
        '',
        targetUrl
      );
    } catch (_) {}

    try {
      if (typeof window.vinorExpressInvalidatePrefetch === 'function') {
        window.vinorExpressInvalidatePrefetch(targetUrl);
      }
    } catch (_) {}

    var cardsRoot = document.getElementById('dashboardMobileCardsRoot');
    if (cardsRoot) cardsRoot.scrollTop = 0;

    if (typeof window.reinitializeCards === 'function') {
      try { window.reinitializeCards(); } catch (_) {}
    }
    if (typeof window.__vinorDashboardSyncChrome === 'function') {
      window.__vinorDashboardSyncChrome({ expandHeader: true, resetScroll: false });
    }
    if (typeof window.setupVinorDashboardPullRefresh === 'function') {
      try { window.setupVinorDashboardPullRefresh(); } catch (_) {}
    }
    if (window.__vinorDashboardVoiceSearch && window.__vinorDashboardVoiceSearch.setup) {
      try { window.__vinorDashboardVoiceSearch.setup(); } catch (_) {}
    }
    try {
      document.dispatchEvent(new CustomEvent('vinor:city-picker-reinit'));
    } catch (_) {}
    bindHistoryUi();
  }

  function runDashboardSearch(targetUrl, opts) {
    opts = opts || {};
    if (!targetUrl || !isDashboardPage()) {
      window.location.href = targetUrl || '/express/partner/dashboard';
      return Promise.resolve(false);
    }

    hideHistoryPanel();

    if (searchAbort) {
      try { searchAbort.abort(); } catch (_) {}
    }
    searchAbort = new AbortController();
    var signal = searchAbort.signal;

    setCardsLoading(true);

    var fetchUrl;
    try {
      var u = new URL(targetUrl, window.location.origin);
      u.searchParams.set('_refresh', Date.now().toString());
      fetchUrl = u.toString();
    } catch (_) {
      fetchUrl = targetUrl + (targetUrl.indexOf('?') >= 0 ? '&' : '?') + '_refresh=' + Date.now();
    }

    searchPromise = fetch(fetchUrl, {
      method: 'GET',
      headers: {
        Accept: 'text/html',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        Pragma: 'no-cache',
        'X-Requested-With': 'XMLHttpRequest'
      },
      cache: 'no-store',
      credentials: 'same-origin',
      signal: signal
    })
      .then(function (res) {
        if (!res.ok) throw new Error('search');
        return res.text();
      })
      .then(function (html) {
        if (!isDashboardPage()) return false;
        applySearchHtml(html, targetUrl);
        setCardsLoading(false);
        if (opts.saveHistory && opts.query) addToHistory(opts.query);
        return true;
      })
      .catch(function (err) {
        setCardsLoading(false);
        if (err && err.name === 'AbortError') return false;
        if (typeof window.vinorExpressNavigate === 'function') {
          return window.vinorExpressNavigate(targetUrl, { forward: false });
        }
        window.location.href = targetUrl;
        return false;
      })
      .finally(function () {
        searchPromise = null;
        searchAbort = null;
      });

    return searchPromise;
  }

  function runFromForm(form, qOverride, opts) {
    opts = opts || {};
    var q = typeof qOverride === 'string' ? qOverride.trim() : '';
    var url = buildSearchUrl(form, qOverride);
    if (!url) return Promise.resolve(false);
    var input = getInput();
    if (input && typeof qOverride === 'string') input.value = q;
    if (input && !opts.keepFocus) {
      try { input.blur(); } catch (_) {}
    }
    return runDashboardSearch(url, {
      saveHistory: q.length > 0,
      query: q
    });
  }

  function onFormSubmit(e) {
    var form = e.target && e.target.id === 'searchForm' ? e.target : (e.target.closest && e.target.closest('#searchForm'));
    if (!form || !isDashboardPage()) return;
    e.preventDefault();
    e.stopPropagation();
    var input = getInput();
    var q = input ? input.value : '';
    runFromForm(form, q);
  }

  var submitBound = false;

  function bindForm() {
    if (submitBound) return;
    submitBound = true;
    document.addEventListener('submit', onFormSubmit, true);
  }

  function teardown() {
    if (searchAbort) {
      try { searchAbort.abort(); } catch (_) {}
      searchAbort = null;
    }
    hideHistoryPanel();
  }

  window.__vinorDashboardSearch = {
    buildUrl: buildSearchUrl,
    run: runDashboardSearch,
    runFromForm: runFromForm,
    addHistory: addToHistory,
    clearHistory: clearHistory
  };

  function setup() {
    bindForm();
    bindHistoryUi();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else {
    setup();
  }

  window.addEventListener('vinor:express-page-swap', function (ev) {
    if (!ev.detail || ev.detail.navKey === 'dashboard') {
      window.setTimeout(setup, 0);
      return;
    }
    teardown();
  });
})();
