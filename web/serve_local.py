#!/usr/bin/env python3
"""Lokaler Server, der die Cloudflare-_headers wirklich mitsendet.

Ohne das testet man die App ohne CSP - und merkt erst auf der echten Domain,
dass die Content-Security-Policy etwas blockiert.

    python3 web/serve_local.py        # http://127.0.0.1:8898
"""
import functools
import http.server
import pathlib
import re
import sys

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


class Handler(http.server.SimpleHTTPRequestHandler):
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
