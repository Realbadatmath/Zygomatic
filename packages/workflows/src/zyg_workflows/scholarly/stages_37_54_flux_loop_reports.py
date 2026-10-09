# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The six stages `run_slot_loop` is made of, one function each.

`run_slot_loop` was 315 lines: the render loop, the throughput estimate, the
VLM render-gate report, the typography-gate report, the per-slot gate outcomes
and the era / retry-ladder receipts. Each of those is a stage here, called in
the same order by the orchestrator, with every log line, every
`pipeline_state` write and every `_gate_receipt` call unchanged.

`slot_outcomes` is the pure one: it turns `fs._slot_review` and
`fs._shipped_flagged` into the `SlotOutcomes` record the outcomes line, the era
receipt and the ladder receipt all read, and it touches nothing else. The
report functions take the `fs` / `ctx` frames whole so their bodies stayed
verbatim; a plain `types.SimpleNamespace` with the handful of fields each one
reads is enough to exercise them.

Import direction: this module imports nothing from `stages_37_54_flux_loop` —
the orchestrator imports from here.
"""

from dataclasses import dataclass
from dataclasses import field
import time

from zyg_workflows import gui_state
from zyg_workflows import paths
from zyg_workflows.pipeline_common import _update_flux_seconds_per_image_estimate
from zyg_workflows.scholarly import stages_37_54_flux_slot as _flux_slot


@dataclass(frozen=True)
class SlotOutcomes:
    """What the gates did to the slots, as the three receipts need to read it.

    `outcomes` is the dict written to `pipeline_state['slot_gate_outcomes']`;
    the other fields are the raw lists behind it, which the outcomes log line,
    the era receipt and the retry-ladder receipt each use directly (the era
    receipt wants `unreviewed['era']` even when the dict's own
    `unreviewed_era` was blanked because the era gate was off).
    """

    outcomes: dict = field(default_factory=dict)
    unreviewed: dict = field(default_factory=dict)
    sub_threshold: list = field(default_factory=list)
    repaired: list = field(default_factory=list)
    escalated: list = field(default_factory=list)
    flagged_slots: list = field(default_factory=list)
    clean: int = 0
    slots: int = 0


def render_slots(fs, ctx) -> float:
    """Render slot 0..`ctx._n_flux_images`, in order, and return the wall seconds.

    Appends each produced path to `fs._flux_generated_paths` IN PLACE, as the
    loop always did, and breaks on the job's stop event or the GUI stop flag —
    once before the inference of a slot (it cannot be interrupted mid-way) and
    once after it.
    """
    _debug = ctx._debug
    _log = ctx._log
    _n_flux_images = ctx._n_flux_images
    _flux_generated_paths = fs._flux_generated_paths
    _sch_family_label = fs._sch_family_label
    # `_generate_one`, the 1,176-line closure that stood here, is
    # `generate_one` in `stages_37_54_flux_slot`; the body of its
    # `for _attempt in range(3):` is `run_attempt` in
    # `stages_37_54_flux_attempt`. Both carry the slot frame on
    # `SlotState`, and the `_last_prompt` / `_prev_focal_zone` pair
    # the closure used to rebind in that scope is now the pair of
    # `fs` fields `capture` reads out of it.
    # Generate sequentially (CUDA doesn't parallelize well on single GPU)
    _stop_ev = ctx.job.get('stop_event')
    _flux_gen_started = time.time()
    for _fi in range(_n_flux_images):
        # Check before starting next inference (can't interrupt mid-generation)
        if (_stop_ev and _stop_ev.is_set()) or gui_state._pipeline_stop_flag:
            _debug(
                'Stage 3.5',
                f'FLUX loop stopped at slot {_fi}/{_n_flux_images} before inference '
                f'[stop_flag={gui_state._pipeline_stop_flag}, stop_event={_stop_ev.is_set() if _stop_ev else False}]',
                level='WARN',
            )
            break
        _result_path = _flux_slot.generate_one(fs, ctx, _fi)
        if _result_path:
            _flux_generated_paths.append(_result_path)
        # Progress log every 10 images and at completion
        if (_fi % 10 == 9) or (_fi == _n_flux_images - 1):
            _elapsed_s = max(0.0, time.time() - _flux_gen_started)
            _done_count = len(_flux_generated_paths)
            _s_per_img = _elapsed_s / max(_done_count, 1)
            _remaining = (_n_flux_images - _fi - 1) * _s_per_img
            _log(
                'INFO',
                'Stage 3.5',
                f'{_sch_family_label} progress: {_fi + 1}/{_n_flux_images} images '
                f'({int(100 * (_fi + 1) / _n_flux_images)}%) '
                f'— {_s_per_img:.1f}s/img, ~{int(_remaining)}s remaining',
            )
        if (_stop_ev and _stop_ev.is_set()) or gui_state._pipeline_stop_flag:
            _debug(
                'Stage 3.5',
                f'FLUX loop stopped after slot {_fi} '
                f'[stop_flag={gui_state._pipeline_stop_flag}, stop_event={_stop_ev.is_set() if _stop_ev else False}, '
                f'generated={len(_flux_generated_paths)}/{_fi + 1}]',
                level='WARN',
            )
            break

    return max(0.0, time.time() - _flux_gen_started)


def report_throughput(fs, ctx, elapsed_s: float) -> None:
    """Fold the loop's wall time into the next-run seconds-per-image estimate.

    Writes `flux_seconds_per_image_estimate` and `flux_gen_elapsed_s` into
    `pipeline_state` and logs the throughput line, then — whether or not
    anything was generated — the `Generated N images` line.
    """
    _log = ctx._log
    pipeline_state = ctx.pipeline_state
    _flux_generated_paths = fs._flux_generated_paths
    _sch_family_label = fs._sch_family_label
    _flux_gen_elapsed = elapsed_s
    if _flux_generated_paths:
        _observed_s_per_image = _flux_gen_elapsed / max(len(_flux_generated_paths), 1)
        # Per-family telemetry (P-13): a Qwen queue-wait number
        # must never be read back as FLUX render cost.
        _updated_s_per_image = _update_flux_seconds_per_image_estimate(
            _observed_s_per_image,
            image_count=len(_flux_generated_paths),
            family=('qwen' if ctx._sch_qwen_stills else 'flux'),
            pipeline_id=ctx.pipeline_id,
        )
        pipeline_state['flux_seconds_per_image_estimate'] = round(_updated_s_per_image, 3)
        pipeline_state['flux_gen_elapsed_s'] = round(_flux_gen_elapsed, 1)
        _log(
            'INFO',
            'Stage 3.5',
            f'{_sch_family_label} throughput: {_flux_gen_elapsed:.1f}s / {len(_flux_generated_paths)} images '
            f'(~{_observed_s_per_image:.2f}s/image); next-run estimate '
            f'~{_updated_s_per_image:.2f}s/image',
        )

    _log('INFO', 'Stage 3.5', f'Generated {len(_flux_generated_paths)} {_sch_family_label} images')


def report_vlm_gate(fs, ctx) -> None:
    """Report the VLM render gate, and shout when it produced no verdict at all.

    A no-op when `fs._VLM_QC_ENABLED` is false. Otherwise: the counts line, then
    the WARNING that distinguishes a silent gate from a clean run, then
    `pipeline_state['vlm_gate_stats']`.
    """
    if not fs._VLM_QC_ENABLED:
        return
    _log = ctx._log
    _vlm_gate_stats = fs._vlm_gate_stats
    _VLM_ERA_ENABLED = fs._VLM_ERA_ENABLED
    _VLM_QC_MODEL = fs._VLM_QC_MODEL
    _anatomy_esc_budget = fs._anatomy_esc_budget
    _log(
        'INFO',
        'Stage 3.5',
        f'VLM render gate ({_VLM_QC_MODEL}): {_vlm_gate_stats["checked"]} checked, '
        f'{_vlm_gate_stats["defect"]} flagged, {_vlm_gate_stats["skipped"]} skipped, '
        f'{_vlm_gate_stats["unreadable"]} unreadable'
        + (f', {_vlm_gate_stats["anachronism"]} anachronism' if _VLM_ERA_ENABLED else '')
        + (
            f'; empty verdicts re-asked {_vlm_gate_stats["anatomy_reask"]} '
            f'({_vlm_gate_stats["anatomy_reask_verdict"]} answered), '
            f'escalated {_vlm_gate_stats["anatomy_escalated"]}/'
            f'{_vlm_gate_stats["anatomy_escalation_calls"]} '
            f'(budget {_anatomy_esc_budget})'
            if _vlm_gate_stats['anatomy_reask']
            else ''
        ),
    )
    # "checked" is the ONLY number that means a frame was really
    # inspected. If it is zero — or a large share of calls came
    # back without a verdict — the gate is not doing its job and
    # must say so, loudly. A silent gate reporting 0 defects is
    # indistinguishable from a clean run, which is how this gate
    # went unnoticed for 4 runs / 135 images.
    _vlm_calls = _vlm_gate_stats['checked'] + _vlm_gate_stats['skipped'] + _vlm_gate_stats['unreadable']
    if _vlm_calls and not _vlm_gate_stats['checked']:
        _log(
            'WARNING',
            'Stage 3.5',
            f'VLM render gate produced NO usable verdict in '
            f'{_vlm_calls} calls — renders shipped UNREVIEWED. '
            f'Check Ollama and ZYG_SCHOLARLY_VLM_QC_MODEL '
            f'({_VLM_QC_MODEL}); note this model needs imperative '
            f'prompts ("Say yes if…"), not questions.',
        )
    elif _vlm_gate_stats['unreadable'] > _vlm_gate_stats['checked']:
        _log(
            'WARNING',
            'Stage 3.5',
            f'VLM render gate: {_vlm_gate_stats["unreadable"]} of '
            f'{_vlm_calls} calls returned no verdict — most frames '
            f'went unreviewed; treat the 0-defect result as unproven',
        )
    ctx.pipeline_state['vlm_gate_stats'] = dict(_vlm_gate_stats)


def report_typography(fs, ctx) -> None:
    """Report the typography gate and file its receipt.

    Typography gate reports separately: it runs on a different
    model from the anatomy gate and fails independently, so
    folding its numbers into the line above would hide which of
    the two is dead. When the gate is off, only the receipt is filed.
    """
    _gate_receipt = ctx._gate_receipt
    if not fs._VLM_TEXT_ENABLED:
        _gate_receipt('typography', False, 'ZYG_SCHOLARLY_VLM_TEXT=0')
        return
    _log = ctx._log
    pipeline_state = ctx.pipeline_state
    _vlm_gate_stats = fs._vlm_gate_stats
    _vlm_text_boxes = fs._vlm_text_boxes
    _tx_judge = _vlm_gate_stats.get('text_judge') or 'none'
    _log(
        'INFO',
        'Stage 3.5',
        f'Typography gate ({_tx_judge}): '
        f'{_vlm_gate_stats["text_checked"]} checked, '
        f'{_vlm_gate_stats["typography"]} flagged, '
        f'{_vlm_gate_stats["text_skipped"]} skipped, '
        f'{_vlm_gate_stats["text_unreadable"]} unreadable',
    )
    _tx_calls = _vlm_gate_stats['text_checked'] + _vlm_gate_stats['text_skipped'] + _vlm_gate_stats['text_unreadable']
    if _tx_calls and not _vlm_gate_stats['text_checked']:
        _log(
            'WARNING',
            'Stage 3.5',
            f'Typography gate produced NO usable verdict in '
            f'{_tx_calls} calls — renders shipped without any '
            f'lettering review. Check the Qwen3-VL judge '
            f'({paths.ZYG_MODELS_DIR / "vlm_judge"}) and '
            f'ANTHROPIC_API_KEY.',
        )
    elif _vlm_gate_stats['text_skipped']:
        _log(
            'WARNING',
            'Stage 3.5',
            f'Typography gate skipped {_vlm_gate_stats["text_skipped"]} '
            f'frame(s) — local judge unusable AND no '
            f'ANTHROPIC_API_KEY in the environment',
        )
    pipeline_state['vlm_gate_stats'] = dict(_vlm_gate_stats)
    if _vlm_text_boxes:
        pipeline_state['vlm_text_boxes'] = dict(_vlm_text_boxes)
    # A gate that reached no frame at all did not run, however
    # many times it was called: 'checked 0' with a live judge
    # and 'checked 0' with a dead one read identically in the
    # log, so the receipt records which of the two it was.
    _gate_receipt(
        'typography',
        bool(_vlm_gate_stats['text_checked']),
        (
            ''
            if _vlm_gate_stats['text_checked']
            else f'judge={_tx_judge}, no frame produced a verdict ({_tx_calls} call(s))'
        ),
        {
            'checked': _vlm_gate_stats['text_checked'],
            'flagged': _vlm_gate_stats['typography'],
            'skipped': _vlm_gate_stats['text_skipped'],
            'unreadable': _vlm_gate_stats['text_unreadable'],
            'second_vote': _vlm_gate_stats['text_second_vote'],
            'second_flag': _vlm_gate_stats['text_second_flag'],
            'judge': _tx_judge,
        },
    )


def slot_outcomes(slot_review: dict, shipped_flagged, *, qc_enabled: bool, era_enabled: bool) -> SlotOutcomes:
    """Turn the per-slot review records into the gate-outcome lists. Pure.

    In: `{slot: review}` and the list of `{'slot': n, ...}` records that shipped
    with an unresolved flag; the two gate switches decide which `unreviewed`
    verdicts count against "clean". Out: a `SlotOutcomes` whose `.outcomes` is
    exactly what `pipeline_state['slot_gate_outcomes']` holds.

    The old "every slot cleared" line was printed on a run whose
    hook shipped anatomy-unreviewed and whose slot 35 shipped at
    0.45 with a repaired-then-still-wrong map. A gate that did
    not look is not a gate that passed; the lists name the slots
    each judge never saw, the slots under the QA threshold, the
    slots repaired in place, and the slots that shipped flagged.
    """
    _unrev = {
        k: sorted(i for i, r in slot_review.items() if r.get(k) == 'unreviewed')
        for k in ('anatomy', 'typography', 'era')
    }
    _subthr = sorted(
        i
        for i, r in slot_review.items()
        if r.get('score') is not None and r.get('anatomy_shot') and float(r['score']) < 0.72
    )
    _repaired = sorted(i for i, r in slot_review.items() if r.get('repaired'))
    # 'escalated' = the anatomy verdict came from the second judge
    # after moondream returned nothing (P-08) — reviewed, but by
    # a judge that caught 0/9 on the 08-24 panel, so it is named.
    _escalated = sorted(i for i, r in slot_review.items() if r.get('anatomy') == 'escalated')
    _flagged_slots = sorted(int(_f['slot']) for _f in shipped_flagged)
    _n_clean = sum(
        1
        for i, r in slot_review.items()
        if i not in _flagged_slots
        and i not in _subthr
        and all(r.get(k) != 'unreviewed' for k in ('anatomy', 'typography') if qc_enabled or k != 'anatomy')
        and (r.get('era') != 'unreviewed' or not era_enabled)
    )
    _outcomes = {
        'slots': len(slot_review),
        'clean': _n_clean,
        'unreviewed_anatomy': _unrev['anatomy'],
        'unreviewed_typography': _unrev['typography'],
        'unreviewed_era': _unrev['era'] if era_enabled else [],
        'sub_threshold': _subthr,
        'repaired': _repaired,
        'escalated_anatomy': _escalated,
        'shipped_flagged': _flagged_slots,
        'per_slot': {
            str(i): {k: v for k, v in r.items() if not k.endswith(('_a0', '_a1', '_a2'))}
            for i, r in slot_review.items()
        },
    }
    return SlotOutcomes(
        outcomes=_outcomes,
        unreviewed=_unrev,
        sub_threshold=_subthr,
        repaired=_repaired,
        escalated=_escalated,
        flagged_slots=_flagged_slots,
        clean=_n_clean,
        slots=len(slot_review),
    )


def report_slot_outcomes(fs, ctx, so: SlotOutcomes) -> None:
    """Log the GATE OUTCOMES line and write the outcomes into `pipeline_state`.

    The line is a WARNING when anything shipped flagged, landed under the QA
    threshold or went unreviewed, and INFO otherwise.
    """
    _log = ctx._log
    pipeline_state = ctx.pipeline_state
    _shipped_flagged = fs._shipped_flagged
    _unrev, _subthr, _repaired = so.unreviewed, so.sub_threshold, so.repaired
    _escalated, _flagged_slots, _n_clean = so.escalated, so.flagged_slots, so.clean
    pipeline_state['slot_gate_outcomes'] = so.outcomes
    _lvl_line = 'WARNING' if (_flagged_slots or _subthr or any(_unrev.values())) else 'INFO'
    _log(
        _lvl_line,
        'Stage 3.5',
        f'GATE OUTCOMES — {_n_clean}/{so.slots} slots fully reviewed and clean; '
        f'unreviewed by anatomy judge: {_unrev["anatomy"] or "none"}; '
        f'unreviewed by typography judge: {_unrev["typography"] or "none"}; '
        + (f'unreviewed by era judge: {_unrev["era"] or "none"}; ' if fs._VLM_ERA_ENABLED else '')
        + f'below QA 0.72: {_subthr or "none"}; repaired in place: {_repaired or "none"}; '
        f'anatomy escalated to second judge: {_escalated or "none"}; '
        f'shipped flagged: {_flagged_slots or "none"}',
    )
    if _shipped_flagged:
        _log(
            'WARNING',
            'Stage 3.5',
            f'{len(_shipped_flagged)} slot(s) shipped with an '
            f'unresolved gate flag after the full retry ladder: '
            f'{", ".join(str(_f["slot"]) for _f in _shipped_flagged)}',
        )
        pipeline_state['shipped_flagged'] = list(_shipped_flagged)
    else:
        pipeline_state['shipped_flagged'] = []


def report_era_and_ladder(fs, ctx, so: SlotOutcomes) -> None:
    """File the era-gate and retry-ladder receipts and the era stats.

    The ladder ran iff at least one slot was attempted; the
    receipt carries how far up it actually climbed, which is
    the number the escalation claims have to be judged against.
    """
    _gate_receipt = ctx._gate_receipt
    _era_gate_stats = fs._era_gate_stats
    _ladder_stats = fs._ladder_stats
    _unrev = so.unreviewed
    # Era gate receipt
    if fs._VLM_ERA_ENABLED:
        _gate_receipt(
            'era',
            bool(_era_gate_stats['checked']),
            (
                ''
                if _era_gate_stats['checked']
                else f'no frame produced a verdict ({_era_gate_stats["unavailable"]} unavailable)'
            ),
            {
                'checked': _era_gate_stats['checked'],
                'flagged': _era_gate_stats['flagged'],
                'gore': _era_gate_stats['gore'],
                'subject_missing': _era_gate_stats['subject_missing'],
                'unavailable': _era_gate_stats['unavailable'],
                'judge': _era_gate_stats['judge'],
                'seconds': round(_era_gate_stats['seconds'], 1),
                'by_id': dict(_era_gate_stats['by_id']),
                'unreviewed_slots': _unrev['era'],
            },
        )
    else:
        _gate_receipt(
            'era',
            False,
            'modern episode' if not ctx._era_lock['is_historical'] else 'ZYG_SCHOLARLY_VLM_ERA=0',
        )
    ctx.pipeline_state['era_gate_stats'] = dict(_era_gate_stats)
    _gate_receipt(
        'retry_ladder',
        bool(_ladder_stats['slots']),
        ('' if _ladder_stats['slots'] else 'no slot reached the ladder'),
        dict(
            _ladder_stats,
            unreviewed_anatomy=_unrev['anatomy'],
            unreviewed_typography=_unrev['typography'],
            sub_threshold=so.sub_threshold,
            shipped_flagged=so.flagged_slots,
        ),
    )
