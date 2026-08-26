/* Offline-Betrieb: im Club ist der Empfang schlecht.
 *
 * Strategie: NETZ ZUERST fuer alles Eigene, Cache als Rueckfall.
 *
 * Vorher war es umgekehrt (Cache zuerst). Das hat einen echten Fehler
 * verursacht: die Dateinamen tragen keine Version, also lieferte der Cache
 * nach einem Deploy weiter die alte style.css aus, waehrend index.html und
 * app.js schon neu waren. Ergebnis war eine Mischung aus alt und neu - beim
 * Umschalten auf "immer hell" blieb die Ansicht dunkel, weil das alte CSS
 * data-theme gar nicht kannte.
 *
 * Netz zuerst kostet bei knapp 60 KB eigener Dateien wenig und schliesst
 * gemischte Staende aus. Offline bleibt es nutzbar: ist kein Netz da, schlaegt
 * fetch sofort fehl und der Cache greift; bei schlechtem Empfang bricht der
 * Timeout nach 2,5 s ab.
 */
const V = 'rbf26-v9';
const TIMEOUT_MS = 2500;
const SHELL = [
  './', 'index.html', 'style.css', 'app.js', 'team.js', 'plan.js', 'icon.svg',
  'manifest.webmanifest',
  'vendor/leaflet/leaflet.js', 'vendor/leaflet/leaflet.css',
  'vendor/leaflet/leaflet.markercluster.js',
  'vendor/leaflet/MarkerCluster.css', 'vendor/leaflet/MarkerCluster.Default.css',
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

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('timeout')), ms);
    promise.then((v) => { clearTimeout(t); resolve(v); },
                 (e) => { clearTimeout(t); reject(e); });
  });
}

async function networkFirst(req) {
  const cache = await caches.open(V);
  try {
    const res = await withTimeout(fetch(req), TIMEOUT_MS);
    if (res && res.ok) cache.put(req, res.clone()).catch(() => {});
    return res;
  } catch (err) {
    const hit = await cache.match(req, { ignoreSearch: false });
    if (hit) return hit;
    throw err;
  }
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Kartenkacheln nie cachen - das laeuft sonst voll.
  if (url.hostname.endsWith('openstreetmap.org')) return;

  // Fremde Hosts (Kuenstlerbilder) gehen direkt ans Netz.
  if (url.origin !== location.origin) return;

  // Die Team-API niemals cachen: dort geht es um den aktuellen Stand, und ein
  // zwischengespeicherter Abgleich waere schlimmer als keiner.
  if (url.pathname.startsWith('/api/')) return;

  e.respondWith(networkFirst(req));
});
