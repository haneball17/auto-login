from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from pathlib import Path
from typing import Callable

from .config import AccountItem, AppConfig
from .ocr_ops import contains_keywords, ocr_window_text
from .process_ops import (
    activate_window,
    close_window_by_title,
    ensure_launcher_window,
    kill_processes,
    select_latest_active_window,
    wait_game_window,
    wait_process_exit,
)
from .ui_ops import (
    click_point,
    expand_roi_region,
    get_window_rect,
    load_roi_region,
    list_roi_names,
    match_template_in_roi,
    match_template_in_region,
    press_key,
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

    state_path = base_dir / "logs" / "state.json"
    state = _load_state(state_path)
    start_index = _resolve_start_index(state, accounts)

    total = len(accounts)
    max_retry = config.flow.account_max_retry
    success_count = 0
    fail_count = 0
    logger.info("开始单次全账号流程，共 %d 个账号", total)

    for index, account in enumerate(accounts[start_index:], start_index + 1):
        if _should_stop(stop_flag_path):
            logger.info("检测到 stop.flag，终止账号执行")
            _save_state(
                state_path,
                accounts,
                index,
                status="stopped",
            )
            break
        success = False
        start_time = time.time()
        _save_state(state_path, accounts, index, status="running")
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

        _save_state(state_path, accounts, index + 1, status="running")

        wait_seconds = config.flow.wait_next_account_seconds
        if index < total and wait_seconds > 0:
            if _should_stop(stop_flag_path):
                logger.info("检测到 stop.flag，跳过等待并终止账号执行")
                _save_state(
                    state_path,
                    accounts,
                    index + 1,
                    status="stopped",
                )
                break
            logger.info("等待 %s 秒后进入下一个账号", wait_seconds)
            time.sleep(wait_seconds)

    if not _should_stop(stop_flag_path):
        _save_state(state_path, accounts, total, status="completed")
    logger.info(
        "单次全账号流程结束: 成功=%d, 失败=%d, 总数=%d",
        success_count,
        fail_count,
        total,
    )


def _should_stop(stop_flag_path: Path | None) -> bool:
    return stop_flag_path is not None and stop_flag_path.exists()


def _hash_accounts(accounts: list[AccountItem]) -> str:
    raw = "|".join(account.username for account in accounts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load_state(state_path: Path) -> dict:
    if not state_path.is_file():
        return {}
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("读取断点文件失败: %s", exc)
        return {}


def _save_state(
    state_path: Path,
    accounts: list[AccountItem],
    next_index: int,
    status: str,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(accounts)
    if status == "completed":
        next_index = total + 1
    if next_index < 1:
        next_index = 1
    data = {
        "accounts_hash": _hash_accounts(accounts),
        "total": total,
        "next_index": next_index,
        "status": status,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with state_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)


def _resolve_start_index(state: dict, accounts: list[AccountItem]) -> int:
    if not state:
        return 0
    if state.get("accounts_hash") != _hash_accounts(accounts):
        logger.info("断点账号列表不一致，忽略断点，从头开始")
        return 0
    status = state.get("status")
    total = len(accounts)
    next_index = state.get("next_index")
    try:
        next_index = int(next_index)
    except (TypeError, ValueError):
        next_index = 1
    if status == "completed" or next_index > total:
        logger.info("断点已完成，从头开始")
        return 0
    if next_index <= 1:
        return 0
    logger.info("检测到账号断点，从第 %d/%d 个账号继续", next_index, total)
    return next_index - 1


def _build_scene_checkers(
    config: AppConfig,
    channel_resolver: Callable[[], Path] | None = None,
    character_resolver: Callable[[], Path] | None = None,
    in_game_resolver: Callable[[], Path] | None = None,
) -> list[tuple[str, Callable[[], bool]]]:
    checkers: list[tuple[str, Callable[[], bool]]] = []
    if channel_resolver is not None:
        checkers.append(
            (
                "频道选择界面",
                lambda: _match_scene_once(
                    config=config,
                    anchor_resolver=channel_resolver,
                    template_rel_path=Path("channel_select/title.png"),
                    roi_rel_path=Path("channel_select/roi.json"),
                    roi_name="title",
                    threshold=config.flow.template_threshold,
                    label="频道选择界面",
                ),
            )
        )
    if character_resolver is not None:
        checkers.append(
            (
                "角色选择界面",
                lambda: _match_scene_once(
                    config=config,
                    anchor_resolver=character_resolver,
                    template_rel_path=Path("character_select/title.png"),
                    roi_rel_path=Path("character_select/roi.json"),
                    roi_name="title",
                    threshold=config.flow.template_threshold,
                    label="角色选择界面",
                    expand_ratio=2.0,
                ),
            )
        )
    if in_game_resolver is not None:
        checkers.append(
            (
                "进入游戏界面",
                lambda: _match_in_game_once(config, in_game_resolver),
            )
        )
    return checkers


def _detect_scene(
    scene_checkers: list[tuple[str, Callable[[], bool]]],
) -> str | None:
    for name, checker in scene_checkers:
        try:
            if checker():
                return name
        except Exception as exc:
            logger.debug("场景检测失败: %s", exc)
    return None


def _maybe_handle_unexpected_ui(
    config: AppConfig,
    scene_checkers: list[tuple[str, Callable[[], bool]]],
    last_ocr_time: float,
) -> tuple[str | None, float]:
    interval = config.flow.ocr_interval_seconds
    if interval <= 0 or not scene_checkers:
        return None, last_ocr_time
    if not config.flow.ocr_keywords:
        return None, last_ocr_time
    now = time.time()
    if now - last_ocr_time < interval:
        return None, last_ocr_time
    last_ocr_time = now
    text = ocr_window_text(
        window_title=config.launcher.game_window_title_keyword,
        region_ratio=config.flow.ocr_region_ratio,
    ).strip()
    if not contains_keywords(text, config.flow.ocr_keywords):
        return None, last_ocr_time
    logger.warning("OCR 检测到异常界面关键词: %s", text)

    hwnd = select_latest_active_window(config.launcher.game_window_title_keyword)
    if hwnd is not None:
        try:
            activate_window(hwnd)
        except Exception as exc:
            logger.warning("激活窗口失败: %s", exc)
    try:
        rect = get_window_rect(config.launcher.game_window_title_keyword)
    except Exception as exc:
        logger.warning("读取窗口坐标失败: %s", exc)
        return None, last_ocr_time
    center = (rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
    actions: list[tuple[str, Callable[[], None]]] = [
        ("ESC", lambda: press_key("esc")),
        ("Enter", lambda: press_key("enter")),
        ("中心点击", lambda: click_point(center)),
    ]
    for name, action in actions:
        action()
        logger.info("异常界面处理动作: %s", name)
        time.sleep(0.5)
        scene = _detect_scene(scene_checkers)
        if scene:
            logger.info("异常界面处理完成，当前场景: %s", scene)
            return scene, last_ocr_time
    logger.warning("异常界面处理后仍未回到可识别场景")
    return None, last_ocr_time


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


def _make_anchor_resolver(
    config: AppConfig,
    base_dir: Path,
    stage: str,
    validator: Callable[[Path], None],
) -> Callable[[], Path]:
    default_root = base_dir / "anchors"
    last_size: tuple[int, int] | None = None
    last_root: Path | None = None

    def resolve() -> Path:
        nonlocal last_size, last_root
        rect = get_window_rect(config.launcher.game_window_title_keyword)
        size = (rect[2], rect[3])
        if size != last_size:
            width, height = size
            resolution_root = default_root / f"{width}x{height}"
            if resolution_root.is_dir():
                try:
                    validator(resolution_root)
                except Exception as exc:
                    logger.error(
                        "%s 分辨率变化为 %sx%s，模板不可用: %s，回退默认模板",
                        stage,
                        width,
                        height,
                        exc,
                    )
                    validator(default_root)
                    last_root = default_root
                else:
                    logger.info(
                        "%s 分辨率变化为 %sx%s，使用模板: %s",
                        stage,
                        width,
                        height,
                        resolution_root,
                    )
                    last_root = resolution_root
            else:
                logger.error(
                    "%s 分辨率变化为 %sx%s，模板目录不存在: %s，回退默认模板",
                    stage,
                    width,
                    height,
                    resolution_root,
                )
                validator(default_root)
                last_root = default_root
            last_size = size
        if last_root is None:
            validator(default_root)
            last_root = default_root
        return last_root

    return resolve


def _match_scene_once(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    template_rel_path: Path,
    roi_rel_path: Path,
    roi_name: str,
    threshold: float,
    label: str,
    expand_ratio: float | None = None,
) -> bool:
    anchor_root = anchor_resolver()
    template_path = anchor_root / template_rel_path
    roi_path = anchor_root / roi_rel_path
    result = match_template_in_roi(
        template_path=template_path,
        roi_path=roi_path,
        roi_name=roi_name,
        window_title=config.launcher.game_window_title_keyword,
        threshold=threshold,
        label=label,
    )
    if result.found:
        return True
    if expand_ratio is None:
        return False
    expanded_region = _expand_roi_region(
        roi_path,
        roi_name,
        config.launcher.game_window_title_keyword,
        expand_ratio,
    )
    expanded_result = match_template_in_region(
        template_path=template_path,
        roi_region=expanded_region,
        window_title=config.launcher.game_window_title_keyword,
        threshold=threshold,
        label=label,
    )
    return expanded_result.found


def _match_in_game_once(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
) -> bool:
    anchor_root = anchor_resolver()
    name_template = anchor_root / "in_game" / "name_cecilia.png"
    title_template = anchor_root / "in_game" / "title_duel.png"
    roi_path = anchor_root / "in_game" / "roi.json"
    name_result = match_template_in_roi(
        template_path=name_template,
        roi_path=roi_path,
        roi_name="name_cecilia",
        window_title=config.launcher.game_window_title_keyword,
        threshold=config.flow.in_game_name_threshold,
        label="name_cecilia",
    )
    if not name_result.found:
        return False
    title_result = match_template_in_roi(
        template_path=title_template,
        roi_path=roi_path,
        roi_name="title_duel",
        window_title=config.launcher.game_window_title_keyword,
        threshold=config.flow.in_game_title_threshold,
        label="title_duel",
    )
    return title_result.found


def _expand_roi_region(
    roi_path: Path,
    roi_name: str,
    window_title: str,
    expand_ratio: float,
) -> tuple[int, int, int, int]:
    roi_region = load_roi_region(roi_path, roi_name)
    rect = get_window_rect(window_title)
    bounds = (rect[2], rect[3])
    return expand_roi_region(roi_region, expand_ratio, bounds)


def _make_channel_anchor_resolver(
    config: AppConfig,
    base_dir: Path,
) -> Callable[[], Path]:
    return _make_anchor_resolver(
        config=config,
        base_dir=base_dir,
        stage="频道选择",
        validator=lambda root: _validate_channel_anchor_root(
            root,
            config.flow.channel_random_range,
        ),
    )


def _make_character_anchor_resolver(
    config: AppConfig,
    base_dir: Path,
) -> Callable[[], Path]:
    return _make_anchor_resolver(
        config=config,
        base_dir=base_dir,
        stage="角色选择",
        validator=_validate_character_anchor_root,
    )


def _make_in_game_anchor_resolver(
    config: AppConfig,
    base_dir: Path,
) -> Callable[[], Path]:
    return _make_anchor_resolver(
        config=config,
        base_dir=base_dir,
        stage="进入游戏",
        validator=_validate_in_game_anchor_root,
    )


def _wait_template_with_resolver(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    template_rel_path: Path,
    roi_rel_path: Path,
    roi_name: str,
    label: str,
    timeout_seconds: int,
    threshold: float,
    poll_interval: float,
    expand_ratio: float | None = None,
    scene_checkers: list[tuple[str, Callable[[], bool]]] | None = None,
) -> bool:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")
    if poll_interval <= 0:
        raise ValueError("poll_interval 必须大于 0")
    game_title = config.launcher.game_window_title_keyword
    deadline = time.time() + timeout_seconds
    last_report = 0.0
    last_ocr_time = 0.0

    while time.time() < deadline:
        anchor_root = anchor_resolver()
        template_path = anchor_root / template_rel_path
        roi_path = anchor_root / roi_rel_path
        if expand_ratio is None:
            result = match_template_in_roi(
                template_path=template_path,
                roi_path=roi_path,
                roi_name=roi_name,
                window_title=game_title,
                threshold=threshold,
                label=label,
            )
        else:
            roi_region = _expand_roi_region(
                roi_path,
                roi_name,
                game_title,
                expand_ratio,
            )
            result = match_template_in_region(
                template_path=template_path,
                roi_region=roi_region,
                window_title=game_title,
                threshold=threshold,
                label=label,
            )
        now = time.time()
        if now - last_report >= max(5.0, poll_interval):
            logger.info("%s模板匹配中: score=%.3f", label, result.score)
            last_report = now
        if result.found:
            logger.info("检测到%s模板匹配成功，score=%.3f", label, result.score)
            return True
        if scene_checkers:
            scene, last_ocr_time = _maybe_handle_unexpected_ui(
                config,
                scene_checkers,
                last_ocr_time,
            )
            if scene == label:
                return True
            if scene is not None:
                logger.info("等待%s过程中场景变化为: %s", label, scene)
                return False
        time.sleep(poll_interval)
    logger.warning("等待%s超时", label)
    return False


def _wait_channel_select_ready(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    scene_checkers: list[tuple[str, Callable[[], bool]]] | None = None,
) -> bool:
    ready = _wait_template_with_resolver(
        config=config,
        anchor_resolver=anchor_resolver,
        template_rel_path=Path("channel_select/title.png"),
        roi_rel_path=Path("channel_select/roi.json"),
        roi_name="title",
        label="频道选择界面",
        timeout_seconds=config.flow.step_timeout_seconds,
        threshold=config.flow.template_threshold,
        poll_interval=1.0,
        scene_checkers=scene_checkers,
    )
    return ready


def _wait_character_select_ready(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    timeout_seconds: int,
    scene_checkers: list[tuple[str, Callable[[], bool]]] | None = None,
) -> bool:
    ready = _wait_template_with_resolver(
        config=config,
        anchor_resolver=anchor_resolver,
        template_rel_path=Path("character_select/title.png"),
        roi_rel_path=Path("character_select/roi.json"),
        roi_name="title",
        label="角色选择界面",
        timeout_seconds=timeout_seconds,
        threshold=config.flow.template_threshold,
        poll_interval=1.0,
        scene_checkers=scene_checkers,
    )
    if ready:
        return True
    logger.warning("角色选择界面未匹配到，尝试扩大 ROI 范围")
    return _wait_template_with_resolver(
        config=config,
        anchor_resolver=anchor_resolver,
        template_rel_path=Path("character_select/title.png"),
        roi_rel_path=Path("character_select/roi.json"),
        roi_name="title",
        label="角色选择界面",
        timeout_seconds=timeout_seconds,
        threshold=config.flow.template_threshold,
        poll_interval=1.0,
        expand_ratio=2.0,
        scene_checkers=scene_checkers,
    )


def _enter_channel_to_character_select(config: AppConfig, base_dir: Path) -> None:
    startgame_retry = config.flow.channel_startgame_retry
    channel_resolver = _make_channel_anchor_resolver(config, base_dir)
    character_resolver = _make_character_anchor_resolver(config, base_dir)
    in_game_resolver = _make_in_game_anchor_resolver(config, base_dir)
    scene_checkers = _build_scene_checkers(
        config,
        channel_resolver=channel_resolver,
        character_resolver=character_resolver,
        in_game_resolver=in_game_resolver,
    )
    for attempt in range(1, startgame_retry + 1):
        scene = _detect_scene(scene_checkers)
        if scene in {"角色选择界面", "进入游戏界面"}:
            logger.info("检测到已进入%s，跳过频道选择", scene)
            return
        ready = _wait_channel_select_ready(
            config,
            channel_resolver,
            scene_checkers=scene_checkers,
        )
        if not ready:
            scene = _detect_scene(scene_checkers)
            if scene in {"角色选择界面", "进入游戏界面"}:
                logger.info("检测到已进入%s，跳过频道选择", scene)
                return
            logger.warning(
                "等待频道选择界面超时，第 %d/%d 次重试",
                attempt,
                startgame_retry,
            )
            continue
        _select_channel_with_refresh(
            config,
            channel_resolver,
            scene_checkers=scene_checkers,
        )
        ready = _wait_character_select_ready(
            config,
            character_resolver,
            timeout_seconds=config.flow.step_timeout_seconds,
            scene_checkers=scene_checkers,
        )
        if ready:
            logger.info("已进入角色选择界面")
            return
        if _match_in_game_once(config, in_game_resolver):
            logger.info("检测到已进入游戏界面，跳过角色选择等待")
            return
        logger.warning(
            "未进入角色选择界面，第 %d/%d 次重试",
            attempt,
            startgame_retry,
        )

    _end_game_and_fail(
        config,
        channel_resolver() / "channel_select" / "roi.json",
        reason="进入角色选择界面失败，已超过重试次数",
    )


def _enter_character_to_in_game(config: AppConfig, base_dir: Path) -> None:
    startgame_retry = config.flow.channel_startgame_retry
    character_resolver = _make_character_anchor_resolver(config, base_dir)
    in_game_resolver = _make_in_game_anchor_resolver(config, base_dir)
    scene_checkers = _build_scene_checkers(
        config,
        character_resolver=character_resolver,
        in_game_resolver=in_game_resolver,
    )
    for attempt in range(1, startgame_retry + 1):
        if _match_in_game_once(config, in_game_resolver):
            logger.info("检测到已进入游戏界面，跳过角色选择")
            _wait_in_game_and_exit(config)
            return
        ready = _wait_character_select_ready(
            config,
            character_resolver,
            timeout_seconds=config.flow.step_timeout_seconds,
            scene_checkers=scene_checkers,
        )
        if not ready:
            logger.warning(
                "等待角色选择界面超时，第 %d/%d 次重试",
                attempt,
                startgame_retry,
            )
            if _match_in_game_once(config, in_game_resolver):
                logger.info("检测到已进入游戏界面，跳过角色选择")
                _wait_in_game_and_exit(config)
                return
            continue

        if not _select_character_and_start(
            config,
            character_resolver,
            scene_checkers=scene_checkers,
        ):
            logger.warning(
                "角色位置未匹配到，第 %d/%d 次重试",
                attempt,
                startgame_retry,
            )
            if _match_in_game_once(config, in_game_resolver):
                logger.info("检测到已进入游戏界面，跳过角色选择")
                _wait_in_game_and_exit(config)
                return
            continue

        in_game_ready = _wait_in_game_ready(
            config,
            in_game_resolver,
            timeout_seconds=config.flow.in_game_match_timeout_seconds,
            scene_checkers=scene_checkers,
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
        character_resolver() / "character_select" / "roi.json",
        reason="进入游戏界面失败，已超过重试次数",
    )


def _select_character_and_start(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    scene_checkers: list[tuple[str, Callable[[], bool]]] | None = None,
) -> bool:
    result = _find_character(
        config=config,
        anchor_resolver=anchor_resolver,
        timeout_seconds=config.flow.step_timeout_seconds,
        expand_ratio=None,
        scene_checkers=scene_checkers,
    )
    if result is None:
        logger.warning("角色模板未匹配到，尝试扩大 ROI 范围")
        result = _find_character(
            config=config,
            anchor_resolver=anchor_resolver,
            timeout_seconds=config.flow.step_timeout_seconds,
            expand_ratio=2.0,
            scene_checkers=scene_checkers,
        )
        if result is None:
            return False

    center, score, anchor_root = result
    click_point(center)
    logger.info("已选择角色: character_1, score=%.3f, point=%s", score, center)
    time.sleep(1)
    roi_path = anchor_root / "character_select" / "roi.json"
    _click_roi_button(config, roi_path, "button_startgame")
    return True


def _find_character(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    timeout_seconds: int,
    expand_ratio: float | None,
    scene_checkers: list[tuple[str, Callable[[], bool]]] | None = None,
) -> tuple[tuple[int, int], float, Path] | None:
    game_title = config.launcher.game_window_title_keyword
    threshold = config.flow.template_threshold
    poll_interval = 0.5
    deadline = time.time() + timeout_seconds
    last_root: Path | None = None
    template_path: Path | None = None
    roi_path: Path | None = None
    last_ocr_time = 0.0

    while time.time() < deadline:
        anchor_root = anchor_resolver()
        if anchor_root != last_root:
            template_path = anchor_root / "character_select" / "character_1.png"
            roi_path = anchor_root / "character_select" / "roi.json"
            last_root = anchor_root

        if expand_ratio is None:
            result = match_template_in_roi(
                template_path=template_path,
                roi_path=roi_path,
                roi_name="character_region",
                window_title=game_title,
                threshold=threshold,
                label="character_1",
            )
        else:
            roi_region = _expand_roi_region(
                roi_path,
                "character_region",
                game_title,
                expand_ratio,
            )
            result = match_template_in_region(
                template_path=template_path,
                roi_region=roi_region,
                window_title=game_title,
                threshold=threshold,
                label="character_1",
            )
        if result.found and result.center:
            return (result.center, result.score, anchor_root)
        if scene_checkers:
            _, last_ocr_time = _maybe_handle_unexpected_ui(
                config,
                scene_checkers,
                last_ocr_time,
            )
        time.sleep(poll_interval)
    return None


def _wait_in_game_ready(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    timeout_seconds: int,
    scene_checkers: list[tuple[str, Callable[[], bool]]] | None = None,
) -> bool:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")

    game_title = config.launcher.game_window_title_keyword
    name_threshold = config.flow.in_game_name_threshold
    title_threshold = config.flow.in_game_title_threshold
    poll_interval = 0.5
    deadline = time.time() + timeout_seconds
    last_report = 0.0
    last_root: Path | None = None
    roi_path: Path | None = None
    name_template: Path | None = None
    title_template: Path | None = None
    last_ocr_time = 0.0

    while time.time() < deadline:
        anchor_root = anchor_resolver()
        if anchor_root != last_root:
            roi_path = anchor_root / "in_game" / "roi.json"
            name_template = anchor_root / "in_game" / "name_cecilia.png"
            title_template = anchor_root / "in_game" / "title_duel.png"
            last_root = anchor_root

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
        if scene_checkers:
            scene, last_ocr_time = _maybe_handle_unexpected_ui(
                config,
                scene_checkers,
                last_ocr_time,
            )
            if scene == "进入游戏界面":
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


def _select_channel_with_refresh(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    scene_checkers: list[tuple[str, Callable[[], bool]]] | None = None,
) -> None:
    max_channel = config.flow.channel_random_range
    refresh_limit = config.flow.channel_refresh_max_retry
    search_timeout = config.flow.channel_search_timeout_seconds
    refresh_delay = config.flow.channel_refresh_delay_ms / 1000

    for refresh_attempt in range(0, refresh_limit + 1):
        found = _find_channels(
            config=config,
            anchor_resolver=anchor_resolver,
            max_channel=max_channel,
            timeout_seconds=search_timeout,
            scene_checkers=scene_checkers,
        )
        if found:
            name, center, score, anchor_root = random.choice(found)
            logger.info(
                "检测到可选频道数量=%d, 随机选择=%s, score=%.3f",
                len(found),
                name,
                score,
            )
            click_point(center)
            logger.info("已选择频道: %s, point=%s", name, center)
            time.sleep(0.5)
            roi_path = anchor_root / "channel_select" / "roi.json"
            _click_roi_button(config, roi_path, "button_startgame")
            return

        if refresh_attempt >= refresh_limit:
            _end_game_and_fail(
                config,
                anchor_resolver() / "channel_select" / "roi.json",
                reason="频道区域未找到可选频道，结束游戏",
            )

        logger.warning(
            "频道区域未找到可选频道，执行刷新: %d/%d",
            refresh_attempt + 1,
            refresh_limit,
        )
        _click_roi_button(
            config,
            anchor_resolver() / "channel_select" / "roi.json",
            "button_refresh",
        )
        time.sleep(refresh_delay)


def _find_channels(
    config: AppConfig,
    anchor_resolver: Callable[[], Path],
    max_channel: int,
    timeout_seconds: int,
    scene_checkers: list[tuple[str, Callable[[], bool]]] | None = None,
) -> list[tuple[str, tuple[int, int], float, Path]]:
    game_title = config.launcher.game_window_title_keyword
    threshold = config.flow.template_threshold
    poll_interval = 0.5
    deadline = time.time() + timeout_seconds
    results: list[tuple[str, tuple[int, int], float, Path]] = []
    last_root: Path | None = None
    channel_templates: list[tuple[str, Path]] = []
    last_ocr_time = 0.0

    while time.time() < deadline:
        anchor_root = anchor_resolver()
        if anchor_root != last_root:
            channel_templates = _load_channel_templates(
                anchor_root,
                max_channel,
            )
            last_root = anchor_root
        roi_path = anchor_root / "channel_select" / "roi.json"
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
                results.append(
                    (name, result.center, result.score, anchor_root)
                )
        if results:
            return results
        if scene_checkers:
            _, last_ocr_time = _maybe_handle_unexpected_ui(
                config,
                scene_checkers,
                last_ocr_time,
            )
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
