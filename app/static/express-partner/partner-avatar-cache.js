/**
 * کش آواتار همکار — نمایش فوری بدون لود مجدد از شبکه (SPA + رفرش صفحه).
 */
(function (g) {
  'use strict';

  var CACHE_NAME = 'vinor-partner-avatar-v1';
  var STORE_KEY = 'vinor_partner_avatar_meta';
  var mem = { base: '', version: 0, objectUrl: '' };
  var inflight = null;

  function parseVersion(url) {
    if (!url) return 0;
    var m = String(url).match(/[?&]v=(\d+)/);
    return m ? parseInt(m[1], 10) || 0 : 0;
  }

  function baseUrl(url) {
    return String(url || '').split('?')[0].split('#')[0];
  }

  function readMeta() {
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function writeMeta(base, version) {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify({ base: base, version: version || 0 }));
    } catch (_) {}
  }

  function revokeObjectUrl() {
    if (!mem.objectUrl) return;
    try { URL.revokeObjectURL(mem.objectUrl); } catch (_) {}
    mem.objectUrl = '';
  }

  function rememberObjectUrl(base, version, objectUrl) {
    revokeObjectUrl();
    mem.base = base;
    mem.version = version || 0;
    mem.objectUrl = objectUrl;
    writeMeta(base, mem.version);
  }

  function selectTargets(root) {
    root = root || document;
    var out = [];
    ['avatarProfileImg', 'avatarPreviewImg'].forEach(function (id) {
      var el = root.getElementById ? root.getElementById(id) : null;
      if (el) out.push(el);
    });
    return out;
  }

  function hideFallbacks(root) {
    root = root || document;
    ['avatarProfileFallback', 'avatarPreviewFallback'].forEach(function (id) {
      var el = root.getElementById ? root.getElementById(id) : null;
      if (el) el.classList.add('hidden');
    });
  }

  function showImg(img, src) {
    if (!img || !src) return;
    img.src = src;
    img.classList.remove('hidden');
  }

  function resolveServerUrl(img) {
    if (!img) return '';
    return (
      img.getAttribute('data-avatar-url') ||
      img.getAttribute('src') ||
      ''
    ).trim();
  }

  function matches(imgUrl) {
    var b = baseUrl(imgUrl);
    var v = parseVersion(imgUrl);
    return mem.objectUrl && mem.base === b && mem.version === v;
  }

  function cacheOpen() {
    if (!g.caches || !g.caches.open) return Promise.resolve(null);
    return g.caches.open(CACHE_NAME).catch(function () { return null; });
  }

  function cacheGet(url) {
    return cacheOpen().then(function (cache) {
      if (!cache) return null;
      return cache.match(new Request(url, { credentials: 'same-origin' })).catch(function () { return null; });
    });
  }

  function cachePut(url, response) {
    return cacheOpen().then(function (cache) {
      if (!cache || !response || !response.ok) return;
      return cache.put(new Request(url, { credentials: 'same-origin' }), response.clone());
    }).catch(function () {});
  }

  function blobToObjectUrl(blob, url) {
    var b = baseUrl(url);
    var v = parseVersion(url);
    var objectUrl = URL.createObjectURL(blob);
    rememberObjectUrl(b, v, objectUrl);
    return objectUrl;
  }

  function warm(url) {
    var full = String(url || '').trim();
    if (!full) return Promise.resolve('');
    if (matches(full)) return Promise.resolve(mem.objectUrl);

    if (inflight && inflight.url === full) return inflight.promise;

    var promise = cacheGet(full).then(function (cached) {
      if (cached) return cached.blob();
      return fetch(full, { credentials: 'same-origin' }).then(function (res) {
        if (!res.ok) throw new Error('avatar_fetch');
        return cachePut(full, res).then(function () { return res.blob(); });
      });
    }).then(function (blob) {
      return blobToObjectUrl(blob, full);
    }).finally(function () {
      if (inflight && inflight.url === full) inflight = null;
    });

    inflight = { url: full, promise: promise };
    return promise;
  }

  function apply(root) {
    root = root || document;
    var imgs = selectTargets(root);
    if (!imgs.length) return Promise.resolve(false);

    var serverUrl = resolveServerUrl(imgs[0]);
    if (!serverUrl) return Promise.resolve(false);

    if (matches(serverUrl)) {
      imgs.forEach(function (img) { showImg(img, mem.objectUrl); });
      hideFallbacks(root);
      return Promise.resolve(true);
    }

    var meta = readMeta();
    var sameMeta = meta && meta.base === baseUrl(serverUrl) && meta.version === parseVersion(serverUrl);

    if (sameMeta) {
      return warm(serverUrl).then(function (objectUrl) {
        if (!objectUrl) return false;
        imgs.forEach(function (img) {
          if (img.isConnected) showImg(img, objectUrl);
        });
        hideFallbacks(root);
        return true;
      }).catch(function () { return false; });
    }

    imgs.forEach(function (img) {
      if (!img.dataset.vinorAvatarBound) {
        img.dataset.vinorAvatarBound = '1';
        img.addEventListener('load', function onLoad() {
          if (img.naturalWidth > 0) warm(serverUrl).catch(function () {});
        }, { once: true });
      }
    });
    return Promise.resolve(false);
  }

  function setFromUrl(url) {
    var full = String(url || '').trim();
    if (!full) return Promise.resolve('');
    return warm(full).then(function (objectUrl) {
      selectTargets(document).forEach(function (img) { showImg(img, objectUrl); });
      hideFallbacks(document);
      return objectUrl;
    });
  }

  function setFromBlob(blob, version) {
    if (!blob) return Promise.resolve('');
    revokeObjectUrl();
    var v = version || Date.now();
    var objectUrl = URL.createObjectURL(blob);
    rememberObjectUrl('blob:' + v, v, objectUrl);
    selectTargets(document).forEach(function (img) { showImg(img, objectUrl); });
    hideFallbacks(document);
    return Promise.resolve(objectUrl);
  }

  function clear() {
    revokeObjectUrl();
    mem.base = '';
    mem.version = 0;
    try { sessionStorage.removeItem(STORE_KEY); } catch (_) {}
    if (!g.caches || !g.caches.delete) return Promise.resolve();
    return g.caches.delete(CACHE_NAME).catch(function () {});
  }

  function getInstant(url) {
    var full = String(url || '').trim();
    if (!full || !matches(full)) return '';
    return mem.objectUrl;
  }

  function hydrateImg(img, fallbackId) {
    if (!img) return false;
    var url = resolveServerUrl(img);
    if (!url) return false;
    var instant = getInstant(url);
    img.src = instant || url;
    img.classList.remove('hidden');
    if (instant) {
      var fb = fallbackId && document.getElementById
        ? document.getElementById(fallbackId)
        : null;
      if (fb) fb.classList.add('hidden');
      return true;
    }
    return false;
  }

  g.vinorHydratePartnerAvatar = function (imgId, fallbackId) {
    var img = document.getElementById(imgId || 'avatarProfileImg');
    return hydrateImg(img, fallbackId || 'avatarProfileFallback');
  };

  g.vinorPartnerAvatarCache = {
    apply: apply,
    warm: warm,
    getInstant: getInstant,
    hydrate: hydrateImg,
    setFromUrl: setFromUrl,
    setFromBlob: setFromBlob,
    clear: clear,
  };

  g.addEventListener('vinor:express-page-swap', function (ev) {
    var key = ev && ev.detail && ev.detail.navKey;
    if (key === 'profile') apply(document);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (document.getElementById('profilePage') || document.getElementById('profileEditPage')) {
        apply(document);
      }
    });
  } else if (document.getElementById('profilePage') || document.getElementById('profileEditPage')) {
    apply(document);
  }
})(window);
