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
    '/express/partner/invite-colleagues': 'profile',
    '/express/partner/training': 'profile',
    '/express/partner/routine': 'profile'
  };

  var SKIP_PATH_PREFIXES = [
    '/express/partner/login',
    '/express/partner/login/otp',
    '/express/partner/verify',
    '/express/partner/apply',
    '/express/partner/thanks',
    '/express/partner/offline',
    '/express/partner/logout'
  ];

  var prefetchCache = Object.create(null);
  var prefetchInflight = Object.create(null);

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

  function isPartnerUrl(href) {
    var u = parseUrl(href);
    if (!u || u.origin !== window.location.origin) return false;
    if (u.pathname.indexOf(PREFIX) !== 0) return false;
    var p = normPath(u.pathname);
    for (var i = 0; i < SKIP_PATH_PREFIXES.length; i++) {
      if (p === SKIP_PATH_PREFIXES[i] || p.indexOf(SKIP_PATH_PREFIXES[i] + '/') === 0) return false;
    }
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
    return !isLandDetailPath(pathname) && !isAiPagePath(pathname);
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

  function afterPageSwap(navKey) {
    var path = window.location.pathname;
    var onDetail = isLandDetailPath(path);
    var showNav = shouldShowBottomNav(path);
    setBottomNavVisible(showNav);
    if (showNav) setBottomNavActive(navKey);
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
    } catch (_) {}
    if (navKey === 'dashboard' && window.__vinorDashboardChrome) {
      window.__vinorDashboardChrome.setup({ resetScroll: true, expandHeader: true });
    } else if (window.__vinorDashboardChrome) {
      window.__vinorDashboardChrome.teardown();
    }
    if (navKey === 'dashboard' && window.__vinorDashboardVoiceSearch) {
      window.__vinorDashboardVoiceSearch.setup();
    } else if (window.__vinorDashboardVoiceSearch && window.__vinorDashboardVoiceSearch.teardown) {
      window.__vinorDashboardVoiceSearch.teardown();
    }
    try {
      if (typeof window.hoistVinorExpressBodyModals === 'function') {
        window.hoistVinorExpressBodyModals();
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
      document.dispatchEvent(new CustomEvent('vinor:city-picker-reinit'));
    } catch (_) {}
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
    if (!href || prefetchCache[href] || prefetchInflight[href]) return;
    prefetchInflight[href] = true;
    fetch(href, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html', 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (res) {
        if (res.ok) return res.text();
        throw new Error('prefetch');
      })
      .then(function (html) {
        prefetchCache[href] = html;
      })
      .catch(function () {})
      .finally(function () {
        delete prefetchInflight[href];
      });
  }

  function softNavigate(href, dir, opts) {
    opts = opts || {};
    var navKey = softTabKeyForUrl(href);
    var swapEl = document.getElementById('vinor-express-page-swap');
    var scriptsEl = document.getElementById('vinor-express-page-scripts');
    if (!swapEl) {
      window.location.href = href;
      return Promise.resolve(false);
    }

    function applyHtml(html) {
      var doc = new DOMParser().parseFromString(html, 'text/html');
      var newSwap = doc.getElementById('vinor-express-page-swap');
      var newScripts = doc.getElementById('vinor-express-page-scripts');
      if (!newSwap) throw new Error('swap');
      stopAllExpressMedia();
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
            { vinorExpress: true, tabKey: navKey, depth: navDepthForUrl(href) },
            '',
            href
          );
        } catch (_) {}
      }
      afterPageSwap(navKey);
      if (!isLandDetailPath(window.location.pathname)) {
        playEnterAnimation(dir);
      }
      return true;
    }

    var cached = prefetchCache[href];
    if (cached) {
      try {
        return Promise.resolve(applyHtml(cached));
      } catch (_) {
        delete prefetchCache[href];
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
        if (!res.ok) throw new Error('nav');
        return res.text();
      })
      .then(function (html) {
        prefetchCache[href] = html;
        return applyHtml(html);
      })
      .catch(function () {
        window.location.href = href;
        return false;
      });
  }

  function navigateWithAnimation(href, dir) {
    stopAllExpressMedia();
    var toDetail = false;
    try {
      var u = parseUrl(href);
      if (u) toDetail = isLandDetailPath(u.pathname);
    } catch (_) {}
    if (prefersReducedMotion() || toDetail) {
      return softNavigate(href, dir || 0);
    }
    stripNavClasses(document.documentElement);
    var shell = document.getElementById('tg-page-shell');
    if (!shell || !dir) {
      return softNavigate(href, dir || 0);
    }
    var rtl = document.documentElement.getAttribute('dir') === 'rtl';
    var leave = rtl
      ? (dir > 0 ? 'tg-page-leave-rtl-forward' : 'tg-page-leave-rtl-back')
      : (dir > 0 ? 'tg-page-leave-ltr-forward' : 'tg-page-leave-ltr-back');
    document.documentElement.classList.add('tg-nav-transitioning', leave);
    var navigated = false;
    function go() {
      if (navigated) return;
      navigated = true;
      document.documentElement.classList.remove('tg-nav-transitioning');
      softNavigate(href, dir);
    }
    function onLeave(ev) {
      if (ev.target !== shell) return;
      if (!/^tgLeave/i.test(firstAnimName(ev))) return;
      shell.removeEventListener('animationend', onLeave);
      go();
    }
    shell.addEventListener('animationend', onLeave);
    setTimeout(function () {
      shell.removeEventListener('animationend', onLeave);
      go();
    }, 160);
  }

  function vinorExpressNavigate(href, opts) {
    opts = opts || {};
    if (!href) return Promise.resolve(false);
    if (!isPartnerUrl(href)) {
      window.location.href = href;
      return Promise.resolve(false);
    }
    var from = window.location.href;
    var dir = navDirection(from, href, opts.dir);
    if (opts.back) dir = -1;
    if (opts.forward) dir = 1;
    if (dir) {
      try {
        sessionStorage.setItem(STORAGE_KEY, String(dir));
      } catch (_) {}
      return navigateWithAnimation(href, dir);
    }
    stopAllExpressMedia();
    return softNavigate(href, 0);
  }

  window.vinorExpressNavigate = vinorExpressNavigate;
  window.vinorExpressPrefetch = prefetchHref;

  window.addEventListener('popstate', function () {
    if (!document.getElementById('vinor-express-page-swap')) return;
    if (!isPartnerUrl(window.location.href)) return;
    softNavigate(window.location.href, 0, { fromPopstate: true });
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
      if (!href || href === '#' || href.indexOf('javascript:') === 0) return;
      if (!isPartnerUrl(href)) return;

      var nav = document.getElementById('bottomNavMenu');
      var isTab = nav && nav.contains(a) && a.hasAttribute('data-nav-key');
      var isBack = a.getAttribute('data-vinor-express-nav') === 'back';

      if (isTab) {
        if (prefersReducedMotion()) return;
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
      if (href && isPartnerUrl(href)) prefetchHref(href);
    },
    { passive: true }
  );

  document.addEventListener(
    'mouseover',
    function (e) {
      var a = e.target.closest && e.target.closest('a[href]');
      if (!a) return;
      var href = a.getAttribute('href');
      if (href && isPartnerUrl(href)) prefetchHref(href);
    },
    { passive: true }
  );

  function syncBottomNavForCurrentPath() {
    var path = window.location.pathname;
    var showNav = shouldShowBottomNav(path);
    setBottomNavVisible(showNav);
    if (showNav) {
      setBottomNavActive(softTabKeyForUrl(window.location.href));
    }
  }

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
