/**
 * ناوبری تخصصی پرتال همکار — soft-swap + انیمیشن برای همهٔ مسیرهای /express/partner/
 * رجیستری مسیرها: منبع واحد برای تب، عمق، فوتر و prefetch
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'vinor_express_tab_nav_dir';
  var PREFIX = '/express/partner/';
  var LAND_DETAIL_RE = /^\/express\/partner\/lands\/[^/]+$/;

  /** @type {Record<string, {tab: string, depth: number, bottomNav?: boolean, prefetch?: boolean}>} */
  var ROUTE_REGISTRY = {
    '/express/partner/dashboard': { tab: 'dashboard', depth: 0, bottomNav: true, prefetch: true },
    '/express/partner/commissions': { tab: 'commissions', depth: 0, bottomNav: true, prefetch: false },
    '/express/partner/profile': { tab: 'profile', depth: 0, bottomNav: true, prefetch: false },
    '/express/partner/profile/edit': { tab: 'profile', depth: 1, bottomNav: true, prefetch: false },
    '/express/partner/favorites': { tab: 'favorites', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/notes': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/notifications': { tab: 'notifications', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/postchi': { tab: 'notifications', depth: 2, bottomNav: false, prefetch: false },
    '/express/partner/help': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/support': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/top-sellers': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/invite': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/training': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/routine': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/legal/privacy': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/legal/terms': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/cooperation-terms': { tab: 'dashboard', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/apply': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/thanks': { tab: 'profile', depth: 1, bottomNav: true, prefetch: true },
    '/express/partner/commissions/transactions': { tab: 'commissions', depth: 1, bottomNav: true, prefetch: false },
    '/express/partner/ai': { tab: '', depth: 1, bottomNav: false, prefetch: false },
    '/express/partner/login': { tab: '', depth: 0, bottomNav: false, prefetch: true },
    '/express/partner/login/otp': { tab: '', depth: 1, bottomNav: false, prefetch: true }
  };

  var SKIP_PATH_PREFIXES = [
    '/express/partner/verify',
    '/express/partner/download-app',
    '/express/partner/offline',
    '/express/partner/logout'
  ];

  /** مراحل ورود — ناوبری نرم بین شماره و OTP */
  var AUTH_SOFT_PATHS = [
    '/express/partner/login',
    '/express/partner/login/otp'
  ];

  var prefetchCache = Object.create(null);
  var prefetchInflight = Object.create(null);
  var navGeneration = 0;
  var leaveTimerId = 0;

  /** از چت AI به جزئیات فایل — بارگذاری کامل (soft-swap UI را خالی می‌کند) */
  function isAiChatLandCard(el) {
    if (!el || !el.closest) return false;
    return !!(el.closest('#aiMessages') || el.closest('[data-vinor-ai-card]'));
  }

  function navigateFromAiChatCard(href) {
    try {
      sessionStorage.setItem('vinor_land_from', 'ai');
    } catch (_) {}
    window.location.assign(href);
  }

  function lookupRoute(pathname) {
    var p = normPath(pathname || '');
    if (ROUTE_REGISTRY[p]) return ROUTE_REGISTRY[p];
    if (LAND_DETAIL_RE.test(p)) {
      return { tab: '', depth: 2, bottomNav: false, prefetch: false };
    }
    if (p.indexOf(PREFIX) === 0) {
      return { tab: '', depth: 1, bottomNav: true, prefetch: true };
    }
    return null;
  }

  function routePrefetchAllowed(pathname) {
    var cfg = lookupRoute(pathname);
    if (!cfg) return true;
    return cfg.prefetch !== false;
  }

  /** توقف همه ویدیوها قبل از soft-swap — جلوگیری از ادامه صدا در جزئیات/داشبورد */
  function stopAllExpressMedia() {
    try {
      var swap = document.getElementById('vinor-express-page-swap');
      var roots = swap ? [swap, document] : [document];
      roots.forEach(function (root) {
        root.querySelectorAll('video').forEach(function (v) {
          try {
            v.pause();
            v.muted = true;
            v.defaultMuted = true;
            v.setAttribute('muted', '');
          } catch (_) {}
        });
      });
    } catch (_) {}
  }

  window.vinorExpressStopAllMedia = stopAllExpressMedia;

  /** پاک‌سازی state صفحات قبل از soft-swap — جلوگیری از beforeunload مانده در WebView/APK */
  function teardownSoftNavPageState() {
    try {
      if (window.__vinorProfileEditSaveCtrl) {
        window.__vinorProfileEditSaveCtrl.abort();
        window.__vinorProfileEditSaveCtrl = null;
      }
    } catch (_) {}
    window.__vinorProfileEditIsDirty = null;
    window.__vinorProfileEditMarkDirty = null;
    window.__vinorProfileEditSave = null;
    window.__vinorProfileEditFlushSave = null;
    try {
      if (window.__vinorApplyPageAbort) window.__vinorApplyPageAbort.abort();
    } catch (_) {}
    try {
      if (window.__vinorThanksPageAbort) window.__vinorThanksPageAbort.abort();
    } catch (_) {}
    try {
      if (window.__vinorAuthPageAbort) window.__vinorAuthPageAbort.abort();
    } catch (_) {}
  }
  window.__vinorExpressTeardownPageState = teardownSoftNavPageState;

  function bumpNavGeneration() {
    navGeneration += 1;
    if (leaveTimerId) {
      window.clearTimeout(leaveTimerId);
      leaveTimerId = 0;
    }
    stripNavClasses(document.documentElement);
    return navGeneration;
  }

  function isStaleNav(gen) {
    return gen !== navGeneration;
  }

  function normalizeNavHref(href) {
    try {
      var u = parseUrl(href);
      if (!u) return href;
      if (isAuthSoftPath(u.pathname)) {
        u.searchParams.delete('_');
      }
      var qs = u.searchParams.toString();
      return u.pathname + (qs ? '?' + qs : '') + u.hash;
    } catch (_) {
      return href;
    }
  }

  function normPath(pathname) {
    return (pathname || '').replace(/\/+$/, '') || '/';
  }

  function parseUrl(href) {
    try {
      return new URL(href, window.location.origin);
    } catch (_) {
      return null;
    }
  }

  function isAuthSoftPath(pathname) {
    var p = normPath(pathname || '');
    for (var i = 0; i < AUTH_SOFT_PATHS.length; i++) {
      if (p === AUTH_SOFT_PATHS[i]) return true;
    }
    return false;
  }

  function isHardSkipPath(pathname) {
    var p = normPath(pathname || '');
    for (var i = 0; i < SKIP_PATH_PREFIXES.length; i++) {
      if (p === SKIP_PATH_PREFIXES[i] || p.indexOf(SKIP_PATH_PREFIXES[i] + '/') === 0) return true;
    }
    return false;
  }

  function isAuthShellDoc(doc) {
    if (!doc) return false;
    return !!(doc.getElementById('loginStep1Form') || doc.getElementById('otpForm'));
  }

  function authNavDirection(fromHref, toHref) {
    try {
      var from = normPath(parseUrl(fromHref).pathname);
      var to = normPath(parseUrl(toHref).pathname);
      if (from === '/express/partner/login' && to === '/express/partner/login/otp') return 1;
      if (from === '/express/partner/login/otp' && to === '/express/partner/login') return -1;
    } catch (_) {}
    return 0;
  }

  function shouldForceFullNav(fromHref, toHref) {
    try {
      var fromU = parseUrl(fromHref);
      var toU = parseUrl(toHref);
      if (!fromU || !toU) return false;
      var fromAuth = isAuthSoftPath(fromU.pathname);
      var toAuth = isAuthSoftPath(toU.pathname);
      if (fromAuth && toAuth) return false;
      // ورود/OTP داخل همان شِل swap — auth_base و base هر دو #vinor-express-page-swap دارند
      if ((fromAuth || toAuth) && document.getElementById('vinor-express-page-swap')) return false;
    } catch (_) {}
    return false;
  }

  function shouldPrefetchNav(fromHref, toHref) {
    if (!isPartnerUrl(toHref)) return false;
    if (shouldForceFullNav(fromHref, toHref)) return false;
    try {
      var toPath = normPath(parseUrl(toHref).pathname);
      var fromPath = normPath(parseUrl(fromHref).pathname);
      if (isAuthSoftPath(toPath)) {
        if (toPath === '/express/partner/login') return true;
        if (toPath === '/express/partner/login/otp' && fromPath === '/express/partner/login') return true;
        return false;
      }
    } catch (_) {}
    return true;
  }

  function currentAuthSegment() {
    try {
      var meta = document.querySelector('meta[name="vinor-express-auth"]');
      return (meta && meta.getAttribute('content')) || 'guest';
    } catch (_) {
      return 'guest';
    }
  }

  function authSegmentFromDoc(doc) {
    if (!doc) return '';
    try {
      var meta = doc.querySelector('meta[name="vinor-express-auth"]');
      return (meta && meta.getAttribute('content')) || 'guest';
    } catch (_) {
      return 'guest';
    }
  }

  function syncAuthSegmentFromDoc(doc) {
    try {
      var next = authSegmentFromDoc(doc);
      var meta = document.querySelector('meta[name="vinor-express-auth"]');
      if (meta && next) meta.setAttribute('content', next);
    } catch (_) {}
  }

  function navCacheKey(href) {
    return currentAuthSegment() + '::' + normalizeNavHref(href);
  }

  function clearAllPrefetchCache() {
    try {
      prefetchCache = Object.create(null);
      prefetchInflight = Object.create(null);
    } catch (_) {}
  }

  function clearAuthPrefetchCache() {
    clearAllPrefetchCache();
  }

  function shouldUsePrefetchCache(href) {
    try {
      var p = normPath(parseUrl(href).pathname);
      if (LAND_DETAIL_RE.test(p)) return false;
      if (!routePrefetchAllowed(p)) return false;
      if (p === '/express/partner/login/otp') return true;
      if (p === '/express/partner/login') return true;
      if (isAuthSoftPath(p)) return false;
      return true;
    } catch (_) {
      return true;
    }
  }

  function hasExpressAppShellScripts() {
    try {
      return !!(
        document.querySelector('script[src*="tailwindcdn"]') &&
        document.querySelector('script[src*="dashboard-chrome"]')
      );
    } catch (_) {
      return false;
    }
  }

  function landDetailHtmlLooksValid(html) {
    if (!html || typeof html !== 'string') return false;
    return html.indexOf('id="vinor-land-detail-styles"') !== -1 &&
      html.indexOf('id="landDetailPage"') !== -1;
  }

  function isCurrentAuthShell() {
    try {
      if (document.getElementById('loginStep1Form') || document.getElementById('otpForm')) return true;
      return document.documentElement.classList.contains('vinor-auth-flow');
    } catch (_) {
      return false;
    }
  }

  function needsFullNavForResponse(requestedHref, resolvedUrl, doc, opts) {
    opts = opts || {};
    try {
      var reqPath = normPath(parseUrl(requestedHref).pathname);
      var resPath = normPath(parseUrl(resolvedUrl).pathname);
      var docAuth = authSegmentFromDoc(doc);
      if (!opts.postLogin && docAuth && docAuth !== currentAuthSegment()) return true;
      if (!opts.postLogin && isCurrentAuthShell() && !isAuthShellDoc(doc) && !isAuthSoftPath(resPath)) return true;
      if (!opts.postLogin && !isAuthSoftPath(reqPath) && isAuthShellDoc(doc)) return true;
      if (isHardSkipPath(resPath)) return true;
      if (resPath.indexOf(PREFIX) !== 0) return true;
    } catch (_) {
      return true;
    }
    return false;
  }

  function isPartnerUrl(href) {
    var u = parseUrl(href);
    if (!u || u.origin !== window.location.origin) return false;
    if (u.pathname.indexOf(PREFIX) !== 0) return false;
    var p = normPath(u.pathname);
    if (isAuthSoftPath(p)) return true;
    if (isHardSkipPath(p)) return false;
    return true;
  }

  function softTabKeyForUrl(url) {
    try {
      var cfg = lookupRoute(parseUrl(url).pathname);
      return (cfg && cfg.tab) || '';
    } catch (_) {
      return '';
    }
  }

  function navDepthForUrl(url) {
    try {
      var cfg = lookupRoute(parseUrl(url).pathname);
      if (cfg) return cfg.depth;
      return 0;
    } catch (_) {
      return 0;
    }
  }

  function tabIndexForKey(key) {
    var order = ['dashboard', 'favorites', 'commissions', 'notifications', 'profile'];
    var i = order.indexOf(key);
    return i === -1 ? -1 : i;
  }

  function navDirection(fromHref, toHref, explicitDir) {
    if (explicitDir) return explicitDir;
    var fromKey = softTabKeyForUrl(fromHref);
    var toKey = softTabKeyForUrl(toHref);
    var fromDepth = navDepthForUrl(fromHref);
    var toDepth = navDepthForUrl(toHref);
    if (toDepth > fromDepth) return 1;
    if (toDepth < fromDepth) return -1;
    if (fromKey && toKey && fromKey !== toKey) {
      var fi = tabIndexForKey(fromKey);
      var ti = tabIndexForKey(toKey);
      if (fi >= 0 && ti >= 0 && fi !== ti) return ti > fi ? 1 : -1;
    }
    return 0;
  }

  function prefersReducedMotion() {
    try {
      return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (_) {
      return false;
    }
  }

  function firstAnimName(ev) {
    try {
      var raw = ev.animationName || '';
      var i = raw.indexOf(',');
      return (i === -1 ? raw : raw.slice(0, i)).trim();
    } catch (_) {
      return '';
    }
  }

  function stripNavClasses(el) {
    if (!el || !el.classList) return;
    var rm = [];
    el.classList.forEach(function (c) {
      if (c.indexOf('tg-page-leave-') === 0 || c.indexOf('tg-page-enter-') === 0) rm.push(c);
    });
    rm.forEach(function (c) { el.classList.remove(c); });
    el.classList.remove('tg-nav-transitioning');
  }

  function runScriptsIn(container) {
    if (!container) return;
    container.querySelectorAll('script').forEach(function (oldScript) {
      var s = document.createElement('script');
      Array.prototype.forEach.call(oldScript.attributes, function (attr) {
        s.setAttribute(attr.name, attr.value);
      });
      s.textContent = oldScript.textContent;
      oldScript.parentNode.replaceChild(s, oldScript);
    });
  }

  function isLandDetailPath(pathname) {
    return LAND_DETAIL_RE.test(normPath(pathname || ''));
  }

  function isAiPagePath(pathname) {
    return normPath(pathname || '') === '/express/partner/ai';
  }

  function shouldShowBottomNav(pathname) {
    var cfg = lookupRoute(pathname || window.location.pathname || '');
    if (cfg) return cfg.bottomNav !== false;
    return !isLandDetailPath(pathname) && !isAiPagePath(pathname) && !isAuthSoftPath(normPath(pathname || ''));
  }

  function syncAuthFlowClass(pathname) {
    try {
      var onAuth = isAuthSoftPath(normPath(pathname || window.location.pathname));
      document.documentElement.classList.toggle('vinor-auth-flow', onAuth);
    } catch (_) {}
  }

  function setBottomNavVisible(show) {
    var nav = document.getElementById('bottomNavMenu');
    if (!nav) return;
    if (show) {
      nav.removeAttribute('hidden');
      nav.style.removeProperty('display');
      nav.setAttribute('aria-hidden', 'false');
    } else {
      nav.setAttribute('hidden', 'hidden');
      nav.style.display = 'none';
      nav.setAttribute('aria-hidden', 'true');
    }
  }

  /** منوی پایین باید روی body بماند؛ در swap فقط duplicate حذف شود، نه تنها نسخهٔ موجود */
  function hoistBottomNavFromSwap(swapRoot) {
    if (!swapRoot) {
      swapRoot = document.getElementById('vinor-express-page-swap');
    }
    if (!swapRoot) return;
    var bodyNav = null;
    try {
      bodyNav = document.querySelector('body > #bottomNavMenu');
    } catch (_) {}
    var swapNav = swapRoot.querySelector('#bottomNavMenu');
    if (!swapNav) {
      swapRoot.querySelectorAll('#bottomNavMenu').forEach(function (dup) { dup.remove(); });
      return;
    }
    if (bodyNav && bodyNav !== swapNav) {
      swapNav.remove();
      return;
    }
    if (!bodyNav) {
      try {
        document.body.appendChild(swapNav);
        swapNav.setAttribute('data-tg-shell-done', '1');
      } catch (_) {}
      return;
    }
    swapNav.remove();
  }

  function setBottomNavActive(navKey) {
    var nav = document.getElementById('bottomNavMenu');
    if (!nav || !navKey) return;
    nav.querySelectorAll('#bottomNavItems > a[data-nav-key]').forEach(function (link) {
      var on = link.getAttribute('data-nav-key') === navKey;
      link.classList.toggle('tg-tab-active', on);
      link.setAttribute('aria-current', on ? 'page' : 'false');
    });
  }

  function bottomNavKeyForLocation(href) {
    try {
      var u = parseUrl(href || window.location.href);
      if (!u) return '';
      var p = normPath(u.pathname);
      if (isAuthSoftPath(p)) {
        var nxt = u.searchParams.get('next') || '';
        if (nxt.indexOf('/profile') !== -1) return 'profile';
        return '';
      }
      return softTabKeyForUrl(href || window.location.href);
    } catch (_) {
      return softTabKeyForUrl(href || window.location.href);
    }
  }

  function resetSoftNavPageHooks(pathname) {
    var p = normPath(pathname || window.location.pathname || '');
    if (!/\/express\/partner\/favorites\/?$/.test(p)) {
      try { delete window.__vinorPagePullRefresh; } catch (_) {}
    }
  }

  function syncPartnerCsrfFromPage() {
    try {
      var fresh = '';
      if (typeof window.vinorReadCsrfToken === 'function') {
        fresh = window.vinorReadCsrfToken() || '';
      }
      if (!fresh) {
        var cfgEl = document.getElementById('landDetailConfig');
        if (cfgEl) {
          var pageCfg = JSON.parse(cfgEl.textContent || '{}');
          if (pageCfg && pageCfg.csrfToken) fresh = pageCfg.csrfToken;
        }
      }
      if (fresh && window.VINOR_NOTIFY_CFG) {
        window.VINOR_NOTIFY_CFG.csrfToken = fresh;
      }
    } catch (_) {}
  }

  function afterPageSwap(navKey) {
    try {
      if (typeof VinorOtpBridge !== 'undefined' && VinorOtpBridge.onUrlChanged) {
        VinorOtpBridge.onUrlChanged(String(window.location.href || ''));
      }
    } catch (_) {}
    var path = window.location.pathname;
    resetSoftNavPageHooks(path);
    syncPartnerCsrfFromPage();
    syncAuthFlowClass(path);
    hoistBottomNavFromSwap();
    var onDetail = isLandDetailPath(path);
    var showNav = shouldShowBottomNav(path);
    setBottomNavVisible(showNav);
    if (showNav) {
      var tabKey = navKey || bottomNavKeyForLocation(window.location.href);
      setBottomNavActive(tabKey);
    }
    try {
      var shell = document.getElementById('tg-page-shell');
      if (!onDetail) {
        if (shell) shell.scrollTop = 0;
        window.scrollTo(0, 0);
      } else if (shell) {
        shell.scrollTop = 0;
      }
      var cm = document.getElementById('commissionsPageMain');
      if (cm) cm.scrollTop = 0;
      var cards = document.getElementById('dashboardMobileCardsRoot');
      if (cards) cards.scrollTop = 0;
      var postchiMsgs = document.getElementById('postchiMessages');
      if (postchiMsgs) postchiMsgs.scrollTop = postchiMsgs.scrollHeight;
      document.documentElement.removeAttribute('data-vinor-dash-scroll');
      document.documentElement.removeAttribute('data-vinor-comm-scroll');
    } catch (_) {}
    if (navKey === 'profile' && window.vinorPartnerAvatarCache) {
      try { window.vinorPartnerAvatarCache.apply(document); } catch (_) {}
    }
    if (navKey === 'profile') {
      var prefetchProfileSubpages = function () {
        try {
          [
            '/express/partner/apply',
            '/express/partner/thanks',
            '/express/partner/top-sellers',
            '/express/partner/help',
            '/express/partner/invite',
            '/express/partner/routine'
          ].forEach(function (path) {
            prefetchHref(new URL(path, window.location.origin).href);
          });
        } catch (_) {}
      };
      if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(prefetchProfileSubpages, { timeout: 2200 });
      } else {
        window.setTimeout(prefetchProfileSubpages, 600);
      }
    }
    if (navKey === 'dashboard' && currentAuthSegment() === 'guest') {
      try {
        prefetchHref(new URL('/express/partner/login', window.location.origin).href);
      } catch (_) {}
    }
    if (navKey === 'profile' && currentAuthSegment() === 'guest') {
      try {
        prefetchHref(new URL('/express/partner/login', window.location.origin).href);
      } catch (_) {}
    }
    if (navKey === 'dashboard' && window.__vinorDashboardChrome) {
      window.__vinorDashboardChrome.setup({ resetScroll: true, expandHeader: true });
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          if (typeof window.reinitializeCards === 'function') {
            try { window.reinitializeCards(); } catch (_) {}
          }
          if (typeof window.setupVinorDashboardPullRefresh === 'function') {
            try { window.setupVinorDashboardPullRefresh(); } catch (_) {}
          }
        });
      });
    } else if (window.__vinorDashboardChrome) {
      window.__vinorDashboardChrome.teardown();
    }
    if (navKey === 'commissions' && window.__vinorCommissionsChrome) {
      window.__vinorCommissionsChrome.setup({ resetScroll: !onDetail });
    } else if (window.__vinorCommissionsChrome) {
      window.__vinorCommissionsChrome.teardown();
    }
    try {
      var onCommTxnList = normPath(path) === '/express/partner/commissions/transactions';
      if (!onCommTxnList && window.__vinorCommTxnPageChrome && window.__vinorCommTxnPageChrome.teardown) {
        window.__vinorCommTxnPageChrome.teardown();
      }
      if (!onCommTxnList && typeof window.removeVinorCommTxnModalsFromBody === 'function') {
        window.removeVinorCommTxnModalsFromBody();
      }
    } catch (_) {}
    if (navKey !== 'commissions') {
      try {
        if (window.__vinorCommPullAbort) window.__vinorCommPullAbort.abort();
        if (window.__vinorCommModalAbort) window.__vinorCommModalAbort.abort();
      } catch (_) {}
    }
    if (navKey === 'dashboard' && window.__vinorDashboardVoiceSearch) {
      window.__vinorDashboardVoiceSearch.setup();
    } else if (window.__vinorDashboardVoiceSearch && window.__vinorDashboardVoiceSearch.teardown) {
      window.__vinorDashboardVoiceSearch.teardown();
    }
    try {
      if (onDetail && typeof window.removeVinorLandDetailModalsFromBody === 'function') {
        window.removeVinorLandDetailModalsFromBody();
      }
      if (typeof window.hoistVinorExpressBodyModals === 'function') {
        window.hoistVinorExpressBodyModals();
      }
      if (onDetail && typeof window.vinorScheduleVisitModalRecovery === 'function') {
        try { window.vinorScheduleVisitModalRecovery(); } catch (_) {}
      }
      if (navKey !== 'commissions') {
        if (window.vinorExpressModalOverlay && window.vinorExpressModalOverlay.closeAll) {
          window.vinorExpressModalOverlay.closeAll();
        }
        if (typeof window.removeVinorCommissionModalsFromBody === 'function') {
          window.removeVinorCommissionModalsFromBody();
        }
      }
      if (!document.getElementById('profileEditPage')) {
        if (typeof window.removeVinorProfileEditModalsFromBody === 'function') {
          window.removeVinorProfileEditModalsFromBody();
        }
      }
      if (!onDetail && typeof window.removeVinorLandDetailModalsFromBody === 'function') {
        window.removeVinorLandDetailModalsFromBody();
      }
    } catch (_) {}
    try {
      if (window.Alpine && typeof window.Alpine.initTree === 'function') {
        var root = document.getElementById('vinor-express-page-swap');
        if (root) window.Alpine.initTree(root);
      }
      if (typeof window.vinorPostchiBoot === 'function') {
        window.vinorPostchiBoot();
      }
      if (typeof window.vinorFavoritesBoot === 'function') {
        window.vinorFavoritesBoot();
      }
    } catch (_) {}
    try {
      if (typeof window.reinitializeCards === 'function') window.reinitializeCards();
    } catch (_) {}
    try {
      window.dispatchEvent(new CustomEvent('vinor:express-page-swap', { detail: { navKey: navKey } }));
    } catch (_) {}
    if (onDetail && typeof window.vinorLandDetailGalleryKick === 'function') {
      requestAnimationFrame(function () {
        try { window.vinorLandDetailGalleryKick(); } catch (_) {}
        setTimeout(function () {
          try { window.vinorLandDetailGalleryKick(); } catch (_) {}
        }, 400);
      });
    }
    if (onDetail && typeof window.vinorLandDetailActionsKick === 'function') {
      requestAnimationFrame(function () {
        try { window.vinorLandDetailActionsKick(); } catch (_) {}
        setTimeout(function () {
          try { window.vinorLandDetailActionsKick(); } catch (_) {}
        }, 400);
      });
    }
    try {
      if (typeof window.__vinorPartnerHeaderChromeSetup === 'function') {
        window.__vinorPartnerHeaderChromeSetup();
      } else if (typeof window.__vinorPartnerHeaderPadSync === 'function') {
        window.__vinorPartnerHeaderPadSync();
      }
    } catch (_) {}
    try {
      document.dispatchEvent(new CustomEvent('vinor:city-picker-reinit'));
    } catch (_) {}
    if (typeof window.setupVinorExpressPullRefresh === 'function') {
      try { window.setupVinorExpressPullRefresh(); } catch (_) {}
    }
  }

  function playEnterAnimation(dir) {
    if (!dir || prefersReducedMotion()) return;
    if (isLandDetailPath(window.location.pathname)) return;
    var shell = document.getElementById('tg-page-shell');
    if (!shell) return;
    var rtl = document.documentElement.getAttribute('dir') === 'rtl';
    var enter = rtl
      ? (dir > 0 ? 'tg-page-enter-rtl-forward' : 'tg-page-enter-rtl-back')
      : (dir > 0 ? 'tg-page-enter-ltr-forward' : 'tg-page-enter-ltr-back');
    document.documentElement.classList.add(enter);
    var finished = false;
    function done() {
      if (finished) return;
      finished = true;
      stripNavClasses(document.documentElement);
    }
    function onEnterEnd(ev) {
      if (ev.target !== shell) return;
      if (!/^tgEnter/i.test(firstAnimName(ev))) return;
      shell.removeEventListener('animationend', onEnterEnd);
      done();
    }
    shell.addEventListener('animationend', onEnterEnd);
    setTimeout(function () {
      shell.removeEventListener('animationend', onEnterEnd);
      done();
    }, 220);
  }

  function prefetchHref(href) {
    var key = navCacheKey(href);
    if (!key || prefetchCache[key] || prefetchInflight[key]) return;
    if (!shouldPrefetchNav(window.location.href, href)) return;
    prefetchInflight[key] = true;
    fetch(href, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html', 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (res) {
        if (!res.ok) throw new Error('prefetch');
        return res.text().then(function (html) {
          return { html: html, url: res.url || href };
        });
      })
      .then(function (payload) {
        if (!payload || !payload.html) return;
        var resolved = payload.url || href;
        var doc = new DOMParser().parseFromString(payload.html, 'text/html');
        if (needsFullNavForResponse(href, resolved, doc)) return;
        prefetchCache[navCacheKey(resolved)] = payload.html;
      })
      .catch(function () {})
      .finally(function () {
        delete prefetchInflight[key];
      });
  }

  function softNavigate(href, dir, opts) {
    opts = opts || {};
    var gen = opts.navGen || bumpNavGeneration();
    var navKey = softTabKeyForUrl(href);
    var targetHref = navCacheKey(href);
    try {
      var tp = normPath(parseUrl(href).pathname);
      if (tp === '/express/partner/commissions' || tp === '/express/partner/commissions/transactions') {
        delete prefetchCache[targetHref];
      }
    } catch (_) {}
    var swapEl = document.getElementById('vinor-express-page-swap');
    var scriptsEl = document.getElementById('vinor-express-page-scripts');
    if (!swapEl) {
      window.location.href = href;
      return Promise.resolve(false);
    }

    function applyHtml(html, resolvedHref) {
      if (isStaleNav(gen)) return false;
      var doc = new DOMParser().parseFromString(html, 'text/html');
      var newSwap = doc.getElementById('vinor-express-page-swap');
      var newScripts = doc.getElementById('vinor-express-page-scripts');
      if (!newSwap) throw new Error('swap');
      var finalHref = resolvedHref || href;
      if (isLandDetailPath(normPath(parseUrl(finalHref).pathname)) && !landDetailHtmlLooksValid(html)) {
        try { delete prefetchCache[navCacheKey(finalHref)]; } catch (_) {}
        window.location.assign(finalHref);
        return false;
      }
      if (needsFullNavForResponse(href, finalHref, doc, opts)) {
        window.location.assign(finalHref);
        return false;
      }
      teardownSoftNavPageState();
      stopAllExpressMedia();
      if (typeof window.vinorLandDetailTeardown === 'function') {
        try { window.vinorLandDetailTeardown(); } catch (_) {}
      }
      if (window.__vinorAuthPageAbort) {
        try { window.__vinorAuthPageAbort.abort(); } catch (_) {}
      }
      syncAuthSegmentFromDoc(doc);
      swapEl.innerHTML = newSwap.innerHTML;
      hoistBottomNavFromSwap(swapEl);
      if (scriptsEl && newScripts) {
        scriptsEl.innerHTML = newScripts.innerHTML;
      }
      runScriptsIn(swapEl);
      if (scriptsEl && newScripts) {
        runScriptsIn(scriptsEl);
      }
      if (doc.title) document.title = doc.title;
      if (!opts.fromPopstate) {
        try {
          history.pushState(
            { vinorExpress: true, tabKey: navKey, depth: navDepthForUrl(finalHref) },
            '',
            finalHref
          );
        } catch (_) {}
      }
      if (isStaleNav(gen)) return false;
      afterPageSwap(softTabKeyForUrl(finalHref));
      try {
        window.__vinorExpressNavDepth = navDepthForUrl(finalHref);
      } catch (_) {}
      if (!isLandDetailPath(window.location.pathname)) {
        playEnterAnimation(dir);
      }
      return true;
    }

    var cached = (!opts.postLogin && shouldUsePrefetchCache(href)) ? prefetchCache[targetHref] : null;
    if (cached && isLandDetailPath(normPath(parseUrl(href).pathname)) && !landDetailHtmlLooksValid(cached)) {
      delete prefetchCache[targetHref];
      cached = null;
    }
    if (cached) {
      try {
        return Promise.resolve(applyHtml(cached, href));
      } catch (_) {
        delete prefetchCache[targetHref];
      }
    }

    return fetch(href, {
      credentials: 'same-origin',
      headers: {
        Accept: 'text/html',
        'X-Requested-With': 'XMLHttpRequest'
      },
      cache: opts.postLogin ? 'no-store' : 'default'
    })
      .then(function (res) {
        if (isStaleNav(gen)) return null;
        if (!res.ok) throw new Error('nav');
        return res.text().then(function (html) {
          return { html: html, url: res.url || href };
        });
      })
      .then(function (payload) {
        if (!payload || isStaleNav(gen)) return false;
        if (needsFullNavForResponse(href, payload.url, new DOMParser().parseFromString(payload.html, 'text/html'), opts)) {
          window.location.assign(payload.url || href);
          return false;
        }
        if (shouldUsePrefetchCache(payload.url || href)) {
          prefetchCache[navCacheKey(payload.url || href)] = payload.html;
        }
        return applyHtml(payload.html, payload.url || href);
      })
      .catch(function () {
        if (isStaleNav(gen)) return false;
        window.location.href = href;
        return false;
      });
  }

  function navigateWithAnimation(href, dir, opts) {
    opts = opts || {};
    var gen = opts.navGen || bumpNavGeneration();
    var navOpts = { navGen: gen };
    if (opts.postLogin) navOpts.postLogin = true;
    stopAllExpressMedia();
    var toDetail = false;
    try {
      var u = parseUrl(href);
      if (u) toDetail = isLandDetailPath(u.pathname);
    } catch (_) {}
    if (prefersReducedMotion() || toDetail) {
      return softNavigate(href, dir || 0, navOpts);
    }
    stripNavClasses(document.documentElement);
    var shell = document.getElementById('tg-page-shell');
    if (!shell || !dir) {
      return softNavigate(href, dir || 0, navOpts);
    }
    var rtl = document.documentElement.getAttribute('dir') === 'rtl';
    var leave = rtl
      ? (dir > 0 ? 'tg-page-leave-rtl-forward' : 'tg-page-leave-rtl-back')
      : (dir > 0 ? 'tg-page-leave-ltr-forward' : 'tg-page-leave-ltr-back');
    document.documentElement.classList.add('tg-nav-transitioning', leave);
    var navigated = false;
    function go() {
      if (navigated || isStaleNav(gen)) return;
      navigated = true;
      document.documentElement.classList.remove('tg-nav-transitioning');
      softNavigate(href, dir, navOpts);
    }
    function onLeave(ev) {
      if (isStaleNav(gen)) {
        shell.removeEventListener('animationend', onLeave);
        return;
      }
      if (ev.target !== shell) return;
      if (!/^tgLeave/i.test(firstAnimName(ev))) return;
      shell.removeEventListener('animationend', onLeave);
      go();
    }
    shell.addEventListener('animationend', onLeave);
    leaveTimerId = window.setTimeout(function () {
      leaveTimerId = 0;
      shell.removeEventListener('animationend', onLeave);
      go();
    }, 160);
  }

  function confirmLeaveProfileEdit() {
    if (!document.getElementById('profileEditPage')) return true;
    if (typeof window.__vinorProfileEditIsDirty !== 'function') return true;
    if (!window.__vinorProfileEditIsDirty()) return true;
    return window.confirm('تغییرات ذخیره نشده‌اند. بدون ذخیره خارج می‌شوید؟');
  }

  function flushProfileEditBeforeLeave(fromHref, toHref) {
    try {
      if (!document.getElementById('profileEditPage')) return Promise.resolve();
      var fromPath = normPath(parseUrl(fromHref).pathname);
      var toPath = normPath(parseUrl(toHref).pathname);
      if (fromPath !== '/express/partner/profile/edit' || fromPath === toPath) {
        return Promise.resolve();
      }
      if (!confirmLeaveProfileEdit()) {
        return Promise.reject(new Error('profile_edit_unsaved'));
      }
      teardownSoftNavPageState();
    } catch (_) {}
    return Promise.resolve();
  }

  function vinorExpressNavigate(href, opts) {
    opts = opts || {};
    if (!href) return Promise.resolve(false);
    if (!isPartnerUrl(href)) {
      window.location.href = href;
      return Promise.resolve(false);
    }
    var from = window.location.href;
    try {
      window.__vinorExpressLastHref = from;
    } catch (_) {}
    return flushProfileEditBeforeLeave(from, href).then(function () {
      if (!opts.postLogin && shouldForceFullNav(from, href)) {
        window.location.assign(href);
        return false;
      }
      if (opts.postLogin) {
        stopAllExpressMedia();
        return softNavigate(href, 1, opts);
      }
      var dir = navDirection(from, href, opts.dir);
      if (opts.back) dir = -1;
      if (opts.forward) dir = 1;
      var authDir = authNavDirection(from, href);
      if (authDir) dir = authDir;
      if (dir) {
        try {
          sessionStorage.setItem(STORAGE_KEY, String(dir));
        } catch (_) {}
        return navigateWithAnimation(href, dir, opts);
      }
      stopAllExpressMedia();
      return softNavigate(href, 0, opts);
    }).catch(function (err) {
      if (err && err.message === 'profile_edit_unsaved') return false;
      throw err;
    });
  }

  window.vinorExpressNavigate = vinorExpressNavigate;

  function vinorExpressSoftRefresh() {
    var href = window.location.href.split('#')[0];
    var sep = href.indexOf('?') >= 0 ? '&' : '?';
    var url = href + sep + '_refresh=' + Date.now();
    var swapEl = document.getElementById('vinor-express-page-swap');
    var scriptsEl = document.getElementById('vinor-express-page-scripts');
    if (!swapEl) {
      window.location.reload();
      return Promise.resolve(false);
    }
    stopAllExpressMedia();
    if (typeof window.vinorLandDetailTeardown === 'function') {
      try { window.vinorLandDetailTeardown(); } catch (_) {}
    }
    teardownSoftNavPageState();
    return fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html', 'X-Requested-With': 'XMLHttpRequest' },
      cache: 'no-store'
    })
      .then(function (res) {
        if (!res.ok) throw new Error('refresh');
        return res.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var newSwap = doc.getElementById('vinor-express-page-swap');
        var newScripts = doc.getElementById('vinor-express-page-scripts');
        if (!newSwap) throw new Error('swap');
        syncAuthSegmentFromDoc(doc);
        swapEl.innerHTML = newSwap.innerHTML;
        hoistBottomNavFromSwap(swapEl);
        if (scriptsEl && newScripts) {
          scriptsEl.innerHTML = newScripts.innerHTML;
        }
        runScriptsIn(swapEl);
        if (scriptsEl && newScripts) {
          runScriptsIn(scriptsEl);
        }
        if (doc.title) document.title = doc.title;
        afterPageSwap(softTabKeyForUrl(window.location.href));
        return true;
      })
      .catch(function () {
        window.location.reload();
        return false;
      });
  }
  window.vinorExpressSoftRefresh = vinorExpressSoftRefresh;

  window.vinorExpressPrefetch = prefetchHref;
  window.vinorExpressClearAuthCache = clearAuthPrefetchCache;
  window.vinorExpressClearPrefetchCache = clearAllPrefetchCache;

  function clearExpressPartnerRuntimeCaches() {
    try {
      if (typeof window.vinorClearBottomNavMenuCache === 'function') {
        window.vinorClearBottomNavMenuCache();
      }
    } catch (_) {}
    try {
      if (navigator.serviceWorker && navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage({ type: 'CLEAR_PARTNER_RUNTIME' });
      }
    } catch (_) {}
    try {
      if (window.caches && window.caches.keys) {
        return window.caches.keys().then(function (keys) {
          return Promise.all(keys.filter(function (k) {
            return k.indexOf('express-partner-runtime-') === 0 ||
              k.indexOf('express-partner-api-') === 0;
          }).map(function (k) { return window.caches.delete(k); }));
        });
      }
    } catch (_) {}
    return Promise.resolve();
  }

  function vinorPostLoginNavigate(dest) {
    if (!dest) return;
    clearAuthPrefetchCache();
    clearExpressPartnerRuntimeCaches().finally(function () {
      var destUrl = dest;
      try {
        destUrl = new URL(dest, window.location.origin).href;
      } catch (_) {}
      if (
        document.getElementById('vinor-express-page-swap') &&
        isPartnerUrl(destUrl) &&
        hasExpressAppShellScripts()
      ) {
        vinorExpressNavigate(destUrl, { forward: 1, postLogin: true }).then(function (ok) {
          if (ok === false) window.location.replace(destUrl);
        }).catch(function () {
          window.location.replace(destUrl);
        });
        return;
      }
      window.location.replace(destUrl);
    });
  }
  window.vinorPostLoginNavigate = vinorPostLoginNavigate;

  function clearExpressPartnerCaches() {
    clearAllPrefetchCache();
    clearAuthPrefetchCache();
    try {
      if (typeof window.vinorClearBottomNavMenuCache === 'function') {
        window.vinorClearBottomNavMenuCache();
      }
    } catch (_) {}
    try {
      if (window.vinorPartnerAvatarCache) {
        window.vinorPartnerAvatarCache.clear();
      }
    } catch (_) {}
    try {
      if (/VinorApp\//i.test(navigator.userAgent || '') &&
          window.VinorNativeShell &&
          typeof window.VinorNativeShell.onPartnerLogout === 'function') {
        window.VinorNativeShell.onPartnerLogout();
      }
    } catch (_) {}
    var runtimeClear = clearExpressPartnerRuntimeCaches();
    var shellClear;
    try {
      if (window.caches && window.caches.keys) {
        shellClear = window.caches.keys().then(function (keys) {
          return Promise.all(keys.filter(function (k) {
            return k.indexOf('express-partner-') === 0;
          }).map(function (k) { return window.caches.delete(k); }));
        });
      }
    } catch (_) {}
    if (shellClear && runtimeClear) {
      return Promise.all([shellClear, runtimeClear]).then(function () {});
    }
    return shellClear || runtimeClear || Promise.resolve();
  }

  /** خروج امن: API + پاک‌سازی کش + بارگذاری کامل (APK/WebView/PWA) */
  function vinorExpressLogout(destUrl) {
    bumpNavGeneration();
    stopAllExpressMedia();
    if (window.__vinorAuthPageAbort) {
      try { window.__vinorAuthPageAbort.abort(); } catch (_) {}
    }
    var dest = destUrl || '/express/partner/login?change=1';
    var apiUrl = '/express/partner/api/logout';
    return fetch(apiUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (data && data.redirect) dest = data.redirect;
          return clearExpressPartnerCaches();
        });
      })
      .catch(function () {
        return clearExpressPartnerCaches();
      })
      .then(function () {
        try { sessionStorage.removeItem(STORAGE_KEY); } catch (_) {}
        try { sessionStorage.removeItem('vinor_express_notifications_auto_enabled'); } catch (_) {}
        try { document.documentElement.classList.add('vinor-auth-flow'); } catch (_) {}
        var u = dest;
        u += (u.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now();
        window.location.replace(u);
      });
  }
  window.vinorExpressLogout = vinorExpressLogout;

  window.addEventListener('popstate', function (ev) {
    if (!document.getElementById('vinor-express-page-swap')) return;
    if (!isPartnerUrl(window.location.href)) return;
    var target = window.location.href;
    var dir = 0;
    try {
      var prevDepth = window.__vinorExpressNavDepth;
      var nextDepth = ev.state && typeof ev.state.depth === 'number'
        ? ev.state.depth
        : navDepthForUrl(target);
      if (typeof prevDepth === 'number') {
        if (nextDepth > prevDepth) dir = 1;
        else if (nextDepth < prevDepth) dir = -1;
      }
      var authDir = authNavDirection(window.__vinorExpressLastHref || '', target);
      if (authDir) dir = authDir;
      window.__vinorExpressNavDepth = nextDepth;
      window.__vinorExpressLastHref = target;
    } catch (_) {}
    var flush = document.getElementById('profileEditPage')
      ? (confirmLeaveProfileEdit() ? Promise.resolve() : Promise.reject(new Error('profile_edit_unsaved')))
      : Promise.resolve();
    flush.then(function () {
      softNavigate(target, dir, { fromPopstate: true });
    }).catch(function (err) {
      if (err && err.message === 'profile_edit_unsaved') {
        try { history.forward(); } catch (_) {}
      }
    });
  });

  document.addEventListener('DOMContentLoaded', function () {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw || prefersReducedMotion()) {
        sessionStorage.removeItem(STORAGE_KEY);
        return;
      }
      sessionStorage.removeItem(STORAGE_KEY);
      var dir = parseInt(raw, 10);
      if (!dir) return;
      playEnterAnimation(dir);
    } catch (_) {}
  });

  document.addEventListener(
    'click',
    function (e) {
      if (typeof e.button === 'number' && e.button !== 0) return;
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;

      var card = e.target.closest && e.target.closest('.express-card[data-href]');
      if (card && !e.target.closest('[data-fav-code]')) {
        var cardHref = card.getAttribute('data-href');
        if (cardHref && isPartnerUrl(cardHref)) {
          e.preventDefault();
          e.stopPropagation();
          if (isAiChatLandCard(card)) {
            navigateFromAiChatCard(cardHref);
          } else {
            vinorExpressNavigate(cardHref, { forward: true });
          }
          return;
        }
      }

      var a = e.target.closest && e.target.closest('a[href]');
      if (!a) return;
      if (a.getAttribute('download')) return;
      if (a.getAttribute('target') === '_blank') return;
      var href = a.getAttribute('href');
      if (a.getAttribute('data-vinor-express-full-nav') === '1') {
        e.preventDefault();
        if (href) window.location.assign(href);
        return;
      }
      if (!href || href === '#' || href.indexOf('javascript:') === 0) return;

      if (shouldForceFullNav(window.location.href, href)) {
        if (parseUrl(href) && parseUrl(href).pathname.indexOf(PREFIX) === 0) {
          e.preventDefault();
          window.location.assign(href);
        }
        return;
      }

      if (!isPartnerUrl(href)) return;

      var nav = document.getElementById('bottomNavMenu');
      var isTab = nav && nav.contains(a) && a.hasAttribute('data-nav-key');
      var navAttr = a.getAttribute('data-vinor-express-nav');
      var isBack = navAttr === 'back';
      var isForward = navAttr === 'forward' || navAttr === '1'
        || (a.classList && a.classList.contains('profile-menu-card'));

      if (isTab) {
        e.preventDefault();
        if (prefersReducedMotion()) {
          vinorExpressNavigate(href);
          return;
        }
        var tabs = Array.prototype.slice.call(nav.querySelectorAll('#bottomNavItems > a[data-nav-key]'));
        var ti = tabs.indexOf(a);
        var activeEl = nav.querySelector('.tg-tab-active[data-nav-key]');
        var fi = activeEl ? tabs.indexOf(activeEl) : -1;
        var dir = fi >= 0 && ti >= 0 && fi !== ti ? (ti > fi ? 1 : -1) : 0;
        if (!dir) {
          try {
            var curPath = normPath(parseUrl(window.location.href).pathname);
            var destPath = normPath(parseUrl(href).pathname);
            if (curPath !== destPath) {
              vinorExpressNavigate(href);
            }
          } catch (_) {}
          return;
        }
        e.preventDefault();
        try {
          sessionStorage.setItem(STORAGE_KEY, String(dir));
        } catch (_) {}
        navigateWithAnimation(href, dir);
        return;
      }

      e.preventDefault();
      if (isBack) {
        vinorExpressNavigate(href, { back: true });
      } else if (isForward) {
        vinorExpressNavigate(href, { forward: true });
      } else {
        vinorExpressNavigate(href);
      }
    },
    true
  );

  document.addEventListener(
    'touchstart',
    function (e) {
      var a = e.target.closest && e.target.closest('a[href]');
      if (!a) return;
      var href = a.getAttribute('href');
      if (href && shouldPrefetchNav(window.location.href, href)) prefetchHref(href);
    },
    { passive: true }
  );

  document.addEventListener(
    'mouseover',
    function (e) {
      var a = e.target.closest && e.target.closest('a[href]');
      if (!a) return;
      var href = a.getAttribute('href');
      if (href && shouldPrefetchNav(window.location.href, href)) prefetchHref(href);
    },
    { passive: true }
  );

  function initExpressNavHistory() {
    if (!isPartnerUrl(window.location.href)) return;
    if (isHardSkipPath(window.location.pathname)) return;
    try {
      if (!history.state || !history.state.vinorExpress) {
        history.replaceState({
          vinorExpress: true,
          tabKey: softTabKeyForUrl(window.location.href),
          depth: navDepthForUrl(window.location.href)
        }, '', window.location.href);
      }
      window.__vinorExpressNavDepth = navDepthForUrl(window.location.href);
      window.__vinorExpressLastHref = window.location.href;
    } catch (_) {}
  }

  function syncBottomNavForCurrentPath() {
    var path = window.location.pathname;
    syncAuthFlowClass(path);
    var showNav = shouldShowBottomNav(path);
    setBottomNavVisible(showNav);
    if (showNav) {
      setBottomNavActive(bottomNavKeyForLocation(window.location.href));
    }
  }

  function invalidatePrefetchForHref(href) {
    try {
      var key = navCacheKey(href);
      delete prefetchCache[key];
      var path = normPath(parseUrl(href).pathname);
      Object.keys(prefetchCache).forEach(function (k) {
        if (normPath(k.split('::')[1] || k.split('?')[0]) === path) delete prefetchCache[k];
      });
    } catch (_) {}
  }

  window.vinorExpressInvalidatePrefetch = invalidatePrefetchForHref;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initExpressNavHistory();
      syncBottomNavForCurrentPath();
    });
  } else {
    initExpressNavHistory();
    syncBottomNavForCurrentPath();
  }

  function prefetchMainTabs() {
    try {
      [
        '/express/partner/favorites',
        '/express/partner/commissions',
        '/express/partner/notifications',
        '/express/partner/profile'
      ].forEach(function (path) {
        prefetchHref(new URL(path, window.location.origin).href);
      });
    } catch (_) {}
  }

  if (typeof window.requestIdleCallback === 'function') {
    window.requestIdleCallback(prefetchMainTabs, { timeout: 3500 });
  } else {
    window.setTimeout(prefetchMainTabs, 2200);
  }
})();
