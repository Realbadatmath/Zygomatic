#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Render an episode's stored S prompts on Qwen-Image-2512 (ComfyUI) for an A/B
against the FLUX.1-schnell frames that shipped.

    python3 scripts/bench_qwen_vs_schnell.py --state <pipeline_state.json> --out <dir> \
        [--slots 0,4,15] [--steps 20] [--cfg 2.5] [--front-anchor]

Same prompts, same slot order, same 1280x720, seed = the slot's stored seed when
present. The output directory then feeds scripts/bench_era_gate.py (anachronisms,
gore, subject) and typography_ocr (lettering) so both renderers are scored by the
same judges, and a contact sheet for eyes.

--front-anchor prepends the era label to each prompt, as the live pipeline does
since 2026-08-25; off by default so the A/B isolates the MODEL.
"""

import argparse
import json
import os
import sys
import time

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)
os.chdir(CREWS)
_VENV_PY = os.path.join(os.path.dirname(CREWS), '.venv', 'bin', 'python')
if (
    os.path.exists(_VENV_PY)
    and os.path.abspath(sys.prefix) != os.path.abspath(os.path.dirname(CREWS) + '/.venv')
    and not os.environ.get('ZYG_TEST_NO_REEXEC')
):
    os.execv(_VENV_PY, [_VENV_PY, '-u', os.path.abspath(__file__)] + sys.argv[1:])  # noqa: S606  re-exec under the venv interpreter: no shell, argv is this file's own


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--slots', default='')
    ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--cfg', type=float, default=2.5)
    ap.add_argument('--front-anchor', action='store_true')
    a = ap.parse_args()
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    from zyg_dashboard import crewai_web_gui  # noqa: F401
    from zyg_workflows import pipeline_scholarly as ps
    from zyg_workflows import comfy_generation_service as cgs

    if not cgs.is_available():
        sys.exit('ComfyUI not available')
    if not cgs.has_qwen_t2i():
        sys.exit('Qwen-Image-2512 checkpoint missing')
    st = json.load(open(a.state))
    era = st.get('episode_era') or {}
    imgs = sorted((e for e in st.get('essay_images', []) if e.get('source') == 'flux'), key=lambda e: int(e['index']))
    want = {int(x) for x in a.slots.split(',') if x.strip()}
    os.makedirs(a.out, exist_ok=True)
    neg = (
        ps._FLUX_NEGATIVE_STATIC
        if hasattr(ps, '_FLUX_NEGATIVE_STATIC')
        else (
            'nude, nudity, naked, explicit, nsfw, gore, cartoon, anime, watermark, logo, text overlay, '
            'ugly, blurry, low quality, extra fingers, missing fingers, fused fingers, deformed hands, '
            'extra limbs, warped face, clone face, duplicate person, bad anatomy'
        )
    )
    neg = neg + ', ' + ps._ERA_NEGATIVE
    meta = []
    t_all = time.time()
    for e in imgs:
        i = int(e['index'])
        if want and i not in want:
            continue
        dst = os.path.join(a.out, f'slot_{i:03d}.jpg')
        if os.path.isfile(dst):
            continue
        prompt = str(e.get('prompt') or '')
        if a.front_anchor and era.get('period_label'):
            prompt = f'{era["period_label"]}, {prompt}'
        seed = int(e.get('seed') or (1000 + i))
        t0 = time.time()
        ok, bk = cgs.generate_still(
            dst,
            prompt,
            width=1280,
            height=720,
            steps=a.steps,
            cfg=a.cfg,
            seed=seed,
            model_family='qwen',
            extra_negative=neg,
            prompt_finalized=True,
            clear_vram_after=False,
            log_fn=lambda m: None,
        )
        dt = time.time() - t0
        print(f'slot {i:3d} {"ok " if ok else "FAIL"} {bk:24s} {dt:5.1f}s seed={seed}')
        meta.append({'slot': i, 'ok': ok, 'backend': bk, 'seconds': round(dt, 1), 'seed': seed, 'prompt': prompt})
    json.dump(
        {
            'era': era,
            'steps': a.steps,
            'cfg': a.cfg,
            'front_anchor': a.front_anchor,
            'renders': meta,
            'total_s': round(time.time() - t_all, 1),
        },
        open(os.path.join(a.out, 'render_meta.json'), 'w'),
        indent=1,
    )
    print(f'done: {sum(1 for m in meta if m["ok"])}/{len(meta)} in {time.time() - t_all:.0f}s')


if __name__ == '__main__':
    main()
