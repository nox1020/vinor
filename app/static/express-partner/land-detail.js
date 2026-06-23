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
    } catch (e3) { /* ignore */ }
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
    document.querySelectorAll('.ld-modal').forEach(function (m) {
      m.classList.add('hidden');
      m.style.display = 'none';
      m.setAttribute('aria-hidden', 'true');
    });
    activeLandModalId = null;
    landModalOverlayCloseAll();
  }

  function openLandModal(id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    closeLandModals();
    modal.classList.remove('hidden');
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
    activeLandModalId = id;
    landModalOverlayOpen();
    var panel = modal.querySelector('[data-land-modal-panel]') || modal.querySelector('.relative');
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
    var dots = gallery.querySelectorAll('.ld-dot');
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
        label.textContent = faDigits(index + 1) + ' از ' + faDigits(cfg.totalItems);
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

    btn.addEventListener('click', toggle);
    document.addEventListener('click', onDocClick);
    addCleanup(function () {
      btn.removeEventListener('click', toggle);
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
        return;
      }
      if (!activeRoot || !activeRoot.contains(ev.target)) return;
      if (ev.target.closest('[data-land-open-contact]')) {
        ev.preventDefault();
        openLandModal('landContactModal');
        return;
      }
      if (ev.target.closest('[data-land-open-location]')) {
        ev.preventDefault();
        openLandModal('landLocationModal');
      }
    }

    function onEscape(ev) {
      if (ev.key !== 'Escape' || !activeLandModalId) return;
      ev.preventDefault();
      closeLandModals();
    }

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
      btnClass: 'bg-teal-700/90 hover:bg-teal-600 border border-teal-500/35 shadow-none',
      specLabel: 'فعال',
    },
    visit_pending: {
      label: 'در انتظار تأیید بازدید',
      icon: 'fa-clock',
      btnClass: 'bg-slate-600/90 cursor-default opacity-90 shadow-none border-0',
      specLabel: 'منتظر تأیید ادمین',
    },
    deal: {
      label: 'درخواست معامله',
      icon: 'fa-handshake',
      btnClass: 'bg-teal-700/90 hover:bg-teal-600 border border-teal-500/35 shadow-none',
      specLabel: 'بازدید ثبت‌شده',
    },
    release: {
      label: 'رفع معامله',
      icon: 'fa-check-circle',
      btnClass: 'bg-teal-600 hover:bg-teal-500 shadow-lg shadow-teal-900/30 border-0',
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

  function isDateInVisitRange(d) {
    var iso = toLocalISODate(d);
    return iso >= toLocalISODate(visitCalState.minDate) && iso <= toLocalISODate(visitCalState.maxDate);
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
      btn.className = 'aspect-square rounded-lg text-xs font-medium transition ' + (
        !enabled
          ? 'text-gray-600 cursor-not-allowed opacity-40'
          : visitCalState.selectedIso === iso
            ? 'bg-teal-500 text-white ring-2 ring-teal-300'
            : iso === todayIso
              ? 'bg-white/10 text-white hover:bg-teal-600/40'
              : 'text-gray-200 hover:bg-white/10'
      );
      btn.disabled = !enabled;
      if (enabled) {
        (function (dayIso) {
          btn.addEventListener('click', function () {
            visitCalState.selectedIso = dayIso;
            var hidden = document.getElementById('landVisitDateInput');
            var selectedEl = document.getElementById('landVisitCalSelected');
            if (hidden) hidden.value = dayIso;
            if (selectedEl) selectedEl.textContent = formatIsoToJalali(dayIso);
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
    var selectedEl = document.getElementById('landVisitCalSelected');
    if (hidden) hidden.value = '';
    if (selectedEl) selectedEl.textContent = 'تاریخ انتخاب نشده';
    syncVisitSubmitEnabled();
  }

  function syncVisitSubmitEnabled() {
    var submitBtn = document.getElementById('landVisitSubmitBtn');
    var dateInput = document.getElementById('landVisitDateInput');
    if (!submitBtn) return;
    var hasDate = !!(dateInput && (dateInput.value || '').trim());
    submitBtn.disabled = !hasDate || submitBtn.dataset.busy === '1';
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
      hint.textContent = 'بازدید: ' + display;
      hint.classList.remove('hidden');
    } else {
      hint.textContent = '';
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

  function showTxToast(message, isError) {
    var toast = document.getElementById('landTxToast');
    if (!toast || !message) return;
    toast.textContent = message;
    toast.classList.remove('hidden', 'is-success', 'is-error');
    toast.classList.add(isError ? 'is-error' : 'is-success');
    syncFooterSpacer();
    clearTimeout(showTxToast._t);
    showTxToast._t = setTimeout(function () {
      toast.classList.add('hidden');
      toast.classList.remove('is-success', 'is-error');
      syncFooterSpacer();
    }, 2800);
  }

  function getLandCsrf() {
    var btn = document.getElementById('landTxToggleBtn');
    var cfg = readConfig();
    return (btn && btn.getAttribute('data-csrf')) ||
      (cfg && cfg.csrfToken) ||
      (window.VINOR_NOTIFY_CFG && window.VINOR_NOTIFY_CFG.csrfToken) ||
      '';
  }

  function syncTxButtonDisabled(btn, mode) {
    if (!btn || btn.tagName !== 'BUTTON') return;
    var pending = mode === 'visit_pending';
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
    if (initialMode !== 'visit_pending') return;

    var root = document.querySelector(ROOT_SEL);
    var prevMode = initialMode;

    function pollOnce() {
      fetchLandTxStatus().then(function (data) {
        if (!data || !data.success) return;
        var mode = data.tx_mode || 'visit';
        if (mode === prevMode) return;
        prevMode = mode;
        applyTxMode(mode, data.visit_date || '', data.visit_date_jalali || '');
        if (mode === 'deal') {
          showTxToast('بازدید تأیید شد — اکنون می‌توانید درخواست معامله ثبت کنید.', false);
          stopVisitStatusPoll();
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

  function applyTxMode(mode, visitDate, visitDateJalali) {
    var root = document.querySelector(ROOT_SEL);
    var btn = document.getElementById('landTxToggleBtn');
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
      var label = btn.querySelector('.land-tx-label');
      if (icon) icon.className = 'fas ' + cfg.icon + ' land-tx-icon';
      if (label) label.textContent = cfg.label;
      btn.className = 'w-full flex items-center justify-center gap-2 rounded-2xl text-white font-bold py-3.5 text-sm active:scale-[0.98] transition-all disabled:opacity-70 disabled:pointer-events-none ' + cfg.btnClass;
      if (visitDate) {
        btn.setAttribute('data-visit-date', visitDate);
      }
      syncTxButtonDisabled(btn, mode);
    }
    var badge = document.getElementById('landTxStatusBadge');
    if (badge) badge.classList.toggle('hidden', mode !== 'release');
    var spec = document.querySelector('[data-land-tx-spec-value]');
    if (spec) spec.textContent = cfg.specLabel;
    if (mode === 'deal' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'visit_pending' && (visitDate || visitDateJalali)) {
      updateVisitDateHint(visitDate, visitDateJalali);
    } else if (mode === 'visit' || mode === 'release') {
      updateVisitDateHint('');
    }
    if (mode !== 'visit_pending') {
      stopVisitStatusPoll();
    }
    if (mode === 'visit') {
      scheduleVisitModalRecovery();
    }
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
    if (!btn || !btn.hasAttribute('data-land-tx-toggle')) return false;
    if (!btn.getAttribute('data-visit-request-url')) return false;
    var cfg = readConfig();
    var mode = (btn.getAttribute('data-land-tx-mode') || (cfg && cfg.txMode) || '').trim();
    return mode === 'visit' || mode === 'visit_pending' || mode === 'deal' || mode === 'release';
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
    initVisitCalendarControls();
    bindVisitSubmitHandler();
  }

  function scheduleVisitModalRecovery() {
    if (!shouldOfferVisitModal()) return;
    if (document.getElementById('landVisitModal')) return;
    recoverVisitModal().then(function (modal) {
      if (modal) rebindVisitModalHandlers();
    });
  }

  function openVisitModalNow() {
    openLandModal('landVisitModal');
    initVisitCalendarControls();
    initVisitCalBounds();
    resetVisitCalendarSelection();
    renderVisitCalendar();
    syncVisitSubmitEnabled();
  }

  function openVisitModal() {
    var btn = document.getElementById('landTxToggleBtn');
    var mode = (btn && btn.getAttribute('data-land-tx-mode')) || '';
    if (mode && mode !== 'visit') {
      return;
    }

    var modal = ensureVisitModalEl();
    if (modal) {
      openVisitModalNow();
      return;
    }

    if (btn) {
      btn.dataset.busy = '1';
      btn.disabled = true;
    }

    recoverVisitModal().then(function (recovered) {
      if (btn) {
        btn.dataset.busy = '0';
        syncTxButtonDisabled(btn, 'visit');
      }
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
    return fetch(url, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        Accept: 'application/json',
      },
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
    if (!submitBtn || !txBtn) return;
    if (submitBtn.dataset.visitSubmitBound === '1') return;
    submitBtn.dataset.visitSubmitBound = '1';

    function onSubmit() {
      if (submitBtn.disabled || submitBtn.dataset.busy === '1') return;
      var visitDate = dateInput ? (dateInput.value || '').trim() : '';
      if (!visitDate) {
        showTxToast('لطفاً تاریخ بازدید را انتخاب کنید.', true);
        return;
      }
      var url = txBtn.getAttribute('data-visit-request-url');
      if (!url) return;

      var prevLabel = submitBtn.innerHTML;
      submitBtn.dataset.busy = '1';
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> در حال ارسال…';
      closeLandModals();

      var jalaliPreview = formatIsoToJalaliShort(visitDate) || formatIsoToJalali(visitDate);
      applyTxMode('visit_pending', visitDate, jalaliPreview);
      initVisitStatusPoll('visit_pending');
      focusDetailActionsAfterVisit();

      postLandAction(url, { visit_date: visitDate }, function (data) {
        var mode = data.tx_mode || 'visit_pending';
        applyTxMode(
          mode,
          data.visit_date || visitDate,
          data.visit_date_jalali || jalaliPreview
        );
        if (mode === 'visit_pending') initVisitStatusPoll('visit_pending');
        var toastMsg = (data.message && String(data.message).indexOf('قبلاً') !== -1)
          ? data.message
          : VISIT_SENT_MSG;
        showTxToast(toastMsg, false);
        focusDetailActionsAfterVisit();
        fetchLandTxStatus().then(function (st) {
          if (!st || !st.success) return;
          applyTxMode(
            st.tx_mode || mode,
            st.visit_date || visitDate,
            st.visit_date_jalali || jalaliPreview
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

  function initTransactionToggle() {
    var btn = document.getElementById('landTxToggleBtn');
    var root = document.querySelector(ROOT_SEL);
    if (!btn || !root || !btn.hasAttribute('data-land-tx-toggle')) return;

    var cfg = readConfig();
    var initialMode = (cfg && cfg.txMode) || btn.getAttribute('data-land-tx-mode') || 'visit';
    var initialVisit = (cfg && cfg.visitDate) || btn.getAttribute('data-visit-date') || '';
    var initialVisitJalali = (cfg && cfg.visitDateJalali) || '';
    applyTxMode(initialMode, initialVisit, initialVisitJalali);
    if (initialMode === 'visit_pending') initVisitStatusPoll('visit_pending');
    addCleanup(stopVisitStatusPoll);

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

      if (mode === 'visit') {
        openVisitModal();
        return;
      }

      var prevMode = mode;
      var prevStatus = root.dataset.txStatus || btn.getAttribute('data-land-tx-status') || 'active';
      var prevVisit = btn.getAttribute('data-visit-date') || '';
      var optimisticMode = prevMode === 'release' ? 'visit' : (prevMode === 'deal' ? 'release' : 'visit');
      var url = btn.getAttribute('data-land-tx-url');

      btn.dataset.busy = '1';
      btn.disabled = true;
      applyTxMode(optimisticMode);

      postLandAction(url, null, function (data) {
        var st = data.new_status || statusFromMode(optimisticMode);
        var nextMode = data.tx_mode || (st === 'in_transaction' ? 'release' : (prevVisit ? 'deal' : 'visit'));
        applyTxMode(
          nextMode,
          data.visit_date || (nextMode === 'deal' ? prevVisit : ''),
          data.visit_date_jalali || (nextMode === 'deal' ? formatIsoToJalaliShort(prevVisit) : '')
        );
        showTxToast(data.message, false);
      }).catch(function (err) {
        applyTxMode(prevMode, prevVisit, formatIsoToJalaliShort(prevVisit));
        root.dataset.txStatus = prevStatus;
        showTxToast(err.message || 'خطا در بروزرسانی', true);
      }).finally(function () {
        btn.dataset.busy = '0';
        var currentMode = btn.getAttribute('data-land-tx-mode') || root.dataset.txMode || 'visit';
        syncTxButtonDisabled(btn, currentMode);
      });
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
        if (label) label.textContent = 'بیشتر بخوانید';
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
    }
    if (root.dataset.ldInited === '1') return;

    activeRoot = root;
    root.dataset.ldInited = '1';
    setBottomNavVisible(false);

    hoistLandModalsSafe();
    scheduleVisitModalRecovery();

    var cfg = readConfig();
    initGallery(cfg);
    initVideoSound();
    initMoreMenu();
    initShare(cfg);
    initModals();
    initVisitRequest();
    initTransactionToggle();
    initLandFlashes(cfg);
    initPartnerMarketing(cfg);
    initDescToggle();

    if (typeof window.vinorSyncFavButtons === 'function') {
      try { window.vinorSyncFavButtons(root); } catch (e) { /* ignore */ }
    }

    var similarTrack = root.querySelector('#ldSimilarTrack');
    if (similarTrack && typeof window.vinorInitPremiumCards === 'function') {
      try { window.vinorInitPremiumCards(similarTrack, similarTrack); } catch (e) { /* ignore */ }
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

  if (!window.__vinorLandDetailBound) {
    window.__vinorLandDetailBound = true;
    document.addEventListener('DOMContentLoaded', onPageReady);
    document.addEventListener('vinor:express-page-swap', onPageReady);
  }
  onPageReady();
})();
