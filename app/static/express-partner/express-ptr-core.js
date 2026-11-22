/**
 * هستهٔ مشترک pull-to-refresh وینور (وب و WebView اپ).
 *
 * قواعد تا رفرش با اسکرول عمودی دعوا نکند:
 *  - فقط وقتی شروع می‌شود که صفحه بالای بالا باشد و هیچ ظرف اسکرول داخلیِ زیر انگشت (لیست، مودال، شیت، چت)
 *    به پایین اسکرول نشده باشد؛ وگرنه کشیدن به پایین یعنی «اسکرول به بالا» نه رفرش.
 *  - قفل محور: اولین حرکت ≥ SLOP تعیین می‌کند؛ افقی (کاروسل، تب، کشو) یا رو به بالا = لغو.
 *  - فاصلهٔ فعلی ملاک است نه بیشینه: کشیدن و برگرداندن انگشت رفرش نمی‌کند.
 *  - روی ورودی‌ها، مودال/شیت باز، لایه‌های fixed (شیت/کشو/نوار) و [data-vinor-ptr-ignore] شروع نمی‌شود.
 *  - همهٔ شنونده‌ها passive هستند؛ اسکرول مرورگر هرگز مسدود نمی‌شود.
 */
(function (root) {
  'use strict';
  if (root.VinorPtr && root.VinorPtr.version >= 2) return;

  var TRIGGER = 72;
  var SHOW = 40;
  var SLOP = 10;
  var TOP_EPS = 2;
  var AXIS_RATIO = 1.2;

  var IGNORE_SELECTOR = [
    'input', 'textarea', 'select', '[contenteditable=""]', '[contenteditable="true"]',
    '[data-vinor-ptr-ignore]', '[data-vinor-ptr="off"]',
    '[role="dialog"]', '[aria-modal="true"]', '.leaflet-container', '.ai-composer'
  ].join(',');

  function docScrollTop() {
    try {
      var se = document.scrollingElement || document.documentElement;
      return Math.max(
        root.scrollY || 0, root.pageYOffset || 0,
        se ? se.scrollTop || 0 : 0,
        document.documentElement ? document.documentElement.scrollTop || 0 : 0,
        document.body ? document.body.scrollTop || 0 : 0
      );
    } catch (_) { return 0; }
  }

  /** یکی از اجداد هدف (تا boundary) خودش اسکرول شده است؟ */
  function innerScrolled(target, boundary) {
    var el = target && target.nodeType === 1 ? target : (target && target.parentElement) || null;
    while (el && el !== boundary && el !== document.body && el !== document.documentElement) {
      if ((el.scrollTop || 0) > 0) return true;
      el = el.parentElement;
    }
    return false;
  }

  function ignoredTarget(target) {
    try {
      var el = target && target.nodeType === 1 ? target : (target && target.parentElement);
      return !!(el && el.closest && el.closest(IGNORE_SELECTOR));
    } catch (_) { return false; }
  }

  /** لمس داخل لایهٔ fixed (شیت، مودال، کشو، هدر، نوار پایین) که ظرف اصلی را در بر ندارد → رفرشِ صفحهٔ پشت نه. */
  function inFixedLayer(target, scrollRoot) {
    var el = target && target.nodeType === 1 ? target : (target && target.parentElement) || null;
    while (el && el !== document.body && el !== document.documentElement) {
      if (scrollRoot && el === scrollRoot) return false;
      try {
        if (root.getComputedStyle(el).position === 'fixed') {
          return !(scrollRoot && el.contains(scrollRoot));
        }
      } catch (_) { return false; }
      el = el.parentElement;
    }
    return false;
  }

  function overlayOpen() {
    try {
      var de = document.documentElement;
      return de.classList.contains('vinor-express-overlay-modal-open') || de.hasAttribute('data-vinor-ptr-lock');
    } catch (_) { return false; }
  }

  /**
   * opts: target (شنوندهٔ لمس)، scrollRoot (ظرف اسکرول اصلی یا null = سند)، accept(e)، onRefresh() → Promise،
   * setHint(visible, refreshing)
   * خروجی: { detach(), state() }
   */
  function attach(opts) {
    var target = opts.target || document;
    var scrollRoot = opts.scrollRoot || null;
    var ac = typeof AbortController === 'function' ? new AbortController() : null;
    var o = ac ? { passive: true, signal: ac.signal } : { passive: true };
    var g = null;
    var busy = false;

    function hint(v, r) { if (opts.setHint) { try { opts.setHint(!!v, !!r); } catch (_) {} } }
    function atTop() {
      if (opts.atTop) return opts.atTop();
      // هم ظرف اصلی و هم سند: ظرفی که overflow:auto دارد ولی ارتفاعش محدود نیست هرگز اسکرول نمی‌شود و
      // اسکرول واقعی روی سند است؛ بررسی فقط یکی از آن‌ها وسط صفحه رفرش می‌داد.
      return (scrollRoot ? scrollRoot.scrollTop || 0 : 0) <= TOP_EPS && docScrollTop() <= TOP_EPS;
    }
    function reset() { g = null; if (!busy) hint(false, false); }

    function onStart(e) {
      g = null;
      if (busy || !e.touches || e.touches.length !== 1) return;
      if (overlayOpen() || ignoredTarget(e.target) || inFixedLayer(e.target, scrollRoot)) return;
      if (opts.accept && !opts.accept(e)) return;
      if (!atTop() || innerScrolled(e.target, null)) return;
      g = { x0: e.touches[0].clientX, y0: e.touches[0].clientY, axis: '', pull: 0 };
    }

    function onMove(e) {
      if (!g || !e.touches || e.touches.length !== 1) { if (g) reset(); return; }
      var dx = e.touches[0].clientX - g.x0;
      var dy = e.touches[0].clientY - g.y0;
      if (!g.axis) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) < SLOP) return;
        g.axis = (dy > 0 && Math.abs(dy) > Math.abs(dx) * AXIS_RATIO) ? 'pull' : 'none';
        if (g.axis !== 'pull') { reset(); return; }
      }
      if (!atTop()) { reset(); return; }
      g.pull = Math.max(0, dy);
      hint(g.pull >= SHOW, false);
    }

    function onEnd() {
      if (!g) return;
      var go = g.axis === 'pull' && g.pull >= TRIGGER && atTop() && !busy;
      g = null;
      if (!go) { hint(false, false); return; }
      busy = true;
      hint(true, true);
      var p;
      try { p = Promise.resolve(opts.onRefresh ? opts.onRefresh() : null); } catch (err) { p = Promise.resolve(); }
      p.catch(function () {}).then(function () { busy = false; hint(false, false); });
    }

    target.addEventListener('touchstart', onStart, o);
    target.addEventListener('touchmove', onMove, o);
    target.addEventListener('touchend', onEnd, o);
    target.addEventListener('touchcancel', reset, o);

    return {
      detach: function () {
        if (ac) { try { ac.abort(); } catch (_) {} }
        else {
          target.removeEventListener('touchstart', onStart, o);
          target.removeEventListener('touchmove', onMove, o);
          target.removeEventListener('touchend', onEnd, o);
          target.removeEventListener('touchcancel', reset, o);
        }
        g = null; busy = false; hint(false, false);
      },
      state: function () { return { gesture: g, busy: busy }; }
    };
  }

  root.VinorPtr = {
    version: 2,
    TRIGGER: TRIGGER, SHOW: SHOW, SLOP: SLOP, TOP_EPS: TOP_EPS,
    attach: attach,
    innerScrolled: innerScrolled,
    inFixedLayer: inFixedLayer,
    ignoredTarget: ignoredTarget,
    docScrollTop: docScrollTop
  };
})(typeof window !== 'undefined' ? window : this);
