from __future__ import annotations

import logging
import subprocess
import sys
import time

try:
    import psutil
except ModuleNotFoundError:  # pragma: no cover - 运行时依赖
    psutil = None


class GameProcessService:
    """游戏进程检测服务。"""

    def __init__(self, process_name: str, logger: logging.Logger) -> None:
        self._process_name = process_name
        self._logger = logger

    def _is_running_psutil(self) -> bool:
        """使用 psutil 检测进程是否存在。"""

        if psutil is None:
            return False
        try:
            for proc in psutil.process_iter(["name"]):
                name = proc.info.get("name")
                if name and name.lower() == self._process_name.lower():
                    return True
        except Exception:
            # psutil 可能因权限或进程变化抛错，记录后继续
            self._logger.debug("psutil 进程扫描异常", exc_info=True)
        return False

    def _is_running_fallback(self) -> bool:
        """使用系统命令兜底检测进程是否存在。"""

        if sys.platform.startswith("win"):
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {self._process_name}"],
                capture_output=True,
                text=True,
            )
            return self._process_name.lower() in result.stdout.lower()

        result = subprocess.run(
            ["ps", "-A", "-o", "comm="],
            capture_output=True,
            text=True,
        )
        return any(
            line.strip().lower() == self._process_name.lower()
            for line in result.stdout.splitlines()
        )

    def is_running(self) -> bool:
        """检测游戏进程是否存在。"""

        if self._is_running_psutil():
            return True
        return self._is_running_fallback()

    def wait_game_process(
        self, timeout_seconds: int, poll_interval_seconds: float = 1.0
    ) -> bool:
        """等待游戏进程出现，超时则失败。"""

        self._logger.info(
            "等待游戏进程出现：name=%s timeout=%s",
            self._process_name,
            timeout_seconds,
        )

        start_time = time.monotonic()
        interval = max(0.2, poll_interval_seconds)

        while time.monotonic() - start_time < timeout_seconds:
            if self.is_running():
                self._logger.info("检测到游戏进程：%s", self._process_name)
                return True
            time.sleep(interval)

        self._logger.error(
            "等待游戏进程超时：name=%s timeout=%s",
            self._process_name,
            timeout_seconds,
        )
        return False
