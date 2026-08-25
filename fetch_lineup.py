#!/usr/bin/env python3
"""Holt das Reeperbahn-Festival-Line-up ueber die GraphQL-API der Website.

Endpunkt:  https://www.reeperbahnfestival.com/graphql   (POST, keine Auth)
Backend:   Drupal + graphql_views. Introspection ist offen.

Warum zwei Phasen:
  1. Die View "overview_act" liefert - auf eine Edition gefiltert - genau die
     Musik-Acts (fieldParticipantType = "act"). Ihr Argument "page" wird
     serverseitig ignoriert, ein hohes "limit" liefert aber alles. Mit allen
     Detailfeldern auf einmal antwortet der Server jedoch mit 502.
  2. Deshalb holt Phase 1 nur die Node-IDs und Phase 2 die Details per
     entityQuery in kleinen Bloecken. entityQuery hat ein funktionierendes
     offset/limit.

Datenschutz - bewusste Grenze:
  Der Drupal-Typ NodeParticipant wird auch fuer Konferenz-Sprechende benutzt
  (Edition 2026: 528 Participants, davon 341 Musik-Acts) und enthaelt Felder
  wie fieldFirstName, fieldLastName, fieldPosition, fieldCompany, fieldPronouns.
  Dieses Skript fragt diese Felder NICHT ab und beschraenkt sich ueber die
  Act-Liste aus Phase 1 auf Musik-Acts. Nicht angefragt werden ausserdem die
  Typen OsContact*, OsCheckInRecord*, OsRecordMember*, NodePerson und
  WebformSubmission* - dort liegen Kontakt-, Gaesteliste- und Bewerbungsdaten.

Nur Standardbibliothek.

Nutzung:
    python3 fetch_lineup.py --editions
    python3 fetch_lineup.py --edition 4
    python3 fetch_lineup.py --edition 4 --chunk 15 --delay 2.0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import gql
from gql import query

PLACEHOLDER_TIME = "06:00"

EDITIONS_Q = """
{
  entityQuery(entityType: OS_EDITION, limit: 30) {
    items {
      ... on OsEdition { id label status date { value endValue } }
    }
  }
}
"""

# Phase 1: nur IDs - bewusst schlank, damit der Server nicht mit 502 abbricht.
ACT_IDS_Q = """
query ActIds($edition: String!, $limit: Int!) {
  getView(id: "overview_act") {
    executable(displayId: "default") {
      ... on ViewOverviewActDefault {
        execute(limit: $limit, filters: { edition: $edition }) {
          rows {
            ... on NodeParticipant { nid title fieldParticipantType }
          }
        }
      }
    }
  }
}
"""

# Phase 2: Details, ausschliesslich oeffentliche Programmfelder.
ACT_DETAIL_Q = """
query ActDetails($nids: [String]!) {
  entityQuery(
    entityType: NODE
    limit: 200
    filter: { conditions: [{ field: "nid", value: $nids, operator: IN }] }
  ) {
    total
    items {
      ... on NodeParticipant {
        nid
        uuid
        title
        fieldParticipantType
        fieldProgramNumber
        fieldCountry { value }
        fieldGenre { name }
        fieldMood { name }
        fieldSpotify { uri { path } }
        fieldSoundcloud { uri { path } }
        fieldYoutube { uri { path } }
        fieldWebsite { uri { path } }
        fieldBiography
        # R3_2 ist ein serverseitiges Derivat: 900x600 statt Original.
        # Beim Test 75 KB statt 2124 KB - Faktor 28 auf Festival-WLAN.
        fieldImage {
          fieldMediaImage {
            alt
            entity { url { path } }
            derivative(style: R3_2) { urlPath width height }
          }
        }
        url { path }
        fieldAppearances {
          nid
          title
          fieldDate
          fieldWeekday
          fieldShowcase
          fieldPlanned
          fieldVenue { title }
          fieldVenueLocation { label }
          fieldGenre { name }
          url { path }
        }
      }
    }
  }
}
"""


def check_braces(text: str, label: str) -> None:
    depth = 0
    for ch in text:
        depth += (ch == "{") - (ch == "}")
        if depth < 0:
            raise ValueError(f"{label}: schliessende Klammer ohne Gegenstueck")
    if depth:
        raise ValueError(f"{label}: {depth} Klammer(n) offen")


for _name, _q in (("EDITIONS_Q", EDITIONS_Q), ("ACT_IDS_Q", ACT_IDS_Q),
                  ("ACT_DETAIL_Q", ACT_DETAIL_Q)):
    check_braces(_q, _name)


def first(value):
    """Drupal liefert Felder teils als Liste, teils als Einzelwert."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def names(value) -> list[str]:
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    return [i["name"] for i in items if isinstance(i, dict) and i.get("name")]


def link(value) -> str | None:
    item = first(value)
    if not isinstance(item, dict):
        return None
    uri = item.get("uri")
    return uri.get("path") if isinstance(uri, dict) else uri


SITE = "https://www.reeperbahnfestival.com"


def image_url(field) -> str | None:
    """Bevorzugt das kleine Derivat; das Original ist teils ueber 2 MB gross."""
    item = first(field)
    if not isinstance(item, dict):
        return None
    media = first(item.get("fieldMediaImage"))
    if not isinstance(media, dict):
        return None
    url = (first(media.get("derivative")) or {}).get("urlPath")
    if not url:
        entity = first(media.get("entity")) or {}
        url = (first(entity.get("url")) or {}).get("path")
    if url and url.startswith("/"):
        url = SITE + url
    return url or None


def path_of(value) -> str | None:
    item = first(value)
    return item.get("path") if isinstance(item, dict) else None


def list_editions() -> None:
    for e in query(EDITIONS_Q)["entityQuery"]["items"]:
        d = e.get("date") or {}
        mark = " [aktiv]" if e.get("status") else ""
        print(f"  id={e['id']:>3}  {e.get('label')!r:38s} "
              f"{d.get('value')} - {d.get('endValue')}{mark}")


def fetch_act_ids(edition: str, limit: int = 1000) -> list[dict]:
    rows = query(ACT_IDS_Q, {"edition": edition, "limit": limit}) \
        ["getView"]["executable"]["execute"]["rows"]
    acts = [r for r in rows if r.get("nid")]
    if len(acts) >= limit:
        print(f"  WARNUNG: {len(acts)} = Limit, evtl. abgeschnitten", file=sys.stderr)
    return acts


def fetch_details(nids: list[int], chunk: int = 20) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(nids), chunk):
        part = [str(n) for n in nids[i:i + chunk]]
        items = query(ACT_DETAIL_Q, {"nids": part})["entityQuery"]["items"]
        out.extend(x for x in items if x.get("nid"))
        print(f"  {min(i + chunk, len(nids)):>4}/{len(nids)} Acts geladen",
              file=sys.stderr)
    return out


def to_shows(acts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Flache Auftritts-Datensaetze im Schema von rbf_core.Show."""
    shows, undated = [], []
    for act in acts:
        base = {
            "artist": act.get("title"),
            "country": (first(act.get("fieldCountry")) or {}).get("value"),
            "genres": names(act.get("fieldGenre")),
            "description": act.get("fieldBiography") or None,
            "url": path_of(act.get("url")),
            "image": image_url(act.get("fieldImage")),
            "source": "graphql:entityQuery",
            "extra": {
                "nid": act.get("nid"),
                "uuid": act.get("uuid"),
                "program_number": act.get("fieldProgramNumber"),
                "moods": names(act.get("fieldMood")),
                "spotify": link(act.get("fieldSpotify")),
                "soundcloud": link(act.get("fieldSoundcloud")),
                "youtube": link(act.get("fieldYoutube")),
                "website": link(act.get("fieldWebsite")),
            },
        }

        appearances = act.get("fieldAppearances") or []
        if not isinstance(appearances, list):
            appearances = [appearances]
        appearances = [a for a in appearances if isinstance(a, dict)]

        if not appearances:
            undated.append(base)
            continue

        for ap in appearances:
            venue = first(ap.get("fieldVenue")) or {}
            location = first(ap.get("fieldVenueLocation")) or {}
            start = ap.get("fieldDate")
            show = dict(base)
            # 06:00 ist im Quellsystem der Platzhalter fuer "Tag steht,
            # Uhrzeit noch offen" - 41 von 406 Auftritten beim ersten Abruf.
            placeholder = bool(start) and start[11:16] == PLACEHOLDER_TIME
            show.update({
                "start": start,
                "day": start[:10] if start else None,
                "venue": venue.get("title") or location.get("label"),
                "stage": None,
                "ext_id": str(ap["nid"]) if ap.get("nid") is not None else None,
                "time_tbd": placeholder,
            })
            show["extra"] = dict(base["extra"], **{
                "appearance_nid": ap.get("nid"),
                "appearance_title": ap.get("title"),
                "weekday": ap.get("fieldWeekday"),
                "showcase": ap.get("fieldShowcase"),
                "planned": ap.get("fieldPlanned"),
                "appearance_url": path_of(ap.get("url")),
            })
            shows.append(show)
    return shows, undated


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--editions", action="store_true")
    ap.add_argument("--edition", default="4", help="Edition-ID (2026 = 4)")
    ap.add_argument("--chunk", type=int, default=20, help="Acts pro Detailabfrage")
    ap.add_argument("--delay", type=float, default=1.0, help="Pause zwischen Requests (s)")
    ap.add_argument("--out", default="shows.json")
    ap.add_argument("--raw-out", default="acts-raw.json")
    args = ap.parse_args()

    gql.DELAY = args.delay

    if args.editions:
        list_editions()
        return 0

    print(f"Phase 1: Act-IDs fuer Edition {args.edition}", file=sys.stderr)
    ids = fetch_act_ids(args.edition)
    types = {t for a in ids for t in (a.get("fieldParticipantType") or [])}
    print(f"  {len(ids)} Acts, fieldParticipantType={sorted(types)}", file=sys.stderr)
    if types - {"act"}:
        print(f"  WARNUNG: unerwartete Typen {types - {'act'}} - pruefen, ob "
              f"Personendaten enthalten sind", file=sys.stderr)

    print("Phase 2: Details", file=sys.stderr)
    acts = fetch_details([a["nid"] for a in ids], args.chunk)

    Path(args.raw_out).write_text(json.dumps(acts, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    shows, undated = to_shows(acts)
    Path(args.out).write_text(json.dumps(shows, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    print(f"\n{len(acts)} Acts, {len(shows)} Auftritte, "
          f"{len(undated)} Acts ohne Termin")
    print(f"  -> {args.out}, {args.raw_out}")
    if undated:
        Path("acts-ohne-termin.json").write_text(
            json.dumps(undated, indent=2, ensure_ascii=False), encoding="utf-8")
        print("  -> acts-ohne-termin.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
