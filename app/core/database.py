from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from sqlalchemy.pool import AsyncAdaptedQueuePool
from loguru import logger


# ── Declarative Base (shared across all models) ───────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Module-level engine & session factory (set in init_database) ───────────────
engine: AsyncEngine = None  # type: ignore
AsyncSessionFactory: async_sessionmaker = None  # type: ignore


async def init_database(
    db_url: str,
    pool_size: int = 20,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,
    echo: bool = False,
) -> None:
    """
    Called once at app startup inside lifespan.

    Pool tuning guide (heavy load):
      pool_size=20   → baseline persistent connections
      max_overflow=10 → burst connections (total max = 30)
      pool_recycle=1800 → recycle connections every 30 min (avoids MySQL "gone away")
      pool_timeout=30 → wait up to 30s for a free connection before raising
    """
    global engine, AsyncSessionFactory

    # aiomysql driver: pip install aiomysql
    # Ensure URL format: mysql+aiomysql://user:pass@host:3306/dbname
    engine = create_async_engine(
        db_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,           # Validates connection before checkout
        poolclass=AsyncAdaptedQueuePool,
        connect_args={
            "charset": "utf8mb4",
            "connect_timeout": 10,
        },
    )

    AsyncSessionFactory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,       # Avoid lazy-load errors after commit
        autocommit=False,
        autoflush=False,
    )

    # Validate DB connectivity
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database engine initialized | pool_size={} max_overflow={}", pool_size, max_overflow)


async def close_database() -> None:
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database engine disposed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields an async DB session.
    Automatically rolls back on exception, commits on success.

    Usage:
        async def endpoint(db: AsyncSession = Depends(get_db)):
    """
    if AsyncSessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_database() in lifespan.")

    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def db_health_check() -> bool:
    """Returns True if database is reachable — used in /health endpoint."""
    if engine is None:
        logger.error("DB health check failed | error=engine not initialized")
        return False
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("DB health check failed | error={}", exc)
        return False
