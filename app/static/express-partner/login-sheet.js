/* ورود درجا: هر جا ورود لازم است، همان صفحهٔ ورود (شماره → کد) در باتم‌شیت روی صفحهٔ فعلی باز می‌شود.
 * بعد از ورود، کاربر روی همین صفحه می‌ماند (یا به مقصد next همان اقدام می‌رود). آدرس /login مستقیم هم کار می‌کند. */
(function () {
  if (window.vinorOpenLoginSheet) return;
  var LOGIN_RE = /^\/express\/partner\/login(?:\/otp)?\/?$/;
  var embedded = false;
  try { embedded = window.self !== window.top; } catch (_) { embedded = true; }

  function parse(href) {
    try { return new URL(href, window.location.href); } catch (_) { return null; }
  }
  function isLoginHref(href) {
    var u = parse(href);
    return !!(u && u.origin === window.location.origin && LOGIN_RE.test(u.pathname));
  }
  function onLoginPage() { return LOGIN_RE.test(window.location.pathname); }
  function isGuest() {
    var m = document.querySelector('meta[name="vinor-express-auth"]');
    return !m || m.getAttribute('content') === 'guest';
  }

  var CSS = '.vn-login-sheet{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:flex-end;justify-content:center}' +
    '.vn-login-sheet__backdrop{position:absolute;inset:0;background:rgba(0,0,0,.62)}' +
    '.vn-login-sheet__panel{position:relative;width:100%;max-width:28rem;height:min(82dvh,720px);background:#000;border-radius:20px 20px 0 0;overflow:hidden;box-shadow:0 -8px 32px rgba(0,0,0,.5);animation:vnLoginSheetUp .22s ease-out}' +
    '.vn-login-sheet__grip{position:absolute;top:6px;left:50%;width:36px;height:4px;margin-left:-18px;border-radius:2px;background:rgba(255,255,255,.22);z-index:1}' +
    '.vn-login-sheet__frame{display:block;width:100%;height:100%;border:0;background:#000}' +
    'html.vn-login-sheet-open,html.vn-login-sheet-open body{overflow:hidden}' +
    '@keyframes vnLoginSheetUp{from{transform:translateY(100%)}to{transform:none}}';
  function injectCss() {
    if (document.getElementById('vnLoginSheetCss')) return;
    var st = document.createElement('style');
    st.id = 'vnLoginSheetCss';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  function settle(next) {
    fetch('/express/partner/api/auth-state', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.logged_in) finish(next); else close(); })
      .catch(close);
  }

  var sheet = null;
  var sheetNext = '';
  function close() {
    if (!sheet) return;
    sheet.remove();
    sheet = null;
    document.documentElement.classList.remove('vn-login-sheet-open');
  }

  function finish(next) {
    close();
    if (next) {
      var u = parse(next);
      if (u && u.origin === window.location.origin &&
          (u.pathname + u.search) !== (window.location.pathname + window.location.search)) {
        window.location.assign(u.pathname + u.search + u.hash);
        return;
      }
    }
    window.location.reload();
  }

  function open(loginHref) {
    if (embedded || onLoginPage()) return false;
    var u = parse(loginHref || '/express/partner/login');
    if (!u) return false;
    var next = u.searchParams.get('next') || '';
    if (!next) {
      next = window.location.pathname + window.location.search;
      u.searchParams.set('next', next);
    }
    close();
    sheet = document.createElement('div');
    sheet.id = 'vinorLoginSheet';
    sheet.className = 'vn-login-sheet';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.setAttribute('aria-label', 'ورود به وینور');
    sheet.innerHTML =
      '<div class="vn-login-sheet__backdrop" data-login-sheet-close></div>' +
      '<div class="vn-login-sheet__panel"><span class="vn-login-sheet__grip" aria-hidden="true"></span>' +
      '<iframe class="vn-login-sheet__frame" title="ورود به وینور" allow="otp-credentials"></iframe></div>';
    var frame = sheet.querySelector('iframe');
    // ناوبری نرم داخل iframe رویداد load ندارد؛ مسیر iframe پایش می‌شود.
    var settled = false;
    var poll = setInterval(function () {
      if (!sheet || settled) { clearInterval(poll); return; }
      var pth = '';
      try {
        if (frame.contentWindow.location.protocol === 'about:') return;
        pth = frame.contentWindow.location.pathname;
      } catch (_) { return; }
      if (!LOGIN_RE.test(pth) && pth !== '/express/partner/verify') {
        settled = true;
        clearInterval(poll);
        settle(next);
      }
    }, 300);
    frame.addEventListener('load', function () {
      var w, path;
      try { w = frame.contentWindow; if (w.location.protocol === 'about:') return; path = w.location.pathname; } catch (_) { return; }
      if (LOGIN_RE.test(path) || path === '/express/partner/verify') return;
      // از صفحهٔ ورود خارج شد: یا ورود موفق بود یا کاربر بست.
      if (settled) return;
      settled = true;
      settle(next);
    });
    sheet.addEventListener('click', function (e) {
      if (e.target.closest('[data-login-sheet-close]')) close();
    });
    sheetNext = next;
    injectCss();
    document.body.appendChild(sheet);
    document.documentElement.classList.add('vn-login-sheet-open');
    frame.src = u.pathname + u.search;
    return true;
  }

  window.vinorOpenLoginSheet = open;
  window.vinorCloseLoginSheet = close;
  window.vinorGoLogin = function (href) {
    if (!open(href)) window.location.assign(href || '/express/partner/login');
  };

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sheet) close();
  });

  if (embedded) {
    // داخل شیت: خروج از صفحهٔ ورود (موفق یا بستن) به والد خبر داده می‌شود، iframe ناوبری نمی‌کند.
    var leave = function () {
      try { window.parent.postMessage({ type: 'vinor-login-leave' }, window.location.origin); } catch (_) {}
    };
    var wrapInner = function () {
      var nav = window.vinorExpressNavigate;
      if (typeof nav !== 'function' || nav.__vinorLoginSheet) return;
      var w2 = function (url) {
        if (onLoginPage() && !isLoginHref(url)) { leave(); return Promise.resolve(true); }
        return nav.apply(this, arguments);
      };
      w2.__vinorLoginSheet = true;
      window.vinorExpressNavigate = w2;
    };
    wrapInner();
    document.addEventListener('DOMContentLoaded', wrapInner);
    window.addEventListener('load', wrapInner);
    return;
  }

  window.addEventListener('message', function (e) {
    if (e.origin !== window.location.origin || !sheet) return;
    if (e.data && e.data.type === 'vinor-login-leave') settle(sheetNext);
  });

  // لینک‌های ورود (بازدید مهمان، منوی وینور من، …) قبل از ناوبری نرم گرفته می‌شوند.
  window.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target === '_blank' || !isLoginHref(a.getAttribute('href'))) return;
    if (!isGuest() && !onLoginPage()) return;
    if (open(a.getAttribute('href'))) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);

  function wrapNav() {
    var nav = window.vinorExpressNavigate;
    if (typeof nav !== 'function' || nav.__vinorLoginSheet) return;
    var wrapped = function (url, opts) {
      if (isLoginHref(url) && open(url)) return Promise.resolve(true);
      return nav.apply(this, arguments);
    };
    wrapped.__vinorLoginSheet = true;
    window.vinorExpressNavigate = wrapped;
  }
  wrapNav();
  document.addEventListener('DOMContentLoaded', wrapNav);
  window.addEventListener('load', wrapNav);
})();
