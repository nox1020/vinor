/**
 * انتخاب شهر — تک‌انتخابی یا چندانتخابی (data-multi-city)
 */
(function (g) {
  'use strict';

  if (g.vinorExpressModalOverlay) { /* ok */ } else {
    var depth = 0;
    g.vinorExpressModalOverlay = {
      open: function () {
        depth++;
        document.documentElement.classList.add('vinor-express-overlay-modal-open');
        document.body.style.overflow = 'hidden';
      },
      close: function () {
        depth = Math.max(0, depth - 1);
        if (!depth) {
          document.documentElement.classList.remove('vinor-express-overlay-modal-open');
          document.body.style.overflow = '';
        }
      }
    };
  }

  var MAJOR = ['تهران', 'کرج', 'اصفهان', 'مشهد', 'شیراز'];
  var closeFns = {};

  function debounce(fn, wait) {
    var t;
    return function () {
      var args = arguments;
      var ctx = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, wait);
    };
  }

  function id(modal, suffix) {
    return (modal.getAttribute('data-cp-prefix') || '') + suffix;
  }

  function el(modal, suffix) {
    return document.getElementById(id(modal, suffix));
  }

  function rowValue(row) {
    if (!row) return null;
    return row.getAttribute('data-city-row');
  }

  function isMulti(modal) {
    return modal.getAttribute('data-multi-city') === '1';
  }

  function allCitiesLabel(modal, trigger) {
    var n = 0;
    if (trigger) {
      n = parseInt(trigger.getAttribute('data-cities-count') || '0', 10);
    }
    if (!n) {
      n = parseInt(modal.getAttribute('data-cities-count') || '0', 10);
    }
    if (n > 0) return n + ' شهر';
    return 'همه شهرها';
  }

  function parseHiddenValue(raw, multi) {
    var s = (raw || '').trim();
    if (!s) return multi ? [] : '';
    if (!multi) return s;
    return s.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
  }

  function joinHiddenValue(pending, multi) {
    if (multi) {
      return Array.isArray(pending) ? pending.join(',') : '';
    }
    return pending || '';
  }

  function formatTriggerLabel(modal, pending, trigger, emptyLabel) {
    var multi = isMulti(modal);
    var allowAll = modal.getAttribute('data-allow-all') === '1';
    if (multi) {
      var arr = Array.isArray(pending) ? pending : [];
      if (!arr.length) return allCitiesLabel(modal, trigger);
      if (arr.length === 1) return arr[0];
      return arr.length + ' شهر';
    }
    if (!pending) {
      return allowAll ? allCitiesLabel(modal, trigger) : emptyLabel;
    }
    return pending;
  }

  function setRowSelected(row, on) {
    if (!row) return;
    row.classList.toggle('is-selected', on);
    var name = row.querySelector('.city-picker-name');
    var mark = row.querySelector('.city-picker-mark');
    if (name) {
      name.classList.toggle('text-emerald-400', on);
      name.classList.toggle('text-white', !on);
    }
    if (mark) {
      if (on && !mark.querySelector('.fa-check')) {
        var ok = document.createElement('i');
        ok.className = 'fas fa-check text-emerald-500';
        ok.setAttribute('aria-hidden', 'true');
        mark.appendChild(ok);
      } else if (!on) {
        while (mark.firstChild) mark.removeChild(mark.firstChild);
      }
    }
  }

  function pendingIncludes(pending, value, multi) {
    if (multi) {
      return Array.isArray(pending) && pending.indexOf(value) >= 0;
    }
    return pending === value;
  }

  function updateSelection(modal, pending) {
    var multi = isMulti(modal);
    var list = el(modal, 'List');
    if (list) {
      list.querySelectorAll('[data-city-row]').forEach(function (row) {
        var val = rowValue(row);
        var on;
        if (multi) {
          if (val === '') {
            on = !pending || !pending.length;
          } else {
            on = pendingIncludes(pending, val, true);
          }
        } else {
          on = pendingIncludes(pending, val, false);
        }
        setRowSelected(row, on);
      });
    }
    var chips = el(modal, 'Chips');
    if (chips) {
      chips.querySelectorAll('[data-city-chip]').forEach(function (chip) {
        var v = chip.getAttribute('data-city-chip') || '';
        var on = multi ? pendingIncludes(pending, v, true) : pending === v;
        chip.classList.toggle('border-emerald-500', on);
        chip.classList.toggle('bg-emerald-500/15', on);
        chip.classList.toggle('text-emerald-300', on);
      });
    }
    var cur = el(modal, 'CurrentLabel');
    var trigger = document.getElementById(modal.getAttribute('data-trigger-id') || '');
    var emptyLabel = modal.getAttribute('data-empty-label') || 'انتخاب شهر';
    if (cur) {
      cur.textContent = formatTriggerLabel(modal, pending, trigger, emptyLabel);
    }
  }

  function filterList(modal, query) {
    var list = el(modal, 'List');
    var empty = el(modal, 'Empty');
    if (!list) return;
    var q = (query || '').trim();
    var allowAll = modal.getAttribute('data-allow-all') === '1';
    var visible = 0;
    list.querySelectorAll('[data-city-row]').forEach(function (row) {
      var val = rowValue(row);
      var label = (row.querySelector('.city-picker-name') || {}).textContent || val || '';
      var match = !q || label.indexOf(q) >= 0 || (val && val.indexOf(q) >= 0);
      if (allowAll && val === '' && 'همه شهرها'.indexOf(q) >= 0) match = true;
      row.classList.toggle('hidden', !match);
      if (match) visible++;
    });
    if (empty) empty.classList.toggle('hidden', visible > 0);
  }

  function firstMajor(modal) {
    var list = el(modal, 'List');
    if (!list) return '';
    for (var i = 0; i < MAJOR.length; i++) {
      var rows = list.querySelectorAll('[data-city-row]');
      for (var j = 0; j < rows.length; j++) {
        if (rowValue(rows[j]) === MAJOR[i]) return MAJOR[i];
      }
    }
    var all = list.querySelectorAll('[data-city-row]');
    for (var k = 0; k < all.length; k++) {
      var v = rowValue(all[k]);
      if (v) return v;
    }
    return '';
  }

  function isValidCity(modal, value) {
    if (value === '') return modal.getAttribute('data-allow-all') === '1';
    var list = el(modal, 'List');
    if (!list) return false;
    var rows = list.querySelectorAll('[data-city-row]');
    for (var i = 0; i < rows.length; i++) {
      if (rowValue(rows[i]) === value) return true;
    }
    return false;
  }

  function isValidSelection(modal, pending) {
    var multi = isMulti(modal);
    if (multi) {
      var arr = Array.isArray(pending) ? pending : [];
      if (!arr.length) return modal.getAttribute('data-allow-all') === '1';
      for (var i = 0; i < arr.length; i++) {
        if (!isValidCity(modal, arr[i])) return false;
      }
      return true;
    }
    return isValidCity(modal, pending);
  }

  function initPicker(modal) {
    if (modal.getAttribute('data-cp-ready') === '1') return;
    modal.setAttribute('data-cp-ready', '1');

    var overlay = g.vinorExpressModalOverlay;
    var multi = isMulti(modal);
    var pending = multi ? [] : '';
    var hidden = document.getElementById(modal.getAttribute('data-hidden-id') || '');
    var label = document.getElementById(modal.getAttribute('data-label-id') || '');
    var trigger = document.getElementById(modal.getAttribute('data-trigger-id') || '');
    var triggerText = document.getElementById(modal.getAttribute('data-trigger-text-id') || '');
    var form = document.getElementById(modal.getAttribute('data-form-id') || '');
    var applySubmit = modal.getAttribute('data-apply-submit') === '1';
    var emptyLabel = modal.getAttribute('data-empty-label') || 'انتخاب شهر';

    var closeBtn = el(modal, 'Close');
    var backdrop = modal.querySelector('[data-city-modal-backdrop]');
    var search = el(modal, 'Search');
    var applyBtn = el(modal, 'Apply');
    var geoQuick = el(modal, 'GeoQuick');
    var list = el(modal, 'List');
    var chips = el(modal, 'Chips');

    function readHidden() {
      return parseHiddenValue(hidden ? hidden.value : '', multi);
    }

    function setPendingSingle(c) {
      var x = c == null ? '' : String(c).trim();
      if (!isValidCity(modal, x)) return;
      pending = x;
      updateSelection(modal, pending);
    }

    function togglePendingCity(c) {
      var x = String(c || '').trim();
      if (x === '') {
        pending = [];
        updateSelection(modal, pending);
        return;
      }
      if (!isValidCity(modal, x)) return;
      if (!Array.isArray(pending)) pending = [];
      var idx = pending.indexOf(x);
      if (idx >= 0) {
        pending.splice(idx, 1);
      } else {
        pending.push(x);
      }
      updateSelection(modal, pending);
    }

    function openPicker() {
      pending = readHidden();
      if (search) search.value = '';
      modal.classList.remove('hidden');
      modal.setAttribute('aria-hidden', 'false');
      if (trigger) trigger.setAttribute('aria-expanded', 'true');
      overlay.open();
      filterList(modal, '');
      updateSelection(modal, pending);
    }

    function closePicker() {
      pending = readHidden();
      if (search) search.value = '';
      modal.classList.add('hidden');
      modal.setAttribute('aria-hidden', 'true');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
      overlay.close();
      filterList(modal, '');
    }

    function applyPicker() {
      if (!isValidSelection(modal, pending)) return;
      var v = joinHiddenValue(pending, multi);
      if (hidden) hidden.value = v;
      var display = formatTriggerLabel(modal, pending, trigger, emptyLabel);
      if (label) label.textContent = display;
      if (triggerText) {
        triggerText.textContent = display;
        triggerText.classList.toggle('text-zinc-500', multi ? !pending.length : !pending);
      }
      closePicker();
      if (applySubmit && form) form.submit();
      try {
        document.dispatchEvent(new CustomEvent('vinor:city-picker-applied', {
          detail: { hiddenId: hidden ? hidden.id : '', value: v }
        }));
      } catch (_) {}
    }

    closeFns[modal.id] = closePicker;
    modal._cpOpen = openPicker;
    if (closeBtn) closeBtn.addEventListener('click', closePicker);
    if (backdrop) backdrop.addEventListener('click', closePicker);
    if (applyBtn) applyBtn.addEventListener('click', applyPicker);

    if (search) {
      search.addEventListener('input', debounce(function () {
        filterList(modal, search.value);
      }, 120));
      search.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        var q = (search.value || '').trim();
        var allowAll = modal.getAttribute('data-allow-all') === '1';
        if (allowAll && !q) {
          if (multi) togglePendingCity('');
          else setPendingSingle('');
          e.preventDefault();
          return;
        }
        if (q && isValidCity(modal, q)) {
          if (multi) togglePendingCity(q);
          else setPendingSingle(q);
          e.preventDefault();
          return;
        }
        if (!list) return;
        var shown = list.querySelectorAll('[data-city-row]:not(.hidden)');
        if (shown.length === 1) {
          var v = rowValue(shown[0]);
          if (multi) togglePendingCity(v);
          else setPendingSingle(v);
          e.preventDefault();
        }
      });
    }

    if (list) {
      list.addEventListener('click', function (e) {
        var row = e.target && e.target.closest && e.target.closest('[data-city-row]');
        if (!row || row.classList.contains('hidden')) return;
        var v = rowValue(row);
        if (multi) togglePendingCity(v);
        else setPendingSingle(v);
      });
    }

    if (chips) {
      chips.addEventListener('click', function (e) {
        var chip = e.target && e.target.closest && e.target.closest('[data-city-chip]');
        if (!chip) return;
        var v = chip.getAttribute('data-city-chip') || '';
        if (multi) togglePendingCity(v);
        else setPendingSingle(v);
      });
    }

    if (geoQuick) {
      geoQuick.addEventListener('click', function () {
        var pick = firstMajor(modal);
        if (!pick) return;
        if (multi) togglePendingCity(pick);
        else setPendingSingle(pick);
      });
    }
  }

  function boot() {
    document.querySelectorAll('[data-city-picker-root]').forEach(function (modal) {
      var trigger = document.getElementById(modal.getAttribute('data-trigger-id') || '');
      if (!trigger || trigger.getAttribute('data-cp-bound') === '1') return;
      trigger.setAttribute('data-cp-bound', '1');
      trigger.addEventListener('click', function () {
        initPicker(modal);
        if (modal._cpOpen) modal._cpOpen();
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  document.addEventListener('vinor:express-page-swap', boot);
  document.addEventListener('vinor:city-picker-reinit', boot);

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('[data-city-picker-root]').forEach(function (modal) {
      if (!modal.classList.contains('hidden') && closeFns[modal.id]) {
        closeFns[modal.id]();
        e.preventDefault();
      }
    });
  });
})(window);
