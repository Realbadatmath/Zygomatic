# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Render the Medusa drawing as a looping clip with Wan2.2-I2V-A14B.

    /usr/bin/python3 render_medusa_loop.py probe   # 448x496 x 33f — the graph, ~4 min
    /usr/bin/python3 render_medusa_loop.py hero    # 896x992 x 81f — the take, ~45 min

Then compose_medusa_loop.py turns the take into medusa_loop.mp4, which the board
plays while a Medusa workflow is live. Everything outside the mane is composited
back from the drawing afterwards, so this render only has to be right about the
hair — see README_loop.md for the whole pipeline.

Measured on this box: 126 s/step at 896x992x81 (sequence length 76,384), so the
hero take is ~45 min of GPU. Do not start one while the operator is mid-chat: a
Vicky turn loads a 28 GiB brain on top of this and one of the two will OOM.

Decisions that are NOT free choices, each with the reason:

* PAD, NEVER RESCALE. The drawing is 882x986 and the encode node steps by 8, but
  the latent patchify is 2x2 over an 8x downsample, so the real constraint is 16.
  Rescaling 882->832 shifts features by several px against the 39 masks baked at
  882x986, and the composite seam then lands in the wrong place. Padding with
  BORDER_REPLICATE and cropping back at the same offsets is pixel-exact.
* THE SOURCE IS THE PNG, not medusa_base.jpg. The jpg is a q90 re-encode and the
  ringing around every ink stroke is free boil fodder for the model.
* fun_or_fl2v_model = False, declared explicitly. Its INPUT_TYPES default says
  True but the python signature says False, so an omitted key silently picks a
  different conditioning layout. False is also the CORRECT one here: with True
  the decode keeps the pinned end frame, which is our start frame — an exact
  duplicate of frame 0 and a guaranteed one-frame stutter on every loop. With
  False the wrapper drops it and the clip ends one frame before it repeats.
* NO Lightning LoRA. Measured on this box (2026-09-06): the 4-step LoRA held the
  subject but panned the camera instead of moving it, and invented new content.
  On line art "invents content" means new snakes and re-drawn strokes.
* shift 5.0, noise_aug 0.0. Shift is this stack's measured motion lever (2.0 =
  frozen, 5.0 = alive); noise augmentation buys motion by buying invention, which
  is the one thing an ink drawing cannot afford.
* timeout_s 5400. _comfy_client defaults to 600 s and INTERRUPTS YOUR OWN JOB
  when it expires; this shape is ~2x the token count the default was tuned on.
"""

import copy
import json
import os
import sys
import time

from zyg_workflows.paths import ZYG_CREWS_ROOT

CREWS = str(ZYG_CREWS_ROOT)
HERE = os.path.dirname(os.path.abspath(__file__))  # kanban_assets/medusa
sys.path.insert(0, CREWS)

import cv2  # noqa: E402  must follow the sys.path.insert above
from zyg_workflows import _comfy_client as comfy  # noqa: E402  must follow the sys.path.insert above

# The lossless original, NOT medusa_base.jpg: the jpg is a q90 re-encode and the
# ringing it leaves around every ink stroke is free boil fodder for the model.
SRC = os.environ.get(
    'MDZ_SRC',
    os.path.expanduser('~/Documents/craiyon_142159_Black_and_white_drawing_of_Medusa_with_celtic_knot_snake_hair.png'),
)

MODES = {  # name: (width, height, frames)
    'probe': (448, 496, 33),
    'motion': (448, 496, 81),  # what the board actually uses — see README_loop.md
    'hero': (896, 992, 81),  # measured NOT to move: kept only as the evidence
}
# end_image pins the last frame back onto the first. It does not close the loop
# on this checkpoint (measured), and pinning both ends is itself a brake on the
# motion in between, so the mode that exists for motion does not use it.
END_IMAGE = os.environ.get('MDZ_END_IMAGE', '1') != '0'
FPS = 17.0
STEPS = 20
CFG = 5.0
SHIFT = 5.0
SEED = 20260923
LOOP_SHIFT = int(os.environ.get('MDZ_LOOP_SHIFT', '6'))  # 0 = no WanVideoLoopArgs

POS = (
    '固定镜头, static shot, fixed camera, locked-off tripod shot. '
    'A black and white pen and ink drawing of Medusa. The snakes in her hair '
    'slither and coil, sliding over one another in slow continuous S-curves, '
    'heads turning and swaying, forked tongues flicking in and out. Her face, '
    'eyes, mouth, shoulders and chest stay completely still and motionless, '
    'carved in stone. Clean crisp black ink linework, fine cross-hatching, '
    'engraving style, flat white paper background, high contrast monochrome.'
)

# Extends the repo's curated locked-camera negative. The Chinese tokens are kept
# untranslated on purpose — this stack measured that translating them weakens
# them — and the usual 'static, frozen, no motion' tokens are deliberately absent:
# on a locked-camera shot those are what make Wan churn the set and push in.
NEG = (
    '色调艳丽, 过曝, 整体发灰, 最差质量, 低质量, JPEG压缩残留, 丑陋的, 残缺的, '
    '畸形的, 形态畸形的肢体, 多余的手指, 手指融合, 杂乱的背景, 镜头移动, 镜头晃动, '
    '推镜, 拉镜, 变焦, 彩色, camera movement, camera pan, camera zoom, dolly, '
    'push in, tracking shot, handheld camera, morphing background, warping, '
    'objects changing, flickering, changing face, changing hairstyle, '
    'different person, photorealistic, photograph, 3d render, color, colour, '
    'painted, blurry, soft focus, motion blur, smudged wobbly lines, '
    'boiling texture, shimmering outlines, melting ink, new lines appearing, '
    'face moving, head turning, blinking, deformed anatomy, extra limbs'
)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'probe'
    W, H, FRAMES = MODES[mode]

    img = cv2.imread(SRC, cv2.IMREAD_COLOR)
    h0, w0 = img.shape[:2]
    if mode == 'hero':
        # 882 -> 896 (+7 each side), 986 -> 992 (+3 each side). No resampling.
        pad = ((H - h0) // 2, H - h0 - (H - h0) // 2, (W - w0) // 2, W - w0 - (W - w0) // 2)
        inp = cv2.copyMakeBorder(img, *pad, cv2.BORDER_REPLICATE)
        meta = {'pad_top': pad[0], 'pad_left': pad[2], 'crop': [w0, h0]}
    else:
        inp = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
        meta = {'pad_top': 0, 'pad_left': 0, 'crop': [W, H]}
    if inp.shape[:2] != (H, W):
        raise AssertionError(inp.shape)
    stage_png = os.path.join(HERE, f'medusa_in_{mode}.png')
    cv2.imwrite(stage_png, inp)

    if not comfy.server_reachable():
        sys.exit('ComfyUI is not answering on 127.0.0.1:8188')

    wf = copy.deepcopy(comfy.load_workflow('wan22_i2v'))
    name = comfy.stage_input_image(stage_png)
    if END_IMAGE:
        wf['11']['inputs']['end_image'] = ['10', 0]  # same frame at both ends

    # end_image alone does NOT close the loop on this checkpoint — measured on the
    # 448x496 probe, the last frame was the FURTHEST from the first (18.7 grey
    # levels, a monotone drift away from the start), which is what the wrapper's
    # own tooltip implies: fun_or_fl2v_model is "for the official FLF2V or Fun
    # model" and Wan2.2-I2V-A14B is neither. WanVideoLoopArgs is the wrapper's
    # real loop: it rolls the latent by shift_skip every step, so the sequence is
    # circular by construction rather than by conditioning.
    if LOOP_SHIFT:
        wf['70'] = {
            'class_type': 'WanVideoLoopArgs',
            'inputs': {'shift_skip': LOOP_SHIFT, 'start_percent': 0.0, 'end_percent': 1.0},
        }
        wf['30']['inputs']['loop_args'] = ['70', 0]
        wf['31']['inputs']['loop_args'] = ['70', 0]
    boundary = STEPS // 2  # HIGH expert first half, LOW second

    ov = {
        # The fp8 T5 would save ~4.7 GB of HOST ram (which is the tight side on
        # this box: swap is full), but the node refuses it — "fp8 scaled is not
        # supported by this node" — so the bf16 encoder stays.
        '2': {'model_name': 'umt5-xxl-enc-bf16.safetensors', 'precision': 'bf16', 'load_device': 'offload_device'},
        '10': {'image': name},
        '11': {
            'width': W,
            'height': H,
            'num_frames': FRAMES,
            'noise_aug_strength': 0.0,
            'start_latent_strength': 1.0,
            'end_latent_strength': 1.0,
            'fun_or_fl2v_model': False,
            'augment_empty_frames': 0.0,
            'tiled_vae': False,
            'force_offload': True,
        },
        '20': {'positive_prompt': POS, 'negative_prompt': NEG},
        '30': {
            'seed': SEED,
            'steps': STEPS,
            'cfg': CFG,
            'shift': SHIFT,
            'scheduler': 'unipc',
            'start_step': 0,
            'end_step': boundary,
            'force_offload': True,
        },
        '31': {
            'seed': SEED,
            'steps': STEPS,
            'cfg': CFG,
            'shift': SHIFT,
            'scheduler': 'unipc',
            'start_step': boundary,
            'end_step': -1,
            'force_offload': True,
        },
        '40': {'enable_vae_tiling': False, 'normalization': 'default'},
        '45': {'fps': FPS},
        '50': {'filename_prefix': f'ZygMedusa{mode.title()}'},
    }

    print(
        f'{mode}: {W}x{H} x {FRAMES}f, {STEPS} steps (boundary {boundary}), cfg {CFG}, shift {SHIFT}, seed {SEED}',
        flush=True,
    )
    t0 = time.time()
    outs = comfy.submit(wf, overrides=ov, timeout_s=5400)
    print('timing:', json.dumps(getattr(comfy, 'last_submit_timing', {})), flush=True)
    if not outs:
        sys.exit('ComfyUI returned no output')
    tag = os.environ.get('MDZ_TAG', '')
    dst = os.path.join(HERE, f'medusa_{mode}{tag}.mp4')
    with open(outs[0], 'rb') as a, open(dst, 'wb') as b:
        b.write(a.read())
    meta.update(
        {
            'src': outs[0],
            'mode': mode,
            'w': W,
            'h': H,
            'frames': FRAMES,
            'fps': FPS,
            'seed': SEED,
            'shift': SHIFT,
            'steps': STEPS,
            'wall_s': round(time.time() - t0, 1),
        }
    )
    meta['loop_shift'] = LOOP_SHIFT
    with open(os.path.join(HERE, f'medusa_{mode}{tag}.json'), 'w') as fh:
        json.dump(meta, fh, indent=1)
    print(f'{dst}  ({meta["wall_s"]:.0f}s wall)', flush=True)

    # ZYG_COMFY_KEEP_LOADED=1 on this box, so the experts would otherwise sit on
    # the card and the next Vicky turn would fail to load her brain.
    try:
        import urllib.request

        req = urllib.request.Request(
            'http://127.0.0.1:8188/free',
            method='POST',
            data=json.dumps({'unload_models': True, 'free_memory': True}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        # noqa below: the URL is the literal loopback http:// above, never caller-supplied,
        # so there is no scheme for an attacker to swap; a Request also rules safe_urlopen out.
        urllib.request.urlopen(req, timeout=30).read()  # nosec B310  # noqa: S310  literal http:// loopback URL
        print('asked ComfyUI to release the models', flush=True)
    except Exception as e:  # noqa: BLE001
        print(f'(could not free ComfyUI models: {e})', flush=True)


if __name__ == '__main__':
    main()
