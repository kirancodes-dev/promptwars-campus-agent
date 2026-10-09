# Deployment readiness

The full step-by-step guide is in [deployment/cloud-run.md](../deployment/cloud-run.md). This page records what is ready and what is not.

## Status (2026-10-09, revision `campuspilot-ai-00005-c5s`)

| Item | Status |
|---|---|
| Dockerfile (multi-stage, Node 22 build → Python 3.12 slim, non-root uid 1000, `$PORT`, health check, 1 worker, proxy headers) | **Built** with Cloud Build (1 min 14 s); local Docker build still not run |
| `.dockerignore` excludes `.env`, credentials, `node_modules`, `dist`, `.venv`, caches | Prepared |
| Production mode (`APP_ENV=production`): docs disabled, `Secure` cookies, no dev CORS, CSP, SPA fallback, JSON 404s | **Verified** by running uvicorn locally with production settings |
| Static asset serving and SPA fallback from FastAPI | **Verified** (browser smoke test) |
| Secrets via Secret Manager | `SESSION_SECRET` created and mounted. `GEMINI_API_KEY` is intentionally **not** configured: Gemini is disabled in production and the built-in planner serves every request |
| Firestore | **Verified live** (`(default)` database, asia-south1): plan → approve → read-back verification, workflow history and audit log. Explicit deny-all client rules prepared in `firestore.rules` (deploy pending approval) |
| Cloud Run service | **Deployed and smoke-tested**: https://campuspilot-ai-165103643932.asia-south1.run.app (gen2, max 1 instance, scale to zero, `TZ=Asia/Kolkata`), revision `campuspilot-ai-00005-c5s` (commit `e407c52`), serving 100% of traffic. Includes multi-day exam planning, the "What I understood" panel, the per-IP rate limit, bounded Firestore queries and batched audit writes |

## Readiness gate

Production-ready for a public multi-user service? **No.**

- No account authentication (anonymous sessions only). Acceptable for a competition demo; not for real student data.
- Single instance required (in-memory approvals/rate limits).
- Default storage is temporary.

Ready for a supervised competition demo on Cloud Run with one instance? **Yes.** The live API smoke test and the headless-browser journey passed against revision `campuspilot-ai-00005-c5s` on 2026-10-09.

## Live smoke test (revision `campuspilot-ai-00005-c5s`, 2026-10-09)

Only these checks were run against the public service:

- **First visit:** a session cookie is issued on page load, and parallel first requests share one session.
- **Browser journey** (headless Chrome, 320–1440 px, 0 console errors): plan → approve → saved and verified → history → preferences → reject → clarification.
- **New planning features:** a multi-exam plan and the "What I understood" panel.
- **Firestore:** approving the flagship plan saved exactly 2 events and 1 task; all 3 were read back and verified.
- **Approval security:** replay → 409; another session → 404; altered payload → 400 with nothing saved; a client-sent `approved: true` does not bypass approval.
- **Rate limit:** 60 state-changing requests accepted, then 429.
- **History and audit:** the workflow history and audit log are returned for the session.
- **Status:** planner `deterministic`, `ai_available: false`, storage Firestore (durable).
- **Hardening and logs:** `/openapi.json` → 404 (API docs disabled); no 5xx responses or error logs on the revision during the test.

**Not checked live:** Gemini (disabled), screen readers, real phones.

## Rollback

The previous revision `campuspilot-ai-00004-gl8` is still available:

```bash
gcloud run services update-traffic campuspilot-ai --project promptwar-7576f --region asia-south1 \
  --to-revisions=campuspilot-ai-00004-gl8=100
```

## Verify the image when Docker is available

```bash
docker build -t campuspilot-ai:local .
docker run --rm -p 8080:8080 campuspilot-ai:local
curl -s localhost:8080/health
BASE_URL=http://127.0.0.1:8080/ node scripts/browser-smoke.mjs   # see docs/testing.md
```
