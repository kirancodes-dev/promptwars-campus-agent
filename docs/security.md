# Security review

Scope: backend API, agent pipeline, persistence, frontend, configuration. Reviewed 2026-10-09. Every "Fixed" item has a regression test (`backend/api/test_security.py`, `backend/agent/test_advanced_workflows.py`, existing suites).

## Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | Critical | `POST /run` with `"approved": true` executed protected writes without server-side approval | **Fixed** — flag ignored; writes only via `/approve` |
| 2 | Critical | Approving a `/memory/propose` request executed an empty plan yet reported success | **Fixed** — real staged step, executed and verified |
| 3 | High | All visitors shared one `demo-user` namespace | **Fixed for anonymous use** — signed per-browser sessions; not authentication (see Limitations) |
| 4 | High | Approvals not bound to a user; tamper check only covered the first task; replay not atomic | **Fixed** — user + workflow + SHA-256 action hash binding, atomic single-use claim, TTL |
| 5 | High | `create_*`/`update_*` tools not approval-gated; model output could set `requires_approval:false` | **Fixed** — orchestrator policy gates every data-changing tool |
| 6 | High | Tools accepted a model-supplied `user_id` (cross-user access via the planner) | **Fixed** — parameter removed from the allow-list; identity comes only from the session |
| 7 | Medium | No request size limits, no rate limiting, no goal length limit | **Fixed** — 32 KB body cap, 60 req/min per session, 1,000-char goals |
| 8 | Medium | Parameter values unvalidated (lengths, IDs, dates, durations) | **Fixed** — router value validation |
| 9 | Medium | Firestore failure silently fell back to memory while status said "memory" | **Fixed** — `memory_fallback` + `durable:false` surfaced in API and UI |
| 10 | Medium | Missing security headers; API docs exposed in production | **Fixed** — CSP, nosniff, frame-deny, referrer policy; docs off when `APP_ENV=production` |
| 11 | Low | Unhandled errors could return framework default bodies | **Fixed** — JSON 500 handler without internals |
| 12 | Low | Google Fonts loaded from a third party | **Fixed** — system font stack; CSP `default-src 'self'` |
| 15 | Medium | Session race: parallel first API requests each minted a new session; a late response could replace the cookie that owned a pending approval, making approval fail with 404 (found on the live deployment) | **Fixed** — the session cookie is issued on the page load, before any API call; regression tests added. Failure mode was safe: nothing executed |
| 16 | Medium | Rate limit bypass: cookie-less clients got a new session (and a fresh per-session limit) on every request — 10/10 requests succeeded at a limit of 3 | **Fixed** — additional per-IP limit on all API calls (default 600/min, generous for shared campus IPs); regression tests |
| 17 | Low | No explicit Firestore security rules for the app's `(default)` database (default-deny applied implicitly) | **Prepared** — `firestore.rules` (deny all client access) + `firebase.json`; deploying them needs approval |
| 18 | Low | Gemini output validated with ad-hoc checks | **Hardened** — strict Pydantic schema (allowed fields, types, bounded sizes); unknown fields in tool calls rejected; reason-specific fallback |
| 13 | High (open) | No account authentication | **Open** — needs an identity-provider decision (see README › Security limitations) |
| 14 | Medium (open) | Approvals/rate limits in process memory → single instance only | **Accepted for demo** — `--max-instances=1` |

No critical or high finding remains open except #13, which needs an identity-provider decision.

## Threat-model review (2026-10-09)

| Threat | Control | Evidence |
|---|---|---|
| Reading another visitor's data (IDOR) | All storage keyed by the session user; IDs from other sessions return 404 | `api/test_security.py` isolation tests; live cross-session 404 |
| Session fixation / forged sessions | Server-signed cookie; invalid cookies replaced; session issued on page load; `run.app` is a public suffix | forged-cookie tests (API and page load) |
| CSRF | `SameSite=Lax`; JSON-only bodies (text/plain and form posts get 422) | `test_cross_site_simple_requests_rejected` |
| Approval replay / substitution / expiry | Single-use atomic claim, SHA-256 payload hash, TTL, server-held plan | approval integrity tests; live 409/400/404 checks |
| Client claims approval | `approved` field ignored on `/run` | test + live check |
| Model authorises its own mutation | Approval flags from model discarded; server policy gates all writes | `test_model_cannot_mark_a_delete_as_approved` |
| Prompt injection | Goal fenced as data; allow-listed tools; schema; approval | Gemini integration tests |
| Arbitrary code / queries from model | No eval/exec; tool allow-list; parameter validation; no raw queries | tests + static check |
| Resource exhaustion | 32 KB body cap; goal length; 12-session cap; per-session + per-IP rate limits; bounded Firestore reads; tool timeouts | tests |
| Secret exposure | Keys only server-side via env/Secret Manager; errors report type names only; status never echoes values | `test_status_*` tests; pattern scans of commits |
| Direct Firestore access | Only the runtime service account (`roles/datastore.user`); client rules deny (default + prepared file) | Rules API check: `prompt1` deny-all, `(default)` no client rules |
| Information disclosure in errors | Generic 500s; API docs disabled in production | tests; live checks |

## Identity and user isolation

- Every request is bound to a user by `SecurityMiddleware`. In `IDENTITY_MODE=session` (default) the server issues `cp_session=<128-bit random id>.<HMAC-SHA256>` (HttpOnly, SameSite=Lax, Secure in production). Unsigned or tampered cookies are replaced with a new session; clients cannot pick a user ID. No client-supplied header is trusted as identity.
- The user ID flows through a `contextvar` to every tool, the memory service, verification, audit and workflow storage. All persistence keys are per user.
- Other users' approvals and workflows return 404 (existence is not revealed).
- **This is session isolation, not authentication.** Anyone holding the cookie is that session. Data does not follow the student across devices.
- `IDENTITY_MODE=demo` shares one user and is for local development/tests only.

Tested: two-session isolation for tasks, workflows, audit, preferences; cross-session approve/reject (by ID, alias ID and goal); forged cookie.

## Approval integrity

| Attack | Defence | Test |
|---|---|---|
| Client sets `approved:true` on `/run` | Ignored | `test_client_approved_flag_on_run_is_ignored` |
| Replay an approval | Atomic `pending → executing` claim; 409 afterwards | `test_approval_executes_exactly_once` |
| Approve after reject / reject after approve | 409 | same + `test_rejected_actions_never_execute` |
| Change parameters at approval time | Client parameters must equal a staged action; server executes only the stored plan | `test_parameter_substitution_rejected` |
| Approve something other than what was reviewed | `payload_hash` must match | `test_payload_hash_binding` |
| Server-side plan mutated after staging | Hash recomputed at claim time | `test_server_side_plan_mutation_detected` |
| Stale approval | 15-minute TTL → 410 | `test_expired_approval_rejected` |
| Another user's approval | 404 | `test_other_user_cannot_approve_or_reject` |
| Unrelated workflow | Each approval stores its own plan/workflow | `test_two_workflows_do_not_share_approvals` |
| Double tap | Server single-use + UI in-flight guard | browser test (double-click → 3 writes, not 6) |

## AI safety

- Gemini output is data. The response must match a strict schema (`ModelPlan`: allowed fields, types, at most 12 tool calls, bounded strings; unknown fields inside tool calls are rejected). Tool names must be in the allow-list; parameters are validated; `requires_approval` from the model is discarded; `user_id` is rejected. The fallback note distinguishes "AI unavailable" (timeouts, quota, auth, network) from "AI plan failed safety checks".
- The user goal is fenced in the prompt as untrusted text; the system prompt tells the model to ignore instructions that try to change its rules. The server does not rely on this: approval, validation and identity are enforced in code.
- Any Gemini error, invalid JSON, invalid tool or failed dependency validation → deterministic plan, with a visible note.
- No `eval`, `exec`, dynamic imports or shell calls (asserted by tests).

## API hardening

- CORS: only localhost dev origins in development; none in production (same origin). Credentials allowed only for listed origins.
- CSRF: cookies are `SameSite=Lax` (not sent on cross-site POSTs) and FastAPI rejects non-JSON bodies for JSON endpoints.
- Errors: validation errors are 400/422 with readable messages; 500s return a generic JSON message; stack traces are only logged server-side.
- `/health` returns only `{"status":"healthy"}`. `/status` reports modes, never key values (tested with a dummy key).

## Secrets

- `.gitignore` covers `.env*` (except examples), service-account/credential JSON, keys/PEM, virtualenvs, `node_modules`, `dist`, caches and logs. `.dockerignore` mirrors it.
- `backend/.env.example` and `frontend/.env.example` contain placeholders only.
- No secrets were found in the working tree (pattern scan for Google API keys, private keys, GitHub/OpenAI tokens). The repository has no commits yet, so there is no history to scan.
- The audit log stores goal text (sanitised for key/token patterns), step names, tool names and outcomes — never tool parameters.

## Dependencies

- Backend: upper-bounded ranges in `backend/requirements.txt`; versions verified locally are listed there. No new runtime dependencies were added.
- Frontend: `npm audit --omit=dev` → 0 vulnerabilities. New dev-only test dependencies are pinned exact versions released at least several weeks earlier (vitest 4.1.11, jsdom 26.1.0, Testing Library).

## Remaining work before a public launch

1. Real authentication (e.g. Firebase Authentication with Google sign-in), mapping the verified UID to `user_id`.
2. Move pending approvals and rate limits to shared storage (Firestore or Memorystore) to allow more than one instance.
3. Per-user time zones.
4. A Firestore security-rules file if the database is ever accessed from clients (today only the server's service account accesses it).
