/**
 * جزئیات فایل همکار — گالری، ویدیو، مودال‌ها
 */
(function () {
  'use strict';

  var ROOT_SEL = '.land-detail-page';
  var activeRoot = null;
  var cleanupFns = [];
  var activeLandModalId = null;
  var VISIT_SENT_MSG = 'درخواست بازدید ارسال شد';

  function readConfig() {
    var el = document.getElementById('landDetailConfig');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || '{}');
    } catch (e) {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('[vinor land-detail] landDetailConfig parse failed', e);
      }
      return null;
    }
  }

  function stripLegacyVariantQuery(url) {
    var u = String(url || '').trim();
    if (!u || u.indexOf('?') === -1) return u;
    var parts = u.split('?', 2);
    var qs = parts[1] || '';
    if (/(\bfmt=|\bvariant=)/.test(qs)) return parts[0];
    return u;
  }

  function cleanSlideMedia(slide) {
    if (!slide || slide.type !== 'image') return slide;
    var thumb = String(slide.thumb || slide.full || '').trim();
    var full = stripLegacyVariantQuery(String(slide.full || slide.thumb || thumb).trim());
    if (!thumb) thumb = full;
    return { type: 'image', thumb: thumb, full: full };
  }

  function isVinorWebView() {
    return /VinorApp\//i.test(navigator.userAgent || '');
  }

  function isExpressGuestUser() {
    try {
      var meta = document.querySelector('meta[name="vinor-express-auth"]');
      return !meta || meta.getAttribute('content') === 'guest';
    } catch (_) {
      return true;
    }
  }

  function redirectExpressGuestToLogin() {
    var next = window.location.pathname + window.location.search;
    var url = '/express/partner/login?next=' + encodeURIComponent(next);
    if (window.vinorExpressNavigate) {
      window.vinorExpressNavigate(url, { forward: true });
      return;
    }
    window.location.assign(url);
  }

  function hideGalleryLoader() {
    var loader = document.getElementById('landMediaLoading');
    if (!loader) return;
    loader.classList.remove('is-visible', 'opacity-100');
    loader.classList.add('opacity-0');
    loader.setAttribute('aria-hidden', 'true');
  }

  function kickGalleryMedia() {
    var root = document.querySelector(ROOT_SEL);
    if (!root) return;

    var video = document.getElementById('landVideo');
    if (video && !video.classList.contains('hidden')) {
      var deferSrc = video.getAttribute('data-vinor-defer-src');
      if (deferSrc && !video.dataset.vinorSrcLoaded) {
        video.innerHTML = '';
        var source = document.createElement('source');
        source.src = deferSrc;
        source.type = 'video/mp4';
        video.appendChild(source);
        video.dataset.vinorSrcLoaded = '1';
        try { video.load(); } catch (e) { /* ignore */ }
      }
      video.play().catch(function () { /* ignore */ });
      hideGalleryLoader();
      return;
    }

    var img = document.getElementById('landMainImage');
    if (!img || img.classList.contains('hidden')) return;

    if (img.classList.contains('is-loaded')) {
      hideGalleryLoader();
      return;
    }

    if (img.complete && img.naturalWidth > 0) {
      img.classList.add('is-loaded');
      img.classList.remove('is-broken');
      hideGalleryLoader();
      return;
    }

    var src = String(img.getAttribute('src') || img.currentSrc || '').trim();
    if (!src) {
      var cfg = readConfig();
      var slides = (cfg && cfg.slides) || [];
      for (var i = 0; i < slides.length; i++) {
        if (slides[i] && slides[i].type === 'image') {
          src = slides[i].thumb || slides[i].full || '';
          break;
        }
      }
    }
    if (!src) return;

    function onOk() {
      img.classList.add('is-loaded');
      img.classList.remove('is-broken');
      hideGalleryLoader();
    }
    function onFail() {
      img.classList.add('is-broken');
      hideGalleryLoader();
    }

    img.onload = function () { onOk(); };
    img.onerror = function () { onFail(); };
    if (img.getAttribute('src') !== src) {
      img.src = src;
    } else {
      img.src = '';
      img.src = src;
    }
  }

  function scheduleGalleryKick() {
    requestAnimationFrame(kickGalleryMedia);
    setTimeout(kickGalleryMedia, 350);
    setTimeout(kickGalleryMedia, 1500);
  }

  function addCleanup(fn) {
    cleanupFns.push(fn);
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

  function runCleanup() {
    cleanupFns.forEach(function (fn) {
      try { fn(); } catch (e) { /* ignore */ }
    });
    cleanupFns = [];
    if (activeRoot) {
      delete activeRoot.dataset.ldInited;
      delete activeRoot.dataset.ldLandCode;
      var v = activeRoot.querySelector('#landVideo');
      if (v) {
        try { v.pause(); } catch (e2) { /* ignore */ }
      }
    }
    activeRoot = null;
    activeLandModalId = null;
    setBottomNavVisible(true);
    closeLandModals();
    visitCalState.controlsBound = false;
    try {
      if (typeof window.removeVinorLandDetailModalsFromBody === 'function') {
        window.removeVinorLandDetailModalsFromBody();
      }
      removeLandDetailFooterFromBody();
    } catch (e3) { /* ignore */ }
  }

  function removeLandDetailFooterFromBody() {
    try {
      document.querySelectorAll('body > .ld-actions[data-land-detail-footer]').forEach(function (el) {
        el.remove();
      });
    } catch (e) { /* ignore */ }
  }

  function hoistLandDetailFooter() {
    var page = document.getElementById('landDetailPage') || document.querySelector(ROOT_SEL);
    if (!page) return null;
    var footer = page.querySelector('.ld-actions[data-land-detail-footer]') ||
      page.querySelector('.ld-actions');
    if (!footer) return null;
    if (footer.parentNode !== document.body) {
      document.body.appendChild(footer);
    }
    footer.style.zIndex = '70';
    return footer;
  }

  function bindContactModalTel() {
    var modal = document.getElementById('landContactModal');
    if (!modal) return;
    var link = modal.querySelector('a[href^="tel:"]');
    if (!link || link.dataset.ldTelBound === '1') return;
    link.dataset.ldTelBound = '1';
    function onTelClick(ev) {
      var href = String(link.getAttribute('href') || '').trim();
      if (!href) return;
      if (isVinorWebView()) {
        ev.preventDefault();
        try {
          window.location.href = href;
        } catch (e) {
          window.open(href, '_self');
        }
      }
    }
    link.addEventListener('click', onTelClick);
    addCleanup(function () {
      link.removeEventListener('click', onTelClick);
      delete link.dataset.ldTelBound;
    });
  }

  function landModalOverlayOpen() {
    if (window.vinorExpressModalOverlay && window.vinorExpressModalOverlay.open) {
      window.vinorExpressModalOverlay.open();
      return;
    }
    document.documentElement.classList.add('vinor-express-overlay-modal-open');
    document.body.style.overflow = 'hidden';
  }

  function landModalOverlayClose() {
    if (window.vinorExpressModalOverlay && window.vinorExpressModalOverlay.close) {
      window.vinorExpressModalOverlay.close();
      return;
    }
    document.documentElement.classList.remove('vinor-express-overlay-modal-open');
    document.body.style.overflow = '';
  }

  function landModalOverlayCloseAll() {
    if (window.vinorExpressModalOverlay && window.vinorExpressModalOverlay.closeAll) {
      window.vinorExpressModalOverlay.closeAll();
      return;
    }
    document.documentElement.classList.remove('vinor-express-overlay-modal-open');
    document.body.style.overflow = '';
  }

  function closeLandModals() {
    document.querySelectorAll('.ld-modal.is-open').forEach(function (m) {
      m.classList.remove('is-open');
    });
    var toHide = document.querySelectorAll('.ld-modal:not(.hidden)');
    if (!toHide.length) {
      activeLandModalId = null;
      landModalOverlayCloseAll();
      return;
    }
    setTimeout(function () {
      document.querySelectorAll('.ld-modal').forEach(function (m) {
        m.classList.add('hidden');
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
      });
      activeLandModalId = null;
      landModalOverlayCloseAll();
    }, 300);
  }

  function openLandModal(id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    document.querySelectorAll('.ld-modal.is-open').forEach(function (m) {
      if (m !== modal) {
        m.classList.remove('is-open');
        m.classList.add('hidden');
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
      }
    });
    modal.classList.remove('hidden');
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
    activeLandModalId = id;
    landModalOverlayOpen();
    if (id === 'landContactModal') {
      bindContactModalTel();
    }
    if (id === 'landDealModal') {
      syncDealModalVisitHint();
    }
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        modal.classList.add('is-open');
      });
    });
    var panel = modal.querySelector('[data-land-modal-panel]');
    if (panel) {
      try {
        var focusable = panel.querySelector('button:not([disabled]), [href], input:not([disabled])');
        if (focusable) focusable.focus({ preventScroll: true });
      } catch (e) { /* ignore */ }
    }
  }

  function initGallery(cfg) {
    var gallery = document.getElementById('landGallery');
    if (!gallery || !cfg || !cfg.slides || !cfg.slides.length) {
      var loneImg = document.getElementById('landMainImage');
      if (loneImg && loneImg.getAttribute('src')) {
        var loneLoader = document.getElementById('landMediaLoading');
        function loneReveal() {
          if (loneLoader) {
            loneLoader.classList.remove('is-visible', 'opacity-100');
            loneLoader.classList.add('opacity-0');
            loneLoader.setAttribute('aria-hidden', 'true');
          }
          loneImg.classList.add('is-loaded');
        }
        if (loneImg.complete && loneImg.naturalWidth > 0) loneReveal();
        else {
          loneImg.addEventListener('load', loneReveal, { once: true });
          loneImg.addEventListener('error', loneReveal, { once: true });
        }
      }
      return;
    }

    var slides = cfg.slides.map(cleanSlideMedia);
    var video = document.getElementById('landVideo');
    var img = document.getElementById('landMainImage');
    var dots = document.querySelectorAll('.ld-gallery__dots--footer .ld-dot');
    var label = document.getElementById('landGallerySlideLabel');
    var index = 0;
    var loadFallbackTimer = null;
    var LOADER_MAX_MS = 45000;
    var activeSlideReq = 0;

    function isSwipeControlTarget(node) {
      if (!node || !node.closest) return false;
      return !!node.closest(
        '#landVideoSoundToggle, #landVideoSoundWrap, #landDetailMoreBtn, #landDetailMoreMenu, ' +
        '#landDetailDownloadBtn, [data-land-detail-fav], [data-vinor-express-nav], .ld-dot'
      );
    }

    function setLoader(visible) {
      var loader = document.getElementById('landMediaLoading');
      if (!loader) return;
      if (loadFallbackTimer) {
        clearTimeout(loadFallbackTimer);
        loadFallbackTimer = null;
      }
      if (visible) {
        loader.classList.add('is-visible', 'opacity-100');
        loader.classList.remove('opacity-0');
        loader.setAttribute('aria-hidden', 'false');
        loadFallbackTimer = setTimeout(function () {
          setLoader(false);
        }, LOADER_MAX_MS);
      } else {
        loader.classList.remove('is-visible', 'opacity-100');
        loader.classList.add('opacity-0');
        loader.setAttribute('aria-hidden', 'true');
      }
    }

    function imageReady(el) {
      return !!(el && el.complete && el.naturalWidth > 0);
    }

    function waitForImage(el, done) {
      if (!el) {
        done();
        return;
      }
      if (imageReady(el)) {
        done();
        return;
      }
      var finished = false;
      function once() {
        if (finished) return;
        finished = true;
        el.removeEventListener('load', once);
        el.removeEventListener('error', once);
        done();
      }
      el.addEventListener('load', once);
      el.addEventListener('error', once);
    }

    function waitForVideo(el, done) {
      if (!el) {
        done();
        return;
      }
      if (el.readyState >= 2) {
        done();
        return;
      }
      var finished = false;
      function once() {
        if (finished) return;
        finished = true;
        el.removeEventListener('loadeddata', once);
        el.removeEventListener('canplay', once);
        el.removeEventListener('error', once);
        done();
      }
      el.addEventListener('loadeddata', once);
      el.addEventListener('canplay', once);
      el.addEventListener('error', once);
    }

    function faDigits(n) {
      return String(n).replace(/\d/g, function (d) {
        return '۰۱۲۳۴۵۶۷۸۹'[d];
      });
    }

    function setVideoSoundVisible(visible) {
      var wrap = document.getElementById('landVideoSoundWrap');
      if (!wrap) return;
      wrap.classList.toggle('hidden', !visible);
      wrap.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }

    function preloadAdjacentSlides() {
      if (slides.length < 2) return;
      var targets = [index - 1, index + 1];
      targets.forEach(function (offset) {
        var i = offset;
        if (i < 0) i = slides.length - 1;
        if (i >= slides.length) i = 0;
        var s = slides[i];
        if (!s || s.type !== 'image') return;
        var u = s.thumb || s.full;
        if (!u) return;
        var pre = new Image();
        pre.decoding = 'async';
        pre.src = u;
      });
    }

    function showImageSlide(slide) {
      if (!img) return;
      var reqId = ++activeSlideReq;
      function isStale() {
        return reqId !== activeSlideReq;
      }

      setVideoSoundVisible(false);
      if (video) {
        try { video.pause(); } catch (e) { /* ignore */ }
        video.classList.add('hidden');
      }
      img.classList.remove('hidden');
      var thumb = slide.thumb || slide.full;
      var full = slide.full || thumb;
      var sameSrc = (img.getAttribute('src') || '') === thumb;

      function reveal(ok) {
        if (isStale()) return;
        setLoader(false);
        img.classList.add('is-loaded');
        img.classList.toggle('is-broken', ok === false);
        if (ok !== false) preloadAdjacentSlides();
      }

      function bindLoad(src, allowFullFallback) {
        var triedFull = false;
        setLoader(true);

        if (isVinorWebView()) {
          function directAttempt(url, canFallback) {
            if (isStale()) return;
            img.onload = function () {
              if (isStale()) return;
              img.onerror = null;
              img.dataset.full = full;
              reveal(true);
            };
            img.onerror = function () {
              if (isStale()) return;
              if (canFallback && !triedFull && full && url !== full) {
                triedFull = true;
                directAttempt(full, false);
                return;
              }
              reveal(false);
            };
            if (img.getAttribute('src') !== url) {
              img.src = url;
            } else {
              img.src = '';
              img.src = url;
            }
            img.dataset.full = full;
          }
          directAttempt(src, allowFullFallback);
          return;
        }

        function attempt(url, canFallback) {
          if (isStale()) return;
          var pre = new Image();
          pre.decoding = 'async';
          pre.onload = function () {
            if (isStale()) return;
            img.onload = null;
            img.onerror = null;
            img.src = url;
            img.dataset.full = full;
            reveal(true);
          };
          pre.onerror = function () {
            if (isStale()) return;
            if (canFallback && !triedFull && full && url !== full) {
              triedFull = true;
              attempt(full, false);
              return;
            }
            reveal(false);
          };
          pre.src = url;
        }

        attempt(src, allowFullFallback);
      }

      if (sameSrc) {
        if (imageReady(img)) {
          reveal(true);
          return;
        }
        img.classList.remove('is-loaded', 'is-broken');
        setLoader(true);
        var waitedFull = false;
        function onSameDone() {
          if (isStale()) return;
          if (imageReady(img)) {
            reveal(true);
            return;
          }
          if (!waitedFull && full && thumb !== full) {
            waitedFull = true;
            bindLoad(full, false);
            return;
          }
          reveal(false);
        }
        waitForImage(img, onSameDone);
        return;
      }

      bindLoad(thumb, thumb !== full);
    }

    function showVideoSlide() {
      activeSlideReq++;
      if (!video) return;
      setVideoSoundVisible(true);
      if (img) {
        img.classList.add('hidden');
        img.classList.remove('is-loaded');
      }
      video.classList.remove('hidden');
      var deferSrc = video.getAttribute('data-vinor-defer-src');
      if (deferSrc && !video.dataset.vinorSrcLoaded) {
        video.innerHTML = '';
        var source = document.createElement('source');
        source.src = deferSrc;
        source.type = 'video/mp4';
        video.appendChild(source);
        video.dataset.vinorSrcLoaded = '1';
        try { video.load(); } catch (e) { /* ignore */ }
      }
      setLoader(true);
      waitForVideo(video, function () {
        setLoader(false);
        video.play().catch(function () {});
      });
      video.play().catch(function () {});
    }

    function syncGalleryChrome() {
      dots.forEach(function (dot) {
        var dotIdx = parseInt(dot.getAttribute('data-index'), 10);
        if (!isNaN(dotIdx)) {
          dot.classList.toggle('is-active', dotIdx === index);
        }
      });
      if (label && cfg.totalItems > 1) {
        var countEl = label.querySelector('[data-slide-count]');
        var countText = faDigits(index + 1) + ' از ' + faDigits(cfg.totalItems);
        if (countEl) countEl.textContent = countText;
        else label.textContent = countText;
      }
    }

    function updateUi() {
      syncGalleryChrome();
      var slide = slides[index];
      if (!slide) return;
      if (slide.type === 'video') {
        showVideoSlide();
      } else if (slide.type === 'image') {
        showImageSlide(slide);
      }
    }

    function goTo(next) {
      if (next < 0) next = slides.length - 1;
      if (next >= slides.length) next = 0;
      if (next === index) return;
      index = next;
      syncGalleryChrome();
      var slide = slides[index];
      if (!slide) return;
      if (slide.type === 'video') {
        showVideoSlide();
      } else if (slide.type === 'image') {
        showImageSlide(slide);
      }
    }

    function bindGallerySwipe(el) {
      if (!el) return;
      var touchStartX = null;
      var touchStartY = null;
      var touchEndX = null;
      var swipeAxis = null;
      var swipeLockUntil = 0;
      var SWIPE_THRESHOLD = 28;
      var usePointer = !('ontouchstart' in window);

      function handleSwipe(dx) {
        if (Date.now() < swipeLockUntil) return;
        if (Math.abs(dx) < SWIPE_THRESHOLD) return;
        swipeLockUntil = Date.now() + 280;
        if (dx < 0) goTo(index + 1);
        else goTo(index - 1);
      }

      function resetTouch() {
        touchStartX = null;
        touchStartY = null;
        touchEndX = null;
        swipeAxis = null;
      }

      function onTouchStart(e) {
        if (isSwipeControlTarget(e.target)) return;
        var t = e.touches && e.touches[0];
        if (!t) return;
        touchStartX = t.clientX;
        touchStartY = t.clientY;
        touchEndX = null;
        swipeAxis = null;
      }

      function onTouchMove(e) {
        if (touchStartX === null || touchStartY === null) return;
        var t = e.touches && e.touches[0];
        if (!t) return;
        var dx = t.clientX - touchStartX;
        var dy = t.clientY - touchStartY;
        if (!swipeAxis) {
          if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return;
          swipeAxis = Math.abs(dx) >= Math.abs(dy) ? 'x' : 'y';
        }
        if (swipeAxis === 'x') {
          touchEndX = t.clientX;
          if (e.cancelable) e.preventDefault();
        }
      }

      function onTouchEnd(e) {
        if (isSwipeControlTarget(e.target)) return;
        if (touchStartX === null) return;
        var t = e.changedTouches && e.changedTouches[0];
        var endX = touchEndX !== null ? touchEndX : (t ? t.clientX : touchStartX);
        if (swipeAxis === 'x') handleSwipe(endX - touchStartX);
        resetTouch();
      }

      function onTouchCancel() {
        resetTouch();
      }

      el.addEventListener('touchstart', onTouchStart, { passive: true });
      el.addEventListener('touchmove', onTouchMove, { passive: false });
      el.addEventListener('touchend', onTouchEnd, { passive: true });
      el.addEventListener('touchcancel', onTouchCancel, { passive: true });

      addCleanup(function () {
        el.removeEventListener('touchstart', onTouchStart);
        el.removeEventListener('touchmove', onTouchMove);
        el.removeEventListener('touchend', onTouchEnd);
        el.removeEventListener('touchcancel', onTouchCancel);
      });

      if (!usePointer) return;

      var pointerDown = false;
      function onPointerDown(e) {
        if (isSwipeControlTarget(e.target)) return;
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        pointerDown = true;
        touchStartX = e.clientX;
        touchEndX = null;
        try { el.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      }

      function onPointerMove(e) {
        if (!pointerDown || touchStartX === null) return;
        touchEndX = e.clientX;
      }

      function onPointerUp(e) {
        if (isSwipeControlTarget(e.target)) return;
        if (!pointerDown || touchStartX === null) return;
        pointerDown = false;
        var endX = touchEndX !== null ? touchEndX : e.clientX;
        handleSwipe(endX - touchStartX);
        touchStartX = null;
        touchEndX = null;
        try { el.releasePointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      }

      function onPointerCancel() {
        pointerDown = false;
        touchStartX = null;
        touchEndX = null;
      }

      el.addEventListener('pointerdown', onPointerDown);
      el.addEventListener('pointermove', onPointerMove);
      el.addEventListener('pointerup', onPointerUp);
      el.addEventListener('pointercancel', onPointerCancel);

      addCleanup(function () {
        el.removeEventListener('pointerdown', onPointerDown);
        el.removeEventListener('pointermove', onPointerMove);
        el.removeEventListener('pointerup', onPointerUp);
        el.removeEventListener('pointercancel', onPointerCancel);
      });
    }

    dots.forEach(function (dot, i) {
      function onDotClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var idx = parseInt(dot.getAttribute('data-index'), 10);
        if (!isNaN(idx)) goTo(idx);
      }
      dot.style.pointerEvents = 'auto';
      dot.style.cursor = 'pointer';
      dot.addEventListener('click', onDotClick);
      addCleanup(function () {
        dot.removeEventListener('click', onDotClick);
      });
    });

    bindGallerySwipe(document.getElementById('landGallerySwipe') || gallery);

    addCleanup(function () {
      if (loadFallbackTimer) {
        clearTimeout(loadFallbackTimer);
        loadFallbackTimer = null;
      }
      setLoader(false);
      if (video) {
        try { video.pause(); } catch (e2) { /* ignore */ }
      }
    });

    if (slides.length > 1 && slides[0] && slides[0].type === 'video') {
      for (var si = 0; si < slides.length; si++) {
        if (slides[si].type === 'image') {
          index = si;
          break;
        }
      }
    }

    updateUi();

    var galleryWatchdog = setTimeout(function () {
      var img = document.getElementById('landMainImage');
      var loader = document.getElementById('landMediaLoading');
      if (!img || img.classList.contains('hidden')) return;
      if (img.classList.contains('is-loaded')) return;
      if (loader && loader.classList.contains('is-visible')) {
        kickGalleryMedia();
      }
    }, 2800);
    addCleanup(function () {
      clearTimeout(galleryWatchdog);
    });

    if (isVinorWebView()) {
      scheduleGalleryKick();
    }
  }

  function initVideoSound() {
    var btn = document.getElementById('landVideoSoundToggle');
    var video = document.getElementById('landVideo');
    var icon = document.getElementById('landVideoSoundIcon');
    if (!video) return;

    function isVideoSlideActive() {
      if (video.classList.contains('hidden')) return false;
      var wrap = document.getElementById('landVideoSoundWrap');
      if (wrap && wrap.classList.contains('hidden')) return false;
      return true;
    }

    function applyMuted(muted) {
      video.muted = muted;
      if (btn) {
        btn.dataset.muted = muted ? 'true' : 'false';
        btn.setAttribute('aria-pressed', muted ? 'true' : 'false');
        btn.setAttribute('aria-label', muted ? 'بی‌صدا' : 'با صدا');
      }
      if (icon) {
        icon.className = muted ? 'fas fa-volume-xmark text-sm' : 'fas fa-volume-high text-sm';
      }
      if (!muted) {
        try { video.volume = 1; } catch (e) { /* ignore */ }
      }
    }

    function unmuteFromVolumeKey() {
      if (!isVideoSlideActive()) return false;
      if (!video.muted) return false;
      applyMuted(false);
      video.play().catch(function () {});
      return true;
    }

    window.vinorLandDetailHandleVolumeKey = unmuteFromVolumeKey;

    function onClick(e) {
      e.stopPropagation();
      applyMuted(!video.muted);
      if (!video.muted) video.play().catch(function () {});
    }

    applyMuted(true);
    if (btn) {
      btn.addEventListener('click', onClick);
    }
    addCleanup(function () {
      if (btn) btn.removeEventListener('click', onClick);
      if (window.vinorLandDetailHandleVolumeKey === unmuteFromVolumeKey) {
        delete window.vinorLandDetailHandleVolumeKey;
      }
      applyMuted(true);
    });
  }

  function initMoreMenu() {
    var btn = document.getElementById('landDetailMoreBtn');
    var menu = document.getElementById('landDetailMoreMenu');
    if (!btn || !menu) return;

    function close() {
      menu.classList.add('hidden');
      btn.setAttribute('aria-expanded', 'false');
    }
    function toggle(e) {
      e.stopPropagation();
      menu.classList.toggle('hidden');
      btn.setAttribute('aria-expanded', menu.classList.contains('hidden') ? 'false' : 'true');
    }
    function onDocClick() {
      close();
    }

    function onMenuClick(e) {
      e.stopPropagation();
    }

    btn.addEventListener('click', toggle);
    menu.addEventListener('click', onMenuClick);
    document.addEventListener('click', onDocClick);
    addCleanup(function () {
      btn.removeEventListener('click', toggle);
      menu.removeEventListener('click', onMenuClick);
      document.removeEventListener('click', onDocClick);
      close();
    });

    menu.querySelectorAll('[data-copy-text]').forEach(function (item) {
      function onCopy() {
        var t = item.getAttribute('data-copy-text');
        if (!t) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(t).catch(function () {});
        }
        close();
      }
      item.addEventListener('click', onCopy);
      addCleanup(function () {
        item.removeEventListener('click', onCopy);
      });
    });
  }

  function initShare(cfg) {
    var btn = document.getElementById('landDetailShareBtn');
    if (!btn) return;
    function closeMoreMenu() {
      var menu = document.getElementById('landDetailMoreMenu');
      var moreBtn = document.getElementById('landDetailMoreBtn');
      if (menu) menu.classList.add('hidden');
      if (moreBtn) moreBtn.setAttribute('aria-expanded', 'false');
    }
    function onShare() {
      var url = (cfg && cfg.shareUrl) || window.location.href;
      var title = document.title || 'فایل';
      closeMoreMenu();
      if (navigator.share) {
        navigator.share({ title: title, url: url }).catch(function () {});
      } else if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).catch(function () {});
      }
    }
    btn.addEventListener('click', onShare);
    addCleanup(function () {
      btn.removeEventListener('click', onShare);
    });
  }

  function initModals() {
    function onDocClick(ev) {
      if (ev.target.closest('[data-land-modal-close]')) {
        ev.preventDefault();
        ev.stopPropagation();
        closeLandModals();
      }
    }

    function onEscape(ev) {
      if (ev.key !== 'Escape' || !activeLandModalId) return;
      ev.preventDefault();
      closeLandModals();
    }

    document.querySelectorAll('[data-land-open-contact]').forEach(function (btn) {
      if (btn.dataset.ldContactBound === '1') return;
      btn.dataset.ldContactBound = '1';
      function onContact(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (isExpressGuestUser()) {
          redirectExpressGuestToLogin();
          return;
        }
        openLandModal('landContactModal');
      }
      btn.addEventListener('click', onContact);
      addCleanup(function () {
        btn.removeEventListener('click', onContact);
        delete btn.dataset.ldContactBound;
      });
    });

    document.querySelectorAll('[data-land-open-location]').forEach(function (btn) {
      if (btn.dataset.ldLocationBound === '1') return;
      btn.dataset.ldLocationBound = '1';
      function onLocation(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        openLandModal('landLocationModal');
      }
      btn.addEventListener('click', onLocation);
      addCleanup(function () {
        btn.removeEventListener('click', onLocation);
        delete btn.dataset.ldLocationBound;
      });
    });

    document.addEventListener('click', onDocClick, true);
    document.addEventListener('keydown', onEscape);
    addCleanup(function () {
      document.removeEventListener('click', onDocClick, true);
      document.removeEventListener('keydown', onEscape);
      closeLandModals();
    });
  }

  var TX_UI = {
    visit: {
      label: 'درخواست بازدید',
      icon: 'fa-calendar-check',
      btnClass: 'ld-btn-tx',
      specLabel: 'فعال',
    },
    revisit: {
      label: 'بازدید مجدد',
      icon: 'fa-calendar-plus',
      btnClass: 'ld-btn-tx',
      specLabel: 'ثبت بازدید جدید',
    },
    visit_pending: {
      label: 'در انتظار بازدید',
      icon: 'fa-clock',
      btnClass: 'ld-btn-tx ld-btn-tx--pending cursor-default',
      specLabel: 'منتظر تأیید ادمین',
    },
    visit_done: {
      label: 'بازدید انجام شد',
      icon: 'fa-check-double',
      btnClass: 'ld-btn-tx',
      specLabel: 'بازدید تأییدشده',
    },
    visit_done_pending: {
      label: 'در انتظار تأیید بازدید',
      icon: 'fa-clock',
      btnClass: 'ld-btn-tx ld-btn-tx--pending cursor-default',
      specLabel: 'منتظر تأیید انجام بازدید',
    },
    visit_commission_pending: {
      label: 'در انتظار پورسانت بازدید',
      icon: 'fa-clock',
      btnClass: 'ld-btn-tx ld-btn-tx--pending cursor-default',
      specLabel: 'منتظر تأیید پورسانت بازدید',
    },
    deal: {
      label: 'درخواست معامله',
      icon: 'fa-handshake',
      btnClass: 'ld-btn-tx',
      specLabel: 'بازدید ثبت‌شده',
    },
    deal_pending: {
      label: 'معامله ثبت شد',
      icon: 'fa-clock',
      btnClass: 'ld-btn-tx ld-btn-tx--pending cursor-default',
      specLabel: 'در انتظار تأیید ادمین',
    },
    release: {
      label: 'رفع معامله',
      icon: 'fa-check-circle',
      btnClass: 'ld-btn-tx ld-btn-tx--release',
      specLabel: 'در حال معامله',
    },
  };

  function statusFromMode(mode) {
    return mode === 'release' ? 'in_transaction' : 'active';
  }

  var visitCalState = {
    viewDate: null,
    selectedIso: '',
    minDate: null,
    maxDate: null,
    controlsBound: false,
  };

  var faPersianYM = null;
  var faPersianDay = null;
  var faPersianYMParts = null;
  var faPersianFull = null;

  function initJalaliFormatters() {
    if (faPersianYM) return;
    faPersianYM = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { year: 'numeric', month: 'long' });
    faPersianDay = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { day: 'numeric' });
    faPersianYMParts = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { year: 'numeric', month: 'numeric' });
    faPersianFull = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  function toLatinDigits(s) {
    return String(s).replace(/[\u06F0-\u06F9\u0660-\u0669]/g, function (d) {
      var code = d.charCodeAt(0);
      if (code >= 0x06F0) return String(code - 0x06F0);
      return String(code - 0x0660);
    });
  }

  function toLocalISODate(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function parseLocalISODate(iso) {
    if (!iso) return null;
    var p = String(iso).split('-');
    if (p.length < 3) return null;
    var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    return isNaN(d.getTime()) ? null : d;
  }

  function getPersianParts(date) {
    initJalaliFormatters();
    var y = 0;
    var m = 0;
    faPersianYMParts.formatToParts(date).forEach(function (part) {
      if (part.type === 'year') y = Number(toLatinDigits(part.value));
      if (part.type === 'month') m = Number(toLatinDigits(part.value));
    });
    return { y: y, m: m, d: Number(toLatinDigits(faPersianDay.format(date))) };
  }

  function getPersianMonthDates(baseDate) {
    var base = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate());
    var py = getPersianParts(base).y;
    var pm = getPersianParts(base).m;
    var first = new Date(base);
    for (var i = 0; i < 40; i++) {
      var parts = getPersianParts(first);
      if (parts.y === py && parts.m === pm && parts.d === 1) break;
      first.setDate(first.getDate() - 1);
    }
    var dates = [];
    var cursor = new Date(first);
    for (var j = 0; j < 40; j++) {
      var cp = getPersianParts(cursor);
      if (cp.y !== py || cp.m !== pm) break;
      dates.push(new Date(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    return dates;
  }

  function formatIsoToJalali(iso) {
    var d = parseLocalISODate(iso);
    if (!d) return iso || '';
    initJalaliFormatters();
    return faPersianFull.format(d);
  }

  function formatIsoToJalaliShort(iso) {
    var d = parseLocalISODate(iso);
    if (!d) return iso || '';
    try {
      return d.toLocaleDateString('fa-IR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        timeZone: 'Asia/Tehran',
      });
    } catch (e) {
      return formatIsoToJalali(iso);
    }
  }

  function initVisitCalBounds() {
    var cfg = readConfig();
    var minIso = (cfg && cfg.visitDateMin) || '';
    var today = parseLocalISODate(minIso);
    if (!today) {
      today = new Date();
      today = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    }
    visitCalState.minDate = today;
    visitCalState.maxDate = new Date(today);
    visitCalState.maxDate.setDate(visitCalState.maxDate.getDate() + 90);
    visitCalState.viewDate = new Date(today);
  }

  function isVisitWeekdayAllowed(d) {
    var cfg = readConfig();
    var allowed = (cfg && cfg.visitAllowedWeekdays) || null;
    if (!allowed || !allowed.length) return true;
    return allowed.indexOf(d.getDay()) >= 0;
  }

  function isDateInVisitRange(d) {
    var iso = toLocalISODate(d);
    return iso >= toLocalISODate(visitCalState.minDate)
      && iso <= toLocalISODate(visitCalState.maxDate)
      && isVisitWeekdayAllowed(d);
  }

  function syncVisitSelectedLabel(iso, jalaliText) {
    var pill = document.getElementById('landVisitCalSelected');
    var textEl = pill && pill.querySelector('.ld-cal-selected-text');
    var label = jalaliText || (iso ? formatIsoToJalali(iso) : '') || 'تاریخ انتخاب نشده';
    if (textEl) textEl.textContent = label;
    if (pill) {
      pill.classList.toggle('is-set', !!iso);
    }
  }

  function syncDealModalVisitHint() {
    var btn = document.getElementById('landTxToggleBtn');
    var hintEl = document.getElementById('landDealVisitHint');
    var wrap = document.getElementById('landDealVisitHintWrap');
    if (!hintEl) return;
    var hint = document.getElementById('landVisitDateHint');
    var jalali = '';
    if (hint && !hint.classList.contains('hidden')) {
      var raw = (hint.textContent || '').replace(/^بازدید:\s*/, '').trim();
      if (raw) jalali = raw;
    }
    if (!jalali && btn) {
      var vd = btn.getAttribute('data-visit-date') || '';
      if (vd) jalali = formatIsoToJalaliShort(vd) || vd;
    }
    if (jalali) {
      hintEl.textContent = jalali;
      if (wrap) wrap.classList.remove('hidden');
    }
  }

  function renderVisitCalendar() {
    var grid = document.getElementById('landVisitCalGrid');
    var monthLabel = document.getElementById('landVisitCalMonth');
    if (!grid || !visitCalState.viewDate) return;
    initJalaliFormatters();

    var monthDates = getPersianMonthDates(visitCalState.viewDate);
    if (!monthDates.length) return;

    if (monthLabel) monthLabel.textContent = faPersianYM.format(monthDates[0]);
    grid.innerHTML = '';

    var firstDay = monthDates[0].getDay();
    var startOffset = firstDay === 6 ? 0 : firstDay + 1;
    for (var i = 0; i < startOffset; i++) {
      var ph = document.createElement('div');
      ph.className = 'aspect-square';
      grid.appendChild(ph);
    }

    var todayIso = toLocalISODate(visitCalState.minDate);
    monthDates.forEach(function (gd) {
      var iso = toLocalISODate(gd);
      var enabled = isDateInVisitRange(gd);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = faPersianDay.format(gd);
      btn.className = 'ld-cal-day' + (
        !enabled
          ? ' ld-cal-day--disabled'
          : visitCalState.selectedIso === iso
            ? ' ld-cal-day--selected'
            : iso === todayIso
              ? ' ld-cal-day--today'
              : ' ld-cal-day--default'
      );
      btn.disabled = !enabled;
      if (enabled) {
        (function (dayIso) {
          btn.addEventListener('click', function () {
            visitCalState.selectedIso = dayIso;
            var hidden = document.getElementById('landVisitDateInput');
            if (hidden) hidden.value = dayIso;
            syncVisitSelectedLabel(dayIso);
            renderVisitCalendar();
            syncVisitSubmitEnabled();
          });
        })(iso);
      }
      grid.appendChild(btn);
    });
  }

  function resetVisitCalendarSelection() {
    visitCalState.selectedIso = '';
    var hidden = document.getElementById('landVisitDateInput');
    if (hidden) hidden.value = '';
    syncVisitSelectedLabel('');
    syncVisitSubmitEnabled();
  }

  function normalizeIranMobileInput(raw) {
    var s = String(raw || '').trim().replace(/[\s\-]/g, '');
    s = s.replace(/[۰-۹]/g, function (d) {
      return String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d));
    }).replace(/[٠-٩]/g, function (d) {
      return String('٠١٢٣٤٥٦٧٨٩'.indexOf(d));
    });
    if (s.indexOf('+98') === 0) s = '0' + s.slice(3);
    if (s.indexOf('0098') === 0) s = '0' + s.slice(4);
    if (s.indexOf('98') === 0 && s.length === 12) s = '0' + s.slice(2);
    return s;
  }

  function isValidIranMobileInput(raw) {
    var s = normalizeIranMobileInput(raw);
    return /^09\d{9}$/.test(s);
  }

  function readVisitCustomerFields() {
    var firstEl = document.getElementById('landVisitCustomerFirst');
    var lastEl = document.getElementById('landVisitCustomerLast');
    var phoneEl = document.getElementById('landVisitCustomerPhone');
    return {
      first: firstEl ? (firstEl.value || '').trim() : '',
      last: lastEl ? (lastEl.value || '').trim() : '',
      phone: phoneEl ? normalizeIranMobileInput(phoneEl.value || '') : '',
    };
  }

  function validateVisitCustomerFields() {
    var fields = readVisitCustomerFields();
    if (!fields.first) return 'نام مشتری را وارد کنید.';
    if (!fields.last) return 'نام خانوادگی مشتری را وارد کنید.';
    if (!fields.phone) return 'شماره تماس مشتری را وارد کنید.';
    if (!isValidIranMobileInput(fields.phone)) return 'شماره تماس مشتری معتبر نیست.';
    return '';
  }

  function resetVisitCustomerFields() {
    ['landVisitCustomerFirst', 'landVisitCustomerLast', 'landVisitCustomerPhone'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
  }

  function syncVisitSubmitEnabled() {
    var submitBtn = document.getElementById('landVisitSubmitBtn');
    var dateInput = document.getElementById('landVisitDateInput');
    if (!submitBtn) return;
    var hasDate = !!(dateInput && (dateInput.value || '').trim());
    var customerOk = !validateVisitCustomerFields();
    submitBtn.disabled = !hasDate || !customerOk || submitBtn.dataset.busy === '1';
  }

  function bindVisitCustomerFieldInputs() {
    ['landVisitCustomerFirst', 'landVisitCustomerLast', 'landVisitCustomerPhone'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el || el.dataset.visitCustomerBound === '1') return;
      el.dataset.visitCustomerBound = '1';
      function onChange() {
        syncVisitSubmitEnabled();
      }
      el.addEventListener('input', onChange);
      el.addEventListener('change', onChange);
      addCleanup(function () {
        el.removeEventListener('input', onChange);
        el.removeEventListener('change', onChange);
        delete el.dataset.visitCustomerBound;
      });
    });
  }

  function clampVisitCalViewDate() {
    if (!visitCalState.viewDate || !visitCalState.minDate || !visitCalState.maxDate) return;
    var t = visitCalState.viewDate.getTime();
    if (t < visitCalState.minDate.getTime()) {
      visitCalState.viewDate = new Date(visitCalState.minDate);
    } else if (t > visitCalState.maxDate.getTime()) {
      visitCalState.viewDate = new Date(visitCalState.maxDate);
    }
  }

  function initVisitCalendarControls() {
    if (visitCalState.controlsBound) return;
    visitCalState.controlsBound = true;
    initVisitCalBounds();

    var prev = document.getElementById('landVisitCalPrev');
    var next = document.getElementById('landVisitCalNext');
    if (prev) {
      prev.addEventListener('click', function () {
        visitCalState.viewDate.setDate(visitCalState.viewDate.getDate() - 28);
        clampVisitCalViewDate();
        renderVisitCalendar();
      });
    }
    if (next) {
      next.addEventListener('click', function () {
        visitCalState.viewDate.setDate(visitCalState.viewDate.getDate() + 28);
        clampVisitCalViewDate();
        renderVisitCalendar();
      });
    }
  }

  function updateVisitDateHint(isoDate, jalaliLabel) {
    var hint = document.getElementById('landVisitDateHint');
    if (!hint) return;
    var display = jalaliLabel || formatIsoToJalaliShort(isoDate) || isoDate;
    if (isoDate || jalaliLabel) {
      var span = hint.querySelector('span');
      var label = 'بازدید: ' + display;
      if (span) {
        span.textContent = label;
      } else {
        hint.innerHTML = '<i class="fas fa-calendar-check" aria-hidden="true"></i><span>' + label + '</span>';
      }
      hint.classList.remove('hidden');
    } else {
      var clearSpan = hint.querySelector('span');
      if (clearSpan) clearSpan.textContent = '';
      else hint.textContent = '';
      hint.classList.add('hidden');
    }
    syncFooterSpacer();
  }

  var footerSpacerResizeBound = false;

  function syncFooterSpacer() {
    if (window.matchMedia('(min-width: 1024px)').matches) return;
    var spacer = document.querySelector('.ld-footer-spacer');
    var footer = document.querySelector('.ld-actions');
    if (!spacer || !footer) return;
    var h = Math.ceil(footer.getBoundingClientRect().height) + 16;
    var px = h + 'px';
    spacer.style.height = px;
    spacer.style.minHeight = px;
    document.documentElement.style.setProperty('--ld-footer-h', px);
  }

  function bindFooterSpacerResize() {
    if (footerSpacerResizeBound) return;
    footerSpacerResizeBound = true;
    var t;
    window.addEventListener('resize', function () {
      clearTimeout(t);
      t = setTimeout(syncFooterSpacer, 100);
    });
  }

  function escapeToastText(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function parseTxToastMessage(message) {
    var raw = String(message || '').trim();
    if (!raw) return { title: '', detail: '', tone: 'success' };

    var pipe = raw.split('|');
    if (pipe.length > 1) {
      return {
        title: pipe[0].replace(/\.\s*$/, '').trim(),
        detail: pipe.slice(1).join('|').trim(),
        tone: 'warning',
      };
    }

    var paren = raw.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
    if (paren) {
      return {
        title: paren[1].replace(/\.\s*$/, '').trim(),
        detail: paren[2].trim(),
        tone: 'warning',
      };
    }

    var dash = raw.split(/\s*[—–]\s+/);
    if (dash.length > 1 && dash[0].length <= 72) {
      return {
        title: dash[0].replace(/\.\s*$/, '').trim(),
        detail: dash.slice(1).join(' — ').trim(),
        tone: 'success',
      };
    }

    return { title: raw.replace(/\.\s*$/, '').trim(), detail: '', tone: 'success' };
  }

  function txToastIconClass(parsed, isError) {
    if (isError) return 'fa-circle-exclamation';
    if (parsed.tone === 'warning') return 'fa-info-circle';
    if (parsed.title.indexOf('معامله') !== -1) return 'fa-handshake';
    if (parsed.title.indexOf('بازدید') !== -1) return 'fa-calendar-check';
    if (parsed.title.indexOf('پورسانت') !== -1) return 'fa-coins';
    if (parsed.title.indexOf('کپی') !== -1) return 'fa-copy';
    if (parsed.title.indexOf('دانلود') !== -1) return 'fa-download';
    return 'fa-check-circle';
  }

  function renderTxToast(toast, parsed, isError) {
    var icon = txToastIconClass(parsed, isError);
    var detailHtml = parsed.detail
      ? '<span class="ld-tx-toast__detail">' + escapeToastText(parsed.detail) + '</span>'
      : '';
    toast.innerHTML =
      '<span class="ld-tx-toast__icon" aria-hidden="true"><i class="fas ' + icon + '"></i></span>' +
      '<span class="ld-tx-toast__body">' +
        '<span class="ld-tx-toast__title">' + escapeToastText(parsed.title) + '</span>' +
        detailHtml +
      '</span>';
  }

  function showTxToast(message, isError) {
    var toast = document.getElementById('landTxToast');
    if (!toast || !message) return;
    var parsed = parseTxToastMessage(message);
    if (!parsed.title && parsed.detail) {
      parsed.title = parsed.detail;
      parsed.detail = '';
    }
    renderTxToast(toast, parsed, isError);
    toast.classList.remove('hidden', 'is-success', 'is-error', 'is-warning', 'is-visible');
    if (isError) {
      toast.classList.add('is-error');
    } else if (parsed.tone === 'warning') {
      toast.classList.add('is-warning');
    } else {
      toast.classList.add('is-success');
    }
    requestAnimationFrame(function () {
      toast.classList.add('is-visible');
    });
    syncFooterSpacer();
    clearTimeout(showTxToast._t);
    var duration = parsed.detail ? 4600 : 3000;
    showTxToast._t = setTimeout(function () {
      toast.classList.remove('is-visible');
      clearTimeout(showTxToast._hideT);
      showTxToast._hideT = setTimeout(function () {
        toast.classList.add('hidden');
        toast.classList.remove('is-success', 'is-error', 'is-warning');
        toast.textContent = '';
        syncFooterSpacer();
      }, 260);
    }, duration);
  }

  function getLandCsrf() {
    if (typeof window.vinorReadCsrfToken === 'function') {
      var fromCookie = window.vinorReadCsrfToken();
      if (fromCookie) return fromCookie;
    }
    var btn = document.getElementById('landTxToggleBtn');
    var cfg = readConfig();
    return (btn && btn.getAttribute('data-csrf')) ||
      (cfg && cfg.csrfToken) ||
      (window.VINOR_NOTIFY_CFG && window.VINOR_NOTIFY_CFG.csrfToken) ||
      '';
  }

  function syncTxButtonDisabled(btn, mode) {
    if (!btn || btn.tagName !== 'BUTTON') return;
    var pending = mode === 'visit_pending' || mode === 'visit_done_pending' || mode === 'visit_commission_pending' || mode === 'deal_pending';
    btn.disabled = false;
    btn.setAttribute('aria-disabled', pending ? 'true' : 'false');
  }

  var visitStatusPollTimer = null;

  function stopVisitStatusPoll() {
    if (visitStatusPollTimer) {
      clearInterval(visitStatusPollTimer);
      visitStatusPollTimer = null;
    }
  }

  function fetchLandTxStatus() {
    var cfg = readConfig();
    var btn = document.getElementById('landTxToggleBtn');
    var url = (btn && btn.getAttribute('data-tx-status-url')) || (cfg && cfg.txStatusUrl) || '';
    if (!url) return Promise.resolve(null);
    return fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    }).then(function (res) {
      return res.json().then(function (data) {
        return res.ok ? data : null;
      });
    }).catch(function () {
      return null;
    });
  }

  function initVisitStatusPoll(initialMode) {
    stopVisitStatusPoll();
    if (initialMode !== 'visit_pending' && initialMode !== 'visit_done_pending' && initialMode !== 'visit_commission_pending' && initialMode !== 'deal_pending') return;

    var root = document.querySelector(ROOT_SEL);
    var prevMode = initialMode;

    function pollOnce() {
      fetchLandTxStatus().then(function (data) {
        if (!data || !data.success) return;
        var mode = data.tx_mode || 'visit';
        if (mode === prevMode) return;
        prevMode = mode;
        applyTxMode(mode, data.visit_date || '', data.visit_date_jalali || '', data.can_revisit);
        if (mode === 'visit_done') {
          showTxToast('بازدید تأیید شد — پس از انجام بازدید، آن را ثبت کنید.', false);
          stopVisitStatusPoll();
        } else if (mode === 'visit_done_pending') {
          showTxToast('بازدید انجام شد ثبت شده و منتظر تأیید ادمین است.', false);
        } else if (mode === 'deal') {
          showTxToast('پورسانت بازدید تأیید شد — اکنون می‌توانید درخواست معامله ثبت کنید.', false);
          stopVisitStatusPoll();
        } else if (mode === 'deal_pending') {
          showTxToast('درخواست معامله ثبت شد و منتظر تأیید ادمین است.', false);
          stopVisitStatusPoll();
        } else if (mode === 'release') {
          showTxToast('درخواست معامله تأیید شد — فایل در حال معامله است.', false);
          stopVisitStatusPoll();
        } else if (mode === 'visit_commission_pending') {
          showTxToast('بازدید توسط ادمین تأیید شد و پورسانت بازدید منتظر تأیید است.', false);
        } else if (mode === 'visit') {
          showTxToast('درخواست بازدید رد شد. می‌توانید تاریخ جدید انتخاب کنید.', false);
          stopVisitStatusPoll();
          scheduleVisitModalRecovery();
        } else if (mode !== 'visit_pending') {
          stopVisitStatusPoll();
        }
        if (root) root.dataset.txMode = mode;
      });
    }

    pollOnce();
    visitStatusPollTimer = setInterval(pollOnce, 8000);
  }

  function isVisitApprovalPending(txMode) {
    return txMode === 'visit_pending' || txMode === 'visit_done_pending' || txMode === 'visit_commission_pending';
  }

  function isLandInTransaction(txMode, txStatus) {
    return txMode === 'release' || txStatus === 'in_transaction';
  }

  function syncRevisitButton(canRevisit, txMode) {
    var revisitBtn = document.getElementById('landRevisitBtn');
    if (!revisitBtn) return;
    var root = document.querySelector(ROOT_SEL);
    var txStatus = (root && root.dataset.txStatus) || '';
    var inTransaction = isLandInTransaction(txMode, txStatus);
    var showActive = !!canRevisit && !inTransaction && txMode === 'deal';
    var showPendingBlocked = !!canRevisit && isVisitApprovalPending(txMode);
    var showBlocked = (inTransaction && txMode === 'release') || showPendingBlocked;
    var show = showActive || showBlocked;
    var item = document.getElementById('landRevisitItem') || revisitBtn.closest('.ld-fab-menu__item');
    var label = item && item.querySelector('.ld-fab-menu__label');
    var icon = revisitBtn.querySelector('i');
    if (item) {
      item.classList.toggle('hidden', !show);
      item.classList.toggle('ld-fab-menu__item--revisit-blocked', showBlocked);
    }
    revisitBtn.classList.remove('ld-fab-menu__action--teal', 'ld-fab-menu__action--muted');
    if (showBlocked) {
      revisitBtn.classList.add('ld-fab-menu__action--muted');
      revisitBtn.dataset.revisitBlocked = '1';
      if (showPendingBlocked) {
        revisitBtn.dataset.revisitPendingBlocked = '1';
      } else {
        delete revisitBtn.dataset.revisitPendingBlocked;
      }
      revisitBtn.setAttribute('aria-disabled', 'true');
      if (icon) icon.className = 'fas fa-lock';
      if (label) label.textContent = 'بازدید مجدد';
    } else {
      delete revisitBtn.dataset.revisitBlocked;
      delete revisitBtn.dataset.revisitPendingBlocked;
      if (showActive) {
        revisitBtn.classList.add('ld-fab-menu__action--teal');
        revisitBtn.setAttribute('aria-disabled', 'false');
        if (icon) icon.className = 'fas fa-calendar-plus';
      } else {
        revisitBtn.setAttribute('aria-disabled', 'true');
      }
      if (label) label.textContent = 'بازدید مجدد';
    }
    revisitBtn.disabled = false;
    syncFabDirectMode();
  }

  function countFabInteractiveItems() {
    var items = document.querySelectorAll('.ld-fab-menu__items .ld-fab-menu__item:not(.hidden):not(.ld-fab-menu__item--status)');
    var count = 0;
    items.forEach(function (item) {
      var btn = item.querySelector('button.ld-fab-menu__action');
      if (btn && !btn.classList.contains('hidden')) count += 1;
    });
    return count;
  }

  function fabIconForMode(mode) {
    var icons = {
      visit: 'fa-calendar-check',
      deal: 'fa-handshake',
      release: 'fa-check-circle',
      revisit: 'fa-calendar-plus',
      visit_done: 'fa-check-double',
      visit_pending: 'fa-clock',
      visit_done_pending: 'fa-clock',
      visit_commission_pending: 'fa-clock',
      deal_pending: 'fa-clock',
    };
    return icons[mode] || 'fa-handshake';
  }

  function syncFabTriggerIcon() {
    var iconEl = document.getElementById('landFabTriggerIcon');
    if (!iconEl) return;
    var count = countFabInteractiveItems();
    var icon = 'fa-handshake';
    var callBtn = document.querySelector('.ld-fab-menu__items [data-land-open-contact]');
    var txBtn = document.getElementById('landTxToggleBtn');
    var callVisible = callBtn && callBtn.closest('.ld-fab-menu__item:not(.hidden)');
    var txVisible = txBtn && txBtn.closest('.ld-fab-menu__item:not(.hidden)');
    if (count <= 1) {
      if (callVisible) icon = 'fa-phone';
      else if (txVisible) icon = fabIconForMode(txBtn.getAttribute('data-land-tx-mode') || 'visit');
      else if (document.querySelector('.ld-fab-menu__item--status .fa-lock')) icon = 'fa-lock';
      else if (document.querySelector('.ld-fab-menu__item--status .fa-check-double')) icon = 'fa-check-double';
    } else if (callVisible) {
      icon = 'fa-phone';
    }
    iconEl.className = 'fas ' + icon + ' ld-fab-trigger__icon ld-fab-trigger__icon--idle';
  }

  function syncFabDirectMode() {
    var dock = document.querySelector('.ld-fab-dock');
    var trigger = document.getElementById('landFabTrigger');
    if (!dock || !trigger) return;
    var count = countFabInteractiveItems();
    var direct = count <= 1;
    var callBtn = document.querySelector('.ld-fab-menu__items [data-land-open-contact]');
    var txBtn = document.getElementById('landTxToggleBtn');
    var callVisible = callBtn && callBtn.closest('.ld-fab-menu__item:not(.hidden)');
    dock.dataset.fabDirect = direct ? '1' : '0';
    if (direct && count === 1) {
      if (callVisible) {
        trigger.setAttribute('aria-label', 'تماس');
      } else if (txBtn && txBtn.closest('.ld-fab-menu__item:not(.hidden)')) {
        var label = txBtn.closest('.ld-fab-menu__item').querySelector('.ld-fab-menu__label');
        trigger.setAttribute('aria-label', label ? label.textContent.trim() : 'عملیات فایل');
      } else {
        trigger.setAttribute('aria-label', 'عملیات فایل');
      }
    } else {
      trigger.setAttribute('aria-label', callVisible ? 'تماس و عملیات فایل' : 'عملیات فایل');
    }
    syncFabTriggerIcon();
  }

  function closeFabMenu() {
    var dock = document.querySelector('.ld-fab-dock');
    if (!dock || !dock.classList.contains('is-open')) return;
    dock.classList.remove('is-open');
    var trigger = document.getElementById('landFabTrigger');
    var menu = document.getElementById('landFabMenu');
    var backdrop = dock.querySelector('[data-land-fab-backdrop]');
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
    if (menu) menu.setAttribute('aria-hidden', 'true');
    if (backdrop) backdrop.setAttribute('aria-hidden', 'true');
    syncFooterSpacer();
  }

  function openFabMenu() {
    var dock = document.querySelector('.ld-fab-dock');
    if (!dock) return;
    dock.classList.add('is-open');
    var trigger = document.getElementById('landFabTrigger');
    var menu = document.getElementById('landFabMenu');
    var backdrop = dock.querySelector('[data-land-fab-backdrop]');
    if (trigger) trigger.setAttribute('aria-expanded', 'true');
    if (menu) menu.setAttribute('aria-hidden', 'false');
    if (backdrop) backdrop.setAttribute('aria-hidden', 'false');
    syncFooterSpacer();
  }

  function initFabMenu() {
    var dock = document.querySelector('.ld-fab-dock');
    var trigger = document.getElementById('landFabTrigger');
    if (!dock || !trigger || trigger.dataset.ldFabBound === '1') return;
    trigger.dataset.ldFabBound = '1';
    syncFabDirectMode();

    function onTriggerClick(ev) {
      ev.preventDefault();
      ev.stopPropagation();
      if (dock.dataset.fabDirect === '1') {
        var item = dock.querySelector('.ld-fab-menu__items .ld-fab-menu__item:not(.hidden):not(.ld-fab-menu__item--status) button.ld-fab-menu__action');
        if (item) item.click();
        else openFabMenu();
        return;
      }
      if (dock.classList.contains('is-open')) closeFabMenu();
      else openFabMenu();
    }

    function onBackdropClick(ev) {
      ev.preventDefault();
      closeFabMenu();
    }

    function onFabActionClick() {
      requestAnimationFrame(closeFabMenu);
    }

    function onFabEscape(ev) {
      if (ev.key !== 'Escape' || !dock.classList.contains('is-open')) return;
      ev.preventDefault();
      closeFabMenu();
    }

    trigger.addEventListener('click', onTriggerClick);
    var backdrop = dock.querySelector('[data-land-fab-backdrop]');
    if (backdrop) backdrop.addEventListener('click', onBackdropClick);
    dock.querySelectorAll(
      '[data-land-open-contact], [data-land-tx-toggle], [data-land-revisit-trigger]'
    ).forEach(function (btn) {
      btn.addEventListener('click', onFabActionClick);
    });
    document.addEventListener('keydown', onFabEscape);

    addCleanup(function () {
      trigger.removeEventListener('click', onTriggerClick);
      if (backdrop) backdrop.removeEventListener('click', onBackdropClick);
      dock.querySelectorAll(
        '[data-land-open-contact], [data-land-tx-toggle], [data-land-revisit-trigger]'
      ).forEach(function (btn) {
        btn.removeEventListener('click', onFabActionClick);
      });
      document.removeEventListener('keydown', onFabEscape);
      closeFabMenu();
      delete trigger.dataset.ldFabBound;
    });
  }

  function applyTxMode(mode, visitDate, visitDateJalali, canRevisit) {
    var root = document.querySelector(ROOT_SEL);
    var btn = document.getElementById('landTxToggleBtn');
    var cfg = readConfig();
    if (canRevisit === undefined || canRevisit === null) {
      if (root && root.dataset.canRevisit !== undefined) {
        canRevisit = root.dataset.canRevisit === '1' || root.dataset.canRevisit === 'true';
      } else if (cfg && cfg.canRevisit !== undefined) {
        canRevisit = cfg.canRevisit;
      }
    }
    if (root && canRevisit !== undefined && canRevisit !== null) {
      root.dataset.canRevisit = canRevisit ? '1' : '0';
    }
    if (mode === 'deal_pending' || mode === 'blocked') {
      canRevisit = false;
      if (root) root.dataset.canRevisit = '0';
    }
    var cfg = TX_UI[mode] || TX_UI.visit;
    var status = statusFromMode(mode);
    if (root) {
      root.dataset.txMode = mode;
      root.dataset.txStatus = status;
    }
    if (btn) {
      btn.setAttribute('data-land-tx-mode', mode);
      btn.setAttribute('data-land-tx-status', status);
      var icon = btn.querySelector('.land-tx-icon');
      var item = btn.closest('.ld-fab-menu__item');
      var label = (item && item.querySelector('.land-tx-label')) || document.querySelector('.land-tx-label');
      if (icon) icon.className = 'fas ' + cfg.icon + ' land-tx-icon';
      if (label) label.textContent = cfg.label;
      btn.classList.remove(
        'ld-btn-tx', 'ld-btn-tx--release', 'ld-btn-tx--pending',
        'ld-fab-menu__action--teal', 'ld-fab-menu__action--muted', 'ld-fab-menu__action--pending', 'ld-fab-menu__action--deal'
      );
      if (mode === 'release') {
        btn.classList.add('ld-btn-tx--release', 'ld-fab-menu__action--muted');
      } else if (mode === 'visit_pending' || mode === 'visit_done_pending' || mode === 'visit_commission_pending' || mode === 'deal_pending') {
        btn.classList.add('ld-btn-tx--pending', 'ld-fab-menu__action--pending');
      } else if (mode === 'deal') {
        btn.classList.add('ld-btn-tx', 'ld-fab-menu__action--deal');
      } else {
        btn.classList.add('ld-btn-tx', 'ld-fab-menu__action--teal');
      }
      if (visitDate) {
        btn.setAttribute('data-visit-date', visitDate);
      }
      syncTxButtonDisabled(btn, mode);
    }
    var badge = document.getElementById('landTxStatusBadge');
    if (badge) badge.classList.toggle('hidden', mode !== 'release');
    var expertBadge = document.getElementById('landExpertVerifiedBadge');
    if (expertBadge) expertBadge.classList.toggle('hidden', mode === 'release');
    var spec = document.querySelector('[data-land-tx-spec-value]');
    if (spec) spec.textContent = cfg.specLabel;
    if (mode === 'deal' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'visit_done' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'visit_done_pending' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'visit_pending' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'visit_commission_pending' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'deal_pending' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'release' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'visit' || mode === 'revisit') {
      updateVisitDateHint('');
    }
    if (mode !== 'visit_pending' && mode !== 'visit_done_pending' && mode !== 'visit_commission_pending' && mode !== 'deal_pending') {
      stopVisitStatusPoll();
    }
    if (mode === 'visit' || mode === 'revisit') {
      scheduleVisitModalRecovery();
    }
    if (mode === 'deal') {
      syncDealModalVisitHint();
    }
    syncRevisitButton(canRevisit, mode);
    syncFabDirectMode();
    requestAnimationFrame(function () {
      syncFooterSpacer();
    });
  }

  function focusDetailActionsAfterVisit() {
    requestAnimationFrame(function () {
      syncFooterSpacer();
      var footer = document.querySelector('.ld-actions');
      if (footer && typeof footer.scrollIntoView === 'function') {
        try {
          footer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } catch (e) {
          footer.scrollIntoView(false);
        }
      }
    });
  }

  function applyTxStatus(status) {
    var mode = status === 'in_transaction' ? 'release' : 'visit';
    applyTxMode(mode);
  }

  var visitModalRecoverPromise = null;

  function hoistLandModalsSafe() {
    try {
      if (typeof window.hoistVinorExpressBodyModals === 'function') {
        window.hoistVinorExpressBodyModals();
      }
    } catch (e) { /* ignore */ }
  }

  function shouldOfferVisitModal() {
    var btn = document.getElementById('landTxToggleBtn');
    if (!getVisitRequestUrl()) return false;
    if (readCanRevisitFlag()) return true;
    var cfg = readConfig();
    var mode = (btn && btn.getAttribute('data-land-tx-mode')) || (cfg && cfg.txMode) || '';
    return canOpenVisitModal(mode, readCanRevisitFlag());
  }

  function ensureVisitModalEl() {
    var modal = document.getElementById('landVisitModal');
    if (modal) return modal;
    var detailPage = document.getElementById('landDetailPage');
    var root = activeRoot || detailPage || document.querySelector(ROOT_SEL);
    if (root && root.querySelector('#landVisitModal')) {
      hoistLandModalsSafe();
      return document.getElementById('landVisitModal');
    }
    return null;
  }

  function injectVisitModalFromNode(modalNode) {
    if (!modalNode) return null;
    try {
      document.querySelectorAll('#landVisitModal').forEach(function (el) {
        try { el.remove(); } catch (e) { /* ignore */ }
      });
    } catch (e) { /* ignore */ }
    var imported = document.importNode(modalNode, true);
    var detailPage = document.getElementById('landDetailPage');
    if (detailPage) {
      detailPage.appendChild(imported);
    } else {
      document.body.appendChild(imported);
    }
    hoistLandModalsSafe();
    return document.getElementById('landVisitModal');
  }

  function fetchVisitModalFromServer() {
    var path = window.location.pathname + window.location.search;
    return fetch(path, {
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        Accept: 'text/html',
      },
    })
      .then(function (res) {
        if (!res.ok) throw new Error('fetch');
        return res.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var modal = doc.getElementById('landVisitModal');
        if (!modal) {
          var page = doc.getElementById('landDetailPage');
          if (page) modal = page.querySelector('#landVisitModal');
        }
        return injectVisitModalFromNode(modal);
      })
      .catch(function () {
        return null;
      });
  }

  function recoverVisitModal() {
    var modal = ensureVisitModalEl();
    if (modal) return Promise.resolve(modal);

    if (visitModalRecoverPromise) return visitModalRecoverPromise;

    visitModalRecoverPromise = fetchVisitModalFromServer()
      .then(function (fetched) {
        if (!document.querySelector(ROOT_SEL)) return null;
        if (fetched) return fetched;
        hoistLandModalsSafe();
        return ensureVisitModalEl();
      })
      .finally(function () {
        visitModalRecoverPromise = null;
      });

    return visitModalRecoverPromise;
  }

  function rebindVisitModalHandlers() {
    visitCalState.controlsBound = false;
    var submitBtn = document.getElementById('landVisitSubmitBtn');
    if (submitBtn) delete submitBtn.dataset.visitSubmitBound;
    initVisitCalendarControls();
    bindVisitSubmitHandler();
  }

  function scheduleVisitModalRecovery() {
    if (!shouldOfferVisitModal() && !readCanRevisitFlag()) return;
    if (document.getElementById('landVisitModal')) return;
    recoverVisitModal().then(function (modal) {
      if (modal) rebindVisitModalHandlers();
    });
  }

  function getVisitRequestUrl() {
    var txBtn = document.getElementById('landTxToggleBtn');
    var revisitBtn = document.getElementById('landRevisitBtn');
    return (txBtn && txBtn.getAttribute('data-visit-request-url')) ||
      (revisitBtn && revisitBtn.getAttribute('data-visit-request-url')) ||
      '';
  }

  function canOpenVisitModal(mode, canRevisit) {
    if (!mode) return true;
    if (mode === 'visit' || mode === 'revisit') return true;
    if (canRevisit && mode === 'deal') return true;
    return false;
  }

  function readCanRevisitFlag() {
    var root = document.querySelector(ROOT_SEL);
    if (root && root.dataset.canRevisit !== undefined) {
      return root.dataset.canRevisit === '1' || root.dataset.canRevisit === 'true';
    }
    var cfg = readConfig();
    return !!(cfg && cfg.canRevisit);
  }

  function openVisitModalNow() {
    openLandModal('landVisitModal');
    initVisitCalendarControls();
    initVisitCalBounds();
    resetVisitCalendarSelection();
    resetVisitCustomerFields();
    bindVisitCustomerFieldInputs();
    renderVisitCalendar();
    syncVisitSubmitEnabled();
  }

  function openVisitModal(forceOpen) {
    var btn = document.getElementById('landTxToggleBtn');
    var root = document.querySelector(ROOT_SEL);
    var mode = (btn && btn.getAttribute('data-land-tx-mode')) || (root && root.dataset.txMode) || '';
    var canRevisit = readCanRevisitFlag();
    if (!forceOpen && !canOpenVisitModal(mode, canRevisit)) {
      return;
    }

    var modal = ensureVisitModalEl();
    if (modal) {
      openVisitModalNow();
      return;
    }

    var busyBtn = btn || document.getElementById('landRevisitBtn');
    if (busyBtn) {
      busyBtn.dataset.busy = '1';
      if (busyBtn.tagName === 'BUTTON') busyBtn.disabled = true;
    }

    recoverVisitModal().then(function (recovered) {
      if (busyBtn) {
        busyBtn.dataset.busy = '0';
        if (busyBtn.tagName === 'BUTTON') busyBtn.disabled = false;
      }
      if (btn) syncTxButtonDisabled(btn, btn.getAttribute('data-land-tx-mode') || mode || 'visit');
      if (recovered) {
        rebindVisitModalHandlers();
        openVisitModalNow();
        return;
      }
      showTxToast('امکان ثبت درخواست بازدید برای این ملک وجود ندارد.', true);
    });
  }

  function closeVisitModal() {
    closeLandModals();
  }

  function postLandAction(url, extraFields, onSuccess) {
    var csrf = getLandCsrf();
    var body = new FormData();
    if (csrf) body.append('csrf_token', csrf);
    if (extraFields) {
      Object.keys(extraFields).forEach(function (k) {
        body.append(k, extraFields[k]);
      });
    }
    var hdrs = typeof window.vinorCsrfFetchHeaders === 'function'
      ? window.vinorCsrfFetchHeaders({
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        })
      : {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        };
    if (csrf && !hdrs['X-CSRFToken']) hdrs['X-CSRFToken'] = csrf;
    return fetch(url, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      headers: hdrs,
    }).then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, data: data };
      });
    }).then(function (result) {
      if (!result.ok || !result.data || !result.data.success) {
        throw new Error((result.data && result.data.message) || 'خطا در انجام عملیات');
      }
      if (onSuccess) onSuccess(result.data);
      return result.data;
    });
  }

  function bindVisitSubmitHandler() {
    var submitBtn = document.getElementById('landVisitSubmitBtn');
    var dateInput = document.getElementById('landVisitDateInput');
    var txBtn = document.getElementById('landTxToggleBtn');
    if (!submitBtn) return;
    var visitUrl = getVisitRequestUrl();
    if (!visitUrl) return;
    if (submitBtn.dataset.visitSubmitBound === '1') return;
    submitBtn.dataset.visitSubmitBound = '1';

    function onSubmit() {
      if (submitBtn.disabled || submitBtn.dataset.busy === '1') return;
      var visitDate = dateInput ? (dateInput.value || '').trim() : '';
      if (!visitDate) {
        showTxToast('لطفاً تاریخ بازدید را انتخاب کنید.', true);
        return;
      }
      var customerErr = validateVisitCustomerFields();
      if (customerErr) {
        showTxToast(customerErr, true);
        return;
      }
      var customer = readVisitCustomerFields();
      var url = visitUrl;
      if (!url) return;

      var prevLabel = submitBtn.innerHTML;
      submitBtn.dataset.busy = '1';
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> در حال ارسال…';
      closeLandModals();

      var jalaliPreview = formatIsoToJalaliShort(visitDate) || formatIsoToJalali(visitDate);
      applyTxMode('visit_pending', visitDate, jalaliPreview, false);
      initVisitStatusPoll('visit_pending');
      focusDetailActionsAfterVisit();

      postLandAction(url, {
        visit_date: visitDate,
        customer_first_name: customer.first,
        customer_last_name: customer.last,
        customer_phone: customer.phone,
      }, function (data) {
        var mode = data.tx_mode || 'visit_pending';
        applyTxMode(
          mode,
          data.visit_date || visitDate,
          data.visit_date_jalali || jalaliPreview,
          data.can_revisit
        );
        if (mode === 'visit_pending') initVisitStatusPoll('visit_pending');
        var toastMsg = (data.message && String(data.message).indexOf('قبلاً') !== -1)
          ? data.message
          : VISIT_SENT_MSG;
        showTxToast(toastMsg, false);
        if (data.redirect_url) {
          if (window.vinorExpressNavigate) {
            window.vinorExpressNavigate(data.redirect_url, { forward: true });
          } else {
            window.location.href = data.redirect_url;
          }
          return;
        }
        focusDetailActionsAfterVisit();
        fetchLandTxStatus().then(function (st) {
          if (!st || !st.success) return;
          applyTxMode(
            st.tx_mode || mode,
            st.visit_date || visitDate,
            st.visit_date_jalali || jalaliPreview,
            st.can_revisit
          );
        });
      }).catch(function (err) {
        stopVisitStatusPoll();
        applyTxMode('visit', '', '');
        showTxToast(err.message || 'خطا در ثبت بازدید', true);
      }).finally(function () {
        submitBtn.dataset.busy = '0';
        submitBtn.innerHTML = prevLabel;
        syncVisitSubmitEnabled();
      });
    }

    submitBtn.addEventListener('click', onSubmit);
    addCleanup(function () {
      submitBtn.removeEventListener('click', onSubmit);
      delete submitBtn.dataset.visitSubmitBound;
    });
  }

  function initVisitRequest() {
    bindVisitSubmitHandler();
  }

  function initRevisitTriggers() {
    document.querySelectorAll('[data-land-revisit-trigger]').forEach(function (revisitBtn) {
      if (revisitBtn.dataset.ldRevisitBound === '1') return;
      revisitBtn.dataset.ldRevisitBound = '1';
      function onRevisitClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (revisitBtn.dataset.busy === '1') return;
        if (revisitBtn.dataset.revisitBlocked === '1') {
          closeFabMenu();
          if (revisitBtn.dataset.revisitPendingBlocked === '1') {
            showTxToast(
              'بازدید در انتظار تأیید است|تا زمان تأیید ادمین، امکان ثبت بازدید مجدد وجود ندارد.',
              false
            );
          } else {
            showTxToast(
              'ابتدا رفع معامله را انجام دهید|برای ثبت بازدید مجدد، از گزینه «رفع معامله» استفاده کنید.',
              false
            );
          }
          return;
        }
        if (revisitBtn.disabled) return;
        var root = document.querySelector(ROOT_SEL);
        var txMode = (root && root.dataset.txMode) || '';
        var txStatus = (root && root.dataset.txStatus) || '';
        if (isVisitApprovalPending(txMode)) {
          closeFabMenu();
          showTxToast(
            'بازدید در انتظار تأیید است|تا زمان تأیید ادمین، امکان ثبت بازدید مجدد وجود ندارد.',
            false
          );
          return;
        }
        if (isLandInTransaction(txMode, txStatus)) {
          closeFabMenu();
          showTxToast(
            'ابتدا رفع معامله را انجام دهید|برای ثبت بازدید مجدد، از گزینه «رفع معامله» استفاده کنید.',
            false
          );
          return;
        }
        openVisitModal(true);
      }
      revisitBtn.addEventListener('click', onRevisitClick);
      addCleanup(function () {
        revisitBtn.removeEventListener('click', onRevisitClick);
        delete revisitBtn.dataset.ldRevisitBound;
      });
    });
  }

  function initTransactionToggle() {
    var btn = document.getElementById('landTxToggleBtn');
    var root = document.querySelector(ROOT_SEL);
    if (!btn || !root || !btn.hasAttribute('data-land-tx-toggle')) return;

    var cfg = readConfig();
    var initialMode = (cfg && cfg.txMode) || btn.getAttribute('data-land-tx-mode') || 'visit';
    var initialVisit = (cfg && cfg.visitDate) || btn.getAttribute('data-visit-date') || '';
    var initialVisitJalali = (cfg && cfg.visitDateJalali) || '';
    var initialCanRevisit = cfg && cfg.canRevisit;
    applyTxMode(initialMode, initialVisit, initialVisitJalali, initialCanRevisit);
    if (initialMode === 'visit_pending' || initialMode === 'visit_done_pending' || initialMode === 'visit_commission_pending' || initialMode === 'deal_pending') {
      initVisitStatusPoll(initialMode);
    }
    addCleanup(stopVisitStatusPoll);

    function executeVisitDone() {
      var prevMode = btn.getAttribute('data-land-tx-mode') || root.dataset.txMode || 'visit_done';
      var prevVisit = btn.getAttribute('data-visit-date') || '';
      var url = btn.getAttribute('data-visit-complete-url');
      if (!url) {
        showTxToast('مسیر ثبت انجام بازدید در دسترس نیست.', true);
        return;
      }
      btn.dataset.busy = '1';
      btn.disabled = true;
      applyTxMode('visit_done_pending', prevVisit, formatIsoToJalaliShort(prevVisit));
      postLandAction(url, null, function (data) {
        var nextMode = data.tx_mode || 'visit_done_pending';
        applyTxMode(
          nextMode,
          data.visit_date || prevVisit,
          data.visit_date_jalali || formatIsoToJalaliShort(prevVisit),
          data.can_revisit
        );
        if (nextMode === 'visit_done_pending' || nextMode === 'visit_commission_pending' || nextMode === 'deal_pending') initVisitStatusPoll(nextMode);
        showTxToast(data.message, false);
      }).catch(function (err) {
        applyTxMode(prevMode, prevVisit, formatIsoToJalaliShort(prevVisit), root.dataset.canRevisit === '1');
        showTxToast(err.message || 'خطا در ثبت انجام بازدید', true);
      }).finally(function () {
        btn.dataset.busy = '0';
        var currentMode = btn.getAttribute('data-land-tx-mode') || root.dataset.txMode || 'visit';
        syncTxButtonDisabled(btn, currentMode);
      });
    }

    function executeLandTxToggle(mode) {
      var prevMode = mode;
      var prevStatus = root.dataset.txStatus || btn.getAttribute('data-land-tx-status') || 'active';
      var prevVisit = btn.getAttribute('data-visit-date') || '';
      var optimisticMode = prevMode === 'release' ? 'deal' : (prevMode === 'deal' ? 'release' : 'visit');
      var url = btn.getAttribute('data-land-tx-url');
      var confirmBtn = prevMode === 'deal'
        ? document.getElementById('landDealConfirmBtn')
        : document.getElementById('landReleaseConfirmBtn');

      btn.dataset.busy = '1';
      btn.disabled = true;
      if (confirmBtn) {
        confirmBtn.dataset.busy = '1';
        confirmBtn.disabled = true;
      }
      applyTxMode(optimisticMode, prevVisit, formatIsoToJalaliShort(prevVisit));
      closeLandModals();

      postLandAction(url, null, function (data) {
        var st = data.new_status || statusFromMode(optimisticMode);
        var nextMode = data.tx_mode || (st === 'in_transaction' ? 'release' : (prevVisit ? 'deal' : 'visit'));
        var keepVisit = data.visit_date || prevVisit;
        var keepVisitJalali = data.visit_date_jalali || formatIsoToJalaliShort(keepVisit);
        applyTxMode(nextMode, keepVisit, keepVisitJalali, data.can_revisit);
        if (nextMode === 'deal_pending') initVisitStatusPoll(nextMode);
        showTxToast(data.message, false);
      }).catch(function (err) {
        applyTxMode(prevMode, prevVisit, formatIsoToJalaliShort(prevVisit), root.dataset.canRevisit === '1');
        root.dataset.txStatus = prevStatus;
        showTxToast(err.message || 'خطا در بروزرسانی', true);
      }).finally(function () {
        btn.dataset.busy = '0';
        if (confirmBtn) {
          confirmBtn.dataset.busy = '0';
          confirmBtn.disabled = false;
        }
        var currentMode = btn.getAttribute('data-land-tx-mode') || root.dataset.txMode || 'visit';
        syncTxButtonDisabled(btn, currentMode);
      });
    }

    function bindTxConfirm(modalBtnId, mode) {
      var confirmBtn = document.getElementById(modalBtnId);
      if (!confirmBtn || confirmBtn.dataset.ldTxConfirmBound === '1') return;
      confirmBtn.dataset.ldTxConfirmBound = '1';
      function onConfirm() {
        if (confirmBtn.disabled || confirmBtn.dataset.busy === '1') return;
        executeLandTxToggle(mode);
      }
      confirmBtn.addEventListener('click', onConfirm);
      addCleanup(function () {
        confirmBtn.removeEventListener('click', onConfirm);
        delete confirmBtn.dataset.ldTxConfirmBound;
      });
    }

    bindTxConfirm('landDealConfirmBtn', 'deal');
    bindTxConfirm('landReleaseConfirmBtn', 'release');

    function onClick() {
      if (btn.disabled || btn.dataset.busy === '1') return;
      var mode = btn.getAttribute('data-land-tx-mode') || root.dataset.txMode || 'visit';

      if (mode === 'visit_pending') {
        var pendingHint = '';
        var hintEl = document.getElementById('landVisitDateHint');
        if (hintEl && !hintEl.classList.contains('hidden')) {
          pendingHint = ' ' + (hintEl.textContent || '').trim();
        }
        showTxToast(
          'درخواست بازدید در انتظار تأیید ادمین است.' + pendingHint,
          false
        );
        return;
      }

      if (mode === 'visit_commission_pending') {
        showTxToast('پورسانت بازدید در انتظار تأیید ادمین است. پس از تأیید می‌توانید درخواست معامله ثبت کنید.', false);
        return;
      }

      if (mode === 'visit_done_pending') {
        showTxToast('بازدید انجام شد ثبت شده و منتظر تأیید ادمین است.', false);
        return;
      }

      if (mode === 'visit' || mode === 'revisit') {
        openVisitModal();
        return;
      }

      if (mode === 'visit_done') {
        executeVisitDone();
        return;
      }

      if (mode === 'deal_pending') {
        showTxToast('درخواست معامله ثبت شده و منتظر تأیید ادمین است.', false);
        return;
      }

      if (mode === 'deal') {
        openLandModal('landDealModal');
        return;
      }

      if (mode === 'release') {
        openLandModal('landReleaseModal');
        return;
      }
    }

    btn.addEventListener('click', onClick);
    addCleanup(function () {
      btn.removeEventListener('click', onClick);
    });
  }

  function initLandFlashes(cfg) {
    var list = (cfg && cfg.flashMessages) || [];
    if (!list.length) return;
    var first = list[0];
    var text = typeof first === 'string' ? first : (first && first.text);
    if (!text) return;
    var cat = typeof first === 'object' && first ? first.category : '';
    var isError = cat === 'error' || cat === 'danger';
    showTxToast(text, isError);
  }

  function initLandDetailDownload(cfg) {
    var downloadBtn = document.getElementById('landDetailDownloadBtn');
    var downloadWrap = downloadBtn && downloadBtn.closest('.ld-download-wrap');
    if (!downloadBtn || !downloadWrap) return;

    var hideRingTimer = null;

    function isVinorNativeApp() {
      return /VinorApp\//i.test(navigator.userAgent || '');
    }

    function nativeDownloadAvailable() {
      try {
        return isVinorNativeApp() &&
          window.VinorNativeDownload &&
          typeof window.VinorNativeDownload.downloadUrl === 'function';
      } catch (e) {
        return false;
      }
    }

    function absMediaUrl(url) {
      var u = String(url || '').trim();
      if (!u) return '';
      if (/^https?:\/\//i.test(u)) return u;
      if (u.charAt(0) === '/') return window.location.origin + u;
      return window.location.origin + '/' + u;
    }

    function delay(ms) {
      return new Promise(function (resolve) {
        setTimeout(resolve, ms);
      });
    }

    function extFromUrl(url, fallback) {
      try {
        var path = String(url || '').split('?')[0];
        var m = path.match(/\.([a-z0-9]{2,5})$/i);
        if (m) return m[1].toLowerCase();
      } catch (e) { /* ignore */ }
      return fallback || 'jpg';
    }

    function defaultFilename(item) {
      if (item.filename) return item.filename;
      var code = (cfg && cfg.code) || 'file';
      var ext = extFromUrl(item.url, item.type === 'video' ? 'mp4' : 'jpg');
      if (item.type === 'video') return code + '_video.' + ext;
      return code + '_image.' + ext;
    }

    function getMediaItems() {
      return (cfg.marketingMedia || []).filter(function (it) {
        return it && it.url;
      });
    }

    function setDownloadProgress(ratio) {
      var p = Math.max(0, Math.min(1, Number(ratio) || 0));
      downloadWrap.style.setProperty('--ld-dl-p', String(p));
      downloadWrap.classList.toggle('is-downloading', p > 0);
    }

    function resetDownloadProgress() {
      downloadWrap.classList.remove('is-downloading');
      downloadWrap.style.setProperty('--ld-dl-p', '0');
      downloadBtn.removeAttribute('aria-busy');
    }

    function startDownloadProgress() {
      if (hideRingTimer) {
        clearTimeout(hideRingTimer);
        hideRingTimer = null;
      }
      downloadBtn.setAttribute('aria-busy', 'true');
      setDownloadProgress(0.06);
    }

    function finishDownloadProgress(ok) {
      setDownloadProgress(ok ? 1 : 0);
      hideRingTimer = setTimeout(function () {
        resetDownloadProgress();
        hideRingTimer = null;
      }, ok ? 520 : 280);
    }

    function triggerBlobDownload(blob, filename) {
      var a = document.createElement('a');
      var obj = URL.createObjectURL(blob);
      a.href = obj;
      a.download = filename;
      a.rel = 'noopener';
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      setTimeout(function () {
        URL.revokeObjectURL(obj);
        a.remove();
      }, 8000);
    }

    function fetchMediaBlob(item) {
      return fetch(item.url, { credentials: 'same-origin' })
        .then(function (res) {
          if (!res.ok) throw new Error('download');
          return res.blob();
        })
        .then(function (blob) {
          return { blob: blob, filename: defaultFilename(item) };
        });
    }

    function staggerBlobDownloads(results) {
      var chain = Promise.resolve();
      results.forEach(function (r, idx) {
        chain = chain.then(function () {
          triggerBlobDownload(r.blob, r.filename);
          return idx < results.length - 1 ? delay(360) : delay(0);
        });
      });
      return chain;
    }

    function downloadViaNative(items) {
      var bridge = window.VinorNativeDownload;
      var total = items.length;
      var enqueued = 0;
      return new Promise(function (resolve) {
        var i = 0;
        function next() {
          if (i >= total) {
            resolve({
              ok: enqueued > 0,
              saved: enqueued,
              total: total,
              failCount: total - enqueued
            });
            return;
          }
          try {
            bridge.downloadUrl(absMediaUrl(items[i].url), defaultFilename(items[i]));
            enqueued += 1;
          } catch (e) { /* ignore */ }
          i += 1;
          setDownloadProgress(i / total);
          setTimeout(next, i < total ? 320 : 0);
        }
        next();
      });
    }

    function downloadViaWeb(items) {
      var total = items.length;
      var completed = 0;
      function tickProgress() {
        completed += 1;
        setDownloadProgress(completed / total);
      }

      return Promise.all(items.map(function (item) {
        return fetchMediaBlob(item)
          .then(function (result) {
            tickProgress();
            return { ok: true, result: result };
          })
          .catch(function () {
            tickProgress();
            return { ok: false };
          });
      })).then(function (outcomes) {
        var okItems = outcomes.filter(function (o) { return o.ok; }).map(function (o) { return o.result; });
        var failCount = outcomes.length - okItems.length;
        if (!okItems.length) {
          return { ok: false, saved: 0, total: total, failCount: failCount };
        }
        return staggerBlobDownloads(okItems).then(function () {
          return { ok: true, saved: okItems.length, total: total, failCount: failCount };
        });
      });
    }

    function showDownloadResult(result, useNative) {
      if (!result || !result.ok) {
        finishDownloadProgress(false);
        showTxToast('خطا در دانلود — دوباره تلاش کنید', true);
        return;
      }
      finishDownloadProgress(true);
      if (useNative) {
        showTxToast(
          result.failCount > 0
            ? ('دانلود ' + result.saved + ' از ' + result.total + ' فایل در پوشه Downloads')
            : ('دانلود ' + result.saved + ' فایل در پوشه Downloads'),
          false
        );
        return;
      }
      showTxToast(
        result.failCount > 0
          ? ('دانلود ' + result.saved + ' از ' + result.total + ' فایل آغاز شد')
          : ('دانلود ' + result.saved + ' فایل آغاز شد'),
        false
      );
    }

    function onDownloadClick() {
      var items = getMediaItems();
      if (!items.length) {
        showTxToast('فایلی برای دانلود نیست', true);
        return;
      }
      if (downloadWrap.dataset.busy === '1') return;

      downloadWrap.dataset.busy = '1';
      startDownloadProgress();

      var useNative = nativeDownloadAvailable();
      showTxToast(
        useNative
          ? ('در حال افزودن ' + items.length + ' فایل به دانلود…')
          : ('در حال دانلود ' + items.length + ' فایل…'),
        false
      );

      Promise.resolve(useNative ? downloadViaNative(items) : downloadViaWeb(items))
        .then(function (result) {
          showDownloadResult(result, useNative);
        })
        .catch(function () {
          finishDownloadProgress(false);
          showTxToast('خطا در دانلود — دوباره تلاش کنید', true);
        })
        .finally(function () {
          downloadWrap.dataset.busy = '0';
        });
    }

    downloadBtn.addEventListener('click', onDownloadClick);
    addCleanup(function () {
      downloadBtn.removeEventListener('click', onDownloadClick);
      delete downloadWrap.dataset.busy;
      if (hideRingTimer) clearTimeout(hideRingTimer);
      resetDownloadProgress();
    });
  }

  function initPartnerMarketing(cfg) {
    if (!cfg || !cfg.isApprovedPartner) return;

    function copyPartnerText(text, label) {
      var value = String(text || '').trim();
      if (!value) return;
      function done(ok) {
        showTxToast(ok ? (label + ' کپی شد') : 'کپی انجام نشد', !ok);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(function () { done(true); }).catch(function () { done(false); });
        return;
      }
      try {
        var ta = document.createElement('textarea');
        ta.value = value;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        done(document.execCommand('copy'));
        ta.remove();
      } catch (e) {
        done(false);
      }
    }

    document.querySelectorAll('[data-land-copy]').forEach(function (el) {
      function onCopy(ev) {
        if (ev.target.closest('#landDescToggle')) return;
        ev.preventDefault();
        ev.stopPropagation();
        var kind = el.getAttribute('data-land-copy') || '';
        var text = kind === 'title'
          ? (cfg.marketingTitle || '')
          : kind === 'description'
            ? (cfg.marketingDescription || '')
            : '';
        var label = kind === 'title' ? 'عنوان' : 'توضیحات';
        copyPartnerText(text, label);
      }
      el.addEventListener('click', onCopy);
      addCleanup(function () {
        el.removeEventListener('click', onCopy);
      });
    });

    initLandDetailDownload(cfg);
  }

  function initDescToggle() {
    var btn = document.getElementById('landDescToggle');
    var shortEl = document.getElementById('landDescText');
    var fullEl = document.getElementById('landDescFull');
    var label = document.getElementById('landDescToggleLabel');
    var icon = document.getElementById('landDescToggleIcon');
    if (!btn || !fullEl) return;
    function onToggle() {
      var expanded = !fullEl.classList.contains('hidden');
      if (expanded) {
        fullEl.classList.add('hidden');
        if (shortEl) shortEl.classList.remove('hidden');
        if (label) label.textContent = 'مشاهده بیشتر';
        if (icon) icon.classList.remove('rotate-180');
      } else {
        fullEl.classList.remove('hidden');
        if (shortEl) shortEl.classList.add('hidden');
        if (label) label.textContent = 'بستن';
        if (icon) icon.classList.add('rotate-180');
      }
      requestAnimationFrame(function () {
        syncFooterSpacer();
      });
    }
    btn.addEventListener('click', onToggle);
    addCleanup(function () {
      btn.removeEventListener('click', onToggle);
    });
  }

  function initLandDetail() {
    var root = document.querySelector(ROOT_SEL);
    if (!root) {
      runCleanup();
      return;
    }
    if (activeRoot && activeRoot !== root) {
      runCleanup();
      root = document.querySelector(ROOT_SEL);
      if (!root) return;
    }
    var cfg = readConfig();
    var cfgCode = (cfg && cfg.code) || root.getAttribute('data-land-code') || '';
    if (root.dataset.ldInited === '1') {
      if (activeRoot === root && root.dataset.ldLandCode === cfgCode) return;
      runCleanup();
      root = document.querySelector(ROOT_SEL);
      if (!root) return;
      cfg = readConfig();
      cfgCode = (cfg && cfg.code) || root.getAttribute('data-land-code') || '';
    }

    activeRoot = root;
    root.dataset.ldInited = '1';
    root.dataset.ldLandCode = cfgCode;
    setBottomNavVisible(false);

    hoistLandModalsSafe();
    hoistLandDetailFooter();
    scheduleVisitModalRecovery();

    initGallery(cfg);
    initVideoSound();
    initMoreMenu();
    initShare(cfg);
    initModals();
    initVisitRequest();
    initRevisitTriggers();
    initTransactionToggle();
    initFabMenu();
    initLandFlashes(cfg);
    initPartnerMarketing(cfg);
    initDescToggle();

    if (typeof window.vinorSyncFavButtons === 'function') {
      try { window.vinorSyncFavButtons(root); } catch (e) { /* ignore */ }
    }

    bindFooterSpacerResize();
    requestAnimationFrame(function () {
      syncFooterSpacer();
      requestAnimationFrame(syncFooterSpacer);
    });
    addCleanup(function () {
      document.documentElement.style.removeProperty('--ld-footer-h');
    });
  }

  function onPageReady() {
    var root = document.querySelector(ROOT_SEL);
    if (root) {
      if (activeRoot && activeRoot !== root) {
        runCleanup();
      }
      initLandDetail();
    } else {
      runCleanup();
    }
  }

  window.vinorScheduleVisitModalRecovery = scheduleVisitModalRecovery;
  window.vinorLandDetailTeardown = runCleanup;
  window.vinorLandDetailGalleryKick = kickGalleryMedia;
  window.vinorLandDetailActionsKick = function vinorLandDetailActionsKick() {
    var root = document.querySelector(ROOT_SEL);
    if (!root) return;
    if (!root.dataset.ldInited || root.dataset.ldInited !== '1') {
      initLandDetail();
      return;
    }
    hoistLandModalsSafe();
    hoistLandDetailFooter();
    syncFooterSpacer();
    bindContactModalTel();
    bindVisitSubmitHandler();
    initFabMenu();
    syncFabDirectMode();
  };

  if (!window.__vinorLandDetailBound) {
    window.__vinorLandDetailBound = true;
    document.addEventListener('DOMContentLoaded', onPageReady);
    document.addEventListener('vinor:express-page-swap', onPageReady);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) kickGalleryMedia();
    });
  }
  onPageReady();
})();
