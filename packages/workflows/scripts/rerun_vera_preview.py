#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Re-render Vera (a6ca8cb13e6e) SDXL previews with the fixed pipeline."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from zyg_workflows import paths

CREWS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CREWS))
os.chdir(CREWS)

CHAR_ID = 'a6ca8cb13e6e'
DATASET = paths.ZYG_LORA_DATASETS / 'storyteller_chars' / CHAR_ID


def main() -> int:
    from zyg_workflows import character_bible_service as cbs
    from zyg_dashboard import crewai_web_gui as gui

    pkg = cbs.load(CHAR_ID)
    if not pkg:
        print(f'No bible for {CHAR_ID}', flush=True)
        return 1

    sp = pkg.setdefault('style_profile', {})
    sp['render_style'] = 'photorealistic'
    cond = pkg.setdefault('conditioning', {})
    cond['instantid_enabled'] = False
    cond['model_family'] = 'sdxl'
    cond['hand_detail_strength'] = float(os.environ.get('ZYG_PREVIEW_HAND_DETAIL_DENOISE', '0.42'))
    cond['quality_suffix'] = (
        'shot on 85mm portrait lens, f/1.8, shallow depth of field, '
        'highly detailed, sharp focus, cinematic lighting, '
        'photorealistic skin texture, natural pores, 8k photograph'
    )
    cond['negative_prompt'] = (
        'blurry, low quality, low resolution, jpeg artifacts, deformed face, bad anatomy, '
        'extra fingers, extra limbs, mutated hands, malformed, asymmetric eyes, '
        'watermark, text, signature, logo, cartoon, anime, cel shading, illustration, '
        'line art, flat colors, 2d, manga, painterly, sketch, oil painting'
    )
    cbs.save(pkg)
    print('Bible: photorealistic SDXL preview, instantid_enabled=False', flush=True)

    params, info = gui._char_params_from_bible(CHAR_ID)
    info['render_mode'] = 'blender'
    info['package'] = cbs.load(CHAR_ID)

    print('Starting SDXL preview regenerate (force=True)…', flush=True)
    t0 = time.monotonic()
    res = gui._render_char_preview_slots(
        CHAR_ID,
        params,
        info,
        log_fn=lambda m: print(f'  {m}', flush=True),
        force=True,
        model_family='sdxl',
    )
    elapsed = time.monotonic() - t0

    out = {k: v for k, v in res.items() if k != 'slot_meta'}
    out['elapsed_s'] = round(elapsed, 1)
    out['slot_meta'] = res.get('slot_meta') or {}
    print('\n=== RESULT ===', flush=True)
    print(json.dumps(out, indent=2), flush=True)

    for name in ('preview_sdxl_front.png', 'preview_sdxl_face.png'):
        p = DATASET / name
        if p.is_file():
            print(
                f'{name}: {p.stat().st_size // 1024} KB  '
                f'mtime={time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))}',
                flush=True,
            )
        else:
            print(f'{name}: MISSING', flush=True)

    ok = bool(res.get('rendered')) and res.get('preview_quality_ok')
    if res.get('preview_warning'):
        print(f'preview_warning: {res["preview_warning"]}', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
