# Competition submission draft — PromptWars × Error Zero 2026

> Draft for the author to edit. **Not submitted.** Fill in the bracketed fields. Do not add claims beyond what is verified in `docs/testing.md`.

**Project title:** CampusPilot AI

**Tagline:** The study planner that asks before it acts — and proves what it did.

**Repository:** https://github.com/kirancodes-dev/promptwars-campus-agent
**Live demo:** https://campuspilot-ai-165103643932.asia-south1.run.app
**Demo video:** [add link]

## Problem

Students juggle classes, project meetings and revision. Planning study time around existing commitments is tedious, and AI chatbots either only suggest a timetable or take actions without the student seeing exactly what will change.

## Solution

CampusPilot AI turns a natural-language goal ("2 hours of DBMS, 1 hour of DAA, meeting at 4 PM") into a dependency-ordered workflow. It runs the read-only steps itself — reading the schedule, checking conflicts, finding free slots inside the student's preferred window — then presents every data-changing action for approval. Approved changes are executed once, read back and verified, and recorded in an activity timeline and audit log. It remembers study preferences (window, session/break length, subject timing) and uses them in later plans.

## Target audience

College students who plan their own study sessions around classes, meetings and deadlines — primarily on their phones.

## Differentiators

1. **Approval as a server-side security boundary**: every data-changing tool is gated regardless of planner/model output; approvals are bound to the session, workflow and a SHA-256 hash of the reviewed actions, single-use and time-limited.
2. **Verified outcomes**: "saved" is shown only after the stored state is read back and matches.
3. **Honest degradation**: fully functional without an API key; automatic, visible fallback when Gemini fails; storage durability shown in the UI.
4. **Explainable plans**: each step says whether it reads or changes data, its status, dependencies, and technical details on demand.
5. **Mobile-first UX**: bottom navigation, sticky approval bar, 44 px touch targets, no horizontal scroll from 320 px.

## Architecture summary

React 19 + Vite + Tailwind SPA → FastAPI (session middleware, rate limits, security headers) → Orchestrator → Planner (Gemini structured JSON or deterministic) → Tool router (allow-list + validation) → Approval gate → Executor → Tools → Persistence (in-memory or Firestore) → read-back verification → audit trail. Single container for Cloud Run. Diagram: `docs/architecture.md`.

## Google technology

- **Gemini 2.5 Flash** (`google-genai`, JSON mode) for planning, behind strict validation with a deterministic fallback. *Integrated and tested with mocks; not exercised against the live API in this repository.*
- **Cloud Firestore** for durable per-session storage, with bounded queries and batched audit writes. *Verified live on the demo deployment.*
- **Cloud Run (gen2) + Secret Manager + Artifact Registry/Cloud Build**: live demo in asia-south1, scale to zero, one instance. Steps in `deployment/cloud-run.md`.

## Security and human control

Server-enforced approval policy; approval replay, tampering, expiry and cross-session use rejected (tested); per-browser signed anonymous sessions isolate visitors; model output treated as untrusted (allow-listed tools, validated parameters, no `eval`/`exec`); request size limits, rate limiting, CSP and security headers; secrets only via environment/Secret Manager. Limitation: no account login yet.

## Implementation highlights

- Workflow engine with dependency validation (missing, self, cyclic, duplicate), blocked-step reporting, partial completion, bounded read retries, never-retried writes, idempotent resume, per-step timeouts.
- Deterministic planner that parses arbitrary subjects/durations and allocates conflict-free, preference-aware slots.
- Chained intents: "remember my preference, then plan" under one approval.

## Testing evidence (2026-10-09)

- Backend: 304 automated tests (1 optional live-Gemini test skipped without a key), 86% line+branch coverage — including 21 realistic planning scenarios, 35 security tests and 9 mocked Gemini failure/abuse tests.
- Frontend: 29 tests (88% line coverage), ESLint clean, production build succeeds.
- Accessibility: axe-core 0 violations across 9 UI states; 30/30 keyboard-only checks; no horizontal scroll from 320 px or at 200% text size. Not tested with screen readers or real phones.
- Live (Cloud Run + Firestore, revision 00004): plan → approve → read-back verification, replay/cross-session rejection, Secure cookie, no API docs — verified. Newer features (multi-day exam planning, "What I understood") are tested locally and will be live after the next deployment.
- CI: GitHub Actions runs the same checks on every push.

## Known limitations

No account authentication (anonymous sessions); single-instance requirement; server-local time zone (set to India for the demo); no external calendar integration; Gemini not verified live (no valid key); `docker run` not tested locally (the image builds on Cloud Build); screen readers and real phones not tested.

## Demo instructions

See `docs/demo-script.md` (3 minutes, no API key required).

## Suggested pitch (30 seconds)

"Most AI assistants either just talk, or act without asking. CampusPilot plans your study time like an agent — it reads your schedule, avoids your meeting, respects your preferences — then shows exactly what it wants to change and waits for your yes. After you approve, it saves, re-checks every item, and logs it. It even keeps working when the AI is offline, and tells you so."

## Suggested judging presentation order

1. Problem (15 s) → 2. Flagship goal live (60 s) → 3. Approval + verification (30 s) → 4. Memory/preferences influencing a plan (30 s) → 5. Honest status & fallback (15 s) → 6. Architecture & security slide (30 s) → 7. Limitations & next steps (15 s).
