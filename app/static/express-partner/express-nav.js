/**
 * ناوبری سریع پرتال همکار: soft-swap + انیمیشن (مثل تب‌های فوتر) برای همهٔ مسیرهای /express/partner/
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'vinor_express_tab_nav_dir';
  var PREFIX = '/express/partner/';

  var TAB_PATHS = {
    '/express/partner/dashboard': 'dashboard',
    '/express/partner/commissions': 'commissions',
    '/express/partner/profile': 'profile'
  };

  /** از چت AI به جزئیات فایل — بارگذاری کامل صفحه (soft-swap باعث خالی شدن UI می‌شد) */
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

  /** مسیرهای زیرصفحه (عمق ۱) — تب والد برای هایلایت فوتر */
  var STACK_PARENT_TAB = {
    '/express/partner/profile/edit': 'profile',
    '/express/partner/favorites': 'profile',
    '/express/partner/notes': 'profile',
    '/express/partner/notifications': 'profile',
    '/express/partner/help': 'profile',
    '/express/partner/support': 'profile',
    '/express/partner/top-sellers': 'profile',
    '/express/partner/invite': 'profile',
    '/express/partner/training': 'profile',
    '/express/partner/routine': 'profile',
    '/express/partner/cooperation-terms': 'dashboard',
    '/express/partner/commissions/transactions': 'commissions'
  };

  var SKIP_PATH_PREFIXES = [
    '/express/partner/verify',
    '/express/partner/apply',
    '/express/partner/thanks',
    '/express/partner/offline',
    '/express/partner/logout'
  ];

  /** مراحل ورود — ناوبری نرم بین شماره و OTP (نه با تب‌های فوتر) */
  var AUTH_SOFT_PATHS = [
    '/express/partner/login',
    '/express/partner/login/otp'
  ];

  var prefetchCache = Object.create(null);
  var prefetchInflight = Object.create(null);
  var navGeneration = 0;
  var leaveTimerId = 0;

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
      // فقط جابه‌جایی بین شماره و OTP نرم است؛ auth و اپ shell متفاوت دارند
      if (fromAuth && toAuth) return false;
      if (fromAuth || toAuth) return true;
    } catch (_) {}
    return false;
  }

  function shouldPrefetchNav(fromHref, toHref) {
    if (!isPartnerUrl(toHref)) return false;
    if (shouldForceFullNav(fromHref, toHref)) return false;
    try {
      var toPath = normPath(parseUrl(toHref).pathname);
      var fromPath = normPath(parseUrl(fromHref).pathname);
      if (isAuthSoftPath(toPath) && toPath === '/express/partner/login/otp' && fromPath === '/express/partner/login') {
        return true;
      }
      if (isAuthSoftPath(toPath)) return false;
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
      if (p === '/express/partner/profile/edit') return false;
      if (p === '/express/partner/profile') return false;
      if (p === '/express/partner/commissions' || p === '/express/partner/commissions/transactions') return false;
      if (isAuthSoftPath(p)) return p === '/express/partner/login/otp';
      return true;
    } catch (_) {
      return true;
    }
  }

  function isCurrentAuthShell() {
    try {
      if (document.getElementById('loginStep1Form') || document.getElementById('otpForm')) return true;
      return document.documentElement.classList.contains('vinor-auth-flow');
    } catch (_) {
      return false;
    }
  }

  function needsFullNavForResponse(requestedHref, resolvedUrl, doc) {
    try {
      var reqPath = normPath(parseUrl(requestedHref).pathname);
      var resPath = normPath(parseUrl(resolvedUrl).pathname);
      var docAuth = authSegmentFromDoc(doc);
      if (docAuth && docAuth !== currentAuthSegment()) return true;
      if (isCurrentAuthShell() && !isAuthShellDoc(doc) && !isAuthSoftPath(resPath)) return true;
      if (!isAuthSoftPath(reqPath) && isAuthShellDoc(doc)) return true;
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
      var p = normPath(parseUrl(url).pathname);
      if (TAB_PATHS[p]) return TAB_PATHS[p];
      if (STACK_PARENT_TAB[p]) return STACK_PARENT_TAB[p];
      if (/^\/express\/partner\/lands\/[^/]+$/.test(p)) return '';
      return '';
    } catch (_) {
      return '';
    }
  }

  function navDepthForUrl(url) {
    try {
      var p = normPath(parseUrl(url).pathname);
      if (p === '/express/partner/login') return 0;
      if (p === '/express/partner/login/otp') return 1;
      if (TAB_PATHS[p]) return 0;
      if (STACK_PARENT_TAB[p]) return 1;
      if (/^\/express\/partner\/lands\/[^/]+$/.test(p)) return 2;
      return 0;
    } catch (_) {
      return 0;
    }
  }

  function tabIndexForKey(key) {
    var order = ['dashboard', 'commissions', 'profile'];
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
    return /^\/express\/partner\/lands\/[^/]+$/.test(normPath(pathname || ''));
  }

  function isAiPagePath(pathname) {
    return normPath(pathname || '') === '/express/partner/ai';
  }

  function shouldShowBottomNav(pathname) {
    var p = normPath(pathname || window.location.pathname || '');
    return !isLandDetailPath(p) && !isAiPagePath(p) && !isAuthSoftPath(p);
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

  function afterPageSwap(navKey) {
    try {
      if (typeof VinorOtpBridge !== 'undefined' && VinorOtpBridge.onUrlChanged) {
        VinorOtpBridge.onUrlChanged(String(window.location.href || ''));
      }
    } catch (_) {}
    var path = window.location.pathname;
    syncAuthFlowClass(path);
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
      document.documentElement.removeAttribute('data-vinor-dash-scroll');
      document.documentElement.removeAttribute('data-vinor-comm-scroll');
    } catch (_) {}
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
    } catch (_) {}
    try {
      if (typeof window.reinitializeCards === 'function') window.reinitializeCards();
    } catch (_) {}
    try {
      window.dispatchEvent(new CustomEvent('vinor:express-page-swap', { detail: { navKey: navKey } }));
    } catch (_) {}
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
      if (needsFullNavForResponse(href, finalHref, doc)) {
        window.location.assign(finalHref);
        return false;
      }
      stopAllExpressMedia();
      if (window.__vinorAuthPageAbort) {
        try { window.__vinorAuthPageAbort.abort(); } catch (_) {}
      }
      syncAuthSegmentFromDoc(doc);
      swapEl.innerHTML = newSwap.innerHTML;
      swapEl.querySelectorAll('#bottomNavMenu').forEach(function (dup) { dup.remove(); });
      if (scriptsEl && newScripts) {
        scriptsEl.innerHTML = newScripts.innerHTML;
        runScriptsIn(scriptsEl);
      }
      runScriptsIn(swapEl);
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

    var cached = shouldUsePrefetchCache(href) ? prefetchCache[targetHref] : null;
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
      }
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
        if (needsFullNavForResponse(href, payload.url, new DOMParser().parseFromString(payload.html, 'text/html'))) {
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

  function navigateWithAnimation(href, dir) {
    var gen = bumpNavGeneration();
    stopAllExpressMedia();
    var toDetail = false;
    try {
      var u = parseUrl(href);
      if (u) toDetail = isLandDetailPath(u.pathname);
    } catch (_) {}
    if (prefersReducedMotion() || toDetail) {
      return softNavigate(href, dir || 0, { navGen: gen });
    }
    stripNavClasses(document.documentElement);
    var shell = document.getElementById('tg-page-shell');
    if (!shell || !dir) {
      return softNavigate(href, dir || 0, { navGen: gen });
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
      softNavigate(href, dir, { navGen: gen });
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
      if (shouldForceFullNav(from, href)) {
        window.location.assign(href);
        return false;
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
        return navigateWithAnimation(href, dir);
      }
      stopAllExpressMedia();
      return softNavigate(href, 0);
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
    if (window.__vinorAuthPageAbort) {
      try { window.__vinorAuthPageAbort.abort(); } catch (_) {}
    }
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
        swapEl.querySelectorAll('#bottomNavMenu').forEach(function (dup) { dup.remove(); });
        if (scriptsEl && newScripts) {
          scriptsEl.innerHTML = newScripts.innerHTML;
          runScriptsIn(scriptsEl);
        }
        runScriptsIn(swapEl);
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

  function vinorPostLoginNavigate(dest) {
    if (!dest) return;
    clearAuthPrefetchCache();
    window.location.replace(dest);
  }
  window.vinorPostLoginNavigate = vinorPostLoginNavigate;

  function clearExpressPartnerCaches() {
    clearAllPrefetchCache();
    try {
      if (window.caches && window.caches.keys) {
        return window.caches.keys().then(function (keys) {
          return Promise.all(keys.filter(function (k) {
            return k.indexOf('express-partner-') === 0;
          }).map(function (k) { return window.caches.delete(k); }));
        });
      }
    } catch (_) {}
    return Promise.resolve();
  }

  /** خروج امن: API + پاک‌سازی کش + بارگذاری کامل (APK/WebView/PWA) */
  function vinorExpressLogout(destUrl) {
    bumpNavGeneration();
    stopAllExpressMedia();
    if (window.__vinorAuthPageAbort) {
      try { window.__vinorAuthPageAbort.abort(); } catch (_) {}
    }
    var dest = destUrl || '/express/partner/dashboard';
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
        try { document.documentElement.classList.remove('vinor-auth-flow'); } catch (_) {}
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

      var card = e.target.closest && e.target.closest('.express-card.vinor-premium-card[data-href]');
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
      var isBack = a.getAttribute('data-vinor-express-nav') === 'back';

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
        if (!dir) return;
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
    document.addEventListener('DOMContentLoaded', syncBottomNavForCurrentPath);
  } else {
    syncBottomNavForCurrentPath();
  }

  function prefetchMainTabs() {
    try {
      ['/express/partner/commissions', '/express/partner/profile'].forEach(function (path) {
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
