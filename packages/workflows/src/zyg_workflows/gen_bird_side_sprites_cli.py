# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.gen_bird_side_sprites`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.gen_bird_side_sprites` still reaches it.

`np` and `Image` are imported THROUGH the library module, and the library module is imported before
`comfy_generation_service`, on purpose: the library inserts the crews root on `sys.path`, chdirs into
it and only then imports `storyteller_scene_service`, and that order is what loads the project's
`.env` (ZYG_USE_COMFYUI etc.) before the generation service reads it.
"""

import argparse
import json
import os


def main() -> int:
    # comfy_generation_service is guarded against import-time checks (it touches the live Comfy
    # server), so the CLI imports it only when it runs.
    from zyg_workflows import comfy_generation_service as cgs

    # The library module needs Blender/bpy or an audio stack a bare checkout has not got (it is on
    # tests/import_smoke_skip.txt), so the CLI imports it only when it runs; this module imports clean.
    from zyg_workflows.gen_bird_side_sprites import (
        NEG,
        OUT_DIR,
        PHASES,
        SEED,
        SIZE,
        STYLE,
        Image,
        _calibrate,
        _flood_key,
        _measure_body,
        np,
    )

    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default=None)
    ap.add_argument('--seed', type=int, default=SEED)
    args = ap.parse_args()

    if not cgs.has_klein_t2i():
        print(f'[gen] ABORT: klein-4B not reachable: {cgs.klein_missing_parts()}')
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = {'phases': {}}
    existing = os.path.join(OUT_DIR, 'sprites.json')
    if os.path.isfile(existing):
        with open(existing) as fh:
            manifest = json.load(fh)

    for name, (elev, tmpl) in PHASES.items():
        if args.only and name != args.only:
            continue
        prompt = tmpl.format(STYLE=STYLE)
        raw_path = os.path.join(OUT_DIR, f'_raw_{name}.png')
        print(f'[gen] {name}: seed={args.seed} -> {raw_path}')
        ok, backend = cgs.generate_still(
            raw_path,
            prompt,
            width=SIZE,
            height=SIZE,
            steps=20,
            cfg=4.0,
            seed=args.seed,
            model_family='klein',
            force_workflow='klein_txt2img',
            extra_negative=NEG,
            skip_qa=True,
            prompt_finalized=True,
            human_subject=False,
            solo_subject=True,
        )
        if not ok or not os.path.isfile(raw_path):
            print(f'[gen] {name}: FAILED ({backend})')
            return 2
        im = Image.open(raw_path).convert('RGBA')
        keyed = _flood_key(im)
        al = np.asarray(keyed.split()[-1], dtype=np.float32)
        ys, xs = np.where(al > 8)
        if len(xs) < 20:
            print(f'[gen] {name}: NOTHING KEYED IN — flood fill ate the bird or the backdrop was not uniform')
            return 3
        pad = 6
        x0, x1 = max(0, xs.min() - pad), min(keyed.width, xs.max() + pad)
        y0, y1 = max(0, ys.min() - pad), min(keyed.height, ys.max() + pad)
        crop = keyed.crop((x0, y0, x1, y1))
        head_h, anchor, span, diag = _measure_body(crop)
        fname = f'{name}.png'
        crop.save(os.path.join(OUT_DIR, fname))
        os.remove(raw_path)
        manifest['phases'][name] = {
            'file': fname,
            'size': [crop.width, crop.height],
            'body_w': head_h,  # placeholder — _calibrate() below rescales it
            '_head_h': head_h,
            '_diag': diag,
            'anchor': list(anchor),
            'span': span,
            'elev': elev,
            'src_cell': f'{name}_{args.seed}',
        }
        print(
            f'[gen] {name}: {crop.width}x{crop.height}, head_h={head_h:.1f}, '
            f'anchor=({anchor[0]:.1f},{anchor[1]:.1f}), span={span:.1f}, '
            f'diag={diag:.1f}'
        )

    _calibrate(manifest)
    manifest['ladder'] = ['side_up', 'side_upper', 'side_level', 'side_lower', 'side_down']
    manifest['note'] = (
        'Serinus canaria, SIDE-PROFILE views, head/beak toward screen-left '
        '(banking that way) — the yaw companion to canary/ (rear-only). '
        'Rendered with FLUX.2 klein-4B (Apache-2.0) txt2img, seed 4041, same '
        'as the rear set, so it reads as the same bird. elev matches the '
        'rear ladder 1-for-1 so _bird_phase_at resolves both sets the same '
        'way; side_glide has elev null and is chosen off tuck, same as '
        'rear_glide. Mirror horizontally at render time for a shot whose '
        'yaw sign is positive (turning screen-right) instead of re-rendering.'
    )
    with open(os.path.join(OUT_DIR, 'sprites.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    print(f'[gen] wrote {os.path.join(OUT_DIR, "sprites.json")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
