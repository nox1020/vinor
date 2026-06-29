/*
  وینور اکسپرس - Service Worker جداگانه برای پنل همکاران اکسپرس
  Scope: '/express/partner/'
  این Service Worker کاملاً مجزا از PWA اصلی وینور است
*/

const VERSION = 'v1.0.35-solid-black-chrome';
const PRECACHE = `express-partner-precache-${VERSION}`;
const RUNTIME = `express-partner-runtime-${VERSION}`;
const API_CACHE = `express-partner-api-${VERSION}`;
const ICONS_CACHE = `express-partner-icons-${VERSION}`;

/** کش کردن پاسخ navigate برای HTML باعث می‌شود پس از خروج، PWA همان صفحهٔ لاگین‌شدهٔ قبلی را نشان دهد. */
const KEEP_CACHE_NAMES = new Set([PRECACHE, RUNTIME, API_CACHE, ICONS_CACHE]);

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

// URLs برای precache در نصب (مختص Express Partner)
// توجه: dashboard و صفحات session-based را precache نمی‌کنیم
const PRECACHE_URLS = [
  '/express/partner/login',
  // dashboard را precache نمی‌کنیم چون محتوای آن session-based است
  // '/express/partner/dashboard',
  // profile و commissions هم session-based هستند
  // '/express/partner/profile',
  // '/express/partner/commissions',
  '/express/partner/notes',
  '/express/partner/apply',
  '/express/partner/thanks',
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
    try {
      await cache.addAll(PRECACHE_URLS.concat(LOCAL_ASSETS).map((u) => new Request(u, { credentials: 'same-origin' })));
    } catch (err) {
      console.error('Express Partner SW: Cache install error', err);
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

function isAuthPartnerPath(pathname) {
  const p = (pathname || '').replace(/\/+$/, '') || '/';
  return p === '/express/partner/login' ||
    p === '/express/partner/logout' ||
    p === '/express/partner/verify';
}

function isNoStoreResponse(response) {
  if (!response) return true;
  const cc = (response.headers.get('cache-control') || '').toLowerCase();
  return cc.includes('no-store') || cc.includes('private');
}

async function cacheApkNavigation(request, response) {
  if (!isVinorApkRequest(request) || !response || !response.ok) return;
  if (isNoStoreResponse(response)) return;
  const url = new URL(request.url);
  if (isAuthPartnerPath(url.pathname)) return;
  const ct = (response.headers.get('content-type') || '').toLowerCase();
  if (!ct.includes('text/html')) return;
  try {
    const cache = await caches.open(RUNTIME);
    await cache.put(request, response.clone());
    await trimCache(RUNTIME, 20);
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

  // فقط Express Partner routes را handle کن
  if (!isExpressPartnerRoute(url) && !isExpressPartnerAPI(request) && !isStaticAsset(request)) {
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
              return new Response(JSON.stringify({ error: 'Offline', message: 'شما آفلاین هستید' }), { 
                status: 503, 
                headers: { 'Content-Type': 'application/json' } 
              });
            }
          })());
          return;
        }
        /* فرم‌های وب (شامل خروج): برای logout redirect را follow کن تا WebView/APK درست دنبال کند */
        if (isExpressPartnerRoute(url)) {
          event.respondWith((async () => {
            try {
              var pathNorm = url.pathname.replace(/\/+$/, '') || '/';
              var isLogout = pathNorm === '/express/partner/logout';
              return await fetch(request, {
                redirect: isLogout ? 'follow' : 'manual',
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
          await cacheApkNavigation(request, resp);
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

  // Express Partner API: Network-first با cache fallback
  if (isExpressPartnerAPI(request)) {
    event.respondWith((async () => {
      const cache = await caches.open(API_CACHE);
      try {
        const resp = await fetch(request);
        if (resp.ok && !isNoStoreResponse(resp)) {
          await trimCache(API_CACHE, 50);
          cache.put(request, resp.clone());
        }
        return resp;
      } catch (_) {
        const cached = await cache.match(request);
        if (cached) return cached;
        return new Response(JSON.stringify({ error: 'Offline', message: 'شما آفلاین هستید' }), { 
          status: 503, 
          headers: { 'Content-Type': 'application/json' } 
        });
      }
    })());
    return;
  }
});

// Background Sync برای درخواست‌های queued
self.addEventListener('sync', (event) => {
  if (event.tag.startsWith('express-partner-')) {
    event.waitUntil((async () => {
      // Handle background sync برای Express Partner
      // می‌تواند برای sync کردن داده‌ها در پس‌زمینه استفاده شود
      console.log('Express Partner: Background sync', event.tag);
    })());
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
        data: data.url || '/express/partner/dashboard',
        dir: 'rtl',
        lang: 'fa'
      };
      event.waitUntil(self.registration.showNotification(title, options));
    } catch (_) {
      event.waitUntil(self.registration.showNotification('پنل همکاران وینور', {
        body: 'پیام جدید',
        icon: '/static/icons/icon-192.png',
        dir: 'rtl',
        lang: 'fa'
      }));
    }
  }
});

// Handle notification click
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data || '/express/partner/dashboard';
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
            fetch(url, { cache: 'no-cache' }).catch(() => {});
          });
        }
        break;
      case 'SKIP_WAITING':
        self.skipWaiting();
        break;
      case 'CLEAR_PARTNER_RUNTIME':
        event.waitUntil((async () => {
          try {
            await caches.delete(RUNTIME);
            await caches.delete(API_CACHE);
          } catch (_) {}
        })());
        break;
      default:
        console.log('Express Partner SW: Unknown message type', event.data.type);
    }
  }
});
