/* Excel-Datei ohne Fremdbibliothek.

   Eine .xlsx ist ein ZIP-Archiv mit ein paar XML-Dateien darin. Beides ist
   ueberschaubar, wenn man auf Kompression verzichtet: der ZIP-Teil ist dann
   nur Kopfzeilen und eine Pruefsumme, der Excel-Teil eine Tabelle als XML.
   Die verbreitete Bibliothek dafuer (SheetJS) waere 800 KB - mehr als die
   ganze App - und die Regel des Projekts heisst: kein Build-Schritt, keine
   Abhaengigkeit, die in zwei Jahren nicht mehr da ist.

   Was die Datei kann: mehrere Blaetter, Zahlen als Zahlen, Text als Text,
   fette Kopfzeile, eingefrorene erste Zeile, Autofilter, Spaltenbreiten nach
   Inhalt. Was sie NICHT kann: Formeln, Formate, Datumszellen - das braucht
   das Archiv nicht. Gelesen wird sie von Excel, LibreOffice, Numbers und
   openpyxl (letzteres prueft der Test).

   Aufruf: RBFXlsx.build([{ name, rows: [[...], ...] }]) -> Uint8Array
 */
'use strict';

/* Als Funktion gekapselt: klassische Skripte teilen sich den globalen
   Namensraum, und app.js kennt hhmm und WD schon. */
(() => {
/* ---------- ZIP, nur "stored" ---------- */

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

/* Zeitstempel im DOS-Format: zwei Sekunden Aufloesung, Jahre ab 1980. */
function dosStamp(d) {
  const time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
  const date = ((Math.max(1980, d.getFullYear()) - 1980) << 9)
    | ((d.getMonth() + 1) << 5) | d.getDate();
  return { time, date };
}

/* files: [{ name, data: Uint8Array }] -> Uint8Array
   Jede Datei bekommt einen lokalen Kopf vor den Daten, am Ende steht das
   zentrale Verzeichnis mit denselben Angaben und ein Abschlussblock. Das
   Bit 0x0800 sagt "Dateinamen sind UTF-8". */
function zipStore(files, now = new Date()) {
  const enc = new TextEncoder();
  const { time, date } = dosStamp(now);
  const parts = [];
  const central = [];
  let offset = 0;
  const le16 = (v, view, at) => view.setUint16(at, v & 0xFFFF, true);
  const le32 = (v, view, at) => view.setUint32(at, v >>> 0, true);
  for (const f of files) {
    const name = enc.encode(f.name);
    const data = f.data;
    const crc = crc32(data);
    const loc = new Uint8Array(30 + name.length);
    const lv = new DataView(loc.buffer);
    le32(0x04034B50, lv, 0); le16(20, lv, 4); le16(0x0800, lv, 6); le16(0, lv, 8);
    le16(time, lv, 10); le16(date, lv, 12); le32(crc, lv, 14);
    le32(data.length, lv, 18); le32(data.length, lv, 22);
    le16(name.length, lv, 26); le16(0, lv, 28);
    loc.set(name, 30);
    const cen = new Uint8Array(46 + name.length);
    const cv = new DataView(cen.buffer);
    le32(0x02014B50, cv, 0); le16(20, cv, 4); le16(20, cv, 6); le16(0x0800, cv, 8);
    le16(0, cv, 10); le16(time, cv, 12); le16(date, cv, 14); le32(crc, cv, 16);
    le32(data.length, cv, 20); le32(data.length, cv, 24); le16(name.length, cv, 28);
    le16(0, cv, 30); le16(0, cv, 32); le16(0, cv, 34); le16(0, cv, 36);
    le32(0, cv, 38); le32(offset, cv, 42);
    cen.set(name, 46);
    parts.push(loc, data);
    central.push(cen);
    offset += loc.length + data.length;
  }
  const cdSize = central.reduce((s, c) => s + c.length, 0);
  const end = new Uint8Array(22);
  const ev = new DataView(end.buffer);
  le32(0x06054B50, ev, 0); le16(0, ev, 4); le16(0, ev, 6);
  le16(files.length, ev, 8); le16(files.length, ev, 10);
  le32(cdSize, ev, 12); le32(offset, ev, 16); le16(0, ev, 20);
  const total = offset + cdSize + 22;
  const out = new Uint8Array(total);
  let at = 0;
  for (const p of [...parts, ...central, end]) { out.set(p, at); at += p.length; }
  return out;
}

/* ---------- SpreadsheetML ---------- */

/* Steuerzeichen ausser Tab und Zeilenumbruch sind in XML 1.0 verboten -
   eine Notiz mit einem verirrten Zeichen darf nicht die ganze Datei
   unlesbar machen. */
const xmlEsc = (s) => String(s)
  .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

/* 0 -> A, 25 -> Z, 26 -> AA */
function colName(i) {
  let s = '';
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  }
  return s;
}

/* Blattnamen: hoechstens 31 Zeichen, ohne [ ] : * ? / \ und eindeutig -
   sonst weigert sich Excel, die Datei zu oeffnen. */
function sheetNames(sheets) {
  const used = new Set();
  return sheets.map((sh, i) => {
    let base = String(sh.name || `Blatt${i + 1}`).replace(/[[\]:*?/\\]/g, ' ')
      .replace(/\s+/g, ' ').trim().slice(0, 31) || `Blatt${i + 1}`;
    let name = base, n = 2;
    while (used.has(name.toLowerCase())) {
      const suffix = ` (${n++})`;
      name = base.slice(0, 31 - suffix.length) + suffix;
    }
    used.add(name.toLowerCase());
    return name;
  });
}

function cellXml(ref, v, style) {
  const s = style ? ` s="${style}"` : '';
  if (v === null || v === undefined || v === '') return '';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return `<c r="${ref}"${s} t="inlineStr"><is><t>${xmlEsc(String(v))}</t></is></c>`;
    return `<c r="${ref}"${s}><v>${v}</v></c>`;
  }
  if (typeof v === 'boolean') return `<c r="${ref}"${s} t="b"><v>${v ? 1 : 0}</v></c>`;
  return `<c r="${ref}"${s} t="inlineStr"><is><t xml:space="preserve">${xmlEsc(v)}</t></is></c>`;
}

function sheetXml(rows) {
  const ncol = rows.reduce((m, r) => Math.max(m, r.length), 0);
  const nrow = rows.length;
  const widths = new Array(ncol).fill(6);
  for (const r of rows) {
    r.forEach((v, i) => {
      const len = v === null || v === undefined ? 0 : String(v).length;
      widths[i] = Math.max(widths[i], Math.min(60, len + 2));
    });
  }
  const last = `${colName(Math.max(0, ncol - 1))}${Math.max(1, nrow)}`;
  const cols = widths.map((w, i) =>
    `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('');
  const body = rows.map((r, ri) => {
    const cells = r.map((v, ci) => cellXml(`${colName(ci)}${ri + 1}`, v, ri === 0 ? 1 : 0)).join('');
    return `<row r="${ri + 1}">${cells}</row>`;
  }).join('');
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    + `<dimension ref="A1:${last}"/>`
    + '<sheetViews><sheetView workbookViewId="0">'
    + (nrow > 1 ? '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>' : '')
    + '</sheetView></sheetViews>'
    + '<sheetFormatPr defaultRowHeight="15"/>'
    + (ncol ? `<cols>${cols}</cols>` : '')
    + `<sheetData>${body}</sheetData>`
    + (nrow > 1 && ncol ? `<autoFilter ref="A1:${last}"/>` : '')
    + '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
    + '</worksheet>';
}

const STYLES = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
  + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
  + '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
  + '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
  + '<fills count="2"><fill><patternFill patternType="none"/></fill>'
  + '<fill><patternFill patternType="gray125"/></fill></fills>'
  + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
  + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
  + '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
  + '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
  + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
  + '</styleSheet>';

function build(sheets, now = new Date()) {
  if (!Array.isArray(sheets) || !sheets.length) throw new Error('keine Blaetter');
  const names = sheetNames(sheets);
  const enc = new TextEncoder();
  const files = [];
  const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
  const CT = 'application/vnd.openxmlformats-officedocument.spreadsheetml';
  files.push({ name: '[Content_Types].xml', data: enc.encode(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    + '<Default Extension="xml" ContentType="application/xml"/>'
    + `<Override PartName="/xl/workbook.xml" ContentType="${CT}.sheet.main+xml"/>`
    + `<Override PartName="/xl/styles.xml" ContentType="${CT}.styles+xml"/>`
    + sheets.map((_, i) =>
      `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="${CT}.worksheet+xml"/>`).join('')
    + '</Types>') });
  files.push({ name: '_rels/.rels', data: enc.encode(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + `<Relationship Id="rId1" Type="${R}/officeDocument" Target="xl/workbook.xml"/>`
    + '</Relationships>') });
  files.push({ name: 'xl/workbook.xml', data: enc.encode(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    + ` xmlns:r="${R}"><sheets>`
    + names.map((n, i) => `<sheet name="${xmlEsc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')
    + '</sheets></workbook>') });
  files.push({ name: 'xl/_rels/workbook.xml.rels', data: enc.encode(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + sheets.map((_, i) =>
      `<Relationship Id="rId${i + 1}" Type="${R}/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')
    + `<Relationship Id="rId${sheets.length + 1}" Type="${R}/styles" Target="styles.xml"/>`
    + '</Relationships>') });
  files.push({ name: 'xl/styles.xml', data: enc.encode(STYLES) });
  sheets.forEach((sh, i) => {
    files.push({ name: `xl/worksheets/sheet${i + 1}.xml`, data: enc.encode(sheetXml(sh.rows || [])) });
  });
  return zipStore(files, now);
}

window.RBFXlsx = { build, crc32, zipStore, colName, xmlEsc, sheetNames };
})();
