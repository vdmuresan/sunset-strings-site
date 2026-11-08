#!/usr/bin/env python3
"""Check the static copy without submitting forms or contacting hosting accounts.

File checks always run. HTTP checks run when tools/serve_mirror.py is listening
on 127.0.0.1:8765.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
INVENTORY = ROOT / "inventory"

REQUIRED = [
    SITE / "index.html",
    SITE / "contact" / "index.html",
    SITE / "blog" / "index.html",
    SITE / "video" / "index.html",
    SITE / "quartet" / "index.html",
    SITE / "sitemap.xml",
    SITE / "robots.txt",
    SITE / "_redirects",
    SITE / "_headers",
    SITE / "404.html",
    SITE / "__status" / "lessons.html",
    INVENTORY / "routes.json",
    INVENTORY / "widgets.json",
    INVENTORY / "coverage.json",
    INVENTORY / "assets.json",
    INVENTORY / "provenance.json",
    INVENTORY / "redirects.json",
    ROOT / "docs" / "COVERAGE.md",
    ROOT / "docs" / "WIDGETS.md",
    ROOT / "docs" / "DEPLOYMENT.md",
    ROOT / "wrangler.toml",
    ROOT / "worker" / "index.js",
    ROOT / "functions" / "_middleware.js",
]

SECRET_MARKERS = [
    "set-cookie:",
    "client_secret",
    "BEGIN PRIVATE",
    "oauth_token",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def check_files(errors: list[str]) -> dict:
    for path in REQUIRED:
        if not path.exists():
            fail(errors, f"missing {path.relative_to(ROOT)}")
    if (SITE / "lessons" / "index.html").exists():
        fail(errors, "site/lessons/index.html exists; disabled lessons must not be republished as 200")
    contact = read(SITE / "contact" / "index.html") if (SITE / "contact" / "index.html").exists() else ""
    home = read(SITE / "index.html") if (SITE / "index.html").exists() else ""
    checks = {
        "honeybook_script": "widget.honeybook.com/assets_users_production/websiteplacements/placement-controller.min.js" in contact,
        "honeybook_id": "5e4c55e6a1d8be08fef5603e" in contact,
        "gtm": "GTM-P32B4CX" in home,
        "ga4": "G-C2F9D4EDFB" in home,
        "lessons_link": 'href="/lessons"' in home,
        "phone": "727) 210-5775" in home or "7272105775" in home,
        "canonical_home": 'rel="canonical" href="https://www.sunsetstrings.com"' in home,
    }
    for name, ok in checks.items():
        if not ok:
            fail(errors, f"content check failed: {name}")
    video = SITE / "video" / "v" / "canonind" / "index.html"
    if video.exists():
        text = read(video)
        if "FZvErefzATI" not in text or "cdn.embedly.com" not in text:
            fail(errors, "Canon in D page lost the YouTube/Embedly embed")
    else:
        fail(errors, "missing video/v/canonind")
    blob = "\n".join(read(path) for path in [ROOT / "worker" / "index.js", ROOT / "functions" / "_middleware.js"])
    if blob.count("lessons") < 2 or blob.count("__offset") < 2:
        fail(errors, "router files do not both implement lessons and offset routes")
    coverage = json.loads(read(INVENTORY / "coverage.json")) if (INVENTORY / "coverage.json").exists() else {}
    if coverage.get("http_200_pages", 0) < 200:
        fail(errors, f"expected at least 200 HTML 200s, found {coverage.get('http_200_pages')}")
    if coverage.get("image_files", 0) < 100:
        fail(errors, f"expected localized images, found {coverage.get('image_files')}")
    secrets = scan_secrets()
    if secrets:
        fail(errors, "possible secrets: " + ", ".join(secrets[:8]))
    return coverage


def scan_secrets() -> list[str]:
    hits = []
    roots = [SITE, INVENTORY, ROOT / "docs"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".woff2", ".ico"}:
                continue
            if path.stat().st_size > 2_000_000:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                continue
            for marker in SECRET_MARKERS:
                if marker.lower() in text:
                    hits.append(f"{path.relative_to(ROOT)}:{marker}")
            if "AKIA" in path.read_text(encoding="utf-8", errors="ignore"):
                import re
                if re.search(r"AKIA[0-9A-Z]{16}", path.read_text(encoding="utf-8", errors="ignore")):
                    hits.append(f"{path.relative_to(ROOT)}:AKIA")
    return hits


def check_http(errors: list[str]) -> bool:
    base = "http://127.0.0.1:8765"

    def get(path: str) -> tuple[int, str, str]:
        try:
            with urllib.request.urlopen(base + path, timeout=5) as response:
                body = response.read(800000).decode("utf-8", errors="replace")
                return response.status, response.geturl(), body
        except urllib.error.HTTPError as error:
            body = error.read(800000).decode("utf-8", errors="replace")
            return error.code, "", body

    try:
        status, _url, body = get("/")
    except Exception:
        return False
    if status != 200 or "Sunset Strings" not in body:
        fail(errors, f"local / status {status}")
    status, _url, body = get("/contact")
    if status != 200 or "5e4c55e6a1d8be08fef5603e" not in body:
        fail(errors, f"local /contact did not serve HoneyBook markup ({status})")
    status, _url, _body = get("/lessons")
    if status != 404:
        fail(errors, f"/lessons returned {status}, expected 404")
    request = urllib.request.Request(base + "/more", method="GET")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(request, timeout=5)
        fail(errors, "/more did not redirect")
    except urllib.error.HTTPError as error:
        location = error.headers.get("Location", "")
        if error.code not in {301, 302, 303, 307, 308} or location != "/blog":
            fail(errors, f"/more redirect unexpected {error.code} {location}")
    return True


def main() -> None:
    errors: list[str] = []
    coverage = check_files(errors)
    http_ran = check_http(errors)
    print(json.dumps({
        "http_checks": http_ran,
        "http_200_pages": coverage.get("http_200_pages"),
        "image_files": coverage.get("image_files"),
        "errors": errors,
    }, indent=2))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
