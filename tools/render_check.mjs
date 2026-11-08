import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const puppeteer = require("/tmp/ss-npm/node_modules/puppeteer-core");

const chrome = "/usr/local/bin/google-chrome";
const outDir = "/workspace/docs/screenshots";
const artifactDir = "/opt/cursor/artifacts";
fs.mkdirSync(outDir, { recursive: true });
fs.mkdirSync(artifactDir, { recursive: true });

const pages = ["/", "/contact", "/blog", "/quartet", "/video/v/canonind", "/lessons"];
const viewports = [
  { name: "desktop", width: 1440, height: 900, mobile: false },
  { name: "mobile", width: 390, height: 844, mobile: true },
];

function blocked(url, method) {
  const host = new URL(url).host;
  if (host.includes("google-analytics.com") || host.includes("doubleclick.net") || host.includes("googletagmanager.com")) {
    return "analytics blocked during render check";
  }
  if (method !== "GET" && method !== "HEAD" && (host.includes("honeybook.com") || host.includes("squarespace.com") || host.includes("calendly.com"))) {
    return "non-GET blocked";
  }
  return "";
}

async function shoot(browser, base, label) {
  const notes = [];
  for (const viewport of viewports) {
    for (const pagePath of pages) {
      const page = await browser.newPage();
      const requests = [];
      await page.setViewport({ width: viewport.width, height: viewport.height, isMobile: viewport.mobile, hasTouch: viewport.mobile });
      if (viewport.mobile) {
        await page.setUserAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1");
      }
      await page.setRequestInterception(true);
      page.on("request", (request) => {
        const reason = blocked(request.url(), request.method());
        if (reason) {
          requests.push({ url: request.url().slice(0, 180), method: request.method(), blocked: reason });
          request.abort().catch(() => {});
          return;
        }
        requests.push({ url: request.url().slice(0, 180), method: request.method(), blocked: "" });
        request.continue().catch(() => {});
      });
      const target = base.replace(/\/$/, "") + pagePath;
      let status = 0;
      try {
        const response = await page.goto(target, { waitUntil: "domcontentloaded", timeout: 45000 });
        status = response ? response.status() : 0;
        await new Promise((resolve) => setTimeout(resolve, pagePath === "/contact" || pagePath.startsWith("/video") ? 6000 : 2500));
      } catch (error) {
        notes.push({ page: pagePath, viewport: viewport.name, error: String(error).slice(0, 300), status });
        await page.close();
        continue;
      }
      const facts = await page.evaluate(() => {
        const iframes = [...document.querySelectorAll("iframe")].map((frame) => frame.src || frame.getAttribute("src") || "").slice(0, 12);
        const images = [...document.querySelectorAll("img")];
        const loaded = images.filter((img) => img.naturalWidth > 0).length;
        return {
          title: document.title,
          iframeCount: iframes.length,
          iframes,
          imageCount: images.length,
          loadedImages: loaded,
          honeybookNodes: document.querySelectorAll("[class*='hb-'], iframe[src*='honeybook'], [id*='honeybook']").length,
          formCount: document.querySelectorAll("form").length,
          textSample: (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 240),
        };
      });
      const safe = pagePath.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "home";
      const file = `${label}-${safe}-${viewport.name}.png`;
      await page.screenshot({ path: path.join(outDir, file) });
      if ((pagePath === "/" || pagePath === "/contact") && viewport.name === "desktop") {
        fs.copyFileSync(path.join(outDir, file), path.join(artifactDir, file));
      }
      notes.push({ page: pagePath, viewport: viewport.name, status, file, ...facts, requestCount: requests.length, hosts: [...new Set(requests.map((item) => { try { return new URL(item.url).host; } catch { return ""; } }).filter(Boolean))].sort() });
      await page.close();
    }
  }
  return notes;
}

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const report = { generated_at: new Date().toISOString(), analytics: "Google tag requests were aborted so the check would not send analytics.", submissions: "No forms were submitted and no non-GET requests to HoneyBook, Squarespace, or Calendly were sent.", local: [], live: [] };
try {
  report.local = await shoot(browser, "http://127.0.0.1:8765", "local");
  report.live = await shoot(browser, "https://www.sunsetstrings.com", "live");
} finally {
  await browser.close();
}
fs.writeFileSync("/workspace/inventory/render-check.json", JSON.stringify(report, null, 2));
console.log(JSON.stringify(report.local.map((item) => ({ page: item.page, viewport: item.viewport, status: item.status, images: item.loadedImages, honey: item.honeybookNodes, forms: item.formCount, iframes: item.iframeCount, error: item.error || "" })), null, 2));
console.log("--- live ---");
console.log(JSON.stringify(report.live.map((item) => ({ page: item.page, viewport: item.viewport, status: item.status, images: item.loadedImages, honey: item.honeybookNodes, forms: item.formCount, iframes: item.iframeCount, error: item.error || "" })), null, 2));
