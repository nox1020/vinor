/**
 * Vinor AI — چت + منوی کشویی + کارت فایل
 */
(function () {
  'use strict';

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

  if (!form || !input || !list || !btn) return;

  var chatUrl = form.getAttribute('data-chat-url') || '';
  var historyUrl = form.getAttribute('data-history-url') || '';
  var clearUrl = form.getAttribute('data-clear-url') || '';
  var switchUrl = form.getAttribute('data-switch-url') || '';
  var syncUrl = form.getAttribute('data-sync-url') || '';
  var welcome = list.getAttribute('data-welcome') || 'سلام! من Vinor AI هستم.';
  var historyAbort = null;
  var switchAbort = null;
  var syncAbort = null;
  var historyTimer = null;
  var lastThreadsKey = '';
  var lastSyncAt = '';
  var seenEscalationIds = {};
  var emptyPollStreak = 0;
  var pollPaused = false;
  var submitting = false;
  var lastSubmitAt = 0;
  var POLL_MS = 15000;
  var MIN_SUBMIT_GAP_MS = 4000;
  var MIN_MSG_LEN = 2;

  function activeThreadId() {
    return (threadInput && threadInput.value) || '';
  }

  function setActiveThreadId(id) {
    if (threadInput) threadInput.value = id || '';
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

  function buildCardsHtml(msg) {
    if (msg.cards_html) {
      return '<div class="ai-msg-cards w-full min-w-0 max-w-full">' + msg.cards_html + '</div>';
    }
    if (!msg.land_cards || !msg.land_cards.length) return '';
    var inner = msg.land_cards.map(function (c) {
      return c.html || '';
    }).join('');
    if (!inner) return '';
    return (
      '<div class="ai-msg-cards w-full min-w-0 max-w-full">' +
      '<div class="ai-land-cards mt-2.5 flex w-full max-w-full flex-col gap-2.5">' +
      inner +
      '</div></div>'
    );
  }

  function initCardsIn(wrap) {
    if (!wrap) return;
    if (typeof window.vinorInitPremiumCards === 'function') {
      window.vinorInitPremiumCards(wrap, list);
    }
  }

  function messageSeen(msg) {
    var eid = msg.escalation_id || '';
    if (eid) {
      if (seenEscalationIds[eid]) return true;
      seenEscalationIds[eid] = 1;
    }
    var ts = msg.created_at || '';
    if (ts && list.querySelector('.ai-msg-wrap[data-created-at="' + ts + '"]')) {
      return true;
    }
    return false;
  }

  function bumpLastSyncAt(ts) {
    if (ts && (!lastSyncAt || ts > lastSyncAt)) lastSyncAt = ts;
  }

  function scanLastSyncFromDom() {
    var maxTs = '';
    list.querySelectorAll('.ai-msg-wrap[data-created-at]').forEach(function (w) {
      var t = w.getAttribute('data-created-at') || '';
      if (t > maxTs) maxTs = t;
    });
    if (maxTs) lastSyncAt = maxTs;
  }

  function storedMessageCount() {
    return list.querySelectorAll('.ai-msg-wrap[data-created-at]').length;
  }

  function knownEscalationIds() {
    var ids = [];
    list.querySelectorAll('.ai-msg-wrap[data-escalation-id]').forEach(function (w) {
      var id = w.getAttribute('data-escalation-id');
      if (id) ids.push(id);
    });
    return ids;
  }

  function appendMessage(msg) {
    if (messageSeen(msg)) return;
    var role = msg.role || 'assistant';
    var text = (msg.content || '').trim();
    var cardsHtml = buildCardsHtml(msg);
    var isAdmin = msg.source === 'admin_escalation' || (text && text.indexOf('پاسخ تیم وینور') === 0);

    var wrap = document.createElement('div');
    wrap.className =
      'ai-msg-wrap flex max-w-[92%] flex-col gap-0 ' +
      (role === 'user' ? 'mr-auto items-end' : 'ml-auto items-start');
    wrap.setAttribute('data-role', role);
    if (msg.created_at) wrap.setAttribute('data-created-at', msg.created_at);
    if (msg.escalation_id) wrap.setAttribute('data-escalation-id', msg.escalation_id);
    if (isAdmin) wrap.setAttribute('data-admin-reply', '1');

    if (text) {
      var bubble = document.createElement('div');
      bubble.className =
        'rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap break-words ' +
        (role === 'user'
          ? 'border border-emerald-500/25 bg-emerald-500/10 text-emerald-100'
          : isAdmin
            ? 'border border-amber-500/35 bg-amber-500/15 text-amber-50'
            : 'border border-violet-500/20 bg-violet-500/10 text-violet-100');
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
    bumpLastSyncAt(msg.created_at || '');
    list.scrollTop = list.scrollHeight;
  }

  function appendBubble(text, role) {
    appendMessage({ role: role, content: text });
  }

  function renderMessages(messages) {
    list.innerHTML = '';
    seenEscalationIds = {};
    lastSyncAt = '';
    (messages || []).forEach(function (m) {
      if (m && m.role && (m.content || m.cards_html || (m.land_cards && m.land_cards.length))) {
        appendMessage(m);
      }
    });
    showWelcomeIfEmpty();
    scanLastSyncFromDom();
    list.scrollTop = list.scrollHeight;
  }

  function showWelcomeIfEmpty() {
    if (list.querySelector('[data-role]')) return;
    appendBubble(welcome, 'assistant');
  }

  function setBusy(on) {
    btn.disabled = !!on;
    input.disabled = !!on;
    if (newChatBtn) newChatBtn.disabled = !!on;
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
          (t.is_active ? '1' : '0')
        );
      })
      .join('|');
  }

  function renderThreadList(threads) {
    if (!historyList) return;
    var key = threadsCacheKey(threads);
    if (key && key === lastThreadsKey) return;
    lastThreadsKey = key;
    historyList.innerHTML = '';
    if (!threads || !threads.length) {
      historyList.innerHTML =
        '<p class="rounded-xl border border-dashed border-white/10 px-3 py-6 text-center text-xs text-zinc-500">هنوز گفتگویی ذخیره نشده است.</p>';
      return;
    }
    threads.forEach(function (th) {
      var btnEl = document.createElement('button');
      btnEl.type = 'button';
      btnEl.className =
        'ai-thread-item w-full rounded-xl border px-3 py-2.5 text-right transition ' +
        (th.is_active
          ? 'border-violet-500/40 bg-violet-500/15'
          : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.06]');
      btnEl.setAttribute('data-thread-id', th.id);
      btnEl.innerHTML =
        '<div class="flex items-start justify-between gap-2">' +
        '<span class="text-xs font-semibold text-white line-clamp-2 leading-snug">' +
        escapeHtml(th.title || 'گفتگو') +
        '</span>' +
        (th.is_active
          ? '<span class="shrink-0 rounded-full bg-violet-500/30 px-1.5 py-0.5 text-[9px] text-violet-200">فعال</span>'
          : '') +
        '</div>' +
        (th.preview
          ? '<p class="mt-1 text-[10px] text-zinc-500 line-clamp-2 leading-relaxed">' +
            escapeHtml(th.preview) +
            '</p>'
          : '') +
        '<p class="mt-1.5 text-[9px] text-zinc-600 flex items-center justify-between gap-2">' +
        '<span>' +
        (th.message_count || 0) +
        ' پیام</span>' +
        '<time class="tabular-nums">' +
        formatDate(th.updated_at) +
        '</time></p>';
      btnEl.addEventListener('click', function () {
        switchThread(th.id);
      });
      historyList.appendChild(btnEl);
    });
  }

  function openSideMenu() {
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
    if (!sidePanel || !sideBackdrop) return;
    sidePanel.classList.remove('is-open');
    sidePanel.setAttribute('aria-hidden', 'true');
    sideBackdrop.classList.remove('is-open');
    sideBackdrop.setAttribute('aria-hidden', 'true');
    if (menuBtn) menuBtn.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  function applyThreads(threads) {
    if (threads && threads.length) renderThreadList(threads);
  }

  async function refreshHistory(immediate) {
    if (!historyUrl) return;
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
      pollSync();
      closeSideMenu();
    } catch (err) {
      if (err && err.name !== 'AbortError') alert(err.message || 'خطا');
    } finally {
      setBusy(false);
      input.focus();
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
      input.focus();
    } catch (err) {
      alert(err.message || 'خطا');
    } finally {
      setBusy(false);
    }
  }

  async function pollSync() {
    if (!syncUrl || document.hidden || pollPaused) return;
    var tid = activeThreadId();
    if (!tid) return;
    if (syncAbort) syncAbort.abort();
    syncAbort = new AbortController();
    try {
      var url =
        syncUrl +
        (syncUrl.indexOf('?') >= 0 ? '&' : '?') +
        'thread_id=' +
        encodeURIComponent(tid) +
        '&count=' +
        encodeURIComponent(String(storedMessageCount())) +
        '&exclude_esc=' +
        encodeURIComponent(knownEscalationIds().join(','));

      var resp = await fetch(url, {
        credentials: 'same-origin',
        headers: apiHeaders(false),
        signal: syncAbort.signal,
      });
      var data = await resp.json();
      if (!data || !data.ok || !data.messages || !data.messages.length) {
        emptyPollStreak += 1;
        if (emptyPollStreak >= 15) pollPaused = true;
        return;
      }
      emptyPollStreak = 0;
      pollPaused = false;
      var added = false;
      data.messages.forEach(function (m) {
        if (m && m.role && (m.content || m.cards_html)) {
          appendMessage(m);
          added = true;
        }
      });
      if (added) {
        scanLastSyncFromDom();
        list.scrollTop = list.scrollHeight;
      }
    } catch (err) {
      if (err && err.name !== 'AbortError') {
        /* ignore */
      }
    }
  }

  function resumePoll() {
    pollPaused = false;
    emptyPollStreak = 0;
    pollSync();
  }

  showWelcomeIfEmpty();
  list.querySelectorAll('.ai-msg-wrap').forEach(function (w) {
    initCardsIn(w);
    var eid = w.getAttribute('data-escalation-id');
    if (eid) seenEscalationIds[eid] = 1;
  });
  scanLastSyncFromDom();
  list.scrollTop = list.scrollHeight;

  setInterval(pollSync, POLL_MS);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) return;
    resumePoll();
  });

  if (menuBtn) menuBtn.addEventListener('click', openSideMenu);
  if (sideClose) sideClose.addEventListener('click', closeSideMenu);
  if (sideBackdrop) sideBackdrop.addEventListener('click', closeSideMenu);
  if (newChatBtn) newChatBtn.addEventListener('click', startNewChat);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sidePanel && sidePanel.classList.contains('is-open')) {
      closeSideMenu();
    }
  });

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (submitting || btn.disabled) return;
    var msg = (input.value || '').trim();
    if (!msg || msg.length < MIN_MSG_LEN) return;
    var now = Date.now();
    if (lastSubmitAt && now - lastSubmitAt < MIN_SUBMIT_GAP_MS) {
      appendBubble('لطفاً چند ثانیه صبر کنید و دوباره بفرستید.', 'assistant');
      return;
    }

    submitting = true;
    lastSubmitAt = now;
    appendBubble(msg, 'user');
    input.value = '';
    resumePoll();
    setBusy(true);

    try {
      var resp = await fetch(chatUrl, {
        method: 'POST',
        headers: apiHeaders(true),
        credentials: 'same-origin',
        body: JSON.stringify({ message: msg, thread_id: activeThreadId() }),
      });
      var data = null;
      try {
        data = await resp.json();
      } catch (_) {}

      if (!resp.ok || !data || !data.ok) {
        var errText = (data && data.error) || 'خطا در دریافت پاسخ';
        if (data && data.escalated && data.reply) {
          if (data.thread_id) setActiveThreadId(data.thread_id);
          appendMessage({
            role: 'assistant',
            content: data.reply,
            cards_html: data.cards_html,
            land_cards: data.land_cards,
            escalation_id: data.escalation_id,
          });
          if (data.threads) applyThreads(data.threads);
          else await refreshHistory();
          pollSync();
          return;
        }
        throw new Error(errText);
      }
      if (data.thread_id) setActiveThreadId(data.thread_id);
      appendMessage({
        role: 'assistant',
        content: data.reply || '',
        cards_html: data.cards_html,
        land_cards: data.land_cards,
      });
      if (data.threads) {
        lastThreadsKey = '';
        applyThreads(data.threads);
      } else {
        await refreshHistory();
      }
      pollSync();
    } catch (err) {
      var errMsg = String(err.message || 'خطای ناشناخته');
      appendBubble(errMsg, 'assistant');
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
