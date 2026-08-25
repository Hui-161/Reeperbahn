"""Minimaler GraphQL-Client fuer die Reeperbahn-API."""
import json, time, urllib.error, urllib.request

ENDPOINT = "https://www.reeperbahnfestival.com/graphql"
UA = "rbf-lineup/0.1 (persoenliches Projekt)"
_last = [0.0]

DELAY = 1.0

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
    if "errors" in data:
        raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False)[:1500])
    return data["data"]
