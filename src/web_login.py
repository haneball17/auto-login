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
_UI_AUTOMATION_CLASSES = (
    "UIAutomationClient.CUIAutomation",
    "UIAutomationClient.CUIAutomation8",
)
_UI_AUTOMATION_RETRY_SECONDS = 10.0
_ui_automation_last_error_time = 0.0
_ui_automation_last_error_msg = ""


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
    start_time: float,
    timeout_seconds: int,
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
    last_ui_check = 0.0
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
                return login_info

        if found_process:
            seen_process = True
            now = time.time()
            if now - last_ui_check >= 1.0:
                login_info = _read_login_url_from_edge_ui(process_name)
                if login_info:
                    return login_info
                last_ui_check = now
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


def _read_login_url_from_edge_ui(
    process_name: str,
) -> LoginUrlInfo | None:
    try:
        import win32gui
        import win32process
        import win32com.client
        import pythoncom
    except ImportError as exc:
        logger.warning("win32 组件不可用，无法读取浏览器地址栏: %s", exc)
        return None

    now = time.time()
    if now - _ui_automation_last_error_time < _UI_AUTOMATION_RETRY_SECONDS:
        return None

    pythoncom.CoInitialize()
    try:
        automation = _create_ui_automation(win32com.client)
        if automation is None:
            return None

        hwnd_list: list[int] = []

        try:
            def _enum_handler(hwnd: int, extra: object) -> None:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    if psutil.Process(pid).name() != process_name:
                        return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return
                hwnd_list.append(hwnd)

            win32gui.EnumWindows(_enum_handler, None)
        except Exception as exc:
            logger.warning("枚举浏览器窗口失败: %s", exc)
            return None

        foreground = win32gui.GetForegroundWindow()
        if foreground in hwnd_list:
            hwnd_list.remove(foreground)
            hwnd_list.insert(0, foreground)

        for hwnd in hwnd_list:
            try:
                element = automation.ElementFromHandle(hwnd)
            except Exception:
                continue
            login_info = _find_login_url_in_element(automation, element)
            if login_info:
                logger.info("通过地址栏捕获登录URL: port=%s", login_info.port)
                return login_info
        return None
    finally:
        pythoncom.CoUninitialize()

    return None


def _create_ui_automation(client) -> object | None:
    last_error: Exception | None = None
    for class_name in _UI_AUTOMATION_CLASSES:
        try:
            return client.Dispatch(class_name)
        except Exception as exc:
            last_error = exc
            continue
    _log_ui_automation_error(last_error)
    return None


def _log_ui_automation_error(error: Exception | None) -> None:
    global _ui_automation_last_error_time
    global _ui_automation_last_error_msg
    now = time.time()
    message = str(error) if error else "未知错误"
    if (
        message != _ui_automation_last_error_msg
        or now - _ui_automation_last_error_time >= _UI_AUTOMATION_RETRY_SECONDS
    ):
        logger.warning("UIAutomation 初始化失败: %s", message)
        _ui_automation_last_error_msg = message
        _ui_automation_last_error_time = now


def _find_login_url_in_element(automation, element) -> LoginUrlInfo | None:
    tree_scope_subtree = 4
    control_type_property_id = 30003
    edit_control_type_id = 50004
    value_pattern_id = 10002

    try:
        condition = automation.CreatePropertyCondition(
            control_type_property_id,
            edit_control_type_id,
        )
        edits = element.FindAll(tree_scope_subtree, condition)
    except Exception:
        return None

    for index in range(edits.Length):
        try:
            edit = edits.GetElement(index)
            pattern = edit.GetCurrentPattern(value_pattern_id)
            value = pattern.CurrentValue
        except Exception:
            continue
        if not value:
            continue
        login_info = extract_login_url(str(value))
        if login_info:
            return login_info
    return None


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
