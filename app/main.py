from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .core import register_exception_handlers, setup_logging
from .core.cache import close_redis_pool, init_redis_pool
from .core.database import close_database, init_database
from .core.rate_limiting import register_rate_limiting


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────
    setup_logging(level=settings.LOG_LEVEL, json_logs=settings.ENV == "production")
    await init_database(settings.DATABASE_URL)
    await init_redis_pool(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD,
    )
    yield
    # ── Shutdown ─────────────────────────────────────────────────────
    await close_redis_pool()
    await close_database()


app = FastAPI(title="Production API", lifespan=lifespan)

register_exception_handlers(app)
register_rate_limiting(app)
