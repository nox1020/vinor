(function () {
  'use strict';

  function formatTime(ts) {
    var value = typeof ts === 'number' ? ts : Number(ts);
    if (!value) return '';
    var date = String(value).length > 10 ? new Date(value) : new Date(value * 1000);
    if (isNaN(date.getTime())) return '';
    return date.toLocaleTimeString('fa-IR', {
      timeZone: 'Asia/Tehran',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function formatDayLabel(ts) {
    var value = typeof ts === 'number' ? ts : Number(ts);
    if (!value) return '';
    var date = String(value).length > 10 ? new Date(value) : new Date(value * 1000);
    if (isNaN(date.getTime())) return '';
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
    var value = typeof ts === 'number' ? ts : Number(ts);
    if (!value) return '';
    var date = String(value).length > 10 ? new Date(value) : new Date(value * 1000);
    if (isNaN(date.getTime())) return '';
    return date.toLocaleDateString('en-CA', { timeZone: 'Asia/Tehran' });
  }

  function stripMessage(msg) {
    return {
      id: msg.id,
      role: msg.role,
      body: msg.body,
      action_url: msg.action_url,
      created_at: msg.created_at,
      type: msg.type
    };
  }

  function decorateMessages(list) {
    var prevDay = '';
    return (list || []).map(function (msg) {
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

  function messagesEl() {
    return document.getElementById('postchiMessages');
  }

  function isPinnedToLatest(el) {
    el = el || messagesEl();
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 56;
  }

  function pinToLatest(el) {
    el = el || messagesEl();
    if (!el) return;

    function snap() {
      el.scrollTop = el.scrollHeight;
      var anchor = document.getElementById('postchiScrollAnchor');
      if (!anchor) return;
      try {
        anchor.scrollIntoView({ block: 'end', behavior: 'instant' });
      } catch (_) {
        try { anchor.scrollIntoView(false); } catch (_e) {}
      }
    }

    snap();
    requestAnimationFrame(function () {
      snap();
      requestAnimationFrame(snap);
    });
  }

  function pinToLatestSoon() {
    pinToLatest();
    setTimeout(function () { pinToLatest(); }, 40);
    setTimeout(function () { pinToLatest(); }, 140);
  }

  var postchiResizeObserver = null;
  var postchiResizeTarget = null;

  function bindPostchiResizePin(el) {
    el = el || messagesEl();
    if (!el || typeof ResizeObserver === 'undefined') return;
    if (postchiResizeTarget === el && postchiResizeObserver) return;
    if (postchiResizeObserver) {
      try { postchiResizeObserver.disconnect(); } catch (_) {}
    }
    postchiResizeTarget = el;
    postchiResizeObserver = new ResizeObserver(function () {
      if (isPinnedToLatest(el)) pinToLatest(el);
    });
    postchiResizeObserver.observe(el);
  }

  var pageSwapScrollBound = false;

  function bindPostchiPageSwapScroll() {
    if (pageSwapScrollBound) return;
    pageSwapScrollBound = true;
    window.addEventListener('vinor:express-page-swap', function () {
      if (!messagesEl()) return;
      pinToLatestSoon();
    });
  }

  function definePostchiPage() {
    if (typeof Alpine === 'undefined') return;
    if (Alpine.data('vinorPostchiPage')) return;

    Alpine.data('vinorPostchiPage', function () {
      return {
        messages: [],
        loading: false,
        cfg: window.__VINOR_POSTCHI_CFG__ || {},

        setMessages: function (list) {
          this.messages = decorateMessages((list || []).map(stripMessage));
          var self = this;
          this.$nextTick(function () {
            bindPostchiResizePin();
            pinToLatestSoon();
          });
        },

        init: function () {
          bindPostchiPageSwapScroll();
          var seed = this.cfg.seed;
          if (Array.isArray(seed) && seed.length) {
            this.setMessages(seed);
          } else {
            this.fetchMessages();
          }
          this.markOpened();
          var self = this;
          this.$nextTick(function () {
            bindPostchiResizePin();
            pinToLatestSoon();
          });
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
                self.setMessages(d.messages);
              }
            })
            .catch(function () {})
            .finally(function () { self.loading = false; });
        }
      };
    });
  }

  document.addEventListener('alpine:init', definePostchiPage);
  if (typeof Alpine !== 'undefined') definePostchiPage();
})();
