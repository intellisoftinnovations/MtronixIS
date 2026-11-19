/* Mtronix IS Service Worker — offline app shell, cached pages & product images */
const VERSION = 'mtx-v1';
const STATIC_CACHE = `mtx-static-${VERSION}`;
const MEDIA_CACHE = `mtx-media-${VERSION}`;
const PAGES_CACHE = `mtx-pages-${VERSION}`;

const PRECACHE_URLS = [
  '/offline/',
  '/static/css/style.css',
  '/static/vendor/html5-qrcode.min.js',
  '/static/js/offline.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

const NO_CACHE_PREFIXES = ['/login/', '/logout/', '/account/2fa/', '/api/'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      Promise.allSettled(PRECACHE_URLS.map((url) => cache.add(url)))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  const keep = new Set([STATIC_CACHE, MEDIA_CACHE, PAGES_CACHE]);
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !keep.has(k)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CLEAR_USER_CACHES') {
    event.waitUntil(Promise.all([caches.delete(PAGES_CACHE), caches.delete(MEDIA_CACHE)]));
  }
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Static assets: stale-while-revalidate
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.open(STATIC_CACHE).then(async (cache) => {
        const cached = await cache.match(req, { ignoreSearch: true });
        const networkPromise = fetch(req).then((res) => {
          if (res && res.ok) cache.put(req, res.clone());
          return res;
        }).catch(() => null);
        return cached || networkPromise || new Response('', { status: 504 });
      })
    );
    return;
  }

  // Product images (/media/): cache-first with background refresh
  if (url.pathname.startsWith('/media/')) {
    event.respondWith(
      caches.open(MEDIA_CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        const networkPromise = fetch(req).then((res) => {
          if (res && res.ok) cache.put(req, res.clone());
          return res;
        }).catch(() => null);
        return cached || networkPromise || new Response('', { status: 404 });
      })
    );
    return;
  }

  // Never cache auth/API endpoints
  if (NO_CACHE_PREFIXES.some((p) => url.pathname.startsWith(p))) {
    return;
  }

  // HTML navigations: network-first, fallback to cached page, then /offline/
  if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(
      fetch(req).then((res) => {
        if (res && res.ok && !res.redirected) {
          const copy = res.clone();
          caches.open(PAGES_CACHE).then((cache) => cache.put(req, copy));
        }
        return res;
      }).catch(async () => {
        const pageCache = await caches.open(PAGES_CACHE);
        const cached = await pageCache.match(req) || await pageCache.match(url.pathname);
        if (cached) return cached;
        const staticCache = await caches.open(STATIC_CACHE);
        return (await staticCache.match('/offline/')) || new Response('Offline', { status: 503 });
      })
    );
  }
});
