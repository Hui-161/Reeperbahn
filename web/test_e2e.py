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

    days = pg.locator(".day").count()
    rows_all_default = pg.locator(".row").count()
    check("Standard ist 'Alle Tage' (heute liegt vor dem Festival)",
          pg.locator('.day[data-day=""]').get_attribute("aria-selected") == "true")
    check("Reiter: Alle + vier Tage", days == 5, f"{days} Reiter")
    # Ab hier auf einen einzelnen Tag stellen, damit die Zaehlungen eindeutig sind.
    pg.locator('.day[data-day="2026-09-17"]').click()
    pg.wait_for_timeout(400)
    rows0 = pg.locator(".row").count()
    check("Liste rendert", 20 < rows0 < rows_all_default,
          f"{rows0} an einem Tag, {rows_all_default} an allen")
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
    name = pg.locator("#detail .d-title").inner_text()
    pg.fill("#d-note", "Konflikt mit Lowertown pruefen")
    pg.wait_for_selector("#d-saved:has-text('Gespeichert')", timeout=4000)
    check("Notiz speichert", True, name)
    pg.locator(".rate button[data-r='1']").click()
    check("Note 1 setzt sich",
          pg.locator(".rate button[data-r='1']").get_attribute("aria-pressed")=="true")
    # Sieben Knoepfe: 1, 1,5, 2, 2,5, 3, 4, 5 - die Zwischennoten stehen
    # dazwischen, zaehlen im Filter aber zur naechstbesseren ganzen Note.
    steps = pg.locator(".rate button").evaluate_all("els => els.map(e => e.dataset.r)")
    check("Skala hat sieben Stufen mit Zwischennoten",
          steps == ["1", "1.5", "2", "2.5", "3", "4", "5"], steps)
    check("Zwischennoten mit deutschem Komma",
          pg.locator('.rate button[data-r="1.5"] b').inner_text() == "1,5",
          pg.locator('.rate button[data-r="1.5"] b').inner_text())
    # Klein DAZWISCHEN, aber ohne die Trefferflaeche zu verlieren: sichtbar
    # deutlich schmaler und kleiner gesetzt als eine ganze Note, in der Hoehe
    # aber gleich - ein Knopf von der Groesse der Zahl waere auf dem Handy
    # nicht zu treffen.
    geo = pg.evaluate("""() => {
      const g = (sel) => {
        const b = document.querySelector(sel);
        const r = b.getBoundingClientRect();
        return { w: r.width, h: r.height,
                 fs: parseFloat(getComputedStyle(b.querySelector('b')).fontSize) };
      };
      return { half: g('.rate button[data-r="1.5"]'),
               full: g('.rate button[data-r="1"]') };
    }""")
    check("Zwischennote ist schmaler als die halbe ganze Note",
          geo["half"]["w"] < geo["full"]["w"] / 2,
          f"{geo['half']['w']:.0f}px gegen {geo['full']['w']:.0f}px")
    check("Zwischennote ist deutlich kleiner gesetzt",
          geo["half"]["fs"] < geo["full"]["fs"] * 0.7,
          f"{geo['half']['fs']}px gegen {geo['full']['fs']}px")
    check("Trefferflaeche behaelt die volle Hoehe",
          abs(geo["half"]["h"] - geo["full"]["h"]) < 1
          and geo["half"]["h"] >= 44,
          f"{geo['half']['h']:.0f}px gegen {geo['full']['h']:.0f}px")
    pg.screenshot(path="/tmp/shot-detail.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("Note faerbt Zeile", pg.locator(".row.rated-1").count() >= 1)
    check("Note steht als Zahl in der Liste",
          pg.locator("#list .grade-1").count() >= 1)
    check("Notiz-Marke in der Liste", pg.locator(".row-name.has-note").count() >= 1)

    # --- Zwischennoten: 1,5 zaehlt im Filter zu 1, 2,5 zu 2 ---
    pg.locator(".row").first.click(); pg.wait_for_selector(".rate")
    pg.locator('.rate button[data-r="1.5"]').click()
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    badge = pg.locator("#list .grade").first
    check("Zeile zeigt 1,5", badge.inner_text() == "1,5", badge.inner_text())
    bcls = badge.get_attribute("class")
    check("1,5 traegt die Farbe der 1",
          "grade-1" in bcls and "grade-half" in bcls, bcls)
    check("Zeilenrand folgt dem Eimer",
          "rated-1" in pg.locator(".row").first.get_attribute("class"),
          pg.locator(".row").first.get_attribute("class"))
    pg.locator(".row").nth(1).click(); pg.wait_for_selector(".rate")
    pg.locator('.rate button[data-r="2.5"]').click()
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Zweite Zeile zeigt 2,5",
          pg.locator(".row").nth(1).locator(".grade").inner_text() == "2,5")

    pg.click("#f-rate"); pg.wait_for_timeout(300)
    chips = pg.locator("#ratebox .chip").evaluate_all(
        "els => els.map(e => e.dataset.rate)")
    check("Filter bleibt bei fuenf Stufen",
          chips == ["1", "2", "3", "4", "5"], chips)
    check("Chip nennt die Zwischennote",
          "1,5" in pg.locator('#ratebox .chip[data-rate="1"]').inner_text(),
          pg.locator('#ratebox .chip[data-rate="1"]').inner_text())
    pg.locator('#ratebox .chip[data-rate="1"]').click(); pg.wait_for_timeout(400)
    shown = pg.locator("#list .grade").evaluate_all(
        "els => els.map(e => e.textContent)")
    check("Filter 1 nimmt 1,5 mit", "1,5" in shown, shown)
    check("Filter 1 laesst 2,5 draussen", "2,5" not in shown, shown)
    pg.locator('#ratebox .chip[data-rate="1"]').click()
    pg.locator('#ratebox .chip[data-rate="2"]').click(); pg.wait_for_timeout(400)
    shown = pg.locator("#list .grade").evaluate_all(
        "els => els.map(e => e.textContent)")
    check("Filter 2 nimmt 2,5 mit", "2,5" in shown, shown)
    check("Filter 2 laesst 1,5 draussen", "1,5" not in shown, shown)
    pg.locator('#ratebox .chip[data-rate="2"]').click()
    pg.click("#f-rate"); pg.wait_for_timeout(200)

    # --- Anspielen direkt aus der Liste ---
    order = pg.evaluate("""() => [...document.querySelector('.row').children]
      .map(c => c.className.split(' ')[0]).join('|')""")
    check("Play-Knopf steht links vom Herz",
          order.index("row-play") < order.index("row-fav"), order)
    pidx = pg.evaluate("""() => [...document.querySelectorAll('.row')]
      .findIndex(r => r.querySelector('.row-play').dataset.quickplay)""")
    check("Es gibt Acts mit Spotify-Link", pidx >= 0, pidx)
    pg.locator(".row").nth(pidx).locator(".row-play").click()
    pg.wait_for_timeout(500)
    check("Player oeffnet, Detaildialog bleibt zu",
          not pg.locator("#player").is_hidden()
          and pg.evaluate("() => !document.querySelector('#detail').open"))
    check("Spotify-Rahmen geladen", pg.locator("#player-slot iframe").count() == 1)
    check("Liste macht Platz fuer die Leiste",
          "has-player" in pg.evaluate("() => document.body.className"))
    # Der Player liegt ausserhalb von #list, deshalb ueberlebt er ein render().
    psrc = pg.locator("#player-slot iframe").get_attribute("src")
    pg.click("#f-genre"); pg.wait_for_timeout(300)
    check("Player laeuft beim Filtern weiter",
          pg.locator("#player-slot iframe").get_attribute("src") == psrc)
    pg.click("#f-genre"); pg.wait_for_timeout(200)
    pg.locator(".row-play.is-playing").first.click(); pg.wait_for_timeout(300)
    check("Nochmal tippen beendet",
          pg.locator("#player").is_hidden()
          and pg.locator("#player-slot iframe").count() == 0)

    # --- Ortskuerzel ---
    # Sie stehen im Spielort-Kasten, nicht in jeder Programmzeile: dort stand
    # das Kuerzel direkt neben dem vollen Namen und las sich doppelt
    # ("25  25 Club").
    pg.click("#f-venue"); pg.wait_for_timeout(400)
    vcodes = pg.evaluate("""() => [...document.querySelectorAll('#venuebox .vcode')]
      .map(e => e.textContent.trim())""")
    check("Kuerzel stehen im Spielort-Kasten",
          len(vcodes) > 10 and all(len(c) == 2 for c in vcodes),
          f"{len(vcodes)} Orte, z. B. {sorted(set(vcodes))[:8]}")
    check("Kuerzel sind eindeutig", len(vcodes) == len(set(vcodes)),
          f"{len(vcodes)} Orte, {len(set(vcodes))} Kuerzel")
    check("Kein Kuerzel mehr in der Programmzeile",
          pg.locator(".row .vcode").count() == 0,
          pg.locator(".row .vcode").count())
    pg.click("#f-venue"); pg.wait_for_timeout(200)

    # --- Ziehen zum Neuladen abgeschaltet ---
    ov = pg.evaluate(
        "() => getComputedStyle(document.documentElement).overscrollBehaviorY")
    check("Kein Neuladen durch Wischen", ov == "contain", ov)

    # --- Zurueck schliesst Ebenen, verlaesst erst nach Warnung ---
    pg.click("#btn-menu"); pg.wait_for_timeout(250)
    pg.go_back(); pg.wait_for_timeout(400)
    check("Zurueck schliesst erst das Menue",
          pg.evaluate("() => !document.querySelector('#menu').open")
          and pg.locator(".row").count() > 0)
    pg.go_back(); pg.wait_for_timeout(400)
    check("Zurueck warnt vor dem Verlassen",
          "Nochmal zurück" in pg.inner_text("#toast"), pg.inner_text("#toast"))
    check("App laeuft noch", pg.locator(".row").count() > 0)

    # --- Der schwarze Bildschirm in Firefox fuer Android ---
    # Ursache war ".detail::backdrop": die 55 % schwarze Flaeche galt auch fuer
    # einen GESCHLOSSENEN Dialog. Raeumt der Browser die Top-Layer-Ebene beim
    # Zurueck nicht sofort ab, bleibt sie ueber der ganzen Seite stehen. Mit
    # dialog[open]::backdrop kann das nicht passieren - unabhaengig davon, wie
    # sich der Browser verhaelt.
    bd = pg.evaluate("""() => {
      const d = document.querySelector('#menu');
      const shut = getComputedStyle(d, '::backdrop').backgroundColor;
      return { open: d.open, shut };
    }""")
    check("Geschlossener Dialog malt keine dunkle Flaeche",
          not bd["open"] and bd["shut"] in
          ("rgba(0, 0, 0, 0)", "transparent", ""), bd)
    pg.click("#btn-menu"); pg.wait_for_timeout(300)
    bd2 = pg.evaluate("""() => getComputedStyle(
      document.querySelector('#menu'), '::backdrop').backgroundColor""")
    check("Offener Dialog hat weiter seine Abdunklung",
          bd2 == "rgba(0, 0, 0, 0.55)", bd2)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    # Firefox fuer Android schliesst einen modalen Dialog beim Zurueck SELBST
    # und loest zusaetzlich popstate aus. Chrome verbraucht den Druck. Hier
    # wird der Firefox-Fall nachgestellt: Dialog von aussen schliessen, dann
    # popstate. Es darf NICHT zusaetzlich eine zweite Ebene zugehen.
    pg.click("#btn-search"); pg.wait_for_timeout(200)
    pg.click("#btn-menu"); pg.wait_for_timeout(300)
    pg.evaluate("""() => {
      document.querySelector('#menu').close();       // wie der Browser es tut
      window.dispatchEvent(new PopStateEvent('popstate', { state: null }));
    }""")
    pg.wait_for_timeout(300)
    check("Selbst geschlossener Dialog kostet nur EINE Ebene",
          not pg.locator("#searchbar").is_hidden(),
          "Suchleiste noch offen"
          if not pg.locator("#searchbar").is_hidden()
          else "Suchleiste zu — es ging eine Ebene zu viel zu")
    pg.click("#q-clear"); pg.wait_for_timeout(200)

    # Der Zurueck-Handler darf keine Knopfdruecke nachbilden: das laeuft durch
    # den ganzen Klick-Verteiler und zeichnet mitten in der Navigation neu.
    src = pg.evaluate("() => document.querySelector('script[src*=\"app.js\"]').src")
    js = pg.request.get(src).text()
    body = js[js.index("function closeOneLayer"):]
    body = body[:body.index("\n}")]
    check("closeOneLayer klickt keine Knoepfe", ".click()" not in body,
          body[:120])

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
    # Ortsmarker tragen ihr Kuerzel, damit 34 Haeuser auf engem Raum
    # unterscheidbar sind - und damit sie nicht wie eine numerierte
    # Route-Station aussehen.
    mcodes = pg.evaluate("""() => [...document.querySelectorAll('.venue-code')]
      .map(e => e.textContent.trim())""")
    check("Marker tragen ihr Kuerzel",
          len(mcodes) > 0 and all(len(c) == 2 for c in mcodes), mcodes)
    check("Kuerzel steht im Popup",
          pg.locator(".leaflet-popup .pop-code").count() == 1,
          pg.locator(".leaflet-popup .pop-title").inner_text())
    # Cluster-Blasen duerfen NICHT gefuellt sein wie die Route-Nadeln - das
    # war der gemeldete Fehler ("kolidiert mit der nummer der locations").
    # Geprueft wird die Eigenschaft, auf die es ankommt: die Fuellung einer
    # Blase darf nicht die Akzentfarbe sein, denn die tragen die Nadeln der
    # Route. Sonst heisst eine Zahl mal "so viele Haeuser" und mal
    # "hierhin als Erstes" - bei gleichem Aussehen.
    cl = pg.evaluate("""() => {
      const e = document.querySelector('.marker-cluster div');
      if (!e) return null;
      const probe = document.createElement('span');
      probe.style.color = 'var(--accent)';
      document.body.appendChild(probe);
      const accent = getComputedStyle(probe).color;
      probe.remove();
      const s = getComputedStyle(e);
      return { bg: s.backgroundColor, border: s.borderStyle,
               width: s.borderTopWidth, accent };
    }""")
    if cl is None:
        check("Cluster-Stil geprueft", True, "keine Blase auf dieser Zoomstufe")
    else:
        check("Cluster tragen NICHT die Farbe der Route-Nadeln",
              cl["bg"] != cl["accent"], f"{cl['bg']} vs Akzent {cl['accent']}")
        check("Cluster sind geringt",
              cl["border"] == "solid" and cl["width"] != "0px",
              f"{cl['border']} {cl['width']}")
    pg.screenshot(path="/tmp/shot-map.png")

    # Persistenz nach Reload
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_selector(".row", timeout=15000)
    check("Favorit ueberlebt Reload", pg.locator('.row-fav[aria-pressed="true"]').count() >= 1)
    check("Note ueberlebt Reload", pg.locator(".row.rated-1").count() >= 1)

    csp = [e for e in errors if "content security policy" in e.lower()
           or "refused to" in e.lower()]
    check("Keine CSP-Verletzung", not csp, str(csp[:3]))
    # "Alle Tage": Suche und Stoebern ueber Tagesgrenzen
    pg.locator('.day[data-day=""]').click()
    pg.wait_for_timeout(400)
    rows_all = pg.locator(".row").count()
    check("Alle-Tage-Reiter zeigt mehr als ein Tag",
          rows_all > rows0 and rows_all == rows_all_default,
          f"{rows0} (ein Tag) -> {rows_all} (alle)")
    heads = pg.locator(".slot-head").all_inner_texts()
    check("Gruppen nennen den Tag",
          any(h.startswith(("Mi", "Do", "Fr", "Sa")) for h in heads), heads[:2])
    pg.locator('.day[data-day="2026-09-18"]').click(); pg.wait_for_timeout(300)
    check("Zurueck auf einen Tag", pg.locator(".row").count() < rows_all)

    # Karte: der echte Weg - Spielort in der Liste antippen, dann im Popup
    # filtern. (Direkt auf einen Marker zu klicken ist unzuverlaessig: bei 34
    # Haeusern auf engem Raum verdecken sich die Marker gegenseitig.)
    pg.locator(".row-sub .venue").first.click(); pg.wait_for_timeout(1000)
    pg.locator("[data-onlyvenue]").click(); pg.wait_for_timeout(600)
    check("Karte schliesst nach 'Nur dieses Haus'", pg.locator("#list").is_visible())
    check("Genau ein Spielort gefiltert",
          "(1)" in pg.locator("#f-venue").inner_text(),
          pg.locator("#f-venue").inner_text())
    check("Und ueber alle Tage",
          pg.locator('.day[data-day=""]').get_attribute("aria-selected") == "true")
    venues_in_list = set(pg.locator(".row-sub .venue").all_inner_texts())
    check("Liste zeigt nur diesen Spielort", len(venues_in_list) == 1, str(venues_in_list))
    pg.click("#f-reset"); pg.wait_for_timeout(300)

    # Team: Partner-Datei laden und "Beide" pruefen
    import json as _json, tempfile as _tf
    lineup2 = _json.load(open("web/data/lineup.json", encoding="utf-8"))
    my_fav = pg.locator(".row-fav[aria-pressed='true']").count()
    check("Team-Chip ist ohne Partner:in verborgen", pg.locator("#f-team").is_hidden())
    # Partner mag genau die Acts der ersten zwei Zeilen
    idx = pg.locator(".row").evaluate_all("els => els.slice(0,2).map(e => e.dataset.act)")
    pids = [lineup2["acts"][int(i)]["id"] for i in idx]
    pfile = _tf.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    _json.dump({"kind": "rbf26-auswahl", "version": 3,
                "fav": [pids[0]], "seen": [], "rate": {str(pids[1]): 1}}, pfile)
    pfile.close()
    pg.click("#btn-menu"); pg.wait_for_selector("#menu[open]")
    pg.once("dialog", lambda d: d.accept("Linda"))
    pg.once("dialog", lambda d: d.accept())
    pg.set_input_files("#file-partner", pfile.name)
    pg.wait_for_timeout(900)
    if pg.locator("#menu[open]").count():
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Team-Chip erscheint mit Partner:in", pg.locator("#f-team").is_visible())
    check("Partner-Note steht in der Liste", pg.locator("#list .grade-p").count() >= 1,
          f"{pg.locator('#list .grade-p').count()}")
    check("Partner-Favorit steht in der Liste", pg.locator("#list .heart-p").count() >= 1)
    # Erst wenn ICH denselben Act auch mag, darf "Beide" anspringen.
    pg.click("#f-team"); pg.wait_for_timeout(400)
    check("'Beide' ist leer, solange nur eine Seite will",
          pg.locator(".row").count() == 0, f"{pg.locator('.row').count()}")
    pg.click("#f-team"); pg.wait_for_timeout(300)
    pg.locator(f'.row[data-act="{idx[0]}"] .row-fav').first.click()
    pg.wait_for_timeout(300)
    pg.click("#f-team"); pg.wait_for_timeout(400)
    check("'Beide' findet den gemeinsamen Act",
          pg.locator(".row").count() >= 1, f"{pg.locator('.row').count()}")
    check("Und markiert ihn im Detail als gemeinsam", True)
    # Beide neuen Filter an, dann zuruecksetzen. (Der Reset-Knopf ist nur
    # sichtbar, wenn ueberhaupt ein Filter aktiv ist.)
    pg.click("#f-seen"); pg.wait_for_timeout(200)
    check("Reset-Knopf sichtbar, sobald ein Filter laeuft",
          pg.locator("#f-reset").is_visible())
    pg.click("#f-reset"); pg.wait_for_timeout(350)
    check("Reset raeumt Gesehen und Beide auf",
          pg.locator("#f-seen").get_attribute("aria-pressed") == "false"
          and pg.locator("#f-team").get_attribute("aria-pressed") == "false"
          and pg.locator("#f-reset").is_hidden())

    # --- Bewertungsfilter als Kasten mit 1 bis 5 ---
    pg.click("#f-rate"); pg.wait_for_selector("#ratebox .chip")
    check("Notenkasten hat fuenf Stufen", pg.locator("#ratebox .chip").count() == 5,
          f"{pg.locator('#ratebox .chip').count()}")
    check("Andere Kaesten sind zu",
          pg.locator("#genrebox").is_hidden() and pg.locator("#venuebox").is_hidden())
    pg.locator('#ratebox .chip[data-rate="1"]').click(); pg.wait_for_timeout(350)
    only1 = pg.locator(".row").count()
    check("Note 1 filtert", only1 >= 1, f"{only1} Zeile(n)")
    check("Chip zeigt die Anzahl", "(1)" in pg.locator("#f-rate").inner_text(),
          pg.locator("#f-rate").inner_text())
    pg.locator('#ratebox .chip[data-rate="5"]').click(); pg.wait_for_timeout(350)
    check("Note 5 dazu erweitert die Auswahl",
          pg.locator(".row").count() >= only1
          and "(2)" in pg.locator("#f-rate").inner_text(),
          f"{pg.locator('.row').count()} | {pg.locator('#f-rate').inner_text()}")
    pg.locator('#ratebox .chip[data-rate="5"]').click(); pg.wait_for_timeout(250)

    # --- Filterspeicher ---
    pg.click("#btn-filters"); pg.wait_for_selector("#filterbox:not([hidden])")
    check("Notenkasten schliesst beim Oeffnen des Speichers",
          pg.locator("#ratebox").is_hidden())
    check("Speicher startet leer",
          pg.locator("#filterlist .saved").count() == 0)
    pg.fill("#filtername", "Nur Bestnoten")
    pg.click("#filtersave-go"); pg.wait_for_timeout(350)
    check("Filter gespeichert", pg.locator("#filterlist .saved").count() == 1)
    check("Name steht dran",
          "Nur Bestnoten" in pg.locator(".saved-use").first.inner_text())

    # Filter zuruecksetzen, dann den gespeicherten anwenden
    pg.click("#btn-filters"); pg.wait_for_timeout(200)
    pg.click("#f-reset"); pg.wait_for_timeout(350)
    check("Nach Reset kein Notenfilter",
          "(" not in pg.locator("#f-rate").inner_text(),
          pg.locator("#f-rate").inner_text())
    pg.click("#btn-filters"); pg.wait_for_selector("#filterbox:not([hidden])")
    pg.locator(".saved-use").first.click(); pg.wait_for_timeout(500)
    check("Gespeicherter Filter wird angewendet",
          "(1)" in pg.locator("#f-rate").inner_text(),
          pg.locator("#f-rate").inner_text())
    check("Und der Kasten schliesst sich", pg.locator("#filterbox").is_hidden())

    # Loeschen
    pg.click("#btn-filters"); pg.wait_for_selector("#filterbox:not([hidden])")
    pg.locator(".saved-del").first.click(); pg.wait_for_timeout(350)
    check("Filter geloescht", pg.locator("#filterlist .saved").count() == 0)

    # Ueberlebt der Speicher einen Reload?
    pg.fill("#filtername", "Merkposten")
    pg.click("#filtersave-go"); pg.wait_for_timeout(300)
    pg.reload(wait_until="load"); pg.wait_for_selector(".row", timeout=15000)
    pg.click("#btn-filters"); pg.wait_for_selector("#filterbox:not([hidden])")
    check("Gespeicherte Filter ueberleben Reload",
          pg.locator("#filterlist .saved").count() == 1,
          f"{pg.locator('#filterlist .saved').count()}")
    pg.locator(".saved-del").first.click(); pg.wait_for_timeout(250)
    pg.click("#btn-filters"); pg.wait_for_timeout(200)
    pg.click("#f-reset") if pg.locator("#f-reset").is_visible() else None
    pg.wait_for_timeout(300)

    # --- Abendplan ---
    # Ein Tag und ein paar Noten sind Voraussetzung; Noten 1 und 3 sind
    # weiter oben schon gesetzt worden.
    pg.locator('.day[data-day="2026-09-17"]').click(); pg.wait_for_timeout(300)
    # Zwei Acts MIT Uhrzeit bewerten - ohne Uhrzeit ist nichts planbar, und
    # die weiter oben bewerteten Acts stehen zufaellig auf "Zeit offen".
    times = pg.locator(".row .row-time").all_inner_texts()
    dated = [i for i, t in enumerate(times) if "Zeit" not in t][:2]
    check("Es gibt Auftritte mit Uhrzeit am Donnerstag", len(dated) == 2, str(dated))
    for k, i in enumerate(dated):
        pg.locator(".row").nth(i).locator(".row-time").click()
        pg.wait_for_selector("#detail .rate")
        pg.locator(f".rate button[data-r='{k + 1}']").click()
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    pg.click("#btn-menu"); pg.wait_for_selector("#menu[open]")
    pg.click("#m-plan"); pg.wait_for_timeout(600)
    check("Abendplan oeffnet sich", pg.locator("#plan").is_visible()
          and pg.locator("#list").is_hidden())
    body = pg.locator("#plan-body").inner_text()
    check("Plan sagt etwas Sinnvolles",
          "Konzerte" in body or "Nichts zu planen" in body or "Tag wählen" in body,
          body[:70].replace("\n", " "))

    # Noten bis 5 -> es muss etwas planbar sein
    pg.select_option("#plan-max", "5"); pg.wait_for_timeout(500)
    stops = pg.locator("#plan .stop").count()
    check("Mit Noten bis 5 entsteht ein Plan", stops >= 1, f"{stops} Station(en)")
    if stops >= 2:
        check("Fusswege werden ausgewiesen", pg.locator("#plan .leg").count() >= 1,
              f"{pg.locator('#plan .leg').count()} Etappe(n)")
    # Die Endzeit muss zur letzten Station passen - der Zeitzonenfehler zeigte
    # hier zwei Stunden zu wenig.
    summary = pg.locator(".plan-sum").inner_text()
    stop_times = pg.locator("#plan .stop .row-time").all_inner_texts()
    if stop_times and "bis etwa" in summary:
        import re as _re
        last_start = stop_times[-1].strip()
        shown_end = _re.search(r"bis etwa (\d\d):(\d\d)", summary)
        lh, lm = (int(x) for x in last_start.split(":"))
        eh, em = int(shown_end.group(1)), int(shown_end.group(2))
        diff = ((eh * 60 + em) - (lh * 60 + lm)) % (24 * 60)
        # Spielzeit auslesen statt annehmen - sonst prueft der Test seine
        # eigene Vermutung und nicht die App.
        set_min = int(pg.locator("#plan-set").input_value())
        check("Endzeit = letzter Beginn + Spielzeit", diff == set_min,
              f"letzter Start {last_start}, Ende {eh:02d}:{em:02d}, "
              f"Differenz {diff} min, Spielzeit {set_min} min")

    check("Zusammenfassung nennt den Fussweg",
          "Fußweg" in pg.locator(".plan-sum").inner_text(),
          pg.locator(".plan-sum").inner_text()[:60])

    # Spielzeit aendern muss den Plan beeinflussen koennen
    pg.select_option("#plan-set", "50"); pg.wait_for_timeout(500)
    check("Aenderung der Spielzeit wird verarbeitet",
          pg.locator("#plan-body").inner_text() != "", "")

    # Route auf der Karte
    pg.click("#plan-map"); pg.wait_for_timeout(1200)
    check("Route liegt auf der Karte", pg.locator("#map").is_visible())
    pins = pg.locator(".route-pin").count()
    check("Numerierte Stationen gesetzt", pins >= 1, f"{pins} Marker")
    check("Verbindungslinie gezeichnet",
          pg.locator("#map path.leaflet-interactive").count() >= 1
          or pg.locator("#map svg path").count() >= 1)
    # Der gemeldete Fehler: eine nackte Zahl war von der Zahl in einer
    # Cluster-Blase nicht zu unterscheiden. Start und Ziel sind deshalb
    # beschriftet, die Nadel hat eine andere Form, und die Haeuser treten
    # zurueck, solange eine Route liegt.
    check("Genau ein Start", pg.locator(".route-pin.is-first").count() == 1,
          pg.locator(".route-pin.is-first").count())
    tags = pg.locator(".route-pin-tag").evaluate_all(
        "els => els.map(e => e.textContent.trim())")
    check("Start ist beschriftet", "START" in tags, tags)
    if pins > 1:
        check("Ziel ist beschriftet", "ZIEL" in tags, tags)
        check("Richtungspfeil je Teilstrecke",
              pg.locator(".route-arrow").count() == pins - 1,
              f"{pg.locator('.route-arrow').count()} Pfeile, {pins} Stationen")
    check("Spielorte treten hinter die Route zurueck",
          "route-on" in pg.locator("#map").get_attribute("class"))
    faded = pg.evaluate("""() => {
      const e = document.querySelector('.venue-code');
      return e ? getComputedStyle(e).opacity : 'keiner sichtbar';
    }""")
    check("Ortsmarker sind abgeblendet",
          faded in ("0.38", "keiner sichtbar"), faded)
    pg.click("#btn-map"); pg.wait_for_timeout(500)
    check("Karte wieder zu", pg.locator("#list").is_visible())
    check("Route abgeraeumt", pg.locator(".route-pin").count() == 0
          and "route-on" not in pg.locator("#map").get_attribute("class"))

    # --- Spotify: Player erst auf Tippen ---
    pg.click("#btn-menu"); pg.wait_for_selector("#menu[open]")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    found = False
    for i in range(14):
        pg.locator(".row").nth(i).locator(".row-time").click()
        pg.wait_for_selector("#detail .d-title")
        if pg.locator("[data-play]").count():
            found = True
            break
        pg.keyboard.press("Escape"); pg.wait_for_timeout(120)
    check("Anspiel-Knopf vorhanden", found)
    if found:
        check("Vorher KEIN iframe geladen", pg.locator("#detail iframe").count() == 0)
        pg.locator("[data-play]").click(); pg.wait_for_timeout(600)
        src = pg.locator("#detail iframe").first.get_attribute("src") or ""
        check("Spotify-Embed wird geladen",
              src.startswith("https://open.spotify.com/embed/"), src[:60])
    pg.keyboard.press("Escape"); pg.wait_for_timeout(250)

    # Ansicht hell/dunkel per Knopf.
    # WICHTIG: hier wird die GERENDERTE Farbe geprueft, nicht nur das
    # data-theme-Attribut. Genau diese Luecke hat einen Fehler durchgelassen:
    # das Attribut stand richtig, ausgeliefert wurde aber altes CSS aus dem
    # Service-Worker-Cache, und die Ansicht blieb dunkel.
    def theme_attr():
        return pg.locator("html").get_attribute("data-theme")

    def lum():
        """Helligkeit der Kartenflaeche, 0 (schwarz) bis 1 (weiss)."""
        rgb = pg.evaluate(
            "getComputedStyle(document.querySelector('.row')).backgroundColor")
        n = [int(x) / 255 for x in rgb[rgb.index('(') + 1:rgb.index(')')].split(',')[:3]]
        f = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in n]
        return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
    check("Start folgt der Systemvorgabe", theme_attr() is None, str(theme_attr()))

    pg.click("#btn-theme"); pg.wait_for_timeout(200)
    t1 = theme_attr()
    light_lum = lum()
    check("'Immer hell' rendert wirklich hell", light_lum > 0.85,
          f"Helligkeit {light_lum:.3f} (Karte)")
    pg.click("#btn-theme"); pg.wait_for_timeout(200)
    t2 = theme_attr()
    dark_lum = lum()
    check("'Immer dunkel' rendert wirklich dunkel", dark_lum < 0.1,
          f"Helligkeit {dark_lum:.3f} (Karte)")
    pg.click("#btn-theme"); pg.wait_for_timeout(200)
    check("Schalter durchlaeuft hell, dunkel, System",
          {t1, t2} == {"light", "dark"} and theme_attr() is None, f"{t1} -> {t2} -> System")
    pg.click("#btn-theme"); pg.wait_for_timeout(200)   # auf 'light' stehen lassen
    pg.reload(wait_until="load"); pg.wait_for_selector(".row", timeout=15000)
    check("Ansicht ueberlebt Reload", theme_attr() == "light", str(theme_attr()))
    check("Und ist nach dem Reload noch hell", lum() > 0.85, f"Helligkeit {lum():.3f}")

    # Menue oben rechts
    pg.click("#btn-menu"); pg.wait_for_selector("#menu[open]")
    check("Menue enthaelt die Dateiaktionen",
          pg.locator("#m-export").count() == 1 and pg.locator("#m-import").count() == 1
          and pg.locator("#m-seen").count() == 1)
    check("Menue zeigt die aktive Ansicht",
          pg.locator('[data-theme-set="light"]').get_attribute("aria-pressed") == "true")
    check("Menue zeigt Kennzahlen", "Favoriten" in pg.locator("#m-stats").inner_text(),
          pg.locator("#m-stats").inner_text())
    pg.keyboard.press("Escape"); pg.wait_for_timeout(250)
    check("Aktionen sind NICHT mehr im Fuss",
          pg.locator(".foot .linkish").count() == 0)

    # Gesehen markieren und als CSV ausgeben
    pg.locator(".row").nth(1).locator(".row-time").click()
    pg.wait_for_selector("[data-seen]")
    act_name = pg.locator("#detail .d-title").inner_text()
    pg.locator("[data-seen]").click(); pg.wait_for_timeout(250)
    check("Gesehen setzt sich",
          pg.locator("[data-seen]").get_attribute("aria-pressed") == "true")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Gesehen-Marke in der Liste", pg.locator("#list .seen-mark").count() >= 1)

    # Jetzt ist etwas markiert, also kann der Filter geprueft werden.
    pg.click("#f-seen"); pg.wait_for_timeout(350)
    check("Gesehen-Filter zeigt nur Markierte",
          pg.locator(".row").count() == 1 and pg.locator("#list .seen-mark").count() == 1,
          f"{pg.locator('.row').count()} Zeile(n)")
    pg.click("#f-seen"); pg.wait_for_timeout(350)
    check("Gesehen-Filter wieder aus", pg.locator(".row").count() > 1)

    pg.click("#btn-menu"); pg.wait_for_selector("#menu[open]")
    with pg.expect_download() as dl:
        pg.click("#m-seen")
    path = dl.value.path()
    csv_text = open(path, encoding="utf-8-sig").read()
    check("CSV wird heruntergeladen", dl.value.suggested_filename.endswith(".csv"),
          dl.value.suggested_filename)
    check("CSV hat Kopfzeile", csv_text.splitlines()[0].startswith('"Tag";"Zeit";"Act"'),
          csv_text.splitlines()[0][:40])
    check("CSV enthaelt den markierten Act", act_name.split()[0] in csv_text, act_name)
    pg.wait_for_timeout(200)

    # Clustering auf der Karte
    pg.click("#btn-map"); pg.wait_for_timeout(1200)
    clusters = pg.locator(".marker-cluster").count()
    single = pg.locator(".leaflet-marker-icon:not(.marker-cluster)").count()
    check("Marker sind geclustert", clusters > 0, f"{clusters} Cluster, {single} Einzelmarker")
    check("Nicht mehr alle 34 Marker einzeln", single < 34, f"{single} einzeln")
    pg.click("#btn-map"); pg.wait_for_timeout(400)

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
    pg2.locator(".rate button[data-r='5']").click()
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

    # --- Format 2: taste.py liefert die Begruendungen selbst mit ---
    # Die App darf sie dann nicht mehr aus Punktzahlen ableiten, sondern muss
    # den Text uebernehmen - auch den Hinweis "bereits in Playlist entfernt",
    # den nur die Playlist kennt und die App sonst nie erfaehrt.
    ctx3 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    pg3 = ctx3.new_page()
    pg3.goto(BASE + "/", wait_until="load")
    pg3.wait_for_selector(".row", timeout=15000)
    idx3 = pg3.locator(".row").evaluate_all(
        "els => els.slice(0,2).map(e => e.dataset.act)")
    p3 = [lineup["acts"][int(i)]["id"] for i in idx3]
    fixture2 = {
        "format": 2,
        # Absichtlich widerspruechlich zu den Punktzahlen: die Punktzahl des
        # ersten Acts wuerde in Format 1 ein "nein" ergeben. Wenn trotzdem
        # "ja" erscheint, hat die App wirklich die hints benutzt.
        "suggested": {str(p3[0]): 0.99, str(p3[1]): 0.99},
        "evidence": {str(p3[0]): 10, str(p3[1]): 10},
        "hints": {
            str(p3[0]): {"v": "ja", "why": "Bio nennt aus deiner Playlist: Interpol"},
            str(p3[1]): {"v": "nein", "why": "bereits in Playlist entfernt"},
        },
        "known": {},
    }
    fp2 = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                      encoding="utf-8")
    json.dump(fixture2, fp2); fp2.close()
    pg3.once("dialog", lambda d: d.accept())
    pg3.set_input_files("#file", fp2.name)
    pg3.wait_for_timeout(800)
    check("Format 2: hints schlagen Punktzahlen",
          pg3.locator("#list .hint-ja").count() == 1
          and pg3.locator("#list .hint-nein").count() == 1,
          f"ja={pg3.locator('#list .hint-ja').count()} "
          f"nein={pg3.locator('#list .hint-nein').count()}")
    pg3.locator(".row").nth(1).click()
    pg3.wait_for_selector(".suggestion")
    check("Format 2: Playlist-Hinweis steht im Detail",
          "bereits in Playlist entfernt"
          in pg3.locator(".suggestion").inner_text(),
          pg3.locator(".suggestion").inner_text()[:80])
    ctx3.close()

    # Der Fall, der auf dem Handy schiefging: Systemvorgabe DUNKEL, Nutzer
    # waehlt ausdruecklich hell. Vorher blieb es dunkel (altes CSS aus dem
    # Cache), das Attribut allein sah aber richtig aus.
    ctx4 = b.new_context(viewport={"width": 420, "height": 700},
                         color_scheme="dark", locale="de-DE")
    pg4 = ctx4.new_page()
    pg4.goto(BASE + "/", wait_until="load")
    pg4.wait_for_selector(".row", timeout=15000)

    def lum4():
        rgb = pg4.evaluate(
            "getComputedStyle(document.querySelector('.row')).backgroundColor")
        n = [int(x) / 255 for x in rgb[rgb.index('(') + 1:rgb.index(')')].split(',')[:3]]
        f = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in n]
        return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]

    check("Systemvorgabe dunkel wird dunkel gerendert", lum4() < 0.1,
          f"Helligkeit {lum4():.3f}")
    pg4.click('[data-theme-set="light"]') if pg4.locator('#menu[open]').count() \
        else pg4.click("#btn-theme")
    pg4.wait_for_timeout(300)
    check("Ausdrueckliches Hell gewinnt gegen dunkle Systemvorgabe",
          pg4.locator("html").get_attribute("data-theme") == "light" and lum4() > 0.85,
          f"data-theme={pg4.locator('html').get_attribute('data-theme')}, "
          f"Helligkeit {lum4():.3f}")
    ctx4.close()

    # Migration: alte Dreistufen-Werte muessen auf die Skala abgebildet werden
    ctx3 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    ctx3.add_init_script(
        "try { localStorage.setItem('rbf26.rate',"
        " JSON.stringify({'11515':'gruen','10864':'gelb','10874':'rot'})); } catch (e) {}")
    pg3 = ctx3.new_page()
    pg3.goto(BASE + "/", wait_until="load")
    pg3.wait_for_selector(".row", timeout=15000)
    pg3.locator('.day[data-day=""]').click(); pg3.wait_for_timeout(400)
    check("Alte 'gruen' wird Note 1", pg3.locator("#list .grade-1").count() >= 1)
    check("Alte 'gelb' wird Note 3", pg3.locator("#list .grade-3").count() >= 1)
    check("Alte 'rot' wird Note 5", pg3.locator("#list .grade-5").count() >= 1)
    check("Keine alten Klassen mehr",
          pg3.locator(".row.rated-gruen").count() == 0)
    ctx3.close()

    # --- Wischen auf Kuenstlerzeilen ---
    # Eigener Kontext MIT Touch: ohne has_touch gibt es keine Touch-Klasse
    # und die Gesten liessen sich gar nicht nachbilden.
    ctx5 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE",
                         has_touch=True, is_mobile=True)
    pg5 = ctx5.new_page()
    err5 = []
    pg5.on("pageerror", lambda e: err5.append(str(e)))
    pg5.goto(BASE + "/", wait_until="load")
    pg5.wait_for_selector(".row", timeout=20000)

    # Eine Geste als Folge echter Touch-Ereignisse. Schrittweise, damit die
    # Richtungserkennung dieselbe Kette sieht wie auf dem Geraet.
    SWIPE = """([idx, dx, steps]) => {
      const row = document.querySelectorAll('.row')[idx];
      const r = row.getBoundingClientRect();
      const x0 = r.left + 40, y0 = r.top + r.height / 2;
      const fire = (type, x, y) => {
        const t = new Touch({ identifier: 1, target: row, clientX: x,
                              clientY: y, pageX: x, pageY: y });
        const empty = type === 'touchend';
        row.dispatchEvent(new TouchEvent(type, { bubbles: true,
          cancelable: true, touches: empty ? [] : [t],
          targetTouches: empty ? [] : [t], changedTouches: [t] }));
      };
      fire('touchstart', x0, y0);
      for (let i = 1; i <= steps; i++) fire('touchmove', x0 + dx * i / steps, y0);
      fire('touchend', x0 + dx, y0);
    }"""

    pg5.evaluate(SWIPE, [0, 120, 8]); pg5.wait_for_timeout(500)
    check("Wisch nach rechts oeffnet die Schnellbewertung",
          pg5.evaluate("() => document.querySelector('#quick').open"))
    check("Der Detaildialog bleibt dabei zu",
          pg5.evaluate("() => !document.querySelector('#detail').open"))
    qsteps = pg5.locator("#quick-rate button").evaluate_all(
        "e => e.map(x => x.dataset.r)")
    check("Schnellbewertung hat alle sieben Stufen",
          qsteps == ["1", "1.5", "2", "2.5", "3", "4", "5"], qsteps)
    pg5.locator('#quick-rate button[data-r="1.5"]').click()
    pg5.wait_for_timeout(400)
    check("Note aus der Schnellbewertung landet in der Liste",
          pg5.locator("#list .grade").first.inner_text() == "1,5",
          pg5.locator("#list .grade").first.inner_text())

    seen0 = pg5.locator("#list .seen-mark").count()
    pg5.evaluate(SWIPE, [1, -120, 8]); pg5.wait_for_timeout(500)
    check("Wisch nach links markiert als gesehen",
          pg5.locator("#list .seen-mark").count() == seen0 + 1,
          f"{seen0} -> {pg5.locator('#list .seen-mark').count()}")
    check("Mit Ruecknahme-Knopf", pg5.locator("#toast .toast-undo").count() == 1,
          pg5.inner_text("#toast"))
    pg5.locator("#toast .toast-undo").click(); pg5.wait_for_timeout(400)
    check("Ruecknahme stellt wieder her",
          pg5.locator("#list .seen-mark").count() == seen0)

    # Ein zu kurzer Wisch darf nichts tun, sonst loest jedes Verrutschen aus.
    rates0 = pg5.evaluate(
        "() => Object.keys(JSON.parse(localStorage.getItem('rbf26.rate')||'{}')).length")
    pg5.evaluate(SWIPE, [2, 30, 4]); pg5.wait_for_timeout(400)
    check("Zu kurzer Wisch loest nichts aus",
          pg5.evaluate("() => !document.querySelector('#quick').open")
          and pg5.evaluate("() => Object.keys(JSON.parse("
                           "localStorage.getItem('rbf26.rate')||'{}')).length")
              == rates0)

    # Senkrecht muss Scrollen bleiben - sonst verrutscht bei jedem Wischen
    # durch die Liste eine Zeile.
    VERT = """([idx]) => {
      const row = document.querySelectorAll('.row')[idx];
      const r = row.getBoundingClientRect();
      const x0 = r.left + 40, y0 = r.top + r.height / 2;
      const fire = (type, x, y) => {
        const t = new Touch({ identifier: 1, target: row, clientX: x,
                              clientY: y, pageX: x, pageY: y });
        const empty = type === 'touchend';
        row.dispatchEvent(new TouchEvent(type, { bubbles: true,
          cancelable: true, touches: empty ? [] : [t],
          targetTouches: empty ? [] : [t], changedTouches: [t] }));
      };
      fire('touchstart', x0, y0);
      for (let i = 1; i <= 6; i++) fire('touchmove', x0 + 4, y0 - i * 20);
      fire('touchend', x0 + 4, y0 - 120);
      return document.querySelector('#swipe').hidden;
    }"""
    check("Senkrechte Geste bleibt Scrollen", pg5.evaluate(VERT, [3]))

    # Auf dem Herz beginnt keine Geste, sonst kaeme man nicht mehr sauber ran.
    ON_HEART = """() => {
      const h = document.querySelector('.row .row-fav');
      const r = h.getBoundingClientRect();
      const fire = (type, x, y) => {
        const t = new Touch({ identifier: 1, target: h, clientX: x, clientY: y,
                              pageX: x, pageY: y });
        const empty = type === 'touchend';
        h.dispatchEvent(new TouchEvent(type, { bubbles: true, cancelable: true,
          touches: empty ? [] : [t], targetTouches: empty ? [] : [t],
          changedTouches: [t] }));
      };
      fire('touchstart', r.left + 5, r.top + r.height / 2);
      for (let i = 1; i <= 6; i++) fire('touchmove', r.left + 5 + i * 20,
                                        r.top + r.height / 2);
      fire('touchend', r.left + 125, r.top + r.height / 2);
      return document.querySelector('#swipe').hidden
             && !document.querySelector('#quick').open;
    }"""
    check("Auf dem Herz beginnt keine Geste", pg5.evaluate(ON_HEART))

    pg5.click("#btn-menu"); pg5.wait_for_timeout(400)
    check("Wisch-Einstellungen stehen im Menue",
          pg5.locator("#sw-left").count() == 1
          and pg5.locator("#sw-right").count() == 1
          and pg5.locator("#sw-dist").count() == 1)
    pg5.select_option("#sw-left", "fav")
    pg5.keyboard.press("Escape"); pg5.wait_for_timeout(400)
    fav0 = pg5.evaluate(
        "() => JSON.parse(localStorage.getItem('rbf26.fav')||'[]').length")
    pg5.evaluate(SWIPE, [4, -120, 8]); pg5.wait_for_timeout(500)
    check("Umgestellte Richtung wirkt",
          pg5.evaluate("() => JSON.parse("
                       "localStorage.getItem('rbf26.fav')||'[]').length") == fav0 + 1)

    pg5.click("#btn-menu"); pg5.wait_for_timeout(300)
    pg5.uncheck("#sw-on")
    pg5.keyboard.press("Escape"); pg5.wait_for_timeout(300)
    pg5.evaluate(SWIPE, [5, -120, 8]); pg5.wait_for_timeout(400)
    check("Abgeschaltet passiert nichts",
          pg5.evaluate("() => document.querySelector('#swipe').hidden"))

    pg5.click("#btn-menu"); pg5.wait_for_timeout(300)
    pg5.check("#sw-on")
    pg5.keyboard.press("Escape"); pg5.wait_for_timeout(300)
    pg5.evaluate(SWIPE, [6, 120, 8]); pg5.wait_for_timeout(500)
    check("Zurueck schliesst die Schnellbewertung",
          pg5.evaluate("() => document.querySelector('#quick').open"))
    pg5.go_back(); pg5.wait_for_timeout(500)
    check("Und die App laeuft weiter",
          pg5.evaluate("() => !document.querySelector('#quick').open")
          and pg5.locator(".row").count() > 0)
    check("Keine JS-Fehler beim Wischen", not err5, str(err5[:2]))

    # --- Die beiden Fehler aus den Handy-Screenshots ---

    # 1. Eine gesetzte Note war in der Schnellbewertung UNSICHTBAR: der Knopf
    #    hatte data-qr, das CSS zielt auf data-r. Damit griff nur die
    #    Textfarbe fuer "gewaehlt" (dunkel) und nicht der farbige Grund -
    #    dunkel auf dunkel.
    pg5.evaluate(SWIPE, [8, 120, 8]); pg5.wait_for_timeout(500)
    pg5.locator('#quick-rate button[data-r="2"]').click(); pg5.wait_for_timeout(400)
    pg5.evaluate(SWIPE, [8, 120, 8]); pg5.wait_for_timeout(500)
    look = pg5.evaluate("""() => {
      const b = document.querySelector('#quick-rate button[data-r="2"]');
      const plain = document.querySelector('#quick-rate button[data-r="4"]');
      const s = getComputedStyle(b);
      return { pressed: b.getAttribute('aria-pressed'), bg: s.backgroundColor,
               farbe: s.color, andere: getComputedStyle(plain).backgroundColor };
    }""")
    check("Gesetzte Note ist in der Schnellbewertung gesetzt",
          look["pressed"] == "true", look)
    check("Und hat einen eigenen farbigen Grund",
          look["bg"] != look["andere"], f"{look['bg']} gegen {look['andere']}")
    pg5.keyboard.press("Escape"); pg5.wait_for_timeout(300)

    # 2. Die Wischanzeige klebte an einer alten Bildschirmposition, weil sie
    #    nur beim Beruehren vermessen wurde. Eine Geste beginnt aber oft
    #    senkrecht - der Browser scrollt noch, und danach lag das Feld ueber
    #    einer voelligt anderen Zeile.
    aligned = pg5.evaluate("""() => {
      const row = document.querySelectorAll('.row')[10];
      const fire = (type, x, y) => {
        const t = new Touch({ identifier: 1, target: row, clientX: x,
                              clientY: y, pageX: x, pageY: y });
        const empty = type === 'touchend';
        row.dispatchEvent(new TouchEvent(type, { bubbles: true,
          cancelable: true, touches: empty ? [] : [t],
          targetTouches: empty ? [] : [t], changedTouches: [t] }));
      };
      const r0 = row.getBoundingClientRect();
      const y = r0.top + r0.height / 2;
      fire('touchstart', r0.left + 40, y);
      // Die Seite rutscht unter dem Finger weg. Der Finger selbst bleibt, wo
      // er ist - clientY zaehlt vom Fensterrand, nicht vom Dokument. Genau
      // deshalb bemerkt die Richtungserkennung hier KEINE senkrechte
      // Bewegung, und die Zeile ist trotzdem verschoben.
      window.scrollBy(0, 140);
      for (let i = 1; i <= 8; i++) fire('touchmove', r0.left + 40 + i * 15, y);
      const box = document.querySelector('#swipe').getBoundingClientRect();
      const rowNow = row.getBoundingClientRect();
      fire('touchend', r0.left + 160, y);
      return Math.abs(box.top - rowNow.top);
    }""")
    check("Wischanzeige liegt auch nach Scrollen auf der Zeile",
          aligned < 2, f"{aligned:.1f} px daneben")
    check("Nach der Geste bleibt keine Zeile verschoben",
          pg5.evaluate("() => document.querySelectorAll('.row.swiping').length") == 0
          and pg5.evaluate("() => document.querySelector('#swipe').hidden"))
    # Die Geste war weit genug und hat die Schnellbewertung geoeffnet - die
    # muss weg, sonst faengt sie die naechsten Klicks ab.
    if pg5.evaluate("() => document.querySelector('#quick').open"):
        pg5.keyboard.press("Escape"); pg5.wait_for_timeout(300)

    # --- Geschwindigkeit: eine Note darf nicht die ganze Liste neu bauen ---
    # Geprueft wird die Eigenschaft, nicht die Millisekunden: bleibt eine
    # FREMDE Zeile dasselbe DOM-Element, wurde nicht alles neu gebaut. Ein
    # voller Neuaufbau kostete gemessen 1139 ms auf gebremster CPU.
    # Nach einem Wisch sperrt die App den Klick kurz - abwarten, sonst
    # verschluckt sie den Tipper des Tests.
    pg5.evaluate("() => scrollTo({ top: 0, behavior: 'instant' })")
    pg5.wait_for_timeout(600)
    pg5.evaluate("() => { document.querySelectorAll('.row')[20].dataset.probe = 'x'; }")
    pg5.locator(".row").nth(12).locator(".row-time").click()
    pg5.wait_for_selector("#detail .rate")
    pg5.locator("#detail .rate button[data-r='3']").click()
    pg5.wait_for_timeout(300)
    check("Note aendern baut die Liste NICHT neu",
          pg5.evaluate("() => document.querySelectorAll('.row')[20]"
                       ".dataset.probe === 'x'"))
    pg5.keyboard.press("Escape"); pg5.wait_for_timeout(300)

    # Mit aktivem Notenfilter MUSS neu gebaut werden - die Zeile kann ja
    # herausfallen. Sonst bliebe eine Zeile stehen, die nicht mehr passt.
    pg5.click("#f-rate"); pg5.wait_for_timeout(300)
    pg5.locator('#ratebox .chip[data-rate="3"]').click(); pg5.wait_for_timeout(400)
    pg5.evaluate("() => { const r = document.querySelectorAll('.row')[0];"
                 " if (r) r.dataset.probe2 = 'y'; }")
    pg5.locator(".row").first.locator(".row-time").click()
    pg5.wait_for_selector("#detail .rate")
    pg5.locator("#detail .rate button[data-r='5']").click()
    pg5.wait_for_timeout(400)
    pg5.keyboard.press("Escape"); pg5.wait_for_timeout(300)
    check("Mit Notenfilter wird die Liste neu gebaut",
          pg5.evaluate("() => { const r = document.querySelectorAll('.row')[0];"
                       " return !r || r.dataset.probe2 !== 'y'; }"))
    pg5.locator('#ratebox .chip[data-rate="3"]').click()
    pg5.click("#f-rate"); pg5.wait_for_timeout(300)

    # Offscreen-Zeilen werden vom Browser uebersprungen - ohne das dauert ein
    # Neuaufbau fast eine Sekunde.
    cv = pg5.evaluate("""() => {
      const s = getComputedStyle(document.querySelector('.row'));
      return { cv: s.contentVisibility, size: s.containIntrinsicSize };
    }""")
    check("Zeilen ausserhalb des Bildschirms werden uebersprungen",
          cv["cv"] == "auto" and "80px" in cv["size"], cv)
    ctx5.close()

    real = [e for e in errors if "openstreetmap" not in e.lower()
            and "tile" not in e.lower() and "ERR_" not in e
            and e not in csp]
    check("Keine JS-Fehler", not real, str(real[:3]))
    r404 = [u for u in requested404]
    check("Keine 404 auf eigene Dateien", not r404, str(r404[:4]))
    b.close()

print("\n" + ("ALLE PRUEFUNGEN BESTANDEN" if not FAILS else f"FEHLGESCHLAGEN: {FAILS}"))
sys.exit(1 if FAILS else 0)
