(function () {
  var form = document.getElementById('aiChatForm');
  var input = document.getElementById('aiInput');
  var list = document.getElementById('aiMessages');
  var btn = document.getElementById('aiSendBtn');
  if (!form || !input || !list || !btn) return;

  var history = [];
  var chatUrl = form.getAttribute('data-chat-url') || '/ai/api/chat';

  function appendBubble(text, role) {
    var wrap = document.createElement('div');
    wrap.className = 'max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-relaxed ' +
      (role === 'user'
        ? 'mr-auto border border-emerald-500/25 bg-emerald-500/10 text-emerald-100'
        : 'ml-auto border border-white/10 bg-white/5 text-zinc-200');
    wrap.textContent = text;
    list.appendChild(wrap);
    list.scrollTop = list.scrollHeight;
  }

  function csrfToken() {
    var el = form.querySelector('input[name="csrf_token"]');
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var msg = (input.value || '').trim();
    if (!msg) return;

    appendBubble(msg, 'user');
    history.push({ role: 'user', content: msg });
    input.value = '';
    btn.disabled = true;

    try {
      var resp = await fetch(chatUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        credentials: 'same-origin',
        body: JSON.stringify({ message: msg, history: history }),
      });
      var data = await resp.json();
      if (!resp.ok || !data.ok) {
        throw new Error((data && data.error) || 'خطا در دریافت پاسخ');
      }
      appendBubble(data.reply || '', 'assistant');
      history.push({ role: 'assistant', content: data.reply || '' });
    } catch (err) {
      appendBubble(String(err.message || 'خطای ناشناخته'), 'assistant');
    } finally {
      btn.disabled = false;
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
