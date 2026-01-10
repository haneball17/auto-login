from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .logger import setup_logging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="自动登录配置校验与入口")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="配置文件路径",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="环境变量文件路径",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="项目根目录",
    )
    parser.add_argument(
        "--skip-path-check",
        action="store_true",
        help="跳过路径与锚点校验",
    )
    return parser


def _format_schedule(config) -> str:
    schedule = config.schedule
    if schedule.mode == "random_window":
        windows = [
            f"{window.center}±{window.jitter_minutes}分钟"
            for window in schedule.random_windows
        ]
        return f"随机窗口: {', '.join(windows)}"
    return f"固定时间: {', '.join(schedule.fixed_times)}"


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    log_dir = base_dir / "logs"
    logger = setup_logging(log_dir)

    config = load_config(
        config_path=base_dir / args.config,
        env_path=base_dir / args.env,
        base_dir=base_dir,
        validate_paths=not args.skip_path_check,
    )

    logger.info("配置加载成功")
    logger.info("调度模式: %s", config.schedule.mode)
    logger.info("调度明细: %s", _format_schedule(config))


if __name__ == "__main__":
    main()
