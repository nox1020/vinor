/**
 * جزئیات فایل همکار — مخفی شدن هدر شفاف + چسباندن گالری به لبهٔ بالای viewport
 */
(function () {
  'use strict';

  var abort = null;
  var resizeObs = null;
  var lastY = 0;
  var hidden = false;
  var ticking = false;

  var HIDE_AFTER_Y = 20;
  var SHOW_AT_TOP_Y = 6;
  var MIN_DELTA = 5;

  function scrollYNow() {
    if (typeof window.scrollY === 'number' && !Number.isNaN(window.scrollY)) {
      return window.scrollY;
    }
    var shell = document.getElementById('tg-page-shell');
    if (shell && shell.scrollTop) return shell.scrollTop;
    var se = document.scrollingElement;
    return se && se.scrollTop ? se.scrollTop : 0;
  }

  function resetScrollTop() {
    try {
      window.scrollTo(0, 0);
      var shell = document.getElementById('tg-page-shell');
      if (shell) shell.scrollTop = 0;
      var se = document.scrollingElement;
      if (se) se.scrollTop = 0;
    } catch (_) {}
  }

  function setHeaderHidden(header, on) {
    var want = !!on;
    if (!header || want === hidden) return;
    hidden = want;
    header.classList.toggle('is-header-hidden', want);
    header.setAttribute('aria-hidden', want ? 'true' : 'false');
  }

  function updateHeader() {
    var header = document.getElementById('landDetailPartnerHeader');
    if (!header) return;

    var y = scrollYNow();
    var dy = y - lastY;

    if (y <= SHOW_AT_TOP_Y) {
      setHeaderHidden(header, false);
    } else if (dy > MIN_DELTA && y > HIDE_AFTER_Y) {
      setHeaderHidden(header, true);
    } else if (dy < -MIN_DELTA) {
      setHeaderHidden(header, false);
    }

    lastY = y;
  }

  function queueUpdate() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      ticking = false;
      updateHeader();
    });
  }

  function viewportTopOffset() {
    try {
      if (window.visualViewport && typeof window.visualViewport.offsetTop === 'number') {
        return window.visualViewport.offsetTop;
      }
    } catch (_) {}
    return 0;
  }

  function elementTopFromViewport(el) {
    if (!el) return 0;
    var rect = el.getBoundingClientRect();
    return rect.top - viewportTopOffset();
  }

  function clearGalleryPull() {
    var hero = document.querySelector('.land-detail-partner-gallery-hero');
    var gallery = document.getElementById('landGallery');
    var page = document.querySelector('.land-detail-partner-page');
    if (hero) {
      hero.style.removeProperty('margin-top');
      hero.style.removeProperty('transform');
    }
    if (gallery) gallery.style.removeProperty('margin-top');
    if (page) {
      page.style.removeProperty('margin-top');
      page.style.removeProperty('padding-top');
    }
  }

  function flushPartnerGalleryTop() {
    var hero = document.querySelector('.land-detail-partner-gallery-hero');
    var gallery = document.getElementById('landGallery');
    var page = document.querySelector('.land-detail-partner-page');
    if (!hero && !gallery) return;

    var top = elementTopFromViewport(hero || gallery);
    var safe = 'env(safe-area-inset-top, 0px)';

    if (page) {
      page.style.setProperty('margin-top', '0', 'important');
      page.style.setProperty('padding-top', '0', 'important');
    }

    if (hero) {
      if (top > 0.5) {
        hero.style.setProperty('margin-top', (-Math.ceil(top)) + 'px', 'important');
      } else {
        hero.style.removeProperty('margin-top');
      }
    }

    if (gallery) {
      gallery.style.setProperty('margin-top', 'calc(-1 * ' + safe + ')', 'important');
    }
  }

  var galleryFlushTimer = null;

  function scheduleGalleryFlush() {
    /* v2: موقعیت گالری با CSS ثابت است؛ flush تکراری margin باعث پرش بعد از ورود می‌شود */
    if (document.querySelector('.land-detail-v2')) {
      clearGalleryPull();
      return;
    }
    if (galleryFlushTimer) {
      window.clearTimeout(galleryFlushTimer);
      galleryFlushTimer = null;
    }
    flushPartnerGalleryTop();
    requestAnimationFrame(flushPartnerGalleryTop);
    galleryFlushTimer = window.setTimeout(flushPartnerGalleryTop, 120);
  }

  function bindMediaFlush() {
    var video = document.getElementById('landVideo');
    var img = document.getElementById('landMainImage');
    var hero = document.querySelector('.land-detail-partner-gallery-hero');
    if (video) {
      video.addEventListener('loadeddata', scheduleGalleryFlush, { once: true });
      video.addEventListener('loadedmetadata', scheduleGalleryFlush, { once: true });
    }
    if (img) {
      if (img.complete) scheduleGalleryFlush();
      else img.addEventListener('load', scheduleGalleryFlush, { once: true });
    }
    if (hero && window.ResizeObserver) {
      if (resizeObs) {
        try { resizeObs.disconnect(); } catch (_) {}
      }
      resizeObs = new ResizeObserver(scheduleGalleryFlush);
      resizeObs.observe(hero);
    }
  }

  function unbind() {
    if (!abort) return;
    try { abort.abort(); } catch (_) {}
    abort = null;
    if (resizeObs) {
      try { resizeObs.disconnect(); } catch (_) {}
      resizeObs = null;
    }
    clearGalleryPull();
  }

  function bind() {
    unbind();
    var isV2 = !!document.querySelector('.land-detail-v2');
    var header = document.getElementById('landDetailPartnerHeader');
    var hero = document.querySelector('.land-detail-partner-gallery-hero');
    if (!isV2 && !header) return;
    if (isV2 && !hero) return;

    abort = new AbortController();
    var signal = abort.signal;
    var opts = { passive: true, signal: signal };

    hidden = false;
    resetScrollTop();
    lastY = scrollYNow();

    if (header) {
      header.classList.remove('is-header-hidden');
      header.removeAttribute('aria-hidden');
      window.addEventListener('scroll', queueUpdate, opts);
      document.addEventListener('scroll', queueUpdate, Object.assign({ capture: true }, opts));
      var shell = document.getElementById('tg-page-shell');
      if (shell) shell.addEventListener('scroll', queueUpdate, opts);
      queueUpdate();
    }

    window.addEventListener('resize', scheduleGalleryFlush, opts);
    window.addEventListener('orientationchange', scheduleGalleryFlush, opts);
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', scheduleGalleryFlush, opts);
      window.visualViewport.addEventListener('scroll', scheduleGalleryFlush, opts);
    }

    scheduleGalleryFlush();
    bindMediaFlush();
  }

  function scheduleBind() {
    requestAnimationFrame(bind);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scheduleBind);
  } else {
    scheduleBind();
  }

  document.addEventListener('vinor:express-page-swap', scheduleBind);
})();
