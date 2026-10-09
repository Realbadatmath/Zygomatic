#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Assemble TAKE 3 of the Zygomatic Ai intro — post only, no new Wan render.

Take 2 shipped a finished programme with three gaps against the operator's
brief, all of them fixable from the clips already on disk:

  1. shot 3 was level flight, then a dissolve — no plunge to the desert floor.
     Here it carries a `dive_zoom` (z 1 -> 2, focus low at 0.78 H, in-out ease,
     motion blur) BEFORE the speed ramp, so the view falls to the ground and
     the ramp brings it to a halt there.
  2. the dust impacts read as small grey puffs.  Here the element is tinted
     sand (0.92/0.70/0.45 colorize), larger (0.15..0.22 H), faster (1.2x) and
     there are six of them ringing the lettering.
  3. the swirl-in was too faint.  Here it runs 2.0 s with `relief_ramp` and the
     words text, so the letters RISE out of the sand out of a condensing haze
     instead of being simply present.

The plate is matched to the dive's own last frame 100 % (per-channel CDF) and
then gain-matched on mean luma, so the dissolve has no exposure jump.

Stages (each cached on disk, run in order)::

    intro3_assemble.py dive      # shot3_fin + dive_zoom + ramp -> shot3_dive.mp4
    intro3_assemble.py plate     # plate_clean matched to the dive -> plate_v3.png
    intro3_assemble.py words     # emboss 'Zygomatic Ai'        -> words_v3.png
    intro3_assemble.py swirl     # relief-ramp reveal           -> title_v3.mp4
    intro3_assemble.py impacts   # 6 tinted dust hits           -> title_v3_fx.mp4
    intro3_assemble.py final     # shot list + audio      -> final_v3_1080p.mp4
    intro3_assemble.py receipt   # checks, sheets         -> receipt_v3.json

Licence: nothing is generated here.  Every pixel comes from take 2's finished
clips (Wan2.2 / RIFE / RealESRGAN, Apache-2.0 or BSD), the dust element is CC0
(JangaFX) and every audio file carries a commercial_ok licence sidecar that
video_audio checks.  No paid API on this path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np
from zyg_workflows.paths import ZYG_CREWS_ROOT

CREWS = str(ZYG_CREWS_ROOT)
V2 = os.path.join(CREWS, 'output/video_studio/intro_zygomatic_ai_v2')
OUT = os.path.join(CREWS, 'output/video_studio/intro_zygomatic_ai_v3')

P = lambda *a: os.path.join(OUT, *a)
Q = lambda *a: os.path.join(V2, *a)

STATE = P('_state_v3.json')

W, H = 1920, 1080
FPS = 24
SIZE = [W, H]
WORDS = 'Zygomatic Ai'

XFADE = 0.18
RAMP_XFADE = 0.5
PLATE_XFADE = 0.04
PLATE_HOLD = 0.6
FADE_IN = 4.0
FADE_OUT = 3.0

DIVE = {'zoom_end': 2.0, 'focus': [0.5, 0.78], 'ease': 'in-out', 'blur': True}
RAMP = {'tail_s': 0.8, 'end_speed': 0.12}
SWIRL_DUR = 2.0
SWIRL_HOLD = 5.0

ELEMENT = os.path.join(CREWS, 'data/asset_libraries/vfx_volumes/grenadedustimpactvdb_4k.mov')
IMPACT_TINT = [0.92, 0.70, 0.45]
IMPACT_HEIGHTS = [0.16, 0.22, 0.19, 0.17, 0.21, 0.15]
IMPACT_STARTS = [0.3, 0.7, 1.1, 1.5, 1.9, 2.3]
IMPACT_ABOVE_FRACS = [0.15, 0.50, 0.85]
IMPACT_BELOW_FRACS = [0.05, 0.45, 0.90]
PUFF_T = 1.6
PUFF_DELTA = 12.0  # luma units a pixel must move to count as puff


def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


def sh(cmd, what='cmd'):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('%s failed rc=%d\n%s' % (what, r.returncode, r.stderr[-2000:]))
    return r.stdout


def probe_dur(path):
    return float(sh(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]).strip())


def _state():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def _save(key, val):
    s = _state()
    s[key] = val
    json.dump(s, open(STATE, 'w'), indent=1, default=str)
    return val


def frame_rgb(video, t, png=None, from_end=False):
    """One frame of `video` as a float32 RGB array."""
    tmp = png or P('_fr_tmp.png')
    if from_end:
        # -update 1 with NO frame limit: every frame from -0.5 s on overwrites the
        # same png, so what survives is the genuine last one.  A -frames:v 1 here
        # would stop at the FIRST frame of that half second -- 12 frames early on a
        # 3 s fade-out, which reads luma 27.6 instead of the true 1.07.
        sh(['ffmpeg', '-y', '-v', 'error', '-sseof', '-0.5', '-i', video, '-update', '1', tmp], 'frame from end')
    else:
        sh(['ffmpeg', '-y', '-v', 'error', '-ss', '%.4f' % t, '-i', video, '-frames:v', '1', tmp], 'frame at %.3f' % t)
    a = cv2.imread(tmp, cv2.IMREAD_COLOR)
    if a is None:
        raise SystemExit('could not read extracted frame %s' % tmp)
    if png is None:
        os.remove(tmp)
    return a[..., ::-1].astype(np.float32)  # BGR -> RGB


def luma(rgb):
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def gray_frames(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit('cv2 cannot open %s' % path)
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
    cap.release()
    if not out:
        raise SystemExit('no frames read from %s' % path)
    return out


def ncc_scale(a, b, lo=1.0, hi=3.0, n=201, width=512, patch_frac=0.5):
    """Scale taking `a` onto `b`, by a normalised-cross-correlation sweep.

    The middle half of `b` is correlated against `a` upscaled by every
    candidate scale; the scale whose best match scores highest wins.  Unlike
    ORB this needs no keypoints, which is the whole point: the dive's frames
    are motion-blurred sand and ORB finds nothing on them (`orb_scale` returns
    None on this pair at 320, 480, 640 and 960 px).  Returns (scale, ncc).
    """
    sc = float(width) / float(a.shape[1])
    A_ = cv2.resize(a, (width, int(round(a.shape[0] * sc))), interpolation=cv2.INTER_AREA).astype(np.float32)
    B_ = cv2.resize(b, (width, int(round(b.shape[0] * sc))), interpolation=cv2.INTER_AREA).astype(np.float32)
    bh, bw = B_.shape
    ph, pw = int(bh * patch_frac), int(bw * patch_frac)
    patch = B_[(bh - ph) // 2 : (bh - ph) // 2 + ph, (bw - pw) // 2 : (bw - pw) // 2 + pw]
    patch = ((patch - patch.mean()) / (patch.std() + 1e-6)).astype(np.float32)
    best = (-9.0, None)
    for s in np.linspace(lo, hi, n):
        aw, ah = int(round(bw * s)), int(round(bh * s))
        if aw < pw or ah < ph:
            continue
        ai = cv2.resize(A_, (aw, ah), interpolation=cv2.INTER_CUBIC)
        v = float(cv2.matchTemplate(ai, patch, cv2.TM_CCOEFF_NORMED).max())
        if v > best[0]:
            best = (v, float(s))
    return best[1], round(best[0], 4)


def measure_dive_scale():
    """How far the dive really pushes in, measured — not asserted.

    `video_assembly`'s own `s_measured` is ORB between the dive's first and
    last OUTPUT frame, and it comes back None here: blurred sand carries no
    ORB keypoints (checked at 320/480/640/960 px).  Worse, that pair cannot
    isolate the dive even when it matches, because shot 3 is a drone already
    flying forward — its own motion scales the picture 2.45x over the same
    2.7 s, so an endpoint reading is the flight and the dive together.

    So the dive is measured against a CONTROL: the same source frame without
    the dive.  Undived-last -> dived-last is a pure crop-and-resize with no
    source motion in it at all, which is exactly the case the sweep is
    accurate on.  The null test is reported beside it — undived-FIRST ->
    dived-first, where the ease puts z at 1.0 and the answer must be 1.0.
    """
    dived = gray_frames(P('shot3_dive.mp4'))
    plain = gray_frames(Q('shot3_fin.mp4'))
    s_dive, v_dive = ncc_scale(plain[-1], dived[-1])
    s_null, v_null = ncc_scale(plain[0], dived[0])
    s_src, v_src = ncc_scale(plain[0], plain[-1], hi=6.0, n=251)
    s_app, v_app = ncc_scale(dived[0], dived[-1], hi=6.0, n=251)
    rec = {
        's_measured': s_dive,
        's_measured_ncc': v_dive,
        'null_control_s': s_null,
        'null_control_ncc': v_null,
        'source_motion_s': s_src,
        'source_motion_ncc': v_src,
        'apparent_endpoint_s': s_app,
        'apparent_endpoint_ncc': v_app,
        'context_at_sweep_ceiling': bool(s_src >= 5.99 or s_app >= 5.99),
        'context_sweep_hi': 6.0,
        'orb_s_measured': None,
        'method': 'ncc scale sweep, undived last frame -> dived last frame '
        '(video_assembly.orb_scale returns None on this pair)',
    }
    log('dive scale: %s' % json.dumps(rec))
    return rec


# ── stage 1: the dive ──────────────────────────────────────────────────────
def stage_dive():
    """shot 3 plunges, then decelerates to a halt — and its last frame is kept.

    The dive and the ramp both live in `video_assembly`, and the shot list is
    the only way to reach them, so a one-shot title-less list is rendered:
    the dive runs over the whole clip first, then the ramp's slow tail is
    computed from the dived frames.
    """
    from zyg_workflows import video_assembly as A

    src = Q('shot3_fin.mp4')
    if not os.path.exists(src):
        raise SystemExit('missing take 2 input: %s' % src)
    sl = {
        'fps': FPS,
        'size': SIZE,
        'audio': None,
        'shots': [{'path': src, 'dive_zoom': dict(DIVE), 'speed_ramp': dict(RAMP)}],
    }
    rec = A.assemble(sl, P('shot3_dive.mp4'), log=log)
    info = rec['shots'][0].get('dive_zoom') or {}
    log('dive info: %s' % json.dumps(info))
    sh(
        [
            'ffmpeg',
            '-y',
            '-v',
            'error',
            '-sseof',
            '-0.2',
            '-i',
            P('shot3_dive.mp4'),
            '-update',
            '1',
            '-frames:v',
            '1',
            P('end_plate_v3.png'),
        ],
        'end plate extract',
    )
    img = cv2.imread(P('end_plate_v3.png'))
    if img is None or img.shape[:2] != (H, W):
        raise SystemExit('end_plate_v3 bad: %s' % (None if img is None else img.shape,))
    log('end_plate_v3.png %s  dive clip %.3f s' % (img.shape, float(rec['total_s'])))
    scale = measure_dive_scale()
    if float(scale['s_measured']) < 1.6:
        raise SystemExit('dive only pushed in %.3f (< 1.6)' % scale['s_measured'])
    return _save(
        'dive',
        {
            'zoom_end': info.get('zoom_end'),
            's_measured': scale['s_measured'],
            'scale': scale,
            'dive_frames': info.get('frames'),
            'clip_s': float(rec['total_s']),
            'ramp_added_frames': rec['shots'][0]['ramp_added_frames'],
            'opts': dict(DIVE),
            'ramp': dict(RAMP),
        },
    )


# ── stage 2: the plate ─────────────────────────────────────────────────────
def _hist_match_channel(src, ref):
    """Map src's per-channel CDF onto ref's (uint8 LUT)."""
    sh_ = np.bincount(src.ravel(), minlength=256).astype(np.float64)
    rh = np.bincount(ref.ravel(), minlength=256).astype(np.float64)
    scdf = np.cumsum(sh_) / max(1.0, sh_.sum())
    rcdf = np.cumsum(rh) / max(1.0, rh.sum())
    lut = np.searchsorted(rcdf, scdf).clip(0, 255).astype(np.uint8)
    return lut[src]


def stage_plate():
    """The clean plate wearing the dive's own grade — 100 %, then luma-locked.

    Take 2 blended the CDF match 70 % and the title plate ended up brighter
    than the shot it dissolved from, which is the exposure jump the creator
    saw.  Here the match is full, and because a per-channel CDF match is not
    exactly mean-preserving a single gain afterwards pins the mean luma to the
    reference's.
    """
    src = cv2.imread(Q('plate_clean.png'), cv2.IMREAD_COLOR)
    ref = cv2.imread(P('end_plate_v3.png'), cv2.IMREAD_COLOR)
    if src is None or ref is None:
        raise SystemExit('plate match needs plate_clean.png + end_plate_v3.png')
    if src.shape[:2] != (H, W):
        src = cv2.resize(src, (W, H), interpolation=cv2.INTER_LANCZOS4)
    if ref.shape[:2] != (H, W):
        ref = cv2.resize(ref, (W, H), interpolation=cv2.INTER_LANCZOS4)

    matched = np.dstack([_hist_match_channel(src[..., i], ref[..., i]) for i in range(3)]).astype(np.float32)
    lum = lambda bgr: float(luma(bgr[..., ::-1].astype(np.float32)).mean())
    want = lum(ref)
    gain = want / max(lum(matched), 1e-6)
    out = np.clip(matched * gain, 0, 255).astype(np.uint8)
    # clipping at 255 can pull the mean back down on a blown plate: one
    # corrective pass on the unclipped residual, then accept and measure.
    got = lum(out)
    if abs(got - want) > 0.2:
        gain2 = gain * (want / max(got, 1e-6))
        out = np.clip(matched * gain2, 0, 255).astype(np.uint8)
        log('plate: second gain pass %.5f -> %.5f' % (gain, gain2))
        gain = gain2
    cv2.imwrite(P('plate_v3.png'), out)

    rgb = lambda a: [round(float(a[..., i].mean()), 3) for i in (2, 1, 0)]
    rec = {
        'end_plate_rgb': rgb(ref),
        'plate_v3_rgb': rgb(out),
        'plate_clean_rgb': rgb(src),
        'end_plate_luma': round(want, 3),
        'plate_v3_luma': round(lum(out), 3),
        'plate_clean_luma': round(lum(src), 3),
        'luma_delta': round(abs(lum(out) - want), 4),
        'blend': 1.0,
        'gain': round(float(gain), 5),
    }
    log('plate: %s' % json.dumps(rec))
    if rec['luma_delta'] > 6.0:
        raise SystemExit('plate luma delta %.3f > 6' % rec['luma_delta'])
    return _save('plate', rec)


# ── stage 3: the words ─────────────────────────────────────────────────────
def stage_words():
    """Deterministic emboss, read back by the module's own two-reader gate.

    No generative attempt: on take 2's plate Qwen failed all 8 seeds and the
    emboss is what shipped, so the 8 GPU renders are simply not spent again.
    """
    from zyg_workflows import sand_title_fx as S

    rec = S.emboss_words(P('plate_v3.png'), WORDS, P('words_v3.png'), strength=1.0)
    log(
        'words: exact=%s read_by=%s text=%r ocr_full=%r ocr_crop=%r vlm=%r'
        % (
            rec.get('exact'),
            rec.get('read_by'),
            rec.get('ocr_text'),
            rec.get('ocr_full'),
            rec.get('ocr_crop'),
            rec.get('vlm_quote'),
        )
    )
    if not rec.get('exact'):
        raise SystemExit('words gate refused the emboss: %s' % json.dumps(rec, default=str))
    return _save('words', rec)


# ── stage 4: the swirl ─────────────────────────────────────────────────────
def stage_swirl():
    """The relief ramp, 2 s: haze condenses, then the letters rise out of it.

    `words_text` is passed because the ramp path is only taken when the text is
    there to rebuild the letter mask (the module's docstring says so); the
    emboss it rebuilds uses the same seed and height_frac as stage `words`, so
    the hold frames are pixel-identical to words_v3.png.
    """
    from zyg_workflows import sand_title_fx as S

    n = S.swirl_in(
        P('plate_v3.png'),
        P('words_v3.png'),
        P('title_v3.mp4'),
        fps=FPS,
        dur_s=SWIRL_DUR,
        hold_s=SWIRL_HOLD,
        words_text=WORDS,
        relief_ramp=True,
        log=log,
    )
    log('swirl -> title_v3.mp4 %d frames (%.3f s)' % (n, n / float(FPS)))
    # how much of the reveal is visible 40 % of the way in: take 2's defect
    plate = luma(cv2.imread(P('plate_v3.png'))[..., ::-1].astype(np.float32))
    mid = luma(frame_rgb(P('title_v3.mp4'), 0.4 * SWIRL_DUR))
    vis = float(np.abs(mid - plate).mean())
    log('swirl visible at 40%%: mean |diff| = %.3f luma' % vis)
    return _save(
        'swirl', {'frames': int(n), 'dur_s': SWIRL_DUR, 'hold_s': SWIRL_HOLD, 'visible_at_40pct': round(vis, 4)}
    )


# ── stage 5: the impacts ───────────────────────────────────────────────────
def build_record():
    """Six dust hits ringing the lettering, three above and three below."""
    from zyg_workflows import sand_title_fx as S

    mask = S.letters_mask(P('plate_v3.png'), P('words_v3.png'))
    ys, xs = np.nonzero(mask)
    if not len(ys):
        raise SystemExit('no lettering mask for the impact placement')
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bw, bh = float(x1 - x0), float(y1 - y0)
    off = 0.10 * bh
    pts = [(x0 + f * bw, y0 - off) for f in IMPACT_ABOVE_FRACS] + [(x0 + f * bw, y1 + off) for f in IMPACT_BELOW_FRACS]
    layers = []
    for (px, py), hgt, st in zip(pts, IMPACT_HEIGHTS, IMPACT_STARTS):
        layers.append(
            {
                'element': ELEMENT,
                'x': round(px / W, 5),
                'y': round(py / H, 5),
                'anchor': 'bottom-center',
                'height': hgt,
                'start_s': st,
                'loop': False,
                'speed': 1.2,
                'tint': list(IMPACT_TINT),
                'saturation': 1.0,
                'warm': [1.0, 1.0, 1.0],
                'opacity': 0.9,
            }
        )
    log('letters bbox=%s  %d layers' % ([x0, y0, x1, y1], len(layers)))
    return {'layers': layers, 'draft': {'width': 480, 'fps': 12}}, [x0, y0, x1, y1]


def measure_puffs(base_mp4, fx_mp4, boxes, t=PUFF_T):
    """Colour and luma of what the overlay actually put on the sand.

    A pixel counts as puff when it moved more than `PUFF_DELTA` luma between
    the clean title frame and the composited one, inside one of the boxes the
    compositor reports it placed the element in.  `r_minus_b` is that pixel
    set's mean R-B on the composite, in 0..1; `luma_vs_sand` is its mean luma
    minus the mean luma of the lit sand ringing the same boxes on the CLEAN
    frame — negative means the dust is duller than the ground, which is what a
    dust puff does.
    """
    base = frame_rgb(base_mp4, t)
    fx = frame_rgb(fx_mp4, t, png=P('impacts_v3_puff.png'))
    lb, lf = luma(base), luma(fx)
    inbox = np.zeros((H, W), bool)
    ring = np.zeros((H, W), bool)
    for bx, by, bw_, bh_ in boxes:
        x0 = max(0, int(bx))
        y0 = max(0, int(by))
        x1 = min(W, int(bx + bw_))
        y1 = min(H, int(by + bh_))
        if x1 <= x0 or y1 <= y0:
            continue
        inbox[y0:y1, x0:x1] = True
        rx, ry = int(0.25 * (x1 - x0)), int(0.25 * (y1 - y0))
        ring[max(0, y0 - ry) : min(H, y1 + ry), max(0, x0 - rx) : min(W, x1 + rx)] = True
    ring &= ~inbox
    sel = inbox & (np.abs(lf - lb) > PUFF_DELTA)
    n = int(sel.sum())
    if n < 200:
        raise SystemExit('only %d puff pixels at t=%.2f — nothing landed' % (n, t))
    rmb = float((fx[..., 0][sel] - fx[..., 2][sel]).mean())
    out = {
        't_s': t,
        'pixels': n,
        'box_pixels': int(inbox.sum()),
        'r_minus_b': round(rmb / 255.0, 5),
        'r_minus_b_255': round(rmb, 3),
        'puff_luma': round(float(lf[sel].mean()), 3),
        'sand_ring_luma': round(float(lb[ring].mean()), 3),
        'sand_under_puff_luma': round(float(lb[sel].mean()), 3),
        'boxes': [[int(v) for v in b] for b in boxes],
        'delta_luma_threshold': PUFF_DELTA,
        'frame': P('impacts_v3_puff.png'),
    }
    out['luma_vs_sand'] = round(out['puff_luma'] - out['sand_ring_luma'], 3)
    out['luma_vs_sand_under'] = round(out['puff_luma'] - out['sand_under_puff_luma'], 3)
    log('puffs: %s' % json.dumps(out))
    return out


def stage_impacts():
    from zyg_workflows import video_overlay as V

    record, bbox = build_record()
    rec = {'layers': record['layers'], 'draft': record['draft']}

    d = V.composite(P('title_v3.mp4'), rec, P('_impacts_v3_draft.mp4'), draft=True, log=log)
    sh(
        [
            'ffmpeg',
            '-y',
            '-v',
            'error',
            '-ss',
            '%.2f' % PUFF_T,
            '-i',
            P('_impacts_v3_draft.mp4'),
            '-update',
            '1',
            '-frames:v',
            '1',
            '-q:v',
            '2',
            P('impacts_v3_draft.jpg'),
        ],
        'draft puff frame',
    )
    log('draft frame -> impacts_v3_draft.jpg (%s)' % d['out'])

    out = V.composite(P('title_v3.mp4'), rec, P('title_v3_fx.mp4'), draft=False, log=log)
    boxes = [l['placed_px'] for l in out['layers']]
    puffs = measure_puffs(P('title_v3.mp4'), P('title_v3_fx.mp4'), boxes)
    if puffs['r_minus_b'] < 40.0 / 255.0:
        raise SystemExit('puffs not sand-coloured: R-B %.4f < %.4f' % (puffs['r_minus_b'], 40.0 / 255.0))
    if puffs['luma_vs_sand'] >= 0:
        raise SystemExit('puffs brighter than the sand: %+.3f' % puffs['luma_vs_sand'])
    _save('impacts_record', {'record': rec, 'letters_bbox': bbox, 'placed_px': boxes})
    return _save('impacts', puffs)


# ── stage 6: the final ─────────────────────────────────────────────────────
def picture_shots():
    return [
        {'path': Q('shot1_fx.mp4'), 'xfade_s': XFADE},
        {'path': Q('shot2_fx.mp4'), 'xfade_s': XFADE},
        {'path': P('shot3_dive.mp4'), 'xfade_s': RAMP_XFADE},
        {'still': P('plate_v3.png'), 'hold_s': PLATE_HOLD, 'xfade_s': PLATE_XFADE},
        {'path': P('title_v3_fx.mp4')},
    ]


def peak_dbfs(ref, trim_start_s=0.0, dur_s=None):
    """Peak of the segment of `ref` the cue will actually use, in dBFS."""
    from zyg_workflows import video_audio as VA

    path, _meta = VA.resolve_library_file(ref)  # licence sidecar still decides
    cmd = ['ffmpeg', '-v', 'error']
    if trim_start_s:
        cmd += ['-ss', '%.3f' % trim_start_s]
    if dur_s:
        cmd += ['-t', '%.3f' % dur_s]
    cmd += ['-i', path, '-ac', '1', '-ar', '48000', '-f', 'f32le', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    a = np.frombuffer(raw, dtype='<f4')
    if a.size == 0:
        raise SystemExit('no samples read from %s' % ref)
    return 20.0 * float(np.log10(max(abs(a).max(), 1e-9)))


def audio_spec(shot3_at):
    """Take 2's spec verbatim: authored gains over peak-normalised sources."""
    bed_f = 'foley/xyl_ambience_sand_storm.wav'
    e1 = 'sfx/eagle_01_red_tailed_hawk_flying_away.wav'
    e2 = 'sfx/eagle_03_eagle_s.wav'
    wind_f = 'sfx/uh_ambdsgn_heavy_gusts_of_wind.wav'
    norm = {bed_f: peak_dbfs(bed_f), e1: peak_dbfs(e1), e2: peak_dbfs(e2), wind_f: peak_dbfs(wind_f, 20.0, 3.0)}
    log('source peaks dBFS: %s' % {k.split('/')[-1]: round(v, 2) for k, v in norm.items()})
    g = lambda ref, authored: round(authored - norm[ref], 2)
    return {
        'bed': {'file': bed_f, 'gain_db': g(bed_f, -10), 'fade_in_s': 0.5, 'fade_out_s': 3.0, 'loop': True},
        'cues': [
            {'file': e1, 'at_s': 1.0, 'gain_db': g(e1, -3), 'trim_start_s': 0, 'dur_s': None, 'fade_s': 0.05},
            {'file': e2, 'at_s': 3.0, 'gain_db': g(e2, -4), 'trim_start_s': 0, 'dur_s': None, 'fade_s': 0.05},
            {
                'file': wind_f,
                'at_s': round(shot3_at, 3),
                'gain_db': g(wind_f, -14),
                'trim_start_s': 20,
                'dur_s': 3.0,
                'fade_s': 0.5,
            },
        ],
        'duck': None,
        'target_lufs': -14.0,
        'true_peak_db': -1.0,
        '_authored_gains_db': {'bed': -10, 'eagle_1': -3, 'eagle_2': -4, 'wind': -14},
        '_source_peaks_dbfs': {k: round(v, 2) for k, v in norm.items()},
    }


def _band_envelope(wav, band):
    """20 ms RMS envelope of `wav` in dB, restricted to `band` = (lo, hi) Hz."""
    af = []
    if band[0]:
        af.append('highpass=f=%g' % band[0])
    if band[1]:
        af.append('lowpass=f=%g' % band[1])
    raw = subprocess.run(
        [
            'ffmpeg',
            '-v',
            'error',
            '-i',
            wav,
            '-af',
            ','.join(af) or 'anull',
            '-ac',
            '1',
            '-ar',
            '48000',
            '-f',
            'f32le',
            '-',
        ],
        capture_output=True,
    ).stdout
    a = np.frombuffer(raw, dtype='<f4')
    win = 960
    n = a.size // win
    return 20.0 * np.log10(np.sqrt(np.maximum((a[: n * win].reshape(n, win) ** 2).mean(1), 1e-12)))


def bed_relative_onsets(wav, cues, over_db=6.0):
    """Where each cue lands measured against the bed under it (take 2's method)."""
    out = []
    for at, band in cues:
        db = _band_envelope(wav, band)
        n = db.size
        i = int(round(float(at) / 0.02))
        base = db[max(0, i - 55) : max(1, i - 5)]
        floor = float(np.median(base)) if base.size else float(np.median(db))
        floor = max(floor, float(np.median(db)))
        lo, hi = max(0, i - 3), min(n, i + 100)
        seg = db[lo:hi]
        hit = np.nonzero(seg > floor + over_db)[0]
        out.append(
            {
                'onset_s': round((lo + int(hit[0])) * 0.02, 3) if hit.size else None,
                'over_bed_db': round(float(seg.max() - floor), 2),
                'method': 'bed-relative %g-%g Hz, +%g dB over local bed' % (band[0] or 0, band[1] or 24000, over_db),
            }
        )
    return out


def stage_final():
    """Picture first (it yields shot 3's joined_at), then the track, then mux."""
    from zyg_workflows import audio_mix as M
    from zyg_workflows import video_assembly as A
    from zyg_workflows import video_audio as VA

    shots = picture_shots()
    for s in shots:
        src = s.get('path') or s.get('still')
        if not os.path.exists(src):
            raise SystemExit('missing shot source: %s' % src)

    mute = {
        'fps': FPS,
        'size': SIZE,
        'shots': shots,
        'fade_in_s': FADE_IN,
        'fade_out_s': FADE_OUT,
        'fade_color': 'black',
        'audio': None,
    }
    rec = A.assemble(mute, P('_picture_only_v3.mp4'), log=log)
    total = float(rec['total_s'])
    shot3_at = float(rec['shots'][2]['joined_at'])
    log('picture %.3f s, shot3 joined_at=%.3f' % (total, shot3_at))

    spec = audio_spec(shot3_at)
    json.dump(
        {
            'fps': FPS,
            'size': SIZE,
            'shots': shots,
            'fade_in_s': FADE_IN,
            'fade_out_s': FADE_OUT,
            'fade_color': 'black',
            'audio': spec,
        },
        open(P('shotlist_v3.json'), 'w'),
        indent=1,
    )

    wav = P('track_v3.wav')
    arec = VA.build_track(spec, total, wav, log=log)
    log('track built: %s LUFS (%s)' % (arec['lufs'], arec.get('warnings')))
    if abs(float(arec['lufs']) + 14.0) > 0.8:
        res = {}
        ok = M.level_to(wav, target_lufs=-14.0, tp_db=-1.0, log_fn=log, result=res)
        arec['lufs'] = M.measure_lufs(wav)
        arec['level_to'] = dict(res, converged=bool(ok))
        log('level_to: %s -> %s LUFS' % (res.get('input_lufs'), arec['lufs']))
    else:
        arec['level_to'] = None
    bands = [(1800.0, None), (1800.0, None), (None, 800.0)]
    for c, o in zip(arec['cues'], bed_relative_onsets(wav, list(zip([c['at_s'] for c in spec['cues']], bands)))):
        c['measured_onset_s'] = o['onset_s']
        c['onset_over_bed_db'] = o['over_bed_db']
        c['onset_method'] = o['method']
    log('final track %s LUFS, onsets %s' % (arec['lufs'], [c['measured_onset_s'] for c in arec['cues']]))

    if not VA.mux(P('_picture_only_v3.mp4'), wav, P('_muxed_v3.mp4'), log=log):
        raise SystemExit('mux failed')
    sh(
        [
            'ffmpeg',
            '-y',
            '-v',
            'error',
            '-i',
            P('_muxed_v3.mp4'),
            '-c',
            'copy',
            '-movflags',
            '+faststart',
            P('final_v3_1080p.mp4'),
        ],
        'faststart',
    )
    os.remove(P('_muxed_v3.mp4'))
    rec['audio'] = arec
    rec['out'] = P('final_v3_1080p.mp4')
    rec['total_s'] = probe_dur(P('final_v3_1080p.mp4'))
    json.dump(rec, open(P('_assemble_v3.json'), 'w'), indent=1, default=str)
    log('final -> %s  %.3f s' % (rec['out'], rec['total_s']))
    return _save('final', {'total_s': rec['total_s'], 'shot3_at': shot3_at})


# ── stage 7: the receipt ───────────────────────────────────────────────────
def contact_sheet(final, total, path, n=12, cols=4):
    tiles = []
    for i in range(n):
        t = total * (i + 0.5) / float(n)
        f = P('_cs_%02d.png' % i)
        sh(
            [
                'ffmpeg',
                '-y',
                '-v',
                'error',
                '-ss',
                '%.3f' % t,
                '-i',
                final,
                '-frames:v',
                '1',
                '-vf',
                'scale=480:270',
                f,
            ],
            'sheet tile',
        )
        tiles.append(cv2.imread(f))
        os.remove(f)
    rows = [np.hstack(tiles[r * cols : (r + 1) * cols]) for r in range(n // cols)]
    cv2.imwrite(path, np.vstack(rows), [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    log('%s written' % os.path.basename(path))


def dive_strip(final, shot3_at, path):
    tiles = []
    ts = [shot3_at + d for d in (0.3, 1.0, 1.8, 2.5)]
    for i, t in enumerate(ts):
        f = P('_ds_%02d.png' % i)
        sh(
            [
                'ffmpeg',
                '-y',
                '-v',
                'error',
                '-ss',
                '%.3f' % t,
                '-i',
                final,
                '-frames:v',
                '1',
                '-vf',
                'scale=480:270',
                f,
            ],
            'dive tile',
        )
        tiles.append(cv2.imread(f))
        os.remove(f)
    cv2.imwrite(path, np.hstack(tiles), [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    log('%s written (t=%s)' % (os.path.basename(path), [round(t, 3) for t in ts]))
    return [round(t, 3) for t in ts]


def stage_receipt():
    from zyg_workflows import sand_title_fx as S

    st = _state()
    rec = json.load(open(P('_assemble_v3.json')))
    total = float(rec['total_s'])
    final = P('final_v3_1080p.mp4')
    s = rec['shots']
    beats = {}
    for i, name in enumerate(('shot1', 'shot2', 'shot3', 'plate', 'title')):
        a = float(s[i]['joined_at'])
        beats[name] = [round(a, 3), round(a + float(s[i]['dur_out']), 3)]
    title_in = beats['title'][0]
    hold_start = title_in + SWIRL_DUR
    fade_out_start = total - FADE_OUT

    contact_sheet(final, total, P('final_v3_sheet.jpg'))
    strip_ts = dive_strip(final, beats['shot3'][0], P('dive_v3_strip.jpg'))

    hold_end = max(hold_start, fade_out_start - 0.1)
    hold_png = P('hold_last_frame_v3.png')
    sh(['ffmpeg', '-y', '-v', 'error', '-ss', '%.3f' % hold_end, '-i', final, '-frames:v', '1', hold_png], 'hold frame')
    g = S.judge_lettering(hold_png, WORDS, log=log)
    log('hold-frame gate: %s' % json.dumps(g, default=str))
    read = {'ocr_crop': g.get('ocr_crop'), 'ocr_full': g.get('ocr_full'), 'vlm': g.get('vlm_quote')}.get(
        g.get('by')
    ) or g.get('ocr_full')

    # how visible the reveal is 40 % of the way in, measured on the PROGRAMME
    plate_l = luma(cv2.imread(P('plate_v3.png'))[..., ::-1].astype(np.float32))
    mid_l = luma(frame_rgb(final, title_in + 0.4 * SWIRL_DUR))
    vis_prog = float(np.abs(mid_l - plate_l).mean())

    out = {
        'total_s': round(total, 3),
        'beats': {
            'shot1': beats['shot1'],
            'shot2': beats['shot2'],
            'shot3_dive': beats['shot3'],
            'plate_hold': beats['plate'],
            'title_in': round(title_in, 3),
            'hold': [round(hold_start, 3), round(total, 3)],
            'hold_last_unfaded_s': round(hold_end, 3),
            'fade_in': [0.0, FADE_IN],
            'fade_out_start': round(fade_out_start, 3),
            'dive_strip_s': strip_ts,
        },
        'dive': {
            'zoom_end': st['dive']['zoom_end'],
            's_measured': st['dive']['s_measured'],
            'scale_measurement': st['dive']['scale'],
            'focus': DIVE['focus'],
            'ease': DIVE['ease'],
            'blur': DIVE['blur'],
            'dive_frames': st['dive']['dive_frames'],
            'ramp_added_frames': st['dive']['ramp_added_frames'],
            'clip_s': st['dive']['clip_s'],
        },
        'plate_luma_delta': st['plate']['luma_delta'],
        'plate': st['plate'],
        'ocr': {
            'text': read,
            'exact': bool(g['exact']),
            'method': 'sand_title_fx.judge_lettering on %s (by=%s)' % (os.path.basename(hold_png), g.get('by')),
            'ocr_full': g.get('ocr_full'),
            'ocr_crop': g.get('ocr_crop'),
            'conf': g.get('conf'),
            'vlm_quote': g.get('vlm_quote'),
            'frame': hold_png,
            'words_png_exact': bool(st['words']['exact']),
            'words_png_text': st['words']['ocr_text'],
            'words_png_read_by': st['words'].get('read_by'),
            'words_method': st['words']['method'],
        },
        'impacts': {
            'r_minus_b': st['impacts']['r_minus_b'],
            'luma_vs_sand': st['impacts']['luma_vs_sand'],
            'luma_vs_sand_under': st['impacts']['luma_vs_sand_under'],
            'puff_luma': st['impacts']['puff_luma'],
            'sand_ring_luma': st['impacts']['sand_ring_luma'],
            'pixels': st['impacts']['pixels'],
            't_s': st['impacts']['t_s'],
            'tint': list(IMPACT_TINT),
            'heights': IMPACT_HEIGHTS,
            'starts': IMPACT_STARTS,
            'speed': 1.2,
            'opacity': 0.9,
            'element': ELEMENT,
            'letters_bbox': st['impacts_record']['letters_bbox'],
            'placed_px': st['impacts_record']['placed_px'],
            'frame': st['impacts']['frame'],
        },
        'swirl_visible_at_40pct': st['swirl']['visible_at_40pct'],
        'swirl': {
            'dur_s': SWIRL_DUR,
            'hold_s': SWIRL_HOLD,
            'relief_ramp': True,
            'frames': st['swirl']['frames'],
            'visible_at_40pct_title_clip': st['swirl']['visible_at_40pct'],
            'visible_at_40pct_programme': round(vis_prog, 4),
        },
        'lufs': float(rec['audio']['lufs']),
        'cue_onsets': [
            {
                'file': c['file'],
                'at_s': c['at_s'],
                'measured_onset_s': c.get('measured_onset_s'),
                'over_bed_db': c.get('onset_over_bed_db'),
                'method': c.get('onset_method'),
            }
            for c in rec['audio']['cues']
        ],
        'first_frame_luma': round(float(luma(frame_rgb(final, 0.0)).mean()), 3),
        'last_frame_luma': round(float(luma(frame_rgb(final, 0.0, from_end=True)).mean()), 3),
        'files': {
            'final': final,
            'sheet': P('final_v3_sheet.jpg'),
            'dive_strip': P('dive_v3_strip.jpg'),
            'shot3_dive': P('shot3_dive.mp4'),
            'end_plate': P('end_plate_v3.png'),
            'plate': P('plate_v3.png'),
            'words': P('words_v3.png'),
            'title': P('title_v3.mp4'),
            'title_fx': P('title_v3_fx.mp4'),
            'impacts_draft': P('impacts_v3_draft.jpg'),
            'impacts_frame': P('impacts_v3_puff.png'),
            'shotlist': P('shotlist_v3.json'),
            'track': P('track_v3.wav'),
            'hold_frame': hold_png,
            'assemble': P('_assemble_v3.json'),
            'inputs_v2': [Q('shot1_fx.mp4'), Q('shot2_fx.mp4'), Q('shot3_fin.mp4'), Q('plate_clean.png')],
        },
    }
    json.dump(out, open(P('receipt_v3.json'), 'w'), indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))
    return out


STAGES = {
    'dive': stage_dive,
    'plate': stage_plate,
    'words': stage_words,
    'swirl': stage_swirl,
    'impacts': stage_impacts,
    'final': stage_final,
    'receipt': stage_receipt,
}

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    os.chdir(CREWS)
    sys.path.insert(0, CREWS)
    want = sys.argv[1:] or ['all']
    if want == ['all']:
        want = list(STAGES)
    for stg in want:
        if stg not in STAGES:
            raise SystemExit('unknown stage %s (have %s)' % (stg, '|'.join(STAGES)))
        log('=== %s ===' % stg)
        STAGES[stg]()
    log('OK')
