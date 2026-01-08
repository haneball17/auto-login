from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# 将 auto_login 目录加入路径，确保可以导入 src 包
AUTO_LOGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTO_LOGIN_DIR))

from src.config import Account, LauncherConfig
from src.process.launcher import LauncherService


class FakeTime:
    """可控时间源，用于模拟时间流逝。"""

    def __init__(self, start: float = 0.0, step: float = 1.0) -> None:
        self._current = start
        self._step = step

    def monotonic(self) -> float:
        """每次调用推进固定步长，避免真实等待。"""

        value = self._current
        self._current += self._step
        return value


class LauncherServiceTest(unittest.TestCase):
    """启动器服务单元测试。"""

    def _make_service(self, exe_path: str) -> LauncherService:
        """构造启动器服务实例。"""

        config = LauncherConfig(
            exe_path=exe_path,
            game_process_name="DNF.exe",
            game_window_title_keyword="地下城与勇士",
        )
        logger = Mock()
        return LauncherService(config, logger)

    def _make_account(self) -> Account:
        """构造测试账号对象。"""

        return Account(username="tester", password="secret")

    def test_start_launcher_success(self) -> None:
        """启动器存活超过最小阈值后应返回成功。"""

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            exe_path = temp_file.name

        service = self._make_service(exe_path)
        account = self._make_account()
        fake_time = FakeTime(start=0.0, step=1.0)

        mock_process = SimpleNamespace(pid=1234, poll=Mock(return_value=None))

        with (
            patch("src.process.launcher.subprocess.Popen", return_value=mock_process),
            patch("src.process.launcher.time.monotonic", side_effect=fake_time.monotonic),
            patch("src.process.launcher.time.sleep", return_value=None),
        ):
            result = service._start_launcher_detail(account, timeout_seconds=3)

        Path(exe_path).unlink(missing_ok=True)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "启动成功")

    def test_start_launcher_early_exit(self) -> None:
        """进程提前退出时应返回失败并附带退出码。"""

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            exe_path = temp_file.name

        service = self._make_service(exe_path)
        account = self._make_account()
        fake_time = FakeTime(start=0.0, step=1.0)

        mock_process = SimpleNamespace(pid=5678, poll=Mock(return_value=1))

        with (
            patch("src.process.launcher.subprocess.Popen", return_value=mock_process),
            patch("src.process.launcher.time.monotonic", side_effect=fake_time.monotonic),
            patch("src.process.launcher.time.sleep", return_value=None),
        ):
            result = service._start_launcher_detail(account, timeout_seconds=5)

        Path(exe_path).unlink(missing_ok=True)
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 1)

    def test_start_launcher_timeout(self) -> None:
        """超时未满足存活阈值时应返回超时失败。"""

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            exe_path = temp_file.name

        service = self._make_service(exe_path)
        account = self._make_account()
        # 步长较大，确保循环快速结束并触发超时逻辑
        fake_time = FakeTime(start=0.0, step=10.0)

        mock_process = SimpleNamespace(pid=9999, poll=Mock(return_value=None))

        with (
            patch("src.process.launcher.subprocess.Popen", return_value=mock_process),
            patch("src.process.launcher.time.monotonic", side_effect=fake_time.monotonic),
            patch("src.process.launcher.time.sleep", return_value=None),
        ):
            result = service._start_launcher_detail(account, timeout_seconds=3)

        Path(exe_path).unlink(missing_ok=True)
        self.assertFalse(result.success)
        self.assertEqual(result.message, "登录器启动超时")

    def test_start_launcher_invalid_path(self) -> None:
        """路径无效时应返回失败。"""

        temp_dir = tempfile.TemporaryDirectory()
        exe_path = Path(temp_dir.name) / "missing.exe"

        service = self._make_service(str(exe_path))
        account = self._make_account()

        result = service.start_launcher(account, timeout_seconds=3)
        temp_dir.cleanup()

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
