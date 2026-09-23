// SentinelCV Service Worker
// Strategy: Network-first for API calls; Cache-first for static assets.

const CACHE_NAME = 'sentinelcv-v1';
const OFFLINE_PAGE = '/offline';

const STATIC_ASSETS = [
  '/',
  '/offline',
  '/manifest.webmanifest',
];

// ── Install: pre-cache static shell ─────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// ── Activate: clean old caches ───────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET and cross-origin requests
  if (request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  // API routes: network-first, no cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(
          JSON.stringify({ detail: 'Offline — request could not be completed' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        )
      )
    );
    return;
  }

  // Navigation requests: network-first, fall back to cached page or offline page
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          return cached || caches.match(OFFLINE_PAGE);
        })
    );
    return;
  }

  // Static assets: cache-first
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
    )
  );
});

// ── Background sync for offline mutations ────────────────────────────────────
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-pending-logs') {
    event.waitUntil(syncPendingLogs());
  }
});

async function syncPendingLogs() {
  // Replay any queued mutations stored in IndexedDB when connectivity returns.
  // Actual queue implementation lives in the app; this hook triggers the flush.
  const clients = await self.clients.matchAll({ type: 'window' });
  clients.forEach((client) =>
    client.postMessage({ type: 'SW_SYNC_TRIGGER', tag: 'sync-pending-logs' })
  );
}

// ── Push notifications ───────────────────────────────────────────────────────
self.addEventListener('push', (event) => {
  if (!event.data) return;
  let data;
  try {
    data = event.data.json();
  } catch {
    data = { title: 'SentinelCV', body: event.data.text() };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || 'SentinelCV', {
      body: data.body || '',
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      tag: data.tag || 'sentinelcv-notification',
      data: data.url ? { url: data.url } : undefined,
      requireInteraction: data.requireInteraction || false,
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((clients) => {
        const existing = clients.find((c) => c.url === targetUrl && 'focus' in c);
        if (existing) return existing.focus();
        return self.clients.openWindow(targetUrl);
      })
  );
});
