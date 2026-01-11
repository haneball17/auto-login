from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psutil

logger = logging.getLogger("auto_login")

_LOGIN_URL_PATTERN = re.compile(
    r"https?://[^\s\"']*launcher-login\.html\?[^\s\"']+"
)
_CLIPBOARD_RETRY_INTERVAL = 0.05
_CLIPBOARD_RETRY_TIMES = 3


@dataclass(frozen=True)
class LoginUrlInfo:
    url: str
    port: str
    state: str


def extract_login_url(text: str) -> LoginUrlInfo | None:
    match = _LOGIN_URL_PATTERN.search(text)
    if not match:
        return None
    url = match.group(0).strip("\"'")
    return _parse_login_url(url)


def wait_login_url(
    process_name: str,
    window_title_keyword: str | None,
    start_time: float,
    timeout_seconds: int,
    close_on_capture: bool = False,
    poll_interval: float = 0.2,
) -> LoginUrlInfo:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")
    if poll_interval <= 0:
        raise ValueError("poll_interval 必须大于 0")

    logger.info(
        "等待登录URL: 浏览器进程=%s, 超时=%ss",
        process_name,
        timeout_seconds,
    )
    deadline = time.time() + timeout_seconds
    min_create_time = max(start_time - 5.0, 0.0)
    last_report = 0.0
    last_clipboard_check = 0.0
    seen_process = False

    while time.time() < deadline:
        found_process = False
        for proc in psutil.process_iter(["name", "cmdline", "create_time"]):
            try:
                info = proc.info
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            if info.get("name") != process_name:
                continue
            found_process = True

            create_time = info.get("create_time") or 0.0
            if create_time < min_create_time:
                continue

            cmdline = info.get("cmdline") or []
            text = " ".join(str(part) for part in cmdline if part)
            login_info = extract_login_url(text)
            if login_info:
                logger.info("捕获登录URL: port=%s", login_info.port)
                if close_on_capture:
                    _close_login_tab_by_keyword(
                        process_name,
                        window_title_keyword,
                    )
                return login_info

        if found_process:
            seen_process = True
            now = time.time()
            if now - last_clipboard_check >= 1.0:
                login_info = _read_login_url_from_edge_clipboard(
                    process_name,
                    window_title_keyword,
                    close_on_capture,
                )
                if login_info:
                    return login_info
                last_clipboard_check = now
        now = time.time()
        if now - last_report >= 5.0:
            if seen_process:
                logger.info("等待登录URL中：已检测到浏览器进程")
            else:
                logger.info("等待登录URL中：未检测到浏览器进程")
            last_report = now

        time.sleep(poll_interval)

    raise TimeoutError("未捕获到登录URL，无法继续网页登录")


def perform_web_login(
    login_url: str,
    username: str,
    password: str,
    username_selector: str,
    password_selector: str,
    login_button_selector: str,
    success_selector: str,
    timeout_seconds: int,
    evidence_dir: Path | None = None,
) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")

    logger.info("开始网页登录")
    page = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                timeout_ms = int(timeout_seconds * 1000)
                page.goto(
                    login_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                page.fill(username_selector, username, timeout=timeout_ms)
                page.fill(password_selector, password, timeout=timeout_ms)
                page.click(login_button_selector, timeout=timeout_ms)
                page.wait_for_selector(success_selector, timeout=timeout_ms)
                logger.info("网页登录成功")
            except PlaywrightTimeoutError as exc:
                _save_web_login_evidence(
                    evidence_dir,
                    page,
                    exc,
                    "web_login_timeout",
                )
                raise TimeoutError("网页登录超时") from exc
            except Exception as exc:
                _save_web_login_evidence(
                    evidence_dir,
                    page,
                    exc,
                    "web_login_failed",
                )
                raise
            finally:
                browser.close()
    finally:
        page = None


def _parse_login_url(url: str) -> LoginUrlInfo | None:
    parsed = urlparse(url)
    if "launcher-login.html" not in parsed.path:
        return None
    query = parse_qs(parsed.query)
    port = (query.get("port") or [None])[0]
    state = (query.get("state") or [None])[0]
    if not port or not state:
        return None
    return LoginUrlInfo(url=url, port=str(port), state=str(state))


def _read_login_url_from_edge_clipboard(
    process_name: str,
    window_title_keyword: str | None,
    close_on_capture: bool,
) -> LoginUrlInfo | None:
    try:
        import win32clipboard
        import win32con
        import win32gui
        import win32process
    except ImportError as exc:
        logger.warning("win32 组件不可用，无法读取浏览器地址栏: %s", exc)
        return None

    hwnd_list = _find_edge_windows(
        process_name,
        window_title_keyword,
        win32gui,
        win32process,
    )
    if not hwnd_list:
        return None

    from .process_ops import activate_window

    previous_hwnd = win32gui.GetForegroundWindow()
    previous_text = _get_clipboard_text(win32clipboard, win32con)

    try:
        activate_window(hwnd_list[0])
        time.sleep(0.2)
        for _ in range(3):
            _send_copy_address_shortcut()
            time.sleep(0.1)
            text = _get_clipboard_text(win32clipboard, win32con)
            login_info = extract_login_url(text or "")
            if login_info:
                logger.info("通过地址栏捕获登录URL: port=%s", login_info.port)
                if close_on_capture:
                    _close_login_tab_by_hwnd(
                        hwnd_list[0],
                        window_title_keyword,
                    )
                return login_info
    finally:
        if previous_text is not None:
            _set_clipboard_text(win32clipboard, win32con, previous_text)
        if previous_hwnd and previous_hwnd != hwnd_list[0]:
            try:
                activate_window(previous_hwnd)
            except Exception:
                pass
    return None


def _find_edge_windows(
    process_name: str,
    window_title_keyword: str | None,
    win32gui,
    win32process,
) -> list[int]:
    hwnd_list: list[int] = []

    def _enum_handler(hwnd: int, extra: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        if window_title_keyword and window_title_keyword not in title:
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            if psutil.Process(pid).name() != process_name:
                return
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        hwnd_list.append(hwnd)

    try:
        win32gui.EnumWindows(_enum_handler, None)
    except Exception as exc:
        logger.warning("枚举浏览器窗口失败: %s", exc)
        return []

    foreground = win32gui.GetForegroundWindow()
    if foreground in hwnd_list:
        hwnd_list.remove(foreground)
        hwnd_list.insert(0, foreground)

    return hwnd_list


def _close_login_tab_by_keyword(
    process_name: str,
    window_title_keyword: str | None,
) -> None:
    if not window_title_keyword:
        logger.warning("未设置浏览器窗口关键字，跳过关闭登录页")
        return
    try:
        import win32gui
        import win32process
    except ImportError as exc:
        logger.warning("win32 组件不可用，无法关闭登录页: %s", exc)
        return

    hwnd_list = _find_edge_windows(
        process_name,
        window_title_keyword,
        win32gui,
        win32process,
    )
    if not hwnd_list:
        logger.warning("未找到登录页窗口: %s", window_title_keyword)
        return
    _close_login_tab_by_hwnd(hwnd_list[0], window_title_keyword)


def _close_login_tab_by_hwnd(
    hwnd: int,
    window_title_keyword: str | None,
) -> None:
    if not window_title_keyword:
        logger.warning("未设置浏览器窗口关键字，跳过关闭登录页")
        return
    from .process_ops import activate_window

    try:
        activate_window(hwnd)
        time.sleep(0.2)
        _send_close_tab_shortcut()
        logger.info("已关闭登录页标签: %s", window_title_keyword)
    except Exception as exc:
        logger.warning("关闭登录页标签失败: hwnd=%s, err=%s", hwnd, exc)


def _send_copy_address_shortcut() -> None:
    import pyautogui

    pyautogui.hotkey("alt", "d")
    pyautogui.hotkey("ctrl", "c")


def _send_close_tab_shortcut() -> None:
    import pyautogui

    pyautogui.hotkey("ctrl", "w")


def _get_clipboard_text(win32clipboard, win32con) -> str | None:
    for _ in range(_CLIPBOARD_RETRY_TIMES):
        try:
            win32clipboard.OpenClipboard()
            if not win32clipboard.IsClipboardFormatAvailable(
                win32con.CF_UNICODETEXT
            ):
                return None
            return win32clipboard.GetClipboardData(
                win32con.CF_UNICODETEXT
            )
        except Exception:
            time.sleep(_CLIPBOARD_RETRY_INTERVAL)
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
    return None


def _set_clipboard_text(win32clipboard, win32con, text: str) -> None:
    for _ in range(_CLIPBOARD_RETRY_TIMES):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(
                win32con.CF_UNICODETEXT,
                text,
            )
            return
        except Exception:
            time.sleep(_CLIPBOARD_RETRY_INTERVAL)
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass


def _save_web_login_evidence(
    evidence_dir: Path | None,
    page,
    error: Exception,
    tag: str,
) -> None:
    if evidence_dir is None:
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = evidence_dir / f"{tag}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if page is not None:
            page.screenshot(
                path=str(output_dir / "screenshot.png"),
                full_page=True,
            )
            html = page.content()
            (output_dir / "page.html").write_text(
                html,
                encoding="utf-8",
            )
    except Exception as exc:
        logger.warning("保存网页登录证据失败: %s", exc)

    (output_dir / "error.txt").write_text(
        str(error),
        encoding="utf-8",
    )
