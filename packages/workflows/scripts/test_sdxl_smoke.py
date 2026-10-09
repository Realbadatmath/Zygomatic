#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
test_sdxl_smoke.py — SDXL (Juggernaut XL) ComfyUI smoke test
============================================================

Validates that:
  - The SDXL workflow template exists in the repo (`sdxl_txt2img`)
  - The SDXL checkpoint file exists in ComfyUI checkpoints
  - ComfyUI is reachable
  - A single SDXL image can be generated via `comfy_generation_service.generate_still`
  - Character preview still helper works (`generate_character_preview_still`)

Usage:
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  python3 scripts/test_sdxl_smoke.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from zyg_workflows import paths

CREWS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CREWS_DIR))


def main() -> int:
    from zyg_workflows import _comfy_client as cc
    from zyg_workflows import comfy_generation_service as cgs

    comfy_root = str(paths.ZYG_COMFY_ROOT)
    ckpt_name = (
        os.environ.get(
            'ZYG_SDXL_CHECKPOINT',
            'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors',
        ).strip()
        or 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'
    )
    ckpt_path = os.path.join(comfy_root, 'models', 'checkpoints', ckpt_name)

    print('[SDXL-SMOKE] Loading workflow template: sdxl_txt2img')
    wf = cc.load_workflow('sdxl_txt2img')
    assert isinstance(wf, dict) and '10' in wf, 'sdxl_txt2img workflow missing node 10'
    assert wf['10'].get('class_type') == 'CheckpointLoaderSimple', 'node 10 is not CheckpointLoaderSimple'

    print(f'[SDXL-SMOKE] Checking checkpoint exists: {ckpt_path}')
    if not os.path.isfile(ckpt_path):
        raise SystemExit(f'[SDXL-SMOKE] Missing SDXL checkpoint file: {ckpt_path}')

    print('[SDXL-SMOKE] Checking ComfyUI reachable…')
    if not cc.server_reachable():
        raise SystemExit('[SDXL-SMOKE] ComfyUI server not reachable (is it running?)')

    out_path = str(paths.tmp_dir('sdxl_smoke') / 'zyg_sdxl_smoke.png')
    prompt = 'photorealistic portrait photo of a woman, natural skin texture, studio lighting, sharp focus'
    print(f'[SDXL-SMOKE] Generating still: {out_path}')

    t0 = time.monotonic()
    ok, backend = cgs.generate_still(
        out_path=out_path,
        scene_prompt=prompt,
        width=1024,
        height=1024,
        steps=30,
        cfg=6.0,
        seed=12345,
        character_package=None,
        char_id='',
        init_image=None,
        reference_image=None,
        model_family='sdxl',
        log_fn=lambda m: print('[SDXL-SMOKE]', m),
    )
    dt = time.monotonic() - t0

    if not ok:
        raise SystemExit(f'[SDXL-SMOKE] generate_still failed ({backend})')

    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 10_000:
        raise SystemExit('[SDXL-SMOKE] Output file missing or too small')

    print(f'[SDXL-SMOKE] PASS still: {out_path} ({os.path.getsize(out_path) / 1e6:.2f} MB) in {dt:.1f}s via {backend}')

    prev_path = str(paths.tmp_dir('sdxl_smoke') / 'zyg_sdxl_char_preview_smoke.png')
    prev_prompt = (
        'ZYG_CHAR_SMOKE01, 25-year-old female character, close-up portrait, facing camera, '
        'medium skin, brown eyes, brown hair, photorealistic render, highly detailed, sharp focus'
    )
    neg_pkg = {
        'conditioning': {
            'negative_prompt': 'blurry, low quality, deformed face, bad anatomy, watermark, text',
        }
    }
    print(f'[SDXL-SMOKE] Generating character preview still: {prev_path}')
    t1 = time.monotonic()
    ok2, backend2, _drift_ok, _drift_sc = cgs.generate_character_preview_still(
        prev_path,
        prev_prompt,
        width=512,
        height=512,
        seed=54321,
        character_package=neg_pkg,
        char_id='smoke01',
        reference_image=None,
        model_family='sdxl',
        log_fn=lambda m: print('[SDXL-SMOKE]', m),
    )
    dt2 = time.monotonic() - t1

    if not ok2:
        raise SystemExit(f'[SDXL-SMOKE] generate_character_preview_still failed ({backend2})')

    if not os.path.isfile(prev_path) or os.path.getsize(prev_path) < 10_000:
        raise SystemExit('[SDXL-SMOKE] Preview output missing or too small')

    print(
        f'[SDXL-SMOKE] PASS preview: {prev_path} ({os.path.getsize(prev_path) / 1e6:.2f} MB) '
        f'in {dt2:.1f}s via {backend2}'
    )
    print('[SDXL-SMOKE] All checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
