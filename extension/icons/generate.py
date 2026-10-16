#!/usr/bin/env python3
"""从 web/public/favicon.svg 渲染扩展 PNG，保持与主页品牌标一致。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SVG_PATH = ROOT / "web" / "public" / "favicon.svg"
ICON_DIR = Path(__file__).resolve().parent
RENDER_SIZE = 1024
OUTPUT_SIZES = (16, 32, 48, 128)
PATH_COMMANDS = re.compile(r"([MmLlHhVvCcZz])|(-?\d*\.?\d+(?:e[-+]?\d+)?)")


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_color(value: str) -> tuple[int, int, int]:
    color = value.strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise ValueError(f"unsupported svg color: {value}")
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def parse_path(d: str) -> np.ndarray:
    """把品牌标使用的 M/V/L/C 路径采样成折线。"""

    tokens = [match.group(0) for match in PATH_COMMANDS.finditer(d) if match.group(0)]
    points: list[np.ndarray] = []
    command = ""
    args: list[float] = []
    cursor = np.array([0.0, 0.0])

    def take(count: int) -> list[float]:
        if len(args) < count:
            raise ValueError("svg path is incomplete")
        values = args[:count]
        del args[:count]
        return values

    def add_point(point: np.ndarray) -> None:
        nonlocal cursor
        cursor = point
        if points:
            previous = points[-1]
            distance = float(np.hypot(*(point - previous)))
            steps = max(2, int(np.ceil(distance * 4)))
            for t in np.linspace(0.0, 1.0, steps)[1:]:
                points.append(previous + (point - previous) * t)
        else:
            points.append(point)

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            args = []
            if command in {"Z", "z"}:
                add_point(points[0])
            continue
        args.append(float(token))
        index += 1
        if command in {"M", "L"} and len(args) >= 2:
            add_point(np.array(take(2)))
            command = "L"
        elif command == "V" and len(args) >= 1:
            add_point(np.array([cursor[0], take(1)[0]]))
        elif command == "H" and len(args) >= 1:
            add_point(np.array([take(1)[0], cursor[1]]))
        elif command == "C" and len(args) >= 6:
            x1, y1, x2, y2, x, y = take(6)
            start = cursor
            control1 = np.array([x1, y1])
            control2 = np.array([x2, y2])
            end = np.array([x, y])
            for t in np.linspace(0.0, 1.0, 48)[1:]:
                rest = 1.0 - t
                add_point(
                    rest**3 * start
                    + 3 * rest**2 * t * control1
                    + 3 * rest * t**2 * control2
                    + t**3 * end
                )

    if not points:
        raise ValueError("svg path is empty")
    return np.vstack(points)


def rounded_rect_alpha(size: int, radius: float) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size].astype(float)
    left = radius
    top = radius
    right = size - 1 - radius
    bottom = size - 1 - radius
    dx = np.maximum(np.maximum(left - x, x - right), 0.0)
    dy = np.maximum(np.maximum(top - y, y - bottom), 0.0)
    dist = np.hypot(dx, dy) - radius
    return np.clip(0.5 - dist, 0.0, 1.0)


def polyline_distance(points: np.ndarray, size: int) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size].astype(float)
    min_dist = np.full((size, size), np.inf)
    for start, end in zip(points[:-1], points[1:], strict=True):
        span = end - start
        length = float(np.dot(span, span))
        if length < 1e-8:
            dist = np.hypot(x - start[0], y - start[1])
        else:
            t = np.clip(
                ((x - start[0]) * span[0] + (y - start[1]) * span[1]) / length,
                0.0,
                1.0,
            )
            dist = np.hypot(x - (start[0] + t * span[0]), y - (start[1] + t * span[1]))
        min_dist = np.minimum(min_dist, dist)
    return min_dist


def render_mark(size: int) -> Image.Image:
    tree = ET.parse(SVG_PATH)
    root = tree.getroot()
    view_box = [float(part) for part in (root.attrib.get("viewBox") or "0 0 64 64").split()]
    view_width = view_box[2]
    scale = size / view_width

    fill = np.zeros((size, size, 4), dtype=float)
    for child in root:
        tag = local_tag(child.tag)
        if tag == "rect":
            radius = float(child.attrib.get("rx") or 0.0) * scale
            color = parse_color(child.attrib["fill"])
            alpha = rounded_rect_alpha(size, radius)
            fill[..., :3] = np.array(color, dtype=float)
            fill[..., 3] = alpha * 255.0
        elif tag == "path":
            points = parse_path(child.attrib["d"]) * scale
            half_width = float(child.attrib["stroke-width"]) * scale / 2.0
            color = parse_color(child.attrib["stroke"])
            coverage = np.clip(half_width + 0.5 - polyline_distance(points, size), 0.0, 1.0)
            stroke = np.zeros((size, size, 4), dtype=float)
            stroke[..., :3] = np.array(color, dtype=float)
            stroke[..., 3] = coverage * 255.0
            src_a = stroke[..., 3] / 255.0
            dst_a = fill[..., 3] / 255.0
            out_a = src_a + dst_a * (1.0 - src_a)
            for channel in range(3):
                fill[..., channel] = np.where(
                    out_a > 0,
                    (
                        stroke[..., channel] * src_a
                        + fill[..., channel] * dst_a * (1.0 - src_a)
                    )
                    / np.maximum(out_a, 1e-6),
                    fill[..., channel],
                )
            fill[..., 3] = out_a * 255.0

    return Image.fromarray(np.clip(fill, 0, 255).astype(np.uint8), "RGBA")


def main() -> None:
    source = render_mark(RENDER_SIZE)
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for size in OUTPUT_SIZES:
        source.resize((size, size), Image.LANCZOS).save(ICON_DIR / f"icon{size}.png")
    print(
        "generated "
        + ", ".join(f"extension/icons/icon{size}.png" for size in OUTPUT_SIZES)
    )


if __name__ == "__main__":
    main()
