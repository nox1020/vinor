/**
 * Vinor AI — چت + پنل تاریخچه + کارت فایل (همان کارت داشبورد)
 */
(function () {
  'use strict';

  var form = document.getElementById('aiChatForm');
  var input = document.getElementById('aiInput');
  var list = document.getElementById('aiMessages');
  var btn = document.getElementById('aiSendBtn');
  var clearBtn = document.getElementById('aiClearBtn');
  var threadInput = document.getElementById('aiActiveThreadId');
  var historyBtn = document.getElementById('aiHistoryBtn');
  var historyPanel = document.getElementById('aiHistoryPanel');
  var historyBackdrop = document.getElementById('aiHistoryBackdrop');
  var historyClose = document.getElementById('aiHistoryClose');
  var historyList = document.getElementById('aiHistoryList');

  if (!form || !input || !list || !btn) return;

  var chatUrl = form.getAttribute('data-chat-url') || '';
  var historyUrl = form.getAttribute('data-history-url') || '';
  var clearUrl = form.getAttribute('data-clear-url') || '';
  var switchUrl = form.getAttribute('data-switch-url') || '';
  var welcome = list.getAttribute('data-welcome') || 'سلام! من Vinor AI هستم.';

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

  function appendMessage(msg) {
    var role = msg.role || 'assistant';
    var text = (msg.content || '').trim();
    var cardsHtml = buildCardsHtml(msg);

    var wrap = document.createElement('div');
    wrap.className =
      'ai-msg-wrap flex max-w-[92%] flex-col gap-0 ' +
      (role === 'user' ? 'mr-auto items-end' : 'ml-auto items-start');
    wrap.setAttribute('data-role', role);

    if (text) {
      var bubble = document.createElement('div');
      bubble.className =
        'rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap break-words ' +
        (role === 'user'
          ? 'border border-emerald-500/25 bg-emerald-500/10 text-emerald-100'
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
    list.scrollTop = list.scrollHeight;
  }

  function appendBubble(text, role) {
    appendMessage({ role: role, content: text });
  }

  function renderMessages(messages) {
    list.innerHTML = '';
    (messages || []).forEach(function (m) {
      if (m && m.role && (m.content || m.cards_html || (m.land_cards && m.land_cards.length))) {
        appendMessage(m);
      }
    });
    showWelcomeIfEmpty();
    list.scrollTop = list.scrollHeight;
  }

  function showWelcomeIfEmpty() {
    if (list.querySelector('[data-role]')) return;
    appendBubble(welcome, 'assistant');
  }

  function setBusy(on) {
    btn.disabled = !!on;
    input.disabled = !!on;
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

  function renderThreadList(threads) {
    if (!historyList) return;
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

  function openHistory() {
    if (!historyPanel || !historyBackdrop) return;
    historyPanel.classList.add('is-open');
    historyPanel.setAttribute('aria-hidden', 'false');
    historyBackdrop.classList.add('is-open');
    historyBackdrop.setAttribute('aria-hidden', 'false');
    if (historyBtn) historyBtn.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
  }

  function closeHistory() {
    if (!historyPanel || !historyBackdrop) return;
    historyPanel.classList.remove('is-open');
    historyPanel.setAttribute('aria-hidden', 'true');
    historyBackdrop.classList.remove('is-open');
    historyBackdrop.setAttribute('aria-hidden', 'true');
    if (historyBtn) historyBtn.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  async function refreshHistory() {
    if (!historyUrl) return;
    try {
      var url = historyUrl;
      var tid = activeThreadId();
      if (tid) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'thread_id=' + encodeURIComponent(tid);
      var resp = await fetch(url, { credentials: 'same-origin', headers: apiHeaders(false) });
      var data = await resp.json();
      if (data && data.ok) {
        if (data.threads) renderThreadList(data.threads);
      }
    } catch (_) {}
  }

  async function switchThread(threadId) {
    if (!switchUrl || !threadId) return;
    setBusy(true);
    try {
      var resp = await fetch(switchUrl, {
        method: 'POST',
        headers: apiHeaders(true),
        credentials: 'same-origin',
        body: JSON.stringify({ thread_id: threadId }),
      });
      var data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error((data && data.error) || 'خطا');
      setActiveThreadId(data.thread_id);
      renderMessages(data.messages);
      if (data.threads) renderThreadList(data.threads);
      closeHistory();
    } catch (err) {
      alert(err.message || 'خطا');
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  showWelcomeIfEmpty();
  list.querySelectorAll('.ai-msg-wrap').forEach(function (w) {
    initCardsIn(w);
  });
  list.scrollTop = list.scrollHeight;

  if (historyBtn) historyBtn.addEventListener('click', openHistory);
  if (historyClose) historyClose.addEventListener('click', closeHistory);
  if (historyBackdrop) historyBackdrop.addEventListener('click', closeHistory);

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var msg = (input.value || '').trim();
    if (!msg) return;

    appendBubble(msg, 'user');
    input.value = '';
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
        throw new Error((data && data.error) || 'خطا در دریافت پاسخ');
      }
      if (data.thread_id) setActiveThreadId(data.thread_id);
      appendMessage({
        role: 'assistant',
        content: data.reply || '',
        cards_html: data.cards_html,
        land_cards: data.land_cards,
      });
      await refreshHistory();
    } catch (err) {
      appendBubble(String(err.message || 'خطای ناشناخته'), 'assistant');
    } finally {
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

  if (clearBtn && clearUrl) {
    clearBtn.addEventListener('click', async function () {
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
        await refreshHistory();
        closeHistory();
        input.focus();
      } catch (err) {
        alert(err.message || 'خطا');
      }
    });
  }
})();
