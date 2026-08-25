#!/usr/bin/env python3
"""Gleicht das eigene Hoerprofil gegen das Line-up ab und sortiert die Acts
nach Stilmerkmalen - nicht nach den 16 groben Festival-Genres.

Warum nicht nach Genre: die Bewertungen zeigen, dass die groben Genres kaum
trennen. "Indie+Rock" steht bei einem Like UND bei drei Rejects, "Indie+Pop"
bei einem Like und fuenf Rejects. Und "Pop" hat 1 Like zu 19 Rejects - bei
einer Grundrate von 8 % Likes ist das nicht von Zufall zu unterscheiden.
Ein Filter "Pop raus" waere also ein Artefakt der Grundrate, kein Geschmack;
das eigene Hoerprofil ist selbst voller Pop (Indie-, Bedroom-, Power-Pop).

Was stattdessen zaehlt, in dieser Reihenfolge:
  1. Der Act steht selbst im Hoerprofil.
  2. Die Bio nennt einen Kuenstler aus dem Hoerprofil.
  3. Die Bio nennt einen Kuenstler aus dem Umfeld des Profils (mein Urteil).
  4. Die Bio nennt Stilbegriffe, die zu den Profil-Clustern passen -
     oder solche, die eindeutig daneben liegen.
  5. Erst danach, mit kleinem Gewicht, das grobe Genre und das Land.

Merkmalslisten stehen in taste_vocab.py, getrennt nach "aus Daten" und
"mein Urteil". Jeder Act bekommt seine Begruendung mitgegeben, damit
nachpruefbar ist, warum er wo steht.

Eingabe:  taste/labels.csv       (nr,label,artist - label: like|reject)
          taste/profile.csv      (artist)
          web/data/lineup.json   (aus build_web.py)
Ausgabe:  taste/suggestions.json (fuer die Web-App)
          Bericht auf stdout

Nutzung:
    python3 taste.py
    python3 taste.py --top 25
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

from taste_vocab import (BIO_STOPWORDS, COUNTRY_BONUS, GENRE_TIEBREAK,
                         HARD_NEGATIVE_GENRES, MICRO_NEG, MICRO_POS,
                         NEIGHBOURS, OFF_SCENE)

LABELS = Path("taste/labels.csv")
PROFILE = Path("taste/profile.csv")
LINEUP = Path("web/data/lineup.json")
OUT = Path("taste/suggestions.json")

# Mehrere Interpreten in einer Zeile: dann ist nicht entscheidbar, WER
# gemeint war. Solche Zeilen werden gemeldet, nicht geraten.
MULTI = re.compile(r",| & | and |, ")

# Punkte, ab denen ein Act in welche Stufe faellt. Absichtlich Stufen und
# keine Prozentzahl: eine Wahrscheinlichkeit wuerde eine Kalibrierung
# behaupten, die mit fuenf Likes niemand hat.
TIERS = [
    (5.0, "A", "sehr wahrscheinlich etwas fuer dich"),
    (2.5, "B", "wahrscheinlich etwas fuer dich"),
    (1.0, "C", "koennte passen"),
    (-1.0, "D", "unklar - Bio gibt zu wenig her"),
    (float("-inf"), "E", "passt eher nicht"),
]

CAP_PROFILE_REF = 6.0     # Deckel, damit drei Namen nicht dreimal zaehlen
CAP_NEIGHBOUR = 4.0
CAP_MICRO_POS = 4.5


def fold(text: str) -> str:
    """Namensvergleich: Diakritika und Satzzeichen weg, ein Wort ein Wort."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("ø", "o").replace("Ø", "o").replace("ß", "ss")
    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def flat(text: str) -> str:
    """Bio-Text fuer die Begriffssuche: Satzzeichen werden LEERZEICHEN.

    Sonst wird aus "Post-Punk-Trio" das Wort "postpunktrio" und "post punk"
    findet nichts mehr. Zusaetzlich wird eine Variante ohne Leerzeichen
    gebaut, damit auch "postpunk" in einem Wort gefunden wird.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("ø", "o").replace("Ø", "o").replace("ß", "ss")
    text = re.sub(r"[^\w]+", " ", text.lower())
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def term_hits(bio: str, terms: dict[str, float]) -> list[tuple[str, float]]:
    """Welche Stilbegriffe nennt die Bio? Mit Wortgrenzen, damit "rap" nicht
    in "grapefruit" und "dub" nicht in "dubios" anschlaegt."""
    spaced = flat(bio)
    solid = " " + spaced.replace(" ", "") + " "
    hits = []
    for term, weight in terms.items():
        if not weight:
            continue
        pat = r"\b" + re.escape(term) + r"\b"
        if re.search(pat, spaced) or (
                " " in term and term.replace(" ", "") in solid):
            hits.append((term, weight))
    return hits


# "eroeffnete Konzerte fuer Franz Ferdinand" sagt weniger ueber den Stil als
# "Anklaenge an Franz Ferdinand" - ein Support-Slot wird vom Veranstalter
# vergeben, nicht von der Musik. Solche Treffer zaehlen nur halb.
#
# Die Erkennung bleibt bewusst im SELBEN SATZ und nur VOR dem Namen. Ein
# Fenster von n Zeichen um den Namen greift zu weit: bei The Sukis steht
# "Anklaenge an Arctic Monkeys, The Strokes ..." im einen Absatz und
# "Support-Auftritten fuer ..." im naechsten - das ist kein Support-Slot.
# "eroffnet" ist die gefaltete Form von "eroeffnet"; die oe-Schreibweise
# steht daneben, weil nicht jede Bio Umlaute benutzt.
SUPPORT_CUES = re.compile(
    r"eroffnet|eroeffnet|vorprogramm|vorgruppe|vorband|support|tourte mit|"
    r"tour mit|touren mit|begleitete|im line up von|auf tour mit")
SENT_SPLIT = re.compile(r"[.!?\n]+")
# Punkte in Abkuerzungen sind keine Satzenden. Ohne das zerfaellt
# "Fontaines D.C." in zwei Saetze und der Name wird nie gefunden.
ABBREV_DOT = re.compile(r"\b([A-Za-z])\.")


def name_hits(bio: str, names: list[str]) -> list[tuple[str, bool]]:
    """Nennt die Bio einen dieser Kuenstler? Liefert (Name, ist_Support).

    Kurze und mehrdeutige Namen (BIO_STOPWORDS) bleiben aussen vor - sonst
    ueberwiegen die Fehltreffer die echten Funde.
    """
    plain = ABBREV_DOT.sub(r"\1", bio or "")
    sentences = [flat(s) for s in SENT_SPLIT.split(plain) if s.strip()]
    found = []
    for name in names:
        key = fold(name)
        if len(key) < 5 or key in BIO_STOPWORDS:
            continue
        pat = re.compile(r"\b" + re.escape(key) + r"\b")
        for sent in sentences:
            m = pat.search(sent)
            if m:
                found.append((name, bool(SUPPORT_CUES.search(sent[:m.start()]))))
                break
    return found


def load_rows(path: Path) -> list[dict]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


def tier_of(score: float) -> tuple[str, str]:
    for limit, key, label in TIERS:
        if score >= limit:
            return key, label
    return TIERS[-1][1], TIERS[-1][2]


def score_act(act: dict, genres: list[str], profile: list[str],
              profile_folded: set[str]) -> dict:
    """Punkte plus Begruendung. Die Begruendung ist der eigentliche Wert -
    eine Zahl allein liesse sich nicht nachpruefen."""
    bio = act.get("bio") or ""
    names = [genres[i] for i in act["g"]]
    score = 0.0
    why: list[str] = []

    in_profile = fold(act["n"]) in profile_folded
    if in_profile:
        score += 6.0
        why.append("steht selbst in deiner Hoerplaylist")

    def label_ref(name: str, support: bool) -> str:
        return f"{name} (Support-Slot)" if support else name

    raw_refs = name_hits(bio, profile)
    refs = [n for n, _ in raw_refs]
    if raw_refs:
        score += min(CAP_PROFILE_REF,
                     sum(2.0 if sup else 4.0 for _, sup in raw_refs))
        why.append("Bio nennt aus deiner Playlist: "
                   + ", ".join(label_ref(n, s) for n, s in raw_refs))

    # Namen, die schon als Profil-Treffer gezaehlt haben, hier ueberspringen -
    # The Strokes und Arctic Monkeys stehen in beiden Listen.
    seen = {fold(r) for r in refs}
    raw_near = [(n, s) for n, s in name_hits(bio, NEIGHBOURS)
                if fold(n) not in seen]
    near = [n for n, _ in raw_near]
    if raw_near:
        score += min(CAP_NEIGHBOUR,
                     sum(1.0 if sup else 2.0 for _, sup in raw_near))
        why.append("Bio nennt verwandte Acts: "
                   + ", ".join(label_ref(n, s) for n, s in raw_near))

    off = [n for n, _ in name_hits(bio, OFF_SCENE)]
    if off:
        score += -2.0 * len(off)
        why.append("Bio nennt andere Ecke: " + ", ".join(off))

    pos = term_hits(bio, MICRO_POS)
    if pos:
        score += min(CAP_MICRO_POS, sum(w for _, w in pos))
        why.append("Stil passt: " + ", ".join(t for t, _ in pos))

    neg = term_hits(bio, MICRO_NEG)
    if neg:
        score += sum(w for _, w in neg)
        why.append("Stil daneben: " + ", ".join(t for t, _ in neg))

    hard = [n for n in names if n in HARD_NEGATIVE_GENRES]
    if hard:
        score += -3.0 * len(hard)
        why.append("Kategorie, in der du restlos alles aussortiert hast: "
                   + ", ".join(hard))

    tie = sum(GENRE_TIEBREAK.get(n, 0.0) for n in names)
    if tie:
        score += tie
        why.append(f"Genre-Tendenz {tie:+.2f} ({', '.join(names)})")

    bonus = COUNTRY_BONUS.get(act.get("c") or "", 0.0)
    if bonus:
        score += bonus
        why.append(f"Herkunft {act['c']} {bonus:+.2f}")

    if not bio:
        why.append("keine Biografie im Line-up - nur Genre und Land bekannt")

    key, label = tier_of(score)
    return {
        "id": act["id"], "name": act["n"], "score": round(score, 2),
        "tier": key, "tier_label": label,
        "profile_hit": in_profile,
        "profile_refs": refs, "neighbour_refs": near, "off_scene_refs": off,
        "style_pos": [t for t, _ in pos], "style_neg": [t for t, _ in neg],
        "genres": names or ["ohne Angabe"], "country": act.get("c"),
        "has_bio": bool(bio), "spotify": act.get("sp"), "why": why,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=str(LABELS))
    ap.add_argument("--profile", default=str(PROFILE))
    ap.add_argument("--lineup", default=str(LINEUP))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--top", type=int, default=30,
                    help="wie viele Acts der Bericht je Richtung zeigt")
    args = ap.parse_args()

    if not Path(args.labels).exists():
        sys.exit(f"Keine Labels: {args.labels}")
    data = json.loads(Path(args.lineup).read_text(encoding="utf-8"))
    acts, genres = data["acts"], data["genres"]
    by_name = {fold(a["n"]): a for a in acts}

    profile = load_rows(Path(args.profile)) if Path(args.profile).exists() else []
    profile = [r["artist"].strip() for r in profile if r.get("artist")]
    profile_folded = {fold(p) for p in profile}

    # ---------- 1. Labels auf Acts abbilden ----------
    verdict: dict[int, str] = {}
    unresolved, conflicts = [], []
    removed_rows: list[str] = []          # Zeilen aus der Playlist, die weg sind

    for row in load_rows(Path(args.labels)):
        raw, label = row["artist"].strip(), row["label"].strip()
        if label == "reject":
            removed_rows.append(raw)
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
    base_like = len(likes) / max(1, len(verdict))

    # In einer entfernten Zeile MITgenannt, aber nicht selbst bewertet:
    # z. B. "Mine, LIONSTORM". Das ist ein Hinweis, keine Bewertung - wer
    # von beiden gemeint war, steht nicht in den Daten.
    mentioned: dict[int, list[str]] = {}
    for raw in removed_rows:
        if fold(raw) in by_name:
            continue
        for part in re.split(r"\s*(?:,|&| and )\s*", raw):
            act = by_name.get(fold(part))
            if act and act["id"] not in verdict:
                mentioned.setdefault(act["id"], []).append(raw)

    print("=== Abgleich ===")
    print(f"  Line-up:            {len(acts)} Acts")
    print(f"  zugeordnet:         {len(verdict)}  ({len(likes)} like, "
          f"{len(rejects)} aus der Playlist entfernt)")
    print(f"  nicht zugeordnet:   {len(unresolved)}")
    print(f"  noch offen:         {len(acts) - len(verdict)}")
    print(f"  in entfernter Zeile mitgenannt: {len(mentioned)}")
    for c in conflicts:
        print(f"  WIDERSPRUCH: {c['artist']}: {c['labels']}")

    # ---------- 2. Warum das grobe Genre nicht taugt ----------
    gl, gr = Counter(), Counter()
    for a in likes:
        for i in a["g"]:
            gl[i] += 1
    for a in rejects:
        for i in a["g"]:
            gr[i] += 1

    print(f"\n=== Warum nicht nach Genre? (Grundrate: {base_like:.0%} Likes) ===")
    print("  Genre                bewertet  like   Like-Rate  gegen Grundrate")
    for i, name in enumerate(genres):
        judged = gl[i] + gr[i]
        if not judged:
            continue
        rate = gl[i] / judged
        mark = ("spricht dafuer" if rate > base_like * 1.6 and judged >= 4 else
                "spricht dagegen" if rate == 0 and judged >= 4 else
                "nicht unterscheidbar")
        print(f"  {name:20} {judged:>7}  {gl[i]:>4}   {rate:>7.0%}   {mark}")
    print("  Pop steht bei 'nicht unterscheidbar' - genau deshalb wird Pop")
    print("  hier nicht mehr abgewertet.")

    # ---------- 3. Alle Acts bewerten ----------
    scored = [score_act(a, genres, profile, profile_folded) for a in acts]
    for s in scored:
        if s["id"] in verdict:
            s["status"] = ("bereits geliked" if verdict[s["id"]] == "like"
                           else "bereits in Playlist entfernt")
        elif s["id"] in mentioned:
            s["status"] = ("in entfernter Playlist-Zeile mitgenannt: "
                           + "; ".join(mentioned[s["id"]]))
        else:
            s["status"] = "offen"
    scored.sort(key=lambda s: (-s["score"], s["name"]))
    open_scored = [s for s in scored if s["status"] == "offen"]

    # ---------- 4. Selbstpruefung am eigenen Urteil ----------
    print("\n=== Selbstpruefung: findet das Modell die 5 Likes wieder? ===")
    ranks = {s["id"]: n for n, s in enumerate(scored, 1)}
    for a in likes:
        s = next(x for x in scored if x["id"] == a["id"])
        print(f"  Platz {ranks[a['id']]:>3}/{len(scored)}  {s['score']:>6.2f}  "
              f"{s['tier']}  {a['n']}")
    rej_scores = [x["score"] for x in scored if verdict.get(x["id"]) == "reject"]
    like_scores = [x["score"] for x in scored if verdict.get(x["id"]) == "like"]
    if rej_scores and like_scores:
        med_r = sorted(rej_scores)[len(rej_scores) // 2]
        med_l = sorted(like_scores)[len(like_scores) // 2]
        print(f"  Median entfernt: {med_r:+.2f}   Median geliked: {med_l:+.2f}")
        blind = [a["n"] for a in likes
                 if not (next(x for x in scored if x["id"] == a["id"])["has_bio"])]
        if blind:
            print(f"  Ohne Biografie im Line-up, deshalb blind: "
                  f"{', '.join(blind)}.")
        print("  Fuenf Likes, davon " + str(len(blind)) + " ohne Bio - das ist")
        print("  ein Plausibilitaetscheck, keine Validierung.")

    # ---------- 5. Bericht ----------
    counts = Counter(s["tier"] for s in open_scored)
    nobio = Counter(s["tier"] for s in open_scored if not s["has_bio"])
    print(f"\n=== {len(open_scored)} noch offene Acts nach Stufen ===")
    for limit, key, label in TIERS:
        extra = f"   davon {nobio[key]} ohne Bio" if nobio[key] else ""
        print(f"  {key}  {counts[key]:>3}  {label}{extra}")

    print(f"\n=== Die {args.top} aussichtsreichsten offenen Acts ===")
    for s in open_scored[:args.top]:
        print(f"  {s['tier']} {s['score']:>5.2f}  {s['name'][:26]:28}"
              f"{(s['country'] or '--'):3} {', '.join(s['genres'])[:24]}")
        for line in s["why"]:
            print(f"          {line}")

    print(f"\n=== Am ehesten aussortierbar ({args.top}) ===")
    for s in reversed(open_scored[-args.top:]):
        print(f"  {s['tier']} {s['score']:>6.2f}  {s['name'][:26]:28}"
              f"{(s['country'] or '--'):3} {'; '.join(s['why'])[:70]}")

    if mentioned:
        print("\n=== In einer entfernten Playlist-Zeile mitgenannt ===")
        print("  Nicht als 'entfernt' gewertet: bei Kollaborationen steht nicht")
        print("  in den Daten, wegen wem die Zeile weg ist.")
        for s in scored:
            if s["id"] in mentioned:
                print(f"  {s['tier']} {s['score']:>6.2f}  {s['name'][:26]:28}"
                      f"{s['status'][:60]}")

    if unresolved:
        print("\n=== Nicht zugeordnet (bitte selbst entscheiden) ===")
        for u in unresolved:
            print(f"  #{str(u['nr']):>4} {u['label']:6} {u['artist'][:44]:46}"
                  f"{u['reason']}")

    # ---------- 6. Ausgabe fuer die App ----------
    # Die App zeigt pro Act einen Hinweis. Was schon in der Playlist
    # entschieden wurde, ist dort wertvoller als eine Schaetzung - denn die
    # App weiss nichts von Spotify.
    hints = {}
    for s in scored:
        key, reasons = str(s["id"]), "; ".join(s["why"][:2])
        if s["status"] == "bereits geliked":
            hints[key] = {"v": "ja", "why": "in der offiziellen Playlist geliked"}
        elif s["status"] == "bereits in Playlist entfernt":
            hints[key] = {"v": "nein", "why": "bereits in Playlist entfernt"}
        elif s["status"].startswith("in entfernter"):
            hints[key] = {"v": "nein" if s["tier"] == "E" else "ja",
                          "why": "in einer entfernten Playlist-Zeile mitgenannt "
                                 "(unklar, wegen wem) - " + reasons}
        elif s["tier"] in ("A", "B"):
            hints[key] = {"v": "ja", "why": reasons}
        elif s["tier"] == "E":
            hints[key] = {"v": "nein", "why": reasons}

    payload = {
        "format": 2,
        "generated_from": {"labels": args.labels,
                           "lineup": data.get("generated_at")},
        "method": ("Stilmerkmale aus den Biografien plus eigenes Hoerprofil. "
                   "Die 16 groben Genres wirken nur noch als schwacher "
                   "Ausschlag, weil sie in den Bewertungen kaum trennen. "
                   "Pop wird ausdruecklich nicht abgewertet."),
        "base_like_rate": round(base_like, 3),
        "tiers": {k: l for _, k, l in TIERS},
        "known": {str(a["id"]): verdict[a["id"]] for a in acts
                  if a["id"] in verdict},
        "status": {str(s["id"]): s["status"] for s in scored},
        "acts": [{k: v for k, v in s.items() if k != "spotify"} for s in scored],
        "hints": hints,
        # Rueckwaertskompatibel fuer aeltere App-Staende
        "suggested": {str(s["id"]): s["score"] for s in scored},
        "profile_hits": [s["id"] for s in scored if s["profile_hit"]],
        "bio_refs": {str(s["id"]): s["profile_refs"] for s in scored
                     if s["profile_refs"]},
        "unresolved": unresolved,
        "conflicts": conflicts,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"\n{args.out} geschrieben "
          f"({Path(args.out).stat().st_size // 1024} KB)")

    print("\n=== Wie belastbar ist das? ===")
    print(f"  Stark: die {len(rejects)} entfernten Acts. Hip-Hop/Rap, Electronic")
    print("  und Heavy Metal sind restlos gestrichen - das ist ein echtes Signal.")
    print(f"  Schwach: nur {len(likes)} Likes. Die Positiv-Seite kommt daher aus")
    print(f"  {len(profile)} Kuenstlern im Hoerprofil und aus Stilbegriffen, die")
    print("  ich den Profil-Clustern zugeordnet habe. Diese Zuordnung ist mein")
    print("  Urteil (taste_vocab.py), keine Rechnung - bei jedem Act steht")
    print("  deshalb dabei, welcher Begriff gegriffen hat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
