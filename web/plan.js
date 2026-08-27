/* Abendplanung: aus bewerteten Acts eine machbare Reihenfolge bauen.
 *
 * Das ist "weighted interval scheduling with travel times" und exakt loesbar,
 * nicht nur naeherungsweise: Auftritte nach Endzeit sortieren, dann per
 * dynamischer Programmierung den wertvollsten konfliktfreien Pfad waehlen.
 * Zwei Auftritte sind vertraeglich, wenn nach dem Ende des ersten noch der
 * Fussweg zum zweiten passt.
 *
 * Bewusst KEIN Greedy-Verfahren ("immer den naechstbesten nehmen"): das
 * verpasst regelmaessig bessere Kombinationen, etwa wenn ein mittelmaessiger
 * Act zwei sehr gute blockiert.
 *
 * Reine Funktionen, keine DOM-Beruehrung - damit pruefbar.
 */
'use strict';

const PLAN_DEFAULTS = {
  setMinutes: 40,        // Spielzeit eines Slots; die Quelle nennt keine Endzeit
  bufferMinutes: 5,      // Luft fuers Reinkommen, Anstehen, Pinkeln
  walkSpeed: 80,         // Meter pro Minute, entspanntes Gehen
  detour: 1.3,           // Strassen sind laenger als die Luftlinie
};

/** Luftlinie in Metern (Haversine). */
function metersBetween(a, b) {
  if (!a || !b || a.lat == null || b.lat == null) return null;
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const s = Math.sin(dLat / 2) ** 2
    + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

/** Fussweg in Minuten, aufgerundet. Unbekannte Orte kosten 10 Minuten -
    lieber vorsichtig planen als einen Weg unterschlagen. */
function walkMinutes(a, b, opt = PLAN_DEFAULTS) {
  if (a === b) return 0;
  const m = metersBetween(a, b);
  if (m === null) return 10;
  return Math.ceil((m * opt.detour) / opt.walkSpeed);
}

/** HH:MM in der Zeitzone der Quelle (die ISO-Angaben tragen +02:00).
    Ueber new Date().getHours() ginge die Zeitzone des Geraets ein, ueber
    getUTCHours() die von UTC - beides waere in Hamburg um zwei Stunden
    daneben. Genau dieser Fehler stand in der Zusammenfassung des Abendplans. */
function clockInSourceZone(iso, addMinutes = 0) {
  const m = String(iso).match(/([+-])(\d\d):?(\d\d)$/);
  const offset = m
    ? (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3]))
    : 0;
  const t = new Date(iso).getTime() + (addMinutes + offset) * 60000;
  const d = new Date(t);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

const minutesOf = (iso) => {
  const d = new Date(iso);
  return Math.round(d.getTime() / 60000);
};

/**
 * @param {Array} items  [{id, actId, name, startIso, venue:{lat,lng,name}, value}]
 * @returns {{stops:Array, dropped:Array, totalValue:number, walkTotal:number,
 *            dedupedActs:Array}}
 *
 * 62 der 342 Acts spielen mehrfach (60 zweimal, 2 dreimal). Beide Termine
 * gehoeren in die Auswahl - welcher besser passt, entscheidet erst die
 * Rechnung. Zweimal DENSELBEN Act einzuplanen ist aber verschwendeter Abend.
 *
 * "Hoechstens einer je Act" laesst sich nicht in dieselbe Rechnung packen:
 * gewichtete Intervallauswahl MIT Gruppenbeschraenkung ist NP-schwer. Also
 * wird geloest, ein doppelter Act erkannt, der schlechtere Termin gestrichen
 * und neu geloest. Das ist ein Verfahren, kein Beweis - aber es rechnet nach
 * jedem Streichen den ganzen Abend neu, und die Faelle sind selten.
 */
function buildPlan(items, opt = {}) {
  const o = { ...PLAN_DEFAULTS, ...opt };
  if (o.oneShowPerAct === false) return solvePlan(items, o);
  let pool = items;
  const deduped = [];
  for (let round = 0; round < 12; round++) {
    const res = solvePlan(pool, o);
    const seen = new Map();
    let drop = null;
    for (const s of res.stops) {
      // Ohne Act-Kennung gibt es keine Doppelung zu erkennen. Das ist nicht
      // theoretisch: die Tests hier arbeiten mit Auftritten ohne actId, und
      // ohne diese Zeile galten sie alle als derselbe Act.
      if (s.actId === undefined || s.actId === null) continue;
      const prev = seen.get(s.actId);
      if (prev) {
        /* Bei gleichem Wert - und das ist der Normalfall, beide Termine haben
           dieselbe Note - den SPAETEREN streichen. Der fruehere laesst mehr
           Abend uebrig. */
        drop = (s.value < prev.value) ? s
             : (s.value > prev.value) ? prev
             : (s.start >= prev.start ? s : prev);
        break;
      }
      seen.set(s.actId, s);
    }
    if (!drop) { res.dedupedActs = deduped; return res; }
    deduped.push({ id: drop.id, name: drop.name, startIso: drop.startIso });
    pool = pool.filter((x) => x.id !== drop.id);
  }
  const res = solvePlan(pool, o);
  res.dedupedActs = deduped;
  return res;
}

function solvePlan(items, o) {
  const shows = items
    .filter((s) => s.startIso)
    .map((s) => {
      const start = minutesOf(s.startIso);
      return { ...s, start, end: start + o.setMinutes };
    })
    .sort((a, b) => a.end - b.end || a.start - b.start);

  if (!shows.length) return { stops: [], dropped: [], totalValue: 0, walkTotal: 0 };

  const n = shows.length;
  const best = new Array(n + 1).fill(0);
  const choice = new Array(n + 1).fill(null);   // {take:boolean, prev:index}

  for (let i = 1; i <= n; i++) {
    const cur = shows[i - 1];
    // (a) diesen Auftritt weglassen
    let bestValue = best[i - 1];
    let bestChoice = { take: false, prev: i - 1 };

    // (b) diesen Auftritt nehmen: letzten vertraeglichen Vorgaenger suchen
    let prev = 0;
    for (let j = i - 1; j >= 1; j--) {
      const cand = shows[j - 1];
      if (cand.end + walkMinutes(cand.venue, cur.venue, o) + o.bufferMinutes <= cur.start) {
        prev = j;
        break;
      }
    }
    const withCur = cur.value + best[prev];
    if (withCur > bestValue) {
      bestValue = withCur;
      bestChoice = { take: true, prev };
    }
    best[i] = bestValue;
    choice[i] = bestChoice;
  }

  // Rueckwaerts auflesen, welche Auftritte im Plan stehen.
  const picked = [];
  let i = n;
  while (i > 0) {
    const c = choice[i];
    if (c.take) picked.push(shows[i - 1]);
    i = c.prev;
  }
  picked.reverse();

  const chosen = new Set(picked.map((s) => s.id));
  const stops = picked.map((s, idx) => {
    const before = picked[idx - 1];
    return {
      ...s,
      walkFromPrev: before ? walkMinutes(before.venue, s.venue, o) : 0,
      /* Wartezeit sichtbar machen: eine Stunde Leerlauf ist ein Hinweis, dass
         noch etwas dazwischen passt. */
      idleBefore: before
        ? s.start - (before.end + walkMinutes(before.venue, s.venue, o))
        : 0,
    };
  });

  // Was rausfiel, und woran es lag - eine Liste ohne Begruendung hilft nicht.
  const dropped = shows.filter((s) => !chosen.has(s.id)).map((s) => {
    const clash = picked.find((p) => {
      const gap = Math.min(
        Math.abs(p.start - s.start),
        Math.abs(p.end - s.end),
      );
      const overlap = s.start < p.end && p.start < s.end;
      return overlap || gap < walkMinutes(p.venue, s.venue, o);
    });
    return { ...s, clashesWith: clash ? clash.name : null };
  });

  return {
    stops,
    dropped,
    totalValue: best[n],
    walkTotal: stops.reduce((sum, s) => sum + s.walkFromPrev, 0),
  };
}

window.RBFPlan = { buildPlan, walkMinutes, metersBetween, clockInSourceZone,
                   PLAN_DEFAULTS };
