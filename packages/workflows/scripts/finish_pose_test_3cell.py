#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Finish 3-cell pose test: reuse existing cells, generate missing, stitch preview."""

from __future__ import annotations

import os
import sys

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)
os.chdir(_CREWS)

os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
os.environ.setdefault('ZYG_CONTACT_SHEET_STEPS', '16')
os.environ.setdefault('ZYG_CONTACT_SHEET_MIN_CELLS', '2')


def main() -> int:
    from zyg_workflows import _comfy_client as cc
    from zyg_workflows import comfy_generation_service as cgs
    from zyg_workflows import contact_sheet_pipeline as csp

    char_id = os.environ.get('ZYG_POSE_TEST_CHAR_ID', 'pose_test_3cell_01')
    params = {
        'name': 'Pose Test',
        'gender': 'female',
        'hair_color': 'auburn',
        'eye_color': 'green',
        'skin_tone': 'medium',
        'style': 'photorealistic',
    }
    angles = csp.CONTACT_SHEET_ANGLE_LABELS[:3]
    cell_w = csp.EXPORT_CELL_W
    cell_h = csp.EXPORT_CELL_H
    tdir = os.path.join(csp.contact_sheet_dir(char_id), 'cells')
    os.makedirs(tdir, exist_ok=True)

    if not cc.server_reachable():
        print('ERROR: ComfyUI not on :8188')
        return 1
    cc.interrupt_execution()
    cc.free_vram()

    pkg = csp._build_sheet_character_package(char_id, params, 'flux', log_fn=print)
    gen_pkg = dict(pkg) if pkg else {}
    gen_pkg.setdefault('conditioning', {})['hand_detail_pass'] = False
    gen_pkg['conditioning']['instantid_enabled'] = False
    trigger = csp.trigger_token_for(char_id)
    style = csp.caption_style_description('photorealistic')
    steps = int(os.environ.get('ZYG_CONTACT_SHEET_STEPS', '16'))
    cfg = float(os.environ.get('ZYG_CONTACT_SHEET_CFG', '3.5'))
    seed = 1828284620  # prior successful run
    unet = 'flux1-dev.safetensors'
    neg = 'blurry, low quality, deformed face, bad anatomy, duplicate panels'

    ipa_ref = os.path.join(tdir, 'cell_00.png')
    if not os.path.isfile(ipa_ref) or os.path.getsize(ipa_ref) < 5000:
        print('Generating cell 00 (anchor)…')
        scene = f'{angles[0]}, character reference portrait, {style}, {trigger}'
        prompt = cgs.build_locked_prompt(scene, pkg, studio_preview=True)
        ok, be = cgs.generate_still(
            ipa_ref,
            prompt,
            width=cell_w,
            height=cell_h,
            steps=steps,
            cfg=cfg,
            seed=seed,
            character_package=gen_pkg,
            force_workflow='flux_txt2img',
            force_unet=unet,
            skip_qa=True,
            studio_preview=True,
            flux_guidance=cfg,
            extra_negative=neg,
            log_fn=print,
        )
        if not ok:
            print(f'cell_00 failed: {be}')
            return 1
        print(f'cell_00 OK ({be})')
    else:
        print(f'Reusing cell_00 ({os.path.getsize(ipa_ref) // 1024} KB)')

    cell_paths = []
    for idx in range(3):
        path = os.path.join(tdir, f'cell_{idx:02d}.png')
        if os.path.isfile(path) and os.path.getsize(path) > 5000:
            print(f'Reusing cell_{idx:02d}')
            cell_paths.append(path)
            continue
        scene = (
            f'{angles[idx]}, exact same person and outfit as reference, '
            f'character reference portrait, neutral studio background, {style}, {trigger}'
        )
        prompt = cgs.build_locked_prompt(scene, pkg, studio_preview=True)
        pose = cgs.pose_map_path(idx)
        kwargs = dict(
            width=cell_w,
            height=cell_h,
            steps=steps,
            cfg=cfg,
            seed=seed,
            character_package=gen_pkg,
            skip_qa=True,
            studio_preview=True,
            flux_guidance=cfg,
            extra_negative=neg,
            log_fn=print,
            force_unet=unet,
        )
        if idx == 0:
            kwargs['force_workflow'] = 'flux_txt2img'
        else:
            kwargs['reference_image'] = ipa_ref
            kwargs['pose_image'] = pose
            kwargs['force_workflow'] = 'flux_pose_ipa_cell'
        print(f'Generating cell_{idx:02d}…')
        ok, be = cgs.generate_still(path, prompt, **kwargs)
        cc.free_vram()
        if not ok:
            print(f'cell_{idx:02d} failed: {be}')
            return 1
        cell_paths.append(path)
        print(f'cell_{idx:02d} OK ({be})')

    out = csp.master_sheet_path(char_id)
    csp._stitch_cell_images(
        cell_paths,
        out,
        1,
        3,
        cell_w,
        cell_h,
        csp.DEFAULT_GUTTER,
        print,
    )
    csp.write_manifest(
        char_id,
        rows=1,
        cols=3,
        gutter=csp.DEFAULT_GUTTER,
        cell_w=cell_w,
        cell_h=cell_h,
        sheet_path=out,
        extra={
            'generation_mode': 'pose_locked_ipa_openpose',
            'total_tiles': 3,
            'cell_paths': cell_paths,
            'sheet_seed': seed,
        },
    )
    print(f'OK — preview: {out}')
    print(f'    cells: {[os.path.basename(p) for p in cell_paths]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
