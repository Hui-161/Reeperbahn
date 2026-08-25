#!/usr/bin/env python3
"""Holt die Spielorte mit Koordinaten, Adresse, Kapazitaet, Barrierefreiheit.

Wichtige Eigenheit der Quelle:
Unter-Locations (Raeume und Buehnen innerhalb eines Hauses, z. B.
"Molotow  / Top10") haben SELBST keine Koordinaten - die haengen am
Elterneintrag in fieldParentLocation. Wer das nicht aufloest, findet solche
Buehnen auf einer Karte nicht. 134 der 189 Locations tragen eigene
Koordinaten; mit Elternauflösung sind alle 34 im Line-up verwendeten
Spielorte verortbar.

Ausserdem sind die Labels der Quelle teils mit Leerzeichen verunreinigt
("Molotow " mit Leerzeichen am Ende, "Molotow  / Top10" mit doppeltem) -
deshalb der normalisierte Schluessel.

Nur Standardbibliothek.

Nutzung:
    python3 fetch_venues.py --out venues.json
    python3 fetch_venues.py --check data/snapshots/snapshot-*.json
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

from gql import query

VENUES_Q = """
{
  entityQuery(entityType: OS_LOCATION, limit: 500) {
    total
    items {
      ... on OsLocation {
        id
        label
        description
        fieldCapacity
        fieldGeolocation { lat lng }
        fieldAddress { addressLine1 postalCode locality countryCode }
        fieldAccesibility { name }
        fieldParentLocation { id label fieldGeolocation { lat lng } }
        url { path }
      }
    }
  }
}
"""


def first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def norm(label: str | None) -> str:
    """Labels der Quelle haben unsaubere Leerzeichen - Schluessel normalisieren."""
    return re.sub(r"\s+", " ", (label or "").strip()).casefold()


def coords(node) -> tuple[float, float] | None:
    geo = first((node or {}).get("fieldGeolocation"))
    if isinstance(geo, dict) and geo.get("lat") is not None:
        return (geo["lat"], geo["lng"])
    return None


def build(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        if not it.get("label"):
            continue
        parent = first(it.get("fieldParentLocation")) or {}
        own = coords(it)
        inherited = coords(parent) if not own else None
        # Nur Ortsangaben. Der Adresstyp hat auch givenName/familyName -
        # Personenfelder, die hier nichts zu suchen haben.
        addr = first(it.get("fieldAddress")) or {}
        lat_lng = own or inherited
        out.append({
            "id": it.get("id"),
            "label": re.sub(r"\s+", " ", it["label"].strip()),
            "key": norm(it["label"]),
            "parent": re.sub(r"\s+", " ", parent["label"].strip()) if parent.get("label") else None,
            "lat": lat_lng[0] if lat_lng else None,
            "lng": lat_lng[1] if lat_lng else None,
            "coords_from": "self" if own else ("parent" if inherited else None),
            "capacity": it.get("fieldCapacity"),
            "accessibility": [a["name"] for a in (it.get("fieldAccesibility") or [])
                              if isinstance(a, dict) and a.get("name")]
            if isinstance(it.get("fieldAccesibility"), list)
            else ([it["fieldAccesibility"]["name"]]
                  if isinstance(it.get("fieldAccesibility"), dict) else []),
            "address": {
                "street": addr.get("addressLine1"),
                "postal_code": addr.get("postalCode"),
                "city": addr.get("locality"),
                "country_code": addr.get("countryCode"),
            } if addr else None,
            "description": it.get("description") or None,
            "url": (first(it.get("url")) or {}).get("path"),
        })
    return out


def check_against(venues: list[dict], snapshot_glob: str) -> int:
    """Prueft, ob jeder Spielort aus einem Snapshot verortbar ist."""
    files = sorted(glob.glob(snapshot_glob))
    if not files:
        print(f"Kein Snapshot gefunden: {snapshot_glob}", file=sys.stderr)
        return 1
    shows = json.loads(Path(files[-1]).read_text(encoding="utf-8"))["shows"]
    by_key = {v["key"]: v for v in venues}

    used = {}
    for s in shows:
        if s.get("venue"):
            used.setdefault(norm(s["venue"]), s["venue"])

    located, unlocated = [], []
    for key, label in sorted(used.items(), key=lambda x: x[1]):
        v = by_key.get(key)
        (located if v and v["lat"] is not None else unlocated).append((label, v))

    print(f"Snapshot: {files[-1]}")
    print(f"  Spielorte im Line-up: {len(used)}")
    print(f"  verortbar:            {len(located)}")
    inherited = [l for l, v in located if v["coords_from"] == "parent"]
    if inherited:
        print(f"  davon ueber Elternort: {len(inherited)}  {inherited}")
    if unlocated:
        print(f"  NICHT verortbar ({len(unlocated)}):")
        for label, v in unlocated:
            print(f"     {label!r}  (im Ortsverzeichnis: {'ja' if v else 'nein'})")
        return 1
    print("  Alle Spielorte verortbar.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="venues.json")
    ap.add_argument("--check", nargs="?", const="data/snapshots/snapshot-*.json",
                    help="gegen den neuesten Snapshot pruefen")
    args = ap.parse_args()

    data = query(VENUES_Q)["entityQuery"]
    venues = build(data["items"])
    own = sum(1 for v in venues if v["coords_from"] == "self")
    inh = sum(1 for v in venues if v["coords_from"] == "parent")
    none_ = sum(1 for v in venues if v["coords_from"] is None)

    Path(args.out).write_text(json.dumps(venues, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"{len(venues)} Spielorte -> {args.out}")
    print(f"  eigene Koordinaten: {own}, ueber Elternort: {inh}, ohne: {none_}")

    if args.check:
        return check_against(venues, args.check)
    return 0


if __name__ == "__main__":
    sys.exit(main())
