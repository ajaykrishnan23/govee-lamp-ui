// shot.mjs - give the agent eyes. Turn a running page into a PNG AND pipe
// console/page errors back as text (the error text is often the bigger half
// of the value: a blank screenshot says nothing, a stack trace says everything).
//
// Setup (once):   npm i -D playwright && npx playwright install chromium
// Serve first:    npx serve .   (or: python3 -m http.server 5173)
// Then shoot:     node shot.mjs /settings 390x844
//                 node shot.mjs / 1280x800
//
// Loop: write code -> shoot -> Read tmp/shot.png -> say what's wrong in words
// -> fix -> repeat. Shoot 390-wide AND 1280-wide. Cap at ~3 rounds, then show a human.

import { chromium } from '../web/node_modules/playwright/index.mjs';
import { mkdirSync } from 'node:fs';

const [path = '/', size = '1280x800'] = process.argv.slice(2);
const [width, height] = size.split('x').map(Number);
const base = process.env.SHOT_BASE ?? 'https://localhost:8443';

mkdirSync('tmp', { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width, height }, ignoreHTTPSErrors: true });
const page = await ctx.newPage();
// optional: log in first (lamp app)
if (process.env.SHOT_PASSWORD) {
  await page.request.post(`${base}/login`, { data: { password: process.env.SHOT_PASSWORD } });
}

const errors = [];
page.on('console', m => m.type() === 'error' && errors.push(`[console] ${m.text()}`));
page.on('pageerror', e => errors.push(`[pageerror] ${e.message}`));
page.on('requestfailed', r => errors.push(`[requestfailed] ${r.url()} ${r.failure()?.errorText ?? ''}`));

try {
  // 'networkidle' never fires with an open EventSource, so wait for load + a beat
  await page.goto(`${base}${path}`, { waitUntil: 'load', timeout: 15000 });
  await page.waitForTimeout(Number(process.env.SHOT_WAIT ?? 1200));
  if (process.env.SHOT_EVAL) await page.evaluate(process.env.SHOT_EVAL);
  await page.waitForTimeout(300);
} catch (e) {
  errors.push(`[goto] ${e.message}`);
}

const out = `tmp/shot${path.replace(/\W+/g, '_')}_${width}.png`;
await page.screenshot({ path: out, fullPage: true });
await browser.close();

console.log(`wrote ${out}`);
console.log(errors.length ? `\n--- errors ---\n${errors.join('\n')}` : 'no console errors');

// Native macOS (PR Watch-style) equivalent: build to a simulator, then
//   xcrun simctl io booted screenshot tmp/shot.png
// HTML doc/deck: serve the file and shoot each slide/section URL.
