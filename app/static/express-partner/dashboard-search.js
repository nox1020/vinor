/**
 * جستجوی سریع داشبورد — بدون reload کامل؛ فقط کارت‌ها + نوار جستجو (سبک دیوار).
 */
(function () {
  'use strict';

  var searchAbort = null;
  var searchPromise = null;

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
  }

  function runDashboardSearch(targetUrl) {
    if (!targetUrl || !isDashboardPage()) {
      window.location.href = targetUrl || '/express/partner/dashboard';
      return Promise.resolve(false);
    }

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

  function runFromForm(form, qOverride) {
    var url = buildSearchUrl(form, qOverride);
    if (!url) return Promise.resolve(false);
    var input = document.getElementById('searchInput');
    if (input && typeof qOverride === 'string') input.value = qOverride.trim();
    if (input) {
      try { input.blur(); } catch (_) {}
    }
    return runDashboardSearch(url);
  }

  function onFormSubmit(e) {
    var form = e.target && e.target.id === 'searchForm' ? e.target : (e.target.closest && e.target.closest('#searchForm'));
    if (!form || !isDashboardPage()) return;
    e.preventDefault();
    e.stopPropagation();
    var input = document.getElementById('searchInput');
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
  }

  window.__vinorDashboardSearch = {
    buildUrl: buildSearchUrl,
    run: runDashboardSearch,
    runFromForm: runFromForm
  };

  function setup() {
    bindForm();
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
