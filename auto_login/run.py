from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import Account, ConfigError, get_logging_settings, load_config
from src.logger import init_logger
from src.process.launcher import LauncherService


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器，保持入口参数清晰可追踪。"""

    parser = argparse.ArgumentParser(description="auto-login 启动入口")
    default_config = Path(__file__).resolve().parent / "config.toml"
    parser.add_argument(
        "--config",
        default=str(default_config),
        help="配置文件路径（默认使用项目根目录下的 config.toml）",
    )
    parser.add_argument(
        "--test-launcher",
        action="store_true",
        help="仅测试启动器启动（真实环境验证）",
    )
    return parser


def _run_launcher_test(config, logger) -> int:
    """执行启动器真实环境测试。"""

    logger.info("开始启动器真实环境测试")
    service = LauncherService(config.launcher, logger)

    # 启动器仅需要账号名用于日志记录，密码不参与启动
    account_name = (
        config.accounts.pool[0].username if config.accounts.pool else "launcher_test"
    )
    account = Account(username=account_name, password="***")

    # 与流程策略保持一致，默认 30 秒作为启动超时时间
    success = service.start_launcher(account, timeout_seconds=30)
    if success:
        logger.info("启动器测试成功")
        return 0

    logger.error("启动器测试失败，请检查路径或环境")
    return 1


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

    if args.test_launcher:
        return _run_launcher_test(config, logger)

    logger.info("当前仅完成基础骨架，后续功能将逐步接入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
