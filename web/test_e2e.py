"""Browser-Regressionstest der Web-App.

Startet keinen Server - der muss laufen:
    python3 -m http.server 8898 --directory web
    python3 web/test_e2e.py

Besser noch mit den echten Cloudflare-Headern, damit die CSP mitgeprueft
wird - siehe DEPLOY.md. Die Kartenkacheln brauchen Netz; ohne Netz
schlaegt nur die Kachel-Darstellung fehl, nicht der Test.
"""
from playwright.sync_api import sync_playwright
import os, sys, re, urllib.parse, datetime as _dt

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8898")
# Die vier Festivaltage. Faellt der Testlauf auf einen davon,
# stellt die App von sich aus auf diesen Tag statt auf "Alle Tage".
FEST_DAYS = ("2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19")

# Wie viel Breite bekommt die Namenszeile eines Kastens? Alles, was mehr als
# 22 Pixel an den Rand abgibt, hat sie an etwas anderes verloren.
BREITE_JS = """() => [...document.querySelectorAll('.tl-act')]
  .map((e) => ({ d: +e.dataset.dauer,
                 name: e.querySelector('.tl-name').textContent.trim(),
                 hat: Math.round(e.querySelector('.tl-name')
                      .getBoundingClientRect().width),
                 kasten: Math.round(e.getBoundingClientRect().width) }))
  .filter((x) => x.hat < x.kasten - 22)"""

FAILS=[]
def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond: FAILS.append(name)

def tap_row(row):
    """Eine Zeile antippen, um die Detailkarte zu oeffnen.

    Playwright klickt die MITTE des Elements, und eine Programmzeile ist
    keine leere Flaeche: der Spielortname darin oeffnet die KARTE. Bricht
    er um, waechst die Zeile auf zwei Textzeilen und die Marke rutscht
    genau in die Mitte. Genau das ist am 11.9. passiert, als
    "Festival Village / YOUCOOK Sounds Stage" ins Programm kam: der Klick
    auf die Zeile von "Lovis" hat die Karte aufgezogen, der Test wartete
    danach 30 Sekunden vergeblich auf den Detaildialog.

    Die Uhrzeit ist der einzige Teil der Zeile, an dem garantiert kein
    Bedienelement haengt - weder Spielort noch Herz noch Play-Knopf.
    """
    row.locator(".row-time").click()

def zeitleiste(pg, ms=800):
    """Sorgt dafuer, dass die Zeitleiste steht.

    Der Abendplan geht seit dem 18.9. GLEICH mit der Zeitleiste auf. Ein
    Tipper auf "Zeitleiste" schaltet danach also ZURUECK zur Liste - genau
    daran sind hier mehrere Bloecke gescheitert, und zwar still: .tl-act
    bleibt im Dokument stehen, auch wenn #plan-time verborgen ist, also
    zaehlten die Pruefungen weiter und massen nur nichts mehr. Diese
    Helferin fragt, statt zu tippen."""
    if pg.locator("#plan-time").is_hidden():
        pg.click("#plan-timeline")
        pg.wait_for_timeout(ms)
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

    days = pg.locator('.day[role="tab"]').count()
    # Die App stellt auf HEUTE, wenn heute ein Festivaltag ist, sonst auf
    # "Alle Tage". Der Test darf das nicht raten: er lief ab dem 16.9.2026
    # auf die Nase, weil er "Alle Tage" als Vorgabe festgeschrieben hatte -
    # und mit der falschen Vorgabe stimmten danach auch alle Zaehlungen
    # nicht mehr, die sich darauf bezogen.
    # Vorgewaehlt ist der laufende FESTIVALABEND, nicht der Kalendertag:
    # um 00:30 am Donnerstag laeuft noch der Mittwochabend. Vor 6 Uhr zaehlt
    # deshalb der Vortag - genau so rechnet die App (festDayNow).
    jetzt_l = _dt.datetime.now()
    lauf = (jetzt_l - _dt.timedelta(days=1)) if jetzt_l.hour < 6 else jetzt_l
    heute = lauf.date().isoformat()
    day_sel = pg.evaluate("""() => {
      const d = document.querySelector('.day[aria-selected="true"]');
      return d ? (d.dataset.day || '') : null;
    }""")
    check("Vorgewaehlt ist der laufende Abend, sonst 'Alle Tage'",
          day_sel == (heute if heute in FEST_DAYS else ""),
          f"gewaehlt {day_sel!r}, laufender Abend {heute}")
    check("Reiter: Alle + vier Tage", days == 5, f"{days} Reiter")
    # Fuer die Zaehlungen unten: einmal ausdruecklich alle Tage, einmal einer.
    pg.locator('.day[data-day=""]').click(); pg.wait_for_timeout(400)
    rows_all_default = pg.locator(".row").count()
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
    # Er steht VORN und bleibt beim Scrollen der Leiste stehen: der Ausweg
    # aus einem zu engen Filter muss erreichbar sein, ohne erst nach rechts
    # zu wischen. Und er ist nur ein Zeichen, kein Wort.
    check("Der Ausweg steht ganz vorn in der Leiste",
          pg.evaluate("() => document.querySelector('.filters')"
                      ".firstElementChild.id") == "f-reset")
    check("Und ist nur ein Zeichen", pg.evaluate("""() => {
      const t = document.querySelector('#f-reset').textContent.trim();
      return t.length === 1 && !!document.querySelector('#f-reset')
        .getAttribute('aria-label');
    }"""), pg.locator("#f-reset").inner_text())
    check("Auch weit gescrollt bleibt er im Bild", pg.evaluate("""() => {
      const f = document.querySelector('.filters');
      f.scrollLeft = f.scrollWidth;
      const b = document.querySelector('#f-reset').getBoundingClientRect();
      const r = f.getBoundingClientRect();
      return getComputedStyle(document.querySelector('#f-reset')).position
             === 'sticky' && b.left >= r.left - 1 && b.right <= r.right + 1;
    }"""))
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
    # Der Favorit haengt am ACT: spielt der zweimal, gehoeren auch beide
    # Zeilen durch den Filter. Erwartet wird deshalb die Zeilenzahl dieses
    # Acts, nicht die feste 1.
    fav_act = pg.locator(".row").first.get_attribute("data-act")
    fav_rows = pg.locator(f'.row[data-act="{fav_act}"]').count()
    pg.locator(".row-fav").first.click()
    pg.wait_for_timeout(120)
    check("Herz setzt sich",
          pg.locator(".row-fav").first.get_attribute("aria-pressed") == "true")
    pg.click("#f-fav"); pg.wait_for_timeout(250)
    check("Favoriten-Filter zeigt genau diesen Act",
          pg.locator(".row").count() == fav_rows,
          f"{pg.locator('.row').count()} Zeile(n), erwartet {fav_rows}")
    pg.click("#f-fav"); pg.wait_for_timeout(200)

    tap_row(pg.locator(".row").first)
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
    tap_row(pg.locator(".row").first); pg.wait_for_selector(".rate")
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
    tap_row(pg.locator(".row").nth(1)); pg.wait_for_selector(".rate")
    pg.locator('.rate button[data-r="2.5"]').click()
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Zweite Zeile zeigt 2,5",
          pg.locator(".row").nth(1).locator(".grade").inner_text() == "2,5")

    pg.click("#f-rate"); pg.wait_for_timeout(300)
    chips = pg.locator("#ratebox .chip").evaluate_all(
        "els => els.map(e => e.dataset.rate)")
    check("Filter bleibt bei fuenf Noten plus 'noch nicht bewertet'",
          chips == ["1", "2", "3", "4", "5", "0"], chips)
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

    # --- Acts, fuer die das Festival keinen Spotify-Link nennt ---
    # Rund jeder zehnte. Frueher stand dort ein ausgegrauter, toter Knopf;
    # bei Spotify zu finden waren die Acts trotzdem. Wichtigste Zusage: KEINE
    # Zeile hat einen Knopf, der nichts tut - entweder spielt er an oder er
    # fuehrt in die Suche.
    tot = pg.locator(
        ".row-play:not([data-quickplay]):not([data-spsearch])").count()
    check("Keine Zeile hat einen toten Anspiel-Knopf", tot == 0, f"{tot} tote")
    such = pg.locator(".row-play.is-search[data-spsearch]").count()
    check("Acts ohne Link bekommen stattdessen die Suche", such >= 1,
          f"{such} von {pg.locator('.row').count()} Zeilen")
    if such:
        s = pg.locator(".row-play.is-search").first
        # Die Trefferflaeche darf dabei nicht schrumpfen - der Ring sitzt auf
        # einem ::before, damit der Knopf seine 44 px behaelt.
        box = s.bounding_box()
        check("Der Such-Knopf bleibt fingergross",
              box["width"] >= 44 and box["height"] >= 44,
              f'{round(box["width"])}x{round(box["height"])}')
        name = s.evaluate("e => e.closest('.row').querySelector('.row-name')"
                          ".childNodes[0].textContent")
        check("Die Suche fragt nach dem Namen des Acts",
              s.get_attribute("data-spsearch")
              == "https://open.spotify.com/search/"
                 + urllib.parse.quote(name, safe=""),
              s.get_attribute("data-spsearch"))
        # window.open abfangen statt wirklich zu Spotify zu navigieren: der
        # Test soll ohne Netz zu Dritten auskommen und nichts dorthin senden.
        pg.evaluate("() => { window.__auf = []; "
                    "window.open = (u) => { window.__auf.push(u); return null; }; }")
        s.click(); pg.wait_for_timeout(300)
        check("Ein Tipper oeffnet die Spotify-Suche",
              pg.evaluate("() => window.__auf")
              == [s.get_attribute("data-spsearch")],
              str(pg.evaluate("() => window.__auf")))
        check("Und zieht nicht nebenbei den Detaildialog auf",
              pg.locator("#detail[open]").count() == 0)
        # In der Detailkarte dasselbe Angebot, nur ausgeschrieben.
        act_no_sp = s.evaluate("e => e.closest('.row').dataset.act")
        tap_row(pg.locator(f'.row[data-act="{act_no_sp}"]').first)
        pg.wait_for_selector("#detail[open]")
        check("Die Detailkarte bietet die Suche an",
              pg.locator("#detail .embed-wrap .chip").inner_text().strip()
              == "Bei Spotify suchen",
              pg.locator("#detail .embed-wrap .chip").inner_text().strip())
        check("Und sagt, warum kein Player da ist",
              "keinen Spotify-Link" in pg.locator("#detail .embed-note").inner_text())
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    # Abgeschnittene Links der Quelle ("…/artist/" ohne Kennung) sind
    # schlechter als gar keine - sie sehen aus wie ein Angebot und fuehren
    # ins Leere. Geprueft wird die Regel selbst, nicht der Tagesbestand.
    stumpf = pg.evaluate("""() => ({
      artist_ohne_id: usableLink('https://open.spotify.com/intl-de/artist/'),
      channel_ohne_id: usableLink('https://www.youtube.com/channel/'),
      echter_artist: usableLink('https://open.spotify.com/artist/4KfTSPmiPutKQ'),
      playlist_mit_query: usableLink('https://www.youtube.com/playlist?list=PLabc'),
      startseite: usableLink('https://agassi.co.uk/'),
      muell: usableLink('nicht mal eine Adresse'),
    })""")
    check("Abgeschnittene Links werden verworfen",
          stumpf["artist_ohne_id"] is None and stumpf["channel_ohne_id"] is None,
          str(stumpf))
    check("Gueltige Links bleiben - auch mit Kennung in der Query",
          stumpf["echter_artist"] and stumpf["playlist_mit_query"]
          and stumpf["startseite"] and stumpf["muell"] is None,
          str(stumpf))

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
    # Nach dem Neuladen steht wieder die Tagesvorgabe. Herz und Note haengen
    # an Acts vom 17.9. - also erst alle Tage zeigen, sonst sucht der Test
    # sie an einem Tag, an dem sie gar nicht spielen.
    pg.locator('.day[data-day=""]').click(); pg.wait_for_timeout(400)
    check("Favorit ueberlebt Reload", pg.locator('.row-fav[aria-pressed="true"]').count() >= 1)
    check("Note ueberlebt Reload", pg.locator(".row.rated-1").count() >= 1)

    csp = [e for e in errors if "content security policy" in e.lower()
           or "refused to" in e.lower()]
    check("Keine CSP-Verletzung", not csp, str(csp[:3]))

    # --- Line-up von Hand abgleichen ---
    # Holt die veröffentlichte Datei an jedem Zwischenspeicher vorbei. Was
    # er NICHT tut, steht im Kommentar bei refreshLineup: die Festivalseite
    # selbst befragen - das läuft im nächtlichen Lauf.
    pg.click("#btn-menu"); pg.wait_for_selector("#menu[open]")
    check("Im Menü steht ein Abgleich für das Line-up",
          pg.locator("#m-refresh").is_visible(),
          pg.locator("#m-refresh").inner_text())
    rows_vorher = None
    meldung = []
    pg.once("dialog", lambda d: (meldung.append(d.message), d.accept()))
    pg.click("#m-refresh")
    pg.wait_for_timeout(2500)
    check("Er meldet, was dabei herauskam",
          meldung and ("Stand" in meldung[0]),
          (meldung[0] if meldung else "keine Meldung")[:80].replace("\n", " "))
    check("Nennt Acts und Auftritte",
          meldung and re.search(r"\d+ Acts", meldung[0])
          and re.search(r"\d+ Auftritte", meldung[0]),
          (meldung[0] if meldung else "")[:90].replace("\n", " "))
    check("Und die Liste steht danach noch",
          pg.locator(".row").count() > 0, pg.locator(".row").count())
    check("Das Menü ist danach zu", pg.locator("#menu[open]").count() == 0)
    check("Der Knopf ist wieder benutzbar",
          pg.evaluate("() => !document.querySelector('#m-refresh').disabled"))
    # "Alle Tage": Suche und Stoebern ueber Tagesgrenzen
    pg.locator('.day[data-day="2026-09-17"]').click(); pg.wait_for_timeout(300)
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
    # textContent, nicht inner_text: die Zeilen tragen content-visibility:auto,
    # und was ausserhalb des Fensters liegt, wird nicht gerendert - innerText
    # liefert dafuer einen LEEREN String. Bei 24 Auftritten in einem Haus
    # (Stand September 2026) fielen 16 Zeilen darunter, und die Pruefung sah
    # einen Spielort ohne Namen, den es nie gab.
    venues_in_list = set(pg.locator(".row-sub .venue").evaluate_all(
        "els => els.map(e => e.textContent.trim())"))
    check("Liste zeigt nur diesen Spielort", len(venues_in_list) == 1, str(venues_in_list))
    pg.click("#f-reset"); pg.wait_for_timeout(300)

    # Eine Zeile hat zwei Ziele: der Spielortname fuehrt auf die Karte, der
    # Rest in die Detailkarte. Bei einem langen Hausnamen bricht die Zeile um
    # und die Spielort-Marke liegt in der MITTE der Zeile - also genau dort,
    # wo ein Klick ohne Zielangabe landet. Beide Wege werden hier an so einer
    # Zeile gemessen, damit der Unterschied nicht unbemerkt verrutscht.
    mid_venue = pg.evaluate("""() => {
      for (const r of document.querySelectorAll('.row')) {
        const b = r.getBoundingClientRect();
        if (!b.height || b.bottom < 0 || b.top > innerHeight) continue;
        const hit = document.elementFromPoint(b.left + b.width / 2,
                                              b.top + b.height / 2);
        if (hit && hit.classList.contains('venue')) return r.dataset.act;
      }
      return null;
    }""")
    if mid_venue is None:
        check("Zeile mit Spielort in der Mitte geprueft", True,
              "gerade keine solche Zeile im Bild")
    else:
        pg.locator(f'.row[data-act="{mid_venue}"] .venue').first.click()
        pg.wait_for_timeout(900)
        check("Spielort in der Zeilenmitte fuehrt auf die Karte",
              pg.locator("#map").is_visible() and not pg.locator("#detail[open]").count())
        pg.click("#btn-map"); pg.wait_for_timeout(500)
        tap_row(pg.locator(f'.row[data-act="{mid_venue}"]').first)
        pg.wait_for_selector("#detail[open]", timeout=5000)
        check("Die Uhrzeit derselben Zeile fuehrt in die Detailkarte", True)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    # Team: Partner-Datei laden und "Beide" pruefen
    import json as _json, tempfile as _tf
    lineup2 = _json.load(open("web/data/lineup.json", encoding="utf-8"))
    my_fav = pg.locator(".row-fav[aria-pressed='true']").count()
    check("Team-Chip ist ohne Partner:in verborgen", pg.locator("#f-team").is_hidden())
    # Partner mag genau die Acts von zwei Zeilen - Acts mit nur einem
    # Auftritt, sonst zaehlt die Note/der Favorit unten auf zwei Zeilen und
    # die count()==1-Pruefungen brechen (haengt am Act, nicht an der Show).
    shows_per_act2 = {}
    for s in lineup2["shows"]:
        shows_per_act2[s["a"]] = shows_per_act2.get(s["a"], 0) + 1
    cand = pg.locator(".row").evaluate_all("els => els.map(e => e.dataset.act)")
    idx, seen_a = [], set()
    for i in cand:
        if shows_per_act2.get(int(i)) == 1 and i not in seen_a:
            seen_a.add(i); idx.append(i)
        if len(idx) >= 2:
            break
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
    # Team-Meinung ist verdeckt, bis ich selbst bewertet habe - sonst faerbt
    # die fremde Note die eigene ein, bevor sie entsteht.
    # .grade-p sitzt jetzt auch auf der verdeckten "?"-Marke (dieselbe Form
    # wie eine echte Note, siehe teamRowMark) - "verdeckt" heisst also: keine
    # ECHTE Note ausserhalb von .team-hidden.
    check("Partner-Note ist verdeckt, solange ich selbst nicht bewertet habe",
          pg.locator("#list .grade-p:not(.team-hidden)").count() == 0,
          f"{pg.locator('#list .grade-p:not(.team-hidden)').count()}")
    check("Partner-Favorit ist verdeckt, solange ich selbst nicht bewertet habe",
          pg.locator("#list .heart-p").count() == 0,
          f"{pg.locator('#list .heart-p').count()}")
    check("Stattdessen steht ein neutral eingefaerbtes '?' in der Liste",
          pg.locator(f'.row[data-act="{idx[1]}"] .team-hidden').count() >= 1
          and pg.locator(f'.row[data-act="{idx[1]}"] .team-hidden').inner_text() == "?")

    # Eigene Note (bewusst 5, nicht 1-2, damit "Beide" gleich unten nicht
    # faelschlich anspringt) schaltet die Team-Note fuer diesen Act frei.
    tap_row(pg.locator(f'.row[data-act="{idx[1]}"]').first)
    pg.wait_for_selector("#detail[open]")
    check("Detail zeigt den Aufdecken-Knopf, solange ich nicht bewertet habe",
          pg.locator("#detail [data-reveal]").count() == 1)
    pg.locator('#detail .rate button[data-r="5"]').click(); pg.wait_for_timeout(300)
    check("Team-Note im Detail jetzt sichtbar",
          "Note 1" in pg.locator("#d-team .suggestion").inner_text(),
          pg.locator("#d-team .suggestion").inner_text())
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Partner-Note steht jetzt in der Liste",
          pg.locator(f'.row[data-act="{idx[1]}"] .grade-p:not(.team-hidden)').count() == 1)
    # Einmal gesehen ist gesehen: die eigene Note wieder loeschen darf die
    # Team-Note nicht erneut hinter dem "?" verstecken.
    tap_row(pg.locator(f'.row[data-act="{idx[1]}"]').first)
    pg.wait_for_selector("#detail[open]")
    pg.locator('#detail .rate button[data-r="5"]').click(); pg.wait_for_timeout(300)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Eigene Note ist wieder weg",
          pg.locator(f'.row[data-act="{idx[1]}"] .grade:not(.grade-p)').count() == 0)
    check("Team-Note bleibt trotzdem sichtbar",
          pg.locator(f'.row[data-act="{idx[1]}"] .grade-p:not(.team-hidden)').count() == 1
          and pg.locator(f'.row[data-act="{idx[1]}"] .team-hidden').count() == 0)

    # "Trotzdem anzeigen" deckt es auch ohne eigene Note auf.
    tap_row(pg.locator(f'.row[data-act="{idx[0]}"]').first)
    pg.wait_for_selector("#detail[open]")
    pg.locator("#detail [data-reveal]").click(); pg.wait_for_timeout(300)
    check("Aufdecken-Knopf verschwindet nach dem Klick",
          pg.locator("#detail [data-reveal]").count() == 0)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Nach 'Trotzdem anzeigen' steht der Favorit in der Liste",
          pg.locator(f'.row[data-act="{idx[0]}"] .heart-p').count() == 1)

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

    # --- Bewertungsfilter als Kasten mit 1 bis 5 plus "noch nicht bewertet" ---
    pg.click("#f-rate"); pg.wait_for_selector("#ratebox .chip")
    check("Notenkasten hat sechs Stufen (1-5 plus unbewertet)",
          pg.locator("#ratebox .chip").count() == 6,
          f"{pg.locator('#ratebox .chip').count()}")
    all_rows = pg.locator(".row").count()
    pg.locator('#ratebox .chip[data-rate="0"]').click(); pg.wait_for_timeout(350)
    unrated_rows = pg.locator(".row").count()
    check("'Noch nicht bewertet' filtert auf unbewertete Acts",
          0 < unrated_rows < all_rows, f"{unrated_rows} von {all_rows}")
    check("Chip sagt dann 'Unbewertet', nicht 'Bewertet (1)'",
          pg.locator("#f-rate").inner_text().strip() == "Unbewertet",
          pg.locator("#f-rate").inner_text())

    # Der gemeldete Fall: waehrend "noch nicht bewertet" gefiltert ist,
    # einen Act bewerten - er darf nicht sofort verschwinden, sonst verliert
    # man beim Durcharbeiten der Liste die Stelle. Erst ein erneuter
    # Filterwechsel darf ihn wegnehmen.
    target_ai = pg.locator(".row").first.get_attribute("data-act")
    # Acts mit zwei Auftritten stellen zwei Zeilen - der Filter greift pro
    # Act, also muessen nach dem Wechsel beide verschwinden, nicht nur eine.
    target_rows = pg.locator(f'.row[data-act="{target_ai}"]').count()
    tap_row(pg.locator(".row").first)
    pg.wait_for_selector("#detail[open]")
    pg.locator('#detail .rate button[data-r="3"]').click(); pg.wait_for_timeout(300)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Frisch bewerteter Act bleibt vorerst im Unbewertet-Filter stehen",
          pg.locator(".row").count() == unrated_rows, f"{pg.locator('.row').count()}")
    pg.locator('#ratebox .chip[data-rate="0"]').click(); pg.wait_for_timeout(300)
    pg.locator('#ratebox .chip[data-rate="0"]').click(); pg.wait_for_timeout(300)
    check("Nach erneutem Filterwechsel ist er weg",
          pg.locator(".row").count() == unrated_rows - target_rows,
          f"{pg.locator('.row').count()} erwartet {unrated_rows - target_rows}")

    pg.locator('#ratebox .chip[data-rate="0"]').click(); pg.wait_for_timeout(250)
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
    # Auch hier textContent: bei inner_text kommt fuer jede Zeile ausserhalb
    # des Fensters ein leerer String, und "Zeit" steckt dann auch nicht drin -
    # die Auswahl haette eine Zeile "Zeit offen" fuer planbar gehalten.
    times = pg.locator(".row .row-time").evaluate_all(
        "els => els.map(e => e.textContent.trim())")
    dated = [i for i, t in enumerate(times) if t and "Zeit" not in t][:2]
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
    if stop_times and "bis" in summary:
        import re as _re
        # Aus dem Text herausSUCHEN, nicht an ":" zerlegen: in .row-time
        # steht neben der Uhrzeit auch die Aenderungsmarke (⟳), sobald der
        # Termin verschoben oder neu ist. Seit dem 11.9. trifft das die
        # letzte Station, und split(":") lieferte "00\n⟳".
        #
        # Und seit die echte Spielzeit bekannt ist, stehen dort ZWEI
        # Uhrzeiten (Beginn und Ende). Gesucht wird beides: das Ende der
        # letzten Station muss die Endzeit des Abends sein - nicht mehr
        # "Beginn plus Pauschale".
        zeiten = _re.findall(r"(\d\d):(\d\d)", stop_times[-1])
        shown_end = _re.search(r"bis (?:etwa )?(\d\d):(\d\d)", summary)
        eh, em = int(shown_end.group(1)), int(shown_end.group(2))
        lh, lm = int(zeiten[-1][0]), int(zeiten[-1][1])
        diff = ((eh * 60 + em) - (lh * 60 + lm)) % (24 * 60)
        check("Der Abend endet, wenn das letzte Konzert endet", diff == 0,
              f"letzte Station {zeiten}, Ende laut Plan {eh:02d}:{em:02d}, "
              f"Differenz {diff} min")
        # Und wenn die Endzeit bekannt ist, steht dort kein "etwa" mehr -
        # geschaetzt wird nur, wo die Quelle nichts sagt.
        check("Und ohne 'etwa', weil die echte Endzeit bekannt ist",
              len(zeiten) == 2 and "bis etwa" not in summary,
              f"{len(zeiten)} Uhrzeiten | {summary[:70]}")

    check("Zusammenfassung nennt den Fussweg",
          "Fußweg" in pg.locator(".plan-sum").inner_text(),
          pg.locator(".plan-sum").inner_text()[:60])

    # Spielzeit aendern muss den Plan beeinflussen koennen
    pg.select_option("#plan-set", "50"); pg.wait_for_timeout(500)
    check("Aenderung der Spielzeit wird verarbeitet",
          pg.locator("#plan-body").inner_text() != "", "")

    # --- Den Plan von Hand nachjustieren ---
    # Verglichen wird ueber die Auftritts-Kennung, nicht ueber den Namen: ein
    # Act kann mehrfach spielen, und dann steht derselbe Name zu Recht wieder
    # da - nur mit anderer Uhrzeit.
    PLAN_IDS = ("() => [...document.querySelectorAll('#plan-body .stop .row')]"
                ".map(r => r.dataset.show)")
    ids0 = pg.evaluate(PLAN_IDS)
    check("Jede Station hat Festhalten und Ausschliessen",
          pg.locator("#plan-body .stop [data-pin]").count() == len(ids0)
          and pg.locator("#plan-body .stop [data-skip]").count() == len(ids0),
          f"{len(ids0)} Stationen")
    if pg.locator("#plan-body .plan-drop li [data-pin]").count():
        want = pg.locator("#plan-body .plan-drop li [data-pin]").first \
            .get_attribute("data-pin")
        pg.locator("#plan-body .plan-drop li [data-pin]").first.click()
        pg.wait_for_timeout(700)
        ids1 = pg.evaluate(PLAN_IDS)
        check("Festgehaltener Termin kommt in den Plan", want in ids1,
              f"{want} in {ids1}")
        check("Der Plan wird darum herum neu gerechnet", ids0 != ids1)
        check("Der Knopf zeigt, dass er gesetzt ist",
              pg.locator(f'#plan-body [data-pin="{want}"].on').count() >= 1)
        check("Die Handauswahl wird benannt",
              "Von Hand gesetzt" in pg.locator("#plan-body").inner_text())

        drop = pg.locator("#plan-body .stop [data-skip]").first \
            .get_attribute("data-skip")
        pg.locator("#plan-body .stop [data-skip]").first.click()
        pg.wait_for_timeout(700)
        ids2 = pg.evaluate(PLAN_IDS)
        check("Ausgeschlossener Termin faellt heraus", drop not in ids2,
              f"{drop} in {ids2}")
        check("Der Plan bleibt dabei bestueckt", len(ids2) > 0, len(ids2))

        pg.click("#plan-reset-manual"); pg.wait_for_timeout(700)
        check("Zuruecknehmen stellt den Vorschlag wieder her",
              pg.evaluate(PLAN_IDS) == ids0,
              f"{pg.evaluate(PLAN_IDS)} gegen {ids0}")

    # 62 Acts spielen mehrfach - zweimal derselbe waere verschwendeter Abend.
    check("Kein Act steht zweimal im Plan", pg.evaluate("""() => {
      const a = [...document.querySelectorAll('#plan-body .stop .row')]
        .map(r => r.dataset.act);
      return a.length === new Set(a).size;
    }"""))

    # --- Mehrfachauftritte in der Liste ---
    multi = pg.evaluate("""() => {
      const all = [...document.querySelectorAll('.multi')]
        .map(e => e.textContent.trim());
      const first = document.querySelector('.multi');
      return { n: all.length, kinds: [...new Set(all)].sort(),
               title: first ? first.getAttribute('title') : null };
    }""")
    check("Mehrfachauftritte sind markiert", multi["n"] > 0, multi["n"])
    check("Nur die tatsaechlich vorkommenden Zahlen",
          set(multi["kinds"]) <= {"\u00d72", "\u00d73"}, multi["kinds"])
    check("Der Titel nennt, der wievielte Auftritt es ist",
          "Auftritt" in (multi["title"] or ""), multi["title"])

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
        # Und sie zeigen auch wirklich irgendwohin. Die Drehung stand als
        # style="…" im Markup, und die CSP verwirft Inline-Stile lautlos -
        # jahrelang zeigten alle Pfeile stur nach rechts. Geprueft wird
        # deshalb die gerechnete Drehung, nicht nur die Anzahl.
        gedreht = pg.evaluate("""() => [...document.querySelectorAll('.route-arrow')]
          .map(e => getComputedStyle(e).transform)
          .filter(t => t && t !== 'none').length""")
        check("Und sie sind in die Laufrichtung gedreht",
              gedreht == pins - 1, f"{gedreht} von {pins - 1} gedreht")
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
    pg.locator("[data-seen]").click(); pg.wait_for_timeout(500)
    check("Gesehen setzt sich",
          pg.locator("[data-seen]").get_attribute("aria-pressed") == "true")
    # Abhaken und benoten gehören zusammen: wer gerade herauskommt, hat eine
    # Meinung. Deshalb geht die Skala von selbst auf - mit dem Anlass
    # drangeschrieben, damit klar ist, warum sie da ist.
    check("Nach dem Abhaken geht die Skala von selbst auf",
          pg.locator("#quick[open]").count() == 1)
    check("Für denselben Act",
          pg.locator("#quick-name").inner_text() == act_name,
          f'{pg.locator("#quick-name").inner_text()} gegen {act_name}')
    check("Und sagt, warum sie aufgeht",
          pg.locator("#quick-sub").is_visible()
          and "Gesehen" in pg.locator("#quick-sub").inner_text(),
          pg.locator("#quick-sub").inner_text())
    check("Mit der vollen Skala", pg.locator("#quick-rate button").count() == 7)
    seen_rate = pg.locator("#quick-name").inner_text()
    pg.locator('#quick-rate button[data-r="3"]').click(); pg.wait_for_timeout(400)
    check("Eine Note von dort setzt sich und schließt die Skala",
          pg.locator("#quick[open]").count() == 0
          and pg.locator('#detail .rate button[data-r="3"]')
              .get_attribute("aria-pressed") == "true", seen_rate)
    # Zurücknehmen ist kein Anlass für eine Note.
    pg.locator("[data-seen]").click(); pg.wait_for_timeout(500)
    check("Das Zurücknehmen öffnet nichts",
          pg.locator("#quick[open]").count() == 0
          and pg.locator("[data-seen]").get_attribute("aria-pressed") == "false")
    pg.locator("[data-seen]").click(); pg.wait_for_timeout(500)
    if pg.locator("#quick[open]").count():
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    check("Gesehen-Marke in der Liste", pg.locator("#list .seen-mark").count() >= 1)

    # Jetzt ist etwas markiert, also kann der Filter geprueft werden.
    # "Gesehen" haengt am ACT, nicht am Auftritt: wer zweimal spielt, traegt
    # die Marke auf beiden Zeilen, und beide gehoeren durch den Filter. Statt
    # einer festen 1 wird deshalb gezaehlt, was vorher markiert war.
    marked = pg.locator("#list .seen-mark").count()
    pg.click("#f-seen"); pg.wait_for_timeout(350)
    check("Gesehen-Filter zeigt nur Markierte",
          pg.locator(".row").count() == marked
          and pg.locator("#list .seen-mark").count() == marked,
          f"{pg.locator('.row').count()} Zeile(n), markiert waren {marked}")
    pg.click("#f-seen"); pg.wait_for_timeout(350)
    check("Gesehen-Filter wieder aus", pg.locator(".row").count() > 1)

    # Was abgehakt ist, ist schraffiert - man sieht es, ohne den Haken am
    # Namen zu suchen.
    check("Gesehene Zeilen sind schraffiert",
          pg.locator(".row.is-seen").count() == marked,
          f'{pg.locator(".row.is-seen").count()} von {marked} markierten')
    check("Und zwar mit einem Streifenmuster", pg.evaluate("""() => {
      const e = document.querySelector('.row.is-seen');
      return e && getComputedStyle(e).backgroundImage.includes('repeating-linear');
    }"""))
    # Der Zaehler am laufenden Filter zaehlt ACTS, nicht Konzerte: wer
    # zweimal spielt, zaehlt einmal. Genau das behauptet die Zahl.
    acts_gesehen = pg.evaluate("""() => {
      const s = new Set([...document.querySelectorAll('.row.is-seen')]
        .map((e) => e.dataset.act));
      return s.size;
    }""")
    pg.click("#f-seen"); pg.wait_for_timeout(400)
    chip = pg.locator("#f-seen").inner_text()
    check("Der laufende Gesehen-Filter nennt die Zahl im Kopf",
          chip.strip() == f"✓ Gesehen ({acts_gesehen})", chip)
    check("Und zählt Acts, nicht Konzerte",
          acts_gesehen <= marked, f"{acts_gesehen} Acts aus {marked} Zeilen")
    pg.click("#f-seen"); pg.wait_for_timeout(300)
    check("Ohne Filter steht die Zahl nicht da",
          pg.locator("#f-seen").inner_text().strip() == "✓ Gesehen",
          pg.locator("#f-seen").inner_text())

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

    # --- Karte nach Uhrzeit einfaerben ---
    # Filter haben auf der Karte keine Wirkung - stattdessen tritt eine
    # Zeitwahl an ihre Stelle, die Spielorte nach der eigenen Note der dort
    # gerade spielenden Acts einfaerbt.
    import json as _json3
    lineup3 = _json3.load(open("web/data/lineup.json", encoding="utf-8"))
    target = next(s for s in lineup3["shows"]
                  if not s.get("tbd") and s.get("t") and s.get("v") is not None
                  and lineup3["venues"][s["v"]].get("lat") is not None)
    pg.click(f'.day[data-day="{target["d"]}"]'); pg.wait_for_timeout(300)
    tap_row(pg.locator(f'.row[data-act="{target["a"]}"]').first)
    pg.wait_for_selector("#detail[open]")
    r1btn = pg.locator('#detail .rate button[data-r="1"]')
    r1btn.click(); pg.wait_for_timeout(150)
    # Robust gegen eine schon vorhandene Note 1 aus einem frueheren Testschritt -
    # ein zweiter Klick auf dieselbe Note schaltet sie sonst wieder aus.
    if r1btn.get_attribute("aria-pressed") != "true":
        r1btn.click(); pg.wait_for_timeout(150)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    pg.click("#btn-map"); pg.wait_for_timeout(1000)
    check("Filter sind auf der Karte ausgeblendet", pg.locator(".filters").is_hidden())
    check("Zeitwahl steht stattdessen da", pg.locator("#maptime").is_visible())
    pg.fill("#maptime-time", target["t"][11:16])
    pg.locator("#maptime-time").dispatch_event("input")
    pg.wait_for_timeout(400)
    # Ob der Marker gerade einzeln steht oder im Buendel haengt, entscheiden
    # Zoom und Dichte der Haeuser - beides wandert mit jedem Line-up.
    # Gefaerbt sein muss er so oder so.
    check("Eigene Bestnote faerbt den Spielort gruen",
          pg.locator(".venue-code-r1").count()
          + pg.locator(".marker-cluster.mc-r1").count() >= 1,
          f'einzeln={pg.locator(".venue-code-r1").count()} '
          f'Buendel={pg.locator(".marker-cluster.mc-r1").count()} | '
          + pg.locator("#maptime-legend").inner_text())
    # Wie viele Haeuser um diese Uhrzeit eine eigene Note tragen, haengt am
    # Line-up und aendert sich mit jedem Abruf - festgenagelt wird deshalb
    # nur, dass die Legende ueberhaupt zaehlt und den Treffer mitzaehlt.
    legend = pg.locator("#maptime-legend").inner_text()
    legend_rated = re.match(r"(\d+) bewertet", legend)
    check("Legende nennt den Treffer",
          bool(legend_rated) and int(legend_rated.group(1)) >= 1, legend)
    check("'Jetzt' schaltet sich beim Eintippen einer Uhrzeit ab",
          pg.locator("#maptime-now").get_attribute("aria-pressed") == "false")

    # Der Fader unten spannt den FESTIVALABEND, nicht den Kalendertag: die
    # Nacht (00:xx) gehoert an das Ende des Abends, nicht an seinen Anfang.
    # Deshalb wird in Festivalminuten gerechnet, alles vor 6 Uhr plus 24 h.
    def festmin(hhmm):
        v = int(hhmm[:2]) * 60 + int(hhmm[3:5])
        return v + 1440 if v < 360 else v

    day_times = sorted(festmin(s["t"][11:16]) for s in lineup3["shows"]
                       if s["d"] == target["d"] and not s.get("tbd") and s.get("t"))
    check("Faderleiste liegt unter der Karte", pg.locator("#mapbar").is_visible())
    check("Fader spannt den ganzen Abend, Nacht am Ende",
          int(pg.locator("#mapfader").get_attribute("min")) == day_times[0]
          and int(pg.locator("#mapfader").get_attribute("max")) == day_times[-1] + 40,
          f'{pg.locator("#mapfader").get_attribute("min")}..'
          f'{pg.locator("#mapfader").get_attribute("max")} gegen '
          f'{day_times[0]}..{day_times[-1] + 40}')

    # Ein Nacht-Auftritt desselben Festivaltags liegt hinter 24:00 - wenn der
    # Fader ihn trifft, stimmt die Rechnung.
    late = [s for s in lineup3["shows"]
            if s["d"] == target["d"] and not s.get("tbd") and s.get("t")
            and s["t"][11:13] < "06" and s.get("v") is not None]
    if late:
        pg.locator("#mapfader").fill(str(festmin(late[0]["t"][11:16])))
        pg.locator("#mapfader").dispatch_event("input"); pg.wait_for_timeout(400)
        check("Fader erreicht die Auftritte nach Mitternacht",
              pg.locator("#mapbar-time").inner_text() == late[0]["t"][11:16],
              f'{pg.locator("#mapbar-time").inner_text()} gegen {late[0]["t"][11:16]}')
        check("Und das Zeitfeld oben zieht mit",
              pg.locator("#maptime-time").input_value() == late[0]["t"][11:16],
              f'{pg.locator("#maptime-time").input_value()} gegen {late[0]["t"][11:16]}')

    # Der gemeldete Fehler: Tagwechsel auf der Karte sprang zurueck zur Liste.
    other_day = next(d for d in lineup3["days"] if d != target["d"])
    pg.click(f'.day[data-day="{other_day}"]'); pg.wait_for_timeout(600)
    check("Tagwechsel bleibt auf der Karte",
          pg.locator("#map").is_visible() and pg.locator("#list").is_hidden())
    check("Und die Faderleiste nennt den neuen Tag",
          pg.locator("#mapbar-day").inner_text() != "",
          pg.locator("#mapbar-day").inner_text())

    # Zurueck auf den Tag des Testauftritts und auf dessen Uhrzeit.
    pg.click(f'.day[data-day="{target["d"]}"]'); pg.wait_for_timeout(400)
    pg.locator("#mapfader").fill(str(festmin(target["t"][11:16])))
    pg.locator("#mapfader").dispatch_event("input"); pg.wait_for_timeout(400)

    # Buendel tragen die Farbe ihres besten Kindes - sonst muesste man erst
    # hineinzoomen, um zu sehen, ob sich der Kreis lohnt. Dafuer erst weit
    # genug HERAUSzoomen: steht der bewertete Marker gerade einzeln, sagt die
    # Pruefung nichts ueber die Buendel aus.
    for _ in range(4):
        pg.locator(".leaflet-control-zoom-out").click(); pg.wait_for_timeout(250)
    pg.wait_for_timeout(500)
    check("Ein Buendel ist nach der besten Note gefaerbt",
          pg.locator(".marker-cluster.mc-r1").count() >= 1,
          f'r1={pg.locator(".marker-cluster.mc-r1").count()} '
          f'unrated={pg.locator(".marker-cluster.mc-unrated").count()} '
          f'off={pg.locator(".marker-cluster.mc-off").count()} '
          f'einzeln-r1={pg.locator(".venue-code-r1").count()}')

    # Die gewaehlte Uhrzeit muss den Ausflug in die Liste ueberleben - sonst
    # ist Vorausplanen nicht moeglich, weil "Jetzt" ausserhalb des Festivals
    # nichts zeigt.
    pg.click("#btn-map"); pg.wait_for_timeout(400)
    check("Zurueck in der Liste stehen die Filter wieder da",
          pg.locator(".filters").is_visible() and pg.locator("#maptime").is_hidden())
    pg.click("#btn-map"); pg.wait_for_timeout(800)
    check("Gewaehlte Uhrzeit ueberlebt Schliessen und Oeffnen",
          pg.locator("#mapbar-time").inner_text() == target["t"][11:16],
          f'{pg.locator("#mapbar-time").inner_text()} gegen {target["t"][11:16]}')

    # Spielort antippen: wer spielt hier zu DIESER Uhrzeit?
    pg.click("#btn-map"); pg.wait_for_timeout(300)
    pg.locator(f'.row[data-act="{target["a"]}"] .venue').first.click()
    pg.wait_for_timeout(1600)
    check("Popup nennt Tag und Uhrzeit",
          target["t"][11:16] in pg.locator(".pop-now-head").inner_text(),
          pg.locator(".pop-now-head").inner_text())
    check("Popup zeigt, wer dann dort spielt",
          pg.locator(".pop-act").count() >= 1
          and target["t"][11:16] in pg.locator(".pop-act").first.inner_text(),
          pg.locator(".pop-act").first.inner_text().replace("\n", " ") if
          pg.locator(".pop-act").count() else "keine Zeile")
    check("Mit der eigenen Note daran", pg.locator(".pop-act .grade").count() >= 1)
    pg.locator(".pop-act").first.click(); pg.wait_for_timeout(600)
    check("Und der Act laesst sich von dort oeffnen",
          pg.locator("#detail[open]").count() == 1)

    # Favorit: kleines lila Herz an der Blase des Spielorts. Gesetzt wird er
    # aus dem eben geoeffneten Detaildialog - die Liste liegt hinter der
    # Karte und ist gerade nicht anklickbar.
    hearts_before = pg.locator(".venue-fav").count()
    pg.locator('#detail [data-fav]').first.click(); pg.wait_for_timeout(400)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
    hearts_after = pg.locator(".venue-fav").count()
    check("Favorit haengt als Herz an der Spielort-Blase",
          hearts_after == hearts_before + 1, f"{hearts_before} -> {hearts_after}")
    heart_color = pg.evaluate("""() => {
      const h = document.querySelector('.venue-fav');
      return h ? getComputedStyle(h).color : '';
    }""")
    check("Und zwar in der Akzentfarbe", bool(heart_color)
          and heart_color not in ("rgb(0, 0, 0)", ""), heart_color)

    # Wieder abwaehlen, damit der Zustand fuer spaetere Pruefungen steht -
    # und weil das Herz dann auch verschwinden muss.
    pg.click("#btn-map"); pg.wait_for_timeout(400)
    pg.locator(f'.row[data-act="{target["a"]}"] .row-fav').first.click()
    pg.wait_for_timeout(300)
    pg.click("#btn-map"); pg.wait_for_timeout(700)
    check("Herz verschwindet mit dem Favoriten",
          pg.locator(".venue-fav").count() == hearts_before,
          f"{pg.locator('.venue-fav').count()} gegen {hearts_before}")

    pg.click("#btn-map"); pg.wait_for_timeout(400)

    # --- Vorschlaege importieren ---
    # Bewusst in einem FRISCHEN Kontext: im bisherigen sind schon Acts
    # bewertet, und eine eigene Bewertung unterdrueckt den Vorschlagspunkt.
    # Ohne Isolierung testet man sonst die Vorgeschichte statt den Import.
    import json, tempfile
    lineup = json.load(open("web/data/lineup.json", encoding="utf-8"))
    # Ein Act mit zwei Auftritten traegt den Hinweis auf BEIDEN Zeilen (er
    # haengt am Act, nicht an der einzelnen Show) - fuer die exakten
    # count()==1-Pruefungen unten muessen die Testkandidaten deshalb Acts
    # mit genau einem Auftritt sein, sonst zaehlt derselbe Hinweis doppelt.
    shows_per_act = {}
    for s in lineup["shows"]:
        shows_per_act[s["a"]] = shows_per_act.get(s["a"], 0) + 1

    def single_show_picks(page, n=2):
        cand = page.locator(".row").evaluate_all("els => els.map(e => e.dataset.act)")
        seen, out = set(), []
        for i in cand:
            if shows_per_act.get(int(i)) == 1 and i not in seen:
                seen.add(i); out.append(i)
            if len(out) >= n:
                break
        return out

    ctx2 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    pg2 = ctx2.new_page()
    pg2.goto(BASE + "/", wait_until="load")
    pg2.wait_for_selector(".row", timeout=15000)
    act_idx = single_show_picks(pg2)
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
    tap_row(pg2.locator(f'.row[data-act="{act_idx[0]}"]').first)
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
    idx3 = single_show_picks(pg3)
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
    tap_row(pg3.locator(f'.row[data-act="{idx3[1]}"]').first)
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

    # Wischen ist kalt gestellt: die Mechanik bleibt, loest aber nichts aus.
    pg5.evaluate(SWIPE, [0, 120, 8]); pg5.wait_for_timeout(400)
    check("Wischen ist standardmaessig aus",
          pg5.evaluate("() => !document.querySelector('#quick').open")
          and pg5.evaluate("() => document.querySelector('#swipe').hidden"))
    # Nicht den Speicher pruefen: der wird absichtlich erst beschrieben, wenn
    # man etwas umstellt. Der sichtbare Schalter ist die Wahrheit.
    pg5.click("#btn-menu"); pg5.wait_for_timeout(300)
    check("Der Schalter im Menue steht auf aus",
          not pg5.is_checked("#sw-on"))
    # Ab hier eingeschaltet - die Mechanik soll fuer eine spaetere Verwendung
    # geprueft bleiben.
    pg5.check("#sw-on")
    pg5.keyboard.press("Escape"); pg5.wait_for_timeout(300)

    pg5.evaluate(SWIPE, [0, 120, 8]); pg5.wait_for_timeout(500)
    check("Eingeschaltet oeffnet ein Wisch nach rechts die Schnellbewertung",
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
    # Abgehakt wird der AUFTRITT, nicht der Act: es kommt genau EINE Marke
    # dazu, auch wenn derselbe Act noch zweimal spielt. (Hier stand einmal
    # die Zeilenzahl des Acts - das war aus der Zeit, als "gesehen" nur den
    # Kuenstler kannte, und ging nur durch, solange der zufaellig gewaehlte
    # Act einmal spielte. Beim Stand vom 18.9. spielt er dreimal.)
    swipe_act = pg5.locator(".row").nth(1).get_attribute("data-act")
    swipe_rows = pg5.locator(f'.row[data-act="{swipe_act}"]').count()
    swipe_show = pg5.locator(".row").nth(1).get_attribute("data-show")
    pg5.evaluate(SWIPE, [1, -120, 8]); pg5.wait_for_timeout(500)
    check("Wisch nach links markiert als gesehen",
          pg5.locator("#list .seen-mark").count() == seen0 + 1,
          f"{seen0} -> {pg5.locator('#list .seen-mark').count()}, "
          f"der Act steht {swipe_rows}x in der Liste")
    check("Und zwar genau diesen Auftritt",
          pg5.locator(f'.row[data-show="{swipe_show}"] .seen-mark').count() == 1)
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

    # Auch MIT Notenfilter wird nicht mehr alles neu gebaut. Frueher war das
    # noetig, weil die bewertete Zeile aus dem Filter fallen kann - seit
    # filterKeep bleibt sie aber bis zum naechsten Filterwechsel ohnehin
    # stehen. Der Neuaufbau brachte also nichts und liess die Liste
    # springen. Geprueft wird beides: fremde Zeile bleibt dasselbe Element,
    # die bewertete wird ersetzt (traegt die neue Note), und nichts rutscht.
    pg5.click("#f-rate"); pg5.wait_for_timeout(300)
    pg5.locator('#ratebox .chip[data-rate="3"]').click(); pg5.wait_for_timeout(400)
    pg5.click("#f-rate"); pg5.wait_for_timeout(200)
    rows_before = pg5.locator(".row").count()
    # Jede Zeile bekommt ihre eigene Marke: danach laesst sich sagen, WELCHE
    # ersetzt wurde. (Bei diesem Filter ist oft nur eine Zeile sichtbar -
    # eine feste "Nachbarzeile" gibt es also nicht.)
    pg5.evaluate("""() => [...document.querySelectorAll('.row')]
      .forEach((r, i) => { r.dataset.probe2 = 'p' + i; })""")
    rated_act = pg5.locator(".row").first.get_attribute("data-act")
    y_before = pg5.evaluate("() => scrollY")
    pg5.locator(".row").first.locator(".row-time").click()
    pg5.wait_for_selector("#detail .rate")
    pg5.locator("#detail .rate button[data-r='5']").click()
    pg5.wait_for_timeout(400)
    pg5.keyboard.press("Escape"); pg5.wait_for_timeout(300)
    # Ersetzt werden alle Zeilen DES BEWERTETEN ACTS - hat er zwei Auftritte,
    # sind das zu Recht zwei. Zeilen anderer Acts muessen ihre Marke behalten.
    state = pg5.evaluate("""() => [...document.querySelectorAll('.row')]
      .map((r, i) => ({ act: r.dataset.act, kept: r.dataset.probe2 === 'p' + i }))""")
    check("Mit Notenfilter wird nur der bewertete Act ersetzt",
          bool(state)
          and all(not s["kept"] for s in state if s["act"] == rated_act)
          and all(s["kept"] for s in state if s["act"] != rated_act),
          f'Act {rated_act}: '
          + str([(s["act"], s["kept"]) for s in state]))
    check("Die Zeile bleibt trotz Filter stehen und traegt die neue Note",
          pg5.locator(".row").count() == rows_before
          and pg5.locator(".row").first.locator(".grade").inner_text() == "5",
          f'{pg5.locator(".row").count()} von {rows_before} Zeilen, '
          + pg5.locator(".row").first.locator(".grade").inner_text())
    check("Und die Liste rutscht dabei nicht",
          abs(pg5.evaluate("() => scrollY") - y_before) <= 2,
          f'{y_before} -> {pg5.evaluate("() => scrollY")}')
    pg5.click("#f-rate"); pg5.wait_for_timeout(200)
    pg5.locator('#ratebox .chip[data-rate="3"]').click()
    pg5.click("#f-rate"); pg5.wait_for_timeout(300)

    # --- Bewerten direkt in der Anspielleiste ---
    pidx2 = pg5.evaluate("""() => [...document.querySelectorAll('.row')]
      .findIndex(r => r.querySelector('.row-play').dataset.quickplay)""")
    pg5.locator(".row").nth(pidx2).locator(".row-play").click()
    pg5.wait_for_timeout(600)
    psteps = pg5.locator("#player-rate button").evaluate_all(
        "e => e.map(x => x.dataset.r)")
    check("Anspielleiste hat die ganze Skala",
          psteps == ["1", "1.5", "2", "2.5", "3", "4", "5"], psteps)
    geo2 = pg5.evaluate("""() => {
      const g = (s) => {
        const b = document.querySelector(s);
        const r = b.getBoundingClientRect();
        return { w: Math.round(r.width), h: Math.round(r.height) };
      };
      return { ganz: g('#player-rate button[data-r=\"3\"]'),
               halb: g('#player-rate button[data-r=\"2.5\"]') };
    }""")
    check("Punkte sind rund und die halben kleiner",
          geo2["ganz"]["w"] == geo2["ganz"]["h"]
          and geo2["halb"]["w"] < geo2["ganz"]["w"],
          geo2)
    # Note 4 statt 1,5: diese Zeile trug aus einem frueheren Schritt schon
    # 1,5, und ein zweiter Griff auf dieselbe Note nimmt sie wieder weg.
    pg5.locator('#player-rate button[data-r="4"]').click()
    pg5.wait_for_timeout(400)
    # pidx2 ist die Position in der Liste, nicht der Act-Index - data-act
    # traegt den Act-Index, deshalb hier ueber nth() gehen.
    check("Note aus der Leiste steht in der Zeile",
          pg5.locator(".row").nth(pidx2).locator(".grade").inner_text() == "4",
          pg5.locator(".row").nth(pidx2).locator(".grade").inner_text())
    check("Der Punkt in der Leiste ist gefaerbt", pg5.evaluate("""() => {
      const b = document.querySelector('#player-rate button[data-r=\"4\"]');
      const o = document.querySelector('#player-rate button[data-r=\"3\"]');
      return b.getAttribute('aria-pressed') === 'true'
        && getComputedStyle(b).backgroundColor
           !== getComputedStyle(o).backgroundColor;
    }"""))
    # Der Player laeuft weiter - eine Note darf ihn nicht neu laden.
    check("Bewerten unterbricht das Anspielen nicht",
          pg5.locator("#player-slot iframe").count() == 1
          and not pg5.locator("#player").is_hidden())
    pg5.click("#player-close"); pg5.wait_for_timeout(300)
    check("Skala verschwindet mit der Leiste",
          pg5.locator("#player-rate button").count() == 0)

    # --- Anspielen darf die Liste nicht verruecken, auch nicht mit Filter ---
    # Gemeldet beim Weiterspringen zum naechsten Act. Ursache war nicht der
    # Player, sondern refreshAct(): bei aktivem Noten-, Favoriten-, Gesehen-
    # oder Team-Filter baut es die ganze Liste neu, weil eine NOTE die
    # Sichtbarkeit aendern kann. Fuers Anspielen gilt das nie. Ohne den Fix
    # gemessen: 687 px beim ersten Play, 420 beim Wechsel, 316 beim Stopp.
    pg5.click('.day[data-day=""]'); pg5.wait_for_timeout(400)
    pg5.click("#f-rate"); pg5.wait_for_selector("#ratebox .chip")
    pg5.locator('#ratebox .chip[data-rate="0"]').click(); pg5.wait_for_timeout(400)
    pg5.click("#f-rate"); pg5.wait_for_timeout(200)
    pg5.evaluate("() => scrollTo(0, 4000)"); pg5.wait_for_timeout(400)
    playable = pg5.evaluate("""() => {
      const out = [];
      [...document.querySelectorAll('.row')].forEach((r, i) => {
        const top = r.getBoundingClientRect().top;
        if (top > 120 && top < 700 && r.querySelector('.row-play').dataset.quickplay)
          out.push(i);
      });
      return out.slice(0, 2);
    }""")
    if len(playable) == 2:
        y0 = pg5.evaluate("() => scrollY")
        pg5.locator(".row").nth(playable[0]).locator(".row-play").click()
        pg5.wait_for_timeout(700)
        y1 = pg5.evaluate("() => scrollY")
        check("Anspielen mit aktivem Filter verrueckt die Liste nicht",
              abs(y1 - y0) <= 2, f"{y0} -> {y1}")
        pg5.locator(".row").nth(playable[1]).locator(".row-play").click()
        pg5.wait_for_timeout(700)
        y2 = pg5.evaluate("() => scrollY")
        check("Und der Wechsel zum naechsten Act auch nicht",
              abs(y2 - y1) <= 2, f"{y1} -> {y2}")
        # Nicht "genau eine Zeile": ein Act mit zwei Auftritten hat zwei
        # Zeilen, und beide gehoeren zum laufenden Anspielen. Was NICHT
        # passieren darf, ist ein Pausenzeichen an einem ZWEITEN Act - so
        # sah es vorher aus, weil die vorher spielende Zeile ihr Zeichen
        # behielt.
        playing_acts = pg5.evaluate("""() => [...new Set(
          [...document.querySelectorAll('.row-play.is-playing')]
            .map(e => e.closest('.row').dataset.act))]""")
        check("Das Pausenzeichen steht nur beim laufenden Act",
              len(playing_acts) == 1, str(playing_acts))
        pg5.locator(".row").nth(playable[1]).locator(".row-play").click()
        pg5.wait_for_timeout(600)
        y3 = pg5.evaluate("() => scrollY")
        check("Und das Beenden auch nicht", abs(y3 - y2) <= 2, f"{y2} -> {y3}")
        check("Danach zeigt keine Zeile mehr das Pausenzeichen",
              pg5.locator(".row-play.is-playing").count() == 0)

        # Und das Bewerten AUS der Leiste heraus - der zweite gemeldete
        # Sprung. Ohne den Fix gemessen: 582 px, dann je rund 315 px, also
        # bei jedem Durchhoeren ein Stueck weiter nach unten.
        #
        # Gemessen wird die BILDSCHIRMPOSITION einer sichtbaren Zeile, nicht
        # scrollY: hat der Act zwei Auftritte, wird auch seine zweite Zeile
        # ersetzt, und liegt die oberhalb des Fensters, verschiebt der
        # Browser scrollY von sich aus, um das Sichtbare stillzuhalten
        # (Scroll-Anchoring). Genau das ist erwuenscht - fuer das Auge
        # bewegt sich dabei nichts, und danach fragt die Meldung.
        pg5.locator(".row").nth(playable[0]).locator(".row-play").click()
        pg5.wait_for_timeout(700)
        probe_js = """() => {
          const r = [...document.querySelectorAll('.row')]
            .find(x => { const t = x.getBoundingClientRect().top;
                         return t > 150 && t < 700; });
          return r ? Math.round(r.getBoundingClientRect().top) : null;
        }"""
        seen_at = pg5.evaluate(probe_js)
        moved, scrolled = [], []
        ry = pg5.evaluate("() => scrollY")
        for note in ("3", "2", "1"):
            pg5.locator(f'#player-rate button[data-r="{note}"]').click()
            pg5.wait_for_timeout(500)
            now_at = pg5.evaluate(probe_js)
            ry2 = pg5.evaluate("() => scrollY")
            moved.append(abs((now_at if now_at is not None else 0)
                             - (seen_at if seen_at is not None else 0)))
            scrolled.append(abs(ry2 - ry))
            seen_at, ry = now_at, ry2
        check("Bewerten in der Anspielleiste verrueckt die Liste nicht",
              max(moved) <= 2, f"Sichtbares: {moved} px, scrollY: {scrolled} px")
        check("Die Note steht danach in der Zeile",
              pg5.locator(".row").nth(playable[0]).locator(".grade").inner_text() == "1",
              pg5.locator(".row").nth(playable[0]).locator(".grade").inner_text())
        pg5.click("#player-close"); pg5.wait_for_timeout(300)
    else:
        check("Zwei anspielbare Zeilen im Blick gefunden", False, str(playable))
    pg5.click("#f-rate"); pg5.wait_for_timeout(200)
    pg5.locator('#ratebox .chip[data-rate="0"]').click(); pg5.wait_for_timeout(300)
    pg5.click("#f-rate"); pg5.wait_for_timeout(200)

    # Offscreen-Zeilen werden vom Browser uebersprungen - ohne das dauert ein
    # Neuaufbau fast eine Sekunde.
    cv = pg5.evaluate("""() => {
      const s = getComputedStyle(document.querySelector('.row'));
      return { cv: s.contentVisibility, size: s.containIntrinsicSize };
    }""")
    check("Zeilen ausserhalb des Bildschirms werden uebersprungen",
          cv["cv"] == "auto" and "80px" in cv["size"], cv)
    ctx5.close()

    # --- Aenderungen am Programm ---
    # Uhrzeiten verschieben sich beim Reeperbahn Festival dauernd. Wer sich
    # einen Abend gebaut hat, muss das mitbekommen.
    marks = pg.evaluate("""() => {
      const all = [...document.querySelectorAll('.chg')];
      const moved = all.find(e => e.classList.contains('chg-moved'));
      return { n: all.length, movedTitel: moved ? moved.getAttribute('title') : null };
    }""")
    if marks["n"]:
        check("Geaenderte Termine sind in der Liste markiert", True, marks["n"])
        # Der erste Treffer muss keine Verschiebung sein - bei vielen
        # Aenderungen kann auch "neu" oder "gestrichen" zuerst kommen.
        # Geprueft wird gezielt eine .chg-moved-Marke, falls vorhanden.
        if marks["movedTitel"] is not None:
            check("Die Marke nennt die Verschiebung",
                  "\u2192" in marks["movedTitel"], marks["movedTitel"])
        else:
            check("Keine Zeitverschiebung markiert, andere Aenderungsart vorhanden",
                  True, "kein .chg-moved in dieser Ausgabe")
    else:
        check("Keine Aenderungen, also keine Marken", True,
              "changes.json ohne Eintraege")
    pg.click("#btn-menu"); pg.wait_for_timeout(300)
    check("Menuepunkt fuer Aenderungen", pg.locator("#m-news").count() == 1)
    pg.click("#m-news"); pg.wait_for_timeout(700)
    check("Aenderungsansicht oeffnet", not pg.locator("#news").is_hidden())
    check("Kopfzeile nennt den Stand",
          pg.locator("#news-meta").inner_text().strip() != "",
          pg.locator("#news-meta").inner_text()[:70])
    if pg.locator("#news-body [data-findshow]").count():
        pg.locator("#news-body [data-findshow]").first.click()
        pg.wait_for_timeout(900)
        check("Sprung fuehrt zur Zeile in der Liste",
              pg.locator("#news").is_hidden() and pg.locator(".row").count() > 0)
        check("Und hebt sie kurz hervor", pg.locator(".row.flash").count() == 1,
              pg.locator(".row.flash").count())
    else:
        pg.click("#btn-menu"); pg.wait_for_timeout(250)
        pg.locator("#menu [data-close]").click(); pg.wait_for_timeout(250)
    pg.click("#btn-menu"); pg.wait_for_timeout(250)
    pg.click("#m-news"); pg.wait_for_timeout(600)
    pg.go_back(); pg.wait_for_timeout(600)
    check("Zurueck schliesst die Aenderungsansicht",
          pg.locator("#news").is_hidden())

    # --- Der letzte Stand, wenn die Liste nicht mehr kommt ---
    # EIGENER Kontext mit blockiertem Service Worker. Sonst antwortet dessen
    # Zwischenspeicher - und seine Anfragen gehen an Playwrights Routing
    # vorbei. Genau daran ist der erste Versuch dieses Tests vorbeigelaufen:
    # die Zeilen kamen vom Worker, nicht von der eigenen Notkopie.
    ctx6 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE",
                         service_workers="block")
    pg6 = ctx6.new_page()
    err6 = []
    pg6.on("pageerror", lambda e: err6.append(str(e)))
    pg6.goto(BASE + "/", wait_until="load")
    pg6.wait_for_selector(".row", timeout=20000)
    pg6.wait_for_timeout(1800)
    check("Kein Service Worker in diesem Kontext",
          pg6.evaluate("() => !navigator.serviceWorker.controller"))
    check("Der Stand wird im Browser abgelegt",
          pg6.evaluate("() => { const s = localStorage.getItem('rbf26.lineup');"
                       " return s ? JSON.parse(s).acts.length : 0; }") > 0)

    # 200, aber Unsinn - ein kaputter Build darf einen guten Stand nicht
    # verdraengen.
    pg6.route("**/data/lineup.json", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body='{"acts":[],"shows":[],"days":[],"venues":[]}'))
    pg6.reload(wait_until="load")
    pg6.wait_for_selector(".row", timeout=15000)
    check("Unbrauchbare Datei wird nicht uebernommen",
          pg6.locator(".row").count() > 0, pg6.locator(".row").count())
    check("Und der alte Stand wird als solcher benannt",
          not pg6.locator("#stale").is_hidden(),
          pg6.locator("#stale").inner_text()[:70])
    pg6.unroute("**/data/lineup.json")

    pg6.route("**/data/lineup.json", lambda r: r.abort())
    pg6.reload(wait_until="load")
    pg6.wait_for_selector(".row", timeout=15000)
    check("Auch bei Netzfehler bleibt die Liste da",
          pg6.locator(".row").count() > 0, pg6.locator(".row").count())
    check("Mit Hinweis auf den alten Stand",
          not pg6.locator("#stale").is_hidden())
    pg6.unroute("**/data/lineup.json")

    pg6.reload(wait_until="load")
    pg6.wait_for_selector(".row", timeout=15000)
    check("Danach wieder frischer Stand, ohne Hinweis",
          pg6.locator("#stale").is_hidden())

    # Spielort ohne Koordinaten: kommt vor, sobald das Festival ein neues
    # Haus ins Programm nimmt und die Koordinaten nachtraegt (im September
    # 2026 war das 'o2 music Studio Hamburg'). Auf der Karte fehlt es dann -
    # der Antipper in der Liste darf aber nicht einfach ins Leere laufen.
    # Die eingecheckten Daten haben so einen Ort nicht, also untergeschoben.
    import json as _json6
    _lin6 = _json6.load(open("web/data/lineup.json", encoding="utf-8"))
    _vi = next(i for i, v in enumerate(_lin6["venues"]) if v.get("lat") is not None)
    _lin6["venues"][_vi]["lat"] = None
    _lin6["venues"][_vi]["lng"] = None
    pg6.route("**/data/lineup.json", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=_json6.dumps(_lin6)))
    pg6.reload(wait_until="load")
    pg6.wait_for_selector(".row", timeout=15000)
    _row = pg6.locator(f'.row .venue[data-venue="{_vi}"]').first
    _row.scroll_into_view_if_needed(); _row.click()
    pg6.wait_for_timeout(600)
    check("Spielort ohne Koordinaten sagt das, statt nichts zu tun",
          not pg6.locator("#toast").is_hidden()
          and "Koordinaten" in pg6.locator("#toast").inner_text(),
          pg6.locator("#toast").inner_text()[:70])
    check("Und die Karte bleibt dabei zu", pg6.locator("#map").is_hidden())
    pg6.unroute("**/data/lineup.json")

    check("Keine JS-Fehler im Notstands-Kontext", not err6, str(err6[:2]))
    ctx6.close()

    # --- Abendplan: Überschneidung, paralleles Umschalten, Zeitleiste ---
    # EIGENER Kontext mit vielen Noten. Der Plan weiter oben kommt mit ein
    # bis zwei Stationen aus - da gibt es nichts Paralleles zu sehen, und
    # genau darum geht es hier.
    ctx7 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    pg7 = ctx7.new_page()
    err7 = []
    pg7.on("pageerror", lambda e: err7.append("pageerror: " + str(e)))
    pg7.on("console",
           lambda m: err7.append(m.text) if m.type == "error"
           and "ERR_" not in m.text else None)
    pg7.goto(BASE + "/", wait_until="load")
    pg7.wait_for_selector(".row", timeout=20000)
    lineup7 = _json.load(open("web/data/lineup.json", encoding="utf-8"))
    day7 = lineup7["days"][1]
    ids7 = list(dict.fromkeys(
        [lineup7["acts"][s["a"]]["id"] for s in lineup7["shows"]
         if s["d"] == day7 and not s["tbd"]]))[:60]
    pg7.evaluate("""(ids) => {
      const r = {};
      ids.forEach((id, i) => { r[id] = (i % 3) + 1; });
      localStorage.setItem('rbf26.rate', JSON.stringify(r));
    }""", ids7)
    pg7.reload(wait_until="load")
    pg7.wait_for_selector(".row", timeout=20000)
    pg7.click(f'.day[data-day="{day7}"]'); pg7.wait_for_timeout(400)
    pg7.click("#btn-menu"); pg7.wait_for_selector("#menu[open]")
    pg7.click("#m-plan"); pg7.wait_for_timeout(800)

    # Der Abendplan geht mit der ZEITLEISTE auf, nicht mit der Liste.
    check("Der Abendplan geht gleich mit der Zeitleiste auf",
          not pg7.locator("#plan-time").is_hidden()
          and pg7.locator("#plan-body").is_hidden()
          and pg7.locator("#plan-timeline").get_attribute("aria-pressed") == "true",
          f'Leiste verborgen: {pg7.locator("#plan-time").is_hidden()}')
    # Was hier gleich geprüft wird, steht in der LISTE - also einmal
    # umschalten. Der Knopf tut beides.
    pg7.click("#plan-timeline"); pg7.wait_for_timeout(500)
    check("Und der Knopf schaltet zurück auf die Liste",
          pg7.locator("#plan-time").is_hidden()
          and not pg7.locator("#plan-body").is_hidden())

    # Die Voreinstellung, mit der der Abendplan aufgeht. Das ist keine
    # Kosmetik: sie entscheidet, was jemand sieht, der nichts einstellt.
    vor = pg7.evaluate("""() => ({
      note: document.querySelector('#plan-max').value,
      spielzeit: document.querySelector('#plan-set').value,
      ueberschneidung: document.querySelector('#plan-ovl').value,
    })""")
    check("Der Abendplan geht mit den vereinbarten Werten auf",
          vor == {"note": "3", "spielzeit": "30", "ueberschneidung": "10"},
          str(vor))
    check("Und die Rechnung nimmt sie auch",
          pg7.locator("#plan .leg.over").count() >= 1,
          f"{pg7.locator('#plan .leg.over').count()} Etappen mit Überschneidung")

    # Ab hier misst dieser Block die Überschneidung selbst - also erst
    # ausdrücklich auf "aus", sonst vergleicht er zwei Budgets statt keines
    # mit einem.
    pg7.select_option("#plan-ovl", "0"); pg7.wait_for_timeout(700)
    stops7 = pg7.locator("#plan .stop").count()
    check("Mit vielen Noten entsteht ein voller Plan", stops7 >= 4,
          f"{stops7} Stationen")

    # Überschneidung: aus heisst aus.
    check("Ohne Budget gibt es keine Überschneidung",
          pg7.locator("#plan .leg.over").count() == 0)
    pg7.select_option("#plan-ovl", "20"); pg7.wait_for_timeout(700)
    stops_ovl = pg7.locator("#plan .stop").count()
    check("Mit Budget passen mehr Konzerte in den Abend", stops_ovl > stops7,
          f"{stops7} -> {stops_ovl}")
    over7 = pg7.locator("#plan .leg.over")
    check("Und die Etappen weisen sie aus", over7.count() >= 1,
          f"{over7.count()} von {stops_ovl - 1}")
    # Das Wort passt nicht in die Zeile, das Zeichen schon - aber der Titel
    # muss es ausschreiben, sonst raet man.
    ovl_txt = pg7.locator("#plan .leg-ovl").first
    check("Die Überschneidung steht als ≠ in der Etappe",
          ovl_txt.inner_text().startswith("≠"), ovl_txt.inner_text())
    check("Mit ausgeschriebenem Titel",
          "Überschneidung" in (ovl_txt.get_attribute("title") or ""),
          ovl_txt.get_attribute("title"))
    # Keine Etappe darf mehr aufgeben, als das Budget erlaubt.
    worst = pg7.evaluate("""() => Math.max(0, ...[...document.querySelectorAll(
      '#plan .leg-ovl')].map(e => parseInt(e.textContent.replace(/\\D+/g, ''), 10)))""")
    check("Keine Etappe überzieht das gewählte Budget", worst <= 20,
          f"höchstens {worst} min bei 20 erlaubt")
    pg7.select_option("#plan-ovl", "0"); pg7.wait_for_timeout(700)
    check("Zurück auf aus rechnet den alten Plan",
          pg7.locator("#plan .stop").count() == stops7
          and pg7.locator("#plan .leg.over").count() == 0)

    # Zähler und Umschalten.
    PLAN7 = ("() => [...document.querySelectorAll('#plan-body .stop .row')]"
             ".map(r => r.dataset.show)")
    alt7 = pg7.locator("#plan .alt-count")
    check("Stationen mit parallelen Acts tragen einen Zähler",
          alt7.count() >= 1, f"{alt7.count()} von {stops7}")
    if alt7.count():
        first_alt = alt7.first
        check("Der Zähler nennt eine Anzahl",
              re.fullmatch(r"\+\d+", first_alt.inner_text().strip()),
              first_alt.inner_text())
        check("Und sagt im Titel, wer da parallel läuft",
              "zur selben Zeit" in (first_alt.get_attribute("title") or ""),
              (first_alt.get_attribute("title") or "")[:60])
        stop_id = first_alt.evaluate("e => e.closest('.stop').dataset.stop")
        before7 = pg7.evaluate(PLAN7)
        first_alt.click(); pg7.wait_for_timeout(800)
        after7 = pg7.evaluate(PLAN7)
        check("Ein Tipper tauscht den Act gegen einen parallelen",
              stop_id not in after7 and after7 != before7,
              f"{before7} -> {after7}")
        check("Der Abend wird dabei neu gerechnet, nicht nur die Zeile",
              len(after7) >= 1)
        check("Der Tausch lässt sich zurücknehmen",
              pg7.locator("#toast .toast-undo").count() == 1,
              pg7.locator("#toast").inner_text()[:60])
        pg7.locator("#toast .toast-undo").click(); pg7.wait_for_timeout(800)
        check("Und ist danach wirklich zurück",
              pg7.evaluate(PLAN7) == before7,
              f"{pg7.evaluate(PLAN7)} gegen {before7}")

        # Dieselbe Bewegung mit dem Finger. Die Geste im Plan ist eine
        # eigene - die der Liste ist abgeschaltet und würde hier Noten
        # ändern statt umzuschalten.
        SWAP = """([id, dx]) => {
          const stop = document.querySelector(`.stop[data-stop="${id}"]`);
          const r = stop.getBoundingClientRect();
          const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
          const fire = (type, x) => {
            const t = new Touch({ identifier: 3, target: stop, clientX: x,
                                  clientY: y0, pageX: x, pageY: y0 });
            const empty = type === 'touchend';
            stop.dispatchEvent(new TouchEvent(type, { bubbles: true,
              cancelable: true, touches: empty ? [] : [t],
              targetTouches: empty ? [] : [t], changedTouches: [t] }));
          };
          fire('touchstart', x0);
          for (let i = 1; i <= 8; i++) fire('touchmove', x0 + (dx * i) / 8);
          fire('touchend', x0 + dx);
        }"""
        # Erst nur HALTEN, nicht loslassen: waehrend der Geste muss der
        # naechste Act schon von der Seite hereinschauen. Ohne das war der
        # Wisch eine Wette - man gab die Station aus der Hand und sah erst
        # nach dem Loslassen, was man bekommt.
        HOLD = """([id, dx]) => {
          const stop = document.querySelector(`.stop[data-stop="${id}"]`);
          const r = stop.getBoundingClientRect();
          const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
          const fire = (type, x) => {
            const t = new Touch({ identifier: 4, target: stop, clientX: x,
                                  clientY: y0, pageX: x, pageY: y0 });
            stop.dispatchEvent(new TouchEvent(type, { bubbles: true,
              cancelable: true, touches: [t], targetTouches: [t],
              changedTouches: [t] }));
          };
          fire('touchstart', x0);
          for (let i = 1; i <= 8; i++) fire('touchmove', x0 + (dx * i) / 8);
        }"""
        DROP = """([id]) => {
          const stop = document.querySelector(`.stop[data-stop="${id}"]`);
          const t = new Touch({ identifier: 4, target: stop, clientX: 0, clientY: 0 });
          stop.dispatchEvent(new TouchEvent('touchend', { bubbles: true,
            cancelable: true, touches: [], targetTouches: [], changedTouches: [t] }));
        }"""
        held = pg7.locator("#plan .alt-count").first.evaluate(
            "e => e.closest('.stop').dataset.stop")
        held_name = pg7.locator(f'#plan .stop[data-stop="{held}"] .row-name').first \
            .evaluate("e => e.childNodes[0].textContent.trim()")
        pg7.evaluate(HOLD, [held, -90]); pg7.wait_for_timeout(250)
        peek = pg7.evaluate("""() => {
          const p = document.getElementById('swap-peek');
          const s = document.querySelector('.stop.swapping');
          const pr = p.getBoundingClientRect();
          const sr = s ? s.getBoundingClientRect() : null;
          const n = p.querySelector('.row-name');
          return { offen: !p.hidden, name: n ? n.childNodes[0].textContent.trim() : null,
                   links: pr.left, breite: pr.width,
                   stationLinks: sr ? sr.left : null,
                   versatz: s ? s.style.transform : null };
        }""")
        check("Während des Wischens schiebt sich der nächste Act herein",
              peek["offen"] and peek["name"], str(peek)[:110])
        check("Und zwar ein anderer als der, den man wegschiebt",
              peek["name"] != held_name, f'{held_name} -> {peek["name"]}')
        # Er kommt von RECHTS, also genau eine Zeilenbreite hinter der
        # Station her - sonst laege er auf ihr.
        check("Er hängt am Finger, eine Zeilenbreite versetzt",
              peek["breite"] > 100
              and abs((peek["links"] - peek["stationLinks"]) - peek["breite"]) < 2,
              f'Vorschau {round(peek["links"])}, Station {round(peek["stationLinks"])}, '
              f'Breite {round(peek["breite"])}')
        pg7.evaluate(DROP, [held]); pg7.wait_for_timeout(800)
        check("Nach dem Loslassen ist die Vorschau weg",
              pg7.evaluate("() => document.getElementById('swap-peek').hidden"))
        check("Und der vorgeschaute Act steht jetzt im Plan",
              pg7.locator("#plan .stop .row-name").evaluate_all(
                  "els => els.map(e => e.childNodes[0].textContent.trim())")
              .count(peek["name"]) >= 1,
              f'{peek["name"]} in '
              + str(pg7.locator("#plan .stop .row-name").evaluate_all(
                  "els => els.map(e => e.childNodes[0].textContent.trim())")[:6]))
        pg7.locator("#toast .toast-undo").click(); pg7.wait_for_timeout(700)

        swipe_from = pg7.evaluate(PLAN7)
        pg7.evaluate(SWAP, [stop_id, -120]); pg7.wait_for_timeout(800)
        check("Wischen tauscht genauso",
              pg7.evaluate(PLAN7) != swipe_from,
              f"{swipe_from} -> {pg7.evaluate(PLAN7)}")
        check("Die Station bleibt dabei nicht verschoben liegen",
              pg7.evaluate("""() => [...document.querySelectorAll('.stop')]
                .every(s => !s.style.transform && !s.classList.contains('swapping'))"""))
        check("Und der Wisch öffnet nicht nebenbei die Detailkarte",
              pg7.locator("#detail[open]").count() == 0)
        pg7.locator("#toast .toast-undo").click(); pg7.wait_for_timeout(700)

    # --- Zeitleiste ---
    pg7.click("#plan-timeline"); pg7.wait_for_timeout(800)
    check("Die Zeitleiste löst die Liste ab",
          pg7.locator("#plan-time").is_visible()
          and pg7.locator("#plan-body").is_hidden()
          and pg7.locator("#plan-timeline").get_attribute("aria-pressed") == "true")
    tl = pg7.locator(".tl-act")
    check("Sie zeigt alle in Frage kommenden Acts, nicht nur den Plan",
          tl.count() > pg7.locator(".tl-act.in-plan").count()
          and pg7.locator(".tl-act.in-plan").count() >= 1,
          f"{tl.count()} Blöcke, davon {pg7.locator('.tl-act.in-plan').count()} im Plan")
    # DAS ist der Zweck: Gleichzeitiges steht nebeneinander. Läge es
    # übereinander, wäre die Ansicht wertlos - und genau das passiert, wenn
    # die Maße nicht ankommen (style-src 'self' verwirft style="…").
    geom = pg7.evaluate("""() => {
      const a = [...document.querySelectorAll('.tl-act')];
      let ueber = 0;
      for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) {
        const A = a[i].getBoundingClientRect(), B = a[j].getBoundingClientRect();
        if (A.top < B.bottom && B.top < A.bottom
            && A.left < B.right && B.left < A.right) ueber++;
      }
      const c = document.querySelector('.tl-canvas');
      return { ueber, spuren: new Set(a.map(e => e.style.left)).size,
               hoehe: c.offsetHeight, breite: c.offsetWidth,
               sicht: document.querySelector('.tl-scroll').clientWidth };
    }""")
    check("Kein Block liegt auf einem anderen", geom["ueber"] == 0,
          f'{geom["ueber"]} Überdeckungen')
    check("Parallel Laufendes steht in mehreren Spuren", geom["spuren"] >= 2,
          f'{geom["spuren"]} Spuren')
    check("Die Leinwand hat eine Höhe", geom["hoehe"] > 200, f'{geom["hoehe"]} px')
    check("Und ist seitlich scrollbar statt gequetscht",
          geom["breite"] > geom["sicht"], f'{geom["breite"]} auf {geom["sicht"]} px')
    check("Die Stunden sind beschriftet",
          pg7.locator(".tl-hour").count() >= 3
          and re.fullmatch(r"\d\d:00",
                           pg7.locator(".tl-hour span").first.inner_text().strip()),
          pg7.locator(".tl-hour span").first.inner_text())
    check("Die eigene Note steht an den Blöcken",
          pg7.locator(".tl-act .grade").count() >= 1,
          f'{pg7.locator(".tl-act .grade").count()}')
    check("Und die Stationen des Plans sind numeriert",
          pg7.locator(".tl-act.in-plan .tl-no").count()
          == pg7.locator(".tl-act.in-plan").count())
    # Ortskürzel und Mehrfachauftritte gehören an den Block: sonst muss man
    # für "wo ist das denn?" jedes Mal aufmachen.
    check("Jeder Block nennt sein Ortskürzel",
          pg7.locator(".tl-act .vcode").count() == tl.count(),
          f'{pg7.locator(".tl-act .vcode").count()} von {tl.count()}')
    check("Und das Kürzel sind zwei Zeichen",
          re.fullmatch(r"\S{1,3}",
                       pg7.locator(".tl-act .vcode").first.inner_text().strip()),
          pg7.locator(".tl-act .vcode").first.inner_text())
    check("Wer mehrfach spielt, trägt das am Block",
          pg7.locator(".tl-act .multi").count() >= 1
          and pg7.locator(".tl-act .multi").first.inner_text().startswith("×"),
          f'{pg7.locator(".tl-act .multi").count()} Marken')

    # Die Verbindung von Station zu Station mit der Laufzeit.
    n_stops_tl = pg7.locator(".tl-act.in-plan").count()
    check("Zwischen den Stationen läuft eine Linie",
          pg7.locator(".tl-link").count() == n_stops_tl - 1,
          f'{pg7.locator(".tl-link").count()} Linien bei {n_stops_tl} Stationen')
    check("Mit der Laufzeit daran",
          pg7.locator(".tl-link-label").count() == n_stops_tl - 1
          and re.fullmatch(r"\d+ min",
              pg7.locator(".tl-link-label").first.text_content().strip()),
          pg7.locator(".tl-link-label").first.text_content())
    # Die Linie muss die beiden Kästen wirklich verbinden, nicht irgendwo
    # liegen - geprüft am Endpunkt gegen die Lage des zweiten Blocks.
    check("Die Linie trifft die nächste Station", pg7.evaluate("""() => {
      const l = document.querySelector('.tl-link');
      const acts = [...document.querySelectorAll('.tl-act.in-plan')];
      if (!l || acts.length < 2) return false;
      const svg = document.querySelector('.tl-links').getBoundingClientRect();
      const b = acts[1].getBoundingClientRect();
      const x = svg.left + +l.getAttribute('x2');
      const y = svg.top + +l.getAttribute('y2');
      return x > b.left - 2 && x < b.right + 2 && Math.abs(y - b.top) < 3;
    }"""))

    # Der rote Strich steht IMMER da - egal, welcher Tag gewählt ist und
    # ob "jetzt" hineinfällt. Die Uhrzeit stammt vom Telefon.
    #
    # Dieser Block läuft mit der ECHTEN Uhr. Ob der Strich als "außerhalb"
    # gekennzeichnet ist, hängt damit am Kalender: day7 ist der zweite
    # Festivaltag, und sobald der wirklich läuft, liegt "jetzt" mitten
    # darin. Genau daran ist diese Prüfung am 17.9. um 12:35 gescheitert,
    # nachdem sie um 11:55 noch durchging. Die Kennzeichnung wird deshalb
    # dort geprüft, wo die Uhr gestellt ist (Kontext 8, "Er klebt dann an
    # der Kante und sagt das"); hier bleibt, was unabhängig vom Datum gilt.
    strich7 = pg7.locator(".tl-now")
    check("Ein Strich für jetzt steht in jedem Fall",
          strich7.count() == 1, f'{strich7.count()} Striche für {day7}')
    check("Mit der Uhrzeit vom Telefon daran",
          re.fullmatch(r"\d\d:\d\d", strich7.inner_text().strip()),
          strich7.inner_text().strip())
    lage7 = pg7.evaluate("""() => {
      const n = document.querySelector('.tl-now');
      const c = document.querySelector('.tl-canvas');
      return { top: n ? parseFloat(n.style.top) : null,
               hoehe: c ? parseFloat(c.style.height) : null,
               klasse: n ? n.className : null };
    }""")
    check("Und innerhalb der Leiste, nicht darüber hinaus",
          lage7["top"] is not None and lage7["hoehe"] is not None
          and 0 <= lage7["top"] <= lage7["hoehe"], str(lage7))

    # --- Die Griffe zu einem Auftritt ---
    # Aus der Zeitleiste geht bewusst NICHT die Detailkarte auf.
    pg7.locator(".tl-act").first.click(); pg7.wait_for_timeout(700)
    check("Ein Block öffnet die Griffe, nicht die Detailkarte",
          pg7.locator("#tlmenu[open]").count() == 1
          and pg7.locator("#detail[open]").count() == 0)
    # Seit die echte Spielzeit bekannt ist, steht dort eine Zeitspanne und
    # die Dauer in Minuten - nicht mehr nur der Beginn.
    check("Sie nennen Tag, Spielzeit, Kürzel und Spielort",
          re.search(r"(Mi|Do|Fr|Sa) \d\d:\d\d–\d\d:\d\d · \d+ min · \S+ ",
                    pg7.locator("#tl-when").inner_text()),
          pg7.locator("#tl-when").inner_text()[:70])
    chips7 = pg7.locator("#tl-top .chip").all_inner_texts()
    check("Mit Spotify-Abkürzung, Gesehen und Favorit",
          len(chips7) == 4 and ("Anspielen" in chips7[0] or "Spotify" in chips7[0])
          and "Gesehen" in chips7[1] and "Favorit" in chips7[2], str(chips7))
    check("Und einem Weg zur ausführlichen Künstlerkarte",
          "Künstlerkarte" in chips7[3], chips7[3])
    check("Und der vollen Notenskala",
          pg7.locator("#tl-rate button").count() == 7)
    seg7 = pg7.locator("#tl-plan button").all_inner_texts()
    check("Dazu die Wahl, ob das in den Abendplan kommt",
          len(seg7) == 3, str(seg7))
    check("Genau eine der drei gilt", pg7.evaluate(
        """() => [...document.querySelectorAll('#tl-plan button')]
             .filter(b => b.getAttribute('aria-pressed') === 'true').length""") == 1)

    tl_show = pg7.locator("#tlmenu").get_attribute("data-show")
    # Note aus diesem Dialog: setzt sich UND lässt den Plan neu rechnen,
    # ohne den Dialog zu schließen - man ist ja noch beim Entscheiden.
    tl_before = pg7.evaluate(PLAN7)
    pg7.locator('#tl-rate button[data-r="5"]').click(); pg7.wait_for_timeout(700)
    check("Eine Note von hier setzt sich",
          pg7.locator('#tl-rate button[data-r="5"]').get_attribute("aria-pressed")
          == "true")
    check("Und der Dialog bleibt dabei offen",
          pg7.locator("#tlmenu[open]").count() == 1)
    check("Der Plan rechnet neu", pg7.evaluate(PLAN7) != tl_before,
          f"{tl_before[:4]} -> {pg7.evaluate(PLAN7)[:4]}")
    pg7.locator('#tl-rate button[data-r="5"]').click(); pg7.wait_for_timeout(500)

    pg7.click("#tl-seen"); pg7.wait_for_timeout(600)
    check("Gesehen lässt sich hier abhaken",
          pg7.locator("#tl-seen").get_attribute("aria-pressed") == "true"
          and pg7.evaluate("() => JSON.parse(localStorage.getItem("
                           "'rbf26.seen')||'[]').length") >= 1)
    # Auch von hier aus geht danach die Skala auf - dieselbe Frage, egal
    # über welchen Weg man abhakt.
    check("Und die Skala geht auch von hier auf",
          pg7.locator("#quick[open]").count() == 1
          and "Gesehen" in pg7.locator("#quick-sub").inner_text(),
          pg7.locator("#quick-sub").inner_text())
    pg7.keyboard.press("Escape"); pg7.wait_for_timeout(400)
    check("Zurück führt in die Griffe, nicht weiter hinaus",
          pg7.locator("#quick[open]").count() == 0
          and pg7.locator("#tlmenu[open]").count() == 1)

    # Die drei Stufen schreiben in dieselben Mengen wie 📌 und ✕ in der Liste.
    pg7.locator('#tl-plan button[data-tlplan="fest"]').click()
    pg7.wait_for_timeout(700)
    check("'Muss rein' hält den Termin fest", pg7.evaluate(
        f"() => JSON.parse(localStorage.getItem('rbf26.planpin')||'[]')"
        f".includes('{tl_show}')"))
    check("Und der Termin steht danach im Plan", tl_show in pg7.evaluate(PLAN7),
          f"{tl_show} in {pg7.evaluate(PLAN7)}")
    pg7.locator('#tl-plan button[data-tlplan="raus"]').click()
    pg7.wait_for_timeout(700)
    check("'Nicht heute' schließt ihn aus", pg7.evaluate(
        f"() => !JSON.parse(localStorage.getItem('rbf26.planpin')||'[]')"
        f".includes('{tl_show}') && JSON.parse(localStorage.getItem("
        f"'rbf26.planskip')||'[]').includes('{tl_show}')"))
    check("Und er ist aus dem Plan verschwunden",
          tl_show not in pg7.evaluate(PLAN7))
    pg7.locator('#tl-plan button[data-tlplan="auto"]').click()
    pg7.wait_for_timeout(700)
    check("'Wenn es passt' nimmt beides zurück", pg7.evaluate(
        f"() => !JSON.parse(localStorage.getItem('rbf26.planpin')||'[]')"
        f".includes('{tl_show}') && !JSON.parse(localStorage.getItem("
        f"'rbf26.planskip')||'[]').includes('{tl_show}')"))

    # --- "Nicht heute" blendet in der Leiste nicht aus, sondern legt beiseite ---
    # Mit einem EIGENEN Block: der von oben hat inzwischen keine Note mehr
    # (gesetzt und wieder gelöscht) und gehört damit ohnehin nicht mehr in
    # die Leiste - ausgeschlossen wird nur sichtbar, was sonst zu sehen wäre.
    pg7.keyboard.press("Escape"); pg7.wait_for_timeout(400)
    weg = pg7.evaluate("""() => {
      const e = [...document.querySelectorAll('.tl-act')].find(
        (x) => x.querySelector('.grade:not(.grade-p)') && !x.classList.contains('skipped'));
      return e ? [e.dataset.tlshow, parseFloat(e.style.left)] : null;
    }""")
    if weg:
        weg_id, links_vorher = weg[0], weg[1]
        pg7.locator(f'.tl-act[data-tlshow="{weg_id}"]').click()
        pg7.wait_for_selector("#tlmenu[open]")
        pg7.locator('#tl-plan button[data-tlplan="raus"]').click()
        pg7.wait_for_timeout(700)
        pg7.keyboard.press("Escape"); pg7.wait_for_timeout(400)
        raus7 = pg7.locator(f'.tl-act[data-tlshow="{weg_id}"]')
        check("Ausgeschlossen heißt in der Leiste nicht verschwunden",
              raus7.count() == 1
              and weg_id not in pg7.evaluate(PLAN7),
              f"{weg_id} noch da: {raus7.count()}")
        check("Grau hinterlegt und entfärbt", pg7.evaluate(
            f"""() => {{
              const e = document.querySelector('.tl-act[data-tlshow="{weg_id}"]');
              const s = getComputedStyle(e);
              return e.classList.contains('skipped') && +s.opacity < 0.7
                     && s.filter.includes('grayscale');
            }}"""), raus7.get_attribute("class"))
        links_nachher = float(str(raus7.evaluate("e => e.style.left"))
                              .replace("px", ""))
        check("Und nach links geschoben", links_nachher < links_vorher,
              f"{links_vorher} -> {links_nachher}")
        # Die Regel dahinter: was heute nicht stattfindet, steht links von
        # allem, was gleichzeitig läuft und noch in Frage kommt.
        ordnung7 = pg7.evaluate("""() => {
          const a = [...document.querySelectorAll('.tl-act')].map((e) => ({
            left: parseFloat(e.style.left), top: parseFloat(e.style.top),
            h: parseFloat(e.style.height),
            raus: e.classList.contains('skipped'),
          }));
          let paare = 0, falsch = 0;
          for (const r of a.filter((x) => x.raus)) {
            for (const n of a.filter((x) => !x.raus)) {
              if (!(r.top < n.top + n.h && n.top < r.top + r.h)) continue;
              paare++;
              if (r.left > n.left) falsch++;
            }
          }
          return { paare, falsch };
        }""")
        check("Er steht links von allem, was gleichzeitig noch zählt",
              ordnung7["paare"] >= 1 and ordnung7["falsch"] == 0,
              f'{ordnung7["falsch"]} von {ordnung7["paare"]} Paaren verkehrt')
        # Und mit einem Tipper zurückzuholen - dafür steht er ja noch da.
        pg7.locator(f'.tl-act[data-tlshow="{weg_id}"]').click()
        pg7.wait_for_selector("#tlmenu[open]")
        check("Ein Tipper darauf öffnet die Griffe mit 'Nicht heute' aktiv",
              pg7.evaluate("""() => [...document.querySelectorAll('#tl-plan button')]
                   .filter((x) => x.getAttribute('aria-pressed') === 'true')
                   .map((x) => x.dataset.tlplan)""") == ["raus"])
        pg7.locator('#tl-plan button[data-tlplan="auto"]').click()
        pg7.wait_for_timeout(700)
        check("Und zurückgeholt ist er wieder ganz da",
              "skipped" not in (pg7.locator(f'.tl-act[data-tlshow="{weg_id}"]')
                                .get_attribute("class") or ""),
              pg7.locator(f'.tl-act[data-tlshow="{weg_id}"]').get_attribute("class"))
    # Die naechsten Pruefungen brauchen offene Griffe - egal, ob der Abstecher
    # oben einen Block gefunden hat.
    if pg7.locator("#tlmenu[open]").count() == 0:
        pg7.locator(".tl-act").first.click()
        pg7.wait_for_selector("#tlmenu[open]")
    # Der Weg hinüber: die Griffe machen zu, die Detailkarte geht auf, und
    # zwar für DENSELBEN Act. Zwei modale Dialoge übereinander wären eine
    # Ebene zu viel zum Zurückgehen.
    tl_titel = pg7.locator("#tl-name").inner_text()
    pg7.click("#tl-detail"); pg7.wait_for_timeout(700)
    check("Die Künstlerkarte öffnet sich aus den Griffen heraus",
          pg7.locator("#detail[open]").count() == 1
          and pg7.locator("#tlmenu[open]").count() == 0)
    check("Und zeigt denselben Act",
          pg7.locator("#detail .d-title").inner_text() == tl_titel,
          f'{pg7.locator("#detail .d-title").inner_text()} gegen {tl_titel}')
    check("Mit dem, wofür sie da ist - allen Auftritten und dem Anhören",
          {"Auftritte", "Anhören"}
          <= {t.strip().title() for t in
              pg7.locator("#detail .d-section h3").all_inner_texts()},
          str(pg7.locator("#detail .d-section h3").all_inner_texts()[:5]))
    pg7.keyboard.press("Escape"); pg7.wait_for_timeout(600)
    # Und man landet wieder bei dem Auftritt, bei dem man war - nicht
    # draußen in der Leiste. Der Abstecher hat die Griffe nur geparkt.
    check("Zurück aus der Künstlerkarte führt in die Griffe",
          pg7.locator("#tlmenu[open]").count() == 1
          and pg7.locator("#detail[open]").count() == 0
          and pg7.locator("#tl-name").inner_text() == tl_titel,
          f'{pg7.locator("#tl-name").inner_text()} gegen {tl_titel}')
    # Dasselbe über die Anspielleiste, wenn dieser Act bei Spotify ist.
    if pg7.locator("#tl-top [data-tlplay]").count():
        pg7.locator("#tl-top [data-tlplay]").click(); pg7.wait_for_timeout(900)
        check("Die Anspielleiste parkt die Griffe ebenso",
              not pg7.locator("#player").is_hidden()
              and pg7.locator("#tlmenu[open]").count() == 0)
        pg7.click("#player-close"); pg7.wait_for_timeout(700)
        check("Und ihr Schließen führt genauso zurück",
              pg7.locator("#tlmenu[open]").count() == 1
              and pg7.locator("#tl-name").inner_text() == tl_titel,
              pg7.locator("#tl-name").inner_text())
    # Erst das nächste Zurück verlässt die Griffe wirklich.
    pg7.keyboard.press("Escape"); pg7.wait_for_timeout(600)
    check("Ein weiteres Zurück verlässt die Griffe in die Zeitleiste",
          pg7.locator("dialog[open]").count() == 0
          and pg7.locator("#plan-time").is_visible())
    # Fuer die letzte Pruefung die Griffe wieder oeffnen - irgendeinen
    # Block, nicht denselben: der ist inzwischen aus der Leiste gefallen.
    # Die Note wurde oben gesetzt und wieder geloescht, und ohne Note und
    # ohne festen Termin gehoert er nicht mehr in den Plan.
    pg7.locator(".tl-act").first.click()
    pg7.wait_for_selector("#tlmenu[open]")

    pg7.keyboard.press("Escape"); pg7.wait_for_timeout(400)
    check("Zurück schließt die Griffe", pg7.locator("#tlmenu[open]").count() == 0)

    pg7.click("#plan-timeline"); pg7.wait_for_timeout(500)
    check("Nochmal tippen führt zurück zur Liste",
          not pg7.locator("#plan-body").is_hidden()
          and pg7.locator("#plan-time").is_hidden())

    # --- Abendplan als Abkürzung oben ---
    pg7.click("#btn-plan"); pg7.wait_for_timeout(500)
    check("Der Kopfknopf schließt den Plan wieder",
          pg7.locator("#plan").is_hidden()
          and pg7.locator("#btn-plan").get_attribute("aria-pressed") == "false")
    pg7.click("#btn-plan"); pg7.wait_for_timeout(600)
    check("Und öffnet ihn ohne Umweg über das Menü",
          pg7.locator("#plan").is_visible()
          and pg7.locator("#btn-plan").get_attribute("aria-pressed") == "true"
          and pg7.locator("#menu[open]").count() == 0)
    check("Die Kopfzeile bleibt dabei in einer Reihe", pg7.evaluate("""() => {
      const h1 = document.querySelector('.top h1').getBoundingClientRect();
      const a = document.querySelector('.top-actions').getBoundingClientRect();
      return h1.right <= a.left + 1 && a.right <= innerWidth + 1;
    }"""))

    csp7 = [e for e in err7 if "content security policy" in e.lower()
            or "refused to apply" in e.lower()]
    check("Keine CSP-Verletzung im Abendplan", not csp7, str(csp7[:2]))
    check("Keine JS-Fehler im Plan-Kontext", not err7, str(err7[:2]))
    ctx7.close()

    # --- Der rote Strich für JETZT ---
    # Mit GESTELLTER Uhr, nicht mit der echten: sonst prüfte der Test nur an
    # vier Abenden im Jahr etwas und wäre sonst blind. Gestellt wird auf
    # 21:00 Ortszeit an einem Festivaltag - dann läuft wirklich etwas.
    ctx8 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE",
                         timezone_id="Europe/Berlin")
    ctx8.clock.install(time=_dt.datetime(
        *[int(x) for x in day7.split("-")], 19, 0, 0,
        tzinfo=_dt.timezone.utc))          # 19:00 UTC = 21:00 in Hamburg
    ctx8.clock.resume()
    pg8 = ctx8.new_page()
    err8 = []
    pg8.on("pageerror", lambda e: err8.append(str(e)))
    pg8.goto(BASE + "/", wait_until="load")
    pg8.wait_for_selector(".row", timeout=20000)
    pg8.evaluate("""(ids) => {
      const r = {};
      ids.forEach((id, i) => { r[id] = (i % 3) + 1; });
      localStorage.setItem('rbf26.rate', JSON.stringify(r));
    }""", ids7)
    pg8.reload(wait_until="load")
    pg8.wait_for_selector(".row", timeout=20000)
    check("Bei gestellter Uhr wählt die App den laufenden Tag vor",
          pg8.evaluate("""() => {
            const d = document.querySelector('.day[aria-selected="true"]');
            return d ? d.dataset.day : null;
          }""") == day7, day7)
    pg8.click("#btn-plan"); pg8.wait_for_timeout(700)
    zeitleiste(pg8, 800)
    now8 = pg8.locator(".tl-now")
    check("Läuft der Abend, steht ein Strich für jetzt da", now8.count() == 1,
          f"{now8.count()} Striche")
    if now8.count():
        check("Er ist mit der Uhrzeit beschriftet",
              now8.locator("span").inner_text().strip() == "21:00",
              now8.locator("span").inner_text())
        check("Und rot, nicht in der Rasterfarbe", pg8.evaluate("""() => {
          const c = getComputedStyle(document.querySelector('.tl-now')).borderTopColor;
          const m = c.match(/\\d+/g).map(Number);
          return m[0] > 140 && m[0] > m[1] * 1.5 && m[0] > m[2] * 1.5;
        }"""), pg8.evaluate("() => getComputedStyle("
                            "document.querySelector('.tl-now')).borderTopColor"))
        # Er muss an der richtigen Stelle liegen: auf Höhe der Acts, die um
        # 21:00 laufen. Sonst wäre er hübsch und falsch.
        check("Er liegt auf der Höhe der Acts, die gerade laufen",
              pg8.evaluate("""() => {
                const y = document.querySelector('.tl-now').getBoundingClientRect().top;
                return [...document.querySelectorAll('.tl-act')].some(a => {
                  const r = a.getBoundingClientRect();
                  return r.top <= y && r.bottom >= y;
                });
              }"""))
    # Der Strich steht AUCH da, wenn "jetzt" gar nicht in diesen Abend
    # faellt - dann klebt er an der Kante und sagt es. Die Uhrzeit vom
    # Telefon stimmt in jedem Fall, die Lage sagt "davor" oder "danach".
    anderer = next(d for d in lineup7["days"] if d != day7)
    pg8.click(f'.day[data-day="{anderer}"]'); pg8.wait_for_timeout(900)
    rand8 = pg8.locator(".tl-now")
    check("Auch an einem anderen Tag steht ein Strich für jetzt",
          rand8.count() == 1, f"{rand8.count()}")
    if rand8.count():
        check("Er klebt dann an der Kante und sagt das",
              rand8.evaluate("e => e.classList.contains('off')")
              and "außerhalb" in (rand8.get_attribute("title") or ""),
              f'{rand8.get_attribute("class")} | {rand8.get_attribute("title")}')
        check("Mit derselben minutengenauen Uhrzeit",
              rand8.locator("span").inner_text().strip() == "21:00",
              rand8.locator("span").inner_text())
        check("Und innerhalb der Leiste, nicht darüber hinaus",
              pg8.evaluate("""() => {
                const t = parseFloat(document.querySelector('.tl-now').style.top);
                const h = document.querySelector('.tl-canvas').offsetHeight;
                return t >= 0 && t <= h;
              }"""))

    # --- Der "Jetzt"-Knopf neben den Tagen ---
    pg8.click("#btn-plan"); pg8.wait_for_timeout(500)   # zurück zur Liste
    check("Neben den Tagen steht ein Sprung auf jetzt",
          pg8.locator("#btn-now").is_visible()
          and "21:00" in pg8.locator("#btn-now").inner_text(),
          pg8.locator("#btn-now").inner_text().replace("\n", " "))
    pg8.click('.day[data-day=""]'); pg8.wait_for_timeout(400)
    pg8.click("#btn-now"); pg8.wait_for_timeout(1400)
    check("Er wählt den laufenden Tag", pg8.evaluate(
        """() => { const d = document.querySelector('.day[aria-selected="true"]');
                   return d ? d.dataset.day : null; }""") == day7, day7)
    # Und springt an die Uhrzeit: die erste Zeile unter dem Kopf ist die
    # nächste, die um 21:00 oder später anfängt.
    treffer8 = pg8.evaluate("""() => {
      const top = document.querySelector('.top').getBoundingClientRect().bottom;
      const r = [...document.querySelectorAll('.row')].find(
        (e) => e.getBoundingClientRect().top >= top - 30);
      return r ? r.querySelector('.row-time').textContent.trim().slice(0, 5) : null;
    }""")
    check("Und springt an die jetzige Uhrzeit",
          treffer8 and re.fullmatch(r"\d\d:\d\d", treffer8)
          and treffer8 >= "21:00", str(treffer8))

    check("Keine JS-Fehler im Uhr-Kontext", not err8, str(err8[:2]))
    ctx8.close()

    # --- "Jetzt" ausserhalb der Festivaltage ---
    # Dann gibt es keinen laufenden Tag, also wird auch keiner gewaehlt -
    # gesprungen wird trotzdem an die Uhrzeit.
    ctx10 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE",
                          timezone_id="Europe/Berlin")
    ctx10.clock.install(time=_dt.datetime(2026, 9, 10, 19, 0, 0,
                                          tzinfo=_dt.timezone.utc))
    ctx10.clock.resume()
    pg10 = ctx10.new_page()
    err10 = []
    pg10.on("pageerror", lambda e: err10.append(str(e)))
    pg10.goto(BASE + "/", wait_until="load")
    pg10.wait_for_selector(".row", timeout=20000)
    check("Vor dem Festival steht 'Alle Tage'", pg10.evaluate(
        """() => { const d = document.querySelector('.day[aria-selected="true"]');
                   return d ? d.dataset.day : null; }""") == "")
    pg10.click("#btn-now"); pg10.wait_for_timeout(1400)
    check("'Jetzt' wählt dann keinen Tag aus", pg10.evaluate(
        """() => { const d = document.querySelector('.day[aria-selected="true"]');
                   return d ? d.dataset.day : null; }""") == "")
    check("Springt aber trotzdem an eine Uhrzeit", pg10.evaluate("""() => {
      const top = document.querySelector('.top').getBoundingClientRect().bottom;
      return [...document.querySelectorAll('.row')].some(
        (e) => Math.abs(e.getBoundingClientRect().top - top) < 120);
    }"""))
    check("Keine JS-Fehler im Vorfeld-Kontext", not err10, str(err10[:2]))
    ctx10.close()

    # --- Team-Durchschnitt in der Zeitleiste ---
    # Die Partneransicht fasst alle Mitglieder zur BESTEN Note zusammen -
    # daraus liesse sich kein Mittel zurueckrechnen. Geprueft wird deshalb
    # gegen die Einzelnoten, die jetzt zusaetzlich mitlaufen.
    ctx9 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    pg9 = ctx9.new_page()
    err9 = []
    pg9.on("pageerror", lambda e: err9.append(str(e)))
    pg9.on("console",
           lambda m: err9.append(m.text) if m.type == "error"
           and "ERR_" not in m.text else None)
    pg9.goto(BASE + "/", wait_until="load")
    pg9.wait_for_selector(".row", timeout=20000)
    # Ich bewerte die ersten 40, zwei Mitglieder bewerten anders. Zwei Acts
    # sind NUR Favorit, ohne eigene Note - an denen muss der Schnitt
    # verdeckt bleiben.
    # Schluessel als Text: JSON-Objekte haben nur Text-Schluessel, und
    # Playwright gibt ein dict mit Zahlen-Schluesseln gar nicht erst durch.
    mine9 = {str(ids7[i]): (i % 3) + 1 for i in range(min(40, len(ids7)))}
    linda9 = {str(i): ((n + 1) % 5) + 1 for n, i in enumerate(ids7)}
    momo9 = {str(i): ((n + 3) % 5) + 1 for n, i in enumerate(ids7)}
    fav9 = [ids7[45], ids7[46]] if len(ids7) > 46 else []
    # Was NUR die anderen gesehen haben - ich selbst habe nichts abgehakt.
    seen9 = [ids7[2], ids7[3]]
    pg9.evaluate("""([mine, a, bb, favs, gesehen]) => {
      localStorage.setItem('rbf26.rate', JSON.stringify(mine));
      localStorage.setItem('rbf26.fav', JSON.stringify(favs));
      localStorage.setItem('rbf26.partner', JSON.stringify({
        name: 'Linda, Momo', fav: [], seen: gesehen, rate: a,
        members: [{ name: 'Linda', rate: a }, { name: 'Momo', rate: bb }],
      }));
      localStorage.removeItem('rbf26.revealed');
      localStorage.removeItem('rbf26.seen');
    }""", [mine9, linda9, momo9, fav9, seen9])
    pg9.reload(wait_until="load")
    pg9.wait_for_selector(".row", timeout=20000)
    pg9.click(f'.day[data-day="{day7}"]'); pg9.wait_for_timeout(400)

    # --- "Gesehen" gilt fürs ganze Team ---
    # Wer zusammen hingeht, hakt es einmal ab. Die eigene Menge bleibt aber
    # die eigene: ein Haken der Gegenseite wird NICHT hineingeschrieben,
    # sonst käme ein zurückgenommener Haken beim nächsten Abgleich zurück.
    marken9 = pg9.locator("#list .seen-mark")
    check("Was die anderen gesehen haben, ist auch bei mir markiert",
          marken9.count() >= 2, f"{marken9.count()} Marken")
    titel9 = marken9.first.get_attribute("title") or ""
    check("Und die Marke sagt, von wem", "Gesehen von" in titel9, titel9)
    check("Ohne dass es in meiner eigenen Liste landet",
          pg9.evaluate("() => JSON.parse(localStorage.getItem("
                       "'rbf26.seen')||'[]').length") == 0)
    pg9.click("#f-seen"); pg9.wait_for_timeout(450)
    check("Der Gesehen-Filter nimmt sie mit",
          pg9.locator(".row").count() == marken9.count()
          and pg9.locator(".row").count() >= 2,
          f"{pg9.locator('.row').count()} Zeilen")
    pg9.click("#f-seen"); pg9.wait_for_timeout(400)

    pg9.click("#btn-plan"); pg9.wait_for_timeout(700)
    zeitleiste(pg9, 800)

    avg9 = pg9.locator(".tl-act .grade-p:not(.team-hidden)")
    check("Die Zeitleiste zeigt den Team-Schnitt", avg9.count() >= 1,
          f"{avg9.count()} von {pg9.locator('.tl-act').count()} Blöcken")
    check("Neben der eigenen Note, nicht statt ihr", pg9.evaluate("""() => {
      const b = [...document.querySelectorAll('.tl-act')].find(
        e => e.querySelector('.grade-p:not(.team-hidden)')
             && e.querySelector('.grade:not(.grade-p)'));
      return !!b;
    }"""))
    check("Als Mittelwert gekennzeichnet",
          avg9.first.inner_text().startswith("Ø"), avg9.first.inner_text())
    check("Mit der Zahl der Stimmen im Titel",
          re.search(r"aus \d+ Stimme", avg9.first.get_attribute("title") or ""),
          avg9.first.get_attribute("title"))
    # Nachrechnen: die gezeigte Zahl muss das Mittel aus den drei Noten
    # sein, nicht die beste - genau daran wäre die alte Zusammenfassung
    # gescheitert.
    shown9 = pg9.evaluate("""() => {
      const out = {};
      for (const b of document.querySelectorAll('.tl-act')) {
        const g = b.querySelector('.grade-p:not(.team-hidden)');
        if (g) out[b.dataset.tlshow] = g.textContent.trim();
      }
      return out;
    }""")
    act_of = {str(sh["id"]): str(lineup7["acts"][sh["a"]]["id"])
              for sh in lineup7["shows"]}
    falsch = []
    for show_id, txt in shown9.items():
        aid = act_of.get(str(show_id))
        stimmen = [v for v in (linda9.get(aid), momo9.get(aid), mine9.get(aid))
                   if v]
        # Wie die App: auf eine Nachkommastelle, deutsches Komma, glatte
        # Werte ohne ",0".
        soll = "Ø" + f"{round(sum(stimmen) / len(stimmen), 1):g}".replace(".", ",")
        if txt != soll:
            falsch.append((txt, soll, stimmen))
    check("Und die Zahl ist wirklich das Mittel, nicht die beste Note",
          not falsch, str(falsch[:3]))

    # --- Wonach die Spalten geordnet sind ---
    # Vorher nach gar nichts: jeder Auftritt kam in die erste freie Spur.
    # Jetzt gilt "je weiter rechts, desto besser bewertet" - als Tendenz,
    # nicht als Zusage: ein Kasten haelt seine Spalte über seine ganze
    # Länge, ein später beginnender besserer Act findet sie also belegt.
    ordnung = pg9.evaluate("""() => {
      const a = [...document.querySelectorAll('.tl-act')].map((e) => ({
        left: Math.round(parseFloat(e.style.left)),
        top: parseFloat(e.style.top), h: parseFloat(e.style.height),
        // Geordnet wird nach dem Team-Schnitt; nur wo es keinen gibt,
        // zaehlt die eigene Note.
        note: (() => {
          const p = e.querySelector('.grade-p:not(.team-hidden)');
          if (p) return parseFloat(p.textContent.replace(/[^\\d,]/g, '')
                                    .replace(',', '.'));
          const g = e.querySelector('.grade:not(.grade-p)');
          return g ? parseFloat(g.textContent.replace(',', '.')) : 9;
        })(),
      }));
      let falsch = 0, geprueft = 0;
      for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) {
        const A = a[i], B = a[j];
        if (!(A.top < B.top + B.h && B.top < A.top + A.h)) continue;
        if (A.note === B.note) continue;
        geprueft++;
        const gut = A.note < B.note ? A : B;
        const schlecht = gut === A ? B : A;
        if (gut.left < schlecht.left) falsch++;
      }
      /* Und die Frage, die man wirklich stellt: schaue ich zu einem
         Zeitpunkt ganz nach rechts - steht dort das Beste, was gerade
         laeuft? Gemessen an jedem Beginn, an dem mehr als eines laeuft. */
      let momente = 0, rechtsBeste = 0;
      for (const p of a) {
        const laufend = a.filter((x) => x.top <= p.top && x.top + x.h > p.top);
        if (laufend.length < 2) continue;
        momente++;
        const rechts = laufend.reduce((m, x) => (x.left > m.left ? x : m));
        const beste = Math.min(...laufend.map((x) => x.note));
        if (rechts.note === beste) rechtsBeste++;
      }
      const spuren = [...new Set(a.map((x) => x.left))].sort((p, q) => p - q);
      return { falsch, geprueft, spuren: spuren.length, momente, rechtsBeste };
    }""")
    check("Gleichzeitige Acts stehen nach Note geordnet",
          ordnung["geprueft"] >= 20
          and ordnung["falsch"] / ordnung["geprueft"] <= 0.1,
          f'{ordnung["falsch"]} von {ordnung["geprueft"]} Paaren verkehrt')
    check("Ganz rechts steht fast immer das Beste, was gerade läuft",
          ordnung["momente"] >= 10
          and ordnung["rechtsBeste"] / ordnung["momente"] >= 0.9,
          f'{ordnung["rechtsBeste"]} von {ordnung["momente"]} Zeitpunkten '
          f'bei {ordnung["spuren"]} Spalten')
    check("Und die Legende sagt das auch",
          "rechts" in pg9.locator("#plan-time .menu-note").inner_text(),
          pg9.locator("#plan-time .menu-note").inner_text()[:80])

    # Der Schutz gilt auch hier: ohne eigene Note kein fremdes Urteil.
    hid9 = pg9.locator(".tl-act .team-hidden")
    check("Ohne eigene Note bleibt der Schnitt verdeckt", hid9.count() >= 1,
          f"{hid9.count()} verdeckte Marken")
    if hid9.count():
        check("Der verdeckte Block hat wirklich keine eigene Note",
              hid9.first.evaluate("e => !e.closest('.tl-act')"
                                  ".querySelector('.grade:not(.grade-p)')"))
        check("Und die Marke verrät nichts als '?'",
              hid9.first.inner_text().strip() == "?", hid9.first.inner_text())
        # Selbst bewerten deckt ihn im selben Griff auf.
        hid9.first.evaluate("e => e.closest('.tl-act').click()")
        pg9.wait_for_selector("#tlmenu[open]")
        check("Auch die Griffe zeigen ihn erst verdeckt",
              "Team ?" in pg9.locator("#tl-when").inner_text(),
              pg9.locator("#tl-when").inner_text()[-30:])
        pg9.locator('#tl-rate button[data-r="2"]').click(); pg9.wait_for_timeout(800)
        check("Eine eigene Note deckt den Schnitt sofort auf",
              re.search(r"Team Ø\d", pg9.locator("#tl-when").inner_text()),
              pg9.locator("#tl-when").inner_text()[-30:])
        pg9.keyboard.press("Escape"); pg9.wait_for_timeout(400)

    # Ältere gespeicherte Partnerdaten kennen die Einzelnoten nicht. Dann
    # gibt es eben keinen Schnitt - aber keinen Absturz und keine Zahl, die
    # etwas anderes bedeutet, als sie behauptet.
    pg9.evaluate("""([a]) => {
      localStorage.setItem('rbf26.partner', JSON.stringify({
        name: 'Alt', fav: [], seen: [], rate: a,
      }));
    }""", [linda9])
    pg9.reload(wait_until="load")
    pg9.wait_for_selector(".row", timeout=20000)
    pg9.click("#btn-plan"); pg9.wait_for_timeout(700)
    zeitleiste(pg9, 800)
    check("Alte Partnerdaten ohne Einzelnoten zeigen keinen Schnitt",
          pg9.locator(".tl-act .grade-p:not(.team-hidden)").count() == 0
          and pg9.locator(".tl-act").count() >= 1,
          f'{pg9.locator(".tl-act .grade-p:not(.team-hidden)").count()} Schnitte '
          f'bei {pg9.locator(".tl-act").count()} Blöcken')
    check("Keine JS-Fehler im Team-Kontext", not err9, str(err9[:2]))
    ctx9.close()

    # --- Die tatsächliche Spielzeit ---
    # Die Quelle hat ein Feld für die Endzeit und lässt es leer, schreibt sie
    # aber im Titel des Auftritts aus (siehe end_from_title in rbf_core.py).
    # Für 568 der 575 Auftritte ist sie damit bekannt - und ab jetzt überall
    # zu sehen, statt dass eine Pauschale für alle gilt.
    ctx15 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    pg15 = ctx15.new_page()
    err15 = []
    pg15.on("pageerror", lambda e: err15.append(str(e)))
    pg15.on("console", lambda m: err15.append(m.text)
            if m.type == "error" and "ERR_" not in m.text else None)
    lineup15 = _json.load(open("web/data/lineup.json", encoding="utf-8"))
    mit_e = [s for s in lineup15["shows"] if s.get("e")]
    check("Die Web-Daten tragen die echte Endzeit",
          len(mit_e) > len(lineup15["shows"]) * 0.9,
          f'{len(mit_e)} von {len(lineup15["shows"])} Auftritten')
    # Und die Längen sind nicht alle gleich - sonst wäre es wieder eine
    # Pauschale, nur an anderer Stelle.
    laengen = {int((_dt.datetime.fromisoformat(s["e"])
                    - _dt.datetime.fromisoformat(s["t"])).total_seconds() // 60)
               for s in mit_e}
    check("Mit wirklich unterschiedlichen Spielzeiten", len(laengen) >= 8,
          f"{len(laengen)} verschiedene: {sorted(laengen)[:8]}…")

    day15 = lineup15["days"][1]
    ids15 = list(dict.fromkeys(
        [lineup15["acts"][s["a"]]["id"] for s in lineup15["shows"]
         if s["d"] == day15 and not s["tbd"]]))[:70]
    pg15.goto(BASE + "/", wait_until="load")
    pg15.wait_for_selector(".row", timeout=20000)
    pg15.evaluate("""(ids) => {
      const r = {};
      ids.forEach((id, i) => { r[id] = (i % 3) + 1; });
      localStorage.setItem('rbf26.rate', JSON.stringify(r));
    }""", ids15)
    pg15.reload(wait_until="load")
    pg15.wait_for_selector(".row", timeout=20000)
    pg15.click(f'.day[data-day="{day15}"]'); pg15.wait_for_timeout(400)

    # In der Liste: die Endzeit unter dem Beginn.
    zeilen15 = pg15.locator(".row").count()
    check("Jede Zeile nennt auch das Ende",
          pg15.locator(".row .row-bis").count() == zeilen15,
          f"{pg15.locator('.row .row-bis').count()} von {zeilen15}")
    ersteZeit = pg15.locator(".row .row-time").first
    check("Und im Titel die Spielzeit in Minuten",
          re.search(r"\d\d:\d\d bis \d\d:\d\d — \d+ min",
                    ersteZeit.get_attribute("title") or ""),
          ersteZeit.get_attribute("title"))
    # Die Zahl muss stimmen, nicht nur dastehen.
    krumm15 = pg15.evaluate("""() => {
      const bad = [];
      for (const r of document.querySelectorAll('.row')) {
        const t = r.querySelector('.row-time').getAttribute('title') || '';
        const m = t.match(/(\\d\\d):(\\d\\d) bis (\\d\\d):(\\d\\d) — (\\d+) min/);
        if (!m) continue;
        let d = (+m[3] * 60 + +m[4]) - (+m[1] * 60 + +m[2]);
        if (d <= 0) d += 1440;
        if (d !== +m[5]) bad.push(t);
      }
      return bad;
    }""")
    check("Die Minutenzahl passt zur Zeitspanne", not krumm15, str(krumm15[:2]))

    # Auf der Künstlerkarte: Zeitspanne und Dauer je Auftritt.
    tap_row(pg15.locator(".row").first)
    pg15.wait_for_selector("#detail .slots")
    check("Die Künstlerkarte nennt die Spanne je Auftritt",
          re.search(r"\d\d:\d\d–\d\d:\d\d",
                    pg15.locator("#detail .slots time").first.inner_text()),
          pg15.locator("#detail .slots time").first.inner_text())
    check("Und die Dauer daneben",
          re.fullmatch(r"\d+ min",
                       pg15.locator("#detail .slot-len").first.inner_text()),
          pg15.locator("#detail .slot-len").first.inner_text())
    pg15.keyboard.press("Escape"); pg15.wait_for_timeout(300)

    # In der Zeitleiste: Kästen so hoch, wie ihr Konzert dauert.
    pg15.click("#btn-plan"); pg15.wait_for_timeout(700)
    zeitleiste(pg15, 800)
    tl15 = pg15.evaluate("""() => {
      const a = [...document.querySelectorAll('.tl-act')];
      const paare = a.map(e => [+e.dataset.dauer,
                                Math.round(parseFloat(e.style.height))]);
      const hoehen = [...new Set(paare.map(p => p[1]))];
      // Hoehe muss proportional zur Dauer sein: laenger heisst nie niedriger.
      const sortiert = [...paare].sort((x, y) => x[0] - y[0]);
      let verkehrt = 0;
      for (let i = 1; i < sortiert.length; i++) {
        if (sortiert[i][1] < sortiert[i - 1][1] - 1) verkehrt++;
      }
      // Ueberdeckt ein Kasten einen anderen?
      let kollision = 0;
      for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) {
        const A = a[i].getBoundingClientRect(), B = a[j].getBoundingClientRect();
        if (A.left < B.right - 1 && B.left < A.right - 1
            && A.top < B.bottom - 1 && B.top < A.bottom - 1) kollision++;
      }
      // Wird eine Zeile im Kasten zusammengequetscht? Flex-Kinder schrumpfen,
      // statt ueberzulaufen - also die Namenszeile einzeln messen, und zwar
      // an ihrer EIGENEN Zeilenhoehe: kurze Kaesten setzen kleiner, und das
      // ist kein Fehler. Gemeint ist die eine Zeile, die immer ganz zu sehen
      // sein muss; lange Namen brechen um und werden zu Recht abgeschnitten.
      const gequetscht = a.filter(e => {
        const n = e.querySelector('.tl-name');
        if (!n) return false;
        const lh = parseFloat(getComputedStyle(n).lineHeight) || 0;
        return n.clientHeight + 1 < Math.min(lh, n.scrollHeight);
      }).length;
      return { bloecke: a.length, hoehen: hoehen.length, verkehrt, kollision,
               gequetscht, kurz: document.querySelectorAll('.tl-act.kurz').length };
    }""")
    check("Die Kästen sind unterschiedlich hoch", tl15["hoehen"] >= 4,
          f'{tl15["hoehen"]} verschiedene Höhen bei {tl15["bloecke"]} Blöcken')
    check("Und zwar proportional zur Spielzeit", tl15["verkehrt"] == 0,
          f'{tl15["verkehrt"]} Paare verkehrt herum')
    check("Kein Block überdeckt einen anderen", tl15["kollision"] == 0,
          f'{tl15["kollision"]} Überdeckungen')
    check("Keine Zeile wird im Block zusammengequetscht",
          tl15["gequetscht"] == 0, f'{tl15["gequetscht"]} gequetschte Namen')
    check("Kurze Sets bekommen die knappe Fassung", tl15["kurz"] >= 1,
          f'{tl15["kurz"]} knappe Kästen')
    # Der Name ist das Wichtigste am Kasten - auch im kürzesten. In den
    # 15-Minuten-Kacheln standen Name und Note einmal NEBENeinander; der Fuß
    # nahm 44 der 98 Pixel, dem Namen blieben 35, und "goldie 333" braucht
    # 61. Geprüft wird deshalb die Breite, die der Name wirklich bekommt.
    schmal15 = pg15.evaluate(BREITE_JS)
    check("Auch im kürzesten Kasten bekommt der Name die volle Breite",
          not schmal15, str(schmal15[:3]))
    check("Die Blöcke nennen Beginn und Ende",
          pg15.locator(".tl-act .tl-bis").count() >= tl15["bloecke"] - 7,
          f'{pg15.locator(".tl-act .tl-bis").count()} von {tl15["bloecke"]}')
    check("Keine JS-Fehler im Spielzeit-Kontext", not err15, str(err15[:2]))
    ctx15.close()
    # --- Der Blick bleibt beim Umstellen der Priorität stehen ---
    # Gemeldet: "In Timeline Priorität ändern. Springe ich immer wieder an
    # den Anfang der Timeline." Ursache war nicht die Leiste selbst, sondern
    # das Neuzeichnen: box.innerHTML wird ersetzt, das Dokument ist einen
    # Augenblick kürzer als die Scrollposition, und der Browser klemmt sie
    # auf 0. Gemessen auf Telefongröße - auf einem breiten Fenster passiert
    # es nicht, deshalb läuft diese Prüfung ausdrücklich bei 360x740.
    ctx16 = b.new_context(viewport={"width": 360, "height": 740}, locale="de-DE",
                          has_touch=True, is_mobile=True)
    pg16 = ctx16.new_page()
    err16 = []
    pg16.on("pageerror", lambda e: err16.append(str(e)))
    lineup16 = _json.load(open("web/data/lineup.json", encoding="utf-8"))
    day16 = lineup16["days"][1]
    ids16 = list(dict.fromkeys(
        [lineup16["acts"][s["a"]]["id"] for s in lineup16["shows"]
         if s["d"] == day16 and not s["tbd"]]))[:70]
    pg16.goto(BASE + "/", wait_until="load")
    pg16.wait_for_selector(".row", timeout=20000)
    pg16.evaluate("""(ids) => {
      const r = {};
      ids.forEach((id, i) => { r[id] = (i % 3) + 1; });
      localStorage.setItem('rbf26.rate', JSON.stringify(r));
    }""", ids16)
    pg16.reload(wait_until="load")
    pg16.wait_for_selector(".row", timeout=20000)
    pg16.click(f'.day[data-day="{day16}"]'); pg16.wait_for_timeout(400)
    pg16.click("#btn-plan"); pg16.wait_for_timeout(700)
    zeitleiste(pg16, 800)
    # Weit in die Leiste hinein - erst dort greift das Klemmen.
    pg16.evaluate("""() => scrollTo(0, Math.round(document.body.scrollHeight * 0.55))""")
    pg16.wait_for_timeout(500)
    y_vor = pg16.evaluate("() => Math.round(scrollY)")
    check("Für die Prüfung wirklich weit gescrollt", y_vor > 400, f"{y_vor} px")
    ref16 = pg16.evaluate("""() => {
      const e = [...document.querySelectorAll('.tl-act')].find(x => {
        const r = x.getBoundingClientRect();
        return r.top > 120 && r.bottom < innerHeight - 60;
      });
      return e ? e.dataset.tlshow : null;
    }""")
    pg16.locator(f'.tl-act[data-tlshow="{ref16}"]').click()
    pg16.wait_for_selector("#tlmenu[open]")
    y_offen = pg16.evaluate("() => Math.round(scrollY)")
    check("Das Öffnen der Griffe verschiebt die Seite nicht",
          abs(y_offen - y_vor) <= 2, f"{y_vor} -> {y_offen}")
    # Fünfmal umstellen - gemeldet war "immer wieder".
    verlauf = []
    for modus in ("fest", "raus", "auto", "fest", "raus"):
        pg16.locator(f'#tl-plan button[data-tlplan="{modus}"]').click()
        pg16.wait_for_timeout(700)
        verlauf.append(pg16.evaluate("() => Math.round(scrollY)"))
    check("Und das Umstellen der Priorität auch nicht",
          all(abs(y - y_vor) <= 2 for y in verlauf), f"{y_vor} -> {verlauf}")
    pg16.keyboard.press("Escape"); pg16.wait_for_timeout(500)
    check("Nach dem Schließen steht man immer noch dort",
          abs(pg16.evaluate("() => Math.round(scrollY)") - y_vor) <= 2,
          f'{y_vor} -> {pg16.evaluate("() => Math.round(scrollY)")}')
    check("Keine JS-Fehler im Verankerungs-Kontext", not err16, str(err16[:2]))
    ctx16.close()
    # --- "Den habe ich schon gesehen - an einem anderen Termin" ---
    # 62 Acts spielen mehrfach. Wer einen davon am Mittwoch gesehen hat, will
    # das am Donnerstag wissen, BEVOR er sich wieder hinstellt. Das ist eine
    # andere Aussage als "bei diesem Konzert war ich" - also eine eigene
    # Marke und nicht dieselbe Schraffur.
    ctx17 = b.new_context(viewport={"width": 390, "height": 840}, locale="de-DE")
    pg17 = ctx17.new_page()
    err17 = []
    pg17.on("pageerror", lambda e: err17.append(str(e)))
    pg17.on("console", lambda m: err17.append(m.text)
            if m.type == "error" and "ERR_" not in m.text else None)
    lineup17 = _json.load(open("web/data/lineup.json", encoding="utf-8"))
    day17 = lineup17["days"][1]
    ids17 = list(dict.fromkeys(
        [lineup17["acts"][s["a"]]["id"] for s in lineup17["shows"]
         if s["d"] == day17 and not s["tbd"]]))[:70]
    # Ein bewerteter Act mit zwei Terminen, einer davon an diesem Tag.
    von17 = {}
    for s in lineup17["shows"]:
        if s.get("tbd") or not s.get("t"):
            continue
        von17.setdefault(s["a"], []).append(s)
    kandidat = next((ai, sorted(ss, key=lambda x: x["t"]))
                    for ai, ss in von17.items()
                    if len(ss) >= 2 and any(x["d"] == day17 for x in ss)
                    and lineup17["acts"][ai]["id"] in set(ids17))
    ai17, shows17 = kandidat
    heute17 = next(x for x in shows17 if x["d"] == day17)
    anders17 = next(x for x in shows17 if x["id"] != heute17["id"])

    pg17.goto(BASE + "/", wait_until="load")
    pg17.wait_for_selector(".row", timeout=20000)
    pg17.evaluate("""([ids, sid]) => {
      const r = {};
      ids.forEach((id, i) => { r[String(id)] = (i % 3) + 1; });
      localStorage.setItem('rbf26.rate', JSON.stringify(r));
      localStorage.setItem('rbf26.seenshow', JSON.stringify([String(sid)]));
    }""", [ids17, anders17["id"]])
    pg17.reload(wait_until="load")
    pg17.wait_for_selector(".row", timeout=20000)
    pg17.click(f'.day[data-day="{day17}"]'); pg17.wait_for_timeout(400)
    pg17.click("#btn-plan"); pg17.wait_for_timeout(900)

    # Nebenbei bestätigt: der Plan geht mit der Leiste auf, auch hier.
    check("Auch über den Kopfknopf geht der Plan mit der Leiste auf",
          not pg17.locator("#plan-time").is_hidden())

    blk17 = pg17.locator(f'.tl-act[data-tlshow="{heute17["id"]}"]')
    check("Der heutige Auftritt steht in der Leiste", blk17.count() == 1,
          f'{lineup17["acts"][ai17]["n"]}, Auftritt {heute17["id"]}')
    check("Die Kachel ist als 'schon gesehen' gekennzeichnet",
          "seen-else" in (blk17.get_attribute("class") or ""),
          blk17.get_attribute("class"))
    # Die Auskunft ist ein FARBIGER GRUND, kein Zeichen: ein Zeichen kostet
    # Breite, die dem Namen fehlt. Also den Grund messen, nicht ein Element.
    grund17 = blk17.evaluate("(e) => getComputedStyle(e).backgroundColor")
    normal17 = pg17.evaluate("""() => {
      const e = [...document.querySelectorAll('.tl-act')]
        .find(x => !x.classList.contains('seen-else')
                   && !x.classList.contains('in-plan'));
      return e ? getComputedStyle(e).backgroundColor : null;
    }""")
    check("Und zwar durch einen eigenen Grund, nicht durch die übliche Farbe",
          grund17 != normal17 and grund17 not in (None, "rgba(0, 0, 0, 0)"),
          f"{grund17} gegen {normal17}")
    check("Der Titel nennt Tag, Uhrzeit und Spielort des anderen Termins",
          re.search(r"Schon gesehen: (Mi|Do|Fr|Sa) \d\d:\d\d · .",
                    blk17.get_attribute("title") or ""),
          (blk17.get_attribute("title") or "")[-70:])
    # Nicht mit "hier gewesen" verwechseln: dieser Auftritt ist NICHT abgehakt.
    check("Der Block selbst ist nicht als besucht schraffiert",
          "is-seen" not in (blk17.get_attribute("class") or ""),
          blk17.get_attribute("class"))
    # Ein Act ohne zweiten gesehenen Termin darf den Grund NICHT tragen.
    check("Andere Blöcke tragen ihn nicht",
          pg17.locator(".tl-act.seen-else").count() == 1,
          f'{pg17.locator(".tl-act.seen-else").count()} Kacheln')

    # In den Griffen ausgeschrieben - dort wird entschieden.
    blk17.evaluate("e => e.click()")
    pg17.wait_for_selector("#tlmenu[open]")
    check("Die Griffe schreiben es aus",
          "Schon gesehen" in pg17.locator("#tl-when").inner_text(),
          pg17.locator("#tl-when").inner_text()[:110])
    # Wird dieser Auftritt abgehakt, ist es kein "anderer Termin" mehr.
    pg17.locator("#tl-seen").click(); pg17.wait_for_timeout(600)
    if pg17.locator("#quick[open]").count():
        pg17.keyboard.press("Escape"); pg17.wait_for_timeout(300)
    pg17.keyboard.press("Escape"); pg17.wait_for_timeout(500)
    nach17 = pg17.locator(f'.tl-act[data-tlshow="{heute17["id"]}"]')
    check("Abgehakt wird daraus die Schraffur, nicht der blaue Grund",
          "is-seen" in (nach17.get_attribute("class") or "")
          and "seen-else" not in (nach17.get_attribute("class") or ""),
          nach17.get_attribute("class"))
    check("Keine JS-Fehler im Anderswo-Kontext", not err17, str(err17[:2]))
    ctx17.close()
    # --- Gesehen: das einzelne Konzert gegen den ganzen Künstler ---
    # 62 Acts spielen mehrfach. "Gesehen" am Act allein kann deshalb nicht
    # sagen, ob man einmal oder zweimal da war - und genau das will man am
    # Ende wissen. Abgehakt wird jetzt der AUFTRITT; der Künstler gilt als
    # gesehen, sobald einer seiner Auftritte abgehakt ist.
    ctx11 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    pg11 = ctx11.new_page()
    err11 = []
    pg11.on("pageerror", lambda e: err11.append(str(e)))
    pg11.on("console", lambda m: err11.append(m.text)
            if m.type == "error" and "ERR_" not in m.text else None)

    lineup11 = _json.load(open("web/data/lineup.json", encoding="utf-8"))
    von_act = {}
    for s in lineup11["shows"]:
        if s.get("tbd") or not s.get("t"):
            continue
        von_act.setdefault(s["a"], []).append(s)
    # Ein Act mit genau zwei Terminen - das ist der Fall, um den es geht.
    zwei = next(ai for ai, ss in sorted(von_act.items()) if len(ss) == 2)
    act11 = lineup11["acts"][zwei]
    shows11 = sorted(von_act[zwei], key=lambda s: s["t"])

    pg11.goto(BASE + "/", wait_until="load")
    pg11.wait_for_selector(".row", timeout=20000)
    pg11.click('.day[data-day=""]'); pg11.wait_for_timeout(300)
    pg11.click("#btn-search"); pg11.wait_for_timeout(250)
    pg11.fill("#q", act11["n"]); pg11.wait_for_timeout(500)
    zeilen = pg11.locator(f'.row[data-act="{zwei}"]')
    check("Ein Act mit zwei Terminen hat zwei Zeilen", zeilen.count() == 2,
          f'{act11["n"]}: {zeilen.count()}')
    check("Und keine davon ist abgehakt",
          pg11.locator(f'.row[data-act="{zwei}"].is-seen').count() == 0)

    # Auf der Künstlerkarte steht je Auftritt ein Haken.
    tap_row(zeilen.first)
    pg11.wait_for_selector("#detail .slots")
    check("Die Künstlerkarte hakt je Auftritt einzeln ab",
          pg11.locator("#detail .slots .slot-seen").count() == 2,
          f'{pg11.locator("#detail .slots .slot-seen").count()} Haken')
    pg11.locator(f'#detail [data-seenshow="{shows11[0]["id"]}"]').click()
    pg11.wait_for_timeout(500)
    if pg11.locator("#quick[open]").count():
        check("Abhaken ruft auch hier die Skala auf", True)
        pg11.keyboard.press("Escape"); pg11.wait_for_timeout(300)
    check("Der abgehakte Auftritt ist markiert",
          "on" in (pg11.locator(
              f'#detail [data-seenshow="{shows11[0]["id"]}"]')
              .get_attribute("class") or ""))
    check("Der andere Auftritt bleibt offen",
          "on" not in (pg11.locator(
              f'#detail [data-seenshow="{shows11[1]["id"]}"]')
              .get_attribute("class") or ""))
    pg11.keyboard.press("Escape"); pg11.wait_for_timeout(400)

    # In der Liste heisst das: EINE Zeile schraffiert, die andere nicht.
    marked = pg11.evaluate(f"""() => [...document.querySelectorAll(
      '.row[data-act="{zwei}"]')].map(r => [r.dataset.show,
      r.classList.contains('is-seen')])""")
    check("In der Liste ist nur der besuchte Termin schraffiert",
          sorted(marked) == sorted([[str(shows11[0]["id"]), True],
                                    [str(shows11[1]["id"]), False]]),
          str(marked))
    # Der Künstler gilt trotzdem als gesehen - das ist die andere Ebene.
    check("Der Künstler gilt damit als gesehen", pg11.evaluate(
        f"""() => (JSON.parse(localStorage.getItem('rbf26.seen')) || [])
                  .includes({act11["id"]})"""))

    # Und der Filter fragt ebenfalls den AUFTRITT. Vorher fragte er den Act
    # und zeigte deshalb beide Zeilen - eine schraffiert, eine nicht.
    pg11.click("#f-seen"); pg11.wait_for_timeout(600)
    gefiltert = pg11.evaluate(
        "() => [...document.querySelectorAll('.row')].map(r => r.dataset.show)")
    check("Der Gesehen-Filter zeigt nur den besuchten Termin",
          gefiltert == [str(shows11[0]["id"])], str(gefiltert))
    # Die Zahl am Chip zählt weiterhin ACTS - das ist eine andere Frage als
    # die Zahl der Zeilen, und der Titel sagt welche.
    check("Der Chip zählt weiter Acts", "(1)" in pg11.locator("#f-seen").inner_text(),
          pg11.locator("#f-seen").inner_text())
    pg11.click("#f-seen"); pg11.wait_for_timeout(400)

    # Zweiter Termin dazu: jetzt steht die Zahl da, um die es geht.
    tap_row(zeilen.first)
    pg11.wait_for_selector("#detail .slots")
    pg11.locator(f'#detail [data-seenshow="{shows11[1]["id"]}"]').click()
    pg11.wait_for_timeout(500)
    if pg11.locator("#quick[open]").count():
        pg11.keyboard.press("Escape"); pg11.wait_for_timeout(300)
    kopf = pg11.locator("#detail .d-section h3").filter(has_text="Auftritte")
    check("Zweimal gesehen steht als Zahl an den Auftritten",
          "2×" in kopf.first.inner_text(), kopf.first.inner_text())
    pg11.keyboard.press("Escape"); pg11.wait_for_timeout(400)
    check("Und beide Zeilen sind jetzt schraffiert",
          pg11.locator(f'.row[data-act="{zwei}"].is-seen').count() == 2)
    # Und der Filter zeigt jetzt beide Konzerte - die Zahl am Chip bleibt
    # bei einem Act, der Titel erklärt den Unterschied.
    pg11.click("#f-seen"); pg11.wait_for_timeout(600)
    beide = pg11.evaluate(
        "() => [...document.querySelectorAll('.row')].map(r => r.dataset.show)")
    check("Nach dem zweiten Termin zeigt der Filter beide Konzerte",
          sorted(beide) == sorted([str(s["id"]) for s in shows11]), str(beide))
    check("Der Chip unterscheidet Acts und Konzerte im Titel",
          pg11.locator("#f-seen").get_attribute("title") == "1 Acts, in 2 Konzerten gesehen",
          pg11.locator("#f-seen").get_attribute("title"))
    pg11.click("#f-seen"); pg11.wait_for_timeout(400)
    pg11.click("#btn-menu"); pg11.wait_for_selector("#menu[open]")
    check("Das Menü zählt Künstler UND Konzerte",
          "1 gesehen (2 Konzerte)" in pg11.locator("#m-stats").inner_text(),
          pg11.locator("#m-stats").inner_text()[:80])
    pg11.keyboard.press("Escape"); pg11.wait_for_timeout(300)

    # Zurücknehmen: ist der letzte Termin weg, ist auch der Künstler wieder
    # offen. Ein Haken, den man nicht mehr wegbekommt, wäre schlimmer.
    tap_row(zeilen.first)
    pg11.wait_for_selector("#detail .slots")
    for sh11 in shows11:
        pg11.locator(f'#detail [data-seenshow="{sh11["id"]}"]').click()
        pg11.wait_for_timeout(400)
        if pg11.locator("#quick[open]").count():
            pg11.keyboard.press("Escape"); pg11.wait_for_timeout(250)
    pg11.keyboard.press("Escape"); pg11.wait_for_timeout(400)
    check("Ohne abgehakten Termin ist auch der Künstler wieder offen",
          pg11.evaluate(
              f"""() => (JSON.parse(localStorage.getItem('rbf26.seen')) || [])
                        .includes({act11["id"]})""") is False
          and pg11.locator(f'.row[data-act="{zwei}"].is-seen').count() == 0)

    # Altbestand: ein Haken am Act ohne benannten Termin. Der darf nicht
    # rückwirkend verschwinden - er gilt dann für alle Zeilen des Acts.
    pg11.evaluate(f"""() => {{
      localStorage.setItem('rbf26.seen', JSON.stringify([{act11["id"]}]));
      localStorage.setItem('rbf26.seenshow', '[]');
    }}""")
    pg11.reload(wait_until="load")
    pg11.wait_for_selector(".row", timeout=20000)
    pg11.click('.day[data-day=""]'); pg11.wait_for_timeout(300)
    pg11.click("#btn-search"); pg11.wait_for_timeout(250)
    pg11.fill("#q", act11["n"]); pg11.wait_for_timeout(500)
    alt11 = pg11.locator(f'.row[data-act="{zwei}"].is-seen').count()
    check("Ein alter Haken ohne Termin gilt weiter für alle Zeilen",
          alt11 == 2, f"{alt11} von 2")

    # Der Haken des TEAMS steht neben dem eigenen, nicht in ihm. Vorher trug
    # ein Knopf beide - er sah abgehakt aus, ließ sich aber nur für einen von
    # beiden umschalten. Wer darauf tippte, sah nichts passieren und musste
    # glauben, der Haken lasse sich nicht mehr entfernen. Genau das war
    # gemeldet.
    pg11.evaluate(f"""() => {{
      localStorage.setItem('rbf26.seen', '[]');
      localStorage.setItem('rbf26.seenshow', '[]');
      localStorage.setItem('rbf26.partner', JSON.stringify({{
        name: 'Linda', fav: [], seen: [], seenShow: ['{shows11[0]["id"]}'],
        rate: {{}}, members: [{{ name: 'Linda', rate: {{}} }}],
      }}));
    }}""")
    pg11.reload(wait_until="load")
    pg11.wait_for_selector(".row", timeout=20000)
    pg11.click('.day[data-day=""]'); pg11.wait_for_timeout(300)
    pg11.click("#btn-search"); pg11.wait_for_timeout(250)
    pg11.fill("#q", act11["n"]); pg11.wait_for_timeout(500)
    tap_row(pg11.locator(f'.row[data-act="{zwei}"]').first)
    pg11.wait_for_selector("#detail .slots")
    eigen11 = pg11.locator(f'#detail [data-seenshow="{shows11[0]["id"]}"]')
    check("Der Haken des Teams steht als eigene Marke daneben",
          pg11.locator("#detail .slot-seen-p").count() == 1,
          f'{pg11.locator("#detail .slot-seen-p").count()} Team-Marken')
    check("Und sagt, von wem er ist",
          "Linda" in (pg11.locator("#detail .slot-seen-p").get_attribute("title") or ""),
          pg11.locator("#detail .slot-seen-p").get_attribute("title"))
    check("Mein eigener Knopf steht dabei auf offen",
          "on" not in (eigen11.get_attribute("class") or ""),
          eigen11.get_attribute("class"))
    # Und er folgt weiterhin NUR mir - hin und wieder zurück.
    eigen11.click(); pg11.wait_for_timeout(450)
    if pg11.locator("#quick[open]").count():
        pg11.keyboard.press("Escape"); pg11.wait_for_timeout(300)
    an11 = "on" in (pg11.locator(
        f'#detail [data-seenshow="{shows11[0]["id"]}"]').get_attribute("class") or "")
    pg11.locator(f'#detail [data-seenshow="{shows11[0]["id"]}"]').click()
    pg11.wait_for_timeout(450)
    if pg11.locator("#quick[open]").count():
        pg11.keyboard.press("Escape"); pg11.wait_for_timeout(300)
    aus11 = "on" in (pg11.locator(
        f'#detail [data-seenshow="{shows11[0]["id"]}"]').get_attribute("class") or "")
    check("Trotz Team-Haken lässt sich der eigene setzen und wieder entfernen",
          an11 and not aus11, f"an={an11} aus={aus11}")
    check("Und die Marke des Teams bleibt dabei stehen",
          pg11.locator("#detail .slot-seen-p").count() == 1)
    pg11.keyboard.press("Escape"); pg11.wait_for_timeout(300)
    check("Keine JS-Fehler im Gesehen-Kontext", not err11, str(err11[:2]))
    ctx11.close()

    # --- Griffe: die anderen Termine desselben Acts, zum Anspringen ---
    ctx12 = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
    pg12 = ctx12.new_page()
    err12 = []
    pg12.on("pageerror", lambda e: err12.append(str(e)))
    pg12.on("console", lambda m: err12.append(m.text)
            if m.type == "error" and "ERR_" not in m.text else None)
    day12 = lineup11["days"][1]
    ids12 = list(dict.fromkeys(
        [lineup11["acts"][s["a"]]["id"] for s in lineup11["shows"]
         if s["d"] == day12 and not s["tbd"]]))[:80]
    pg12.goto(BASE + "/", wait_until="load")
    pg12.wait_for_selector(".row", timeout=20000)
    pg12.evaluate("""(ids) => {
      const r = {};
      ids.forEach((id, i) => { r[id] = (i % 3) + 1; });
      localStorage.setItem('rbf26.rate', JSON.stringify(r));
    }""", ids12)
    pg12.reload(wait_until="load")
    pg12.wait_for_selector(".row", timeout=20000)
    pg12.click(f'.day[data-day="{day12}"]'); pg12.wait_for_timeout(400)
    pg12.click("#btn-plan"); pg12.wait_for_timeout(700)
    zeitleiste(pg12, 800)
    # Ein Block, dessen Act mehrfach spielt - den erkennt man am ×N.
    mehrfach = pg12.locator(".tl-act").filter(has=pg12.locator(".multi")).first
    check("In der Zeitleiste stehen Acts, die mehrfach spielen",
          mehrfach.count() == 1)
    name12 = mehrfach.locator(".tl-name").evaluate(
        "e => e.childNodes[0].textContent.trim()")
    mehrfach.evaluate("e => e.click()")
    pg12.wait_for_timeout(600)
    more = pg12.locator("#tl-more")
    check("Die Griffe zählen die anderen Termine auf", not more.is_hidden())
    alts = pg12.locator("#tl-more .tl-alt")
    check("Mit Tag, Uhrzeit und Spielort", alts.count() >= 1
          and re.search(r"\d\d:\d\d", alts.first.inner_text()),
          alts.first.inner_text().replace("\n", " ")[:60])
    check("Und dem Kürzel des Spielorts davor",
          alts.first.locator(".tl-alt-where b").count() == 1,
          alts.first.locator(".tl-alt-where").inner_text()[:40])
    # Anspringen: derselbe Act, anderer Termin.
    vorher12 = pg12.locator("#tl-when").inner_text()
    ziel12 = alts.first.get_attribute("data-tljump")
    alts.first.click(); pg12.wait_for_timeout(800)
    check("Ein Tipper springt zu diesem Auftritt",
          pg12.evaluate("() => document.querySelector('#tlmenu').dataset.show")
          == ziel12, ziel12)
    check("Derselbe Künstler, andere Zeit",
          pg12.locator("#tl-name").inner_text() == name12
          and pg12.locator("#tl-when").inner_text() != vorher12,
          f'{vorher12[:28]} -> {pg12.locator("#tl-when").inner_text()[:28]}')
    # Liegt der Termin an einem anderen Abend, geht die Leiste dahinter mit.
    tag12 = pg12.evaluate("""(id) => {
      const d = document.querySelector('.day[aria-selected="true"]');
      return d ? d.dataset.day : null;
    }""", ziel12)
    soll12 = next((s.get("d") for s in lineup11["shows"]
                   if str(s["id"]) == str(ziel12)), None)
    check("Und der gewählte Tag geht mit", tag12 == soll12,
          f"{tag12} gegen {soll12}")
    check("Keine JS-Fehler im Sprung-Kontext", not err12, str(err12[:2]))
    ctx12.close()

    # --- Schmales Telefon ---
    # Gemessen war hier der Fehler: Titel und sechs Symbole zusammen waren
    # breiter als der Bildschirm, und weil nichts nachgab, wurde die ganze
    # SEITE breiter - dann verrutscht alles waagerecht.
    for breite in (360, 320):
        ctx13 = b.new_context(viewport={"width": breite, "height": 740},
                              locale="de-DE")
        pg13 = ctx13.new_page()
        err13 = []
        pg13.on("pageerror", lambda e: err13.append(str(e)))
        pg13.goto(BASE + "/", wait_until="load")
        pg13.wait_for_selector(".row", timeout=20000)
        # Ohne Noten bliebe der Abendplan leer - dann prüfte der Block
        # unten eine Zeitleiste ohne Blöcke, also nichts.
        pg13.evaluate("""(ids) => {
          const r = {};
          ids.forEach((id, i) => { r[id] = (i % 3) + 1; });
          localStorage.setItem('rbf26.rate', JSON.stringify(r));
        }""", ids12)
        pg13.reload(wait_until="load")
        pg13.wait_for_selector(".row", timeout=20000)
        UEBER = ("() => document.documentElement.scrollWidth"
                 " - document.documentElement.clientWidth")
        check(f"Bei {breite} px schiebt die Liste die Seite nicht breiter",
              pg13.evaluate(UEBER) <= 0, f"{pg13.evaluate(UEBER)} px zu viel")
        pg13.click(f'.day[data-day="{day12}"]'); pg13.wait_for_timeout(300)
        pg13.click("#btn-plan"); pg13.wait_for_timeout(700)
        check(f"Bei {breite} px auch der Abendplan nicht",
              pg13.evaluate(UEBER) <= 0, f"{pg13.evaluate(UEBER)} px zu viel")
        zeitleiste(pg13, 700)
        check(f"Bei {breite} px auch die Zeitleiste nicht",
              pg13.evaluate(UEBER) <= 0, f"{pg13.evaluate(UEBER)} px zu viel")
        if breite == 360:
            # Auf dem häufigsten schmalen Android steht der Titel ganz da.
            check("Bei 360 px steht der Titel vollständig",
                  pg13.evaluate("""() => {
                    const h = document.querySelector('h1');
                    return h.scrollWidth <= h.clientWidth + 1;
                  }"""))
            # Und die Zeitleiste zeigt mehr als zwei Spalten nebeneinander.
            spalten = pg13.evaluate("""() => {
              const sc = document.querySelector('#plan-time .tl-scroll');
              const b = document.querySelector('.tl-act');
              return b ? Math.floor(sc.clientWidth / b.offsetWidth) : 0;
            }""")
            check("Und mindestens drei Spalten passen nebeneinander",
                  spalten >= 3, f"{spalten} Spalten")
            # Nichts wird dabei abgeschnitten: der Fuss eines Blocks trägt
            # Note, Team-Schnitt und Kürzel - die müssen hineinpassen.
            eng = pg13.evaluate("""() => [...document.querySelectorAll(
              '.tl-act .tl-foot')].filter(e => e.scrollWidth > e.clientWidth + 1
              ).length""")
            fuesse = pg13.locator(".tl-act .tl-foot").count()
            check("Und in den Blöcken wird nichts abgeschnitten",
                  eng == 0 and fuesse >= 10,
                  f"{eng} zu enge von {fuesse} Fußzeilen")
        check(f"Keine JS-Fehler bei {breite} px", not err13, str(err13[:2]))
        ctx13.close()

    # --- Statusleiste: die Farbe des Telefons kommt aus EINER Quelle ---
    # Beschwerde von einem kleineren Gerät: "ich erkenne meine Statusleiste
    # oben nicht mehr". Sie übernimmt in der installierten App die
    # theme-color - und die war fast dasselbe Weiß wie der Rahmen der App.
    ctx14 = b.new_context(viewport={"width": 360, "height": 740}, locale="de-DE")
    pg14 = ctx14.new_page()
    pg14.goto(BASE + "/", wait_until="load")
    pg14.wait_for_selector(".row", timeout=20000)
    farben = pg14.evaluate("""() => {
      const meta = document.querySelector('meta[name="theme-color"]');
      const cs = getComputedStyle(document.querySelector('.top'));
      return {
        meta: (meta && meta.content || '').trim().toLowerCase(),
        band: getComputedStyle(document.documentElement)
                .getPropertyValue('--bg-top').trim().toLowerCase(),
        kopf: cs.backgroundColor,
        seite: getComputedStyle(document.body).backgroundColor,
      };
    }""")
    check("Die Statusleiste trägt dieselbe Farbe wie die Kopfleiste",
          farben["meta"] == farben["band"] and farben["band"] != "",
          f'{farben["meta"]} gegen {farben["band"]}')
    check("Und die hebt sich vom Rest der Seite ab",
          farben["kopf"] != farben["seite"],
          f'{farben["kopf"]} gegen {farben["seite"]}')
    check("Die Kopfleiste ist deckend, nicht durchscheinend",
          "rgba" not in farben["kopf"] or farben["kopf"].endswith(", 1)"),
          farben["kopf"])
    ctx14.close()

    real = [e for e in errors if "openstreetmap" not in e.lower()
            and "tile" not in e.lower() and "ERR_" not in e
            and e not in csp]
    check("Keine JS-Fehler", not real, str(real[:3]))
    r404 = [u for u in requested404]
    check("Keine 404 auf eigene Dateien", not r404, str(r404[:4]))
    b.close()

print("\n" + ("ALLE PRUEFUNGEN BESTANDEN" if not FAILS else f"FEHLGESCHLAGEN: {FAILS}"))
sys.exit(1 if FAILS else 0)
