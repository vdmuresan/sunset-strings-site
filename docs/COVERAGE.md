# Sunset Strings public-site capture

Generated 2026-11-08T23:44:52Z from https://www.sunsetstrings.com.

## Counts

- Sitemap page URLs: 211
- Saved HTTP 200 HTML routes: 262
- Saved HTTP 404 responses: 3
- RSS feeds saved: 2
- Deployable route files, excluding the lessons 404 body: 262
- Localized image records: 908, stored as 780 unique files. Sixty-nine records are the Squarespace no-image placeholder.
- Image download failures: 2
- Localized CSS files: 15
- Localized font files: 32
- Platform script archival copies: 33

## Gaps recorded from the live site

- Live /lessons returns 404. The footer link is preserved. No lessons content was invented.
- robots.txt disallows ?tag= and reversePaginate. First-page tag indexes were captured; later tag pages and reverse pagination were not.
- robots.txt disallows /search. The empty search shell was still captured and flagged because it is a public page.
- format=json was not requested.
- /account redirects into the Squarespace login UI. That flow was not mirrored and no account was created.
- /config redirects toward Squarespace login. Only the status and host were recorded.
- Squarespace visitor JavaScript, HoneyBook, Embedly, YouTube, Calendly, and Google tags stay on their original hosts.

## Lessons

- Live `/lessons` status: 404
- The footer still links to `/lessons`. That link is preserved.
- No lessons page was invented, and disabled content was not turned back on.
- Lessons 404 body matches the generic missing-page body after whitespace collapse: False

## Not end-to-end verified

- HoneyBook form submission
- Squarespace commerce cart and checkout
- Calendly booking
- YouTube playback beyond embed markup
- Google Analytics / Tag Manager collection
- Squarespace customer account login

Markup presence is recorded in inventory/widgets.json. Browser render checks, when present, are inventory/render-check.json and are separate from a completed booking, purchase, or inquiry.

## Redirect probes

```json
{
  "https://sunsetstrings.com/": {
    "requested": "https://sunsetstrings.com/",
    "status": 200,
    "final_url": "https://www.sunsetstrings.com/",
    "content_type": "text/html;charset=utf-8",
    "chain": [
      {
        "url": "https://sunsetstrings.com/",
        "status": 301,
        "location": "https://www.sunsetstrings.com/",
        "content_type": ""
      },
      {
        "url": "https://www.sunsetstrings.com/",
        "status": 200,
        "location": "",
        "content_type": "text/html;charset=utf-8"
      }
    ],
    "x_robots": ""
  },
  "http://sunsetstrings.com/": {
    "error": "timed out"
  },
  "http://www.sunsetstrings.com/": {
    "error": "timed out",
    "note": "The full-body probe timed out. A later HEAD returned HTTP 200 and no Location header."
  },
  "https://www.sunsetstrings.com/": {
    "requested": "https://www.sunsetstrings.com/",
    "status": 200,
    "final_url": "https://www.sunsetstrings.com/",
    "content_type": "text/html;charset=utf-8",
    "chain": [
      {
        "url": "https://www.sunsetstrings.com/",
        "status": 200,
        "location": "",
        "content_type": "text/html;charset=utf-8"
      }
    ],
    "x_robots": ""
  },
  "https://www.sunsetstrings.com/lessons": {
    "requested": "https://www.sunsetstrings.com/lessons",
    "status": 404,
    "final_url": "https://www.sunsetstrings.com/lessons",
    "content_type": "text/html;charset=utf-8",
    "chain": [
      {
        "url": "https://www.sunsetstrings.com/lessons",
        "status": 404,
        "location": "",
        "content_type": "text/html;charset=utf-8"
      }
    ],
    "x_robots": ""
  },
  "https://www.sunsetstrings.com/more": {
    "requested": "https://www.sunsetstrings.com/more",
    "status": 200,
    "final_url": "https://www.sunsetstrings.com/blog",
    "content_type": "text/html;charset=utf-8",
    "chain": [
      {
        "url": "https://www.sunsetstrings.com/more",
        "status": 302,
        "location": "https://www.sunsetstrings.com/blog",
        "content_type": ""
      },
      {
        "url": "https://www.sunsetstrings.com/blog",
        "status": 200,
        "location": "",
        "content_type": "text/html;charset=utf-8"
      }
    ],
    "x_robots": ""
  },
  "https://www.sunsetstrings.com/audio": {
    "requested": "https://www.sunsetstrings.com/audio",
    "status": 200,
    "final_url": "https://www.sunsetstrings.com/quartet",
    "content_type": "text/html;charset=utf-8",
    "chain": [
      {
        "url": "https://www.sunsetstrings.com/audio",
        "status": 302,
        "location": "https://www.sunsetstrings.com/quartet",
        "content_type": ""
      },
      {
        "url": "https://www.sunsetstrings.com/quartet",
        "status": 200,
        "location": "",
        "content_type": "text/html;charset=utf-8"
      }
    ],
    "x_robots": ""
  },
  "https://www.sunsetstrings.com/checkout": {
    "requested": "https://www.sunsetstrings.com/checkout",
    "status": 200,
    "final_url": "https://www.sunsetstrings.com/cart",
    "content_type": "text/html;charset=utf-8",
    "chain": [
      {
        "url": "https://www.sunsetstrings.com/checkout",
        "status": 302,
        "location": "https://www.sunsetstrings.com/cart",
        "content_type": ""
      },
      {
        "url": "https://www.sunsetstrings.com/cart",
        "status": 200,
        "location": "",
        "content_type": "text/html;charset=utf-8"
      }
    ],
    "x_robots": ""
  },
  "https://www.sunsetstrings.com/account": {
    "requested": "https://www.sunsetstrings.com/account",
    "status": 200,
    "final_url": "https://www.sunsetstrings.com/?userAccountPath=&noredirect=&redacted=1",
    "content_type": "text/html;charset=utf-8",
    "chain": [
      {
        "url": "https://www.sunsetstrings.com/account",
        "status": 307,
        "location": "https://www.sunsetstrings.com/?userAccountPath=&noredirect=&redacted=1",
        "content_type": "text/html;charset=utf-8"
      },
      {
        "url": "https://www.sunsetstrings.com/?userAccountPath=&noredirect=&redacted=1",
        "status": 200,
        "location": "",
        "content_type": "text/html;charset=utf-8"
      }
    ],
    "x_robots": ""
  },
  "https://sunsetstrings.squarespace.com/": {
    "requested": "https://sunsetstrings.squarespace.com/",
    "status": 200,
    "final_url": "https://sunsetstrings.squarespace.com/",
    "content_type": "text/html;charset=utf-8",
    "chain": [
      {
        "url": "https://sunsetstrings.squarespace.com/",
        "status": 200,
        "location": "",
        "content_type": "text/html;charset=utf-8"
      }
    ],
    "x_robots": ""
  },
  "https://www.sunsetstrings.com/blog?format=rss": {
    "requested": "https://www.sunsetstrings.com/blog?format=rss",
    "status": 200,
    "final_url": "https://www.sunsetstrings.com/blog?format=rss",
    "content_type": "application/rss+xml; charset=UTF-8",
    "chain": [
      {
        "url": "https://www.sunsetstrings.com/blog?format=rss",
        "status": 200,
        "location": "",
        "content_type": "application/rss+xml; charset=UTF-8"
      }
    ],
    "x_robots": ""
  },
  "https://www.sunsetstrings.com/config": {
    "status": 302,
    "location_host": "www.sunsetstrings.com",
    "note": "Full redirect URL was not stored because it carries a request-specific OAuth state."
  },
  "dns_ns": [
    "dee.ns.cloudflare.com.",
    "devin.ns.cloudflare.com."
  ]
}
```


## Browser render check

Captured 2026-11-08 with headless Chrome. Google tag requests were aborted. No form was submitted and no playback or booking was started.

Checked `/`, `/contact`, `/blog`, `/quartet`, `/video/v/canonind`, and `/lessons` at 1440x900 and 390x844, on the local copy and on the live site.

- Image load counts matched on every checked page. The homepage loaded 5 of 50 images in the first viewport on both, which is the live lazy-load behavior.
- Contact HoneyBook iframe measured 1324.8 by 1878 pixels on both. The local form showed the event date, name, email, phone, and venue fields. It was not submitted.
- Quartet SoundCloud player drew the waveform for "A Thousand Years - Sunset Strings Quartet". Playback was not started.
- Canon in D showed the YouTube poster and play button through the Embedly iframe. Playback was not started.
- `/lessons` returned HTTP 404 on both. The 404 body is the contact page, including the HoneyBook form. No lessons page was added.

Screenshots are in `docs/screenshots/`. Details are in `inventory/render-check.json`.
