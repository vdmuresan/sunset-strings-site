#!/usr/bin/env python3
"""Local static server with the same route rules as worker/index.js.

Used to validate the copy. It does not contact Cloudflare or Squarespace.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RSS_FILES = {"/blog": "/feeds/blog.xml", "/video": "/feeds/video.xml"}
REDIRECTS = {}


def load_redirects() -> None:
    path = SITE / "_redirects"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            REDIRECTS[parts[0]] = (parts[1], int(parts[2]) if len(parts) > 2 else 302)


def bare(path: str) -> str:
    trimmed = path.rstrip("/")
    return trimmed or "/"


def normalize_lookup(path: str) -> str:
    path = unquote(path)
    if path.startswith("/blog/tag/"):
        path = "/blog/tag/" + path[len("/blog/tag/") :].replace("+", " ")
    return path


def resolve_file(url_path: str) -> Path | None:
    path = unquote(url_path.split("?", 1)[0])
    if path.endswith("/"):
        path = path[:-1]
    candidates = []
    if path in ("", "/"):
        candidates.append(SITE / "index.html")
    else:
        relative = path.lstrip("/")
        candidates.append(SITE / relative)
        candidates.append(SITE / relative / "index.html")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self.serve(head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self.serve(head=True)

    def serve(self, head: bool) -> None:
        parsed = urlparse(self.path)
        path = bare(unquote(parsed.path))
        if path in REDIRECTS:
            target, code = REDIRECTS[path]
            self.send_response(code)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/lessons":
            return self.file_response(SITE / "__status" / "lessons.html", 404, head)
        if path == "/__status" or path.startswith("/__status/"):
            body = b"Not found"
            self.respond(404, "text/plain; charset=utf-8", body, head)
            return
        params = parse_qs(parsed.query)
        keys = list(params)
        if params.get("format") == ["rss"] and path in RSS_FILES and keys == ["format"]:
            return self.file_response(SITE / RSS_FILES[path].lstrip("/"), 200, head)
        offset = params.get("offset", [None])[0]
        if offset and offset.isdigit() and keys == ["offset"]:
            return self.file_response(SITE / path.lstrip("/") / "__offset" / offset / "index.html", 200, head)
        found = resolve_file(normalize_lookup(parsed.path))
        if found is None:
            return self.file_response(SITE / "404.html", 404, head)
        return self.file_response(found, 200, head)

    def file_response(self, path: Path, status: int, head: bool) -> None:
        if not path.is_file():
            body = b"Not found"
            self.respond(404, "text/plain; charset=utf-8", body, head)
            return
        data = path.read_bytes()
        ctype = "text/html; charset=utf-8"
        suffix = path.suffix.lower()
        if suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif suffix == ".xml":
            ctype = "application/xml; charset=utf-8"
        elif suffix == ".txt":
            ctype = "text/plain; charset=utf-8"
        elif suffix == ".jpg":
            ctype = "image/jpeg"
        elif suffix == ".png":
            ctype = "image/png"
        elif suffix == ".webp":
            ctype = "image/webp"
        elif suffix == ".woff2":
            ctype = "font/woff2"
        elif suffix == ".svg":
            ctype = "image/svg+xml"
        elif suffix == ".ico":
            ctype = "image/x-icon"
        self.respond(status, ctype, data, head)

    def respond(self, status: int, content_type: str, body: bytes, head: bool) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)


def main() -> None:
    load_redirects()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving {SITE} on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
