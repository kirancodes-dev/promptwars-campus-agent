# Competition submission draft — PromptWars × Error Zero 2026

> Draft for the author to edit. **Not submitted.** Fill in the bracketed fields. Do not add claims beyond what is verified in `docs/testing.md`.

**Project title:** CampusPilot AI

**Tagline:** The study planner that asks before it acts — and proves what it did.

**Repository:** https://github.com/kirancodes-dev/promptwars-campus-agent (not yet pushed)
**Live demo:** [not deployed — add Cloud Run URL after deployment]
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
- **Cloud Firestore** for optional durable per-user storage. *Adapter tested with a mocked client; not verified live.*
- **Cloud Run + Secret Manager + Artifact Registry/Cloud Build** deployment path documented in `deployment/cloud-run.md`. *Not deployed.*

## Security and human control

Server-enforced approval policy; approval replay, tampering, expiry and cross-session use rejected (tested); per-browser signed anonymous sessions isolate visitors; model output treated as untrusted (allow-listed tools, validated parameters, no `eval`/`exec`); request size limits, rate limiting, CSP and security headers; secrets only via environment/Secret Manager. Limitation: no account login yet.

## Implementation highlights

- Workflow engine with dependency validation (missing, self, cyclic, duplicate), blocked-step reporting, partial completion, bounded read retries, never-retried writes, idempotent resume, per-step timeouts.
- Deterministic planner that parses arbitrary subjects/durations and allocates conflict-free, preference-aware slots.
- Chained intents: "remember my preference, then plan" under one approval.

## Testing evidence (2026-10-09, local)

- Backend: 251 unittest tests passing (including 40 workflow and 28 security tests).
- Frontend: 21 Vitest/Testing Library tests passing; ESLint clean; production build succeeds.
- Headless Chrome: 0 px horizontal overflow and 0 console errors at 320–1440 px; full phone journey (plan → approve → verify → activity → preferences → reset → reject → clarification).

## Known limitations

No account authentication; single-instance requirement; temporary storage by default; server-local time zone; no external calendar integration; Gemini and Firestore not verified live; Docker image not yet built.

## Demo instructions

See `docs/demo-script.md` (3 minutes, no API key required).

## Suggested pitch (30 seconds)

"Most AI assistants either just talk, or act without asking. CampusPilot plans your study time like an agent — it reads your schedule, avoids your meeting, respects your preferences — then shows exactly what it wants to change and waits for your yes. After you approve, it saves, re-checks every item, and logs it. It even keeps working when the AI is offline, and tells you so."

## Suggested judging presentation order

1. Problem (15 s) → 2. Flagship goal live (60 s) → 3. Approval + verification (30 s) → 4. Memory/preferences influencing a plan (30 s) → 5. Honest status & fallback (15 s) → 6. Architecture & security slide (30 s) → 7. Limitations & next steps (15 s).
