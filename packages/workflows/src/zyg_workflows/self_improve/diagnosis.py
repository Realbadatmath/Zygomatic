# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""VLM narrative, diagnose, and the next-attempt brief.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import json
import os
import time
import logging as _zyg_logging

from zyg_workflows.self_improve.base import _jsonable, _mklog, _write_json, _write_text
from zyg_workflows.self_improve.remedies import _explain, kb, kb_match
from zyg_workflows.self_improve.signature import build_signature
from zyg_workflows.self_improve.planning import plan_next_attempt

_zyg_log = _zyg_logging.getLogger('zyg_workflows.self_improve')


# ══════════════════════════════════════════════════════════════════════════════
# 9.  VLM NARRATIVE (contract-defensive)
# ══════════════════════════════════════════════════════════════════════════════


def _run_vlm(run_dir, clip_path, signature, tier='resident', checklist='scene20_binary', beat_times=None, log_fn=None):
    """vlm_report.analyze_render if it exists; otherwise a clearly-marked skip.

    Refuses the GPU while ComfyUI is sampling (comfy_offload.comfy_is_sampling) —
    a judge that steals VRAM from a 90-minute render is worse than no judge."""
    log = _mklog(log_fn)
    try:
        from zyg_workflows import vlm_report as VR
    except Exception as e:
        log(f'[self_improve] vlm_report unavailable ({e}) — pixel evidence only')
        return {'ok': False, 'skipped': True, 'reason': f'vlm_report_unavailable:{e}'}
    try:
        from zyg_workflows import comfy_offload as CO

        if CO.comfy_is_sampling():
            log('[self_improve] ComfyUI is sampling — VLM refused (comfy_sampling)')
            return {'ok': False, 'skipped': True, 'reason': 'comfy_sampling'}
    except Exception as _exc:
        _zyg_log.warning('comfy sampling check failed, running the VLM without it: %s', _exc)
    regions = (signature.get('qc_spec') or {}).get('regions') or {}
    char_regions = {k: list(v) for k, v in regions.items()}
    try:
        return VR.analyze_render(
            clip_path=clip_path,
            shot_metadata_path=os.path.join(run_dir, 'shot_metadata.json'),
            out_dir=os.path.join(run_dir, 'vlm_report'),
            char_regions=char_regions,
            checklist=checklist,
            tier=tier,
            beat_times=beat_times,
            log_fn=log,
        )
    except Exception as e:
        log(f'[self_improve] vlm_report.analyze_render failed ({e})')
        return {'ok': False, 'skipped': True, 'reason': f'error:{e}'}


# ══════════════════════════════════════════════════════════════════════════════
# 10.  diagnose
# ══════════════════════════════════════════════════════════════════════════════


def diagnose(
    run_dir,
    clip_path=None,
    raw_clip=None,
    params=None,
    regions=None,
    use_vlm=True,
    tier='resident',
    checklist='scene20_binary',
    beat_times=None,
    record_attempts=False,
    log_fn=None,
):
    """Full read of one finished run: signature (evidence) + VLM report
    (narrative) + ranked remedies + a next-attempt plan.

    Writes <run_dir>/diagnosis.json and <run_dir>/NEXT_ATTEMPT.md.
    Returns {'ok','signature','vlm','remedies','plan','explanations'}."""
    log = _mklog(log_fn)
    run_dir = os.path.abspath(run_dir)
    res = {'ok': False, 'run_dir': run_dir, 'when': time.strftime('%Y-%m-%d %H:%M:%S')}
    try:
        sig = build_signature(
            run_dir, clip_path=clip_path, raw_clip=raw_clip, params=params, regions=regions, log_fn=log
        )
        res['signature'] = sig
        if not sig.get('ok'):
            res['error'] = sig.get('error', 'signature failed')
            _write_json(os.path.join(run_dir, 'diagnosis.json'), res, log)
            return res

        res['vlm'] = (
            _run_vlm(run_dir, sig['clip'], sig, tier=tier, checklist=checklist, beat_times=beat_times, log_fn=log)
            if use_vlm
            else {'ok': False, 'skipped': True, 'reason': 'use_vlm=False'}
        )
        # the VLM's verdict is EVIDENCE too — inject it into the signature (contract
        # key 'vlm') BEFORE matching, so judge-conditioned rules can fire.
        v = res['vlm'] or {}
        if v.get('ok'):
            nf = vlm_findings(v)
            sig['vlm'] = {
                'flags': list(v.get('flags') or [f['id'] for f in nf if f['ok'] is False and f['id']]),
                'findings': [
                    {
                        'id': f['id'],
                        'severity': f['severity'],
                        'bbox': f['bbox'],
                        'where': f['where'],
                        'source': f['source'],
                    }
                    for f in nf
                ],
                'verdict': v.get('verdict'),
            }

        kbo = kb(log_fn=log)
        res['kb'] = getattr(kbo, 'name', getattr(kbo, '__name__', 'unknown'))
        remedies = kb_match(kbo, sig, log_fn=log)
        res['remedies'] = remedies
        res['explanations'] = [_explain(kbo, r) for r in remedies]

        base = dict(params or sig.get('params') or {})
        res['plan'] = plan_next_attempt(res, base, record_attempts=record_attempts, log_fn=log)

        res['findings'] = _merge_findings(sig, res.get('vlm') or {})
        res['ok'] = True
        _write_json(os.path.join(run_dir, 'diagnosis.json'), res, log)
        _write_text(os.path.join(run_dir, 'NEXT_ATTEMPT.md'), render_next_attempt_md(res), log)
        log(f'[self_improve] diagnosis written → {run_dir}/diagnosis.json + NEXT_ATTEMPT.md')
    except Exception as e:
        import traceback

        res['error'] = str(e)[:300]
        res['traceback'] = traceback.format_exc()[-1500:]
        log(f'[self_improve] diagnose failed: {e}')
    return res


def vlm_findings(vlm):
    """vlm_report's findings, normalised — it ships a RICHER shape than the agreed
    contract and both must keep working.

        contract : {id, source, severity, ok, where, reason, bbox}
        shipped  : {id, region, defect_class, severity, status, source,
                    signals[{source,name,status,reason,...}], evidence, boxes, times}

    `source` is re-labelled into this module's attribution vocabulary so a reader
    can always tell which EYE saw a thing — vlm_report runs pixel checks of its
    own, and folding those in under a bare 'pixel' tag beside pipeline_debug's
    would erase exactly the distinction the report exists to make:
        vlm    → vlm:vlm_report      (the judge)
        pixel  → pixel:vlm_report    (its own continuity/anatomy metrics)
        both   → fused:vlm_report    (judge and metric agree)
    `reason` is rebuilt from the failing signals when the finding has no prose."""
    out = []
    for f in (vlm or {}).get('findings') or []:
        if not isinstance(f, dict):
            continue
        ok = f.get('ok')
        if ok is None:
            st = str(f.get('status', '')).lower()
            ok = True if st == 'pass' else (False if st in ('fail', 'failed') else None)
        reason = f.get('reason')
        if not reason:
            bad = [s for s in (f.get('signals') or []) if str(s.get('status', '')).lower() in ('fail', 'failed')]
            parts = []
            for s in (bad or (f.get('signals') or []))[:2]:
                r = s.get('reason') or s.get('note')
                if r:
                    parts.append(f'{s.get("source", "?")}/{s.get("name", "?")}: {r}')
                elif s.get('measured') is not None:
                    parts.append(
                        f'{s.get("source", "?")}/{s.get("name", "?")}: {json.dumps(_jsonable(s["measured"]))[:160]}'
                    )
            reason = (
                ' | '.join(parts)
                or str(f.get('evidence') or '')[:200]
                or f'{f.get("defect_class", "defect")} on {f.get("region", "frame")}'
            )
        bbox = f.get('bbox')
        if bbox is None and f.get('boxes'):
            b = f['boxes']
            bbox = b[0] if isinstance(b, list) and b else b
        src = str(f.get('source') or 'vlm')
        src = {'vlm': 'vlm:vlm_report', 'pixel': 'pixel:vlm_report', 'both': 'fused:vlm_report'}.get(
            src, f'vlm_report:{src}'
        )
        out.append(
            {
                'id': f.get('id'),
                'source': src,
                'severity': f.get('severity'),
                'ok': ok,
                'where': f.get('where') or f.get('region'),
                'reason': reason,
                'bbox': bbox,
                'defect_class': f.get('defect_class'),
                'times': f.get('times'),
                'caveats': f.get('caveats'),
            }
        )
    return out


def _merge_findings(signature, vlm):
    """One list, every finding ATTRIBUTED to the instrument that saw it.

    The judge is blind to some defects (ink) and weak on temporal ones; the pixel
    gates are blind to semantics. A report that does not say which eye saw what
    is not evidence, so `source` is mandatory on every row."""
    out = []
    for f in signature.get('failures') or []:
        out.append(
            {
                'id': f['gate'],
                'source': 'pixel:pipeline_debug',
                'severity': 'major',
                'ok': False,
                'where': f.get('region'),
                'reason': f'{f["gate"]} = {f["value"]} (gate {f["threshold"]}, margin {f["margin"]})',
            }
        )
    for f in signature.get('facts') or []:
        if f['ns'] in (
            'motion.lost_in_postprocess',
            'keep.contains_motion',
            'chain.step_destructive',
            'chain.step_destructive_pinning',
            'prop.morph_at_seam',
            'discovery.motion_lost_inside_pin',
        ):
            out.append(
                {
                    'id': f['fact'],
                    'source': 'pixel:self_improve',
                    'severity': 'critical' if 'destructive_pinning' in f['ns'] else 'major',
                    'ok': False,
                    'where': f['args'],
                    'reason': f['note'],
                }
            )
    out.extend(vlm_findings(vlm))
    return out


def render_next_attempt_md(diagnosis):
    """The merged human/driver-readable brief: VLM narrative first (it says WHAT
    is wrong in words), pixel evidence second (it says WHY, in numbers), then the
    recipe.  Every finding names the instrument that produced it."""
    sig = diagnosis.get('signature') or {}
    vlm = diagnosis.get('vlm') or {}
    plan = diagnosis.get('plan') or {}
    L = [
        f'# NEXT ATTEMPT — {sig.get("run_name", "?")}',
        '',
        f'_generated {diagnosis.get("when")} by self_improve.py; KB = {diagnosis.get("kb")}_',
        '',
    ]

    L += ['## 1. What the judge saw (VLM narrative)', '']
    if vlm.get('skipped') or not vlm.get('ok'):
        L += [
            f'> **VLM report unavailable** — `{vlm.get("reason", "unknown")}`. '
            f'The findings below are PIXEL evidence only. The judge is blind to '
            f'some defect classes (ink) and weak on temporal ones, so this brief '
            f'is strictly less complete than a fused one.',
            '',
        ]
    else:
        L += [
            f'**verdict: {vlm.get("verdict")}**  ·  model '
            f'`{vlm.get("model")}`  ·  {vlm.get("n_crops")} crops  ·  '
            f'{vlm.get("elapsed_s")}s',
            '',
        ]
        for f in vlm_findings(vlm):
            if f['ok']:
                continue
            L.append(
                f'* `{f["id"]}` **{f["severity"]}** — seen by `{f["source"]}`'
                f'{" at " + str(f["where"]) if f["where"] else ""}: '
                f'{f["reason"]}'
            )
        L.append('')

    L += [
        '## 2. What the pixels measured (evidence)',
        '',
        f'delivered `{os.path.basename(sig.get("clip") or "?")}`  ·  raw '
        f'`{os.path.basename(sig.get("raw_clip") or "") or "(none on disk)"}`',
        '',
        '| region | raw | delivered | Δ | gate | verdict |',
        '|---|---|---|---|---|---|',
    ]
    for name, d in (sig.get('region_deltas') or {}).items():
        L.append(
            f'| {name} | {d.get("raw", "—")} | {d.get("delivered")} | '
            f'{d.get("pct", "—")}% | {d.get("gate")} | '
            f'{"PASS" if d.get("delivered_ok") else "**FAIL**"} |'
        )
    L.append('')
    if sig.get('chain_deltas'):
        L += ['### Chain attribution — which link did it', '']
        for c in sig['chain_deltas']:
            if not c['worsened']:
                continue
            L.append(
                f'* **{c["step"]}** (`{c["from"]}` → `{c["to"]}`): '
                + '; '.join(f'{w["region"]} {w["before"]}→{w["after"]} ({w["pct"]}%)' for w in c['worsened'])
            )
        L.append('')
    if sig.get('keep_boxes_detail'):
        L += [
            '### Pinned (keep-mask) boxes, interrogated on the RAW render',
            '',
            '| pin | box | source | motion inside (raw) | prop NCC (raw, unpinned) | pin needed? |',
            '|---|---|---|---|---|---|',
        ]
        for k, v in sig['keep_boxes_detail'].items():
            L.append(
                f'| {k} | {v["box"]} | {v.get("source")} | '
                f'{v.get("raw_flow", "—")}'
                f'{" **MOVING**" if v.get("contains_motion") else ""} | '
                f'{v.get("raw_ncc_min", "—")} | '
                f'{"NO — already stable unpinned" if v.get("pin_unnecessary") else ("yes" if v.get("pin_unnecessary") is False else "—")} |'
            )
        L.append('')
    ml = sig.get('motion_loss') or {}
    if ml.get('boxes'):
        L += ['### Region-free discovery (no region names used)', '']
        for b in ml['boxes'][:4]:
            L.append(
                f'* box `{b["box"]}` lost {round(100 * b["drop_frac"])}% of its '
                f'motion ({b["raw"]} → {b["delivered"]}, {b["tiles"]} tiles)'
            )
        L.append('')

    L += ['## 3. Ranked remedies (selected from the facts above)', '']
    for i, e in enumerate(diagnosis.get('explanations') or [], 1):
        L.append(f'{i}. ```\n{e}\n```')
    if not diagnosis.get('explanations'):
        L.append('_no remedy matched — see plan notes._')
    L.append('')

    L += [
        '## 4. The recipe for the next run',
        '',
        '```json',
        json.dumps(_jsonable(plan.get('params') or {}), indent=1),
        '```',
        '',
        f'applied: {", ".join(a["id"] for a in (plan.get("applied") or [])) or "none"}',
        '',
    ]
    if plan.get('skipped'):
        L += ['skipped:', '']
        for s in plan['skipped']:
            L.append(f'* `{s["id"]}` — {s["reason"]}: {s.get("detail")}')
        L.append('')
    if plan.get('expected'):
        L += [
            '### Pass condition for the next attempt',
            '',
            '| metric | current | must reach | predicted | basis |',
            '|---|---|---|---|---|',
        ]
        for e in plan['expected']:
            L.append(
                f'| {e["metric"]} | {e.get("current")} | {e.get("direction")} '
                f'{e.get("threshold")} | {e.get("predicted", "—")} | '
                f'{e.get("evidence")} |'
            )
        L.append('')
    for n in plan.get('notes') or []:
        L.append(f'> {n}')
    return '\n'.join(L) + '\n'
