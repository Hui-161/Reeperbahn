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
    check("B sieht As Favorit-Marke", B.locator("#list .heart-p").count() >= 1,
          f"{B.locator('#list .heart-p').count()}")
    check("B sieht As Note", B.locator("#list .grade-p").count() >= 1,
          f"{B.locator('#list .grade-p').count()}")

    # B setzt eigene Note 2 auf denselben Act wie As Favorit -> "Beide"
    B.locator(f'.row[data-act="{idxA[0]}"] .row-time').first.click()
    B.wait_for_selector("#detail .rate")
    check("Detail nennt die Team-Einschaetzung",
          B.locator("#detail .suggestion").count() >= 1)
    B.locator(".rate button[data-r='2']").click()
    B.keyboard.press("Escape"); B.wait_for_timeout(300)
    B.click("#f-team"); B.wait_for_timeout(400)
    check("'Beide' findet den gemeinsamen Act", B.locator(".row").count() >= 1,
          f"{B.locator('.row').count()}")
    B.click("#f-team"); B.wait_for_timeout(200)
    # Der automatische Abgleich laeuft verzoegert - abwarten statt Knopf druecken.
    B.wait_for_timeout(6000)

    # ---------- Rueckweg: A gleicht ab und sieht Bs Note ----------
    A.click("#btn-menu"); A.wait_for_selector("#menu[open]")
    A.click("#m-sync"); A.wait_for_timeout(3500)
    if A.locator("#menu[open]").count():
        A.keyboard.press("Escape"); A.wait_for_timeout(300)
    check("A sieht nach dem Abgleich Bs Marken", A.locator("#list .grade-p").count() >= 1,
          f"{A.locator('#list .grade-p').count()} | Dialoge: "
          + " | ".join(dlgA.seen[-2:])[:90])

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

    real = [e for e in errsA + errsB
            if "openstreetmap" not in e.lower() and "ERR_" not in e]
    check("Keine JS-Fehler", not real, str(real[:2]))
    b.close()

print("\n" + ("TEAM-ABGLEICH: ALLE PRUEFUNGEN BESTANDEN" if not FAILS
             else f"FEHLGESCHLAGEN: {FAILS}"))
sys.exit(1 if FAILS else 0)
