#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regenerate Vera front preview until YOLO sees two hands with decent confidence."""

from __future__ import annotations

import os
import sys
import time

from zyg_workflows import paths

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)
os.chdir(CREWS)

CHAR_ID = 'a6ca8cb13e6e'
FRONT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars' / CHAR_ID / 'preview_sdxl_front.png')
MAX_ROUNDS = int(os.environ.get('ZYG_HAND_ITERATE_MAX', '4'))
MIN_HANDS = 2
MAX_HANDS = 2
MIN_YOLO = float(os.environ.get('ZYG_HAND_ITERATE_MIN_YOLO', '0.75'))


def _score(path: str) -> tuple[float, int]:
    from zyg_dashboard.crewai_web_gui import _preview_hand_yolo_score

    sc, n, _ = _preview_hand_yolo_score(path)
    return sc, n


def main() -> int:
    from zyg_workflows import character_bible_service as cbs
    from zyg_dashboard import crewai_web_gui as gui

    pkg = cbs.load(CHAR_ID)
    if not pkg:
        print(f'No bible for {CHAR_ID}', flush=True)
        return 1
    cond = pkg.setdefault('conditioning', {})
    sp = pkg.setdefault('style_profile', {})
    sp['render_style'] = 'photorealistic'
    cond['instantid_enabled'] = False
    cond['model_family'] = 'sdxl'
    cond['hand_detail_strength'] = float(os.environ.get('ZYG_PREVIEW_HAND_DETAIL_DENOISE', '0.42'))
    cond['quality_suffix'] = (
        'shot on 85mm portrait lens, f/1.8, shallow depth of field, '
        'highly detailed, sharp focus, cinematic lighting, '
        'photorealistic skin texture, natural pores, 8k photograph'
    )
    cond['negative_prompt'] = (
        'blurry, low quality, deformed face, bad anatomy, extra fingers, extra limbs, '
        'mutated hands, cartoon, anime, cel shading, illustration, line art, flat colors, '
        '2d, manga, painterly, sketch'
    )
    cbs.save(pkg)
    params, info = gui._char_params_from_bible(CHAR_ID)
    info['render_mode'] = 'blender'
    info['package'] = cbs.load(CHAR_ID)

    for rnd in range(1, MAX_ROUNDS + 1):
        print(f'\n=== Round {rnd}/{MAX_ROUNDS} ===', flush=True)
        os.environ['ZYG_PREVIEW_SEED_CANDIDATES'] = os.environ.get(
            'ZYG_PREVIEW_SEED_CANDIDATES',
            '7',
        )
        os.environ['ZYG_PREVIEW_SEED_ROUND'] = str(rnd)
        t0 = time.time()
        result = gui._render_char_preview_slots(
            CHAR_ID,
            params,
            info,
            log_fn=lambda m: print(f'  {m}', flush=True),
            force=True,
            model_family='sdxl',
        )
        print(f'elapsed={time.time() - t0:.1f}s result={result.get("preview_quality_ok")}', flush=True)
        if not os.path.isfile(FRONT):
            print('ERROR: front png missing', flush=True)
            continue
        yolo_sc, hand_n = _score(FRONT)
        print(f'POST yolo={yolo_sc:.2f} hands={hand_n} path={FRONT}', flush=True)
        if MIN_HANDS <= hand_n <= MAX_HANDS and yolo_sc >= MIN_YOLO:
            print('SUCCESS: two hands detected with good confidence', flush=True)
            return 0
    print('WARN: criteria not met after max rounds — check image manually', flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
