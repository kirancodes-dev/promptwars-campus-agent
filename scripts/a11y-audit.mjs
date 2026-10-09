/**
 * Not a project dependency. Run from a scratch directory that has playwright-core (and axe-core for the audit):
 *   mkdir -p /tmp/cp-e2e && cd /tmp/cp-e2e && npm i playwright-core@1.62.0 axe-core@4.10.3
 *   BASE_URL=http://127.0.0.1:8000/ node /path/to/repo/scripts/a11y-audit.mjs
 * CHROME_PATH overrides the Chrome binary. The audit bypasses CSP in the test browser only, to inject axe.
 */
import { createRequire } from "node:module";
const require = createRequire(process.cwd() + "/");
const { chromium } = require("playwright-core");
const axeSource = require("fs").readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const BASE = process.env.BASE_URL;
const b = await chromium.launch({ executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const results = {};
async function audit(page, label) {
  await page.addScriptTag({ content: axeSource });
  const r = await page.evaluate(async () => await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] } }));
  results[label] = r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help, sample: v.nodes[0]?.target?.join(" ") }));
  console.log(`\n[${label}] violations: ${r.violations.length}, passes: ${r.passes.length}, incomplete (needs manual check): ${r.incomplete.length}`);
  for (const v of results[label]) console.log(`  - ${v.impact} ${v.id} (${v.nodes}x): ${v.help} — e.g. ${v.sample}`);
  for (const v of r.incomplete) console.log(`  ? manual check: ${v.id} (${v.nodes.length}x) — ${v.help}`);
}
for (const [w, h] of [[390, 844], [1440, 1000]]) {
  const p = await (await b.newContext({ viewport: { width: w, height: h }, bypassCSP: true })).newPage();
  await p.goto(BASE); await p.getByRole("button", { name: /Plan it/ }).waitFor();
  await audit(p, `${w}px home`);
  await p.getByRole("button", { name: /Plan tomorrow's study \(demo\)/ }).click();
  await p.getByRole("button", { name: /Plan it/ }).click();
  await p.getByRole("heading", { name: /Review these/ }).waitFor();
  await audit(p, `${w}px plan + approval`);
  await p.getByRole("button", { name: /Approve \d changes/ }).click();
  await p.getByText("What was saved").waitFor();
  await audit(p, `${w}px completed`);
  if (w === 390) {
    await p.getByRole("navigation", { name: "Sections" }).getByRole("button", { name: /Preferences/ }).click();
    await p.getByRole("button", { name: /^Edit$/ }).click();
    await audit(p, `${w}px preferences edit`);
    await p.getByRole("button", { name: /^Cancel$/ }).click();
    await p.getByRole("button", { name: /Reset to defaults/ }).click();
    await audit(p, `${w}px reset dialog`);
    await p.getByRole("navigation", { name: "Sections" }).getByRole("button", { name: /Activity/ }).click();
    await audit(p, `${w}px activity`);
  }
}
{
  const p = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  await p.goto(BASE); await p.getByRole("button", { name: /Plan it/ }).waitFor();
  await p.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
  await p.waitForTimeout(200);
  const over = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log(`\n[390px, text at 200%] horizontal overflow: ${over}px`);
}
require("fs").writeFileSync(process.env.OUT || "a11y-results.json", JSON.stringify(results, null, 2));
await b.close();
