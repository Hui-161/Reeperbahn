#!/usr/bin/env python3
"""Kern des eigenen Reeperbahn-Systems: Datenmodell, Snapshots, Diff, Kalender.

Dieser Teil ist unabhaengig davon, wie die Daten von der Website kommen.
Er erwartet nur normalisierte Auftritte (Shows) und leistet dann:

  * stabile IDs, damit ein Auftritt ueber Snapshots hinweg wiedererkannt wird
  * versionierte Snapshots mit Inhalts-Hash (identische Laeufe erzeugen
    keinen neuen Snapshot)
  * Diff zwischen zwei Snapshots: neue / entfallene / geaenderte Auftritte
  * ICS-Export fuer den eigenen Zeitplan

Nur Standardbibliothek.

Nutzung:
    python3 rbf_core.py snapshot shows.json      # Snapshot ablegen
    python3 rbf_core.py diff                     # letzte zwei vergleichen
    python3 rbf_core.py diff a.json b.json
    python3 rbf_core.py ics shows.json --artists "shame,Lowertown"
    python3 rbf_core.py selftest
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

SNAPSHOT_DIR = Path("data/snapshots")
SITE = "https://www.reeperbahnfestival.com"

# Felder, deren Aenderung als inhaltliche Aenderung gemeldet wird.
# Bewusst ohne "description"/"image": dort rauschen CMS-Umbrueche staendig.
WATCHED_FIELDS = ("start", "end", "venue", "stage", "day", "country",
                  "genres", "url", "time_tbd")


def slugify(text: str) -> str:
    """Normalisiert Kuenstlernamen fuer den Vergleich. 'Sløtface' -> 'slotface'."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ø", "o").replace("Ø", "o").replace("ß", "ss")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")


@dataclasses.dataclass
class Show:
    """Ein Auftritt. 'artist' und 'start' bilden die Identitaet."""

    artist: str
    start: str | None = None          # ISO 8601, z. B. "2026-09-17T21:00:00+02:00"
    ext_id: str | None = None         # stabile Quell-ID des Auftritts (appearance_nid)
    time_tbd: bool = False            # Uhrzeit noch Platzhalter, Tag steht
    end: str | None = None
    venue: str | None = None
    stage: str | None = None
    day: str | None = None            # "2026-09-17"
    country: str | None = None
    genres: list[str] = dataclasses.field(default_factory=list)
    url: str | None = None
    description: str | None = None
    image: str | None = None
    source: str | None = None         # woher der Datensatz stammt
    extra: dict = dataclasses.field(default_factory=dict)

    @property
    def artist_slug(self) -> str:
        return slugify(self.artist)

    @property
    def show_id(self) -> str:
        """Stabile Identitaet eines Auftritts.

        Bevorzugt die ID der Quelle (appearance_nid): nur so bleibt ein
        Auftritt derselbe, wenn sich Uhrzeit ODER Venue aendern - und genau
        das passiert dauernd, weil Uhrzeiten zunaechst als Platzhalter
        (06:00) eingetragen sind und spaeter praezisiert werden.

        Ohne Quell-ID: Kuenstler + Startzeit, notfalls Kuenstler + Venue.
        Der Venue ist nie alleiniger zweiter Teil, wenn eine Zeit existiert -
        eine Verlegung soll als Aenderung erscheinen, nicht als neuer Slot.
        """
        if self.ext_id:
            return hashlib.sha1(f"appearance:{self.ext_id}".encode()).hexdigest()[:16]
        second = self.start or f"venue:{slugify(self.venue or '')}"
        return hashlib.sha1(f"{self.artist_slug}|{second}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        data = dataclasses.asdict(self)
        data["show_id"] = self.show_id
        data["artist_slug"] = self.artist_slug
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Show":
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in fields})


def content_hash(shows: list[Show]) -> str:
    """Hash ueber den fachlichen Inhalt - unabhaengig von der Sortierung."""
    payload = sorted(
        json.dumps({k: v for k, v in s.to_dict().items() if k != "extra"},
                   sort_keys=True, ensure_ascii=False)
        for s in shows
    )
    return hashlib.sha256("\n".join(payload).encode()).hexdigest()[:16]


class SnapshotStore:
    def __init__(self, directory: Path = SNAPSHOT_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[Path]:
        return sorted(self.dir.glob("snapshot-*.json"))

    def load(self, path: Path) -> list[Show]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return [Show.from_dict(s) for s in data["shows"]]

    def latest(self) -> list[Show] | None:
        files = self.list()
        return self.load(files[-1]) if files else None

    def save(self, shows: list[Show], fetched_at: str | None = None) -> Path | None:
        """Legt einen Snapshot ab. Gibt None zurueck, wenn sich inhaltlich
        nichts geaendert hat - so bleibt die Historie aussagekraeftig."""
        new_hash = content_hash(shows)
        files = self.list()
        if files:
            previous = json.loads(files[-1].read_text(encoding="utf-8"))
            if previous.get("content_hash") == new_hash:
                return None

        stamp = fetched_at or datetime.now().astimezone().isoformat(timespec="seconds")
        path = self.dir / f"snapshot-{re.sub(r'[^0-9]', '', stamp)[:14]}.json"
        path.write_text(
            json.dumps(
                {
                    "fetched_at": stamp,
                    "content_hash": new_hash,
                    "show_count": len(shows),
                    "artist_count": len({s.artist_slug for s in shows}),
                    "shows": [s.to_dict() for s in shows],
                },
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path


def diff(old: list[Show], new: list[Show]) -> dict:
    """Vergleicht zwei Staende. Kuenstler-Ebene und Auftritts-Ebene getrennt,
    weil ein verschobener Slot etwas anderes ist als ein neuer Act."""
    old_by_id = {s.show_id: s for s in old}
    new_by_id = {s.show_id: s for s in new}
    old_artists = {s.artist_slug: s.artist for s in old}
    new_artists = {s.artist_slug: s.artist for s in new}

    changed = []
    for show_id in old_by_id.keys() & new_by_id.keys():
        before, after = old_by_id[show_id], new_by_id[show_id]
        deltas = {
            field: [getattr(before, field), getattr(after, field)]
            for field in WATCHED_FIELDS
            if getattr(before, field) != getattr(after, field)
        }
        if deltas:
            # ext_id mitgeben: nur damit kann die Web-App den geaenderten
            # Auftritt in ihrer eigenen Liste wiederfinden - show_id ist ein
            # Hash und steht dort nicht.
            changed.append({"artist": after.artist, "show_id": show_id,
                            "ext_id": after.ext_id, "changes": deltas})

    return {
        "added_shows": [s.to_dict() for i, s in new_by_id.items() if i not in old_by_id],
        "removed_shows": [s.to_dict() for i, s in old_by_id.items() if i not in new_by_id],
        "changed_shows": changed,
        "added_artists": sorted(new_artists[s] for s in new_artists.keys() - old_artists.keys()),
        "removed_artists": sorted(old_artists[s] for s in old_artists.keys() - new_artists.keys()),
    }


def format_diff(result: dict) -> str:
    if not any(result.values()):
        return "Keine Aenderungen."

    lines = []
    if result["added_artists"]:
        lines.append(f"NEUE KUENSTLER ({len(result['added_artists'])})")
        lines += [f"  + {a}" for a in result["added_artists"]]
    if result["removed_artists"]:
        lines.append(f"\nENTFALLENE KUENSTLER ({len(result['removed_artists'])})")
        lines += [f"  - {a}" for a in result["removed_artists"]]
    if result["changed_shows"]:
        lines.append(f"\nGEAENDERTE AUFTRITTE ({len(result['changed_shows'])})")
        for item in result["changed_shows"]:
            lines.append(f"  ~ {item['artist']}")
            for field, (before, after) in item["changes"].items():
                lines.append(f"      {field}: {before!r} -> {after!r}")

    extra = len(result["added_shows"]) - len(result["added_artists"])
    if extra > 0:
        lines.append(f"\n{extra} zusaetzliche Auftritte bereits bekannter Kuenstler")
    return "\n".join(lines)


def _ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;") \
                       .replace(",", "\\,").replace("\n", "\\n")


def _ics_stamp(iso: str) -> str:
    """ISO 8601 -> UTC-Zeitstempel. Die Quelle liefert Offsets (+02:00);
    ohne Umrechnung entstehen 'floating times', die je Kalender anders
    interpretiert werden."""
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        return dt.strftime("%Y%m%dT%H%M%S")
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def to_ics(shows: list[Show], calendar_name: str = "Reeperbahn Festival",
           default_minutes: int = 45, site: str = SITE,
           dtstamp: str | None = None) -> str:
    """ICS-Export. Auftritte ohne Startzeit werden uebersprungen.

    Die Quelle liefert keine Endzeiten, deshalb default_minutes: ein Termin
    mit Laenge 0 wird in vielen Kalendern gar nicht angezeigt.
    """
    stamp = dtstamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//rbf-lineup//DE",
        "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{_ics_escape(calendar_name)}",
    ]
    for show in shows:
        if not show.start:
            continue
        if show.time_tbd:
            # Uhrzeit steht noch nicht fest -> Ganztagstermin statt 06:00-Termin
            day = datetime.fromisoformat(show.start).date()
            out += [
                "BEGIN:VEVENT",
                f"UID:{show.show_id}@rbf-lineup",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{_ics_escape(show.artist + ' (Uhrzeit offen)')}",
                f"LOCATION:{_ics_escape(show.venue or show.stage or '')}",
            ]
            url_tbd = show.url or ""
            if url_tbd.startswith("/"):
                url_tbd = site.rstrip("/") + url_tbd
            if url_tbd:
                out.append(f"URL:{url_tbd}")
            out.append("END:VEVENT")
            continue
        if show.end:
            end = _ics_stamp(show.end)
        else:
            end = _ics_stamp((datetime.fromisoformat(show.start)
                              + timedelta(minutes=default_minutes)).isoformat())
        url = show.url or ""
        if url.startswith("/"):
            url = site.rstrip("/") + url
        genres = ", ".join(show.genres or [])
        details = " ".join(x for x in (genres, show.country or "", url) if x)
        out += [
            "BEGIN:VEVENT",
            f"UID:{show.show_id}@rbf-lineup",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_ics_stamp(show.start)}",
            f"DTEND:{end}",
            f"SUMMARY:{_ics_escape(show.artist)}",
            f"LOCATION:{_ics_escape(show.venue or show.stage or '')}",
            f"DESCRIPTION:{_ics_escape(details)}",
        ]
        if url:
            out.append(f"URL:{url}")
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def to_csv(shows: list[Show], site: str = SITE) -> str:
    """Flache Tabelle, nach Startzeit sortiert - zum Reinschauen und Filtern."""
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["artist", "day", "start", "zeit_offen", "venue", "country",
                "genres", "spotify", "url"])
    for s in sorted(shows, key=lambda x: (x.start or "", x.artist or "")):
        url = s.url or ""
        w.writerow([s.artist, s.day, s.start, "ja" if s.time_tbd else "",
                    s.venue, s.country,
                    "; ".join(s.genres or []),
                    (s.extra or {}).get("spotify") or "",
                    site.rstrip("/") + url if url.startswith("/") else url])
    return buf.getvalue()


def load_shows(path: str | Path) -> list[Show]:
    """Liest entweder eine reine Show-Liste oder eine Snapshot-Datei."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data["shows"]
    return [Show.from_dict(s) for s in data]


def selftest() -> int:
    """Prueft Identitaet, Diff und Snapshot-Deduplizierung an Beispieldaten."""
    a = [
        Show("shame", "2026-09-17T21:00:00+02:00", venue="Docks"),
        Show("Lowertown", "2026-09-18T20:00:00+02:00", venue="Molotow"),
        Show("Gretel", "2026-09-19T22:30:00+02:00", venue="Molotow"),
    ]
    b = [
        Show("shame", "2026-09-17T21:00:00+02:00", venue="Grosse Freiheit 36"),  # Venue neu
        Show("Lowertown", "2026-09-18T20:00:00+02:00", venue="Molotow"),         # gleich
        Show("English Teacher", "2026-09-18T23:00:00+02:00", venue="Uebel"),     # neu
    ]                                                                            # Gretel weg

    assert Show("Sløtface").artist_slug == "slotface"
    assert Show("shame", "2026-09-17T21:00:00+02:00", venue="Docks").show_id == a[0].show_id

    result = diff(a, b)
    assert result["added_artists"] == ["English Teacher"], result["added_artists"]
    assert result["removed_artists"] == ["Gretel"], result["removed_artists"]
    # shame wechselt den Venue -> genau eine Aenderung, kein neuer Auftritt.
    assert [c["artist"] for c in result["changed_shows"]] == ["shame"]
    assert result["changed_shows"][0]["changes"] == {"venue": ["Docks", "Grosse Freiheit 36"]}
    assert len(result["added_shows"]) == 1, "nur English Teacher ist wirklich neu"

    assert diff(a, a) == {"added_shows": [], "removed_shows": [], "changed_shows": [],
                          "added_artists": [], "removed_artists": []}

    # Zeitverschiebung bei gleicher ID-Basis -> als Aenderung erkannt.
    c = [Show("Lowertown", "2026-09-18T20:00:00+02:00", venue="Molotow", stage="Bar")]
    d = [Show("Lowertown", "2026-09-18T20:00:00+02:00", venue="Molotow", stage="Saal")]
    assert diff(c, d)["changed_shows"][0]["changes"] == {"stage": ["Bar", "Saal"]}

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        store = SnapshotStore(Path(tmp))
        assert store.save(a) is not None
        assert store.save(a) is None, "identischer Inhalt darf keinen Snapshot erzeugen"
        assert len(store.latest()) == 3

    ics = to_ics(a, dtstamp="20260101T000000Z")
    assert ics.count("BEGIN:VEVENT") == 3
    assert to_ics([Show("Ohne Zeit")]).count("BEGIN:VEVENT") == 0
    # UTC-Umrechnung: 21:00+02:00 -> 19:00Z
    one = to_ics([Show("X", "2026-09-17T21:00:00+02:00")], dtstamp="20260101T000000Z")
    assert "DTSTART:20260917T190000Z" in one, one
    assert "DTEND:20260917T194500Z" in one, one   # 45 min Vorgabe
    assert "DTSTAMP:" in one
    # relative URL wird absolut
    rel = to_ics([Show("Y", "2026-09-17T21:00:00+02:00", url="/act/mess")],
                 dtstamp="20260101T000000Z")
    assert "URL:https://www.reeperbahnfestival.com/act/mess" in rel

    # Quell-ID gewinnt: Zeit UND Venue aendern sich, Auftritt bleibt derselbe.
    e1 = [Show("Act", "2026-09-17T06:00:00+02:00", ext_id="11646",
               venue="25 Club", time_tbd=True)]
    e2 = [Show("Act", "2026-09-17T21:30:00+02:00", ext_id="11646",
               venue="Molotow", time_tbd=False)]
    r = diff(e1, e2)
    assert not r["added_shows"] and not r["removed_shows"], r
    ch = r["changed_shows"][0]["changes"]
    assert ch["start"] == ["2026-09-17T06:00:00+02:00", "2026-09-17T21:30:00+02:00"]
    assert ch["venue"] == ["25 Club", "Molotow"]
    assert ch["time_tbd"] == [True, False]

    # Platzhalter -> Ganztagstermin, kein 06:00-Termin
    tbd = to_ics(e1, dtstamp="20260101T000000Z")
    assert "DTSTART;VALUE=DATE:20260917" in tbd, tbd
    assert "T060000" not in tbd
    assert "Uhrzeit offen" in tbd

    csv_out = to_csv([Show("A", "2026-09-17T21:00:00+02:00", venue="Docks",
                           country="DE", genres=["Indie"], url="/act/a")])
    assert "https://www.reeperbahnfestival.com/act/a" in csv_out
    assert csv_out.splitlines()[0].startswith("artist,day,start")

    print("selftest: alle Pruefungen bestanden")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("snapshot", help="Show-Liste als Snapshot ablegen")
    p.add_argument("file")
    p.add_argument("--dir", default=str(SNAPSHOT_DIR))

    p = sub.add_parser("diff", help="Zwei Snapshots vergleichen")
    p.add_argument("a", nargs="?")
    p.add_argument("b", nargs="?")
    p.add_argument("--dir", default=str(SNAPSHOT_DIR))
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("ics", help="Kalenderdatei erzeugen")
    p.add_argument("file")
    p.add_argument("--artists", help="Komma-Liste; leer = alle")
    p.add_argument("--out", default="reeperbahn.ics")

    p = sub.add_parser("csv", help="Flache CSV-Tabelle erzeugen")
    p.add_argument("file")
    p.add_argument("--out", default="shows.csv")

    sub.add_parser("selftest", help="Eigene Tests laufen lassen")

    args = ap.parse_args()

    if args.cmd == "selftest":
        return selftest()

    if args.cmd == "snapshot":
        store = SnapshotStore(Path(args.dir))
        shows = load_shows(args.file)
        path = store.save(shows)
        if path is None:
            print(f"{len(shows)} Auftritte gelesen - inhaltsgleich mit dem letzten Snapshot.")
        else:
            print(f"{len(shows)} Auftritte -> {path}")
        return 0

    if args.cmd == "diff":
        if args.a and args.b:
            old, new = load_shows(args.a), load_shows(args.b)
        else:
            files = SnapshotStore(Path(args.dir)).list()
            if len(files) < 2:
                print(f"Mindestens zwei Snapshots noetig, {len(files)} vorhanden.",
                      file=sys.stderr)
                return 1
            old, new = load_shows(files[-2]), load_shows(files[-1])
            print(f"# {files[-2].name} -> {files[-1].name}\n")
        result = diff(old, new)
        print(json.dumps(result, indent=2, ensure_ascii=False) if args.json
              else format_diff(result))
        return 0

    if args.cmd == "csv":
        shows = load_shows(args.file)
        Path(args.out).write_text(to_csv(shows), encoding="utf-8")
        print(f"{len(shows)} Auftritte -> {args.out}")
        return 0

    if args.cmd == "ics":
        shows = load_shows(args.file)
        if args.artists:
            wanted = {slugify(a) for a in args.artists.split(",") if a.strip()}
            shows = [s for s in shows if s.artist_slug in wanted]
        Path(args.out).write_text(to_ics(shows), encoding="utf-8")
        print(f"{len(shows)} Auftritte -> {args.out}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
