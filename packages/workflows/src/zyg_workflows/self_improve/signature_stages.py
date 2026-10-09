# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Measurement stages of `build_signature` — one function per evidence surface.

`signature.build_signature` is the orchestrator: it makes the empty signature,
resolves the run's inputs (`resolve_inputs`) and then calls the stages below in
the order the original single function ran them.  Every stage mutates the
signature dict in place — appending to `facts` / `failures` and filling the
remedy_kb contract surfaces — so the published contract keys are unchanged.
"""

import os
import re
import time
from dataclasses import dataclass
from typing import Any

from zyg_workflows.self_improve.base import SCHEMA, _COVER_FRAC, _jsonable, _read_json
from zyg_workflows.self_improve.chain import (
    _CONTRACT_STEP,
    _box_iou,
    _box_subtract_note,
    detect_chain,
    keep_boxes_from_mask,
    keep_boxes_from_metadata,
)
from zyg_workflows.self_improve.measure import (
    _fact,
    _find_clip,
    _find_raw,
    _num_or_none,
    load_qc_spec,
    measure_clip,
    motion_loss_map,
)


@dataclass
class SignatureInputs:
    """Everything one `build_signature` call resolves from disk before measuring.

    Carries what the original function kept in enclosing locals: the shot
    metadata, the QC spec and its gates, the named regions, the detected render
    chain and the delivered / raw clip paths.
    """

    meta: dict
    spec: dict
    regions: dict
    min_flow: Any
    max_churn: Any
    ncc_min: Any
    prop_pairs: Any
    chain: list
    clip_path: str
    raw_clip: str | None


def new_signature(run_dir, params):
    """Return the empty signature for `run_dir`: contract surface + evidence surface.

    `params` is the run's parameter dict (copied, never aliased).
    """
    return {
        'schema': SCHEMA,
        'run_dir': run_dir,
        'run_name': os.path.basename(run_dir),
        'built': time.strftime('%Y-%m-%d %H:%M:%S'),
        'facts': [],
        'failures': [],
        # ── remedy_kb contract surface ──
        'gates': {},
        'regions': {},
        'props': {},
        'keep_boxes': {},
        'chain': [],
        'deltas': {},
        'params': dict(params or {}),
        # ── self_improve evidence surface ──
        'region_deltas': {},
        'chain_deltas': [],
        'chain_steps': [],
        'keep_boxes_detail': {},
        'metrics': {},
        'ok': False,
    }


def resolve_inputs(sig, run_dir, clip_path, raw_clip, regions, chain, log):
    """Resolve spec, chain and clips for `run_dir` into a `SignatureInputs`.

    Fills `shot_metadata`, `qc_spec`, `chain_steps`, `chain`, `clip` and
    `raw_clip` on `sig`.  Returns None — after setting `sig['error']` — when no
    delivered clip is on disk, which is the one early exit the caller honours.
    """
    meta = _read_json(os.path.join(run_dir, 'shot_metadata.json'), {}) or {}
    sig['shot_metadata'] = meta
    spec = load_qc_spec(run_dir, log_fn=log)
    regions = regions or spec.get('regions') or {}
    regions = {k: tuple(v) for k, v in regions.items()}
    min_flow = spec.get('min_flow')
    max_churn = spec.get('max_churn')
    ncc_min = spec.get('ncc_min')
    prop_pairs = spec.get('prop_pairs')
    sig['qc_spec'] = {
        'source': spec.get('source'),
        'regions': _jsonable(regions),
        'min_flow': min_flow,
        'max_churn': max_churn,
        'ncc_min': ncc_min,
    }

    chain = chain if chain is not None else detect_chain(run_dir, log_fn=log)
    sig['chain_steps'] = chain
    # contract `chain` is a flat list of stage NAMES in the KB's vocabulary
    sig['chain'] = [_CONTRACT_STEP.get(c['step'], c['step']) for c in chain if c['variant_of'] is None]
    clip_path = clip_path or _find_clip(run_dir, chain)
    raw_clip = raw_clip if raw_clip is not None else _find_raw(chain)
    if raw_clip and clip_path and os.path.abspath(raw_clip) == os.path.abspath(clip_path):
        raw_clip = None  # delivered IS the raw render — no post-process to blame
    sig['clip'] = clip_path
    sig['raw_clip'] = raw_clip
    if not clip_path or not os.path.isfile(clip_path):
        sig['error'] = f'no delivered clip found in {run_dir}'
        log(f'[self_improve] {sig["error"]}')
        return None
    log(
        f'[self_improve] delivered={os.path.basename(clip_path)} '
        f'raw={os.path.basename(raw_clip) if raw_clip else "(none)"}'
    )
    return SignatureInputs(
        meta=meta,
        spec=spec,
        regions=regions,
        min_flow=min_flow,
        max_churn=max_churn,
        ncc_min=ncc_min,
        prop_pairs=prop_pairs,
        chain=chain,
        clip_path=clip_path,
        raw_clip=raw_clip,
    )


def collect_keep_boxes(sig, run_dir, meta, keep_boxes, log):
    """Return the run's keep/pin boxes as `{name: {'box': [...], ...}}`.

    Caller-supplied `keep_boxes` win; otherwise they are discovered from the shot
    metadata and from the first two `mask*.png` in `run_dir`.  Fills
    `keep_boxes_detail` (full records) and `keep_boxes` (contract shape).
    """
    kb = dict(keep_boxes or {})
    if not kb:
        kb.update(keep_boxes_from_metadata(meta, log_fn=log))
        masks = [os.path.join(run_dir, n) for n in sorted(os.listdir(run_dir)) if re.match(r'^mask.*\.png$', n)]
        for m in masks[:2]:
            kb.update(keep_boxes_from_mask(m, log_fn=log).get('boxes') or {})
    kb = {k: (v if isinstance(v, dict) else {'box': list(v), 'source': 'caller'}) for k, v in kb.items()}
    sig['keep_boxes_detail'] = kb
    sig['keep_boxes'] = {k: list(v['box']) for k, v in kb.items()}  # contract shape
    return kb


def measure_clips(sig, ctx, kb, run_dir, log):
    """Measure the delivered clip and, when one exists, the raw render.

    Keep boxes become props on both clips and extra FLOW regions on the raw clip
    ("does this pin cover something that was moving before we pinned it?").
    Returns `(m_del, m_raw)` and fills `metrics.delivered` / `metrics.raw`.
    """
    prop_boxes = dict(ctx.spec.get('prop_boxes') or {})
    for k, v in kb.items():
        prop_boxes.setdefault(f'keep:{k}', v['box'])
    m_del = measure_clip(
        ctx.clip_path,
        ctx.regions,
        ctx.min_flow,
        ctx.max_churn,
        prop_boxes,
        ctx.prop_pairs,
        ctx.ncc_min,
        cache_dir=run_dir,
        log_fn=log,
    )
    sig['metrics']['delivered'] = m_del
    m_raw = None
    if ctx.raw_clip and os.path.isfile(ctx.raw_clip):
        raw_regions = dict(ctx.regions)
        for k, v in kb.items():
            raw_regions[f'keep:{k}'] = tuple(v['box'])
        raw_min = dict(ctx.min_flow) if isinstance(ctx.min_flow, dict) else ctx.min_flow
        raw_max = dict(ctx.max_churn) if isinstance(ctx.max_churn, dict) else ctx.max_churn
        if isinstance(raw_min, dict):
            for k in kb:
                raw_min.setdefault(f'keep:{k}', 0.0)
        if isinstance(raw_max, dict):
            for k in kb:
                raw_max.setdefault(f'keep:{k}', 9.0)
        m_raw = measure_clip(
            ctx.raw_clip,
            raw_regions,
            raw_min,
            raw_max,
            prop_boxes,
            ctx.prop_pairs,
            ctx.ncc_min,
            cache_dir=run_dir,
            log_fn=log,
        )
        sig['metrics']['raw'] = m_raw
    return m_del, m_raw


def region_flow_gate_default():
    """The repo-wide fallback region-flow gate (`pipeline_debug._REGION_FLOW_MIN`)."""
    from zyg_workflows import pipeline_debug as DBG

    return DBG._REGION_FLOW_MIN


def record_region_deltas(sig, ctx, m_del, m_raw):
    """Diff raw → delivered on every named region and publish the gate surfaces.

    Fills `region_deltas`, the contract `regions` / `gates` / `deltas` entries
    and — through `region_motion_facts` — the per-region failures and facts.
    """
    for name in ctx.regions:
        d = (m_del.get('regions') or {}).get(name)
        if not d:
            continue
        gate = d['gate_min_flow']
        rec = {
            'gate': gate,
            'delivered': d['flow_norm'],
            'delivered_raw_px': d['flow_mean'],
            'delivered_ok': d['ok'],
            'churn_p95': d['churn_p95'],
        }
        r = (m_raw.get('regions') or {}).get(name) if m_raw else None
        if r:
            rec.update(
                {
                    'raw': r['flow_norm'],
                    'raw_raw_px': r['flow_mean'],
                    'raw_ok': r['ok'],
                    'delta': round(d['flow_norm'] - r['flow_norm'], 4),
                    'pct': round(100.0 * (d['flow_norm'] - r['flow_norm']) / r['flow_norm'], 1)
                    if r['flow_norm'] > 1e-9
                    else None,
                }
            )
        sig['region_deltas'][name] = rec
        # contract surfaces
        sig['regions'][name] = {
            'flow_mean': d['flow_norm'],  # NORMALISED — see build_signature's docstring
            'flow_mean_px': d['flow_mean'],
            'flow_p95': d['flow_p95'],
            'churn_mean': d['churn_mean'],
            'churn_p95': d['churn_p95'],
            'ok': d['ok'],
            'min_flow': gate,
            'max_churn': d['gate_max_churn'],
            'box': list(ctx.regions[name]),
            **(
                {'role': (ctx.spec.get('roles') or {})[name]}
                if isinstance(ctx.spec.get('roles'), dict) and name in ctx.spec['roles']
                else {}
            ),
        }
        sig['gates'][f'region_flow:{name}'] = {'ok': d['ok'], 'score': d['flow_norm'], 'threshold': gate}
        if r:
            sig['deltas'][f'region_flow:{name}'] = {'before': r['flow_norm'], 'after': d['flow_norm']}
        region_motion_facts(sig, name, d, r, rec, gate, bool(m_raw))


def region_motion_facts(sig, name, d, r, rec, gate, has_raw):
    """Attribute one region's verdict: failure record plus the explaining fact.

    `d` is the delivered measurement, `r` the raw one (None without a raw
    render), `rec` the already-built delta record and `gate` the region's
    `min_flow`.  Appends to `sig['failures']` / `sig['facts']` only.
    """
    if not d['ok']:
        sig['failures'].append(
            {
                'gate': f'region_flow:{name}',
                'region': name,
                'value': d['flow_norm'],
                'threshold': gate,
                'margin': round(d['flow_norm'] - gate, 4),
                'why': 'flow' if not d['flow_ok'] else 'churn',
            }
        )
        sig['facts'].append(
            _fact(
                'gate.fail',
                {'region': name},
                {'value': d['flow_norm'], 'gate': gate},
                f'{name} measures {d["flow_norm"]:.3f} (gate {gate})',
            )
        )
    if r and r['ok'] and not d['ok']:
        sig['facts'].append(
            _fact(
                'motion.lost_in_postprocess',
                {'region': name},
                {'raw': r['flow_norm'], 'delivered': d['flow_norm'], 'pct': rec.get('pct'), 'gate': gate},
                f'{name}: raw render PASSES at {r["flow_norm"]:.3f}, delivered '
                f'FAILS at {d["flow_norm"]:.3f} ({rec.get("pct")}%) — the render '
                f'was fine, a post-process removed the motion',
            )
        )
    if r and not r['ok'] and not d['ok']:
        sig['facts'].append(
            _fact(
                'motion.frozen_at_source',
                {'region': name},
                {'raw': r['flow_norm'], 'gate': gate},
                f'{name} already fails on the RAW render ({r["flow_norm"]:.3f} '
                f'< {gate}) — the sampler, not the post-process',
            )
        )
    if not has_raw and not d['ok']:
        sig['facts'].append(
            _fact(
                'motion.failed_no_raw',
                {'region': name},
                {'delivered': d['flow_norm'], 'gate': gate},
                f'{name} fails but no raw render is on disk to attribute it',
            )
        )


def measure_main_chain(main_chain, ctx, m_del, m_raw, run_dir, log):
    """Measure every artifact of the main chain, reusing the two clips measured.

    Returns `{file: metrics}` for the links of `main_chain`.
    """
    measured = {}
    for c in main_chain:
        if c['path'] == ctx.clip_path and m_del.get('ok'):
            measured[c['file']] = m_del
        elif ctx.raw_clip and c['path'] == ctx.raw_clip and m_raw:
            measured[c['file']] = m_raw
        else:
            measured[c['file']] = measure_clip(
                c['path'], ctx.regions, ctx.min_flow, ctx.max_churn, None, None, None, cache_dir=run_dir, log_fn=log
            )
    return measured


def worsened_regions(ma, mb, regions):
    """Regions that `ma` → `mb` pushed from passing to failing, with the drop."""
    worsened = []
    for name in regions:
        ra = (ma['regions'] or {}).get(name)
        rb = (mb['regions'] or {}).get(name)
        if not ra or not rb:
            continue
        drop = ra['flow_norm'] - rb['flow_norm']
        if ra['ok'] and not rb['ok']:
            worsened.append(
                {
                    'region': name,
                    'before': ra['flow_norm'],
                    'after': rb['flow_norm'],
                    'drop': round(drop, 4),
                    'pct': round(-100.0 * drop / ra['flow_norm'], 1) if ra['flow_norm'] > 1e-9 else None,
                    'crossed_gate': True,
                }
            )
    return worsened


def record_chain_deltas(sig, ctx, m_del, m_raw, run_dir, log):
    """Diff every consecutive link of the chain so the destroying step is localised.

    Fills `chain_deltas` and appends a `chain.step_destructive[_pinning]` fact
    for each link that pushed a region across its gate.
    """
    main_chain = [c for c in ctx.chain if c['variant_of'] is None]
    measured = measure_main_chain(main_chain, ctx, m_del, m_raw, run_dir, log)
    for i in range(len(main_chain) - 1):
        a, b = main_chain[i], main_chain[i + 1]
        ma, mb = measured.get(a['file']), measured.get(b['file'])
        if not (ma and mb and ma.get('ok') and mb.get('ok')):
            continue
        worsened = worsened_regions(ma, mb, ctx.regions)
        link = {
            'from': a['file'],
            'to': b['file'],
            'step': b['step'],
            'family': b['family'],
            'param_key': b['param_key'],
            'disable_value': b['disable_value'],
            'keep_mask': b.get('keep_mask'),
            'worsened': worsened,
        }
        sig['chain_deltas'].append(link)
        if worsened:
            # A step that reads a keep mask gets its OWN namespace so that
            # keep-box evidence can only ever indict a pinning step.
            ns = 'chain.step_destructive_pinning' if b.get('keep_mask') else 'chain.step_destructive'
            sig['facts'].append(
                _fact(
                    ns,
                    {'step': b['step']},
                    {
                        'from': a['file'],
                        'to': b['file'],
                        'worsened': worsened,
                        'param_key': b['param_key'],
                        'disable_value': b['disable_value'],
                        'family': b['family'],
                        'keep_mask': bool(b.get('keep_mask')),
                    },
                    f'step "{b["step"]}" ({a["file"]} → {b["file"]}) pushed '
                    + ', '.join(f'{w["region"]} {w["before"]:.3f}→{w["after"]:.3f} ({w["pct"]}%)' for w in worsened)
                    + ' across the gate'
                    + (' (this step composites over a keep mask)' if b.get('keep_mask') else ''),
                )
            )


def record_variant_evidence(sig, ctx, run_dir, log):
    """Measure the alternatives already executed in this run dir (free evidence).

    Each variant becomes a `variant.tried_and_failed` / `tried_and_passed` fact
    keyed by FAMILY, so "this slot's alternative already failed" binds to the
    destructive step's family rather than to one artifact's name.
    """
    for c in ctx.chain:
        if c['variant_of'] is None:
            continue
        mv = measure_clip(
            c['path'], ctx.regions, ctx.min_flow, ctx.max_churn, None, None, None, cache_dir=run_dir, log_fn=log
        )
        if not mv.get('ok'):
            continue
        still_bad = [n for n, v in (mv['regions'] or {}).items() if not v['ok']]
        ev = {
            'file': c['file'],
            'variant_of': c['variant_of'],
            'step': c['step'],
            'regions': {n: v['flow_norm'] for n, v in (mv['regions'] or {}).items()},
            'failing': still_bad,
        }
        if still_bad:
            still_bad_detail = ', '.join(f'{n}={ev["regions"][n]}' for n in still_bad)
            sig['facts'].append(
                _fact(
                    'variant.tried_and_failed',
                    {'family': c['family']},
                    ev,
                    f'{c["file"]} is an already-executed "{c["step"]}" alternative for '
                    f'the "{c["family"]}" slot and STILL fails {still_bad} '
                    f'({still_bad_detail}) — '
                    f'do not propose that alternative again',
                )
            )
        else:
            sig['facts'].append(
                _fact(
                    'variant.tried_and_passed',
                    {'family': c['family']},
                    ev,
                    f'{c["file"]} is an already-executed "{c["step"]}" alternative for '
                    f'the "{c["family"]}" slot and passes every named region',
                )
            )


def keep_box_raw_probe(sig, kname, kv, kbox, m_raw, gate_default):
    """Probe one pin on the RAW clip: does it cover motion, is it needed at all?

    Sets `raw_flow` / `contains_motion` / `raw_ncc_min` / `pin_unnecessary` on
    the keep record `kv` and appends the matching `keep.*` facts.
    """
    rr = (m_raw.get('regions') or {}).get(f'keep:{kname}')
    if rr:
        kv['raw_flow'] = rr['flow_norm']
        kv['contains_motion'] = bool(rr['flow_norm'] >= gate_default)
        if kv['contains_motion']:
            sig['facts'].append(
                _fact(
                    'keep.contains_motion',
                    {'keep': kname},
                    {
                        'raw_flow': rr['flow_norm'],
                        'gate': gate_default,
                        'box': list(kbox),
                        'source': kv.get('source'),
                    },
                    f'pin "{kname}" {list(kbox)} measures {rr["flow_norm"]:.3f} '
                    f'px/sample of REAL motion on the raw render (gate '
                    f'{gate_default}) — pinning it statically must freeze that',
                )
            )
    pr = (m_raw.get('props') or {}).get(f'keep:{kname}')
    if pr:
        kv['raw_ncc_min'] = pr['ncc_min']
        kv['pin_unnecessary'] = bool(pr['ok'])
        if pr['ok']:
            sig['facts'].append(
                _fact(
                    'keep.pin_unnecessary',
                    {'keep': kname},
                    {
                        'ncc_min': pr['ncc_min'],
                        'ncc_max': pr['ncc_max'],
                        'gate': pr['gate_ncc_min'],
                        'box': list(kbox),
                    },
                    f'pin "{kname}" is not needed: on the UNPINNED raw render '
                    f'its content already holds NCC {pr["ncc_min"]}-'
                    f'{pr["ncc_max"]} across every seam (gate '
                    f'{pr["gate_ncc_min"]})',
                )
            )
        else:
            sig['facts'].append(
                _fact(
                    'keep.pin_justified',
                    {'keep': kname},
                    {'ncc_min': pr['ncc_min'], 'gate': pr['gate_ncc_min']},
                    f'pin "{kname}" IS earning its place: raw NCC drops to {pr["ncc_min"]} (< {pr["gate_ncc_min"]})',
                )
            )


def keep_box_overlap_facts(sig, regions, kname, kbox):
    """Fact every failing region that lies inside pin `kname`, with a shrink note."""
    for f in sig['failures']:
        rname = f['region']
        rbox = regions.get(rname)
        if not rbox:
            continue
        iou, contained = _box_iou(rbox, kbox)
        if contained >= _COVER_FRAC:
            sig['facts'].append(
                _fact(
                    'keep.covers_failing_region',
                    {'region': rname, 'keep': kname},
                    {
                        'iou': round(iou, 3),
                        'region_frac_inside_keep': round(contained, 3),
                        'keep_box': list(kbox),
                        'region_box': list(rbox),
                        'shrink_to': _box_subtract_note(list(kbox), list(rbox)),
                    },
                    f'{round(100 * contained)}% of failing region "{rname}" '
                    f'{list(rbox)} lies inside pin "{kname}" {list(kbox)}',
                )
            )


def interrogate_keep_boxes(sig, ctx, kb, m_raw, gate_default):
    """Interrogate every keep/pin box: raw motion, pin necessity, region overlap."""
    for kname, kv in kb.items():
        kbox = tuple(kv['box'])
        kv['contains_motion'] = None
        kv['pin_unnecessary'] = None
        if m_raw:
            keep_box_raw_probe(sig, kname, kv, kbox, m_raw, gate_default)
        # overlap of this pin with each FAILING region
        keep_box_overlap_facts(sig, ctx.regions, kname, kbox)


def record_motion_loss_discovery(sig, ctx, kb, log):
    """Region-free discovery: where did motion disappear between raw and delivered?

    Fills `motion_loss` and appends a `discovery.motion_lost` fact per cluster
    (plus `discovery.motion_lost_inside_pin` when a cluster sits inside a pin).
    """
    if not (ctx.raw_clip and os.path.isfile(ctx.raw_clip)):
        return
    ml = motion_loss_map(ctx.raw_clip, ctx.clip_path, log_fn=log)
    sig['motion_loss'] = ml
    for b in (ml.get('boxes') or [])[:4]:
        inside = []
        for kname, kv in kb.items():
            _iou, contained = _box_iou(b['box'], tuple(kv['box']))
            if contained >= _COVER_FRAC:
                inside.append({'keep': kname, 'frac': round(contained, 3)})
        sig['facts'].append(
            _fact(
                'discovery.motion_lost',
                {'box': 'x'.join(str(v) for v in b['box'])},
                {**b, 'inside_keep': inside},
                f'unnamed region {b["box"]} lost {round(100 * b["drop_frac"])}% of its '
                f'motion ({b["raw"]:.3f} → {b["delivered"]:.3f})'
                + (f' and lies inside pin(s) {[i["keep"] for i in inside]}' if inside else ''),
            )
        )
        if inside:
            sig['facts'].append(
                _fact(
                    'discovery.motion_lost_inside_pin',
                    {'keep': inside[0]['keep']},
                    {**b, 'inside_keep': inside},
                    f'the lost-motion cluster {b["box"]} is {round(100 * inside[0]["frac"])}% '
                    f'inside pin "{inside[0]["keep"]}"',
                )
            )


def record_props(sig, kb, m_del, m_raw):
    """Publish the `props` contract surface that decides pin necessity.

    Keep-derived props are named EXACTLY like their keep_boxes key so the KB's
    `k._key == p._key` join (and normalize_signature's `pinned` derivation) work
    without a translation table.
    """
    for pname, pv in (m_del.get('props') or {}).items():
        key = pname[5:] if pname.startswith('keep:') else pname
        praw = (m_raw.get('props') or {}).get(pname) if m_raw else None
        entry = sig['props'].setdefault(key, {})
        entry.update(
            {
                'box': list(pv['box']),
                'min_ncc': pv['ncc_min'],
                'ncc_min': pv['gate_ncc_min'],  # contract: the GATE, not the value
                'ncc_max': pv['ncc_max'],
                'ok': pv['ok'],
                'raw_min_ncc': (praw or {}).get('ncc_min'),
                'pinned': bool(key in kb)
                or bool(max((_box_iou(pv['box'], tuple(k2['box']))[1] for k2 in kb.values()), default=0.0) >= 0.5),
            }
        )
        sig['gates'][f'prop_ncc:{key}'] = {'ok': pv['ok'], 'score': pv['ncc_min'], 'threshold': pv['gate_ncc_min']}
        if praw and praw.get('ncc_min') is not None and pv['ncc_min'] is not None:
            sig['deltas'][f'prop_ncc:{key}'] = {'before': praw['ncc_min'], 'after': pv['ncc_min']}


def record_prop_morphs(sig, m_del):
    """Fact every non-keep prop that morphs at a seam on the DELIVERED clip."""
    for pname, pv in (m_del.get('props') or {}).items():
        if pname.startswith('keep:'):
            continue
        if not pv['ok']:
            bad = [p for p in pv['pairs'] if not p['ok']]
            sig['facts'].append(
                _fact(
                    'prop.morph_at_seam',
                    {'prop': pname},
                    {'pairs': bad, 'gate': pv['gate_ncc_min']},
                    f'prop "{pname}" morphs at ' + ', '.join(f'{p["t0"]}s→{p["t1"]}s (ncc {p["ncc"]})' for p in bad),
                )
            )


def probe_block(pr):
    """Normalise a `probe_report.json` dict into the contract `probe` block."""
    v = pr.get('verdict')
    return {
        'skipped': bool(pr.get('skipped')),
        'verdict': (
            'skipped'
            if pr.get('skipped')
            else (
                'frozen'
                if isinstance(v, str) and 'frozen' in v.lower()
                else ('ok' if isinstance(v, str) and v.upper().startswith('PASS') else v)
            )
        ),
        **({'context_windows': pr['context_windows']} if 'context_windows' in pr else {}),
    }


def lora_block(params):
    """The `loras` block (total weight + normalised items), or None when absent."""
    if not isinstance(params.get('loras'), (list, dict)):
        return None
    items = params['loras'] if isinstance(params['loras'], list) else (params['loras'].get('items') or [])
    norm = [
        {
            'name': (i[0] if isinstance(i, (list, tuple)) else i.get('name')),
            'scale': _num_or_none(i[1] if isinstance(i, (list, tuple)) else i.get('scale')),
            **({'trained_on': i.get('trained_on')} if isinstance(i, dict) and i.get('trained_on') else {}),
        }
        for i in items
    ]
    tw = sum(x['scale'] or 0.0 for x in norm)
    return {'total_weight': round(tw, 3), 'items': norm}


def record_contract_tail(sig, run_dir):
    """Fill the remaining contract fields: `probe`, `run`, `loras`.

    Absent when unmeasured, never invented.
    """
    pr = _read_json(os.path.join(run_dir, 'probe_report.json'))
    if isinstance(pr, dict):
        sig['probe'] = probe_block(pr)
    p = sig['params']
    run_blk = {}
    for src, dst in (
        ('context_windows', 'context_windows'),
        ('render.context_windows', 'context_windows'),
        ('config_proven', 'config_proven'),
    ):
        if src in p:
            run_blk[dst] = p[src]
    if run_blk:
        sig['run'] = run_blk
    loras = lora_block(p)
    if loras is not None:
        sig['loras'] = loras
