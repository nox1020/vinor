(function (win) {
  'use strict';

  var SNAPSHOT_ID = 'vnCommFinancialSnapshot';
  var SUMMARY_API = '/express/partner/commissions/summary';
  var lastGoodSnapshot = null;

  function toInt(v) {
    var n = parseInt(String(v == null ? '0' : v).replace(/[^\d-]/g, ''), 10);
    return isNaN(n) ? 0 : Math.max(0, n);
  }

  function toFaDigits(s) {
    var p = '۰۱۲۳۴۵۶۷۸۹';
    return String(s || '').replace(/[0-9]/g, function (d) { return p[parseInt(d, 10)]; });
  }

  function formatToman(n) {
    var v = Math.max(0, toInt(n));
    if (v === 0) return '۰ تومان';
    var raw = String(v);
    var rev = raw.split('').reverse().join('');
    var parts = [];
    for (var i = 0; i < rev.length; i += 3) parts.push(rev.slice(i, i + 3));
    return toFaDigits(parts.join('،').split('').reverse().join('')) + ' تومان';
  }

  function normalizeSnapshot(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var wd = toInt(raw.withdrawable_balance);
    var minWd = Math.max(0, toInt(raw.min_withdrawal_amount || 10000000));
    var canWithdraw = typeof raw.can_withdraw === 'boolean' ? raw.can_withdraw : (wd >= minWd);
    return {
      version: 1,
      withdrawable_balance: wd,
      requestable_balance: toInt(raw.requestable_balance != null ? raw.requestable_balance : wd),
      in_withdrawal_amount: toInt(raw.in_withdrawal_amount),
      in_withdrawal_count: toInt(raw.in_withdrawal_count),
      pending_amount: toInt(raw.pending_amount),
      pending_count: toInt(raw.pending_count),
      total_confirmed_amount: toInt(raw.total_confirmed_amount),
      total_confirmed_count: toInt(raw.total_confirmed_count),
      paid_withdrawal_amount: toInt(
        raw.paid_withdrawal_amount != null ? raw.paid_withdrawal_amount : raw.received_amount
      ),
      paid_withdrawal_count: toInt(
        raw.paid_withdrawal_count != null ? raw.paid_withdrawal_count : raw.received_count
      ),
      min_withdrawal_amount: minWd,
      can_withdraw: canWithdraw,
      generated_at: raw.generated_at || ''
    };
  }

  function isValidSnapshot(s) {
    return !!(s && typeof s === 'object' && s.version === 1 && typeof s.withdrawable_balance === 'number');
  }

  function parseSnapshotFromRoot(root) {
    root = root || document;
    var el = root.getElementById ? root.getElementById(SNAPSHOT_ID) : null;
    if (!el && root.querySelector) el = root.querySelector('#' + SNAPSHOT_ID);
    if (!el) return null;
    try {
      return normalizeSnapshot(JSON.parse(el.textContent || ''));
    } catch (_) {
      return null;
    }
  }

  function updateSnapshotScriptEl(snapshot) {
    var el = document.getElementById(SNAPSHOT_ID);
    if (!el || !isValidSnapshot(snapshot)) return;
    try { el.textContent = JSON.stringify(snapshot); } catch (_) {}
  }

  function setTextIfChanged(el, text) {
    if (!el) return;
    var next = String(text || '');
    if (el.textContent === next) return;
    el.textContent = next;
  }

  function applyFinancialSnapshot(snapshot) {
    var s = normalizeSnapshot(snapshot);
    if (!isValidSnapshot(s)) return false;
    lastGoodSnapshot = s;
    updateSnapshotScriptEl(s);

    var wdText = formatToman(s.withdrawable_balance);

    var mount = document.getElementById('commissionsRefreshMount');
    var scope = mount || document;

    setTextIfChanged(scope.querySelector('[data-comm-withdrawable]'), wdText);

    setTextIfChanged(scope.querySelector('[data-comm-in-withdrawal]'), formatToman(s.in_withdrawal_amount));

    setTextIfChanged(scope.querySelector('[data-comm-pending]'), formatToman(s.pending_amount));

    var dotEl = scope.querySelector('[data-comm-withdraw-dot]');
    if (dotEl) {
      var hasActive = s.in_withdrawal_amount > 0 || s.in_withdrawal_count > 0;
      dotEl.classList.toggle('vn-comm-wd-dot--live', hasActive);
    }

    setTextIfChanged(scope.querySelector('[data-comm-total]'), formatToman(s.total_confirmed_amount));
    var totalCntEl = scope.querySelector('[data-comm-total-count]');
    if (totalCntEl) {
      setTextIfChanged(totalCntEl, toFaDigits(String(s.total_confirmed_count || 0)) + ' پورسانت تأیید شده');
    }

    setTextIfChanged(scope.querySelector('[data-comm-wd-paid]'), formatToman(s.paid_withdrawal_amount));
    var paidCntEl = scope.querySelector('[data-comm-wd-paid-count]');
    if (paidCntEl) {
      var paidCntText = s.paid_withdrawal_count > 0
        ? toFaDigits(String(s.paid_withdrawal_count)) + ' درخواست برداشت پرداخت‌شده'
        : 'هنوز برداشتی پرداخت نشده';
      setTextIfChanged(paidCntEl, paidCntText);
    }

    var wdBtn = scope.querySelector('[data-open-withdraw-modal]');
    if (wdBtn) {
      wdBtn.setAttribute('data-withdrawable-int', String(s.withdrawable_balance));
      var can = s.can_withdraw;
      wdBtn.disabled = !can;
      if (can) {
        wdBtn.removeAttribute('aria-disabled');
        wdBtn.classList.remove('opacity-45', 'cursor-not-allowed');
      } else {
        wdBtn.setAttribute('aria-disabled', 'true');
        wdBtn.classList.add('opacity-45', 'cursor-not-allowed');
      }
    }

    var modalBal = document.getElementById('vnWithdrawModalBalance');
    setTextIfChanged(modalBal, wdText);

    var belowMinEl = scope.querySelector('[data-comm-below-min-note]');
    if (belowMinEl) {
      var showBelow = s.withdrawable_balance > 0 && !s.can_withdraw;
      belowMinEl.classList.toggle('hidden', !showBelow);
      if (showBelow) {
        belowMinEl.textContent = 'کف برداشت ' + formatToman(s.min_withdrawal_amount) + ' است.';
      }
    }

    return true;
  }

  function fetchFinancialSnapshot() {
    return fetch(SUMMARY_API, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      cache: 'no-store'
    }).then(function (res) {
      if (!res.ok) throw new Error('bad_status');
      return res.json();
    }).then(function (j) {
      if (!j || !j.success || !j.snapshot) throw new Error('bad_payload');
      return normalizeSnapshot(j.snapshot);
    });
  }

  function syncFromServer() {
    return fetchFinancialSnapshot().then(function (s) {
      if (!isValidSnapshot(s)) throw new Error('invalid');
      applyFinancialSnapshot(s);
      return s;
    });
  }

  function validateRefreshDoc(doc) {
    if (!doc) return false;
    var next = doc.getElementById('commissionsRefreshMount');
    if (!next || !String(next.innerHTML || '').trim()) return false;
    if (!next.querySelector('[data-comm-withdrawable]')) return false;
    return isValidSnapshot(parseSnapshotFromRoot(doc));
  }

  function bootstrap() {
    var initial = parseSnapshotFromRoot(document);
    if (isValidSnapshot(initial)) {
      lastGoodSnapshot = initial;
      applyFinancialSnapshot(initial);
    }
  }

  win.__vinorCommFinancial = {
    formatToman: formatToman,
    normalize: normalizeSnapshot,
    apply: applyFinancialSnapshot,
    fetch: fetchFinancialSnapshot,
    sync: syncFromServer,
    getLastGood: function () { return lastGoodSnapshot; },
    parseFromRoot: parseSnapshotFromRoot,
    validateRefreshDoc: validateRefreshDoc
  };
  win.__vinorCommFinancialSync = syncFromServer;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
})(window);
