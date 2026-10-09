# Deploying CampusPilot AI to Google Cloud Run

> These steps were used for the live deployment on 2026-10-09 (project `promptwar-7576f`, region `asia-south1`). Commands that create resources or may incur cost are marked 💳.

One container serves the built React app and the FastAPI API on `$PORT` (Cloud Run sets it; default 8080).

## 0. Decide first

| Decision | Recommended for the competition demo |
|---|---|
| Region | `asia-south1` (Mumbai). Confirm Cloud Run, Artifact Registry and Firestore are available in your chosen region. |
| Storage | Start with in-memory (`FIRESTORE_ENABLED=false`). Data resets on every restart/scale-to-zero; the UI says so. Enable Firestore (step 6) for durable data. |
| AI | Optional. Without `GEMINI_API_KEY` the built-in planner is used. |
| Instances | **Exactly one** (`--max-instances=1`). Pending approvals and rate limits live in process memory. |
| Public access | `--allow-unauthenticated` makes the demo public. Each visitor gets a private anonymous session, but there is no login. |

Cost: Cloud Run, Artifact Registry, Cloud Build, Secret Manager and Firestore have free tiers, but free usage depends on current quotas, region and traffic, and requires a billing account. **Zero cost is not guaranteed.** Gemini API usage is billed (or free-tier limited) separately from hosting. Set a budget alert (step 10) before deploying.

## 1. Variables

```bash
export PROJECT_ID="your-project-id"          # replace
export REGION="asia-south1"
export SERVICE="campuspilot-ai"
export REPO="campuspilot"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}"
export TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)"
export RUNTIME_SA="campuspilot-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
```

## 2. Authenticate and select the project

```bash
gcloud auth login
gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"
```

## 3. Enable APIs 💳 (requires billing on the project)

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com
# Only if you will use Firestore:
gcloud services enable firestore.googleapis.com
```

## 4. Runtime service account (least privilege)

```bash
gcloud iam service-accounts create campuspilot-runtime --display-name="CampusPilot runtime"
# Only if using Firestore:
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/datastore.user"
```

The service account needs no other roles; secret access is granted per secret in step 5. Never download a service-account key — Cloud Run uses the attached identity.

## 5. Secrets in Secret Manager 💳

Create secrets from your terminal; never paste secrets into source files, chat, or command history you share.

```bash
# Session-cookie signing key (required for stable sessions across restarts)
python3 -c "import secrets; print(secrets.token_hex(32), end='')" | \
  gcloud secrets create campuspilot-session-secret --data-file=-

# Gemini key (optional). Type the key at the prompt; it is not echoed or saved in history.
read -rs GEMINI_KEY && printf '%s' "$GEMINI_KEY" | \
  gcloud secrets create campuspilot-gemini-key --data-file=- && unset GEMINI_KEY

for s in campuspilot-session-secret campuspilot-gemini-key; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor"
done
```

## 6. Firestore (optional) 💳

```bash
gcloud firestore databases create --location="${REGION}" --type=firestore-native
```

Data is stored under `users/{session-id}/...`. Only the server's service account accesses Firestore; no client SDK is used.

## 6b. Firestore security rules (recommended)

The app never accesses Firestore from the browser; only the runtime service account (IAM) does. A database with no rules already denies client access; deploying the repository's explicit deny-all rules documents that intent. Requires the Firebase CLI logged in to your account:

```bash
firebase deploy --only firestore:rules --project "${PROJECT_ID}"   # uses firebase.json + firestore.rules
```

## 7. Build the image 💳 (Cloud Build) — or locally

```bash
gcloud artifacts repositories create "${REPO}" --repository-format=docker --location="${REGION}"

# Option A: Cloud Build (no local Docker needed)
gcloud builds submit --tag "${IMAGE}:${TAG}" .

# Option B: local Docker
docker build -t "${IMAGE}:${TAG}" .
gcloud auth configure-docker "${REGION}-docker.pkg.dev"
docker push "${IMAGE}:${TAG}"
```

### Local verification before pushing (not yet performed — Docker was unavailable)

```bash
docker build -t campuspilot-ai:local .
docker run --rm -p 8080:8080 -e SESSION_SECRET=local-test-only campuspilot-ai:local
curl -s localhost:8080/health                      # {"status":"healthy"}
curl -s localhost:8080/api/agent/status            # planner/storage/identity modes
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/            # 200 (SPA)
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/api/nope    # 404 JSON
docker run --rm campuspilot-ai:local id            # uid=1000(appuser)
```

## 8. Deploy 💳

```bash
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}:${TAG}" \
  --region="${REGION}" \
  --service-account="${RUNTIME_SA}" \
  --allow-unauthenticated \
  --port=8080 \
  --cpu=1 --memory=512Mi \
  --min-instances=0 --max-instances=1 \
  --concurrency=40 --timeout=60 \
  --execution-environment=gen2 \
  --set-env-vars="APP_ENV=production,IDENTITY_MODE=session,FIRESTORE_ENABLED=false,GEMINI_MODEL=gemini-2.5-flash,TZ=Asia/Kolkata,GRPC_DNS_RESOLVER=native" \
  --set-secrets="SESSION_SECRET=campuspilot-session-secret:latest"
```

Add Gemini: append `--set-secrets="GEMINI_API_KEY=campuspilot-gemini-key:latest"` (use `--update-secrets` on an existing service).
Add Firestore: `--update-env-vars="FIRESTORE_ENABLED=true,FIRESTORE_PROJECT_ID=${PROJECT_ID}"`.

Why these settings (learned from the live deployment on 2026-10-09):

- `--execution-environment=gen2` is required with Firestore. On the default first-generation sandbox every Firestore call took 1–5 s, plan requests took ~55 s and approvals hit the 60 s timeout; on gen2 the same requests take about 0.3–1.1 s.
- `GRPC_DNS_RESOLVER=native` is set as well. It made Firestore reads fast in an in-region Cloud Build test, but on its own it did not fix Cloud Run; gen2 did.
- `TZ=Asia/Kolkata` makes "today/tomorrow" and default study times follow Indian time instead of UTC. Change it for other audiences.

`--min-instances=0` scales to zero when idle (lowest cost). With in-memory storage this also wipes data and pending approvals; the UI shows "Temporary" storage. Cloud Run uses the container's `/health` only if you configure a probe; the Dockerfile `HEALTHCHECK` is for local Docker. Optional startup probe:

```bash
gcloud run services update "${SERVICE}" --region="${REGION}" \
  --startup-probe=httpGet.path=/health,httpGet.port=8080,initialDelaySeconds=0,periodSeconds=5,failureThreshold=6
```

## 9. Smoke test

```bash
URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --format='value(status.url)')"
curl -s "${URL}/health"
curl -s -c /tmp/cp.cookies "${URL}/api/agent/status"
curl -s -b /tmp/cp.cookies -H 'content-type: application/json' \
  -d '{"goal":"Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM."}' \
  "${URL}/api/agent/run" | python3 -m json.tool | head -40   # expect "status": "waiting_approval"
curl -s -o /dev/null -w '%{http_code}\n' "${URL}/docs"     # SPA shell (200), not Swagger
```

Then open `${URL}` on a phone and run the demo script (`docs/demo-script.md`).

## 10. Cost controls 💳

```bash
# Budget alert (requires billing account ID)
gcloud billing budgets create --billing-account=YOUR_BILLING_ACCOUNT_ID \
  --display-name="CampusPilot demo" --budget-amount=5USD \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9
```

Also: keep `--max-instances=1`, `--min-instances=0`; delete old images (`gcloud artifacts docker images list ${IMAGE}`); set a Gemini quota/limit in Google AI Studio if you enable AI.

## 11. Logs

```bash
gcloud run services logs read "${SERVICE}" --region="${REGION}" --limit=100
```

The app logs warnings (Gemini fallback, audit failures) by exception type only; it never logs keys or request bodies.

## 12. Rollback

```bash
gcloud run revisions list --service="${SERVICE}" --region="${REGION}"
gcloud run services update-traffic "${SERVICE}" --region="${REGION}" --to-revisions=REVISION_NAME=100
```

## 13. Cleanup (stops all charges for this app)

```bash
gcloud run services delete "${SERVICE}" --region="${REGION}"
gcloud artifacts repositories delete "${REPO}" --location="${REGION}"
gcloud secrets delete campuspilot-session-secret
gcloud secrets delete campuspilot-gemini-key
# Firestore data (irreversible): delete the database in the console or
# gcloud firestore databases delete --database='(default)'
gcloud iam service-accounts delete "${RUNTIME_SA}"
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Status shows "Temporary" storage with Firestore enabled (`memory_fallback`) | Firestore API not enabled, database missing, or missing `roles/datastore.user` |
| Planner shows "Built-in planner" with a key set | Secret not mounted as `GEMINI_API_KEY`, or the runtime SA lacks `secretAccessor` |
| Approval returns "no longer available" | Instance restarted or scaled to zero; run the goal again |
| Requests take tens of seconds / approvals time out (504) | Service running on the first-generation environment; redeploy with `--execution-environment=gen2` |
| Everyone loses sessions after deploy | `SESSION_SECRET` not set (random key per instance) |
