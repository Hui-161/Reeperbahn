#!/usr/bin/env python3
"""Ein Befehl: Line-up holen, Snapshot ablegen, Aenderungen melden.

Fuer den taeglichen Lauf per cron oder GitHub Actions gedacht.

Exit-Codes (fuer Automatisierung):
    0  keine Aenderungen
    10 Aenderungen gefunden (Details auf stdout)
    1  Fehler beim Abruf

Nutzung:
    python3 sync.py
    python3 sync.py --edition 4 --json
    python3 sync.py --quiet          # nur bei Aenderungen etwas ausgeben
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import gql
from fetch_lineup import fetch_act_ids, fetch_details, to_shows
from rbf_core import Show, SnapshotStore, diff, format_diff


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", default="4", help="Edition-ID (2026 = 4)")
    ap.add_argument("--dir", default="data/snapshots")
    ap.add_argument("--chunk", type=int, default=20)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--json", action="store_true", help="Diff als JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="bei Gleichstand nichts ausgeben (fuer cron)")
    args = ap.parse_args()

    gql.DELAY = args.delay
    store = SnapshotStore(args.dir)
    previous = store.latest()

    try:
        ids = fetch_act_ids(args.edition)
        types = {t for a in ids for t in (a.get("fieldParticipantType") or [])}
        if types - {"act"}:
            print(f"ABBRUCH: unerwartete Participant-Typen {sorted(types - {'act'})}. "
                  f"Die Act-Liste koennte Personendaten von Konferenz-Sprechenden "
                  f"enthalten - bitte pruefen, bevor weiter abgerufen wird.",
                  file=sys.stderr)
            return 1
        raw = fetch_details([a["nid"] for a in ids], args.chunk)
    except Exception as exc:
        print(f"Abruf fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    shows_data, _ = to_shows(raw)
    shows = [Show.from_dict(s) for s in shows_data]
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    if previous is None:
        path = store.save(shows, stamp)
        print(f"Erster Snapshot: {len(shows)} Auftritte, "
              f"{len({s.artist_slug for s in shows})} Acts -> {path}")
        return 0

    result = diff(previous, shows)
    changed = any(result.values())
    path = store.save(shows, stamp)

    if not changed:
        if not args.quiet:
            print(f"Keine Aenderungen ({len(shows)} Auftritte). "
                  f"Kein neuer Snapshot." if path is None else
                  f"Keine inhaltlichen Aenderungen, Snapshot: {path}")
        return 0

    header = (f"Reeperbahn Festival - Aenderungen am {stamp}\n"
              f"{len(previous)} -> {len(shows)} Auftritte\n")
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json
          else header + "\n" + format_diff(result))
    return 10


if __name__ == "__main__":
    sys.exit(main())
