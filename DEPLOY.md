# Deployment: GitHub → Cloudflare Pages → hui161.de

Die App ist eine statische Seite **ohne Build-Schritt**. Kein npm, kein
Bundler, keine Node-Version, die in zwei Jahren nicht mehr baut. Cloudflare
Pages liefert den Ordner `web/` unveraendert aus.

## So laeuft es zusammen

```
GitHub Actions (taeglich 5:30 UTC)
    sync.py            Line-up abrufen, mit dem letzten Snapshot vergleichen
    build_web.py       web/data/lineup.json neu bauen
    git commit + push  nur wenn sich inhaltlich etwas geaendert hat
        |
        v
Cloudflare Pages       erkennt den Push, deployt web/ neu
        |
        v
reeperbahn.hui161.de
```

**Es sind keine Secrets und keine API-Tokens noetig.** Cloudflare Pages holt
sich den Code ueber die GitHub-App-Verknuepfung, und der Workflow braucht nur
das ohnehin vorhandene `GITHUB_TOKEN`.

## Schritt 1: Cloudflare Pages verbinden

Cloudflare Dashboard → **Workers & Pages** → **Create** → **Pages** →
**Connect to Git** → dieses Repository auswaehlen.

Dann diese Einstellungen — **die Ausgabeverzeichnis-Angabe ist der einzige
Punkt, bei dem man etwas falsch machen kann**:

| Feld | Wert |
|---|---|
| Production branch | `main` |
| Framework preset | **None** |
| Build command | **leer lassen** |
| Build output directory | **`web`** |
| Root directory | `/` (unveraendert) |

Bleibt „Build output directory" leer, liefert Cloudflare das Repo-Wurzel-
verzeichnis aus — dann sieht man die Python-Dateien statt der App.

Nach dem ersten Deploy ist die Seite unter `<projektname>.pages.dev`
erreichbar. Damit erst pruefen, ob alles laedt, bevor die eigene Domain
dazukommt.

## Schritt 2: hui161.de anbinden

Voraussetzung: `hui161.de` liegt als Zone in demselben Cloudflare-Konto, die
Nameserver der Domain zeigen also auf Cloudflare. Steht die Domain noch bei
einem anderen Anbieter, muss sie zuerst als Zone hinzugefuegt und die
Nameserver umgestellt werden.

Im Pages-Projekt → **Custom domains** → **Set up a custom domain**.

**Empfehlung: eine Subdomain.**

```
reeperbahn.hui161.de
```

Cloudflare legt den passenden CNAME automatisch an. Der Vorteil: die
Hauptdomain `hui161.de` bleibt unberuehrt, falls dort schon etwas liegt oder
spaeter liegen soll. Ein Festival-Timetable auf der Wurzel der eigenen Domain
ist selten die gewuenschte Dauerloesung.

**Wenn es doch die Hauptdomain sein soll:** `hui161.de` als Custom Domain
eintragen. Cloudflare loest das ueber CNAME-Flattening, ein CNAME auf dem
Apex ist dort also erlaubt — bei den meisten anderen Anbietern nicht.
Zusaetzlich `www.hui161.de` eintragen oder per Redirect-Rule auf die Apex
umleiten, sonst laeuft die www-Variante ins Leere.

Der DNS-Eintrag muss **proxied** sein (orange Wolke). Auf „DNS only"
gestellt, greifen die Regeln aus `web/_headers` nicht.

Das TLS-Zertifikat stellt Cloudflare selbst aus; das dauert nach dem
Anlegen ein paar Minuten.

## Schritt 3: Rechte fuer den Workflow

Damit der taegliche Lauf den Snapshot committen und ein Issue anlegen kann:

**GitHub → Settings → Actions → General → Workflow permissions** →
**Read and write permissions**.

Neue Repositories stehen standardmaessig auf „read-only" — ohne diese
Umstellung laeuft der Abruf, aber der Commit am Ende schlaegt fehl.

Testen ohne auf 5:30 zu warten: **Actions → lineup-check → Run workflow**.

## Lokal entwickeln

```bash
python3 web/serve_local.py      # http://127.0.0.1:8898
```

Nicht `python3 -m http.server` nehmen. `serve_local.py` sendet die Header aus
`web/_headers` wirklich mit — inklusive Content-Security-Policy. Sonst faellt
erst auf der echten Domain auf, dass die CSP etwas blockiert.

Regressionstest im Browser:

```bash
pip install playwright && python3 -m playwright install chromium
python3 web/serve_local.py &
python3 web/test_e2e.py
```

Prueft 22 Punkte: Rendering, Genre-Filter samt „ohne Angabe"-Eimer,
Favoriten, Notizen, Ampel, Suchfokus, Karte, Persistenz nach Reload — und
dass **keine** CSP-Verletzung und kein 404 auftritt. Laeuft auch in CI
(`.github/workflows/ci.yml`).

Daten neu bauen, ohne die API zu fragen:

```bash
python3 build_web.py --offline
```

## Was zu beachten ist

**Kartenkacheln kommen von OpenStreetMap.** Die Nutzungsbedingungen erlauben
das fuer geringe Last, verlangen aber die Namensnennung — die ist eingebaut
und darf nicht entfernt werden. Bei ernsthaftem Traffic waere ein eigener
Kachel-Dienst oder ein Cloudflare-Cache davor faellig. Fuer eine private App
ist es unproblematisch. Die Kacheln sind absichtlich **nicht** im Service
Worker gecacht, sonst laeuft der Speicher voll.

**Der Service Worker ist mit `no-cache` ausgeliefert.** Das steht so in
`_headers` und sollte so bleiben: ein lange gecachter Service Worker haelt
Nutzer sonst auf einer alten Version fest. Wird der Cache-Inhalt geaendert,
die Version in `web/sw.js` hochzaehlen (`const V = 'rbf26-v1'`), damit alte
Caches verworfen werden.

**Offline-Betrieb ist Absicht.** Im Club ist der Empfang schlecht. Huelle und
Programmdaten liegen im Cache; beim ersten Aufruf braucht die App aber Netz.
Einmal zu Hause oeffnen, dann funktioniert sie vor Ort.

**Der eigene Zustand liegt nur im Browser.** Favoriten, Notizen und
Ampelbewertungen stehen in `localStorage` — auf genau diesem Geraet, in genau
diesem Browser. Kein Server, kein Konto, keine Synchronisierung. Das ist die
datensparsame Variante, hat aber eine Kehrseite: Browserdaten loeschen loescht
die Auswahl, und das Handy allein hat sie, nicht der Laptop. Wer das
synchronisieren will, braucht eine bewusste Entscheidung fuer einen Speicher
dahinter — und damit fuer eine Datenverarbeitung, die es jetzt nicht gibt.

**Die App ist als PWA installierbar.** Auf dem Handy „Zum Home-Bildschirm
hinzufuegen"; dann startet sie ohne Browserleiste.
