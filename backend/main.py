from collections import deque
from http.cookies import SimpleCookie
import logging
import os
from pathlib import Path
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # python-dotenv is optional at runtime
    pass

try:
    from api.agent import router as agent_router
    from services.identity import (
        SESSION_COOKIE_NAME,
        SESSION_MAX_AGE_SECONDS,
        bind_user,
        get_identity_mode,
        new_session_cookie,
        reset_user,
        user_from_cookie,
    )
    from services.persistence import DEFAULT_USER_ID
except ImportError:
    from backend.api.agent import router as agent_router
    from backend.services.identity import (
        SESSION_COOKIE_NAME,
        SESSION_MAX_AGE_SECONDS,
        bind_user,
        get_identity_mode,
        new_session_cookie,
        reset_user,
        user_from_cookie,
    )
    from backend.services.persistence import DEFAULT_USER_ID

logger = logging.getLogger("campuspilot")

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
DOCS_ENABLED = os.getenv("ENABLE_API_DOCS", "false" if IS_PRODUCTION else "true").strip().lower() == "true"
MAX_BODY_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(32 * 1024)))

app = FastAPI(
    title="CampusPilot AI",
    description="AI-powered autonomous personal assistant for students",
    version="0.2.0",
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)


# --------------------------------------------------------------------------- rate limiting


class RateLimiter:
    """Small in-process sliding-window limiter (per session or client IP). Single instance only."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    @staticmethod
    def limit() -> int:
        try:
            return max(0, int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")))
        except ValueError:
            return 60

    def allow(self, key: str) -> tuple[bool, int]:
        limit = self.limit()
        if limit == 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 10_000:
                cutoff = now - 60
                for k in [k for k, q in self._hits.items() if not q or q[-1] < cutoff]:
                    self._hits.pop(k, None)
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                return False, int(60 - (now - q[0])) + 1
            q.append(now)
            return True, 0


rate_limiter = RateLimiter()

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
_CSP = (
    b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    b"img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    b"frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "true" if IS_PRODUCTION else "false").strip().lower() == "true"


class SecurityMiddleware:
    """
    Pure ASGI middleware:
    - binds every request to an anonymous signed session (or the demo user in demo mode),
    - caps request body size,
    - rate-limits state-changing API calls,
    - adds security headers.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        headers = dict(scope.get("headers") or [])

        # 1. Body size cap (declared length and actual streamed bytes).
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > MAX_BODY_BYTES:
                    await self._json(send, 413, {"detail": "Request is too large."})
                    return
            except ValueError:
                await self._json(send, 400, {"detail": "Invalid Content-Length header."})
                return

        received = 0
        too_large = False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        # 2. Identity
        set_cookie_value = None
        if get_identity_mode() == "demo":
            user_id = DEFAULT_USER_ID
        else:
            user_id = None
            raw_cookie = headers.get(b"cookie")
            if raw_cookie:
                try:
                    jar = SimpleCookie()
                    jar.load(raw_cookie.decode("latin-1"))
                    morsel = jar.get(SESSION_COOKIE_NAME)
                    user_id = user_from_cookie(morsel.value if morsel else None)
                except Exception:
                    user_id = None
            if user_id is None:
                user_id, set_cookie_value = new_session_cookie()
                if not path.startswith("/api/"):
                    # Only API calls create sessions; static files stay cookie-free.
                    set_cookie_value = None

        # 3. Rate limit state-changing API calls.
        if path.startswith("/api/") and method in ("POST", "PUT", "PATCH", "DELETE"):
            client = scope.get("client") or ("unknown", 0)
            key = user_id if get_identity_mode() == "session" else f"ip:{client[0]}"
            allowed, retry_after = rate_limiter.allow(key)
            if not allowed:
                await self._json(
                    send,
                    429,
                    {"detail": "Too many requests. Please wait a moment and try again."},
                    extra=[(b"retry-after", str(retry_after).encode())],
                )
                return

        is_docs = path.startswith(_DOC_PATHS)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers") or [])
                hdrs.extend(_SECURITY_HEADERS)
                if not is_docs:
                    hdrs.append((b"content-security-policy", _CSP))
                if path.startswith("/api/"):
                    hdrs.append((b"cache-control", b"no-store"))
                if set_cookie_value:
                    cookie = (
                        f"{SESSION_COOKIE_NAME}={set_cookie_value}; Path=/; Max-Age={SESSION_MAX_AGE_SECONDS}; "
                        f"HttpOnly; SameSite=Lax" + ("; Secure" if _cookie_secure() else "")
                    )
                    hdrs.append((b"set-cookie", cookie.encode("latin-1")))
                message["headers"] = hdrs
            await send(message)

        token = bind_user(user_id)
        try:
            await self.app(scope, limited_receive, send_wrapper)
        finally:
            reset_user(token)
        if too_large:
            logger.warning("Rejected oversized streamed request body on %s", path)

    @staticmethod
    async def _json(send, status_code: int, body: dict, extra: list | None = None) -> None:
        import json

        payload = json.dumps(body).encode()
        hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
        hdrs.extend(_SECURITY_HEADERS)
        if extra:
            hdrs.extend(extra)
        await send({"type": "http.response.start", "status": status_code, "headers": hdrs})
        await send({"type": "http.response.body", "body": payload})


_default_origins = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "" if IS_PRODUCTION else _default_origins).split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
app.add_middleware(SecurityMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error. Please try again."})


# API routes
app.include_router(agent_router, prefix="/api/agent", tags=["Agent"])


@app.api_route(
    "/api/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
def api_fallback(subpath: str):
    """Ensure any unmatched /api route returns a clean 404 JSON API error."""
    raise HTTPException(status_code=404, detail="API endpoint not found")


@app.get("/health")
def health():
    return {"status": "healthy"}


# Frontend serving configuration
DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", str(DEFAULT_FRONTEND_DIR))).resolve()

# Mount /assets if directory exists
assets_dir = FRONTEND_DIR / "assets"
if assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/")
def root():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return {
        "message": "CampusPilot AI backend is running",
        "status": "ok",
    }


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    # Guard API routes from returning HTML
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    if FRONTEND_DIR.is_dir():
        candidate_file = (FRONTEND_DIR / full_path).resolve()
        # Prevent directory traversal attacks
        try:
            candidate_file.relative_to(FRONTEND_DIR)
            if candidate_file.is_file():
                return FileResponse(str(candidate_file))
        except ValueError:
            raise HTTPException(status_code=404, detail="Not Found")

        # Unknown file-like paths (e.g. /missing.js) are 404s, not the SPA shell.
        if "." in Path(full_path).name:
            raise HTTPException(status_code=404, detail="Not Found")

        # SPA fallback: return index.html for client-side routing
        index_file = FRONTEND_DIR / "index.html"
        if index_file.is_file():
            return FileResponse(str(index_file))

    raise HTTPException(status_code=404, detail="Not Found")
