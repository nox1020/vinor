/*
  Vinor Service Worker – offline-first shell with runtime caching
  Scope: '/'
*/

const VERSION = 'v1.2.2-offline-outbox-cap';
const PRECACHE = `vinor-precache-${VERSION}`;
const RUNTIME = `vinor-runtime-${VERSION}`;
const API_CACHE = `vinor-api-${VERSION}`;
const ICONS_CACHE = `vinor-icons-${VERSION}`;
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

// URLs to precache at install
const PRECACHE_URLS = [
  '/',
  '/start',
  '/app',
  '/login',
  '/verify',
  '/search',
  '/about',
  '/help',
  '/faq',
  '/guide/safe-buy',
  '/connection',
  '/city',
  '/city/multi',
  // careers & consultant
  '/careers/consultant',
  '/careers/consultant/apply',
  '/consultant/dashboard',
  // user pages (will cache shell or redirect)
  '/favorites',
  '/profile',
  '/settings',
  '/my-lands',
  '/notifications',
  // submit/ad flows (shell)
  '/submit-ad',
  '/lands/add/step1',
  '/lands/add',
  '/lands/add/details',
  '/lands/add/step3',
  // manifests
  '/manifest.webmanifest',
  // Icons/sounds (best-effort if exist)
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/sounds/notify.mp3'
];
const OFFLINE_URL = '/connection';
// Precache local icon/font assets for full offline
const LOCAL_ICON_FONT_ASSETS = [
  '/static/vendor/fontawesome/css/all.min.css',
  '/static/vendor/fontawesome/webfonts/fa-solid-900.woff2',
  '/static/vendor/fontawesome/webfonts/fa-regular-400.woff2',
  '/static/vendor/fontawesome/webfonts/fa-brands-400.woff2',
  '/static/fonts/vazirmatn.css',
  // optional if you add specific woff2 files
  '/static/fonts/vazirmatn-regular.woff2',
  '/static/fonts/vazirmatn-bold.woff2',
  '/static/fonts/vazirmatn-medium.woff2',
  '/static/fonts/vazirmatn-light.woff2'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(PRECACHE);
    try { await cache.addAll(PRECACHE_URLS.concat(LOCAL_ICON_FONT_ASSETS).map((u) => new Request(u, { credentials: 'same-origin' }))); } catch(_) {}
    // Best-effort: prewarm external CSS/fonts/icons into dedicated ICONS cache for offline rendering
    try {
      const icache = await caches.open(ICONS_CACHE);
      await Promise.all(EXTERNAL_WARM.map(async (url) => {
        try { const resp = await fetch(url, { mode: 'no-cors' }); await icache.put(url, resp.clone()); } catch(_) {}
      }));
    } catch(_) {}
    // Seed critical API data so core UI works fully offline right after install
    try {
      const api = await caches.open(API_CACHE);
      const apiWarm = ['/api/lands/approved', '/api/express-listings'];
      await Promise.all(apiWarm.map(async (u) => {
        try {
          const req = new Request(u, { credentials: 'same-origin' });
          const resp = await fetch(req);
          if (resp && resp.ok) await api.put(req, resp);
        } catch(_) {}
      }));
    } catch(_) {}
    // Don't auto-skipWaiting; wait for user action via SKIP_WAITING message
    // This allows showing update badge in UI before activating new SW
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.filter((k) => ![PRECACHE, RUNTIME, API_CACHE].includes(k)).map((k) => caches.delete(k))
    );
    // Enable Navigation Preload for faster nav when online
    try { if (self.registration.navigationPreload) await self.registration.navigationPreload.enable(); } catch(_) {}
    await self.clients.claim();
  })());
});

function isSameOrigin(url) {
  try { return new URL(url, self.location.origin).origin === self.location.origin; } catch { return false; }
}

// External CDNs are disabled in offline-first mode.
const EXTERNAL_ORIGINS = [];

// No external warmup in full local/offline mode.
const EXTERNAL_WARM = [];

function isAPI(request) {
  const url = new URL(request.url);
  if (!isSameOrigin(url.href)) return false;
  return url.pathname.startsWith('/api/');
}

function isStaticAsset(request) {
  const url = new URL(request.url);
  if (!isSameOrigin(url.href)) return false;
  return url.pathname.startsWith('/static/');
}

function isUploads(request) {
  const url = new URL(request.url);
  if (!isSameOrigin(url.href)) return false;
  return url.pathname.startsWith('/uploads/');
}

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Queue POST requests for offline (API JSON and non-multipart form posts)
  if (request.method === 'POST') {
    try {
      const url = new URL(request.url);
      const same = isSameOrigin(url.href);
      if (same) {
        const ct = request.headers.get('content-type') || '';
        // API JSON posts (except uploads)
        if (url.pathname.startsWith('/api/') && !url.pathname.startsWith('/api/uploads/')) {
          event.respondWith(handleJsonPostWithQueue(request));
          return;
        }
        // App form posts (exclude multipart uploads)
        if ((url.pathname.startsWith('/lands/') || url.pathname.startsWith('/ads/')) && !ct.includes('multipart/form-data')) {
          event.respondWith((async () => {
            try {
              return await fetch(request);
            } catch (_) {
              // Fallback: queue and show offline page
              try { await handleJsonPostWithQueue(request); } catch(_e) {}
              const pc = await caches.open(PRECACHE);
              const off = await pc.match(OFFLINE_URL);
              return off || new Response('queued', { status: 202 });
            }
          })());
          return;
        }
      }
    } catch(_) {}
  }

  // Navigation requests: App Shell network-first → cache fallback (بدون صفحه آفلاین)
  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        // Use preloaded response if available
        const preload = await event.preloadResponse;
        const resp = preload || await fetch(request);
        // نباید redirect responses (302/301) یا responses با Vary: Cookie را cache کنیم
        // چون redirect بر اساس session است و نباید cache شود
        const isRedirect = resp.status >= 300 && resp.status < 400;
        const hasVaryCookie = resp.headers.get('Vary') && resp.headers.get('Vary').includes('Cookie');
        const noCache = resp.headers.get('Cache-Control') && resp.headers.get('Cache-Control').includes('no-store');
        
        if (!isRedirect && !hasVaryCookie && !noCache) {
          // Optionally update precache copy of shell routes
          const cache = await caches.open(PRECACHE);
          try { cache.put(request, resp.clone()); } catch(_) {}
        }
        return resp;
      } catch (_) {
        const cache = await caches.open(PRECACHE);
        // Prefer exact cached page; else try cached /app shell; else offline
        const cached = await cache.match(request);
        if (cached) return cached;
        const appShell = await cache.match('/app');
        if (appShell) return appShell;
        // بدون صفحه آفلاین: اجازه می‌دهیم مرورگر خطای شبکه نمایش دهد
        return new Response('Offline', { status: 503 });
      }
    })());
    return;
  }

  // API: stale-while-revalidate
  if (isAPI(request) && request.method === 'GET') {
    event.respondWith((async () => {
      const cache = await caches.open(API_CACHE);
      const cached = await cache.match(request);
      const networkPromise = fetch(request)
        .then(async (resp) => { try { cache.put(request, resp.clone()); await trimCache(API_CACHE, 60); } catch(_) {} return resp; })
        .catch(() => undefined);
      return cached || (await networkPromise) || new Response(JSON.stringify({ ok: false, offline: true }), { status: 503, headers: { 'Content-Type': 'application/json' } });
    })());
    return;
  }

  // Static assets: stale-while-revalidate (return cache immediately, update in background)
  if ((isStaticAsset(request) || isUploads(request)) && request.method === 'GET') {
    event.respondWith((async () => {
      const cache = await caches.open(RUNTIME);
      const cached = await cache.match(request);
      if (cached) {
        // Kick off background update
        event.waitUntil((async () => {
          try {
            const resp = await fetch(request, { credentials: 'same-origin', cache: 'no-store' });
            try { await cache.put(request, resp.clone()); await trimCache(RUNTIME, 150); } catch(_) {}
          } catch(_) {}
        })());
        return cached;
      }
      try {
        const resp = await fetch(request, { credentials: 'same-origin' });
        try { await cache.put(request, resp.clone()); await trimCache(RUNTIME, 150); } catch(_) {}
        return resp;
      } catch (_) {
        // Image fallback placeholder (if asset is an image)
        const accept = request.headers.get('accept') || '';
        if (accept.includes('image')) {
          const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="100%" height="100%" fill="#e5e7eb"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#9ca3af" font-family="sans-serif" font-size="24">Offline</text></svg>';
          return new Response(svg, { headers: { 'Content-Type': 'image/svg+xml' } });
        }
        throw _;
      }
    })());
    return;
  }

  // External CDN assets: cache-first (opaque allowed)
  try {
    const url = new URL(request.url);
    if (EXTERNAL_ORIGINS.includes(url.origin) && request.method === 'GET') {
      event.respondWith((async () => {
        const cache = await caches.open(ICONS_CACHE);
        const cached = await cache.match(request, { ignoreVary: true });
        if (cached) return cached;
        try {
          const resp = await fetch(request, { mode: 'no-cors' }); // may be opaque
          try { cache.put(request, resp.clone()); } catch(_) {}
          return resp;
        } catch (_) {
          return new Response('', { status: 504 });
        }
      })());
      return;
    }
  } catch(_) {}

  // Default: network-first with cache fallback for GET
  if (request.method === 'GET') {
    event.respondWith((async () => {
      const cache = await caches.open(RUNTIME);
      try {
        const resp = await fetch(request);
        try { cache.put(request, resp.clone()); await trimCache(RUNTIME, 150); } catch(_) {}
        return resp;
      } catch (_) {
        const cached = await cache.match(request);
        if (cached) return cached;
        return new Response('Offline', { status: 503 });
      }
    })());
  }
});

// Warm-up handler (list of URLs from the app)
self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data && data.type === 'VINOR_WARMUP') {
    const urls = Array.isArray(data.urls) ? data.urls : [];
    event.waitUntil((async () => {
      const cache = await caches.open(PRECACHE);
      await Promise.all(urls.map(async (u) => {
        try { const req = new Request(u, { credentials: 'same-origin' }); const resp = await fetch(req); cache.put(req, resp); } catch(_) {}
      }));
    })());
  }
  // Trigger background sync warmup (if supported)
  if (data && data.type === 'VINOR_WARMUP_SYNC') {
    if (self.registration && 'sync' in self.registration) {
      try { self.registration.sync.register('vinor-warmup'); } catch(_) {}
    }
  }
  // Warm external assets upon request from client
  if (data && data.type === 'VINOR_WARMUP_EXT') {
    event.waitUntil((async () => {
      try {
        const rcache = await caches.open(RUNTIME);
        await Promise.all(EXTERNAL_WARM.map(async (url) => {
          try { const resp = await fetch(url, { mode: 'no-cors', cache: 'no-store' }); await rcache.put(url, resp.clone()); } catch(_) {}
        }));
      } catch(_) {}
    })());
  }
  // Queue a generic request (e.g., finalize GET) from client
  if (data && data.type === 'VINOR_QUEUE') {
    const url = String(data.url || '/');
    const method = String(data.method || 'GET').toUpperCase();
    const headers = data.headers || {};
    const body = data.body || null;
    event.waitUntil((async () => {
      try {
        await queueRequest({ url, method, headers, body, credentials: 'include', ts: Date.now() });
        if (self.registration && 'sync' in self.registration) {
          try { await self.registration.sync.register('vinor-sync'); } catch(_) {}
        }
      } catch(_) {}
    })());
  }
  // Queue a form POST provided by page script
  if (data && data.type === 'VINOR_QUEUE_FORM') {
    const url = String(data.url || '/');
    const method = String(data.method || 'POST').toUpperCase();
    const headers = data.headers || { 'Content-Type': 'application/x-www-form-urlencoded' };
    const body = data.body || '';
    event.waitUntil((async () => {
      try {
        await queueRequest({ url, method, headers, body, credentials: 'include', ts: Date.now() });
        if (self.registration && 'sync' in self.registration) {
          try { await self.registration.sync.register('vinor-sync'); } catch(_) {}
        }
      } catch(_) {}
    })());
  }
  // Handle SKIP_WAITING message from client to activate waiting SW immediately
  if (data && data.type === 'SKIP_WAITING') {
    event.waitUntil(self.skipWaiting());
  }
});

// Background sync to refresh important URLs when back online
self.addEventListener('sync', (event) => {
  if (event.tag === 'vinor-warmup') {
    event.waitUntil((async () => {
      const urls = ['/', '/app', '/api/lands/approved', '/api/express-listings'];
      const cache = await caches.open(PRECACHE);
      await Promise.all(urls.map(async (u) => {
        try { const req = new Request(u, { credentials: 'same-origin' }); const resp = await fetch(req, { cache: 'no-store' }); cache.put(req, resp); } catch(_) {}
      }));
    })());
  }
});

// Background sync: replay queued requests when back online
self.addEventListener('sync', (event) => {
  if (event.tag === 'vinor-sync') {
    event.waitUntil(replayQueue());
  }
});

// ===== Background Sync Queue (IndexedDB) =====
function openQueueDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('vinor-sync-db', 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('queue')) db.createObjectStore('queue', { keyPath: 'id', autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

const QUEUE_MAX = 40;
const QUEUE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

function isSensitiveQueuedUrl(url) {
  const p = String(url || '').toLowerCase();
  return /\/(pay|payment|deal|wallet|settlement|finance|otp|login|logout|verify|ai\/chat)(\/|$)/.test(p);
}

async function queueRequest(entry) {
  try {
    if (isSensitiveQueuedUrl(entry && entry.url)) return;
    const db = await openQueueDb();
    entry.ts = entry.ts || Date.now();
    await new Promise((resolve, reject) => {
      const tx = db.transaction('queue', 'readwrite');
      tx.objectStore('queue').add(entry);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    await trimQueueDb(db);
  } catch (e) {}
}

async function trimQueueDb(db) {
  const now = Date.now();
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
  const drop = items.filter((it) => now - it.ts > QUEUE_TTL_MS).map((it) => it.id);
  const live = items.filter((it) => drop.indexOf(it.id) < 0).sort((a, b) => a.ts - b.ts);
  if (live.length > QUEUE_MAX) {
    live.slice(0, live.length - QUEUE_MAX).forEach((it) => drop.push(it.id));
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

async function replayQueue() {
  const db = await openQueueDb();
  const entries = await new Promise((resolve, reject) => {
    const out = [];
    const tx = db.transaction('queue', 'readonly');
    const store = tx.objectStore('queue');
    const req = store.openCursor();
    req.onsuccess = (e) => {
      const cursor = e.target.result;
      if (cursor) { out.push({ id: cursor.key, ...cursor.value }); cursor.continue(); }
      else { resolve(out); }
    };
    req.onerror = () => reject(req.error);
  });

  for (const item of entries) {
    try {
      const resp = await fetch(item.url, {
        method: item.method || 'POST',
        headers: item.headers || { 'Content-Type': 'application/json' },
        body: item.body || null,
        credentials: item.credentials || 'same-origin',
      });
      if (resp && resp.ok) {
        await new Promise((resolve, reject) => {
          const tx = db.transaction('queue', 'readwrite');
          tx.objectStore('queue').delete(item.id);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      }
    } catch (_) { /* keep in queue */ }
  }
}

async function handleJsonPostWithQueue(request) {
  try {
    return await fetch(request);
  } catch (e) {
    if (isSensitiveQueuedUrl(request.url)) {
      return new Response(JSON.stringify({
        ok: false,
        queued: false,
        offline: true,
        message: 'برای انجام این عملیات اینترنت لازم است'
      }), { status: 503, headers: { 'Content-Type': 'application/json' } });
    }
    try {
      const cloned = request.clone();
      let body = null;
      try { body = await cloned.text(); } catch(_) {}
      const headers = {};
      request.headers.forEach((v, k) => { headers[k] = v; });
      await queueRequest({ url: request.url, method: request.method, headers, body, credentials: 'include', ts: Date.now() });
      if (self.registration && 'sync' in self.registration) {
        try { await self.registration.sync.register('vinor-sync'); } catch(_) {}
      }
    } catch(_) {}
    return new Response(JSON.stringify({ ok: false, queued: true, offline: true, message: 'پس از اتصال اینترنت ارسال می‌شود' }), { status: 202, headers: { 'Content-Type': 'application/json' } });
  }
}

// ===== Push Notifications Handler (Background) =====
self.addEventListener('push', (event) => {
  let payload = {};
  let title = 'وینور';
  let body = 'اعلان جدید دریافت شد';
  let icon = '/static/icons/icon-192.png';
  let badge = '/static/icons/icon-96.png';
  let url = '/app/notifications';
  let tag = 'vinor-notification';
  let requireInteraction = false;

  try {
    if (event.data) {
      const data = event.data.json();
      if (data && typeof data === 'object') {
        payload = data;
        title = data.title || title;
        body = data.body || body;
        icon = data.icon || icon;
        badge = data.badge || badge;
        url = data.url || data.action_url || url;
        tag = data.tag || data.id || tag;
        requireInteraction = data.requireInteraction === true;
      } else if (typeof event.data.text === 'function') {
        try {
          const textData = event.data.text();
          payload = JSON.parse(textData);
          title = payload.title || title;
          body = payload.body || body;
          icon = payload.icon || icon;
          badge = payload.badge || badge;
          url = payload.url || payload.action_url || url;
          tag = payload.tag || payload.id || tag;
          requireInteraction = payload.requireInteraction === true;
        } catch (_) {
          body = event.data.text() || body;
        }
      }
    }
  } catch (e) {
    // Fallback: use default values
    try {
      if (event.data && typeof event.data.text === 'function') {
        body = event.data.text() || body;
      }
    } catch (_) {}
  }

  const notificationOptions = {
    body: body,
    icon: icon,
    badge: badge,
    tag: tag,
    requireInteraction: requireInteraction,
    data: { ...payload, url: url },
    actions: []
  };

  // اضافه کردن action برای باز کردن اعلان
  if (url) {
    notificationOptions.actions.push({
      action: 'open',
      title: 'مشاهده'
    });
  }

  event.waitUntil(
    self.registration.showNotification(title, notificationOptions)
      .then(() => {
        // ارسال پیام به کلاینت برای پخش صدا
        return self.clients.matchAll({ type: 'window', includeUncontrolled: true })
          .then(clients => {
            clients.forEach(client => {
              try {
                client.postMessage({
                  type: 'PUSH_RECEIVED',
                  data: payload
                });
              } catch (_) {}
            });
          });
      })
      .catch(err => {
        // لاگ خطا در صورت عدم موفقیت
        console.error('Failed to show notification:', err);
      })
  );
});

// ===== Notification Click Handler =====
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const notificationData = event.notification.data || {};
  const urlToOpen = notificationData.url || '/app/notifications';
  const action = event.action;

  if (action === 'open' || !action) {
    event.waitUntil(
      self.clients.matchAll({ type: 'window', includeUncontrolled: true })
        .then(clients => {
          // اگر پنجره باز است، روی آن فوکوس کن
          for (const client of clients) {
            if (client.url.includes(urlToOpen) && 'focus' in client) {
              return client.focus();
            }
          }
          // اگر پنجره‌ای باز نیست، یک پنجره جدید باز کن
          if (self.clients.openWindow) {
            return self.clients.openWindow(urlToOpen);
          }
        })
        .catch(err => {
          console.error('Failed to open notification:', err);
        })
    );
  }
});

// ===== Notification Close Handler =====
self.addEventListener('notificationclose', (event) => {
  // در صورت نیاز می‌توانید عملیاتی را اینجا انجام دهید
  // مثلاً ارسال رویداد به سرور برای ردیابی
});

