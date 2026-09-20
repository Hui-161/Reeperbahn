/* Prueft Archiv-Rechnung und Excel-Schreiber gegen Handrechnungen - ohne
   Browser. Aufruf aus dem Projektverzeichnis:  node web/test_archive.mjs
   Die Excel-Datei wird dazu nach $RBF_XLSX_OUT geschrieben (Vorgabe:
   /tmp/rbf-test.xlsx), damit ein Python-Schritt sie mit zipfile und
   openpyxl gegenlesen kann - der Schreiber soll nicht nur sich selbst
   glauben. */
import fs from 'node:fs';
globalThis.window = {};
for (const f of ['web/archive.js', 'web/xlsx.js']) {
  eval(fs.readFileSync(f, 'utf8').replace(/window\.(RBF\w+)/g, 'globalThis.$1'));
}
const A = globalThis.RBFArchive, X = globalThis.RBFXlsx;

let fails = 0;
const ok = (name, cond, extra = '') => {
  console.log((cond ? '  OK   ' : '  FAIL ') + name + (extra ? '  ' + extra : ''));
  if (!cond) fails++;
};

/* Ein kleines Festival: vier Acts, zwei Spielorte, zwei Tage. */
const data = {
  generated_at: '2026-09-18T09:55:56+00:00',
  days: ['2026-09-17', '2026-09-18'],
  genres: ['Indie', 'Pop', 'Punk'],
  venues: [{ n: 'Molotow', cap: 300, addr: 'Nobistor 14' },
           { n: 'Docks', cap: 1500, addr: 'Spielbudenplatz 19' }],
  acts: [
    { id: 101, n: 'Alpha', c: 'DE', g: [0], sp: 'https://open.spotify.com/artist/a' },
    { id: 102, n: 'Beta', c: 'UK', g: [1, 2] },
    { id: 103, n: 'Gamma', c: 'DE', g: [] },
    { id: 104, n: 'Delta', c: 'DK', g: [0] },
  ],
  shows: [
    { id: '1', a: 0, d: '2026-09-17', t: '2026-09-17T20:00:00+02:00', e: '2026-09-17T20:45:00+02:00', v: 0 },
    { id: '2', a: 0, d: '2026-09-18', t: '2026-09-18T22:00:00+02:00', e: '2026-09-18T22:30:00+02:00', v: 1 },
    { id: '3', a: 1, d: '2026-09-17', t: '2026-09-17T21:00:00+02:00', e: null, v: 0 },
    { id: '4', a: 2, d: '2026-09-18', t: '2026-09-18T23:00:00+02:00', e: '2026-09-19T00:00:00+02:00', v: 1 },
    { id: '5', a: 3, d: '2026-09-18', t: '2026-09-18T19:00:00+02:00', e: '2026-09-18T19:30:00+02:00', v: 0 },
  ],
};
/* Gesehen gilt fuer beide: L hat Auftritt 4 (Gamma im Docks) abgehakt, ich
   nicht - er zaehlt trotzdem, siehe norm(). */
const ctx = {
  data,
  seen: new Set([101, 102, 103]),           // Delta nur Favorit, nie gesehen
  seenShow: new Set(['1', '2', '3']),       // Alpha zweimal, Beta einmal, Gamma nur ueber L
  rate: { 101: 1, 102: 2.5, 104: 1 },
  fav: new Set([101, 104]),
  note: { 102: 'laut  und  gut' },
  commit: { 102: { ak: true, vvk: true, price: 30 }, 103: { sp: false }, 101: { berlin: true } },
  partner: { name: 'L', seen: [102], seenShow: ['4'], rate: { 101: 2 }, fav: [] },
};

const st = A.stats(ctx);
ok('Drei Acts gesehen', st.acts === 3, String(st.acts));
ok('Vier Konzerte abgehakt - Ls Haken an Auftritt 4 zaehlt mit', st.konzerte === 4, String(st.konzerte));
ok('Alpha ist der Mehrfache', st.mehrfach.length === 1 && st.mehrfach[0].name === 'Alpha'
   && st.mehrfach[0].times === 2);
ok('Zwei Spielorte', st.spielorte === 2);
ok('Minuten: 45 + 30 + 30 (Ersatz) + 60', st.minuten === 165 && st.geschaetzt === 1,
   `${st.minuten}, geschaetzt ${st.geschaetzt}`);
ok('Formatiert als 2 h 45 min', st.minutenText === '2 h 45 min', st.minutenText);
ok('fmtMin: 59 -> "59 min", 120 -> "2 h"', A.fmtMin(59) === '59 min' && A.fmtMin(120) === '2 h');
ok('Bewertet: Alpha und Beta', st.bewertet === 2);
ok('Favoriten: 2, davon 1 gesehen, Delta verpasst',
   st.favoriten === 2 && st.favGesehen === 1 && st.favVerpasst.length === 1
   && st.favVerpasst[0].name === 'Delta');
ok('Entdeckung: Beta (2,5 -> Eimer 2, kein Favorit)',
   st.entdeckungen.length === 1 && st.entdeckungen[0].name === 'Beta');
ok('Eine Notiz', st.notizen === 1);
ok('Nachbewertet: Alpha und Beta - Gammas leerer Eintrag zaehlt nicht',
   st.nachbewertet === 2, String(st.nachbewertet));
ok('Tage: Do 2 Konzerte, Fr 2', st.tage.length === 2 && st.tage[0].wd === 'Do'
   && st.tage[0].konzerte === 2 && st.tage[1].konzerte === 2,
   JSON.stringify(st.tage.map((t) => [t.wd, t.konzerte])));
ok('Genres: Indie 1, Pop 1, Punk 1, ohne Angabe 1',
   st.genres.length === 4 && st.genres.every((g) => g.n === 1)
   && st.genres.some((g) => g.name === 'ohne Angabe'));
ok('Laender: DE 2, UK 1', st.laender[0].name === 'DE' && st.laender[0].n === 2
   && st.laender[1].n === 1);
ok('Noten: eine 1, eine 2 (2,5 im Eimer 2), eine unbewertet',
   st.noten[1] === 1 && st.noten[2] === 1 && st.noten[0] === 1);
ok('Einsatz gezaehlt: AK 1, VVK 1, Berlin 1, 30 EUR 1',
   st.einsatz.ak === 1 && st.einsatz.vvk === 1 && st.einsatz.berlin === 1
   && st.einsatz.price[30] === 1 && st.einsatz.sp === 0);
ok('Team: abgehakt habe ich 3, L 1, beide 0',
   st.team && st.team.ich === 3 && st.team.du === 1 && st.team.beide === 0, JSON.stringify(st.team));
ok('wer(): Auftritt 4 kommt von L, Auftritt 1 von mir',
   A.wer({ ...ctx, partner: ctx.partner }, data.shows[3]) === 'L'
   && A.wer(ctx, data.shows[0]) === 'ich' && A.wer(ctx, data.shows[4]) === '');
/* Ohne Partner zaehlt nur das Eigene - dann bleibt es bei drei. */
ok('Ohne Partner: drei Konzerte', A.stats({ ...ctx, partner: null }).konzerte === 3);

const rank = A.rankActs(ctx);
ok('Rang: Alpha (1), Beta (2,5), Gamma (ohne Note)',
   rank.map((a) => a.act.n).join(',') === 'Alpha,Beta,Gamma', rank.map((a) => a.act.n).join(','));
ok('Einsatz Beta = 2 Haken + Stufe 3 = 5', rank[1].einsatz === 5, String(rank[1].einsatz));
ok('Einsatz Alpha = 1', rank[0].einsatz === 1);
ok('Gamma: leerer Eintrag wird null', rank[2].commit === null && rank[2].einsatz === 0);
ok('einsatz() Hoechstwert 9', A.einsatz({ ak: 1, vvk: 1, sp: 1, cute: 1, berlin: 1, price: 50 }) === 9);
ok('cleanCommit wirft Unbekanntes und falsche Preise weg',
   JSON.stringify(A.cleanCommit({ ak: true, foo: true, price: 17 })) === '{"ak":true}');

const orte = A.rankVenues(ctx);
ok('Spielorte: je 2 Konzerte, Docks (Ø 1) vor Molotow (Ø 1,8)',
   orte[0].venue.n === 'Docks' && orte[0].konzerte === 2 && orte[0].avg === 1
   && orte[1].venue.n === 'Molotow' && orte[1].konzerte === 2,
   orte.map((o) => `${o.venue.n} ${o.konzerte} Ø${o.avg}`).join(', '));
ok('Molotow: Durchschnitt aus 1 und 2,5 = 1,8 (gerundet)', orte[1].avg === 1.8, String(orte[1].avg));
ok('Molotow: 45 + 30 Minuten, Docks: 30 + 60', orte[1].minuten === 75 && orte[0].minuten === 90);

/* Rangfolge bei gleicher Note: der Einsatz entscheidet, dann wie oft. */
const r2 = A.rankActs({ ...ctx, rate: { 101: 1, 102: 1, 103: 1 },
                        commit: { 103: { vvk: true, price: 50 } } });
ok('Gleiche Note: Gamma (Einsatz 5) vor Alpha (2x gesehen) vor Beta',
   r2.map((a) => a.act.n).join(',') === 'Gamma,Alpha,Beta', r2.map((a) => a.act.n).join(','));

/* Ein Act in seenShow, aber nicht in seen: zaehlt trotzdem. */
const st3 = A.stats({ ...ctx, seen: new Set(), seenShow: new Set(['5']), partner: null });
ok('Auftritt ohne Act-Haken zaehlt als gesehen', st3.acts === 1 && st3.konzerte === 1);

/* Tabellen */
const sheets = A.sheets(ctx);
const names = sheets.map((s) => s.name);
ok('Sechs Blaetter mit Team', names.join('|') ===
   'Konzerte gesehen|Acts|Spielorte|Statistik|Line-up komplett|Team', names.join('|'));
ok('Konzerte: Kopf + 4 Zeilen', sheets[0].rows.length === 5);
ok('Spalte "Abgehakt von": ich, ich, ich, L',
   sheets[0].rows.slice(1).map((r) => r[11]).join(',') === 'ich,ich,ich,L',
   sheets[0].rows.slice(1).map((r) => r[11]).join(','));
ok('Konzerte chronologisch, Minuten als Zahl',
   sheets[0].rows[1][5] === 'Alpha' && sheets[0].rows[1][4] === 45
   && sheets[0].rows[2][5] === 'Beta' && sheets[0].rows[2][4] === 30 && sheets[0].rows[2][3] === '',
   JSON.stringify(sheets[0].rows.slice(1).map((r) => [r[5], r[4], r[3]])));
ok('Notiz mit einfachen Leerzeichen', sheets[0].rows[2][12] === 'laut und gut');
const kopf = sheets[1].rows[0];
ok('Acts: alle fuenf Einsatz-Spalten da',
   ['Abendkasse', 'Vorverkauf', 'Spotify folgen', 'Niedlichkeitsbonus', 'Konzert in Berlin']
     .every((k) => kopf.includes(k)));
const beta = sheets[1].rows.find((r) => r[1] === 'Beta');
ok('Beta: AK ja, VVK ja, 30 EUR, Einsatz 5',
   beta[kopf.indexOf('Abendkasse')] === 'ja' && beta[kopf.indexOf('Vorverkauf')] === 'ja'
   && beta[kopf.indexOf('Ticket bis (€)')] === 30 && beta[kopf.indexOf('Einsatz (Punkte)')] === 5);
ok('Line-up komplett: alle fuenf Auftritte', sheets[4].rows.length === 6);
ok('Ohne Partner kein Team-Blatt', A.sheets({ ...ctx, partner: null }).length === 5);

/* Archivdatei */
const doc = A.archiveDoc(ctx, { filters: [] });
ok('Archivdatei traegt Kennung und Programm', doc.kind === 'rbf26-archiv'
   && doc.lineup.acts.length === 4 && doc.mine.seen.length === 3 && doc.topActs[0].name === 'Alpha');
ok('Archivdatei: commit und Zusatz sind in mine', doc.mine.commit[102].price === 30
   && Array.isArray(doc.mine.filters));

/* ---------- Excel ---------- */
ok('Spaltennamen: A, Z, AA, AZ, BA', [0, 25, 26, 51, 52].map(X.colName).join(',') === 'A,Z,AA,AZ,BA');
ok('CRC32 von "123456789" ist CBF43926',
   X.crc32(new TextEncoder().encode('123456789')).toString(16).toUpperCase() === 'CBF43926');
ok('XML-Escape', X.xmlEsc('a<b>&"c"\u0007') === 'a&lt;b&gt;&amp;&quot;c&quot;');
ok('Blattnamen bereinigt und eindeutig',
   X.sheetNames([{ name: 'A/B:C' }, { name: 'A B C' }, { name: 'x'.repeat(40) }]).join('|')
   === 'A B C|A B C (2)|' + 'x'.repeat(31));

const bytes = X.build(sheets, new Date('2026-09-20T12:00:00'));
ok('ZIP faengt mit lokalem Kopf an', bytes[0] === 0x50 && bytes[1] === 0x4B && bytes[2] === 3 && bytes[3] === 4);
const dv = new DataView(bytes.buffer);
ok('ZIP endet mit Abschlussblock', dv.getUint32(bytes.length - 22, true) === 0x06054B50);
const entries = dv.getUint16(bytes.length - 12, true);
ok('11 Eintraege: 5 Rahmen + 6 Blaetter', entries === 11, String(entries));
const cdOffset = dv.getUint32(bytes.length - 6, true);
const cdSize = dv.getUint32(bytes.length - 10, true);
ok('Verzeichnis liegt vor dem Abschluss', cdOffset + cdSize + 22 === bytes.length);
/* Das Verzeichnis lesen: jeder Name muss da sein, jede Pruefsumme stimmen. */
const found = [];
let at = cdOffset, crcOk = true;
while (at < cdOffset + cdSize) {
  const nlen = dv.getUint16(at + 28, true);
  const name = new TextDecoder().decode(bytes.subarray(at + 46, at + 46 + nlen));
  const crc = dv.getUint32(at + 16, true);
  const size = dv.getUint32(at + 24, true);
  const loc = dv.getUint32(at + 42, true);
  const lnlen = dv.getUint16(loc + 26, true);
  const dataAt = loc + 30 + lnlen;
  if (X.crc32(bytes.subarray(dataAt, dataAt + size)) !== crc) crcOk = false;
  found.push(name);
  at += 46 + nlen;
}
ok('Pruefsummen stimmen fuer alle Eintraege', crcOk);
ok('Pflichtteile vorhanden', ['[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml',
   'xl/_rels/workbook.xml.rels', 'xl/styles.xml', 'xl/worksheets/sheet1.xml',
   'xl/worksheets/sheet6.xml'].every((n) => found.includes(n)), found.join(','));
const out = process.env.RBF_XLSX_OUT || '/tmp/rbf-test.xlsx';
fs.writeFileSync(out, bytes);
console.log(`  Excel-Datei geschrieben: ${out} (${bytes.length} Bytes)`);

console.log('\n' + (fails ? `FEHLGESCHLAGEN: ${fails}` : 'ALLE PRUEFUNGEN BESTANDEN'));
process.exit(fails ? 1 : 0);
