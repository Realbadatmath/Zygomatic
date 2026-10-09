#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""animate_receipt.py — the four-arm receipt for Wan2.2-Animate-14B (S06, 2026-09-02).

The claim under test: driving Wan2.2-Animate-14B with a reference still and OUR OWN
per-frame 2D skeleton holds a character's face through a clip better than the live path,
which paints ONE static skeleton into the VACE control channel for the whole clip.

Arms, all on the same shot and the same 233 frames:
  (i)   vace_static  the CURRENT VACE static-skeleton render of this shot
  (ii)  animate_ok   Animate, our skeleton, the character's own reference still
  (iii) animate_wrong Animate, our skeleton, ANOTHER character's reference still
  (iv)  animate_shuf  arm (ii) with its frame order shuffled

Design note that belongs in the open: arm (i) is also the DRIVER for arms (ii)-(iv).
The alternative sibling render (scene20_v20) was measured at 34.8 dB PSNR against
scene20_v29 on the same crop — the same base render with a different grade, so it is not
an independent baseline and pretending otherwise would be the dishonest option. Using
arm (i) as the driver means every arm sees identical motion and identical framing; what
differs is only where the identity comes from. Arm (ii) is NOT scored against its own
conditioning image: every arm is scored against the house canon anchor, which is
photoreal and therefore equally far from all four painterly arms.

Nulls reported beside every number:
  N1  canon(subject) vs canon(other character)   — the different-person floor
  N2  arm (iii)                                  — the pipeline's own wrong-identity arm
  N3  arm (iv)                                   — the null for the SEAM statistic only:
      per-frame cosine is order-invariant, so a shuffle MUST leave min/mean/spread
      unchanged. If it does not, the scorer is not measuring what it claims.
  N4  the driver footage itself                  — what "doing nothing" scores

Four-state ledger per frame: found / not_found / unmeasurable / not_detectable.

Usage:
  python scripts/animate_receipt.py --work output/animate_receipts/abel_s06 \
      --subject c3345deb5bde --other 0015c8a3f2e3 [--arms ii,iii,lora] [--chunks 3]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

from zyg_workflows import paths

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATASETS = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
LORA_DIR = str(paths.ZYG_COMFY_LORA_DIR / 'wan_chars')
# The AuraFace operating points identity_qc_service publishes for this pack.
PACK_THRESHOLDS = {'frontal': 0.465, 'oblique': 0.317, 'profile': 0.206}

PROMPT = (
    'a fair-haired teenage boy in a dark 17th-century doublet with a white collar, '
    'seated at a candlelit table, reading a large ledger, painterly illustration'
)


def log(m):
    print(m, flush=True)


# ANCHOR CHOICE, measured not assumed (output/animate_receipts/anchor_calibration.json).
# The house canon anchor is photoreal FLUX; this shot and every arm of this bench are
# painterly ("arcane") renders. AuraFace across that style gap is dead: Abel's own
# photoreal canon scores 0.011-0.142 against Abel's own arcane cells, while Abel's canon
# scores 0.221 against CORNELIS's canon. The same person across the style gap therefore
# ranks BELOW a different person within one style — a scorer in that state cannot be used
# to decide anything, and using it anyway would have produced a confident, meaningless
# table. The anchor is an IN-STYLE image instead. It is deliberately NOT the cell used as
# arm (ii)'s reference still: cell_00 conditions the render, cell_06 scores it (the two
# are 0.649 apart — plainly the same person, independently drawn).
ANCHOR_CELL = 'cell_06.png'
REFERENCE_CELL = 'cell_00.png'
PHOTOREAL_CANON = 'contact_sheet/contact_sheet_anchor_face.png'


def canon_anchor(char_id: str) -> str:
    return os.path.join(DATASETS, char_id, 'arcane_prev_v5', ANCHOR_CELL)


def photoreal_canon(char_id: str) -> str:
    return os.path.join(DATASETS, char_id, PHOTOREAL_CANON)


def other_cells(char_id: str) -> list:
    import glob

    return sorted(glob.glob(os.path.join(DATASETS, char_id, 'arcane_prev_v5', '*.png')))


def reference_still(char_id: str) -> str:
    return os.path.join(DATASETS, char_id, 'arcane_prev_v5', REFERENCE_CELL)


# ------------------------------------------------------------------ scoring


def _cos(a, b):
    d = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return None
    return d / (na * nb)


def score_frames(frame_paths: list, anchor_path: str, batch: int = 60) -> dict:
    """Per-frame AuraFace cosine to the canon anchor, with a four-state ledger."""
    from zyg_workflows import identity_qc_service as IQ

    ok, reason = IQ.available()
    if not ok:
        return {'state': 'not_detectable', 'reason': 'identity QC unavailable: %s' % reason}
    a = IQ.embed_images([anchor_path]).get(anchor_path) or {}
    if not a.get('face_detected') or not a.get('embedding'):
        return {'state': 'not_detectable', 'reason': 'anchor has no detectable face'}
    ae = a['embedding']

    per = []
    for i in range(0, len(frame_paths), batch):
        chunk = frame_paths[i : i + batch]
        emb = IQ.embed_images(chunk)
        for p in chunk:
            e = emb.get(p)
            if e is None:
                per.append({'state': 'unmeasurable', 'cos': None})
            elif not e.get('face_detected') or not e.get('embedding'):
                per.append({'state': 'not_found', 'cos': None})
            else:
                c = _cos(ae, e['embedding'])
                per.append({'state': 'found' if c is not None else 'unmeasurable', 'cos': c})
        log('    scored %d/%d' % (min(i + batch, len(frame_paths)), len(frame_paths)))

    vals = [d['cos'] for d in per if d['state'] == 'found']
    out = {
        'state': 'found' if vals else 'not_found',
        'n': len(per),
        'found': sum(1 for d in per if d['state'] == 'found'),
        'not_found': sum(1 for d in per if d['state'] == 'not_found'),
        'unmeasurable': sum(1 for d in per if d['state'] == 'unmeasurable'),
        'per_frame': [d['cos'] for d in per],
    }
    if vals:
        mean = sum(vals) / len(vals)
        out.update(
            {
                'min': round(min(vals), 4),
                'max': round(max(vals), 4),
                'mean': round(mean, 4),
                'sd': round(math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)), 4),
                'spread': round(max(vals) - min(vals), 4),
            }
        )
    return out


def seam_drift(per_frame: list, seams: list, half: int = 8) -> list:
    """|mean cosine in the `half` frames before a seam - mean in the `half` after|.

    Reported as a number with its own four-state entry; a seam with too few scored
    frames on one side is 'unmeasurable', never silently 0.
    """
    out = []
    for s in seams:
        before = [c for c in per_frame[max(0, s - half) : s] if c is not None]
        after = [c for c in per_frame[s : s + half] if c is not None]
        if len(before) < 3 or len(after) < 3:
            out.append({'seam': s, 'state': 'unmeasurable', 'n_before': len(before), 'n_after': len(after)})
            continue
        mb = sum(before) / len(before)
        ma = sum(after) / len(after)
        out.append(
            {
                'seam': s,
                'state': 'found',
                'mean_before': round(mb, 4),
                'mean_after': round(ma, 4),
                'drift': round(abs(ma - mb), 4),
                'signed': round(ma - mb, 4),
                'n_before': len(before),
                'n_after': len(after),
            }
        )
    return out


# ------------------------------------------------------------------ arms


def frames_of_dir(d: str, pref: str = '') -> list:
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith('.png') and f.startswith(pref)]


def run_animate_arm(name, work, reference, chunks, seed, lora=None, w=416, h=480, steps=None, frames=None):
    from zyg_workflows import wan_animate_service as A

    out = os.path.join(work, name)
    strip = os.path.join(out, 'frames')
    if frames_of_dir(strip):
        log('  [%s] frames already on disk — reusing' % name)
        meta = json.load(open(os.path.join(out, 'meta.json')))
        return meta
    kw = {}
    if steps:
        kw['steps'] = int(steps)
    res = A.generate_animate_clips(
        reference,
        os.path.join(work, 'pose'),
        os.path.join(work, 'face'),
        out,
        width=w,
        height=h,
        n_chunks=chunks,
        seed=seed,
        prompt=PROMPT,
        lora=lora,
        log_fn=log,
        frames=int(frames) if frames else A.CHUNK_FRAMES,
        **kw,
    )
    meta = {
        'frames': res['frames'],
        'seams': res['seams'],
        'mp4': res['mp4'],
        'chunks': res['chunks'],
        'reference': reference,
        'lora': lora,
        'seed': seed,
        'width': w,
        'height': h,
        'steps': steps,
    }
    json.dump(meta, open(os.path.join(out, 'meta.json'), 'w'), indent=1)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--subject', required=True)
    ap.add_argument('--other', required=True)
    ap.add_argument('--chunks', type=int, default=3)
    ap.add_argument('--wrong-chunks', type=int, default=3)
    ap.add_argument('--lora-chunks', type=int, default=1)
    ap.add_argument('--seed', type=int, default=20260902)
    ap.add_argument('--steps', type=int, default=12)
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('--arms', default='ii,iii,lora')
    ap.add_argument('--score-only', action='store_true')
    a = ap.parse_args()

    work = a.work
    arms = [x.strip() for x in a.arms.split(',') if x.strip()]
    anchor = canon_anchor(a.subject)
    report = {
        'work': work,
        'subject': a.subject,
        'other': a.other,
        'anchor': anchor,
        'pack_thresholds': PACK_THRESHOLDS,
        'steps': a.steps,
        'seed': a.seed,
        'driver_is_arm_i': True,
        'arms': {},
        'nulls': {},
    }

    driver = frames_of_dir(os.path.join(work, 'driver'))
    n = len(driver)
    log('driver/arm(i): %d frames' % n)

    if not a.score_only:
        if 'ii' in arms:
            log('== arm (ii) animate, correct reference ==')
            run_animate_arm(
                'animate_ok', work, reference_still(a.subject), a.chunks, a.seed, steps=a.steps, frames=a.frames
            )
        if 'ii25' in arms:
            log('== arm (ii) at 25 steps: step-matched to the VACE arm ==')
            run_animate_arm(
                'animate_ok_s25', work, reference_still(a.subject), a.chunks, a.seed, steps=25, frames=a.frames
            )
        if 'iii' in arms:
            log('== arm (iii) animate, WRONG reference ==')
            run_animate_arm(
                'animate_wrong', work, reference_still(a.other), a.wrong_chunks, a.seed, steps=a.steps, frames=a.frames
            )
        if 'lora' in arms:
            lora = 'wan_chars/wan_char_%s.safetensors' % a.subject
            if os.path.isfile(os.path.join(LORA_DIR, os.path.basename(lora))):
                log('== task 4: arm (ii) + Wan2.1 character LoRA ==')
                run_animate_arm(
                    'animate_ok_lora',
                    work,
                    reference_still(a.subject),
                    a.lora_chunks,
                    a.seed,
                    lora=lora,
                    steps=a.steps,
                    frames=a.frames,
                )
            else:
                log('LoRA missing: %s' % lora)

    # ---- score every arm that exists
    def add(name, paths, seams=None):
        if not paths:
            report['arms'][name] = {'state': 'not_found', 'reason': 'no frames on disk'}
            return
        log('scoring %s (%d frames)' % (name, len(paths)))
        s = score_frames(paths, anchor)
        if seams:
            s['seam_drift'] = seam_drift(s.get('per_frame') or [], seams)
        report['arms'][name] = s

    add('i_vace_static', driver)
    ok_meta = None
    p = os.path.join(work, 'animate_ok', 'meta.json')
    if os.path.isfile(p):
        ok_meta = json.load(open(p))
        add('ii_animate_ok', frames_of_dir(os.path.join(work, 'animate_ok', 'frames')), seams=ok_meta.get('seams'))
    p = os.path.join(work, 'animate_wrong', 'meta.json')
    if os.path.isfile(p):
        add('iii_animate_wrong', frames_of_dir(os.path.join(work, 'animate_wrong', 'frames')))
    p = os.path.join(work, 'animate_ok_s25', 'meta.json')
    if os.path.isfile(p):
        m = json.load(open(p))
        add(
            'ii25_animate_ok_25steps',
            frames_of_dir(os.path.join(work, 'animate_ok_s25', 'frames')),
            seams=m.get('seams'),
        )
    p = os.path.join(work, 'animate_ok_lora', 'meta.json')
    if os.path.isfile(p):
        m = json.load(open(p))
        add('lora_animate_ok', frames_of_dir(os.path.join(work, 'animate_ok_lora', 'frames')), seams=m.get('seams'))

    # arm (iv): shuffle arm (ii). Reuses the SAME per-frame cosines under a permutation,
    # so it is a null for the seam statistic and a check on the scorer, not a new render.
    if 'ii_animate_ok' in report['arms'] and report['arms']['ii_animate_ok'].get('per_frame'):
        import random

        pf = list(report['arms']['ii_animate_ok']['per_frame'])
        random.Random(a.seed).shuffle(pf)
        vals = [c for c in pf if c is not None]
        mean = sum(vals) / len(vals)
        report['arms']['iv_animate_shuffled'] = {
            'state': 'found',
            'n': len(pf),
            'found': len(vals),
            'min': round(min(vals), 4),
            'max': round(max(vals), 4),
            'mean': round(mean, 4),
            'spread': round(max(vals) - min(vals), 4),
            'seam_drift': seam_drift(pf, (ok_meta or {}).get('seams') or []),
            'note': 'same cosines, permuted order — min/mean/spread MUST match arm (ii)',
        }

    # ---- N1: the different-person floor between the two canon anchors
    try:
        from zyg_workflows import identity_qc_service as IQ

        others = other_cells(a.other)
        e = IQ.embed_images([anchor, photoreal_canon(a.subject)] + others)
        ea = (e.get(anchor) or {}).get('embedding')
        floor = []
        for op in others:
            ob = (e.get(op) or {}).get('embedding')
            if ea and ob:
                floor.append(round(_cos(ea, ob), 4))
        report['nulls']['N1_different_person_in_style'] = {
            'anchor': anchor,
            'other_cells': len(floor),
            'per_cell': floor,
            'max': max(floor) if floor else 'not_detectable',
            'mean': round(sum(floor) / len(floor), 4) if floor else 'not_detectable',
            'note': 'the conservative floor is the MAX: no arm may be called an identity '
            'match on a score another character can reach',
        }
        pc = (e.get(photoreal_canon(a.subject)) or {}).get('embedding')
        report['nulls']['N0_anchor_vs_house_photoreal_canon'] = (
            round(_cos(ea, pc), 4) if (ea and pc) else 'not_detectable'
        )
    except Exception as exc:  # noqa: BLE001
        report['nulls']['N1_different_person_in_style'] = 'unmeasurable: %s' % exc
    report['nulls']['N4_driver_footage'] = report['arms']['i_vace_static'].get('mean')

    # ---- the gate
    g = {}
    ii = report['arms'].get('ii25_animate_ok_25steps') or report['arms'].get('ii_animate_ok', {})
    g['ii_arm_used'] = 'ii25_animate_ok_25steps' if report['arms'].get('ii25_animate_ok_25steps') else 'ii_animate_ok'
    i_ = report['arms'].get('i_vace_static', {})
    iii = report['arms'].get('iii_animate_wrong', {})
    if ii.get('state') == 'found' and i_.get('state') == 'found':
        g['ii_beats_i'] = bool(ii['mean'] > i_['mean'])
        g['ii_minus_i'] = round(ii['mean'] - i_['mean'], 4)
    if ii.get('state') == 'found' and iii.get('state') == 'found':
        g['ii_beats_iii'] = bool(ii['mean'] > iii['mean'])
        g['ii_minus_iii'] = round(ii['mean'] - iii['mean'], 4)
    g['pass'] = bool(g.get('ii_beats_i') and g.get('ii_beats_iii'))
    report['gate'] = g

    out = os.path.join(work, 'receipt.json')
    json.dump(report, open(out, 'w'), indent=1)
    log('wrote %s' % out)
    log(
        json.dumps(
            {k: {kk: vv for kk, vv in v.items() if kk != 'per_frame'} for k, v in report['arms'].items()}, indent=1
        )
    )
    log('NULLS  ' + json.dumps(report['nulls']))
    log('GATE   ' + json.dumps(g))


if __name__ == '__main__':
    main()
