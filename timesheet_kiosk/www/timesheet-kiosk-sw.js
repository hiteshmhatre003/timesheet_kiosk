const CACHE = "timesheet-kiosk-v1";
const SHELL = [
  "/timesheet-kiosk",
  "/assets/timesheet_kiosk/css/timesheet-kiosk.css",
  "/assets/timesheet_kiosk/js/timesheet-kiosk-api.js",
  "/assets/timesheet_kiosk/js/timesheet-kiosk-app.js",
  "/assets/timesheet_kiosk/timesheet-kiosk-manifest.json",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

// Network-first for API calls, cache-first for the static shell.
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.includes("/api/")) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(caches.match(e.request).then((cached) => cached || fetch(e.request)));
});
