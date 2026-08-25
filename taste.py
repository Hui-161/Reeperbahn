#!/usr/bin/env python3
"""Gleicht eigene Playlist-Bewertungen gegen das Line-up ab und schaetzt,
welche der noch unbewerteten Acts eher nichts sind.

Datenlage bestimmt, was seriös geht: viele Rejects, wenige Likes. Daraus
laesst sich ein "eher nicht"-Filter bauen, aber kein Empfehlungssystem.
Das Skript sagt deshalb, wie belastbar jede Aussage ist, statt eine
Rangliste zu erfinden.

Eingabe:  taste/labels.csv           (nr,label,artist - label: like|reject)
          web/data/lineup.json       (aus build_web.py)
Ausgabe:  taste/suggestions.json     (fuer die Web-App)
          Bericht auf stdout

Nutzung:
    python3 taste.py
    python3 taste.py --min-evidence 4
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

LABELS = Path("taste/labels.csv")
PROFILE = Path("taste/profile.csv")

# Kuenstlernamen, die als normale Woerter in deutschen oder englischen Texten
# vorkommen. Ohne diese Liste liefert die Bio-Suche Unsinn: "Traenen" ist in
# drei Bios das Wort fuer Traenen, "das Pop" ist Artikel plus Genre
# ("das Pop-Punk-Trio"), "jungle" ein Genrebegriff ("breakbeat jungle").
BIO_STOPWORDS = {
    "tranen", "das pop", "jungle", "ende", "sind", "slut", "dusted", "keir",
    "aze", "kasi", "leila", "hard life", "cool aid", "gossip", "lovehead",
    "vian", "sum one", "wallners", "nauplia", "leyya", "ennio",
}
LINEUP = Path("web/data/lineup.json")
OUT = Path("taste/suggestions.json")

# Mehrere Interpreten in einer Zeile: dann ist nicht entscheidbar, WER
# gemeint war. Solche Zeilen werden gemeldet, nicht geraten.
MULTI = re.compile(r",| & | and |, ")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("ø", "o").replace("Ø", "o").replace("ß", "ss")
    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def load_csv_column(path: Path, column: str) -> list[str]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    return [r[column].strip() for r in csv.DictReader(lines) if r.get(column)]


def bio_matches(bio: str, profile: list[str]) -> list[str]:
    """Nennt die Bio einen Kuenstler aus dem eigenen Profil?

    Nur mit Wortgrenzen und ohne die Namen aus BIO_STOPWORDS - sonst ueberwiegen
    die Fehltreffer die echten Funde.
    """
    hay = " " + fold(bio) + " "
    found = []
    for name in profile:
        key = fold(name)
        if len(key) < 5 or key in BIO_STOPWORDS:
            continue
        if re.search(r"\b" + re.escape(key) + r"\b", hay):
            found.append(name)
    return found


def load_labels(path: Path) -> list[dict]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=str(LABELS))
    ap.add_argument("--profile", default=str(PROFILE))
    ap.add_argument("--lineup", default=str(LINEUP))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--min-evidence", type=int, default=3,
                    help="ab wie vielen bewerteten Acts ein Genre als belastbar gilt")
    args = ap.parse_args()

    if not Path(args.labels).exists():
        sys.exit(f"Keine Labels: {args.labels}")
    data = json.loads(Path(args.lineup).read_text(encoding="utf-8"))
    acts, genres = data["acts"], data["genres"]
    by_name = {fold(a["n"]): a for a in acts}

    # ---------- 1. Labels auf Acts abbilden ----------
    verdict: dict[int, str] = {}
    unresolved, conflicts = [], []

    for row in load_labels(Path(args.labels)):
        raw, label = row["artist"].strip(), row["label"].strip()
        act = by_name.get(fold(raw))
        if act is None:
            reason = ("mehrere Interpreten - nicht entscheidbar, wer gemeint ist"
                      if MULTI.search(raw) else "kein Act dieses Namens im Line-up")
            unresolved.append({"nr": row.get("nr"), "artist": raw,
                               "label": label, "reason": reason})
            continue
        prev = verdict.get(act["id"])
        if prev and prev != label:
            conflicts.append({"artist": act["n"], "labels": [prev, label]})
            continue
        verdict[act["id"]] = label

    likes = [a for a in acts if verdict.get(a["id"]) == "like"]
    rejects = [a for a in acts if verdict.get(a["id"]) == "reject"]
    open_acts = [a for a in acts if a["id"] not in verdict]

    print("=== Abgleich ===")
    print(f"  Line-up:            {len(acts)} Acts")
    print(f"  zugeordnet:         {len(verdict)}  ({len(likes)} like, {len(rejects)} reject)")
    print(f"  nicht zugeordnet:   {len(unresolved)}")
    print(f"  noch offen:         {len(open_acts)}")
    if conflicts:
        print(f"  WIDERSPRUECHE:      {len(conflicts)}")
        for c in conflicts:
            print(f"     {c['artist']}: {c['labels']}")

    if unresolved:
        print("\n=== Nicht zugeordnet (bitte selbst entscheiden) ===")
        for u in unresolved:
            print(f"  #{u['nr']:>4} {u['label']:6s} {u['artist'][:44]:46s} {u['reason']}")

    # ---------- 2. Was sagen die Labels ueber Genres? ----------
    gl, gr = Counter(), Counter()
    for a in likes:
        for i in a["g"]:
            gl[i] += 1
    for a in rejects:
        for i in a["g"]:
            gr[i] += 1

    total = Counter()
    for a in acts:
        for i in a["g"]:
            total[i] += 1

    print("\n=== Genres: wie streng hast du aussortiert? ===")
    print("  Genre                 bewertet  davon raus   Anteil   im Line-up")
    rows = []
    for i, name in enumerate(genres):
        judged = gl[i] + gr[i]
        if not judged:
            continue
        share = gr[i] / judged
        rows.append((share, judged, i, name))
    for share, judged, i, name in sorted(rows, key=lambda r: (-r[0], -r[1])):
        weak = "" if judged >= args.min_evidence else "   (zu wenig Daten)"
        print(f"  {name:20s} {judged:>7}   {gr[i]:>8}   {share:>6.0%}   {total[i]:>8}{weak}")

    base = len(rejects) / max(1, len(verdict))
    print(f"\n  Grundrate: {base:.0%} aller von dir bewerteten Acts hast du aussortiert.")
    print("  Ein Genre ist nur dann aussagekraeftig, wenn sein Anteil deutlich")
    print("  darueber oder darunter liegt UND genug bewertete Acts dahinterstehen.")

    # ---------- 3. Offene Acts einschaetzen ----------
    def genre_score(i: int) -> tuple[float, int]:
        """Laplace-geglaettete Reject-Wahrscheinlichkeit eines Genres."""
        judged = gl[i] + gr[i]
        return (gr[i] + 1) / (judged + 2), judged

    profile = load_csv_column(Path(args.profile), "artist") \
        if Path(args.profile).exists() else []
    profile_folded = {fold(p) for p in profile}
    print(f"\n=== Positiv-Profil: {len(profile)} Kuenstler ===")
    plays = [a for a in acts if fold(a["n"]) in profile_folded]
    for a in plays:
        print(f"  SPIELT SELBST: {a['n']} [{', '.join(genres[i] for i in a['g'])}]")

    scored = []
    for a in open_acts:
        parts = [genre_score(i) for i in a["g"]]
        strong = [(s, n) for s, n in parts if n >= args.min_evidence]
        use = strong or parts
        if use:
            score = sum(s for s, _ in use) / len(use)
            evidence = sum(n for _, n in use)
        else:
            score, evidence = base, 0
        refs = bio_matches(a.get("bio") or "", profile) if profile else []
        direct = fold(a["n"]) in profile_folded
        scored.append({
            "id": a["id"], "name": a["n"], "score": round(score, 3),
            "evidence": evidence,
            "profile_hit": direct,
            "bio_refs": refs,
            "genres": [genres[i] for i in a["g"]] or ["ohne Angabe"],
            "country": a.get("c"),
            "spotify": a.get("sp"),
        })

    scored.sort(key=lambda x: (-x["score"], -x["evidence"], x["name"]))
    solid = [s for s in scored if s["evidence"] >= args.min_evidence]

    print(f"\n=== Einschaetzung der {len(open_acts)} offenen Acts ===")
    print(f"  mit belastbarer Genre-Evidenz: {len(solid)}")
    print("\n  Am ehesten aussortierbar (Genres, die du stark gefiltert hast):")
    for s in solid[:12]:
        print(f"    {s['score']:.2f}  {s['name'][:30]:32s} {', '.join(s['genres'])[:34]}")
    print("\n  Am ehesten interessant (nur Genre-Signal):")
    for s in reversed(solid[-12:]):
        print(f"    {s['score']:.2f}  {s['name'][:30]:32s} {', '.join(s['genres'])[:34]}")

    strong = [s for s in scored if s["profile_hit"] or s["bio_refs"]]
    print(f"\n=== Belegte Treffer ({len(strong)}) - Bio nennt eigene Hoergewohnheiten ===")
    for s in sorted(strong, key=lambda x: (not x["profile_hit"], -len(x["bio_refs"]))):
        mark = "SPIELT SELBST" if s["profile_hit"] else ", ".join(s["bio_refs"])
        print(f"  {s['name'][:26]:28s} {', '.join(s['genres'])[:26]:28s} {mark}")

    # ---------- 4. Ausgabe fuer die App ----------
    payload = {
        "generated_from": {"labels": args.labels, "lineup": data.get("generated_at")},
        "base_reject_rate": round(base, 3),
        "min_evidence": args.min_evidence,
        "known": {str(a["id"]): verdict[a["id"]] for a in acts if a["id"] in verdict},
        "suggested": {str(s["id"]): s["score"] for s in scored},
        "profile_hits": [s["id"] for s in scored if s["profile_hit"]],
        "bio_refs": {str(s["id"]): s["bio_refs"] for s in scored if s["bio_refs"]},
        "evidence": {str(s["id"]): s["evidence"] for s in scored},
        "unresolved": unresolved,
        "conflicts": conflicts,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"\n{args.out} geschrieben")

    print("\n=== Wie belastbar ist das? ===")
    print(f"  Negativ-Signal: stark. {len(rejects)} aussortierte Acts, Grundrate {base:.0%};")
    print("  Hip-Hop/Rap, Electronic und Heavy Metal hast du restlos gestrichen.")
    if profile:
        print(f"  Positiv-Signal: {len(profile)} Kuenstler im Hoerprofil, aber nur "
              f"{len(strong)} Acts")
        print("  lassen sich daran BELEGEN (Bio nennt einen davon). Der Rest ist")
        print("  Genre-Naeherung - und Genre trennt schlecht: von deinen bewerteten")
        print(f"  Indie-Acts hast du {gr[genres.index('Indie')]}/"
              f"{gl[genres.index('Indie')] + gr[genres.index('Indie')]} aussortiert.")
        print("  Heisst: die belegten Treffer sind belastbar, die Genre-Rangliste")
        print("  taugt zum Vorsortieren, nicht als Empfehlung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
