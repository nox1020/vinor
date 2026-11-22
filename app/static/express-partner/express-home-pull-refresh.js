/**
 * Pull-to-refresh — /express/partner/home (موبایل)
 * اسکرول اصلی در حالت AI داخل #vnHomeScroll است؛ در غیر این صورت اسکرول سند.
 * منطق ژست در express-ptr-core.js (قفل محور، اسکرول داخلی، فاصلهٔ فعلی).
 */
(function () {
  'use strict';

  var MOBILE_MQ = '(max-width: 1023px)';
  var pullHandle = null;

  function isMobileViewport() {
    try { return window.matchMedia(MOBILE_MQ).matches; } catch (_) { return window.innerWidth <= 1023; }
  }

  function isHomePath() {
    try {
      var p = (window.location.pathname || '').replace(/\/+$/, '') || '/';
      return p === '/express/partner/home';
    } catch (_) { return false; }
  }

  function findHomeScrollRoot() {
    var sc = document.getElementById('vnHomeScroll');
    if (!sc) return null;
    try {
      var oy = window.getComputedStyle(sc).overflowY;
      if (oy === 'auto' || oy === 'scroll') return sc;
    } catch (_) { /* ignore */ }
    return null;
  }

  function setPullHint(visible, refreshing) {
    var hint = document.getElementById('vinorExpressPullHint');
    if (!hint) return;
    hint.classList.toggle('is-visible', !!(visible || refreshing));
    hint.classList.toggle('is-refreshing', !!refreshing);
    hint.setAttribute('aria-hidden', (visible || refreshing) ? 'false' : 'true');
  }

  function performHomeRefresh() {
    if (typeof window.vinorExpressSoftRefresh === 'function') {
      return window.vinorExpressSoftRefresh();
    }
    window.location.reload();
    return Promise.resolve();
  }

  function setupVinorHomePullRefresh() {
    if (pullHandle) {
      try { pullHandle.detach(); } catch (_) {}
    }
    pullHandle = null;
    setPullHint(false, false);

    if (!isMobileViewport() || !isHomePath()) return;

    var page = document.getElementById('homeDashboardPage');
    if (!page) return;

    if (!window.VinorPtr || typeof window.VinorPtr.attach !== 'function') return;

    pullHandle = window.VinorPtr.attach({
      target: document,
      scrollRoot: findHomeScrollRoot(),
      accept: function (e) { return page.contains(e.target); },
      setHint: setPullHint,
      onRefresh: performHomeRefresh
    });
  }

  window.setupVinorHomePullRefresh = setupVinorHomePullRefresh;

  if (!window.__vinorHomePullSwapBound) {
    window.__vinorHomePullSwapBound = true;
    document.addEventListener('vinor:express-page-swap', setupVinorHomePullRefresh);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupVinorHomePullRefresh);
  } else {
    setupVinorHomePullRefresh();
  }
})();
