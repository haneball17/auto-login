from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

DEFAULT_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.log"

    logger = logging.getLogger("auto_login")
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
