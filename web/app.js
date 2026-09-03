/* Reeperbahn-Timetable. Vanilla, kein Build-Schritt.
   Eigener Zustand (Favoriten, Notizen, Ampel) bleibt im Browser. */
'use strict';

const DATA_URL = 'data/lineup.json';
const KEY = 'rbf26.';
const WD = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
const RATES = [[1, 'sehr gut'], [1.5, 'sehr gut bis gut'], [2, 'gut'],
               [2.5, 'gut bis geht so'], [3, 'geht so'], [4, 'eher nicht'],
               [5, 'gar nicht']];
// Bis Version 1 gab es drei Stufen. Alte Bewertungen werden auf die Skala
// abgebildet, damit auf dem Handy nichts verloren geht.
const RATE_MIGRATION = { gruen: 1, gelb: 3, rot: 5 };

/* Die Zwischennoten 1,5 und 2,5 zaehlen im FILTER zur naechstbesseren ganzen
   Note: wer "1" filtert, will 1,5 mitsehen. Deshalb gibt es zwei Ebenen -
   die Note, die man vergibt, und der Eimer, in dem sie landet. Der Eimer
   steuert Filter, Randfarbe und Abendplan; die Note steht als Zahl dran. */
const rateBucket = (r) => Math.floor(+r) || 0;
/* 1.5 als "1,5" - im Deutschen mit Komma. */
const rateText = (r) => String(r).replace('.', ',');
const NO_GENRE = -1;   // eigener Eimer: Acts ohne Genre-Angabe

/* ---------- Speicher: faellt still auf Arbeitsspeicher zurueck ---------- */

const mem = {};
const store = {
  get(k, fallback) {
    try {
      const raw = localStorage.getItem(KEY + k);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) { return k in mem ? mem[k] : fallback; }
  },
  set(k, v) {
    mem[k] = v;
    try { localStorage.setItem(KEY + k, JSON.stringify(v)); } catch (e) { /* privater Modus */ }
  },
};

const fav = new Set(store.get('fav', []));
const seen = new Set(store.get('seen', []));
/* Acts, bei denen die Team-Meinung bewusst aufgedeckt wurde, obwohl man
   selbst noch nicht bewertet hat - siehe teamRowMark(). */
const revealed = new Set(store.get('revealed', []));
const saveRevealed = () => store.set('revealed', [...revealed]);
let note = store.get('note', {});
let rate = store.get('rate', {});
(() => {
  let touched = false;
  for (const [id, v] of Object.entries(rate)) {
    if (typeof v === 'string' && v in RATE_MIGRATION) { rate[id] = RATE_MIGRATION[v]; touched = true; }
  }
  if (touched) store.set('rate', rate);
})();
const anchor = store.get('anchor', {});
/* Vorschlaege aus taste.py. Getrennt von "rate": die eigene Bewertung
   gewinnt immer, der Vorschlag ist nur eine Vorbelegung. */
let hint = store.get('hint', {});
/* Auswahl der Partner:in - nur gelesen, niemals veraendert. Getrennt zu
   halten ist der ganze Trick: jede Seite schreibt ausschliesslich ihre eigene
   Datei, damit kann beim Zusammenfuehren nichts kollidieren. */
let partner = store.get('partner', null);
// Wann der letzte Abgleich durchlief - steht in der Fusszeile und im
// Menue. Weit oben deklariert, weil metaLine() und teamInfo() es lesen.
let lastSyncAt = store.get('lastsync', null);
/* Gespeicherte Filtersaetze. Die Suche gehoert absichtlich NICHT dazu: ein
   gespeicherter Filter soll eine Sicht sein, kein eingefrorener Suchbegriff. */
let savedFilters = store.get('filters', []);
const team = window.RBFTeam ? window.RBFTeam.createTeamClient(store) : null;
let syncing = false;

const saveFav = () => store.set('fav', [...fav]);
const saveSeen = () => store.set('seen', [...seen]);

/* ---------- Ansicht hell/dunkel ----------
   Drei Zustaende: Systemvorgabe, immer hell, immer dunkel. Die Wahl steht in
   localStorage und wird als data-theme auf <html> gesetzt; das CSS entscheidet
   den Rest. */

const THEMES = ['system', 'light', 'dark'];
// Gleiche Strichstaerke und Groesse wie die uebrigen Kopf-Icons, damit der
// Schalter nicht wie ein Textzeichen zwischen SVGs sitzt.
const THEME_ICON = {
  system: '<circle cx="12" cy="12" r="8"/><path d="M12 4v16" />'
        + '<path d="M12 6a6 6 0 0 0 0 12z" fill="currentColor" stroke="none"/>',
  light: '<circle cx="12" cy="12" r="4.2"/>'
       + '<path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2'
       + 'M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"/>',
  dark: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a7.5 7.5 0 1 0 10.5 10.5z"/>',
};
const THEME_LABEL = { system: 'Systemvorgabe', light: 'hell', dark: 'dunkel' };
let theme = store.get('theme', 'system');

function applyTheme() {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
  const icon = document.getElementById('theme-icon');
  if (icon) icon.innerHTML = THEME_ICON[theme];
  const btn = document.getElementById('btn-theme');
  if (btn) btn.title = `Ansicht: ${THEME_LABEL[theme]}`;
  for (const b of document.querySelectorAll('[data-theme-set]')) {
    b.setAttribute('aria-pressed', String(b.dataset.themeSet === theme));
  }
  // Die Browserleiste soll mitziehen.
  const dark = theme === 'dark' || (theme === 'system'
    && matchMedia('(prefers-color-scheme: dark)').matches);
  for (const m of document.querySelectorAll('meta[name="theme-color"]')) m.remove();
  const meta = document.createElement('meta');
  meta.name = 'theme-color';
  meta.content = dark ? '#12111c' : '#faf8fd';
  document.head.appendChild(meta);
}

function setTheme(next) {
  theme = THEMES.includes(next) ? next : 'system';
  store.set('theme', theme);
  applyTheme();
}

applyTheme();

/* ---------- Zustand ---------- */

const S = {
  data: null,
  day: null,
  q: '',
  favOnly: false,
  rates: new Set(),
  genres: new Set(),
  venues: new Set(),
  seenOnly: false,
  teamOnly: false,
  mapOn: false,
  planOn: false,
};

const MAP_DETAIL_ZOOM = 17;
let map = null, cluster = null;
let venueCode = [];             // Index des Spielorts -> zwei Buchstaben
const markers = [];
const popupHtml = [];

const $ = (sel) => document.querySelector(sel);
const el = {
  status: $('#status'), list: $('#list'), mapBox: $('#map'), days: $('#days'),
  genrebox: $('#genrebox'), venuebox: $('#venuebox'),
  ratebox: $('#ratebox'), filterbox: $('#filterbox'),
  plan: $('#plan'), planBody: $('#plan-body'),
  news: $('#news'), newsBody: $('#news-body'),
  detail: $('#detail'), menu: $('#menu'), meta: $('#meta'),
  filePartner: $('#file-partner'),
  q: $('#q'), searchbar: $('#searchbar'), file: $('#file'),
  player: $('#player'), toast: $('#toast'),
  quick: $('#quick'), swipe: $('#swipe'),
};

/* Kurze Rueckmeldung ohne Dialog - fuer Dinge, die keine Bestaetigung
   brauchen, aber sichtbar sein muessen. Mit undo bekommt sie einen Knopf:
   eine Wischgeste passiert leicht versehentlich, und ohne Ruecknahme muesste
   man den Act erst wieder suchen. */
let toastTimer = null;
let toastFade = null;
function hideToast() {
  clearTimeout(toastTimer); clearTimeout(toastFade);
  el.toast.classList.remove('is-on');
  toastFade = setTimeout(() => { el.toast.hidden = true; }, 200);
}
function toast(text, ms = 2400, undo = null) {
  clearTimeout(toastTimer); clearTimeout(toastFade);
  el.toast.textContent = text;
  if (undo) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'toast-undo';
    b.textContent = 'Zurücknehmen';
    b.addEventListener('click', () => { undo(); hideToast(); });
    el.toast.append(b);
  }
  // Ohne Knopf darf die Meldung keine Tipper abfangen.
  el.toast.style.pointerEvents = undo ? 'auto' : 'none';
  el.toast.hidden = false;
  el.toast.classList.add('is-on');
  toastTimer = setTimeout(hideToast, ms);
}

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const hhmm = (iso) => iso ? iso.slice(11, 16) : '';
const pRate = (id) => (partner && partner.rate ? +partner.rate[id] || 0 : 0);
const pFav = (id) => !!(partner && partner.fav && partner.fav.includes(id));
const pSeen = (id) => !!(partner && partner.seen && partner.seen.includes(id));
/* "Beide": ein Act, den beide als Favorit haben oder beide mit 1-2 bewerten.
   Das ist die Frage, die ein Team wirklich hat - wo wollen wir zusammen hin.
   Ueber den Eimer gerechnet, damit 1,5 und 2,5 mitzaehlen. */
const bothWant = (id) => {
  const mine = fav.has(id) || (rateBucket(rate[id]) > 0 && rateBucket(rate[id]) <= 2);
  const theirs = pFav(id) || (rateBucket(pRate(id)) > 0 && rateBucket(pRate(id)) <= 2);
  return mine && theirs;
};

/* Ob es zu einem Act ueberhaupt eine Team-Meinung gibt (Note oder Favorit -
   "gesehen" allein zaehlt nicht, das ist keine Wertung). */
const teamHasOpinion = (id) => rateBucket(pRate(id)) > 0 || pFav(id);
/* Erst zeigen, wenn man selbst bewertet hat, sonst faerbt die fremde Note die
   eigene ein, bevor sie entsteht - oder wenn bewusst aufgedeckt wurde. */
const teamOpinionShown = (id) => rateBucket(rate[id]) > 0 || revealed.has(id);

/* In der Zeile: solange verdeckt, dieselbe Marke wie eine echte Note -
   nur mit "?" statt Zahl und ohne Farbe nach Note, damit die Farbe selbst
   nichts verraet. Gleiche Form wie .grade-p, bewusst kein eigenes Symbol,
   sonst faellt es visuell aus der Zeile statt als "eine Note" erkannt zu
   werden. */
function teamRowMark(id, rb) {
  if (!teamHasOpinion(id)) return '';
  if (rb <= 0 && !teamOpinionShown(id)) {
    return `<span class="grade grade-p team-hidden"
      title="${esc(partnerName())} hat schon bewertet — sichtbar, sobald du selbst bewertest"
      >?</span>`;
  }
  const pb = rateBucket(pRate(id));
  return `${pb ? `<span class="grade grade-p grade-p-${pb}"
      title="${esc(partnerName())}: Note ${rateText(pRate(id))}">${
      rateText(pRate(id))}</span>` : ''}${
    pFav(id) ? `<span class="heart-p" title="${esc(partnerName())}: Favorit">♥</span>` : ''}`;
}

/* In der Detailansicht: derselbe Schutz, aber mit Knopf zum bewussten
   Aufdecken statt nur dem stummen Punkt. */
function teamSuggestion(id) {
  const seenNote = pSeen(id) ? ' · gesehen' : '';
  if (!teamHasOpinion(id)) {
    return `<span>${esc(partnerName())}: noch keine Angabe${seenNote}</span>`;
  }
  if (!teamOpinionShown(id)) {
    return `<span>${esc(partnerName())} hat schon bewertet — noch nicht sichtbar,
      damit deine eigene Einschätzung unvoreingenommen bleibt.${seenNote}</span>
      <button type="button" class="chip chip-ghost" data-reveal="${id}"
        >Trotzdem anzeigen</button>`;
  }
  return `<span>${esc(partnerName())}:
    ${pRate(id) ? `<b>Note ${rateText(pRate(id))}</b>` : 'keine Note'}${
      pFav(id) ? ' · <b>Favorit</b>' : ''}${seenNote}${
      bothWant(id) ? ' — <b>ihr wollt beide hin</b>' : ''}</span>`;
}

/* Zieht das Team-Feld im offenen Detaildialog nach, falls er gerade genau
   diesen Act zeigt - etwa wenn die eigene Note eben erst die Ansicht
   freigeschaltet hat. */
function refreshTeamBox(ai) {
  const box = document.getElementById('d-team');
  if (!box || +el.detail.dataset.ai !== ai) return;
  const act = S.data.acts[ai];
  const inner = box.querySelector('.suggestion');
  if (inner && act) inner.innerHTML = teamSuggestion(act.id);
}
const fold = (s) => String(s ?? '').toLowerCase()
  .normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/ø/g, 'o').replace(/ß/g, 'ss');

/* ---------- Laden ---------- */

/* ---------- Aenderungen am Programm ----------
   Uhrzeiten verschieben sich beim Reeperbahn Festival dauernd: sie stehen
   zuerst als Platzhalter im System und werden spaeter praezisiert. Wer sich
   einen Abend gebaut hat, muss das mitbekommen - sonst steht er vor der
   falschen Tuer.

   build_changes.py vergleicht die Snapshots und legt web/data/changes.json
   ab. Fehlt die Datei, laeuft die App normal weiter: sie ist eine Zugabe,
   keine Voraussetzung. */
let changes = { entries: [] };
let changeByShow = new Map();

async function loadChanges() {
  try {
    const res = await fetch('data/changes.json', { cache: 'no-cache' });
    if (!res.ok) return;
    const d = await res.json();
    if (!d || !Array.isArray(d.entries)) return;
    changes = d;
    changeByShow = new Map();
    for (const e of d.entries) {
      if (!e.show) continue;
      const key = String(e.show);
      if (!changeByShow.has(key)) changeByShow.set(key, []);
      changeByShow.get(key).push(e);
    }
  } catch (e) { /* ohne Aenderungsliste laeuft die App genauso */ }
}

const CHANGE_KIND = { moved: 'verschoben', added: 'neu',
                      removed: 'gestrichen' };

function changeNote(showId) {
  const list = changeByShow.get(String(showId));
  if (!list || !list.length) return null;
  const e = list[0];
  const when = new Date(e.at);
  const day = isNaN(when) ? e.at : when.toLocaleDateString('de-DE');
  return {
    kind: e.kind,
    text: e.kind === 'moved'
      ? `${e.what}: ${e.from} → ${e.to} (bemerkt am ${day})`
      : `${e.what} (bemerkt am ${day})`,
  };
}

/* Der letzte brauchbare Stand, im Browser abgelegt.

   Der Service Worker hat schon einen Zwischenspeicher, und offline
   funktioniert die App damit auch (gemessen: 406 Zeilen nach dem Neuladen
   ohne Netz). Er deckt aber zwei Faelle NICHT ab: der Browser kann seinen
   Zwischenspeicher unter Platzmangel wegwerfen, und wenn der Server mit 200
   antwortet, aber Unsinn liefert - ein kaputter Build zum Beispiel -, wird
   der gute Stand vom schlechten ueberschrieben.

   Deshalb hier eine zweite, unabhaengige Kopie plus eine Plausibilitaets-
   pruefung: was keine Acts und keine Auftritte hat, wird nicht uebernommen.
   370 KB sind viel fuer localStorage, passen aber in die ueblichen 5 MB. */
const LAST_GOOD = 'lineup';

function looksUsable(d) {
  return !!(d && Array.isArray(d.acts) && d.acts.length
            && Array.isArray(d.shows) && d.shows.length
            && Array.isArray(d.days) && Array.isArray(d.venues));
}

let usingFallback = null;   // Datum des angezeigten Standes, falls Notkopie

async function load() {
  let fresh = null;
  let why = '';
  try {
    const res = await fetch(DATA_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const parsed = await res.json();
    if (!looksUsable(parsed)) throw new Error('Datei unvollständig');
    fresh = parsed;
  } catch (err) {
    why = err.message;
  }

  if (fresh) {
    S.data = fresh;
    usingFallback = null;
    // Nach dem ersten Zeichnen ablegen, damit der Start nicht warten muss.
    setTimeout(() => {
      try { store.set(LAST_GOOD, fresh); } catch (e) { /* Speicher voll */ }
    }, 1200);
  } else {
    const kept = store.get(LAST_GOOD, null);
    if (looksUsable(kept)) {
      S.data = kept;
      usingFallback = kept.generated_at || null;
    } else {
      el.status.innerHTML = '<b>Programm konnte nicht geladen werden.</b><br>'
        + esc(why) + '<br><small>Und es gibt noch keinen gespeicherten Stand — '
        + 'beim ersten Aufruf braucht die App einmal Netz.</small>';
      return;
    }
  }
  // Waehrend des Festivals der heutige Tag, sonst alles - vorher will man
  // stoebern, waehrenddessen den Abend.
  S.day = S.data.days.includes(todayISO()) ? todayISO() : null;
  // Vor dem ersten render(): die Kuerzel stehen auch in der Liste, nicht nur
  // auf der Karte - sonst muesste man die Zuordnung jedes Mal neu suchen.
  venueCode = venueCodes(S.data.venues);
  el.status.hidden = true;
  renderDays();
  renderGenres();
  renderVenues();
  renderRates();
  renderSavedFilters();
  render();
  metaLine();
  showStaleBanner();
}

/* Ein alter Stand muss dranstehen. Sonst plant man den Abend nach Daten von
   letzter Woche und merkt es nicht.

   Zwei Faelle, und der zweite war beim ersten Versuch nicht abgedeckt:

   1. Der Abruf ist gescheitert und die eigene Notkopie hat uebernommen.
   2. Der Abruf hat GEKLAPPT, aber der Service Worker hat aus seinem
      Zwischenspeicher geantwortet, weil kein Netz da ist. Dann kommt gueltig
      aussehende Ware an, die beliebig alt sein kann - der Grund, warum die
      Liste ohne Netz ueberhaupt noch da ist. Ohne Hinweis haelt man sie fuer
      aktuell. Erkannt an navigator.onLine: ist das falsch, kann nichts
      frisch sein, egal wer geantwortet hat. */
function showStaleBanner() {
  const bar = $('#stale');
  if (!bar) return;
  const offline = navigator.onLine === false;
  const stamp = usingFallback || (offline && S.data ? S.data.generated_at : null);
  if (!stamp) { bar.hidden = true; return; }
  const d = new Date(stamp);
  bar.innerHTML = '<b>Kein Netz.</b> Angezeigt wird der gespeicherte Stand vom '
    + esc(isNaN(d) ? String(stamp) : d.toLocaleString('de-DE'))
    + '. Verschiebungen danach fehlen.';
  bar.hidden = false;
}

/* Kommt das Netz zurueck, muss der Hinweis weg - und der frische Stand her. */
addEventListener('online', () => {
  showStaleBanner();
  load().then(loadChanges).then(() => { if (S.data) render(); });
});
addEventListener('offline', showStaleBanner);

/* Die Fusszeile sagt jetzt auch, ob der Team-Abgleich laeuft. Vorher stand das
   nur im Menue - man musste es aufklappen, um zu sehen, dass gar kein Team
   eingerichtet war. */
function metaLine() {
  if (!S.data) return;
  const d = new Date(S.data.generated_at);
  let t = `${S.data.acts.length} Acts · ${S.data.shows.length} Auftritte · `
    + `Stand ${isNaN(d) ? S.data.generated_at : d.toLocaleDateString('de-DE')}`;
  if (team && team.config) {
    t += ` · Team-Abgleich an${lastSyncAt ? ', ' + relTime(lastSyncAt) : ''}`;
  }
  el.meta.textContent = t;
}

const todayISO = () => new Date().toISOString().slice(0, 10);

/* ---------- Kopfbereich ---------- */

function renderDays() {
  const all = `<button class="day" role="tab" data-day=""
    aria-selected="${S.day === null}">Alle
    <small>${S.data.days.length} Tage</small></button>`;
  el.days.innerHTML = all + S.data.days.map((d) => {
    const dt = new Date(d + 'T12:00:00');
    return `<button class="day" role="tab" data-day="${d}"
      aria-selected="${d === S.day}">${WD[dt.getDay()]}
      <small>${dt.getDate()}.${dt.getMonth() + 1}.</small></button>`;
  }).join('');
}

function renderGenres() {
  const counts = new Map();
  for (const sh of S.data.shows) {
    const g = S.data.acts[sh.a].g;
    if (!g.length) counts.set(NO_GENRE, (counts.get(NO_GENRE) || 0) + 1);
    for (const i of g) counts.set(i, (counts.get(i) || 0) + 1);
  }
  const entries = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
  el.genrebox.innerHTML = entries.map(([i, n]) => {
    const label = i === NO_GENRE ? 'ohne Angabe' : S.data.genres[i];
    return `<button class="chip" data-genre="${i}"
      aria-pressed="${S.genres.has(i)}">${esc(label)} <span class="tag">${n}</span></button>`;
  }).join('');
}

function renderVenues() {
  const counts = new Map();
  for (const sh of S.data.shows) {
    if (sh.v != null) counts.set(sh.v, (counts.get(sh.v) || 0) + 1);
  }
  // Nach Anzahl sortiert: die grossen Haeuser zuerst, danach alphabetisch.
  const entries = [...counts.entries()].sort((a, b) =>
    b[1] - a[1] || S.data.venues[a[0]].n.localeCompare(S.data.venues[b[0]].n, 'de'));
  // Das Kuerzel steht HIER, nicht in jeder Programmzeile: in der Zeile stand
  // es direkt neben dem vollen Namen und las sich doppelt ("25  25 Club").
  // Dieser Kasten ist die Stelle, an der man die Zuordnung nachschaut.
  el.venuebox.innerHTML = entries.map(([i, n]) =>
    `<button class="chip" data-venuefilter="${i}" aria-pressed="${S.venues.has(i)}"
      ><span class="vcode">${esc(venueCode[i] || '')}</span>${
      esc(S.data.venues[i].n)} <span class="tag">${n}</span></button>`).join('');
}

/* Genau ein Kasten offen. Paarweise Verdrahtung war bei zwei Kaesten noch
   uebersichtlich, bei vier ist sie eine Fehlerquelle. */
const BOXES = ['genrebox', 'ratebox', 'venuebox', 'filterbox'];

function openBox(which) {
  const wasOpen = which && !el[which].hidden;
  for (const name of BOXES) el[name].hidden = true;
  if (which && !wasOpen) el[which].hidden = false;
  $('#btn-filters').setAttribute('aria-pressed', String(!el.filterbox.hidden));
  sizeMap();
}

/* Der Filter hat fuenf Stufen, nicht sieben: 1,5 wird unter 1 mitgezaehlt
   und 2,5 unter 2. Die Zahl am Chip zaehlt beide Noten zusammen, sonst
   passt sie nicht zu dem, was der Filter dann zeigt. */
function renderRates() {
  const counts = new Map();
  let unrated = 0;
  for (const a of S.data.acts) {
    const b = rateBucket(rate[a.id]);
    if (b) counts.set(b, (counts.get(b) || 0) + 1);
    else unrated++;
  }
  const halves = new Map();
  for (const [n] of RATES) if (!Number.isInteger(n)) halves.set(rateBucket(n), n);
  const numbered = RATES.filter(([n]) => Number.isInteger(n))
    .map(([n, label]) => {
      const half = halves.get(n);
      return `<button class="chip" data-rate="${n}" aria-pressed="${S.rates.has(n)}"
        >${n}${half ? ` und ${rateText(half)}` : ''} ${esc(label)}
        <span class="tag">${counts.get(n) || 0}</span></button>`;
    }).join('');
  // Eigener Eimer 0: Acts ohne eigene Note. Kein regulaerer RATES-Wert, weil
  // 0 keine Note ist, sondern ihr Fehlen - filtert aber ueber denselben
  // rateBucket()-Vergleich mit, der fuer unbewertete Acts ohnehin 0 liefert.
  const none = `<button class="chip chip-ghost" data-rate="0" aria-pressed="${S.rates.has(0)}"
    >noch nicht bewertet
    <span class="tag">${unrated}</span></button>`;
  el.ratebox.innerHTML = numbered + none;
}

/* ---------- Filterspeicher ---------- */

function currentFilter() {
  return {
    day: S.day,
    fav: S.favOnly,
    seen: S.seenOnly,
    team: S.teamOnly,
    rates: [...S.rates],
    genres: [...S.genres],
    venues: [...S.venues],
  };
}

function describeFilter(f) {
  const bits = [];
  if (f.day) bits.push(dayLabel(f.day));
  else bits.push('alle Tage');
  if (f.fav) bits.push('Favoriten');
  if (f.seen) bits.push('gesehen');
  if (f.team) bits.push('beide');
  if (f.rates && f.rates.length) {
    const nums = f.rates.filter((n) => n !== 0);
    const parts = [];
    if (nums.length) parts.push('Note ' + nums.join('/'));
    if (f.rates.includes(0)) parts.push('unbewertet');
    bits.push(parts.join(' + '));
  }
  if (f.genres && f.genres.length) {
    bits.push(f.genres.map((i) => i === NO_GENRE ? 'ohne Angabe' : S.data.genres[i]).join(', '));
  }
  if (f.venues && f.venues.length) {
    bits.push(f.venues.map((i) => (S.data.venues[i] || {}).n || '?').join(', '));
  }
  return bits.join(' · ');
}

function applyFilter(f) {
  S.day = f.day ?? null;
  S.favOnly = !!f.fav;
  S.seenOnly = !!f.seen;
  S.teamOnly = !!f.team;
  S.rates = new Set((f.rates || []).map(Number));
  S.genres = new Set((f.genres || []).map(Number));
  S.venues = new Set((f.venues || []).map(Number));
  S.q = '';
  el.q.value = '';
  el.searchbar.hidden = true;
  for (const [id, on] of [['f-fav', S.favOnly], ['f-seen', S.seenOnly],
                          ['f-team', S.teamOnly]]) {
    $('#' + id).setAttribute('aria-pressed', String(on));
  }
  renderDays();
  renderGenres();
  renderVenues();
  renderRates();
  render();
}

function renderSavedFilters() {
  const list = $('#filterlist');
  const hint = $('#filterhint');
  if (!list) return;
  if (!savedFilters.length) {
    list.innerHTML = '<span class="menu-note">Noch nichts gespeichert. '
      + 'Filter einstellen, unten benennen, speichern.</span>';
  } else {
    list.innerHTML = savedFilters.map((f, i) =>
      `<span class="saved">
         <button class="saved-use" data-usefilter="${i}"
           title="${esc(describeFilter(f.f))}">${esc(f.name)}</button>
         <button class="saved-del" data-delfilter="${i}"
           aria-label="${esc(f.name)} löschen">✕</button>
       </span>`).join('');
  }
  if (hint) hint.textContent = 'Gespeichert werden Tag, Genres, Spielorte, Noten '
    + 'und die Schalter — der Suchbegriff nicht.';
}

/* ---------- Auswahl ---------- */

function visibleShows() {
  const q = fold(S.q.trim());
  const searching = q.length > 0;
  const spanAll = searching || S.day === null;
  const out = [];

  for (const sh of S.data.shows) {
    const act = S.data.acts[sh.a];

    // Ueber alle Tage: bei aktiver Suche und wenn "Alle" gewaehlt ist.
    if (!spanAll && sh.d && sh.d !== S.day) continue;

    if (S.favOnly && !fav.has(act.id)) continue;
    if (S.rates.size && !S.rates.has(rateBucket(rate[act.id]))) continue;
    if (S.seenOnly && !seen.has(act.id)) continue;
    if (S.teamOnly && !bothWant(act.id)) continue;

    if (S.venues.size && (sh.v == null || !S.venues.has(sh.v))) continue;

    if (S.genres.size) {
      const g = act.g;
      const hit = g.length
        ? g.some((i) => S.genres.has(i))
        : S.genres.has(NO_GENRE);
      if (!hit) continue;
    }

    if (searching) {
      const venue = sh.v != null ? S.data.venues[sh.v].n : '';
      const hay = fold([act.n, act.c, venue, ...act.g.map((i) => S.data.genres[i])].join(' '));
      if (!hay.includes(q)) continue;
    }

    out.push(sh);
  }
  return out;
}

/* ---------- Liste ---------- */

/* ---------- Nur das Noetige neu zeichnen ----------
   render() baut die ganze Liste neu: 406 Zeilen, 285 KB HTML, auf einem
   gebremsten Handy 111 ms gemessen. Nach jedem Tippen auf eine Note fuehlt
   sich das an wie Haengen.

   Aendert sich nur der Zustand EINES Acts, werden deshalb nur dessen Zeilen
   ersetzt. Voll neu gebaut wird nur, wenn die Aenderung entscheidet, WELCHE
   Zeilen sichtbar sind - dann muss die Zeile ja verschwinden oder
   auftauchen. */
let showById = null;
function showMap() {
  if (!showById) showById = new Map(S.data.shows.map((s) => [String(s.id), s]));
  return showById;
}

/* Wie oft ein Act ueberhaupt spielt. 62 der 342 Acts treten mehrfach auf
   (60 zweimal, 2 dreimal) - ohne Hinweis in der Liste plant man den falschen
   Termin ein oder haelt einen fuer verpasst, den man noch sehen kann. */
let showsPerAct = null;
function actShowCount(ai) {
  if (!showsPerAct) {
    showsPerAct = new Map();
    for (const s of S.data.shows) {
      showsPerAct.set(s.a, (showsPerAct.get(s.a) || 0) + 1);
    }
  }
  return showsPerAct.get(ai) || 1;
}

/* Der wievielte Auftritt dieses Acts ist das? Nach Zeit sortiert, damit
   "2 von 2" auch stimmt. */
let showOrdinal = null;
function actShowOrdinal(sh) {
  if (!showOrdinal) {
    showOrdinal = new Map();
    const byAct = new Map();
    for (const s of S.data.shows) {
      if (!byAct.has(s.a)) byAct.set(s.a, []);
      byAct.get(s.a).push(s);
    }
    for (const list of byAct.values()) {
      list.sort((a, b) => String(a.t || '').localeCompare(String(b.t || '')));
      list.forEach((s, i) => showOrdinal.set(String(s.id), i + 1));
    }
  }
  return showOrdinal.get(String(sh.id)) || 1;
}

function refreshAct(ai) {
  if (!Number.isFinite(ai) || !S.data) { render(); return; }
  // Ein aktiver Filter auf Note, Favorit, Gesehen oder Team entscheidet ueber
  // die Sichtbarkeit - dann hilft Flicken nicht.
  if (S.rates.size || S.favOnly || S.seenOnly || S.teamOnly) { render(); return; }
  const rows = el.list.querySelectorAll(`.row[data-act="${ai}"]`);
  if (!rows.length) return;
  const act = S.data.acts[ai];
  const map = showMap();
  for (const node of rows) {
    const sh = map.get(node.dataset.show);
    if (sh) node.outerHTML = row(sh, act);
  }
}

let renderPending = false;

function render() {
  /* Nicht mitten in einer Wischgeste neu bauen: der Neuaufbau ersetzt genau
     die Zeile, an der der Finger haengt. Danach zeigte die Anzeige auf eine
     Zeile, die es nicht mehr gab - so entstand das Bild mit dem Feld an der
     falschen Stelle. Nachgeholt wird es beim Loslassen. */
  if (sw && sw.active) { renderPending = true; return; }
  renderPending = false;
  const anyFilter = S.favOnly || S.rates.size > 0 || S.seenOnly || S.teamOnly
    || S.genres.size > 0 || S.venues.size > 0 || S.q.trim() !== '';
  $('#f-reset').hidden = !anyFilter;
  $('#f-genre').classList.toggle('on', S.genres.size > 0);
  $('#f-genre').textContent = S.genres.size ? `Genres (${S.genres.size})` : 'Genres';
  $('#f-rate').classList.toggle('on', S.rates.size > 0);
  $('#f-rate').textContent = S.rates.size ? `Bewertet (${S.rates.size})` : 'Bewertet';
  $('#f-team').hidden = !partner;
  $('#f-venue').classList.toggle('on', S.venues.size > 0);
  $('#f-venue').textContent = S.venues.size ? `Spielorte (${S.venues.size})` : 'Spielorte';

  if (S.newsOn) {
    el.list.hidden = true; el.mapBox.hidden = true;
    el.plan.hidden = true; el.news.hidden = false;
    renderNews();
    return;
  }
  el.news.hidden = true;
  if (S.planOn) {
    el.list.hidden = true; el.mapBox.hidden = true; el.plan.hidden = false;
    renderPlan();
    return;
  }
  el.plan.hidden = true;
  if (S.mapOn) { el.list.hidden = true; el.mapBox.hidden = false; sizeMap(); return; }
  el.mapBox.hidden = true;
  el.list.hidden = false;

  const shows = visibleShows();
  if (!shows.length) {
    el.list.innerHTML = `<p class="empty"><b>Nichts gefunden.</b>
      ${anyFilter ? 'Vielleicht ist ein Filter zu eng.' : ''}</p>`;
    return;
  }

  const spanAll = S.q.trim() !== '' || S.day === null;
  let html = '', head = '';
  for (const sh of shows) {
    const act = S.data.acts[sh.a];
    const group = sh.tbd
      ? (spanAll ? dayLabel(sh) + ' - Uhrzeit noch offen' : 'Uhrzeit noch offen')
      : (spanAll ? dayLabel(sh) + ' ' + hhmm(sh.t).slice(0, 2) + ' Uhr'
                 : hhmm(sh.t).slice(0, 2) + ' Uhr');
    if (group !== head) { head = group; html += `<div class="slot-head">${esc(head)}</div>`; }
    html += row(sh, act);
  }
  el.list.innerHTML = html;
  restoreAnchor();
}

/* Label immer aus dem Festivaltag, nicht aus dem Kalendertag: ein Auftritt um
   00:30 gehoert zur Nacht des Vortags. */
function dayLabel(sh) {
  const d = typeof sh === 'string' ? sh : (sh.d || (sh.t || '').slice(0, 10));
  if (!d) return '';
  return WD[new Date(d + 'T12:00:00').getDay()];
}

function row(sh, act) {
  const venue = sh.v != null ? S.data.venues[sh.v] : null;
  const r = rate[act.id];
  // Randfarbe und Notenfarbe folgen dem Eimer, weil es fuer 1,5 keine eigene
  // Farbe gibt und braucht: die genaue Note steht als Zahl daneben.
  const rb = rateBucket(r);
  const tags = act.g.map((i) => `<span class="tag">${esc(S.data.genres[i])}</span>`).join('');
  const chg = changeNote(sh.id);
  const changeMark = chg
    ? `<span class="chg chg-${chg.kind}" title="${esc(chg.text)}">⟳</span>`
    : '';
  const total = actShowCount(sh.a);
  const nth = total > 1 ? actShowOrdinal(sh) : 1;
  const multi = total > 1
    ? `<span class="multi" title="Spielt ${total}× beim Festival — das hier ist Auftritt ${nth}">×${total}</span>`
    : '';
  return `<button class="row${rb ? ' rated-' + rb : ''}" data-show="${esc(sh.id)}" data-act="${sh.a}">
    <span class="row-time${sh.tbd ? ' tbd' : ''}">${sh.tbd ? 'Zeit<br>offen' : hhmm(sh.t)}${changeMark}</span>
    <span class="row-main">
      <span class="row-name${note[act.id] ? ' has-note' : ''}${
        seen.has(act.id) ? ' seen-mark' : ''}">${esc(act.n)}${multi}${
        rb ? `<span class="grade grade-${rb}${Number.isInteger(+r) ? '' : ' grade-half'}"
              title="Meine Note: ${rateText(r)}">${rateText(r)}</span>`
          : (hint[act.id] ? `<span class="hint hint-${hint[act.id].v}"
              title="Vorschlag: ${esc(hint[act.id].v)}"></span>` : '')}${
        teamRowMark(act.id, rb)}</span>
      <span class="row-sub">${venue
        ? `<span class="venue" data-venue="${sh.v}">${esc(venue.n)}</span>`
        : 'Spielort offen'}
        ${act.c ? ' · ' + esc(act.c) : ''}</span>
      ${tags ? `<span class="row-tags">${tags}</span>` : ''}
    </span>
    <span class="row-play${playingAct === act.id ? ' is-playing' : ''}"
      role="button" data-quickplay="${esc(spotifyEmbed(act.sp) || '')}"
      data-playname="${esc(act.n)}"
      aria-disabled="${!act.sp}"
      aria-label="${act.sp ? 'Anspielen' : 'Kein Spotify-Link'}"
      title="${act.sp ? '30 Sekunden anspielen' : 'Für diesen Act gibt es keinen Spotify-Link'}"
      >${playingAct === act.id ? '❙❙' : '▶'}</span>
    <span class="row-fav" role="button" aria-pressed="${fav.has(act.id)}"
      data-fav="${act.id}" aria-label="Favorit">${fav.has(act.id) ? '♥' : '♡'}</span>
  </button>`;
}

/* ---------- Anspielen direkt aus der Liste ----------
   Der Player sitzt als Leiste UNTER der Liste, nicht in der Zeile: eine
   Zeile aufzuklappen verschiebt alles darunter, und beim naechsten render()
   waere der Player wieder weg. So laeuft er weiter, waehrend man scrollt,
   filtert oder einen anderen Act oeffnet. */
let playingAct = null;

/* Die Skala in der Anspielleiste. Rund und ohne Beschriftung - in der Leiste
   ist kein Platz fuer "sehr gut", der Text steht im aria-label. */
function renderPlayerRate(ai) {
  const act = S.data && S.data.acts[ai];
  if (!act) { $('#player-rate').innerHTML = ''; return; }
  el.player.dataset.ai = ai;
  $('#player-rate').innerHTML = RATES.map(([k, label]) =>
    `<button data-r="${k}"${Number.isInteger(k) ? '' : ' class="is-half"'}
      aria-pressed="${+rate[act.id] === k}"
      title="${rateText(k)} — ${esc(label)}"
      aria-label="Note ${rateText(k)} — ${esc(label)}">${rateText(k)}</button>`).join('');
}

function openPlayer(src, name, actId, ai) {
  playingAct = actId;
  $('#player-name').textContent = name;
  renderPlayerRate(ai);
  // Nur neu setzen, wenn sich die Adresse aendert - sonst startet der
  // Player bei jedem Tippen von vorn.
  const slot = $('#player-slot');
  if (slot.dataset.src !== src) {
    slot.dataset.src = src;
    slot.innerHTML = `<iframe src="${esc(src)}" title="Spotify-Player"
      loading="lazy" allow="encrypted-media; clipboard-write"
      referrerpolicy="no-referrer"></iframe>`;
  }
  el.player.hidden = false;
  document.body.classList.add('has-player');
  /* NUR die betroffene Zeile auffrischen, kein render(). Ein voller Neuaufbau
     ruft restoreAnchor(), und das rechnet direkt nach dem Aufbau mit den
     geschaetzten Zeilenhoehen von content-visibility - gemessen sprang die
     Liste dadurch um 719 Pixel. */
  refreshAct(ai);
}

function closePlayer() {
  const wasAi = +el.player.dataset.ai;
  playingAct = null;
  $('#player-rate').innerHTML = '';
  delete el.player.dataset.ai;
  const slot = $('#player-slot');
  slot.innerHTML = '';
  delete slot.dataset.src;
  el.player.hidden = true;
  document.body.classList.remove('has-player');
  // Auch hier nur die Zeile: sonst springt die Liste beim Schliessen.
  refreshAct(wasAi);
}

/* ---------- Scrollposition halten (Wunsch 2) ---------- */

let scrollTimer = null;
addEventListener('scroll', () => {
  if (S.mapOn || S.q.trim()) return;
  clearTimeout(scrollTimer);
  scrollTimer = setTimeout(() => {
    const rows = el.list.querySelectorAll('.row');
    const top = document.querySelector('.top').offsetHeight;
    for (const r of rows) {
      if (r.getBoundingClientRect().bottom > top) {
        anchor[S.day || 'alle'] = r.dataset.show;
        store.set('anchor', anchor);
        break;
      }
    }
  }, 150);
}, { passive: true });

function restoreAnchor() {
  const id = anchor[S.day || 'alle'];
  if (!id || S.q.trim()) return;
  const target = el.list.querySelector(`.row[data-show="${CSS.escape(id)}"]`);
  if (!target) return;
  const top = document.querySelector('.top').offsetHeight;
  requestAnimationFrame(() => {
    const y = target.getBoundingClientRect().top + scrollY - top - 8;
    scrollTo({ top: Math.max(0, y), behavior: 'instant' });
  });
}

/* ---------- Abendplan ---------- */

/* Wert eines Auftritts. Note 1 zaehlt am meisten, 5 am wenigsten; ein
   Favorit ohne Note liegt in der Mitte. Der Team-Bonus ist absichtlich hoch:
   ein Konzert, das beide wollen, ist mehr wert als zwei einzelne Wuensche. */
function planValue(actId, opts) {
  const r = +rate[actId] || 0;
  let v = 0;
  if (r) v = 6 - r;
  else if (opts.withFav && fav.has(actId)) v = 3;
  if (!v) return 0;
  if (opts.teamBonus && bothWant(actId)) v += 3;
  return v;
}

/* ---------- Abendplan von Hand nachjustieren ----------
   Der Vorschlag rechnet mit Noten, aber der Abend gehoert dem Nutzer: ein
   Act, den man trotz mittlerer Note sehen will, muss rein; ein anderer raus.
   Zwei Mengen von Auftritts-Kennungen reichen dafuer.

   Feste Termine kommen mit einem sehr hohen Wert in die Rechnung - dann nimmt
   sie die Optimierung von selbst, solange sie ueberhaupt zusammenpassen.
   Widersprechen sich zwei feste Termine, faellt einer heraus, und das wird
   gemeldet statt verschwiegen. */
let planPin = new Set(store.get('planpin', []) || []);
let planSkip = new Set(store.get('planskip', []) || []);
const PIN_VALUE = 1000;

function savePlanChoice() {
  store.set('planpin', [...planPin]);
  store.set('planskip', [...planSkip]);
}

function planOptions() {
  return {
    maxNote: +($('#plan-max') || {}).value || 2,
    setMinutes: +($('#plan-set') || {}).value || 40,
    withFav: !!($('#plan-fav') || {}).checked,
    teamBonus: !!($('#plan-team') || {}).checked && !!partner,
  };
}

let lastPlan = null;

function collectPlanItems(opts) {
  const items = [];
  let undated = 0;
  for (const sh of S.data.shows) {
    if (!sh.t) continue;
    if (sh.tbd) {
      // Ohne Uhrzeit nicht planbar - aber zaehlen, sonst wundert man sich,
      // warum ein bewerteter Act fehlt.
      const a = S.data.acts[sh.a];
      // Eimer, nicht Rohnote: "bis Note 1" soll 1,5 einschliessen, genau wie
      // der Filter es tut.
      const r = rateBucket(rate[a.id]);
      if ((!S.day || sh.d === S.day)
          && ((r && r <= opts.maxNote) || (opts.withFav && fav.has(a.id)))) undated++;
      continue;
    }
    if (S.day && sh.d !== S.day) continue;
    if (planSkip.has(sh.id)) continue;          // von Hand ausgeschlossen
    const act = S.data.acts[sh.a];
    const r = rateBucket(rate[act.id]);
    const pinned = planPin.has(sh.id);
    // Ein fester Termin braucht keine gute Note - genau darum geht es.
    const eligible = pinned || (r && r <= opts.maxNote)
      || (opts.withFav && fav.has(act.id));
    if (!eligible) continue;
    const value = pinned ? PIN_VALUE : planValue(act.id, opts);
    if (value <= 0) continue;
    const v = sh.v != null ? S.data.venues[sh.v] : null;
    items.push({
      id: sh.id, actIdx: sh.a, actId: act.id, name: act.n,
      startIso: sh.t, value,
      venue: v ? { lat: v.lat, lng: v.lng, name: v.n } : null,
      venueIdx: sh.v,
      pinned,
      note: +rate[act.id] || 0,     // die echte Note, auch 1,5
    });
  }
  items.undatedCount = undated;
  return items;
}

function renderPlan() {
  const opts = planOptions();
  $('#plan-team-wrap').hidden = !partner;
  const items = collectPlanItems(opts);

  if (!S.day) {
    el.planBody.innerHTML = '<p class="empty"><b>Erst einen Tag wählen.</b>'
      + 'Ein Abendplan gilt für einen Abend — oben auf Mi, Do, Fr oder Sa tippen.</p>';
    lastPlan = null;
    return;
  }
  if (!items.length) {
    el.planBody.innerHTML = `<p class="empty"><b>Nichts zu planen.</b>
      Für ${esc(dayLabel(S.day))} gibt es keine Acts mit Note bis ${opts.maxNote}
      ${opts.withFav ? 'und keine Favoriten' : ''}.
      ${items.undatedCount
        ? `${items.undatedCount} passende Acts haben noch keine Uhrzeit und
           lassen sich deshalb nicht einplanen.`
        : 'Bewerte erst ein paar Acts.'}</p>`;
    lastPlan = null;
    return;
  }

  const plan = window.RBFPlan.buildPlan(items, { setMinutes: opts.setMinutes });
  lastPlan = plan;
  const pinnedOut = items.filter((x) => x.pinned)
    .filter((x) => !plan.stops.some((s) => s.id === x.id));

  const last = plan.stops[plan.stops.length - 1];
  const end = last
    ? window.RBFPlan.clockInSourceZone(last.startIso, opts.setMinutes)
    : '';
  let html = `<p class="plan-sum"><b>${plan.stops.length} Konzerte</b> aus
    ${items.length} in Frage kommenden · ${plan.walkTotal} min Fußweg gesamt
    ${plan.stops.length ? `· bis etwa ${esc(end)}` : ''}
    ${items.undatedCount ? `<br>${items.undatedCount} passende Acts haben noch
      keine Uhrzeit und fehlen deshalb.` : ''}</p>`;

  // Ein fester Termin, der trotzdem nicht reinpasst, muss auffallen - sonst
  // sucht man ihn im Plan und wundert sich.
  if (pinnedOut.length) {
    html += `<p class="plan-warn"><b>Nicht alle festen Termine passen
      zusammen.</b> Draußen bleibt: ${pinnedOut.map((x) =>
        `${esc(x.name)} ${hhmm(x.startIso)}`).join(', ')}. Einen davon lösen,
      dann rechnet der Plan neu.</p>`;
  }
  if (plan.dedupedActs && plan.dedupedActs.length) {
    html += `<p class="plan-note">${plan.dedupedActs.map((d) =>
      `${esc(d.name)} spielt mehrfach — eingeplant ist der andere Termin`)
      .join('. ')}.</p>`;
  }
  if (planPin.size || planSkip.size) {
    html += `<p class="plan-note">Von Hand gesetzt:
      ${planPin.size} fest, ${planSkip.size} ausgeschlossen ·
      <button type="button" class="linkish" id="plan-reset-manual">alles
      zurücknehmen</button></p>`;
  }

  plan.stops.forEach((s, i) => {
    if (i > 0) {
      const tight = s.idleBefore <= 5;
      const gap = s.idleBefore >= 60;
      const wait = s.idleBefore >= 60
        ? `${Math.floor(s.idleBefore / 60)} h ${s.idleBefore % 60} min`
        : `${s.idleBefore} min`;
      html += `<div class="leg${tight ? ' tight' : ''}${gap ? ' gap' : ''}">
        ${s.walkFromPrev} min Fußweg${s.idleBefore > 0
          ? ` · ${wait} Luft` : ' · direkt anschließend'}
        ${tight ? ' — knapp' : ''}${gap ? ' — große Lücke, da passt noch was rein'
          : ''}</div>`;
    }
    const sh = showMap().get(String(s.id));
    const total = actShowCount(s.actIdx);
    html += `<div class="stop"><span class="stop-no">${i + 1}</span>
      ${row(sh, S.data.acts[s.actIdx])}
      <span class="stop-acts">
        <button type="button" class="pill${planPin.has(s.id) ? ' on' : ''}"
          data-pin="${esc(s.id)}" aria-pressed="${planPin.has(s.id)}"
          title="Diesen Termin festhalten">📌</button>
        <button type="button" class="pill" data-skip="${esc(s.id)}"
          title="${total > 1 ? 'Diesen Termin nicht — der andere darf rein'
                             : 'Diesen Auftritt heute nicht'}">✕</button>
      </span></div>`;
  });

  if (plan.dropped.length) {
    const inPlan = new Set(plan.stops.map((s) => s.actId));
    // Mit einem Griff hereinholen: DAS ist "doch den anderen waehlen".
    html += `<div class="plan-drop"><h3>Passt nicht mehr rein
      (${plan.dropped.length})</h3><ul>${plan.dropped.slice(0, 20).map((d) =>
        `<li><button type="button" class="pill${planPin.has(d.id) ? ' on' : ''}"
            data-pin="${esc(d.id)}" aria-pressed="${planPin.has(d.id)}"
            title="Diesen Termin festhalten — der Plan rechnet neu">📌</button>
          ${esc(d.name)} — ${hhmm(d.startIso)}${
          inPlan.has(d.actId) ? ' (spielt mehrfach, ein Termin steht schon im Plan)'
            : (d.clashesWith ? `, überschneidet sich mit ${esc(d.clashesWith)}` : '')
        }</li>`).join('')}
      </ul>
      <p class="menu-note">Auf 📌 tippen heißt: dieser Termin muss rein. Der
      Plan rechnet dann alles andere darum herum neu.</p></div>`;
  }
  el.planBody.innerHTML = html;
}

function renderNews() {
  const n = changes.entries.length;
  const from = changes.generated_from
    ? new Date(changes.generated_from) : null;
  $('#news-meta').textContent = n
    ? `${changes.total || n} Änderungen seit Beginn der Beobachtung, `
      + `${changes.compared || 0} Stände verglichen. Stand `
      + (from && !isNaN(from) ? from.toLocaleString('de-DE')
                              : String(changes.generated_from))
    : 'Noch keine Änderungen bemerkt. Die App vergleicht das Programm täglich.';

  if (!n) {
    el.newsBody.innerHTML = `<p class="empty"><b>Alles unverändert.</b>
      Sobald ein Konzert verschoben, verlegt oder gestrichen wird, steht es
      hier — und an der betroffenen Zeile in der Liste.</p>`;
    return;
  }
  // Nach Tag gruppieren: "was kam heute dazu" ist die Frage.
  let html = '';
  let head = '';
  for (const e of changes.entries) {
    const when = new Date(e.at);
    const day = isNaN(when) ? e.at : when.toLocaleDateString('de-DE');
    if (day !== head) {
      head = day;
      html += `<div class="slot-head">bemerkt am ${esc(day)}</div>`;
    }
    const arrow = e.kind === 'moved'
      ? `${esc(e.from)} <b>→ ${esc(e.to)}</b>`
      : esc(e.to || e.from || '');
    html += `<div class="news-row news-${esc(e.kind)}">
      <span class="news-kind">${esc(CHANGE_KIND[e.kind] || e.kind)}</span>
      <span class="news-main"><b>${esc(e.act)}</b><br>
        <span class="news-what">${esc(e.what)}: ${arrow}</span></span>
      ${e.show && e.kind !== 'removed' ? `<button type="button" class="pill"
        data-findshow="${esc(e.show)}" title="In der Liste zeigen">→</button>` : ''}
    </div>`;
  }
  el.newsBody.innerHTML = html;
}

function showNews(on) {
  S.newsOn = on;
  if (on) { S.planOn = false; mapOffQuiet(); }
  openBox(null);
  render();
  scrollTo({ top: 0, behavior: 'instant' });
}

function showPlan(on) {
  S.planOn = on;
  if (on) { S.newsOn = false; mapOffQuiet(); }
  openBox(null);
  render();
  scrollTo({ top: 0, behavior: 'instant' });
}

/* Route auf der Karte: Linie durch die Stationen plus numerierte Marker.
   Die Cluster bleiben aus, sonst verschwindet die Route in den Buendeln. */
let routeLayer = null;

function showRoute() {
  if (!lastPlan || !lastPlan.stops.length) { alert('Es gibt noch keinen Plan.'); return; }
  const pts = lastPlan.stops.filter((s) => s.venue && s.venue.lat != null);
  if (!pts.length) { alert('Zu den Stationen fehlen Koordinaten.'); return; }
  S.planOn = false;
  S.mapOn = true;
  $('#btn-map').setAttribute('aria-pressed', 'true');
  render();
  const m = ensureMap();
  setTimeout(() => {
    m.invalidateSize();
    if (routeLayer) m.removeLayer(routeLayer);
    routeLayer = L.layerGroup().addTo(m);
    // Die Spielort-Marker treten zurueck, solange eine Route liegt. Sonst
    // stehen 34 Kuerzel gleich stark neben den Stationen der Route.
    document.getElementById('map').classList.add('route-on');
    const latlngs = pts.map((s) => [s.venue.lat, s.venue.lng]);

    /* Mehrere Konzerte im selben Haus liegen auf derselben Koordinate - dann
       verdeckt eine Nadel die andere vollstaendig, und verdeckt war
       ausgerechnet der Start. Die Nadeln werden deshalb aufgefaechert, aber
       in BILDSCHIRM-Pixeln: ein Versatz in Koordinaten waere beim
       Hineinzoomen riesig und beim Herauszoomen unsichtbar. Der erste Versuch
       mit 12 m Abstand ergab bei diesem Zoom 6 Pixel - zu wenig.
       Die Linie behaelt die echten Koordinaten, es wird nichts verschoben,
       was auf der Karte etwas bedeutet. */
    const fanIndex = [];
    const seenAt = new Map();
    latlngs.forEach(([lat, lng], i) => {
      const key = lat.toFixed(5) + ',' + lng.toFixed(5);
      const n = seenAt.get(key) || 0;
      seenAt.set(key, n + 1);
      fanIndex[i] = n;
    });
    const fanShift = (n) => {
      if (!n) return [0, 0];
      const a = -Math.PI / 2 + n * (Math.PI / 3);      // 60 Grad je Schritt
      const r = 30;                                     // Pixel
      return [Math.round(r * Math.cos(a)), Math.round(r * Math.sin(a))];
    };

    // Leaflet will einen Farbwert, keine CSS-Variable - also den aktuellen
    // Akzent auslesen, damit die Linie in beiden Ansichten passt.
    const accent = getComputedStyle(document.documentElement)
      .getPropertyValue('--accent').trim() || '#b197fc';
    L.polyline(latlngs, { color: accent, weight: 4, opacity: .9,
                          dashArray: '1 8', lineCap: 'round' }).addTo(routeLayer);

    // Richtungspfeile in der Mitte jeder Teilstrecke: die Nummern allein
    // sagen nicht, in welche Richtung es weitergeht.
    for (let i = 0; i + 1 < latlngs.length; i++) {
      const [a, b] = [latlngs[i], latlngs[i + 1]];
      // Gleiches Haus: es gibt keine Strecke und damit keine Richtung.
      if (a[0] === b[0] && a[1] === b[1]) continue;
      const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      // Bildschirmwinkel: Laengengrade mit dem Kosinus der Breite stauchen,
      // sonst zeigt der Pfeil auf dieser Breite gut 30 Grad daneben.
      const k = Math.cos(a[0] * Math.PI / 180);
      const deg = Math.atan2((b[1] - a[1]) * k, b[0] - a[0]) * 180 / Math.PI;
      L.marker(mid, {
        interactive: false,
        icon: L.divIcon({
          className: '', iconSize: [16, 16], iconAnchor: [8, 8],
          html: `<span class="route-arrow" style="transform:rotate(${
            (90 - deg).toFixed(1)}deg)">➤</span>`,
        }),
      }).addTo(routeLayer);
    }

    pts.forEach((s, i) => {
      const first = i === 0;
      const last = i === pts.length - 1;
      // Start und Ziel sind beschriftet, nicht nur numeriert: die reine Zahl
      // war von der Zahl in einer Cluster-Blase nicht zu unterscheiden.
      const badge = first ? 'START' : last ? 'ZIEL' : '';
      const [fx, fy] = fanShift(fanIndex[i]);
      L.marker(latlngs[i], {
        icon: L.divIcon({
          // Der Faecher steckt im iconAnchor, nicht in der Koordinate: so
          // bleibt der Marker geografisch dort, wo das Haus steht.
          className: '', iconSize: [44, 52],
          iconAnchor: [22 - fx, 40 - fy],
          popupAnchor: [fx, fy - 40],
          // Die Beschriftung liegt AUSSERHALB der gedrehten Nadel, sonst
          // dreht sie mit und schiebt sich ueber die Zahl.
          html: `<span class="route-stop">
                   <span class="route-pin${first ? ' is-first' : ''}${
                     last && !first ? ' is-last' : ''}"
                     ><span class="route-pin-no">${i + 1}</span></span>
                   ${badge ? `<span class="route-pin-tag">${badge}</span>` : ''}
                 </span>`,
        }),
        // Rueckwaerts: die fruehere Station liegt oben, der Start ganz oben.
        // Vorher lag die spaetere obendrauf und hat den Start verdeckt.
        zIndexOffset: 1000 + (pts.length - i) + (first ? 100 : 0),
      }).addTo(routeLayer).bindPopup(
        `<div class="pop-title">${first ? 'Start: ' : last ? 'Zuletzt: ' : i + 1 + '. '}${
          esc(s.name)}</div>
         <div class="pop-meta">${hhmm(s.startIso)} · ${
           esc(venueCode[s.venueIdx] || '')} ${esc(s.venue.name)}</div>`);
    });
    m.fitBounds(latlngs, { padding: [46, 46] });
  }, 80);
}

/* Die Route wieder abraeumen - sonst bleibt sie liegen, wenn man die Karte
   fuer etwas anderes benutzt, und die Spielorte bleiben blass. */
function clearRoute() {
  if (routeLayer && map) map.removeLayer(routeLayer);
  routeLayer = null;
  const box = document.getElementById('map');
  if (box) box.classList.remove('route-on');
}

/* ---------- Detailansicht ---------- */

function openDetail(ai) {
  const act = S.data.acts[ai];
  const slots = S.data.shows.filter((s) => s.a === ai);
  const links = [
    act.sp && ['Spotify', act.sp],
    act.yt && ['YouTube', act.yt],
    act.web && ['Website', act.web],
    act.url && ['Festivalseite', 'https://www.reeperbahnfestival.com' + act.url],
  ].filter(Boolean);

  el.detail.innerHTML = `<div class="d-wrap">
    <div class="d-head">
      <div>
        <h2 class="d-title">${esc(act.n)}</h2>
        <div class="d-sub">${[act.c, act.g.map((i) => S.data.genres[i]).join(', ')]
          .filter(Boolean).map(esc).join(' · ')}</div>
      </div>
      <button class="icon-btn d-close" data-close aria-label="Schließen">✕</button>
    </div>

    ${partner ? `<div class="d-section" id="d-team">
      <h3>Team</h3>
      <div class="suggestion">${teamSuggestion(act.id)}</div>
    </div>` : ''}

    ${hint[act.id] ? `<div class="d-section">
      <div class="suggestion">
        <span class="hint hint-${hint[act.id].v}"></span>
        <span><b>Vorschlag: ${hint[act.id].v === 'ja' ? 'eher ja' : 'eher nein'}</b> —
        ${esc(hint[act.id].why)}. Deine Einschätzung unten überschreibt das.</span>
      </div>
    </div>` : ''}

    <div class="d-section">
      <h3>Meine Einschätzung</h3>
      <div class="rate">${RATES.map(([k, label]) =>
        `<button data-r="${k}"
          class="${Number.isInteger(k) ? '' : 'is-half'}"
          aria-pressed="${+rate[act.id] === k}"
          aria-label="${rateText(k)} - ${label}"><b>${rateText(k)}</b><small
          >${label}</small></button>`).join('')}
      </div>
      <p class="rate-note">1,5 und 2,5 liegen dazwischen. Im Filter zählen sie
      zu 1 beziehungsweise 2.</p>
    </div>

    <div class="d-section">
      <h3>Notiz <span class="tag">privat</span></h3>
      <textarea id="d-note" placeholder="Warum hin? Wer kommt mit? Konflikt mit…"
        >${esc(note[act.id] || '')}</textarea>
      <div class="saved" id="d-saved" role="status"></div>
    </div>

    <div class="d-section">
      <h3>Auftritte</h3>
      <ul class="slots">${slots.map((s) => {
        const v = s.v != null ? S.data.venues[s.v] : null;
        return `<li>
          <time>${s.tbd ? dayLabel(s) + ', Zeit offen' : dayLabel(s) + ' ' + hhmm(s.t)}</time>
          <span>${v ? esc(v.n) : 'Spielort offen'}</span>
          ${v && v.lat ? `<button data-venue="${s.v}">Karte</button>` : ''}
        </li>`;
      }).join('')}</ul>
    </div>

    ${links.length ? `<div class="d-section"><h3>Anhören</h3>
      ${act.sp ? `<div class="embed-wrap" id="embed-slot">
        <button class="chip" data-play="${esc(spotifyEmbed(act.sp) || '')}">
          ▶ 30 Sekunden anspielen</button>
        <p class="embed-note">Lädt den Spotify-Player erst auf Tippen — vorher
        wird nichts zu Spotify übertragen.</p>
      </div>` : ''}
      <div class="links">${links.map(([n, u]) =>
        `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${n}</a>`).join('')}
      </div></div>` : ''}

    ${act.img ? `<div class="d-section">
      <img class="d-img" src="${esc(act.img)}" alt="${esc(act.n)}"
           decoding="async" width="900" height="600">
    </div>` : ''}

    ${act.bio ? `<div class="d-section"><h3>Über</h3>
      <p class="bio">${esc(act.bio)}</p></div>` : ''}

    <div class="d-section">
      <div class="filters">
        <button class="chip" data-fav="${act.id}" aria-pressed="${fav.has(act.id)}">
          <span class="heart">${fav.has(act.id) ? '♥' : '♡'}</span>
          ${fav.has(act.id) ? 'Favorit' : 'Als Favorit merken'}
        </button>
        <button class="chip" data-seen="${act.id}" aria-pressed="${seen.has(act.id)}">
          ${seen.has(act.id) ? '✓ Gesehen' : 'Als gesehen markieren'}
        </button>
      </div>
    </div>
  </div>`;

  el.detail.dataset.act = act.id;
  el.detail.dataset.ai = ai;
  if (!el.detail.open) el.detail.showModal();
  syncDialogCount();
}

/* Notiz: verzoegert speichern, damit nicht bei jedem Tastendruck geschrieben wird. */
let noteTimer = null;
el.detail.addEventListener('input', (e) => {
  if (e.target.id !== 'd-note') return;
  const id = el.detail.dataset.act;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => {
    const text = e.target.value.trim();
    if (text) note[id] = text; else delete note[id];
    store.set('note', note);
    const saved = $('#d-saved');
    if (saved) {
      saved.textContent = 'Gespeichert';
      setTimeout(() => { if (saved) saved.textContent = ''; }, 1400);
    }
    markNote(id, !!text);
  }, 400);
});

function markNote(actId, has) {
  for (const r of el.list.querySelectorAll('.row')) {
    if (S.data.acts[+r.dataset.act].id === +actId) {
      r.querySelector('.row-name').classList.toggle('has-note', has);
    }
  }
}

/* Spotify-Künstlerlink in eine Embed-Adresse umschreiben.
   Der offizielle Embed-Player braucht keinen API-Schlüssel und spielt für
   alle 30 Sekunden an; volle Titel gibt es nur im Desktop-Browser mit
   eingeloggtem Premium-Konto - auf dem Handy hat Spotify das
   Drittanbieter-Streaming eingestellt. Die preview_url der Web-API ist fuer
   neue Anwendungen seit Ende 2024 nicht mehr verfuegbar. */
function spotifyEmbed(url) {
  const m = String(url || '').match(/spotify\.com\/(?:intl-[a-z]+\/)?(artist|track|album)\/([A-Za-z0-9]+)/);
  return m ? `https://open.spotify.com/embed/${m[1]}/${m[2]}` : null;
}

/* ---------- Ortskuerzel ----------
   Zwei Buchstaben pro Spielort, aus dem Namen abgeleitet. Auf der Karte
   liegen 34 Haeuser dicht beieinander; nackte Nadeln sind nicht
   unterscheidbar, und eine Nummer waere mit den Zahlen der Cluster und der
   Route verwechselbar. Buchstaben sind es nicht.

   Woerter wie "Club" oder "Theater" fliegen raus, weil sie in mehreren Namen
   stehen und deshalb nicht unterscheiden. */
const CODE_SKIP = new Set([
  'club', 'bar', 'hall', 'halle', 'theater', 'kirche', 'saal', 'haus',
  'restaurant', 'cafe', 'café', 'kiez', 'hamburg', 'st', 'der', 'die', 'das',
  'den', 'dem', 'und', 'im', 'am', 'an', 'in', 'zur', 'zum', 'auf', 'the',
  'of', 'bei', 'beim', 'von', 'vor', 'kleine', 'grosse', 'große', 'neue',
]);

function venueCodes(venues) {
  const words = (n) => String(n || '')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/).filter(Boolean);

  /* Kandidaten in der Reihenfolge, in der sie versucht werden. */
  function candidates(name) {
    const all = words(name);
    const sig = all.filter((w) => !CODE_SKIP.has(w.toLowerCase()));
    const use = sig.length ? sig : all;
    const out = [];

    /* Nebenraeume heissen "Haus / Raum" ("Mojo Club / Mojo Jazz Café").
       Dann ist der Anfangsbuchstabe des Hauses plus der des ERSTEN eigenen
       Wortes des Raumes das sprechendste Kuerzel: MJ, nicht MM. */
    const parts = String(name || '').split('/');
    if (parts.length >= 2) {
      const head = words(parts[0]).filter((w) => !CODE_SKIP.has(w.toLowerCase()));
      const seen = new Set(words(parts[0]).map((w) => w.toLowerCase()));
      const tail = words(parts.slice(1).join(' '))
        .filter((w) => !seen.has(w.toLowerCase())
                       && !CODE_SKIP.has(w.toLowerCase()));
      if (head[0] && tail[0]) out.push(head[0][0] + tail[0][0]);
    }

    if (use.length >= 2) out.push(use[0][0] + use[1][0]);
    if (use[0] && use[0].length >= 2) out.push(use[0].slice(0, 2));
    if (use[0]) {
      // Erster Buchstabe plus jeder weitere Buchstabe desselben Wortes -
      // "Molotow" ergibt so MO, ML, MT, MW ...
      for (const c of use[0].slice(1)) out.push(use[0][0] + c);
    }
    if (all.length >= 2) out.push(all[0][0] + all[1][0]);
    if (use[0]) for (let d = 2; d <= 9; d++) out.push(use[0][0] + d);
    return out.map((c) => c.toUpperCase());
  }

  // Nach Namen sortiert vergeben, nicht nach Array-Position: dann bleibt ein
  // Kuerzel gleich, auch wenn das Line-up neue Haeuser dazwischenschiebt.
  const order = venues.map((v, i) => [i, v])
    .filter(([, v]) => v)
    .sort((a, b) => String(a[1].n).localeCompare(String(b[1].n), 'de'));

  const codes = [];
  const taken = new Set();
  for (const [i, v] of order) {
    let code = candidates(v.n).find((c) => !taken.has(c));
    if (!code) code = 'X' + (taken.size % 10);      // sollte nie eintreten
    taken.add(code);
    codes[i] = code;
  }
  return codes;
}

/* ---------- Karte (Wunsch 3 und 7) ---------- */

function ensureMap() {
  if (map) return map;
  map = L.map('map', { scrollWheelZoom: true })
    .setView([53.5503, 9.9637], 15);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const counts = new Map();
  for (const s of S.data.shows) if (s.v != null) counts.set(s.v, (counts.get(s.v) || 0) + 1);

  // Clustering: 34 Haeuser auf engem Raum verdecken sich sonst gegenseitig.
  cluster = L.markerClusterGroup({
    maxClusterRadius: 38,
    showCoverageOnHover: false,
    spiderfyOnMaxZoom: true,
    // Ab dieser Zoomstufe keine Cluster mehr. Damit ist "Spielort anzeigen"
    // deterministisch: hinzoomen, Marker ist einzeln, Popup auf. Ohne das
    // muesste man sich auf zoomToShowLayer und dessen Animation verlassen -
    // die laeuft nicht zuverlaessig, wenn die Karte gerade erst sichtbar
    // wurde und ihre Groesse noch stale ist.
    disableClusteringAtZoom: MAP_DETAIL_ZOOM,
  });
  const pts = [];
  const codes = venueCode.length ? venueCode : venueCodes(S.data.venues);
  S.data.venues.forEach((v, i) => {
    if (v.lat == null) return;
    const bits = [
      v.addr && esc(v.addr),
      v.cap && `Kapazität ${v.cap}`,
      v.acc && v.acc.length && esc(v.acc.join(', ')),
      v.inherited && v.parent && `Koordinaten von ${esc(v.parent)}`,
    ].filter(Boolean);
    popupHtml[i] =
      `<div class="pop-title"><span class="pop-code">${esc(codes[i])}</span>
         ${esc(v.n)}</div>
       <div class="pop-meta">${counts.get(i) || 0} Auftritte${bits.length ? '<br>' + bits.join('<br>') : ''}</div>
       <div class="pop-actions">
         <button data-onlyvenue="${i}">Nur dieses Haus zeigen</button>
       </div>`;
    const m = L.marker([v.lat, v.lng], {
      icon: L.divIcon({
        className: '', iconSize: [30, 30], iconAnchor: [15, 15],
        popupAnchor: [0, -14],
        html: `<span class="venue-code" title="${esc(v.n)}">${esc(codes[i])}</span>`,
      }),
    }).bindPopup(popupHtml[i]);
    cluster.addLayer(m);
    markers[i] = m;
    pts.push([v.lat, v.lng]);
  });
  map.addLayer(cluster);
  if (pts.length) map.fitBounds(pts, { padding: [30, 30] });
  return map;
}

function showVenue(i) {
  const v = S.data.venues[i];
  if (!v || v.lat == null) return;
  if (el.detail.open) el.detail.close();
  clearRoute();               // sonst bleiben die Spielorte blass
  openBox(null);
  S.mapOn = true;
  $('#btn-map').setAttribute('aria-pressed', 'true');
  render();
  const m = ensureMap();
  setTimeout(() => {
    m.invalidateSize();
    m.setView([v.lat, v.lng], MAP_DETAIL_ZOOM, { animate: false });
    // Popup direkt an der Koordinate statt am Marker: der Marker kann in
    // diesem Moment noch im Cluster stecken (die Gruppe baut erst bei
    // zoomend um), und dann haengt ein Marker-Popup an einem Element, das
    // gar nicht auf der Karte liegt.
    if (popupHtml[i]) m.openPopup(popupHtml[i], [v.lat, v.lng], { offset: [0, -12] });
  }, 80);
}

/* ---------- Ereignisse ---------- */

document.addEventListener('click', (e) => {
  const t = e.target;

  // Aus der Karte heraus auf genau dieses Haus filtern - und ueber alle Tage,
  // sonst sieht man nur den Bruchteil des gewaehlten Tages.
  const only = t.closest('[data-onlyvenue]');
  if (only) {
    e.preventDefault(); e.stopPropagation();
    const i = +only.dataset.onlyvenue;
    S.venues.clear(); S.venues.add(i);
    S.day = null;
    mapOffQuiet();
    renderDays();
    renderVenues();
    render();
    scrollTo({ top: 0, behavior: 'instant' });
    return;
  }

  /* Abendplan von Hand: festhalten, ausschliessen, zuruecknehmen. Muss VOR
     dem Spielort- und dem Zeilen-Handler stehen, weil die Knoepfe innerhalb
     einer Zeile im Plan sitzen. */
  const pinBtn = t.closest('[data-pin]');
  if (pinBtn) {
    e.preventDefault(); e.stopPropagation();
    const id = pinBtn.dataset.pin;
    if (planPin.has(id)) planPin.delete(id); else { planPin.add(id); planSkip.delete(id); }
    savePlanChoice();
    renderPlan();
    return;
  }
  const skipBtn = t.closest('[data-skip]');
  if (skipBtn) {
    e.preventDefault(); e.stopPropagation();
    const id = skipBtn.dataset.skip;
    planSkip.add(id); planPin.delete(id);
    savePlanChoice();
    renderPlan();
    return;
  }
  if (t.closest('#plan-reset-manual')) {
    e.preventDefault(); e.stopPropagation();
    planPin.clear(); planSkip.clear();
    savePlanChoice();
    renderPlan();
    return;
  }

  const findShow = t.closest('[data-findshow]');
  if (findShow) {
    e.preventDefault(); e.stopPropagation();
    const id = findShow.dataset.findshow;
    const sh = showMap().get(String(id));
    // Filter aufheben, sonst sucht man eine Zeile, die gerade weggefiltert ist.
    S.newsOn = false;
    S.day = sh ? (sh.d || null) : null;
    S.q = ''; el.q.value = '';
    S.favOnly = false; S.seenOnly = false; S.teamOnly = false;
    S.rates.clear(); S.genres.clear(); S.venues.clear();
    renderDays(); renderGenres(); renderVenues(); renderRates();
    render();
    const node = el.list.querySelector(`.row[data-show="${CSS.escape(String(id))}"]`);
    if (node) {
      const top = document.querySelector('.top').offsetHeight;
      requestAnimationFrame(() => {
        const y = node.getBoundingClientRect().top + scrollY - top - 8;
        scrollTo({ top: Math.max(0, y), behavior: 'instant' });
        node.classList.add('flash');
        setTimeout(() => node.classList.remove('flash'), 1600);
      });
    } else {
      // Der Knopf fehlt zwar planmaessig bei gestrichenen Auftritten (siehe
      // renderNews), aber eine aeltere Verschiebung kann auf einen Auftritt
      // zeigen, der seither aus anderem Grund verschwunden ist - dann lieber
      // sagen, dass er weg ist, als stumm nichts zu tun.
      toast('Dieser Auftritt steht nicht mehr im aktuellen Programm.');
    }
    return;
  }

  const venue = t.closest('[data-venue]');
  if (venue) { e.preventDefault(); e.stopPropagation(); showVenue(+venue.dataset.venue); return; }

  // Muss VOR der Zeile stehen, sonst oeffnet der Klick den Detaildialog.
  const qp = t.closest('[data-quickplay]');
  if (qp) {
    e.preventDefault(); e.stopPropagation();
    if (!qp.dataset.quickplay) return;            // kein Spotify-Link
    const ai = +qp.closest('.row').dataset.act;
    const actId = S.data.acts[ai].id;
    if (playingAct === actId) closePlayer();
    else openPlayer(qp.dataset.quickplay, qp.dataset.playname, actId, ai);
    return;
  }

  const favBtn = t.closest('[data-fav]');
  if (favBtn) {
    e.preventDefault(); e.stopPropagation();
    const id = +favBtn.dataset.fav;
    fav.has(id) ? fav.delete(id) : fav.add(id);
    saveFav();
    scheduleSync();
    const on = fav.has(id);
    // An Ort und Stelle aktualisieren, damit die Liste nicht springt.
    for (const n of document.querySelectorAll(`[data-fav="${id}"]`)) {
      n.setAttribute('aria-pressed', String(on));
      const heart = n.querySelector('.heart');
      if (heart) { heart.textContent = on ? '♥' : '♡'; n.lastChild.textContent =
        on ? ' Favorit' : ' Als Favorit merken'; }
      else n.textContent = on ? '♥' : '♡';
    }
    if (S.favOnly) render();
    return;
  }

  const play = t.closest('[data-play]');
  if (play && play.dataset.play) {
    const slot = document.getElementById('embed-slot');
    if (slot) {
      slot.innerHTML = `<iframe src="${esc(play.dataset.play)}"
        title="Spotify-Player" loading="lazy" allow="encrypted-media; clipboard-write"
        referrerpolicy="no-referrer"></iframe>
        <p class="embed-note">Volle Titel nur im Desktop-Browser mit
        eingeloggtem Spotify-Premium-Konto.</p>`;
    }
    return;
  }

  const seenBtn = t.closest('[data-seen]');
  if (seenBtn) {
    e.preventDefault(); e.stopPropagation();
    const id = +seenBtn.dataset.seen;
    seen.has(id) ? seen.delete(id) : seen.add(id);
    saveSeen();
    scheduleSync();
    const on = seen.has(id);
    for (const n of document.querySelectorAll(`[data-seen="${id}"]`)) {
      n.setAttribute('aria-pressed', String(on));
      n.textContent = on ? '✓ Gesehen' : 'Als gesehen markieren';
    }
    refreshAct(+el.detail.dataset.ai);
    return;
  }

  const rateBtn = t.closest('[data-r]');
  if (rateBtn) {
    /* EIN Zuhoerer fuer alle drei Orte, an denen bewertet wird: Detailansicht,
       Schnellbewertung und Anspielleiste. Welcher Act gemeint ist, steht am
       naechstgelegenen data-ai - nicht fest am Detaildialog. (Zeilen tragen
       data-act, nicht data-ai, koennen hier also nicht dazwischenkommen.)

       Vorher hatte die Schnellbewertung eigene data-qr-Knoepfe, damit dieser
       Zuhoerer sie nicht faengt. Weil das CSS aber auf data-r zielt, war eine
       gesetzte Note dort unsichtbar: dunkle Schrift auf dunklem Grund. */
    const host = rateBtn.closest('[data-ai]') || el.detail;
    const ai = +host.dataset.ai;
    const act = S.data && S.data.acts[ai];
    if (!act) return;
    const id = act.id;
    const val = +rateBtn.dataset.r;
    if (+rate[id] === val) delete rate[id]; else rate[id] = val;
    store.set('rate', rate);
    scheduleSync();
    for (const b of host.querySelectorAll('[data-r]')) {
      b.setAttribute('aria-pressed', String(+rate[id] === +b.dataset.r));
    }
    // Die Leiste zeigt vielleicht denselben Act - dann dort mitziehen.
    if (host !== el.player && +el.player.dataset.ai === ai) renderPlayerRate(ai);
    // Die Schnellbewertung ist genau fuer diesen einen Griff da.
    if (host === el.quick) el.quick.close();
    refreshAct(ai);
    refreshTeamBox(ai);
    return;
  }

  const revealBtn = t.closest('[data-reveal]');
  if (revealBtn) {
    // Bewusstes Aufdecken der Team-Meinung, obwohl noch keine eigene Note
    // steht - der Ausweg fuer "ich will es trotzdem wissen".
    const id = +revealBtn.dataset.reveal;
    revealed.add(id);
    saveRevealed();
    const host = revealBtn.closest('[data-ai]');
    const ai = host ? +host.dataset.ai : NaN;
    if (Number.isFinite(ai)) { refreshTeamBox(ai); refreshAct(ai); }
    return;
  }

  // Den Dialog schliessen, IN DEM der Knopf steckt. Vorher stand hier
  // el.detail.close(), deshalb war das ✕ im Menue wirkungslos: es hat den
  // Detaildialog geschlossen, der ohnehin schon zu war.
  const closer = t.closest('[data-close]');
  if (closer) {
    const dlg = closer.closest('dialog');
    (dlg || el.detail).close();
    return;
  }

  const day = t.closest('.day');
  if (day) {
    S.day = day.dataset.day || null;
    for (const b of el.days.children) b.setAttribute('aria-selected', String(b === day));
    mapOffQuiet();
    render();
    return;
  }

  const rateChip = t.closest('[data-rate]');
  if (rateChip) {
    const n = +rateChip.dataset.rate;
    S.rates.has(n) ? S.rates.delete(n) : S.rates.add(n);
    rateChip.setAttribute('aria-pressed', String(S.rates.has(n)));
    render();
    return;
  }

  const useFilter = t.closest('[data-usefilter]');
  if (useFilter) {
    const f = savedFilters[+useFilter.dataset.usefilter];
    if (f) { applyFilter(f.f); openBox(null); }
    return;
  }

  const delFilter = t.closest('[data-delfilter]');
  if (delFilter) {
    const i = +delFilter.dataset.delfilter;
    savedFilters.splice(i, 1);
    store.set('filters', savedFilters);
    renderSavedFilters();
    return;
  }

  const venueFilter = t.closest('[data-venuefilter]');
  if (venueFilter) {
    const i = +venueFilter.dataset.venuefilter;
    S.venues.has(i) ? S.venues.delete(i) : S.venues.add(i);
    venueFilter.setAttribute('aria-pressed', String(S.venues.has(i)));
    render();
    return;
  }

  const genre = t.closest('[data-genre]');
  if (genre) {
    const i = +genre.dataset.genre;
    S.genres.has(i) ? S.genres.delete(i) : S.genres.add(i);
    genre.setAttribute('aria-pressed', String(S.genres.has(i)));
    render();
    return;
  }

  const rowEl = t.closest('.row');
  if (rowEl) { openDetail(+rowEl.dataset.act); return; }
});

/* Wunsch 4: Tastatur muss sich oeffnen. Auf iOS darf focus() nur INNERHALB
   der Nutzergeste passieren - kein await, kein Timeout davor. Deshalb steht
   das Feld schon im DOM und wird hier direkt fokussiert. */
$('#btn-search').addEventListener('click', () => setSearch(el.searchbar.hidden));

$('#q-clear').addEventListener('click', () => setSearch(false));

let qTimer = null;
el.q.addEventListener('input', () => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => { S.q = el.q.value; render(); }, 120);
});

$('#f-fav').addEventListener('click', (e) => {
  S.favOnly = !S.favOnly;
  e.currentTarget.setAttribute('aria-pressed', String(S.favOnly));
  render();
});

$('#f-rate').addEventListener('click', () => { renderRates(); openBox('ratebox'); });

$('#f-seen').addEventListener('click', (e) => {
  S.seenOnly = !S.seenOnly;
  e.currentTarget.setAttribute('aria-pressed', String(S.seenOnly));
  render();
});

$('#f-team').addEventListener('click', (e) => {
  S.teamOnly = !S.teamOnly;
  e.currentTarget.setAttribute('aria-pressed', String(S.teamOnly));
  render();
});

$('#f-genre').addEventListener('click', () => openBox('genrebox'));
$('#f-venue').addEventListener('click', () => openBox('venuebox'));

$('#btn-filters').addEventListener('click', () => {
  renderSavedFilters();
  openBox('filterbox');
});

$('#filtersave-go').addEventListener('click', () => {
  const input = $('#filtername');
  const name = input.value.trim().slice(0, 32);
  if (!name) { input.focus(); return; }
  const f = currentFilter();
  const empty = !f.fav && !f.seen && !f.team && !f.rates.length
    && !f.genres.length && !f.venues.length && f.day === null;
  if (empty && !confirm('Es ist gerade kein Filter gesetzt. Trotzdem speichern?')) return;
  const at = savedFilters.findIndex((x) => x.name === name);
  if (at >= 0) savedFilters[at] = { name, f }; else savedFilters.push({ name, f });
  store.set('filters', savedFilters);
  input.value = '';
  renderSavedFilters();
});

$('#filtername').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); $('#filtersave-go').click(); }
});

$('#f-reset').addEventListener('click', () => {
  S.favOnly = S.seenOnly = S.teamOnly = false;
  S.rates.clear(); S.genres.clear(); S.venues.clear(); S.q = '';
  el.q.value = ''; el.searchbar.hidden = true;
  $('#f-fav').setAttribute('aria-pressed', 'false');
  $('#f-seen').setAttribute('aria-pressed', 'false');
  $('#f-team').setAttribute('aria-pressed', 'false');
  renderGenres();
  renderVenues();
  renderRates();
  render();
});

/* Karte und Suche als Funktion, nicht als Knopfdruck. Der Zurueck-Handler
   hat vorher $('#btn-map').click() aufgerufen - das laeuft durch den ganzen
   Klick-Verteiler und zeichnet die Liste neu, mitten in einer laufenden
   Verlaufsnavigation. Firefox fuer Android hat das mit einer leeren Seite
   quittiert. */
function setMap(on) {
  if (on && S.planOn) S.planOn = false;
  S.mapOn = on;
  if (!on) clearRoute();
  $('#btn-map').setAttribute('aria-pressed', String(on));
  if (on) openBox(null);
  render();
  if (on) { const m = ensureMap(); setTimeout(() => m.invalidateSize(), 60); }
}

/* Karte aus, ohne selbst neu zu zeichnen - fuer Stellen, die gleich danach
   ohnehin rendern. Wichtig ist das clearRoute(): ohne das blieb die Klasse
   route-on stehen, und beim naechsten Oeffnen lagen die Ortsmarker mit 38 %
   Deckkraft unter einer alten Route. */
function mapOffQuiet() {
  if (!S.mapOn) return;
  S.mapOn = false;
  clearRoute();
  $('#btn-map').setAttribute('aria-pressed', 'false');
}

function setSearch(on) {
  el.searchbar.hidden = !on;
  if (on) { el.q.focus({ preventScroll: true }); return; }
  el.q.value = '';
  if (S.q) { S.q = ''; render(); }
}

$('#btn-map').addEventListener('click', () => setMap(!S.mapOn));

/* Die Kopfhoehe schwankt (Suchleiste, Genre-Kaesten). Statt sie in CSS zu
   raten, wird sie gemessen. */
function sizeMap() {
  if (!S.mapOn) return;
  const top = document.querySelector('.top').getBoundingClientRect().height;
  const foot = document.querySelector('.foot').getBoundingClientRect().height;
  el.mapBox.style.height = Math.max(260, innerHeight - top - foot) + 'px';
  if (map) map.invalidateSize();
}
addEventListener('resize', sizeMap);
addEventListener('orientationchange', sizeMap);

el.detail.addEventListener('click', (e) => {
  if (e.target === el.detail) el.detail.close();   // Klick auf den Hintergrund
});

/* Inhalt beim Schliessen verwerfen: ein geschlossenes <dialog> behaelt sonst
   sein Markup, und veraltete Elemente zaehlen bei Selektoren mit. */
el.detail.addEventListener('close', () => {
  clearTimeout(noteTimer);
  el.detail.innerHTML = '';
  delete el.detail.dataset.act;
});

/* ---------- Sichern und Laden ----------
   Bewusst als Datei und nicht ueber einen Server: Geschmacksdaten sind
   persoenlich, das Repository ist oeffentlich. So bleiben sie auf dem Geraet
   und lassen sich trotzdem zwischen Handy und Laptop bewegen. */

function download(name, text, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function exportChoice() {
  download('reeperbahn-auswahl.json', JSON.stringify({
    kind: 'rbf26-auswahl', version: 3,
    fav: [...fav], seen: [...seen], note, rate, hint,
  }, null, 2), 'application/json');
}

/* Gesehen-Liste als CSV: das ist die Mitschrift des Festivals, also mit Tag,
   Zeit, Spielort, eigener Note und Notiz - nicht nur Namen. */
function exportSeen() {
  if (!seen.size) { alert('Noch nichts als gesehen markiert.'); return; }
  const rows = [];
  for (const sh of S.data.shows) {
    const act = S.data.acts[sh.a];
    if (!seen.has(act.id)) continue;
    rows.push([
      sh.d || '', sh.tbd ? '' : hhmm(sh.t), act.n,
      sh.v != null ? S.data.venues[sh.v].n : '',
      (act.g || []).map((i) => S.data.genres[i]).join('; '),
      act.c || '', rate[act.id] || '', (note[act.id] || '').replace(/\s+/g, ' '),
    ]);
  }
  // Acts ohne Auftritt in den Daten trotzdem auffuehren, damit nichts fehlt.
  const listed = new Set(rows.map((r) => r[2]));
  for (const act of S.data.acts) {
    if (seen.has(act.id) && !listed.has(act.n)) {
      rows.push(['', '', act.n, '', '', act.c || '', rate[act.id] || '',
                 (note[act.id] || '').replace(/\s+/g, ' ')]);
    }
  }
  rows.sort((a, b) => (a[0] + a[1]).localeCompare(b[0] + b[1]) || a[2].localeCompare(b[2]));
  const head = ['Tag', 'Zeit', 'Act', 'Spielort', 'Genres', 'Land', 'Note', 'Notiz'];
  const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const csv = '\uFEFF' + [head, ...rows].map((r) => r.map(q).join(';')).join('\r\n');
  download('reeperbahn-gesehen.csv', csv, 'text/csv;charset=utf-8');
}

el.file.addEventListener('change', async () => {
  const f = el.file.files && el.file.files[0];
  if (!f) return;
  let data;
  try { data = JSON.parse(await f.text()); }
  catch (e) { alert('Die Datei ist kein gültiges JSON.'); return; }
  el.file.value = '';

  if (data.kind === 'rbf26-auswahl') {
    (data.fav || []).forEach((id) => fav.add(+id));
    (data.seen || []).forEach((id) => seen.add(+id));
    Object.assign(note, data.note || {});
    Object.assign(rate, data.rate || {});
    Object.assign(hint, data.hint || {});
    saveFav(); saveSeen();
    store.set('note', note); store.set('rate', rate); store.set('hint', hint);
    alert('Auswahl übernommen.');
  } else if (data.suggested) {
    hint = buildHints(data);
    store.set('hint', hint);
    const n = Object.keys(hint).length;
    alert(`${n} Vorschläge übernommen. Deine eigenen Bewertungen bleiben unberührt.`);
  } else {
    alert('Unbekanntes Format. Erwartet wird ein Export dieser App oder ' +
          'taste/suggestions.json.');
    return;
  }
  render();
});

/* Aus taste/suggestions.json ableiten, was in der App angezeigt wird.
   Format 2 bringt die Begruendungen schon mit - dort steht auch, was in der
   offiziellen Playlist bereits entfernt wurde. Aeltere Dateien haben nur
   Punktzahlen, die werden wie bisher umgerechnet. */
function buildHints(data) {
  if (data.hints && Object.keys(data.hints).length) {
    const out = {};
    for (const [id, h] of Object.entries(data.hints)) {
      if (h && h.v) out[id] = { v: h.v, why: String(h.why || '') };
    }
    return out;
  }
  const out = {};
  const refs = data.bio_refs || {};
  const hits = new Set((data.profile_hits || []).map(String));
  const known = data.known || {};
  const evidence = data.evidence || {};

  for (const [id, score] of Object.entries(data.suggested || {})) {
    if (known[id]) continue;                      // schon selbst entschieden
    if (hits.has(id)) {
      out[id] = { v: 'ja', why: 'steht in deiner eigenen Hörplaylist' };
    } else if (refs[id] && refs[id].length) {
      out[id] = { v: 'ja', why: 'Bio nennt ' + refs[id].join(', ') };
    } else if (score >= 0.9 && (evidence[id] || 0) >= (data.min_evidence || 3)) {
      out[id] = { v: 'nein', why: 'Genre, das du durchweg aussortiert hast' };
    }
  }
  return out;
}

$('#btn-theme').addEventListener('click', () => {
  setTheme(THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]);
});

document.addEventListener('click', (e) => {
  const pick = e.target.closest('[data-theme-set]');
  if (pick) setTheme(pick.dataset.themeSet);
});

/* ---------- Menue ---------- */

$('#btn-menu').addEventListener('click', () => {
  const rated = Object.keys(rate).length;
  $('#m-stats').textContent =
    `${fav.size} Favoriten · ${rated} bewertet · ${seen.size} gesehen · `
    + `${Object.keys(note).length} Notizen`;
  applyTheme();
  partnerInfo();
  teamInfo();
  renderSwipeOpts();
  el.menu.showModal();
  syncDialogCount();
});

el.menu.addEventListener('click', (e) => {
  if (e.target === el.menu) el.menu.close();
});

$('#m-export').addEventListener('click', () => { el.menu.close(); exportChoice(); });
$('#m-import').addEventListener('click', () => { el.menu.close(); el.file.click(); });
$('#m-seen').addEventListener('click', () => { el.menu.close(); exportSeen(); });
/* ---------- Team online ---------- */

function teamInfo() {
  const note = $('#m-team-note');
  const c = team && team.config;
  const on = !!c;
  for (const [id, show] of [['m-sync', on], ['m-team-share', on], ['m-team-leave', on],
                            ['m-team-new', !on], ['m-team-join', !on]]) {
    const b = $('#' + id);
    if (b) b.hidden = !show;
  }
  if (!note) return;
  if (!on) {
    // Deutlich als AUS markieren. Vorher stand hier nur Prosa, und man konnte
    // nicht erkennen, dass gar nichts laeuft - der Austausch ueber Dateien
    // sah aus wie das Ganze.
    note.innerHTML = '<b class="sync-off">Kein Online-Team — es wird nichts '
      + 'abgeglichen.</b><br>„Team einrichten“ drücken und der zweiten Person '
      + 'Beitrittslink und Passphrase geben. Danach läuft der Abgleich von '
      + 'selbst, ohne Dateien.';
    return;
  }
  const ago = lastSyncAt ? relTime(lastSyncAt) : 'noch nicht';
  note.innerHTML = `<b class="sync-on">Abgleich läuft automatisch</b> — `
    + `alle ${PULL_FAST_MS / 1000} Sekunden, wenn etwas passiert, sonst `
    + `alle ${PULL_SLOW_MS / 1000}. `
    + `Letzter Abgleich: ${esc(ago)}.<br>`
    + `Du erscheinst als „${esc(c.name)}“. Ende-zu-Ende verschlüsselt — der `
    + 'Server sieht nur Chiffrat. Wer Link und Passphrase hat, ist im Team.';
}

/* "vor 12 Sekunden" ist beim Hinsehen brauchbarer als eine Uhrzeit. */
function relTime(iso) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 10) return 'gerade eben';
  if (s < 90) return `vor ${s} Sekunden`;
  const m = Math.round(s / 60);
  if (m < 90) return `vor ${m} Minuten`;
  const h = Math.round(m / 60);
  if (h < 36) return `vor ${h} Stunden`;
  return new Date(iso).toLocaleString('de-DE');
}

function myTeamDoc() {
  return { fav: [...fav], seen: [...seen], rate, at: new Date().toISOString() };
}

/* Mehrere Mitglieder werden zu EINER Partneransicht zusammengefasst: fuer zwei
   Personen ist das genau richtig, bei mehr sieht man die Vereinigung. */
function adoptOthers(others) {
  const usable = others.filter((o) => !o.undecryptable);
  if (!usable.length) return 0;
  const merged = { name: usable.map((o) => o.name || 'Team').join(', '),
                   fav: [], seen: [], rate: {} };
  for (const o of usable) {
    for (const id of (o.fav || [])) merged.fav.push(+id);
    for (const id of (o.seen || [])) merged.seen.push(+id);
    for (const [id, v] of Object.entries(o.rate || {})) {
      // Bei mehreren Personen gewinnt die bessere Note.
      if (!merged.rate[id] || +v < +merged.rate[id]) merged.rate[id] = +v;
    }
  }
  partner = merged;
  store.set('partner', partner);
  return usable.length;
}

/* Woran man erkennt, ob sich auf der Gegenseite etwas getan hat - ohne den
   Zeitstempel, der sich bei jedem Abgleich aendert. */
function partnerSignature() {
  if (!partner) return '';
  return JSON.stringify([partner.name, (partner.fav || []).length,
                         Object.keys(partner.rate || {}).length,
                         (partner.seen || []).length]);
}

/* Automatischer Abgleich nach eigenen Aenderungen. Ohne das muesste man
   mitten im Konzert daran denken, "Jetzt abgleichen" zu druecken - und genau
   das passiert nicht. Verzoegert, damit schnelles Durchtippen nicht jedes Mal
   einen Schreibzugriff ausloest (KV erlaubt ohnehin nur einen pro Sekunde und
   Schluessel). */
const SYNC_DEBOUNCE_MS = 4000;
let syncTimer = null;

function scheduleSync() {
  if (!team || !team.config) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => runSync(true), SYNC_DEBOUNCE_MS);
}

/* Regelmaessig NUR lesen. Lesen ist billig (100.000/Tag), Schreiben nicht
   (1.000/Tag).

   Das Intervall war 90 Sekunden - und war damit der eigentliche Engpass. Gegen
   die echte API gemessen: eine AENDERUNG an einem bestehenden Eintrag ist nach
   1 Sekunde abrufbar, nur ein NEUER Eintrag braucht rund 30 Sekunden, bis er
   im Verzeichnis auftaucht. Der Speicher war also schnell, das Nachfragen war
   langsam.

   15 Sekunden im Vordergrund, nach 10 Minuten ohne Neuigkeiten auf 60
   Sekunden gedrosselt. Zwei Geraete, die den ganzen Tag offen sind, kommen
   damit auf gut 10.000 Leseanfragen - ein Zehntel des Freibetrags. */
/* Takt. 15 Sekunden waren zu dicht: zusammen mit einer Verzeichnis-Abfrage
   je Takt war der Tagesdeckel des Speichers nach vier Stunden erreicht. Die
   Abfrage ist jetzt weg (siehe runSync), und der Takt geht schneller in den
   Ruhezustand - solange nichts passiert, fragt die App nur noch alle
   anderthalb Minuten. Sobald von der Gegenseite etwas kommt, ist sie wieder
   schnell. */
const PULL_FAST_MS = 20000;
const PULL_SLOW_MS = 90000;
const IDLE_BEFORE_SLOW_MS = 2 * 60 * 1000;
let pullTimer = null;
let lastRemoteChange = 0;

function startPulling() {
  clearInterval(pullTimer);
  if (!team || !team.config) return;
  lastRemoteChange = Date.now();
  let current = PULL_FAST_MS;
  const arm = (ms) => {
    current = ms;
    clearInterval(pullTimer);
    pullTimer = setInterval(tick, ms);
  };
  const tick = () => {
    if (document.visibilityState !== 'visible') return;
    runSync(true, true);
    const idle = Date.now() - lastRemoteChange;
    const want = idle > IDLE_BEFORE_SLOW_MS ? PULL_SLOW_MS : PULL_FAST_MS;
    if (want !== current) arm(want);
  };
  arm(PULL_FAST_MS);
}

/* Ein neuer Beitritt taucht im Verzeichnis erst nach etwa 30 Sekunden auf.
   Nach dem eigenen Hochladen wird deshalb einmal verzoegert nachgefragt -
   sonst sieht man die neue Person erst beim naechsten Takt. */
let catchUpTimer = null;
function scheduleCatchUp() {
  clearTimeout(catchUpTimer);
  catchUpTimer = setTimeout(() => runSync(true, true), 35000);
}

/* Nur hochladen, wenn sich wirklich etwas geaendert hat. Sonst verbraucht
   jeder App-Start einen Schreibzugriff, und die sind knapp. */
let pushedSignature = null;

/* Wen wir schon kennen. Damit holt der Server die Dokumente einzeln statt
   ueber ein Verzeichnis - siehe die Erklaerung in team.js. */
let knownMembers = store.get('teammembers', []) || [];
let lastDiscover = 0;
const DISCOVER_EVERY_MS = 10 * 60 * 1000;

let throttledUntil = 0;

async function runSync(quiet, pullOnly) {
  if (!team || !team.config || syncing) return;
  if (Date.now() < throttledUntil && quiet) return;
  syncing = true;
  const note = $('#m-team-note');
  if (note && !quiet) note.textContent = 'Abgleich läuft …';
  try {
    const doc = myTeamDoc();
    // at ist ein Zeitstempel und aendert sich immer - fuer den Vergleich raus.
    const sig = JSON.stringify([doc.fav, doc.seen, doc.rate]);
    const needPush = !pullOnly && sig !== pushedSignature;
    /* Nach neuen Mitgliedern SUCHEN kostet eine Verzeichnis-Abfrage, und davon
       gibt es nur 1.000 am Tag. Also nur, wenn es einen Grund gibt: wir kennen
       noch niemanden, jemand hat von Hand angestossen, oder es ist zehn
       Minuten her. */
    const discover = !knownMembers.length || !quiet
      || Date.now() - lastDiscover > DISCOVER_EVERY_MS;
    const ids = discover ? null : knownMembers;
    if (discover) lastDiscover = Date.now();
    let others;
    if (needPush) {
      others = await team.sync(doc, ids);
      pushedSignature = sig;
      scheduleCatchUp();
    } else {
      others = await team.pull(ids);
    }
    // Nur ein echtes Suchen darf die Liste ersetzen; eine gezielte Abfrage
    // kann per Bauart niemanden Neues enthalten.
    if (others.listed) {
      const found = others.map((o) => o.id).sort();
      if (JSON.stringify(found) !== JSON.stringify([...knownMembers].sort())) {
        knownMembers = found;
        store.set('teammembers', knownMembers);
      }
    }
    const before = partnerSignature();
    const n = adoptOthers(others);
    const changed = partnerSignature() !== before;
    if (changed) lastRemoteChange = Date.now();
    const undec = others.filter((o) => o.undecryptable).length;
    lastSyncAt = new Date().toISOString();
    store.set('lastsync', lastSyncAt);
    teamInfo();
    partnerInfo();
    metaLine();
    // NUR neu zeichnen, wenn von der Gegenseite wirklich etwas Neues kam.
    // Vorher lief hier alle 15 Sekunden ein voller Neuaufbau der Liste - 111 ms
    // auf einem gebremsten Handy, fuer nichts. Genau das war die spuerbare
    // Traegheit.
    if (changed) render();
    if (!quiet) {
      // Genau sagen, was passiert ist. "Abgeglichen" allein liess offen, ob
      // etwas hochgeladen wurde und ob die Gegenseite ueberhaupt existiert.
      const sent = needPush ? 'Deine Auswahl ist hochgeladen. '
                            : 'Nichts Neues zum Hochladen. ';
      alert(sent + (n
        ? `${n} weitere Person(en) im Team gelesen.`
        + (undec ? ` ${undec} Eintrag/Einträge sind nicht lesbar — dort weicht `
                 + 'die Passphrase ab.' : '')
        : undec
          ? `${undec} Eintrag/Einträge sind nicht lesbar — dort weicht die `
            + 'Passphrase ab. Beide brauchen genau dieselbe.'
          // Nicht "niemand da" behaupten: ein neuer Eintrag taucht im
          // Verzeichnis erst nach etwa 30 Sekunden auf.
          : 'Noch niemand sonst sichtbar. Ein frischer Beitritt braucht rund '
            + 'eine halbe Minute, bis er auf der anderen Seite ankommt — die '
            + 'App fragt von selbst nach.'));
    }
    if (quiet && undec && !n && note) {
      note.textContent = 'Die Gegenseite ist nicht lesbar — dort weicht die '
        + 'Passphrase ab. Beide brauchen genau dieselbe.';
    }
  } catch (err) {
    if (err.status === 429) {
      /* Tagesbudget des Speichers erreicht. Weiter im Sekundentakt zu fragen
         macht es nur schlimmer - also lange Pause und Bescheid sagen. */
      throttledUntil = Date.now() + 30 * 60 * 1000;
      const msg = 'Der Speicher hat sein Tagesbudget erreicht. Der Abgleich '
        + 'pausiert eine halbe Stunde. Deine Auswahl bleibt auf dem Gerät.';
      if (note) note.textContent = msg;
      if (!quiet) alert(msg);
    } else {
      const msg = err.code === 'token_invalid'
        ? 'Die Passphrase passt nicht zu diesem Team.'
        : `Abgleich fehlgeschlagen: ${err.message}`;
      if (note) note.textContent = msg;
      if (!quiet) alert(msg);
    }
  } finally {
    syncing = false;
  }
}

$('#m-team-new').addEventListener('click', async () => {
  const name = (prompt('Wie sollen die anderen dich sehen?', 'Ich') || '').trim();
  if (!name) return;
  const pass = (prompt('Passphrase für das Team. Beide brauchen genau dieselbe.\n'
    + 'Mindestens 12 Zeichen, gern ein Satz.') || '').trim();
  if (pass.length < 12) { alert('Zu kurz — mindestens 12 Zeichen.'); return; }
  team.create(name, pass);
  teamInfo();
  el.menu.close();
  await runSync(false);
  startPulling();
});

$('#m-team-join').addEventListener('click', async () => {
  const raw = (prompt('Beitrittslink oder Team-ID einfügen:') || '').trim();
  const m = raw.match(/[A-Za-z0-9_-]{16,40}$/);
  if (!m) { alert('Darin steckt keine Team-ID.'); return; }
  const name = (prompt('Wie sollen die anderen dich sehen?', 'Ich') || '').trim();
  if (!name) return;
  const pass = (prompt('Passphrase des Teams:') || '').trim();
  if (pass.length < 12) { alert('Zu kurz — mindestens 12 Zeichen.'); return; }
  team.join(m[0], name, pass);
  teamInfo();
  el.menu.close();
  await runSync(false);
  startPulling();
});

$('#m-team-share').addEventListener('click', async () => {
  const c = team.config;
  const link = `${location.origin}${location.pathname}#team=${c.teamId}`;
  try {
    await navigator.clipboard.writeText(link);
    alert('Link kopiert. Die Passphrase NICHT über denselben Kanal schicken — '
        + 'sonst hat ein Mitlesender beides.');
  } catch (e) {
    prompt('Link zum Kopieren:', link);
  }
});

$('#m-team-leave').addEventListener('click', () => {
  if (!confirm('Team verlassen? Deine eigenen Daten bleiben auf diesem Gerät.')) return;
  team.leave();
  clearInterval(pullTimer);
  teamInfo();
  el.menu.close();
  alert('Team verlassen. Das Dokument auf dem Server bleibt bis zum Ablauf liegen.');
});

$('#m-sync').addEventListener('click', () => { el.menu.close(); runSync(false); });

$('#m-plan').addEventListener('click', () => { el.menu.close(); showPlan(true); });
$('#m-news').addEventListener('click', () => { el.menu.close(); showNews(true); });

for (const id of ['plan-max', 'plan-set', 'plan-fav', 'plan-team']) {
  const node = $('#' + id);
  if (node) node.addEventListener('change', renderPlan);
}
$('#plan-map').addEventListener('click', showRoute);
$('#plan-ics').addEventListener('click', () => {
  if (!lastPlan || !lastPlan.stops.length) { alert('Es gibt noch keinen Plan.'); return; }
  const shows = lastPlan.stops.map((s) => {
    const sh = S.data.shows.find((x) => x.id === s.id);
    const act = S.data.acts[sh.a];
    return {
      artist: act.n, start: sh.t, ext_id: sh.id,
      venue: sh.v != null ? S.data.venues[sh.v].n : null,
      genres: (act.g || []).map((i) => S.data.genres[i]),
      country: act.c, url: act.url, time_tbd: false,
    };
  });
  // Der ICS-Bau steckt im Python-Teil; hier die schlanke Variante.
  const pad = (n) => String(n).padStart(2, '0');
  const stamp = (iso) => {
    const d = new Date(iso);
    return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}`
      + `T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}00Z`;
  };
  const esc2 = (t) => String(t || '').replace(/([,;\\])/g, '\\$1');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//rbf-lineup//DE',
                 'CALSCALE:GREGORIAN', 'X-WR-CALNAME:Reeperbahn Abendplan'];
  const opts = planOptions();
  for (const s of shows) {
    const endMs = new Date(s.start).getTime() + opts.setMinutes * 60000;
    lines.push('BEGIN:VEVENT', `UID:${s.ext_id}@rbf-plan`,
      `DTSTAMP:${stamp(new Date().toISOString())}`,
      `DTSTART:${stamp(s.start)}`, `DTEND:${stamp(new Date(endMs).toISOString())}`,
      `SUMMARY:${esc2(s.artist)}`, `LOCATION:${esc2(s.venue || '')}`,
      `DESCRIPTION:${esc2((s.genres || []).join(', '))}`, 'END:VEVENT');
  }
  lines.push('END:VCALENDAR');
  download('reeperbahn-abendplan.ics', lines.join('\r\n') + '\r\n', 'text/calendar');
});

$('#m-partner').addEventListener('click', () => el.filePartner.click());
$('#m-partner-clear').addEventListener('click', () => {
  partner = null;
  store.set('partner', null);
  S.teamOnly = false;
  $('#f-team').setAttribute('aria-pressed', 'false');
  partnerInfo();
  render();
});

function partnerName() {
  return (partner && partner.name) || 'Partner:in';
}

function partnerInfo() {
  const note = $('#m-partner-note');
  const clear = $('#m-partner-clear');
  if (!note) return;
  const online = !!(team && team.config);
  if (!partner) {
    clear.hidden = true;
    note.textContent = online
      ? 'Von der anderen Seite ist noch nichts angekommen. Sobald sie dem Team '
        + 'beigetreten ist und etwas bewertet, erscheint es hier von selbst — '
        + 'ohne Datei.'
      : 'Noch nichts von der anderen Seite. Mit einem Online-Team geht das von '
        + 'selbst; ohne Team über „Auswahl sichern“ und die Datei austauschen.';
    return;
  }
  clear.hidden = false;
  const both = S.data
    ? S.data.acts.filter((a) => bothWant(a.id)).length : 0;
  note.textContent = `${partnerName()}: ${(partner.fav || []).length} Favoriten, `
    + `${Object.keys(partner.rate || {}).length} bewertet, `
    + `${(partner.seen || []).length} gesehen · ${both} Acts wollt ihr beide sehen.`
    + (online && lastSyncAt ? ` · Stand ${relTime(lastSyncAt)}` : '');
}

el.filePartner.addEventListener('change', async () => {
  const f = el.filePartner.files && el.filePartner.files[0];
  if (!f) return;
  let data;
  try { data = JSON.parse(await f.text()); }
  catch (err) { alert('Die Datei ist kein gültiges JSON.'); return; }
  el.filePartner.value = '';
  if (data.kind !== 'rbf26-auswahl') {
    alert('Das ist kein Export dieser App. Die Partner:in muss im Menü '
        + '„Auswahl sichern“ verwenden.');
    return;
  }
  // Der Name wird erfragt, nicht geraten - die Datei enthaelt keinen.
  const name = (prompt('Wie soll die Person heißen?', data.name || 'Partner:in')
    || 'Partner:in').slice(0, 24);
  partner = {
    name,
    fav: (data.fav || []).map(Number),
    seen: (data.seen || []).map(Number),
    rate: data.rate || {},
    loaded_at: new Date().toISOString().slice(0, 16).replace('T', ' '),
  };
  store.set('partner', partner);
  partnerInfo();
  render();
  alert(`${name} übernommen. Der Filter „Beide“ zeigt jetzt, wo ihr euch einig seid.`);
});

if ('serviceWorker' in navigator) {
  addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}

/* Beitrittslink: #team=... im Fragment aufgreifen, aber nichts ohne Zutun
   speichern - die Passphrase fehlt ja noch. */
(function fromLink() {
  const m = location.hash.match(/team=([A-Za-z0-9_-]{16,40})/);
  if (!m || !team || team.config) return;
  addEventListener('load', () => {
    if (!confirm('Dieser Link lädt dich in ein Team ein. Beitreten?')) return;
    history.replaceState(null, '', location.pathname);
    $('#m-team-join').click();
  });
})();

/* Wechselt man weg, bevor die Verzoegerung abgelaufen ist, waere die
   Aenderung sonst erst beim naechsten Start draussen. */
addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') {
    // Ausstehende eigene Aenderung noch mitnehmen.
    if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; runSync(true); }
  } else {
    runSync(true, true);   // zurueck im Bild: nur lesen
  }
});

$('#player-close').addEventListener('click', closePlayer);

/* ---------- Wischen auf Kuenstlerzeilen ----------
   Nach rechts: Bewertung waehlen. Nach links: als gesehen markieren.
   Beide Richtungen sind im Menue umstellbar.

   Bewusst OHNE Huellelement pro Zeile: das haette jede CSS-Regel und jeden
   Test getroffen, der auf "#list > .row" baut. Stattdessen wird die Zeile
   selbst verschoben und EIN gemeinsames Feld dahintergelegt, positioniert
   nach der Bounding-Box der Zeile.

   Kein preventDefault noetig: "touch-action: pan-y pinch-zoom" auf der Zeile
   sagt dem Browser, dass senkrecht gescrollt und gezoomt werden darf,
   waagerecht aber nicht - er ueberlaesst uns die Richtung von selbst. Damit
   koennen alle Zuhoerer passiv bleiben, was auf schwachen Geraeten den
   Unterschied macht. */
/* Wischen ist AUSGESCHALTET. Die Mechanik bleibt vollstaendig erhalten -
   sie taugt spaeter fuer etwas anderes -, aber sie loest nichts mehr aus, bis
   man sie im Menue einschaltet. Bewertet wird jetzt in der Anspielleiste,
   dafuer braucht es keine Geste. */
const SWIPE_DEFAULTS = { on: false, left: 'seen', right: 'quick', dist: 72,
                         v: 2 };
const SWIPE_ACTIONS = {
  seen: { icon: '✓', text: 'Gesehen', cls: 'act-seen' },
  fav: { icon: '♥', text: 'Favorit', cls: 'act-fav' },
  rate1: { icon: '1', text: 'Note 1', cls: 'act-r1' },
  rate5: { icon: '5', text: 'Note 5', cls: 'act-r5' },
  quick: { icon: '★', text: 'Bewerten', cls: 'act-quick' },
  off: null,
};
let swipeCfg = Object.assign({}, SWIPE_DEFAULTS, store.get('swipe', {}) || {});
/* Einmalig abschalten, auch bei denen, die es schon eingeschaltet gespeichert
   haben. Wer es danach im Menue wieder anmacht, behaelt das - die Marke v
   verhindert, dass ihm hier ein zweites Mal dazwischengeredet wird. */
if (swipeCfg.v !== 2) {
  swipeCfg = Object.assign({}, swipeCfg, { on: false, v: 2 });
  store.set('swipe', swipeCfg);
}

/* Zeilen, deren Beruehrung auf einem eigenen Bedienelement beginnt, wischen
   nicht - sonst kaeme man an Herz und Play nicht mehr sauber heran. */
const SWIPE_SKIP = '.row-fav, .row-play, .venue, .tag';

let sw = null;                 // laufende Geste
let suppressClickUntil = 0;    // ein Wisch darf die Zeile nicht oeffnen

function swipeActionFor(dx) {
  return SWIPE_ACTIONS[dx > 0 ? swipeCfg.right : swipeCfg.left] || null;
}

function swipePaint(dx) {
  const box = el.swipe;
  const act = swipeActionFor(dx);
  const armed = Math.abs(dx) >= swipeCfg.dist;
  /* Die Position JEDES Mal neu bestimmen. Vorher wurde sie einmal beim
     Beruehren gemerkt - aber eine Geste beginnt oft senkrecht, der Browser
     scrollt noch ein Stueck, und danach klebte das Feld an einer alten
     Bildschirmposition: es lag ueber einer voelligt anderen Zeile.
     Ein getBoundingClientRect pro Bewegung ist billig, die Zeile ist ja
     schon vermessen. */
  const r = sw.row.getBoundingClientRect();
  box.style.top = `${r.top}px`;
  box.style.left = `${r.left - dx}px`;
  box.style.width = `${r.width}px`;
  box.style.height = `${r.height}px`;
  box.className = 'swipe'
    + (act ? ' ' + act.cls : ' act-none')
    + (dx > 0 ? ' from-left' : ' from-right')
    + (armed ? ' armed' : '');
  box.querySelector('.swipe-icon').textContent = act ? act.icon : '·';
  box.querySelector('.swipe-text').textContent = act ? act.text : '—';
  sw.row.style.transform = `translateX(${dx}px)`;
}

function swipeStart(row, touch) {
  sw = { row, ai: +row.dataset.act, x0: touch.clientX, y0: touch.clientY,
         dx: 0, active: false };
}

function swipeCancel() {
  if (!sw) return;
  // Die Zeile kann inzwischen ausgetauscht sein (ein Neuaufbau ersetzt das
  // Element). Dann steckt der Versatz noch an einer Zeile, die keiner mehr
  // sieht - und an der neuen darf keiner haengen. Also beides aufraeumen.
  sw.row.style.transform = '';
  sw.row.classList.remove('swiping');
  for (const stale of el.list.querySelectorAll('.row.swiping')) {
    stale.style.transform = '';
    stale.classList.remove('swiping');
  }
  el.swipe.hidden = true;
  sw = null;
  // Ein waehrend der Geste aufgeschobener Neuaufbau wird jetzt nachgeholt.
  if (renderPending) render();
}

function swipeFinish() {
  if (!sw) return;
  const { dx, ai } = sw;
  const far = Math.abs(dx) >= swipeCfg.dist;
  const active = sw.active;
  swipeCancel();
  if (!active) return;
  // Nur den Klick der Geste selbst abfangen - der kommt in wenigen
  // Millisekunden. 500 ms hatten auch einen echten Tipper danach
  // verschluckt.
  suppressClickUntil = Date.now() + 350;
  if (far) runSwipeAction(dx > 0 ? swipeCfg.right : swipeCfg.left, ai);
}

function runSwipeAction(key, ai) {
  const act = S.data.acts[ai];
  if (!act || key === 'off') return;
  const id = act.id;
  if (key === 'quick') { openQuick(ai); return; }
  if (key === 'fav') {
    const was = fav.has(id);
    was ? fav.delete(id) : fav.add(id);
    saveFav(); scheduleSync(); refreshAct(ai);
    toast(`${act.n}: ${was ? 'kein Favorit mehr' : 'als Favorit gemerkt'}`, 3200,
          () => { was ? fav.add(id) : fav.delete(id);
                  saveFav(); scheduleSync(); refreshAct(ai); });
    return;
  }
  if (key === 'seen') {
    const was = seen.has(id);
    was ? seen.delete(id) : seen.add(id);
    saveSeen(); scheduleSync(); refreshAct(ai);
    toast(`${act.n}: ${was ? 'nicht mehr als gesehen' : 'als gesehen markiert'}`, 3200,
          () => { was ? seen.add(id) : seen.delete(id);
                  saveSeen(); scheduleSync(); refreshAct(ai); });
    return;
  }
  const want = key === 'rate1' ? 1 : 5;
  const before = rate[id];
  if (+before === want) delete rate[id]; else rate[id] = want;
  store.set('rate', rate); scheduleSync(); refreshAct(ai);
  toast(`${act.n}: ${rate[id] ? 'Note ' + rateText(rate[id]) : 'Note entfernt'}`, 3200,
        () => {
          if (before === undefined) delete rate[id]; else rate[id] = before;
          store.set('rate', rate); scheduleSync(); refreshAct(ai);
        });
}

el.list.addEventListener('touchstart', (e) => {
  if (!swipeCfg.on || e.touches.length !== 1) return;
  // Eine haengengebliebene Geste aufraeumen statt die neue abzulehnen. Geht
  // ein touchend verloren - Browser brechen eine Beruehrung auch mal ohne
  // Ereignis ab -, waere sonst bis zum Neuladen kein Wischen mehr moeglich.
  if (sw) swipeCancel();
  const row = e.target.closest && e.target.closest('.row');
  if (!row || e.target.closest(SWIPE_SKIP)) return;
  swipeStart(row, e.touches[0]);
}, { passive: true });

el.list.addEventListener('touchmove', (e) => {
  if (!sw || e.touches.length !== 1) return;
  const t = e.touches[0];
  const dx = t.clientX - sw.x0;
  const dy = t.clientY - sw.y0;
  if (!sw.active) {
    // Erst ab einer klar waagerechten Bewegung uebernehmen. Ohne das
    // verrutscht jeder Scrollversuch die Zeile.
    if (Math.abs(dy) > Math.abs(dx) || Math.abs(dx) < 12) {
      if (Math.abs(dy) > 12) swipeCancel();
      return;
    }
    sw.active = true;
    sw.row.classList.add('swiping');
    el.swipe.hidden = false;
  }
  sw.dx = dx;
  swipePaint(dx);
}, { passive: true });

el.list.addEventListener('touchend', swipeFinish, { passive: true });
el.list.addEventListener('touchcancel', swipeCancel, { passive: true });

/* Ein Wisch endet auf der Zeile und wuerde sonst als Tipper gelten. Der
   Abfang laeuft in der Erfassungsphase, damit er vor jedem anderen
   Zuhoerer greift. */
el.list.addEventListener('click', (e) => {
  if (Date.now() < suppressClickUntil) {
    e.stopPropagation();
    e.preventDefault();
  }
}, true);

/* ---------- Schnellbewertung ---------- */

let quickAct = null;

function openQuick(ai) {
  const act = S.data.acts[ai];
  if (!act) return;
  quickAct = ai;
  $('#quick-name').textContent = act.n;
  // Dieselben data-r-Knoepfe wie im Detaildialog. Erst hatten sie data-qr,
  // damit der gemeinsame Zuhoerer sie nicht faengt - aber das CSS zielt auf
  // data-r, also fehlte der farbige Grund und eine gesetzte Note war dunkel
  // auf dunkel, also unsichtbar. Jetzt liest der Zuhoerer den Act vom
  // Dialog, und beide benutzen dieselben Knoepfe und dasselbe CSS.
  el.quick.dataset.act = act.id;
  el.quick.dataset.ai = ai;
  $('#quick-rate').innerHTML = RATES.map(([k, label]) =>
    `<button data-r="${k}" class="${Number.isInteger(k) ? '' : 'is-half'}"
      aria-pressed="${+rate[act.id] === k}"
      aria-label="${rateText(k)} - ${label}"><b>${rateText(k)}</b><small
      >${esc(label)}</small></button>`).join('');
  $('#quick-fav').setAttribute('aria-pressed', String(fav.has(act.id)));
  $('#quick-clear').hidden = !rate[act.id];
  el.quick.showModal();
  syncDialogCount();
}

/* Die Noten selbst macht der gemeinsame data-r-Zuhoerer. Hier bleibt nur,
   was es im Detaildialog nicht gibt. */
el.quick.addEventListener('click', (e) => {
  if (quickAct == null) return;
  const id = S.data.acts[quickAct].id;
  if (e.target.closest('#quick-fav')) {
    fav.has(id) ? fav.delete(id) : fav.add(id);
    saveFav(); scheduleSync(); refreshAct(quickAct);
    $('#quick-fav').setAttribute('aria-pressed', String(fav.has(id)));
    return;
  }
  if (e.target.closest('#quick-clear')) {
    delete rate[id];
    store.set('rate', rate); scheduleSync(); refreshAct(quickAct);
    el.quick.close();
  }
});

/* ---------- Einstellungen zum Wischen ---------- */

function renderSwipeOpts() {
  $('#sw-on').checked = !!swipeCfg.on;
  $('#sw-left').value = swipeCfg.left;
  $('#sw-right').value = swipeCfg.right;
  $('#sw-dist').value = String(swipeCfg.dist);
}

for (const [id, key] of [['sw-on', 'on'], ['sw-left', 'left'],
                         ['sw-right', 'right'], ['sw-dist', 'dist']]) {
  $('#' + id).addEventListener('change', (e) => {
    swipeCfg[key] = key === 'on' ? e.target.checked
      : key === 'dist' ? +e.target.value : e.target.value;
    store.set('swipe', swipeCfg);
  });
}

/* ---------- Zurueck-Taste und Zurueck-Geste ----------
   Ohne das verlaesst ein Wisch von der Kante die App, obwohl gerade nur ein
   Dialog offen ist. Der Trick: beim Start einen Eintrag in die Historie
   legen. Jedes Zurueck poppt ihn, wir raeumen eine Ebene auf und legen ihn
   neu - erst wenn nichts mehr offen ist UND wir vorgewarnt haben, legen wir
   ihn nicht neu, und das naechste Zurueck verlaesst die App wirklich. */
let leaveArmed = false;
let leaveTimer = null;

/* Was das Zurueck der Reihe nach schliesst. Erste zutreffende Ebene gewinnt. */
function closeOneLayer() {
  if (el.quick.open) { el.quick.close(); return true; }
  if (el.detail.open) { el.detail.close(); return true; }
  if (el.menu.open) { el.menu.close(); return true; }
  if (!el.player.hidden) { closePlayer(); return true; }
  if (BOXES.some((n) => !el[n].hidden)) { openBox(null); return true; }
  if (S.newsOn) { showNews(false); return true; }
  if (S.planOn) { showPlan(false); return true; }
  if (S.mapOn) { setMap(false); return true; }
  if (!el.searchbar.hidden) { setSearch(false); return true; }
  return false;
}

/* Der Wachposten wird VERZOEGERT neu gelegt, nicht synchron im Handler.
   history.pushState() mitten in der Abarbeitung von popstate ist in Firefox
   fuer Android eine bekannt wacklige Stelle. Der gemeinsame Timer sorgt
   ausserdem dafuer, dass zwei Aufrufe im selben Durchlauf zu EINEM Eintrag
   werden - sonst braeuchte es hinterher zwei Zurueck fuer eine Ebene. */
let guardTimer = null;
function rearmGuard() {
  clearTimeout(guardTimer);
  guardTimer = setTimeout(() => {
    try { history.pushState({ rbf: 'guard' }, ''); } catch (e) { /* egal */ }
  }, 0);
}

/* Browser schliessen einen modalen Dialog beim Zurueck teils SELBST. Chrome
   verbraucht den Druck dabei und loest kein popstate aus, Firefox fuer
   Android loest es zusaetzlich aus. Ohne Gegenmassnahme geht dort eine Ebene
   zu viel zu.

   Erkannt wird das durch ZAEHLEN, nicht ueber das close-Ereignis. Das kommt
   erst im naechsten Durchlauf - ein Zeitstempel daraus ist zum Zeitpunkt des
   popstate noch leer. Genau daran ist mein erster Versuch gescheitert, und
   in echtem Firefox waere er genauso gescheitert. Der Vergleich unten ist
   synchron. */
const DIALOGS = [el.detail, el.menu, el.quick];
let dialogsOpen = 0;
function syncDialogCount() {
  dialogsOpen = DIALOGS.filter((d) => d.open).length;
}
for (const dlg of DIALOGS) dlg.addEventListener('close', syncDialogCount);

history.replaceState({ rbf: 'base' }, '');
history.pushState({ rbf: 'guard' }, '');

addEventListener('popstate', () => {
  // Weniger Dialoge offen als zuletzt bekannt? Dann hat der Browser selbst
  // einen geschlossen, und diese Ebene ist schon verbraucht.
  const nowOpen = DIALOGS.filter((d) => d.open).length;
  if (nowOpen < dialogsOpen) { dialogsOpen = nowOpen; rearmGuard(); return; }
  if (closeOneLayer()) { syncDialogCount(); rearmGuard(); return; }
  if (!leaveArmed) {
    leaveArmed = true;
    toast('Nochmal zurück zum Verlassen der App', 2600);
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(() => { leaveArmed = false; }, 2600);
    rearmGuard();
    return;
  }
  // Vorgewarnt und nichts mehr offen: nichts neu auflegen, der Browser geht.
});

/* Erst das Programm, dann die Aenderungen: die Liste soll nicht auf eine
   Zusatzdatei warten. Danach einmal neu zeichnen, damit die Marken sitzen. */
load().then(() => {
  if (team && team.config) { runSync(true); startPulling(); }
  return loadChanges();
}).then(() => {
  if (S.data && changeByShow.size) render();
});
