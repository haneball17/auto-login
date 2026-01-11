from __future__ import annotations

import logging
import random
import time
from pathlib import Path

from .config import AppConfig
from .process_ops import (
    activate_window,
    ensure_launcher_window,
    kill_processes,
    wait_game_window,
    wait_process_exit,
)
from .ui_ops import (
    click_point,
    get_window_rect,
    load_roi_region,
    list_roi_names,
    match_template_in_roi,
    roi_center,
    wait_launcher_start_enabled,
    wait_template_match,
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

    _retry_start_launcher(
        launcher.exe_path,
        launcher.launcher_window_title_keyword,
        step_retry,
    )

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
        window_title_keyword=web.browser_window_title_keyword,
        close_on_capture=web.close_browser_on_url_capture,
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

    _wait_game_window_ready(config)
    _enter_channel_to_role_select(config, base_dir)


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


def _wait_game_window_ready(config: AppConfig) -> None:
    game_title = config.launcher.game_window_title_keyword
    hwnd = wait_game_window(
        title_keyword=game_title,
        timeout_seconds=config.flow.step_timeout_seconds,
        poll_interval=1.0,
    )
    activate_window(hwnd)
    logger.info("游戏窗口就绪")


def _wait_channel_select_ready(config: AppConfig, base_dir: Path) -> None:
    game_title = config.launcher.game_window_title_keyword
    template_path = base_dir / "anchors" / "channel_select" / "title.png"
    roi_path = base_dir / "anchors" / "channel_select" / "roi.json"
    ready = wait_template_match(
        template_path=template_path,
        timeout_seconds=config.flow.step_timeout_seconds,
        threshold=config.flow.template_threshold,
        poll_interval=1.0,
        roi_path=roi_path,
        roi_name="title",
        window_title=game_title,
        label="频道选择界面",
    )
    if not ready:
        raise TimeoutError("等待频道选择界面超时")


def _wait_role_select_ready(
    config: AppConfig,
    base_dir: Path,
    timeout_seconds: int,
) -> bool:
    game_title = config.launcher.game_window_title_keyword
    template_path = base_dir / "anchors" / "role_select" / "title.png"
    roi_path = base_dir / "anchors" / "role_select" / "roi.json"
    return wait_template_match(
        template_path=template_path,
        timeout_seconds=timeout_seconds,
        threshold=config.flow.template_threshold,
        poll_interval=1.0,
        roi_path=roi_path,
        roi_name="title",
        window_title=game_title,
        label="角色选择界面",
    )


def _enter_channel_to_role_select(config: AppConfig, base_dir: Path) -> None:
    startgame_retry = config.flow.channel_startgame_retry
    for attempt in range(1, startgame_retry + 1):
        _wait_channel_select_ready(config, base_dir)
        _select_channel_with_refresh(config, base_dir)
        ready = _wait_role_select_ready(
            config,
            base_dir,
            timeout_seconds=config.flow.channel_role_wait_seconds,
        )
        if ready:
            logger.info("已进入角色选择界面")
            return
        logger.warning(
            "未进入角色选择界面，第 %d/%d 次重试",
            attempt,
            startgame_retry,
        )

    _end_game_and_fail(
        config,
        base_dir,
        reason="进入角色选择界面失败，已超过重试次数",
    )


def _select_channel_with_refresh(config: AppConfig, base_dir: Path) -> None:
    roi_path = base_dir / "anchors" / "channel_select" / "roi.json"
    _validate_channel_rois(roi_path)

    max_channel = config.flow.channel_random_range
    channel_templates = _load_channel_templates(base_dir, max_channel)
    refresh_limit = config.flow.channel_refresh_max_retry
    search_timeout = config.flow.channel_search_timeout_seconds
    refresh_delay = config.flow.channel_refresh_delay_ms / 1000

    for refresh_attempt in range(0, refresh_limit + 1):
        found = _find_channels(
            config=config,
            roi_path=roi_path,
            channel_templates=channel_templates,
            timeout_seconds=search_timeout,
        )
        if found:
            name, center, score = random.choice(found)
            logger.info(
                "检测到可选频道数量=%d, 随机选择=%s, score=%.3f",
                len(found),
                name,
                score,
            )
            click_point(center)
            logger.info("已选择频道: %s, point=%s", name, center)
            time.sleep(1)
            _click_channel_button(config, roi_path, "button_startgame")
            return

        if refresh_attempt >= refresh_limit:
            _end_game_and_fail(
                config,
                base_dir,
                reason="频道区域未找到可选频道，结束游戏",
            )

        logger.warning(
            "频道区域未找到可选频道，执行刷新: %d/%d",
            refresh_attempt + 1,
            refresh_limit,
        )
        _click_channel_button(config, roi_path, "button_refresh")
        time.sleep(refresh_delay)


def _find_channels(
    config: AppConfig,
    roi_path: Path,
    channel_templates: list[tuple[str, Path]],
    timeout_seconds: int,
) -> list[tuple[str, tuple[int, int], float]]:
    game_title = config.launcher.game_window_title_keyword
    threshold = config.flow.template_threshold
    poll_interval = 0.5
    deadline = time.time() + timeout_seconds
    results: list[tuple[str, tuple[int, int], float]] = []

    while time.time() < deadline:
        results.clear()
        for name, template_path in channel_templates:
            result = match_template_in_roi(
                template_path=template_path,
                roi_path=roi_path,
                roi_name="channel_region",
                window_title=game_title,
                threshold=threshold,
                label=f"{name}",
            )
            if result.found and result.center:
                results.append((name, result.center, result.score))
        if results:
            return results
        time.sleep(poll_interval)

    return []


def _load_channel_templates(
    base_dir: Path,
    max_channel: int,
) -> list[tuple[str, Path]]:
    template_dir = base_dir / "anchors" / "channel_select"
    templates: list[tuple[str, Path]] = []
    missing: list[str] = []
    for index in range(1, max_channel + 1):
        name = f"channel_{index}"
        path = template_dir / f"{name}.png"
        if not path.is_file():
            missing.append(str(path))
        templates.append((name, path))
    if missing:
        raise ValueError(f"频道模板缺失: {', '.join(missing)}")
    return templates


def _validate_channel_rois(roi_path: Path) -> None:
    required = {
        "title",
        "channel_region",
        "button_startgame",
        "button_refresh",
        "button_endgame",
    }
    available = set(list_roi_names(roi_path))
    missing = sorted(required - available)
    if missing:
        raise ValueError(f"频道 ROI 缺失: {', '.join(missing)}")


def _click_channel_button(
    config: AppConfig,
    roi_path: Path,
    roi_name: str,
) -> None:
    window_rect = get_window_rect(config.launcher.game_window_title_keyword)
    roi_region = load_roi_region(roi_path, roi_name)
    center = roi_center(roi_region, offset=(window_rect[0], window_rect[1]))
    click_point(center)
    logger.info("已点击按钮: %s, point=%s", roi_name, center)


def _end_game_and_fail(
    config: AppConfig,
    base_dir: Path,
    reason: str,
) -> None:
    roi_path = base_dir / "anchors" / "channel_select" / "roi.json"
    _click_channel_button(config, roi_path, "button_endgame")

    process_name = config.launcher.game_process_name
    exited = wait_process_exit(
        process_name,
        timeout_seconds=config.flow.step_timeout_seconds,
        poll_interval=1.0,
    )
    if not exited and config.flow.force_kill_on_exit_fail:
        killed = kill_processes(process_name)
        logger.warning("强制结束游戏进程: count=%d", killed)
        exited = wait_process_exit(
            process_name,
            timeout_seconds=5,
            poll_interval=1.0,
        )
    if not exited:
        logger.warning("游戏进程仍未退出: %s", process_name)

    raise RuntimeError(reason)
