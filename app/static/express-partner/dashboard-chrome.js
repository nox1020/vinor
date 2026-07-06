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
      return p === '/express/partner/files';
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
    return 0;
  }

  function setShellScrollLock(on) {
    try {
      if (on) document.documentElement.setAttribute('data-vinor-dash-scroll', '1');
      else document.documentElement.removeAttribute('data-vinor-dash-scroll');
    } catch (_) {}
  }

  function clearCardsHeight(el) {
    if (!el.cardsRoot) return;
    el.cardsRoot.style.height = '';
    el.cardsRoot.style.maxHeight = '';
    el.cardsRoot.style.minHeight = '';
    el.cardsRoot.removeAttribute('data-vn-dash-scroll-lock');
    el.cardsRoot.style.removeProperty('--vinor-dash-card-h');
    setShellScrollLock(false);
  }

  function isVerticalCardsViewport() {
    try {
      return window.matchMedia('(max-width: 639px)').matches;
    } catch (_) {
      return window.innerWidth <= 639;
    }
  }

  function syncCardsHeight(el) {
    if (!el.cardsRoot) return;
    try {
      if (!window.matchMedia('(max-width: 639px)').matches) {
        clearCardsHeight(el);
        return;
      }
      var cs = window.getComputedStyle(el.cardsRoot);
      if (cs.display === 'none' || cs.visibility === 'hidden') {
        clearCardsHeight(el);
        return;
      }
      var rootTop = el.cardsRoot.getBoundingClientRect().top;
      if (!Number.isFinite(rootTop)) return;

      var nav = document.getElementById('bottomNavMenu');
      var verticalMobile = isVerticalCardsViewport();
      var available;

      if (verticalMobile) {
        /*
          موبایل عمودی: تا انتهای viewport (نه فقط لبهٔ بالای nav) تا پس‌زمینهٔ لیست
          از زیر منوی شیشه‌ای و safe-area دیده شود — نه body مشکی جدا.
        */
        var bottomEdge = window.innerHeight;
        try {
          if (window.visualViewport) {
            bottomEdge = window.visualViewport.offsetTop + window.visualViewport.height;
          }
        } catch (_) {}
        available = bottomEdge - rootTop;
      } else {
        var navTop = nav ? nav.getBoundingClientRect().top : window.innerHeight;
        if (window.visualViewport) {
          var lb = window.visualViewport.offsetTop + window.visualViewport.height;
          navTop = Math.min(navTop, lb);
        }
        available = navTop - rootTop;
        var cardNeed = measureTabletCardHeight(el);
        if (cardNeed > 0) available = Math.max(available, cardNeed + 8);
        available = Math.ceil(available) + HEIGHT_SLACK_PX;
      }

      if (!Number.isFinite(available)) return;
      available = Math.max(160, Math.ceil(available));
      var prev = parseFloat(String(el.cardsRoot.style.height || '').replace('px', ''), 10);
      if (Number.isFinite(prev) && Math.abs(prev - available) < 8) {
        setShellScrollLock(isVerticalCardsViewport() && scrollMode === 'cards');
        try {
          if (isVerticalCardsViewport()) {
            el.cardsRoot.style.setProperty('--vinor-dash-card-h', available + 'px');
          }
        } catch (_) {}
        return;
      }
      el.cardsRoot.style.height = available + 'px';
      el.cardsRoot.style.maxHeight = available + 'px';
      el.cardsRoot.style.minHeight = available + 'px';
      el.cardsRoot.setAttribute('data-vn-dash-scroll-lock', '1');
      setShellScrollLock(isVerticalCardsViewport() && scrollMode === 'cards');
      try {
        if (isVerticalCardsViewport()) {
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

  function mainBannerVisible(main) {
    if (!main) return false;
    try {
      var kids = main.children;
      for (var i = 0; i < kids.length; i++) {
        var node = kids[i];
        if (!node || node.id === 'dashboardMobileCardsRoot') continue;
        var cs = window.getComputedStyle(node);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
        return true;
      }
    } catch (_) {}
    return false;
  }

  function headerGapExtra(el) {
    var base = 8;
    if (!el.main || el.main.getAttribute('data-vinor-dash-partner') !== '1') return base;
    try {
      var raw = window.getComputedStyle(el.main).getPropertyValue('--vn-dash-header-gap').trim();
      if (raw) {
        var n = parseFloat(raw);
        if (Number.isFinite(n)) return Math.max(0, n);
      }
    } catch (_) {}
    return 2;
  }

  function syncPadding(el) {
    if (!el.header || !el.main) return;
    var h = el.header.getBoundingClientRect().height;
    var gapExtra = headerGapExtra(el);
    var padPx = Math.ceil(h + gapExtra);
    var pad = padPx + 'px';
    try {
      el.main.style.setProperty('--vn-dash-header-pad', pad);
    } catch (_) {}
    var verticalMobile = isVerticalCardsViewport();
    var partnerPad = el.main.getAttribute('data-vinor-dash-partner') === '1';
    if (verticalMobile) {
      el.main.style.paddingTop = '0';
      var track = document.getElementById('cardsTrack');
      if (track) {
        if (mainBannerVisible(el.main)) {
          track.style.paddingTop = '0.25rem';
        } else if (partnerPad) {
          track.style.paddingTop = Math.max(0, padPx - 4) + 'px';
        } else {
          track.style.paddingTop = pad;
        }
      }
    } else {
      el.main.style.paddingTop = Math.ceil(h + (partnerPad ? 3 : 6)) + 'px';
      var trackDesktop = document.getElementById('cardsTrack');
      if (trackDesktop) trackDesktop.style.paddingTop = '';
    }
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
    if (!isVerticalCardsViewport()) {
      window.setTimeout(scheduleCardsHeight, 320);
    } else {
      scheduleCardsHeight();
    }
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
    clearCardsHeight(el);
    compact = false;
  }

  function bindListeners() {
    disconnectListeners();
    var el = getEl();
    if (!el.header || !el.main) return;

    compact = readCompactFromDom(el);
    scrollMode = scrollModeFor(el);
    setShellScrollLock(scrollMode === 'cards' && isVerticalCardsViewport());

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
        var nav = document.getElementById('bottomNavMenu');
        if (nav) {
          var ron = new ResizeObserver(scheduleCardsHeight);
          ron.observe(nav);
          resizeObs.push(ron);
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
