#!/usr/bin/env python3
"""Lokaler Server: sendet die echten _headers UND bildet die Team-API nach.

Zwei Gruende:

1. Ohne die Header aus _headers testet man die App ohne CSP - und merkt erst
   auf der echten Domain, dass die Content-Security-Policy etwas blockiert.
2. Die Team-API (/api/team/...) wird hier im Speicher nachgebildet, mit
   derselben Semantik wie worker/index.js. So laesst sich der komplette
   Abgleich zwischen zwei "Geraeten" im Browsertest pruefen, ohne Cloudflare.

Der Speicher ist absichtlich fluechtig - jeder Neustart faengt leer an.

    python3 web/serve_local.py        # http://127.0.0.1:8898
"""
import functools
import hashlib
import http.server
import json
import os
import pathlib
import re
import sys
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8898


def parse_headers(path: pathlib.Path):
    """Liest das _headers-Format von Cloudflare Pages."""
    rules, block = [], None
    if not path.exists():
        return rules
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            block = (line.strip(), [])
            rules.append(block)
        elif block:
            key, _, value = line.strip().partition(":")
            block[1].append((key.strip(), value.strip()))
    return rules


RULES = parse_headers(ROOT / "_headers")


# --- Team-API im Speicher, Semantik wie worker/index.js ---
TEAM_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
MEMBER_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
MAX_BODY = 128 * 1024
MAX_MEMBERS = 8
AUTH: dict[str, str] = {}
DOCS: dict[str, dict] = {}

# Cloudflare KV ist eventual consistent, und zwar UNGLEICHMAESSIG. Gegen die
# echte API gemessen:
#   ein NEUER Schluessel taucht im Verzeichnis-Listing erst nach ~30 s auf
#   eine AENDERUNG an einem bestehenden Schluessel ist nach ~1 s da
# Ohne diese Nachbildung war der Team-Test gruen, waehrend es in Wirklichkeit
# aussah, als komme nichts an - der Mock lieferte alles sofort.
# Mit RBF_KV_LAG=0 laesst sich die Verzoegerung fuer schnelle Testlaeufe
# abschalten.
KV_FIRST_SEEN_LAG = float(os.environ.get("RBF_KV_LAG", "30"))
FIRST_WRITE: dict[tuple, float] = {}


# Der Freibetrag von Workers KV hat drei getrennte Tagesdeckel: 100.000
# Lesevorgaenge, 1.000 Schreibvorgaenge, 1.000 Verzeichnis-Abfragen. Der
# kleinste bindet - und genau den hat die App aufgebraucht, weil jeder
# Abgleich ein list() ausgeloest hat. Hier wird mitgezaehlt, damit sich das
# Budget messen laesst statt schaetzen: GET /api/kvops liefert die Zaehler.
KV_OPS = {"read": 0, "write": 0, "list": 0, "delete": 0}


def visible_members(team: str) -> list[dict]:
    """Was ein Listing JETZT zeigen wuerde."""
    now = time.monotonic()
    out = []
    for (t, mid), doc in DOCS.items():
        if t != team:
            continue
        born = FIRST_WRITE.get((t, mid), 0.0)
        if now - born < KV_FIRST_SEEN_LAG:
            continue                      # Schluessel noch nicht im Verzeichnis
        out.append({"id": mid, **doc})
    return out


class Handler(http.server.SimpleHTTPRequestHandler):
    # ---------- Team-API ----------

    def _api_parts(self):
        path = self.path.split("?")[0].strip("/").split("/")
        if len(path) >= 3 and path[0] == "api" and path[1] == "team":
            return path[2], (path[3] if len(path) > 3 else None)
        return None, None

    def _reply(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self, team):
        KV_OPS["read"] += 1          # der Worker liest hier auth:{team}
        token = self.headers.get("X-Team-Token") or ""
        if len(token) < 20:
            return "missing"
        digest = hashlib.sha256(token.encode()).hexdigest()
        if team not in AUTH:
            AUTH[team] = digest
            return "created"
        return "ok" if AUTH[team] == digest else "denied"

    def _team_request(self):
        """True, wenn die Anfrage von der Team-API beantwortet wurde."""
        if self.path.split("?")[0] == "/api/kvops":
            if self.command == "DELETE":
                for k in KV_OPS:
                    KV_OPS[k] = 0
            self._reply(dict(KV_OPS))
            return True
        team, member = self._api_parts()
        if team is None:
            if self.path.startswith("/api/"):
                self._reply({"error": "not_found"}, 404)
                return True
            return False
        if not TEAM_RE.match(team):
            self._reply({"error": "bad_team"}, 400); return True
        if member is not None and not MEMBER_RE.match(member):
            self._reply({"error": "bad_member"}, 400); return True

        state = self._auth(team)
        if state == "missing":
            self._reply({"error": "token_required"}, 401); return True
        if state == "denied":
            self._reply({"error": "token_invalid"}, 403); return True

        if self.command == "GET" and member is None:
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            want = [m for m in (q.get("members", [""])[0]).split(",") if m]
            if want:
                if not all(MEMBER_RE.match(m) for m in want):
                    self._reply({"error": "bad_member"}, 400); return True
                out = []
                for mid in want[:MAX_MEMBERS]:
                    KV_OPS["read"] += 1
                    doc = DOCS.get((team, mid))
                    if doc is None:
                        continue
                    born = FIRST_WRITE.get((team, mid), 0.0)
                    if time.monotonic() - born < KV_FIRST_SEEN_LAG:
                        continue
                    out.append({"id": mid, **doc})
                self._reply({"team": team, "members": out, "listed": False})
                return True
            KV_OPS["list"] += 1
            members = visible_members(team)
            KV_OPS["read"] += len(members)
            self._reply({"team": team, "members": members, "listed": True})
            return True

        if self.command == "PUT" and member:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._reply({"error": "too_large"}, 413); return True
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._reply({"error": "bad_json"}, 400); return True
            if not isinstance(payload.get("iv"), str) or not isinstance(payload.get("ct"), str):
                self._reply({"error": "bad_payload"}, 400); return True
            current = [k for k in DOCS if k[0] == team]
            if (team, member) not in DOCS and len(current) >= MAX_MEMBERS:
                self._reply({"error": "team_full", "max": MAX_MEMBERS}, 409); return True
            KV_OPS["read"] += 1                       # gibt es das Dokument schon?
            if (team, member) not in DOCS:
                KV_OPS["list"] += 1                     # nur dann das Verzeichnis
            KV_OPS["write"] += 1
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            FIRST_WRITE.setdefault((team, member), time.monotonic())
            DOCS[(team, member)] = {"iv": payload["iv"], "ct": payload["ct"],
                                    "updated": stamp}
            self._reply({"ok": True, "updated": stamp}); return True

        if self.command == "DELETE" and member:
            KV_OPS["delete"] += 1
            DOCS.pop((team, member), None)
            FIRST_WRITE.pop((team, member), None)
            self._reply({"ok": True}); return True

        self._reply({"error": "method_not_allowed"}, 405); return True

    def do_GET(self):
        if not self._team_request():
            super().do_GET()

    def do_PUT(self):
        self._team_request()

    def do_DELETE(self):
        self._team_request()

    # ---------- statische Dateien ----------

    def end_headers(self):
        path = self.path.split("?")[0]
        for pattern, headers in RULES:
            if re.fullmatch(pattern.replace("*", ".*"), path):
                for key, value in headers:
                    self.send_header(key, value)
        super().end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"http://127.0.0.1:{PORT}  ({len(RULES)} Header-Regeln aus _headers)")
    http.server.HTTPServer(("127.0.0.1", PORT),
                           functools.partial(Handler, directory=str(ROOT))).serve_forever()
