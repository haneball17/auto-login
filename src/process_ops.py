from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("auto_login")


def start_launcher(exe_path: Path) -> subprocess.Popen:
    if not exe_path.is_file():
        raise FileNotFoundError(f"启动器路径不存在: {exe_path}")

    logger.info("启动登录器: %s", exe_path)
    return subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))


def wait_launcher_window(
    title_keyword: str,
    timeout_seconds: int = 30,
    poll_interval: float = 1.0,
) -> int:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")
    if poll_interval <= 0:
        raise ValueError("poll_interval 必须大于 0")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        hwnd = select_latest_active_window(title_keyword)
        if hwnd is not None:
            return hwnd
        time.sleep(poll_interval)

    raise TimeoutError(f"等待启动器窗口超时: {title_keyword}")


def ensure_launcher_window(
    exe_path: Path,
    title_keyword: str,
    timeout_seconds: int = 30,
    poll_interval: float = 1.0,
) -> int:
    hwnd = select_latest_active_window(title_keyword)
    if hwnd is not None:
        logger.info("检测到已运行的启动器窗口，直接激活")
        activate_window(hwnd)
        return hwnd

    start_launcher(exe_path)
    hwnd = wait_launcher_window(
        title_keyword=title_keyword,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
    )
    activate_window(hwnd)
    return hwnd


def select_latest_active_window(title_keyword: str) -> int | None:
    win32gui = _import_win32gui()

    foreground = win32gui.GetForegroundWindow()
    if foreground and title_keyword in win32gui.GetWindowText(foreground):
        return foreground

    matches = _find_windows_by_title(title_keyword)
    return matches[0] if matches else None


def _find_windows_by_title(title_keyword: str) -> list[int]:
    win32gui = _import_win32gui()
    matches: list[int] = []

    def _enum_handler(hwnd: int, extra: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title_keyword in title:
            matches.append(hwnd)

    win32gui.EnumWindows(_enum_handler, None)
    return matches


def activate_window(hwnd: int) -> None:
    win32gui = _import_win32gui()
    try:
        import win32con
    except ImportError as exc:
        raise RuntimeError("win32con 不可用，无法激活窗口") from exc

    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)


def _import_win32gui():
    try:
        import win32gui
    except ImportError as exc:
        raise RuntimeError("win32gui 不可用，无法定位窗口") from exc
    return win32gui
