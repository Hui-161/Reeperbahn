/* Archiv: was vom Festival bleibt.

   Reine Rechnung ohne DOM, wie plan.js - damit sich jede Zahl, die im Archiv
   steht, im Test ohne Browser nachrechnen laesst. Den Zustand reicht app.js
   herein:

     ctx = { data, seen, seenShow, rate, fav, note, commit, partner }

   seen und fav sind Mengen von Act-Kennungen (Zahlen), seenShow eine Menge
   von Auftritts-Kennungen (Zeichenketten), rate/note/commit Objekte mit der
   Act-Kennung als Schluessel. partner ist die zusammengefasste Sicht der
   anderen Seite oder null.
 */
'use strict';

/* Als Funktion gekapselt: klassische Skripte teilen sich den globalen
   Namensraum, und app.js kennt hhmm und WD schon. */
(() => {
/* Was man bereit ist, fuer den Act zu TUN - nicht, wie gut er war. Die Note
   sagt "sehr gut"; das hier sagt "dafuer stelle ich mich an die Abendkasse".
   Das sind zwei verschiedene Aussagen, und die zweite ist nach dem Festival
   die interessantere: sie entscheidet, wen man wiedersieht. */
const COMMITS = [
  { k: 'ak', label: 'Abendkasse', kurz: 'AK',
    hint: 'Dafür stelle ich mich spontan an die Abendkasse.' },
  { k: 'vvk', label: 'Vorverkauf', kurz: 'VVK',
    hint: 'Dafür kaufe ich vorher ein Ticket.' },
  { k: 'sp', label: 'Spotify folgen', kurz: '♫',
    hint: 'Dem Act bei Spotify folgen.' },
  { k: 'cute', label: 'Niedlichkeitsbonus', kurz: '♥',
    hint: 'Extrapunkte fürs Herz.' },
  { k: 'berlin', label: 'Konzert in Berlin', kurz: 'BER',
    hint: 'Ein eigenes Konzert in Berlin würde ich besuchen.' },
];
/* Bis zu welchem Ticketpreis man mitgehen wuerde - EINE Stufe, keine
   Mehrfachwahl: wer 30 zahlt, zahlt auch 15. */
const PRICES = [15, 20, 30, 50];
/* Ersatzwert fuer die sieben Auftritte ohne Endzeit - derselbe wie im
   Abendplan, damit dieselbe Frage nicht zwei Antworten hat. */
const FALLBACK_MIN = 30;
const WD = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];

const hhmm = (iso) => (iso ? String(iso).slice(11, 16) : '');
const wd = (d) => (d ? WD[new Date(d + 'T12:00:00').getDay()] : '');
const bucket = (r) => Math.floor(+r) || 0;
const rateText = (r) => (r ? String(r).replace('.', ',') : '');

/* Laenge eines Auftritts in Minuten; ohne Endzeit der Ersatzwert. Das
   zweite Ergebnis sagt, ob geschaetzt wurde - die Summe unten nennt dann,
   wie viele Auftritte darin nur geschaetzt sind. */
function showLen(sh) {
  if (sh && sh.t && sh.e) {
    const n = Math.round((new Date(sh.e) - new Date(sh.t)) / 60000);
    if (n > 0) return { min: n, geschaetzt: false };
  }
  return { min: FALLBACK_MIN, geschaetzt: true };
}

/* "5 h 30 min" - Stunden erst ab einer vollen. */
function fmtMin(n) {
  n = Math.max(0, Math.round(n || 0));
  const h = Math.floor(n / 60), m = n % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

/* Der Einsatz in einer Zahl, fuer die Rangfolge und die Tabelle: jedes
   Haekchen ein Punkt, die Preisstufe ein bis vier Punkte. Hoechstens neun.
   Bewusst ohne Gewichtung - wer meint, "Vorverkauf" zaehle doppelt, sieht
   die Haekchen ja daneben und kann selbst gewichten. */
function einsatz(c) {
  if (!c) return 0;
  let n = 0;
  for (const { k } of COMMITS) if (c[k]) n += 1;
  const p = PRICES.indexOf(+c.price);
  if (p >= 0) n += p + 1;
  return n;
}

/* Leere Eintraege loeschen, damit "nachbewertet" nur die zaehlt, die
   wirklich etwas gesagt haben. Gibt den bereinigten Eintrag oder null. */
function cleanCommit(c) {
  if (!c) return null;
  const out = {};
  for (const { k } of COMMITS) if (c[k]) out[k] = true;
  if (PRICES.includes(+c.price)) out.price = +c.price;
  return Object.keys(out).length ? out : null;
}

/* "Gesehen" gilt fuer das ganze Team: wer zusammen hingeht, hakt einmal ab,
   und mal tippt die eine, mal der andere. Fuer die Rechnung zaehlt deshalb
   die VEREINIGUNG aus eigenen Haken und denen der Gegenseite (seenAll,
   seenShowAll) - genau wie die Liste es seit jeher mit seenShowAny haelt.
   Die eigenen Mengen bleiben daneben getrennt stehen: die Sicherung darf
   nur schreiben, was man selbst gesagt hat, sonst kaeme ein von der
   Gegenseite zurueckgenommener Haken beim Wiedereinlesen zurueck. */
function norm(ctx) {
  const toSet = (v) => (v instanceof Set ? v : new Set(v || []));
  const p = ctx.partner || null;
  const seen = toSet(ctx.seen);
  const seenShow = new Set([...toSet(ctx.seenShow)].map(String));
  const pSeen = new Set(p ? (p.seen || []) : []);
  const pShow = new Set(p ? (p.seenShow || []).map(String) : []);
  return {
    data: ctx.data,
    seen, seenShow, pSeen, pShow,
    seenAll: new Set([...seen, ...pSeen]),
    seenShowAll: new Set([...seenShow, ...pShow]),
    rate: ctx.rate || {},
    fav: toSet(ctx.fav),
    note: ctx.note || {},
    commit: ctx.commit || {},
    partner: p,
  };
}

/* Wer hat abgehakt - fuer die Tabelle und den Bericht. */
function wer(c, sh) {
  const ich = c.seenShow.has(String(sh.id)), du = c.pShow.has(String(sh.id));
  return ich && du ? 'beide' : ich ? 'ich' : du ? (c.partner && c.partner.name) || 'Partner:in' : '';
}

/* Die gesehenen Acts mit ihren abgehakten Auftritten. Ein Act zaehlt als
   gesehen, wenn er in seen steht ODER ein Auftritt abgehakt ist - das
   zweite impliziert das erste, aber eine eingelesene Datei muss nicht
   sauber sein. Auftritte chronologisch. */
function seenActs(c) {
  const byAct = new Map();
  for (const sh of c.data.shows) {
    if (!c.seenShowAll.has(String(sh.id))) continue;
    if (!byAct.has(sh.a)) byAct.set(sh.a, []);
    byAct.get(sh.a).push(sh);
  }
  const out = [];
  c.data.acts.forEach((act, ai) => {
    const shows = (byAct.get(ai) || [])
      .sort((x, y) => String(x.t || '').localeCompare(String(y.t || '')));
    if (!shows.length && !c.seenAll.has(act.id)) return;
    const commit = cleanCommit(c.commit[act.id]);
    out.push({
      ai, act, shows, times: shows.length,
      rate: c.rate[act.id] ? +c.rate[act.id] : 0,
      bucket: bucket(c.rate[act.id]),
      fav: c.fav.has(act.id),
      note: String(c.note[act.id] || ''),
      commit, einsatz: einsatz(commit),
    });
  });
  return out;
}

/* Rangfolge der Acts: erst die Note (1 ist besser, unbewertet nach hinten),
   dann der Einsatz, dann wie oft gesehen, dann Favorit, dann der Name.
   Die Note zuerst, weil sie die Frage "wie war es" beantwortet; der Einsatz
   trennt dann die vielen Einsen voneinander. */
function rankActs(ctx) {
  const c = norm(ctx);
  return seenActs(c).sort((x, y) =>
    ((x.rate || 6) - (y.rate || 6)) || (y.einsatz - x.einsatz)
    || (y.times - x.times) || ((y.fav ? 1 : 0) - (x.fav ? 1 : 0))
    || x.act.n.localeCompare(y.act.n, 'de'));
}

/* Spielorte nach besuchten Konzerten; bei Gleichstand gewinnt die bessere
   Durchschnittsnote der dort gesehenen Acts. Der Durchschnitt zaehlt nur
   bewertete Acts - ein unbewerteter Act ist keine 3. */
function rankVenues(ctx) {
  const c = norm(ctx);
  const per = new Map();
  for (const sh of c.data.shows) {
    if (!c.seenShowAll.has(String(sh.id)) || sh.v == null) continue;
    if (!per.has(sh.v)) {
      per.set(sh.v, { vi: sh.v, venue: c.data.venues[sh.v], konzerte: 0,
                      acts: new Set(), minuten: 0, noten: [] });
    }
    const e = per.get(sh.v);
    e.konzerte += 1;
    e.acts.add(sh.a);
    e.minuten += showLen(sh).min;
    const r = +c.rate[c.data.acts[sh.a].id];
    if (r) e.noten.push(r);
  }
  return [...per.values()].map((e) => ({
    ...e, acts: e.acts.size,
    avg: e.noten.length
      ? Math.round(e.noten.reduce((s, r) => s + r, 0) / e.noten.length * 10) / 10
      : null,
  })).sort((x, y) => (y.konzerte - x.konzerte)
    || ((x.avg || 6) - (y.avg || 6)) || x.venue.n.localeCompare(y.venue.n, 'de'));
}

function count(map, key) { map.set(key, (map.get(key) || 0) + 1); }
const sortedCounts = (map, nameOf = (k) => k) => [...map.entries()]
  .map(([k, n]) => ({ key: k, name: nameOf(k), n }))
  .sort((a, b) => (b.n - a.n) || String(a.name).localeCompare(String(b.name), 'de'));

function stats(ctx) {
  const c = norm(ctx);
  const acts = seenActs(c);
  const konzerte = acts.reduce((s, a) => s + a.times, 0);
  let minuten = 0, geschaetzt = 0;
  const tage = new Map();
  const orte = new Set();
  for (const a of acts) {
    for (const sh of a.shows) {
      const l = showLen(sh);
      minuten += l.min;
      if (l.geschaetzt) geschaetzt += 1;
      if (sh.v != null) orte.add(sh.v);
      const d = sh.d || String(sh.t || '').slice(0, 10);
      if (!tage.has(d)) tage.set(d, { d, wd: wd(d), konzerte: 0, minuten: 0, acts: new Set() });
      const t = tage.get(d);
      t.konzerte += 1; t.minuten += l.min; t.acts.add(a.ai);
    }
  }
  const genres = new Map(), laender = new Map();
  const noten = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  const ein = { price: {} };
  for (const { k } of COMMITS) ein[k] = 0;
  for (const p of PRICES) ein.price[p] = 0;
  for (const a of acts) {
    if (a.act.g && a.act.g.length) for (const g of a.act.g) count(genres, g);
    else count(genres, -1);
    count(laender, a.act.c || '—');
    noten[a.bucket] += 1;
    if (a.commit) {
      for (const { k } of COMMITS) if (a.commit[k]) ein[k] += 1;
      if (a.commit.price) ein.price[a.commit.price] += 1;
    }
  }
  const favGesehen = acts.filter((a) => a.fav);
  const favVerpasst = [];
  c.data.acts.forEach((act, ai) => {
    if (c.fav.has(act.id) && !acts.some((a) => a.ai === ai)) favVerpasst.push({ ai, name: act.n });
  });
  /* Wer hat die Haken gesetzt? Gezaehlt wird ueber die KONZERTE, weil dort
     abgehakt wird. Es ist eine Randnotiz - gesehen habt ihr sie beide. */
  let team = null;
  if (c.partner) {
    let ich = 0, du = 0, beide = 0;
    for (const a of acts) {
      for (const sh of a.shows) {
        const w = wer(c, sh);
        if (w === 'beide') beide += 1; else if (w === 'ich') ich += 1; else if (w) du += 1;
      }
    }
    team = { name: c.partner.name || 'Partner:in', ich, du, beide };
  }
  return {
    konzerte, acts: acts.length,
    mehrfach: acts.filter((a) => a.times > 1)
      .map((a) => ({ ai: a.ai, name: a.act.n, times: a.times }))
      .sort((x, y) => (y.times - x.times) || x.name.localeCompare(y.name, 'de')),
    spielorte: orte.size,
    minuten, minutenText: fmtMin(minuten), geschaetzt,
    bewertet: acts.filter((a) => a.rate).length,
    favoriten: c.fav.size,
    favGesehen: favGesehen.length,
    favVerpasst: favVerpasst.sort((x, y) => x.name.localeCompare(y.name, 'de')),
    /* Gesehen, ohne vorher Favorit gewesen zu sein, und dann mit 1 oder 2
       benotet - das sind die Acts, die man ohne das Festival nie gehoert
       haette. Die eigentliche Ausbeute eines Showcase-Festivals. */
    entdeckungen: acts.filter((a) => !a.fav && a.bucket && a.bucket <= 2)
      .map((a) => ({ ai: a.ai, name: a.act.n, rate: a.rate }))
      .sort((x, y) => (x.rate - y.rate) || x.name.localeCompare(y.name, 'de')),
    notizen: acts.filter((a) => a.note.trim()).length,
    nachbewertet: acts.filter((a) => a.commit).length,
    tage: [...tage.values()].sort((x, y) => x.d.localeCompare(y.d))
      .map((t) => ({ ...t, acts: t.acts.size, minutenText: fmtMin(t.minuten) })),
    genres: sortedCounts(genres, (g) => (g < 0 ? 'ohne Angabe' : c.data.genres[g])),
    laender: sortedCounts(laender),
    noten,
    einsatz: ein,
    team,
  };
}

/* ---------- Tabellen fuer die Excel-Datei ----------
   Eine Zeile je Zeile, erste Zeile die Ueberschrift. Zahlen bleiben Zahlen,
   damit man in Excel damit rechnen kann; Ja/Nein als Text, weil ein
   WAHR/FALSCH in der deutschen Excel-Fassung mehr verwirrt als hilft. */
const jn = (b) => (b ? 'ja' : '');
const genresOf = (c, act) => (act.g || []).map((i) => c.data.genres[i]).join(', ');
const venueName = (c, sh) => (sh.v != null ? c.data.venues[sh.v].n : '');

function sheets(ctx) {
  const c = norm(ctx);
  const st = stats(c);
  const acts = rankActs(c);
  const byAi = new Map(acts.map((a) => [a.ai, a]));

  const konzerte = [['Tag', 'Datum', 'Beginn', 'Ende', 'Minuten', 'Act', 'Land',
                     'Genres', 'Spielort', 'Note', 'Wie oft gesehen', 'Abgehakt von', 'Notiz']];
  const alle = c.data.shows.filter((sh) => c.seenShowAll.has(String(sh.id)))
    .sort((x, y) => String(x.t || '').localeCompare(String(y.t || '')));
  for (const sh of alle) {
    const a = byAi.get(sh.a);
    konzerte.push([wd(sh.d), sh.d || '', sh.tbd ? '' : hhmm(sh.t),
                   sh.e ? hhmm(sh.e) : '', showLen(sh).min, a.act.n, a.act.c || '',
                   genresOf(c, a.act), venueName(c, sh), a.rate || '', a.times,
                   wer(c, sh), a.note.replace(/\s+/g, ' ')]);
  }

  const actRows = [['Rang', 'Act', 'Land', 'Genres', 'Note', 'Favorit', 'Wie oft gesehen',
                    'Gesehen wo', ...COMMITS.map((x) => x.label), 'Ticket bis (€)',
                    'Einsatz (Punkte)', 'Notiz', 'Spotify']];
  acts.forEach((a, i) => {
    actRows.push([i + 1, a.act.n, a.act.c || '', genresOf(c, a.act), a.rate || '',
                  jn(a.fav), a.times,
                  a.shows.map((sh) => `${wd(sh.d)} ${hhmm(sh.t)} ${venueName(c, sh)}`.trim()).join('; '),
                  ...COMMITS.map((x) => jn(a.commit && a.commit[x.k])),
                  (a.commit && a.commit.price) || '', a.einsatz,
                  a.note.replace(/\s+/g, ' '), a.act.sp || '']);
  });

  const orte = [['Rang', 'Spielort', 'Konzerte gesehen', 'Acts', 'Minuten', 'Ø Note',
                 'Kapazität', 'Adresse']];
  rankVenues(c).forEach((v, i) => {
    orte.push([i + 1, v.venue.n, v.konzerte, v.acts, v.minuten, v.avg == null ? '' : v.avg,
               v.venue.cap || '', v.venue.addr || '']);
  });

  const zahlen = [['Kennzahl', 'Wert'],
    ['Konzerte besucht', st.konzerte], ['Acts gesehen', st.acts],
    ['davon mehrfach', st.mehrfach.length], ['Spielorte besucht', st.spielorte],
    ['Minuten Musik', st.minuten], ['davon geschätzt (ohne Endzeit)', st.geschaetzt],
    ['Acts bewertet', st.bewertet], ['Favoriten', st.favoriten],
    ['Favoriten gesehen', st.favGesehen], ['Favoriten verpasst', st.favVerpasst.length],
    ['Entdeckungen (Note 1–2, kein Favorit)', st.entdeckungen.length],
    ['Notizen', st.notizen], ['Nachbewertet', st.nachbewertet]];
  for (const t of st.tage) zahlen.push([`Konzerte am ${t.wd} ${t.d}`, t.konzerte]);
  for (const g of st.genres) zahlen.push([`Genre: ${g.name}`, g.n]);
  for (const l of st.laender) zahlen.push([`Land: ${l.name}`, l.n]);
  for (const b of [1, 2, 3, 4, 5]) zahlen.push([`Note ${b}`, st.noten[b]]);
  zahlen.push(['Unbewertet', st.noten[0]]);
  for (const x of COMMITS) zahlen.push([x.label, st.einsatz[x.k]]);
  for (const p of PRICES) zahlen.push([`Ticket bis ${p} €`, st.einsatz.price[p]]);
  if (st.team) {
    zahlen.push(['Abgehakt von mir', st.team.ich], [`Abgehakt von ${st.team.name}`, st.team.du],
                ['Abgehakt von beiden', st.team.beide]);
  }

  /* Das ganze Programm mit den eigenen Marken - falls man spaeter wissen
     will, wer noch spielte, waehrend man woanders stand. */
  const lineup = [['Tag', 'Datum', 'Beginn', 'Ende', 'Act', 'Land', 'Genres', 'Spielort',
                   'Note', 'Favorit', 'Gesehen']];
  for (const sh of c.data.shows) {
    const act = c.data.acts[sh.a];
    lineup.push([wd(sh.d), sh.d || '', sh.tbd ? '' : hhmm(sh.t), sh.e ? hhmm(sh.e) : '',
                 act.n, act.c || '', genresOf(c, act), venueName(c, sh),
                 c.rate[act.id] ? +c.rate[act.id] : '', jn(c.fav.has(act.id)),
                 jn(c.seenShowAll.has(String(sh.id)))]);
  }

  const out = [
    { name: 'Konzerte gesehen', rows: konzerte },
    { name: 'Acts', rows: actRows },
    { name: 'Spielorte', rows: orte },
    { name: 'Statistik', rows: zahlen },
    { name: 'Line-up komplett', rows: lineup },
  ];
  if (c.partner) {
    const pRate = c.partner.rate || {};
    const pFav = new Set(c.partner.fav || []);
    const team = [['Act', 'Meine Note', `Note ${st.team.name}`, 'Mein Favorit',
                   `Favorit ${st.team.name}`, 'Gesehen']];
    c.data.acts.forEach((act, ai) => {
      const gesehen = byAi.has(ai);
      if (!gesehen && !pRate[act.id] && !pFav.has(act.id) && !c.rate[act.id] && !c.fav.has(act.id)) return;
      team.push([act.n, c.rate[act.id] ? +c.rate[act.id] : '', pRate[act.id] ? +pRate[act.id] : '',
                 jn(c.fav.has(act.id)), jn(pFav.has(act.id)), jn(gesehen)]);
    });
    out.push({ name: 'Team', rows: team });
  }
  return out;
}

/* Die Archivdatei: das Programm, wie es am Ende stand, plus alles Eigene.
   Die Passphrase des Teams fehlt aus demselben Grund wie in der Sicherung
   (siehe exportChoice in app.js): sie gehoert in keine Datei. */
function archiveDoc(ctx, extra) {
  const c = norm(ctx);
  return {
    kind: 'rbf26-archiv', version: 1,
    exported: new Date().toISOString(),
    festival: { jahr: 2026, tage: c.data.days, stand: c.data.generated_at },
    stats: stats(c),
    topActs: rankActs(c).map((a, i) => ({
      rang: i + 1, id: a.act.id, name: a.act.n, note: a.rate || null, gesehen: a.times,
      einsatz: a.einsatz, commit: a.commit,
      auftritte: a.shows.map((sh) => ({ id: sh.id, tag: sh.d, beginn: hhmm(sh.t),
                                        ende: hhmm(sh.e), spielort: venueName(c, sh) })),
    })),
    topSpielorte: rankVenues(c).map((v, i) => ({
      rang: i + 1, name: v.venue.n, konzerte: v.konzerte, acts: v.acts, minuten: v.minuten,
      note: v.avg })),
    mine: {
      fav: [...c.fav], seen: [...c.seen], seenShow: [...c.seenShow],
      rate: c.rate, note: c.note, commit: c.commit, ...(extra || {}),
    },
    partner: c.partner,
    lineup: { genres: c.data.genres, venues: c.data.venues, acts: c.data.acts,
              shows: c.data.shows },
  };
}

window.RBFArchive = { COMMITS, PRICES, FALLBACK_MIN, einsatz, cleanCommit, fmtMin,
                      stats, rankActs, rankVenues, sheets, archiveDoc, showLen,
                      rateText, wd, hhmm,
                      /* von aussen mit dem rohen Zustand aufgerufen (app.js, Tests) */
                      wer: (ctx, sh) => wer(norm(ctx), sh) };
})();
