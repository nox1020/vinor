(function () {
  'use strict';

  function faDigits(n) {
    return String(n).replace(/\d/g, function (d) {
      return '۰۱۲۳۴۵۶۷۸۹'[d];
    });
  }

  function tsToDate(ts) {
    var value = typeof ts === 'number' ? ts : Number(ts);
    if (!value) return null;
    return String(value).length > 10 ? new Date(value) : new Date(value * 1000);
  }

  function formatTime(ts) {
    var date = tsToDate(ts);
    if (!date || isNaN(date.getTime())) return '';
    return date.toLocaleTimeString('fa-IR', {
      timeZone: 'Asia/Tehran',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function formatDayLabel(ts) {
    var date = tsToDate(ts);
    if (!date || isNaN(date.getTime())) return '';
    var startToday = new Date();
    startToday.setHours(0, 0, 0, 0);
    var startYesterday = new Date(startToday);
    startYesterday.setDate(startYesterday.getDate() - 1);
    if (date >= startToday) return 'امروز';
    if (date >= startYesterday) return 'دیروز';
    return date.toLocaleDateString('fa-IR', {
      timeZone: 'Asia/Tehran',
      month: 'short',
      day: 'numeric'
    });
  }

  function dayKey(ts) {
    var date = tsToDate(ts);
    if (!date || isNaN(date.getTime())) return '';
    return date.toLocaleDateString('en-CA', { timeZone: 'Asia/Tehran' });
  }

  function decorateMessages(list) {
    var prevDay = '';
    return (list || []).map(function (msg, index) {
      var dk = dayKey(msg.created_at);
      var showDaySep = dk && dk !== prevDay;
      if (showDaySep) prevDay = dk;
      return Object.assign({}, msg, {
        showDaySep: showDaySep,
        dayLabel: showDaySep ? formatDayLabel(msg.created_at) : '',
        timeLabel: formatTime(msg.created_at)
      });
    });
  }

  function scrollToBottom() {
    var el = document.getElementById('postchiMessages');
    if (!el) return;
    requestAnimationFrame(function () {
      el.scrollTop = el.scrollHeight;
    });
  }

  function definePostchiPage() {
    if (typeof Alpine === 'undefined') return;
    if (Alpine.data('vinorPostchiPage')) return;

    Alpine.data('vinorPostchiPage', function () {
      return {
        messages: [],
        draft: '',
        loading: false,
        sending: false,
        cfg: window.__VINOR_POSTCHI_CFG__ || {},

        init: function () {
          var seed = this.cfg.seed;
          if (Array.isArray(seed) && seed.length) {
            this.messages = decorateMessages(seed);
            scrollToBottom();
          } else {
            this.fetchMessages();
          }
          this.markOpened();
        },

        markOpened: function () {
          var url = this.cfg.openUrl;
          if (!url) return;
          fetch(url, {
            method: 'POST',
            headers: window.vinorCsrfFetchHeaders
              ? window.vinorCsrfFetchHeaders({ Accept: 'application/json' })
              : { Accept: 'application/json' },
            credentials: 'same-origin'
          })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (d && d.success) {
                try {
                  window.dispatchEvent(new CustomEvent('vinor:notifications:update', {
                    detail: { unread: Number(d.unread_count || 0), notifications: null }
                  }));
                } catch (_) {}
                if (typeof VinorNotifyCenter !== 'undefined') {
                  VinorNotifyCenter.fetchList(true);
                }
              }
            })
            .catch(function () {});
        },

        fetchMessages: function () {
          var self = this;
          var url = this.cfg.messagesUrl;
          if (!url) return;
          this.loading = true;
          fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (d && d.success && Array.isArray(d.messages)) {
                self.messages = decorateMessages(d.messages);
                scrollToBottom();
              }
            })
            .catch(function () {})
            .finally(function () { self.loading = false; });
        },

        send: function () {
          var self = this;
          var text = (this.draft || '').trim();
          if (!text || this.sending) return;
          var url = this.cfg.sendUrl;
          if (!url) return;

          this.sending = true;
          fetch(url, {
            method: 'POST',
            headers: window.vinorCsrfFetchHeaders({
              'Content-Type': 'application/json',
              Accept: 'application/json'
            }),
            credentials: 'same-origin',
            body: JSON.stringify({ message: text })
          })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (d && d.success && d.message) {
                var merged = self.messages.concat(decorateMessages([d.message]));
                self.messages = decorateMessages(
                  merged.map(function (m) {
                    return {
                      id: m.id,
                      role: m.role,
                      body: m.body,
                      action_url: m.action_url,
                      created_at: m.created_at,
                      type: m.type
                    };
                  })
                );
                self.draft = '';
                var input = document.getElementById('postchiInput');
                if (input) input.style.height = '';
                scrollToBottom();
              }
            })
            .catch(function () {})
            .finally(function () { self.sending = false; });
        },

        autosize: function (el) {
          if (!el) return;
          el.style.height = 'auto';
          el.style.height = Math.min(el.scrollHeight, 112) + 'px';
        },

        openAction: function (url) {
          if (!url) return;
          try {
            if (typeof window.vinorExpressNavigate === 'function' && url.indexOf('/express/partner/') === 0) {
              window.vinorExpressNavigate(url, { forward: true });
              return;
            }
          } catch (_) {}
          window.location.href = url;
        }
      };
    });
  }

  document.addEventListener('alpine:init', definePostchiPage);
  if (typeof Alpine !== 'undefined') definePostchiPage();
})();
