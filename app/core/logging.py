import sys
import logging
from pathlib import Path
from loguru import logger

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "app.log"


def setup_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """
    Configure Loguru for production.
    - Rotating file sink at logs/app.log (10MB per file, 7 days retention)
    - Stdout sink with colorized human-readable output
    - Intercepts stdlib `logging` (SQLAlchemy, uvicorn, etc.)
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Remove default Loguru handler
    logger.remove()

    # ── Stdout sink (dev-friendly, colorized) ──────────────────────────────
    logger.add(
        sys.stdout,
        level=level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        backtrace=True,
        diagnose=True,
    )

    # ── Rotating file sink (production) ────────────────────────────────────
    log_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{name}:{function}:{line} | {message}"
    )
    if json_logs:
        # Structured JSON for log aggregators (Datadog, ELK, Loki)
        log_format = "{message}"  # Loguru serialize=True handles JSON

    logger.add(
        str(LOG_FILE),
        level=level,
        format=log_format,
        rotation="10 MB",       # New file every 10 MB
        retention="7 days",     # Auto-delete logs older than 7 days
        compression="gz",       # Compress rotated logs
        enqueue=True,           # Thread-safe async writing
        backtrace=True,
        diagnose=False,         # Never expose internals in prod file logs
        serialize=json_logs,    # JSON mode for log shippers
    )

    # ── Intercept standard library logging (uvicorn, sqlalchemy) ──────────
    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for log_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(log_name).handlers = [InterceptHandler()]

    logger.info("Logging configured | file={} | level={}", LOG_FILE, level)
