/* Prueft den Planungsalgorithmus gegen Handrechnungen - ohne Browser.
   Aufruf aus dem Projektverzeichnis:  node web/test_plan.mjs
   Wichtigster Fall: ein hoch bewerteter Act, der zwei andere blockiert.
   Ein Greedy-Verfahren greift dort nach der besseren Einzelnote und
   verliert die bessere Summe. */
globalThis.window = {};
const src = await import('node:fs').then(fs => fs.promises.readFile('web/plan.js','utf8'));
eval(src.replace("window.RBFPlan", "globalThis.RBFPlan"));
const { buildPlan, walkMinutes, clockInSourceZone } = globalThis.RBFPlan;

const A = { lat: 53.5500, lng: 9.9600, name: 'A' };
const B = { lat: 53.5505, lng: 9.9650, name: 'B' };   // ~340 m
const far = { lat: 53.5700, lng: 9.9900, name: 'Fern' };

let fails = 0;
const ok = (name, cond, extra='') => {
  console.log((cond ? '  OK   ' : '  FAIL ') + name + (extra ? '  ' + extra : ''));
  if (!cond) fails++;
};

ok('Fussweg A->B plausibel (3-8 min)',
   walkMinutes(A,B) >= 3 && walkMinutes(A,B) <= 8, `${walkMinutes(A,B)} min`);
ok('Gleicher Ort kostet 0', walkMinutes(A,A) === 0);
ok('Unbekannter Ort kostet 10', walkMinutes(A,null) === 10);

// Zwei Auftritte, die sich zeitlich ueberschneiden: nur der wertvollere zaehlt
let r = buildPlan([
  {id:'1', name:'Gut',    startIso:'2026-09-18T20:00:00+02:00', venue:A, value:5},
  {id:'2', name:'Mittel', startIso:'2026-09-18T20:10:00+02:00', venue:A, value:2},
]);
ok('Ueberschneidung: nur der wertvollere', r.stops.length===1 && r.stops[0].name==='Gut',
   r.stops.map(s=>s.name).join(','));
ok('Der andere steht als entfallen drin', r.dropped.length===1);

// Nacheinander am selben Ort: beide passen
r = buildPlan([
  {id:'1', name:'Erst',  startIso:'2026-09-18T20:00:00+02:00', venue:A, value:3},
  {id:'2', name:'Dann',  startIso:'2026-09-18T21:00:00+02:00', venue:A, value:3},
]);
ok('Zeitlich getrennt: beide im Plan', r.stops.length===2, r.stops.map(s=>s.name).join(','));

// Fussweg macht es unmoeglich: 40 min Set + Weg > Abstand
r = buildPlan([
  {id:'1', name:'Hier', startIso:'2026-09-18T20:00:00+02:00', venue:A, value:3},
  {id:'2', name:'Weit', startIso:'2026-09-18T20:45:00+02:00', venue:far, value:3},
]);
ok('Zu weit weg wird ausgeschlossen', r.stops.length===1, r.stops.map(s=>s.name).join(','));

// Der entscheidende Fall: EIN hoch bewerteter Act ueberschneidet sich mit
// ZWEI anderen, die untereinander passen. Ein Greedy-Verfahren nach Wert
// greift nach der 4 und verliert 3+3.
//   Block 20:00-20:40 (Wert 4)
//   Gut1  19:30-20:10 (Wert 3)  -> ueberschneidet Block
//   Gut2  20:20-21:00 (Wert 3)  -> ueberschneidet Block, passt nach Gut1
r = buildPlan([
  {id:'b', name:'Block', startIso:'2026-09-18T20:00:00+02:00', venue:A, value:4},
  {id:'g1',name:'Gut1',  startIso:'2026-09-18T19:30:00+02:00', venue:A, value:3},
  {id:'g2',name:'Gut2',  startIso:'2026-09-18T20:20:00+02:00', venue:A, value:3},
]);
ok('Optimum statt Greedy: 3+3 schlaegt 4',
   r.totalValue===6 && r.stops.map(s=>s.name).join(',')==='Gut1,Gut2',
   `Wert ${r.totalValue}: ${r.stops.map(s=>s.name).join(',')}`);

// Und die Gegenprobe: passt der wertvolle daneben, muss er auch rein.
r = buildPlan([
  {id:'b', name:'Block', startIso:'2026-09-18T20:00:00+02:00', venue:A, value:4},
  {id:'g2',name:'Gut2',  startIso:'2026-09-18T20:50:00+02:00', venue:A, value:3},
]);
ok('Vertraeglicher wertvoller Act bleibt drin',
   r.totalValue===7 && r.stops.length===2,
   `Wert ${r.totalValue}: ${r.stops.map(s=>s.name).join(',')}`);

// Wartezeit wird ausgewiesen
r = buildPlan([
  {id:'1', name:'Frueh', startIso:'2026-09-18T18:00:00+02:00', venue:A, value:1},
  {id:'2', name:'Spaet', startIso:'2026-09-18T22:00:00+02:00', venue:A, value:1},
]);
ok('Leerlauf wird ausgewiesen', r.stops[1].idleBefore > 180,
   `${r.stops[1].idleBefore} min`);
ok('Leere Eingabe faellt nicht um', buildPlan([]).stops.length===0);

// Zeitzone: die Quelle liefert +02:00. Ein Konzert um 23:15 plus 40 Minuten
// endet um 23:55 Hamburger Zeit - NICHT um 21:55. Genau dieser Fehler stand
// in der Zusammenfassung des Abendplans.
ok('Endzeit in der Zone der Quelle, nicht UTC',
   clockInSourceZone('2026-09-18T23:15:00+02:00', 40) === '23:55',
   clockInSourceZone('2026-09-18T23:15:00+02:00', 40));
ok('Ohne Zuschlag unveraendert',
   clockInSourceZone('2026-09-18T20:35:00+02:00') === '20:35',
   clockInSourceZone('2026-09-18T20:35:00+02:00'));
ok('Tageswechsel wird richtig gerechnet',
   clockInSourceZone('2026-09-18T23:50:00+02:00', 40) === '00:30',
   clockInSourceZone('2026-09-18T23:50:00+02:00', 40));
ok('Andere Zone wird respektiert',
   clockInSourceZone('2026-09-18T12:00:00-05:00', 30) === '12:30',
   clockInSourceZone('2026-09-18T12:00:00-05:00', 30));

// ---------- Ein Act, zwei Termine ----------
// 62 der 342 Acts spielen mehrfach. Beide Termine gehoeren in die Auswahl -
// aber zweimal derselbe Act waere verschwendeter Abend.
const V = { lat: 53.5503, lng: 9.9637, name: 'Haus' };
const zwei = [
  { id: 'd1', actId: 7, name: 'Doppel', startIso: '2026-09-16T20:00:00+02:00',
    venue: V, value: 5 },
  { id: 'd2', actId: 7, name: 'Doppel', startIso: '2026-09-16T22:00:00+02:00',
    venue: V, value: 5 },
  { id: 'e1', actId: 8, name: 'Einmal', startIso: '2026-09-16T21:00:00+02:00',
    venue: V, value: 4 },
];
const rz = buildPlan(zwei, { setMinutes: 40 });
ok('Derselbe Act steht nur einmal im Plan',
   new Set(rz.stops.map((s) => s.actId)).size === rz.stops.length,
   rz.stops.map((s) => s.name + ' ' + s.startIso.slice(11, 16)).join(', '));
ok('Bei gleichem Wert bleibt der fruehere Termin',
   rz.stops.some((s) => s.id === 'd1'),
   rz.stops.map((s) => s.id).join(','));
ok('Der andere Termin wird als Doppelung gemeldet',
   rz.dedupedActs.length === 1 && rz.dedupedActs[0].id === 'd2',
   JSON.stringify(rz.dedupedActs));
ok('Der andere Act bleibt trotzdem drin',
   rz.stops.some((s) => s.actId === 8),
   rz.stops.map((s) => s.actId).join(','));

// Der wertvollere Termin gewinnt, egal in welcher Reihenfolge er kommt.
const wert = [
  { id: 'f1', actId: 9, name: 'Wahl', startIso: '2026-09-16T20:00:00+02:00',
    venue: V, value: 2 },
  { id: 'f2', actId: 9, name: 'Wahl', startIso: '2026-09-16T22:00:00+02:00',
    venue: V, value: 6 },
];
const rw = buildPlan(wert, { setMinutes: 40 });
ok('Bei ungleichem Wert gewinnt der wertvollere Termin',
   rw.stops.length === 1 && rw.stops[0].id === 'f2',
   rw.stops.map((s) => s.id + ':' + s.value).join(','));

// Ohne Act-Kennung darf die Regel NICHT greifen - sonst faellt jeder
// Auftritt unter denselben "Act". Genau daran sind die Tests oben
// zerbrochen, als die Regel neu war.
const ohne = [
  { id: 'g1', name: 'A', startIso: '2026-09-16T20:00:00+02:00', venue: V, value: 3 },
  { id: 'g2', name: 'B', startIso: '2026-09-16T22:00:00+02:00', venue: V, value: 3 },
];
ok('Ohne Act-Kennung bleiben beide drin',
   buildPlan(ohne, { setMinutes: 40 }).stops.length === 2,
   buildPlan(ohne, { setMinutes: 40 }).stops.length);

console.log(fails ? `\nFEHLGESCHLAGEN: ${fails}` : '\nPLAN-ALGORITHMUS: ALLE PRUEFUNGEN BESTANDEN');
process.exit(fails ? 1 : 0);
