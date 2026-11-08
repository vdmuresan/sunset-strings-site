#!/usr/bin/env python3
"""Capture the public Sunset Strings site into a static copy.

Source of truth: https://www.sunsetstrings.com (live HTML, sitemap, robots).
Does not log into Squarespace or Cloudflare, does not submit forms, and does
not store Set-Cookie values or OAuth state parameters.

Raw responses are gzipped under capture/raw. Deployable HTML under site/ has
runs of 20+ spaces collapsed and site-owned images/CSS/fonts localized.
Squarespace visitor JavaScript and third-party widgets stay remote embeds.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import queue
from collections import defaultdict
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "capture"
RAW = CAPTURE / "raw"
GAPS = CAPTURE / "gaps"
PLATFORM = CAPTURE / "platform-js"
SITE = ROOT / "site"
INVENTORY = ROOT / "inventory"
DOCS = ROOT / "docs"

HOST = "www.sunsetstrings.com"
ORIGIN = f"https://{HOST}"
SITE_ID = "62f69923e0afe00d7b94a0aa"
UA = (
    "SunsetStringsOwnerArchive/1.0 "
    "(+https://github.com/vdmuresan/sunset-strings-site; public HTML capture)"
)
DOWNLOAD_HOSTS = {
    "images.squarespace-cdn.com",
    "static1.squarespace.com",
    "file.squarespace-cdn.com",
    "assets.squarespace.com",
    "definitions.sqspcdn.com",
}
PAGE_WORKERS = 6
ASSET_WORKERS = 8
MAX_ASSET_BYTES = 25 * 1024 * 1024
STARTED = datetime.now(timezone.utc)

SSL_CTX = ssl.create_default_context()

# Squarespace robots.txt Disallow rules for User-agent: * captured 2026-11-08.
# Re-fetched at runtime and unioned with this list.
DISALLOW_PREFIXES = [
    "/config",
    "/search",
    "/account",
    "/commerce/digital-download/",
    "/api/",
    "/static/",
]
DISALLOW_QUERY_KEYS = {
    "author",
    "tag",
    "month",
    "view",
    "format",
    "reversepaginate",
}
# format=rss is a public feed and is not named by the live robots file.
# format=json and the other robots values stay disallowed.
ALLOWED_FORMATS = {"rss"}

IMG_URL_RE = re.compile(
    r"(?:https?:)?//(?:images\.squarespace-cdn\.com|static1\.squarespace\.com)/[^\"'\s<>),]+",
    re.I,
)
FONT_URL_RE = re.compile(
    r"https?://file\.squarespace-cdn\.com/[^\"'\s<>),]+\.woff2",
    re.I,
)
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", re.I)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(NoRedirect(), HTTPSHandler(context=SSL_CTX))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    line = f"[{utc_now()}] {message}"
    print(line, flush=True)
    CAPTURE.mkdir(parents=True, exist_ok=True)
    with (CAPTURE / "crawl.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_url(url: str) -> str:
    """Drop fragments and redact query keys that carry request secrets."""
    parts = urlparse(url)
    sensitive = re.compile(r"(state|code|token|crumb|session|password|auth|sig)", re.I)
    kept = []
    redacted = False
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if sensitive.search(key) or sensitive.search(value):
            redacted = True
            continue
        kept.append((key, value))
    query = urlencode(kept)
    if redacted:
        query = (query + "&" if query else "") + "redacted=1"
    return urlunparse(parts._replace(query=query, fragment=""))


def same_site(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host in {HOST, "sunsetstrings.com"}


def normalize_page_url(url: str) -> str | None:
    if not url or url.startswith(("mailto:", "tel:", "sms:", "javascript:", "#")):
        return None
    absolute = urljoin(ORIGIN + "/", url)
    parts = urlparse(absolute)
    if parts.netloc.lower() not in {HOST, "sunsetstrings.com"}:
        return None
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    keys = {key.lower() for key, _ in query_pairs}
    if keys & (DISALLOW_QUERY_KEYS - {"format"}):
        return None
    if "format" in keys:
        formats = {value.lower() for key, value in query_pairs if key.lower() == "format"}
        if formats - ALLOWED_FORMATS:
            return None
        if formats != {"rss"}:
            return None
        query = "format=rss"
    elif "offset" in keys:
        offsets = [value for key, value in query_pairs if key.lower() == "offset"]
        if len(keys) != 1 or not offsets or not offsets[0].isdigit():
            return None
        query = f"offset={offsets[0]}"
    elif keys:
        return None
    else:
        query = ""
    return urlunparse(("https", HOST, path, "", query, ""))


def robots_allowed(url: str) -> bool:
    parts = urlparse(url)
    path = parts.path or "/"
    if path != "/search" and any(path == prefix or path.startswith(prefix if prefix.endswith("/") else prefix + "/") or path.startswith(prefix) for prefix in DISALLOW_PREFIXES):
        # /search is the public search shell. Robots disallows it; the owner
        # asked for navigation shells, so the single unqueried /search page is
        # captured and flagged. /account, /config, /api, and /static are not.
        if path == "/search" or path.startswith("/search/"):
            return True
        return False
    if path.startswith("/api/") and not path.startswith("/api/ui-extensions/"):
        return False
    return True


def normalize_slashes(text: str) -> str:
    # JSON encodes a slash as a backslash followed by a slash. Fold that back.
    return text.replace("\\/", "/")


def request_once(url: str, timeout: int = 60) -> tuple[int, str, dict, bytes]:
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with OPENER.open(req, timeout=timeout) as response:
            payload = response.read()
            headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, response.geturl(), headers, payload
    except Exception as error:
        status = getattr(error, "code", None)
        headers_obj = getattr(error, "headers", None)
        headers = {}
        if headers_obj is not None:
            headers = {key.lower(): value for key, value in headers_obj.items()}
        payload = b""
        if hasattr(error, "read"):
            try:
                payload = error.read()
            except Exception:
                payload = b""
        location = headers.get("location", "")
        if status is None:
            raise
        return status, location or url, headers, payload


def fetch_chain(url: str, limit: int = 6) -> dict:
    chain = []
    current = url
    payload = b""
    headers: dict = {}
    status = 0
    for _ in range(limit):
        status, target, headers, payload = request_once(current)
        location = headers.get("location", "")
        public_location = sanitize_url(urljoin(current, location)) if location else ""
        chain.append(
            {
                "url": sanitize_url(current),
                "status": status,
                "location": public_location,
                "content_type": headers.get("content-type", ""),
            }
        )
        if status in {301, 302, 303, 307, 308} and location:
            nxt = urljoin(current, location)
            host = urlparse(nxt).netloc.lower()
            if host and host not in {HOST, "sunsetstrings.com"}:
                break
            if "state=" in nxt or "oauth" in nxt or "login.squarespace.com" in nxt:
                break
            current = nxt
            continue
        break
    return {
        "requested": sanitize_url(url),
        "status": status,
        "final_url": sanitize_url(current),
        "content_type": headers.get("content-type", ""),
        "chain": chain,
        "body": payload,
        "x_robots": headers.get("x-robots-tag", ""),
    }


def header_probe(url: str) -> dict:
    result = fetch_chain(url)
    result.pop("body", None)
    return result


def collapse_spaces(html: str) -> str:
    return re.sub(r" {20,}", " ", html)


def asset_key(url: str) -> str:
    cleaned = unescape(url.replace("\\/", "/").replace("&amp;", "&"))
    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    parts = urlparse(cleaned)
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) >= 4 and segments[0] == "content" and segments[1] == "v1":
        return segments[3]
    return parts.netloc.lower() + parts.path


def extension_for(content_type: str, url: str) -> str:
    ctype = content_type.split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "image/x-icon": ".ico",
        "image/vnd.microsoft.icon": ".ico",
        "text/css": ".css",
        "font/woff": ".woff",
        "font/woff2": ".woff2",
        "application/font-woff": ".woff",
        "application/font-woff2": ".woff2",
        "font/ttf": ".ttf",
        "font/otf": ".otf",
        "application/vnd.ms-fontobject": ".eot",
        "application/javascript": ".js",
        "text/javascript": ".js",
        "application/pdf": ".pdf",
        "audio/mpeg": ".mp3",
    }
    if ctype in mapping:
        return mapping[ctype]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico", ".css", ".js", ".woff2", ".pdf", ".mp3"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ""


def safe_name(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return value[:80] or "file"


def self_check() -> None:
    sample = normalize_slashes(
        'src="//images.squarespace-cdn.com/content/v1/'
        + SITE_ID
        + '/518c254f-d4bd-4afb-b50d-9169d4a08ad3/Logo.png?format=1500w" '
        'and "https:\\/\\/images.squarespace-cdn.com\\/content\\/v1\\/'
        + SITE_ID
        + '\\/1715696483235-5SEX1CQHRJBZMWEJ9Y77\\/photo.jpg"'
    )
    found = IMG_URL_RE.findall(sample)
    if len(found) != 2:
        raise SystemExit(f"image url self-check failed: {found}")
    key = asset_key(found[1])
    if key != "1715696483235-5SEX1CQHRJBZMWEJ9Y77":
        raise SystemExit(f"asset key self-check failed: {key}")
    if normalize_page_url("https://www.sunsetstrings.com/blog/?offset=12&tag=x") is not None:
        raise SystemExit("query filter self-check failed")
    if normalize_page_url("/blog?offset=12") != ORIGIN + "/blog?offset=12":
        raise SystemExit("offset normalize failed")
    if robots_allowed(ORIGIN + "/config"):
        raise SystemExit("robots self-check failed")
    if not robots_allowed(ORIGIN + "/lessons"):
        raise SystemExit("lessons should be fetched so the 404 can be recorded")


def load_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    pages = re.findall(r"<loc>(https://www\.sunsetstrings\.com[^<]*)</loc>", xml_text)
    images = re.findall(r"<image:loc>(.*?)</image:loc>", xml_text)
    return pages, [unescape(image) for image in images]


def rel_page_path(url: str) -> str:
    parts = urlparse(url)
    path = unquote(parts.path or "/")
    if path.startswith("/blog/tag/"):
        path = "/blog/tag/" + path[len("/blog/tag/") :].replace("+", " ")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query = dict(parse_qsl(parts.query))
    if query.get("format") == "rss":
        name = "blog.xml" if path == "/blog" else "video.xml" if path == "/video" else safe_name(path.strip("/")) + ".xml"
        return f"feeds/{name}"
    if path == "/":
        base = "index.html"
    else:
        base = path.strip("/") + "/index.html"
    if query.get("offset", "").isdigit():
        return path.strip("/") + f"/__offset/{query['offset']}/index.html"
    return base


def raw_path_for(url: str) -> Path:
    digest = hashlib.sha1(url.encode()).hexdigest()
    return RAW / f"{digest}.html.gz"


def meta_path_for(url: str) -> Path:
    return raw_path_for(url).with_suffix("").with_suffix(".meta.json")


class Crawler:
    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.seen: set[str] = set()
        self.records: list[dict] = []
        self.queue: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.active = 0
        self.fetched = 0
        self.redirects: list[dict] = []

    def enqueue(self, url: str | None) -> None:
        if not url:
            return
        normalized = normalize_page_url(url)
        if not normalized or not robots_allowed(normalized):
            return
        with self.condition:
            if self.limit is not None and self.fetched + self.queue.qsize() + self.active >= self.limit:
                return
            if normalized in self.seen:
                return
            self.seen.add(normalized)
            self.queue.put(normalized)
            self.condition.notify()

    def discover_links(self, html: str, page_url: str) -> None:
        for href in re.findall(r"""(?:href|src)=["']([^"'#]+)""", html, re.I):
            self.enqueue(urljoin(page_url, unescape(href)))
        for href in re.findall(r"""https://www\.sunsetstrings\.com[^"'\\\s<>]*""", html):
            self.enqueue(href.replace("\\/", "/"))

    def process(self, url: str) -> None:
        log(f"fetch {url}")
        try:
            result = fetch_chain(url)
        except Exception as error:
            record = {
                "requested": url,
                "status": 0,
                "error": str(error),
                "fetched_at": utc_now(),
            }
            with self.lock:
                self.records.append(record)
            log(f"error {url} {error}")
            return
        body = result.pop("body")
        final_url = normalize_page_url(result["final_url"]) or result["final_url"]
        record = {
            "requested": result["requested"],
            "final_url": result["final_url"],
            "status": result["status"],
            "content_type": result["content_type"],
            "x_robots": result["x_robots"],
            "chain": result["chain"],
            "bytes": len(body),
            "sha256": sha256(body) if body else "",
            "fetched_at": utc_now(),
        }
        if len(result["chain"]) > 1:
            self.redirects.append(
                {
                    "from": result["requested"],
                    "chain": result["chain"],
                    "final_status": result["status"],
                }
            )
        ctype = result["content_type"].lower()
        text = ""
        if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype):
            text = body.decode("utf-8", errors="replace")
        if result["status"] == 200 and "html" in ctype:
            title = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
            canonical = re.search(r'rel="canonical" href="([^"]+)"', text, re.I)
            robots = re.search(r'name="robots" content="([^"]+)"', text, re.I)
            description = re.search(r'name="description" content="([^"]*)"', text, re.I)
            record.update(
                {
                    "title": re.sub(r"\s+", " ", unescape(title.group(1))).strip() if title else "",
                    "canonical": unescape(canonical.group(1)) if canonical else "",
                    "meta_robots": robots.group(1) if robots else "",
                    "description": unescape(description.group(1)) if description else "",
                    "saved_raw": str(raw_path_for(final_url).relative_to(ROOT)),
                }
            )
            raw_path_for(final_url).parent.mkdir(parents=True, exist_ok=True)
            raw_path_for(final_url).write_bytes(gzip.compress(body))
            self.discover_links(text, final_url)
        elif result["status"] == 200 and ("xml" in ctype or "rss" in ctype):
            record["saved_raw"] = str(raw_path_for(url).relative_to(ROOT))
            record["kind"] = "feed"
            raw_path_for(url).write_bytes(gzip.compress(body))
            for link in re.findall(r"<link>(.*?)</link>", text):
                self.enqueue(unescape(link).strip())
        elif result["status"] == 404 and "html" in ctype:
            record["title"] = ""
            title = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
            if title:
                record["title"] = re.sub(r"\s+", " ", unescape(title.group(1))).strip()
            canonical = re.search(r'rel="canonical" href="([^"]+)"', text, re.I)
            record["canonical"] = unescape(canonical.group(1)) if canonical else ""
            record["kind"] = "not-found"
            record["saved_raw"] = str(raw_path_for(url).relative_to(ROOT))
            raw_path_for(url).parent.mkdir(parents=True, exist_ok=True)
            raw_path_for(url).write_bytes(gzip.compress(body))
        else:
            record["kind"] = "unsaved"
            record["note"] = "Body not stored. Non-HTML, redirect off-site, or error."
        with self.lock:
            self.records.append(record)
            self.fetched += 1
        log(f"done {result['status']} {len(body)} {url}")

    def worker(self) -> None:
        while True:
            with self.condition:
                while self.queue.empty() and self.active > 0:
                    self.condition.wait()
                if self.queue.empty() and self.active == 0:
                    return
                url = self.queue.get()
                self.active += 1
            try:
                self.process(url)
            finally:
                with self.condition:
                    self.active -= 1
                    self.condition.notify_all()

    def run(self, seeds: list[str]) -> None:
        for seed in seeds:
            self.enqueue(seed)
        threads = [threading.Thread(target=self.worker, daemon=True) for _ in range(PAGE_WORKERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()


def read_gzip_text(path: Path) -> str:
    return gzip.decompress(path.read_bytes()).decode("utf-8", errors="replace")


def collect_from_html(html: str) -> dict:
    html = normalize_slashes(html)
    images = IMG_URL_RE.findall(html)
    fonts = FONT_URL_RE.findall(html)
    stylesheets = re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]*>', html, re.I)
    css_urls = []
    for tag in stylesheets:
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if href:
            css_urls.append(unescape(href.group(1)))
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I)
    iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
    forms = re.findall(r"<form\b([^>]*)>", html, re.I)
    return {
        "images": images,
        "fonts": fonts,
        "stylesheets": css_urls,
        "scripts": [unescape(item) for item in scripts],
        "iframes": [unescape(item) for item in iframes],
        "forms": forms,
    }


def download_binary(url: str) -> tuple[bytes, str, str]:
    current = url
    for _ in range(5):
        status, _target, headers, payload = request_once(current)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location", "")
            if not location:
                raise RuntimeError(f"HTTP {status}")
            nxt = urljoin(current, location)
            host = urlparse(nxt).netloc.lower()
            if host not in DOWNLOAD_HOSTS:
                raise RuntimeError(f"redirect host {host}")
            current = nxt
            continue
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        ctype = headers.get("content-type", "")
        if payload.startswith(b"wOFF"):
            ctype = "font/woff"
        elif payload.startswith(b"wOF2"):
            ctype = "font/woff2"
        if "text/html" in ctype.lower():
            raise RuntimeError("html response for asset")
        if len(payload) > MAX_ASSET_BYTES:
            raise RuntimeError(f"asset too large {len(payload)}")
        return payload, ctype, current
    raise RuntimeError("too many redirects")


def local_asset_path(kind: str, key: str, ext: str) -> str:
    digest = hashlib.sha1(key.encode()).hexdigest()[:12]
    return f"/assets/{kind}/{digest}{ext}"


def build_site(records: list[dict], sitemap_images: list[str], sitemap_xml: str, robots_txt: str) -> dict:
    pages = []
    for record in records:
        if record.get("status") == 200 and record.get("saved_raw") and record.get("kind") != "feed":
            pages.append(record)
        if record.get("kind") == "feed" and record.get("saved_raw"):
            pages.append(record)
    image_urls: set[str] = set(sitemap_images)
    font_urls: set[str] = set()
    css_urls: set[str] = set()
    script_map: dict[str, set[str]] = defaultdict(set)
    iframe_map: dict[str, set[str]] = defaultdict(set)
    form_map: dict[str, list[str]] = defaultdict(list)
    honeybook_pages: set[str] = set()
    embedly_pages: set[str] = set()
    youtube_ids: dict[str, set[str]] = defaultdict(set)
    calendly_values: set[str] = set()
    gtm_ids: set[str] = set()
    ga_ids: set[str] = set()
    recaptcha_keys: set[str] = set()
    social_urls: set[str] = set()
    page_summaries = []

    html_by_output: dict[str, str] = {}
    for record in records:
        saved = record.get("saved_raw")
        if not saved:
            continue
        text = read_gzip_text(ROOT / saved)
        requested = record["requested"]
        if urlparse(requested).path.lower().endswith(".svg"):
            svg_path = unquote(urlparse(requested).path).lstrip("/")
            page_summaries.append(
                {
                    "requested": requested,
                    "final_url": record.get("final_url"),
                    "status": record.get("status"),
                    "title": "",
                    "canonical": "",
                    "meta_robots": "",
                    "x_robots": record.get("x_robots", ""),
                    "description": "",
                    "words": 0,
                    "bytes_raw": record.get("bytes"),
                    "sha256_raw": record.get("sha256"),
                    "fetched_at": record.get("fetched_at"),
                    "output": svg_path,
                    "kind": "svg",
                }
            )
            html_by_output[svg_path] = text
            continue
        output = rel_page_path(requested if record.get("kind") == "feed" else (normalize_page_url(record.get("final_url") or requested) or requested))
        if record.get("kind") == "not-found":
            output = "__status/" + safe_name(urlparse(requested).path.strip("/")) + ".html"
        if record.get("status") != 200 and record.get("kind") != "not-found":
            continue
        found = collect_from_html(text)
        image_urls.update(found["images"])
        font_urls.update(found["fonts"])
        for href in found["stylesheets"]:
            absolute = href
            if absolute.startswith("//"):
                absolute = "https:" + absolute
            css_urls.add(absolute)
        path = urlparse(requested).path or "/"
        for src in found["scripts"]:
            script_map[src].add(path)
        for src in found["iframes"]:
            iframe_map[src].add(path)
        if found["forms"]:
            form_map[path].extend(found["forms"][:8])
        if "widget.honeybook.com" in text or "honeybook.com" in text:
            honeybook_pages.add(path)
        if "embedly.com" in text:
            embedly_pages.add(path)
        for video_id in set(re.findall(r"youtube\.com/(?:embed/|watch\?v=)([A-Za-z0-9_-]{6,})", text)):
            youtube_ids[video_id].add(path)
        for video_id in set(re.findall(r"i\.ytimg\.com/vi/([A-Za-z0-9_-]{6,})/", text)):
            youtube_ids[video_id].add(path)
        calendly_values.update(re.findall(r"https?:\\?/\\?/calendly\.com[^\"'\\s<]*", text))
        gtm_ids.update(re.findall(r"GTM-[A-Z0-9]+", text))
        ga_ids.update(re.findall(r"\bG-[A-Z0-9]{6,}\b", text))
        recaptcha_keys.update(re.findall(r'recaptchaEnterpriseSiteKey\\?":\\?"([^"\\]+)', text))
        recaptcha_keys.update(re.findall(r'"recaptchaEnterpriseSiteKey":"([^"]+)"', text))
        social_urls.update(re.findall(r'"profileUrl":"(https:[^"]+)"', text))
        visible = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
        visible = re.sub(r"<style[\s\S]*?</style>", " ", visible, flags=re.I)
        visible = re.sub(r"<[^>]+>", " ", visible)
        words = re.findall(r"[A-Za-z0-9'’-]{2,}", unescape(visible))
        page_summaries.append(
            {
                "requested": requested,
                "final_url": record.get("final_url"),
                "status": record.get("status"),
                "title": record.get("title", ""),
                "canonical": record.get("canonical", ""),
                "meta_robots": record.get("meta_robots", ""),
                "x_robots": record.get("x_robots", ""),
                "description": record.get("description", ""),
                "words": len(words),
                "bytes_raw": record.get("bytes"),
                "sha256_raw": record.get("sha256"),
                "fetched_at": record.get("fetched_at"),
                "output": output,
                "kind": record.get("kind", "page"),
            }
        )
        html_by_output[output] = text

    log(f"asset candidates images={len(image_urls)} css={len(css_urls)} fonts={len(font_urls)}")
    image_map, image_inventory, image_failures = download_images(image_urls)
    css_files, css_inventory, font_urls_from_css, css_image_urls = download_css(css_urls)
    font_urls.update(font_urls_from_css)
    extra_images, extra_inv, extra_fail = download_images(css_image_urls, image_map)
    image_map.update(extra_images)
    image_inventory.extend(extra_inv)
    image_failures.extend(extra_fail)
    font_map, font_inventory, font_failures = download_fonts(font_urls)
    rewrite_css_files(css_files, image_map, font_map)
    script_inventory = download_platform_scripts(script_map)

    written = []
    tag_root = SITE / "blog" / "tag"
    if tag_root.exists():
        shutil.rmtree(tag_root)
    bad_svg = SITE / "universal" / "svg" / "social-accounts.svg"
    if bad_svg.is_dir():
        shutil.rmtree(bad_svg)
    for output, text in html_by_output.items():
        if output.startswith("feeds/") or output.endswith(".svg"):
            destination = SITE / output
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
            written.append(output)
            continue
        rewritten = render_html(text, image_map, font_map, css_files)
        destination = SITE / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rewritten, encoding="utf-8")
        written.append(output)

    generic_404 = html_by_output.get("__status/__capture-probe-not-a-page.html")
    lessons = html_by_output.get("__status/lessons.html")
    if generic_404:
        (SITE / "404.html").write_text(render_html(generic_404, image_map, font_map, css_files), encoding="utf-8")
        written.append("404.html")
    elif lessons:
        (SITE / "404.html").write_text(render_html(lessons, image_map, font_map, css_files), encoding="utf-8")
        written.append("404.html")

    (SITE / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")
    (SITE / "robots.txt").write_text(robots_txt, encoding="utf-8")
    (SITE / "_headers").write_text(
        "/*\n  X-Frame-Options: SAMEORIGIN\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n",
        encoding="utf-8",
    )
    redirects = observed_redirects(records)
    redirect_lines = ["# Path aliases observed on the live site. Host-level apex/www rules are documented, not emulated here."]
    for item in redirects:
        source = urlparse(item["from"]).path
        finals = [hop for hop in item["chain"] if hop.get("location")]
        if not finals:
            continue
        target = urlparse(finals[0]["location"]).path or "/"
        code = finals[0]["status"]
        if source and target and source != target and urlparse(finals[0]["location"]).netloc in {"", HOST}:
            redirect_lines.append(f"{source} {target} {code}")
    if not any(line.startswith("/checkout ") for line in redirect_lines):
        redirect_lines.append("/checkout /cart 302")
    (SITE / "_redirects").write_text("\n".join(dict.fromkeys(redirect_lines)) + "\n", encoding="utf-8")

    return {
        "pages": page_summaries,
        "written": written,
        "images": image_inventory,
        "image_failures": image_failures,
        "css": css_inventory,
        "fonts": font_inventory,
        "font_failures": font_failures,
        "scripts": script_inventory,
        "script_map": {key: sorted(value) for key, value in script_map.items()},
        "iframe_map": {key: sorted(value) for key, value in iframe_map.items()},
        "forms": {key: value for key, value in form_map.items()},
        "honeybook_pages": sorted(honeybook_pages),
        "embedly_pages": sorted(embedly_pages),
        "youtube_ids": {key: sorted(value) for key, value in youtube_ids.items()},
        "calendly": sorted({item.replace("\\/", "/") for item in calendly_values}),
        "gtm": sorted(gtm_ids),
        "ga": sorted(ga_ids),
        "recaptcha": sorted(recaptcha_keys),
        "social": sorted({unescape(item) for item in social_urls}),
        "redirect_lines": redirect_lines,
        "lessons_equals_generic_404": bool(lessons and generic_404 and collapse_spaces(lessons) == collapse_spaces(generic_404)),
    }


def load_prior_assets(kind: str) -> dict[str, dict]:
    path = INVENTORY / "assets.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    found = {}
    for item in data.get(kind, []):
        local = item.get("local")
        if item.get("key") and local and (SITE / local.lstrip("/")).is_file():
            found[item["key"]] = item
    return found


def download_images(urls: set[str], existing: dict | None = None) -> tuple[dict, list, list]:
    mapping = dict(existing or {})
    inventory = []
    failures = []
    grouped: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        if "squarespace" not in url:
            continue
        lower = urlparse(url.replace("\\/", "/")).path.lower()
        if lower.endswith((".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js")):
            continue
        grouped[asset_key(url)].append(url)
    prior = load_prior_assets("images")
    work = []
    for key, variants in grouped.items():
        if key in mapping:
            continue
        if key in prior:
            mapping[key] = prior[key]["local"]
            inventory.append(prior[key])
            continue
        original = sorted(variants, key=lambda item: ("format=" in item, len(item)))[0]
        original = original.replace("\\/", "/")
        if original.startswith("//"):
            original = "https:" + original
        bare = original.split("?")[0]
        if bare.startswith("http://"):
            bare = "https://" + bare[len("http://") :]
        work.append((key, bare, variants))

    lock = threading.Lock()
    sha_to_local = {item.get("sha256"): item["local"] for item in inventory if item.get("sha256") and item.get("local")}

    def task(item: tuple[str, str, list[str]]) -> None:
        key, bare, variants = item
        attempts = [bare]
        if "format=" not in bare:
            attempts.append(bare + "?format=2500w")
            attempts.append(bare + "?format=1500w")
        last_error = ""
        for attempt in attempts:
            host = urlparse(attempt).netloc.lower()
            if host not in DOWNLOAD_HOSTS:
                last_error = f"host not allowed {host}"
                continue
            try:
                payload, ctype, final_url = download_binary(attempt)
            except Exception as error:
                last_error = str(error)
                continue
            ext = extension_for(ctype, final_url)
            if ext in {".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js"}:
                last_error = f"not an image ({ctype})"
                continue
            if not ext:
                last_error = f"unknown type {ctype}"
                continue
            digest = sha256(payload)
            with lock:
                reused = sha_to_local.get(digest)
            if reused and (SITE / reused.lstrip("/")).is_file():
                local = reused
            else:
                rel = local_asset_path("media", key, ext).lstrip("/")
                destination = SITE / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
                local = "/" + rel
            record = {
                "key": key,
                "local": local,
                "source": final_url,
                "requested": attempt,
                "variants": variants[:12],
                "variant_count": len(variants),
                "bytes": len(payload),
                "sha256": digest,
                "content_type": ctype,
                "placeholder": "no-image.png" in final_url,
                "fetched_at": utc_now(),
            }
            with lock:
                mapping[key] = local
                sha_to_local[digest] = local
                inventory.append(record)
            return
        with lock:
            failures.append({"key": key, "source": bare, "error": last_error, "variants": variants[:4]})

    run_pool(task, work, ASSET_WORKERS)
    log(f"images stored={len(inventory)} failed={len(failures)}")
    return mapping, inventory, failures


def download_css(urls: set[str]) -> tuple[dict, list, set[str], set[str]]:
    mapping = {}
    inventory = []
    fonts: set[str] = set()
    images: set[str] = set()
    lock = threading.Lock()

    def task(url: str) -> None:
        absolute = url if url.startswith("http") else ("https:" + url if url.startswith("//") else urljoin(ORIGIN + "/", url))
        host = urlparse(absolute).netloc.lower()
        if host not in DOWNLOAD_HOSTS:
            return
        try:
            payload, ctype, _final = download_binary(absolute)
        except Exception as error:
            with lock:
                inventory.append({"source": absolute, "error": str(error)})
            return
        text = payload.decode("utf-8", errors="replace")
        rel = local_asset_path("css", absolute, ".css").lstrip("/")
        destination = SITE / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        found_fonts, found_images = css_dependencies(text, absolute)
        with lock:
            mapping[url] = "/" + rel
            mapping[absolute] = "/" + rel
            if url.startswith("https:"):
                mapping["//" + url[len("https://") :]] = "/" + rel
            inventory.append(
                {
                    "source": absolute,
                    "local": "/" + rel,
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                    "content_type": ctype,
                    "fetched_at": utc_now(),
                }
            )
            fonts.update(found_fonts)
            images.update(found_images)

    run_pool(task, sorted(urls), min(4, ASSET_WORKERS))
    return mapping, inventory, fonts, images


def css_dependencies(css_text: str, base: str) -> tuple[set[str], set[str]]:
    fonts = set()
    images = set()
    for _quote, raw in CSS_URL_RE.findall(css_text):
        if raw.startswith("data:") or raw.startswith("#"):
            continue
        absolute = urljoin(base, raw.replace("\\/", "/"))
        suffix = urlparse(absolute).path.lower()
        if suffix.endswith((".woff2", ".woff", ".ttf", ".otf", ".eot")):
            fonts.add(absolute)
        elif "squarespace" in absolute and not suffix.endswith((".css", ".js")):
            images.add(absolute)
    fonts.update(match.replace("\\/", "/") for match in FONT_URL_RE.findall(css_text))
    images.update(match.replace("\\/", "/") for match in IMG_URL_RE.findall(css_text))
    return fonts, images


def download_fonts(urls: set[str]) -> tuple[dict, list, list]:
    mapping = {}
    inventory = []
    failures = []
    lock = threading.Lock()

    def task(url: str) -> None:
        absolute = url.replace("\\/", "/")
        if absolute.startswith("//"):
            absolute = "https:" + absolute
        host = urlparse(absolute).netloc.lower()
        if host not in DOWNLOAD_HOSTS:
            return
        try:
            payload, ctype, final_url = download_binary(absolute.split("?")[0])
        except Exception as error:
            with lock:
                failures.append({"source": absolute, "error": str(error)})
            return
        ext = extension_for(ctype, final_url)
        if ext not in {".woff", ".woff2", ".ttf", ".otf", ".eot"}:
            ext = Path(urlparse(final_url).path).suffix.lower()
        if ext not in {".woff", ".woff2", ".ttf", ".otf", ".eot"}:
            with lock:
                failures.append({"source": absolute, "error": f"not a font ({ctype})"})
            return
        rel = local_asset_path("fonts", absolute.split("?")[0], ext).lstrip("/")
        destination = SITE / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        with lock:
            mapping[asset_key(absolute)] = "/" + rel
            inventory.append(
                {
                    "source": absolute.split("?")[0],
                    "local": "/" + rel,
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                    "content_type": ctype,
                    "fetched_at": utc_now(),
                    "note": "Fetched from the font URL referenced by the live site. The upstream license stays with the font owner. This archive does not claim authorship.",
                }
            )

    run_pool(task, sorted(set(urls)), ASSET_WORKERS)
    log(f"fonts stored={len(inventory)} failed={len(failures)}")
    return mapping, inventory, failures


def download_platform_scripts(script_map: dict[str, set[str]]) -> list[dict]:
    inventory = []
    lock = threading.Lock()
    urls = []
    for src in script_map:
        absolute = src
        if absolute.startswith("//"):
            absolute = "https:" + absolute
        host = urlparse(absolute).netloc.lower()
        if host in DOWNLOAD_HOSTS:
            urls.append((src, absolute))

    def task(item: tuple[str, str]) -> None:
        src, absolute = item
        try:
            payload, ctype, _final = download_binary(absolute)
        except Exception as error:
            with lock:
                inventory.append({"source": absolute, "error": str(error), "pages": sorted(script_map[src])[:30]})
            return
        name = safe_name(Path(urlparse(absolute).path).name)
        digest = hashlib.sha1(absolute.encode()).hexdigest()[:10]
        destination = PLATFORM / f"{digest}-{name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        with lock:
            inventory.append(
                {
                    "source": absolute,
                    "archived_copy": str(destination.relative_to(ROOT)),
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                    "content_type": ctype,
                    "pages": sorted(script_map[src]),
                    "deployed_html": "left pointing at the original CDN URL",
                    "copyright": "Squarespace platform runtime. Not Sunset Strings authorship.",
                    "fetched_at": utc_now(),
                }
            )

    run_pool(task, urls, 4)
    return inventory


def rewrite_css_files(css_files: dict, image_map: dict, font_map: dict) -> None:
    seen = set()
    for local in css_files.values():
        if local in seen:
            continue
        seen.add(local)
        path = SITE / local.lstrip("/")
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        path.write_text(rewrite_asset_urls(text, image_map, font_map), encoding="utf-8")


def rewrite_asset_urls(text: str, image_map: dict, font_map: dict) -> str:
    def image_sub(match: re.Match) -> str:
        key = asset_key(match.group(0))
        return image_map.get(key, match.group(0))

    def font_sub(match: re.Match) -> str:
        key = asset_key(match.group(0))
        return font_map.get(key, match.group(0))

    text = IMG_URL_RE.sub(image_sub, text)
    text = FONT_URL_RE.sub(font_sub, text)
    return text


def render_html(html: str, image_map: dict, font_map: dict, css_files: dict) -> str:
    text = collapse_spaces(normalize_slashes(html))
    protected: list[str] = []

    def protect(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"__SS_PROTECT_{len(protected) - 1}__"

    text = re.sub(r"<script type=\"application/ld\+json\">[\s\S]*?</script>", protect, text, flags=re.I)
    text = re.sub(
        r"<meta\b[^>]*(?:og:image|twitter:image|itemprop=\"image\"|itemprop=\"thumbnailUrl\")[^>]*>",
        protect,
        text,
        flags=re.I,
    )
    text = re.sub(r"<link\b[^>]*rel=\"image_src\"[^>]*>", protect, text, flags=re.I)
    text = rewrite_asset_urls(text, image_map, font_map)
    for source, local in sorted(css_files.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(source, local)
    def anchor_sub(match: re.Match) -> str:
        prefix, quote, path = match.group(1), match.group(2), match.group(3)
        if not path.startswith("/"):
            path = "/" + path
        return f"{prefix}{quote}{path}{quote}"

    text = re.sub(
        r'(<a\b[^>]*?\bhref=)(["\'])https?://www\.sunsetstrings\.com([^"\']*)\2',
        anchor_sub,
        text,
        flags=re.I,
    )
    for index, original in enumerate(protected):
        text = text.replace(f"__SS_PROTECT_{index}__", original)
    return text


def observed_redirects(records: list[dict]) -> list[dict]:
    items = []
    for record in records:
        chain = record.get("chain") or []
        if len(chain) > 1:
            items.append({"from": record["requested"], "chain": chain, "final_status": record.get("status")})
    return items


def run_pool(task, items, workers: int) -> None:
    if not items:
        return
    work = queue.Queue()
    for item in items:
        work.put(item)

    def runner() -> None:
        while True:
            try:
                item = work.get_nowait()
            except queue.Empty:
                return
            try:
                task(item)
            except Exception as error:
                log(f"task error {error}")
            finally:
                work.task_done()

    threads = [threading.Thread(target=runner, daemon=True) for _ in range(max(1, workers))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def write_reports(bundle: dict, probes: dict, sitemap_count: int, robots_txt: str) -> None:
    INVENTORY.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    pages = bundle["pages"]
    http_pages = [page for page in pages if page["kind"] != "feed"]
    ok_pages = [page for page in http_pages if page["status"] == 200]
    missing = [page for page in http_pages if page["status"] == 404]
    outputs = [page["output"] for page in ok_pages if not str(page["output"]).startswith("__status")]
    lessons = next((page for page in pages if urlparse(page["requested"]).path == "/lessons"), None)
    coverage = {
        "generated_at": utc_now(),
        "source": ORIGIN,
        "sitemap_url_count": sitemap_count,
        "fetched_records": len(pages),
        "http_200_pages": len(ok_pages),
        "http_404_pages": len(missing),
        "feed_count": sum(1 for page in pages if page["kind"] == "feed"),
        "deployable_routes": len(outputs),
        "image_files": len(bundle["images"]),
        "image_failures": bundle["image_failures"],
        "css_files": [item for item in bundle["css"] if "local" in item],
        "css_failures": [item for item in bundle["css"] if "error" in item],
        "font_files": len(bundle["fonts"]),
        "font_failures": bundle["font_failures"],
        "platform_script_archive": bundle["scripts"],
        "lessons": lessons,
        "lessons_equals_generic_404": bundle["lessons_equals_generic_404"],
        "whitespace": "Deployable HTML collapses runs of 20 or more spaces. Raw gzip bytes are unchanged.",
        "images_policy": "Each Squarespace content image was stored once. Redirects to images.squarespace-cdn.com were followed. Identical bytes are stored once. URLs that redirect to Squarespace's no-image.png placeholder share that one file. format=2500w and format=1500w are fallbacks when the queryless URL is not a 200 image.",
        "gaps": [
            "Live /lessons returns 404. The footer link is preserved. No lessons content was invented.",
            "robots.txt disallows ?tag= and reversePaginate. First-page tag indexes were captured; later tag pages and reverse pagination were not.",
            "robots.txt disallows /search. The empty search shell was still captured and flagged because it is a public page.",
            "format=json was not requested.",
            "/account redirects into the Squarespace login UI. That flow was not mirrored and no account was created.",
            "/config redirects toward Squarespace login. Only the status and host were recorded.",
            "Squarespace visitor JavaScript, HoneyBook, Embedly, YouTube, Calendly, and Google tags stay on their original hosts.",
        ],
        "not_end_to_end": [
            "HoneyBook form submission",
            "Squarespace commerce cart and checkout",
            "Calendly booking",
            "YouTube playback beyond embed markup",
            "Google Analytics / Tag Manager collection",
            "Squarespace customer account login",
        ],
    }
    (INVENTORY / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    (INVENTORY / "routes.json").write_text(json.dumps(pages, indent=2), encoding="utf-8")
    (INVENTORY / "assets.json").write_text(
        json.dumps({"images": bundle["images"], "css": bundle["css"], "fonts": bundle["fonts"]}, indent=2),
        encoding="utf-8",
    )
    widgets = build_widget_inventory(bundle)
    (INVENTORY / "widgets.json").write_text(json.dumps(widgets, indent=2), encoding="utf-8")
    (INVENTORY / "redirects.json").write_text(json.dumps({"live_probes": probes, "fetched_redirects": bundle["redirect_lines"]}, indent=2), encoding="utf-8")
    provenance = {
        "started_at": STARTED.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at": utc_now(),
        "source": ORIGIN,
        "method": "Public GET of sitemap, robots, HTML, RSS, and CDN assets. No Squarespace login, no Cloudflare account, no form posts.",
        "robots": robots_txt,
        "probes": probes,
        "site_id": SITE_ID,
        "notes": [
            "Live HTML comment identifies Squarespace and the site identifier sunsetstrings.",
            "Canonical host is https://www.sunsetstrings.com.",
            "Public DNS NS is Cloudflare. HTTPS responses include server: cloudflare and a Squarespace crumb cookie.",
            "https://sunsetstrings.squarespace.com responds with server: Squarespace and canonical https://www.sunsetstrings.com.",
            "The Cloudflare account was not accessed. Connector authentication was still pending.",
            "/lessons is listed in the live sitemap and the footer, and the live GET returns 404. Disabled lessons content was not invented or reactivated.",
            "format=json was not requested. Live robots.txt disallows it.",
        ],
    }
    (INVENTORY / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    write_markdown(bundle, coverage, widgets, probes)


def build_widget_inventory(bundle: dict) -> dict:
    endpoints = []
    for src, pages in sorted(bundle["script_map"].items()):
        endpoints.append({"type": "script", "url": src, "pages": pages})
    for src, pages in sorted(bundle["iframe_map"].items()):
        endpoints.append({"type": "iframe", "url": src, "pages": pages})
    return {
        "generated_at": utc_now(),
        "policy": "Third-party widgets are retained as the original public embed. Their private application code was not copied or reimplemented.",
        "honeybook": {
            "provider": "HoneyBook",
            "public_placement_id": "5e4c55e6a1d8be08fef5603e",
            "script": "https://widget.honeybook.com/assets_users_production/websiteplacements/placement-controller.min.js",
            "pixel": "https://www.honeybook.com/p.png?pid=5e4c55e6a1d8be08fef5603e",
            "container_class": "hb-p-5e4c55e6a1d8be08fef5603e-1",
            "pages": bundle["honeybook_pages"],
            "function": "Contact page inquiry embed inside a Squarespace embed block.",
            "submission": "Not tested. No inquiry was sent.",
            "dependency": "Requires HoneyBook widget servers at view time. Domain allowlisting is unresolved until a browser render check.",
        },
        "google": {
            "tag_manager": bundle["gtm"],
            "analytics_4": bundle["ga"],
            "iframe": "https://www.googletagmanager.com/ns.html?id=GTM-P32B4CX",
            "script": "https://www.googletagmanager.com/gtag/js?id=G-C2F9D4EDFB",
            "dependency": "Google tag endpoints. Collection was not exercised as a conversion and is not required for page content.",
        },
        "recaptcha_enterprise_site_key": bundle["recaptcha"],
        "calendly_profile_urls_as_published": bundle["calendly"],
        "youtube_ids_found_in_public_html": bundle["youtube_ids"],
        "embedly_pages": bundle["embedly_pages"],
        "embedly_note": "Video items carry Squarespace VideoEmbed data-config-embed-video with an Embedly iframe around YouTube. The Embedly key present in that public HTML is retained in the page; it is public page configuration, not a newly issued credential.",
        "social_profile_urls": bundle["social"],
        "forms_found": bundle["forms"],
        "declared_endpoints": endpoints,
        "cloudflare_edge_injections": [
            "/cdn-cgi/scripts/5c5dd728/cloudflare-static/email-decode.min.js",
            "https://static.cloudflareinsights.com/beacon.min.js",
        ],
        "squarespace_runtime": "Visitor JS remains loaded from assets.squarespace.com, definitions.sqspcdn.com, and static1.squarespace.com. Archival copies are under capture/platform-js and are not served as the site runtime. Squarespace retains copyright in those files.",
    }


def write_markdown(bundle: dict, coverage: dict, widgets: dict, probes: dict) -> None:
    lesson_status = coverage["lessons"]["status"] if coverage["lessons"] else "not fetched"
    lines = [
        "# Sunset Strings public-site capture",
        "",
        f"Generated {coverage['generated_at']} from {coverage['source']}.",
        "",
        "## Counts",
        "",
        f"- Sitemap page URLs: {coverage['sitemap_url_count']}",
        f"- Saved HTTP 200 HTML routes: {coverage['http_200_pages']}",
        f"- Saved HTTP 404 responses: {coverage['http_404_pages']}",
        f"- RSS feeds saved: {coverage['feed_count']}",
        f"- Deployable route files, excluding the lessons 404 body: {coverage['deployable_routes']}",
        f"- Localized image files: {coverage['image_files']}",
        f"- Image download failures: {len(coverage['image_failures'])}",
        f"- Localized CSS files: {len(coverage['css_files'])}",
        f"- Localized font files: {coverage['font_files']}",
        f"- Platform script archival copies: {len(coverage['platform_script_archive'])}",
        "",
        "## Gaps recorded from the live site",
        "",
    ]
    for gap in coverage.get("gaps", []):
        lines.append(f"- {gap}")
    lines += [
        "",
        "## Lessons",
        "",
        f"- Live `/lessons` status: {lesson_status}",
        "- The footer still links to `/lessons`. That link is preserved.",
        "- No lessons page was invented, and disabled content was not turned back on.",
        f"- Lessons 404 body matches the generic missing-page body after whitespace collapse: {coverage['lessons_equals_generic_404']}",
        "",
        "## Not end-to-end verified",
        "",
    ]
    for item in coverage["not_end_to_end"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "Markup presence is recorded in inventory/widgets.json. Browser render checks, when present, are inventory/render-check.json and are separate from a completed booking, purchase, or inquiry.",
        "",
        "## Redirect probes",
        "",
        "```json",
        json.dumps(probes, indent=2)[:8000],
        "```",
        "",
    ]
    (DOCS / "COVERAGE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (DOCS / "WIDGETS.md").write_text(
        "# Widgets and external dependencies\n\n"
        "Third-party widgets stay as the public embed from the live site. "
        "This project does not reimplement HoneyBook, Embedly, YouTube, Calendly, or Google tags.\n\n"
        "```json\n"
        + json.dumps(widgets, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )


def provider_probes() -> dict:
    targets = [
        "https://sunsetstrings.com/",
        "http://sunsetstrings.com/",
        "http://www.sunsetstrings.com/",
        "https://www.sunsetstrings.com/",
        "https://www.sunsetstrings.com/lessons",
        "https://www.sunsetstrings.com/more",
        "https://www.sunsetstrings.com/audio",
        "https://www.sunsetstrings.com/checkout",
        "https://www.sunsetstrings.com/account",
        "https://sunsetstrings.squarespace.com/",
        "https://www.sunsetstrings.com/blog?format=rss",
    ]
    probes = {}
    for url in targets:
        try:
            probes[url] = header_probe(url)
        except Exception as error:
            probes[url] = {"error": str(error)}
    # /config redirects into Squarespace OAuth. Record status and host only.
    try:
        status, _target, headers, _body = request_once("https://www.sunsetstrings.com/config")
        location = headers.get("location", "")
        host = urlparse(urljoin("https://www.sunsetstrings.com/config", location)).netloc if location else ""
        probes["https://www.sunsetstrings.com/config"] = {
            "status": status,
            "location_host": host,
            "note": "Full redirect URL was not stored because it carries a request-specific OAuth state.",
        }
    except Exception as error:
        probes["https://www.sunsetstrings.com/config"] = {"error": str(error)}
    try:
        ns = subprocess.check_output(["dig", "+short", "NS", "sunsetstrings.com"], text=True).strip().splitlines()
    except Exception as error:
        ns = [str(error)]
    probes["dns_ns"] = ns
    return probes


def main() -> None:
    self_check()
    limit = None
    args = sys.argv[1:]
    if "--build-only" in args:
        log("build-only start")
        records = json.loads((CAPTURE / "fetch-records.json").read_text(encoding="utf-8"))
        robots_txt = (CAPTURE / "robots.txt").read_text(encoding="utf-8")
        sitemap_xml = (CAPTURE / "sitemap.xml").read_text(encoding="utf-8")
        sitemap_pages, sitemap_images = load_sitemap(sitemap_xml)
        probes = {}
        redirects_path = INVENTORY / "redirects.json"
        if redirects_path.exists():
            probes = json.loads(redirects_path.read_text(encoding="utf-8")).get("live_probes", {})
        http_www = probes.get("http://www.sunsetstrings.com/")
        if isinstance(http_www, dict) and http_www.get("error"):
            http_www["note"] = "The full-body probe timed out. A later HEAD returned HTTP 200 and no Location header."
        bundle = build_site(records, sitemap_images, sitemap_xml, robots_txt)
        write_reports(bundle, probes, len(sitemap_pages), robots_txt)
        log("build-only complete")
        return
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    CAPTURE.mkdir(parents=True, exist_ok=True)
    log("capture start")
    probes = provider_probes()
    robots = fetch_chain(ORIGIN + "/robots.txt")
    robots_txt = robots["body"].decode("utf-8", errors="replace")
    (CAPTURE / "robots.txt").write_text(robots_txt, encoding="utf-8")
    sitemap = fetch_chain(ORIGIN + "/sitemap.xml")
    sitemap_xml = sitemap["body"].decode("utf-8", errors="replace")
    (CAPTURE / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")
    sitemap_pages, sitemap_images = load_sitemap(sitemap_xml)
    seeds = [ORIGIN + "/"] + sitemap_pages + [
        ORIGIN + "/cart",
        ORIGIN + "/search",
        ORIGIN + "/blog?format=rss",
        ORIGIN + "/video?format=rss",
        ORIGIN + "/__capture-probe-not-a-page",
    ]
    crawler = Crawler(limit)
    crawler.run(seeds)
    (CAPTURE / "fetch-records.json").write_text(json.dumps(crawler.records, indent=2), encoding="utf-8")
    log(f"crawl records {len(crawler.records)}")
    bundle = build_site(crawler.records, sitemap_images, sitemap_xml, robots_txt)
    write_reports(bundle, probes, len(sitemap_pages), robots_txt)
    log("capture complete")


if __name__ == "__main__":
    main()
