/**
 * انتخاب تاریخ تولد — چرخ اسکرول سه‌ستونه (سبک تلگرام)، تقویم جلالی
 */
(function (g) {
  'use strict';

  var ITEM_H = 44;
  var YEAR_MIN = 1320;
  var YEAR_MAX = 1393;
  var MONTHS = [
    'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
    'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'
  ];
  var LEAP_REMAINDERS = { 1: 1, 5: 1, 9: 1, 13: 1, 17: 1, 22: 1, 26: 1, 30: 1 };

  var modal = null;
  var panel = null;
  var hiddenInput = null;
  var triggerText = null;
  var wheels = { day: null, month: null, year: null };
  var pending = { day: 1, month: 1, year: 1370 };
  var committed = { day: 0, month: 0, year: 0, raw: '' };
  var scrollTimer = null;
  var inited = false;

  function toFa(n) {
    return String(n).replace(/[0-9]/g, function (d) {
      return '۰۱۲۳۴۵۶۷۸۹'[parseInt(d, 10)];
    });
  }

  function isLeapYear(y) {
    return !!LEAP_REMAINDERS[y % 33];
  }

  function daysInMonth(month, year) {
    if (month <= 6) return 31;
    if (month <= 11) return 30;
    return isLeapYear(year) ? 30 : 29;
  }

  function parseBirth(raw) {
    var s = String(raw || '').trim();
    if (!s) return { day: 0, month: 0, year: 0, raw: '' };
    var parts = s.split('/').map(function (p) { return parseInt(p.trim(), 10); }).filter(function (n) { return !isNaN(n); });
    var y = parts[0] || 0;
    var m = parts[1] || 1;
    var d = parts[2] || 1;
    if (y && !parts[1] && !parts[2]) {
      m = 1;
      d = 1;
    }
    if (y < YEAR_MIN) y = YEAR_MIN;
    if (y > YEAR_MAX) y = YEAR_MAX;
    if (m < 1) m = 1;
    if (m > 12) m = 12;
    var maxD = daysInMonth(m, y);
    if (d < 1) d = 1;
    if (d > maxD) d = maxD;
    return { day: d, month: m, year: y, raw: y + '/' + m + '/' + d };
  }

  function formatDisplay(parsed) {
    if (!parsed || !parsed.year) return '';
    var mName = MONTHS[parsed.month - 1] || '';
    return toFa(parsed.day) + ' ' + mName + ' ' + toFa(parsed.year);
  }

  function formatValue(parsed) {
    if (!parsed || !parsed.year) return '';
    return String(parsed.year) + '/' + String(parsed.month) + '/' + String(parsed.day);
  }

  function updateTriggerText() {
    if (!triggerText) return;
    var label = formatDisplay(committed);
    triggerText.textContent = label || 'انتخاب کنید';
    triggerText.classList.toggle('text-zinc-500', !label);
  }

  function wheelInner(col) {
    return col && col.querySelector('.tg-birth-wheel-inner');
  }

  function buildWheel(col, type, values, activeValue, labelFn) {
    if (!col) return;
    col.innerHTML = '';
    var inner = document.createElement('div');
    inner.className = 'tg-birth-wheel-inner flex flex-col';
    inner.appendChild(spacer());
    values.forEach(function (v) {
      var item = document.createElement('div');
      item.className = 'tg-birth-wheel-item';
      item.setAttribute('data-wheel-value', String(v));
      if (type === 'month') item.setAttribute('data-wheel-month', '1');
      item.textContent = labelFn ? labelFn(v) : toFa(v);
      if (v === activeValue) item.classList.add('is-active');
      inner.appendChild(item);
    });
    inner.appendChild(spacer());
    col.appendChild(inner);
    scrollToValue(col, activeValue, false);
  }

  function spacer() {
    var el = document.createElement('div');
    el.className = 'tg-birth-wheel-spacer';
    el.setAttribute('aria-hidden', 'true');
    return el;
  }

  function yearValues() {
    var out = [];
    for (var y = YEAR_MAX; y >= YEAR_MIN; y--) out.push(y);
    return out;
  }

  function monthValues() {
    var out = [];
    for (var m = 1; m <= 12; m++) out.push(m);
    return out;
  }

  function dayValues(month, year) {
    var max = daysInMonth(month, year);
    var out = [];
    for (var d = 1; d <= max; d++) out.push(d);
    return out;
  }

  function scrollToValue(col, value, smooth) {
    var inner = wheelInner(col);
    if (!inner) return;
    var item = inner.querySelector('[data-wheel-value="' + value + '"]');
    if (!item) return;
    var top = item.offsetTop - (col.clientHeight / 2) + (ITEM_H / 2);
    col.scrollTo({ top: top, behavior: smooth ? 'smooth' : 'auto' });
    refreshActive(col);
  }

  function readWheelValue(col) {
    var inner = wheelInner(col);
    if (!inner) return 0;
    var items = inner.querySelectorAll('.tg-birth-wheel-item');
    if (!items.length) return 0;
    var center = col.scrollTop + col.clientHeight / 2;
    var best = null;
    var bestDist = Infinity;
    items.forEach(function (item) {
      var itemCenter = item.offsetTop + ITEM_H / 2;
      var dist = Math.abs(itemCenter - center);
      if (dist < bestDist) {
        bestDist = dist;
        best = item;
      }
    });
    return best ? parseInt(best.getAttribute('data-wheel-value') || '0', 10) : 0;
  }

  function refreshActive(col) {
    var inner = wheelInner(col);
    if (!inner) return;
    var items = inner.querySelectorAll('.tg-birth-wheel-item');
    if (!items.length) return;
    var center = col.scrollTop + col.clientHeight / 2;
    items.forEach(function (item) {
      var itemCenter = item.offsetTop + ITEM_H / 2;
      var active = Math.abs(itemCenter - center) < ITEM_H / 2;
      item.classList.toggle('is-active', active);
    });
  }

  function syncPendingFromWheels() {
    pending.year = readWheelValue(wheels.year) || pending.year;
    pending.month = readWheelValue(wheels.month) || pending.month;
    var days = dayValues(pending.month, pending.year);
    pending.day = readWheelValue(wheels.day) || pending.day;
    if (pending.day > days.length) pending.day = days.length;
    if (days.indexOf(pending.day) < 0) pending.day = days[0];
  }

  function rebuildDayWheel(keepDay) {
    var days = dayValues(pending.month, pending.year);
    if (keepDay && pending.day > days.length) pending.day = days.length;
    buildWheel(wheels.day, 'day', days, pending.day, function (v) { return toFa(v); });
  }

  function rebuildAllWheels() {
    buildWheel(wheels.year, 'year', yearValues(), pending.year, function (v) { return toFa(v); });
    buildWheel(wheels.month, 'month', monthValues(), pending.month, function (v) { return MONTHS[v - 1]; });
    rebuildDayWheel(true);
  }

  function onWheelScroll(col) {
    refreshActive(col);
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(function () {
      syncPendingFromWheels();
      if (col === wheels.month || col === wheels.year) {
        var prevDay = pending.day;
        rebuildDayWheel(true);
        scrollToValue(wheels.day, pending.day, true);
      }
      snapWheel(col);
    }, 80);
  }

  function snapWheel(col) {
    var val = readWheelValue(col);
    if (val) scrollToValue(col, val, true);
  }

  function openModal() {
    if (!modal || !panel) return;
    pending = {
      day: committed.day || 1,
      month: committed.month || 1,
      year: committed.year || 1370
    };
    if (!committed.year) {
      pending.year = 1370;
      pending.month = 1;
      pending.day = 1;
    }
    rebuildAllWheels();
    if (typeof g.hoistVinorExpressBodyModals === 'function') g.hoistVinorExpressBodyModals();
    modal.classList.remove('hidden');
    modal.classList.add('birth-date-picker-modal--open');
    modal.setAttribute('aria-hidden', 'false');
    if (g.vinorExpressModalOverlay) g.vinorExpressModalOverlay.open();
  }

  function closeModal() {
    if (!modal || !panel) return;
    modal.classList.remove('birth-date-picker-modal--open');
    window.setTimeout(function () {
      modal.classList.add('hidden');
    }, 280);
    modal.setAttribute('aria-hidden', 'true');
    if (g.vinorExpressModalOverlay) g.vinorExpressModalOverlay.close();
  }

  function commitSelection() {
    syncPendingFromWheels();
    committed = {
      day: pending.day,
      month: pending.month,
      year: pending.year,
      raw: formatValue(pending)
    };
    if (hiddenInput) hiddenInput.value = committed.raw;
    updateTriggerText();
    closeModal();
    try {
      document.dispatchEvent(new CustomEvent('vinor:birth-date-applied', {
        detail: { value: committed.raw, display: formatDisplay(committed) }
      }));
    } catch (_) {}
  }

  function clearSelection() {
    committed = { day: 0, month: 0, year: 0, raw: '' };
    if (hiddenInput) hiddenInput.value = '';
    updateTriggerText();
    closeModal();
    try {
      document.dispatchEvent(new CustomEvent('vinor:birth-date-applied', { detail: { value: '', display: '' } }));
    } catch (_) {}
  }

  function applyExternalValue(raw) {
    committed = parseBirth(raw);
    committed.raw = committed.year ? formatValue(committed) : '';
    if (hiddenInput) hiddenInput.value = committed.raw;
    updateTriggerText();
  }

  function bindWheel(col) {
    if (!col || col.getAttribute('data-wheel-bound') === '1') return;
    col.setAttribute('data-wheel-bound', '1');
    col.addEventListener('scroll', function () { onWheelScroll(col); }, { passive: true });
  }

  function initDom() {
    modal = document.getElementById('birthDatePickerModal');
    if (!modal) return false;
    panel = document.getElementById('birthDatePickerPanel');
    hiddenInput = document.getElementById('profileBirth');
    triggerText = document.getElementById('profileBirthTriggerText');
    wheels.day = document.getElementById('birthWheelDay');
    wheels.month = document.getElementById('birthWheelMonth');
    wheels.year = document.getElementById('birthWheelYear');

    var trigger = document.getElementById('profileBirthTrigger');
    var closeBtn = document.getElementById('birthDatePickerClose');
    var confirmBtn = document.getElementById('birthDatePickerConfirm');
    var clearBtn = document.getElementById('birthDatePickerClear');
    var backdrop = modal.querySelector('[data-birth-modal-backdrop]');

    bindWheel(wheels.day);
    bindWheel(wheels.month);
    bindWheel(wheels.year);

    if (trigger && trigger.getAttribute('data-birth-trigger-bound') !== '1') {
      trigger.setAttribute('data-birth-trigger-bound', '1');
      trigger.addEventListener('click', openModal);
    }
    if (closeBtn && closeBtn.getAttribute('data-birth-close-bound') !== '1') {
      closeBtn.setAttribute('data-birth-close-bound', '1');
      closeBtn.addEventListener('click', closeModal);
    }
    if (backdrop && backdrop.getAttribute('data-birth-backdrop-bound') !== '1') {
      backdrop.setAttribute('data-birth-backdrop-bound', '1');
      backdrop.addEventListener('click', closeModal);
    }
    if (confirmBtn && confirmBtn.getAttribute('data-birth-confirm-bound') !== '1') {
      confirmBtn.setAttribute('data-birth-confirm-bound', '1');
      confirmBtn.addEventListener('click', commitSelection);
    }
    if (clearBtn && clearBtn.getAttribute('data-birth-clear-bound') !== '1') {
      clearBtn.setAttribute('data-birth-clear-bound', '1');
      clearBtn.addEventListener('click', clearSelection);
    }

    if (hiddenInput && hiddenInput.value) {
      applyExternalValue(hiddenInput.value);
    } else {
      updateTriggerText();
    }
    return true;
  }

  function boot() {
    if (!document.getElementById('birthDatePickerModal')) return;
    initDom();
    inited = true;
  }

  g.vinorBirthDatePickerApplyFromServer = function (raw) {
    if (!inited) boot();
    applyExternalValue(raw || '');
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
  document.addEventListener('vinor:express-page-swap', boot);

  if (!g.__vinorBirthPickerEscBound) {
    g.__vinorBirthPickerEscBound = true;
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (modal && modal.classList.contains('birth-date-picker-modal--open')) {
        e.preventDefault();
        closeModal();
      }
    });
  }
})(window);
