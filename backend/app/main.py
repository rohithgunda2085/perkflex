"""PerkFlex API (FastAPI).

Run locally:   npm run api           (or: cd backend && ../../.venv/bin/python -m uvicorn app.main:app --port 3001)
In a container: see backend/Dockerfile
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .db import close_pool, open_pool, request_connection
from .email.ses import worker_loop
from .routes import admin, advisor, assistant, auth, travel
from .routes import email as email_routes

log = logging.getLogger("perkflex")
MAX_BODY_BYTES = 8 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if len(settings.session_secret) < 32:
        raise RuntimeError("SESSION_SECRET must be set to at least 32 characters.")
    open_pool()
    # Email is sent by a small loop inside the API when SES is configured. Several tasks can run it at once.
    sender = asyncio.create_task(worker_loop(settings)) if settings.email_enabled and settings.email_from else None
    yield
    if sender:
        sender.cancel()
    close_pool()


app = FastAPI(title="PerkFlex API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def protect(request: Request, call_next):
    """Caps request size and keeps API responses out of caches."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return JSONResponse({"error": "Request too large."}, status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def bad_request(_: Request, exc: RequestValidationError):
    # Field names only: never echo back what the client sent.
    fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "request" for e in exc.errors()})
    return JSONResponse({"error": "Invalid request.", "fields": fields}, status_code=422)


@app.exception_handler(Exception)
async def unexpected(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"error": "Something went wrong. Please try again."}, status_code=500)


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    detail = "Not found." if exc.status_code == 404 and exc.detail == "Not Found" else exc.detail
    return JSONResponse({"error": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.get("/api/health")
def health() -> dict[str, bool]:
    with request_connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


app.include_router(auth.router)
app.include_router(travel.router)
app.include_router(assistant.router)
app.include_router(advisor.router)
app.include_router(admin.router)
app.include_router(email_routes.router)
