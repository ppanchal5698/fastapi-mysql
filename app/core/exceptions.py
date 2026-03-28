from typing import Any, Optional, cast
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from loguru import logger


# ── Base Application Exception ────────────────────────────────────────────────
class AppException(Exception):
    """
    Root of the custom exception tree.
    All domain errors should subclass this.
    """
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: Optional[str] = None,
        detail: Optional[Any] = None,
        headers: Optional[dict] = None,
    ):
        self.message = message or self.__class__.message
        self.detail = detail
        self.headers = headers
        super().__init__(self.message)

    def to_dict(self) -> dict:
        payload = {
            "error": self.error_code,
            "message": self.message,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


# ── HTTP Domain Exceptions ────────────────────────────────────────────────────
class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"
    message = "The requested resource was not found."


class UnauthorizedError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "UNAUTHORIZED"
    message = "Authentication credentials are missing or invalid."

    def __init__(self, message: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.headers = {"WWW-Authenticate": "Bearer"}


class ForbiddenError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"
    message = "Resource already exists or state conflict detected."


class ValidationError(AppException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"
    message = "Request payload validation failed."


class BadRequestError(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "BAD_REQUEST"
    message = "The request is malformed or contains invalid parameters."


class RateLimitError(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests. Please slow down."

    def __init__(self, retry_after: int = 60, message: Optional[str] = None, **kwargs: Any):
        super().__init__(message, **kwargs)
        self.headers = {"Retry-After": str(retry_after)}


class ServiceUnavailableError(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "SERVICE_UNAVAILABLE"
    message = "A downstream service is temporarily unavailable."


class DatabaseError(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "DATABASE_ERROR"
    message = "A database operation failed."


class CacheError(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "CACHE_ERROR"
    message = "Cache operation failed."


# ── Exception Handlers ────────────────────────────────────────────────────────
async def _app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    logger.warning(
        "AppException | path={} method={} error={} message={}",
        request.url.path, request.method, exc.error_code, exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
        headers=exc.headers or {},
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    logger.warning(
        "HTTPException | path={} status={} detail={}",
        request.url.path, exc.status_code, exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "HTTP_ERROR", "message": str(exc.detail)},
        headers=getattr(exc, "headers", {}),
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": " → ".join(str(l) for l in err["loc"]), "message": err["msg"]}
        for err in exc.errors()
    ]
    logger.warning("ValidationError | path={} errors={}", request.url.path, errors)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "VALIDATION_ERROR", "message": "Request validation failed.", "detail": errors},
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception | path={} method={} error={}",
        request.url.path, request.method, str(exc),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers on the FastAPI app.
    Call this in main.py after creating `app = FastAPI(...)`.
    """
    app.add_exception_handler(AppException, cast(Any, _app_exception_handler))
    app.add_exception_handler(StarletteHTTPException, cast(Any, _http_exception_handler))
    app.add_exception_handler(RequestValidationError, cast(Any, _validation_exception_handler))
    app.add_exception_handler(Exception, cast(Any, _unhandled_exception_handler))
    logger.info("Exception handlers registered")
