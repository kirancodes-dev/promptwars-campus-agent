# Architecture

CampusPilot AI is one deployable unit: a FastAPI backend that also serves the built React SPA. Everything below describes code that exists in this repository.

## Request flow

```mermaid
sequenceDiagram
  participant S as Student (browser)
  participant F as React SPA
  participant M as SecurityMiddleware
  participant A as FastAPI /api/agent
  participant O as AgentOrchestrator
  participant P as Planner (Gemini or deterministic)
  participant R as Router + approval policy
  participant E as Executor + tools
  participant D as Persistence
  participant Q as Approval store

  S->>F: types goal, presses "Plan it"
  F->>M: POST /api/agent/run {goal}
  M->>M: size cap, session cookie → user_id, rate limit
  M->>A: request (user bound in contextvar)
  A->>O: run(goal, approved=False)
  O->>P: plan(goal)
  P-->>O: AgentPlan (steps + depends_on)
  O->>O: validate deps (missing, self, cycles, duplicates, read-before-write)
  loop each step in order
    O->>R: requires approval? (plan flag OR tool flag OR tool mutates)
    alt read step, deps done
      O->>E: execute (retry once on failure)
      E->>D: read (scoped to user_id)
    else write step
      O-->>O: mark waiting_approval (not executed)
    end
  end
  O-->>A: AgentExecutionResult + WorkflowRecord
  A->>Q: stage(user, workflow, plan, sha256(actions)), TTL 15 min
  A-->>F: plan, approval_requests (+payload_hash)
  S->>F: reviews changes, taps "Approve"
  F->>A: POST /approve {approval_id, payload_hash}
  A->>Q: claim(): owner? pending? not expired? hash matches?
  A->>O: run_workflow(stored plan, approved=True)
  O->>E: execute writes once (never retried)
  E->>D: write
  O->>D: read back + compare fields (verification)
  O->>D: audit events, workflow history
  A-->>F: verified results
```

## Components

| Component | File | Responsibility |
|---|---|---|
| Security middleware | `backend/main.py` | 32 KB body cap, anonymous session identity, per-session rate limit, security headers/CSP, JSON 500s |
| Identity | `backend/services/identity.py` | HMAC-signed `cp_session` cookie → `session-<id>` user; contextvar used by every tool |
| API | `backend/api/agent.py` | REST endpoints; stages approvals; never forwards a client approval flag |
| Orchestrator | `backend/agent/orchestrator.py` | Planning with fallback, approval policy, sequential dependency-gated execution, retries, timeouts, verification, audit |
| Planner | `backend/agent/planner.py` | Intent detection and deterministic builders; Gemini plan parsing/hardening |
| Router | `backend/agent/router.py` | Tool allow-list (17 tools), required/unknown parameter checks, value validation, `mutates` flag |
| Executor | `backend/agent/executor.py` | Maps tool names to Python functions; refuses protected tools without approval |
| Workflow validation/verification | `backend/agent/workflow.py` | Dependency graph checks; read-back verification for every write tool |
| Approval store | `backend/services/approvals.py` | User-bound, hash-bound, single-use, expiring approvals (in process memory) |
| Persistence | `backend/services/persistence.py`, `in_memory.py`, `firestore.py` | Same interface for memory and Firestore; all data keyed by user |
| Gemini | `backend/services/gemini.py` | Prompt with tool catalog and fenced untrusted goal; JSON mode; 20 s timeout |

## Workflow model

`backend/models/workflow.py`:

- `WorkflowRecord`: `workflow_id`, `goal`, `status` (`planned`, `waiting_approval`, `running`, `completed`, `partially_completed`, `failed`, `rejected`, `needs_clarification`), `created_at`, `updated_at`, `planner_mode`, `planner_note`, `approval_id`, `steps`, `summary`, `next_action`.
- `WorkflowStep`: `step_id`, `order`, `title`, `description`, `kind` (`read`/`write`/`reasoning`), `tool`, `parameters`, `depends_on`, `requires_approval`, `status` (`planned`, `waiting_approval`, `running`, `completed`, `failed`, `skipped`, `blocked`, `rejected`), `attempts`, `retry_eligible`, `result`, `error`, `verification` (`checked`, `passed`, `detail`), timestamps.

Execution rules (sequential, in plan order):

1. A step runs only when every dependency is `completed`. A failed/blocked dependency makes the step `blocked` with an explanation; independent steps still run (partial completion).
2. Approval policy: a step requires approval if the plan says so, the tool is registered as approval-required, **or the tool changes data** (`mutates=True`). Planner or model output can add approval but never remove it.
3. Read steps may run twice (one retry); write steps run at most once and are never retried automatically.
4. A write step already `completed` in this workflow is never re-executed (idempotent resume).
5. Each tool call has a timeout (`TOOL_TIMEOUT_SECONDS`, default 15 s). A timed-out write is reported as "may or may not have been saved; not retried".
6. Successful writes are verified by reading the stored entity and comparing the approved fields.

## Planning

- **Deterministic planner** (always available): intent detection → builders. The study planner extracts `(subject, minutes)` pairs ("2 hours of DBMS", "DAA for 90 minutes"), an optional meeting time, explicit per-subject times ("DBMS at 6 PM"), then allocates non-overlapping slots inside the saved study window, honouring break length and subject time-of-day preferences, and avoiding existing events and the meeting.
- **Gemini planner** (when `GEMINI_API_KEY` is set): structured JSON with a tool catalog. Output is capped (12 tool calls, string lengths), `requires_approval` and `user_id` fields from the model are discarded/rejected, writes are made to depend on preceding reads, and the plan must pass the same dependency validation. Any failure → deterministic plan with `planner_mode="deterministic_fallback"` and a user-visible note.

## Storage layout

In memory: dictionaries keyed by user ID. In Firestore:

```
users/{user_id}/tasks/{task_id}
users/{user_id}/schedule/{event_id}
users/{user_id}/notes/{note_id}
users/{user_id}/preferences/default
users/{user_id}/audit_logs/{audit_id}
users/{user_id}/workflows/{workflow_id}
```

Pending approvals and rate-limit counters are **not** persisted (process memory only).

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/agent/plan` | Plan only, executes nothing |
| POST | `/api/agent/run` | Plan, run reads, stage writes for approval (`approved` field is ignored) |
| POST | `/api/agent/approve` | Execute a staged approval (`approval_id`, optional `payload_hash`) |
| POST | `/api/agent/reject` | Reject a staged approval |
| GET | `/api/agent/status` | Planner, storage durability, identity mode (no secrets) |
| GET | `/api/agent/workflows`, `/workflows/{id}` | This session's workflow history |
| GET | `/api/agent/audit` | This session's audit events (`limit` 1–200) |
| GET | `/api/agent/memory`, `/memory/summary` | Preferences |
| POST | `/api/agent/memory/propose` | Stage a preference change for approval (returns a field-level diff) |
| POST | `/api/agent/memory/update` | `approved:false` → propose; `approved:true` → direct edit from the preferences form (validated, verified, audited) |
| POST | `/api/agent/memory/reset` | Reset with `{"confirm": true}` |
| GET | `/health` | Liveness |

### Intentional API changes in this round

- `/run` no longer executes protected writes when the client sends `approved: true` (critical fix).
- Approval replays return **409**, expired approvals **410**, other users' approvals **404**, payload mismatch **400**.
- `/approve` and `/reject` reject unknown body fields (422).
- `AgentExecutionResult` gained `workflow`, `skipped_actions`, `planner_mode`, `planner_note`; `ApprovalRequest` gained `step_id`, `title`, `description`, `payload_hash`, `expires_at`; new status value `rejected`.
- `/memory/update` with `approved:true` now *replaces* lists/maps (form semantics) instead of appending.
