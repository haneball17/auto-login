from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Callable

from .config import AccountItem, AppConfig
from .process_ops import (
    activate_window,
    close_window_by_title,
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


def run_launcher_web_login_flow(
    config: AppConfig,
    base_dir: Path,
    account: AccountItem | None = None,
) -> None:
    click_time = run_launcher_flow(config, base_dir)

    if account is None and not config.accounts.pool:
        raise ValueError("账号池为空，无法执行网页登录")

    if account is None:
        account = config.accounts.pool[0]
    web = config.web

    logger.info("开始处理账号: %s / %s", account.username, account.password)

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
    _enter_channel_to_character_select(config, base_dir)
    _enter_character_to_in_game(config, base_dir)
    logger.info("账号流程完成: %s / %s", account.username, account.password)


def run_all_accounts_once(
    config: AppConfig,
    base_dir: Path,
    stop_flag_path: Path | None = None,
) -> None:
    accounts = config.accounts.pool
    if not accounts:
        raise ValueError("账号池为空，无法执行单次全账号流程")

    total = len(accounts)
    max_retry = config.flow.account_max_retry
    success_count = 0
    fail_count = 0
    logger.info("开始单次全账号流程，共 %d 个账号", total)

    for index, account in enumerate(accounts, 1):
        if _should_stop(stop_flag_path):
            logger.info("检测到 stop.flag，终止账号执行")
            break
        success = False
        start_time = time.time()
        for attempt in range(1, max_retry + 1):
            logger.info(
                "账号 %d/%d 第 %d/%d 次尝试: %s",
                index,
                total,
                attempt,
                max_retry,
                account.username,
            )
            try:
                run_launcher_web_login_flow(config, base_dir, account)
                logger.info("账号 %d/%d 完成: %s", index, total, account.username)
                success = True
                break
            except Exception as exc:
                logger.exception(
                    "账号 %d/%d 失败，第 %d/%d 次: %s",
                    index,
                    total,
                    attempt,
                    max_retry,
                    exc,
                )
                try:
                    _force_exit_game(config)
                except Exception as cleanup_exc:
                    logger.warning("账号失败清理异常: %s", cleanup_exc)

        if not success:
            logger.error(
                "账号 %d/%d 失败超过重试次数，跳过: %s",
                index,
                total,
                account.username,
            )
            fail_count += 1
        else:
            success_count += 1

        elapsed = time.time() - start_time
        logger.info(
            "账号 %d/%d 耗时 %.2f 秒: %s",
            index,
            total,
            elapsed,
            account.username,
        )

        wait_seconds = config.flow.wait_next_account_seconds
        if index < total and wait_seconds > 0:
            if _should_stop(stop_flag_path):
                logger.info("检测到 stop.flag，跳过等待并终止账号执行")
                break
            logger.info("等待 %s 秒后进入下一个账号", wait_seconds)
            time.sleep(wait_seconds)

    logger.info(
        "单次全账号流程结束: 成功=%d, 失败=%d, 总数=%d",
        success_count,
        fail_count,
        total,
    )


def _should_stop(stop_flag_path: Path | None) -> bool:
    return stop_flag_path is not None and stop_flag_path.exists()


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


def _resolve_anchor_root(
    base_dir: Path,
    window_title: str,
    stage: str,
    validator: Callable[[Path], None],
) -> Path:
    default_root = base_dir / "anchors"
    rect = get_window_rect(window_title)
    width, height = rect[2], rect[3]
    resolution_root = default_root / f"{width}x{height}"

    if resolution_root.is_dir():
        try:
            validator(resolution_root)
        except Exception as exc:
            logger.error(
                "%s 分辨率模板不可用: %s (窗口=%sx%s)，回退默认模板",
                stage,
                exc,
                width,
                height,
            )
        else:
            logger.info("%s 使用分辨率模板: %s", stage, resolution_root)
            return resolution_root
    else:
        logger.error(
            "%s 分辨率模板目录不存在: %s (窗口=%sx%s)，回退默认模板",
            stage,
            resolution_root,
            width,
            height,
        )

    validator(default_root)
    return default_root


def _resolve_channel_anchor_root(config: AppConfig, base_dir: Path) -> Path:
    return _resolve_anchor_root(
        base_dir=base_dir,
        window_title=config.launcher.game_window_title_keyword,
        stage="频道选择",
        validator=lambda root: _validate_channel_anchor_root(
            root,
            config.flow.channel_random_range,
        ),
    )


def _resolve_character_anchor_root(config: AppConfig, base_dir: Path) -> Path:
    return _resolve_anchor_root(
        base_dir=base_dir,
        window_title=config.launcher.game_window_title_keyword,
        stage="角色选择",
        validator=_validate_character_anchor_root,
    )


def _resolve_in_game_anchor_root(config: AppConfig, base_dir: Path) -> Path:
    return _resolve_anchor_root(
        base_dir=base_dir,
        window_title=config.launcher.game_window_title_keyword,
        stage="进入游戏",
        validator=_validate_in_game_anchor_root,
    )


def _wait_channel_select_ready(config: AppConfig, anchor_root: Path) -> None:
    game_title = config.launcher.game_window_title_keyword
    template_path = anchor_root / "channel_select" / "title.png"
    roi_path = anchor_root / "channel_select" / "roi.json"
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


def _wait_character_select_ready(
    config: AppConfig,
    anchor_root: Path,
    timeout_seconds: int,
) -> bool:
    game_title = config.launcher.game_window_title_keyword
    template_path = anchor_root / "character_select" / "title.png"
    roi_path = anchor_root / "character_select" / "roi.json"
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


def _enter_channel_to_character_select(config: AppConfig, base_dir: Path) -> None:
    startgame_retry = config.flow.channel_startgame_retry
    for attempt in range(1, startgame_retry + 1):
        channel_root = _resolve_channel_anchor_root(config, base_dir)
        _wait_channel_select_ready(config, channel_root)
        _select_channel_with_refresh(config, channel_root)
        character_root = _resolve_character_anchor_root(config, base_dir)
        ready = _wait_character_select_ready(
            config,
            character_root,
            timeout_seconds=config.flow.step_timeout_seconds,
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
        channel_root / "channel_select" / "roi.json",
        reason="进入角色选择界面失败，已超过重试次数",
    )


def _enter_character_to_in_game(config: AppConfig, base_dir: Path) -> None:
    startgame_retry = config.flow.channel_startgame_retry
    for attempt in range(1, startgame_retry + 1):
        character_root = _resolve_character_anchor_root(config, base_dir)
        ready = _wait_character_select_ready(
            config,
            character_root,
            timeout_seconds=config.flow.step_timeout_seconds,
        )
        if not ready:
            logger.warning(
                "等待角色选择界面超时，第 %d/%d 次重试",
                attempt,
                startgame_retry,
            )
            continue

        if not _select_character_and_start(config, character_root):
            logger.warning(
                "角色位置未匹配到，第 %d/%d 次重试",
                attempt,
                startgame_retry,
            )
            continue

        in_game_root = _resolve_in_game_anchor_root(config, base_dir)
        in_game_ready = _wait_in_game_ready(
            config,
            in_game_root,
            timeout_seconds=config.flow.in_game_match_timeout_seconds,
        )
        if in_game_ready:
            _wait_in_game_and_exit(config)
            return

        logger.warning(
            "未进入游戏界面，第 %d/%d 次重试",
            attempt,
            startgame_retry,
        )

    _end_game_and_fail(
        config,
        character_root / "character_select" / "roi.json",
        reason="进入游戏界面失败，已超过重试次数",
    )


def _select_character_and_start(
    config: AppConfig,
    anchor_root: Path,
) -> bool:
    roi_path = anchor_root / "character_select" / "roi.json"
    _validate_character_rois(roi_path)
    template_path = anchor_root / "character_select" / "character_1.png"
    if not template_path.is_file():
        raise ValueError(f"角色模板缺失: {template_path}")

    result = _find_character(
        config=config,
        roi_path=roi_path,
        template_path=template_path,
        timeout_seconds=config.flow.step_timeout_seconds,
    )
    if result is None:
        return False

    center, score = result
    click_point(center)
    logger.info("已选择角色: character_1, score=%.3f, point=%s", score, center)
    time.sleep(1)
    _click_roi_button(config, roi_path, "button_startgame")
    return True


def _find_character(
    config: AppConfig,
    roi_path: Path,
    template_path: Path,
    timeout_seconds: int,
) -> tuple[tuple[int, int], float] | None:
    game_title = config.launcher.game_window_title_keyword
    threshold = config.flow.template_threshold
    poll_interval = 0.5
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        result = match_template_in_roi(
            template_path=template_path,
            roi_path=roi_path,
            roi_name="character_region",
            window_title=game_title,
            threshold=threshold,
            label="character_1",
        )
        if result.found and result.center:
            return (result.center, result.score)
        time.sleep(poll_interval)
    return None


def _wait_in_game_ready(
    config: AppConfig,
    anchor_root: Path,
    timeout_seconds: int,
) -> bool:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")
    roi_path = anchor_root / "in_game" / "roi.json"
    _validate_in_game_rois(roi_path)
    name_template = anchor_root / "in_game" / "name_cecilia.png"
    title_template = anchor_root / "in_game" / "title_duel.png"
    if not name_template.is_file():
        raise ValueError(f"游戏模板缺失: {name_template}")
    if not title_template.is_file():
        raise ValueError(f"游戏模板缺失: {title_template}")

    game_title = config.launcher.game_window_title_keyword
    name_threshold = config.flow.in_game_name_threshold
    title_threshold = config.flow.in_game_title_threshold
    poll_interval = 0.5
    deadline = time.time() + timeout_seconds
    last_report = 0.0

    while time.time() < deadline:
        name_result = match_template_in_roi(
            template_path=name_template,
            roi_path=roi_path,
            roi_name="name_cecilia",
            window_title=game_title,
            threshold=name_threshold,
            label="name_cecilia",
        )
        title_result = match_template_in_roi(
            template_path=title_template,
            roi_path=roi_path,
            roi_name="title_duel",
            window_title=game_title,
            threshold=title_threshold,
            label="title_duel",
        )
        now = time.time()
        if now - last_report >= 5.0:
            logger.info(
                "进入游戏匹配中: name=%.3f, title=%.3f",
                name_result.score,
                title_result.score,
            )
            last_report = now
        if name_result.found and title_result.found:
            logger.info("进入游戏界面匹配成功")
            return True
        time.sleep(poll_interval)

    return False


def _wait_in_game_and_exit(config: AppConfig) -> None:
    base_wait = config.flow.enter_game_wait_seconds
    random_range = config.flow.enter_game_wait_seconds_random_range
    min_wait = max(0, base_wait - random_range)
    max_wait = base_wait + random_range
    wait_seconds = random.randint(min_wait, max_wait)
    logger.info(
        "进入游戏界面，等待 %s 秒后退出 (基准=%s, 随机范围=±%s)",
        wait_seconds,
        base_wait,
        random_range,
    )
    time.sleep(wait_seconds)
    _force_exit_game(config)


def _force_exit_game(config: AppConfig) -> None:
    process_name = config.launcher.game_process_name
    exit_timeout = min(10, config.flow.step_timeout_seconds)
    closed = close_window_by_title(config.launcher.game_window_title_keyword)
    if closed:
        exited = wait_process_exit(
            process_name,
            timeout_seconds=exit_timeout,
            poll_interval=1.0,
        )
        if exited:
            return

    if not config.flow.force_kill_on_exit_fail:
        logger.warning("未配置强制结束，游戏仍在运行: %s", process_name)
        return

    killed = kill_processes(process_name)
    logger.info("强制结束游戏进程: count=%d", killed)
    exited = wait_process_exit(
        process_name,
        timeout_seconds=5,
        poll_interval=1.0,
    )
    if not exited:
        logger.warning("游戏进程仍未退出: %s", process_name)


def _select_channel_with_refresh(config: AppConfig, anchor_root: Path) -> None:
    roi_path = anchor_root / "channel_select" / "roi.json"
    _validate_channel_rois(roi_path)

    max_channel = config.flow.channel_random_range
    channel_templates = _load_channel_templates(anchor_root, max_channel)
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
            time.sleep(0.5)
            _click_roi_button(config, roi_path, "button_startgame")
            return

        if refresh_attempt >= refresh_limit:
            _end_game_and_fail(
                config,
                roi_path,
                reason="频道区域未找到可选频道，结束游戏",
            )

        logger.warning(
            "频道区域未找到可选频道，执行刷新: %d/%d",
            refresh_attempt + 1,
            refresh_limit,
        )
        _click_roi_button(config, roi_path, "button_refresh")
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
    anchor_root: Path,
    max_channel: int,
) -> list[tuple[str, Path]]:
    template_dir = anchor_root / "channel_select"
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


def _validate_channel_anchor_root(anchor_root: Path, max_channel: int) -> None:
    title_path = anchor_root / "channel_select" / "title.png"
    roi_path = anchor_root / "channel_select" / "roi.json"
    if not title_path.is_file():
        raise FileNotFoundError(f"频道标题模板缺失: {title_path}")
    if not roi_path.is_file():
        raise FileNotFoundError(f"频道 ROI 缺失: {roi_path}")
    _validate_channel_rois(roi_path)
    _load_channel_templates(anchor_root, max_channel)


def _validate_character_anchor_root(anchor_root: Path) -> None:
    title_path = anchor_root / "character_select" / "title.png"
    roi_path = anchor_root / "character_select" / "roi.json"
    template_path = anchor_root / "character_select" / "character_1.png"
    if not title_path.is_file():
        raise FileNotFoundError(f"角色标题模板缺失: {title_path}")
    if not roi_path.is_file():
        raise FileNotFoundError(f"角色 ROI 缺失: {roi_path}")
    if not template_path.is_file():
        raise FileNotFoundError(f"角色模板缺失: {template_path}")
    _validate_character_rois(roi_path)


def _validate_in_game_anchor_root(anchor_root: Path) -> None:
    roi_path = anchor_root / "in_game" / "roi.json"
    name_path = anchor_root / "in_game" / "name_cecilia.png"
    title_path = anchor_root / "in_game" / "title_duel.png"
    if not roi_path.is_file():
        raise FileNotFoundError(f"游戏 ROI 缺失: {roi_path}")
    if not name_path.is_file():
        raise FileNotFoundError(f"游戏模板缺失: {name_path}")
    if not title_path.is_file():
        raise FileNotFoundError(f"游戏模板缺失: {title_path}")
    _validate_in_game_rois(roi_path)


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


def _validate_character_rois(roi_path: Path) -> None:
    required = {
        "title",
        "character_region",
        "button_startgame",
        "button_endgame",
    }
    available = set(list_roi_names(roi_path))
    missing = sorted(required - available)
    if missing:
        raise ValueError(f"角色 ROI 缺失: {', '.join(missing)}")


def _validate_in_game_rois(roi_path: Path) -> None:
    required = {"name_cecilia", "title_duel"}
    available = set(list_roi_names(roi_path))
    missing = sorted(required - available)
    if missing:
        raise ValueError(f"游戏 ROI 缺失: {', '.join(missing)}")


def _click_roi_button(
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
    roi_path: Path,
    reason: str,
) -> None:
    _click_roi_button(config, roi_path, "button_endgame")
    _force_exit_game(config)

    raise RuntimeError(reason)
