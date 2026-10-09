# Deployment readiness

The full step-by-step guide is in [deployment/cloud-run.md](../deployment/cloud-run.md). This page records what is ready and what is not.

## Status (2026-10-09, after live deployment)

| Item | Status |
|---|---|
| Dockerfile (multi-stage, Node 22 build → Python 3.12 slim, non-root uid 1000, `$PORT`, health check, 1 worker, proxy headers) | **Built** with Cloud Build (1 min 14 s); local Docker build still not run |
| `.dockerignore` excludes `.env`, credentials, `node_modules`, `dist`, `.venv`, caches | Prepared |
| Production mode (`APP_ENV=production`): docs disabled, `Secure` cookies, no dev CORS, CSP, SPA fallback, JSON 404s | **Verified** by running uvicorn locally with production settings |
| Static asset serving and SPA fallback from FastAPI | **Verified** (browser smoke test) |
| Secrets via Secret Manager | `SESSION_SECRET` created and mounted; `GEMINI_API_KEY` not yet added (built-in planner in use) |
| Firestore | **Verified live** (`(default)` database, asia-south1): plan → approve → read-back verification, workflow history and audit log |
| Cloud Run service | **Deployed**: https://campuspilot-ai-165103643932.asia-south1.run.app (gen2, max 1 instance, scale to zero) |

## Readiness gate

Production-ready for a public multi-user service? **No.**

- No account authentication (anonymous sessions only). Acceptable for a competition demo; not for real student data.
- Single instance required (in-memory approvals/rate limits).
- Default storage is temporary.

Ready for a supervised competition demo on Cloud Run with one instance? **Yes** — live API smoke test and headless-browser journey pass against the deployed service (after the session-cookie fix described in docs/security.md is deployed).

## Verify the image when Docker is available

```bash
docker build -t campuspilot-ai:local .
docker run --rm -p 8080:8080 campuspilot-ai:local
curl -s localhost:8080/health
BASE_URL=http://127.0.0.1:8080/ node scripts/browser-smoke.mjs   # see docs/testing.md
```
