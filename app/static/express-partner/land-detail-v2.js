/**

 * جزئیات فایل همکار v2 — اشتراک، منو، بیشتر بخوانید، علاقه‌مندی

 */

(function () {

  'use strict';



  var abort = null;



  function toast(msg) {

    try {

      if (window.vinorToast) {

        window.vinorToast(msg);

        return;

      }

    } catch (_) {}

    try {

      var el = document.createElement('div');

      el.className = 'fixed bottom-24 inset-x-4 z-[200] mx-auto max-w-sm rounded-xl bg-slate-800 px-4 py-2 text-center text-sm text-white shadow-lg';

      el.textContent = msg;

      document.body.appendChild(el);

      setTimeout(function () {

        try { el.remove(); } catch (_) {}

      }, 2200);

    } catch (_) {}

  }



  function copyText(text) {

    if (!text) return;

    if (navigator.clipboard && navigator.clipboard.writeText) {

      navigator.clipboard.writeText(text).then(function () {

        toast('کپی شد');

      }).catch(fallback);

      return;

    }

    fallback();

    function fallback() {

      try {

        var ta = document.createElement('textarea');

        ta.value = text;

        ta.setAttribute('readonly', '');

        ta.style.position = 'fixed';

        ta.style.left = '-9999px';

        document.body.appendChild(ta);

        ta.select();

        document.execCommand('copy');

        ta.remove();

        toast('کپی شد');

      } catch (_) {

        toast('کپی نشد');

      }

    }

  }



  function bindShare() {

    var btn = document.getElementById('landDetailShareBtn');

    if (!btn) return;

    btn.addEventListener('click', function () {

      var url = window.location.href;

      var title = document.querySelector('.land-detail-v2-content h1');

      var shareData = {

        title: title ? title.textContent.trim() : 'فایل وینور',

        url: url

      };

      if (navigator.share) {

        navigator.share(shareData).catch(function () {});

        return;

      }

      copyText(url);

    }, { signal: abort.signal });

  }



  function bindMoreMenu() {

    var moreBtn = document.getElementById('landDetailMoreBtn');

    var menu = document.getElementById('landDetailMoreMenu');

    if (!moreBtn || !menu) return;



    moreBtn.addEventListener('click', function (e) {

      e.stopPropagation();

      var open = !menu.classList.contains('hidden');

      menu.classList.toggle('hidden', open);

      moreBtn.setAttribute('aria-expanded', open ? 'false' : 'true');

    }, { signal: abort.signal });



    document.addEventListener('click', function (e) {

      if (menu.classList.contains('hidden')) return;

      if (e.target.closest('#landDetailMoreBtn') || e.target.closest('#landDetailMoreMenu')) return;

      menu.classList.add('hidden');

      moreBtn.setAttribute('aria-expanded', 'false');

    }, { signal: abort.signal });



    menu.querySelectorAll('[data-copy-text]').forEach(function (item) {

      item.addEventListener('click', function () {

        copyText(item.getAttribute('data-copy-text'));

        menu.classList.add('hidden');

        moreBtn.setAttribute('aria-expanded', 'false');

      }, { signal: abort.signal });

    });

  }



  function bindDescToggle() {

    var text = document.getElementById('landDescText');

    var toggle = document.getElementById('landDescToggle');

    var chevron = document.getElementById('landDescChevron');

    if (!text || !toggle) return;



    requestAnimationFrame(function () {

      if (text.scrollHeight <= text.clientHeight + 4) return;

      toggle.classList.remove('hidden');

    });



    toggle.addEventListener('click', function () {
      var nowCollapsed = text.classList.toggle('line-clamp-4');
      var isOpen = !nowCollapsed;
      var collapsedLbl = toggle.querySelector('[data-label-collapsed]');
      var expandedLbl = toggle.querySelector('[data-label-expanded]');
      if (collapsedLbl) collapsedLbl.classList.toggle('hidden', isOpen);
      if (expandedLbl) expandedLbl.classList.toggle('hidden', !isOpen);
      if (chevron) chevron.classList.toggle('rotate-180', isOpen);
    }, { signal: abort.signal });

  }



  function bindFavDetail() {

    document.addEventListener('click', function (ev) {

      var btn = ev.target.closest && ev.target.closest('[data-land-detail-fav]');

      if (!btn) return;

      ev.preventDefault();

      ev.stopPropagation();

      var code = String(btn.getAttribute('data-fav-code') || '');

      if (!code || !window.vinorReadFavs || !window.vinorWriteFavs) return;

      var a = window.vinorReadFavs();

      var i = a.indexOf(code);

      if (i >= 0) a.splice(i, 1);

      else a.push(code);

      window.vinorWriteFavs(a);

      if (window.vinorSyncFavButtons) window.vinorSyncFavButtons();

    }, { capture: true, signal: abort.signal });



    if (window.vinorSyncFavButtons) {

      requestAnimationFrame(function () {

        window.vinorSyncFavButtons(document.querySelector('.land-detail-v2'));

      });

    }

  }



  function unbind() {

    if (!abort) return;

    try { abort.abort(); } catch (_) {}

    abort = null;

  }



  function bind() {

    unbind();

    if (!document.querySelector('.land-detail-v2')) return;

    abort = new AbortController();

    bindShare();

    bindMoreMenu();

    bindDescToggle();

    bindFavDetail();

  }



  window.__vinorInitLandDetailV2 = bind;
})();

