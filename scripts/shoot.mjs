// Render docs/index.html in headless Chrome and save every [data-shot] card as charts/<name>.png, plus the full page.
// Usage: node scripts/shoot.mjs   (needs google-chrome on PATH and internet for the font + ECharts CDN)
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { tmpdir } from "node:os";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const port = 9334, W = 1280, SCALE = 2;
const chrome = spawn(process.env.CHROME || "google-chrome", ["--headless=new", "--no-sandbox", "--disable-gpu", `--remote-debugging-port=${port}`,
  `--user-data-dir=${tmpdir()}/kv-shoot`, "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let tabs;
for (let i = 0; i < 60 && !tabs; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch { await sleep(250); } }
const ws = new WebSocket(tabs.find(t => t.type === "page").webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pend = {};
ws.onmessage = e => { const m = JSON.parse(e.data); if (pend[m.id]) { pend[m.id](m.result); delete pend[m.id]; } };
const cmd = (method, params = {}) => new Promise(r => { pend[++id] = r; ws.send(JSON.stringify({ id, method, params })); });
const js = async expr => (await cmd("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.value;

await cmd("Emulation.setDeviceMetricsOverride", { width: W, height: 900, deviceScaleFactor: SCALE, mobile: false });
await cmd("Page.navigate", { url: pathToFileURL(resolve(root, "docs/index.html")).href });
for (let i = 0; i < 80 && !(await js("!!(window.echarts && document.fonts && document.fonts.status === 'loaded')")); i++) await sleep(250);
await js("document.querySelector('.top').style.position = 'static'; Object.values(echarts).length");
await sleep(800);
const H = await js("document.documentElement.scrollHeight");
await cmd("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: SCALE, mobile: false });
await js("dispatchEvent(new Event('resize'))");
await sleep(800);
mkdirSync(resolve(root, "charts"), { recursive: true });
const cards = await js(`[...document.querySelectorAll('[data-shot]')].map(e => { const r = e.getBoundingClientRect();
  return { name: e.dataset.shot, x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height }; })`);
const shot = async (file, clip) => writeFileSync(file, Buffer.from((await cmd("Page.captureScreenshot",
  { format: "png", captureBeyondViewport: true, ...(clip ? { clip: { ...clip, scale: 1 } } : {}) })).data, "base64"));
for (const c of cards) {
  await shot(resolve(root, `charts/${c.name}.png`), { x: c.x - 6, y: c.y - 6, width: c.w + 12, height: c.h + 12 });
  console.log("charts/" + c.name + ".png");
}
await shot(resolve(root, "docs/preview.png"), { x: 0, y: 0, width: W, height: H });
console.log("docs/preview.png", W, "x", H);
chrome.kill();
process.exit(0);
