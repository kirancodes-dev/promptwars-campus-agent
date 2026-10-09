# Testing

Results below were produced locally on 2026-10-09 (macOS, Python 3.12.13, Node 20.20.2, Chrome headless via playwright-core 1.62.0) unless marked **live**. The CI workflow runs the same backend and frontend checks on Ubuntu with Python 3.12 / Node 22; it has not run on GitHub yet because the workflow has not been pushed.

## Commands

```bash
# Backend — 304 tests (1 optional live Gemini test is skipped without a key)
cd backend
./.venv/bin/python -m unittest discover -s . -p "test_*.py"
./.venv/bin/pip install -r requirements-dev.txt           # coverage, pyflakes
./.venv/bin/python -m coverage run --branch --source=. --omit="*/test_*.py,.venv/*" -m unittest discover -s . -p "test_*.py"
./.venv/bin/python -m coverage report

# Frontend — 29 tests, coverage, lint, build
cd frontend && npm ci && npm test && npm run test:coverage && npm run lint && npm run build

# Browser checks (need Chrome and a running backend serving frontend/dist)
mkdir -p /tmp/cp-e2e && cd /tmp/cp-e2e && npm i playwright-core@1.62.0 axe-core@4.10.3
BASE_URL=http://127.0.0.1:8000/ node /path/to/repo/scripts/browser-smoke.mjs     # responsive + full journey
BASE_URL=http://127.0.0.1:8000/ node /path/to/repo/scripts/keyboard-journey.mjs  # keyboard only
BASE_URL=http://127.0.0.1:8000/ node /path/to/repo/scripts/a11y-audit.mjs        # axe-core WCAG 2.2 AA rules

# Optional live Gemini test (your own fresh key in backend/.env; never in CI)
CAMPUSPILOT_LIVE_GEMINI_TEST=1 ./.venv/bin/python -m unittest agent.test_gemini_integration
```

## Results

| Check | Before this round | Now |
|---|---|---|
| Backend tests | 256 | **304** (1 optional live skipped) |
| Backend coverage (line + branch, `coverage.py`) | 78% | **86%** |
| Frontend tests | 21 | **29** |
| Frontend coverage (v8) | — | **87.8% lines, 72.9% branches** |
| Lint (ESLint) / static check (pyflakes) | clean / not run | clean / clean |
| axe-core violations (9 UI states, 390 px + 1440 px) | 1 rule in every state (no `<h1>`) | **0** |
| Keyboard-only journey | not tested | **30/30 checks** |

Lowest backend coverage is now in `agent/planning/preferences_text.py` (now directly tested), `tools/notes.py` and `tools/tasks.py` (68–70%: legacy dict-proxy helpers kept for compatibility).

## What the backend tests cover

| Suite | Focus |
|---|---|
| `agent/test_planner_scenarios.py` (21) | Realistic goals on a fixed clock: date phrases; multiple exams (earliest-deadline-first, sessions before each exam, spread over days); fixed meeting kept free; priorities change order; impossible single-day and before-exam plans explain real free time; conflicting deadlines; past exam dates; vague dates ("next week") are not guessed; exam without study time is not invented; nothing invented (no meeting unless stated); default day stated as an assumption; saved preferences respected and labelled; explicit time overrides a saved preference; replanning avoids saved blocks and reuses freed time; storage outage while planning is disclosed and blocks writes; malformed goals never produce writes; "today" plans never start in the past |
| `agent/test_gemini_integration.py` (9 + 1 live) | Real `GeminiService` with a mocked SDK: success and approved execution; timeouts, 429 quota, invalid key, 403, 5xx, network errors → "AI unavailable" fallback; invalid JSON, empty/None, wrong shape, missing fields, unknown or code-like tool names, extra fields, bad dates, too many steps, oversized text, another user's data → "failed safety checks" fallback; model cannot approve its own delete; prompt injection is fenced and cannot execute writes; status never contains the key |
| `agent/test_verification.py` (8) | Read-back verification for every write tool: success, missing entity, field mismatch, preferences, reset, storage errors |
| `agent/test_advanced_workflows.py` (40) | Dependency validation, approval policy, bounded read retries, no write retries, idempotent resume, timeouts, audit events, Gemini fallback |
| `agent/test_preferences_text.py` (4) | Preference sentences: breaks, sessions, windows, subject timing, notes; nothing invented |
| `api/test_security.py` (35) | Session isolation, page-load session + concurrent first requests share one session, forged cookies, approval replay / tampering / expiry / cross-session, client approval flag ignored, input limits, per-session and per-IP rate limits (cookie-dropping bypass), CSRF-style requests, headers, error hiding, honest storage status |
| `services/test_firestore.py` (14) | Firestore adapter with a fake client, including range-query correctness at the 24-hour boundary, newest-first bounded reads (reads exactly `limit` documents) and chunked batch writes |
| Other suites | Tools, router, executor, planner intents, orchestrator, persistence, memory, Gemini service |

## Efficiency measurements

Firestore operations per request, counted with the fake Firestore client (same request sequence before and after). Writes are billed per document either way; round trips are separate network calls.

| Request | Reads before → after | Round trips before → after |
|---|---|---|
| `GET /api/agent/memory` | 2 → 1 | 2 → 1 |
| Plan the flagship goal | 1 → 1 | 15 → 7 |
| Approve (3 changes) | 3 → 3 | 25 → 11 |
| "Show my tasks" | 1 → 1 | 7 → 4 |
| Audit log (limit 40, after 11 runs) | 71 → 40 (now bounded by the limit) | 1 → 1 |

**Live baseline** (revision `00004`, n = 8 fresh sessions, client in India → asia-south1): memory median 438 ms, plan 707 ms, approve 948 ms, audit 385 ms. The optimised code is **not deployed yet**, so no live "after" numbers exist.

Measured and deliberately not changed: a new worker thread per tool call costs about 44 µs more than a shared pool (n = 2000, local); a shared pool could be exhausted by hung calls, so per-call isolation is kept.

Frontend bundle: 288.7 kB JS (87.3 kB gzip), 29.8 kB CSS (6.5 kB gzip).

## Browser, keyboard and accessibility

- **Responsive** (headless Chrome): 0 px horizontal overflow and 0 console errors at 320, 360, 390, 430, 768, 1024 and 1440 px; 0 px overflow at 390 px with text scaled to 200%; a 9-change multi-exam plan fits at 360 px.
- **Journey**: plan → approve (double-click saves exactly 3 items, all verified) → history → preferences save/reset → reject → clarification. **Live** on revision `00004` the same journey passed (with the session-race fix).
- **Keyboard only** (390 and 1440 px, 30/30): skip link first; goal entry; Ctrl/⌘+Enter submit; error on empty goal; Approve reachable with a 2 px focus outline; preferences edit/save; reset dialog receives focus and can be cancelled; bottom navigation and history expansion.
- **axe-core 4.10.3** (WCAG 2.0/2.1/2.2 A+AA + best practice): 0 violations in 9 states. Items axe cannot decide: colour contrast of the goal box and Approve button under the sticky header/bar — computed manually from the design tokens (16:1 and ≈5.3:1).

## Not verified

- Live Gemini (no valid key). Mocked only.
- Screen readers (VoiceOver/TalkBack) and real phones. Only emulation, semantic structure and automated rules.
- `docker run` locally (Docker unavailable); the image does build on Cloud Build.
- The CI workflow on GitHub itself (not pushed yet); its commands were run locally in a fresh environment.
- The new features on the live site (not deployed yet).
