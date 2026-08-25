/* Offline-Betrieb: im Club ist der Empfang schlecht.
   Huelle aus dem Cache, Daten bevorzugt aus dem Netz mit Cache als Rueckfall. */
const V = 'rbf26-v1';
const SHELL = [
  './', 'index.html', 'style.css', 'app.js', 'icon.svg', 'manifest.webmanifest',
  'vendor/leaflet/leaflet.js', 'vendor/leaflet/leaflet.css',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(V)
    .then((c) => c.addAll(SHELL))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== V).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Kartenkacheln nie cachen - das laeuft sonst voll.
  if (url.hostname.endsWith('openstreetmap.org')) return;

  // Programmdaten: frisch bevorzugt, offline der letzte Stand.
  if (url.pathname.endsWith('lineup.json')) {
    e.respondWith(
      fetch(req).then((res) => {
        caches.open(V).then((c) => c.put(req, res.clone()));
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  if (url.origin !== location.origin) return;
  e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
    if (res.ok) caches.open(V).then((c) => c.put(req, res.clone()));
    return res;
  })));
});
