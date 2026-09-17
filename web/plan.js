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
  // Ersatz-Spielzeit: gilt NUR fuer Auftritte ohne Endzeit. Die Quelle
  // nennt sie inzwischen fuer 568 von 575 Auftritten (siehe
  // end_from_title in rbf_core.py) - gerechnet wird also mit der echten
  // Spielzeit, und dieser Wert ist der Rest.
  setMinutes: 40,
  bufferMinutes: 5,      // Luft fuers Reinkommen, Anstehen, Pinkeln
  overlapMinutes: 0,     // wie viele Minuten des laufenden Konzerts man opfert
  walkSpeed: 80,         // Meter pro Minute, entspanntes Gehen
  detour: 1.3,           // Strassen sind laenger als die Luftlinie
};

/**
 * Wie viel Zeit bleibt zwischen zwei Auftritten uebrig, nachdem der Fussweg
 * abgezogen ist? Negativ heisst: so viele Minuten des ERSTEN Konzerts fallen
 * weg, wenn man rechtzeitig beim zweiten sein will.
 */
function slackBetween(a, b, o) {
  return b.start - (a.end + walkMinutes(a.venue, b.venue, o));
}

/**
 * Ab wann gelten zwei Auftritte als vertraeglich?
 *
 * Ohne Ueberschneidungsbudget bleibt es bei der alten Regel: nach dem Ende
 * des ersten Konzerts muss der Fussweg PLUS die Luft passen.
 *
 * Mit Budget zaehlt nur noch, wie viele Minuten des laufenden Konzerts man
 * aufgibt - die Luft IST dann das, was man aufgibt, sie ein zweites Mal zu
 * verlangen waere doppelt gezaehlt. "10 min Ueberschneidung" heisst deshalb
 * genau das: hoechstens 10 Minuten des laufenden Konzerts verpassen. So
 * stimmt die Zahl im Kopf mit der Zahl in der Zeile ueberein.
 */
function minSlack(o) {
  return o.overlapMinutes > 0 ? -o.overlapMinutes : o.bufferMinutes;
}

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

/* Wann ist ein Auftritt zu Ende? Die echte Endzeit, sonst Start plus der
   eingestellten Ersatz-Spielzeit. Eine Endzeit VOR dem Start waere eine
   kaputte Angabe - dann lieber die Ersatzzeit als ein Konzert, das
   rueckwaerts laeuft. */
function endMinutes(s, start, o) {
  if (!s.endIso) return start + o.setMinutes;
  const e = minutesOf(s.endIso);
  return Number.isFinite(e) && e > start ? e : start + o.setMinutes;
}

function solvePlan(items, o) {
  const shows = items
    .filter((s) => s.startIso)
    .map((s) => {
      const start = minutesOf(s.startIso);
      return { ...s, start, end: endMinutes(s, start, o) };
    })
    .sort((a, b) => a.end - b.end || a.start - b.start);

  if (!shows.length) return { stops: [], dropped: [], totalValue: 0, walkTotal: 0 };

  const n = shows.length;

  /* Bester Abend, der MIT diesem Auftritt endet - und der Vorgaenger, ueber
     den er dorthin kam.

     Frueher stand hier die Lehrbuchfassung: bester Abend BIS zu diesem
     Auftritt, und dazu der letzte vertraegliche Vorgaenger, ab dem alles
     davor als erlaubt gilt. Das stimmt fuer reine Zeitintervalle - ist ein
     Vorgaenger vertraeglich, sind alle frueheren es erst recht.
     Hier stimmt es nicht: zwischen zwei Auftritten liegt ein FUSSWEG, und
     der haengt am Ort, nicht an der Uhrzeit. Ein frueherer Auftritt am
     anderen Ende der Stadt kann unvertraeglich sein, waehrend der spaetere
     nebenan passt. Der fruehere steckte dann im "besten Abend bis dorthin"
     und stand hinterher ungeprueft neben dem naechsten - gemessen 34
     Minuten Ueberschneidung bei 10 erlaubten, und 22 Minuten sogar bei
     abgeschaltetem Budget.

     Jetzt wird jeder Vorgaenger einzeln geprueft. Damit ist jedes Paar, das
     im Plan nebeneinander steht, auch wirklich geprueft worden. Das kostet
     n² statt n log n - bei hoechstens ein paar hundert Auftritten je Abend
     ist das nicht messbar, und richtig zu rechnen ist es wert. */
  const bestEnd = new Array(n).fill(0);
  const from = new Array(n).fill(-1);
  for (let i = 0; i < n; i++) {
    const cur = shows[i];
    let bestPrev = 0;
    let bestJ = -1;
    for (let j = i - 1; j >= 0; j--) {
      if (slackBetween(shows[j], cur, o) < minSlack(o)) continue;
      if (bestEnd[j] > bestPrev) { bestPrev = bestEnd[j]; bestJ = j; }
    }
    bestEnd[i] = cur.value + bestPrev;
    from[i] = bestJ;
  }

  // Wo endet der beste Abend? Bei Gleichstand der fruehere - er laesst mehr
  // Abend uebrig, dieselbe Regel wie beim Streichen doppelter Acts.
  let last = -1;
  let bestValue = 0;
  for (let i = 0; i < n; i++) {
    if (bestEnd[i] > bestValue) { bestValue = bestEnd[i]; last = i; }
  }

  // Rueckwaerts auflesen, welche Auftritte im Plan stehen.
  const picked = [];
  for (let i = last; i >= 0; i = from[i]) picked.push(shows[i]);
  picked.reverse();

  const chosen = new Set(picked.map((s) => s.id));
  const stops = picked.map((s, idx) => {
    const before = picked[idx - 1];
    const slack = before ? slackBetween(before, s, o) : 0;
    return {
      ...s,
      // Wie lange dieser Auftritt wirklich dauert - die Zeitleiste zeichnet
      // danach, und die Liste schreibt es hin.
      lengthMinutes: s.end - s.start,
      walkFromPrev: before ? walkMinutes(before.venue, s.venue, o) : 0,
      /* Wartezeit sichtbar machen: eine Stunde Leerlauf ist ein Hinweis, dass
         noch etwas dazwischen passt. */
      idleBefore: Math.max(0, slack),
      /* Und die Gegenrichtung: so viele Minuten des vorherigen Konzerts
         fallen weg. Beides kann nicht gleichzeitig groesser als 0 sein. */
      overlapBefore: Math.max(0, -slack),
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
    totalValue: bestValue,
    walkTotal: stops.reduce((sum, s) => sum + s.walkFromPrev, 0),
  };
}

/**
 * Wer spielt zur selben Zeit wie ein Auftritt?
 *
 * "Parallel" heisst hier: die beiden Spielfenster ueberlappen sich um
 * mindestens eine Minute. Bewusst NICHT "passt in den Plan" - wer kurz
 * vorbeischauen will, will erst einmal sehen, was ueberhaupt gleichzeitig
 * laeuft; ob es sich ausgeht, rechnet die Auswahl danach.
 *
 * Derselbe Act zaehlt nicht als Alternative zu sich selbst: 62 Acts spielen
 * mehrfach, und zwei Termine desselben Acts sind kein anderes Konzert.
 *
 * Sortiert nach Wert, bei Gleichstand nach Beginn - so steht beim
 * Durchtippen das Naheliegendste vorn.
 */
function parallelTo(items, ref, opt = {}) {
  const o = { ...PLAN_DEFAULTS, ...opt };
  const startOf = (s) => minutesOf(s.startIso);
  const refStart = ref.start != null ? ref.start : startOf(ref);
  const refEnd = ref.end != null ? ref.end : endMinutes(ref, refStart, o);
  return items
    .filter((s) => s.startIso && String(s.id) !== String(ref.id))
    .filter((s) => ref.actId == null || s.actId == null || s.actId !== ref.actId)
    .filter((s) => {
      const a = startOf(s);
      return a < refEnd && refStart < endMinutes(s, a, o);
    })
    .sort((a, b) => (b.value || 0) - (a.value || 0) || startOf(a) - startOf(b));
}

window.RBFPlan = { buildPlan, walkMinutes, metersBetween, clockInSourceZone,
                   parallelTo, slackBetween, minSlack, PLAN_DEFAULTS };
