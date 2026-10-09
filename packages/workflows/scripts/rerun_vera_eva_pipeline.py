#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Re-train Vera with Eva pipeline (FLUX LoRA + FLUX locked preview)."""

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
LORA_TIMEOUT_S = int(os.environ.get('ZYG_LORA_TRAIN_TIMEOUT_S', '3600'))


def main() -> int:
    from zyg_workflows import character_bible_service as cbs
    from zyg_dashboard import crewai_web_gui as gui
    from zyg_workflows import lora_trainer_service as lts

    pkg = cbs.load(CHAR_ID)
    if not pkg:
        print(f'No bible for {CHAR_ID}', flush=True)
        return 1

    sp = pkg.setdefault('style_profile', {})
    sp['render_style'] = 'photorealistic'
    sp['genre'] = sp.get('genre') or 'romance'
    sp.setdefault('lighting_profile', 'soft warm key, gentle backlight, gauzy fill')
    sp.setdefault(
        'default_clothing',
        'elegant flowing dress, soft warm tones, refined jewelry',
    )
    sp.setdefault('accessories', 'pearl earrings, delicate pendant')

    cond = pkg.setdefault('conditioning', {})
    cond['model_family'] = 'flux'
    cond['instantid_enabled'] = False
    cond['face_detail_pass'] = True
    cond['face_detail_strength'] = 0.48
    cond['skin_pore_pass'] = True
    cond['quality_suffix'] = (
        'shot on 85mm portrait lens, f/5.6, sharp focus, '
        'visible skin pores, natural skin microdetail, realistic skin texture, '
        'cinematic lighting, highly detailed, 8k'
    )
    cond['negative_prompt'] = (
        'blurry, low quality, deformed face, bad anatomy, extra fingers, '
        'cartoon, anime, cel shading, illustration, line art, painterly, sketch'
    )
    cbs.save(pkg)
    print('Bible: FLUX photorealistic (Eva pipeline)', flush=True)

    dataset_dir = str(DATASET)
    trigger = pkg.get('trigger_token') or f'ZYG_CHAR_{CHAR_ID[:6].upper()}'

    trainer = lts.get_trainer()

    def _flux_lora_ready(status: dict) -> bool:
        if status.get('failed') or not status.get('done'):
            return False
        lp = status.get('lora_path') or ''
        if not lp or not Path(lp).is_file():
            return False
        if status.get('model_family') != 'flux':
            return False
        return 'lora-weights-flux' in lp and Path(lp).stat().st_size > 250_000_000

    st = trainer.get_status(CHAR_ID, model_family='flux')
    if not _flux_lora_ready(st):
        print('Starting FLUX LoRA training (SimpleTuner)…', flush=True)
        trainer.start_training(
            CHAR_ID,
            dataset_dir,
            trigger_token=trigger,
            model_family='flux',
        )
        elapsed = 0
        while elapsed < LORA_TIMEOUT_S:
            time.sleep(10)
            elapsed += 10
            st = trainer.get_status(CHAR_ID, model_family='flux')
            pct = int(st.get('pct', 0))
            if pct > 0 and pct % 10 == 0:
                print(
                    f'  training {pct}% ({st.get("step", 0)}/{st.get("total_steps", 200)})',
                    flush=True,
                )
            if _flux_lora_ready(st):
                print(f'  LoRA done: {st.get("lora_path")}', flush=True)
                break
            if st.get('failed'):
                print(f'  LoRA FAILED: {st.get("error")}', flush=True)
                tail = st.get('log_tail') or []
                for line in tail[-8:]:
                    print(f'    {line}', flush=True)
                return 1
        else:
            print('LoRA training timed out', flush=True)
            return 1

    lora_path = st.get('lora_path') or trainer.get_lora_path(CHAR_ID, model_family='flux')
    if not _flux_lora_ready({**st, 'lora_path': lora_path, 'done': bool(lora_path)}):
        print(f'No valid FLUX LoRA after training: {lora_path}', flush=True)
        return 1
    cbs.update_lora(CHAR_ID, lora_path, print, model_family='flux')

    params, info = gui._char_params_from_bible(CHAR_ID)
    info['render_mode'] = 'blender'
    info['package'] = cbs.load(CHAR_ID)
    info['model_family'] = 'flux'

    print('Generating hybrid previews (SDXL front + FLUX face, pores + hand pass)…', flush=True)
    t0 = time.monotonic()
    res = gui._render_char_preview_slots(
        CHAR_ID,
        params,
        info,
        log_fn=lambda m: print(f'  {m}', flush=True),
        force=True,
        model_family='flux',
    )
    elapsed = time.monotonic() - t0
    out = {k: v for k, v in res.items() if k != 'slot_meta'}
    out['elapsed_s'] = round(elapsed, 1)
    out['slot_meta'] = res.get('slot_meta') or {}
    print('\n=== RESULT ===', flush=True)
    print(json.dumps(out, indent=2), flush=True)
    for name in (
        'preview_sdxl_front.png',
        'preview_flux_face.png',
        'preview_flux_front.png',
        'preview_flux_face.png',
    ):
        p = DATASET / name
        if p.is_file():
            print(f'{name}: {p.stat().st_size // 1024} KB', flush=True)
    return 0 if res.get('preview_quality_ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
