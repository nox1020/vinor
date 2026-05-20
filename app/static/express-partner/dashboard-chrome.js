/**
 * کنترلر پایدار هدر/فیلتر داشبورد همکار — یک‌بار لود می‌شود و بعد از هر soft-tab دوباره bind می‌کند.
 */
(function () {
  'use strict';

  var dashAbort = null;
  var resizeObs = [];
  var compact = false;
  var heightRaf = 0;
  var scrollEndTimer = 0;
  var touchQueued = false;
  var scrollMode = '';

  var COMPACT_MIN_Y = 10;
  var EXPAND_MAX_Y = 2;
  var HEIGHT_SLACK_PX = 14;

  function getEl() {
    return {
      header: document.getElementById('expressDashboardHeader'),
      main: document.getElementById('expressDashboardMain'),
      cardsRoot: document.getElementById('dashboardMobileCardsRoot')
    };
  }

  function isDashboardPage() {
    try {
      var p = (window.location.pathname || '').replace(/\/+$/, '') || '/';
      return p === '/express/partner/dashboard';
    } catch (_) {
      return false;
    }
  }

  function scrollModeFor(el) {
    if (!el.cardsRoot) return 'document';
    try {
      if (!window.matchMedia('(max-width: 639px)').matches) return 'document';
      var cs = window.getComputedStyle(el.cardsRoot);
      if (cs.display === 'none' || cs.visibility === 'hidden') return 'document';
      if (cs.overflowY === 'auto' || cs.overflowY === 'scroll') return 'cards';
    } catch (_) {}
    return 'document';
  }

  function scrollTopDocument() {
    if (typeof window.scrollY === 'number' && !Number.isNaN(window.scrollY)) return window.scrollY;
    var shell = document.getElementById('tg-page-shell');
    if (shell && shell.scrollTop) return shell.scrollTop;
    var se = document.scrollingElement;
    if (se && se.scrollTop) return se.scrollTop;
    return 0;
  }

  function scrollTopNow(el) {
    if (scrollMode === 'cards' && el.cardsRoot) {
      return el.cardsRoot.scrollTop || 0;
    }
    return scrollTopDocument();
  }

  function resetScroll(el) {
    try {
      if (el.cardsRoot) el.cardsRoot.scrollTop = 0;
      var shell = document.getElementById('tg-page-shell');
      if (shell) shell.scrollTop = 0;
      var se = document.scrollingElement;
      if (se) se.scrollTop = 0;
      window.scrollTo(0, 0);
    } catch (_) {}
  }

  function readCompactFromDom(el) {
    if (!el.header) return false;
    return el.header.classList.contains('dash-header--compact');
  }

  function measureTabletCardHeight(el) {
    try {
      if (!window.matchMedia('(min-width: 640px) and (max-width: 1023px)').matches) return 0;
      var track = document.getElementById('cardsTrack');
      if (!track || !el.cardsRoot || !el.cardsRoot.contains(track)) return 0;
      var slot = track.querySelector('.snap-start');
      if (!slot) return 0;
      var card = slot.querySelector('.vinor-premium-card') || slot;
      var h = card.getBoundingClientRect().height;
      return Number.isFinite(h) && h > 0 ? Math.ceil(h) : 0;
    } catch (_) {
      return 0;
    }
  }

  function syncCardsHeight(el) {
    if (!el.cardsRoot) return;
    try {
      if (!window.matchMedia('(max-width: 1023px)').matches) {
        el.cardsRoot.style.height = '';
        el.cardsRoot.style.removeProperty('--vinor-dash-card-h');
        return;
      }
      var cs = window.getComputedStyle(el.cardsRoot);
      if (cs.display === 'none' || cs.visibility === 'hidden') {
        el.cardsRoot.style.height = '';
        el.cardsRoot.style.removeProperty('--vinor-dash-card-h');
        return;
      }
      var nav = document.getElementById('bottomNavMenu');
      var navTop = nav ? nav.getBoundingClientRect().top : window.innerHeight;
      if (window.visualViewport) {
        var lb = window.visualViewport.offsetTop + window.visualViewport.height;
        navTop = Math.min(navTop, lb);
      }
      var rootTop = el.cardsRoot.getBoundingClientRect().top;
      var available = navTop - rootTop;
      if (!Number.isFinite(available)) return;
      available = Math.max(160, Math.ceil(available) + HEIGHT_SLACK_PX);
      var cardNeed = measureTabletCardHeight(el);
      if (cardNeed > 0) available = Math.max(available, cardNeed + 8);
      var prev = parseFloat(String(el.cardsRoot.style.height || '').replace('px', ''), 10);
      if (Number.isFinite(prev) && Math.abs(prev - available) < 8) {
        try {
          if (window.matchMedia('(max-width: 639px)').matches) {
            el.cardsRoot.style.setProperty('--vinor-dash-card-h', available + 'px');
          }
        } catch (_) {}
        return;
      }
      el.cardsRoot.style.height = available + 'px';
      try {
        if (window.matchMedia('(max-width: 639px)').matches) {
          el.cardsRoot.style.setProperty('--vinor-dash-card-h', available + 'px');
        } else {
          el.cardsRoot.style.removeProperty('--vinor-dash-card-h');
        }
      } catch (_) {}
    } catch (_) {}
  }

  function scheduleCardsHeight() {
    if (heightRaf) return;
    heightRaf = requestAnimationFrame(function () {
      heightRaf = 0;
      syncCardsHeight(getEl());
    });
  }

  function syncPadding(el) {
    if (!el.header || !el.main) return;
    var h = el.header.getBoundingClientRect().height;
    el.main.style.paddingTop = Math.ceil(h + 6) + 'px';
    scheduleCardsHeight();
  }

  function applyCompact(on) {
    var el = getEl();
    if (!el.header) return;
    var want = !!on;
    if (want === compact && el.header.classList.contains('dash-header--compact') === want) return;
    compact = want;
    el.header.classList.toggle('dash-header--compact', compact);
    syncPadding(el);
    window.setTimeout(scheduleCardsHeight, 320);
  }

  function updateCompactFromScroll() {
    var el = getEl();
    if (!el.header) return;
    var y = scrollTopNow(el);
    if (y <= EXPAND_MAX_Y) applyCompact(false);
    else if (y >= COMPACT_MIN_Y) applyCompact(true);
  }

  function onCardsScroll() {
    updateCompactFromScroll();
    window.clearTimeout(scrollEndTimer);
    scrollEndTimer = window.setTimeout(function () {
      scrollEndTimer = 0;
      scheduleCardsHeight();
    }, 160);
  }

  function queueTouchScroll() {
    if (touchQueued) return;
    touchQueued = true;
    requestAnimationFrame(function () {
      touchQueued = false;
      updateCompactFromScroll();
    });
  }

  function disconnectListeners() {
    if (dashAbort) {
      try { dashAbort.abort(); } catch (_) {}
      dashAbort = null;
    }
    resizeObs.forEach(function (o) {
      try { o.disconnect(); } catch (_) {}
    });
    resizeObs = [];
    scrollMode = '';
  }

  function teardown() {
    disconnectListeners();
    var el = getEl();
    if (el.header) {
      el.header.classList.remove('dash-header--compact');
    }
    compact = false;
  }

  function bindListeners() {
    disconnectListeners();
    var el = getEl();
    if (!el.header || !el.main) return;

    compact = readCompactFromDom(el);
    scrollMode = scrollModeFor(el);

    dashAbort = new AbortController();
    var sig = dashAbort.signal;
    var opts = { passive: true, signal: sig };

    if (scrollMode === 'cards') {
      el.cardsRoot.addEventListener('scroll', onCardsScroll, opts);
      el.cardsRoot.addEventListener('touchmove', queueTouchScroll, opts);
      el.cardsRoot.addEventListener('touchend', queueTouchScroll, opts);
    } else {
      window.addEventListener('scroll', updateCompactFromScroll, opts);
      document.addEventListener('scroll', updateCompactFromScroll, Object.assign({ capture: true }, opts));
      var shell = document.getElementById('tg-page-shell');
      if (shell) shell.addEventListener('scroll', updateCompactFromScroll, opts);
      var se = document.scrollingElement;
      if (se) se.addEventListener('scroll', updateCompactFromScroll, opts);
    }

    window.addEventListener('resize', function () {
      var cur = getEl();
      if (!cur.header) return;
      var nextMode = scrollModeFor(cur);
      if (nextMode !== scrollMode) {
        bindListeners();
        return;
      }
      syncPadding(cur);
      syncCardsHeight(cur);
      updateCompactFromScroll();
    }, opts);

    try {
      if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', scheduleCardsHeight, opts);
      }
    } catch (_) {}

    try {
      if (el.header && window.ResizeObserver) {
        var ro = new ResizeObserver(function () {
          syncPadding(getEl());
          scheduleCardsHeight();
        });
        ro.observe(el.header);
        resizeObs.push(ro);
        if (el.main) {
          var rom = new ResizeObserver(scheduleCardsHeight);
          rom.observe(el.main);
          resizeObs.push(rom);
        }
      }
    } catch (_) {}
  }

  function setup(opts) {
    opts = opts || {};
    var el = getEl();
    if (!el.header || !el.main) return;

    if (opts.resetScroll !== false) resetScroll(el);
    if (opts.expandHeader !== false) {
      compact = false;
      el.header.classList.remove('dash-header--compact');
    } else {
      compact = readCompactFromDom(el);
    }

    syncPadding(el);
    syncCardsHeight(el);
    bindListeners();
    updateCompactFromScroll();
  }

  function setupDeferred(opts) {
    setup(opts);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        setup(Object.assign({}, opts, { resetScroll: false, expandHeader: false }));
      });
    });
    window.setTimeout(function () {
      setup({ resetScroll: false, expandHeader: false });
    }, 280);
  }

  function sync() {
    var el = getEl();
    if (!el.header) return;
    compact = readCompactFromDom(el);
    syncPadding(el);
    syncCardsHeight(el);
    updateCompactFromScroll();
  }

  window.__vinorDashboardChrome = {
    setup: setupDeferred,
    teardown: teardown,
    sync: sync,
    rebind: bindListeners
  };

  window.__vinorDashboardSyncChrome = function (opts) {
    if (opts && (opts.resetScroll || opts.expandHeader)) {
      setupDeferred(opts);
    } else {
      sync();
    }
  };

  window.__vinorDashboardOnTabEnter = function () {
    setupDeferred({ resetScroll: true, expandHeader: true });
  };

  window.__vinorDashboardBindMobileScroll = function () {
    bindListeners();
  };

  window.__vinorDashboardSyncChromeNow = sync;

  window.addEventListener('vinor:express-page-swap', function (ev) {
    if (!ev.detail || ev.detail.navKey === 'dashboard') return;
    teardown();
  });

  if (isDashboardPage()) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        setupDeferred({ resetScroll: true, expandHeader: true });
      });
    } else {
      setupDeferred({ resetScroll: true, expandHeader: true });
    }
  }
})();
