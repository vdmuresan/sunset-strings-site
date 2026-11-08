# sunset-strings-site

Sunset Strings Inc. website - static rebuild on Cloudflare Pages

This branch is a public capture of the live site at <https://www.sunsetstrings.com>, taken on 2026-11-08. It is a copy for a later Cloudflare deploy. It is not a redesign, not a HoneyBook or Airtable migration, and not a DNS cutover.

Production was not changed. The Cloudflare account was not opened. No inquiry, purchase, booking, or account was submitted.

## Provider

The live HTML says Squarespace (`<!-- This is Squarespace. -->`, site id `62f69923e0afe00d7b94a0aa`). The canonical URL is `https://www.sunsetstrings.com`.

Public DNS for `sunsetstrings.com` is Cloudflare (`dee.ns.cloudflare.com`, `devin.ns.cloudflare.com`). HTTPS responses include `server: cloudflare`. `https://sunsetstrings.squarespace.com/` answers with `server: Squarespace` and the same canonical URL. Whether the Cloudflare zone is the customer's or Squarespace's edge was not checked in an account.

| Request | Live result |
| --- | --- |
| `https://sunsetstrings.com/` | 301 to `https://www.sunsetstrings.com/` |
| `http://sunsetstrings.com/` | 301 to `http://www.sunsetstrings.com/` |
| `http://www.sunsetstrings.com/` | 200 over HTTP. A later HEAD confirmed this. The full-body probe timed out once. |
| `https://www.sunsetstrings.com/contact` and `/contact/` | both 200 |
| `https://www.sunsetstrings.com/lessons` | 404 |

HTTPS responses send HSTS `max-age=15552000`. That header is not copied onto this static project.

## What was captured

- Sitemap: 211 URLs. Every sitemap URL was fetched. `/lessons` is in the sitemap and returns 404.
- Unique HTML files in `site/`: 219, including 63 blog tag indexes and 2 blog list pages with `?offset=`.
- Video items: 75. RSS feeds: `site/feeds/blog.xml` (20 items) and `site/feeds/video.xml` (20 items). The feeds are the live Squarespace feeds, not the full archive. The full post and video HTML is in `site/`.
- Localized images: 908 files. Two URL failures are a CSS `url(#check)` fragment and a scripts directory, not photographs.
- Localized CSS: 15 files. Fonts: 32 files.
- Squarespace visitor JavaScript: 33 archival copies in `capture/platform-js/`. The pages still load those scripts from the Squarespace CDN.

Raw responses are gzipped in `capture/raw/`. Counts, hashes, and timestamps are in `inventory/`.

`/lessons` stays a 404. The live 404 body is the contact page, and that body is preserved at `site/__status/lessons.html`. The footer link to Lessons is unchanged. Disabled lessons content was not turned back on.

Tag indexes are the first page only. Later tag pages use `?tag=`, which `robots.txt` disallows, so they were not fetched. `reversePaginate` was not fetched for the same reason. `?format=json` was not requested. The individual posts are still in the sitemap capture.

`/search` is disallowed by robots.txt. The empty search shell was captured because it is a public page, and that exception is recorded. `/account` and `/config` were not saved. `/account` redirects into the Squarespace login UI. `/config` redirects toward Squarespace login; the OAuth state value was not stored.

## Widgets

These are the live embeds. Their private implementations were not copied.

| Widget | Where | Public id | Render check |
| --- | --- | --- | --- |
| HoneyBook contact form | `/contact` embed block | placement `5e4c55e6a1d8be08fef5603e` | Iframe from `public.honeybook.com` measured 1324.8×1878 px on the local copy and the live site. Fields were visible. Not submitted. |
| SoundCloud players | `/quartet`, `/trio`, `/duo`, `/violin`, `/electric` | playlist ids `1484783224`, `1484790292`, `1484796079`, `1484808520`, `1484812795` | Quartet waveform rendered. Playback was not started. Share tokens stay inside the original iframes. |
| YouTube via Embedly | video items, including `/video/v/canonind` | YouTube id `FZvErefzATI` on that page; 69 ids in inventory | Poster and play button rendered. Playback was not started. |
| Google Tag Manager and GA4 | site-wide | `GTM-P32B4CX`, `G-C2F9D4EDFB` | Tags are in the HTML. Requests were blocked during the render check, so collection was not verified. |
| reCAPTCHA Enterprise | Squarespace context | site key `6LdDFQwjAAAAAPigEvvPgEVbb7QBm-TkVJdDTlAv` | Public site key only. |
| Calendly profile | social profile JSON | `https://calendly.com/sunsetstrings,` | The trailing comma is in the live JSON and was not changed. No booking was made. |
| Social links | header/footer data | Instagram `instagram.com/sunsetstringsmusic`, Facebook, LinkedIn, Pinterest, YouTube `@sunsetstringsmusic`, X `@sunsetstrings` | Links preserved. |

Squarespace commerce cart (`/cart`, and `/checkout` redirecting to it) is included and still depends on Squarespace. It was not used.

## Checks

```bash
python3 tools/capture_public_site.py
python3 tools/capture_public_site.py --build-only
python3 tools/validate_mirror.py
python3 tools/serve_mirror.py --port 8765
node tools/render_check.mjs
```

Results from this capture:

- `capture_public_site.py` completed with exit 0. The follow-up `--build-only` completed with exit 0 after image redirects and tag URLs were corrected.
- `validate_mirror.py` completed with exit 0, including HTTP checks against `127.0.0.1:8765`: `/` 200, `/contact` contains the HoneyBook placement id, `/lessons` 404, `/more` redirects to `/blog`.
- 20,199 internal `href` values resolved to a file, a known redirect (`/more`, `/audio`, `/checkout`), or `/lessons`.
- Desktop and mobile screenshots of the live site and the local copy are in `docs/screenshots/`.

## Deploy

See `docs/DEPLOYMENT.md`. `wrangler.toml` and `functions/_middleware.js` are offline config only. Do not deploy until the sanctioned Cloudflare connector is authenticated. Do not use another host as a workaround. Do not change production DNS.

Before a public preview on a hostname other than `www.sunsetstrings.com`, replace `site/robots.txt` with `deploy/robots.preview-noindex.txt` or put the preview behind Cloudflare Access. Canonical tags still point at production on purpose.

This copy is not ready for a production cutover. Page HTML, CSS, images, and fonts are local. Squarespace JavaScript, HoneyBook, SoundCloud, YouTube/Embedly, and Google tags still have to answer at view time. Cart, checkout, and accounts are not independent.

## Copyright

Page copy, photographs, and credits stay as they were published, including photographer names already in captions and filenames. This archive does not claim Squarespace's platform CSS or JavaScript, HoneyBook, SoundCloud, YouTube, Embedly, Google, or the upstream font designs. Font files were saved from the URLs the live pages request so the pages can render.
