# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_signature — THE EVIDENCE.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
The measurement stages live in `signature_stages.py`; this module is the orchestrator.
"""

import os
import time

from zyg_workflows.self_improve import signature_stages as _stages
from zyg_workflows.self_improve.base import _mklog, _read_json


# ══════════════════════════════════════════════════════════════════════════════
# 7.  build_signature — THE EVIDENCE
# ══════════════════════════════════════════════════════════════════════════════


def build_signature(
    run_dir, clip_path=None, raw_clip=None, params=None, regions=None, keep_boxes=None, chain=None, log_fn=None
):
    """Measure a finished run and reduce it to a matchable signature.

    Nothing about the defect is passed in.  What goes in is where the run lives;
    what comes out is a set of measured FACTS (`facts[]`, each with its evidence)
    that a remedy KB can match without a human in the loop.

    Measurements performed
      * the delivered clip and — when a pre-post-process render exists — the RAW
        clip, on the same named regions with the same gates (`metrics`)
      * `deltas[region]`: raw → delivered, absolute and %, plus which side passes
        its gate.  This is the column that exposes a post-process that destroys
        motion; on scene20_v8 it reads abel_hand 0.254 → 0.080 (-68 %), raw PASS
        / delivered FAIL.
      * every consecutive link of the detected chain diffed the same way
        (`chain_deltas`) so the destroying step is localised, not guessed.
      * every keep/pin box (metadata + mask connected components) probed on the
        RAW clip for `contains_motion` (region flow) and `pin_unnecessary`
        (prop NCC already above the gate without any pin).
      * a region-free motion-loss grid (`motion_loss`).

    SHAPE.  The top-level keys `gates / regions / props / keep_boxes / chain /
    params / probe / run / vlm / deltas` are exactly the contract published in
    config/remedy_kb.json['_signature_contract'] — remedy_kb.match() reads those
    paths, so they are authoritative and must not be repurposed.  Everything this
    module needs for its own reporting lives beside them under non-colliding
    names (`region_deltas`, `keep_boxes_detail`, `chain_steps`, `chain_deltas`,
    `facts`, `failures`, `metrics`, `motion_loss`).

    NOTE on `regions[*].flow_mean`: the contract compares it straight to
    `min_flow`, so this field carries the GEOMETRY-NORMALISED flow (flow_norm).
    The un-normalised px/sample value is kept beside it as `flow_mean_px`.
    Feeding a 1664x960@24 delivered clip's raw px value to a gate calibrated at
    832x480@17 would inflate it 1.41x and pass broken clips.

    Returns the signature dict (schema 'zyg.signature/1').  Fail-safe: on error a
    signature with ['error'] and whatever was measured before the failure."""
    log = _mklog(log_fn)
    t0 = time.time()
    run_dir = os.path.abspath(run_dir)
    sig = _stages.new_signature(run_dir, params)
    try:
        ctx = _stages.resolve_inputs(sig, run_dir, clip_path, raw_clip, regions, chain, log)
        if ctx is None:
            return sig

        # ── keep / pin boxes ────────────────────────────────────────────────
        kb = _stages.collect_keep_boxes(sig, run_dir, ctx.meta, keep_boxes, log)

        # ── measure delivered + raw on named regions ────────────────────────
        m_del, m_raw = _stages.measure_clips(sig, ctx, kb, run_dir, log)
        gate_default = _stages.region_flow_gate_default()

        # ── deltas: raw → delivered, per named region ───────────────────────
        _stages.record_region_deltas(sig, ctx, m_del, m_raw)

        # ── chain deltas: which LINK destroyed it ───────────────────────────
        _stages.record_chain_deltas(sig, ctx, m_del, m_raw, run_dir, log)

        # ── variants already tried IN THIS RUN DIR (free evidence) ──────────
        _stages.record_variant_evidence(sig, ctx, run_dir, log)

        # ── keep-box interrogation on the RAW clip ──────────────────────────
        _stages.interrogate_keep_boxes(sig, ctx, kb, m_raw, gate_default)

        # ── region-free discovery ───────────────────────────────────────────
        _stages.record_motion_loss_discovery(sig, ctx, kb, log)

        # ── props: the contract surface that decides pin necessity ──────────
        _stages.record_props(sig, kb, m_del, m_raw)

        # ── prop / seam morphing on the DELIVERED clip ──────────────────────
        _stages.record_prop_morphs(sig, m_del)

        # ── remaining contract fields (absent when unmeasured, never invented) ──
        _stages.record_contract_tail(sig, run_dir)

        # ── cross-run memory ────────────────────────────────────────────────
        sig['ledger'] = _ledger_view(run_dir, log_fn=log)
        for g in (sig['ledger'] or {}).get('gates') or []:
            sig['gates'].setdefault(g['gate'], {'ok': (g['outcome'] == 'pass'), 'score': g['score'], 'threshold': None})
        sig['fact_index'] = sorted({f['ns'] for f in sig['facts']})
        sig['ok'] = True
        sig['seconds'] = round(time.time() - t0, 1)
        log(
            f'[self_improve] signature built in {sig["seconds"]}s — '
            f'{len(sig["facts"])} facts, {len(sig["failures"])} failing gate(s)'
        )
    except Exception as e:
        import traceback

        sig['error'] = str(e)[:300]
        sig['traceback'] = traceback.format_exc()[-1500:]
        log(f'[self_improve] build_signature failed: {e}')
    return sig


def _ledger_view(run_dir, log_fn=None):
    """What the ledger already knows about this run and the last two weeks."""
    out = {'ok': False}
    try:
        from zyg_workflows import run_ledger as RL

        rid = None
        rep = _read_json(os.path.join(run_dir, 'debug', 'report.json'), {}) or {}
        rid = (rep.get('verdict') or {}).get('run_id') or rep.get('run_id')
        out['run_id'] = rid
        if rid:
            g = RL.gates_for_run(rid) or []
            out['gates'] = [
                {'gate': r['gate'], 'outcome': r['outcome'], 'score': r['score'], 'tag': r['tag']} for r in g
            ]
            out['failed_gates'] = [r['gate'] for r in g if (r['outcome'] or '') == 'fail']
        t = RL.trends(days=14) or {}
        out['trend_shifts'] = [x for x in (t.get('gates') or []) if x.get('shift')][:8]
        out['ok'] = True
    except Exception as e:
        out['error'] = str(e)[:200]
        _mklog(log_fn)(f'[self_improve] ledger view unavailable: {e}')
    return out
