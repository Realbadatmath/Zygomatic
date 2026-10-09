#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Intro shots driver — Qwen desert still, tornado bake, three Wan2.2 shots.

Session-tree task video-studio-intro-workflow-still-entry--3cfb1e#11.

Runs video_studio IN THIS PROCESS (the render worker is a thread here), so the
live kanban-server never has to be restarted for the per-link prompt work to be
visible.  Stages are separate CLI verbs so one bash call owns one render.

    python tests_vst/intro_shots.py still
    python tests_vst/intro_shots.py bake
    python tests_vst/intro_shots.py shot --k 1 --seed 1001
    python tests_vst/intro_shots.py receipt
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from zyg_workflows.paths import ZYG_CREWS_ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
sys.path.insert(0, CREWS)

# wan_video_service budgets a ComfyUI submit with ZYG_WAN_TIMEOUT_S (default
# 900 s). A 53-frame 1280x720 Wan2.2 clip does not fit in that: seed 1001's
# first attempt was interrupted at exactly 900 s mid-sampler. 2100 s keeps the
# render inside this driver's own 40-minute poll cap.
os.environ.setdefault('ZYG_WAN_TIMEOUT_S', '2100')

OUT = os.path.join(CREWS, 'output', 'video_studio', 'intro_zygomatic_ai')
os.makedirs(OUT, exist_ok=True)

#: The VFX element frames rendered beside the crews tree; $ZYG_VFX_ELEMENTS overrides it.
VFX_ELEMENTS = os.environ.get('ZYG_VFX_ELEMENTS') or str(ZYG_CREWS_ROOT.parents[1] / 'output' / 'vfx_elements')
ELEM_DIR = os.path.join(VFX_ELEMENTS, 'tornadoloopingvdb_4k')
ELEMS = ('f_0020.png', 'f_0064.png', 'f_0108.png')
HEIGHT_FRACS = (0.07, 0.10, 0.085)
X_FRACS = (0.58, 0.66, 0.74)

W, H = 1280, 720
SEEDS_STILL = (11, 23, 47)

PROMPT = (
    'Aerial first-person view from a high-flying eagle over a vast empty '
    'desert at golden hour, endless rippled sand dunes to a hazy far '
    'horizon placed in the upper middle of the frame, fine sand grains '
    'streaming and swirling low across the desert floor in the wind, '
    'warm low sun from the left, long soft shadows, ultra-detailed, '
    'photoreal, cinematic, 24mm wide angle'
)
EXTRA_NEG = 'tornado, people, animals, text, watermark, buildings, roads, vehicles'


# ───────────────────────────────────────────────────────── horizon measurement
def horizon_row(path: str) -> tuple[int, bool]:
    """Row of the horizon: argmax of the smoothed |gradient| of the per-row mean
    luminance over the middle 60 % of columns, searched in 0.30H..0.65H.
    Returns (row, fallback_used)."""
    g = cv2.cvtColor(cv2.imread(path, cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    mid = g[:, int(0.20 * w) : int(0.80 * w)].astype(np.float64)
    prof = mid.mean(axis=1)
    grad = np.abs(np.gradient(prof))
    k = 9
    sm = np.convolve(grad, np.ones(k) / k, mode='same')
    lo, hi = int(0.30 * h), int(0.65 * h)
    band = sm[lo:hi]
    if band.size == 0 or float(band.max()) <= 1e-6:
        return int(0.50 * h), True
    return int(lo + int(np.argmax(band))), False


def sand_detail(path: str) -> float:
    """Laplacian variance of the lower half — how much sand texture survived."""
    g = cv2.cvtColor(cv2.imread(path, cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g[g.shape[0] // 2 :], cv2.CV_64F).var())


# ──────────────────────────────────────────────────────────── STEP 1 — still
def stage_still() -> None:
    os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    from zyg_workflows import comfy_generation_service as cgs

    rows = []
    for seed in SEEDS_STILL:
        out = os.path.join(OUT, f'still_cand_{seed}.png')
        t0 = time.time()
        ok, backend = cgs.generate_still(
            out,
            PROMPT,
            width=W,
            height=H,
            steps=20,
            cfg=3.5,
            seed=seed,
            model_family='qwen',
            skip_qa=True,
            prompt_finalized=True,
            solo_subject=False,
            human_subject=False,
            extra_negative=EXTRA_NEG,
        )
        print(f'seed {seed}: ok={ok} backend={backend} {time.time() - t0:.1f}s', flush=True)
        rec = {
            'seed': seed,
            'ok': bool(ok),
            'backend': str(backend),
            'path': out,
            'seconds': round(time.time() - t0, 1),
        }
        if ok and os.path.isfile(out):
            row, fb = horizon_row(out)
            rec.update(
                horizon_row=row,
                horizon_frac=round(row / H, 4),
                fallback=fb,
                in_range=not fb,
                sand_laplacian_var=round(sand_detail(out), 2),
            )
        rows.append(rec)
        print(json.dumps(rec), flush=True)

    usable = [r for r in rows if r.get('ok') and r.get('in_range')]
    pool = usable or [r for r in rows if r.get('ok')]
    if not pool:
        raise SystemExit('no candidate still was produced')
    best = max(pool, key=lambda r: r.get('sand_laplacian_var', 0.0))
    shutil.copy2(best['path'], os.path.join(OUT, 'still_desert.png'))
    receipt = {
        'prompt': PROMPT,
        'extra_negative': EXTRA_NEG,
        'model_family': 'qwen',
        'width': W,
        'height': H,
        'steps': 20,
        'cfg': 3.5,
        'horizon_rule': (
            'argmax of the smoothed |gradient| of the '
            'per-row mean luminance over the middle 60% of '
            'columns, searched in rows 0.30H..0.65H'
        ),
        'candidates': rows,
        'chosen_seed': best['seed'],
        'chosen_horizon_row': best.get('horizon_row'),
        'chosen_reason': (
            'highest lower-half Laplacian variance among '
            'the candidates whose horizon was found in '
            'the 0.30H..0.65H band'
        ),
        'still': os.path.join(OUT, 'still_desert.png'),
    }
    with open(os.path.join(OUT, 'still_receipt.json'), 'w') as fh:
        json.dump(receipt, fh, indent=1)
    print('CHOSE seed', best['seed'], 'horizon', best.get('horizon_row'), flush=True)


# ─────────────────────────────────────────────────────── STEP 2 — tornado bake
def stage_bake() -> None:
    src = os.path.join(OUT, 'still_desert.png')
    hz, fb = horizon_row(src)
    base = Image.open(src).convert('RGBA')
    w, h = base.size
    bottom = int(round(hz + 0.01 * h))

    dust = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dust)
    placed = []
    sprites = []
    for name, hf, xf in zip(ELEMS, HEIGHT_FRACS, X_FRACS):
        im = Image.open(os.path.join(ELEM_DIR, name)).convert('RGBA')
        src_w, src_h = im.size
        th = max(1, int(round(hf * h)))
        tw = max(1, int(round(th * src_w / src_h)))
        im = im.resize((tw, th), Image.LANCZOS)
        a = np.asarray(im).astype(np.float32)
        a[:, :, 0] *= 1.0
        a[:, :, 1] *= 0.92
        a[:, :, 2] *= 0.78
        a[:, :, 3] *= 0.85
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), 'RGBA')
        im = im.filter(ImageFilter.GaussianBlur(1.2))
        cx = int(round(xf * w))
        left, top = cx - tw // 2, bottom - th
        # ground dust goes UNDER the tornado, so it is drawn on its own layer
        ew, eh = 1.6 * tw, 0.012 * h
        dd.ellipse([cx - ew / 2, bottom - eh / 2, cx + ew / 2, bottom + eh / 2], fill=(214, 190, 150, 64))
        sprites.append((im, left, top))
        placed.append(
            {
                'element': name,
                'height_frac': hf,
                'x_frac': xf,
                'px': {'w': tw, 'h': th, 'left': left, 'top': top, 'bottom': bottom, 'cx': cx},
                'dust_ellipse': {'w': round(ew, 1), 'h': round(eh, 1)},
            }
        )

    out = Image.alpha_composite(base, dust)
    for im, left, top in sprites:
        out.alpha_composite(im, (left, top))
    out_path = os.path.join(OUT, 'still_desert_tornadoes.png')
    out.convert('RGB').save(out_path)

    y0, y1 = max(0, int(hz - 0.12 * h)), min(h, int(hz + 0.05 * h))
    x0, x1 = int(0.50 * w), int(0.82 * w)
    crop = out.convert('RGB').crop((x0, y0, x1, y1))
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    crop.save(os.path.join(OUT, 'bake_crop.png'))

    rec = {
        'still': src,
        'horizon_row': hz,
        'horizon_fallback': fb,
        'tornado_bottom_row': bottom,
        'warm_rgb': [1.0, 0.92, 0.78],
        'alpha_scale': 0.85,
        'blur_px': 1.2,
        'placed': placed,
        'crop_box': [x0, y0, x1, y1],
        'crop_scale': 3,
        'out': out_path,
    }
    with open(os.path.join(OUT, 'bake_receipt.json'), 'w') as fh:
        json.dump(rec, fh, indent=1)
    print(json.dumps(rec, indent=1), flush=True)


# ────────────────────────────────────────────────────────── STEP 3 — the shots
NEG = (
    'static, frozen, still image, text, letters, watermark, logo, people, '
    'animals, birds in frame, buildings, roads, vehicles, blurry, '
    'low quality'
)

SHOTS = {
    1: dict(
        frames=53,
        scene_prompt=(
            'First-person aerial view from a flying eagle, flying '
            'fast and straight ahead over a vast golden desert '
            'toward three distant dust tornadoes on the horizon; the '
            'camera pushes forward steadily, the dust devils spin '
            'and slowly grow closer, fine sand grains stream and '
            'swirl low across the desert floor below, warm golden '
            'light, hazy horizon, smooth gliding flight, photoreal'
        ),
        camera_move='slow push in',
        camera_speed='a fast aggressive camera move',
        camera_height="a bird's-eye view far above",
    ),
    2: dict(
        frames=45,
        scene_prompt=(
            'First-person aerial view from a flying eagle: the eagle '
            'banks and turns to the left, the camera pans left '
            'smoothly and steadily so the tornadoes slide out of the '
            'frame on the right, revealing empty rolling dunes, sand '
            'grains streaming across the desert floor, warm golden '
            'light, photoreal'
        ),
        camera_move='slow pan left',
        camera_speed='a steady camera move',
        camera_height="a bird's-eye view far above",
    ),
    3: dict(
        frames=45,
        scene_prompt=(
            'First-person aerial view from a flying eagle: the eagle '
            'dives steeply toward the desert floor, the camera tilts '
            'down and rushes downward fast, the sand rushes up to '
            'fill the frame, the dive slows as the ground comes '
            'close and the view settles at a low hovering angle over '
            'the rippled sand, fine grains blowing across the ground '
            'in sharp detail, warm golden light, photoreal'
        ),
        camera_move='slow tilt down',
        camera_speed='a fast aggressive camera move',
        camera_height='auto',
    ),
}


def params_for(k: int, seed: int) -> dict:
    from zyg_workflows import video_studio as vs

    p = dict(vs.defaults())
    p.update(
        pathway='wan22',
        resolution='1280x720',
        duration_s='1.7',
        fps=17,
        steps=20,
        guidance=5.0,
        seed_mode='fixed',
        variants=1,
        retries=0,
        motion_gate=True,
        black_gate=True,
        freeze_gate=True,
        prompt_mode='auto',
        negative_prompt=NEG,
        camera_rig='aerial drone shot',
        lens='shot on a 24mm wide lens',
        motion_amount='dynamic',
        weather='in a dust-filled haze',
        save_params=True,
        save_graph=True,
        keep_subclips=True,
        color_match=False,
        seed=seed,
    )
    p.update(SHOTS[k])
    if k > 1:
        p['start_from'] = 'last'
    return p


def frames_of(path: str) -> tuple[np.ndarray, np.ndarray, int]:
    cap = cv2.VideoCapture(path)
    got = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        got.append(fr)
    cap.release()
    if len(got) < 2:
        raise RuntimeError(f'{path}: only {len(got)} frame(s)')
    return got[0], got[-1], len(got)


def _grey320(fr: np.ndarray) -> np.ndarray:
    hh = max(1, int(round(fr.shape[0] * 320 / fr.shape[1])))
    return cv2.cvtColor(cv2.resize(fr, (320, hh)), cv2.COLOR_BGR2GRAY)


def geometry(path: str) -> dict:
    """(s, tx, ty) of frame 0 → last frame, translation as a fraction of W/H."""
    f0, fl, n = frames_of(path)
    a, b = _grey320(f0), _grey320(fl)
    gh, gw = a.shape
    method = 'orb+estimateAffinePartial2D'
    M = None
    orb = cv2.ORB_create(nfeatures=4000)
    k1, d1 = orb.detectAndCompute(a, None)
    k2, d2 = orb.detectAndCompute(b, None)
    nmatch = 0
    if d1 is not None and d2 is not None and len(k1) >= 8 and len(k2) >= 8:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        m = sorted(bf.match(d1, d2), key=lambda x: x.distance)[:400]
        nmatch = len(m)
        if len(m) >= 8:
            src = np.float32([k1[x.queryIdx].pt for x in m]).reshape(-1, 1, 2)
            dst = np.float32([k2[x.trainIdx].pt for x in m]).reshape(-1, 1, 2)
            M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if M is None:
        method = 'ecc MOTION_AFFINE'
        warp = np.eye(2, 3, dtype=np.float32)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
        cv2.findTransformECC(
            a.astype(np.float32) / 255.0, b.astype(np.float32) / 255.0, warp, cv2.MOTION_AFFINE, crit, None, 5
        )
        M = warp
    s = float(math.sqrt(max(1e-12, abs(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]))))
    return {
        's': round(s, 4),
        'tx': round(float(M[0, 2]) / gw, 4),
        'ty': round(float(M[1, 2]) / gh, 4),
        'method': method,
        'matches': nmatch,
        'n_frames': n,
    }


def geometry_chained(path: str) -> dict:
    """The same partial affine, but ACCUMULATED frame to frame.

    The brief's gate compares frame 0 with the last frame only. That is sound
    for a pan, where the two frames still overlap, and blind for a dive: shot 3
    ends on close rippled sand that shares no feature with its opening vista,
    so the endpoint fit is drawn from ~30 matches and comes out with the wrong
    sign. Chaining the per-pair fits keeps every pair inside its overlap, so it
    measures the move the camera actually made. Reported alongside the gate,
    never instead of it."""
    cap = cv2.VideoCapture(path)
    fr = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        fr.append(_grey320(f))
    cap.release()
    orb = cv2.ORB_create(nfeatures=4000)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    gh, gw = fr[0].shape
    s, tx, ty, used = 1.0, 0.0, 0.0, 0
    for a, b in zip(fr[:-1], fr[1:]):
        k1, d1 = orb.detectAndCompute(a, None)
        k2, d2 = orb.detectAndCompute(b, None)
        if d1 is None or d2 is None:
            continue
        m = sorted(bf.match(d1, d2), key=lambda x: x.distance)[:400]
        if len(m) < 8:
            continue
        p1 = np.float32([k1[x.queryIdx].pt for x in m]).reshape(-1, 1, 2)
        p2 = np.float32([k2[x.trainIdx].pt for x in m]).reshape(-1, 1, 2)
        M, _ = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if M is None:
            continue
        used += 1
        s *= math.sqrt(max(1e-12, abs(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0])))
        tx += float(M[0, 2]) / gw
        ty += float(M[1, 2]) / gh
    return {'s': round(s, 4), 'tx': round(tx, 4), 'ty': round(ty, 4), 'pairs_used': used, 'pairs': len(fr) - 1}


def geom_pass(k: int, g: dict) -> bool:
    if k == 1:
        return g['s'] >= 1.06 and abs(g['tx']) <= 0.08
    if k == 2:
        return g['tx'] >= 0.12
    return g['ty'] <= -0.10 and g['s'] >= 1.05


def contact_sheet(path: str, out_jpg: str) -> str:
    cap = cv2.VideoCapture(path)
    got = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        got.append(fr)
    cap.release()
    idx = [int(round(i * (len(got) - 1) / 4)) for i in range(5)]
    tiles = [cv2.resize(got[i], (320, 180)) for i in idx]
    cv2.imwrite(out_jpg, np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out_jpg


def _run(k: int, seed: int, src: str) -> dict:
    from zyg_workflows import video_studio as vs

    p = params_for(k, seed)
    if k == 1:
        j = vs.start_render('still', f'intro shot1 seed {seed}', src, p)
    else:
        j = vs.start_render_from_video(f'intro-s{k - 1}', f'intro shot{k} seed {seed}', src, p)
    jid = j['id']
    print(f'shot{k} seed{seed} jid={jid}', flush=True)
    t0 = time.time()
    seen = 0
    while True:
        st = vs.job(jid)
        log = st.get('log', [])
        for line in log[seen:]:
            print('  |', line, flush=True)
        seen = len(log)
        if st.get('state') in ('done', 'error'):
            break
        if time.time() - t0 > 2400:
            raise SystemExit(f'shot{k} seed{seed}: 40 min cap hit')
        time.sleep(30)
    st = vs.job(jid)
    rec = {
        'k': k,
        'jid': jid,
        'seed': seed,
        'state': st['state'],
        'error': st.get('error', ''),
        'wall_s': round(time.time() - t0, 1),
        'log': list(st.get('log', [])),
    }
    if st['state'] == 'done' and st.get('urls'):
        rel = st['urls'][0].split('path=', 1)[1]
        rec['path'] = os.path.join(CREWS, 'output', rel[4:] if rel.startswith('out/') else rel)
        rec['geometry'] = geometry(rec['path'])
        rec['geom_pass'] = geom_pass(k, rec['geometry'])
        rec['sheet'] = contact_sheet(rec['path'], os.path.join(OUT, f'sheet_shot{k}_seed{seed}.jpg'))
    with open(os.path.join(OUT, f'attempt_shot{k}_seed{seed}.json'), 'w') as fh:
        json.dump(rec, fh, indent=1)
    print('RESULT', json.dumps({x: rec[x] for x in rec if x != 'log'}), flush=True)
    return rec


def stage_shot(k: int, seed: int) -> None:
    if k == 1:
        src = os.path.join(OUT, 'still_desert_tornadoes.png')
    else:
        src = os.path.join(OUT, f'shot{k - 1}.mp4')
    if not os.path.isfile(src):
        raise SystemExit(f'source missing: {src}')
    rec = _run(k, seed, src)
    if rec.get('state') == 'done' and rec.get('geom_pass'):
        shutil.copy2(rec['path'], os.path.join(OUT, f'shot{k}.mp4'))
        print(f'ACCEPTED shot{k} seed {seed}', flush=True)
    else:
        print(f'REJECTED shot{k} seed {seed}', flush=True)


def stage_accept(k: int, seed: int) -> None:
    """Take a candidate that passed the worker gates but not the geometry gate
    as the best-of — used only when no seed passes, and recorded as such."""
    rec = json.load(open(os.path.join(OUT, f'attempt_shot{k}_seed{seed}.json')))
    shutil.copy2(rec['path'], os.path.join(OUT, f'shot{k}.mp4'))
    print(f'FORCED shot{k} seed {seed}', flush=True)


# ─────────────────────────────────────────────────────────────────── receipt
def stage_receipt(chosen: list[str]) -> None:
    still = json.load(open(os.path.join(OUT, 'still_receipt.json')))
    bake = json.load(open(os.path.join(OUT, 'bake_receipt.json')))
    shots = []
    for spec in chosen:
        k, seed = (int(x) for x in spec.split(':'))
        rec = json.load(open(os.path.join(OUT, f'attempt_shot{k}_seed{seed}.json')))
        log = rec.get('log', [])
        pos = next((l.split('positive:', 1)[1].strip() for l in log if 'positive:' in l), '')
        mot = None
        for l in log:
            if 'frozen-clip gate' in l and 'motion' in l:
                try:
                    mot = float(l.split('motion', 1)[1].split(')')[0].replace('<', ' ').split()[0])
                except (ValueError, IndexError):
                    pass
        fr = SHOTS[k]['frames']
        shots.append(
            {
                'k': k,
                'jid': rec['jid'],
                'seed': seed,
                'path': os.path.join(OUT, f'shot{k}.mp4'),
                'render_path': rec.get('path', ''),
                'frames': fr,
                'fps': 17,
                'duration_s': round(fr / 17.0, 3),
                'motion_score': mot,
                'geometry': rec.get('geometry', {}),
                'geometry_chained': geometry_chained(os.path.join(OUT, f'shot{k}.mp4')),
                'passed': bool(rec.get('geom_pass')),
                'seeds_tried': sorted(
                    int(f.split('_seed')[1][:-5]) for f in os.listdir(OUT) if f.startswith(f'attempt_shot{k}_seed')
                ),
                'positive': pos,
                'sheet': rec.get('sheet', ''),
                'gates': [l for l in log if 'gate' in l],
            }
        )
    out = {
        'still': {
            'path': os.path.join(OUT, 'still_desert.png'),
            'baked': bake['out'],
            'chosen_seed': still['chosen_seed'],
            'horizon_row': bake['horizon_row'],
            'candidates': still['candidates'],
            'tornadoes': bake['placed'],
        },
        'shots': shots,
    }
    with open(os.path.join(OUT, 'shots.json'), 'w') as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out, indent=1)[:4000], flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=('still', 'bake', 'shot', 'accept', 'receipt'))
    ap.add_argument('--k', type=int, default=1)
    ap.add_argument('--seed', type=int, default=1001)
    ap.add_argument('--chosen', default='')
    a = ap.parse_args()
    if a.stage == 'still':
        stage_still()
    elif a.stage == 'bake':
        stage_bake()
    elif a.stage == 'shot':
        stage_shot(a.k, a.seed)
    elif a.stage == 'accept':
        stage_accept(a.k, a.seed)
    else:
        stage_receipt([s for s in a.chosen.split(',') if s])


if __name__ == '__main__':
    main()
