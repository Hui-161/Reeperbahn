#!/usr/bin/env python3
"""Baut aus den Snapshots eine Liste der Aenderungen fuer die Web-App.

Warum das eine eigene Datei ist: die Snapshots unter data/snapshots/ sind die
Historie, aber sie sind zu gross und zu roh fuer das Handy (14 MB pro Stand).
Hier entsteht daraus web/data/changes.json - nur das, was den Besucher
betrifft, klein genug fuers Netz.

Interessant ist nur eine Handvoll Felder. Dass sich eine Biografie geaendert
hat, muss niemand wissen; dass ein Konzert zwei Stunden spaeter anfaengt oder
in ein anderes Haus verlegt wurde, schon - und beim Reeperbahn Festival
passiert genau das dauernd, weil Uhrzeiten zuerst als Platzhalter (06:00)
eingetragen und spaeter praezisiert werden.

    python3 build_changes.py
    python3 build_changes.py --keep 40
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from rbf_core import Show, diff

SNAPS = Path("data/snapshots")
OUT = Path("web/data/changes.json")

# Nur das, was den Abend veraendert. "description" oder "image" gehoeren
# ausdruecklich nicht dazu.
RELEVANT = {
    "start": "Uhrzeit",
    "venue": "Spielort",
    "stage": "Bühne",
    "day": "Tag",
    "time_tbd": "Uhrzeit",
}

# Ein Platzhalter ist keine Verschiebung, sondern die erste echte Uhrzeit.
PLACEHOLDER_TIME = "06:00"


def stamp_of(path: Path) -> str:
    """snapshot-20260826055634.json -> 2026-08-26T05:56:34"""
    m = re.search(r"(\d{4})(\d\d)(\d\d)(\d\d)(\d\d)(\d\d)", path.name)
    if not m:
        return ""
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}"


def load(path: Path) -> list[Show]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw["shows"] if isinstance(raw, dict) else raw
    return [Show(**{k: v for k, v in r.items() if k in Show.__annotations__})
            for r in rows]


def hhmm(iso: str | None) -> str:
    return (iso or "")[11:16]


def describe(deltas: dict) -> list[tuple[str, str, str]]:
    """Die Aenderungen EINES Auftritts, in lesbarer Form.

    Zusammen betrachtet, nicht Feld fuer Feld: wird eine Uhrzeit wieder
    offen, aendern sich time_tbd UND start gleichzeitig, und start springt
    auf den Platzhalter 06:00. Feld fuer Feld gelesen ergaebe das zwei
    Meldungen, davon eine mit einer Uhrzeit, die es nie gab.
    """
    out = []
    tbd_before, tbd_after = deltas.get("time_tbd", (None, None))
    a, b = (hhmm(deltas["start"][0]), hhmm(deltas["start"][1])) \
        if "start" in deltas else ("", "")

    if tbd_after is True or (b and b == PLACEHOLDER_TIME):
        out.append(("Uhrzeit", "stand fest", "ist wieder offen"))
    elif a and b and a != b:
        if a == PLACEHOLDER_TIME or tbd_before is True:
            out.append(("Uhrzeit", "stand noch nicht fest", b))
        else:
            out.append(("Uhrzeit", a, b))

    for field in ("venue", "stage", "day"):
        if field not in deltas:
            continue
        before, after = deltas[field]
        if not before or not after or before == after:
            continue
        out.append((RELEVANT[field], str(before), str(after)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", type=int, default=60,
                    help="wie viele Aenderungen hoechstens ausgegeben werden")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    files = sorted(SNAPS.glob("snapshot-*.json"))
    if len(files) < 2:
        # Kein Vergleich moeglich - trotzdem eine gueltige Datei schreiben,
        # damit die App nicht auf ein 404 laeuft.
        Path(args.out).write_text(json.dumps(
            {"generated_from": stamp_of(files[-1]) if files else None,
             "entries": [], "note": "noch kein zweiter Stand zum Vergleich"},
            indent=2, ensure_ascii=False), encoding="utf-8")
        print("Nur ein Snapshot - leere Aenderungsliste geschrieben.")
        return 0

    entries = []
    prev = load(files[0])
    for path in files[1:]:
        cur = load(path)
        when = stamp_of(path)
        d = diff(prev, cur)

        for c in d["changed_shows"]:
            deltas = {k: v for k, v in c["changes"].items() if k in RELEVANT}
            for label, a, b in describe(deltas):
                entries.append({
                    "at": when, "kind": "moved", "act": c["artist"],
                    "show": c.get("ext_id"), "what": label,
                    "from": a, "to": b,
                })
        for s in d["added_shows"]:
            entries.append({"at": when, "kind": "added", "act": s["artist"],
                            "show": s.get("ext_id"),
                            "what": "neu im Programm",
                            "from": "", "to": hhmm(s.get("start")) or "Zeit offen"})
        for s in d["removed_shows"]:
            entries.append({"at": when, "kind": "removed", "act": s["artist"],
                            "show": s.get("ext_id"),
                            "what": "aus dem Programm genommen",
                            "from": hhmm(s.get("start")), "to": ""})
        prev = cur

    # Neueste zuerst, dann kappen. Die alten Staende sind im Repository, hier
    # geht es um "was hat sich zuletzt geaendert".
    entries.reverse()
    cut = entries[:args.keep]

    payload = {
        "generated_from": stamp_of(files[-1]),
        "compared": len(files),
        "total": len(entries),
        "entries": cut,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    kinds = {}
    for e in entries:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"{len(files)} Staende verglichen, {len(entries)} Aenderungen "
          f"({', '.join(f'{v}x {k}' for k, v in sorted(kinds.items())) or 'keine'})")
    print(f"{args.out} geschrieben ({len(cut)} Eintraege, "
          f"{Path(args.out).stat().st_size} Bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
