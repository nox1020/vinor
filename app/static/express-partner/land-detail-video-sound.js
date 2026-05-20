/**
 * جزئیات فایل همکار — دکمه بی‌صدا/با‌صدا و پخش مداوم ویدیو
 */
(function (g) {
  'use strict';

  var suppressNextClickUntil = 0;

  function $(id) {
    return document.getElementById(id);
  }

  function applyMute(video, muted) {
    var m = !!muted;
    video.muted = m;
    video.defaultMuted = m;
    if (m) {
      video.setAttribute('muted', '');
    } else {
      video.removeAttribute('muted');
      video.volume = 1;
    }
  }

  function updateUi(btn, icon, muted) {
    var m = !!muted;
    btn.setAttribute('data-muted', m ? 'true' : 'false');
    btn.setAttribute('aria-pressed', m ? 'true' : 'false');
    btn.setAttribute('aria-label', m ? 'بی‌صدا — برای پخش با صدا بزنید' : 'با صدا — برای بی‌صدا کردن بزنید');
    btn.title = m ? 'بی‌صدا' : 'با صدا';
    icon.className = m ? 'fas fa-volume-xmark text-base' : 'fas fa-volume-high text-base';
  }

  function ensurePlaying(video) {
    try {
      video.loop = true;
      var p = video.play();
      if (p && typeof p.catch === 'function') {
        p.catch(function () {
          setTimeout(function () {
            try { video.play(); } catch (_) {}
          }, 100);
        });
      }
    } catch (_) {}
  }

  function toggleSound(e) {
    var btn = e.target && e.target.closest ? e.target.closest('#landVideoSoundToggle') : null;
    if (!btn) return;
    if (e.type === 'click' && Date.now() < suppressNextClickUntil) {
      if (e.cancelable) e.preventDefault();
      e.stopPropagation();
      if (e.stopImmediatePropagation) e.stopImmediatePropagation();
      return;
    }

    var video = $('landVideo');
    var icon = $('landVideoSoundIcon');
    if (!video || !icon) return;

    if (e.cancelable) e.preventDefault();
    e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();

    var currentlyMuted = btn.getAttribute('data-muted') !== 'false';
    var nextMuted = !currentlyMuted;
    applyMute(video, nextMuted);
    updateUi(btn, icon, nextMuted);
    ensurePlaying(video);
  }

  function isLandDetailActive() {
    try {
      return !!document.getElementById('landGallery') && !!$('landVideo');
    } catch (_) {
      return false;
    }
  }

  function teardownLandDetailVideo() {
    var video = $('landVideo');
    if (!video) return;
    try {
      video.pause();
      applyMute(video, true);
      video.removeAttribute('data-vinor-sound-hooks');
    } catch (_) {}
  }

  function initPartnerLandVideo() {
    if (!isLandDetailActive()) return;

    var video = $('landVideo');
    var btn = $('landVideoSoundToggle');
    var icon = $('landVideoSoundIcon');
    if (!video || !btn || !icon) return;

    applyMute(video, true);
    updateUi(btn, icon, true);
    ensurePlaying(video);

    if (video.dataset.vinorSoundHooks === '1') return;
    video.dataset.vinorSoundHooks = '1';

    video.addEventListener('ended', function () {
      if (!isLandDetailActive()) return;
      try {
        video.currentTime = 0;
        ensurePlaying(video);
      } catch (_) {}
    });

    video.addEventListener('pause', function () {
      if (!isLandDetailActive() || !video.isConnected) return;
      if (video.classList.contains('hidden')) return;
      if (document.hidden) return;
      ensurePlaying(video);
    });
  }

  function onPageSwap() {
    teardownLandDetailVideo();
    requestAnimationFrame(initPartnerLandVideo);
  }

  document.addEventListener('click', toggleSound, true);
  document.addEventListener('pointerup', function (e) {
    if (!e.target || !e.target.closest) return;
    if (!e.target.closest('#landVideoSoundToggle')) return;
    if (e.pointerType === 'mouse') return;
    suppressNextClickUntil = Date.now() + 500;
    toggleSound(e);
  }, true);

  function scheduleInit() {
    requestAnimationFrame(initPartnerLandVideo);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scheduleInit);
  } else {
    scheduleInit();
  }

  document.addEventListener('vinor:express-page-swap', onPageSwap);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) teardownLandDetailVideo();
  });

  g.vinorInitLandDetailVideoSound = initPartnerLandVideo;
  g.vinorTeardownLandDetailVideo = teardownLandDetailVideo;
})(window);
