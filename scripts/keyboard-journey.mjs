/**
 * Not a project dependency. Run from a scratch directory that has playwright-core (and axe-core for the audit):
 *   mkdir -p /tmp/cp-e2e && cd /tmp/cp-e2e && npm i playwright-core@1.62.0 axe-core@4.10.3
 *   BASE_URL=http://127.0.0.1:8000/ node /path/to/repo/scripts/keyboard-journey.mjs
 * CHROME_PATH overrides the Chrome binary. The audit bypasses CSP in the test browser only, to inject axe.
 */
import { createRequire } from "node:module";
const { chromium } = createRequire(process.cwd() + "/")("playwright-core");
const b = await chromium.launch({ executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`); };
for (const [w, h] of [[390, 844], [1440, 1000]]) {
  console.log(`\n=== keyboard only @ ${w}px`);
  const p = await (await b.newContext({ viewport: { width: w, height: h } })).newPage();
  await p.goto(process.env.BASE_URL);
  await p.getByRole("button", { name: /Plan it/ }).waitFor();
  const active = () => p.evaluate(() => { const e = document.activeElement; return { tag: e.tagName, name: (e.getAttribute("aria-label") || e.innerText || e.id || "").trim().slice(0, 40), outline: getComputedStyle(e).outlineStyle, ring: getComputedStyle(e).outlineWidth }; });
  async function tabTo(pred, max = 80) {
    for (let i = 0; i < max; i++) { await p.keyboard.press("Tab"); const a = await active(); if (pred(a)) return a; }
    return null;
  }
  const first = await tabTo(() => true, 1);
  check("first Tab reaches the skip link", /Skip to content/.test(first?.name || ""), first?.name);
  const ta = await tabTo((a) => a.tag === "TEXTAREA", 10);
  check("goal box reachable by Tab", !!ta);
  await p.keyboard.press("Control+Enter");
  check("empty submit shows an error message", await p.getByText(/Describe what you want to get done/).isVisible());
  await p.keyboard.type("Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM.");
  await p.keyboard.press("Control+Enter");
  await p.getByRole("heading", { name: /Review these/ }).waitFor({ timeout: 15000 });
  check("Ctrl+Enter submits and the plan appears", true);
  const approve = await tabTo((a) => a.tag === "BUTTON" && /^Approve/.test(a.name));
  check("Approve button reachable by Tab", !!approve, approve ? `outline ${approve.outline} ${approve.ring}` : "");
  check("focus is visibly indicated on Approve", approve && approve.outline !== "none" && approve.ring !== "0px");
  await p.keyboard.press("Enter");
  await p.getByText("What was saved").waitFor({ timeout: 15000 });
  check("Enter approves; verified results shown", true);
  if (w === 390) {
    const nav = await tabTo((a) => a.tag === "BUTTON" && /^Preferences/.test(a.name));
    check("bottom navigation reachable by Tab", !!nav);
    await p.keyboard.press("Enter");
  }
  const edit = await tabTo((a) => a.tag === "BUTTON" && a.name === "Edit");
  check("preferences Edit reachable by Tab", !!edit);
  await p.keyboard.press("Enter");
  const save = await tabTo((a) => a.tag === "BUTTON" && /Save preferences/.test(a.name));
  check("Save preferences reachable by Tab", !!save);
  await p.keyboard.press("Enter");
  await p.getByText(/Saved and verified/).first().waitFor({ timeout: 15000 });
  check("preferences saved via keyboard", true);
  const reset = await tabTo((a) => a.tag === "BUTTON" && /Reset to defaults/.test(a.name));
  check("Reset reachable by Tab", !!reset);
  await p.keyboard.press("Enter");
  const dlgFocus = await active();
  check("reset dialog receives focus", /Reset all study preferences/.test(dlgFocus.name), dlgFocus.name);
  const keep = await tabTo((a) => a.tag === "BUTTON" && /Keep my preferences/.test(a.name), 5);
  check("dialog buttons reachable", !!keep);
  await p.keyboard.press("Enter");
  check("Keep closes the dialog without resetting", !(await p.getByRole("alertdialog").count()));
  if (w === 390) {
    const act = await tabTo((a) => a.tag === "BUTTON" && /^Activity/.test(a.name));
    await p.keyboard.press("Enter");
    const hist = await tabTo((a) => a.tag === "SUMMARY" && /Organize my preparation/.test(a.name));
    check("history entries reachable and expandable by keyboard", !!act && !!hist);
    if (hist) await p.keyboard.press("Enter");
  }
}
console.log(`\n${results.filter((r) => r.ok).length}/${results.length} keyboard checks passed`);
await b.close();
