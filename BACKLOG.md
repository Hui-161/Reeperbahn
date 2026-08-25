# Verbesserungswuensche — Bewertung gegen die Datenlage

Sieben Punkte aus der Nutzung der offiziellen App, bewertet danach, was die
Datenschicht dieses Projekts schon hergibt und wo die eigentliche Arbeit liegt.

Kurzfassung: **kein einziger Punkt scheitert an fehlenden Daten.** Vier sind
reine Frontend-Arbeit, drei sind datenseitig fertig. Was fehlt, ist die
Oberflaeche.

| # | Wunsch | Daten | Aufwand liegt bei |
|---|---|---|---|
| 1 | Notizen + Ampel pro Kuenstler:in | vorhanden | Frontend + lokaler Speicher |
| 2 | Scrollposition in der Timeline merken | nicht noetig | Frontend |
| 3 | Location unter Timings waehlbar, auf Karte | **fertig** | Frontend |
| 4 | Tastatur oeffnet sich bei Suche direkt | nicht noetig | Frontend |
| 5 | Favoriten im Timetable per Herz filtern | vorhanden | Frontend + lokaler Speicher |
| 6 | Nach Genre filtern | **fertig** | Frontend |
| 7 | Locations auf der Karte auffindbar | **fertig, Ursache gefunden** | Frontend |

---

## 1. Notizfunktion mit Ampelsystem

**Daten:** Nichts fehlt. Jeder Act hat eine stabile `nid` und `uuid`, jeder
Auftritt eine stabile `ext_id` (`NodeAppearance.nid`). Daran laesst sich
beliebiger eigener Zustand haengen, der Umbenennungen und Verlegungen
uebersteht.

**Hinweis:** Die Ampel passt genau auf den geplanten Geschmacksfilter. Sinnvoll
waere, beide Quellen zu trennen und sichtbar zu halten — die automatische
Einschaetzung als Vorbelegung, die eigene Ampel als Entscheidung, die immer
gewinnt. Ein System, das die manuelle Setzung stillschweigend ueberschreibt,
verliert Vertrauen.

Rein lokaler Zustand, nichts davon muss das Geraet verlassen.

## 2. Scrollposition in der Timeline halten

**Daten:** Nicht betroffen.

Klassische Scroll-Restoration: Position beim Verlassen sichern, bei Rueckkehr
wiederherstellen. Wichtig ist, an die Zeitachse zu ankern (Uhrzeit/Slot), nicht
an einen Pixelwert — sonst springt die Ansicht, sobald sich die Liste durch
Filter oder ein Line-up-Update aendert.

## 3. Location unter den Timings waehlbar und auf der Karte

**Daten: fertig.** `fetch_venues.py` liefert pro Spielort:

* `lat` / `lng`
* Adresse (Strasse, PLZ, Ort)
* `capacity` — Kapazitaet, brauchbar zur Einschaetzung "kleiner Club oder Halle"
* `accessibility` — Angaben zur Barrierefreiheit
* `parent` — uebergeordnetes Haus bei Raeumen und Nebenbuehnen

Verknuepfung zum Auftritt ueber das Feld `venue`. **Achtung beim Abgleich:**
die Labels der Quelle haben unsaubere Leerzeichen (`"Molotow "` mit Leerzeichen
am Ende, `"Molotow  / Top10"` mit doppeltem). Ohne Normalisierung schlaegt der
Abgleich fehl. `fetch_venues.py` bringt dafuer `norm()` mit.

## 4. Tastatur oeffnet sich beim Klick auf die Suche

**Daten:** Nicht betroffen.

**Ehrliche Einschraenkung:** Auf iOS oeffnet Safari die Tastatur nur, wenn der
Fokus *innerhalb* einer echten Nutzergeste gesetzt wird. Ein `focus()` nach
einem `await`, in einem Timeout oder nach einem Routenwechsel wird ignoriert —
das ist eine Plattformregel, kein Fehler der App. Moeglicherweise ist genau das
der Grund, warum es in der offiziellen App nicht tut.

Praktisch heisst das: das Suchfeld muss bereits im DOM stehen und im
Klick-Handler selbst fokussiert werden, nicht erst nach dem Oeffnen eines
Overlays.

## 5. Favoriten im Timetable per Herz-Klick filtern

**Daten:** Vorhanden, siehe Punkt 1 (stabile IDs).

Reiner Frontend- und Zustandsteil. Ein Umschalter "nur Favoriten" auf derselben
Datenliste.

## 6. Nach Genre filtern

**Daten: fertig.** 16 Genres, Verteilung im aktuellen Line-up:

| Genre | Auftritte | | Genre | Auftritte |
|---|---|---|---|---|
| Indie | 136 | | Singer-Songwriter | 17 |
| Pop | 124 | | R'n'B/Soul | 17 |
| Alternative | 84 | | Heavy Metal | 11 |
| Rock | 64 | | Funk | 9 |
| Hip-Hop/Rap | 46 | | Jazz | 7 |
| Electronic/Live | 29 | | Electronic/DJ | 3 |
| Punk | 26 | | Country | 3 |
| Folk | 20 | | u. a. | |

**Zwei Fallen:**

* Acts haben **mehrere** Genres (z. B. `["Alternative", "Rock"]`). Der Filter
  muss Mehrfachzuordnung koennen, sonst verschwinden Acts je nach
  Sortierreihenfolge.
* **7 % der Auftritte haben gar kein Genre.** Ohne eigenen Eimer "ohne Angabe"
  fallen sie bei jedem aktiven Filter unsichtbar heraus — das ist genau die Art
  Verhalten, die Vertrauen in einen Filter zerstoert.

Zusaetzlich liegt `mood` vor (`fieldMood`), im aktuellen Bestand aber duenn
besetzt.

## 7. Locations auf der Karte nicht auffindbar

**Wahrscheinliche Ursache gefunden — mit Einschraenkung:** Ich habe die
offizielle App nicht untersucht, sondern nur die Datenstruktur. Was ich sagen
kann, passt aber genau zum beschriebenen Symptom.

**Unter-Locations tragen selbst keine Koordinaten.** Raeume und Nebenbuehnen
innerhalb eines Hauses — `"Molotow  / Top10"`, `"BETTY  / BETTY Bar"` — haben
ein leeres `fieldGeolocation`. Die Koordinaten haengen am uebergeordneten
Eintrag in `fieldParentLocation`. Wer diese Vererbung nicht aufloest, hat fuer
solche Buehnen keinen Kartenpunkt.

Zahlen aus dem Abruf:

* 189 Locations insgesamt
* 134 mit eigenen Koordinaten
* **20 nur ueber den Elternort verortbar**
* 35 ohne Koordinaten in der Quelle (davon keine im aktuellen Line-up)

Fuer die 34 im Line-up genutzten Spielorte: **34 von 34 verortbar**, 2 davon
ausschliesslich ueber die Elternauflösung. Ohne sie fehlen zwei Spielstaetten
auf der Karte — genau der beschriebene Effekt.

Pruefbar mit:

```bash
python3 fetch_venues.py --check
```

Der Befehl liefert Exit-Code 1, wenn ein Spielort aus dem Line-up nicht
verortbar ist. Damit taugt er als Regressionstest, wenn das Festival neue
Spielorte nachtraegt.

---

## Was daraus folgt

Die Datenschicht deckt alle sieben Punkte ab. Der Flaschenhals ist die
Oberflaeche — und dafuer ist die Technologieentscheidung noch offen: Web-App,
mobile App, oder erst einmal eine statische Seite mit lokalem Speicher.

Vier der sieben Punkte (1, 2, 4, 5) sind ausschliesslich Frontend-Verhalten und
haengen an dieser Entscheidung. Drei (3, 6, 7) sind datenseitig erledigt und
warten nur auf eine Darstellung.

Punkt 4 ist der einzige, bei dem ein Ergebnis nicht garantiert werden kann —
die iOS-Regel zur Tastatur laesst sich nicht umgehen, nur korrekt bedienen.
