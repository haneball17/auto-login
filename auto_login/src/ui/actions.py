from __future__ import annotations

try:
    import pyautogui
except ModuleNotFoundError as exc:  # pragma: no cover - 运行时依赖
    raise RuntimeError(
        "缺少 UI 依赖库，请先安装：pip install pyautogui"
    ) from exc


def click(x: int, y: int) -> None:
    """点击屏幕坐标，确保触发按钮动作。"""

    pyautogui.click(x=x, y=y)
