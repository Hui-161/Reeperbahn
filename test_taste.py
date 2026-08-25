#!/usr/bin/env python3
"""Tests fuer die Bewertungslogik in taste.py.

Laeuft ohne die persoenlichen CSV-Dateien - geprueft werden die reinen
Funktionen an erfundenen Bios. Genau die Faelle, an denen ich mich beim
Bauen vertan habe, stehen hier drin.

    python3 test_taste.py
"""

from __future__ import annotations

import sys

import taste
from taste_vocab import MICRO_NEG, MICRO_POS

FAILED: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FEHL  {name}\n        erwartet: {want!r}\n        bekommen: {got!r}")
        FAILED.append(name)


def act(name="Test", bio="", genres=(), country=None, aid=1) -> dict:
    return {"id": aid, "n": name, "bio": bio, "g": list(genres), "c": country}


GENRES = ["Alternative", "Electronic/DJ", "Electronic/Live", "Heavy Metal",
          "Hip-Hop/Rap", "Indie", "Pop", "Punk", "Rock"]


def score(bio, genres=(), country=None, profile=()):
    a = act(bio=bio, genres=[GENRES.index(g) for g in genres], country=country)
    return taste.score_act(a, GENRES, list(profile),
                           {taste.fold(p) for p in profile})


def main() -> int:
    print("== Normalisierung ==")
    # Bindestriche muessen zu Leerzeichen werden, sonst findet "post punk"
    # in "Post-Punk-Trio" nichts.
    check("flat trennt Bindestriche", taste.flat("Post-Punk-Trio"),
          " post punk trio ")
    check("fold entfernt Diakritika", taste.fold("Malummí"), "malummi")
    check("fold entfernt Satzzeichen", taste.fold("Fontaines D.C."),
          "fontaines dc")

    print("\n== Stilbegriffe ==")
    check("Bindestrich-Schreibweise",
          [t for t, _ in taste.term_hits("Ein Post-Punk-Trio", MICRO_POS)],
          ["post punk"])
    check("zusammengeschrieben",
          [t for t, _ in taste.term_hits("reiner Postpunk", MICRO_POS)],
          ["post punk", "postpunk"])
    # Wortgrenzen: sonst schlaegt "rap" in "grapefruit" an und "dub" in
    # "dubios" - das war der Grund fuer die Grenzen im Muster.
    check("keine Teilwort-Treffer",
          taste.term_hits("Ein grapefruitfarbenes, dubioses Album", MICRO_NEG),
          [])
    check("Negativbegriff greift",
          [t for t, _ in taste.term_hits("harter Deutschrap", MICRO_NEG)],
          ["deutschrap"])

    print("\n== Referenzkuenstler ==")
    # Stilvergleich zaehlt voll, Support-Slot nur halb.
    check("Stilvergleich ist kein Support",
          taste.name_hits("Anklaenge an Arctic Monkeys.", ["Arctic Monkeys"]),
          [("Arctic Monkeys", False)])
    check("Support wird erkannt",
          taste.name_hits("Sie eröffnete Konzerte für Franz Ferdinand.",
                          ["Franz Ferdinand"]),
          [("Franz Ferdinand", True)])
    # Der Fehler, den ich zuerst gemacht habe: ein Zeichenfenster um den
    # Namen holt das "Support" aus dem naechsten Absatz herein.
    check("Support aus anderem Satz zaehlt nicht",
          taste.name_hits("Anklaenge an Arctic Monkeys. "
                          "Mit Support-Auftritten fuer andere Bands.",
                          ["Arctic Monkeys"]),
          [("Arctic Monkeys", False)])
    # Abkuerzungspunkte duerfen den Satz nicht zerlegen.
    check("Punkt in Abkuerzung trennt nicht",
          taste.name_hits("klingt wie Fontaines D.C. auf Speed",
                          ["Fontaines D.C."]),
          [("Fontaines D.C.", False)])
    check("Stopword-Name wird ignoriert",
          taste.name_hits("Aus der Asche wie ein Phoenix.", ["Phoenix"]), [])
    check("zu kurzer Name wird ignoriert",
          taste.name_hits("Wir moegen Aze sehr.", ["Aze"]), [])

    print("\n== Gewichtung ==")
    # Der Punkt, um den es dem Nutzer ging: Pop darf nicht abwerten.
    pop = score("Eingaengige Songs.", ("Pop",))
    plain = score("Eingaengige Songs.")
    check("Pop wertet nicht ab", pop["score"], plain["score"])
    # Indie-Pop dagegen ist ein Positivsignal - das steht selbst im Profil.
    check("Indie-Pop ist positiv",
          score("Verspielter Indie-Pop.", ("Pop", "Indie"))["score"] > pop["score"],
          True)
    # Hip-Hop: 14 von 14 bewerteten Acts aussortiert.
    check("Hip-Hop wertet ab",
          score("Ein Rapper aus Berlin.", ("Hip-Hop/Rap",))["tier"], "E")
    # Doppelzaehlung: The Strokes steht im Profil UND in den Nachbarn.
    both = score("Anklaenge an The Strokes.", profile=("The Strokes",))
    check("Profilname zaehlt nur einmal", both["neighbour_refs"], [])
    check("Profilname zaehlt als Profiltreffer", both["profile_refs"],
          ["The Strokes"])
    # Support-Slot muss weniger wiegen als ein Stilvergleich.
    styled = score("Anklaenge an Interpol.", profile=("Interpol",))
    supported = score("Eröffnete Konzerte für Interpol.",
                      profile=("Interpol",))
    check("Support wiegt weniger", styled["score"] > supported["score"], True)

    print("\n== Stufen ==")
    check("hohe Punktzahl ergibt A", taste.tier_of(9.0)[0], "A")
    check("Null ergibt D", taste.tier_of(0.0)[0], "D")
    check("negativ ergibt E", taste.tier_of(-2.0)[0], "E")
    # Ohne Bio kann das Modell nichts wissen - das muss dranstehen.
    nobio = score("", ("Indie",))
    check("fehlende Bio wird benannt",
          any("keine Biografie" in w for w in nobio["why"]), True)

    print()
    if FAILED:
        print(f"{len(FAILED)} Pruefung(en) fehlgeschlagen: {', '.join(FAILED)}")
        return 1
    print("alle Pruefungen bestanden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
