/* Cumulous shell SW — network-first for shell so version/install updates stick */
const SHELL = "cumulous-shell-v0.2.8-library-albums";
const ASSETS = ["/app/", "/app/index.html", "/app/manifest.webmanifest", "/install/icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  // Install / version / progress always live from Mac
  if (
    u.pathname.startsWith("/photos/") ||
    u.pathname.startsWith("/install") ||
    u.pathname.startsWith("/app/version") ||
    u.pathname.startsWith("/backup/") ||
    u.pathname.startsWith("/challenge/")
  ) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  if (u.pathname.startsWith("/app") || u.pathname === "/install/icon.png") {
    // Network-first so always-latest shell + version
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copy = r.clone();
          caches.open(SHELL).then((c) => c.put(e.request, copy));
          return r;
        })
        .catch(() => caches.match(e.request))
    );
  }
});
