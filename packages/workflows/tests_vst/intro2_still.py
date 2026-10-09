#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Take 2 start still: eagle-free POV desert + sand-coloured tornado bake.

Stages (run in order, each cached on disk):
    gen    -- Qwen-Image-2512 candidates for the seed list
    judge  -- VLM bird gate + horizon row + lower-half Laplacian -> still_v2.png
    bake   -- sand-tinted tornado elements into still_v2_tornadoes.png + gates

Run from $ZYG_CREWS_ROOT with the crews venv.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from zyg_workflows.paths import ZYG_CREWS_ROOT

CREWS = str(ZYG_CREWS_ROOT)
#: The VFX element frames rendered beside the crews tree; $ZYG_VFX_ELEMENTS overrides it.
VFX_ELEMENTS = os.environ.get('ZYG_VFX_ELEMENTS') or str(ZYG_CREWS_ROOT.parents[1] / 'output' / 'vfx_elements')
OUT = os.path.join(CREWS, 'output/video_studio/intro_zygomatic_ai_v2')
CAND = os.path.join(OUT, 'candidates')
STILL = os.path.join(OUT, 'still_v2.png')
BAKED = os.path.join(OUT, 'still_v2_tornadoes.png')
RECEIPT = os.path.join(OUT, 'still_v2_receipt.json')
CROP = os.path.join(OUT, 'bake_v2_crop.png')

W, H = 1280, 720
SEEDS = [101, 202, 303, 404]

PROMPT = (
    'Point-of-view shot from a camera flying high over a vast empty desert at '
    'golden hour, endless rippled golden sand dunes stretching to a hazy far '
    'horizon placed in the upper middle of the frame, fine sand streaming low '
    'across the dunes in the wind, warm low sun from the left, long soft '
    'shadows, clear empty sky, nothing in the foreground, ultra-detailed, '
    'photoreal, cinematic, 24mm wide angle'
)
NEG = (
    'eagle, bird, wings, feathers, beak, animal, creature, person, '
    'silhouette, foreground object, tornado, dust devil, smoke, fire, '
    'text, watermark, buildings, roads, vehicles'
)

Q_BIRD = 'Is any bird, eagle, wing, feather, beak, animal, person or foreground object visible anywhere in the picture?'
Q_SMOKE = 'Do any dark grey or black smoke plumes appear in the picture?'
PREAMBLE = (
    'You are inspecting a single rendered frame. Answer the question '
    'with yes or no about what is actually visible in the picture, '
    'then give a short reason.'
)

ELEMS = [f'{VFX_ELEMENTS}/tornadoloopingvdb_4k/f_{n}.png' for n in ('0020', '0064', '0108')]
HEIGHTS = [0.06, 0.085, 0.07]
XS = [0.60, 0.67, 0.74]

VLM_MIN_FREE_MIB = 12000.0


def log(msg):
    print(msg, flush=True)


# ── gates ──────────────────────────────────────────────────────────────────
def _gpu_free_mib() -> float:
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader'],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return float(re.findall(r'[\d.]+', r.stdout.strip().splitlines()[0])[0])
    except Exception:  # noqa: BLE001
        return 0.0


def vlm_answer(paths, question, qid):
    """Literal 'yes'/'no' from the local judge, or '' when it cannot run."""
    from zyg_workflows import vlm_inspector as vi

    if not vi.available():
        log('vlm unavailable')
        return '', ''
    free = _gpu_free_mib()
    tier, offload = ('resident', False) if free >= VLM_MIN_FREE_MIB else ('boundary', True)
    log(f'vlm: {free:.0f} MiB free -> tier={tier} offload={offload}')
    res = vi.inspect_frames(
        list(paths),
        items=[{'id': qid, 'question': question, 'expected': 'no', 'severity': 'major', 'frames': 'all'}],
        preamble=PREAMBLE,
        tier=tier,
        offload=offload,
        frame_kind='all',
        log_fn=lambda m: log(str(m)[:200]),
    )
    if not res or res.get('skipped'):
        log(f'vlm skipped ({(res or {}).get("reason")})')
        return '', ''
    v = (res.get('verdicts') or [None])[0] or {}
    ans = str(v.get('answer') or '').strip().lower()
    reason = str(v.get('reason') or '')[:300]
    log(f'vlm {qid}: answer={ans!r} reason={reason[:160]!r}')
    return ans, reason


def horizon_row(img_bgr):
    """Steepest smoothed row-gradient of mean luminance, rows 0.30H..0.60H.

    Mean is taken over the middle 60 percent of the columns only, so dunes at
    the frame edges cannot drag the horizon off its true row."""
    h, w = img_bgr.shape[:2]
    lum = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float64) / 255.0
    c0, c1 = int(0.20 * w), int(0.80 * w)
    rows = lum[:, c0:c1].mean(axis=1)
    k = 9
    pad = np.pad(rows, (k // 2, k // 2), mode='edge')
    smooth = np.convolve(pad, np.ones(k) / k, mode='valid')
    grad = np.abs(np.gradient(smooth))
    lo, hi = int(0.30 * h), int(0.60 * h)
    band = grad[lo:hi]
    if not band.size or float(band.max()) <= 0.0:
        return None
    return int(lo + int(np.argmax(band)))


def lower_laplacian(img_bgr):
    h = img_bgr.shape[0]
    g = cv2.cvtColor(img_bgr[h // 2 :], cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


# ── stages ─────────────────────────────────────────────────────────────────
def stage_gen():
    os.makedirs(CAND, exist_ok=True)
    # generate_still() refuses with (False,'unavailable') unless ComfyUI is the
    # declared primary backend; setdefault so an operator who turned it off wins
    os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    from zyg_workflows import comfy_generation_service as cgs

    for s in SEEDS:
        p = os.path.join(CAND, f'cand_{s}.png')
        if os.path.exists(p):
            log(f'seed {s}: cached')
            continue
        log(f'seed {s}: generating')
        ok, backend = cgs.generate_still(
            p,
            PROMPT,
            width=W,
            height=H,
            steps=20,
            cfg=3.5,
            seed=s,
            model_family='qwen',
            skip_qa=True,
            prompt_finalized=True,
            solo_subject=False,
            human_subject=False,
            extra_negative=NEG,
        )
        log(f'seed {s}: ok={ok} backend={backend}')
        if not ok:
            raise SystemExit(f'generate_still failed for seed {s}: {backend}')


def stage_judge():
    paths = [os.path.join(CAND, f'cand_{s}.png') for s in SEEDS]
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        raise SystemExit('no candidates; run gen first')
    cands = []
    for p in paths:
        seed = int(re.findall(r'cand_(\d+)', p)[0])
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        ans, reason = vlm_answer([p], Q_BIRD, 'bird_free')
        row = horizon_row(img)
        lap = lower_laplacian(img)
        cands.append(
            {
                'seed': seed,
                'vlm_bird': ans or 'unavailable',
                'vlm_reason': reason,
                'horizon_row': row,
                'laplacian': round(lap, 3),
                'path': p,
            }
        )
        log(f'seed {seed}: bird={ans} horizon={row} lap={lap:.1f}')
    passing = [c for c in cands if str(c['vlm_bird']).lower().startswith('no') and c['horizon_row'] is not None]
    if not passing:
        raise SystemExit('no candidate passed the bird + horizon gates')
    best = max(passing, key=lambda c: c['laplacian'])
    log(f'chosen seed {best["seed"]} (lap {best["laplacian"]})')
    Image.open(best['path']).convert('RGB').save(STILL)
    json.dump(
        {'chosen_seed': best['seed'], 'candidates': cands, 'horizon_row': best['horizon_row'], 'still': STILL},
        open(os.path.join(OUT, '_judge.json'), 'w'),
        indent=2,
    )
    return best


# ── bake ───────────────────────────────────────────────────────────────────
def prep_element(path, target_h, lift=1.0):
    """Crop to the alpha bbox, scale to target_h, tint sand, soften.

    ``lift`` is a uniform gain applied after the prescribed desaturate/tint/
    contrast chain. The vendor element is a cool, fairly dark grey plume and the
    (0.96, 0.78, 0.55) sand multiply darkens it further, so against this
    blown-out golden-hour sky the placed columns land just under the 0.75
    luminance gate. The gain preserves the R > G > B ordering the tint
    established; stage_bake solves for the smallest value that passes."""
    im = Image.open(path).convert('RGBA')
    bbox = im.split()[3].getbbox()
    if bbox:
        im = im.crop(bbox)
    scale = target_h / float(im.height)
    im = im.resize((max(1, int(round(im.width * scale))), int(target_h)), Image.LANCZOS)
    a = np.asarray(im, dtype=np.float64) / 255.0
    rgb, alpha = a[..., :3], a[..., 3]
    # 1. desaturate 45 percent
    lum = (rgb * np.array([0.2126, 0.7152, 0.0722])).sum(axis=2, keepdims=True)
    rgb = rgb * 0.55 + lum * 0.45
    # 2. sand tint, not grey
    rgb = rgb * np.array([0.96, 0.78, 0.55])
    # 3. contrast 0.8 around the element's own (alpha-weighted) mean
    wsum = float(alpha.sum()) or 1.0
    mean = float((rgb.mean(axis=2) * alpha).sum() / wsum)
    rgb = np.clip(mean + (rgb - mean) * 0.8, 0.0, 1.0)
    # 3b. sand lift (see docstring)
    rgb = np.clip(rgb * float(lift), 0.0, 1.0)
    # 4. alpha x0.65
    alpha = np.clip(alpha * 0.65, 0.0, 1.0)
    out = Image.fromarray((np.dstack([rgb, alpha]) * 255.0).round().astype(np.uint8), 'RGBA')
    # 5. soften
    return out.filter(ImageFilter.GaussianBlur(1.0))


def compose(base, hz, lift):
    """Composite the three elements at one lift; return (image, boxes)."""
    base_y = int(round(hz + 0.01 * H))  # base 1 percent of H below
    canvas = base.convert('RGBA')
    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    boxes, prepped = [], []
    for path, hf, xf in zip(ELEMS, HEIGHTS, XS):
        el = prep_element(path, hf * H, lift=lift)
        prepped.append(el)
        cx = int(round(xf * W))
        ew, eh = el.size
        x0, y0 = cx - ew // 2, base_y - eh
        boxes.append([x0, y0, x0 + ew, y0 + eh])
        rw, rh = 1.6 * ew, 0.012 * H
        sd.ellipse(
            [cx - rw / 2, base_y - rh / 2, cx + rw / 2, base_y + rh / 2], fill=(214, 178, 128, 51)
        )  # sand, alpha 0.2
    # faint sand ellipses first, so the tornado bases sit on them
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(2.0)))
    for el, (x0, y0, _x1, _y1) in zip(prepped, boxes):
        canvas.alpha_composite(el, (x0, y0))
    return canvas.convert('RGB'), boxes, base_y


def measure(out, boxes, hz):
    """Per-box mean luminance against the sky band just above the horizon."""
    arr = np.asarray(out, dtype=np.float64) / 255.0
    lumf = (arr * np.array([0.2126, 0.7152, 0.0722])).sum(axis=2)
    sky0 = max(0, hz - int(0.06 * H))
    sky_lum = float(lumf[sky0:hz, :].mean())
    rows = []
    for path, (x0, y0, x1, y1) in zip(ELEMS, boxes):
        xs0, ys0 = max(0, x0), max(0, y0)
        xs1, ys1 = min(W, x1), min(H, y1)
        patch = arr[ys0:ys1, xs0:xs1]
        pl = float(lumf[ys0:ys1, xs0:xs1].mean())
        rows.append(
            {
                'element': os.path.basename(path),
                'box': [xs0, ys0, xs1, ys1],
                'lum_ratio': round(pl / sky_lum, 4) if sky_lum else None,
                'rgb_mean': [round(float(patch[..., i].mean()), 4) for i in range(3)],
            }
        )
    return rows


def stage_bake():
    jd = json.load(open(os.path.join(OUT, '_judge.json')))
    base = Image.open(STILL).convert('RGB')
    if base.size != (W, H):
        base = base.resize((W, H), Image.LANCZOS)
    hz = int(jd['horizon_row'])

    lift, out, boxes, bake, base_y = None, None, None, None, None
    for g in [round(1.0 + 0.05 * i, 2) for i in range(13)]:
        out, boxes, base_y = compose(base, hz, g)
        bake = measure(out, boxes, hz)
        ok = all(b['lum_ratio'] >= 0.80 and b['rgb_mean'][0] > b['rgb_mean'][1] > b['rgb_mean'][2] for b in bake)
        log('lift %.2f: ' % g + ' '.join('%.3f' % b['lum_ratio'] for b in bake) + (' PASS' if ok else ''))
        if ok:
            lift = g
            break
    if lift is None:
        raise SystemExit('no sand lift satisfied the luminance gate')

    out.save(BAKED)
    log(f'baked -> {BAKED} horizon={hz} base_y={base_y} lift={lift}')
    for b in bake:
        log(f'{b["element"]}: lum_ratio={b["lum_ratio"]} rgb={b["rgb_mean"]}')
        assert b['lum_ratio'] >= 0.75, f'dark box: {b}'
        r, g_, bl = b['rgb_mean']
        assert r > g_ > bl, f'not sand-coloured: {b}'

    # 3x crop of the horizon band
    cy0, cy1 = max(0, hz - int(0.10 * H)), min(H, base_y + int(0.03 * H))
    cx0, cx1 = int(0.52 * W), int(0.84 * W)
    band = out.crop((cx0, cy0, cx1, cy1))
    band.resize((band.width * 3, band.height * 3), Image.LANCZOS).save(CROP)
    log(f'crop -> {CROP}')

    smoke, smoke_reason = vlm_answer([BAKED], Q_SMOKE, 'smoke_free')
    assert str(smoke).lower().startswith('no'), f'vlm smoke: {smoke!r}'

    cands = [{k: v for k, v in c.items() if k != 'path'} for c in jd['candidates']]
    json.dump(
        {
            'chosen_seed': jd['chosen_seed'],
            'candidates': cands,
            'horizon_row': hz,
            'sand_lift': lift,
            'bake': bake,
            'vlm_smoke': smoke,
            'vlm_smoke_reason': smoke_reason,
            'prompt': PROMPT,
            'negative': NEG,
            'still': STILL,
            'baked': BAKED,
            'crop': CROP,
        },
        open(RECEIPT, 'w'),
        indent=2,
    )
    log(f'receipt -> {RECEIPT}')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    os.chdir(CREWS)
    sys.path.insert(0, CREWS)
    stage = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if stage in ('gen', 'all'):
        stage_gen()
    if stage in ('judge', 'all'):
        stage_judge()
    if stage in ('bake', 'all'):
        stage_bake()
    log('OK')
