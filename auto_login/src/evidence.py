from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class EvidenceContext:
    """证据留存上下文。"""

    base_dir: Path
    cycle_id: str
    account_id: str


class EvidenceRecorder:
    """证据留存器，负责将错误与上下文信息落盘。"""

    def __init__(self, context: EvidenceContext) -> None:
        self._context = context
        self._ensure_dir(context.base_dir)

    @staticmethod
    def _ensure_dir(path: Path) -> None:
        """确保目录存在。"""

        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sanitize(name: str) -> str:
        """清理文件名，避免非法路径字符。"""

        cleaned = name.strip().replace(" ", "_")
        cleaned = cleaned.replace("/", "_").replace("\\", "_")
        return cleaned or "unknown"

    def _step_dir(self, step_name: str) -> Path:
        """生成并创建 step 目录。"""

        step = self._sanitize(step_name)
        step_dir = (
            self._context.base_dir
            / self._sanitize(self._context.cycle_id)
            / self._sanitize(self._context.account_id)
            / step
        )
        self._ensure_dir(step_dir)
        return step_dir

    def save_text(self, step_name: str, filename: str, content: str) -> Path:
        """保存文本内容到证据目录。"""

        step_dir = self._step_dir(step_name)
        target = step_dir / self._sanitize(filename)
        target.write_text(content, encoding="utf-8")
        return target

    def save_bytes(self, step_name: str, filename: str, content: bytes) -> Path:
        """保存二进制内容（如截图）到证据目录。"""

        step_dir = self._step_dir(step_name)
        target = step_dir / self._sanitize(filename)
        target.write_bytes(content)
        return target

    def save_exception(self, step_name: str, exc: BaseException) -> Path:
        """保存异常堆栈到证据目录。"""

        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"trace_{timestamp}.txt"
        return self.save_text(step_name, filename, trace)
