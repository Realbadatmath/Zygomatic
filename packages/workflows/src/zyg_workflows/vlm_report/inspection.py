# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""STEP 2 / 3 — the per-crop VLM judging pass and the pixel-metric pass."""

import json
import os

from zyg_workflows.vlm_report.constants import GROUND_PROMPTS, ITEM_TARGETS, MAX_LOCALIZE_FRAMES
from zyg_workflows.vlm_report.util import _c01, _seam_pairs

# ── STEP 2: inspection ───────────────────────────────────────────────────────


def _checklist_doc(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write_subset_checklist(doc, name, item_ids, out_path, suffix):
    """A single-target checklist file: same preamble, same WORDING, fewer items.

    Wording is never touched — the calibration note in vlm_checklists.json is
    explicit that "sharpening" hand_covers_bowl dropped its recall from 5/5 to
    0/2. All this does is choose which questions are asked about which crop.
    """
    cl = (doc.get('checklists') or {}).get(name) or {}
    items = [i for i in (cl.get('items') or []) if i.get('id') in item_ids]
    if not items:
        return None
    sub = f'{name}__{suffix}'
    payload = {
        'checklists': {
            sub: {'description': cl.get('description', ''), 'preamble': cl.get('preamble', ''), 'items': items}
        }
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    return sub


class _ChecklistPath(object):
    """Temporarily point vlm_inspector at a generated checklist file.

    inspect_frames() resolves the checklist through the module-level
    _CHECKLIST_PATH (env ZYG_VLM_CHECKLISTS, read at import time) and exposes no
    `path` argument, so this is the supported way to hand it a per-target subset
    without editing vlm_inspector or duplicating its worker plumbing. Both the
    env var and the already-imported module attribute are swapped, and both are
    restored, so nothing leaks to another caller in the same process.
    """

    def __init__(self, VLM, path):
        self.VLM, self.path = VLM, path
        self._old_attr = None
        self._old_env = None

    def __enter__(self):
        self._old_attr = getattr(self.VLM, '_CHECKLIST_PATH', None)
        self._old_env = os.environ.get('ZYG_VLM_CHECKLISTS')
        self.VLM._CHECKLIST_PATH = self.path
        os.environ['ZYG_VLM_CHECKLISTS'] = self.path
        return self

    def __exit__(self, *a):
        if self._old_attr is not None:
            self.VLM._CHECKLIST_PATH = self._old_attr
        if self._old_env is None:
            os.environ.pop('ZYG_VLM_CHECKLISTS', None)
        else:
            os.environ['ZYG_VLM_CHECKLISTS'] = self._old_env
        return False


def _remap_bbox(bbox_crop, crop_box):
    """Judge box (0..1 of the CROP) -> full-frame fractional box.

    vlm_worker.parse_bbox has already turned Qwen3-VL's RELATIVE 0-1000 output
    into 0..1 of the image the vision tower saw. That image is the crop, so:

        full_x = cx0 + bx * (cx1 - cx0)
        full_y = cy0 + by * (cy1 - cy0)

    The LANCZOS upscale is uniform, so it cancels out and never appears here.
    """
    if not (bbox_crop and len(bbox_crop) == 4 and crop_box and len(crop_box) == 4):
        return None
    cx0, cy0, cx1, cy1 = [float(v) for v in crop_box]
    bw, bh = (cx1 - cx0), (cy1 - cy0)
    bx0, by0, bx1, by1 = [float(v) for v in bbox_crop]
    return [
        round(_c01(cx0 + bx0 * bw), 4),
        round(_c01(cy0 + by0 * bh), 4),
        round(_c01(cx0 + bx1 * bw), 4),
        round(_c01(cy0 + by1 * bh), 4),
    ]


def _inspect(VLM, crops, sub_name, cl_path, tier, k, refs, log_fn):
    """One inspect_frames call on a set of crops with a generated checklist."""
    with _ChecklistPath(VLM, cl_path):
        return VLM.inspect_frames(
            [c['path'] for c in crops],
            checklist=sub_name,
            tier=tier,
            offload=False,
            ref_images=refs,
            frame_kind='beats',
            k=k,
            log_fn=log_fn,
        )


def _run_inspection(VLM, targets, checklist, cl_doc, tier, k_critical, refs, work_dir, log, log_fn):
    """Screen every target, then localize whatever failed.

    PASS 1 (screen): one call per (target, severity-bucket) over ALL that
    target's crops. Critical items get k=k_critical, majors k=1 — the ensemble is
    spent only where a wrong answer costs a delivery. inspect_frames itself runs
    the worker k times and majority-votes (it does not forward the worker's own
    --k flag), so this is the "call it k times and vote" branch of the contract.

    PASS 2 (localize): a failed item is re-asked on ONE crop at a time, so the
    report can name the timestamp and so the grounding box belongs to that crop
    (vlm_worker always grounds on images[0]).
    """
    items_by_id = {i['id']: i for i in (((cl_doc.get('checklists') or {}).get(checklist) or {}).get('items') or [])}
    results = []
    n_calls = 0
    for role, tg in sorted(targets.items()):
        crops = tg.get('crops') or []
        if not crops:
            continue
        mine = [iid for iid, roles in ITEM_TARGETS.items() if role in roles and iid in items_by_id]
        if not mine:
            continue
        for bucket, k in (('critical', max(1, int(k_critical))), ('major', 1)):
            ids = [i for i in mine if str(items_by_id[i].get('severity', 'major')).lower() == bucket]
            if not ids:
                continue
            cl_path = os.path.join(work_dir, f'cl_{role}_{bucket}.json')
            sub = _write_subset_checklist(cl_doc, checklist, ids, cl_path, f'{role}_{bucket}')
            if not sub:
                continue
            log(f'PASS1 {role}/{bucket}: {len(ids)} item(s) x {len(crops)} crops, k={k}')
            res = _inspect(VLM, crops, sub, cl_path, tier, k, refs, log_fn)
            n_calls += 0 if res.get('skipped') else k
            if res.get('skipped'):
                # A skip is EVIDENCE (identity needs reference portraits; a GPU
                # tier refuses while ComfyUI samples). Recording it keeps the
                # report honest about what was never asked, instead of letting an
                # unasked question look like a passing one.
                log(f'  SKIPPED ({res.get("reason")})')
                for iid in ids:
                    results.append(
                        {
                            'item': iid,
                            'target': role,
                            'phase': 'screen',
                            'answer': None,
                            'expected': None,
                            'ok': None,
                            'severity': bucket,
                            'reason': '',
                            'votes': None,
                            'k': k,
                            'bbox_crop': None,
                            'crops': [c['path'] for c in crops],
                            'times': [c['t'] for c in crops],
                            'tier': None,
                            'model': None,
                            'skipped': True,
                            'skip_reason': res.get('reason'),
                        }
                    )
                continue
            for v in res.get('verdicts') or []:
                results.append(
                    {
                        'item': v.get('id'),
                        'target': role,
                        'phase': 'screen',
                        'answer': v.get('answer'),
                        'expected': v.get('expected'),
                        'ok': v.get('ok'),
                        'severity': v.get('severity'),
                        'reason': v.get('reason'),
                        'votes': v.get('votes'),
                        'k': k,
                        'bbox_crop': v.get('bbox'),
                        'crops': [c['path'] for c in crops],
                        'times': [c['t'] for c in crops],
                        'tier': res.get('tier'),
                        'model': res.get('model'),
                        'skipped': bool(res.get('skipped')),
                        'skip_reason': res.get('reason'),
                    }
                )
    # ---- PASS 2 -------------------------------------------------------------
    localized = []
    for r in results:
        if r['ok'] is not False or r['skipped']:
            continue
        role = r['target']
        tg = targets.get(role) or {}
        crops = (tg.get('crops') or [])[:MAX_LOCALIZE_FRAMES]
        if len(crops) <= 1:
            continue
        iid = r['item']
        k = max(1, int(k_critical)) if r['severity'] == 'critical' else 1
        cl_path = os.path.join(work_dir, f'cl_loc_{role}_{iid}.json')
        sub = _write_subset_checklist(cl_doc, checklist, [iid], cl_path, f'loc_{role}_{iid}')
        if not sub:
            continue
        log(f'PASS2 localize {iid} on {role}: {len(crops)} single-crop calls, k={k}')
        hits = []
        for c in crops:
            res = _inspect(VLM, [c], sub, cl_path, tier, k, refs, log_fn)
            n_calls += 0 if res.get('skipped') else k
            for v in res.get('verdicts') or []:
                rec = {
                    'item': iid,
                    'target': role,
                    'phase': 'localize',
                    't': c['t'],
                    'crop': c['path'],
                    'crop_box': c['box_frac'],
                    'answer': v.get('answer'),
                    'expected': v.get('expected'),
                    'ok': v.get('ok'),
                    'severity': v.get('severity'),
                    'reason': v.get('reason'),
                    'votes': v.get('votes'),
                    'k': k,
                    'bbox_crop': v.get('bbox'),
                    'bbox_full': _remap_bbox(v.get('bbox'), c['box_frac']),
                    'tier': res.get('tier'),
                    'model': res.get('model'),
                }
                localized.append(rec)
                if v.get('ok') is False:
                    hits.append(rec)
        r['localized_fail_times'] = [h['t'] for h in hits]
        r['localized_boxes'] = [h['bbox_full'] for h in hits if h.get('bbox_full')]
        r['localized_n'] = len(crops)
        if not hits:
            # Honest and important: the screen pass saw the defect across the set
            # but no single frame reproduced it. Report the disagreement rather
            # than silently keeping the louder answer.
            r['localize_note'] = 'screen FAILED but no single frame reproduced it - treat as low-confidence'
    return results, localized, n_calls


# ── STEP 3: pixel metrics ────────────────────────────────────────────────────


def _flow_regions(targets):
    """(regions, min_flow) for pipeline_debug.qc_region_flow.

    min_flow is per-region on purpose: 0.12 px/sample is the calibrated
    hands/props floor, heads get 0.06 (calm heads legitimately move less), and
    world-static props (candle/book/page) get 0.0 — demanding that a pinned
    ledger MOVE would manufacture a failure. Their edge-churn gate still applies,
    which is the measurement that actually matters for a static prop.
    """
    regions, min_flow = {}, {}
    for role in ('man_hands', 'boy_hands', 'pipe', 'quill', 'bowl'):
        tg = targets.get(role)
        if tg:
            regions[role] = tuple(tg['box_frac'])
            min_flow[role] = 0.12
    for role, person in (('man_head', 'man'), ('boy_head', 'boy')):
        tg = targets.get(person)
        if tg:
            x0, y0, x1, y1 = tg['box_frac']
            regions[role] = (x0, y0, x1, y0 + 0.34 * (y1 - y0))
            min_flow[role] = 0.06
    for role in ('candle', 'book', 'page'):
        tg = targets.get(role)
        if tg:
            regions[role] = tuple(tg['box_frac'])
            min_flow[role] = 0.0
    return regions, min_flow


def _pixel_metrics(clip_path, targets, meta, dur, n_people, log, log_fn, run_continuity=False):
    """Everything the judge is blind to: motion, morph, anatomy, ownership."""
    out = {
        'region_flow': None,
        'prop_consistency': {},
        'hands': None,
        'action_ownership': None,
        'continuity': None,
        'errors': [],
    }
    try:
        from zyg_workflows import pipeline_debug as PD
    except Exception as e:
        out['errors'].append(f'pipeline_debug unavailable: {e}')
        PD = None

    if PD is not None:
        regions, min_flow = _flow_regions(targets)
        if regions:
            try:
                out['region_flow'] = PD.qc_region_flow(clip_path, regions, min_flow=min_flow, log_fn=log_fn)
                out['region_flow']['_min_flow'] = min_flow
            except Exception as e:
                out['errors'].append(f'qc_region_flow: {e}')
        pairs = _seam_pairs(dur)
        for role in ('pipe', 'candle', 'book'):
            tg = targets.get(role)
            if not tg:
                continue
            try:
                out['prop_consistency'][role] = PD.qc_prop_consistency(
                    clip_path, tuple(tg['box_frac']), pairs=pairs, log_fn=log_fn
                )
            except Exception as e:
                out['errors'].append(f'qc_prop_consistency[{role}]: {e}')
        out['_seam_pairs'] = pairs

    try:
        from zyg_workflows import anatomy_qc as AQ

        out['hands'] = AQ.qc_hands_clip(clip_path, n_people, sample_every=8, log_fn=log_fn)
    except Exception as e:
        out['errors'].append(f'anatomy_qc.qc_hands_clip: {e}')

    # Grounded "who owns the pipe" — the pixel witness for the boy_smoking
    # critical. Cheap (GroundingDINO only, a handful of timestamps), so it runs
    # by default unlike the SAM2/DINOv2 suite.
    try:
        from zyg_workflows import continuity_qc as CQ

        times = [float(t) for t in (meta.get('draw_times') or [])]
        if not times and dur:
            times = [round(dur * f, 2) for f in (0.25, 0.55, 0.85)]
        times = [t for t in times if 0 <= t < max(0.0, dur - 0.05)]
        if times:
            out['action_ownership'] = CQ.action_ownership(
                clip_path,
                {'man': GROUND_PROMPTS['man'], 'boy': GROUND_PROMPTS['boy']},
                GROUND_PROMPTS['pipe'],
                times,
                expected_owner='man',
                log_fn=log_fn,
            )
    except Exception as e:
        out['errors'].append(f'continuity_qc.action_ownership: {e}')

    if run_continuity:
        try:
            from zyg_workflows import continuity_qc as CQ

            objs = [{'name': r, 'ground_prompt': GROUND_PROMPTS[r]} for r in ('pipe', 'candle', 'book') if r in targets]
            if objs:
                out['continuity'] = CQ.analyze_clip(clip_path, objs, sample_fps=2, log_fn=log_fn)
        except Exception as e:
            out['errors'].append(f'continuity_qc.analyze_clip: {e}')
    return out
