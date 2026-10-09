#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Generate static OpenPose-style skeleton maps for contact-sheet pose lock (640×720)."""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_POSE_DIR = os.path.join(_CREWS, 'assets', 'contact_sheet_poses')

# DWPose-style limb colors (RGB) on black background for Union pose mode.
_COLORS = {
    'torso': (255, 0, 0),
    'l_arm': (255, 85, 0),
    'r_arm': (255, 170, 0),
    'l_leg': (0, 255, 0),
    'r_leg': (0, 170, 255),
    'head': (170, 0, 255),
    'face': (255, 255, 0),
}

# Yaw degrees per angle index (matches CONTACT_SHEET_ANGLE_LABELS order).
_YAW_DEG = [
    0,
    -35,
    35,
    -90,
    90,
    180,
    0,
    0,
    0,
    -35,
    35,
    0,
    0,
    -35,
    35,
    0,
    0,
    -35,
    35,
    -35,
    35,
    0,
    -30,
    0,
]


def _rot_y(x: float, y: float, z: float, yaw_rad: float) -> tuple[float, float, float]:
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    return c * x + s * z, y, -s * x + c * z


def _project(x: float, y: float, z: float, cx: float, cy: float, scale: float) -> tuple[int, int]:
    return int(cx + x * scale), int(cy - y * scale + z * 0.15 * scale)


def _stick_figure_points(yaw_deg: float, w: int, h: int) -> dict[str, tuple[int, int]]:
    yaw = math.radians(yaw_deg)
    cx, cy = w * 0.5, h * 0.52
    sc = min(w, h) * 0.22

    def p(x, y, z=0.0):
        xr, yr, zr = _rot_y(x, y, z, yaw)
        return _project(xr, yr, zr, cx, cy, sc)

    return {
        'head': p(0, 1.05, 0),
        'neck': p(0, 0.75, 0),
        'shoulder_l': p(-0.45, 0.7, 0),
        'shoulder_r': p(0.45, 0.7, 0),
        'elbow_l': p(-0.65, 0.35, 0.05),
        'elbow_r': p(0.65, 0.35, 0.05),
        'wrist_l': p(-0.75, 0.0, 0.08),
        'wrist_r': p(0.75, 0.0, 0.08),
        'hip': p(0, 0.0, 0),
        'hip_l': p(-0.22, 0.0, 0),
        'hip_r': p(0.22, 0.0, 0),
        'knee_l': p(-0.22, -0.55, 0.02),
        'knee_r': p(0.22, -0.55, 0.02),
        'ankle_l': p(-0.22, -1.05, 0.04),
        'ankle_r': p(0.22, -1.05, 0.04),
    }


def render_pose(yaw_deg: float, size: tuple[int, int] = (640, 720)) -> Image.Image:
    w, h = size
    img = Image.new('RGB', (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    pts = _stick_figure_points(yaw_deg, w, h)
    lw = max(4, min(w, h) // 80)

    def line(a: str, b: str, color: tuple[int, int, int]) -> None:
        draw.line([pts[a], pts[b]], fill=color, width=lw)

    line('head', 'neck', _COLORS['head'])
    line('neck', 'shoulder_l', _COLORS['torso'])
    line('neck', 'shoulder_r', _COLORS['torso'])
    line('shoulder_l', 'elbow_l', _COLORS['l_arm'])
    line('elbow_l', 'wrist_l', _COLORS['l_arm'])
    line('shoulder_r', 'elbow_r', _COLORS['r_arm'])
    line('elbow_r', 'wrist_r', _COLORS['r_arm'])
    line('neck', 'hip', _COLORS['torso'])
    line('hip', 'hip_l', _COLORS['torso'])
    line('hip', 'hip_r', _COLORS['torso'])
    line('hip_l', 'knee_l', _COLORS['l_leg'])
    line('knee_l', 'ankle_l', _COLORS['l_leg'])
    line('hip_r', 'knee_r', _COLORS['r_leg'])
    line('knee_r', 'ankle_r', _COLORS['r_leg'])
    for k in pts:
        r = lw + 2
        x, y = pts[k]
        draw.ellipse([x - r, y - r, x + r, y + r], fill=_COLORS['face'])
    return img


def generate_pose_library(out_dir: str | None = None, count: int = 24) -> list[str]:
    out_dir = out_dir or DEFAULT_POSE_DIR
    os.makedirs(out_dir, exist_ok=True)
    paths: list[str] = []
    for i in range(count):
        yaw = _YAW_DEG[i] if i < len(_YAW_DEG) else 0
        path = os.path.join(out_dir, f'angle_{i:02d}.png')
        render_pose(yaw).save(path, format='PNG')
        paths.append(path)
    return paths


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=DEFAULT_POSE_DIR)
    ap.add_argument('--count', type=int, default=24)
    args = ap.parse_args()
    paths = generate_pose_library(args.out_dir, args.count)
    print(f'Wrote {len(paths)} pose maps to {args.out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
