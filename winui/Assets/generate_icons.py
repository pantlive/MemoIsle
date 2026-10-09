#!/usr/bin/env python3
"""MemoIsle 品牌图标生成器。

构图：记忆之岛日出 —— teal 渐变圆角方块上，一轮白色圆日与三道渐远的海浪。
输出：
- desktop/icons/icon.png        (512px，应用主图标)
- desktop/icons/icon.ico        (16/24/32/48/64/128/256 多尺寸，Windows 打包用)
- extension/icons/icon128.png   (扩展工具栏/通知图标，与桌面端统一)
"""

from __future__ import annotations

import numpy as np
from pathlib import Path

SIZE = 1024
ROOT = Path(__file__).resolve().parent.parent  # desktop/

TOP_COLOR = np.array([30, 145, 136], dtype=float)    # #1E9188
BOTTOM_COLOR = np.array([12, 87, 81], dtype=float)   # #0C5751


def rounded_square_mask(size: int, inset: int, radius: float) -> np.ndarray:
    """返回 size×size 的圆角方块 alpha（0..1），边缘抗锯齿。"""
    y, x = np.mgrid[0:size, 0:size].astype(float)
    left = inset + radius
    top = inset + radius
    right = size - inset - radius
    bottom = size - inset - radius
    # 计算到圆角边界的最短距离（负值在内）
    dx = np.maximum(np.maximum(left - x, x - right), 0.0)
    dy = np.maximum(np.maximum(top - y, y - bottom), 0.0)
    dist = np.hypot(dx, dy) - radius
    outside = (x < inset) | (x >= size - inset) | (y < inset) | (y >= size - inset)
    dist = np.where(outside, 1.0, dist)
    return np.clip(0.5 - dist, 0.0, 1.0)  # 半像素平滑


def make_icon(size: int) -> np.ndarray:
    y = np.arange(size, dtype=float) / (size - 1)
    background = np.outer(1 - y, TOP_COLOR) + np.outer(y, BOTTOM_COLOR)  # 每行垂直渐变
    shape_mask = rounded_square_mask(size, inset=round(0.02 * size), radius=0.20 * size)
    rgb = background * shape_mask[..., None]
    alpha = shape_mask.copy()

    # 圆日：记忆点
    sun_cy = 0.375 * size
    sun_r = 0.135 * size
    yy, xx = np.mgrid[0:size, 0:size].astype(float)
    sun_dist = np.hypot(xx - 0.5 * size, yy - sun_cy)
    sun_alpha = np.clip(sun_r - sun_dist + 0.5, 0.0, 1.0)
    rgb = rgb + np.ones((size, size, 1)) * sun_alpha[..., None]
    alpha = np.maximum(alpha, sun_alpha)

    # 三道海浪：余弦波带，逐层变细变淡（视觉纵深）
    waves = [
        (0.585, 0.030, 0.95),  # (基线比例, 半厚比例, 透明度)
        (0.675, 0.025, 0.72),
        (0.765, 0.020, 0.50),
    ]
    for base_ratio, half_ratio, opacity in waves:
        base = base_ratio * size
        half = half_ratio * size
        wave_center = base + 0.045 * size * np.cos(2 * np.pi * xx / (0.9 * size))
        inside_x = (xx >= 0.16 * size) & (xx <= 0.84 * size)
        dist = np.abs(yy - wave_center)
        band = np.clip(half - dist + 0.5, 0.0, 1.0) * inside_x
        rgb = rgb + np.ones((size, size, 1)) * (opacity * band[..., None])
        alpha = np.maximum(alpha, band * opacity)

    rgba = np.concatenate(
        [np.clip(rgb, 0, 255), np.clip(alpha * 255, 0, 255)[..., None]],
        axis=2,
    ).astype(np.uint8)
    return rgba


def main() -> None:
    from PIL import Image

    source = make_icon(SIZE)
    image = Image.fromarray(source, "RGBA")

    desktop_icons = ROOT / "icons"
    desktop_icons.mkdir(exist_ok=True)

    image.resize((512, 512), Image.LANCZOS).save(desktop_icons / "icon.png")
    image.save(
        desktop_icons / "icon.ico",
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
    )
    image.resize((128, 128), Image.LANCZOS).save(
        ROOT.parent / "extension" / "icons" / "icon128.png",
    )
    print("generated desktop/icons/icon.png, desktop/icons/icon.ico, extension/icons/icon128.png")


if __name__ == "__main__":
    main()
