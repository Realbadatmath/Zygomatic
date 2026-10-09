# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The steps of ``qc_character_balance``, one function per seam.

``gates_charbal.qc_character_balance`` was a single 398-line function: resolve
the sampling steps, normalise the caller's boxes, decode the clip once per step,
build a record per region, gate the per-face freeze floor, report the hands,
gate the cross-character face-flow ratio and finally judge the boxes
themselves. Each of those is a function here, taking the ``out`` report dict it
fills and returning what the next step needs, so the orchestrator is the list of
steps and nothing else.

Nothing here changes a measurement, a threshold, a log line or the order of the
checks appended to ``out['checks']`` — the report of a given clip is
byte-identical to the one the monolith produced. The auto-repair re-entry stays
in ``gates_charbal`` because it calls ``qc_character_balance`` itself; this
module only tells it whether the boxes are suspect."""

from .gates_charbal_detect import (
    _CHARBAL_BOX_AREA_MAX,
    _CHARBAL_DIR_STEP,
    _CHARBAL_FACE_FILL_MIN,
    _CHARBAL_FACE_FLOW_MIN,
    _CHARBAL_FACE_RATIO_MAX,
    _CHARBAL_FLOW_STEP,
    _box_area,
    _box_inter,
    _charbal_normalize,
    _perpix_stats,
    locate_character_faces,
)
from .gates_motion import _MOTION_COHERENCE_FLOOR, _motion_vector_stats, _region_flow_vectors
from .gates_v7 import _gate_thr


def resolve_steps(out, step_flow, step_dir, max_face_ratio, log):
    """Record the two sampling steps on ``out`` and return them as ``(sf, sd)``.

    A flow step other than the calibrated one moves the ratio the gate compares
    against its cap, so an implicit cap at a non-default step earns a reason, an
    ``out['step_warning']`` marker and a log line."""
    sf = int(step_flow or _CHARBAL_FLOW_STEP)
    sd = int(step_dir or _CHARBAL_DIR_STEP)
    out['step_flow'], out['step_dir'] = sf, sd
    if sf != _CHARBAL_FLOW_STEP and max_face_ratio is None:
        w = (
            f'step_flow={sf} but the ratio cap was calibrated at '
            f'{_CHARBAL_FLOW_STEP}; measured on these clips the median ratio moves '
            f'(v6 1.56->1.72, v11 2.24->1.93 going 4->2) and the separation nearly '
            f'closes. Supply max_face_ratio explicitly for this step.'
        )
        out['reasons'].append(w)
        out['step_warning'] = True
        log(f'[qc_character_balance] WARNING: {w}')
    return sf, sd


def usable_boxes(out, characters, log):
    """Normalise the caller's ``characters`` mapping onto boxes the gate can use.

    Returns the normalised ``{name: {'face': box|None, 'hands': box|None}}``, or
    ``None`` when nothing usable was supplied — in which case ``out['error']``
    says so and the caller must not run the gate."""
    norm, bad = _charbal_normalize(characters)
    for b in bad:
        out['reasons'].append(b)
        log(f'[qc_character_balance] {b}')
    if not norm:
        out['error'] = 'no usable character boxes — THIS GATE DID NOT RUN'
        out['reasons'].append(out['error'])
        log(f'[qc_character_balance] {out["error"]}')
        return None
    return norm


def part_record(box, ps, ds):
    """One region's reported record, built from its two statistics bundles.

    ``ps`` is ``_perpix_stats`` output (``None`` when the region produced no
    per-pixel sample at all) and ``ds`` is ``_motion_vector_stats`` output
    (``None`` when direction statistics are unavailable). Returns the dict the
    report carries under ``characters[name][part]``: an ``unmeasured`` stub when
    ``ps`` is ``None``, otherwise the full record, with a ``direction_note``
    whenever reversals were computed below the coherence floor."""
    if ps is None:
        return {'box': list(box), 'unmeasured': True}
    rec = {
        'box': list(box),
        'flow_median': round(ps['flow_median'], 4),
        'flow_mean': round(ps['flow_mean'], 4),
        'flow_p90': round(ps['flow_p90'], 4),
        'burst_frac': round(ps['burst_frac'], 3),
        'reversals_per_s': None if ds is None else round(ds['reversals_per_s'], 3),
        'net_path': None if ds is None else round(ds['net_path'], 4),
        'net_path_win': None if (ds is None or ds['net_path_win'] is None) else round(ds['net_path_win'], 4),
        'vec_mean': None if ds is None else round(ds['flow_mean'], 4),
        'moving': bool(ds is not None and ds['flow_mean'] >= _MOTION_COHERENCE_FLOOR),
        'n_samples': ps['n_samples'],
        'box_area': round(_box_area(box), 4),
    }
    if rec['reversals_per_s'] is not None and not rec['moving']:
        rec['direction_note'] = (
            'below the coherence floor — reversals/net_path are noise here; qc_motion_quality does not gate them either'
        )
    return rec


def score_box_against_detections(face, detections):
    """Annotate a supplied face record with how much of it is really face.

    The detection is matched on intersection and the fill measured against
    *that* face — comparing against the largest detected face instead would
    score a correct box for the small character as if it had missed the big
    one. Adds ``face_fill``, ``face_covered`` and ``matched_detection`` in
    place."""
    hit = max(detections, key=lambda f: _box_inter(face['box'], f['box']))
    inter = _box_inter(face['box'], hit['box'])
    face['face_fill'] = round(inter / max(_box_area(face['box']), 1e-9), 3)
    face['face_covered'] = round(inter / max(_box_area(hit['box']), 1e-9), 3)
    face['matched_detection'] = hit.get('side')


def measure_characters(out, clip_path, norm, sf, sd, verify_boxes, log_fn, log):
    """Measure every region of every character and fill ``out['characters']``.

    One decode per sampling step, both streamed and nothing cached; when the two
    steps coincide the second decode is skipped. Optionally runs the face
    detector once to score the supplied boxes. Returns the detector result dict,
    or ``None`` when box verification did not run."""
    regions = {}
    for name, rec in norm.items():
        for part in ('face', 'hands'):
            if rec[part] is not None:
                regions[f'{name}.{part}'] = rec[part]
    fps, vecs_f, perpix_f = _region_flow_vectors(clip_path, regions, step=sf)
    out['fps'] = round(float(fps), 3)
    if sd == sf:
        vecs_d = vecs_f
    else:
        _fps2, vecs_d, _pp2 = _region_flow_vectors(clip_path, regions, step=sd)

    # ── box verification (cheap, and the difference between a gate and a rubber stamp)
    det = None
    if verify_boxes and any(r['face'] is not None for r in norm.values()):
        det = locate_character_faces(clip_path, expect=len(norm), log_fn=log_fn)
        out['detected_faces'] = det.get('faces') if det.get('ok') else None
        if not det.get('ok'):
            out['reasons'].append(f'box verification unavailable: {det.get("error")}')

    for name, rec in norm.items():
        crec = {'ok': True, 'reasons': []}
        for part in ('face', 'hands'):
            box = rec[part]
            if box is None:
                crec[part] = None
                continue
            ps = _perpix_stats(perpix_f.get(f'{name}.{part}'))
            ds = _motion_vector_stats(vecs_d.get(f'{name}.{part}'), fps, sd)
            crec[part] = part_record(box, ps, ds)
        # box quality against the detector
        face = crec.get('face')
        if face and not face.get('unmeasured') and det and det.get('ok') and det.get('faces'):
            score_box_against_detections(face, det['faces'])
        # intra-character limb/head balance (informational; qc_motion_balance gates it)
        hands = crec.get('hands')
        if face and hands and not face.get('unmeasured') and not hands.get('unmeasured'):
            crec['hand_face_ratio'] = round(hands['flow_median'] / max(face['flow_median'], 1e-6), 3)
        out['characters'][name] = crec
    return det


def measurable_faces(out, norm, log):
    """The face records that actually produced a measurement, by character name.

    A gate that passes because it MEASURED NOTHING is the failure this file
    exists to stop, and it is not hypothetical: cv2 opens a missing path without
    raising, every region comes back unmeasured, the mapping ends up empty and
    every loop below is a no-op that leaves ok=True. Boxes supplied with not one
    measurement therefore raise the ``character_balance:measured`` check here,
    where the count is still known."""
    faces = {n: c['face'] for n, c in out['characters'].items() if c.get('face') and not c['face'].get('unmeasured')}
    want_faces = [n for n, r in norm.items() if r['face'] is not None]
    if want_faces and not faces:
        msg = (
            f'{len(want_faces)} face box(es) supplied and NOT ONE produced a '
            f'measurement — clip unreadable, too short, or the boxes are '
            f'degenerate; THIS GATE DID NOT RUN'
        )
        out['error'] = msg
        out['reasons'].append(msg)
        out['checks'].append(
            {
                'check': 'character_balance:measured',
                'ok': False,
                'faces_supplied': len(want_faces),
                'faces_measured': 0,
                'note': msg,
            }
        )
        log(f'[qc_character_balance] WARNING: {msg}')
    return faces


def gate_face_floor(out, faces, min_face_flow, min_face_flow_mean, log):
    """Gate 1 — every measured face must clear the freeze floor.

    Per character: resolve the median (and optional mean) threshold, record the
    verdict on the face record and the character record, append the
    ``character_balance:<name>.face`` check and log the line. Mutates ``out``
    and ``faces`` in place."""
    for name, f in faces.items():
        thr = _gate_thr(min_face_flow, name, _CHARBAL_FACE_FLOW_MIN)
        mthr = _gate_thr(min_face_flow_mean, name, None)
        ok = True
        crec = out['characters'][name]
        if thr is not None and f['flow_median'] < float(thr):
            ok = False
            crec['reasons'].append(
                f'face flow_median {f["flow_median"]:.3f} < {thr} — this face is FROZEN '
                f'(a genuinely frozen face measures 0.0008), not merely subordinate'
            )
        if mthr is not None and f['flow_mean'] < float(mthr):
            ok = False
            crec['reasons'].append(
                f'face flow_mean {f["flow_mean"]:.3f} < {mthr} — no gestures at all '
                f'(the v12 pin signature: the median holds while the mean collapses)'
            )
        f['ok'] = ok
        f['min_flow'] = thr
        crec['ok'] = bool(crec['ok'] and ok)
        out['checks'].append(
            {
                'check': f'character_balance:{name}.face',
                'ok': ok,
                'flow_median': f['flow_median'],
                'flow_mean': f['flow_mean'],
                'face_reversals_per_s': f.get('reversals_per_s'),
                'face_net_path': f.get('net_path'),
                'burst_frac': f.get('burst_frac'),
                'face_fill': f.get('face_fill'),
                'min_flow': thr,
                'note': '; '.join(crec['reasons']),
            }
        )
        log(
            f'[qc_character_balance] {name}.face: median {f["flow_median"]:.3f} '
            f'mean {f["flow_mean"]:.3f} (burst {f["burst_frac"]:.2f}) '
            f'rev {f.get("reversals_per_s")}/s net {f.get("net_path")} -> '
            f'{"PASS" if ok else "FAIL"}'
        )


def report_hands(out, log):
    """Append the per-character hands check — reported, never gated.

    ``qc_motion_quality`` owns jitter and ``qc_motion_balance`` owns
    limb-vs-head balance, so every hands check carries ``ok: True``; the point
    is that the report shows the whole body. Characters without a measured hand
    region are skipped."""
    for name, c in out['characters'].items():
        h = c.get('hands')
        if not h or h.get('unmeasured'):
            continue
        out['checks'].append(
            {
                'check': f'character_balance:{name}.hands',
                'ok': True,
                'flow_median': h['flow_median'],
                'flow_mean': h['flow_mean'],
                'hand_reversals_per_s': h.get('reversals_per_s'),
                'hand_net_path': h.get('net_path'),
                'hand_face_ratio': c.get('hand_face_ratio'),
                'note': 'reported, not gated — qc_motion_quality owns jitter and '
                'qc_motion_balance owns limb-vs-head balance',
            }
        )
        log(
            f'[qc_character_balance] {name}.hands: median {h["flow_median"]:.3f} '
            f'rev {h.get("reversals_per_s")}/s net {h.get("net_path")} '
            f'(hand/face {c.get("hand_face_ratio")})'
        )


def gate_face_ratio(out, faces, max_face_ratio, log):
    """Gate 2 — THE cross-character face-flow ratio. Returns the ``cross`` dict.

    Fewer than two measurable faces means a ratio cannot exist, so the check
    passes with a note. Otherwise the lead/lag pair is the argmax/argmin of the
    face medians and the ratio is gated against the cap; a per-pair override is
    looked up under BOTH orderings, because which character leads is an output
    and an override must not silently stop applying on the run where the pair
    flips. Appends ``character_balance:face_ratio`` to ``out['checks']``."""
    cross = {'n_faces': len(faces)}
    if len(faces) < 2:
        cross['ok'] = True
        cross['note'] = (
            f'only {len(faces)} measurable face(s) — a balance ratio needs two; the floor above is all that ran'
        )
        out['checks'].append({'check': 'character_balance:face_ratio', 'ok': True, 'note': cross['note']})
        log(f'[qc_character_balance] face_ratio: {cross["note"]}')
        return cross
    lead = max(faces, key=lambda n: faces[n]['flow_median'])
    lag = min(faces, key=lambda n: faces[n]['flow_median'])
    ratio = faces[lead]['flow_median'] / max(faces[lag]['flow_median'], 1e-6)
    thr = _gate_thr(max_face_ratio, f'{lead}/{lag}', None)
    if thr is None:
        thr = _gate_thr(max_face_ratio, f'{lag}/{lead}', _CHARBAL_FACE_RATIO_MAX)
    ok = not (thr is not None and ratio > float(thr))
    cross.update(
        {
            'face_flow_ratio': round(ratio, 3),
            'lead': lead,
            'lag': lag,
            'lead_flow_median': faces[lead]['flow_median'],
            'lag_flow_median': faces[lag]['flow_median'],
            'lead_flow_mean': faces[lead]['flow_mean'],
            'lag_flow_mean': faces[lag]['flow_mean'],
            'max_ratio': thr,
            'ok': ok,
            'reasons': [],
        }
    )
    if not ok:
        cross['reasons'].append(
            f"{lead}'s face is {ratio:.2f}x as alive as {lag}'s (> {thr}) — "
            f'medians {faces[lead]["flow_median"]:.3f} vs '
            f'{faces[lag]["flow_median"]:.3f}. ONE CHARACTER IS CARRYING THE SHOT; '
            f'{lag} reads as set dressing. This is a PROMPT defect before it is a '
            f'render defect — run qc_beat_prominence on the beats and give {lag} '
            f'the main clause of half of them'
        )
    out['checks'].append(
        {
            'check': 'character_balance:face_ratio',
            'ok': ok,
            'ratio': round(ratio, 3),
            'lead': lead,
            'lag': lag,
            'max_ratio': thr,
            'note': '; '.join(cross['reasons']),
        }
    )
    log(
        f'[qc_character_balance] face_ratio: {ratio:.2f}x '
        f'({lead} {faces[lead]["flow_median"]:.3f} vs {lag} '
        f'{faces[lag]["flow_median"]:.3f}, max {thr}) -> '
        f'{"PASS" if ok else "FAIL"}'
    )
    for r in cross['reasons']:
        log(f'[qc_character_balance]   {r}')
    return cross


def box_suspects(faces):
    """Which face boxes fall outside the calibrated envelope, and why.

    One ``'<name>.face: …'` string per suspect box: too large a share of the
    frame, too little real face in it, or both."""
    suspect = []
    for name, f in faces.items():
        why = []
        if f.get('box_area') is not None and f['box_area'] > _CHARBAL_BOX_AREA_MAX:
            why.append(f'covers {f["box_area"] * 100:.1f}% of the frame (> {_CHARBAL_BOX_AREA_MAX * 100:.0f}%)')
        if f.get('face_fill') is not None and f['face_fill'] < _CHARBAL_FACE_FILL_MIN:
            why.append(f'only {f["face_fill"] * 100:.0f}% of it is face (< {_CHARBAL_FACE_FILL_MIN * 100:.0f}%)')
        if why:
            suspect.append(f'{name}.face: ' + ' and '.join(why))
    return suspect


def judge_box_quality(out, faces, cross, det, log):
    """Box quality — a separate verdict, because a bad box is a broken MEASUREMENT.

    Appends ``character_balance:box_quality``. With suspects it is a FAIL, the
    message lands in ``out['reasons']``, a passing ratio is marked
    ``inconclusive`` and the message is returned so the caller can auto-repair;
    with none it is a PASS and ``None`` comes back."""
    suspect = box_suspects(faces)
    if not suspect:
        out['checks'].append(
            {
                'check': 'character_balance:box_quality',
                'ok': True,
                'suspect': 0,
                'note': 'every face box is inside the calibrated envelope'
                if det and det.get('ok')
                else 'size checked; face_fill NOT checked (verify_boxes off or detector unavailable)',
            }
        )
        return None
    msg = (
        '; '.join(suspect) + ' — a diluted face box drags the median towards the static background '
        "and COMPRESSES the ratio: measured, v11's own production boxes score "
        '1.69 where detector boxes score 2.24, i.e. this gate would have MISSED '
        'the defect it exists for. Re-run with locate_character_faces() boxes '
        'before believing a PASS'
    )
    out['checks'].append({'check': 'character_balance:box_quality', 'ok': False, 'suspect': len(suspect), 'note': msg})
    out['reasons'].append(msg)
    log(f'[qc_character_balance] BOX QUALITY WARNING: {msg}')
    if cross.get('ok'):
        cross['inconclusive'] = True
    return msg
