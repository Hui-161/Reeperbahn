"""Browser-Regressionstest der Web-App.

Startet keinen Server - der muss laufen:
    python3 -m http.server 8898 --directory web
    python3 web/test_e2e.py

Besser noch mit den echten Cloudflare-Headern, damit die CSP mitgeprueft
wird - siehe DEPLOY.md. Die Kartenkacheln brauchen Netz; ohne Netz
schlaegt nur die Kachel-Darstellung fehl, nicht der Test.
"""
from playwright.sync_api import sync_playwright
import os, sys

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8898")

FAILS=[]
def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond: FAILS.append(name)

with sync_playwright() as p:
    # In CI liegt Chromium am Standardpfad; lokal kann er per Umgebungs-
    # variable gesetzt werden: PW_CHROMIUM=/pfad/zu/chrome
    launch = {"args": ["--no-sandbox"]}
    if os.environ.get("PW_CHROMIUM"):
        launch["executable_path"] = os.environ["PW_CHROMIUM"]
    b = p.chromium.launch(**launch)
    ctx = b.new_context(viewport={"width":420,"height":900}, locale="de-DE",
                        device_scale_factor=2)
    pg = ctx.new_page()
    errors=[]
    pg.on("console", lambda m: errors.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    requested404=[]
    pg.on("response", lambda r: requested404.append(r.url)
          if r.status == 404 and "127.0.0.1" in r.url else None)

    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_selector(".row", timeout=15000)

    rows0 = pg.locator(".row").count()
    days = pg.locator(".day").count()
    check("Liste rendert", rows0 > 20 and days == 4, f"{rows0} Zeilen, {days} Tage")
    check("Kopfzeile Uhrzeit-Gruppen", pg.locator(".slot-head").count() > 3)

    # Wunsch 6: Genre-Filter inkl. "ohne Angabe"
    pg.click("#f-genre")
    pg.wait_for_selector("#genrebox .chip")
    labels = pg.locator("#genrebox .chip").all_inner_texts()
    check("Genre-Eimer 'ohne Angabe' vorhanden",
          any("ohne Angabe" in l for l in labels))
    pg.locator("#genrebox .chip", has_text="Heavy Metal").first.click()
    pg.wait_for_timeout(250)
    rows_g = pg.locator(".row").count()
    check("Genre-Filter wirkt", 0 < rows_g < rows0, f"{rows0} -> {rows_g}")
    check("Reset-Knopf erscheint", pg.locator("#f-reset").is_visible())
    pg.click("#f-reset"); pg.wait_for_timeout(250)
    check("Reset stellt wieder her", pg.locator(".row").count() == rows0)

    # Spielort-Filter
    pg.click("#f-venue")
    pg.wait_for_selector("#venuebox .chip")
    check("Genre-Kasten schliesst beim Oeffnen der Spielorte",
          pg.locator("#genrebox").is_hidden())
    vlabels = pg.locator("#venuebox .chip").all_inner_texts()
    check("Spielorte gelistet", len(vlabels) > 10, f"{len(vlabels)} Spielorte")
    pg.locator("#venuebox .chip").first.click()
    pg.wait_for_timeout(250)
    rows_v = pg.locator(".row").count()
    check("Spielort-Filter wirkt", 0 < rows_v < rows0, f"{rows0} -> {rows_v}")
    check("Chip zeigt die Anzahl",
          "(1)" in pg.locator("#f-venue").inner_text(),
          pg.locator("#f-venue").inner_text())
    # mit Genre kombinieren: darf nicht mehr Treffer geben
    pg.click("#f-genre"); pg.wait_for_selector("#genrebox .chip")
    pg.locator("#genrebox .chip").first.click(); pg.wait_for_timeout(250)
    check("Spielort und Genre kombinieren sich", pg.locator(".row").count() <= rows_v)
    pg.click("#f-reset"); pg.wait_for_timeout(300)
    check("Reset raeumt auch die Spielorte auf", pg.locator(".row").count() == rows0)

    # Wunsch 5 + 1: Favorit und Notiz
    pg.locator(".row-fav").first.click()
    pg.wait_for_timeout(120)
    check("Herz setzt sich",
          pg.locator(".row-fav").first.get_attribute("aria-pressed") == "true")
    pg.click("#f-fav"); pg.wait_for_timeout(250)
    check("Favoriten-Filter zeigt genau 1", pg.locator(".row").count() == 1)
    pg.click("#f-fav"); pg.wait_for_timeout(200)

    pg.locator(".row").first.click()
    pg.wait_for_selector("#d-note")
    name = pg.locator(".d-title").inner_text()
    pg.fill("#d-note", "Konflikt mit Lowertown pruefen")
    pg.wait_for_selector("#d-saved:has-text('Gespeichert')", timeout=4000)
    check("Notiz speichert", True, name)
    pg.locator(".rate button[data-r='gruen']").click()
    check("Ampel setzt sich",
          pg.locator(".rate button[data-r='gruen']").get_attribute("aria-pressed")=="true")
    pg.screenshot(path="/tmp/shot-detail.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("Ampel faerbt Zeile", pg.locator(".row.rated-gruen").count() >= 1)
    check("Notiz-Marke in der Liste", pg.locator(".row-name.has-note").count() >= 1)

    # Wunsch 4: Suche fokussiert
    pg.click("#btn-search"); pg.wait_for_timeout(150)
    focused = pg.evaluate("document.activeElement && document.activeElement.id")
    check("Suchfeld ist fokussiert", focused == "q", f"activeElement={focused}")
    pg.fill("#q", "molotow"); pg.wait_for_timeout(300)
    rows_q = pg.locator(".row").count()
    check("Suche nach Spielort findet Treffer", rows_q > 0, f"{rows_q} Treffer")
    pg.click("#q-clear"); pg.wait_for_timeout(250)

    pg.screenshot(path="/tmp/shot-list.png", full_page=False)

    # Wunsch 3 + 7: Karte
    pg.locator(".row-sub .venue").first.click()
    pg.wait_for_timeout(900)
    check("Karte oeffnet sich bei Klick auf Spielort", pg.locator("#map").is_visible())
    check("Marker gesetzt", pg.locator(".leaflet-marker-icon").count() > 5,
          f"{pg.locator('.leaflet-marker-icon').count()} Marker")
    check("Popup offen", pg.locator(".leaflet-popup").count() == 1)
    pg.screenshot(path="/tmp/shot-map.png")

    # Persistenz nach Reload
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_selector(".row", timeout=15000)
    check("Favorit ueberlebt Reload", pg.locator('.row-fav[aria-pressed="true"]').count() >= 1)
    check("Ampel ueberlebt Reload", pg.locator(".row.rated-gruen").count() >= 1)

    csp = [e for e in errors if "content security policy" in e.lower()
           or "refused to" in e.lower()]
    check("Keine CSP-Verletzung", not csp, str(csp[:3]))
    # --- Vorschlaege importieren ---
    # Bewusst in einem FRISCHEN Kontext: im bisherigen sind schon Acts
    # bewertet, und eine eigene Bewertung unterdrueckt den Vorschlagspunkt.
    # Ohne Isolierung testet man sonst die Vorgeschichte statt den Import.
    import json, tempfile
    lineup = json.load(open("web/data/lineup.json", encoding="utf-8"))
    ctx2 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    pg2 = ctx2.new_page()
    pg2.goto(BASE + "/", wait_until="load")
    pg2.wait_for_selector(".row", timeout=15000)
    act_idx = pg2.locator(".row").evaluate_all(
        "els => els.slice(0,2).map(e => e.dataset.act)")
    picks = [lineup["acts"][int(i)]["id"] for i in act_idx]
    fixture = {
        "suggested": {str(picks[0]): 0.95, str(picks[1]): 0.2},
        "evidence": {str(picks[0]): 10, str(picks[1]): 10},
        "min_evidence": 3,
        "profile_hits": [picks[1]],
        "bio_refs": {}, "known": {},
    }
    fp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(fixture, fp); fp.close()
    pg2.once("dialog", lambda d: d.accept())
    pg2.set_input_files("#file", fp.name)
    pg2.wait_for_timeout(800)
    check("Vorschlag 'nein' bei Ausschluss-Genre", pg2.locator("#list .hint-nein").count() == 1,
          f"{pg2.locator('.hint-nein').count()}")
    check("Vorschlag 'ja' bei Profil-Treffer", pg2.locator("#list .hint-ja").count() == 1,
          f"{pg2.locator('.hint-ja').count()}")

    before = pg2.locator("#list .hint").count()
    pg2.locator(".row").first.click()
    pg2.wait_for_selector(".suggestion")
    check("Vorschlag im Detail erklaert", pg2.locator(".suggestion").count() == 1)
    pg2.locator(".rate button[data-r='rot']").click()
    pg2.keyboard.press("Escape"); pg2.wait_for_timeout(500)
    check("Eigene Bewertung verdraengt den Vorschlagspunkt",
          pg2.locator("#list .hint").count() == before - 1,
          f"{before} -> {pg2.locator('#list .hint').count()}")
    check("Dialoginhalt beim Schliessen verworfen",
          pg2.locator("#detail .suggestion").count() == 0)

    pg2.reload(wait_until="load"); pg2.wait_for_selector(".row", timeout=15000)
    check("Vorschlaege ueberleben Reload",
          pg2.locator("#list .hint").count() == before - 1)
    ctx2.close()

    real = [e for e in errors if "openstreetmap" not in e.lower()
            and "tile" not in e.lower() and "ERR_" not in e
            and e not in csp]
    check("Keine JS-Fehler", not real, str(real[:3]))
    r404 = [u for u in requested404]
    check("Keine 404 auf eigene Dateien", not r404, str(r404[:4]))
    b.close()

print("\n" + ("ALLE PRUEFUNGEN BESTANDEN" if not FAILS else f"FEHLGESCHLAGEN: {FAILS}"))
sys.exit(1 if FAILS else 0)
