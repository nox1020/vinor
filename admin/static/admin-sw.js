/*
  Vinor Admin Service Worker – offline-first shell with runtime caching
  Scope: '/admin/'
*/

const VERSION = 'v1.0.0-2025-11-03';
const PRECACHE = `vinor-admin-precache-${VERSION}`;
const RUNTIME = `vinor-admin-runtime-${VERSION}`;
const API_CACHE = `vinor-admin-api-${VERSION}`;

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
const OFFLINE_URL = '/static/offline.html';
const PRECACHE_URLS = [
  '/admin/login',
  '/admin/select',
  '/admin/sw.js',
  '/admin/manifest.webmanifest',
  OFFLINE_URL,
];

const EXTERNAL_WARM = [
  'https://cdn.tailwindcss.com',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css',
  'https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;600;800;900&display=swap',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(PRECACHE);
    for (const u of PRECACHE_URLS) {
      try {
        const req = new Request(u, { credentials: 'same-origin' });
        const resp = await fetch(req);
        if (resp && resp.ok) await cache.put(req, resp.clone());
      } catch(_) {}
    }
    // Best-effort: prewarm external CSS/fonts
    try {
      await Promise.all(EXTERNAL_WARM.map(async (url) => {
        try { 
          const resp = await fetch(url, { mode: 'no-cors' }); 
          if (resp && resp.ok) await cache.put(url, resp.clone()); 
        } catch(_) {}
      }));
    } catch(_) {}
  })());
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.map((name) => {
      if (name !== PRECACHE && name !== RUNTIME && name !== API_CACHE) {
        return caches.delete(name);
      }
    }));
    await clients.claim();
  })());
});

function isSameOrigin(url) {
  try {
    const u = new URL(url);
    return u.origin === self.location.origin;
  } catch {
    return false;
  }
}

function isAdminPath(request) {
  try {
    const url = new URL(request.url);
    return url.pathname.startsWith('/admin/');
  } catch {
    return false;
  }
}

function shouldCacheAdminHtml(request, response) {
  if (!response || !response.ok) return false;
  const url = new URL(request.url);
  const path = url.pathname || '';
  const cc = (response.headers.get('cache-control') || '').toLowerCase();
  const vary = (response.headers.get('vary') || '').toLowerCase();
  const ct = (response.headers.get('content-type') || '').toLowerCase();
  if (!ct.includes('text/html')) return false;
  if (cc.includes('no-store') || cc.includes('private')) return false;
  if (vary.includes('cookie')) return false;
  if (path === '/admin/login' || path === '/admin/logout') return false;
  return true;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') return;

  // Skip cross-origin requests (except no-cors)
  if (!isSameOrigin(url.href) && request.mode !== 'no-cors') return;

  // Admin pages: network-first with cache fallback
  if (isAdminPath(request)) {
    event.respondWith((async () => {
      try {
        const networkResponse = await fetch(request);
        if (shouldCacheAdminHtml(request, networkResponse)) {
          const cache = await caches.open(RUNTIME);
          cache.put(request, networkResponse.clone());
        }
        return networkResponse;
      } catch {
        const cached = await caches.match(request);
        if (cached) return cached;
        const offline = await caches.match(OFFLINE_URL);
        return offline || new Response('Offline', { status: 503 });
      }
    })());
    return;
  }

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith((async () => {
      const cached = await caches.match(request);
      if (cached) return cached;
      try {
        const networkResponse = await fetch(request);
        if (networkResponse && networkResponse.ok) {
          const cache = await caches.open(RUNTIME);
          cache.put(request, networkResponse.clone());
        }
        return networkResponse;
      } catch {
        return new Response('Not found', { status: 404 });
      }
    })());
    return;
  }

  // API calls: network-first
  if (url.pathname.startsWith('/api/')) {
    event.respondWith((async () => {
      try {
        const networkResponse = await fetch(request);
        if (networkResponse && networkResponse.ok) {
          const cache = await caches.open(API_CACHE);
          cache.put(request, networkResponse.clone());
          trimCache(API_CACHE, 50);
        }
        return networkResponse;
      } catch {
        const cached = await caches.match(request);
        if (cached) return cached;
        return new Response(JSON.stringify({ error: 'Offline' }), { 
          status: 503, 
          headers: { 'Content-Type': 'application/json' } 
        });
      }
    })());
    return;
  }
});

// Background sync for offline actions
self.addEventListener('sync', (event) => {
  if (event.tag === 'admin-sync') {
    event.waitUntil((async () => {
      // Handle background sync if needed
    })());
  }
});

