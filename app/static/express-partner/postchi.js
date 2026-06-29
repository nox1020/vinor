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

  function postchiRoot() {
    return document.querySelector('[data-vinor-postchi-page]');
  }

  function messagesEl() {
    return document.getElementById('postchiMessages');
  }

  function readPostchiCfg(root) {
    root = root || postchiRoot();
    if (root) {
      try {
        var raw = root.getAttribute('data-postchi-config');
        if (raw) return JSON.parse(raw);
      } catch (_) {}
    }
    return window.__VINOR_POSTCHI_CFG__ || {};
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
      window.vinorPostchiBoot();
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
        cfg: {},
        _hydrated: false,
        _opened: false,

        loadCfg: function () {
          this.cfg = readPostchiCfg(this.$root);
          return this.cfg;
        },

        hydrate: function () {
          this.loadCfg();
          var seed = this.cfg.seed;
          if (Array.isArray(seed) && seed.length) {
            this.messages = decorateMessages(seed.map(stripMessage));
            this._hydrated = true;
            var self = this;
            this.$nextTick(function () {
              bindPostchiResizePin();
              pinToLatestSoon();
            });
            return;
          }
          if (!this._hydrated && !this.loading) {
            this.fetchMessages();
          }
        },

        setMessages: function (list) {
          this.messages = decorateMessages((list || []).map(stripMessage));
          this._hydrated = true;
          var self = this;
          this.$nextTick(function () {
            bindPostchiResizePin();
            pinToLatestSoon();
          });
        },

        init: function () {
          bindPostchiPageSwapScroll();
          this.hydrate();
          this.markOpened();
        },

        markOpened: function () {
          if (this._opened) return;
          this.loadCfg();
          var url = this.cfg.openUrl;
          if (!url) return;
          this._opened = true;
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
            .catch(function () {
              this._opened = false;
            }.bind(this));
        },

        fetchMessages: function () {
          var self = this;
          this.loadCfg();
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

  window.vinorPostchiBoot = function vinorPostchiBoot() {
    definePostchiPage();
    var root = postchiRoot();
    if (!root || typeof Alpine === 'undefined') return;

    if (!root._x_dataStack || !root._x_dataStack.length) {
      if (typeof Alpine.initTree === 'function') {
        Alpine.initTree(root);
      }
      return;
    }

    try {
      var state = Alpine.$data(root);
      if (state) {
        state._hydrated = false;
        if (typeof state.hydrate === 'function') state.hydrate();
      }
    } catch (_) {}
  };

  document.addEventListener('alpine:init', definePostchiPage);
  if (typeof Alpine !== 'undefined') definePostchiPage();
})();
