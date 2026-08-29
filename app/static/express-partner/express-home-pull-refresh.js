/**
 * Pull-to-refresh — /express/partner/home (موبایل)
 * اسکرول اصلی در حالت AI داخل #vnHomeScroll است؛ در غیر این صورت اسکرول سند.
 */
(function () {
  'use strict';

  var MOBILE_MQ = '(max-width: 1023px)';
  var PULL_TRIGGER_PX = 72;
  var TOP_EPS = 10;
  var pullAbort = null;

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

  function pageScrollTop(scrollRoot) {
    if (scrollRoot) return scrollRoot.scrollTop || 0;
    try {
      var a = typeof window.scrollY === 'number' && !isNaN(window.scrollY) ? window.scrollY : 0;
      var b = typeof window.pageYOffset === 'number' && !isNaN(window.pageYOffset) ? window.pageYOffset : 0;
      var se = document.scrollingElement;
      var c = se && typeof se.scrollTop === 'number' ? se.scrollTop : 0;
      var d = document.documentElement ? document.documentElement.scrollTop || 0 : 0;
      var e = document.body ? document.body.scrollTop || 0 : 0;
      return Math.max(a, b, c, d, e);
    } catch (_) {
      return 0;
    }
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
    if (pullAbort) {
      try { pullAbort.abort(); } catch (_) {}
    }
    pullAbort = null;
    setPullHint(false, false);

    if (!isMobileViewport() || !isHomePath()) return;

    var page = document.getElementById('homeDashboardPage');
    if (!page) return;

    pullAbort = new AbortController();
    var sig = pullAbort.signal;
    var opt = { passive: true, signal: sig };

    var scrollRoot = findHomeScrollRoot();
    var listenTarget = scrollRoot || document;

    var startY = null;
    var maxPull = 0;
    var busy = false;

    function atTop() {
      return pageScrollTop(scrollRoot) <= TOP_EPS;
    }

    function resetGesture() {
      startY = null;
      maxPull = 0;
      if (!busy) setPullHint(false, false);
    }

    listenTarget.addEventListener('touchstart', function (e) {
      if (busy) return;
      if (!e.touches || e.touches.length !== 1) return;
      if (document.documentElement.classList.contains('vinor-express-overlay-modal-open')) return;
      if (!page.contains(e.target)) return;
      if (scrollRoot && !scrollRoot.contains(e.target)) return;
      if (!atTop()) return;
      startY = e.touches[0].clientY;
      maxPull = 0;
    }, opt);

    listenTarget.addEventListener('touchmove', function (e) {
      if (startY == null || !e.touches || e.touches.length !== 1) return;
      if (!atTop()) {
        resetGesture();
        return;
      }
      var dy = e.touches[0].clientY - startY;
      if (dy < -12) {
        resetGesture();
        return;
      }
      if (dy > 0) {
        maxPull = Math.max(maxPull, dy);
        setPullHint(maxPull > 48, false);
      }
    }, opt);

    function endPull() {
      if (startY == null) return;
      var shouldRefresh = maxPull >= PULL_TRIGGER_PX && atTop();
      startY = null;
      maxPull = 0;
      if (!shouldRefresh || busy) {
        setPullHint(false, false);
        return;
      }
      busy = true;
      setPullHint(true, true);
      performHomeRefresh().finally(function () {
        busy = false;
        setPullHint(false, false);
      });
    }

    listenTarget.addEventListener('touchend', endPull, opt);
    listenTarget.addEventListener('touchcancel', resetGesture, opt);
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
