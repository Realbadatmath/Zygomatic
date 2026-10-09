# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_workflows.continuity_qc.models import (
    DEFAULT_THRESHOLDS,
    _containment,
    _detect,
    _frames_at_times,
    _gate,
    _load_gdino,
    available,
    json,
    os,
    paths,
    pick_device,
    sys,
)
from zyg_workflows.continuity_qc.clip import analyze_clip


# ── main gate: action_ownership ───────────────────────────────────────────────
def action_ownership(
    clip_path,
    actor_prompts,
    action_object,
    times,
    expected_owner=None,
    device='auto',
    log_fn=None,
    run_id=None,
    thresholds=None,
    shadow=True,
):
    """Grounded "who is doing it" gate — the kid-smoking guard, done with boxes.

    actor_prompts: {'man': 'older man with white beard', 'boy': 'young boy'}
    action_object: 'white clay pipe'        times: draw/action timestamps (seconds)
    expected_owner: key of actor_prompts that MUST own the prop (default: first key)

    At each timestamp one GroundingDINO forward grounds every actor prompt plus the
    prop; ownership is the fraction of the PROP box that falls inside each actor box
    (asymmetric containment — a small prop inside a big body box scores ~1.0 where
    IoU would score ~0.05). The winner must clear own_overlap_min AND beat the
    runner-up by own_margin_min, otherwise the verdict is 'ambiguous'.

    This replaces the comparative-CLIP check that passed whenever *anybody* smoked.

    Returns {'ok','shadow','block','times':[...],'checks':[...]}; fail-safe on error."""
    log = log_fn or (lambda _m: None)
    thr = dict(DEFAULT_THRESHOLDS)
    thr.update(thresholds or {})
    keys = list(actor_prompts.keys())
    expected_owner = expected_owner or (keys[0] if keys else None)
    out = {
        'tag': f'action_ownership:{os.path.basename(clip_path)}',
        'kind': 'action_ownership',
        'path': clip_path,
        'ok': True,
        'shadow': bool(shadow),
        'block': False,
        'device': None,
        'action_object': action_object,
        'expected_owner': expected_owner,
        'times': [],
        'checks': [],
    }
    try:
        dev = pick_device(device, log_fn=log)
        out['device'] = dev
        gdino = _load_gdino(dev, log_fn=log)
        got, fps = _frames_at_times(clip_path, times)
        prompts = [actor_prompts[k] for k in keys] + [action_object]
        for t, fi, frame in got:
            det = _detect(gdino, frame, prompts, dev, thr['det_score_min'], log_fn=log)
            actors = {k: det[i] for i, k in enumerate(keys)}
            prop = det[-1]
            row = {
                't': round(t, 2),
                'frame': fi,
                'prop': {'score': prop['score'], 'box': prop['box'], 'found': prop['found']},
                'actors': {k: {'score': v['score'], 'box': v['box'], 'found': v['found']} for k, v in actors.items()},
                'overlap': {},
            }
            if not prop['found']:
                row['owner'] = None
                row['verdict'] = 'prop-not-found'
                row['ok'] = True  # can't attribute what isn't there
                row['note'] = f"'{action_object}' not grounded at {t:.1f}s (score {prop['score']:.2f})"
            else:
                for k, v in actors.items():
                    row['overlap'][k] = round(_containment(prop['box'], v['box']), 3)
                ranked = sorted(row['overlap'].items(), key=lambda kv: -kv[1])
                top, top_v = ranked[0]
                second_v = ranked[1][1] if len(ranked) > 1 else 0.0
                row['margin'] = round(top_v - second_v, 3)
                if top_v < thr['own_overlap_min'] or row['margin'] < thr['own_margin_min']:
                    row['owner'] = None
                    row['verdict'] = 'ambiguous'
                    row['ok'] = True  # shadow: unattributable is not a failure
                    row['note'] = f'no clear owner (top {top}={top_v:.2f}, margin {row["margin"]:.2f})'
                else:
                    row['owner'] = top
                    row['ok'] = top == expected_owner
                    row['verdict'] = 'correct-owner' if row['ok'] else 'wrong-owner'
                    row['note'] = (
                        ''
                        if row['ok']
                        else (
                            f"'{action_object}' owned by {top} "
                            f'({top_v:.2f}) not {expected_owner} '
                            f'({row["overlap"].get(expected_owner, 0.0):.2f}) at {t:.1f}s'
                        )
                    )
            out['times'].append(row)
            out['checks'].append(
                {
                    'check': f'action_ownership@{row["t"]}s',
                    'ok': row['ok'],
                    'owner': row['owner'],
                    'verdict': row['verdict'],
                    'overlap': row['overlap'],
                    'note': row['note'],
                }
            )
            _gate(
                run_id,
                f'action_ownership:{action_object}@{row["t"]}s',
                row['ok'],
                score=row['overlap'].get(expected_owner),
                tag=row['verdict'],
            )
            log(
                f'[continuity_qc] ownership @{row["t"]}s: owner={row["owner"]} '
                f'{row["overlap"]} → {"PASS" if row["ok"] else "FAIL"}'
            )
        out['ok'] = all(r['ok'] for r in out['times']) if out['times'] else True
        out['block'] = (not out['ok']) and not shadow
        _gate(run_id, f'action_ownership:{action_object}', out['ok'], tag=expected_owner or '')
    except Exception as e:
        out['error'] = str(e)[:300]
        out['ok'] = True  # fail-safe
        out['block'] = False
        log(f'[continuity_qc] action_ownership ERROR (fail-safe pass): {e}')
    return out


# ── CLI / validation harness ──────────────────────────────────────────────────
_V7 = str(paths.ZYG_OUTPUT_ROOT / 'multichar_seated' / 'scene20_v7' / 'pasted17.mp4')
_V7_OBJECTS = [
    {'name': 'pipe', 'ground_prompt': 'white clay tobacco pipe'},
    {'name': 'candle', 'ground_prompt': 'lit candle in a holder'},
    {'name': 'book', 'ground_prompt': 'open book on the table'},
]
_V7_ACTORS = {'man': 'older man with white beard', 'boy': 'young boy'}


def _main(argv):
    import argparse

    ap = argparse.ArgumentParser(description='grounded continuity QC')
    ap.add_argument('--clip', default=_V7)
    ap.add_argument('--sample-fps', type=float, default=2.0)
    ap.add_argument('--device', default='auto')
    ap.add_argument('--json-out', default='')
    ap.add_argument('--skip-clip', action='store_true')
    ap.add_argument('--skip-ownership', action='store_true')
    ap.add_argument('--times', default='5.2,12.7')
    a = ap.parse_args(argv)
    log = lambda m: print(m, flush=True)
    res = {'clip': a.clip, 'available': available(log_fn=log)}
    if not a.skip_clip:
        res['analyze_clip'] = analyze_clip(a.clip, _V7_OBJECTS, sample_fps=a.sample_fps, device=a.device, log_fn=log)
    if not a.skip_ownership:
        res['action_ownership'] = action_ownership(
            a.clip,
            _V7_ACTORS,
            'white clay pipe',
            [float(x) for x in a.times.split(',') if x.strip()],
            expected_owner='man',
            device=a.device,
            log_fn=log,
        )
    if a.json_out:
        with open(a.json_out, 'w') as fh:
            json.dump(res, fh, indent=1)
        print(f'wrote {a.json_out}')
    return res


if __name__ == '__main__':
    _main(sys.argv[1:])

# ─────────────────────────────────────────────────────────────────────────────
# CALIBRATION — 2026-07-30, output/multichar_seated/scene20_v7/pasted17.mp4
# 832x480, 17 fps, 341 frames → 43 sampled frames at sample_fps=2, 6 context
# windows (stride 57), device=cpu (the GPU was held by a live render), 448 s.
# Ground truth for this clip: the PIPE morphs across the 13.2-13.9 s window seam;
# the CANDLE and the BOOK are stable props; the SET does not get re-derived; the
# MAN (not the boy) holds the pipe at both draw times.
#
# Measured per-seam DINOv2 crop cosine (last frame before → first frame after,
# 8-frame gap ≈ 0.47 s), by window boundary:
#            3.76s   7.06s  10.35s  13.65s  16.94s      min cos-to-frame-0
#   pipe     0.981   0.976   0.856   0.555   0.956            0.440
#   candle   1.000   1.000   0.988   0.992   0.996            0.831
#   book     0.969   0.968   0.970   0.928   0.919            0.910
#   bg       0.976   0.957   0.886   0.901   0.875            0.686
# Mask-area drift across the same seams (%) / grounded-box IoU:
#   pipe   -7/0.98  -11/0.95  -15/0.80  -33/0.38   -1/0.73
#   candle  -1/1.00    0/1.00    0/1.00    0/1.00    0/1.00
#   book     0/0.94    2/0.99   -4/0.95    1/0.97  +33/0.90
#
# Threshold choices and the margin each one has on this clip:
#   dino_seam_cos_min 0.80  worst passer book 0.919 (+0.119); failer pipe 0.555
#                           (-0.245). THIS is the metric that separates a morph
#                           from a page turn — see the area row: the pipe's morph
#                           (-33%) and the book's legitimate page turn (+33%) are
#                           indistinguishable by area, and NCC stays high through
#                           the morph because the clay texture never changes.
#   dino_anchor_min   0.60  candle 0.831 / book 0.910 pass; pipe 0.440 fails.
#   box_iou_min       0.45  book 0.897 passes (+0.447); pipe 0.382 fails (-0.068,
#                           thin — corroboration only, never the sole detector).
#   area_drift_pct_max 45   deliberately loose: must clear the book's +33% page
#                           turn, which also lets the pipe's -33% through. Area is
#                           evidence for the report, not a discriminator here.
#   bg_seam_cos_min   0.78  worst measured background seam 0.875 (+0.095). The
#                           background image blacks out the tracked props AND every
#                           'person' instance (both actors), dilated 9 px; without
#                           the actor masks the same seam reads 0.832 and the gate
#                           would fire on nothing but an arm moving.
#   bg_anchor_min     0.55  background frame-0 cosine decays to 0.686 over 20 s —
#                           that is the run's known global colour creep (v7 qc:
#                           color_drift 106.2), not re-derivation, so it is gated
#                           loosely and the seam metric does the work.
#   presence_rate_min 0.60  NOT exercised by v7 — nothing vanishes in this clip.
#                           Carried over as a conservative default.
#   own_overlap_min   0.12 / own_margin_min 0.05: measured pipe-in-actor
#                           containment was man 0.966 / boy 0.000 at t=5.2 s and
#                           man 0.981 / boy 0.000 at t=12.7 s. Enormous margin —
#                           the actors sit on opposite sides of frame, so this gate
#                           is decisive where the old comparative-CLIP check
#                           (sim 0.284 vs 0.229) was nearly a coin flip.
#
# Verdicts produced: pipe → appearance-drift (flags appearance-drift + resized,
# worst seam 13.65 s = the required 13.2-13.9 s boundary), candle → present,
# book → present, background → stable, ownership → correct-owner at both times.
#
# NOT executed here: nothing in this module needs the GPU to be validated, but the
# cuda path itself (pick_device → 'cuda') was never exercised — the live render
# held 31.9 GB of the 49 GB card for the whole session, so every number above is
# from the CPU path.
# ─────────────────────────────────────────────────────────────────────────────
