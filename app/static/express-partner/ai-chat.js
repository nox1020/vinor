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
  var welcome = list.getAttribute('data-welcome') || 'سلام! من Vinor AI هستم.';
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
  var submitting = false;
  var lastSubmitAt = 0;
  var POLL_MS = 15000;
  var MIN_SUBMIT_GAP_MS = 4000;
  var MIN_MSG_LEN = 2;
  var EMPTY_POLL_PAUSE = 60;
  var pollInFlight = false;
  var postchiOpened = false;
  var onVisChange = null;
  var onKeydown = null;
  var onViewportResize = null;
  var onViewportScroll = null;

  function scrollChatToEnd() {
    if (homeInline) {
      var homeScroll = document.getElementById('vnHomeScroll');
      if (homeScroll) {
        homeScroll.scrollTop = homeScroll.scrollHeight;
        return;
      }
    }
    if (list) list.scrollTop = list.scrollHeight;
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
        scrollChatToEnd();
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

  function setComposerMode(postchi) {
    if (!input) return;
    if (postchi) {
      input.value = '';
      input.placeholder = 'ارسال در پستچی غیرفعال است';
      input.disabled = true;
      input.setAttribute('aria-disabled', 'true');
      if (btn) {
        btn.disabled = true;
        btn.setAttribute('aria-disabled', 'true');
      }
      form.classList.add('ai-composer--readonly');
    } else {
      input.placeholder = 'پیام خود را بنویسید…';
      input.disabled = false;
      input.removeAttribute('aria-disabled');
      if (btn) {
        btn.disabled = false;
        btn.removeAttribute('aria-disabled');
      }
      form.classList.remove('ai-composer--readonly');
    }
  }

  function setBusy(on) {
    if (isPostchiMode()) {
      if (btn) btn.disabled = true;
      if (input) input.disabled = true;
      if (newChatBtn) newChatBtn.disabled = !!on;
      return;
    }
    btn.disabled = !!on;
    input.disabled = !!on;
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

  function messageHasContent(msg) {
    if (!msg) return false;
    return !!(
      (msg.content && String(msg.content).trim()) ||
      msg.cards_html ||
      (msg.land_cards && msg.land_cards.length) ||
      (msg.agent_actions && msg.agent_actions.length)
    );
  }

  function buildCardsHtml(msg) {
    if (msg.cards_html) {
      return '<div class="ai-msg-cards w-full min-w-0 max-w-full">' + msg.cards_html + '</div>';
    }
    var chunks = [];
    if (msg.land_cards && msg.land_cards.length) {
      var inner = msg.land_cards.map(function (c) {
        return c.html || '';
      }).join('');
      if (inner) {
        chunks.push(
          '<div class="ai-land-cards mt-2.5 flex w-full max-w-full flex-col gap-2.5">' +
            inner +
            '</div>'
        );
      }
    }
    if (!chunks.length) return '';
    return '<div class="ai-msg-cards w-full min-w-0 max-w-full">' + chunks.join('') + '</div>';
  }

  function initCardsIn(wrap) {
    if (!wrap) return;
    if (typeof window.vinorInitPremiumCards === 'function') {
      window.vinorInitPremiumCards(wrap, list);
    }
    bindAgentActions(wrap);
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
    root.querySelectorAll('.ai-agent-card[data-agent-type="confirm_visit"]').forEach(function (card) {
      if (card.getAttribute('data-bound') === '1') return;
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
    var cardsHtml = buildCardsHtml(msg);
    var isAdmin =
      msg.source === 'admin_escalation' ||
      msg.source === 'postchi' ||
      (text && text.indexOf('پاسخ تیم وینور') === 0);

    if (!text && !cardsHtml) return null;

    if (!opts.welcome) removeWelcome();

    var wrap = document.createElement('div');
    wrap.className = 'ai-msg-wrap';
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

    if (text) {
      var bubble = document.createElement('div');
      bubble.className = 'ai-msg-bubble';
      bubble.textContent = text;
      wrap.appendChild(bubble);
    }

    if (cardsHtml) {
      var cardsWrap = document.createElement('div');
      cardsWrap.innerHTML = cardsHtml;
      var cardsEl = cardsWrap.firstElementChild;
      if (cardsEl) wrap.appendChild(cardsEl);
      initCardsIn(wrap);
    }

    list.appendChild(wrap);
    if (msg.created_at) bumpLastSyncAt(msg.created_at);
    scrollChatToEnd();
    return wrap;
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

  function reconcileExchange(serverMessages) {
    var msgs = serverMessages || [];
    var lastUser = null;
    var lastAsst = null;
    for (var i = msgs.length - 1; i >= 0; i--) {
      var m = msgs[i];
      if (!m || !m.role) continue;
      if (!lastAsst && m.role === 'assistant' && messageHasContent(m)) lastAsst = m;
      if (!lastUser && m.role === 'user' && messageHasContent(m)) lastUser = m;
      if (lastUser && lastAsst) break;
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

    if (lastAsst) appendMessage(lastAsst);
    scanLastSyncFromDom();
    scrollChatToEnd();
  }

  function renderMessages(messages) {
    list.innerHTML = '';
    seenEscalationIds = {};
    lastSyncAt = '';
    (messages || []).forEach(function (m) {
      if (m && m.role && messageHasContent(m)) {
        appendMessage(m);
      }
    });
    showWelcomeIfEmpty();
    scanLastSyncFromDom();
    scrollChatToEnd();
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
        '<div class="flex items-center justify-between gap-2">' +
        '<span class="ai-thread-item__title">' +
        (isPostchi
          ? '<i class="fas fa-envelope text-[10px] text-emerald-400 shrink-0" aria-hidden="true"></i>'
          : '') +
        '<span>' +
        escapeHtml(th.title || 'گفتگو') +
        '</span></span>' +
        '<span class="flex shrink-0 items-center gap-1">' +
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

  function applyThreads(threads) {
    if (threads && threads.length) renderThreadList(threads);
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
      if (!resp.ok || !data.ok) throw new Error((data && data.error) || 'خطا');
      if (data.thread_id) setActiveThreadId(data.thread_id);
      renderMessages([]);
      lastThreadsKey = '';
      await refreshHistory(true);
      closeSideMenu();
      ensureChatVisible();
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
        if (m && m.role && messageHasContent(m)) {
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
  scanLastSyncFromDom();
  scrollChatToEnd();

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
    if (submitting || btn.disabled) return;
    var msg = (input.value || '').trim();
    if (!msg || msg.length < MIN_MSG_LEN) return;
    var now = Date.now();
    if (lastSubmitAt && now - lastSubmitAt < MIN_SUBMIT_GAP_MS) {
      showEphemeralHint('لطفاً چند ثانیه صبر کنید و دوباره بفرستید.');
      return;
    }

    submitting = true;
    lastSubmitAt = now;
    removeWelcome();
    appendMessage({ role: 'user', content: msg }, { pendingUser: true });
    input.value = '';
    setBusy(true);

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
      var resp = await fetch(chatUrl, {
        method: 'POST',
        headers: apiHeaders(true),
        credentials: 'same-origin',
        body: JSON.stringify({ message: msg, thread_id: activeThreadId() }),
        signal: chatAbort.signal,
      });
      var data = null;
      try {
        data = await resp.json();
      } catch (_) {}

      if (!resp.ok || !data || !data.ok) {
        var errText = (data && data.error) || 'خطا در دریافت پاسخ';
        if (data && data.escalated && data.reply) {
          if (data.thread_id) setActiveThreadId(data.thread_id);
          if (data.messages && data.messages.length) {
            reconcileExchange(data.messages);
          } else {
            removePendingUser();
            appendMessage({
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
      reconcileExchange(data.messages);
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
      submitting = false;
      setBusy(false);
      input.focus();
    }
  });

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
})();
