// Current Law service worker: makes the site installable and keeps recently
// viewed pages readable offline. Pages are always fetched fresh when online.
const VERSION = "v3";
const STATIC = `static-${VERSION}`;
const PAGES = `pages-${VERSION}`;
const ASSETS = `assets-${VERSION}`;
const MAX_PAGES = 150;
const PRECACHE = [
  "/offline/",
  "/favicon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/apple-touch-icon.png",
  "/site.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keep = new Set([STATIC, PAGES, ASSETS]);
    for (const key of await caches.keys()) if (!keep.has(key)) await caches.delete(key);
    if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();
    await self.clients.claim();
  })());
});

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - max; i++) await cache.delete(keys[i]);
}

// Pages: network first, fall back to the last copy we saw, then the offline page.
async function page(event) {
  const req = event.request;
  try {
    const res = (await event.preloadResponse) || (await fetch(req));
    if (res.ok) {
      const copy = res.clone();
      event.waitUntil(caches.open(PAGES).then((c) => c.put(req, copy)).then(() => trim(PAGES, MAX_PAGES)));
    }
    return res;
  } catch {
    return (await caches.match(req, { ignoreSearch: true })) || (await caches.match("/offline/")) || Response.error();
  }
}

// Fingerprinted build files never change, so the cached copy is always right.
async function immutable(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) {
    const copy = res.clone();
    caches.open(ASSETS).then((c) => c.put(req, copy)).then(() => trim(ASSETS, 120));
  }
  return res;
}

// Icons and fonts: serve the cached copy and refresh it in the background.
async function revalidate(event) {
  const req = event.request;
  const hit = await caches.match(req);
  const net = fetch(req).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      caches.open(STATIC).then((c) => c.put(req, copy));
    }
    return res;
  });
  if (hit) {
    event.waitUntil(net.catch(() => {}));
    return hit;
  }
  return net;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const fonts = url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com";
  if (url.origin !== location.origin && !fonts) return;
  if (url.pathname.startsWith("/api/")) return;
  if (req.mode === "navigate") return event.respondWith(page(event));
  if (url.pathname.startsWith("/_astro/")) return event.respondWith(immutable(req));
  if (fonts || /\.(png|svg|ico|webmanifest|woff2?)$/.test(url.pathname)) {
    return event.respondWith(revalidate(event));
  }
});
