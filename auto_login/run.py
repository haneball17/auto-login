from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import ConfigError, get_logging_settings, load_config
from src.logger import init_logger


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器，保持入口参数清晰可追踪。"""

    parser = argparse.ArgumentParser(description="auto-login 启动入口")
    default_config = Path(__file__).resolve().parent / "config.toml"
    parser.add_argument(
        "--config",
        default=str(default_config),
        help="配置文件路径（默认使用项目根目录下的 config.toml）",
    )
    return parser


def main(argv: list[str]) -> int:
    """主入口：加载配置、初始化日志、输出启动信息。"""

    parser = _build_parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config)

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ConfigError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"启动失败：未知错误：{exc}", file=sys.stderr)
        return 1

    log_dir, log_level = get_logging_settings(config)
    logger = init_logger(log_dir, log_level)

    logger.info("配置加载完成，配置路径：%s", config.config_path)
    logger.info("应用名称：%s", config.app_name)
    logger.info("校验模式：strict_paths=%s", config.validation.strict_paths)
    logger.info("当前仅完成基础骨架，后续功能将逐步接入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
