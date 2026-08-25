/* Reeperbahn-Timetable. Vanilla, kein Build-Schritt.
   Eigener Zustand (Favoriten, Notizen, Ampel) bleibt im Browser. */
'use strict';

const DATA_URL = 'data/lineup.json';
const KEY = 'rbf26.';
const WD = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
const RATES = [['gruen', 'Hin'], ['gelb', 'Vielleicht'], ['rot', 'Nein']];
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
let note = store.get('note', {});
let rate = store.get('rate', {});
const anchor = store.get('anchor', {});
/* Vorschlaege aus taste.py. Getrennt von "rate": die eigene Bewertung
   gewinnt immer, der Vorschlag ist nur eine Vorbelegung. */
let hint = store.get('hint', {});

const saveFav = () => store.set('fav', [...fav]);

/* ---------- Zustand ---------- */

const S = {
  data: null,
  day: null,
  q: '',
  favOnly: false,
  rateOnly: false,
  genres: new Set(),
  venues: new Set(),
  mapOn: false,
};

let map = null, markers = [];

const $ = (sel) => document.querySelector(sel);
const el = {
  status: $('#status'), list: $('#list'), mapBox: $('#map'), days: $('#days'),
  genrebox: $('#genrebox'), venuebox: $('#venuebox'),
  detail: $('#detail'), meta: $('#meta'),
  q: $('#q'), searchbar: $('#searchbar'), file: $('#file'),
};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const hhmm = (iso) => iso ? iso.slice(11, 16) : '';
const fold = (s) => String(s ?? '').toLowerCase()
  .normalize('NFD').replace(/[̀-ͯ]/g, '')
  .replace(/ø/g, 'o').replace(/ß/g, 'ss');

/* ---------- Laden ---------- */

async function load() {
  try {
    const res = await fetch(DATA_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    S.data = await res.json();
  } catch (err) {
    el.status.innerHTML = '<b>Programm konnte nicht geladen werden.</b><br>' +
      esc(err.message) + '<br><small>Ohne Netz zeigt die App den letzten ' +
      'gespeicherten Stand — beim ersten Aufruf gibt es den noch nicht.</small>';
    return;
  }
  S.day = S.data.days.includes(todayISO()) ? todayISO() : S.data.days[0];
  el.status.hidden = true;
  renderDays();
  renderGenres();
  renderVenues();
  render();
  const d = new Date(S.data.generated_at);
  el.meta.textContent = `${S.data.acts.length} Acts · ${S.data.shows.length} Auftritte · ` +
    `Stand ${isNaN(d) ? S.data.generated_at : d.toLocaleDateString('de-DE')}`;
}

const todayISO = () => new Date().toISOString().slice(0, 10);

/* ---------- Kopfbereich ---------- */

function renderDays() {
  el.days.innerHTML = S.data.days.map((d) => {
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
  el.venuebox.innerHTML = entries.map(([i, n]) =>
    `<button class="chip" data-venuefilter="${i}" aria-pressed="${S.venues.has(i)}"
      >${esc(S.data.venues[i].n)} <span class="tag">${n}</span></button>`).join('');
}

/* ---------- Auswahl ---------- */

function visibleShows() {
  const q = fold(S.q.trim());
  const searching = q.length > 0;
  const out = [];

  for (const sh of S.data.shows) {
    const act = S.data.acts[sh.a];

    // Bei aktiver Suche ueber alle Tage suchen, sonst nur der gewaehlte Tag.
    if (!searching && sh.d && sh.d !== S.day) continue;

    if (S.favOnly && !fav.has(act.id)) continue;
    if (S.rateOnly && !rate[act.id]) continue;

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

function render() {
  const anyFilter = S.favOnly || S.rateOnly || S.genres.size > 0
    || S.venues.size > 0 || S.q.trim() !== '';
  $('#f-reset').hidden = !anyFilter;
  $('#f-genre').classList.toggle('on', S.genres.size > 0);
  $('#f-genre').textContent = S.genres.size ? `Genres (${S.genres.size})` : 'Genres';
  $('#f-venue').classList.toggle('on', S.venues.size > 0);
  $('#f-venue').textContent = S.venues.size ? `Spielorte (${S.venues.size})` : 'Spielorte';

  if (S.mapOn) { el.list.hidden = true; el.mapBox.hidden = false; sizeMap(); return; }
  el.mapBox.hidden = true;
  el.list.hidden = false;

  const shows = visibleShows();
  if (!shows.length) {
    el.list.innerHTML = `<p class="empty"><b>Nichts gefunden.</b>
      ${anyFilter ? 'Vielleicht ist ein Filter zu eng.' : ''}</p>`;
    return;
  }

  const searching = S.q.trim() !== '';
  let html = '', head = '';
  for (const sh of shows) {
    const act = S.data.acts[sh.a];
    const group = sh.tbd ? 'Uhrzeit noch offen'
      : (searching ? dayLabel(sh) + ', ' + hhmm(sh.t) : hhmm(sh.t).slice(0, 2) + ' Uhr');
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
  const tags = act.g.map((i) => `<span class="tag">${esc(S.data.genres[i])}</span>`).join('');
  return `<button class="row${r ? ' rated-' + r : ''}" data-show="${esc(sh.id)}" data-act="${sh.a}">
    <span class="row-time${sh.tbd ? ' tbd' : ''}">${sh.tbd ? 'Zeit<br>offen' : hhmm(sh.t)}</span>
    <span class="row-main">
      <span class="row-name${note[act.id] ? ' has-note' : ''}">${esc(act.n)}${
        !r && hint[act.id] ? `<span class="hint hint-${hint[act.id].v}"
          title="Vorschlag: ${esc(hint[act.id].v)}"></span>` : ''}</span>
      <span class="row-sub">${venue
        ? `<span class="venue" data-venue="${sh.v}">${esc(venue.n)}</span>` : 'Spielort offen'}
        ${act.c ? ' · ' + esc(act.c) : ''}</span>
      ${tags ? `<span class="row-tags">${tags}</span>` : ''}
    </span>
    <span class="row-fav" role="button" aria-pressed="${fav.has(act.id)}"
      data-fav="${act.id}" aria-label="Favorit">${fav.has(act.id) ? '♥' : '♡'}</span>
  </button>`;
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
        anchor[S.day] = r.dataset.show;
        store.set('anchor', anchor);
        break;
      }
    }
  }, 150);
}, { passive: true });

function restoreAnchor() {
  const id = anchor[S.day];
  if (!id || S.q.trim()) return;
  const target = el.list.querySelector(`.row[data-show="${CSS.escape(id)}"]`);
  if (!target) return;
  const top = document.querySelector('.top').offsetHeight;
  requestAnimationFrame(() => {
    const y = target.getBoundingClientRect().top + scrollY - top - 8;
    scrollTo({ top: Math.max(0, y), behavior: 'instant' });
  });
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
        `<button data-r="${k}" aria-pressed="${rate[act.id] === k}">${label}</button>`).join('')}
      </div>
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
      <button class="chip" data-fav="${act.id}" aria-pressed="${fav.has(act.id)}">
        <span class="heart">${fav.has(act.id) ? '♥' : '♡'}</span>
        ${fav.has(act.id) ? 'Favorit' : 'Als Favorit merken'}
      </button>
    </div>
  </div>`;

  el.detail.dataset.act = act.id;
  if (!el.detail.open) el.detail.showModal();
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

  const pts = [];
  S.data.venues.forEach((v, i) => {
    if (v.lat == null) return;
    const bits = [
      v.addr && esc(v.addr),
      v.cap && `Kapazität ${v.cap}`,
      v.acc && v.acc.length && esc(v.acc.join(', ')),
      v.inherited && v.parent && `Koordinaten von ${esc(v.parent)}`,
    ].filter(Boolean);
    const m = L.marker([v.lat, v.lng]).addTo(map).bindPopup(
      `<div class="pop-title">${esc(v.n)}</div>
       <div class="pop-meta">${counts.get(i) || 0} Auftritte${bits.length ? '<br>' + bits.join('<br>') : ''}</div>`);
    markers[i] = m;
    pts.push([v.lat, v.lng]);
  });
  if (pts.length) map.fitBounds(pts, { padding: [30, 30] });
  return map;
}

function showVenue(i) {
  const v = S.data.venues[i];
  if (!v || v.lat == null) return;
  if (el.detail.open) el.detail.close();
  el.genrebox.hidden = true;
  el.venuebox.hidden = true;
  S.mapOn = true;
  $('#btn-map').setAttribute('aria-pressed', 'true');
  render();
  const m = ensureMap();
  setTimeout(() => {
    m.invalidateSize();
    m.setView([v.lat, v.lng], 17);
    if (markers[i]) markers[i].openPopup();
  }, 60);
}

/* ---------- Ereignisse ---------- */

document.addEventListener('click', (e) => {
  const t = e.target;

  const venue = t.closest('[data-venue]');
  if (venue) { e.preventDefault(); e.stopPropagation(); showVenue(+venue.dataset.venue); return; }

  const favBtn = t.closest('[data-fav]');
  if (favBtn) {
    e.preventDefault(); e.stopPropagation();
    const id = +favBtn.dataset.fav;
    fav.has(id) ? fav.delete(id) : fav.add(id);
    saveFav();
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

  const rateBtn = t.closest('[data-r]');
  if (rateBtn) {
    const id = el.detail.dataset.act;
    const val = rateBtn.dataset.r;
    if (rate[id] === val) delete rate[id]; else rate[id] = val;
    store.set('rate', rate);
    for (const b of el.detail.querySelectorAll('[data-r]')) {
      b.setAttribute('aria-pressed', String(rate[id] === b.dataset.r));
    }
    render();
    return;
  }

  if (t.closest('[data-close]')) { el.detail.close(); return; }

  const day = t.closest('.day');
  if (day) {
    S.day = day.dataset.day;
    for (const b of el.days.children) b.setAttribute('aria-selected', String(b === day));
    if (S.mapOn) { S.mapOn = false; $('#btn-map').setAttribute('aria-pressed', 'false'); }
    render();
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
$('#btn-search').addEventListener('click', () => {
  const open = el.searchbar.hidden;
  el.searchbar.hidden = !open;
  if (open) el.q.focus({ preventScroll: true });
  else { el.q.value = ''; S.q = ''; render(); }
});

$('#q-clear').addEventListener('click', () => {
  el.q.value = ''; S.q = ''; el.searchbar.hidden = true; render();
});

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

$('#f-rate').addEventListener('click', (e) => {
  S.rateOnly = !S.rateOnly;
  e.currentTarget.setAttribute('aria-pressed', String(S.rateOnly));
  render();
});

$('#f-genre').addEventListener('click', () => {
  const open = el.genrebox.hidden;
  el.genrebox.hidden = !open;
  if (open) el.venuebox.hidden = true;   // nur ein Kasten offen
  sizeMap();
});

$('#f-venue').addEventListener('click', () => {
  const open = el.venuebox.hidden;
  el.venuebox.hidden = !open;
  if (open) el.genrebox.hidden = true;
  sizeMap();
});

$('#f-reset').addEventListener('click', () => {
  S.favOnly = S.rateOnly = false; S.genres.clear(); S.venues.clear(); S.q = '';
  el.q.value = ''; el.searchbar.hidden = true;
  $('#f-fav').setAttribute('aria-pressed', 'false');
  $('#f-rate').setAttribute('aria-pressed', 'false');
  renderGenres();
  renderVenues();
  render();
});

$('#btn-map').addEventListener('click', (e) => {
  S.mapOn = !S.mapOn;
  e.currentTarget.setAttribute('aria-pressed', String(S.mapOn));
  if (S.mapOn) { el.genrebox.hidden = true; el.venuebox.hidden = true; }
  render();
  if (S.mapOn) { const m = ensureMap(); setTimeout(() => m.invalidateSize(), 60); }
});

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

$('#btn-export').addEventListener('click', () => {
  const payload = {
    kind: 'rbf26-auswahl', version: 1,
    fav: [...fav], note, rate, hint,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'reeperbahn-auswahl.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
});

$('#btn-import').addEventListener('click', () => el.file.click());

el.file.addEventListener('change', async () => {
  const f = el.file.files && el.file.files[0];
  if (!f) return;
  let data;
  try { data = JSON.parse(await f.text()); }
  catch (e) { alert('Die Datei ist kein gültiges JSON.'); return; }
  el.file.value = '';

  if (data.kind === 'rbf26-auswahl') {
    (data.fav || []).forEach((id) => fav.add(+id));
    Object.assign(note, data.note || {});
    Object.assign(rate, data.rate || {});
    Object.assign(hint, data.hint || {});
    saveFav(); store.set('note', note); store.set('rate', rate); store.set('hint', hint);
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

/* Aus taste/suggestions.json ableiten, was in der App angezeigt wird. */
function buildHints(data) {
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

if ('serviceWorker' in navigator) {
  addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}

load();
