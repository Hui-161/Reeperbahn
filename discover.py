#!/usr/bin/env python3
"""Discovery-Probe fuer reeperbahnfestival.com.

Findet heraus, WOHER die Programmdaten kommen, damit der eigentliche Parser
gegen die echte Struktur geschrieben werden kann statt gegen eine Vermutung.
Geprueft wird auf:

  * robots.txt (wird respektiert)
  * Sitemaps
  * eine eigene JSON-/GraphQL-API (auch auf api./app.-Subdomains)
  * in HTML eingebettetes JSON (Next.js, Nuxt, Redux, Apollo)
  * JSON-LD / schema.org-Event-Daten
  * CMS-Fingerprints (WordPress, TYPO3, Drupal, Contao)

Nur Standardbibliothek - kein "pip install" noetig.
Bewusst langsam (1,5 s Pause pro Request), damit die Seite nicht belastet wird.

Nutzung:
    python3 discover.py
    python3 discover.py --out report.json
    python3 discover.py --delay 3.0
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from urllib.robotparser import RobotFileParser

BASE = "https://www.reeperbahnfestival.com"
PROGRAM_PATH = "/festivalprogramm"

# Ehrlicher, zuordenbarer User-Agent. Nicht als Browser tarnen.
UA = "rbf-lineup-probe/0.1 (persoenliches Projekt; Kontakt via Website-Impressum)"

# Kandidaten fuer eine Datenquelle. Die Liste ist absichtlich breit -
# getroffen wird davon erfahrungsgemaess hoechstens eine Handvoll.
CANDIDATE_PATHS = [
    "/wp-json/",
    "/wp-json/wp/v2/",
    "/wp-json/wp/v2/artist",
    "/wp-json/wp/v2/artists",
    "/?rest_route=/",
    "/api/",
    "/api/v1/",
    "/api/artists",
    "/api/programme",
    "/api/program",
    "/api/festivalprogramm",
    "/api/events",
    "/api/shows",
    "/graphql",
    "/index.php?type=834",          # TYPO3-typischer JSON-Ausgabetyp
    "/?type=100",
    "/sitemap.xml",
    "/sitemap_index.xml",
]

CANDIDATE_SUBDOMAINS = ["api", "app", "data", "cms", "backend", "graphql", "mobile"]

# Marker fuer in HTML eingebettetes JSON.
EMBED_MARKERS = {
    "Next.js (__NEXT_DATA__)": r'id="__NEXT_DATA__"',
    "Nuxt (__NUXT__)": r"window\.__NUXT__",
    "Redux (__INITIAL_STATE__)": r"__INITIAL_STATE__",
    "Apollo (__APOLLO_STATE__)": r"__APOLLO_STATE__",
    "Angular (ng-state)": r'id="ng-state"',
    "Svelte/SvelteKit": r"__sveltekit",
    "Astro": r"astro-island",
}

CMS_MARKERS = {
    "WordPress": r"/wp-content/|/wp-includes/|wp-json",
    "TYPO3": r"typo3temp|typo3conf|/fileadmin/",
    "Drupal": r"/sites/default/files/|Drupal\.settings",
    "Contao": r"/files/|contao",
    "Craft CMS": r"/cpresources/",
    "Statamic": r"/statamic/",
}


class Fetcher:
    """Minimaler HTTP-Client: hoeflich, mit Pause und ohne Retry-Sturm."""

    def __init__(self, delay: float = 1.5, timeout: int = 20) -> None:
        self.delay = delay
        self.timeout = timeout
        self._last = 0.0
        self.count = 0

    def get(self, url: str) -> dict:
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.count += 1

        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return {
                    "url": url,
                    "status": resp.status,
                    "headers": dict(resp.headers),
                    "body": raw,
                    "error": None,
                }
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()[:4000]
            except Exception:
                pass
            return {
                "url": url,
                "status": exc.code,
                "headers": dict(exc.headers or {}),
                "body": body,
                "error": None,
            }
        except Exception as exc:  # DNS, TLS, Timeout, ...
            return {"url": url, "status": None, "headers": {}, "body": b"", "error": str(exc)}


def looks_like_json(res: dict) -> bool:
    ctype = res["headers"].get("Content-Type", "").lower()
    if "json" in ctype:
        return True
    head = res["body"][:200].lstrip()
    return head.startswith(b"{") or head.startswith(b"[")


def probe_robots(fetch: Fetcher, base: str, report: dict) -> RobotFileParser:
    print("\n=== robots.txt ===")
    res = fetch.get(base + "/robots.txt")
    rp = RobotFileParser()
    text = res["body"].decode("utf-8", "replace")

    if res["status"] == 200 and text.strip():
        rp.parse(text.splitlines())
        print(text.strip()[:1500])
        sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)
        report["robots"] = {"status": 200, "text": text[:4000], "sitemaps": sitemaps}
        if sitemaps:
            print(f"\n-> {len(sitemaps)} Sitemap(s) deklariert: {sitemaps}")
    else:
        # Keine robots.txt = alles erlaubt.
        rp.parse([])
        print(f"keine robots.txt (Status {res['status']}, Fehler {res['error']})")
        report["robots"] = {"status": res["status"], "text": None, "sitemaps": []}
    return rp


def probe_program_page(fetch: Fetcher, url: str, report: dict) -> None:
    print(f"\n=== Programmseite: {url} ===")
    res = fetch.get(url)
    info: dict = {
        "url": url,
        "status": res["status"],
        "error": res["error"],
        "bytes": len(res["body"]),
    }

    if res["status"] != 200:
        print(f"Status {res['status']}, Fehler: {res['error']}")
        report["program_page"] = info
        return

    html = res["body"].decode("utf-8", "replace")
    interesting = ("Server", "X-Powered-By", "Content-Type", "ETag",
                   "Last-Modified", "Cache-Control", "X-Generator")
    info["headers"] = {k: v for k, v in res["headers"].items() if k in interesting}

    print(f"Status 200, {len(res['body']):,} Bytes")
    for key, value in info["headers"].items():
        print(f"  {key}: {value}")

    generator = re.search(r'<meta[^>]+name="generator"[^>]+content="([^"]+)"', html, re.I)
    if generator:
        info["generator"] = generator.group(1)
        print(f"  meta generator: {generator.group(1)}")

    info["cms"] = [name for name, pat in CMS_MARKERS.items() if re.search(pat, html, re.I)]
    if info["cms"]:
        print(f"\nCMS-Fingerprint: {', '.join(info['cms'])}")

    info["embedded"] = [name for name, pat in EMBED_MARKERS.items() if re.search(pat, html)]
    if info["embedded"]:
        print(f"Eingebettetes JSON gefunden: {', '.join(info['embedded'])}")
        print("  -> Bester Fall: Daten sind direkt im HTML, kein Scraping der Optik noetig.")

    # JSON-LD auswerten - bei Events oft schon fast das fertige Datenmodell.
    ldjson = re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I
    )
    types: list[str] = []
    for block in ldjson:
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type"):
                types.append(str(node["@type"]))
    info["jsonld_blocks"] = len(ldjson)
    info["jsonld_types"] = sorted(set(types))
    if ldjson:
        print(f"JSON-LD: {len(ldjson)} Block(s), @type: {info['jsonld_types'] or 'nicht lesbar'}")
        if any("Event" in t for t in types):
            print("  -> schema.org/Event vorhanden. Sehr gute, stabile Datenquelle.")

    # API-Aufrufe, die im Markup oder in Inline-Skripten stehen.
    urls = set(re.findall(r'["\'](/(?:api|graphql|wp-json)/[^"\'\s]{2,120})', html))
    urls |= set(re.findall(r'["\'](https?://[\w.-]+/(?:api|graphql|wp-json)/[^"\'\s]{2,120})', html))
    info["api_hints"] = sorted(urls)[:40]
    if urls:
        print(f"\nAPI-Pfade im HTML ({len(urls)}), erste 40:")
        for hint in info["api_hints"]:
            print(f"  {hint}")

    # JS-Bundles: dort steckt die API-Basis-URL oft als Konstante.
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    info["scripts"] = scripts[:30]
    print(f"\n{len(scripts)} externe Skripte (die grossen Bundles lohnen einen Blick)")

    # Kleiner Plausibilitaetstest: steht ein bekannter Act im rohen HTML?
    for probe in ("English Teacher", "Lowertown", "shame"):
        if probe.lower() in html.lower():
            info["renders_lineup_server_side"] = True
            print(f'\n"{probe}" steht im rohen HTML -> serverseitig gerendert, HTML-Parsing moeglich.')
            break
    else:
        info["renders_lineup_server_side"] = False
        print("\nKein Testkuenstler im rohen HTML -> Programm wird per JavaScript nachgeladen.")
        print("  -> Dann ist der XHR-Call im Browser-Netzwerktab die eigentliche API.")

    report["program_page"] = info


def probe_endpoints(fetch: Fetcher, base: str, rp: RobotFileParser, report: dict) -> None:
    print(f"\n=== Endpoint-Kandidaten ({len(CANDIDATE_PATHS)}) ===")
    hits = []
    for path in CANDIDATE_PATHS:
        url = base + path
        if not rp.can_fetch(UA, url):
            print(f"  robots-disallow  {path}")
            hits.append({"path": path, "skipped": "robots.txt disallow"})
            continue

        res = fetch.get(url)
        entry = {
            "path": path,
            "status": res["status"],
            "content_type": res["headers"].get("Content-Type"),
            "bytes": len(res["body"]),
            "json": looks_like_json(res),
        }
        if res["status"] == 200 and entry["json"]:
            entry["preview"] = res["body"][:600].decode("utf-8", "replace")
            print(f"  TREFFER  {path}  ({entry['bytes']:,} B, {entry['content_type']})")
        elif res["status"] == 200:
            print(f"  200 (kein JSON)  {path}")
        else:
            print(f"  {res['status'] or 'ERR'}  {path}")
        hits.append(entry)
    report["endpoints"] = hits


def probe_subdomains(fetch: Fetcher, report: dict) -> None:
    print(f"\n=== Subdomains ({len(CANDIDATE_SUBDOMAINS)}) ===")
    found = []
    for sub in CANDIDATE_SUBDOMAINS:
        host = f"{sub}.reeperbahnfestival.com"
        try:
            socket.getaddrinfo(host, 443)
        except OSError:
            print(f"  kein DNS  {host}")
            continue
        res = fetch.get(f"https://{host}/")
        print(f"  EXISTIERT  {host}  -> Status {res['status'] or 'ERR'} "
              f"{res['headers'].get('Content-Type', '')}")
        found.append({
            "host": host,
            "status": res["status"],
            "content_type": res["headers"].get("Content-Type"),
            "preview": res["body"][:400].decode("utf-8", "replace"),
        })
    report["subdomains"] = found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--program-path", default=PROGRAM_PATH)
    ap.add_argument("--delay", type=float, default=1.5, help="Pause zwischen Requests (s)")
    ap.add_argument("--out", default="discovery-report.json")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    fetch = Fetcher(delay=args.delay)
    report: dict = {"base": base, "user_agent": UA}

    print(f"Probe gegen {base}")
    print(f"User-Agent: {UA}")
    print(f"Pause: {args.delay}s pro Request")

    rp = probe_robots(fetch, base, report)
    probe_program_page(fetch, base + args.program_path, report)
    probe_endpoints(fetch, base, rp, report)
    probe_subdomains(fetch, report)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print(f"\n=== Fertig: {fetch.count} Requests ===")
    print(f"Bericht geschrieben: {args.out}")
    print("\nNaechster Schritt: diesen Bericht (oder die Konsolenausgabe) zurueckgeben,")
    print("dann wird der Parser gegen die tatsaechliche Struktur gebaut.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
