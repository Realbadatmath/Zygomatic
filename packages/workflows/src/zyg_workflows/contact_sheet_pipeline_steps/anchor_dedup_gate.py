# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The cross-character dedup gate (2026-07-17).

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 442-660).
"""

from __future__ import annotations

import os
import uuid
from zyg_workflows import contact_sheet_pipeline as _csp
from .anchor_ctx import AnchorCtx, _dedup_candidates, _dedup_most_similar

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


def step_dedup_gate(ctx: AnchorCtx) -> None:
    """Cross-character dedup gate on the anchor."""
    from zyg_workflows import comfy_generation_service as _cgs
    from zyg_workflows import identity_qc_service as _idqc

    char_id = ctx.char_id
    params = ctx.params
    cell_path = ctx.cell_path
    anchor_path = ctx.anchor_path
    log_fn = ctx.log_fn
    gen_kwargs = ctx.gen_kwargs
    prompt = ctx.prompt
    _cell0_reused = ctx.cell0_reused
    anchor_face = ctx.anchor_face

    # ── CROSS-CHARACTER DEDUP GATE (2026-07-17) ─────────────────────
    # Same-woman audit: with near-identical prompts FLUX converges on
    # its modal face, so back-to-back runs shipped the same person
    # under different names (880e9708 / e4395416 / ac97acfb). Compare
    # the new anchor's ArcFace embedding against existing character
    # anchors; if it is effectively the same face, reroll the anchor
    # with a fresh seed and keep the least-similar candidate.
    _dedup_on = os.environ.get(
        'ZYG_ANCHOR_DEDUP_GATE',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    if _dedup_on and anchor_face and os.path.isfile(anchor_face):
        # Ceilings recalibrated 2026-07-19 from measured pairs: true
        # clones score 0.60+ (Anya↔KiraP 0.62), same-family 0.51,
        # while visually-distinct same-phenotype faces land 0.45-0.50
        # (run d835e071 parked at 0.468 vs a plausibly different
        # person). 0.52 blocks clones without parking every roll that
        # shares a phenotype with the roster. Archived faces use the
        # LAXER ceiling: they were retired to be REPLACED, so a
        # same-phenotype successor is fine — only near-clones block.
        # OPEN CALIBRATION ITEM (2026-08-26). Both ceilings below were
        # measured on glintr100 cosines, and identity_qc_service now
        # defaults to the AuraFace pack, whose cosines sit on a slightly
        # HIGHER scale (frontal same-person median 0.743 vs 0.720;
        # cross-person p99 0.667 vs 0.652). A fixed 0.52 therefore reads
        # marginally stricter than it did, i.e. it errs toward extra
        # rerolls rather than toward admitting clones — the safe
        # direction, but not the calibrated one.
        # auraface_calibration.json only maps the 0.45 operating point
        # (-> 0.489); 0.52 was never measured on this pack, and the
        # house rule is that a threshold is measured, not extrapolated.
        # Re-run the quantile match at 0.52/0.58 before trusting these.
        _dd_max_sim = float(os.environ.get('ZYG_ANCHOR_DEDUP_MAX_SIM', '0.52'))
        _dd_max_sim_arch = float(
            os.environ.get('ZYG_ANCHOR_DEDUP_MAX_SIM_ARCHIVED', '0.58'),
        )
        # Verify-only on resume: measure and record, never reroll.
        _dd_retries = (
            0
            if _cell0_reused
            else max(
                0,
                int(os.environ.get('ZYG_ANCHOR_DEDUP_RETRIES', '3')),
            )
        )
        _dd_others = _dedup_candidates(char_id)
        if _dd_others:
            try:
                import shutil as _sh_dd

                _dd = _dedup_most_similar(anchor_face, _dd_others, _dd_max_sim, _dd_max_sim_arch)
                _dd_backup = cell_path + '.dedup_best.png'
                _dd_best = dict(_dd)
                if _dd['margin'] > 0:
                    _sh_dd.copy2(cell_path, _dd_backup)
                _dd_round = 0
                while _dd['margin'] > 0 and _dd_round < _dd_retries:
                    _dd_round += 1
                    if log_fn:
                        log_fn(
                            f'Dedup gate: anchor matches '
                            f'{"ARCHIVED " if _dd["archived"] else ""}character '
                            f'{_dd["cid"]} (ArcFace sim {_dd["sim"]:.3f} > '
                            f'ceiling {_dd["ceiling"]:g}) — rerolling anchor '
                            f'with fresh seed ({_dd_round}/{_dd_retries})',
                        )
                    # Jittered reroll (2026-07-18): seed-only rerolls
                    # resample the same collapsed FLUX mode (measured
                    # 0.502/0.610/0.465 on run 59f1f012). Shift the
                    # conditioning too: drop the shared ZYG_CHAR_*
                    # trigger prefix (pure noise to base FLUX, but a
                    # near-identical leading token every run), append
                    # individuality tokens, and nudge guidance.
                    _dd_prompt = prompt
                    _dd_trig = _csp.trigger_token_for(char_id)
                    if _dd_trig and _dd_prompt.startswith(_dd_trig):
                        _dd_prompt = _dd_prompt[len(_dd_trig) :].lstrip(', ')
                    _dd_prompt = (
                        f'{_dd_prompt}, distinctive individual facial bone '
                        f'structure, unique memorable face, not a generic '
                        f'stock-model face'
                    )
                    _dd_kw = dict(gen_kwargs)
                    _dd_kw['seed'] = int(uuid.uuid4().int % (2**31))
                    _dd_cfg_base = float(_dd_kw.get('cfg') or 3.5)
                    _dd_cfg = _dd_cfg_base + (0.4 if _dd_round % 2 else -0.4)
                    _dd_kw['cfg'] = _dd_cfg
                    _dd_kw['flux_guidance'] = _dd_cfg
                    _dd_ok, _dd_b = _cgs.generate_still(cell_path, _dd_prompt, **_dd_kw)
                    if not (_dd_ok and os.path.isfile(cell_path)):
                        if log_fn:
                            log_fn('Dedup gate: reroll generation failed — keeping best candidate')
                        break
                    try:
                        anchor_face = _idqc.extract_anchor_face(
                            cell_path,
                            anchor_path,
                            log_fn=log_fn,
                        )
                    except Exception:
                        anchor_face = None
                    if not anchor_face:
                        _sh_dd.copy2(cell_path, anchor_path)
                        anchor_face = anchor_path
                    _dd = _dedup_most_similar(anchor_face, _dd_others, _dd_max_sim, _dd_max_sim_arch)
                    if _dd['sim'] >= 0 and _dd['margin'] < _dd_best['margin']:
                        _dd_best = dict(_dd)
                        _sh_dd.copy2(cell_path, _dd_backup)
                if os.path.isfile(_dd_backup):
                    if _dd['margin'] > _dd_best['margin'] and _dd_best['sim'] >= 0:
                        # Final roll was worse — restore the least-violating candidate.
                        _sh_dd.copy2(_dd_backup, cell_path)
                        try:
                            anchor_face = _idqc.extract_anchor_face(
                                cell_path,
                                anchor_path,
                                log_fn=log_fn,
                            )
                        except Exception:
                            anchor_face = None
                        if not anchor_face:
                            _sh_dd.copy2(cell_path, anchor_path)
                            anchor_face = anchor_path
                        _dd = dict(_dd_best)
                    try:
                        os.remove(_dd_backup)
                    except OSError as _exc:
                        _zyg_log.debug('anchor dedup backup not removed: %s', _exc)
                params['_anchor_dedup'] = {
                    'max_sim': round(_dd['sim'], 3) if _dd['sim'] >= 0 else None,
                    'vs': _dd['cid'] or None,
                    'vs_archived': bool(_dd['archived']),
                    'ceiling': _dd['ceiling'],
                }
                if _dd['margin'] > 0:
                    # Hard gate (2026-07-18): ship-with-warning let a
                    # 0.465-sim near-duplicate straight into the library.
                    # Park resumable instead; the operator can resume,
                    # raise ZYG_ANCHOR_DEDUP_MAX_SIM, or set
                    # ZYG_ANCHOR_DEDUP_HARD=0 to restore warn-only.
                    _dd_hard = os.environ.get(
                        'ZYG_ANCHOR_DEDUP_HARD',
                        '1',
                    ).strip().lower() not in ('0', 'false', 'no', 'off')
                    if _cell0_reused:
                        # Resume = the operator already chose to
                        # continue with this face; re-parking would
                        # loop forever. Record and move on.
                        _dd_hard = False
                    if _dd_hard:
                        # Side-by-side comparison for the operator —
                        # the gray zone is a 5-second visual call.
                        _conflict_img = _csp._save_dedup_conflict_image(
                            char_id,
                            anchor_face,
                            _dd['path'],
                        )
                        if _conflict_img:
                            params['_anchor_dedup']['comparison_image'] = _conflict_img
                            if log_fn:
                                log_fn(
                                    f'Dedup conflict comparison saved → '
                                    f'{_conflict_img} (left: new anchor, '
                                    f'right: {_dd["cid"]})',
                                )
                        if log_fn:
                            log_fn(
                                f'Dedup gate FAILED — anchor is the same face as '
                                f'{"ARCHIVED " if _dd["archived"] else ""}character '
                                f'{_dd["cid"]} (ArcFace sim {_dd["sim"]:.3f} > '
                                f'ceiling {_dd["ceiling"]:g}) after '
                                f'{_dd_retries} jittered rerolls; parking run',
                            )
                        from zyg_workflows import pipeline_control as _pc_dd

                        raise _pc_dd.PipelinePaused(
                            char_id,
                            f'anchor dedup: same face as {_dd["cid"]} '
                            f'(sim {_dd["sim"]:.3f} > {_dd["ceiling"]:g}'
                            f'{", archived" if _dd["archived"] else ""})',
                        )
                    if log_fn:
                        log_fn(
                            f'Dedup gate: retries exhausted — proceeding with '
                            f'least-violating anchor (sim {_dd["sim"]:.3f} vs '
                            f'{_dd["cid"]}); review recommended '
                            f'(ZYG_ANCHOR_DEDUP_HARD=0)',
                        )
                elif _dd['sim'] >= 0 and log_fn:
                    log_fn(
                        f'Dedup gate OK — worst case sim {_dd["sim"]:.3f} vs '
                        f'{_dd["cid"]} ({len(_dd_others)} anchor(s) compared, '
                        f'ceiling {_dd["ceiling"]:g})',
                    )
            except Exception as _dd_exc:
                from zyg_workflows import pipeline_control as _pc_ddx

                if isinstance(_dd_exc, _pc_ddx.PipelinePaused):
                    raise
                if log_fn:
                    log_fn(f'Dedup gate skipped ({_dd_exc})')
    ctx.anchor_face = anchor_face
