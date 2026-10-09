# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STEP 1 / 1c — pin and GroundingDINO target derivation, and the crops."""

import json
import os
import time

from zyg_workflows.vlm_report.constants import (
    BOX_PAD,
    GROUND_PROMPTS,
    MAX_HAND_AREA,
    MAX_OBJECT_AREA,
    MAX_PERSON_AREA,
    MIN_CROP_PX,
    PERSON_SIDE,
    PIN_HALF,
    ROLE_PIN_ANCHOR,
)
from zyg_workflows.vlm_report.util import _area, _box_ok, _iou, _pad_box, _pick_candidate, _stable_box

# ── STEP 1: target derivation ────────────────────────────────────────────────


def _pin_targets(meta, char_regions, log):
    """Targets from the AUTHORED intent in shot_metadata.json + caller regions.

    These are what the shot was BUILT to contain, so they exist even when the
    render destroyed the object and a detector can no longer find it — which is
    exactly the case where a detector-only target list would go quiet on the
    defect it should have caught.
    """
    tg = {}

    def _add(role, box, src, note=''):
        if _box_ok(box):
            tg[role] = {
                'name': role,
                'box_frac': [round(float(v), 4) for v in box],
                'source': src,
                'note': note,
                'per_frame': {},
            }

    for role, key in (('bowl', 'bowl_pin'), ('mouth', 'mouth_pin')):
        p = meta.get(key)
        if isinstance(p, (list, tuple)) and len(p) == 2:
            hx, hy = PIN_HALF[role]
            _add(
                role,
                (float(p[0]) - hx, float(p[1]) - hy, float(p[0]) + hx, float(p[1]) + hy),
                'pin',
                f'expanded from {key} point {list(p)} by +-({hx},{hy})',
            )

    for role, key in (('candle', 'candle_box'), ('book', 'book_box'), ('page', 'page_box')):
        b = meta.get(key)
        if isinstance(b, (list, tuple)) and len(b) == 4:
            _add(role, _pad_box(b), 'pin', f'{key} padded by {BOX_PAD}')

    quad = meta.get('page_quad')
    if isinstance(quad, (list, tuple)) and len(quad) >= 3:
        try:
            xs = [float(p[0]) for p in quad]
            ys = [float(p[1]) for p in quad]
            _add(
                'page',
                _pad_box((min(xs), min(ys), max(xs), max(ys))),
                'pin',
                'bbox of page_quad (overrides page_box when both exist)',
            )
        except Exception as e:
            log(f'page_quad unusable ({e})')

    if char_regions:
        # Left-most box is the man, right-most the boy: scene20's blocking is
        # authored ("a grown man sits at the LEFT ... a boy at the RIGHT"), so
        # position is a more reliable key than whatever the caller named them.
        try:
            items = [(k, tuple(float(x) for x in v)) for k, v in char_regions.items() if _box_ok(v)]
            items.sort(key=lambda kv: (kv[1][0] + kv[1][2]) / 2.0)
            if items:
                _add('man', _pad_box(items[0][1]), 'caller', f'char_regions["{items[0][0]}"] (left-most)')
            if len(items) > 1:
                _add('boy', _pad_box(items[-1][1]), 'caller', f'char_regions["{items[-1][0]}"] (right-most)')
        except Exception as e:
            log(f'char_regions unusable ({e})')
    return tg


def _ground_targets(clip_path, times, log, pins=None, score_min=0.25):
    """Targets LOCATED per frame by GroundingDINO, reusing continuity_qc's path.

    continuity_qc owns the loader (_load_gdino), the device policy (pick_device,
    with its 8 GB VRAM floor) and the amortized one-forward-scores-all-prompts
    detector (_detect, whose token-span scoring is what keeps 'lit candle in a
    holder' from collapsing to 'lit candle'). Re-implementing any of that here
    would fork the calibration, so this only CALLS it.

    Returns {role: {'per_frame': {t: {'box','score'}}, 'box_frac': stable box}}.
    """
    out = {}
    try:
        from zyg_workflows import continuity_qc as CQ
    except Exception as e:
        log(f'continuity_qc unavailable ({e}) — pins only, objects will NOT be tracked')
        return out
    try:
        avail = CQ.available()
        if not avail.get('groundingdino') or not avail.get('gdino_weights'):
            log(f'GroundingDINO not installed ({avail}) — pins only')
            return out
        device = CQ.pick_device('auto', log_fn=log)
        model = CQ._load_gdino(device, log_fn=log)
        got, _fps = CQ._frames_at_times(clip_path, times)
        roles = list(GROUND_PROMPTS.keys())
        prompts = [GROUND_PROMPTS[r] for r in roles]
        pins = pins or {}
        per_role = {r: {} for r in roles}
        modes = {r: {} for r in roles}
        hands_per_t = {}
        t0 = time.time()
        for t, _fi, rgb in got:
            tt = round(float(t), 2)
            dets = CQ._detect(model, rgb, prompts, device, score_min, topk=8, log_fn=log)
            for role, det in zip(roles, dets):
                cands = det.get('candidates') or []
                if role == 'hand':
                    # every plausible hand, not just the best one — both people
                    # have two, and the split into sides happens below
                    hands_per_t[tt] = [
                        c
                        for c in cands
                        if c.get('score', 0) >= score_min and _box_ok(c.get('box')) and _area(c['box']) <= MAX_HAND_AREA
                    ]
                    continue
                anchor = None
                anchor_role = ROLE_PIN_ANCHOR.get(role)
                if anchor_role and anchor_role in pins:
                    anchor = pins[anchor_role]['box_frac']
                cand, mode = _pick_candidate(
                    cands,
                    score_min,
                    anchor=anchor,
                    side=PERSON_SIDE.get(role),
                    max_area=(MAX_PERSON_AREA if role in PERSON_SIDE else MAX_OBJECT_AREA),
                )
                modes[role][tt] = mode
                if cand:
                    per_role[role][tt] = {
                        'box': [round(v, 4) for v in cand['box']],
                        'score': cand.get('score'),
                        'mode': mode,
                    }
        log(f'GroundingDINO: {len(got)} frames x {len(prompts)} prompts on {device} in {time.time() - t0:.1f}s')
        for role, pf in per_role.items():
            if role == 'hand':
                continue
            if not pf:
                log(f'  {role}: NOT LOCATED on any sampled frame ({sorted(set(modes[role].values()))})')
                continue
            box = _stable_box([v['box'] for v in pf.values()])
            if not box:
                continue
            mm = [v.get('mode') for v in pf.values()]
            agrees = sum(1 for m in mm if m == 'anchored')
            note = f'GroundingDINO "{GROUND_PROMPTS[role]}" on {len(pf)}/{len(got)} sampled frames'
            if ROLE_PIN_ANCHOR.get(role) in (pins or {}):
                note += f'; agreed with the authored {ROLE_PIN_ANCHOR[role]} pin on {agrees}/{len(pf)} of them'
            out[role] = {
                'name': role,
                'box_frac': [round(v, 4) for v in box],
                'source': 'grounded',
                'per_frame': pf,
                'note': note,
                'agrees_with_pin': (None if ROLE_PIN_ANCHOR.get(role) not in (pins or {}) else agrees == len(pf)),
                'modes': modes[role],
            }
            log(f'  {role}: {out[role]["box_frac"]} ({note})')
        out['_hands_per_t'] = hands_per_t
    except Exception as e:
        log(f'grounding failed ({e}) — pins only')
    return out


def _hand_side_targets(hands_per_t, man_box, boy_box, log):
    """Split grounded hands into the man's and the boy's, per frame.

    A hand belongs to whoever's body box contains its centre; with no person
    boxes at all, the frame's vertical midline is the fallback (scene20 blocking
    is authored left/right). These targets are what make the report able to say
    "the BOY's hand is frozen" rather than "some hand somewhere is frozen", and
    they double as the dense-flow regions in the pixel half.
    """
    out = {}
    if not hands_per_t:
        return out
    sides = {'man_hands': [], 'boy_hands': []}
    per_frame = {'man_hands': {}, 'boy_hands': {}}

    def _inside(box, cx, cy):
        return bool(box) and box[0] <= cx <= box[2] and box[1] <= cy <= box[3]

    def _cdist(box, cx):
        return abs(((box[0] + box[2]) / 2.0) - cx) if box else 9.9

    for t, cands in hands_per_t.items():
        for c in cands:
            b = c['box']
            cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
            in_man, in_boy = _inside(man_box, cx, cy), _inside(boy_box, cx, cy)
            if in_man and in_boy:
                # overlapping torso boxes: the nearer body centre owns the hand
                side = 'man_hands' if _cdist(man_box, cx) <= _cdist(boy_box, cx) else 'boy_hands'
            elif in_man:
                side = 'man_hands'
            elif in_boy:
                side = 'boy_hands'
            else:
                side = 'man_hands' if cx < 0.5 else 'boy_hands'
            sides[side].append(b)
            prev = per_frame[side].get(t)
            if prev is None or c.get('score', 0) > prev.get('score', 0):
                per_frame[side][t] = {'box': b, 'score': c.get('score')}
    for side, boxes in sides.items():
        box = _stable_box(boxes)
        if box:
            out[side] = {
                'name': side,
                'box_frac': [round(v, 4) for v in box],
                'source': 'grounded',
                'per_frame': per_frame[side],
                'note': f'{len(boxes)} grounded "hand" detections assigned '
                f'to this side across {len(per_frame[side])} frames',
            }
    log('hand sides: ' + ', '.join(f'{k}={len(v.get("per_frame") or {})}f' for k, v in out.items()) or 'none')
    return out


def _merge_targets(pins, grounded, W, H, log):
    """Union + dedupe. A pin and a detection of the same object are ONE target.

    The pin wins on IoU >= 0.45 because it is the authored intent (and it stays
    put when the render destroys the object), but it inherits the detection's
    per-frame boxes so its crops still TRACK the object as it moves — which is
    the whole reason grounding is in the loop.
    """
    targets = dict(pins)
    for role, g in grounded.items():
        if role.startswith('_'):
            continue
        pin = targets.get(role)
        if pin is None:
            targets[role] = g
            continue
        if _iou(pin['box_frac'], g['box_frac']) >= 0.45:
            pin['per_frame'] = g.get('per_frame') or {}
            pin['source'] = 'pin+grounded'
            pin['note'] = (pin.get('note', '') + ' | tracked by ' + g['note']).strip(' |')
        else:
            # A detection that disagrees with the pin is EVIDENCE, not noise:
            # keep both and let the report show the disagreement.
            targets[role + '_grounded'] = dict(g, name=role + '_grounded')
            log(
                f'{role}: pin {pin["box_frac"]} and detection {g["box_frac"]} '
                f'disagree (IoU {_iou(pin["box_frac"], g["box_frac"]):.2f}) — '
                f'keeping BOTH as separate targets'
            )
    targets['frame'] = {
        'name': 'frame',
        'box_frac': [0.0, 0.0, 1.0, 1.0],
        'source': 'whole-frame',
        'per_frame': {},
        'note': 'full frame — the crop rule says recall here is '
        'measurably worse; kept only for questions that '
        'need global layout',
    }
    return targets


# ── STEP 1c: crops ───────────────────────────────────────────────────────────


def _crop_name(role, t, src):
    return f'{role}__t{t:06.2f}__{src}.png'.replace(' ', '')


def _make_crops(targets, frames_by_t, crops_dir, log):
    """Save one deterministic PNG per (target, sampled frame).

    Per-frame grounded boxes are used when present so the crop FOLLOWS the
    object; otherwise the target's stable box is used for every frame. Every crop
    is upscaled (LANCZOS) until its long edge reaches MIN_CROP_PX, because a
    120 px crop judged at native resolution loses exactly the detail the crop was
    cut to expose.
    """
    from PIL import Image
    import numpy as np

    os.makedirs(crops_dir, exist_ok=True)
    index = []
    for role, tg in sorted(targets.items()):
        tg['crops'] = []
        for t in sorted(frames_by_t.keys()):
            pf = (tg.get('per_frame') or {}).get(t)
            box = _pad_box(pf['box']) if (pf and _box_ok(pf.get('box'))) else tuple(tg['box_frac'])
            if not _box_ok(box):
                continue
            rgb = frames_by_t[t]
            h, w = rgb.shape[:2]
            x0, y0 = int(box[0] * w), int(box[1] * h)
            x1, y1 = max(x0 + 8, int(box[2] * w)), max(y0 + 8, int(box[3] * h))
            arr = rgb[y0 : min(y1, h), x0 : min(x1, w)]
            if arr.size == 0:
                continue
            im = Image.fromarray(np.ascontiguousarray(arr))
            long_edge = max(im.size)
            if long_edge < MIN_CROP_PX:
                s = float(MIN_CROP_PX) / float(long_edge)
                im = im.resize((max(28, int(im.width * s)), max(28, int(im.height * s))), Image.LANCZOS)
            src = (
                'trk' if pf else ('pin' if 'pin' in tg['source'] else ('gnd' if tg['source'] == 'grounded' else 'box'))
            )
            path = os.path.join(crops_dir, _crop_name(role, t, src))
            im.save(path)
            rec = {
                'target': role,
                't': t,
                'path': path,
                'box_frac': [round(float(v), 4) for v in box],
                'px': list(im.size),
                'tracked': bool(pf),
            }
            tg['crops'].append(rec)
            index.append(rec)
    try:
        with open(os.path.join(crops_dir, 'INDEX.json'), 'w', encoding='utf-8') as f:
            json.dump(
                {
                    '_doc': 'every crop the judge was shown, with the full-frame fractional box it was cut from',
                    'min_crop_px': MIN_CROP_PX,
                    'crops': index,
                },
                f,
                indent=1,
            )
    except Exception as e:
        log(f'could not write crops INDEX.json ({e})')
    log(f'{len(index)} crops derived across {len(targets)} targets -> {crops_dir}')
    return index
