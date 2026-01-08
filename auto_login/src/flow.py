from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from src.config import Account, FlowConfig
from src.evidence import EvidenceContext, EvidenceRecorder


class ChannelState(Enum):
    """频道界面状态枚举。"""

    READY = "ready"
    FETCH_FAILED = "fetch_failed"
    EMPTY_LIST = "empty_list"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FlowContext:
    """单次账号执行上下文。"""

    cycle_id: str
    account_id: str
    random_seed: int


@dataclass(frozen=True)
class FlowResult:
    """流程执行结果。"""

    success: bool
    failed_step: str | None
    message: str


@dataclass(frozen=True)
class StepPolicy:
    """步骤重试与超时策略。"""

    timeout_seconds: int
    retry: int


class FlowDependencies(Protocol):
    """流程依赖接口，具体实现由自动化模块提供。"""

    def start_launcher(self, account: Account, timeout_seconds: int) -> bool:
        """启动登录器。"""

    def wait_launcher_enable(self, timeout_seconds: int) -> bool:
        """等待启动按钮变为可用并点击启动。"""

    def web_login(self, account: Account, timeout_seconds: int) -> bool:
        """执行网页登录。"""

    def wait_game_process(self, timeout_seconds: int) -> bool:
        """等待游戏进程出现。"""

    def focus_game_window(self) -> bool:
        """聚焦并调整游戏窗口。"""

    def wait_channel_select(self, timeout_seconds: int) -> bool:
        """等待频道选择界面出现。"""

    def get_channel_state(self) -> ChannelState:
        """获取频道界面状态。"""

    def refresh_channel_list(self) -> bool:
        """点击右下角刷新按钮。"""

    def click_channel(self, index: int) -> bool:
        """点击指定频道序号（从 1 开始）。"""

    def click_game_start(self) -> bool:
        """点击“游戏开始”按钮。"""

    def wait_role_select(self, timeout_seconds: int) -> bool:
        """等待角色选择界面出现。"""

    def click_role(self, index: int) -> bool:
        """点击指定角色序号（从 1 开始）。"""

    def wait_in_game(self, timeout_seconds: int) -> bool:
        """等待进入游戏界面。"""

    def exit_game(self) -> bool:
        """退出游戏。"""


class FlowRunner:
    """单账号流程执行器，负责组织步骤、重试与错误证据。"""

    def __init__(
        self,
        *,
        config: FlowConfig,
        logger: logging.Logger,
        evidence_dir: Path,
        deps: FlowDependencies,
    ) -> None:
        self._config = config
        self._logger = logger
        self._evidence_dir = evidence_dir
        self._deps = deps
        self._policies = self._build_policies(config)

    @staticmethod
    def _build_policies(config: FlowConfig) -> dict[str, StepPolicy]:
        """构建默认步骤策略，来源于方案中的建议值。"""

        return {
            "launch": StepPolicy(timeout_seconds=30, retry=1),
            "wait_launcher_enable": StepPolicy(
                timeout_seconds=config.step_timeout_seconds, retry=1
            ),
            "web_login": StepPolicy(timeout_seconds=60, retry=2),
            "wait_game_process": StepPolicy(
                timeout_seconds=config.step_timeout_seconds, retry=1
            ),
            "wait_channel_select": StepPolicy(
                timeout_seconds=config.step_timeout_seconds, retry=2
            ),
            "click_channel": StepPolicy(timeout_seconds=20, retry=config.click_retry),
            "click_channel_start": StepPolicy(
                timeout_seconds=20, retry=config.click_retry
            ),
            "wait_role_select": StepPolicy(
                timeout_seconds=config.step_timeout_seconds, retry=2
            ),
            "click_role": StepPolicy(timeout_seconds=20, retry=config.click_retry),
            "click_role_start": StepPolicy(timeout_seconds=20, retry=config.click_retry),
            "wait_in_game": StepPolicy(
                timeout_seconds=config.step_timeout_seconds, retry=2
            ),
            "exit_game": StepPolicy(timeout_seconds=20, retry=1),
        }

    def _record_failure(
        self, evidence: EvidenceRecorder, step_name: str, reason: str
    ) -> None:
        """记录失败原因，确保排查链路完整。"""

        self._logger.error("步骤失败：%s，原因：%s", step_name, reason)
        evidence.save_text(step_name, "reason.txt", reason)

    def _execute_step(
        self,
        *,
        step_name: str,
        policy: StepPolicy,
        action: Callable[[], bool],
        evidence: EvidenceRecorder,
    ) -> bool:
        """执行步骤并按策略重试，失败时写入证据。"""

        for attempt in range(1, policy.retry + 2):
            try:
                if action():
                    self._logger.info("步骤成功：%s", step_name)
                    return True
            except Exception as exc:
                self._logger.exception("步骤异常：%s", step_name)
                evidence.save_exception(step_name, exc)

            self._logger.warning(
                "步骤失败：%s，重试 %s/%s",
                step_name,
                attempt,
                policy.retry + 1,
            )

        self._record_failure(evidence, step_name, "超过最大重试次数")
        return False

    def _handle_channel_select(
        self,
        *,
        rng: random.Random,
        evidence: EvidenceRecorder,
    ) -> bool:
        """处理频道选择逻辑，包含“获取频道失败/频道列表为空”刷新策略。"""

        policy_wait = self._policies["wait_channel_select"]
        if not self._execute_step(
            step_name="step_wait_channel_select",
            policy=policy_wait,
            action=lambda: self._deps.wait_channel_select(
                policy_wait.timeout_seconds
            ),
            evidence=evidence,
        ):
            return False

        refresh_max = self._config.channel_refresh_max
        for attempt in range(1, refresh_max + 1):
            state = self._deps.get_channel_state()
            if state == ChannelState.READY:
                channel_index = rng.randint(
                    1, self._config.channel_random_range
                )
                self._logger.info("频道选择：%s", channel_index)
                if not self._execute_step(
                    step_name="step_click_channel",
                    policy=self._policies["click_channel"],
                    action=lambda: self._deps.click_channel(channel_index),
                    evidence=evidence,
                ):
                    return False
                if not self._execute_step(
                    step_name="step_click_channel_start",
                    policy=self._policies["click_channel_start"],
                    action=self._deps.click_game_start,
                    evidence=evidence,
                ):
                    return False
                return True

            if state in (ChannelState.FETCH_FAILED, ChannelState.EMPTY_LIST):
                self._logger.warning(
                    "频道状态异常：%s，尝试刷新 %s/%s",
                    state.value,
                    attempt,
                    refresh_max,
                )
            else:
                self._logger.warning(
                    "频道状态未知，尝试刷新 %s/%s",
                    attempt,
                    refresh_max,
                )

            if not self._deps.refresh_channel_list():
                self._record_failure(
                    evidence,
                    "step_channel_refresh",
                    f"刷新频道失败（第 {attempt} 次）",
                )
            time.sleep(1)

        self._record_failure(
            evidence,
            "step_channel_select",
            f"刷新频道超过 {refresh_max} 次仍无法进入正确界面",
        )
        return False

    def _attempt_exit_game(self, evidence: EvidenceRecorder) -> None:
        """失败时尽力退出游戏，避免流程卡死。"""

        policy_exit = self._policies["exit_game"]
        if not self._execute_step(
            step_name="step_exit_game",
            policy=policy_exit,
            action=self._deps.exit_game,
            evidence=evidence,
        ):
            self._logger.error("退出游戏失败，需要人工干预。")

    def run_account(self, *, context: FlowContext, account: Account) -> FlowResult:
        """执行单账号完整流程。"""

        evidence = EvidenceRecorder(
            EvidenceContext(
                base_dir=self._evidence_dir,
                cycle_id=context.cycle_id,
                account_id=context.account_id,
            )
        )
        rng = random.Random(context.random_seed)

        self._logger.info(
            "开始执行账号流程：account=%s seed=%s",
            context.account_id,
            context.random_seed,
        )

        # 1) 启动登录器
        if not self._execute_step(
            step_name="step_launch",
            policy=self._policies["launch"],
            action=lambda: self._deps.start_launcher(
                account, self._policies["launch"].timeout_seconds
            ),
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_launch", "启动登录器失败")

        # 1.5) 等待启动按钮可用
        if not self._execute_step(
            step_name="step_wait_launcher_enable",
            policy=self._policies["wait_launcher_enable"],
            action=lambda: self._deps.wait_launcher_enable(
                self._policies["wait_launcher_enable"].timeout_seconds
            ),
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_wait_launcher_enable", "等待启动器可用失败")

        # 2) 网页登录
        if not self._execute_step(
            step_name="step_web_login",
            policy=self._policies["web_login"],
            action=lambda: self._deps.web_login(
                account, self._policies["web_login"].timeout_seconds
            ),
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_web_login", "网页登录失败")

        # 3) 等待游戏进程出现
        if not self._execute_step(
            step_name="step_wait_game_process",
            policy=self._policies["wait_game_process"],
            action=lambda: self._deps.wait_game_process(
                self._policies["wait_game_process"].timeout_seconds
            ),
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_wait_game_process", "等待游戏进程失败")

        # 4) 聚焦并调整游戏窗口
        if not self._execute_step(
            step_name="step_focus_game_window",
            policy=StepPolicy(timeout_seconds=0, retry=1),
            action=self._deps.focus_game_window,
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_focus_game_window", "聚焦游戏窗口失败")

        # 5) 频道选择（含异常刷新处理）
        if not self._handle_channel_select(rng=rng, evidence=evidence):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_channel_select", "频道选择失败")

        # 6) 等待角色界面
        if not self._execute_step(
            step_name="step_wait_role_select",
            policy=self._policies["wait_role_select"],
            action=lambda: self._deps.wait_role_select(
                self._policies["wait_role_select"].timeout_seconds
            ),
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_wait_role_select", "等待角色界面失败")

        # 7) 选择角色并进入游戏
        if not self._execute_step(
            step_name="step_click_role",
            policy=self._policies["click_role"],
            action=lambda: self._deps.click_role(1),
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_click_role", "选择角色失败")

        if not self._execute_step(
            step_name="step_click_role_start",
            policy=self._policies["click_role_start"],
            action=self._deps.click_game_start,
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_click_role_start", "角色进入游戏失败")

        # 8) 等待进入游戏界面
        if not self._execute_step(
            step_name="step_wait_in_game",
            policy=self._policies["wait_in_game"],
            action=lambda: self._deps.wait_in_game(
                self._policies["wait_in_game"].timeout_seconds
            ),
            evidence=evidence,
        ):
            self._attempt_exit_game(evidence)
            return FlowResult(False, "step_wait_in_game", "等待进入游戏失败")

        # 9) 游戏内停留以完成在线时长要求
        self._logger.info("进入游戏成功，等待 %s 秒", self._config.enter_game_wait_seconds)
        time.sleep(self._config.enter_game_wait_seconds)

        # 10) 退出游戏
        if not self._execute_step(
            step_name="step_exit_game",
            policy=self._policies["exit_game"],
            action=self._deps.exit_game,
            evidence=evidence,
        ):
            return FlowResult(False, "step_exit_game", "退出游戏失败")

        self._logger.info("账号流程完成：%s", context.account_id)
        return FlowResult(True, None, "success")
