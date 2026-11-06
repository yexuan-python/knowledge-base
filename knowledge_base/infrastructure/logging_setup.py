from __future__ import annotations

import logging
import logging.config
import os
import sys
from pathlib import Path

DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str | None = None, log_file: str = "logs/app.log") -> None:
    """Configure application-wide logging once and allow later level updates."""
    # 确保日志目录存在
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_level = (level or os.getenv("KB_LOG_LEVEL", "INFO")).upper()

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": DEFAULT_LOG_FORMAT,
                    "datefmt": DEFAULT_DATE_FORMAT,
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "stream": sys.stdout,
                },
                "file": {
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "filename": log_file,
                    "formatter": "standard",
                    "encoding": "utf-8",
                    "when": "midnight",
                    "interval": 1,
                    "backupCount": 7,
                }
            },
            "root": {
                "handlers": ["console", "file"],
                "level": resolved_level,
            },
            "loggers": {
                "uvicorn": {"level": resolved_level, "handlers": ["console"], "propagate": False},
                "uvicorn.error": {"level": resolved_level, "handlers": ["console", "file"], "propagate": False},
                "uvicorn.access": {"level": resolved_level, "handlers": ["console", "file"], "propagate": False},
            },
        }
    )

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
