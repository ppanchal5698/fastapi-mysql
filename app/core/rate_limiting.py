from typing import Any, cast

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
from loguru import logger


# ── Limiter instance (import this in routers) ─────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,        # Key by client IP
    default_limits=["200/minute"],      # Global fallback limit
    headers_enabled=True,               # Adds X-RateLimit-* response headers
    # storage_uri="redis://localhost:6379"  # Uncomment for Redis-backed distributed limiting
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Replaces SlowAPI's default handler with structured JSON + logging.
    Must be registered via: app.add_exception_handler(RateLimitExceeded, ...)
    """
    logger.warning(
        "Rate limit exceeded | ip={} path={} detail={}",
        get_remote_address(request), request.url.path, exc.detail,
    )
    return JSONResponse(
        status_code=429,
        content={
            "error": "RATE_LIMIT_EXCEEDED",
            "message": f"Too many requests: {exc.detail}. Please retry later.",
        },
        headers={
            "Retry-After": "60",
            "X-RateLimit-Limit": str(exc.detail),
        },
    )


def register_rate_limiting(app: FastAPI) -> None:
    """
    Attach SlowAPI limiter and middleware to the FastAPI app.
    Call once in main.py.

    Per-route usage:
        @router.get("/search")
        @limiter.limit("30/minute")
        async def search(request: Request, ...):
            ...

    Tiered limits per role:
        @limiter.limit("1000/minute", key_func=lambda req: req.state.user_id)
        @limiter.limit("30/minute")  # fallback for anonymous
    """
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, cast(Any, rate_limit_exceeded_handler))
    logger.info("Rate limiting registered | default=200/minute")


# ── Prebuilt limit strings for reuse across routers ───────────────────────────
class Limits:
    """Named rate limit constants — import and use in @limiter.limit(Limits.AUTH)"""
    AUTH = "10/minute"           # Login / token endpoints
    READ = "200/minute"          # GET endpoints
    WRITE = "60/minute"          # POST/PUT/PATCH
    DELETE = "20/minute"         # DELETE (destructive)
    SEARCH = "30/minute"         # Search / expensive queries
    WEBHOOK = "500/minute"       # High-volume inbound webhooks
    ADMIN = "1000/minute"        # Admin panel (trusted IPs only)
