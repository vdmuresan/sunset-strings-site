/**
 * Request router for the Sunset Strings static copy.
 * Offline only. Keep in sync with functions/_middleware.js.
 *
 * ASSETS.fetch reads the static file and does not re-enter this worker.
 */

const RSS_FILES = {
  "/blog": "/feeds/blog.xml",
  "/video": "/feeds/video.xml",
};

function barePath(pathname) {
  const trimmed = pathname.replace(/\/+$/, "");
  return trimmed === "" ? "/" : trimmed;
}

function safeDecode(value) {
  try {
    return decodeURIComponent(value);
  } catch (_error) {
    return value;
  }
}

function encodePath(path) {
  return path
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function normalizeAssetPath(pathname) {
  const decoded = barePath(safeDecode(pathname));
  if (decoded.startsWith("/blog/tag/")) {
    return "/blog/tag/" + decoded.slice("/blog/tag/".length).replaceAll("+", " ");
  }
  return decoded;
}

export async function route(request, env) {
  const url = new URL(request.url);
  const path = barePath(url.pathname);

  if (path === "/lessons") {
    const asset = await env.ASSETS.fetch(new URL("/__status/lessons.html", url.origin));
    const headers = new Headers(asset.headers);
    headers.set("content-type", "text/html; charset=utf-8");
    headers.set("x-robots-tag", "noindex");
    headers.set("cache-control", "no-store");
    return new Response(asset.body, { status: 404, headers });
  }

  if (path === "/__status" || path.startsWith("/__status/")) {
    return new Response("Not found", {
      status: 404,
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "x-robots-tag": "noindex",
      },
    });
  }

  const keys = [...url.searchParams.keys()];
  if (url.searchParams.get("format") === "rss" && RSS_FILES[path] && keys.every((key) => key === "format")) {
    return env.ASSETS.fetch(new URL(RSS_FILES[path], url.origin));
  }

  const offset = url.searchParams.get("offset");
  if (offset && /^[0-9]+$/.test(offset) && keys.every((key) => key === "offset")) {
    return env.ASSETS.fetch(new URL(`${path}/__offset/${offset}/index.html`, url.origin));
  }

  const normalized = normalizeAssetPath(url.pathname);
  if (normalized !== path) {
    const rewritten = new URL(url);
    rewritten.pathname = encodePath(normalized);
    return env.ASSETS.fetch(new Request(rewritten, request));
  }

  return env.ASSETS.fetch(request);
}

export default {
  async fetch(request, env) {
    return route(request, env);
  },
};
