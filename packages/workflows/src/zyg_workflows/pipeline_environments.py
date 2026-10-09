# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_environments.py — Environments workflow: generate SCENERY for videos.

Two functions, matching the board's 2D/3D toggle:
  * generate_scenery_2d  — a still-image environment plate (for still pipelines).
  * generate_scenery_3d  — a short camera-move video through the scenery (for video pipelines),
                           by animating the 2D plate through the existing Wan I2V path.

No characters here — pure environment. Characters are composited in separately
(arcane_multichar / the character face-pass) when a scene needs them.
"""

import os
import shutil

_JUG = 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'
_ENV_NEG = (
    'people, person, human, figure, crowd, portrait, text, watermark, signature, '
    'lowres, blurry, jpeg artifacts, deformed, oversaturated'
)


def _log_noop(_m):
    pass


def generate_scenery_2d(scene_desc, out_path, seed=7, W=1344, H=768, arcane=False, log_fn=None):
    """Wide establishing environment still (no characters). Returns out_path or None.

    arcane=True runs a style_arcane + depth restyle pass so the scenery matches an
    arcane-styled cast; otherwise a photoreal cinematic plate.
    """
    log = log_fn or _log_noop
    from zyg_workflows import _comfy_client as CC

    style = (
        'epic cinematic establishing shot, wide landscape, dramatic natural lighting, '
        'volumetric atmosphere, highly detailed, photorealistic, 8k'
    )
    prompt = f'{scene_desc}, {style}'
    g = {
        '10': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': _JUG}},
        '20': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': prompt}},
        '21': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': _ENV_NEG}},
        '40': {'class_type': 'EmptyLatentImage', 'inputs': {'width': W, 'height': H, 'batch_size': 1}},
        '41': {
            'class_type': 'KSampler',
            'inputs': {
                'model': ['10', 0],
                'positive': ['20', 0],
                'negative': ['21', 0],
                'latent_image': ['40', 0],
                'seed': seed,
                'steps': 32,
                'cfg': 6.5,
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
                'denoise': 1.0,
            },
        },
        '42': {'class_type': 'VAEDecode', 'inputs': {'samples': ['41', 0], 'vae': ['10', 2]}},
        '50': {'class_type': 'SaveImage', 'inputs': {'images': ['42', 0], 'filename_prefix': 'ZygEnv2D'}},
    }
    try:
        outs = CC.submit(g, timeout_s=600)
    except Exception as e:
        log(f'[env2d] base render failed: {e}')
        return None
    if not outs:
        return None
    shutil.copy2(outs[0], out_path)
    if arcane:
        try:
            # style-only arcane restyle (reuse the multichar plate restyler)
            from zyg_workflows import arcane_multichar as MC

            MC._arcane_full(out_path, out_path, scene_desc, seed, log)
            log('[env2d] arcane restyle applied')
        except Exception as e:
            log(f'[env2d] arcane restyle skipped ({e})')
    log(f'[env2d] scenery → {out_path}')
    return out_path


def generate_scenery_3d(
    scene_desc,
    out_dir,
    seconds=5,
    camera='slow cinematic dolly move forward',
    arcane=False,
    seed=7,
    test_mode=True,
    log_fn=None,
):
    """Camera-move video through generated scenery. Builds a 2D plate, then animates it via
    the existing Wan I2V path (camera motion, not subject motion). Returns clip path or None.

    test_mode=True → one native ~5s sub-clip (Phase-1 test mode) for fast inspection.
    """
    log = log_fn or _log_noop
    os.makedirs(out_dir, exist_ok=True)
    plate = os.path.join(out_dir, 'env_plate.png')
    if not generate_scenery_2d(scene_desc, plate, seed=seed, arcane=arcane, log_fn=log):
        return None
    try:
        from zyg_workflows import wan_video_service as WAN
    except Exception as e:
        log(f'[env3d] wan import failed: {e}')
        return None
    meta = [
        {
            'prompt': f'{camera} through {scene_desc}. The environment is static; only the camera moves. '
            f'Cinematic, stable, no people appearing.',
            'subject': 'environment',
            'tag': 'scenery',
            'slot_seconds': seconds,
            'index': 0,
            'path': plate,
            'emotion': 'neutral',
            'shot_type': 'wide establishing',
            'seed': seed,
        }
    ]
    # wide shots use higher flow_shift; test_mode → single native ~5s sub-clip
    res = WAN.generate(
        meta,
        out_dir,
        n_clips=1,
        n_chained=1 if test_mode else None,
        frames=81 if test_mode else None,
        steps=12 if test_mode else None,
        flow_shift=3.0,  # wide scenery: enough for a camera move, still stable (no subject warping)
        log_fn=log,
        visual_style='cinematic',
    )
    if not res:
        log('[env3d] wan produced no clip')
        return None
    log(f'[env3d] scenery clip → {res[0].get("path")}')
    return res[0].get('path')
