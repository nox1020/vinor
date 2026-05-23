/**
 * جزئیات فایل همکار — گالری، ویدیو، مودال‌ها
 */
(function () {
  'use strict';

  var ROOT_SEL = '.land-detail-page';
  var activeRoot = null;
  var cleanupFns = [];

  function readConfig() {
    var el = document.getElementById('landDetailConfig');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || '{}');
    } catch (e) {
      return null;
    }
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
    setBottomNavVisible(true);
    document.documentElement.classList.remove('vinor-express-overlay-modal-open');
  }

  function setLoader(visible) {
    var loader = document.getElementById('landMediaLoading');
    if (!loader) return;
    loader.classList.toggle('is-visible', !!visible);
    loader.classList.toggle('opacity-100', !!visible);
    loader.classList.toggle('opacity-0', !visible);
  }

  function initGallery(cfg) {
    var gallery = document.getElementById('landGallery');
    if (!gallery || !cfg || !cfg.slides || !cfg.slides.length) return;

    var slides = cfg.slides;
    var video = document.getElementById('landVideo');
    var img = document.getElementById('landMainImage');
    var dots = gallery.querySelectorAll('.ld-dot');
    var label = document.getElementById('landGallerySlideLabel');
    var index = 0;

    function faDigits(n) {
      return String(n).replace(/\d/g, function (d) {
        return '۰۱۲۳۴۵۶۷۸۹'[d];
      });
    }

    function showImageSlide(slide) {
      if (!img) return;
      if (video) {
        video.pause();
        video.classList.add('hidden');
      }
      img.classList.remove('hidden');
      var thumb = slide.thumb || slide.full;
      var full = slide.full || thumb;
      if (img.getAttribute('src') === thumb) return;
      setLoader(true);
      img.onload = function () {
        img.onload = null;
        setLoader(false);
        if (full && full !== thumb) {
          var hi = new Image();
          var idx = index;
          hi.onload = function () {
            var cur = slides[idx];
            if (cur && cur.type === 'image' && img.getAttribute('src') === thumb) {
              img.src = full;
            }
          };
          hi.src = full;
        }
      };
      img.onerror = function () {
        img.onerror = null;
        setLoader(false);
      };
      img.src = thumb;
      img.dataset.full = full;
    }

    function updateUi() {
      dots.forEach(function (dot, i) {
        dot.classList.toggle('is-active', i === index);
      });
      if (label && cfg.totalItems > 1) {
        label.textContent = faDigits(index + 1) + ' از ' + faDigits(cfg.totalItems);
      }
      var slide = slides[index];
      if (!slide) return;
      if (slide.type === 'video' && video) {
        if (img) img.classList.add('hidden');
        video.classList.remove('hidden');
        video.play().catch(function () {});
      } else if (slide.type === 'image') {
        showImageSlide(slide);
      }
    }

    function goTo(next) {
      if (next < 0) next = slides.length - 1;
      if (next >= slides.length) next = 0;
      index = next;
      updateUi();
    }

    var startX = 0;
    var tracking = false;
    var THRESH = 48;

    function onTouchStart(e) {
      if (!e.touches || !e.touches.length) return;
      tracking = true;
      startX = e.touches[0].clientX;
    }
    function onTouchEnd(e) {
      if (!tracking) return;
      tracking = false;
      var endX = (e.changedTouches && e.changedTouches[0]) ? e.changedTouches[0].clientX : startX;
      var dx = endX - startX;
      if (Math.abs(dx) < THRESH) return;
      if (dx > 0) goTo(index + 1);
      else goTo(index - 1);
    }

    gallery.addEventListener('touchstart', onTouchStart, { passive: true });
    gallery.addEventListener('touchend', onTouchEnd, { passive: true });
    addCleanup(function () {
      gallery.removeEventListener('touchstart', onTouchStart);
      gallery.removeEventListener('touchend', onTouchEnd);
    });

    updateUi();
  }

  function initVideoSound() {
    var btn = document.getElementById('landVideoSoundToggle');
    var video = document.getElementById('landVideo');
    var icon = document.getElementById('landVideoSoundIcon');
    if (!btn || !video) return;

    function applyMuted(muted) {
      video.muted = muted;
      btn.dataset.muted = muted ? 'true' : 'false';
      btn.setAttribute('aria-pressed', muted ? 'true' : 'false');
      btn.setAttribute('aria-label', muted ? 'بی‌صدا' : 'با صدا');
      if (icon) {
        icon.className = muted ? 'fas fa-volume-xmark text-sm' : 'fas fa-volume-high text-sm';
      }
    }

    function onClick(e) {
      e.stopPropagation();
      applyMuted(!video.muted);
      if (!video.muted) video.play().catch(function () {});
    }

    applyMuted(true);
    btn.addEventListener('click', onClick);
    addCleanup(function () {
      btn.removeEventListener('click', onClick);
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
    function onShare() {
      var url = (cfg && cfg.shareUrl) || window.location.href;
      var title = document.title || 'فایل';
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
    function open(id) {
      var m = document.getElementById(id);
      if (m) {
        m.classList.remove('hidden');
        document.documentElement.classList.add('vinor-express-overlay-modal-open');
      }
    }
    function closeAll() {
      document.querySelectorAll('.ld-modal').forEach(function (m) {
        m.classList.add('hidden');
      });
      document.documentElement.classList.remove('vinor-express-overlay-modal-open');
    }

    var openHandlers = [];
    document.querySelectorAll('[data-land-open-contact]').forEach(function (el) {
      function h() { open('landContactModal'); }
      el.addEventListener('click', h);
      openHandlers.push({ el: el, fn: h });
    });
    document.querySelectorAll('[data-land-open-location]').forEach(function (el) {
      function h() { open('landLocationModal'); }
      el.addEventListener('click', h);
      openHandlers.push({ el: el, fn: h });
    });
    document.querySelectorAll('[data-land-modal-close]').forEach(function (el) {
      el.addEventListener('click', closeAll);
      openHandlers.push({ el: el, fn: closeAll });
    });
    addCleanup(function () {
      openHandlers.forEach(function (x) {
        x.el.removeEventListener('click', x.fn);
      });
      closeAll();
    });
  }

  var TX_UI = {
    active: {
      label: 'درخواست بازدید',
      icon: 'fa-calendar-check',
      btnClass: 'bg-teal-700/90 hover:bg-teal-600 border border-teal-500/35 shadow-none',
      specLabel: 'فعال',
    },
    in_transaction: {
      label: 'رفع معامله',
      icon: 'fa-check-circle',
      btnClass: 'bg-teal-600 hover:bg-teal-500 shadow-lg shadow-teal-900/30 border-0',
      specLabel: 'در حال معامله',
    },
  };

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

  function applyTxStatus(status) {
    var root = document.querySelector(ROOT_SEL);
    var btn = document.getElementById('landTxToggleBtn');
    var cfg = TX_UI[status] || TX_UI.active;
    if (root) root.dataset.txStatus = status;
    if (btn) {
      btn.setAttribute('data-land-tx-status', status);
      var icon = btn.querySelector('.land-tx-icon');
      var label = btn.querySelector('.land-tx-label');
      if (icon) icon.className = 'fas ' + cfg.icon + ' land-tx-icon';
      if (label) label.textContent = cfg.label;
      btn.className = 'w-full flex items-center justify-center gap-2 rounded-2xl text-white font-bold py-3.5 text-sm active:scale-[0.98] transition-all disabled:opacity-60 disabled:pointer-events-none ' + cfg.btnClass;
    }
    var badge = document.getElementById('landTxStatusBadge');
    if (badge) badge.classList.toggle('hidden', status !== 'in_transaction');
    var spec = document.querySelector('[data-land-tx-spec-value]');
    if (spec) spec.textContent = cfg.specLabel;
  }

  function initTransactionToggle() {
    var btn = document.getElementById('landTxToggleBtn');
    var root = document.querySelector(ROOT_SEL);
    if (!btn || !root) return;

    function onClick() {
      if (btn.disabled || btn.dataset.busy === '1') return;
      var prev = root.dataset.txStatus || btn.getAttribute('data-land-tx-status') || 'active';
      var optimistic = prev === 'in_transaction' ? 'active' : 'in_transaction';
      var url = btn.getAttribute('data-land-tx-url');
      var csrf = btn.getAttribute('data-csrf') ||
        (window.VINOR_NOTIFY_CFG && window.VINOR_NOTIFY_CFG.csrfToken) || '';

      btn.dataset.busy = '1';
      btn.disabled = true;
      applyTxStatus(optimistic);

      var body = new FormData();
      if (csrf) body.append('csrf_token', csrf);

      fetch(url, {
        method: 'POST',
        body: body,
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data || !result.data.success) {
            throw new Error((result.data && result.data.message) || 'خطا در بروزرسانی وضعیت');
          }
          var st = result.data.new_status || optimistic;
          applyTxStatus(st);
          showTxToast(result.data.message, false);
        })
        .catch(function (err) {
          applyTxStatus(prev);
          showTxToast(err.message || 'خطا در بروزرسانی', true);
        })
        .finally(function () {
          btn.dataset.busy = '0';
          btn.disabled = false;
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
    if (!root || root.dataset.ldInited === '1') return;

    if (activeRoot && activeRoot !== root) {
      runCleanup();
    }

    activeRoot = root;
    root.dataset.ldInited = '1';
    setBottomNavVisible(false);

    try {
      if (typeof window.hoistVinorExpressBodyModals === 'function') {
        window.hoistVinorExpressBodyModals();
      }
    } catch (e) { /* ignore */ }

    var cfg = readConfig();
    initGallery(cfg);
    initVideoSound();
    initMoreMenu();
    initShare(cfg);
    initModals();
    initTransactionToggle();
    initLandFlashes(cfg);
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
    if (document.querySelector(ROOT_SEL)) {
      initLandDetail();
    } else {
      runCleanup();
    }
  }

  if (!window.__vinorLandDetailBound) {
    window.__vinorLandDetailBound = true;
    document.addEventListener('DOMContentLoaded', onPageReady);
    document.addEventListener('vinor:express-page-swap', onPageReady);
  }
  onPageReady();
})();
