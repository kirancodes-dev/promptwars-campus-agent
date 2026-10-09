# ==========================================
# Stage 1: Build frontend assets
# ==========================================
# Vite 8 requires Node ^20.19 or >=22.12.
FROM node:22-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend ./
RUN npm run build

# ==========================================
# Stage 2: Production runtime
# ==========================================
FROM python:3.12-slim AS runner

# Non-secret defaults only. Secrets (GEMINI_API_KEY, SESSION_SECRET) are injected
# at deploy time from Secret Manager, never baked into the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    APP_ENV=production \
    IDENTITY_MODE=session \
    FRONTEND_DIR=/app/frontend/dist \
    GEMINI_MODEL=gemini-2.5-flash \
    FIRESTORE_ENABLED=false

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/backend
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8080\")}/health', timeout=4)" || exit 1

# One worker: approvals and rate limits live in process memory (see docs/deployment.md).
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
