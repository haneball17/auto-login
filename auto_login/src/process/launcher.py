from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from src.config import Account, LauncherConfig
from src.ui.capture import capture_screen
from src.ui.match import load_template, match_template


@dataclass(frozen=True)
class LauncherStartResult:
    """启动器启动结果。"""

    success: bool
    message: str
    exit_code: int | None = None


class LauncherService:
    """启动器管理服务，负责启动并检测启动器进程。"""

    def __init__(self, config: LauncherConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger

    def _build_creation_flags(self) -> int:
        """构建跨平台 creationflags，避免在非 Windows 报错。"""

        if sys.platform.startswith("win"):
            return subprocess.CREATE_NEW_PROCESS_GROUP
        return 0

    def _validate_exe_path(self) -> Path | None:
        """校验启动器路径有效性。"""

        exe_path = Path(self._config.exe_path)
        if not exe_path.exists():
            self._logger.error("启动器路径不存在：%s", exe_path)
            return None
        if not exe_path.is_file():
            self._logger.error("启动器路径不是文件：%s", exe_path)
            return None
        return exe_path

    def _start_launcher_detail(
        self, account: Account, timeout_seconds: int
    ) -> LauncherStartResult:
        """
        启动登录器并确认其进程存活。

        规则：
        - 启动器进程需至少存活 1~2 秒（取最小值），视为启动成功
        - 若进程快速退出或超时未存活，视为失败
        """

        exe_path = self._validate_exe_path()
        if exe_path is None:
            return LauncherStartResult(False, "启动器路径无效")

        self._logger.info(
            "启动登录器：account=%s exe=%s",
            account.username,
            exe_path,
        )

        try:
            process = subprocess.Popen(
                [str(exe_path)],
                cwd=str(exe_path.parent),
                creationflags=self._build_creation_flags(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self._logger.exception("启动登录器异常：%s", exc)
            return LauncherStartResult(False, f"启动登录器异常：{exc}")

        start_time = time.monotonic()
        min_alive_seconds = min(2, max(1, timeout_seconds))

        while time.monotonic() - start_time < timeout_seconds:
            exit_code = process.poll()
            if exit_code is None:
                # 进程存活时间达到最小阈值，认为启动成功
                if time.monotonic() - start_time >= min_alive_seconds:
                    self._logger.info("登录器启动成功：pid=%s", process.pid)
                    return LauncherStartResult(True, "启动成功")
            else:
                # 进程提前退出，视为启动失败
                self._logger.error("登录器提前退出：exit_code=%s", exit_code)
                return LauncherStartResult(
                    False, "登录器提前退出", exit_code=exit_code
                )
            time.sleep(0.2)

        self._logger.error("登录器启动超时：timeout=%s", timeout_seconds)
        return LauncherStartResult(False, "登录器启动超时")

    def start_launcher(self, account: Account, timeout_seconds: int) -> bool:
        """对外启动接口，满足流程依赖的布尔返回约定。"""

        result = self._start_launcher_detail(account, timeout_seconds)
        return result.success

    def wait_launcher_enable(self, timeout_seconds: int) -> bool:
        """
        等待启动按钮变为可用状态（蓝色）。

        逻辑：
        - 以模板匹配判断“可用/不可用”状态
        - 可用模板命中即成功，不可用模板命中则继续等待
        - 超时则失败
        """

        try:
            enable_template = load_template(self._config.button_enable_template)
            disable_template = load_template(self._config.button_disable_template)
        except Exception as exc:
            self._logger.exception("加载启动器模板失败：%s", exc)
            return False

        threshold = self._config.button_threshold
        interval = max(0.1, self._config.button_check_interval_seconds)
        start_time = time.monotonic()

        self._logger.info(
            "等待启动按钮可用：timeout=%s threshold=%s",
            timeout_seconds,
            threshold,
        )

        while time.monotonic() - start_time < timeout_seconds:
            try:
                screen = capture_screen()
                enable_hit, enable_score, _ = match_template(
                    screen, enable_template, threshold
                )
                disable_hit, disable_score, _ = match_template(
                    screen, disable_template, threshold
                )
            except Exception as exc:
                self._logger.exception("启动器截图或匹配失败：%s", exc)
                return False

            if enable_hit:
                self._logger.info(
                    "启动按钮已可用：score=%.3f", enable_score
                )
                return True

            self._logger.debug(
                "启动按钮未就绪：enable=%.3f disable=%.3f threshold=%.3f",
                enable_score,
                disable_score,
                threshold,
            )
            time.sleep(interval)

        self._logger.error("等待启动按钮可用超时：timeout=%s", timeout_seconds)
        return False
