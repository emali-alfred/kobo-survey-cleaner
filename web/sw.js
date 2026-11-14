/* Offline support: the app files and the Python engine are kept after the
   first visit, so the cleaner works in the field without a connection. */

const VERSION = "__BUILD__";
const APP_CACHE = "surveyclean-app-" + VERSION;
const ENGINE_CACHE = "surveyclean-engine-v1"; // Pyodide files never change for a pinned version

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(APP_CACHE);
    const manifest = await (await fetch("surveyclean/files.json", { cache: "no-store" })).json();
    await cache.addAll([
      "./", "index.html", "app.js", "worker.js", "style.css", "privacy.html",
      "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png",
      "surveyclean/files.json", ...manifest.files.map((f) => "surveyclean/" + f),
    ]);
    self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== APP_CACHE && key !== ENGINE_CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (url.hostname === "cdn.jsdelivr.net" || url.hostname === "files.pythonhosted.org"
      || url.hostname === "pypi.org") {
    // Engine files: cache first, they are versioned.
    event.respondWith((async () => {
      const cache = await caches.open(ENGINE_CACHE);
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) cache.put(req, res.clone());
      return res;
    })());
    return;
  }

  if (url.origin === self.location.origin) {
    // App files: network first so updates arrive, cache when offline.
    event.respondWith((async () => {
      const cache = await caches.open(APP_CACHE);
      try {
        const res = await fetch(req, { cache: "no-cache" }); // revalidate, never a stale copy
        if (res.ok) cache.put(req, res.clone());
        return res;
      } catch {
        return (await cache.match(req, { ignoreSearch: true })) || (await cache.match("index.html"));
      }
    })());
  }
});
