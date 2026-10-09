# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""region_vlm.py — the G4 pass at scale: every readable region, judged (2026-08-05).

RUN:
    python3 -m zyg_workflows.geom.region_vlm <char_id> [--regions eye_left,eye_right,lips,nose]
                               [--limit N] [--tier resident]

THE QUESTION THIS ANSWERS. The deterministic gates prove a region EXISTS and is readable
at its scale; none of them can say whether the pixels inside it still LOOK like the thing
— an eye region that survived the restyle as a smear passes G1 with flying colours. So
every readable region crop goes to the local judge with one closed question ("does this
crop show a human eye?"), THE CROP RULE applied at region grain: the judge measured 5/5
on crops against 0/2 on full frames, and a region crop is the tightest crop there is.

MECHANICS. Crops come straight off regions.png bboxes (pad 40%, upscale to >=224px so the
judge sees pixels, not thumbnails). Questions go through vlm_inspector's persistent
resident-tier server — the same worker pool the render QC trusts, with its VRAM guards.
Verdicts append to the cell's mesh.json under `region_vlm` and aggregate into
region_vlm_report.json per character.

FAILURE SEMANTICS, same contract as every judge here: the judge being unavailable SKIPS
(recorded as skipped, never fabricated); a NO from the judge is a real finding. This is a
reject-only second opinion — it flags, it never blocks.
"""

import argparse
import glob
import json
import os
import sys
import time

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from . import regions as R
from .char_mesh import OUT_ROOT
from .gate_character import AREA_FLOOR
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# region -> what the judge is asked. Closed, one clause, no styling escape hatch: the
# whole POINT is judging whether the region survived the styling.
QUESTIONS = {
    'eye_left': 'a human eye (an iris and eyelid should be recognisable)',
    'eye_right': 'a human eye (an iris and eyelid should be recognisable)',
    'lips': 'a human mouth / lips',
    'nose': 'a human nose',
    'ear_left': 'a human ear',
    'ear_right': 'a human ear',
    'hair_head': 'human hair on a head',
}
DEFAULT_REGIONS = ('eye_left', 'eye_right', 'lips', 'nose', 'ear_left', 'ear_right')


def _crop(img, rm, rid, pad=0.40, min_px=224):
    m = rm == rid
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    pw, ph_ = int((x1 - x0 + 1) * pad) + 4, int((y1 - y0 + 1) * pad) + 4
    x0, y0 = max(0, x0 - pw), max(0, y0 - ph_)
    x1, y1 = min(img.shape[1], x1 + pw), min(img.shape[0], y1 + ph_)
    c = img[y0:y1, x0:x1]
    if c.size == 0:
        return None
    if min(c.shape[:2]) < min_px:
        f = min_px / min(c.shape[:2])
        c = cv2.resize(c, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return c


def judge_cell(cell_dir, region_names, tier, tmp_dir, log):
    from zyg_workflows import vlm_inspector as V

    with open(os.path.join(cell_dir, 'mesh.json')) as f:
        mesh = json.load(f)
    rm = cv2.imread(os.path.join(cell_dir, 'regions.png'), cv2.IMREAD_GRAYSCALE)
    img = cv2.imread(mesh['image'])
    if rm is None or img is None:
        return {}

    results = {}
    for reg in region_names:
        rid = R.REGION_IDX[reg]
        area = int((rm == rid).sum())
        if area < AREA_FLOOR.get(reg, 50):
            continue  # unreadable at this framing — G1's verdict
        crop = _crop(img, rm, rid)
        if crop is None:
            continue
        cp = os.path.join(tmp_dir, '%s_%s.png' % (os.path.basename(cell_dir), reg))
        cv2.imwrite(cp, crop)
        q = [
            {
                'id': 'region_reads',
                'question': 'Does this image crop clearly show %s? The image may be a '
                'painterly/animated style; judge the anatomy, not the style.' % QUESTIONS[reg],
                'expected': 'yes',
                'severity': 'major',
                'grounding': False,
            }
        ]
        res = V._run_worker(V.model_for(tier), [cp], q, tier, log)
        if not res:
            results[reg] = {'verdict': 'skipped', 'area': area}
            continue
        verd = res.get('verdicts') or res.get('answers') or []
        ans = ''
        for v in verd:
            ans = str(v.get('answer', '')).strip().lower()
            break
        results[reg] = {'verdict': 'pass' if ans.startswith('y') else 'fail', 'answer': ans[:60], 'area': area}
        try:
            os.remove(cp)
        except OSError as _exc:
            _zyg_log.debug('region crop cleanup skipped: %s', _exc)
    if results:
        mesh['region_vlm'] = {'tier': tier, 'date': time.strftime('%Y-%m-%d'), 'results': results}
        with open(os.path.join(cell_dir, 'mesh.json'), 'w') as f:
            json.dump(mesh, f)
    return results


def run(char_id, region_names=DEFAULT_REGIONS, tier='resident', limit=0, log=print):
    try:
        from zyg_workflows import vlm_inspector as V

        if not (V.available() and V._enabled()):
            _zyg_log.info('judge unavailable — recording nothing, fabricating nothing')
            return None
    except Exception as e:
        _zyg_log.info('judge unimportable (%s) — aborting pass' % e)
        return None

    root = os.path.join(OUT_ROOT, char_id)
    cells = sorted(d for d in glob.glob(os.path.join(root, 'cell_*')) if os.path.isdir(d))
    if limit:
        cells = cells[:limit]
    tmp = os.path.join(root, '_vlm_crops')
    os.makedirs(tmp, exist_ok=True)

    agg = {r: {'pass': 0, 'fail': 0, 'skipped': 0, 'fails': []} for r in region_names}
    t0 = time.time()
    for c in cells:
        res = judge_cell(c, region_names, tier, tmp, lambda m: None)
        for reg, v in res.items():
            agg[reg][v['verdict']] = agg[reg].get(v['verdict'], 0) + 1
            if v['verdict'] == 'fail':
                agg[reg]['fails'].append(os.path.basename(c))
    doc = {
        'char_id': char_id,
        'tier': tier,
        'cells': len(cells),
        'seconds': round(time.time() - t0, 1),
        'date': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'regions': agg,
    }
    with open(os.path.join(root, 'region_vlm_report.json'), 'w') as f:
        json.dump(doc, f, indent=1)
    for reg, a in agg.items():
        tot = a['pass'] + a['fail']
        _zyg_log.info(
            '  %-10s %d judged: %d pass, %d fail %s'
            % (reg, tot, a['pass'], a['fail'], ('-> ' + ','.join(a['fails'][:6])) if a['fails'] else '')
        )
    try:
        from zyg_workflows import vlm_inspector as V

        V.shutdown_workers()
    except Exception as _exc:
        _zyg_log.warning('vlm worker shutdown failed, judge vram may stay held: %s', _exc)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--regions', default=','.join(DEFAULT_REGIONS))
    ap.add_argument('--tier', default='resident')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args(argv)
    doc = run(a.char_id, tuple(r.strip() for r in a.regions.split(',') if r.strip()), a.tier, a.limit)
    return 0 if doc else 1


if __name__ == '__main__':
    sys.exit(main())
