# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""qc_character_balance — the pixel side of "who is alive": per-character face and
hand flow, reversals, coherence and the cross-character face-flow ratio.

The steps live in :mod:`gates_charbal_steps`; this module is the gate's
signature, its calibration notes and the order the steps run in."""

import os
from .gates_charbal_detect import _detector_face_boxes_for
from .gates_charbal_steps import (
    gate_face_floor,
    gate_face_ratio,
    judge_box_quality,
    measurable_faces,
    measure_characters,
    report_hands,
    resolve_steps,
    usable_boxes,
)
from .gates_v7 import _record_qc


def qc_character_balance(
    clip_path,
    characters,
    min_face_flow=None,
    max_face_ratio=None,
    min_face_flow_mean=None,
    step_flow=None,
    step_dir=None,
    verify_boxes=True,
    auto_boxes=True,
    _retry=False,
    tag=None,
    log_fn=None,
    fail_open=True,
):
    """Is the shot carried by ONE character? (2026-08-01, the "lifeless Abel" gate.)

    Every per-region gate in this file can pass while the shot fails, because they ask
    "does this region move" one region at a time. This one asks the question the operator
    actually asked: are BOTH people alive, and is one of them doing all the living?

    characters: {'cornelis': {'face': (fx0,fy0,fx1,fy1), 'hands': (...)}, 'abel': {...}}
      'head'/'hand' are accepted spellings; a bare box means the face. 'hands' is optional
      and never gated by default — it is reported so the report shows the whole body.
      GET THE FACE BOX RIGHT OR THIS GATE IS BLIND: crop it to the face, not to the head
      plus hat plus wall. locate_character_faces(clip_path) returns boxes that work.

    Measured per character (one decode per sampling step, both streamed, nothing cached):
      face/hands flow_median  : per-pixel Farneback magnitude at sample_every=step_flow,
                                the same unit qc_region_flow reports. THE GATED NUMBER.
      face/hands flow_mean    : same series' mean — burst-dominated, REPORTED not gated
      burst_frac              : fraction of samples above 2x the median (how much of the
                                mean is one gesture)
      reversals_per_s, net_path : direction quality at step_dir, the qc_motion_quality
                                statistics, reported here for context and NOT re-gated —
                                that gate owns them and is calibrated at step=2.
      hand_face_ratio         : intra-character limb-vs-head balance (qc_motion_balance
                                owns the gate; this is the same ratio for one report)

    Gate — both must hold:
      1. every measured face flow_median >= min_face_flow (default 0.12) — the FREEZE
         backstop. It cannot detect subordination; see the calibration block.
      2. max(face flow_median) / min(...) <= max_face_ratio (default 1.85) — THE gate.
         Verified end to end on detector boxes: v6 1.68 PASS, v11 2.24 FAIL, v12 2.18 FAIL.
    Thresholds accept a scalar or {name: value}; the ratio cap also accepts {'lead/lag': v}.

    verify_boxes=True (default, ~0.7s) runs MTCNN and reports, per face box, how much of it
    is actually face (face_fill) and how much of the frame it covers. Out-of-envelope boxes
    raise a SEPARATE 'character_balance:box_quality' check (tagged qc-broken) and mark the
    ratio verdict 'inconclusive' — they do not fail the shot, because the shot is not what
    is broken. Set verify_boxes=False to skip the detector entirely.

    Returns {'ok', 'characters': {...}, 'cross': {...}, 'checks': [...]} and is appended to
    the active DebugRun's qc. Advisory: fail-open on internal error."""
    log = log_fn or (lambda _m: None)
    out = {
        'tag': tag or f'character_balance:{os.path.basename(clip_path)}',
        'kind': 'character_balance',
        'path': clip_path,
        'ok': True,
        'characters': {},
        'cross': {},
        'checks': [],
        'reasons': [],
    }
    try:
        sf, sd = resolve_steps(out, step_flow, step_dir, max_face_ratio, log)
        norm = usable_boxes(out, characters, log)
        if norm is None:
            _record_qc(out)
            return out

        det = measure_characters(out, clip_path, norm, sf, sd, verify_boxes, log_fn, log)
        faces = measurable_faces(out, norm, log)
        gate_face_floor(out, faces, min_face_flow, min_face_flow_mean, log)
        report_hands(out, log)
        cross = gate_face_ratio(out, faces, max_face_ratio, log)
        msg = judge_box_quality(out, faces, cross, det, log)
        if msg:
            # ── AUTO-REPAIR (2026-08-01) ─────────────────────────────────────
            # Warning was not enough. v13/v14/v15 all shipped a box_quality FAIL
            # and therefore an UNTRUSTWORTHY ratio, and each time the real number
            # had to be recovered by hand afterwards with locate_character_faces
            # — during which the production boxes' compressed reading (v15: 1.09)
            # was reported before the detector's (1.58). A gate that knows its own
            # measurement is broken should fix it, not hand the operator a number
            # it has just said not to believe. One retry only (_retry guard).
            if auto_boxes and not _retry:
                repaired = _detector_face_boxes_for(clip_path, characters, log_fn=log)
                if repaired:
                    log(
                        '[qc_character_balance] AUTO-REPAIR: re-running the gate with '
                        'detector face boxes — the ratio below supersedes the one above'
                    )
                    fixed = qc_character_balance(
                        clip_path,
                        repaired,
                        min_face_flow=min_face_flow,
                        max_face_ratio=max_face_ratio,
                        min_face_flow_mean=min_face_flow_mean,
                        step_flow=step_flow,
                        step_dir=step_dir,
                        verify_boxes=verify_boxes,
                        auto_boxes=False,
                        _retry=True,
                        tag=tag,
                        log_fn=log_fn,
                        fail_open=fail_open,
                    )
                    if isinstance(fixed, dict) and not fixed.get('error'):
                        fixed['box_source'] = 'locate_character_faces (AUTO-REPAIRED)'
                        fixed['superseded'] = {
                            'reason': msg,
                            'original_boxes': {
                                k: list(v.get('face') or []) for k, v in characters.items() if isinstance(v, dict)
                            },
                            'original_ratio': (cross or {}).get('face_flow_ratio'),
                        }
                        return fixed
                    log('[qc_character_balance] AUTO-REPAIR failed — keeping the original (inconclusive) result')
        out['cross'] = cross
        out['ok'] = all(c.get('ok', True) for c in out['checks'])
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = bool(fail_open)
        log(f'[qc_character_balance] ERROR (fail-{"open" if fail_open else "CLOSED"}): {e}')
    _record_qc(out)
    return out
