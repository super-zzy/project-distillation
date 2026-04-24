from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_inited = False


def init_logging(app_name: str = "project-distillation") -> None:
    """
    Initialize global logging once.

    Env:
    - LOG_LEVEL: DEBUG/INFO/WARNING/ERROR
    - LOG_DIR: directory for log files (default ./logs)
    - LOG_TO_FILE: 1/0 (default 1)
    """
    global _inited
    if _inited:
        return

    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # File handler
    log_to_file = (os.getenv("LOG_TO_FILE") or "1").strip() not in ("0", "false", "False")
    if log_to_file:
        log_dir = Path(os.getenv("LOG_DIR") or "./logs").resolve()
        log_dir.mkdir(parents=True, exist_ok=True)
        fp = log_dir / f"{app_name}.log"
        fh = RotatingFileHandler(
            fp,
            maxBytes=10 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    _inited = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name or "app")

