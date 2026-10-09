# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""identity_bank — the per-frame clip identity instrument (2026-09-02, S03)."""

import logging as _zyg_logging
import os

from zyg_workflows.bin import exe

from .embedding import (
    SPREAD_ALARM,
    Z_FLOOR,
    _FLOORS,
    _ledger_gate,
    _log,
    _np,
    embed_face,
    embed_region,
)
from .gate import _pick_backend, _record_check, bank_stats, check

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.identity_bank')


# ── per-frame clip instrument (2026-09-02, S03) ──────────────────────────────
# The old check_clip sampled FIVE fixed times through a STATIC box and had zero
# callers. Two things were wrong with it beyond the sampling: a static box is a
# lie the moment the character moves (it scores whatever drifted into the box),
# and a clip that legitimately shows nobody scored the same as a clip that shows
# the wrong person. Both are fixed here.
#
# FOUR-STATE LEDGER, one state per SAMPLED FRAME. The states are not severities;
# they are different KINDS of answer and are never averaged together:
#   found          — a face was located and scored against the bank.
#   not_found      — nothing of the subject in this frame (a cutaway, a landscape
#                    shot). Not a defect and not evidence; excluded from the score.
#   not_detectable — a body IS in frame but no face can be resolved (rear view,
#                    extreme pose, occlusion). The metric does not apply here; a
#                    rear view is not an identity failure.
#   unmeasurable   — the machinery failed (frame extract, detector, model). This
#                    is OUR fault, is counted separately, and never reads as a pass.
LEDGER_STATES = ('found', 'not_found', 'not_detectable', 'unmeasurable')

CLIP_STRIDE = int(os.environ.get('ZYG_IDENTITY_CLIP_STRIDE', '4'))
CLIP_MAX_FRAMES = int(os.environ.get('ZYG_IDENTITY_CLIP_MAX_FRAMES', '400'))
CLIP_MODE = os.environ.get('ZYG_IDENTITY_CLIP_MODE', 'perframe')
# Margin added around the MediaPipe face-oval box before the crop is handed to
# MTCNN: the 478 landmarks stop at the face oval and a face-ID net wants hair,
# jaw and neck (see geom/keypoints._head_crop, same reasoning one layer up).
FACE_BOX_MARGIN = float(os.environ.get('ZYG_IDENTITY_FACE_MARGIN', '0.45'))
# ── clip floors, set from the 2026-09-02 bench (see BENCH CLIP, top of file) ──
# NOT the same numbers as _FLOORS: those are calibrated for `check()` on a single
# still and other callers depend on them. A per-frame clip floor is a different
# measurement (motion blur, compression, off-axis heads) and gets its own value.
CLIP_FLOORS = {
    # 12 arms / 419 scored frames. Genuine arms hold pass_frac >= 0.98 anywhere in
    # [0.40, 0.45] and every impostor arm sits at 0.000 from 0.38 upward, so the
    # whole plateau separates; 0.42 is its middle. The two ends are a real
    # trade-off and the choice is NOT arbitrary: 0.45 buys 0.074 of margin over
    # the highest impostor frame ever seen (0.3763 — Cornelis' bank on Abel's
    # clip) but leaves Cornelis' own true clip only 0.048 of headroom, since he
    # runs 0.498-0.572 all the way through it while Abel runs 0.729-0.820. 0.42
    # keeps +0.044 over that impostor frame and gives Cornelis 0.078. The impostor
    # side is already protected by the pass_frac rule (impostor arms score 0.000,
    # not 0.3), so the binding risk is a false alarm on a genuine clip.
    'facenet': float(os.environ.get('ZYG_IDENTITY_CLIP_FLOOR_FACENET', '0.42')),
    # UNBENCHED FOR CLIPS. Both benched characters have facenet banks, so no arm
    # ran on dinov2 and this number is inherited from the still-image floor, not
    # measured. The docstring already records that dinov2-on-a-head-box is largely
    # a STYLE descriptor (impostor margin +0.048 on stills); do not read a dinov2
    # clip verdict as an identity verdict until an arm has actually run on it.
    'dinov2': float(os.environ.get('ZYG_IDENTITY_CLIP_FLOOR_DINOV2', '0.50')),
}
CLIP_FLOOR_BENCHED = {'facenet': True, 'dinov2': False}
# Fraction of FOUND frames that must clear the per-frame floor for a clip to pass.
# Bench: genuine arms 0.980-1.000, impostor arms 0.000-0.000 at floor 0.45. 0.70
# sits 0.28 under the worst genuine arm and 0.70 over the best impostor — the
# aggregate is what absorbs the razor-thin per-frame gap (the overlap-free window
# between the worst genuine frame and the best impostor frame is only 0.018 wide,
# so no single frame may ever decide a clip).
CLIP_PASS_FRAC = float(os.environ.get('ZYG_IDENTITY_CLIP_PASS_FRAC', '0.70'))
# Minimum FOUND frames before pass_frac is allowed to be a verdict at all.
# MEASURED 2026-09-02: at stride 16 a 3.7 s clip yields 6 found frames, so
# pass_frac can only take the values 0, 1/6, 2/6 ... and ONE frame moves it by
# 0.167 — straight across the 0.70 line. Under this many frames the numbers are
# still reported and `ok` is None: not enough evidence is not a pass and it is
# not a fail either. Every bench arm had >= 15 found frames, so this guard does
# not touch the calibration above.
CLIP_MIN_FOUND = int(os.environ.get('ZYG_IDENTITY_CLIP_MIN_FOUND', '8'))
# Per-frame dispersion. INFORMATIONAL ONLY and deliberately not part of `ok`:
# measured spreads were genuine 0.003-0.299 and impostor 0.085-0.350 — the ranges
# OVERLAP, so spread separates nothing. The shuffle arm says why: a per-frame
# metric is order-blind, so spread cannot be a temporal-continuity measure. 0.35
# is set just above the largest genuine spread observed, as a "go and look" flag.
CLIP_SPREAD_ALARM = float(os.environ.get('ZYG_IDENTITY_CLIP_SPREAD_ALARM', '0.35'))


def enabled():
    """ZYG_IDENTITY_CLIP — default ON, advisory everywhere (never fails a pipeline)."""
    return os.environ.get('ZYG_IDENTITY_CLIP', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def track_face_box(frame_path, roi=None, margin=None, log_fn=None):
    """Locate the face in ONE frame; return (box_frac | None, state, info).

    roi: optional (fx0, fy0, fx1, fy1) restricting the search to one character's
    band of the frame. With two characters in shot a whole-frame detector returns
    whichever face it likes best — the ROI is what says WHICH person to score, and
    is the ONLY thing the old static box was actually good for. Inside the ROI the
    box is re-derived per frame, so the character may walk, lean and turn.

    The returned box is in ORIGINAL-FRAME fractions and is clamped to the ROI.
    """
    margin = FACE_BOX_MARGIN if margin is None else float(margin)
    try:
        import cv2 as _cv2
        from zyg_workflows.geom import keypoints as _kp
    except Exception as e:
        return None, 'unmeasurable', {'error': f'import: {type(e).__name__}: {e}'}
    try:
        bgr = _cv2.imread(str(frame_path))
        if bgr is None:
            return None, 'unmeasurable', {'error': 'imread_failed'}
        H, W = bgr.shape[:2]
        ox = oy = 0
        rx0, ry0, rx1, ry1 = 0.0, 0.0, 1.0, 1.0
        sub = bgr
        if roi:
            rx0, ry0, rx1, ry1 = (_clamp01(float(v)) for v in roi)
            x0, y0 = int(W * rx0), int(H * ry0)
            x1, y1 = int(W * rx1), int(H * ry1)
            # MediaPipe's ImageFrame assumes 4-byte-aligned rows. A BGR crop has row
            # stride 3*w, so 3*w % 4 == 0 only when w % 4 == 0; any other width aborts
            # the PROCESS inside image_frame.cc ("Check failed: 1 == ChannelSize()"),
            # which is worse than a wrong answer — SIGABRT cannot be caught, so the
            # frame cannot even be recorded as `unmeasurable` and the whole run dies.
            # Measured 2026-09-05: widths 940/944 pass, 941/942/943 abort. A 480x704
            # frame under the standard [0.15..0.85] box gives 336 (divisible) and hid
            # this for months; an 896-wide clip gives 627 and does not. Snap DOWN so
            # the crop stays inside the requested ROI.
            x1 = x0 + ((x1 - x0) // 4) * 4
            if x1 - x0 < 48 or y1 - y0 < 48:
                return None, 'unmeasurable', {'error': 'roi_too_small'}
            sub = bgr[y0:y1, x0:x1]
            ox, oy = x0, y0
        det = _kp.detect(sub)
        if det.face.ok and det.face.pts is not None and len(det.face.pts):
            p = det.face.pts
            fx0, fx1 = float(p[:, 0].min()), float(p[:, 0].max())
            fy0, fy1 = float(p[:, 1].min()), float(p[:, 1].max())
            fw, fh = max(fx1 - fx0, 1.0), max(fy1 - fy0, 1.0)
            mx, my = fw * margin, fh * margin
            box = (
                _clamp01(max(rx0, (ox + fx0 - mx) / W)),
                _clamp01(max(ry0, (oy + fy0 - my) / H)),
                _clamp01(min(rx1, (ox + fx1 + mx) / W)),
                _clamp01(min(ry1, (oy + fy1 + my) / H)),
            )
            if box[2] - box[0] < 1e-3 or box[3] - box[1] < 1e-3:
                return None, 'unmeasurable', {'error': 'degenerate_box'}
            return (
                box,
                'found',
                {
                    'via': det.face.via,
                    'face_px': round(max(fw, fh), 1),
                    'yaw': (None if det.face.extra.get('yaw') is None else round(float(det.face.extra['yaw']), 3)),
                },
            )
        if det.body.ok:
            # A subject is there; the face is not resolvable. THIS is the state the
            # old instrument had no room for — it scored the back of a head against
            # a face bank and called the miss a failure.
            return None, 'not_detectable', {'reason': 'body_without_face'}
        return None, 'not_found', {'reason': 'no_subject'}
    except Exception as e:
        _log(log_fn, f'[identity_bank] track_face_box failed: {type(e).__name__}: {e}')
        return None, 'unmeasurable', {'error': f'{type(e).__name__}: {e}'}


def _probe_fps(clip_path):
    try:
        import subprocess

        out = subprocess.run(
            [
                exe('ffprobe'),
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=avg_frame_rate',
                '-of',
                'csv=p=0',
                str(clip_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        num, _, den = out.partition('/')
        f = float(num) / float(den or 1)
        return f if f > 0.1 else 24.0
    except Exception:
        return 24.0


def _explode(clip_path, wd, stride, max_frames):
    """One ffmpeg pass for every sampled frame — a per-frame seek costs ~0.4 s each
    and turns a 60 s clip into a ten-minute measurement."""
    import glob as _glob
    import subprocess

    os.makedirs(wd, exist_ok=True)
    pat = os.path.join(wd, 'f_%06d.png')
    cmd = [
        exe('ffmpeg'),
        '-v',
        'error',
        '-y',
        '-i',
        str(clip_path),
        '-vf',
        f"select='not(mod(n\\,{int(stride)}))'",
        '-vsync',
        '0',
    ]
    if max_frames:
        cmd += ['-frames:v', str(int(max_frames))]
    cmd += [pat]
    subprocess.run(cmd, check=True, timeout=1800)
    return sorted(_glob.glob(os.path.join(wd, 'f_*.png')))


def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def check_clip(
    char_id,
    style_profile,
    clip_path,
    box_frac=None,
    times=None,
    backend=None,
    episode=None,
    render_id=None,
    device=None,
    log_fn=None,
    run_id=None,
    tag='',
    workdir=None,
    mode=None,
    stride=None,
    max_frames=None,
    floor=None,
    pass_frac=None,
    record=True,
    keep_frames=False,
    roi=None,
):
    """Per-frame identity instrument over a finished clip.

    mode='perframe' (default): sample every `stride`-th frame, TRACK the face in
    each one (optionally inside `roi`/`box_frac` to pick which character), score it
    against the bank, and return a per-frame series plus the four-state ledger.
    mode='legacy': the pre-2026-09-02 behaviour — five fixed times through the
    static `box_frac` — kept for comparison, not for production.

    `ok` is None (UNKNOWN) whenever no frame was FOUND. UNKNOWN is never a pass.
    Advisory everywhere: nothing in the pipeline fails on this yet.
    """
    mode = (mode or CLIP_MODE).lower()
    if mode == 'legacy':
        return _check_clip_legacy(
            char_id,
            style_profile,
            clip_path,
            box_frac,
            times=times,
            backend=backend,
            episode=episode,
            render_id=render_id,
            device=device,
            log_fn=log_fn,
            run_id=run_id,
            tag=tag,
            workdir=workdir,
        )
    import shutil as _shutil
    import tempfile

    wd = workdir or tempfile.mkdtemp(prefix='idclip_')
    try:
        np = _np()
        backend = backend or _pick_backend(char_id, style_profile)
        st = bank_stats(char_id, style_profile, backend)
        if not st.get('ok'):
            return {
                'ok': None,
                'mode': mode,
                'cosine': None,
                'z': None,
                'n_bank': st.get('n_bank', 0),
                'backend': backend,
                'error': st.get('error', 'no_bank'),
                'reason': 'empty_bank',
                'series': [],
                'ledger': {k: 0 for k in LEDGER_STATES},
            }
        stride = int(stride or CLIP_STRIDE)
        max_frames = int(CLIP_MAX_FRAMES if max_frames is None else max_frames)
        fps = _probe_fps(clip_path)
        roi = roi if roi is not None else box_frac
        try:
            frames = _explode(clip_path, os.path.join(wd, 'frames'), stride, max_frames)
        except Exception as e:
            return {
                'ok': None,
                'mode': mode,
                'cosine': None,
                'z': None,
                'n_bank': st['n_bank'],
                'backend': backend,
                'error': f'extract: {type(e).__name__}: {e}',
                'reason': 'extract_failed',
                'series': [],
                'ledger': {k: 0 for k in LEDGER_STATES},
            }
        cen = np.asarray(st['centroid'], dtype=np.float32)
        flo = float(floor) if floor is not None else CLIP_FLOORS.get(backend, _FLOORS.get(backend, 0.5))
        sd = st['loo_std']
        series, ledger = [], {k: 0 for k in LEDGER_STATES}
        for i, fp in enumerate(frames):
            n_frame = i * stride
            rec = {'i': n_frame, 't': round(n_frame / fps, 3)}
            box, state, info = track_face_box(fp, roi=roi, log_fn=log_fn)
            if state != 'found':
                rec.update({'state': state, 'cosine': None, 'z': None, **info})
                ledger[state] += 1
                series.append(rec)
                continue
            emb = (
                embed_face(fp, backend='facenet', box_frac=box, device=device, log_fn=log_fn)
                if backend == 'facenet'
                else embed_region(fp, box_frac=box, backend=backend, device=device, log_fn=log_fn)
            )
            if not emb.get('ok'):
                # The tracker saw a face and the embedder could not use it (too
                # small, MTCNN disagrees). That is not_detectable, not a failure:
                # this frame carries no identity evidence either way.
                rec.update(
                    {
                        'state': 'not_detectable',
                        'cosine': None,
                        'z': None,
                        'reason': f'embed:{emb.get("error")}',
                        'box': [round(v, 4) for v in box],
                        'face_px': info.get('face_px'),
                        'via': info.get('via'),
                    }
                )
                ledger['not_detectable'] += 1
                series.append(rec)
                continue
            vec = np.asarray(emb['embedding'], dtype=np.float32)
            if vec.shape != cen.shape:
                rec.update({'state': 'unmeasurable', 'cosine': None, 'z': None, 'error': 'dim_mismatch'})
                ledger['unmeasurable'] += 1
                series.append(rec)
                continue
            cos = float(np.dot(vec, cen))
            z = float((cos - st['loo_mean']) / sd) if sd > 1e-6 else 0.0
            rec.update(
                {
                    'state': 'found',
                    'cosine': round(cos, 4),
                    'z': round(z, 3),
                    'pass': bool(cos >= flo),
                    'box': [round(v, 4) for v in box],
                    'face_px': info.get('face_px'),
                    'via': info.get('via'),
                    'yaw': info.get('yaw'),
                    'det_prob': emb.get('det_prob'),
                }
            )
            ledger['found'] += 1
            series.append(rec)
        cosv = [r['cosine'] for r in series if r.get('cosine') is not None]
        res = {
            'mode': 'perframe',
            'backend': backend,
            'n_bank': st['n_bank'],
            'floor': flo,
            'floor_benched': CLIP_FLOOR_BENCHED.get(backend, False),
            'z_floor': Z_FLOOR,
            'stride': stride,
            'fps': round(fps, 3),
            'sampled': len(frames),
            'ledger': ledger,
            'bank_mean': round(st['loo_mean'], 4),
            'bank_std': round(sd, 4),
            'clip': str(clip_path),
            'char_id': char_id,
            'style': style_profile,
            'roi': ([round(float(v), 4) for v in roi] if roi else None),
            'series': series,
        }
        if not cosv:
            res.update(
                {
                    'ok': None,
                    'cosine': None,
                    'z': None,
                    'found': 0,
                    'reason': (
                        'no_subject_in_clip'
                        if ledger['not_found'] >= max(1, len(frames) - ledger['unmeasurable'])
                        else 'no_measurable_frame'
                    ),
                }
            )
        else:
            n_pass = sum(1 for r in series if r.get('pass'))
            frac = n_pass / len(cosv)
            pf = float(CLIP_PASS_FRAC if pass_frac is None else pass_frac)
            spread = round(max(cosv) - min(cosv), 4)
            zs = [r['z'] for r in series if r.get('z') is not None]
            enough = len(cosv) >= CLIP_MIN_FOUND
            res.update(
                {
                    'ok': bool(frac >= pf) if enough else None,
                    'enough_evidence': enough,
                    'min_found': CLIP_MIN_FOUND,
                    'found': len(cosv),
                    'cosine': round(sum(cosv) / len(cosv), 4),
                    'cosine_min': round(min(cosv), 4),
                    'cosine_max': round(max(cosv), 4),
                    'cosine_p10': round(_pct(cosv, 0.10), 4),
                    'cosine_median': round(_pct(cosv, 0.50), 4),
                    'spread': spread,
                    'spread_alarm': bool(spread > CLIP_SPREAD_ALARM),
                    'spread_threshold': CLIP_SPREAD_ALARM,
                    'n_pass': n_pass,
                    'pass_frac': round(frac, 4),
                    'pass_frac_floor': pf,
                    'z': round(min(zs), 3) if zs else None,
                    'z_median': round(_pct(zs, 0.50), 3) if zs else None,
                    'reason': ('pass' if frac >= pf else 'below_pass_frac')
                    if enough
                    else f'too_few_found_for_verdict ({len(cosv)} < '
                    f'{CLIP_MIN_FOUND}); numbers reported, verdict UNKNOWN',
                }
            )
        if record:
            # ONE row per clip. Recording 350 per-frame rows would turn a within-clip
            # wobble into 350 points of a cross-episode "ratchet" that never happened.
            _record_check(
                char_id,
                style_profile,
                episode,
                render_id,
                run_id,
                backend,
                res.get('cosine'),
                res.get('z'),
                res.get('ok'),
                st['n_bank'],
                clip_path,
                tag or f'clip:perframe:n{stride}',
            )
        _ledger_gate(
            run_id,
            'identity_clip',
            'unknown' if res['ok'] is None else ('pass' if res['ok'] else 'fail'),
            score=res.get('cosine'),
            tag=f'{char_id}/{style_profile}/{backend}',
        )
        _log(
            log_fn,
            f'[identity_bank] clip {os.path.basename(str(clip_path))} '
            f'{char_id}/{backend}: found={ledger["found"]} '
            f'nf={ledger["not_found"]} nd={ledger["not_detectable"]} '
            f'um={ledger["unmeasurable"]} cos={res.get("cosine")} '
            f'pass_frac={res.get("pass_frac")} -> {res.get("reason")}',
        )
        return res
    except Exception as e:
        return {
            'ok': None,
            'mode': 'perframe',
            'cosine': None,
            'z': None,
            'n_bank': 0,
            'error': f'{type(e).__name__}: {e}',
            'series': [],
            'ledger': {k: 0 for k in LEDGER_STATES},
        }
    finally:
        if not workdir and not keep_frames:
            _shutil.rmtree(wd, ignore_errors=True)


def _check_clip_legacy(
    char_id,
    style_profile,
    clip_path,
    box_frac,
    times=None,
    backend=None,
    episode=None,
    render_id=None,
    device=None,
    log_fn=None,
    run_id=None,
    tag='',
    workdir=None,
):
    """Pre-2026-09-02 behaviour, verbatim: five fixed times, one STATIC box, spread
    alarm calibrated on a single render. Kept only so the bench can show what the
    per-frame instrument buys."""
    try:
        import subprocess
        import tempfile

        times = times or [2, 6, 9, 13, 16]
        wd = workdir or tempfile.mkdtemp(prefix='idbank_')
        os.makedirs(wd, exist_ok=True)
        windows = []
        for t in times:
            fp = os.path.join(wd, f'_idb_{os.getpid()}_{t}.png')
            try:
                subprocess.run(
                    [exe('ffmpeg'), '-v', 'error', '-y', '-ss', str(t), '-i', str(clip_path), '-frames:v', '1', fp],
                    check=True,
                    timeout=120,
                )
            except Exception as e:
                windows.append({'t': t, 'ok': None, 'error': f'extract: {e}'})
                continue
            r = check(
                char_id,
                style_profile,
                fp,
                backend=backend,
                box_frac=box_frac,
                episode=episode,
                render_id=render_id,
                device=device,
                log_fn=log_fn,
                run_id=run_id,
                tag=tag or f't={t}s',
            )
            r['t'] = t
            windows.append(r)
            try:
                if not workdir:
                    os.remove(fp)
            except OSError as _exc:
                _zyg_log.debug('frame cleanup skipped: %s', _exc)
        meas = [w for w in windows if w.get('cosine') is not None]
        if not meas:
            return {
                'ok': None,
                'mode': 'legacy',
                'cosine': None,
                'z': None,
                'n_bank': 0,
                'windows': windows,
                'reason': 'no_measurable_window',
            }
        cos = [w['cosine'] for w in meas]
        spread = round(max(cos) - min(cos), 4)
        agg_ok = all(w.get('ok') for w in meas)
        return {
            'ok': bool(agg_ok),
            'mode': 'legacy',
            'cosine': round(sum(cos) / len(cos), 4),
            'cosine_min': min(cos),
            'cosine_max': max(cos),
            'spread': spread,
            'spread_alarm': bool(spread > SPREAD_ALARM),
            'spread_threshold': SPREAD_ALARM,
            'z': round(min(w['z'] for w in meas), 3),
            'n_bank': meas[0].get('n_bank', 0),
            'backend': meas[0].get('backend'),
            'measured': len(meas),
            'sampled': len(windows),
            'windows': windows,
        }
    except Exception as e:
        return {
            'ok': None,
            'mode': 'legacy',
            'cosine': None,
            'z': None,
            'n_bank': 0,
            'error': f'{type(e).__name__}: {e}',
            'windows': [],
        }
