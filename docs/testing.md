# Testing

All results below were produced in the development environment on 2026-10-09 (macOS, Python 3.12.13, Node 20.20.2, Chrome headless via playwright-core 1.62.0).

## Commands

```bash
# Backend — 251 tests (unittest; no network, Gemini and Firestore are mocked)
cd backend
./.venv/bin/python -m unittest discover -s . -p "test_*.py"

# Frontend — 21 tests, lint, production build
cd frontend
npm ci
npm test
npm run lint
npm run build

# Browser smoke test (optional; needs Chrome and a running backend serving frontend/dist)
mkdir -p /tmp/cp-e2e && cd /tmp/cp-e2e && npm i playwright-core@1.62.0
BASE_URL=http://127.0.0.1:8000/ node /path/to/repo/scripts/browser-smoke.mjs
```

`api/test_agent.py::test_frontend_routes_served` is skipped (not failed) when `frontend/dist` has not been built.

## Backend coverage

| Suite | What it covers |
|---|---|
| `tools/test_tasks.py`, `test_schedule.py`, `test_notes.py` | CRUD, validation, not-found errors, note search |
| `tools/test_smart_schedule.py` | Conflict detection (exact, partial, containing, adjacent), free-slot search, flagship 8-step plan order, read-before-write, approval on writes, existing events never overwritten |
| `agent/test_router.py`, `test_executor.py` | Allow-list, required/unknown parameters, approval enforcement, exceptions → failed results |
| `agent/test_planner.py`, `test_planner_gemini.py` | Intent detection, deterministic builders, mocked Gemini plans, invalid model output |
| `agent/test_orchestrator.py` | Plan order, approval waiting, failures, custom executors, Gemini injection |
| `agent/test_advanced_workflows.py` (new, 40) | Missing/self/circular/duplicate dependencies; blocked dependents with independent steps continuing; writes gated even when the plan says otherwise; untrusted executor success ignored; unknown tools and invalid arguments (priority, IDs, path-like IDs, reversed/oversized time ranges, long text); bounded read retries; writes never retried; idempotent resume; verification catching unpersisted writes; timeouts; persistence failures; audit lifecycle events; audit never stores parameters/secrets; audit failure doesn't break a workflow; Gemini fallback on errors, unknown tools, `user_id` injection, too many steps; model can't disable approval; prompt injection in goal; status consistency; generic subject parsing; slots avoid meeting, each other and existing events; explicit times; chained preference + plan; review intent |
| `api/test_security.py` (new, 28) | Session cookie flags; cross-session isolation of tasks, workflows, audit, preferences; cross-session approve/reject by ID, alias and goal; forged cookie; `/run approved:true` ignored; single-use approvals (409 on replay, reject-after-approve, approve-after-reject); payload-hash binding; parameter substitution; server-side mutation detection; expiry (410); malformed approvals; separate workflows; memory proposal executes and verifies; goal limits; invalid JSON; 413 on large bodies; invalid preferences (bad time, negative, too large, invalid day, password in notes, unknown field, empty, reversed window); direct edits validated and verified; reset confirmation; audit limit bounds; rate limiting (429, per session); CSRF-style simple requests; security headers; hidden internal errors; no key leakage in status; honest `memory_fallback`; missing static files are 404 |
| `services/test_*` | Persistence parity (memory & mocked Firestore), user isolation at the storage layer, Firestore init failure, Gemini service errors, memory service |

Latest result: **Ran 251 tests — OK**.

## Frontend coverage (Vitest + Testing Library, jsdom)

- `src/test/lib.test.js` (10): goal validation, preference-influence parsing, "what was saved" only lists completed writes, step counts, expiry minutes, preference form validation/normalisation, API client (same-origin credentials, 410/429/422/500 mapping, network errors).
- `src/test/App.test.jsx` (11): empty-goal validation without an API call; examples fill but don't submit; API failure shows an actionable error and keeps the goal; plan + approval rendering incl. preference influence; approve once despite double click and verified results; rejection stays visibly rejected; expired approval explained with "Plan again"; preference validation before save; reset requires explicit confirmation; bottom navigation; honest status panel.

Latest result: **21 passed**. `npm run lint`: 0 problems. `npm run build`: success (JS ≈ 290 kB / 88 kB gzip, CSS ≈ 29 kB / 6 kB gzip).

## Browser verification (headless Chrome)

`scripts/browser-smoke.mjs` against the production build served by FastAPI (session identity, no Gemini key):

- Widths 320, 360, 390, 430, 768, 1024, 1440: **0 px horizontal overflow, 0 console errors**.
- 390 px phone journey: empty-goal error → example fills box → plan → approval card with 3 changes → **double-click Approve → exactly 3 writes, all verified** → activity history → preference edit saved and verified → reset with confirmation → chained goal rejected (steps shown as Rejected) → clarification card.
- Interactive elements below 44×44 px: only the visually hidden skip link.
- Keyboard: visible focus outline (`:focus-visible` 2 px accent).

Defects found and fixed through this run: duplicated date in approval text, 32 px "Technical details" toggles, "Plan it" wrapping on desktop, write steps showing "Tried 2 times", stale "Nothing is saved" sentence after saving, misleading "Needs your approval" on non-protected waiting steps.

## Not verified

- Live Gemini API (no key available) — mocked only.
- Live Firestore — mocked client only.
- Docker image build/run — Docker not installed.
- Real iOS/Android devices and screen readers (VoiceOver/TalkBack) — only headless Chrome with mobile emulation and semantic/ARIA checks.
- Full automated accessibility audit (axe/Lighthouse). Colour contrast of the design tokens was computed with the WCAG formula: body 15.2:1, muted 7.9:1, faint 4.9:1 on cards; white on primary button 5.0:1, on approve button about 5.3:1 (Tailwind emerald-700) (button colours were darkened after the first check measured 3.6:1 and 3.8:1).
