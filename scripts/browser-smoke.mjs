/**
 * Headless-Chrome smoke test for CampusPilot AI (responsive sweep + main journey).
 *
 * Not a project dependency. Run from any scratch directory:
 *   mkdir -p /tmp/cp-e2e && cd /tmp/cp-e2e && npm i playwright-core@1.62.0
 *   BASE_URL=http://127.0.0.1:8000/ CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
 *     node /path/to/repo/scripts/browser-smoke.mjs
 * Requires a running backend serving the built frontend (IDENTITY_MODE=session, no Gemini key needed).
 */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const { chromium } = createRequire(process.cwd() + "/")("playwright-core");
const BASE = process.env.BASE_URL || "http://127.0.0.1:8000/";
const SHOTS = process.env.SHOTS_DIR || "shots";
mkdirSync(SHOTS, { recursive: true });
const out = [];
const log = (...a) => { out.push(a.join(" ")); console.log(...a); };
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });

async function smallTargets(page) {
  return page.evaluate(() => [...document.querySelectorAll("button, a, input, select, textarea, summary")]
    .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.height < 44 || r.width < 44) && getComputedStyle(el).visibility !== "hidden"; })
    .map((el) => `${el.tagName.toLowerCase()}:${(el.innerText || el.getAttribute("aria-label") || el.id || "").trim().slice(0, 30)} ${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`));
}
async function overflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

// 1. Responsive sweep on first-load screen
for (const w of [320, 360, 390, 430, 768, 1024, 1440]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: 860 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(BASE);
  await page.getByRole("button", { name: /Plan it/ }).waitFor();
  await page.waitForTimeout(300);
  log(`width ${w}: horizontal overflow=${await overflow(page)}px, console errors=${errors.length}`);
  await page.screenshot({ path: `${SHOTS}/home-${w}.png`, fullPage: true });
  await ctx.close();
}

// 2. Main journey on a phone viewport
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(BASE);
await page.getByRole("button", { name: /Plan it/ }).click();
log("empty submit error shown:", await page.getByText(/Describe what you want to get done/).isVisible());
await page.getByRole("button", { name: /Plan tomorrow's study \(demo\)/ }).click();
log("example filled, no request made yet:", (await page.getByRole("textbox").inputValue()).includes("2 hours of DBMS"));
await page.getByRole("button", { name: /Plan it/ }).click();
await page.getByRole("heading", { name: /Review these 2 changes|Review these 3 changes/ }).waitFor({ timeout: 10000 });
log("approval heading:", await page.getByRole("heading", { name: /Review these/ }).innerText());
log("proposed:", (await page.getByRole("list", { name: "Proposed changes" }).innerText()).replace(/\n/g, " | "));
log("overflow after plan:", await overflow(page));
log("small touch targets (plan view):", JSON.stringify(await smallTargets(page)));
await page.screenshot({ path: `${SHOTS}/journey-1-approval-390.png`, fullPage: true });
const approve = page.getByRole("button", { name: /Approve \d changes/ });
await approve.dblclick();
await page.getByText("What was saved").waitFor({ timeout: 10000 });
log("saved items:", (await page.getByText(/read back and verified$/).count()), "| Tried-N-times labels:", await page.getByText(/Tried \d times/).count(), "| stale text:", await page.getByText(/Nothing is saved until you approve/).count());
await page.screenshot({ path: `${SHOTS}/journey-2-done-390.png`, fullPage: true });
// count events persisted (via API with same cookie)
const wfs = await page.evaluate(async () => (await (await fetch("/api/agent/workflows")).json()));
log("workflows in history:", wfs.length, "latest status:", wfs[0]?.status);
const created = wfs[0].steps.filter((s) => s.kind === "write" && s.status === "completed").length;
log("completed writes (double-click must not duplicate):", created);
// Activity tab
await page.getByRole("navigation", { name: "Sections" }).getByRole("button", { name: /Activity/ }).click();
await page.getByRole("heading", { name: "Activity" }).waitFor();
await page.waitForTimeout(400);
await page.screenshot({ path: `${SHOTS}/journey-3-activity-390.png`, fullPage: true });
// Preferences tab
await page.getByRole("navigation", { name: "Sections" }).getByRole("button", { name: /Preferences/ }).click();
await page.getByRole("button", { name: /^Edit$/ }).click();
await page.getByLabel("Break (min)").fill("15");
await page.getByRole("button", { name: /Add subject timing/ }).click();
await page.getByRole("textbox", { name: "Subject 1" }).fill("DBMS");
await page.screenshot({ path: `${SHOTS}/journey-4-prefs-edit-390.png`, fullPage: true });
await page.getByRole("button", { name: /Save preferences/ }).click();
await page.getByText(/Saved and verified (in temporary|\.)/).waitFor();
log("prefs saved message:", await page.getByText(/Saved and verified (in temporary|\.)/).innerText());
await page.getByRole("button", { name: /Reset to defaults/ }).click();
log("reset dialog shown:", await page.getByRole("alertdialog").isVisible());
await page.screenshot({ path: `${SHOTS}/journey-5-reset-confirm-390.png`, fullPage: true });
await page.getByRole("button", { name: /Yes, reset preferences/ }).click();
await page.getByText(/reset to defaults and verified/).waitFor();
log("reset done");
// Chained preference flow on plan tab
await page.getByRole("navigation", { name: "Sections" }).getByRole("button", { name: /Plan/ }).click();
await page.getByRole("button", { name: /Remember a preference, then plan/ }).click();
await page.getByRole("button", { name: /Plan it/ }).click();
await page.getByRole("heading", { name: /Review these/ }).waitFor();
await page.getByRole("button", { name: /Reject all/ }).click();
await page.getByText("You rejected these changes").waitFor();
log("reject flow ok; rejected chips:", await page.getByText("Rejected", { exact: true }).count());
await page.screenshot({ path: `${SHOTS}/journey-6-rejected-390.png`, fullPage: true });
// Clarification
await page.getByRole("textbox").fill("help me study");
await page.getByRole("button", { name: /Plan it/ }).click();
await page.getByText("CampusPilot needs one more detail", { exact: true }).waitFor();
log("clarification shown");
// Keyboard: tab focus visibility
await page.keyboard.press("Tab");
const focusOutline = await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
log("focus outline style on first tab stop:", focusOutline, "->", await page.evaluate(() => document.activeElement.textContent?.trim().slice(0, 30)));
log("console errors during journey:", errors.length, JSON.stringify(errors.slice(0, 5)));

// 3. Desktop journey screenshot
const d = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const dp = await d.newPage();
await dp.goto(BASE);
await dp.getByRole("button", { name: /Plan tomorrow's study \(demo\)/ }).click();
await dp.getByRole("button", { name: /Plan it/ }).click();
await dp.getByRole("heading", { name: /Review these/ }).waitFor();
await dp.screenshot({ path: `${SHOTS}/desktop-approval-1440.png`, fullPage: true });
log("desktop Plan-it button height:", (await dp.getByRole("button", { name: /Plan it/ }).boundingBox()).height);
log("step 8 status:", await dp.locator("ol li").filter({ hasText: "Report completed schedule" }).first().innerText().then(t => t.split("\n").slice(0,3).join(" / ")));
log("desktop overflow:", await overflow(dp));
await browser.close();
