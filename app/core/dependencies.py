from typing import Annotated

import jwt
import redis.asyncio as aioredis
from fastapi import Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from .cache import RedisCache, get_cache
from .database import get_db
from .exceptions import ForbiddenError, UnauthorizedError
from .logging import logger


DBSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[aioredis.Redis, Depends(get_cache)]


async def get_cache_helper(cache: RedisClient) -> RedisCache:
    """Returns a namespaced RedisCache wrapper."""
    return RedisCache(cache, namespace="app")


class PaginationParams:
    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
        size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.size = size
        self.offset = (page - 1) * size
        self.limit = size


Pagination = Annotated[PaginationParams, Depends(PaginationParams)]


class TokenPayload:
    def __init__(self, user_id: int, email: str, roles: list[str]):
        self.user_id = user_id
        self.email = email
        self.roles = roles


def _parse_token_payload(payload: dict[str, object]) -> TokenPayload:
    raw_sub = payload.get("sub")
    try:
        user_id = int(raw_sub) if raw_sub is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        user_id = None
    if user_id is None:
        raise UnauthorizedError("Token subject (sub) is missing or invalid.")

    email = payload.get("email")
    if email is None or not isinstance(email, str):
        raise UnauthorizedError("Token is missing a valid email claim.")

    roles_raw = payload.get("roles", [])
    roles: list[str] = [str(r) for r in roles_raw] if isinstance(roles_raw, list) else []

    return TokenPayload(user_id=user_id, email=email, roles=roles)


async def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TokenPayload:
    """
    Validates Bearer JWT from Authorization header.
    Raises UnauthorizedError on failure — caught by global exception handler.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header.")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Token has expired.")
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError(f"Invalid token: {exc}")

    return _parse_token_payload(payload)


async def get_optional_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TokenPayload | None:
    """Returns parsed user when a valid Bearer token is present; otherwise None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.InvalidTokenError:
        return None

    try:
        return _parse_token_payload(payload)
    except UnauthorizedError:
        return None


CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]
OptionalUser = Annotated[TokenPayload | None, Depends(get_optional_user)]


def require_roles(*required_roles: str):
    """
    Role-based access control dependency factory.

    Usage:
        @router.delete("/admin/users/{id}")
        async def delete_user(
            user: CurrentUser,
            _: None = Depends(require_roles("admin", "superuser")),
        ):
    """

    async def role_checker(current_user: CurrentUser) -> None:
        if not any(role in current_user.roles for role in required_roles):
            logger.warning(
                "RBAC denied | user_id={} required={} has={}",
                current_user.user_id,
                required_roles,
                current_user.roles,
            )
            raise ForbiddenError(f"Requires one of roles: {list(required_roles)}")

    return role_checker
