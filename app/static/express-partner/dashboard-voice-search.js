/**
 * جستجوی صوتی داشبورد — Web Speech API + fallback بومی اندروید (VinorSpeech).
 */
(function () {
  'use strict';

  var listening = false;
  var recognition = null;
  var useNative = false;
  var clickBound = false;

  function getSpeechRecognition() {
    return window.SpeechRecognition || window.webkitSpeechRecognition || null;
  }

  function nativeBridge() {
    try {
      return window.VinorSpeech && typeof window.VinorSpeech.startNative === 'function'
        ? window.VinorSpeech
        : null;
    } catch (_) {
      return null;
    }
  }

  function canUseVoice() {
    if (getSpeechRecognition()) return true;
    var bridge = nativeBridge();
    return !!(bridge && bridge.isNativeAvailable && bridge.isNativeAvailable());
  }

  function getTargets() {
    return {
      btn: document.getElementById('dashboardVoiceSearchBtn'),
      form: document.getElementById('searchForm'),
      input: document.getElementById('searchInput'),
    };
  }

  function setListeningUi(btn, on) {
    if (!btn) return;
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.classList.toggle('text-green-600', on);
    btn.classList.toggle('dark:text-green-400', on);
    btn.classList.toggle('text-gray-500', !on);
    btn.classList.toggle('dark:text-gray-400', !on);
    btn.classList.toggle('animate-pulse', on);
  }

  function showPlaceholder(input, text, placeholderDefault, ms) {
    if (!input) return;
    input.setAttribute('placeholder', text);
    window.setTimeout(function () {
      input.setAttribute('placeholder', placeholderDefault);
    }, ms || 2400);
  }

  function submitSearch(form, input) {
    var q = (input && input.value ? input.value : '').trim();
    if (!q || !form) return;
    if (typeof form.requestSubmit === 'function') form.requestSubmit();
    else form.submit();
  }

  function stopListening(btn, input, placeholderDefault) {
    listening = false;
    setListeningUi(btn, false);
    if (input) input.setAttribute('placeholder', placeholderDefault);
    if (useNative) {
      try {
        nativeBridge() && nativeBridge().stopNative();
      } catch (_) {}
      useNative = false;
    }
    if (recognition) {
      try {
        recognition.stop();
      } catch (_) {}
      recognition = null;
    }
  }

  function ensureMicPermission(done) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      done(true);
      return;
    }
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then(function (stream) {
        try {
          stream.getTracks().forEach(function (t) {
            t.stop();
          });
        } catch (_) {}
        done(true);
      })
      .catch(function () {
        done(false);
      });
  }

  function startWebRecognition(btn, form, input, placeholderDefault) {
    var SR = getSpeechRecognition();
    if (!SR) return false;

    var hadError = false;
    recognition = new SR();
    recognition.lang = 'fa-IR';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = function () {
      listening = true;
      setListeningUi(btn, true);
      input.setAttribute('placeholder', 'در حال گوش دادن…');
    };

    recognition.onresult = function (ev) {
      var text = '';
      for (var i = ev.resultIndex; i < ev.results.length; i++) {
        text += ev.results[i][0].transcript;
      }
      input.value = text.trim();
    };

    recognition.onerror = function (ev) {
      hadError = true;
      var err = (ev && ev.error) || '';
      if (err === 'not-allowed' || err === 'service-not-allowed') {
        showPlaceholder(input, 'دسترسی میکروفون لازم است', placeholderDefault);
      } else if (err !== 'aborted' && err !== 'no-speech') {
        showPlaceholder(input, 'خطا در تشخیص صوت', placeholderDefault);
      }
    };

    recognition.onend = function () {
      listening = false;
      setListeningUi(btn, false);
      input.setAttribute('placeholder', placeholderDefault);
      recognition = null;
      if (!hadError) submitSearch(form, input);
    };

    try {
      recognition.start();
      return true;
    } catch (_) {
      recognition = null;
      return false;
    }
  }

  function startNativeRecognition(btn, form, input, placeholderDefault) {
    var bridge = nativeBridge();
    if (!bridge) return false;

    useNative = true;
    input.setAttribute('placeholder', 'در حال آماده‌سازی…');

    window.__vinorVoiceNativeEvent = function (type, payload) {
      var cur = getTargets();
      if (!listening) return;
      if (type === 'start') {
        listening = true;
        setListeningUi(cur.btn, true);
        if (cur.input) cur.input.setAttribute('placeholder', 'در حال گوش دادن…');
        return;
      }
      if (type === 'partial' || type === 'result') {
        if (payload && cur.input) cur.input.value = payload;
        return;
      }
      if (type === 'error') {
        if (payload === 'not-allowed') {
          showPlaceholder(cur.input, 'دسترسی میکروفون لازم است', placeholderDefault);
        } else if (payload !== 'no-speech') {
          showPlaceholder(cur.input, 'خطا در تشخیص صوت', placeholderDefault);
        }
        stopListening(cur.btn, cur.input, placeholderDefault);
        return;
      }
      if (type === 'end') {
        var q = (cur.input && cur.input.value ? cur.input.value : '').trim();
        stopListening(cur.btn, cur.input, placeholderDefault);
        if (q) submitSearch(cur.form, cur.input);
      }
    };

    try {
      bridge.startNative();
      return true;
    } catch (_) {
      useNative = false;
      listening = false;
      setListeningUi(btn, false);
      input.setAttribute('placeholder', placeholderDefault);
      return false;
    }
  }

  function onVoiceButtonClick(e) {
    var btn = e.target && e.target.closest ? e.target.closest('#dashboardVoiceSearchBtn') : null;
    if (!btn || btn.disabled) return;

    var t = getTargets();
    if (!t.form || !t.input) return;

    e.preventDefault();
    e.stopPropagation();

    var placeholderDefault = t.input.getAttribute('placeholder') || '';

    if (listening) {
      stopListening(t.btn, t.input, placeholderDefault);
      return;
    }

    function startAfterMic(ok) {
      if (!ok) {
        showPlaceholder(t.input, 'دسترسی میکروفون لازم است', placeholderDefault);
        return;
      }
      if (startWebRecognition(t.btn, t.form, t.input, placeholderDefault)) return;
      if (startNativeRecognition(t.btn, t.form, t.input, placeholderDefault)) return;
      showPlaceholder(t.input, 'جستجوی صوتی در دسترس نیست', placeholderDefault);
    }

    if (getSpeechRecognition()) {
      ensureMicPermission(startAfterMic);
    } else if (nativeBridge() && nativeBridge().isNativeAvailable()) {
      startAfterMic(true);
    } else {
      startAfterMic(false);
    }
  }

  function refreshButtonState() {
    var t = getTargets();
    if (!t.btn) return;
    if (!canUseVoice()) {
      t.btn.disabled = true;
      t.btn.setAttribute('title', 'جستجوی صوتی در این دستگاه پشتیبانی نمی‌شود');
      t.btn.classList.add('opacity-40');
      return;
    }
    t.btn.disabled = false;
    t.btn.setAttribute('title', 'جستجوی صوتی');
    t.btn.classList.remove('opacity-40');
    t.btn.tabIndex = 0;
  }

  function setup() {
    refreshButtonState();
    if (!clickBound) {
      clickBound = true;
      document.addEventListener('click', onVoiceButtonClick, true);
    }
  }

  window.__vinorDashboardVoiceSearch = { setup: setup };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else {
    setup();
  }

  window.addEventListener('vinor:express-page-swap', function (ev) {
    if (!ev.detail || ev.detail.navKey !== 'dashboard') return;
    window.setTimeout(setup, 0);
  });

  var origTabEnter = window.__vinorDashboardOnTabEnter;
  window.__vinorDashboardOnTabEnter = function () {
    if (typeof origTabEnter === 'function') origTabEnter();
    setup();
  };
})();
