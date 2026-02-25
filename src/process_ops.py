from __future__ import annotations

import logging
import subprocess
import time
import ctypes
from pathlib import Path

import psutil

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


def wait_game_window(
    title_keyword: str,
    timeout_seconds: int = 60,
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

    raise TimeoutError(f"等待游戏窗口超时: {title_keyword}")


def ensure_launcher_window(
    exe_path: Path,
    title_keyword: str,
    process_name: str | None,
    timeout_seconds: int = 30,
    poll_interval: float = 1.0,
) -> int:
    hwnd = select_latest_active_window(title_keyword)
    if hwnd is not None:
        logger.info("检测到已运行的启动器窗口，直接激活")
        activate_window(hwnd)
        return hwnd

    if process_name and process_exists(process_name):
        logger.info("启动器进程存在但未发现窗口，尝试重启唤起窗口")
        start_launcher(exe_path)
        try:
            hwnd = wait_launcher_window(
                title_keyword=title_keyword,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )
            activate_window(hwnd)
            return hwnd
        except Exception as exc:
            logger.warning("重启唤起窗口失败，准备强制重启: %s", exc)
            killed = kill_processes(process_name)
            logger.info("强制结束启动器进程: count=%d", killed)
            start_launcher(exe_path)
            hwnd = wait_launcher_window(
                title_keyword=title_keyword,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )
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


def wait_process_exit(
    process_name: str,
    timeout_seconds: int = 30,
    poll_interval: float = 1.0,
) -> bool:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")
    if poll_interval <= 0:
        raise ValueError("poll_interval 必须大于 0")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _process_exists(process_name):
            return True
        time.sleep(poll_interval)
    return not _process_exists(process_name)


def process_exists(process_name: str) -> bool:
    return _process_exists(process_name)


def kill_processes(process_name: str) -> int:
    killed = 0
    matched = 0
    for proc in psutil.process_iter(["name"]):
        try:
            if not _process_name_matches(process_name, proc.info.get("name")):
                continue
            matched += 1
            proc.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if matched == 0:
        logger.warning("未找到进程: %s", process_name)
    return killed


def _process_exists(process_name: str) -> bool:
    for proc in psutil.process_iter(["name"]):
        try:
            if _process_name_matches(process_name, proc.info.get("name")):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def close_window_by_title(title_keyword: str) -> bool:
    hwnd = select_latest_active_window(title_keyword)
    if hwnd is None:
        return False
    try:
        import win32con
        win32gui = _import_win32gui()
        activate_window(hwnd)
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return True
    except Exception as exc:
        logger.warning("关闭窗口失败: %s", exc)
        return False


def _process_name_matches(target: str, actual: str | None) -> bool:
    if not actual:
        return False
    return _normalize_process_name(target) == _normalize_process_name(actual)


def _normalize_process_name(name: str) -> str:
    value = name.strip().lower()
    if value.endswith(".exe"):
        value = value[:-4]
    return value


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


def recover_window_to_visible(
    title_keyword: str,
    padding_px: int = 24,
    allow_resize: bool = False,
) -> dict:
    try:
        import win32con
    except ImportError as exc:
        return {
            "success": False,
            "hwnd": None,
            "before_rect": None,
            "after_rect": None,
            "virtual_rect": None,
            "reason": f"win32con_import_error:{exc}",
        }

    win32gui = _import_win32gui()
    hwnd = select_latest_active_window(title_keyword)
    if hwnd is None:
        return {
            "success": False,
            "hwnd": None,
            "before_rect": None,
            "after_rect": None,
            "virtual_rect": None,
            "reason": "window_not_found",
        }

    try:
        before_rect = _get_window_rect_by_hwnd(win32gui, hwnd)
    except Exception as exc:
        return {
            "success": False,
            "hwnd": hwnd,
            "before_rect": None,
            "after_rect": None,
            "virtual_rect": None,
            "reason": f"read_before_rect_failed:{exc}",
        }

    try:
        activate_window(hwnd)
    except Exception:
        pass

    virtual_rect = _get_virtual_screen_rect()
    try:
        import win32api
        import win32con

        visible_rect = _get_monitor_work_rect_by_hwnd(
            win32api,
            win32con,
            hwnd,
        )
    except Exception as exc:
        logger.warning("读取显示器工作区失败，回退虚拟桌面: %s", exc)
        visible_rect = virtual_rect
    target_rect = _compute_recovered_window_rect(
        window_rect=before_rect,
        visible_rect=visible_rect,
        padding_px=max(0, int(padding_px)),
        allow_resize=allow_resize,
    )
    target_left, target_top, target_width, target_height = target_rect

    flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
    if (
        target_width == before_rect[2]
        and target_height == before_rect[3]
    ) or not allow_resize:
        flags |= win32con.SWP_NOSIZE

    try:
        win32gui.SetWindowPos(
            hwnd,
            0,
            int(target_left),
            int(target_top),
            int(target_width),
            int(target_height),
            flags,
        )
    except Exception as exc:
        return {
            "success": False,
            "hwnd": hwnd,
            "before_rect": before_rect,
            "after_rect": None,
            "visible_rect": visible_rect,
            "virtual_rect": virtual_rect,
            "reason": f"set_window_pos_failed:{exc}",
        }

    try:
        after_rect = _get_window_rect_by_hwnd(win32gui, hwnd)
    except Exception as exc:
        return {
            "success": False,
            "hwnd": hwnd,
            "before_rect": before_rect,
            "after_rect": None,
            "visible_rect": visible_rect,
            "virtual_rect": virtual_rect,
            "reason": f"read_after_rect_failed:{exc}",
        }

    return {
        "success": True,
        "hwnd": hwnd,
        "before_rect": before_rect,
        "after_rect": after_rect,
        "visible_rect": visible_rect,
        "virtual_rect": virtual_rect,
        "reason": (
            "window_moved"
            if before_rect != after_rect
            else "window_unchanged"
        ),
    }


def _compute_recovered_window_rect(
    window_rect: tuple[int, int, int, int],
    visible_rect: tuple[int, int, int, int],
    padding_px: int,
    allow_resize: bool,
) -> tuple[int, int, int, int]:
    left, top, width, height = window_rect
    visible_left, visible_top, visible_width, visible_height = visible_rect
    padding = max(0, int(padding_px))

    target_width = width
    target_height = height
    if allow_resize:
        max_width = max(1, visible_width - padding * 2)
        max_height = max(1, visible_height - padding * 2)
        target_width = min(target_width, max_width)
        target_height = min(target_height, max_height)

    min_left = visible_left + padding
    max_left = visible_left + visible_width - target_width - padding
    min_top = visible_top + padding
    max_top = visible_top + visible_height - target_height - padding

    if max_left < min_left:
        target_left = visible_left
    else:
        target_left = min(max(left, min_left), max_left)

    if max_top < min_top:
        target_top = visible_top
    else:
        target_top = min(max(top, min_top), max_top)

    return (target_left, target_top, target_width, target_height)


def _get_window_rect_by_hwnd(
    win32gui,
    hwnd: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise ValueError(
            f"窗口尺寸无效: hwnd={hwnd}, rect={(left, top, right, bottom)}"
        )
    return (left, top, width, height)


def _get_virtual_screen_rect() -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    sm_xvirtualscreen = 76
    sm_yvirtualscreen = 77
    sm_cxvirtualscreen = 78
    sm_cyvirtualscreen = 79

    left = user32.GetSystemMetrics(sm_xvirtualscreen)
    top = user32.GetSystemMetrics(sm_yvirtualscreen)
    width = user32.GetSystemMetrics(sm_cxvirtualscreen)
    height = user32.GetSystemMetrics(sm_cyvirtualscreen)

    if width <= 1 or height <= 1:
        left = 0
        top = 0
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
    if width <= 1 or height <= 1:
        raise ValueError("虚拟桌面尺寸异常，无法复位窗口")
    return (left, top, width, height)


def get_window_work_rect(title_keyword: str) -> tuple[int, int, int, int]:
    try:
        import win32api
        import win32con
    except ImportError as exc:
        raise RuntimeError("win32api/win32con 不可用，无法读取工作区") from exc

    hwnd = select_latest_active_window(title_keyword)
    if hwnd is None:
        raise ValueError(f"未找到窗口: {title_keyword}")
    return _get_monitor_work_rect_by_hwnd(win32api, win32con, hwnd)


def _get_monitor_work_rect_by_hwnd(
    win32api,
    win32con,
    hwnd: int,
) -> tuple[int, int, int, int]:
    monitor = win32api.MonitorFromWindow(
        hwnd,
        win32con.MONITOR_DEFAULTTONEAREST,
    )
    info = win32api.GetMonitorInfo(monitor)
    work = info.get("Work")
    if not work:
        work = info.get("Monitor")
    if not work or len(work) != 4:
        raise ValueError(f"显示器信息异常: hwnd={hwnd}, info={info}")
    left, top, right, bottom = work
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise ValueError(f"工作区尺寸异常: work={work}")
    return (left, top, width, height)


def _import_win32gui():
    try:
        import win32gui
    except ImportError as exc:
        raise RuntimeError("win32gui 不可用，无法定位窗口") from exc
    return win32gui
