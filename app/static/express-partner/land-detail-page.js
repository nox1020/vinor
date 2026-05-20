/**
 * هماهنگ‌کنندهٔ لود صفحهٔ جزئیات فایل — یک listener برای soft-nav و جلوگیری از init/teardown تکراری
 */
(function () {
  'use strict';

  var initRaf = 0;

  function isLandDetailActive() {
    return !!document.getElementById('landGallery');
  }

  function runLandDetailInit() {
    if (!isLandDetailActive()) return;

    if (typeof window.__vinorInitLandDetailGallery === 'function') {
      window.__vinorInitLandDetailGallery();
    }
    if (typeof window.vinorInitLandDetailVideoSound === 'function') {
      window.vinorInitLandDetailVideoSound();
    }
    if (typeof window.__vinorInitLandDetailV2 === 'function') {
      window.__vinorInitLandDetailV2();
    } else if (typeof window.vinorSyncFavButtons === 'function') {
      window.vinorSyncFavButtons(document.querySelector('.land-detail-v2') || document);
    }
  }

  function scheduleLandDetailInit() {
    if (!isLandDetailActive()) return;
    if (initRaf) {
      cancelAnimationFrame(initRaf);
      initRaf = 0;
    }
    initRaf = requestAnimationFrame(function () {
      initRaf = 0;
      runLandDetailInit();
    });
  }

  window.__vinorScheduleLandDetailInit = scheduleLandDetailInit;

  if (!window.__vinorLandDetailPageBooted) {
    window.__vinorLandDetailPageBooted = true;
    document.addEventListener('vinor:express-page-swap', scheduleLandDetailInit);
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        setTimeout(scheduleLandDetailInit, 0);
      });
    }
  }

  setTimeout(scheduleLandDetailInit, 0);
})();
