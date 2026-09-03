"""Zwei Geraete, ein Team: gleicht sich der Zustand wirklich ab?

Braucht einen laufenden Server MIT der API-Nachbildung:
    python3 web/serve_local.py 8899
    BASE_URL=http://127.0.0.1:8899 python3 web/test_team.py

Geprueft wird die ganze Kette: Team anlegen, beitreten, verschluesselt
hochladen, entschluesselt zurueckbekommen, gemeinsame Treffer finden -
und dass eine falsche Passphrase abgewiesen wird.
"""
import json, os, sys
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8898")
PASS = "Reeperbahn zwei Lila"
FAILS = []
def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond: FAILS.append(name)

class Dialogs:
    """EIN Handler pro Seite. Zwei Handler wuerden denselben Dialog doppelt
    beantworten - Playwright bricht dann ab. Sammelt ausserdem alle Texte,
    damit man auf Fehlermeldungen pruefen kann."""

    def __init__(self, pg):
        self.queue = []
        self.seen = []
        pg.on("dialog", self._handle)

    def _handle(self, d):
        self.seen.append(d.message)
        if d.type == "prompt":
            d.accept(self.queue.pop(0) if self.queue else "")
        else:
            d.accept()

    def expect(self, *values):
        self.queue.extend(values)

    def said(self, needle):
        return any(needle.lower() in m.lower() for m in self.seen)

with sync_playwright() as p:
    launch = {"args": ["--no-sandbox"]}
    if os.environ.get("PW_CHROMIUM"): launch["executable_path"] = os.environ["PW_CHROMIUM"]
    b = p.chromium.launch(**launch)

    # ---------- Geraet A ----------
    ctxA = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    A = ctxA.new_page()
    errsA = []
    A.on("pageerror", lambda e: errsA.append(str(e)))
    A.on("console", lambda m: errsA.append(m.text) if m.type == "error" else None)
    A.goto(BASE + "/", wait_until="load")
    A.wait_for_selector(".row", timeout=20000)

    # A markiert: Favorit auf Zeile 0, Note 1 auf Zeile 1
    idxA = A.locator(".row").evaluate_all("els => els.slice(0,2).map(e => e.dataset.act)")
    lineup = json.load(open("web/data/lineup.json", encoding="utf-8"))
    ids = [lineup["acts"][int(i)]["id"] for i in idxA]
    A.locator(".row-fav").nth(0).click(); A.wait_for_timeout(200)
    A.locator(".row").nth(1).locator(".row-time").click()
    A.wait_for_selector("#detail .rate")
    A.locator(".rate button[data-r='1']").click()
    A.keyboard.press("Escape"); A.wait_for_timeout(250)

    dlgA = Dialogs(A)
    dlgA.expect("Lars", PASS)
    A.click("#btn-menu"); A.wait_for_selector("#menu[open]")
    A.click("#m-team-new")
    A.wait_for_timeout(3500)          # PBKDF2 + zwei Requests
    if A.locator("#menu[open]").count():
        A.keyboard.press("Escape"); A.wait_for_timeout(300)
    conf = A.evaluate("localStorage.getItem('rbf26.team')")
    check("Geraet A hat ein Team", bool(conf), (conf or "")[:60])
    team_id = json.loads(conf)["teamId"] if conf else ""
    check("Team-ID sieht plausibel aus", 16 <= len(team_id) <= 40, team_id)

    # ---------- Geraet B ----------
    ctxB = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    B = ctxB.new_page()
    errsB = []
    B.on("pageerror", lambda e: errsB.append(str(e)))
    B.on("console", lambda m: errsB.append(m.text) if m.type == "error" else None)
    B.goto(BASE + "/", wait_until="load")
    B.wait_for_selector(".row", timeout=20000)

    dlgB = Dialogs(B)
    dlgB.expect(team_id, "Linda", PASS)
    B.click("#btn-menu"); B.wait_for_selector("#menu[open]")
    B.click("#m-team-join")
    B.wait_for_timeout(4000)
    if B.locator("#menu[open]").count():
        B.keyboard.press("Escape"); B.wait_for_timeout(300)

    check("B sieht A als Team-Chip", B.locator("#f-team").is_visible())
    # Verdeckt, solange B selbst noch nichts bewertet hat - sonst faerbt As
    # Meinung Bs eigene ein, bevor sie entsteht.
    check("As Favorit-Marke ist fuer B noch verdeckt",
          B.locator("#list .heart-p").count() == 0,
          f"{B.locator('#list .heart-p').count()}")
    check("As Note ist fuer B noch verdeckt",
          B.locator("#list .grade-p").count() == 0,
          f"{B.locator('#list .grade-p').count()}")

    # B setzt eigene Note 2 auf denselben Act wie As Favorit -> "Beide",
    # und schaltet damit gleichzeitig As Favorit-Marke fuer diesen Act frei.
    B.locator(f'.row[data-act="{idxA[0]}"] .row-time').first.click()
    B.wait_for_selector("#detail .rate")
    check("Detail nennt die Team-Einschaetzung",
          B.locator("#detail .suggestion").count() >= 1)
    B.locator(".rate button[data-r='2']").click()
    B.keyboard.press("Escape"); B.wait_for_timeout(300)
    check("As Favorit-Marke steht jetzt fuer diesen Act in der Liste",
          B.locator(f'.row[data-act="{idxA[0]}"] .heart-p').count() == 1)
    B.click("#f-team"); B.wait_for_timeout(400)
    check("'Beide' findet den gemeinsamen Act", B.locator(".row").count() >= 1,
          f"{B.locator('.row').count()}")
    B.click("#f-team"); B.wait_for_timeout(200)

    # As Note (auf dem anderen Act) bleibt verdeckt, bis B sie bewusst aufdeckt.
    B.locator(f'.row[data-act="{idxA[1]}"] .row-time').first.click()
    B.wait_for_selector("#detail .suggestion")
    B.locator("#detail [data-reveal]").click(); B.wait_for_timeout(300)
    B.keyboard.press("Escape"); B.wait_for_timeout(300)
    check("As Note steht nach 'Trotzdem anzeigen' in der Liste",
          B.locator(f'.row[data-act="{idxA[1]}"] .grade-p').count() == 1)
    # Der automatische Abgleich laeuft verzoegert - abwarten statt Knopf druecken.
    B.wait_for_timeout(6000)

    # ---------- Rueckweg: A gleicht ab und sieht Bs Note ----------
    A.click("#btn-menu"); A.wait_for_selector("#menu[open]")
    A.click("#m-sync"); A.wait_for_timeout(3500)
    if A.locator("#menu[open]").count():
        A.keyboard.press("Escape"); A.wait_for_timeout(300)
    # A hat idxA[0] nur favorisiert, nicht bewertet - Bs Note bleibt also
    # verdeckt, bis A sie bewusst aufdeckt. Genau dieser Schutz ist der Punkt.
    check("Bs Note ist fuer A zunaechst verdeckt (Daten kamen an, sind aber nicht sichtbar)",
          A.locator(f'.row[data-act="{idxA[0]}"] .team-hidden').count() == 1,
          f"grade-p={A.locator('#list .grade-p').count()} | Dialoge: "
          + " | ".join(dlgA.seen[-2:])[:90])
    A.locator(f'.row[data-act="{idxA[0]}"] .row-time').first.click()
    A.wait_for_selector("#detail [data-reveal]")
    A.locator("#detail [data-reveal]").click(); A.wait_for_timeout(300)
    A.keyboard.press("Escape"); A.wait_for_timeout(300)
    check("A sieht nach dem Abgleich und Aufdecken Bs Note",
          A.locator(f'.row[data-act="{idxA[0]}"] .grade-p').count() == 1,
          f"{A.locator('#list .grade-p').count()}")

    # ---------- Falsche Passphrase ----------
    ctxC = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    C = ctxC.new_page()
    C.goto(BASE + "/", wait_until="load")
    C.wait_for_selector(".row", timeout=20000)
    dlgC = Dialogs(C)
    dlgC.expect(team_id, "Fremd", "voellig falsche Passphrase")
    C.click("#btn-menu"); C.wait_for_selector("#menu[open]")
    C.click("#m-team-join"); C.wait_for_timeout(4000)
    if not C.locator("#menu[open]").count():
        C.click("#btn-menu"); C.wait_for_selector("#menu[open]")
    check("Falsche Passphrase wird abgewiesen",
          dlgC.said("passt nicht") or dlgC.said("fehlgeschlagen"),
          " | ".join(dlgC.seen)[:110])
    check("Und uebernimmt keine fremden Marken",
          C.locator("#list .grade-p").count() == 0,
          f"{C.locator('#list .grade-p').count()}")

    # ---------- Der Kern: kommt es OHNE Knopfdruck an? ----------
    # Das war der gemeldete Fehler. Er lag nicht am Speicher, sondern am
    # Abfragetakt: 90 Sekunden. Gemessen gegen die echte API ist eine
    # Aenderung an einem bestehenden Eintrag nach 1 Sekunde abrufbar - die
    # App hat nur zu selten nachgefragt. Diese Pruefung faellt durch, wenn
    # der Takt wieder hochgesetzt wird.
    import time as _t
    A.keyboard.press("Escape"); A.wait_for_timeout(200)
    before = B.evaluate("""() => {
      const p = JSON.parse(localStorage.getItem('rbf26.partner') || 'null');
      return p ? Object.keys(p.rate || {}).length : 0;
    }""")
    fresh = [i for i in
             A.locator(".row").evaluate_all("els => els.map(e => e.dataset.act)")
             if i not in idxA][:1]
    A.locator(f'.row[data-act="{fresh[0]}"] .row-time').first.click()
    A.wait_for_selector("#detail .rate")
    A.locator(".rate button[data-r='4']").click()
    A.keyboard.press("Escape")
    t0 = _t.time(); arrived = None
    # Grosszuegig bemessen, damit ein langsamer Rechner den Test nicht
    # rot macht - aber weit unter den 90 Sekunden von vorher.
    while _t.time() - t0 < 45:
        now = B.evaluate("""() => {
          const p = JSON.parse(localStorage.getItem('rbf26.partner') || 'null');
          return p ? Object.keys(p.rate || {}).length : 0;
        }""")
        if now > before: arrived = int(_t.time() - t0); break
        _t.sleep(2)
    check("Aenderung kommt ohne Knopfdruck an", arrived is not None,
          f"nach {arrived} s" if arrived is not None else "nie (Grenze 45 s)")
    check("Und zwar deutlich schneller als die alten 90 s",
          arrived is not None and arrived < 40, f"{arrived} s")

    # Sichtbarer Zustand: laeuft der Abgleich, muss man das sehen koennen -
    # vorher stand nur Prosa im Menue und man konnte nicht erkennen, dass
    # ueberhaupt nichts eingerichtet war.
    B.click("#btn-menu"); B.wait_for_selector("#menu[open]")
    note = B.locator("#m-team-note").inner_text()
    check("Menue zeigt den Abgleich als aktiv",
          B.locator("#m-team-note .sync-on").count() == 1, note[:70])
    check("Menue nennt den letzten Abgleich", "Letzter Abgleich" in note,
          note[:70])
    B.keyboard.press("Escape"); B.wait_for_timeout(200)
    check("Fusszeile nennt den Team-Abgleich",
          "Team-Abgleich an" in B.locator("#meta").inner_text(),
          B.locator("#meta").inner_text()[-60:])

    # ---------- Das Tagesbudget des Speichers ----------
    # Der Freibetrag hat DREI Deckel: 100.000 Lesevorgaenge, aber nur je 1.000
    # Schreibvorgaenge und Verzeichnis-Abfragen. Ein list() bei jedem Abgleich
    # hat den Tag in vier Stunden aufgebraucht - genau so ist es passiert.
    # Geprueft wird deshalb die Eigenschaft: ein stiller Abgleich darf WEDER
    # das Verzeichnis abfragen NOCH schreiben.
    import urllib.request as _u

    def kvops(reset=False):
        r = _u.Request(BASE + "/api/kvops", method="DELETE" if reset else "GET")
        return json.load(_u.urlopen(r))

    if "127.0.0.1" in BASE or "localhost" in BASE:
        kvops(reset=True)
        B.evaluate("() => runSync(true, true)")
        B.wait_for_timeout(1200)
        o = kvops()
        check("Stiller Abgleich ohne Verzeichnis-Abfrage", o["list"] == 0, o)
        check("Stiller Abgleich ohne Schreibvorgang", o["write"] == 0, o)
        # Ein Abgleich liest zwei Schluessel: die Team-Auth und das Dokument
        # der Gegenseite. Die Grenze liegt hoeher, weil im Zeitfenster ein
        # zweiter Takt dazwischenfallen kann - die Aussage, auf die es
        # ankommt, steht in den beiden Pruefungen darueber. Lesevorgaenge
        # haben ohnehin den hundertfachen Deckel.
        check("Und er liest nur wenige Schluessel", o["read"] <= 8, o)

        # Nach neuen Mitgliedern SUCHEN darf eine Abfrage kosten - aber nur,
        # wenn wirklich gesucht wird.
        kvops(reset=True)
        B.evaluate("() => { lastDiscover = 0; }")
        B.evaluate("() => runSync(true, true)")
        B.wait_for_timeout(1200)
        o2 = kvops()
        check("Die Suche nach Mitgliedern kostet genau eine Abfrage",
              o2["list"] == 1, o2)

    real = [e for e in errsA + errsB
            if "openstreetmap" not in e.lower() and "ERR_" not in e]
    check("Keine JS-Fehler", not real, str(real[:2]))
    b.close()

print("\n" + ("TEAM-ABGLEICH: ALLE PRUEFUNGEN BESTANDEN" if not FAILS
             else f"FEHLGESCHLAGEN: {FAILS}"))
sys.exit(1 if FAILS else 0)
