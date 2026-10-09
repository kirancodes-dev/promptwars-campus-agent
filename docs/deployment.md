# Deployment readiness

The full step-by-step guide is in [deployment/cloud-run.md](../deployment/cloud-run.md). This page records what is ready and what is not.

## Status (2026-10-09)

| Item | Status |
|---|---|
| Dockerfile (multi-stage, Node 22 build → Python 3.12 slim, non-root uid 1000, `$PORT`, health check, 1 worker, proxy headers) | Prepared, **not built** (Docker unavailable) |
| `.dockerignore` excludes `.env`, credentials, `node_modules`, `dist`, `.venv`, caches | Prepared |
| Production mode (`APP_ENV=production`): docs disabled, `Secure` cookies, no dev CORS, CSP, SPA fallback, JSON 404s | **Verified** by running uvicorn locally with production settings |
| Static asset serving and SPA fallback from FastAPI | **Verified** (browser smoke test) |
| Secrets via Secret Manager (`GEMINI_API_KEY`, `SESSION_SECRET`) | Documented, not created |
| Firestore | Adapter implemented and tested with a mocked client; **not verified live** |
| Cloud Run service | **Not deployed** |

## Readiness gate

Production-ready for a public multi-user service? **No.**

- No account authentication (anonymous sessions only). Acceptable for a competition demo; not for real student data.
- Single instance required (in-memory approvals/rate limits).
- Default storage is temporary.

Ready for a supervised competition demo on Cloud Run with one instance? **Yes, once the image is built and the smoke test in the guide passes.**

## Verify the image when Docker is available

```bash
docker build -t campuspilot-ai:local .
docker run --rm -p 8080:8080 campuspilot-ai:local
curl -s localhost:8080/health
BASE_URL=http://127.0.0.1:8080/ node scripts/browser-smoke.mjs   # see docs/testing.md
```
