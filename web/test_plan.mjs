/* Prueft den Planungsalgorithmus gegen Handrechnungen - ohne Browser.
   Aufruf aus dem Projektverzeichnis:  node web/test_plan.mjs
   Wichtigster Fall: ein hoch bewerteter Act, der zwei andere blockiert.
   Ein Greedy-Verfahren greift dort nach der besseren Einzelnote und
   verliert die bessere Summe. */
globalThis.window = {};
const src = await import('node:fs').then(fs => fs.promises.readFile('web/plan.js','utf8'));
eval(src.replace("window.RBFPlan", "globalThis.RBFPlan"));
const { buildPlan, walkMinutes } = globalThis.RBFPlan;

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

console.log(fails ? `\nFEHLGESCHLAGEN: ${fails}` : '\nPLAN-ALGORITHMUS: ALLE PRUEFUNGEN BESTANDEN');
process.exit(fails ? 1 : 0);
