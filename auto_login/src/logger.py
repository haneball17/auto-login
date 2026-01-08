from __future__ import annotations

import logging
from pathlib import Path


def _coerce_level(level: str) -> int:
    """将字符串级别转换为 logging 等级，非法值回退为 INFO。"""

    value = str(level).upper()
    mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return mapping.get(value, logging.INFO)


def init_logger(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """初始化日志系统，输出到控制台与文件，确保可追溯。"""

    logger = logging.getLogger("auto_login")
    if logger.handlers:
        # 避免重复初始化导致日志重复输出
        return logger

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "auto_login.log"

    logger.setLevel(_coerce_level(level))
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logger.level)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logger.level)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    logger.info("日志系统初始化完成，日志目录：%s", log_dir)
    return logger
