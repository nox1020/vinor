/**
 * بارگذاری تصویر/ویدیو کارت‌های پریمیوم — مشترک بین داشبورد و علاقه‌مندی‌ها
 */
(function (g) {
  'use strict';

  function initPremiumCardMedia(scope) {
    var root = scope || document;
    root.querySelectorAll('[data-img-wrap]').forEach(function (wrap) {
      if (wrap.dataset.vinorMediaInit === '1') return;
      wrap.dataset.vinorMediaInit = '1';

      var img = wrap.querySelector('[data-card-img]');
      var vid = wrap.querySelector('video');
      var loader = wrap.querySelector('.card-img-loading');

      function hideLoader() {
        if (!loader) return;
        loader.classList.add('opacity-0', 'pointer-events-none');
        setTimeout(function () {
          try { loader.remove(); } catch (_) {}
        }, 250);
      }

      function showMedia(el) {
        if (el) el.classList.remove('opacity-0');
        hideLoader();
      }

      if (!img && !vid) {
        hideLoader();
        return;
      }

      if (img) {
        if (img.complete && img.naturalWidth > 0) showMedia(img);
        else {
          img.addEventListener('load', function () { showMedia(img); }, { once: true });
          img.addEventListener('error', hideLoader, { once: true });
        }
      }

      if (vid && !(vid.hasAttribute('data-vinor-lazy-video') && vid.dataset.vinorLazyLoaded !== '1')) {
        var ready = function () { showMedia(vid); };
        if (vid.readyState >= 2) ready();
        else {
          vid.addEventListener('loadeddata', ready, { once: true });
          vid.addEventListener('error', hideLoader, { once: true });
        }
      }

      setTimeout(hideLoader, 8000);
    });
  }

  function initLazyCardVideos(scope, scrollRoot) {
    var root = scope || document;
    var videos = root.querySelectorAll('video[data-vinor-lazy-video]');
    if (!videos.length) return;

    function loadLazyCardVideo(vid) {
      if (vid.dataset.vinorLazyLoaded === '1') return;
      var wrap = vid.closest('[data-img-wrap]');
      var loader = wrap && wrap.querySelector('.card-img-loading');

      function hideLoader() {
        if (!loader) return;
        loader.classList.add('opacity-0', 'pointer-events-none');
        setTimeout(function () {
          try { loader.remove(); } catch (_) {}
        }, 250);
      }

      function showMedia() {
        vid.classList.remove('opacity-0');
        hideLoader();
      }

      vid.addEventListener('loadeddata', showMedia, { once: true });
      vid.addEventListener('error', hideLoader, { once: true });
      var source = vid.querySelector('source[data-src]');
      if (source && source.dataset.src) {
        source.src = source.dataset.src;
        vid.load();
        vid.play().catch(function () {});
      }
      vid.dataset.vinorLazyLoaded = '1';
    }

    if (!('IntersectionObserver' in g)) {
      videos.forEach(loadLazyCardVideo);
      return;
    }

    var ioOpts = { rootMargin: '120px 0px', threshold: 0.01 };
    if (scrollRoot) ioOpts.root = scrollRoot;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        loadLazyCardVideo(entry.target);
        io.unobserve(entry.target);
      });
    }, ioOpts);
    videos.forEach(function (v) { io.observe(v); });
  }

  g.vinorInitPremiumCards = function (scope, scrollRoot) {
    initPremiumCardMedia(scope);
    initLazyCardVideos(scope, scrollRoot || null);
  };
})(window);
