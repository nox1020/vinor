/**
 * جستجوی صوتی داشبورد — Web Speech API + fallback بومی اندروید (VinorSpeech).
 */
(function () {
  'use strict';

  var listening = false;
  var nativePending = false;
  var recognition = null;
  var useNative = false;
  var clickBound = false;
  var lastVoiceText = '';
  var lastWebError = '';

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

  function isVinorNativeApp() {
    return /VinorApp\//i.test(navigator.userAgent || '');
  }

  function nativeVoiceAvailable() {
    var bridge = nativeBridge();
    try {
      return !!(bridge && bridge.isNativeAvailable && bridge.isNativeAvailable());
    } catch (_) {
      return false;
    }
  }

  function canUseVoice() {
    if (nativeVoiceAvailable()) return true;
    return !!getSpeechRecognition();
  }

  function getTargets() {
    return {
      btn: document.getElementById('dashboardVoiceSearchBtn'),
      form: document.getElementById('searchForm'),
      input: document.getElementById('searchInput'),
    };
  }

  function placeholderDefault(input) {
    if (!input) return '';
    return input.getAttribute('data-voice-placeholder') || input.getAttribute('placeholder') || '';
  }

  function rememberPlaceholder(input) {
    if (!input || input.getAttribute('data-voice-placeholder')) return;
    input.setAttribute('data-voice-placeholder', input.getAttribute('placeholder') || '');
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

  function showPlaceholder(input, text, defaultText, ms) {
    if (!input) return;
    input.setAttribute('placeholder', text);
    window.setTimeout(function () {
      input.setAttribute('placeholder', defaultText || placeholderDefault(input));
    }, ms || 2400);
  }

  function buildSearchUrl(form, q) {
    if (!form || !q) return null;
    var params = new URLSearchParams();
    try {
      new FormData(form).forEach(function (value, key) {
        if (value != null && String(value).trim() !== '') params.set(key, String(value).trim());
      });
    } catch (_) {}
    params.set('q', q);
    var action = form.getAttribute('action') || '/express/partner/files';
    try {
      var u = new URL(action, window.location.origin);
      u.search = params.toString();
      return u.pathname + u.search;
    } catch (_) {
      return action.split('?')[0] + '?' + params.toString();
    }
  }

  function submitSearch(form, input) {
    var q = (input && input.value ? input.value : lastVoiceText || '').trim();
    if (!q || !form) return;
    if (input) input.value = q;
    try {
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (_) {}

    var url = buildSearchUrl(form, q);
    if (!url) return;

    if (window.__vinorDashboardSearch && typeof window.__vinorDashboardSearch.runFromForm === 'function') {
      try {
        var path = window.location.pathname.replace(/\/+$/, '') || '/';
        if (path === '/express/partner/files') {
          window.__vinorDashboardSearch.runFromForm(form, q);
          return;
        }
      } catch (_) {}
    }

    if (typeof window.vinorExpressNavigate === 'function') {
      try {
        var pathNav = window.location.pathname.replace(/\/+$/, '') || '/';
        if (pathNav === '/express/partner/files') {
          window.vinorExpressNavigate(url, { forward: false });
          return;
        }
      } catch (_) {}
    }

    try {
      if (typeof form.requestSubmit === 'function') {
        form.requestSubmit();
        return;
      }
    } catch (_) {}
    try {
      form.submit();
      return;
    } catch (_) {}
    window.location.href = url;
  }

  function finishVoiceSearch(form, input, q) {
    q = (q || (input && input.value) || lastVoiceText || '').trim();
    lastVoiceText = '';
    if (input && q) input.value = q;
    if (q) submitSearch(form, input);
  }

  function transcriptFromEvent(ev) {
    var text = '';
    try {
      for (var i = 0; i < ev.results.length; i++) {
        text += ev.results[i][0].transcript || '';
      }
    } catch (_) {}
    return text.trim();
  }

  function stopListening(btn, input, defaultText) {
    var ph = defaultText || placeholderDefault(input);
    listening = false;
    nativePending = false;
    setListeningUi(btn, false);
    if (input) input.setAttribute('placeholder', ph);
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

  function startWebRecognition(btn, form, input, defaultText) {
    var SR = getSpeechRecognition();
    if (!SR) return false;

    lastWebError = '';
    lastVoiceText = '';
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
      var text = transcriptFromEvent(ev);
      if (!text) return;
      lastVoiceText = text;
      input.value = text;
    };

    recognition.onerror = function (ev) {
      lastWebError = (ev && ev.error) || '';
      if (lastWebError === 'not-allowed' || lastWebError === 'service-not-allowed') {
        showPlaceholder(input, 'دسترسی میکروفون لازم است', defaultText);
      } else if (lastWebError !== 'aborted' && lastWebError !== 'no-speech') {
        showPlaceholder(input, 'خطا در تشخیص صوت', defaultText);
      }
    };

    recognition.onend = function () {
      listening = false;
      setListeningUi(btn, false);
      input.setAttribute('placeholder', defaultText);
      recognition = null;
      var blocked = lastWebError === 'not-allowed' || lastWebError === 'service-not-allowed';
      if (!blocked) finishVoiceSearch(form, input);
    };

    try {
      recognition.start();
      return true;
    } catch (_) {
      recognition = null;
      return false;
    }
  }

  function bindNativeEventHandler(defaultText) {
    window.__vinorVoiceNativeEvent = function (type, payload) {
      var cur = getTargets();
      var ph = defaultText || placeholderDefault(cur.input);
      var text = (payload || '').trim();

      if (type === 'start') {
        nativePending = false;
        listening = true;
        lastVoiceText = '';
        setListeningUi(cur.btn, true);
        if (cur.input) cur.input.setAttribute('placeholder', 'در حال گوش دادن…');
        return;
      }

      if (type === 'partial' || type === 'result') {
        if (text && cur.input) {
          lastVoiceText = text;
          cur.input.value = text;
        }
        return;
      }

      if (type === 'complete') {
        if (text && cur.input) cur.input.value = text;
        lastVoiceText = text || lastVoiceText;
        stopListening(cur.btn, cur.input, ph);
        finishVoiceSearch(cur.form, cur.input, lastVoiceText);
        return;
      }

      if (type === 'error') {
        var q = (cur.input && cur.input.value ? cur.input.value : lastVoiceText || '').trim();
        if (payload === 'not-allowed') {
          showPlaceholder(cur.input, 'دسترسی میکروفون لازم است', ph);
        } else if (payload !== 'no-speech') {
          showPlaceholder(cur.input, 'خطا در تشخیص صوت', ph);
        }
        stopListening(cur.btn, cur.input, ph);
        if (q && payload === 'no-speech') finishVoiceSearch(cur.form, cur.input, q);
        return;
      }

      if (type === 'end') {
        stopListening(cur.btn, cur.input, ph);
        window.setTimeout(function () {
          finishVoiceSearch(cur.form, cur.input);
        }, 0);
      }
    };
  }

  function startNativeRecognition(btn, form, input, defaultText) {
    var bridge = nativeBridge();
    if (!bridge) return false;

    useNative = true;
    nativePending = true;
    lastVoiceText = '';
    bindNativeEventHandler(defaultText);
    input.setAttribute('placeholder', 'در حال آماده‌سازی…');

    try {
      bridge.startNative();
      return true;
    } catch (_) {
      useNative = false;
      nativePending = false;
      listening = false;
      setListeningUi(btn, false);
      input.setAttribute('placeholder', defaultText);
      return false;
    }
  }

  function startVoiceRecognition(btn, form, input, defaultText) {
    if (isVinorNativeApp() && nativeVoiceAvailable()) {
      if (startNativeRecognition(btn, form, input, defaultText)) return;
    }

    if (getSpeechRecognition()) {
      ensureMicPermission(function (ok) {
        if (!ok) {
          showPlaceholder(input, 'دسترسی میکروفون لازم است', defaultText);
          return;
        }
        if (startWebRecognition(btn, form, input, defaultText)) return;
        if (startNativeRecognition(btn, form, input, defaultText)) return;
        showPlaceholder(input, 'جستجوی صوتی در دسترس نیست', defaultText);
      });
      return;
    }

    if (startNativeRecognition(btn, form, input, defaultText)) return;
    showPlaceholder(input, 'جستجوی صوتی در دسترس نیست', defaultText);
  }

  function onVoiceButtonClick(e) {
    var btn = e.target && e.target.closest ? e.target.closest('#dashboardVoiceSearchBtn') : null;
    if (!btn || btn.disabled) return;

    var t = getTargets();
    if (!t.form || !t.input) return;

    e.preventDefault();
    e.stopPropagation();

    rememberPlaceholder(t.input);
    var defaultText = placeholderDefault(t.input);

    if (listening || nativePending) {
      stopListening(t.btn, t.input, defaultText);
      return;
    }

    startVoiceRecognition(t.btn, t.form, t.input, defaultText);
  }

  function refreshButtonState() {
    var t = getTargets();
    if (!t.btn) return;
    rememberPlaceholder(t.input);
    if (!canUseVoice()) {
      t.btn.disabled = true;
      t.btn.setAttribute('title', 'جستجوی صوتی در این دستگاه پشتیبانی نمی‌شود');
      t.btn.setAttribute('aria-label', 'جستجوی صوتی در این دستگاه پشتیبانی نمی‌شود');
      t.btn.classList.add('opacity-40');
      return;
    }
    t.btn.disabled = false;
    t.btn.setAttribute('title', 'جستجوی صوتی');
    t.btn.setAttribute('aria-label', 'جستجوی صوتی');
    t.btn.classList.remove('opacity-40');
    t.btn.tabIndex = 0;
  }

  function teardown() {
    var t = getTargets();
    lastVoiceText = '';
    if (listening || nativePending) {
      stopListening(t.btn, t.input, placeholderDefault(t.input));
    }
  }

  function setup() {
    refreshButtonState();
    if (!clickBound) {
      clickBound = true;
      document.addEventListener('click', onVoiceButtonClick, true);
    }
  }

  window.__vinorDashboardVoiceSearch = { setup: setup, teardown: teardown };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else {
    setup();
  }

  window.addEventListener('vinor:express-page-swap', function (ev) {
    if (!ev.detail || ev.detail.navKey === 'files') {
      window.setTimeout(setup, 0);
      return;
    }
    teardown();
  });

  var origTabEnter = window.__vinorDashboardOnTabEnter;
  window.__vinorDashboardOnTabEnter = function () {
    if (typeof origTabEnter === 'function') origTabEnter();
    setup();
  };
})();
