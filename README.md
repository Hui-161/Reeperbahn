# Reeperbahn-Festival: eigene Datenschicht

Holt das komplette Line-up ueber die GraphQL-API der Festival-Website,
erkennt Aenderungen zuverlaessig und exportiert nach ICS/CSV.

**Stand: 342 Acts, 406 Auftritte fuer Edition 2026 abgerufen und verifiziert.**

Die Aenderungserkennung ist an echten Daten belegt: zwischen zwei Abrufen am
25.08.2026 kam "Seers Of Light" (HU, Heavy Metal) neu ins Line-up. Der
Datensatz tragt `created: 2026-08-25T14:38:47+02:00` - der Diff hat also eine
tatsaechliche Aenderung gemeldet, keinen Artefakt-Fehlalarm.

## Die gefundene API

Es gibt keine dokumentierte API, aber eine offen erreichbare:

```
POST https://www.reeperbahnfestival.com/graphql
Content-Type: application/json
```

Backend ist **Drupal mit dem graphql_views-Modul**. Introspection ist aktiv,
Authentifizierung gibt es nicht.

### Wichtige Eigenheiten

Diese vier Punkte kosten sonst Stunden:

1. **Nur POST.** GET funktioniert scheinbar auch, aber CloudFront cached die
   Antwort **ohne den Query-String im Cache-Key** — jede GET-Abfrage liefert
   danach das Ergebnis der ersten zurueck. Ein Cache-Buster-Parameter hilft
   nicht.
2. **Die Website ist WAF-geschuetzt, `/graphql` nicht.** Normale Seiten
   antworten Nicht-Browsern mit `HTTP 202` und `x-amzn-waf-action: challenge`
   bei leerem Body. Der GraphQL-Endpunkt und alles unter `/api/` sind von der
   Regel ausgenommen — dort kommen echte Antworten.
3. **`page` wird ignoriert.** Das Pager-Argument der Views hat keine Wirkung;
   jede Seite liefert dieselben Zeilen. Ein hohes `limit` liefert alles, mit
   allen Detailfeldern antwortet der Server dann aber mit `502`. Deshalb der
   zweistufige Abruf (IDs, dann Details in Bloecken). `entityQuery` hat ein
   funktionierendes `offset`.
4. **Es sind alle Jahrgaenge drin.** Ohne Edition-Filter kommen auch 2023–2025
   zurueck. `overview_act` hat dafuer einen `edition`-Filter, die Event-View
   nicht.

### Editionen

| id | Label | Zeitraum | |
|---|---|---|---|
| 1 | 2024 | 18.–21.09.2024 | |
| 2 | 2023 | 20.–23.09.2023 | |
| 3 | RBF 2025 – Imagine Togetherness | 17.–20.09.2025 | |
| 4 | **RBF 2026 – Forever legit?** | 16.–19.09.2026 | aktiv |

### Einstiegspunkte

`ping · entityQuery · entityById · entityByUuid · menuByName · route ·
currentUser · getView`

Der Weg zu einer View ist zweistufig:

```graphql
{
  getView(id: "overview_act") {
    executable(displayId: "default") {
      ... on ViewOverviewActDefault {
        execute(limit: 1000, filters: { edition: "4" }) {
          rows { ... on NodeParticipant { nid title } }
        }
      }
    }
  }
}
```

Nutzbare View-IDs: `overview_act`, `overview_festival_event`, `overview_event`.

### Datenqualitaet: Spielorte erben Koordinaten

Unter-Locations (Raeume und Nebenbuehnen, z. B. `"Molotow  / Top10"`) haben ein
leeres `fieldGeolocation`; die Koordinaten haengen am Elterneintrag in
`fieldParentLocation`. 20 der 189 Locations sind **nur** so verortbar. Ausserdem
haben die Labels unsaubere Leerzeichen — Abgleich nur ueber einen normalisierten
Schluessel. `fetch_venues.py` erledigt beides, `--check` prueft es.

### Datenqualitaet: Uhrzeiten sind teils Platzhalter

**`06:00` ist keine Spielzeit, sondern der Platzhalter fuer "Tag steht,
Uhrzeit offen".** Beim Abruf betraf das 41 von 406 Auftritten. 310 Auftritte
liegen im plausiblen Konzertfenster (17:00-03:00).

`fetch_lineup.py` markiert solche Datensaetze mit `time_tbd: true`. Der
ICS-Export macht daraus einen **Ganztagstermin** mit dem Zusatz
"(Uhrzeit offen)" - ein 6-Uhr-Termin im Kalender waere schlicht falsch.

### Datenmodell

* **`NodeParticipant`** = ein Act. 133 Felder, darunter `fieldSpotify`,
  `fieldGenre`, `fieldMood`, `fieldCountry`, `fieldBiography`,
  `fieldAppearances`.
* **`NodeAppearance`** = ein Auftritt: `fieldDate`, `fieldVenue`,
  `fieldVenueLocation`, `fieldWeekday`, `fieldShowcase`.
* Felder kommen **teils als Liste, teils als Einzelwert** — deshalb die
  `first()`-Helfer in `fetch_lineup.py`.
* `Url` und `uri` brauchen immer eine Untermenge: `url { path }`.
* **`NodeAppearance.nid` ist die stabile Identitaet eines Auftritts.** Sie
  wird als `ext_id` uebernommen und bildet die `show_id`. Nur so bleibt ein
  Auftritt derselbe, wenn Uhrzeit *oder* Venue sich aendern - und genau das
  passiert laufend, weil Platzhalterzeiten spaeter praezisiert werden. Ohne
  das wuerde jede Terminierung als "Auftritt entfallen + neuer Auftritt"
  gemeldet statt als Zeitaenderung.

## Datenschutz — die wichtige Grenze

`NodeParticipant` wird **auch fuer Konferenz-Sprechende** verwendet und
enthaelt `fieldFirstName`, `fieldLastName`, `fieldPosition`, `fieldCompany`,
`fieldPronouns`. Fuer Edition 2026 sind das 528 Participants, davon 341
Musik-Acts.

Deshalb:

* Der Abruf nimmt die Act-Liste aus `overview_act` (dort ausschliesslich
  `fieldParticipantType = "act"`) und fragt **nur diese** IDs ab.
* Die Namensfelder werden nicht angefragt.
* `sync.py` **bricht ab**, wenn ein anderer Participant-Typ auftaucht, statt
  stillschweigend Personendaten mitzuziehen.
* Nicht angefragt werden ausserdem `OsContact*`, `OsCheckInRecord*`
  (Gaestelisten, Crew-Check-ins), `OsRecordMember*`, `NodePerson` und
  `WebformSubmission*` (Bewerbungsformulare). Diese Typen sind ueber dasselbe
  Schema erreichbar — bitte auch nicht aus Neugier abfragen.

Kuenstlernamen sind ebenfalls personenbezogene Daten, auch wenn sie
oeffentlich verkuendet wurden. Fuer eine private Auswertung ist das
unkritisch. Sobald daraus etwas Veroeffentlichtes oder betrieblich Genutztes
wird, aendert sich die Bewertung.

## Noch nicht veroeffentlichte Spielzeiten

Die API liefert **exakte Startzeiten** (z. B. `2026-09-17T23:10:00+02:00`).
Die Website selbst zeigt sie noch nicht: ihr eigener Zustand enthaelt
`releaseState: { showDay: false, showDate: false }`.

Fuer die eigene Planung ist das in Ordnung. Diese Zeiten aber zu
veroeffentlichen oder weiterzugeben, wuerde der Ankuendigung des Festivals
vorgreifen — und die Daten koennen sich bis zur offiziellen Freigabe noch
aendern. Also: privat nutzen, nicht publizieren.

## Dateien

| Datei | Zweck |
|---|---|
| `gql.py` | GraphQL-Client: Pause zwischen Requests, Retry mit Backoff |
| `fetch_lineup.py` | zweistufiger Abruf, Mapping auf das Show-Schema |
| `rbf_core.py` | Datenmodell, Snapshots, Diff, ICS-Export, Selbsttest |
| `sync.py` | ein Befehl: holen, Snapshot, Aenderungen melden |
| `fetch_venues.py` | Spielorte mit Koordinaten, Adresse, Kapazitaet, Barrierefreiheit |
| `discover.py` | Discovery-Probe — nur noetig, wenn die Seite umgebaut wird |
| `build_web.py` | baut `web/data/lineup.json` fuer die App |
| `web/` | die Web-App: statisch, kein Build-Schritt |
| `web/serve_local.py` | lokaler Server, sendet die echten Cloudflare-Header |
| `web/test_e2e.py` | Browser-Regressionstest (22 Pruefungen) |
| `taste.py` | Abgleich eigener Bewertungen und Hoerprofil gegen das Line-up |
| `BACKLOG.md` | Verbesserungswuensche, bewertet gegen die Datenlage |
| `DEPLOY.md` | Cloudflare Pages + eigene Domain |
| `data/snapshots/` | Historie — **gehoert ins Repository**, dagegen laeuft der Diff |
| `.github/workflows/lineup-check.yml` | taeglicher Check, Issue bei Aenderungen |

Abrufergebnisse (`shows.json`, `shows.csv`, `acts-raw.json`) sind bewusst
**nicht** eingecheckt — sie sind jederzeit reproduzierbar. Die Snapshots schon:
sie sind die Historie.

Alles laeuft mit der **Python-Standardbibliothek**, kein `pip install`.
Getestet mit Python 3.11.

## Die Web-App

Statische Seite, **kein Build-Schritt**: kein npm, kein Bundler, keine
Node-Version, die in zwei Jahren nicht mehr baut. Leaflet liegt versioniert
im Repo, sonst gibt es keine Abhaengigkeiten.

Enthalten: Timetable nach Festivaltag **oder ueber alle Tage**, Filter nach
Genre (mit eigenem Eimer fuer Acts *ohne* Genre-Angabe) und nach Spielort,
Favoriten, **Gesehen-Markierung**, private Notizen, **Bewertung von 1 bis 5**
(1 = sehr gut, 5 = gar nicht), Volltextsuche ueber alle Tage, Karte mit
**geclusterten** Spielorten samt "Nur dieses Haus zeigen", Umschalter fuer
hell/dunkel/Systemvorgabe, Offline-Betrieb per Service Worker, installierbar
als PWA.

Filter: Favoriten, Bewertet, **Gesehen**, **Beide** (nur mit Partner-Datei),
Genre, Spielort - alle kombinierbar.

## Team online (verschluesselt)

Ueber das Menue: **Team einrichten** erzeugt eine zufaellige Team-ID, dazu
waehlt man eine Passphrase. Die Partner:in tritt mit Beitrittslink und
derselben Passphrase bei. Danach gleicht sich alles automatisch ab - nach jeder
eigenen Aenderung verzoegert um vier Sekunden, beim Start, und beim Wegwechseln
der Seite.

Der Server (`worker/index.js`, Cloudflare KV) sieht **nie Klartext**: die App
verschluesselt im Browser mit AES-GCM, der Schluessel kommt per PBKDF2 aus der
Passphrase. Aus derselben Passphrase entsteht ein Schreib-Token, von dem nur
der SHA-256-Hash abgelegt wird.

Das ist **keine Anmeldung**: wer Team-ID und Passphrase hat, ist im Team. Fuer
zwei Personen und Konzertnoten ist das angemessen - Link und Passphrase aber
ueber getrennte Kanaele austauschen.

Einrichtung des KV-Namespace: [`DEPLOY.md`](DEPLOY.md).

## Team ohne Server (Datei-Variante)

Beide Seiten exportieren ihre Auswahl ("Auswahl sichern") und laden die Datei
der anderen ueber **"Datei von Partner:in laden"**. Danach stehen die
Markierungen nebeneinander: die eigene Note gefuellt, die der Partner:in
umrandet in derselben Farbe. Der Filter **"Beide"** zeigt, wo sich beide einig
sind (beide Favorit oder beide Note 1-2) - die Frage, die ein Team wirklich
hat.

Der Aufbau ist absichtlich so gewaehlt, dass **jede Seite ausschliesslich ihre
eigene Datei schreibt**. Damit kann beim Zusammenfuehren nichts kollidieren -
es gibt keine Konflikte, die man aufloesen muesste. Genau dieses Modell laesst
sich spaeter ohne Aenderung an der Logik auf eine Online-Ablage heben; nur der
Dateitransport wird dann automatisch.

Im Menue oben rechts: Auswahl sichern (JSON), Datei laden, Partner-Datei, und
die **Gesehen-Liste als CSV** - mit Tag, Zeit, Spielort, eigener Note und Notiz,
also als Mitschrift des Festivals und nicht als reine Namensliste.

Die Note steht in der Liste als **Zahl** und nicht nur als Farbe - Farbe
allein ist fuer Farbfehlsichtige keine Information. Bewertungen aus der
frueheren dreistufigen Ampel werden beim Laden automatisch abgebildet
(gruen->1, gelb->3, rot->5).

Zur Karte: die Marker sind geclustert (Leaflet.markercluster, eingecheckt),
weil sich 34 Haeuser auf engem Raum sonst gegenseitig verdecken. Ab Zoomstufe
17 loesen sich die Cluster auf - dadurch ist "Spielort anzeigen"
deterministisch. Das Popup wird an der Koordinate geoeffnet, nicht am Marker:
der kann in dem Moment noch im Cluster stecken, weil die Gruppe erst bei
`zoomend` umbaut.

Eigener Zustand (Favoriten, Notizen, Ampel) bleibt im Browser des Geraets —
kein Server, kein Konto.

**Festivaltag statt Kalendertag:** ein Auftritt um 00:30 zaehlt zur Nacht des
Vortags (Grenze 05:00). Ohne das entsteht ein Tages-Tab mit zwei Auftritten,
und wer Samstagnacht sucht, findet sie unter Sonntag. Betrifft aktuell 12
Auftritte.

**Caching:** Der Service Worker geht **Netz zuerst, Cache als Rueckfall**.
Umgekehrt (Cache zuerst) hat einen echten Fehler verursacht: die Dateinamen
tragen keine Version, also lieferte der Cache nach einem Deploy weiter die
alte `style.css` aus, waehrend `index.html` und `app.js` schon neu waren -
ein gemischter Stand. Deshalb steht in `_headers` auch `no-cache` fuer die
App-Huelle, und `/vendor/*` ist **nicht** `immutable` (ohne Version im Namen
waere das eine Falle fuer ein Jahr).

Der helle Modus ist auf **Tageslicht** ausgelegt: die Lesflaeche (Karten) ist
reinweiss, der Rahmen lila getoent. Textkontraste gegen die Karte: 18.7 / 10.6
/ 6.9 / 7.7 (Text, Sekundaertext, Metatext, Akzent).

Aufsetzen und Deployment: [`DEPLOY.md`](DEPLOY.md).

```bash
python3 build_web.py             # Daten fuer die App bauen
python3 web/serve_local.py       # lokal ansehen, mit echten Headern
python3 web/test_e2e.py          # Browsertest
```

## Nutzung

```bash
python3 fetch_lineup.py --editions          # Editionen auflisten
python3 fetch_lineup.py --edition 4         # Line-up holen
python3 sync.py                             # holen + Aenderungen melden
python3 rbf_core.py diff                    # letzte zwei Snapshots
python3 rbf_core.py csv shows.json          # flache Tabelle
python3 rbf_core.py ics shows.json --artists "shame,Lowertown"
python3 fetch_venues.py --check             # Spielorte + Verortbarkeit pruefen
python3 rbf_core.py selftest                # Tests
```

`sync.py` ist fuer Automatisierung gebaut: Exit-Code **0** = keine
Aenderungen, **10** = Aenderungen (Details auf stdout), **1** = Abruf-Fehler.

Der Workflow unter `.github/workflows/lineup-check.yml` ist einsatzfertig:
taeglich 5:30 UTC, legt bei Aenderungen ein Issue an, schreibt den Diff in die
Job-Zusammenfassung und committet den neuen Snapshot. Manuell startbar per
`workflow_dispatch`.

### Alternativ: taeglicher Check per cron

```cron
30 7 * * * cd /pfad/zu/rbf && python3 sync.py --quiet >> sync.log 2>&1
```

Ein Abruf pro Tag genuegt. Das Line-up aendert sich nicht minuetlich, und
`sync.py` schreibt bei inhaltsgleichem Ergebnis keinen neuen Snapshot — die
Historie enthaelt also nur echte Aenderungen.

## Fairness gegenueber der Seite

Eingebaut, nicht optional: 1 s Pause zwischen Requests (`--delay`), Retry mit
exponentiellem Backoff nur bei 429/5xx, ehrlicher User-Agent ohne
Browser-Tarnung, kein Retry-Sturm. Der komplette Abruf sind rund 20 Requests.

## Robustheit

Das Schema ist nicht dokumentiert und kann sich ohne Ankuendigung aendern.
Bricht der Abruf, liefert `discover.py` die Lage neu; die vier Eigenheiten
oben sind die wahrscheinlichsten Stolperstellen. `acts-raw.json` bleibt
absichtlich erhalten, damit man fehlende Felder nachtraeglich rekonstruieren
kann, ohne erneut abzurufen.

## Vor produktivem Einsatz

Entwurf, fachlich zu pruefen. Nicht unbesehen in einen Automatismus haengen.
