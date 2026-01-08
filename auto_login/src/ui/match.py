from __future__ import annotations

from pathlib import Path

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:  # pragma: no cover - 运行时依赖
    raise RuntimeError(
        "缺少图像识别依赖库，请先安装：pip install opencv-python"
    ) from exc


def load_template(path: Path) -> "np.ndarray":
    """加载模板图片并返回 BGR 图像。"""

    if not path.exists():
        raise FileNotFoundError(f"模板文件不存在：{path}")
    if not path.is_file():
        raise FileNotFoundError(f"模板路径不是文件：{path}")

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"模板文件无法读取：{path}")
    return image


def match_template(
    image: "np.ndarray", template: "np.ndarray", threshold: float
) -> tuple[bool, float, tuple[int, int]]:
    """
    对 image 进行模板匹配，返回是否命中、最佳分数与位置。

    threshold: 命中阈值，范围 0~1。
    """

    if image is None or template is None:
        raise ValueError("输入图像或模板为空")

    if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
        return False, 0.0, (0, 0)

    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return max_val >= threshold, float(max_val), max_loc
