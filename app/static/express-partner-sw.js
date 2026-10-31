/*
  وینور اکسپرس - Service Worker جداگانه برای پنل همکاران اکسپرس
  Scope: '/express/partner/'
  این Service Worker کاملاً مجزا از PWA اصلی وینور است
*/

const VERSION = 'v1.0.69-offline-outbox';
const PRECACHE = `express-partner-precache-${VERSION}`;
const RUNTIME = `express-partner-runtime-${VERSION}`;
const API_CACHE = `express-partner-api-${VERSION}`;
const ICONS_CACHE = `express-partner-icons-${VERSION}`;
const IMAGE_CACHE = `express-partner-images-${VERSION}`;

/** کش کردن پاسخ navigate برای HTML باعث می‌شود پس از خروج، PWA همان صفحهٔ لاگین‌شدهٔ قبلی را نشان دهد. */
const KEEP_CACHE_NAMES = new Set([PRECACHE, RUNTIME, API_CACHE, ICONS_CACHE, IMAGE_CACHE]);

// تابع برای محدود کردن اندازه cache
async function trimCache(name, maxEntries) {
  try {
    const cache = await caches.open(name);
    const keys = await cache.keys();
    if (keys.length > maxEntries) {
      const toDelete = keys.slice(0, keys.length - maxEntries);
      await Promise.all(toDelete.map((req) => cache.delete(req)));
    }
  } catch (_) {}
}

const OUTBOX_MAX = 40;
const OUTBOX_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const OUTBOX_DB = 'vinor-partner-outbox';

function isSensitivePartnerPost(url) {
  const p = String(url || '').toLowerCase();
  return /\/(pay|payment|deal|wallet|settlement|finance|otp|login|logout|verify|ai\/chat)(\/|$)/.test(p);
}

function isQueueablePartnerPost(url) {
  try {
    const p = new URL(url, self.location.origin).pathname.toLowerCase();
    if (isSensitivePartnerPost(p)) return false;
    return p === '/express/partner/api/notes' ||
      p.indexOf('/express/partner/api/notes/') === 0 ||
      p.indexOf('/express/partner/api/notifications/') === 0;
  } catch (_) {
    return false;
  }
}

function openOutboxDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OUTBOX_DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('queue')) {
        db.createObjectStore('queue', { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function enqueueOutbox(entry) {
  const db = await openOutboxDb();
  const now = Date.now();
  entry.ts = entry.ts || now;
  await new Promise((resolve, reject) => {
    const tx = db.transaction('queue', 'readwrite');
    const store = tx.objectStore('queue');
    const req = store.openCursor();
    req.onsuccess = (e) => {
      const cursor = e.target.result;
      if (!cursor) return;
      const v = cursor.value || {};
      if (v.url === entry.url && v.body === entry.body) {
        cursor.delete();
      }
      cursor.continue();
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  await new Promise((resolve, reject) => {
    const tx = db.transaction('queue', 'readwrite');
    tx.objectStore('queue').add(entry);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  await trimOutbox(db, now);
}

async function trimOutbox(db, now) {
  const items = await new Promise((resolve, reject) => {
    const out = [];
    const tx = db.transaction('queue', 'readonly');
    const req = tx.objectStore('queue').openCursor();
    req.onsuccess = (e) => {
      const cursor = e.target.result;
      if (cursor) {
        out.push({ id: cursor.key, ts: (cursor.value && cursor.value.ts) || 0 });
        cursor.continue();
      } else resolve(out);
    };
    req.onerror = () => reject(req.error);
  });
  const drop = [];
  items.forEach((it) => {
    if (now - it.ts > OUTBOX_TTL_MS) drop.push(it.id);
  });
  if (items.length - drop.length > OUTBOX_MAX) {
    const keepN = items.length - drop.length - OUTBOX_MAX;
    items.filter((it) => drop.indexOf(it.id) < 0)
      .sort((a, b) => a.ts - b.ts)
      .slice(0, keepN)
      .forEach((it) => drop.push(it.id));
  }
  if (!drop.length) return;
  await new Promise((resolve, reject) => {
    const tx = db.transaction('queue', 'readwrite');
    const store = tx.objectStore('queue');
    drop.forEach((id) => store.delete(id));
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function replayOutbox() {
  const db = await openOutboxDb();
  const entries = await new Promise((resolve, reject) => {
    const out = [];
    const tx = db.transaction('queue', 'readonly');
    const req = tx.objectStore('queue').openCursor();
    req.onsuccess = (e) => {
      const cursor = e.target.result;
      if (cursor) {
        out.push({ id: cursor.key, ...cursor.value });
        cursor.continue();
      } else resolve(out);
    };
    req.onerror = () => reject(req.error);
  });
  for (const item of entries) {
    try {
      const resp = await fetch(item.url, {
        method: item.method || 'POST',
        headers: item.headers || { 'Content-Type': 'application/json' },
        body: item.body || null,
        credentials: 'include',
      });
      if (resp && (resp.ok || resp.status === 409)) {
        await new Promise((resolve, reject) => {
          const tx = db.transaction('queue', 'readwrite');
          tx.objectStore('queue').delete(item.id);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      }
    } catch (_) { /* keep */ }
  }
}

// URLs برای precache در نصب (مختص Express Partner)
// توجه: dashboard و صفحات session-based را precache نمی‌کنیم
const PRECACHE_URLS = [
  '/express/partner/login',
  // dashboard را precache نمی‌کنیم چون محتوای آن session-based است
  // '/express/partner/dashboard',
  // profile و commissions هم session-based هستند
  // '/express/partner/profile',
  // '/express/partner/commissions',
  '/express/partner/offline',
  // Manifest
  '/express/partner/manifest.webmanifest',
  // Icons (استفاده از آیکون‌های مشترک)
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  /* اسکلت آفلاین / fallback ناوبری */
  '/static/express-partner/skeleton-shell.html'
];

// Assets محلی برای offline
const LOCAL_ASSETS = [
  '/static/vendor/fontawesome/css/all.min.css',
  '/static/vendor/fontawesome/webfonts/fa-solid-900.woff2',
  '/static/vendor/fontawesome/webfonts/fa-regular-400.woff2',
  '/static/vendor/fontawesome/webfonts/fa-brands-400.woff2',
  '/static/fonts/vazirmatn.css',
  '/static/fonts/vazirmatn-regular.woff2',
  '/static/fonts/vazirmatn-medium.woff2',
  '/static/fonts/vazirmatn-bold.woff2',
  '/static/vendor/tailwind/tailwindcdn-3.4.17.js',
  '/static/vendor/alpine/alpine-3.14.1.min.js',
  '/static/js/onboarding.js',
  '/static/express-partner/city-picker.js',
  '/static/express-partner/dashboard-chrome.js',
  '/static/express-partner/express-nav.js',
  '/static/express-partner/land-detail.js',
  '/static/favicon.ico',
  '/static/favicon-32x32.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

// نصب Service Worker
self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(PRECACHE);
    const urls = PRECACHE_URLS.concat(LOCAL_ASSETS);
    for (const u of urls) {
      try {
        const req = new Request(u, { credentials: 'same-origin' });
        const resp = await fetch(req);
        if (resp && resp.ok) {
          await cache.put(req, resp.clone());
        }
      } catch (err) {
        console.warn('Express Partner SW: install cache miss', u, err);
      }
    }
    await self.skipWaiting();
  })());
});

// فعال‌سازی Service Worker
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    // نسخه‌های قبلی express-partner-* را حذف کن (قبلاً هرگز پاک نمی‌شدند و HTML کهنه می‌ماند)
    await Promise.all(keys.filter((k) => !KEEP_CACHE_NAMES.has(k)).map((k) => caches.delete(k)));
    /* Navigation preload با صفحات وابسته به سشن گاهی پاسخ نامرتبط می‌دهد؛ غیرفعال */
    try {
      if (self.registration.navigationPreload) {
        await self.registration.navigationPreload.disable();
      }
    } catch (_) {}
    await self.clients.claim();
  })());
});

// بررسی same-origin
function isSameOrigin(url) {
  try {
    return new URL(url, self.location.origin).origin === self.location.origin;
  } catch {
    return false;
  }
}

// بررسی Express Partner route
function isExpressPartnerRoute(url) {
  return url.pathname.startsWith('/express/partner/');
}

// بررسی API های Express Partner
function isExpressPartnerAPI(request) {
  const url = new URL(request.url);
  if (!isSameOrigin(url.href)) return false;
  return url.pathname.startsWith('/api/express/') || url.pathname.startsWith('/express/partner/api/');
}

// بررسی static assets
function isStaticAsset(request) {
  const url = new URL(request.url);
  if (!isSameOrigin(url.href)) return false;
  return url.pathname.startsWith('/static/');
}

function isUploadAsset(request) {
  const url = new URL(request.url);
  if (!isSameOrigin(url.href)) return false;
  return url.pathname.startsWith('/uploads/');
}

function isLikelyImageRequest(request) {
  const url = new URL(request.url);
  if (!isSameOrigin(url.href)) return false;
  if (url.pathname.startsWith('/uploads/')) return true;
  if (url.pathname.startsWith('/static/')) {
    return /\.(png|jpe?g|gif|webp|svg|avif)$/i.test(url.pathname);
  }
  return /\.(png|jpe?g|gif|webp|svg|avif)$/i.test(url.pathname);
}

/** JS پنل همکار — network-first تا پس از deploy نسخهٔ کهنه cache-first برنگردد */
function isExpressPartnerScript(pathname) {
  return pathname.startsWith('/static/express-partner/') && pathname.endsWith('.js');
}

async function fetchExpressPartnerScript(request) {
  const cache = await caches.open(RUNTIME);
  try {
    const resp = await fetch(request);
    if (resp.ok) {
      await cache.put(request, resp.clone());
    }
    return resp;
  } catch (_) {
    const hit = await cache.match(request);
    if (hit) return hit;
    const url = new URL(request.url);
    const noQuery = new Request(url.pathname, { credentials: 'same-origin' });
    const precache = await caches.open(PRECACHE);
    const precached = await precache.match(noQuery);
    if (precached) return precached;
    return new Response('Offline', { status: 503 });
  }
}

function isVinorApkRequest(request) {
  try {
    return (request.headers.get('User-Agent') || '').includes('VinorApp/');
  } catch (_) {
    return false;
  }
}

function isVinorAppShell() {
  try {
    return (self.navigator && self.navigator.userAgent || '').includes('VinorApp/');
  } catch (_) {
    return false;
  }
}

function isAuthPartnerPath(pathname) {
  const p = (pathname || '').replace(/\/+$/, '') || '/';
  return p === '/express/partner/login' ||
    p === '/express/partner/logout' ||
    p === '/express/partner/verify';
}

/** صفحات وابسته به سشن — در کش navigate ذخیره نشوند */
function isSessionPartnerPath(pathname) {
  const p = (pathname || '').replace(/\/+$/, '') || '/';
  return p === '/express/partner/apply' ||
    p === '/express/partner/thanks' ||
    p === '/express/partner/dashboard' ||
    p === '/express/partner/profile' ||
    p === '/express/partner/profile/edit' ||
    p === '/express/partner/commissions' ||
    p.startsWith('/express/partner/commissions/');
}

function isNoStoreResponse(response) {
  if (!response) return true;
  const cc = (response.headers.get('cache-control') || '').toLowerCase();
  return cc.includes('no-store') || cc.includes('private');
}

/** APIهای وابسته به سشن — فقط برای fallback آفلاین APK (پس از logout پاک می‌شوند) */
function isSessionPartnerApiPath(pathname) {
  const p = (pathname || '').replace(/\/+$/, '') || '/';
  return p.startsWith('/express/partner/api/') ||
    p === '/express/partner/dashboard/data' ||
    p === '/express/partner/profile/data' ||
    p === '/express/partner/profile/edit/data' ||
    p === '/express/partner/routine/data' ||
    p === '/express/partner/routine/steps/detail' ||
    p === '/express/partner/commissions/data' ||
    p.startsWith('/express/partner/notifications');
}

function shouldCachePartnerApi(request, response) {
  if (!response || !response.ok) return false;
  const url = new URL(request.url);
  if (request.method !== 'GET') return false;
  // نسخهٔ اپ نباید کش شود — بنر بروزرسانی باید فوری باشد
  const p = (url.pathname || '').replace(/\/+$/, '') || '/';
  if (p === '/api/express/app-version' || p === '/api/app/version') return false;
  if (isSessionPartnerApiPath(url.pathname)) {
    return isVinorApkRequest(request);
  }
  if (isNoStoreResponse(response)) return false;
  return true;
}

async function cachePartnerNavigation(request, response) {
  if (!response || !response.ok) return;
  const url = new URL(request.url);
  if (isAuthPartnerPath(url.pathname)) return;
  try {
    // مهمانِ صفحهٔ محافظت‌شده به /login هدایت می‌شود؛ آن HTML نباید زیر آدرس مقصد کش شود.
    if (response.redirected && isAuthPartnerPath(new URL(response.url).pathname)) return;
  } catch (_) {}
  if (!isExpressPartnerRoute(url)) return;
  const ct = (response.headers.get('content-type') || '').toLowerCase();
  if (!ct.includes('text/html')) return;
  /*
    HTML پنل no-store است، اما برای آفلاینِ «صفحاتی که قبلاً دیده شده‌اند»
    نسخهٔ runtime را نگه می‌داریم. در logout کش‌های partner پاک می‌شوند.
  */
  try {
    const cache = await caches.open(RUNTIME);
    await cache.put(request, response.clone());
    await trimCache(RUNTIME, 32);
  } catch (_) {}
}

async function matchCachedNavigation(request) {
  try {
    const cache = await caches.open(RUNTIME);
    let hit = await cache.match(request);
    if (hit) return hit;
    hit = await cache.match(request, { ignoreSearch: true });
    return hit || null;
  } catch (_) {
    return null;
  }
}

// Handle fetch events
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // APK: native shouldInterceptRequest مالک آفلاین است.
  // fetch()+clone() روی پاسخ intercept رندرر Chromium را می‌کشد.
  if (isVinorAppShell() || isVinorApkRequest(request)) {
    return;
  }

  // فقط Express Partner routes را handle کن
  if (!isExpressPartnerRoute(url) && !isExpressPartnerAPI(request) && !isStaticAsset(request) && !isUploadAsset(request) && !isLikelyImageRequest(request)) {
    return; // بگذار browser آن را handle کند
  }

  // POST requests (API و form submissions)
  if (request.method === 'POST') {
    try {
      if (isSameOrigin(url.href)) {
        const ct = request.headers.get('content-type') || '';
        // API JSON posts
        if (isExpressPartnerAPI(request)) {
          event.respondWith((async () => {
            try {
              return await fetch(request);
            } catch (_) {
              if (isQueueablePartnerPost(url.href)) {
                try {
                  const cloned = request.clone();
                  let body = null;
                  try { body = await cloned.text(); } catch (_) {}
                  const headers = {};
                  request.headers.forEach((v, k) => { headers[k] = v; });
                  await enqueueOutbox({
                    url: url.href,
                    method: 'POST',
                    headers,
                    body,
                    ts: Date.now(),
                  });
                  if (self.registration && 'sync' in self.registration) {
                    try { await self.registration.sync.register('express-partner-outbox'); } catch (_) {}
                  }
                  return new Response(JSON.stringify({
                    success: false,
                    ok: false,
                    queued: true,
                    offline: true,
                    message: 'پس از اتصال اینترنت ارسال می‌شود'
                  }), {
                    status: 202,
                    headers: { 'Content-Type': 'application/json' }
                  });
                } catch (_) {}
              }
              return new Response(JSON.stringify({
                success: false,
                ok: false,
                offline: true,
                error: 'Offline',
                message: 'برای انجام این عملیات اینترنت لازم است'
              }), { 
                status: 503, 
                headers: { 'Content-Type': 'application/json' } 
              });
            }
          })());
          return;
        }
        /* فرم‌های وب: redirect را به مرورگر بسپار تا URL درست عوض شود.
           follow روی logout باعث می‌شد آدرس روی /logout بماند و GET بعدی 405 بدهد. */
        if (isExpressPartnerRoute(url)) {
          event.respondWith((async () => {
            try {
              return await fetch(request, {
                redirect: 'manual',
                credentials: 'include'
              });
            } catch (_) {
              return new Response('Offline', { status: 503 });
            }
          })());
          return;
        }
      }
    } catch (_) {}
  }

  // Navigation requests: Network-first با offline fallback
  if (request.mode === 'navigate' && isExpressPartnerRoute(url)) {
    event.respondWith((async () => {
      // اگر درخواست AJAX است (X-Requested-With header)، از cache استفاده نکن
      const isAjaxRequest = request.headers.get('X-Requested-With') === 'XMLHttpRequest';
      
      try {
        const resp = await fetch(request);
        if (!isAjaxRequest) {
          await cachePartnerNavigation(request, resp);
        }
        return resp;
      } catch (_) {
        // برای AJAX requests، از cache استفاده نکن و خطا برگردان
        if (isAjaxRequest) {
          return new Response('Network error', { status: 503 });
        }
        const runtimeHit = await matchCachedNavigation(request);
        if (runtimeHit) return runtimeHit;
        const cache = await caches.open(PRECACHE);
        // فقط همان URLهایی که در install به precache اضافه شده‌اند (مثلاً login)
        const cached = await cache.match(request);
        if (cached) return cached;
        const skeletonShell = await cache.match('/static/express-partner/skeleton-shell.html');
        if (skeletonShell) return skeletonShell.clone();
        return new Response('Offline', { status: 503 });
      }
    })());
    return;
  }

  // Static assets: Cache-first با background update
  if (isStaticAsset(request)) {
    if (isExpressPartnerScript(url.pathname)) {
      event.respondWith(fetchExpressPartnerScript(request));
      return;
    }
    event.respondWith((async () => {
      const cache = await caches.open(RUNTIME);
      const cached = await cache.match(request);
      if (cached) {
        // به‌روزرسانی در پس‌زمینه
        fetch(request).then((resp) => {
          if (resp.ok) cache.put(request, resp);
        }).catch(() => {});
        return cached;
      }
      try {
        const resp = await fetch(request);
        if (resp.ok) cache.put(request, resp.clone());
        return resp;
      } catch (_) {
        return new Response('Offline', { status: 503 });
      }
    })());
    return;
  }

  // Uploaded/property images: cache-first with no-query fallback for offline stability
  if (isLikelyImageRequest(request)) {
    event.respondWith((async () => {
      const cache = await caches.open(IMAGE_CACHE);
      const cached = await cache.match(request);
      if (cached) {
        fetch(request).then(async (resp) => {
          if (resp && resp.ok) {
            await cache.put(request, resp.clone());
            await trimCache(IMAGE_CACHE, 220);
          }
        }).catch(() => {});
        return cached;
      }
      try {
        const resp = await fetch(request);
        if (resp && resp.ok) {
          await cache.put(request, resp.clone());
          await trimCache(IMAGE_CACHE, 220);
        }
        return resp;
      } catch (_) {
        const noQuery = await cache.match(request, { ignoreSearch: true });
        if (noQuery) return noQuery;
        return new Response('', { status: 503 });
      }
    })());
    return;
  }

  // Express Partner API: Network-first با cache fallback
  if (isExpressPartnerAPI(request)) {
    event.respondWith((async () => {
      const cache = await caches.open(API_CACHE);
      try {
        const resp = await fetch(request);
        if (resp.ok && shouldCachePartnerApi(request, resp)) {
          await trimCache(API_CACHE, 60);
          cache.put(request, resp.clone());
        }
        return resp;
      } catch (_) {
        const cached = await cache.match(request);
        if (cached) return cached;
        return new Response(JSON.stringify({
          success: false,
          offline: true,
          error: 'Offline',
          message: 'آخرین اطلاعات ذخیره‌شده در دسترس نیست'
        }), { 
          status: 503, 
          headers: { 'Content-Type': 'application/json', 'X-Vinor-Cache': 'MISS' } 
        });
      }
    })());
    return;
  }
});

// Background Sync برای درخواست‌های queued
self.addEventListener('sync', (event) => {
  if (event.tag === 'express-partner-outbox' || event.tag.startsWith('express-partner-')) {
    event.waitUntil(replayOutbox());
  }
});

// Push notifications برای Express Partner
self.addEventListener('push', (event) => {
  if (event.data) {
    try {
      const data = event.data.json();
      const title = data.title || 'پنل همکاران وینور';
      const options = {
        body: data.body || 'پیام جدید',
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/icon-48.png',
        tag: 'express-partner-notification',
        data: data.url || '/express/partner/home?ai=1&thread=__postchi__',
        dir: 'rtl',
        lang: 'fa'
      };
      event.waitUntil(self.registration.showNotification(title, options));
    } catch (_) {
      event.waitUntil(self.registration.showNotification('پنل همکاران وینور', {
        body: 'پیام جدید',
        icon: '/static/icons/icon-192.png',
        data: '/express/partner/home?ai=1&thread=__postchi__',
        dir: 'rtl',
        lang: 'fa'
      }));
    }
  }
});

// Handle notification click
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data || '/express/partner/home?ai=1&thread=__postchi__';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // جستجوی window باز Express Partner
      for (const client of clientList) {
        if (client.url.includes('/express/partner/') && 'focus' in client) {
          return client.focus().then(() => {
            if ('navigate' in client) {
              return client.navigate(url);
            }
          });
        }
      }
      // باز کردن window جدید
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});

// Handle notification close
self.addEventListener('notificationclose', (event) => {
  // برای tracking می‌توان استفاده کرد
  console.log('Express Partner: Notification closed', event.notification.tag);
});

// پیام‌های custom از client
self.addEventListener('message', (event) => {
  if (event.data && event.data.type) {
    switch (event.data.type) {
      case 'VINOR_WARMUP':
        // Warmup کردن routes
        if (event.data.urls && Array.isArray(event.data.urls)) {
          event.data.urls.forEach((url) => {
            fetch(url, { cache: 'no-cache', credentials: 'same-origin' }).catch(() => {});
          });
        }
        break;
      case 'VINOR_WARMUP_APK':
        (async () => {
          const urls = (event.data && event.data.urls) || [
            '/express/partner/login',
            '/express/partner/offline',
            '/static/express-partner/skeleton-shell.html',
            '/static/express-partner/express-nav.js',
          ];
          const precache = await caches.open(PRECACHE);
          await Promise.all(urls.map(async (path) => {
            try {
              const req = new Request(path, { credentials: 'same-origin' });
              const resp = await fetch(req, { cache: 'no-cache' });
              if (resp.ok) await precache.put(req, resp.clone());
            } catch (_) {}
          }));
        })();
        break;
      case 'SKIP_WAITING':
        self.skipWaiting();
        break;
      case 'CLEAR_PARTNER_RUNTIME':
        event.waitUntil((async () => {
          try {
            await caches.delete(RUNTIME);
            await caches.delete(API_CACHE);
            await caches.delete(IMAGE_CACHE);
          } catch (_) {}
        })());
        break;
      case 'CLEAR_PARTNER_ALL':
        event.waitUntil((async () => {
          try {
            const keys = await caches.keys();
            const includePrecache = !!(event.data && event.data.includePrecache);
            await Promise.all(keys.filter((k) => {
              if (!k.startsWith('express-partner-')) return false;
              if (!includePrecache && k.startsWith('express-partner-precache-')) return false;
              return true;
            }).map((k) => caches.delete(k)));
          } catch (_) {}
        })());
        break;
      default:
        console.log('Express Partner SW: Unknown message type', event.data.type);
    }
  }
});
