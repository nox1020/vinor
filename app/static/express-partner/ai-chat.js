/**
 * Vinor AI — چت + منوی کشویی + کارت فایل
 */
(function () {
  'use strict';

  if (typeof window.__vinorAiChatTeardown === 'function') {
    try {
      window.__vinorAiChatTeardown();
    } catch (_) {}
  }

  var form = document.getElementById('aiChatForm');
  var input = document.getElementById('aiInput');
  var list = document.getElementById('aiMessages');
  var btn = document.getElementById('aiSendBtn');
  var newChatBtn = document.getElementById('aiNewChatBtn');
  var threadInput = document.getElementById('aiActiveThreadId');
  var menuBtn = document.getElementById('aiMenuBtn');
  var sidePanel = document.getElementById('aiSidePanel');
  var sideBackdrop = document.getElementById('aiSideBackdrop');
  var sideClose = document.getElementById('aiSideClose');
  var historyList = document.getElementById('aiHistoryList');
  var composer = document.getElementById('aiChatForm');

  if (!form || !input || !list || !btn) return;

  var mode = form.getAttribute('data-mode') || '';
  var embedded = mode === 'embedded';
  var homeLayer = mode === 'home-layer';
  var homeInline = mode === 'home-inline';
  var layerGated = embedded || homeLayer || homeInline;
  var sheetOpen =
    !layerGated ||
    document.documentElement.classList.contains('vinor-ai-open') ||
    document.documentElement.classList.contains('vinor-ai-sheet-open');
  /* خانه: چت همیشه بخشی از داشبورد است — poll همیشه فعال */
  if (homeInline) {
    sheetOpen = true;
  }
  var chatUrl = form.getAttribute('data-chat-url') || '';
  var historyUrl = form.getAttribute('data-history-url') || '';
  var clearUrl = form.getAttribute('data-clear-url') || '';
  var switchUrl = form.getAttribute('data-switch-url') || '';
  var deleteUrl = form.getAttribute('data-delete-url') || '';
  var syncUrl = form.getAttribute('data-sync-url') || '';
  var agentConfirmUrl = form.getAttribute('data-agent-confirm-url') || '';
  var agentCancelUrl = form.getAttribute('data-agent-cancel-url') || '';
  var postchiThreadId = form.getAttribute('data-postchi-thread-id') || '__postchi__';
  var postchiMessagesUrl = form.getAttribute('data-postchi-messages-url') || '';
  var postchiSendUrl = form.getAttribute('data-postchi-send-url') || '';
  var postchiOpenUrl = form.getAttribute('data-postchi-open-url') || '';
  var menuUnreadDot = document.getElementById('aiMenuUnreadDot');
  var welcome = list.getAttribute('data-welcome') || 'سلام، چطور می‌تونم کمکتون کنم؟';
  var historyAbort = null;
  var switchAbort = null;
  var syncAbort = null;
  var chatAbort = null;
  var deleteAbort = null;
  var historyTimer = null;
  var pollTimer = null;
  var lastThreadsKey = '';
  var lastSyncAt = '';
  var seenEscalationIds = {};
  var emptyPollStreak = 0;
  var pollPaused = layerGated && !sheetOpen;
  var pendingChipIntent = '';
  var submitting = false;
  var lastSubmitAt = 0;
  var seenHiddenMsgKeys = {};
  var guestRepliesRemaining = null;
  try {
    var remRaw = form.getAttribute('data-guest-replies-remaining');
    if (remRaw !== null && remRaw !== '') {
      guestRepliesRemaining = Math.max(0, parseInt(remRaw, 10) || 0);
    }
  } catch (_) {}

  function takePendingChipIntent() {
    var fromForm = '';
    try {
      fromForm = (form.getAttribute('data-pending-intent') || '').trim();
      form.removeAttribute('data-pending-intent');
    } catch (_) {}
    var intent = fromForm || pendingChipIntent || '';
    pendingChipIntent = '';
    return intent;
  }

  function takeSilentUserFlag() {
    var silent = false;
    try {
      silent = form.getAttribute('data-silent-user') === '1';
      form.removeAttribute('data-silent-user');
    } catch (_) {}
    return silent;
  }

  function takeSilentMessage() {
    var msg = '';
    try {
      msg = (form.getAttribute('data-silent-message') || '').trim();
      form.removeAttribute('data-silent-message');
    } catch (_) {}
    return msg;
  }

  function submitSilentPrompt(prompt, intent) {
    prompt = (prompt || '').trim();
    if (!prompt) return;
    var liveForm = document.getElementById('aiChatForm');
    var liveInput = document.getElementById('aiInput');
    if (!liveForm) return;
    intent = (intent || '').trim();
    try {
      liveForm.setAttribute('data-silent-user', '1');
      liveForm.setAttribute('data-silent-message', prompt);
      if (intent) liveForm.setAttribute('data-pending-intent', intent);
      else liveForm.removeAttribute('data-pending-intent');
    } catch (_) {}
    try {
      if (liveInput) {
        liveInput.value = '';
        liveInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
    } catch (_) {}
    try {
      var scroll = document.getElementById('vnHomeScroll');
      if (scroll) scroll.scrollTop = scroll.scrollHeight;
    } catch (_) {}
    setTimeout(function () {
      try {
        if (typeof liveForm.requestSubmit === 'function') liveForm.requestSubmit();
        else liveForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      } catch (_) {}
    }, 40);
  }

  function hideChipBar() {
    var bar = form.querySelector('[data-ai-chip-bar]');
    if (bar) bar.setAttribute('hidden', 'hidden');
  }

  function showChipBar() {
    var bar = form.querySelector('[data-ai-chip-bar]');
    if (bar) bar.removeAttribute('hidden');
  }

  function syncChipBarVisibility() {
    try {
      if (list && list.querySelector('.ai-msg-wrap[data-role="user"]')) {
        hideChipBar();
      } else {
        showChipBar();
      }
    } catch (_) {}
  }

  function isGuestAuth() {
    try {
      var m = document.querySelector('meta[name="vinor-express-auth"]');
      return ((m && m.getAttribute('content')) || '') === 'guest';
    } catch (_) {
      return false;
    }
  }

  function isGuestQuotaUser() {
    if (isGuestAuth()) return true;
    if (guestRepliesRemaining !== null) return true;
    try {
      return form.hasAttribute('data-guest-replies-limit');
    } catch (_) {
      return false;
    }
  }

  function noteGuestRepliesFromPayload(data) {
    if (!data || typeof data.guest_replies_remaining !== 'number') return;
    guestRepliesRemaining = Math.max(0, data.guest_replies_remaining);
    try {
      form.setAttribute('data-guest-replies-remaining', String(guestRepliesRemaining));
    } catch (_) {}
    if (guestRepliesRemaining <= 0 && isGuestQuotaUser() && input) {
      input.placeholder = 'به سقف رسیدید — برای ادامه وارد شوید…';
    }
  }

  var loginPromptActive = false;
  var loginPromptTimer = 0;

  function buildNeedLoginCardHtml(subtitle) {
    var sub = String(subtitle || '').trim();
    var subHtml = sub
      ? '<div class="ai-agent-card__body"><div class="ai-agent-line">' + escapeHtml(sub) + '</div></div>'
      : '';
    return (
      '<div class="ai-agent-card" data-agent-type="need_login">' +
      '<div class="ai-agent-card__title">ورود لازم است</div>' +
      subHtml +
      '<div class="ai-agent-card__actions">' +
      '<button type="button" class="ai-agent-btn ai-agent-btn--confirm" data-agent-login>ورود</button>' +
      '</div></div>'
    );
  }

  function openGuestLoginDrawer(hint) {
    loginPromptActive = true;
    var hintText = hint || 'به سقف ۲۰ پاسخ رسیدید. برای ادامه وارد شوید.';
    try {
      if (typeof window.vinorDrawerOpenLogin === 'function') {
        window.vinorDrawerOpenLogin({ hint: hintText });
        return true;
      }
      if (
        window.vinorProfileDrawer &&
        typeof window.vinorProfileDrawer.openLogin === 'function'
      ) {
        window.vinorProfileDrawer.openLogin({ hint: hintText });
        return true;
      }
      if (window.vinorProfileDrawer && typeof window.vinorProfileDrawer.open === 'function') {
        window.vinorProfileDrawer.open();
        return true;
      }
    } catch (_) {}
    try {
      window.location.assign('/express/partner/home?menu=1');
    } catch (_) {}
    return false;
  }

  function promptGuestLoginLimit(message) {
    var msg =
      message ||
      'به سقف ۲۰ پاسخ رسیدید. برای ادامه وارد شوید.';
    guestRepliesRemaining = 0;
    try {
      form.setAttribute('data-guest-replies-remaining', '0');
    } catch (_) {}

    /* کامپوزر را باز بگذار تا دکمه ارسال برای بازکردن مجدد ورود فعال بماند */
    unlockComposer({
      placeholder: 'به سقف رسیدید — برای ادامه وارد شوید…',
    });

    try {
      list.querySelectorAll('.ai-msg-wrap[data-guest-limit-hint="1"]').forEach(function (w) {
        try { w.remove(); } catch (_) {}
      });
    } catch (_) {}

    var wrap = appendMessage({
      role: 'assistant',
      content: msg,
      cards_html: buildNeedLoginCardHtml(msg),
    });
    if (wrap) {
      try { wrap.setAttribute('data-guest-limit-hint', '1'); } catch (_) {}
    }

    if (loginPromptTimer) {
      try { window.clearTimeout(loginPromptTimer); } catch (_) {}
      loginPromptTimer = 0;
    }
    openGuestLoginDrawer(msg);
    loginPromptTimer = window.setTimeout(function () {
      openGuestLoginDrawer(msg);
    }, 160);
  }
  var POLL_MS = 15000;
  var MIN_SUBMIT_GAP_MS = 4000;
  var MIN_MSG_LEN = 1;
  var EMPTY_POLL_PAUSE = 60;
  var pollInFlight = false;
  var postchiOpened = false;
  var onVisChange = null;
  var onKeydown = null;
  var onViewportResize = null;
  var onViewportScroll = null;

  var streamToken = 0;
  var streamRaf = 0;
  var stickChatToBottom = true;
  var scrollBottomBtn = null;
  var scrollBottomBound = false;
  var scrollLatestGen = 0;

  function chatScrollEl() {
    if (homeInline) {
      return document.getElementById('vnHomeScroll') || list;
    }
    return list;
  }

  function isChatNearBottom(el, threshold) {
    if (!el) return true;
    threshold = typeof threshold === 'number' ? threshold : 96;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
  }

  function syncScrollBottomBtn() {
    var el = chatScrollEl();
    var btn = scrollBottomBtn || document.getElementById('aiScrollBottomBtn');
    if (!btn || !el) return;
    var overflow = el.scrollHeight > el.clientHeight + 48;
    var near = isChatNearBottom(el);
    stickChatToBottom = near;
    btn.hidden = !(overflow && !near);
  }

  function ensureScrollBottomBtn() {
    var existing = document.getElementById('aiScrollBottomBtn');
    if (existing) {
      scrollBottomBtn = existing;
      return existing;
    }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'aiScrollBottomBtn';
    btn.className = 'ai-scroll-bottom';
    btn.setAttribute('aria-label', 'رفتن به پایین گفتگو');
    btn.hidden = true;
    btn.innerHTML =
      '<svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
      '<path d="M9.335 13.335c.188.187.443.293.709.293s.521-.106.709-.293l5-5c.388-.388.388-1.025 0-1.413s-1.025-.388-1.413 0L10.044 11.218 5.748 6.922c-.388-.388-1.026-.388-1.413 0s-.388 1.025 0 1.413l5 5z"/>' +
      '</svg>';
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      stickChatToBottom = true;
      scrollChatToEnd({ force: true, smooth: true });
      btn.hidden = true;
    });
    var host = null;
    if (homeInline) {
      host = document.querySelector('#homeDashboardPage .vn-home-shell') || document.getElementById('homeDashboardPage');
    } else {
      host = document.getElementById('aiChat') || (form && form.parentElement);
    }
    if (!host) return null;
    try {
      if (window.getComputedStyle(host).position === 'static') {
        host.style.position = 'relative';
      }
    } catch (_) {}
    host.appendChild(btn);
    scrollBottomBtn = btn;
    return btn;
  }

  function bindChatScrollBottom() {
    ensureScrollBottomBtn();
    var el = chatScrollEl();
    if (!el || scrollBottomBound) {
      syncScrollBottomBtn();
      return;
    }
    scrollBottomBound = true;
    el.addEventListener(
      'scroll',
      function () {
        syncScrollBottomBtn();
      },
      { passive: true }
    );
    window.addEventListener(
      'resize',
      function () {
        syncScrollBottomBtn();
      },
      { passive: true }
    );
    syncScrollBottomBtn();
  }

  function scrollChatToEnd(opts) {
    opts = opts || {};
    var force = !!opts.force;
    var smooth = !!opts.smooth;
    if (!force && !stickChatToBottom) {
      syncScrollBottomBtn();
      return;
    }
    var el = null;
    if (homeInline) {
      el = document.getElementById('vnHomeScroll');
    }
    if (!el) el = list;
    if (!el) return;
    try {
      if (smooth && typeof el.scrollTo === 'function') {
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      } else {
        el.scrollTop = el.scrollHeight;
      }
    } catch (_) {
      try {
        el.scrollTop = el.scrollHeight;
      } catch (__) {}
    }
    stickChatToBottom = true;
    syncScrollBottomBtn();
  }

  /* بدو ورود / تعویض ترد: همیشه آخرین پیام — چند تلاش برای layout دیرگاه */
  function scrollChatToLatest(opts) {
    opts = opts || {};
    var gen = ++scrollLatestGen;
    stickChatToBottom = true;
    function go() {
      if (gen !== scrollLatestGen) return;
      stickChatToBottom = true;
      scrollChatToEnd({ force: true, smooth: !!opts.smooth });
    }
    go();
    try {
      requestAnimationFrame(function () {
        go();
        requestAnimationFrame(go);
      });
    } catch (_) {}
    [40, 120, 280, 520].forEach(function (ms) {
      setTimeout(go, ms);
    });
    if (typeof ResizeObserver === 'undefined') return;
    var watch = chatScrollEl();
    if (!watch) return;
    var ro = null;
    try {
      ro = new ResizeObserver(function () {
        if (gen !== scrollLatestGen) {
          try {
            if (ro) ro.disconnect();
          } catch (_) {}
          return;
        }
        go();
      });
      ro.observe(watch);
      if (list && list !== watch) ro.observe(list);
    } catch (_) {
      return;
    }
    setTimeout(function () {
      try {
        if (ro) ro.disconnect();
      } catch (_) {}
    }, 1400);
  }

  function cancelTypewriter() {
    streamToken += 1;
    if (streamRaf) {
      try {
        window.cancelAnimationFrame(streamRaf);
      } catch (_) {}
      streamRaf = 0;
    }
    try {
      list.querySelectorAll('.ai-msg-wrap[data-streaming="1"]').forEach(function (w) {
        w.removeAttribute('data-streaming');
      });
    } catch (_) {}
  }

  function streamChunkSize(total, index) {
    /* شروع آرام کاراکتری، بعد کمی سریع‌تر مثل GPT */
    if (total <= 80) return 1;
    if (index < 24) return 1;
    if (index < 120) return 2;
    if (total > 900) return 5;
    return 3;
  }

  function typewriteAssistantMessage(msg) {
    if (!msg || (msg.role || 'assistant') === 'user') {
      return Promise.resolve(appendMessage(msg));
    }
    if (messageSeen(msg)) return Promise.resolve(null);

    var text = (msg.content || '').trim();
    /* land_cards را موقع پایان تایپ اعمال کن تا آرایش نوار با جواب هم‌زمان عوض شود */
    var cardsHtml = buildCardsHtml(msg, { skipLands: true });
    var hasLands =
      (msg.land_cards && msg.land_cards.length) ||
      (msg.cards_html && /ai-land-cards/.test(String(msg.cards_html)));
    if (!text && !cardsHtml && !hasLands) return Promise.resolve(null);

    cancelTypewriter();
    removeThinking();
    removeWelcome();

    /* اسکلت پیام را بساز؛ متن را تدریجی پر کن */
    var wrap = appendMessage(
      {
        role: 'assistant',
        content: '',
        created_at: msg.created_at,
        escalation_id: msg.escalation_id,
        source: msg.source,
      },
      { streamShell: true }
    );
    if (!wrap) {
      return Promise.resolve(appendMessage(msg));
    }

    wrap.setAttribute('data-streaming', '1');
    var bubble = wrap.querySelector('.ai-msg-bubble');
    if (!bubble) {
      wrap.removeAttribute('data-streaming');
      return Promise.resolve(wrap);
    }
    bubble.textContent = '';
    bubble.removeAttribute('data-formatted');

    var myToken = streamToken;
    var i = 0;

    return new Promise(function (resolve) {
      function finish() {
        if (myToken !== streamToken) {
          resolve(wrap);
          return;
        }
        wrap.removeAttribute('data-streaming');
        if (text) {
          bubble.innerHTML = formatAssistantHtml(text);
          bubble.setAttribute('data-formatted', '1');
        }
        if (cardsHtml) {
          var body = wrap.querySelector('.ai-msg-body');
          if (body && !body.querySelector('.ai-msg-cards')) {
            var cardsWrap = document.createElement('div');
            cardsWrap.innerHTML = cardsHtml;
            var cardsEl = cardsWrap.firstElementChild;
            if (cardsEl) {
              if (!cardsEl.classList.contains('ai-msg-cards')) {
                var cardsHost = document.createElement('div');
                cardsHost.className = 'ai-msg-cards';
                cardsHost.appendChild(cardsEl);
                body.appendChild(cardsHost);
              } else {
                body.appendChild(cardsEl);
              }
              initCardsIn(body);
            }
          }
        }
        routeLandCardsToHome(msg);
        if (msg.cards_html) {
          var strippedLands = stripLandCardsFromHtml(msg.cards_html);
          if (strippedLands.landCards.length) {
            try {
              if (typeof window.vinorApplyHomeLandCards === 'function') {
                window.vinorApplyHomeLandCards(strippedLands.landCards, {
                  label: 'پیشنهاد فایل',
                });
              }
            } catch (_) {}
          }
        }
        wireCopyBlocks(wrap);
        ensureMsgActions(wrap);
        scrollChatToEnd();
        resolve(wrap);
      }

      function step() {
        if (myToken !== streamToken) {
          resolve(wrap);
          return;
        }
        if (!text) {
          finish();
          return;
        }
        var n = streamChunkSize(text.length, i);
        i = Math.min(text.length, i + n);
        bubble.textContent = text.slice(0, i);
        scrollChatToEnd();
        if (i >= text.length) {
          streamRaf = 0;
          finish();
          return;
        }
        streamRaf = window.requestAnimationFrame(step);
      }

      streamRaf = window.requestAnimationFrame(step);
    });
  }

  function reconcileExchange(serverMessages, opts) {
    opts = opts || {};
    var msgs = serverMessages || [];
    var lastUser = null;
    var lastAsst = null;
    var routedLands = false;
    for (var i = msgs.length - 1; i >= 0; i--) {
      var m = msgs[i];
      if (!m || !m.role) continue;
      if (!routedLands && m.role === 'assistant' && m.land_cards && m.land_cards.length) {
        /* با استریم: آرایش نوار را بعد از اتمام تایپ جواب عوض کن */
        if (!opts.stream) routeLandCardsToHome(m);
        routedLands = true;
      }
      if (!lastAsst && m.role === 'assistant' && messageHasContent(m)) lastAsst = m;
      if (!lastUser && m.role === 'user' && messageHasContent(m)) lastUser = m;
      if (lastUser && lastAsst && routedLands) break;
      if (lastUser && lastAsst && i < msgs.length - 8) break;
    }

    var pending = list.querySelector('.ai-msg-wrap[data-pending-user="1"]');
    if (pending) {
      if (lastUser && lastUser.created_at) {
        pending.removeAttribute('data-pending-user');
        pending.setAttribute('data-created-at', lastUser.created_at);
        bumpLastSyncAt(lastUser.created_at);
      } else {
        pending.remove();
      }
    }

    if (lastAsst) {
      if (opts.stream) return typewriteAssistantMessage(lastAsst);
      appendMessage(lastAsst);
    }
    scanLastSyncFromDom();
    scrollChatToEnd();
    return Promise.resolve(null);
  }

  window.__vinorAiChatSetSheetOpen = function (open) {
    if (homeInline) {
      sheetOpen = true;
      resumePoll();
      return;
    }
    sheetOpen = !!open;
    if (!layerGated) return;
    if (sheetOpen) {
      resumePoll();
      try {
        scrollChatToLatest();
      } catch (_) {}
    } else {
      pollPaused = true;
    }
  };

  function activeThreadId() {
    return (threadInput && threadInput.value) || '';
  }

  function isPostchiMode() {
    return activeThreadId() === postchiThreadId;
  }

  function setActiveThreadId(id) {
    if (threadInput) threadInput.value = id || '';
    setComposerMode(isPostchiMode());
    if (isPostchiMode()) {
      pollPaused = true;
    } else {
      resumePoll();
    }
  }

  function syncComposerReady() {
    if (!form || !input || !btn) return;
    if (
      submitting ||
      form.classList.contains('ai-composer--readonly') ||
      input.disabled
    ) {
      form.classList.remove('ai-composer--ready');
      btn.disabled = true;
      btn.setAttribute('aria-disabled', 'true');
      return;
    }
    var len = (input.value || '').trim().length;
    var canSend = len >= MIN_MSG_LEN;
    /* ready فقط برای type-hint؛ دکمه ارسال همیشه دیده می‌شود و با aria-disabled غیرفعال می‌شود */
    form.classList.toggle('ai-composer--ready', len >= 1);
    /* disabled واقعی فقط در busy/readonly — خالی بودن با aria-disabled */
    btn.disabled = false;
    btn.setAttribute('aria-disabled', canSend ? 'false' : 'true');
  }

  function unlockComposer(opts) {
    opts = opts || {};
    submitting = false;
    try {
      form.classList.remove('ai-composer--readonly');
    } catch (_) {}
    if (input) {
      input.disabled = false;
      input.removeAttribute('aria-disabled');
      if (opts.placeholder) {
        stopTypeHintPlaceholder({ dismiss: false, placeholder: opts.placeholder });
      } else {
        startTypeHintPlaceholder();
      }
    }
    if (btn) btn.removeAttribute('aria-disabled');
    syncComposerReady();
  }

  function autoGrowInput() {
    if (!input) return;
    input.style.height = 'auto';
    var next = Math.min(input.scrollHeight, 152);
    input.style.height = Math.max(24, next) + 'px';
  }

  var TYPE_HINT_PHRASES = [
    'زمین ویلایی تو گرمابسرد دماوند می‌خوام',
    'دشت اول گرمابسرد، حدود ۵۰۰ متری نشون بده',
    'بودجه‌ام برای گرمابسرد حدود ۲ میلیارد تومانه',
  ];
  var typeHintTimer = 0;
  var typeHintDismissed = false;
  var typeHintRunning = false;
  var typeHintGen = 0;
  var typeHintHost = form.querySelector('[data-ai-type-hint]');
  var typeHintClip = typeHintHost
    ? typeHintHost.querySelector('.ai-composer__type-hint-clip')
    : null;
  var typeHintTextEl = typeHintHost
    ? typeHintHost.querySelector('[data-ai-type-hint-text]')
    : null;

  function clearTypeHintTimer() {
    if (typeHintTimer) {
      clearTimeout(typeHintTimer);
      typeHintTimer = 0;
    }
  }

  function staticComposerPlaceholder() {
    if (
      isGuestQuotaUser() &&
      guestRepliesRemaining !== null &&
      guestRepliesRemaining <= 0
    ) {
      return 'به سقف رسیدید — برای ادامه وارد شوید…';
    }
    return 'از وینور AI بپرسید…';
  }

  function hideTypeHintOverlay() {
    if (typeHintHost) typeHintHost.hidden = true;
    if (typeHintTextEl) {
      typeHintTextEl.textContent = '';
      typeHintTextEl.style.transform = '';
    }
  }

  function showTypeHintOverlay() {
    if (typeHintHost) typeHintHost.hidden = false;
  }

  /** پدینگ راهنما = دقیقاً محدودهٔ textarea (مهم برای موبایل) */
  function syncTypeHintGeometry() {
    if (!typeHintHost || !input) return;
    var shell = input.closest('.ai-composer__shell');
    if (!shell) return;
    var sr = shell.getBoundingClientRect();
    var ir = input.getBoundingClientRect();
    if (!sr.width || !ir.width) return;
    typeHintHost.style.paddingLeft = Math.max(0, ir.left - sr.left) + 'px';
    typeHintHost.style.paddingRight = Math.max(0, sr.right - ir.right) + 'px';
    typeHintHost.style.paddingTop = Math.max(0, ir.top - sr.top) + 'px';
    typeHintHost.style.paddingBottom = Math.max(0, sr.bottom - ir.bottom) + 'px';
  }

  /** متن در یک خط؛ سرریز به چپ شیفت می‌شود تا انتهای تایپ دیده شود */
  function renderTypeHintVisible(full) {
    if (!typeHintTextEl || !typeHintClip) {
      if (input) input.placeholder = full || '';
      return;
    }
    showTypeHintOverlay();
    if (input) input.placeholder = '';
    var text = full || '';
    typeHintTextEl.style.transform = 'translateX(0)';
    typeHintTextEl.textContent = text;
    if (!text) return;

    function applyShift() {
      if (!typeHintTextEl || !typeHintClip) return;
      syncTypeHintGeometry();
      var maxW = typeHintClip.clientWidth;
      if (maxW < 12 && input) {
        maxW = Math.max(12, Math.floor(input.getBoundingClientRect().width) - 4);
      }
      var need = typeHintTextEl.scrollWidth || typeHintTextEl.offsetWidth || 0;
      var dx = Math.max(0, need - maxW);
      typeHintTextEl.style.transform = dx > 0 ? 'translateX(' + -dx + 'px)' : 'translateX(0)';
    }

    applyShift();
    requestAnimationFrame(function () {
      applyShift();
      requestAnimationFrame(applyShift);
    });
  }

  function stopTypeHintPlaceholder(opts) {
    opts = opts || {};
    clearTypeHintTimer();
    typeHintRunning = false;
    typeHintGen += 1;
    if (opts.dismiss) typeHintDismissed = true;
    hideTypeHintOverlay();
    if (!input) return;
    if (opts.placeholder != null) {
      input.placeholder = opts.placeholder;
      return;
    }
    if (!(input.value || '').length) {
      input.placeholder = typeHintDismissed ? staticComposerPlaceholder() : '';
    }
  }

  function canRunTypeHint() {
    if (!input || typeHintDismissed) return false;
    if (isPostchiMode()) return false;
    if (form.classList.contains('ai-composer--readonly')) return false;
    if (input.disabled) return false;
    if ((input.value || '').length > 0) return false;
    if (
      isGuestQuotaUser() &&
      guestRepliesRemaining !== null &&
      guestRepliesRemaining <= 0
    ) {
      return false;
    }
    return true;
  }

  function startTypeHintPlaceholder() {
    if (!canRunTypeHint()) {
      if (input && !(input.value || '').length && typeHintDismissed) {
        hideTypeHintOverlay();
        input.placeholder = staticComposerPlaceholder();
      }
      return;
    }
    if (typeHintRunning) return;
    typeHintRunning = true;
    var gen = ++typeHintGen;
    var phraseIdx = 0;

    function schedule(fn, ms) {
      clearTypeHintTimer();
      typeHintTimer = setTimeout(fn, ms);
    }

    function erase(text, i) {
      if (gen !== typeHintGen || !canRunTypeHint()) {
        typeHintRunning = false;
        return;
      }
      if (i < 0) {
        schedule(function () {
          phraseIdx = (phraseIdx + 1) % TYPE_HINT_PHRASES.length;
          typePhrase(TYPE_HINT_PHRASES[phraseIdx], 0);
        }, 400);
        return;
      }
      renderTypeHintVisible(text.slice(0, i));
      schedule(function () {
        erase(text, i - 1);
      }, 20);
    }

    function typePhrase(text, i) {
      if (gen !== typeHintGen || !canRunTypeHint()) {
        typeHintRunning = false;
        return;
      }
      if (i > text.length) {
        schedule(function () {
          erase(text, text.length);
        }, 1600);
        return;
      }
      renderTypeHintVisible(text.slice(0, i));
      schedule(function () {
        typePhrase(text, i + 1);
      }, i === 0 ? 260 : 46);
    }

    if (input) input.placeholder = '';
    showTypeHintOverlay();
    renderTypeHintVisible('');
    typePhrase(TYPE_HINT_PHRASES[phraseIdx], 0);
  }

  function setComposerMode(postchi) {
    if (!input) return;
    if (postchi) {
      input.value = '';
      stopTypeHintPlaceholder({ dismiss: false, placeholder: 'ارسال در پستچی غیرفعال است' });
      input.disabled = true;
      input.setAttribute('aria-disabled', 'true');
      if (btn) {
        btn.disabled = true;
        btn.setAttribute('aria-disabled', 'true');
      }
      form.classList.add('ai-composer--readonly');
      form.classList.remove('ai-composer--ready');
      autoGrowInput();
    } else {
      input.disabled = false;
      input.removeAttribute('aria-disabled');
      if (btn) btn.removeAttribute('aria-disabled');
      form.classList.remove('ai-composer--readonly');
      if (
        isGuestQuotaUser() &&
        guestRepliesRemaining !== null &&
        guestRepliesRemaining <= 0
      ) {
        stopTypeHintPlaceholder({
          dismiss: false,
          placeholder: 'به سقف رسیدید — برای ادامه وارد شوید…',
        });
      } else {
        startTypeHintPlaceholder();
      }
      syncComposerReady();
      autoGrowInput();
    }
  }

  function setBusy(on) {
    if (isPostchiMode()) {
      if (btn) btn.disabled = true;
      if (input) input.disabled = true;
      if (newChatBtn) newChatBtn.disabled = !!on;
      return;
    }
    if (on) {
      btn.disabled = true;
      input.disabled = true;
      form.classList.remove('ai-composer--ready');
    } else {
      unlockComposer();
    }
    if (newChatBtn) newChatBtn.disabled = !!on;
  }

  function syncMenuUnreadBadge(unread) {
    if (!menuUnreadDot) return;
    var n = Number(unread || 0);
    if (n > 0) {
      menuUnreadDot.classList.remove('hidden');
    } else {
      menuUnreadDot.classList.add('hidden');
    }
  }

  function updatePostchiUnreadFromThreads(threads) {
    if (!threads || !threads.length) return;
    for (var i = 0; i < threads.length; i++) {
      var th = threads[i];
      if (th && (th.kind === 'postchi' || th.id === postchiThreadId)) {
        syncMenuUnreadBadge(th.unread || 0);
        return;
      }
    }
  }

  function csrfToken() {
    var el = form.querySelector('input[name="csrf_token"]');
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]+)/);
    if (!m) return '';
    try {
      return decodeURIComponent(m[1]);
    } catch (_) {
      return m[1];
    }
  }

  function apiHeaders(json) {
    var h = { Accept: 'application/json' };
    if (json) h['Content-Type'] = 'application/json';
    var t = csrfToken();
    if (t) h['X-CSRFToken'] = t;
    return h;
  }

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function copyBlockLabel(info, beforeText) {
    var s = String(info || '').trim();
    var low = s.toLowerCase();
    var before = String(beforeText || '');
    if (/دیوار|divar/.test(low) || /متن\s*دیوار|آگهی\s*دیوار/.test(before)) return 'متن دیوار';
    if (/اینستا|insta|instagram/.test(low) || /کپشن|اینستا/.test(before)) return 'کپشن اینستا';
    if (/دیوار/.test(before)) return 'متن دیوار';
    if (s) return s.replace(/^\*+|\*+$/g, '').trim().slice(0, 40) || 'متن';
    return 'متن';
  }

  function copyBtnIconsHtml() {
    return (
      '<svg class="ai-copy-block__icon-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<rect x="9" y="9" width="13" height="13" rx="2"></rect>' +
      '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>' +
      '</svg>' +
      '<svg class="ai-copy-block__icon-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M20 6L9 17l-5-5"></path>' +
      '</svg>'
    );
  }

  function buildCopyBlockHtml(label, text) {
    return (
      '<div class="ai-copy-block" data-ai-copy-block>' +
      '<div class="ai-copy-block__bar">' +
      '<span class="ai-copy-block__label">' +
      escapeHtml(label || 'متن') +
      '</span>' +
      '<button type="button" class="ai-copy-block__btn" data-ai-copy aria-label="کپی متن">' +
      copyBtnIconsHtml() +
      '</button></div>' +
      '<pre class="ai-copy-block__pre" data-ai-copy-text>' +
      escapeHtml(text || '') +
      '</pre></div>'
    );
  }

  function formatAssistantHtml(text) {
    var raw = String(text || '');
    if (!raw) return '';
    var fenceRe = /```([^\n`]*)\n([\s\S]*?)```/g;
    var html = '';
    var last = 0;
    var m;
    var hasFence = false;
    while ((m = fenceRe.exec(raw)) !== null) {
      hasFence = true;
      var before = raw.slice(last, m.index);
      var beforeTrim = before.trim();
      // عنوان درست قبل از بلاک را از prose جدا کن
      var labelHint = beforeTrim;
      var proseKeep = beforeTrim;
      var titleMatch = beforeTrim.match(/(?:^|\n)(?:\*\*)?(متن دیوار|کپشن اینستا|متن آگهی دیوار|آگهی دیوار)(?:\*\*)?\s*:?\s*$/i);
      if (titleMatch) {
        labelHint = titleMatch[1];
        proseKeep = beforeTrim.slice(0, titleMatch.index).trim();
      }
      if (proseKeep) {
        html += '<div class="ai-msg-prose">' + escapeHtml(proseKeep) + '</div>';
      }
      html +=
        '<div class="ai-copy-blocks">' +
        buildCopyBlockHtml(
          copyBlockLabel(m[1], labelHint),
          String(m[2] || '').replace(/\s+$/, '')
        ) +
        '</div>';
      last = m.index + m[0].length;
    }
    var after = raw.slice(last).trim();
    if (after) {
      html += '<div class="ai-msg-prose">' + escapeHtml(after) + '</div>';
    }
    if (!hasFence) {
      return '<div class="ai-msg-prose">' + escapeHtml(raw) + '</div>';
    }
    return html;
  }

  function copyTextToClipboard(text) {
    text = String(text || '');
    if (!text) return Promise.resolve(false);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(
        function () {
          return true;
        },
        function () {
          return false;
        }
      );
    }
    return new Promise(function (resolve) {
      try {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        var ok = document.execCommand('copy');
        document.body.removeChild(ta);
        resolve(!!ok);
      } catch (_) {
        resolve(false);
      }
    });
  }

  function wireCopyBlocks(root) {
    var scope = root || list;
    if (!scope) return;
    scope.querySelectorAll('[data-ai-copy]').forEach(function (btn) {
      if (btn.getAttribute('data-wired') === '1') return;
      btn.setAttribute('data-wired', '1');
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var block = btn.closest('[data-ai-copy-block]');
        var pre = block && block.querySelector('[data-ai-copy-text]');
        var text = pre ? pre.textContent || '' : '';
        copyTextToClipboard(text).then(function (ok) {
          if (!ok) return;
          btn.classList.add('is-copied');
          btn.setAttribute('aria-label', 'کپی شد');
          setTimeout(function () {
            btn.classList.remove('is-copied');
            btn.setAttribute('aria-label', 'کپی متن');
          }, 1600);
        });
      });
    });
  }

  var speakingBtn = null;
  var speakUtterance = null;

  function assistantPlainText(wrap) {
    if (!wrap) return '';
    var bubble = wrap.querySelector('.ai-msg-bubble:not(.ai-msg-thinking)');
    if (!bubble) return '';
    var clone = bubble.cloneNode(true);
    clone.querySelectorAll('.ai-copy-blocks, .ai-agent-actions, .ai-agent-card, pre, script, style').forEach(function (el) {
      try { el.remove(); } catch (_) {}
    });
    return String(clone.textContent || '').replace(/\s+\n/g, '\n').trim();
  }

  function closeAllMsgMenus(except) {
    list.querySelectorAll('[data-ai-msg-menu].is-open').forEach(function (menu) {
      if (except && menu === except) return;
      menu.classList.remove('is-open');
      var host = menu.closest('.ai-msg-action-wrap');
      var btn = host && host.querySelector('[data-ai-msg-more]');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
  }

  function flashActionOk(btn) {
    if (!btn) return;
    btn.classList.add('is-ok');
    setTimeout(function () { btn.classList.remove('is-ok'); }, 1200);
  }

  function stopSpeaking() {
    try {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    } catch (_) {}
    if (speakingBtn) {
      speakingBtn.classList.remove('is-active');
      speakingBtn.setAttribute('aria-label', 'خواندن با صدا');
      speakingBtn = null;
    }
    speakUtterance = null;
  }

  function speakAssistantText(btn, text) {
    if (!text) {
      showEphemeralHint('متنی برای خواندن نیست.');
      return;
    }
    if (!window.speechSynthesis || typeof window.SpeechSynthesisUtterance !== 'function') {
      showEphemeralHint('خواندن با صدا در این مرورگر پشتیبانی نمی‌شود.');
      return;
    }
    if (speakingBtn === btn) {
      stopSpeaking();
      return;
    }
    stopSpeaking();
    var u = new SpeechSynthesisUtterance(text);
    u.lang = 'fa-IR';
    u.rate = 1;
    speakUtterance = u;
    speakingBtn = btn;
    btn.classList.add('is-active');
    btn.setAttribute('aria-label', 'توقف خواندن');
    u.onend = function () {
      if (speakingBtn === btn) {
        btn.classList.remove('is-active');
        btn.setAttribute('aria-label', 'خواندن با صدا');
        speakingBtn = null;
      }
    };
    u.onerror = function () {
      stopSpeaking();
    };
    try {
      window.speechSynthesis.speak(u);
    } catch (_) {
      stopSpeaking();
      showEphemeralHint('خواندن با صدا ممکن نشد.');
    }
  }

  function shareAssistantText(text) {
    if (!text) {
      showEphemeralHint('متنی برای اشتراک نیست.');
      return Promise.resolve(false);
    }
    if (navigator.share) {
      return navigator
        .share({ text: text, title: 'وینور' })
        .then(function () { return true; })
        .catch(function () { return false; });
    }
    return copyTextToClipboard(text).then(function (ok) {
      if (ok) showEphemeralHint('متن کپی شد — می‌توانید اشتراک بگذارید.');
      return ok;
    });
  }

  function buildMsgActionsHtml() {
    return (
      '<div class="ai-msg-actions" data-ai-msg-actions>' +
      '<div class="ai-msg-action-wrap">' +
      '<button type="button" class="ai-msg-action" data-ai-msg-more aria-label="بیشتر" aria-haspopup="true" aria-expanded="false">' +
      '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/></svg>' +
      '</button>' +
      '<div class="ai-msg-action-menu" data-ai-msg-menu role="menu">' +
      '<button type="button" data-ai-msg-menu-copy role="menuitem">کپی متن</button>' +
      '<button type="button" data-ai-msg-menu-share role="menuitem">اشتراک‌گذاری</button>' +
      '</div>' +
      '</div>' +
      '<button type="button" class="ai-msg-action" data-ai-msg-share aria-label="اشتراک‌گذاری">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="2.4"/><circle cx="6" cy="12" r="2.4"/><circle cx="18" cy="19" r="2.4"/><path d="M8.3 10.8l7.4-4.1M8.3 13.2l7.4 4.1"/></svg>' +
      '</button>' +
      '<button type="button" class="ai-msg-action" data-ai-msg-speak aria-label="خواندن با صدا">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10v4a2 2 0 0 0 2 2h2l4 3V5L7 8H5a2 2 0 0 0-2 2z"/><path d="M15.5 8.5a4.5 4.5 0 0 1 0 7"/><path d="M17.8 6a7.5 7.5 0 0 1 0 12"/></svg>' +
      '</button>' +
      '<button type="button" class="ai-msg-action" data-ai-msg-copy aria-label="کپی">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
      '</button>' +
      '</div>'
    );
  }

  function ensureMsgActions(wrap) {
    if (!wrap || wrap.getAttribute('data-role') !== 'assistant') return;
    if (wrap.getAttribute('data-thinking') === '1') return;
    if (wrap.getAttribute('data-ephemeral') === '1') return;
    var body = wrap.querySelector('.ai-msg-body');
    if (!body) return;
    if (body.querySelector('[data-ai-msg-actions]')) return;
    var bubble = body.querySelector('.ai-msg-bubble:not(.ai-msg-thinking)');
    if (!bubble) return;
    var host = document.createElement('div');
    host.innerHTML = buildMsgActionsHtml();
    var actions = host.firstElementChild;
    if (actions) body.appendChild(actions);
  }

  function wireMsgActions(root) {
    var scope = root || list;
    if (!scope) return;
    scope.querySelectorAll('.ai-msg-wrap--assistant, .ai-msg-wrap[data-role="assistant"]').forEach(function (wrap) {
      ensureMsgActions(wrap);
    });
  }

  function onMsgActionsClick(e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var wrap = t.closest('.ai-msg-wrap--assistant, .ai-msg-wrap[data-role="assistant"]');
    if (!wrap || !list.contains(wrap)) return;

    var moreBtn = t.closest('[data-ai-msg-more]');
    if (moreBtn && wrap.contains(moreBtn)) {
      e.preventDefault();
      var wrapMore = moreBtn.closest('.ai-msg-action-wrap');
      var menu = wrapMore && wrapMore.querySelector('[data-ai-msg-menu]');
      var open = menu && menu.classList.contains('is-open');
      closeAllMsgMenus();
      if (menu && !open) {
        menu.classList.add('is-open');
        moreBtn.setAttribute('aria-expanded', 'true');
      }
      return;
    }

    var menuCopy = t.closest('[data-ai-msg-menu-copy]');
    if (menuCopy) {
      e.preventDefault();
      closeAllMsgMenus();
      var textM = assistantPlainText(wrap);
      copyTextToClipboard(textM).then(function (ok) {
        if (ok) showEphemeralHint('کپی شد');
      });
      return;
    }
    var menuShare = t.closest('[data-ai-msg-menu-share]');
    if (menuShare) {
      e.preventDefault();
      closeAllMsgMenus();
      shareAssistantText(assistantPlainText(wrap));
      return;
    }

    var copyBtn = t.closest('[data-ai-msg-copy]');
    if (copyBtn && wrap.contains(copyBtn)) {
      e.preventDefault();
      closeAllMsgMenus();
      copyTextToClipboard(assistantPlainText(wrap)).then(function (ok) {
        if (ok) flashActionOk(copyBtn);
      });
      return;
    }
    var shareBtn = t.closest('[data-ai-msg-share]');
    if (shareBtn && wrap.contains(shareBtn)) {
      e.preventDefault();
      closeAllMsgMenus();
      shareAssistantText(assistantPlainText(wrap)).then(function (ok) {
        if (ok) flashActionOk(shareBtn);
      });
      return;
    }
    var speakBtn = t.closest('[data-ai-msg-speak]');
    if (speakBtn && wrap.contains(speakBtn)) {
      e.preventDefault();
      closeAllMsgMenus();
      speakAssistantText(speakBtn, assistantPlainText(wrap));
    }
  }

  function enhanceAssistantBubbles(root) {
    var scope = root || list;
    if (!scope) return;
    scope.querySelectorAll('.ai-msg-wrap--assistant .ai-msg-bubble, .ai-msg-wrap[data-role="assistant"] .ai-msg-bubble').forEach(function (bubble) {
      if (bubble.getAttribute('data-formatted') === '1') return;
      if (bubble.classList.contains('ai-msg-thinking')) return;
      if (bubble.querySelector('[data-ai-copy-block], .ai-copy-blocks, .ai-agent-card')) {
        bubble.setAttribute('data-formatted', '1');
        return;
      }
      var raw = bubble.textContent || '';
      if (raw.indexOf('```') === -1) {
        bubble.setAttribute('data-formatted', '1');
        return;
      }
      bubble.innerHTML = formatAssistantHtml(raw);
      bubble.setAttribute('data-formatted', '1');
    });
    wireCopyBlocks(scope);
    wireMsgActions(scope);
  }

  function messageHasContent(msg) {
    if (!msg) return false;
    return !!(
      (msg.content && String(msg.content).trim()) ||
      msg.cards_html ||
      msg.land_detail_html ||
      (msg.land_cards && msg.land_cards.length) ||
      (msg.agent_actions && msg.agent_actions.length)
    );
  }

  function routeLandCardsToHome(msg) {
    if (!msg) return;
    if (msg.land_cards && msg.land_cards.length) {
      try {
        if (typeof window.vinorApplyHomeLandCards === 'function') {
          window.vinorApplyHomeLandCards(msg.land_cards, { label: 'پیشنهاد فایل' });
        }
      } catch (_) {}
    }
  }

  function stripLandCardsFromHtml(html) {
    if (!html) return { clean: '', landCards: [] };
    var box = document.createElement('div');
    box.innerHTML = String(html);
    var landCards = [];
    box.querySelectorAll('.ai-land-cards').forEach(function (root) {
      root.querySelectorAll('.vinor-premium-card, .express-card').forEach(function (card) {
        var codeEl = card.closest('[data-land-code]') || card;
        var code = (codeEl.getAttribute && codeEl.getAttribute('data-land-code')) || '';
        landCards.push({ code: code, html: card.outerHTML });
      });
      try {
        root.remove();
      } catch (_) {}
    });
    return { clean: (box.innerHTML || '').trim(), landCards: landCards };
  }

  function buildCardsHtml(msg, opts) {
    opts = opts || {};
    if (!opts.skipLands) routeLandCardsToHome(msg);
    if (!msg.cards_html) return '';
    var stripped = stripLandCardsFromHtml(msg.cards_html);
    if (!opts.skipLands && stripped.landCards.length) {
      try {
        if (typeof window.vinorApplyHomeLandCards === 'function') {
          window.vinorApplyHomeLandCards(stripped.landCards, { label: 'پیشنهاد فایل' });
        }
      } catch (_) {}
    }
    if (!stripped.clean) return '';
    return '<div class="ai-msg-cards w-full min-w-0 max-w-full">' + stripped.clean + '</div>';
  }

  function scrubLandCardsFromChatDom() {
    if (!list) return;
    list.querySelectorAll('.ai-land-cards').forEach(function (root) {
      var landCards = [];
      root.querySelectorAll('.vinor-premium-card, .express-card').forEach(function (card) {
        landCards.push({ html: card.outerHTML });
      });
      if (landCards.length && typeof window.vinorApplyHomeLandCards === 'function') {
        try {
          window.vinorApplyHomeLandCards(landCards, { label: 'پیشنهاد فایل' });
        } catch (_) {}
      }
      var host = root.closest('.ai-msg-cards');
      try {
        root.remove();
      } catch (_) {}
      if (host && !host.children.length) {
        try {
          host.remove();
        } catch (_) {}
      }
    });
  }

  function initCardsIn(wrap) {
    if (!wrap) return;
    if (typeof window.vinorInitPremiumCards === 'function') {
      window.vinorInitPremiumCards(wrap, list);
    }
    bindAgentActions(wrap);
    wireCopyBlocks(wrap);
  }

  function setAgentCardState(card, status, noteText) {
    if (!card) return;
    card.setAttribute('data-agent-status', status || '');
    var actions = card.querySelector('.ai-agent-card__actions');
    if (actions) actions.remove();
    card.classList.add('ai-agent-card--done');
    var note = card.querySelector('[data-agent-note]') || card.querySelector('.ai-agent-card__note');
    if (!note) {
      note = document.createElement('div');
      note.className = 'ai-agent-card__note';
      card.appendChild(note);
    }
    note.classList.remove('hidden');
    note.textContent = noteText || '';
  }

  async function confirmAgentAction(card) {
    if (!card || !agentConfirmUrl) return;
    var token = card.getAttribute('data-token') || '';
    if (!token) return;
    var btns = card.querySelectorAll('button');
    btns.forEach(function (b) {
      b.disabled = true;
    });
    try {
      var resp = await fetch(agentConfirmUrl, {
        method: 'POST',
        headers: apiHeaders(true),
        credentials: 'same-origin',
        body: JSON.stringify({ token: token, thread_id: activeThreadId() }),
      });
      var data = null;
      try {
        data = await resp.json();
      } catch (_) {}
      if (!resp.ok || !data || !data.ok) {
        if (data && data.need_login) {
          try {
            if (window.vinorProfileDrawer && typeof window.vinorProfileDrawer.open === 'function') {
              window.vinorProfileDrawer.open();
            }
          } catch (_) {}
        }
        throw new Error((data && data.error) || 'ثبت اقدام ممکن نشد.');
      }
      setAgentCardState(card, 'confirmed', data.message || 'ثبت شد.');
      if (data.thread_id) setActiveThreadId(data.thread_id);
      if (data.messages && data.messages.length) {
        reconcileExchange(data.messages);
      } else if (data.message) {
        appendMessage({
          role: 'assistant',
          content: data.message,
          created_at: new Date().toISOString(),
        });
      }
    } catch (err) {
      btns.forEach(function (b) {
        b.disabled = false;
      });
      showEphemeralHint(String((err && err.message) || 'خطا در تأیید'));
    }
  }

  async function cancelAgentAction(card) {
    if (!card) return;
    var token = card.getAttribute('data-token') || '';
    if (token && agentCancelUrl) {
      try {
        await fetch(agentCancelUrl, {
          method: 'POST',
          headers: apiHeaders(true),
          credentials: 'same-origin',
          body: JSON.stringify({ token: token }),
        });
      } catch (_) {}
    }
    setAgentCardState(card, 'cancelled', 'انصراف داده شد.');
  }

  function bindAgentActions(root) {
    if (!root) return;
    root.querySelectorAll('.ai-agent-card[data-agent-type]').forEach(function (card) {
      var atype = card.getAttribute('data-agent-type') || '';
      if (card.getAttribute('data-bound') === '1') return;
      if (atype === 'need_login') {
        card.setAttribute('data-bound', '1');
        var loginBtn = card.querySelector('[data-agent-login]');
        if (loginBtn) {
          loginBtn.addEventListener('click', function (e) {
            e.preventDefault();
            openGuestLoginDrawer('برای ادامه وارد شوید.');
          });
        }
        return;
      }
      if (atype === 'next_action') {
        card.setAttribute('data-bound', '1');
        var chatBtn = card.querySelector('[data-agent-chat-prompt]');
        if (chatBtn) {
          chatBtn.addEventListener('click', function (e) {
            e.preventDefault();
            var prompt = chatBtn.getAttribute('data-agent-chat-prompt') || '';
            var intent = chatBtn.getAttribute('data-agent-chat-intent') || '';
            if (!prompt) return;
            submitSilentPrompt(prompt, intent);
          });
        }
        return;
      }
      if (atype.indexOf('confirm_') !== 0) return;
      card.setAttribute('data-bound', '1');
      var confirmBtn = card.querySelector('[data-agent-confirm]');
      var cancelBtn = card.querySelector('[data-agent-cancel]');
      if (confirmBtn) {
        confirmBtn.addEventListener('click', function (e) {
          e.preventDefault();
          confirmAgentAction(card);
        });
      }
      if (cancelBtn) {
        cancelBtn.addEventListener('click', function (e) {
          e.preventDefault();
          cancelAgentAction(card);
        });
      }
    });
  }

  function messageSeen(msg) {
    var eid = msg.escalation_id || '';
    if (eid) {
      if (seenEscalationIds[eid]) return true;
      if (list.querySelector('.ai-msg-wrap[data-escalation-id="' + eid + '"]')) {
        seenEscalationIds[eid] = 1;
        return true;
      }
      seenEscalationIds[eid] = 1;
    }
    var hideKey =
      (msg.role || '') +
      '|' +
      (msg.created_at || '') +
      '|' +
      String(msg.content || '').slice(0, 96);
    if (msg.hide_ui || msg.hide_user) {
      if (seenHiddenMsgKeys[hideKey]) return true;
    }
    var ts = msg.created_at || '';
    var role = msg.role || 'assistant';
    if (ts && list.querySelector('.ai-msg-wrap[data-created-at="' + ts + '"][data-role="' + role + '"]')) {
      return true;
    }
    var text = (msg.content || '').trim();
    if (text && text.indexOf('پاسخ تیم وینور') === 0) {
      var wraps = list.querySelectorAll('.ai-msg-wrap[data-admin-reply="1"] .ai-msg-bubble');
      for (var i = 0; i < wraps.length; i++) {
        if ((wraps[i].textContent || '').trim() === text) return true;
      }
    }
    return false;
  }

  function bumpLastSyncAt(ts) {
    if (ts && (!lastSyncAt || ts > lastSyncAt)) lastSyncAt = ts;
  }

  function scanLastSyncFromDom() {
    var maxTs = '';
    list.querySelectorAll('.ai-msg-wrap[data-created-at]').forEach(function (w) {
      if (w.getAttribute('data-welcome') === '1' || w.getAttribute('data-ephemeral') === '1') return;
      var t = w.getAttribute('data-created-at') || '';
      if (t > maxTs) maxTs = t;
    });
    if (maxTs) lastSyncAt = maxTs;
  }

  function storedMessageCount() {
    return list.querySelectorAll(
      '.ai-msg-wrap[data-created-at]:not([data-welcome="1"]):not([data-ephemeral="1"])'
    ).length;
  }

  function knownEscalationIds() {
    var ids = [];
    list.querySelectorAll('.ai-msg-wrap[data-escalation-id]').forEach(function (w) {
      var id = w.getAttribute('data-escalation-id');
      if (id) ids.push(id);
    });
    return ids;
  }

  function removeWelcome() {
    list.querySelectorAll('.ai-msg-wrap[data-welcome="1"]').forEach(function (w) {
      w.remove();
    });
  }

  function removePendingUser() {
    list.querySelectorAll('.ai-msg-wrap[data-pending-user="1"]').forEach(function (w) {
      w.remove();
    });
  }

  function appendMessage(msg, opts) {
    opts = opts || {};
    if (messageSeen(msg)) return null;
    var role = msg.role || 'assistant';
    var text = (msg.content || '').trim();
    /* پرامپت اکشن مأموریت — در چت نمایش نده */
    if (role === 'user' && (msg.hide_ui || msg.hide_user || opts.silent)) {
      var hk =
        role + '|' + (msg.created_at || '') + '|' + String(msg.content || '').slice(0, 96);
      seenHiddenMsgKeys[hk] = 1;
      if (msg.created_at) bumpLastSyncAt(msg.created_at);
      return null;
    }
    var cardsHtml = buildCardsHtml(msg);
    var isAdmin =
      msg.source === 'admin_escalation' ||
      msg.source === 'postchi' ||
      (text && text.indexOf('پاسخ تیم وینور') === 0);

    if (!text && !cardsHtml && !msg.land_detail_html && !opts.thinking && !opts.streamShell) return null;

    if (!opts.welcome) removeWelcome();

    var isUser = role === 'user';
    var wrap = document.createElement('div');
    wrap.className =
      'ai-msg-wrap ' + (isUser ? 'ai-msg-wrap--user' : 'ai-msg-wrap--assistant');
    wrap.setAttribute('data-role', role);
    if (msg.created_at) wrap.setAttribute('data-created-at', msg.created_at);
    if (msg.escalation_id) wrap.setAttribute('data-escalation-id', msg.escalation_id);
    if (msg.source === 'postchi' && role === 'assistant') {
      wrap.setAttribute('data-postchi', '1');
    }
    if (isAdmin && msg.source !== 'postchi') wrap.setAttribute('data-admin-reply', '1');
    if (opts.pendingUser) wrap.setAttribute('data-pending-user', '1');
    if (opts.welcome) wrap.setAttribute('data-welcome', '1');
    if (opts.ephemeral) wrap.setAttribute('data-ephemeral', '1');
    if (opts.thinking) wrap.setAttribute('data-thinking', '1');

    var row = document.createElement('div');
    row.className = 'ai-msg-row';

    if (!isUser) {
      var avatar = document.createElement('div');
      avatar.className = 'ai-msg-avatar';
      avatar.setAttribute('aria-hidden', 'true');
      avatar.innerHTML =
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z"/>' +
        '<path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7.7-2z" opacity=".85"/>' +
        '</svg>';
      row.appendChild(avatar);
    }

    var body = document.createElement('div');
    body.className = 'ai-msg-body';

    if (opts.thinking) {
      var thinking = document.createElement('div');
      thinking.className = 'ai-msg-bubble ai-msg-thinking';
      thinking.setAttribute('aria-label', 'در حال نوشتن');
      thinking.innerHTML =
        '<span class="ai-msg-dot"></span><span class="ai-msg-dot"></span><span class="ai-msg-dot"></span>';
      body.appendChild(thinking);
    } else if (opts.streamShell) {
      var streamBubble = document.createElement('div');
      streamBubble.className = 'ai-msg-bubble';
      streamBubble.setAttribute('aria-live', 'off');
      body.appendChild(streamBubble);
    } else if (text) {
      var bubble = document.createElement('div');
      bubble.className = 'ai-msg-bubble';
      if (isUser) {
        bubble.textContent = text;
      } else {
        bubble.innerHTML = formatAssistantHtml(text);
        bubble.setAttribute('data-formatted', '1');
      }
      body.appendChild(bubble);
    }

    if (cardsHtml) {
      var cardsWrap = document.createElement('div');
      cardsWrap.innerHTML = cardsHtml;
      var cardsEl = cardsWrap.firstElementChild;
      if (cardsEl) {
        if (!cardsEl.classList.contains('ai-msg-cards')) {
          var cardsHost = document.createElement('div');
          cardsHost.className = 'ai-msg-cards';
          cardsHost.appendChild(cardsEl);
          body.appendChild(cardsHost);
        } else {
          body.appendChild(cardsEl);
        }
        initCardsIn(body);
      }
    }

    if (msg.land_detail_html) {
      var detailHost = document.createElement('div');
      detailHost.className = 'ai-msg-cards ai-msg-cards--land-detail w-full min-w-0 max-w-full mt-1';
      detailHost.innerHTML = msg.land_detail_html;
      body.appendChild(detailHost);
      if (msg.land_code) wrap.setAttribute('data-land-chat-code', String(msg.land_code));
      wrap.setAttribute('data-ephemeral', '1');
      initCardsIn(detailHost);
    }

    row.appendChild(body);
    wrap.appendChild(row);
    list.appendChild(wrap);
    if (!isUser && !opts.thinking && !opts.streamShell) {
      wireCopyBlocks(wrap);
      ensureMsgActions(wrap);
    }
    if (msg.created_at) bumpLastSyncAt(msg.created_at);
    scrollChatToEnd();
    return wrap;
  }

  function showThinking() {
    removeThinking();
    return appendMessage({ role: 'assistant', content: '' }, { thinking: true, ephemeral: true });
  }

  function removeThinking() {
    list.querySelectorAll('.ai-msg-wrap[data-thinking="1"]').forEach(function (w) {
      try {
        w.remove();
      } catch (_) {}
    });
  }

  function appendBubble(text, role, opts) {
    return appendMessage({ role: role, content: text }, opts || {});
  }

  function showEphemeralHint(text) {
    var wrap = appendBubble(text, 'assistant', { ephemeral: true });
    if (!wrap) return;
    setTimeout(function () {
      try {
        wrap.remove();
      } catch (_) {}
    }, 4200);
  }

  function renderMessages(messages) {
    cancelTypewriter();
    list.innerHTML = '';
    seenEscalationIds = {};
    lastSyncAt = '';
    (messages || []).forEach(function (m) {
      if (!m) return;
      routeLandCardsToHome(m);
      if (m.role && messageHasContent(m)) {
        appendMessage(m);
      }
    });
    showWelcomeIfEmpty();
    scanLastSyncFromDom();
    syncChipBarVisibility();
    scrollChatToLatest();
  }

  function showWelcomeIfEmpty() {
    if (isPostchiMode()) return;
    if (list.querySelector('.ai-msg-wrap[data-role]')) return;
    appendMessage({ role: 'assistant', content: welcome }, { welcome: true });
  }

  async function markPostchiOpened() {
    if (!postchiOpenUrl || postchiOpened) return;
    postchiOpened = true;
    try {
      var resp = await fetch(postchiOpenUrl, {
        method: 'POST',
        headers: apiHeaders(false),
        credentials: 'same-origin',
      });
      var data = await resp.json();
      if (data && data.success) {
        syncMenuUnreadBadge(data.unread_count || 0);
        try {
          window.dispatchEvent(
            new CustomEvent('vinor:notifications:update', {
              detail: { unread: Number(data.unread_count || 0), notifications: null },
            })
          );
        } catch (_) {}
      }
    } catch (_) {
      postchiOpened = false;
    }
  }

  async function loadPostchiMessages() {
    if (!postchiMessagesUrl) return;
    setBusy(true);
    try {
      var resp = await fetch(postchiMessagesUrl, {
        credentials: 'same-origin',
        headers: apiHeaders(false),
      });
      var data = await resp.json();
      if (data && data.success && Array.isArray(data.messages)) {
        var mapped = data.messages.map(function (m) {
          return {
            role: m.role === 'out' ? 'user' : 'assistant',
            content: m.body || '',
            created_at: postchiTsToIso(m.created_at),
            source: 'postchi',
          };
        });
        renderMessages(mapped);
      }
    } catch (_) {
      /* ignore */
    } finally {
      setBusy(false);
    }
  }

  function postchiTsToIso(ts) {
    var v = Number(ts) || 0;
    if (!v) return '';
    if (v < 1e12) v *= 1000;
    try {
      return new Date(v).toISOString();
    } catch (_) {
      return '';
    }
  }

  function formatDate(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso).slice(0, 10);
      return d.toLocaleDateString('fa-IR', { month: 'short', day: 'numeric' });
    } catch (_) {
      return String(iso).slice(0, 10);
    }
  }

  function threadsCacheKey(threads) {
    if (!threads || !threads.length) return '';
    return threads
      .map(function (t) {
        return (
          (t.id || '') +
          ':' +
          (t.updated_at || '') +
          ':' +
          (t.message_count || 0) +
          ':' +
          (t.is_active ? '1' : '0') +
          ':' +
          (t.unread || 0) +
          ':' +
          (t.kind || '')
        );
      })
      .join('|');
  }

  function threadItemClasses(th) {
    var inDrawer = !!(historyList && historyList.closest('#epProfileDrawer'));
    var isPostchi = th.kind === 'postchi' || th.id === postchiThreadId;
    var active = !!th.is_active;
    if (inDrawer) {
      return active ? 'is-active' : '';
    }
    if (isPostchi) {
      return active
        ? 'border-emerald-500/40 bg-emerald-500/15'
        : 'border-emerald-500/20 bg-emerald-500/[0.06] hover:bg-emerald-500/10';
    }
    return active
      ? 'border-violet-500/40 bg-violet-500/15'
      : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.06]';
  }

  function renderThreadList(threads) {
    if (!historyList) return;
    var key = threadsCacheKey(threads);
    if (key && key === lastThreadsKey) return;
    lastThreadsKey = key;
    updatePostchiUnreadFromThreads(threads);
    historyList.innerHTML = '';
    var inDrawer = !!(historyList.closest && historyList.closest('#epProfileDrawer'));
    if (!threads || !threads.length) {
      historyList.innerHTML =
        '<p class="px-2 py-4 text-center text-xs text-zinc-500">هنوز گفتگویی نیست</p>';
      return;
    }
    threads.forEach(function (th) {
      var isPostchi = th.kind === 'postchi' || th.id === postchiThreadId;
      var btnEl = document.createElement('button');
      btnEl.type = 'button';
      btnEl.className =
        'ai-thread-item ' +
        (inDrawer
          ? ''
          : 'w-full rounded-xl border px-3 py-2.5 text-right transition ') +
        threadItemClasses(th);
      btnEl.setAttribute('data-thread-id', th.id);
      btnEl.setAttribute('data-active', th.is_active ? '1' : '0');
      if (isPostchi) btnEl.setAttribute('data-thread-kind', 'postchi');
      var unreadBadge =
        th.unread > 0
          ? '<span class="ai-thread-unread">' +
            (th.unread > 99 ? '99+' : String(th.unread)) +
            '</span>'
          : '';
      var deleteBtn = isPostchi
        ? ''
        : '<span class="ai-thread-delete" data-thread-id="' +
          escapeHtml(th.id || '') +
          '" role="button" aria-label="حذف گفتگو" tabindex="-1">' +
          '<i class="fas fa-trash-alt text-[10px]" aria-hidden="true"></i></span>';
      var extras = '';
      if (!inDrawer) {
        if (th.preview) {
          extras +=
            '<p class="ai-thread-item__preview mt-1 text-[10px] text-zinc-500 line-clamp-2 leading-relaxed">' +
            escapeHtml(th.preview) +
            '</p>';
        }
        if (!isPostchi) {
          extras +=
            '<p class="ai-thread-item__meta mt-1.5 text-[9px] text-zinc-600 flex items-center justify-between gap-2">' +
            '<span>' +
            (th.message_count || 0) +
            ' پیام</span>' +
            '<time class="tabular-nums">' +
            formatDate(th.updated_at) +
            '</time></p>';
        }
      }
      btnEl.innerHTML =
        '<div class="ai-thread-item__row' +
        (inDrawer ? '' : ' flex items-center justify-between gap-2') +
        '">' +
        '<span class="ai-thread-item__title">' +
        (isPostchi
          ? '<i class="fas fa-envelope text-[10px] text-emerald-400 shrink-0" aria-hidden="true"></i>'
          : '') +
        '<span>' +
        escapeHtml(th.title || 'گفتگو') +
        '</span></span>' +
        '<span class="ai-thread-item__actions' +
        (inDrawer ? '' : ' flex shrink-0 items-center gap-1') +
        '">' +
        unreadBadge +
        deleteBtn +
        '</span></div>' +
        extras;
      historyList.appendChild(btnEl);
    });
  }

  function openSideMenu() {
    if (window.vinorProfileDrawer && document.querySelector('#epProfileDrawer .ep-profile-drawer__ai')) {
      window.vinorProfileDrawer.open();
      var settingsBtn = document.getElementById('epProfileMenuBtn');
      if (settingsBtn) settingsBtn.setAttribute('aria-expanded', 'true');
      if (menuBtn) menuBtn.setAttribute('aria-expanded', 'true');
      refreshHistory(true);
      return;
    }
    if (!sidePanel || !sideBackdrop) return;
    sidePanel.classList.add('is-open');
    sidePanel.setAttribute('aria-hidden', 'false');
    sideBackdrop.classList.add('is-open');
    sideBackdrop.setAttribute('aria-hidden', 'false');
    if (menuBtn) menuBtn.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
    refreshHistory(true);
  }

  function closeSideMenu() {
    if (window.vinorProfileDrawer && window.vinorProfileDrawer.isOpen && window.vinorProfileDrawer.isOpen()) {
      window.vinorProfileDrawer.close();
    }
    var settingsBtn = document.getElementById('epProfileMenuBtn');
    if (settingsBtn) settingsBtn.setAttribute('aria-expanded', 'false');
    if (!sidePanel || !sideBackdrop) {
      if (menuBtn) menuBtn.setAttribute('aria-expanded', 'false');
      return;
    }
    sidePanel.classList.remove('is-open');
    sidePanel.setAttribute('aria-hidden', 'true');
    sideBackdrop.classList.remove('is-open');
    sideBackdrop.setAttribute('aria-hidden', 'true');
    if (menuBtn) menuBtn.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  function ensureChatVisible() {
    if (!homeInline) return;
    if (window.vinorAiHome && typeof window.vinorAiHome.open === 'function') {
      if (!window.vinorAiHome.isOpen || !window.vinorAiHome.isOpen()) {
        window.vinorAiHome.open({});
      }
    }
  }

  function syncNewChatAvailability(threads) {
    if (!newChatBtn) return;
    if (!isGuestAuth()) {
      newChatBtn.disabled = false;
      newChatBtn.removeAttribute('title');
      return;
    }
    var n = Array.isArray(threads) ? threads.length : 0;
    var atLimit = n >= 2;
    newChatBtn.disabled = atLimit;
    if (atLimit) {
      newChatBtn.setAttribute('title', 'بدون ورود حداکثر ۲ گفتگو — برای بیشتر وارد شوید');
    } else {
      newChatBtn.removeAttribute('title');
    }
  }

  function applyThreads(threads) {
    if (threads && threads.length) renderThreadList(threads);
    syncNewChatAvailability(threads || []);
  }

  async function refreshHistory(immediate) {
    if (!historyUrl || embedded || !historyList) return;
    if (historyTimer) {
      clearTimeout(historyTimer);
      historyTimer = null;
    }
    var run = async function () {
      if (historyAbort) historyAbort.abort();
      historyAbort = new AbortController();
      try {
        var url = historyUrl + (historyUrl.indexOf('?') >= 0 ? '&' : '?') + 'threads_only=1';
        var resp = await fetch(url, {
          credentials: 'same-origin',
          headers: apiHeaders(false),
          signal: historyAbort.signal,
        });
        var data = await resp.json();
        if (data && data.ok && data.threads) applyThreads(data.threads);
      } catch (err) {
        if (err && err.name !== 'AbortError') {
          /* ignore */
        }
      }
    };
    if (immediate) return run();
    historyTimer = setTimeout(run, 280);
  }

  async function switchThread(threadId) {
    if (!switchUrl || !threadId) return;
    if (switchAbort) switchAbort.abort();
    switchAbort = new AbortController();
    setBusy(true);
    try {
      var resp = await fetch(switchUrl, {
        method: 'POST',
        headers: apiHeaders(true),
        credentials: 'same-origin',
        body: JSON.stringify({ thread_id: threadId }),
        signal: switchAbort.signal,
      });
      var data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error((data && data.error) || 'خطا');
      setActiveThreadId(data.thread_id);
      renderMessages(data.messages);
      if (data.threads) applyThreads(data.threads);
      if (data.mode === 'postchi' || data.thread_id === postchiThreadId) {
        postchiOpened = true;
        pollPaused = true;
      } else {
        postchiOpened = false;
        resumePoll();
      }
      closeSideMenu();
      ensureChatVisible();
    } catch (err) {
      if (err && err.name !== 'AbortError') alert(err.message || 'خطا');
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  async function deleteThread(threadId) {
    if (!deleteUrl || !threadId || threadId === postchiThreadId) return;
    if (!window.confirm('این گفتگو حذف شود؟')) return;
    if (deleteAbort) deleteAbort.abort();
    deleteAbort = new AbortController();
    setBusy(true);
    try {
      var resp = await fetch(deleteUrl, {
        method: 'POST',
        headers: apiHeaders(true),
        credentials: 'same-origin',
        body: JSON.stringify({ thread_id: threadId }),
        signal: deleteAbort.signal,
      });
      var data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error((data && data.error) || 'حذف ممکن نیست');
      if (data.thread_id) setActiveThreadId(data.thread_id);
      renderMessages(data.messages);
      lastThreadsKey = '';
      if (data.threads) applyThreads(data.threads);
      else await refreshHistory(true);
      resumePoll();
    } catch (err) {
      if (err && err.name !== 'AbortError') alert(err.message || 'خطا');
    } finally {
      setBusy(false);
    }
  }

  async function startNewChat() {
    if (!clearUrl) return;
    setBusy(true);
    try {
      var resp = await fetch(clearUrl, {
        method: 'POST',
        headers: apiHeaders(false),
        credentials: 'same-origin',
      });
      var data = await resp.json();
      if (!resp.ok || !data || !data.ok) {
        if (data && data.need_login) {
          showEphemeralHint(data.error || 'برای گفتگوی بیشتر وارد شوید.');
          try {
            if (window.vinorProfileDrawer && typeof window.vinorProfileDrawer.open === 'function') {
              window.vinorProfileDrawer.open();
            }
            if (typeof window.vinorDrawerOpenLogin === 'function') {
              window.vinorDrawerOpenLogin();
            }
          } catch (_) {}
          return;
        }
        throw new Error((data && data.error) || 'خطا');
      }
      if (data.thread_id) setActiveThreadId(data.thread_id);
      renderMessages([]);
      lastThreadsKey = '';
      await refreshHistory(true);
      closeSideMenu();
      ensureChatVisible();
      showChipBar();
      input.focus();
    } catch (err) {
      alert(err.message || 'خطا');
    } finally {
      setBusy(false);
    }
  }

  async function pollSync() {
    if (!syncUrl || document.hidden || pollPaused || pollInFlight || isPostchiMode()) return;
    if (layerGated && !sheetOpen) return;
    var tid = activeThreadId();
    if (!tid) return;
    if (syncAbort) syncAbort.abort();
    syncAbort = new AbortController();
    pollInFlight = true;
    try {
      var url =
        syncUrl +
        (syncUrl.indexOf('?') >= 0 ? '&' : '?') +
        'thread_id=' +
        encodeURIComponent(tid) +
        '&count=' +
        encodeURIComponent(String(storedMessageCount()));
      if (lastSyncAt) {
        url += '&after=' + encodeURIComponent(lastSyncAt);
      }
      url += '&exclude_esc=' + encodeURIComponent(knownEscalationIds().join(','));

      var resp = await fetch(url, {
        credentials: 'same-origin',
        headers: apiHeaders(false),
        signal: syncAbort.signal,
      });
      var data = await resp.json();
      if (!data || !data.ok || !data.messages || !data.messages.length) {
        emptyPollStreak += 1;
        if (emptyPollStreak >= EMPTY_POLL_PAUSE) pollPaused = true;
        return;
      }
      emptyPollStreak = 0;
      pollPaused = false;
      var added = false;
      data.messages.forEach(function (m) {
        if (!m || !m.role) return;
        routeLandCardsToHome(m);
        if (messageHasContent(m)) {
          if (appendMessage(m)) added = true;
        }
      });
      if (added) {
        scanLastSyncFromDom();
        scrollChatToEnd();
      }
    } catch (err) {
      if (err && err.name !== 'AbortError') {
        /* ignore */
      }
    } finally {
      pollInFlight = false;
    }
  }

  function resumePoll() {
    if (layerGated && !sheetOpen) {
      pollPaused = true;
      return;
    }
    pollPaused = false;
    emptyPollStreak = 0;
    pollSync();
  }

  function syncComposerInset() {
    if (!composer || !window.visualViewport) return;
    var vv = window.visualViewport;
    var inset = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    composer.style.setProperty(
      '--ai-keyboard-inset',
      inset > 0 ? inset + 'px' : '0px'
    );
  }

  function teardownAiChat() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (historyTimer) {
      clearTimeout(historyTimer);
      historyTimer = null;
    }
    try {
      if (historyAbort) historyAbort.abort();
    } catch (_) {}
    try {
      if (switchAbort) switchAbort.abort();
    } catch (_) {}
    try {
      if (syncAbort) syncAbort.abort();
    } catch (_) {}
    try {
      if (chatAbort) chatAbort.abort();
    } catch (_) {}
    try {
      if (deleteAbort) deleteAbort.abort();
    } catch (_) {}
    historyAbort = null;
    switchAbort = null;
    syncAbort = null;
    chatAbort = null;
    deleteAbort = null;
    closeSideMenu();
    if (onVisChange) {
      document.removeEventListener('visibilitychange', onVisChange);
      onVisChange = null;
    }
    if (onKeydown) {
      document.removeEventListener('keydown', onKeydown);
      onKeydown = null;
    }
    if (window.visualViewport) {
      if (onViewportResize) window.visualViewport.removeEventListener('resize', onViewportResize);
      if (onViewportScroll) window.visualViewport.removeEventListener('scroll', onViewportScroll);
      onViewportResize = null;
      onViewportScroll = null;
    }
    if (composer) composer.style.removeProperty('--ai-keyboard-inset');
    cancelTypewriter();
    scrollLatestGen += 1;
    window.__vinorAiChatTeardown = null;
    window.__vinorAiChatSetSheetOpen = null;
    window.__vinorAiChatSwitchThread = null;
  }

  window.__vinorAiChatTeardown = teardownAiChat;
  window.__vinorAiChatSwitchThread = switchThread;
  window.__vinorAiChatOpenSideMenu = openSideMenu;

  showWelcomeIfEmpty();
  setComposerMode(isPostchiMode());
  if (isPostchiMode()) {
    pollPaused = true;
    markPostchiOpened();
  }
  list.querySelectorAll('.ai-msg-wrap').forEach(function (w) {
    initCardsIn(w);
    var eid = w.getAttribute('data-escalation-id');
    if (eid) seenEscalationIds[eid] = 1;
  });
  scrubLandCardsFromChatDom();
  enhanceAssistantBubbles(list);
  scanLastSyncFromDom();
  scrollChatToLatest();

  list.addEventListener('click', onMsgActionsClick);
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t && t.closest && t.closest('[data-ai-msg-more], [data-ai-msg-menu]')) return;
    closeAllMsgMenus();
  });

  pollTimer = setInterval(pollSync, POLL_MS);
  if (!embedded) {
    refreshHistory(false);
  }
  onVisChange = function () {
    if (document.hidden) return;
    if (layerGated && !sheetOpen) return;
    resumePoll();
  };
  document.addEventListener('visibilitychange', onVisChange);

  window.addEventListener('vinor:notifications:update', function (ev) {
    if (embedded) return;
    var detail = ev && ev.detail;
    if (!detail || detail.unread === undefined || detail.unread === null) return;
    syncMenuUnreadBadge(detail.unread);
    if (historyUrl && isPostchiMode()) {
      lastThreadsKey = '';
      refreshHistory(true);
    }
  });

  if (menuBtn) menuBtn.addEventListener('click', openSideMenu);
  if (sideClose) sideClose.addEventListener('click', closeSideMenu);
  if (sideBackdrop) sideBackdrop.addEventListener('click', closeSideMenu);
  if (newChatBtn) newChatBtn.addEventListener('click', startNewChat);

  var profileMenuBtn = document.getElementById('epProfileMenuBtn');
  if (profileMenuBtn && homeInline) {
    profileMenuBtn.addEventListener('click', function () {
      setTimeout(function () {
        try {
          if (window.vinorProfileDrawer && window.vinorProfileDrawer.isOpen && window.vinorProfileDrawer.isOpen()) {
            refreshHistory(true);
          }
        } catch (_) {}
      }, 80);
    });
  }

  if (historyList) {
    historyList.addEventListener('click', function (e) {
      var delBtn = e.target.closest('.ai-thread-delete');
      if (delBtn) {
        e.preventDefault();
        e.stopPropagation();
        var delId = delBtn.getAttribute('data-thread-id');
        if (delId) deleteThread(delId);
        return;
      }
      var item = e.target.closest('.ai-thread-item');
      if (!item) return;
      var tid = item.getAttribute('data-thread-id');
      if (tid) switchThread(tid);
    });
  }

  onKeydown = function (e) {
    if (e.key !== 'Escape') return;
    if (sidePanel && sidePanel.classList.contains('is-open')) {
      closeSideMenu();
      return;
    }
    if (homeInline && window.vinorProfileDrawer && window.vinorProfileDrawer.isOpen && window.vinorProfileDrawer.isOpen()) {
      closeSideMenu();
    }
  };
  document.addEventListener('keydown', onKeydown);

  if (window.visualViewport) {
    onViewportResize = syncComposerInset;
    onViewportScroll = syncComposerInset;
    window.visualViewport.addEventListener('resize', onViewportResize);
    window.visualViewport.addEventListener('scroll', onViewportScroll);
    syncComposerInset();
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (isPostchiMode()) return;
    if (submitting) return;
    var silentUser = false;
    try {
      silentUser = form.getAttribute('data-silent-user') === '1';
    } catch (_) {}
    var silentMsg = takeSilentMessage();
    var msg = silentMsg || (input.value || '').trim();
    takeSilentUserFlag(); /* clear flag after reading silentMsg */
    if (silentMsg) silentUser = true;
    if (!msg || msg.length < MIN_MSG_LEN) {
      syncComposerReady();
      return;
    }

    /* سقف مهمان: دکمه فعال می‌ماند؛ با ارسال → پیام + منوی ورود */
    if (isGuestQuotaUser() && guestRepliesRemaining !== null && guestRepliesRemaining <= 0) {
      try {
        if (!silentUser) {
          input.value = msg;
          autoGrowInput();
        }
      } catch (_) {}
      promptGuestLoginLimit('به سقف ۲۰ پاسخ رسیدید. برای ادامه وارد شوید.');
      return;
    }

    var now = Date.now();
    if (lastSubmitAt && now - lastSubmitAt < MIN_SUBMIT_GAP_MS) {
      showEphemeralHint('لطفاً چند ثانیه صبر کنید و دوباره بفرستید.');
      return;
    }

    submitting = true;
    lastSubmitAt = now;
    hideChipBar();
    removeWelcome();
    if (!silentUser) {
      appendMessage({ role: 'user', content: msg }, { pendingUser: true });
    }
    showThinking();
    input.value = '';
    autoGrowInput();
    setBusy(true);
    stickChatToBottom = true;
    scrollChatToEnd({ force: true });

    if (isPostchiMode()) {
      if (!postchiSendUrl) {
        submitting = false;
        setBusy(false);
        return;
      }
      try {
        var pResp = await fetch(postchiSendUrl, {
          method: 'POST',
          headers: apiHeaders(true),
          credentials: 'same-origin',
          body: JSON.stringify({ message: msg }),
        });
        var pData = await pResp.json();
        if (!pResp.ok || !pData || !pData.success) {
          removePendingUser();
          throw new Error((pData && pData.error) || 'ارسال ناموفق بود');
        }
        removePendingUser();
        await loadPostchiMessages();
        lastThreadsKey = '';
        await refreshHistory(true);
      } catch (err) {
        removePendingUser();
        showEphemeralHint(err.message || 'خطا در ارسال پیام');
      } finally {
        removeThinking();
        submitting = false;
        setBusy(false);
        input.focus();
      }
      return;
    }

    resumePoll();

    if (chatAbort) chatAbort.abort();
    chatAbort = new AbortController();

    try {
      var intent = takePendingChipIntent();
      var body = { message: msg, thread_id: activeThreadId() };
      if (intent) body.intent = intent;
      if (silentUser) body.hide_user = true;
      var resp = await fetch(chatUrl, {
        method: 'POST',
        headers: apiHeaders(true),
        credentials: 'same-origin',
        body: JSON.stringify(body),
        signal: chatAbort.signal,
      });
      hideChipBar();
      var data = null;
      try {
        data = await resp.json();
      } catch (_) {}

      if (!resp.ok || !data || !data.ok) {
        var errText = (data && data.error) || 'خطا در دریافت پاسخ';
        if (data && data.need_login) {
          removePendingUser();
          removeThinking();
          try {
            input.value = msg;
            autoGrowInput();
          } catch (_) {}
          guestRepliesRemaining = 0;
          noteGuestRepliesFromPayload({ guest_replies_remaining: 0 });
          promptGuestLoginLimit(errText || 'به سقف ۲۰ پاسخ رسیدید. برای ادامه وارد شوید.');
          return;
        }
        if (data && data.escalated && data.reply) {
          if (data.thread_id) setActiveThreadId(data.thread_id);
          if (data.messages && data.messages.length) {
            await reconcileExchange(data.messages, { stream: true });
          } else {
            removePendingUser();
            await typewriteAssistantMessage({
              role: 'assistant',
              content: data.reply,
              cards_html: data.cards_html,
              land_cards: data.land_cards,
              escalation_id: data.escalation_id,
              created_at: data.created_at,
            });
          }
          if (data.threads) applyThreads(data.threads);
          else await refreshHistory();
          pollSync();
          return;
        }
        removePendingUser();
        throw new Error(errText);
      }
      if (data.thread_id) setActiveThreadId(data.thread_id);
      noteGuestRepliesFromPayload(data);
      await reconcileExchange(data.messages, { stream: true });
      if (data.guest_limit_reached || (typeof data.guest_replies_remaining === 'number' && data.guest_replies_remaining <= 0 && isGuestQuotaUser())) {
        guestRepliesRemaining = 0;
        /* سقف پر شد — دفعه بعد منوی ورود؛ همین پاسخ را نشان بده */
      }
      if (data.threads) {
        lastThreadsKey = '';
        applyThreads(data.threads);
      } else {
        await refreshHistory();
      }
      pollSync();
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      removePendingUser();
      var errMsg = String(err.message || 'خطای ناشناخته');
      showEphemeralHint(errMsg);
      if (/اعتبار API|InsufficientBalance|402/i.test(errMsg)) {
        pollPaused = true;
      }
    } finally {
      removeThinking();
      if (!loginPromptActive) {
        submitting = false;
        setBusy(false);
        try {
          input.focus();
        } catch (_) {}
      } else {
        /* سقف ورود: کامپوزر را قفل نکن — unlock داخل promptGuestLoginLimit انجام شده */
        submitting = false;
        unlockComposer({
          placeholder: 'به سقف رسیدید — برای ادامه وارد شوید…',
        });
      }
    }
  });

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (submitting) return;
      var msg = (input.value || '').trim();
      if (!msg || msg.length < MIN_MSG_LEN) return;
      /* حتی اگر دکمه disabled مانده باشد، Enter ارسال را راه بیندازد */
      try {
        if (typeof form.requestSubmit === 'function') form.requestSubmit();
        else form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      } catch (_) {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      }
    }
  });

  input.addEventListener('input', function () {
    if ((input.value || '').length > 0) {
      stopTypeHintPlaceholder({ dismiss: true, placeholder: '' });
    } else if (!typeHintDismissed) {
      startTypeHintPlaceholder();
    } else {
      input.placeholder = staticComposerPlaceholder();
    }
    autoGrowInput();
    syncComposerReady();
  });

  if (btn) {
    btn.addEventListener('click', function (e) {
      if (submitting) {
        e.preventDefault();
        return;
      }
      var msg = (input.value || '').trim();
      if (!msg || msg.length < MIN_MSG_LEN) {
        e.preventDefault();
        syncComposerReady();
        return;
      }
      /* اگر به‌هر دلیل disabled مانده، باز کن و submit را دستی بزن */
      if (btn.disabled) {
        e.preventDefault();
        unlockComposer();
        try {
          form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        } catch (_) {}
      }
    });
  }

  window.__vinorAiChatOnDrawerClose = function () {
    loginPromptActive = false;
    unlockComposer(
      isGuestQuotaUser() && guestRepliesRemaining !== null && guestRepliesRemaining <= 0
        ? { placeholder: 'به سقف رسیدید — برای ادامه وارد شوید…' }
        : {}
    );
  };

  var landDetailPending = null;
  function sendChatPromptFromDetail(prompt, intent) {
    submitSilentPrompt(prompt, intent);
  }

  if (!window.__vinorChatPromptCaptureBound) {
    window.__vinorChatPromptCaptureBound = true;
    document.addEventListener(
      'click',
      function (e) {
        var btn = e.target && e.target.closest && e.target.closest('[data-vn-chat-prompt]');
        if (!btn) return;
        var prompt = btn.getAttribute('data-vn-chat-prompt') || '';
        if (!prompt.trim()) return;
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        var liveForm = document.getElementById('aiChatForm');
        var liveInput = document.getElementById('aiInput');
        if (liveForm && liveInput && document.getElementById('aiMessages')) {
          var intent = btn.getAttribute('data-vn-chat-intent') || '';
          try {
            liveForm.setAttribute('data-silent-user', '1');
            liveForm.setAttribute('data-silent-message', prompt.trim());
            if (intent) liveForm.setAttribute('data-pending-intent', intent);
            else liveForm.removeAttribute('data-pending-intent');
            liveInput.value = '';
            liveInput.dispatchEvent(new Event('input', { bubbles: true }));
          } catch (_) {}
          setTimeout(function () {
            try {
              if (typeof liveForm.requestSubmit === 'function') liveForm.requestSubmit();
              else liveForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            } catch (_) {}
          }, 40);
          return;
        }
        try {
          sessionStorage.setItem('vinor_ai_home_prompt', prompt.trim());
          sessionStorage.setItem('vinor_ai_home_autosend', '1');
          sessionStorage.setItem('vinor_ai_home_silent', '1');
          var intentNav = (btn.getAttribute('data-vn-chat-intent') || '').trim();
          if (intentNav) sessionStorage.setItem('vinor_ai_home_intent', intentNav);
          else sessionStorage.removeItem('vinor_ai_home_intent');
        } catch (_) {}
        if (typeof window.vinorExpressNavigate === 'function') {
          window.vinorExpressNavigate('/express/partner/home', { forward: true });
        } else {
          window.location.assign('/express/partner/home');
        }
      },
      true
    );
  }

  window.vinorShowLandInChat = function (code) {
    code = String(code || '').trim();
    if (!code) return Promise.resolve(false);
    if (landDetailPending === code) return Promise.resolve(false);
    landDetailPending = code;

    var existing = list.querySelector('.ai-msg-wrap[data-land-chat-code="' + code + '"]');
    if (existing) {
      try {
        existing.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      } catch (_) {
        scrollChatToEnd();
      }
      landDetailPending = null;
      return Promise.resolve(true);
    }

    var thinking = showThinking();
    var url = '/express/partner/lands/' + encodeURIComponent(code) + '/chat-detail';
    return fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (payload) {
        removeThinking();
        landDetailPending = null;
        if (!payload.ok || !payload.data || !payload.data.ok || !payload.data.html) {
          showEphemeralHint(
            (payload.data && payload.data.message) || 'جزئیات این فایل در دسترس نیست.'
          );
          return false;
        }
        appendMessage({
          role: 'assistant',
          content: '',
          land_detail_html: payload.data.html,
          land_code: payload.data.code || code,
        });
        return true;
      })
      .catch(function () {
        removeThinking();
        landDetailPending = null;
        showEphemeralHint('خطا در دریافت جزئیات فایل.');
        return false;
      });
  };

  autoGrowInput();
  syncComposerReady();
  syncChipBarVisibility();
  startTypeHintPlaceholder();
  bindChatScrollBottom();
  scrollChatToLatest();
})();
