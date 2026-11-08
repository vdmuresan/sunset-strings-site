# Sunset Strings capture summary

Date: 2026-11-08. Source: https://www.sunsetstrings.com. Branch: `cursor/live-site-capture-d39b`.

The live site is Squarespace (site id `62f69923e0afe00d7b94a0aa`) served on the canonical host `https://www.sunsetstrings.com`. DNS nameservers are Cloudflare. HTTPS is fronted by an edge that identifies itself as Cloudflare. `https://sunsetstrings.squarespace.com/` identifies itself as Squarespace and canonicalizes to www. The Cloudflare account was not accessed. Production DNS was not changed.

## Status

The static copy builds and the checked pages render. It is not ready to replace production.

`python3 tools/validate_mirror.py` exited 0. The capture script and the later `--build-only` pass exited 0.

## Counts

- Sitemap URLs: 211, all fetched. `/lessons` returns 404.
- HTML files in `site/`: 219.
- Blog tag indexes: 63 first pages. Later `?tag=` pages were not fetched because robots.txt disallows them.
- Blog offsets captured: 2. Video items: 75. RSS feeds: 2, each with 20 items.
- Images: 908 local files. Fonts: 32. CSS files: 15.
- Squarespace platform scripts archived, not served: 33.
- Internal link check: 20,199 hrefs accounted for.

## Widgets

- HoneyBook placement `5e4c55e6a1d8be08fef5603e` on `/contact`. The form iframe rendered at the same size as live. Not submitted.
- SoundCloud playlists on quartet, trio, duo, violin, and electric. Quartet waveform rendered. Not played. Share tokens remain only in the original iframes.
- YouTube `FZvErefzATI` through Embedly on `/video/v/canonind`, plus 68 other YouTube ids. Poster rendered. Not played.
- Google Tag Manager `GTM-P32B4CX` and GA4 `G-C2F9D4EDFB`. Present in HTML. Not allowed to collect during the render check.
- Calendly profile is published as `https://calendly.com/sunsetstrings,` with the trailing comma. Not booked.
- `/lessons` is still a 404 whose body is the contact page. Lessons content was not reactivated.

## Still required before launch

1. Authenticate the Cloudflare connector and deploy from `wrangler.toml` or Pages with output directory `site/`. No other host.
2. Keep the preview private, or swap in `deploy/robots.preview-noindex.txt`.
3. Accept that Squarespace JavaScript, HoneyBook, SoundCloud, YouTube, and Google tags remain remote dependencies.
4. Do not point production DNS at this copy and do not cancel Squarespace as part of this work.

Screenshots: `docs/screenshots/`. Inventory: `inventory/`. Deploy notes: `docs/DEPLOYMENT.md`.
