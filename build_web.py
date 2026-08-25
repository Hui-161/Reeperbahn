#!/usr/bin/env python3
"""Baut die Datendatei fuer die Web-App aus Snapshot + Spielorten.

Ausgabe: web/data/lineup.json - eine einzige Datei, die die App laedt.
Genres und Spielorte werden interniert (Index statt Wiederholung), damit die
Datei auf dem Handy schnell laedt.

Nutzung:
    python3 build_web.py
    python3 build_web.py --snapshot data/snapshots/snapshot-XY.json
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import re
import sys
from datetime import date as _date, timedelta
from pathlib import Path

from fetch_venues import build as build_venues, norm, VENUES_Q
from gql import query

OUT = Path("web/data/lineup.json")

# Tagesgrenze des Festivals. Ein Auftritt um 00:30 ist gefuehlt die Nacht des
# Vortags, kein eigener Festivaltag - sonst entsteht ein Tages-Tab mit zwei
# Auftritten, und wer Samstagnacht sucht, findet sie unter Sonntag.
DAY_CUTOFF_HOUR = 5


def strip_html(text: str | None) -> str | None:
    """Biografien kommen als HTML aus Drupal. Die App zeigt Text an."""
    if not text:
        return None
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


def festival_day(iso: str | None) -> str | None:
    """Kalendertag, aber Nachtauftritte zaehlen zum Vortag."""
    if not iso:
        return None
    date, _, rest = iso.partition("T")
    if int(rest[:2] or 0) < DAY_CUTOFF_HOUR:
        y, m, d = (int(x) for x in date.split("-"))
        return (_date(y, m, d) - timedelta(days=1)).isoformat()
    return date


def newest_snapshot() -> Path:
    files = sorted(glob.glob("data/snapshots/snapshot-*.json"))
    if not files:
        sys.exit("Kein Snapshot in data/snapshots/ - erst 'python3 sync.py' laufen lassen.")
    return Path(files[-1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--offline", action="store_true",
                    help="Spielorte aus venues.json statt per API")
    args = ap.parse_args()

    snap_path = Path(args.snapshot) if args.snapshot else newest_snapshot()
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    shows_in = snap["shows"]

    if args.offline and Path("venues.json").exists():
        venues_all = json.loads(Path("venues.json").read_text(encoding="utf-8"))
    else:
        venues_all = build_venues(query(VENUES_Q)["entityQuery"]["items"])
    venue_by_key = {v["key"]: v for v in venues_all}

    # --- Spielorte: nur die, die im Line-up vorkommen ---
    used_keys, venues, vidx = {}, [], {}
    for s in shows_in:
        if s.get("venue"):
            used_keys.setdefault(norm(s["venue"]), s["venue"])
    for key, label in sorted(used_keys.items(), key=lambda x: x[1]):
        v = venue_by_key.get(key) or {}
        addr = v.get("address") or {}
        vidx[key] = len(venues)
        venues.append({
            "n": v.get("label") or re.sub(r"\s+", " ", label.strip()),
            "lat": v.get("lat"), "lng": v.get("lng"),
            "cap": v.get("capacity"),
            "addr": " ".join(x for x in (addr.get("street"),
                                         addr.get("postal_code"),
                                         addr.get("city")) if x) or None,
            "acc": v.get("accessibility") or None,
            "parent": v.get("parent"),
            "inherited": v.get("coords_from") == "parent",
        })

    # --- Genres internieren ---
    genres = sorted({g for s in shows_in for g in (s.get("genres") or [])})
    gidx = {g: i for i, g in enumerate(genres)}

    # --- Acts und Auftritte trennen: ein Act, viele Slots ---
    acts, aidx = [], {}
    for s in shows_in:
        nid = s["extra"].get("nid")
        if nid is None or nid in aidx:
            continue
        aidx[nid] = len(acts)
        acts.append({
            "id": nid,
            "n": s["artist"],
            "c": s.get("country"),
            "g": sorted(gidx[g] for g in (s.get("genres") or [])),
            "sp": s["extra"].get("spotify"),
            "yt": s["extra"].get("youtube"),
            "web": s["extra"].get("website"),
            "url": s.get("url"),
            "img": s.get("image"),
            "bio": strip_html(s.get("description")),
        })

    shows = []
    for s in shows_in:
        nid = s["extra"].get("nid")
        if nid is None:
            continue
        shows.append({
            "id": s.get("ext_id") or s.get("show_id"),
            "a": aidx[nid],
            "t": s.get("start"),
            "d": festival_day(s.get("start")),
            "tbd": bool(s.get("time_tbd")),
            "v": vidx.get(norm(s["venue"])) if s.get("venue") else None,
        })
    shows.sort(key=lambda x: (x["t"] or "", acts[x["a"]]["n"]))

    days = sorted({s["d"] for s in shows if s["d"]})
    payload = {
        "generated_at": snap["fetched_at"],
        "snapshot": snap_path.name,
        "days": days,
        "genres": genres,
        "venues": venues,
        "acts": acts,
        "shows": shows,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")

    kb = out.stat().st_size / 1024
    unlocated = [v["n"] for v in venues if v["lat"] is None]
    print(f"{out}  {kb:.0f} KB")
    print(f"  {len(acts)} Acts, {len(shows)} Auftritte, {len(venues)} Spielorte, "
          f"{len(genres)} Genres, {len(days)} Tage")
    print(f"  Spielorte mit Koordinaten: {sum(1 for v in venues if v['lat'])}/{len(venues)}"
          + (f"  OHNE: {unlocated}" if unlocated else ""))
    print(f"  Auftritte mit offener Uhrzeit: {sum(1 for s in shows if s['tbd'])}")
    nightly = [s for s in shows if s["t"] and s["d"] != s["t"][:10]]
    if nightly:
        print(f"  Nachtauftritte dem Vortag zugeordnet: {len(nightly)}  "
              + ", ".join(f"{acts[s['a']]['n']} {s['t'][11:16]}" for s in nightly[:4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
