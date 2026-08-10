// v3: same network-first-for-the-app-shell strategy as before (see the
// original v1 -> v2 note below) — always try the network first, cache is
// only a fallback for offline. The cache name is bumped again (v2 -> v3)
// because this file itself moved from /timesheet-kiosk-sw.js to
// /timesheet-sw.js as part of switching the app's URL from
// /timesheet-kiosk to /timesheet, which is effectively a brand new service
// worker registration (different scope) anyway — bumping the name just
// makes sure no stale v2 cache entries linger under the old scope.
//
// v2: network-first for the app shell. The previous cache-first strategy
// meant that once a browser had visited the app once, it kept serving the
// OLD cached JS/HTML forever, even after a new version was deployed — the
// only way to get updates was to clear site data. That's exactly why a
// bug fix "worked in incognito but not in a normal browser": incognito
// has no cache, so it always fetched the latest code; a normal browser
// kept replaying whatever was cached on the very first visit.
const CACHE = "timesheet-kiosk-v3";
const SHELL = [
  "/timesheet",
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

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return; // never intercept POST (API calls, login, etc.)

  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
