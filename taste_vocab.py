#!/usr/bin/env python3
"""Merkmalslisten fuer taste.py - getrennt gehalten, weil hier zweierlei steckt.

DATEN (aus taste/labels.csv und taste/profile.csv abgeleitet):
  HARD_NEGATIVE_GENRES - Kategorien, in denen restlos alles aussortiert wurde.

URTEIL (von mir zugeordnet, nicht aus den Bewertungen berechnet):
  MICRO_POS / MICRO_NEG  - Stilbegriffe, gegen die Bios geprueft werden.
  NEIGHBOURS / OFF_SCENE - Referenzkuenstler, die im Hoerprofil NICHT stehen,
                           aber im Umfeld der Profil-Cluster liegen.

Die Trennung ist wichtig: Was aus Daten kommt, ist nachpruefbar. Was Urteil
ist, kann falsch sein - deshalb nennt taste.py bei jedem Act, welcher Begriff
gegriffen hat, statt nur eine Zahl auszugeben.

Grundlage des Urteils sind die Cluster, die im privaten Hoerprofil
(taste/profile.csv, nicht eingecheckt) erkennbar sind. Die Cluster selbst
sind hier genannt, die Kuenstlernamen dahinter bewusst nicht - dieses
Repository ist oeffentlich, das Hoerprofil ist persoenlich:

  Gitarren-Indie und Post-Punk-Revival, britisch wie australisch
  Deutschsprachiger Indie
  Alternative und Stoner Rock
  Dream Pop, verhallte Gitarren
  Retro-Soul und Funk mit Band
  Bedroom- und Elektro-Pop
  Reggae und Dub
  Folk mit Songwriter-Schlagseite

Die Listen NEIGHBOURS und OFF_SCENE nennen dagegen nur allgemein bekannte
Bands als Peilmarken fuer diese Cluster - kein Auszug aus dem Profil.
"""

from __future__ import annotations

# ---------------------------------------------------------------- aus Daten
# 0 Likes bei diesen Kategorien, und genug bewertete Acts, damit das nicht
# nur die Grundrate ist. Zahlen stehen in taste.py im Bericht.
HARD_NEGATIVE_GENRES = {
    "Hip-Hop/Rap": 14,
    "Electronic/Live": 6,
    "Heavy Metal": 4,
    "Electronic/DJ": 2,
}

# Genres mit Like-Rate ueber der Grundrate. Bewusst kleine Gewichte: die
# 16 groben Genres trennen kaum (Indie+Rock steht bei like UND reject).
GENRE_TIEBREAK = {
    "Punk": 0.75,
    "Rock": 0.4,
    "Indie": 0.4,
    "Alternative": 0.3,
    "Funk": 0.3,
    "Folk": 0.2,
    # Pop steht hier absichtlich NICHT: 1 like / 19 reject bei einer Grundrate
    # von 8 % Likes ist statistisch nicht von Zufall zu unterscheiden, und das
    # eigene Hoerprofil ist voll von Pop (Indie-Pop, Bedroom-Pop, Power-Pop).
}

# Die Likes verteilen sich auf GB, AU und US. Schwaches Signal bei fuenf
# Datenpunkten, deshalb kleines Gewicht - und kein Minus fuer DE, weil das
# Hoerprofil voller deutschsprachiger Bands ist.
COUNTRY_BONUS = {"GB": 0.5, "AU": 0.5, "US": 0.25, "IE": 0.4, "SE": 0.25}

# ---------------------------------------------------------------- Urteil
# Stilbegriffe, die in den 197 Bios tatsaechlich vorkommen (gezaehlt, nicht
# erfunden) und zu den Profil-Clustern passen. Punkte pro Treffer.
MICRO_POS: dict[str, float] = {
    "post punk": 2.0, "postpunk": 2.0, "protopunk": 1.5, "no wave": 1.0,
    "new wave": 1.5, "nowave": 1.0, "cold wave": 1.5, "coldwave": 1.5,
    "shoegaze": 2.0, "dream pop": 2.0, "dreampop": 2.0,
    "krautrock": 2.0, "psychedelic": 1.0, "psychedelisch": 1.0,
    "garage rock": 2.0, "garagenrock": 2.0, "garage": 1.0,
    "indie rock": 1.5, "indierock": 1.5, "indie pop": 1.0, "indiepop": 1.0,
    "alternative rock": 1.25, "alternativerock": 1.25,
    "art rock": 1.0, "art pop": 0.75, "artpop": 0.75,
    "britpop": 1.5, "jangle": 1.5, "jangly": 1.5,
    "power pop": 1.5, "powerpop": 1.5,
    "dance punk": 1.5, "dancepunk": 1.5, "indie punk": 1.5, "indiepunk": 1.5,
    "punkrock": 1.0, "punk rock": 1.0, "riot grrrl": 1.25,
    "noise rock": 1.0, "math rock": 1.0, "post rock": 0.75,
    "grunge": 1.5, "stoner": 1.5, "desert rock": 1.5,
    "surf": 1.0, "slacker": 1.0, "lo fi": 0.75, "lofi": 0.75,
    "bedroom pop": 1.25, "bedroompop": 1.25,
    "gitarrenmusik": 1.0, "gitarrenpop": 1.25, "gitarrenrock": 1.5,
    "vintage soul": 1.25, "retro soul": 1.25, "northern soul": 1.0,
    "reggae": 1.0, "dub": 0.75, "ska": 0.5,
    "singer songwriter": 0.0,   # 0/2 bewertet - zu wenig, bleibt neutral
}

MICRO_NEG: dict[str, float] = {
    # deckungsgleich mit den 14/14 aussortierten Hip-Hop-Acts
    "hip hop": -2.5, "hiphop": -2.5, "deutschrap": -3.0, "cloud rap": -2.5,
    "trap": -2.0, "drill": -2.5, "boom bap": -2.0, "rapper": -2.0,
    "rapperin": -2.0, "battlerap": -2.5, "rapcore": -2.0,
    # deckungsgleich mit den 4/4 aussortierten Heavy-Metal-Acts
    "deathcore": -3.0, "metalcore": -3.0, "death metal": -3.0,
    "black metal": -3.0, "post hardcore": -2.0, "hardcore": -2.0,
    "breakdowns": -2.0, "growls": -2.0, "screamo": -2.0,
    # deckungsgleich mit den 8/8 aussortierten Electronic-Acts
    "techno": -2.0, "deep house": -2.0, "tech house": -2.0,
    "french house": -1.5, "house music": -1.5, "housebeats": -1.5,
    "dubstep": -2.0, "edm": -2.0, "hyperpop": -2.5, "clubmusik": -1.5,
    "amapiano": -1.5, "reggaeton": -1.5, "afrobeats": -1.5,
    "neo soul": -1.0, "rnb": -1.0, "contemporary r n b": -1.0,
    "schlager": -2.0, "musical": -1.5, "chanson": -1.0, "oper": -1.0,
}

# Kuenstler, die NICHT im Hoerprofil stehen, aber im Umfeld seiner Cluster.
# Nennt eine Bio einen davon, beschreibt sie die richtige Ecke.
NEIGHBOURS = [
    # Post-Punk-Revival und britischer Gitarren-Indie
    "The Strokes", "Arctic Monkeys", "The Libertines", "Fontaines D.C.",
    "Idles", "Shame", "Yard Act", "Squid", "Dry Cleaning", "Sports Team",
    "Wet Leg", "Wolf Alice", "The Last Dinner Party", "Parquet Courts",
    "Two Door Cinema Club", "Foals", "Editors", "White Lies",
    "Everything Everything", "Blur", "Oasis", "Pulp", "Suede", "Supergrass",
    "The Smiths", "New Order", "Joy Division", "The Cure", "Television",
    "Talking Heads", "Iggy Pop", "The Velvet Underground", "Sonic Youth",
    "Pixies", "The Breeders", "Pavement", "Kings of Leon", "The Killers",
    "The Vaccines", "Peace", "Bombay Bicycle Club",
    # Australien
    "Amyl and the Sniffers", "Tame Impala", "Pond", "King Gizzard",
    "Courtney Barnett", "Royel Otis", "Skegss", "Spacey Jane",
    # Shoegaze, Dream Pop
    "My Bloody Valentine", "Slowdive", "Ride", "Cocteau Twins",
    "Beach House", "Alvvays", "Mazzy Star", "The Jesus and Mary Chain",
    # Alternative, Stoner, Grunge
    "Queens of the Stone Age", "Nirvana", "Pearl Jam", "Soundgarden",
    "Kyuss", "Screaming Trees", "Alice in Chains",
    # Songwriter am Rand des Profils
    "Big Thief", "Alex G", "Phoebe Bridgers", "PJ Harvey", "Fleetwood Mac",
    "Laura Marling", "Fleet Foxes", "Bon Iver", "Sufjan Stevens",
    # Retro-Soul
    "Black Pumas", "Leon Bridges", "Curtis Harding", "Michael Kiwanuka",
]

# Nennt eine Bio diese, geht es sehr wahrscheinlich in eine andere Richtung.
OFF_SCENE = [
    "Drake", "Travis Scott", "Kendrick Lamar", "Playboi Carti", "Lil Baby",
    "Central Cee", "Ufo361", "Apache 207", "Capital Bra", "Bausa", "Luciano",
    "Charli XCX", "SOPHIE", "100 gecs", "PinkPantheress",
    "Skrillex", "Fred again", "Peggy Gou", "Boris Brejcha", "Solomun",
    "Slipknot", "Bring Me The Horizon", "Architects", "Knocked Loose",
    "Ariana Grande", "Dua Lipa", "Sabrina Carpenter", "Taylor Swift",
    "SZA", "Doja Cat", "Beyoncé", "Rihanna", "The Weeknd",
]

# Namen, die als normale Woerter in deutschen oder englischen Texten
# vorkommen. Ohne diese Liste liefert die Bio-Suche Unsinn: "Traenen" ist in
# drei Bios das Wort fuer Traenen, "das Pop" ist Artikel plus Genre
# ("das Pop-Punk-Trio"), "jungle" ein Genrebegriff ("breakbeat jungle").
BIO_STOPWORDS = {
    "tranen", "das pop", "jungle", "ende", "sind", "slut", "dusted", "keir",
    "aze", "kasi", "leila", "hard life", "cool aid", "gossip", "lovehead",
    "vian", "sum one", "wallners", "nauplia", "leyya", "ennio",
    # Nachbarschaftsnamen, die auch normale Woerter sind
    "peace", "shame", "squid", "idles", "ride", "television", "pond",
    "phoenix", "oasis", "blur", "pulp", "suede", "pixies", "pavement",
}
