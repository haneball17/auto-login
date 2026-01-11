from __future__ import annotations

import logging
import time
from pathlib import Path

from .config import AppConfig
from .process_ops import ensure_launcher_window
from .ui_ops import (
    click_point,
    get_window_rect,
    load_roi_region,
    roi_center,
    wait_launcher_start_enabled,
)
from .web_login import perform_web_login, wait_login_url

logger = logging.getLogger("auto_login")


def run_launcher_flow(config: AppConfig, base_dir: Path) -> float:
    launcher = config.launcher
    template_path = base_dir / "anchors" / "launcher_start_enabled" / "button.png"
    roi_path = launcher.start_button_roi_path

    if roi_path is None:
        raise ValueError("缺少启动按钮 ROI 路径: start_button_roi_path")

    step_retry = 2

    _retry_start_launcher(launcher.exe_path, launcher.launcher_window_title_keyword, step_retry)

    if not _wait_start_button(
        template_path=template_path,
        exe_path=launcher.exe_path,
        roi_path=roi_path,
        roi_name=launcher.start_button_roi_name,
        window_title=launcher.launcher_window_title_keyword,
        threshold=config.flow.template_threshold,
        timeout_seconds=config.flow.step_timeout_seconds,
        step_retry=step_retry,
    ):
        raise TimeoutError("启动按钮未就绪")

    window_rect = get_window_rect(launcher.launcher_window_title_keyword)
    roi_region = load_roi_region(roi_path, launcher.start_button_roi_name)
    center = roi_center(roi_region, offset=(window_rect[0], window_rect[1]))
    click_time = time.time()
    click_point(center)
    logger.info("已点击启动按钮中心点: %s", center)
    return click_time


def run_launcher_web_login_flow(config: AppConfig, base_dir: Path) -> None:
    click_time = run_launcher_flow(config, base_dir)

    if not config.accounts.pool:
        raise ValueError("账号池为空，无法执行网页登录")

    account = config.accounts.pool[0]
    web = config.web

    login_info = wait_login_url(
        process_name=web.browser_process_name,
        start_time=click_time,
        timeout_seconds=config.flow.step_timeout_seconds,
        poll_interval=0.2,
    )

    perform_web_login(
        login_url=login_info.url,
        username=account.username,
        password=account.password,
        username_selector=web.username_selector,
        password_selector=web.password_selector,
        login_button_selector=web.login_button_selector,
        success_selector=web.success_selector,
        timeout_seconds=config.flow.step_timeout_seconds,
        evidence_dir=config.evidence.dir,
    )


def _retry_start_launcher(
    exe_path: Path,
    title_keyword: str,
    max_retry: int,
) -> None:
    for attempt in range(1, max_retry + 1):
        try:
            ensure_launcher_window(exe_path, title_keyword)
            logger.info("启动器窗口就绪")
            return
        except Exception as exc:
            logger.warning("启动器启动失败，第 %d/%d 次: %s", attempt, max_retry, exc)
    raise RuntimeError("启动器启动失败，超过重试次数")


def _wait_start_button(
    template_path: Path,
    exe_path: Path,
    roi_path: Path,
    roi_name: str,
    window_title: str,
    threshold: float,
    timeout_seconds: int,
    step_retry: int,
) -> bool:
    for attempt in range(1, step_retry + 1):
        ready = wait_launcher_start_enabled(
            template_path=template_path,
            region=None,
            timeout_seconds=timeout_seconds,
            threshold=threshold,
            poll_interval=1.0,
            color_rule=None,
            roi_path=roi_path,
            roi_name=roi_name,
            window_title=window_title,
        )
        if ready:
            return True
        logger.warning("启动按钮未就绪，第 %d/%d 次重试", attempt, step_retry)
        _retry_start_launcher(exe_path, window_title, 1)
    return False
