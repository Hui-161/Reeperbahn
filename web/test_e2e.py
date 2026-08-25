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
    real = [e for e in errors if "openstreetmap" not in e.lower()
            and "tile" not in e.lower() and "ERR_" not in e
            and e not in csp]
    check("Keine JS-Fehler", not real, str(real[:3]))
    r404 = [u for u in requested404]
    check("Keine 404 auf eigene Dateien", not r404, str(r404[:4]))
    b.close()

print("\n" + ("ALLE PRUEFUNGEN BESTANDEN" if not FAILS else f"FEHLGESCHLAGEN: {FAILS}"))
sys.exit(1 if FAILS else 0)
