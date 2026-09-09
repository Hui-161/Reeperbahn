"""Minimaler GraphQL-Client fuer die Reeperbahn-API."""
import json, sys, time, urllib.error, urllib.request

ENDPOINT = "https://www.reeperbahnfestival.com/graphql"
UA = "rbf-lineup/0.1 (persoenliches Projekt)"
_last = [0.0]

DELAY = 1.0


def unwrap(data: dict) -> dict:
    """Die Antwort auspacken - und eine Teilantwort nicht wegwerfen.

    GraphQL beantwortet einen Feldfehler nicht mit einem Totalausfall: das
    betroffene Feld wird auf null gesetzt, der Rest kommt normal mit, und
    daneben steht ein Eintrag in "errors". Vorher hat jeder solche Eintrag
    hier den ganzen Abruf abgebrochen. Am 9. September 2026 lief die
    naechtliche Aktualisierung deshalb ins Leere, weil der Server bei genau
    EINEM Act ("ATZUR") ueber sein eigenes Spotify-Feld stolperte - 393
    Acts verworfen wegen eines fehlenden Links.

    Abgebrochen wird nur noch, wenn nichts Brauchbares zurueckkommt: kein
    data-Block oder darin ausschliesslich null. Feldfehler werden gemeldet,
    damit sie nicht stillschweigend zur Gewohnheit werden.
    """
    errors = data.get("errors") or []
    payload = data.get("data")
    usable = isinstance(payload, dict) and any(v is not None for v in payload.values())
    if not usable:
        raise RuntimeError(json.dumps(errors, ensure_ascii=False)[:1500] if errors
                           else "Antwort ohne verwertbare Daten")
    for e in errors[:10]:
        print(f"Teilantwort: {e.get('message')} bei {'.'.join(str(p) for p in (e.get('path') or []))}",
              file=sys.stderr)
    if len(errors) > 10:
        print(f"Teilantwort: und {len(errors) - 10} weitere Feldfehler", file=sys.stderr)
    return payload


def query(q, variables=None, delay=None, timeout=90):
    delay = DELAY if delay is None else delay
    wait = delay - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    payload = json.dumps({"query": q, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        ENDPOINT, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": UA, "Accept": "application/json"},
    )
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(2 ** attempt)      # 1s, 2s, 4s, 8s
    else:
        raise RuntimeError(f"Endpunkt antwortet nicht ({last})")
    return unwrap(data)


def selftest() -> int:
    """Prueft das Auspacken der Antwort - ohne Netz."""
    fails = []

    def check(name, cond, extra=""):
        print(("  ok    " if cond else "  FEHL ") + name + (f"  {extra}" if extra else ""))
        if not cond:
            fails.append(name)

    def raises(d):
        try:
            unwrap(d)
            return False
        except RuntimeError:
            return True

    ok = {"data": {"entityQuery": {"items": [1, 2]}}}
    check("Saubere Antwort kommt durch", unwrap(ok)["entityQuery"]["items"] == [1, 2])

    # Der echte Fall vom 9.9.2026: ein Feld eines Acts, Rest vollstaendig.
    teil = {"data": {"entityQuery": {"items": [{"title": "ATZUR", "fieldSpotify": {"uri": None}}]}},
            "errors": [{"message": "Internal server error",
                        "path": ["entityQuery", "items", 15, "fieldSpotify", "uri"]}]}
    got = unwrap(teil)
    check("Teilantwort wird verwendet, nicht verworfen",
          got["entityQuery"]["items"][0]["title"] == "ATZUR")

    check("Fehler ohne Daten bricht ab",
          raises({"errors": [{"message": "Type not found"}]}))
    check("data mit ausschliesslich null bricht ab",
          raises({"data": {"entityQuery": None},
                  "errors": [{"message": "kaputt"}]}))
    check("Antwort ohne data bricht ab", raises({}))

    print("selftest: " + ("alle Pruefungen bestanden" if not fails
                          else f"FEHLGESCHLAGEN: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else 0)
