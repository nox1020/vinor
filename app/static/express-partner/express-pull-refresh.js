/**
 * Pull-to-refresh سراسری — پروفایل، زیرصفحه‌ها و سایر تب‌های اکسپرس (موبایل)
 * داشبورد و پورسانت handler اختصاصی خود را دارند.
 * منطق ژست (قفل محور، اسکرول داخلی، فاصلهٔ فعلی) در express-ptr-core.js است.
 */
(function () {
  'use strict';

  var MOBILE_MQ = '(max-width: 1023px)';
  var pullHandle = null;

  function isMobileViewport() {
    try { return window.matchMedia(MOBILE_MQ).matches; } catch (_) { return window.innerWidth <= 1023; }
  }

  function isAuthPath() {
    var p = window.location.pathname || '';
    return /\/express\/partner\/(?:login|verify|apply|thanks)(?:\/|$)/.test(p);
  }

  function shouldSkipGenericPullRefresh() {
    if (isAuthPath()) return true;
    if (document.getElementById('homeDashboardPage')) return true;
    if (document.querySelector('[data-vinor-ptr="off"]')) return true;
    if (document.querySelector('[data-vinor-postchi-page]')) return true;
    if (document.getElementById('postchiMessages')) return true;
    if (document.getElementById('dashboardMobileCardsRoot') &&
        typeof window.setupVinorDashboardPullRefresh === 'function') {
      return true;
    }
    if (document.getElementById('commissionsPageMain') &&
        typeof window.__vinorCommissionsRefresh === 'function') {
      return true;
    }
    return false;
  }

  function findScrollRoot() {
    var marked = document.querySelector('[data-vinor-ptr-scroll]');
    if (marked) return marked;

    var ids = [
      'aiPageMain',
      'profilePage',
      'profileEditPage',
      'landDetailPage',
      'commissionsTxnPageMain'
    ];
    for (var i = 0; i < ids.length; i++) {
      var el = document.getElementById(ids[i]);
      if (!el) continue;
      try {
        var oy = window.getComputedStyle(el).overflowY;
        if (oy === 'auto' || oy === 'scroll') return el;
      } catch (_) { /* ignore */ }
    }
    return null;
  }

  function setPullHint(visible, refreshing) {
    var hint = document.getElementById('vinorExpressPullHint');
    if (!hint) return;
    hint.classList.toggle('is-visible', !!visible);
    hint.classList.toggle('is-refreshing', !!refreshing);
    hint.setAttribute('aria-hidden', visible ? 'false' : 'true');
  }

  function performRefresh() {
    if (typeof window.__vinorPagePullRefresh === 'function') {
      return Promise.resolve(window.__vinorPagePullRefresh());
    }
    if (typeof window.vinorExpressSoftRefresh === 'function') {
      return window.vinorExpressSoftRefresh();
    }
    window.location.reload();
    return Promise.resolve();
  }

  function setupVinorExpressPullRefresh() {
    if (pullHandle) {
      try { pullHandle.detach(); } catch (_) {}
    }
    pullHandle = null;
    setPullHint(false, false);

    if (!isMobileViewport() || shouldSkipGenericPullRefresh()) return;
    if (!window.VinorPtr || typeof window.VinorPtr.attach !== 'function') return;

    var scrollRoot = findScrollRoot();
    // همیشه روی سند گوش می‌دهیم؛ قبلاً با پیدا شدن ظرف، لمسِ هدر/فوتر هیچ‌وقت رفرش نمی‌کرد.
    pullHandle = window.VinorPtr.attach({
      target: document,
      scrollRoot: scrollRoot,
      setHint: setPullHint,
      onRefresh: performRefresh
    });
  }

  window.setupVinorExpressPullRefresh = setupVinorExpressPullRefresh;

  document.addEventListener('vinor:express-page-swap', setupVinorExpressPullRefresh);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupVinorExpressPullRefresh);
  } else {
    setupVinorExpressPullRefresh();
  }
})();
