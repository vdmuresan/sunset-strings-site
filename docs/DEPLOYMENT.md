# Deployment notes

This is offline configuration for a later Cloudflare deploy. Nothing in this repository was deployed. The production domain, DNS, and Squarespace site were not changed. The Cloudflare account was not opened because connector authentication was still pending.

## What is ready

- `site/` is a static copy of the public site.
- `wrangler.toml` points a Worker static-assets project at `site/` and runs `worker/index.js` first.
- `functions/_middleware.js` is the same router for a Cloudflare Pages project whose build output is `site/`.
- `site/_redirects` repeats the in-site path aliases that returned redirects on the live host: `/more`, `/audio`, and `/checkout`.
- `site/_headers` repeats `X-Frame-Options: SAMEORIGIN` and `X-Content-Type-Options: nosniff`.

## Suggested project settings

Do not run these until the sanctioned connector is authenticated.

Worker static assets:

```bash
# review only; do not deploy from this archive step
npx wrangler deploy --dry-run
```

Pages:

- Root directory: repository root
- Build command: `python3 tools/validate_mirror.py`
- Build output directory: `site`

The copy is already built into `site/`. The build command only checks the checked-in files.

## Router behavior

`worker/index.js` and `functions/_middleware.js` must stay in sync.

- `/lessons` and `/lessons/` respond `404` with `site/__status/lessons.html`. There is no public `200` lessons page.
- `/__status/*` responds `404` so the stored lessons body is not a normal page.
- `/blog?offset=<digits>` and `/video?offset=<digits>` serve `site/blog/__offset/<digits>/index.html` and the video equivalent.
- `/blog?format=rss` and `/video?format=rss` serve `site/feeds/blog.xml` and `site/feeds/video.xml`.
- Other requests serve files under `site/`.

## Production redirects that are not in `_redirects`

These are hostname rules on the current edge. They must not be copied onto a preview hostname.

| Request | Live result |
| --- | --- |
| `https://sunsetstrings.com/` | `301` to `https://www.sunsetstrings.com/` |
| `http://sunsetstrings.com/` | `301` to `http://www.sunsetstrings.com/` |
| `http://www.sunsetstrings.com/` | `200` over HTTP, not upgraded by this capture |
| `https://www.sunsetstrings.com/contact` and `/contact/` | both `200` |
| `https://sunsetstrings.squarespace.com/` | `200` from Squarespace, canonical `https://www.sunsetstrings.com` |

HSTS on the live HTTPS responses is `max-age=15552000`. It is not set in `site/_headers`, so a temporary preview host is not pinned.

## Canonical tags

Canonical, Open Graph, and Twitter URL tags still point at `https://www.sunsetstrings.com`. Anchor links inside the pages were rewritten to root-relative paths so browsing the copy stays on the copy. Squarespace's `static-context` JSON still names the production host, so platform JavaScript can still call the live Squarespace site. That coupling is unresolved until a real cutover, which this work does not perform.

`site/robots.txt` is the live robots file, including `Sitemap: https://www.sunsetstrings.com/sitemap.xml`. Before any public preview on a non-production hostname, replace it with `deploy/robots.preview-noindex.txt` or put the preview behind Cloudflare Access. Access was not configured.

## Launch steps still required

1. Authenticate the Cloudflare connector. Do not use another hosting account as a workaround.
2. Choose Worker static assets or Pages, using the settings above.
3. Decide whether the preview is private. If it is public, swap in the preview robots file before the first deploy.
4. Review widget dependencies in `docs/WIDGETS.md` and `inventory/render-check.json`. HoneyBook, YouTube/Embedly, Google tags, and Squarespace JavaScript still load from their own hosts.
5. Do not change production DNS, do not cancel Squarespace, and do not point `sunsetstrings.com` at this copy until those dependencies are accepted.
6. Cart and account surfaces post against Squarespace. Do not submit them from a preview.

## Local checks

```bash
python3 tools/validate_mirror.py
python3 tools/serve_mirror.py --port 8765
```

`validate_mirror.py` checks files and, when the server is already running, HTTP status for `/`, `/contact`, `/lessons`, and `/more`. It does not submit forms.
