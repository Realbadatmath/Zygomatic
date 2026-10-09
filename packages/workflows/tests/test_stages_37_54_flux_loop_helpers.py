# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the six stages `run_slot_loop` was split into.

`run_slot_loop` was 315 lines of render loop plus five report blocks, so none of
the arithmetic below had ever been reachable: the clean/unreviewed/sub-threshold
bookkeeping, the WARNING that tells a silent VLM gate from a clean run, the
typography receipt and the throughput estimate were all inline in a body that
drives FLUX on the GPU.

They are `stages_37_54_flux_loop_reports` functions now. `slot_outcomes` is
pure. The report functions take the `fs` / `ctx` frames whole, so a plain
`SimpleNamespace` carrying the handful of fields each one reads — plus a `_log`
that appends to a list — exercises them with no GPU, no Ollama and no network.
"""

from types import SimpleNamespace


from zyg_workflows.scholarly import stages_37_54_flux_loop as loop
from zyg_workflows.scholarly import stages_37_54_flux_loop_reports as rep


def _ctx(**over):
    """A `ctx` frame whose `_log` and `_gate_receipt` only record their calls."""
    logs: list = []
    receipts: list = []
    ns = SimpleNamespace(
        _log=lambda lvl, stage, msg: logs.append((lvl, stage, msg)),
        _debug=lambda *a, **k: None,
        _gate_receipt=lambda *a, **k: receipts.append(a),
        pipeline_state={},
        pipeline_id=1,
        _sch_qwen_stills=False,
        _n_flux_images=0,
        job={},
        _era_lock={'is_historical': True},
        logs=logs,
        receipts=receipts,
    )
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


def _vlm_stats(**over):
    """The `_vlm_gate_stats` counters both gate reports read, all zero."""
    stats = {
        'checked': 0,
        'defect': 0,
        'skipped': 0,
        'unreadable': 0,
        'anachronism': 0,
        'anatomy_reask': 0,
        'anatomy_reask_verdict': 0,
        'anatomy_escalated': 0,
        'anatomy_escalation_calls': 0,
        'text_checked': 0,
        'typography': 0,
        'text_skipped': 0,
        'text_unreadable': 0,
        'text_second_vote': 0,
        'text_second_flag': 0,
        'text_judge': '',
    }
    stats.update(over)
    return stats


# ── slot_outcomes: the pure one ──────────────────────────────────────────────


def test_a_slot_no_judge_ever_saw_is_not_counted_clean():
    review = {
        0: {'anatomy': 'ok', 'typography': 'ok', 'era': 'ok'},
        1: {'anatomy': 'unreviewed', 'typography': 'ok', 'era': 'ok'},
        2: {'anatomy': 'ok', 'typography': 'unreviewed', 'era': 'ok'},
    }
    so = rep.slot_outcomes(review, [], qc_enabled=True, era_enabled=True)
    assert so.slots == 3
    assert so.clean == 1
    assert so.unreviewed == {'anatomy': [1], 'typography': [2], 'era': []}
    assert so.outcomes['unreviewed_anatomy'] == [1]
    assert so.outcomes['clean'] == 1


def test_the_anatomy_verdict_stops_counting_when_the_qc_gate_is_off():
    review = {0: {'anatomy': 'unreviewed', 'typography': 'ok', 'era': 'ok'}}
    assert rep.slot_outcomes(review, [], qc_enabled=True, era_enabled=True).clean == 0
    off = rep.slot_outcomes(review, [], qc_enabled=False, era_enabled=True)
    assert off.clean == 1
    # the list still names the slot — only its weight against "clean" changed
    assert off.unreviewed['anatomy'] == [0]


def test_an_era_unreviewed_slot_is_clean_and_unlisted_when_the_era_gate_is_off():
    review = {0: {'anatomy': 'ok', 'typography': 'ok', 'era': 'unreviewed'}}
    on = rep.slot_outcomes(review, [], qc_enabled=True, era_enabled=True)
    assert (on.clean, on.outcomes['unreviewed_era']) == (0, [0])
    off = rep.slot_outcomes(review, [], qc_enabled=True, era_enabled=False)
    assert off.clean == 1
    assert off.outcomes['unreviewed_era'] == []
    # the era receipt still needs the raw list even when the dict blanked it
    assert off.unreviewed['era'] == [0]


def test_only_an_anatomy_shot_under_072_counts_sub_threshold():
    review = {
        0: {'score': 0.45, 'anatomy_shot': True},
        1: {'score': 0.45, 'anatomy_shot': False},
        2: {'score': 0.72, 'anatomy_shot': True},
        3: {'score': None, 'anatomy_shot': True},
    }
    so = rep.slot_outcomes(review, [], qc_enabled=True, era_enabled=True)
    assert so.sub_threshold == [0]
    assert so.outcomes['sub_threshold'] == [0]
    # the other three are clean: a 0.45 on a non-anatomy shot is not a defect
    assert so.clean == 3


def test_repaired_escalated_and_shipped_flagged_slots_are_named_and_sorted():
    review = {
        5: {'repaired': True, 'anatomy': 'escalated'},
        2: {'repaired': True, 'anatomy': 'ok'},
        9: {'anatomy': 'escalated'},
    }
    so = rep.slot_outcomes(review, [{'slot': 9}, {'slot': '2'}], qc_enabled=True, era_enabled=True)
    assert so.repaired == [2, 5]
    assert so.escalated == [5, 9]
    assert so.flagged_slots == [2, 9]
    assert so.outcomes['shipped_flagged'] == [2, 9]
    # slot 5 is the only one neither flagged nor under the threshold, and an
    # 'escalated' anatomy verdict is a verdict: a second judge did look at it
    assert so.clean == 1


def test_per_slot_keeps_the_review_but_drops_the_per_attempt_keys():
    review = {3: {'anatomy': 'ok', 'score': 0.9, 'prompt_a0': 'x', 'note_a2': 'y'}}
    so = rep.slot_outcomes(review, [], qc_enabled=True, era_enabled=True)
    assert so.outcomes['per_slot'] == {'3': {'anatomy': 'ok', 'score': 0.9}}


# ── the VLM render gate report ───────────────────────────────────────────────


def test_a_disabled_render_gate_reports_nothing_at_all():
    ctx = _ctx()
    rep.report_vlm_gate(SimpleNamespace(_VLM_QC_ENABLED=False), ctx)
    assert ctx.logs == []
    assert ctx.pipeline_state == {}


def test_a_gate_that_answered_nothing_shouts_that_renders_shipped_unreviewed():
    ctx = _ctx()
    stats = _vlm_stats(skipped=4, unreadable=5)
    rep.report_vlm_gate(
        SimpleNamespace(
            _VLM_QC_ENABLED=True,
            _VLM_ERA_ENABLED=False,
            _VLM_QC_MODEL='moondream',
            _vlm_gate_stats=stats,
            _anatomy_esc_budget=3,
        ),
        ctx,
    )
    levels = [lvl for lvl, _s, _m in ctx.logs]
    assert levels == ['INFO', 'WARNING']
    assert 'NO usable verdict in 9 calls' in ctx.logs[1][2]
    assert 'moondream' in ctx.logs[0][2] and 'moondream' in ctx.logs[1][2]
    assert ctx.pipeline_state['vlm_gate_stats'] == stats
    assert ctx.pipeline_state['vlm_gate_stats'] is not stats


def test_a_gate_that_looked_at_every_frame_logs_one_info_line_only():
    ctx = _ctx()
    rep.report_vlm_gate(
        SimpleNamespace(
            _VLM_QC_ENABLED=True,
            _VLM_ERA_ENABLED=True,
            _VLM_QC_MODEL='qwen',
            _vlm_gate_stats=_vlm_stats(checked=9, defect=1, anachronism=2),
            _anatomy_esc_budget=3,
        ),
        ctx,
    )
    assert [lvl for lvl, _s, _m in ctx.logs] == ['INFO']
    assert '9 checked, 1 flagged' in ctx.logs[0][2]
    assert ', 2 anachronism' in ctx.logs[0][2]


def test_mostly_unreadable_is_reported_as_an_unproven_zero_defect_result():
    ctx = _ctx()
    rep.report_vlm_gate(
        SimpleNamespace(
            _VLM_QC_ENABLED=True,
            _VLM_ERA_ENABLED=False,
            _VLM_QC_MODEL='m',
            _vlm_gate_stats=_vlm_stats(checked=1, unreadable=8),
            _anatomy_esc_budget=3,
        ),
        ctx,
    )
    assert [lvl for lvl, _s, _m in ctx.logs] == ['INFO', 'WARNING']
    assert 'treat the 0-defect result as unproven' in ctx.logs[1][2]


# ── the typography gate report ───────────────────────────────────────────────


def test_a_disabled_typography_gate_still_files_its_receipt():
    ctx = _ctx()
    rep.report_typography(SimpleNamespace(_VLM_TEXT_ENABLED=False), ctx)
    assert ctx.logs == []
    assert ctx.receipts == [('typography', False, 'ZYG_SCHOLARLY_VLM_TEXT=0')]


def test_the_typography_receipt_records_which_judge_produced_no_verdict():
    ctx = _ctx()
    rep.report_typography(
        SimpleNamespace(
            _VLM_TEXT_ENABLED=True,
            _vlm_gate_stats=_vlm_stats(text_skipped=2, text_unreadable=1, text_judge='qwen3-vl'),
            _vlm_text_boxes={},
        ),
        ctx,
    )
    name, passed, why, detail = ctx.receipts[0]
    assert (name, passed) == ('typography', False)
    assert why == 'judge=qwen3-vl, no frame produced a verdict (3 call(s))'
    assert detail['judge'] == 'qwen3-vl' and detail['skipped'] == 2
    assert [lvl for lvl, _s, _m in ctx.logs] == ['INFO', 'WARNING']
    assert 'NO usable verdict in 3 calls' in ctx.logs[1][2]


def test_a_typography_gate_that_read_lettering_passes_with_an_empty_reason():
    ctx = _ctx()
    rep.report_typography(
        SimpleNamespace(
            _VLM_TEXT_ENABLED=True,
            _vlm_gate_stats=_vlm_stats(text_checked=6, typography=1, text_judge='qwen3-vl'),
            _vlm_text_boxes={'0': [[1, 2, 3, 4]]},
        ),
        ctx,
    )
    name, passed, why, detail = ctx.receipts[0]
    assert (name, passed, why) == ('typography', True, '')
    assert detail['checked'] == 6 and detail['flagged'] == 1
    assert [lvl for lvl, _s, _m in ctx.logs] == ['INFO']
    assert ctx.pipeline_state['vlm_text_boxes'] == {'0': [[1, 2, 3, 4]]}


def test_a_judge_that_never_named_itself_is_reported_as_none():
    ctx = _ctx()
    rep.report_typography(
        SimpleNamespace(
            _VLM_TEXT_ENABLED=True,
            _vlm_gate_stats=_vlm_stats(text_checked=1),
            _vlm_text_boxes={},
        ),
        ctx,
    )
    assert 'Typography gate (none):' in ctx.logs[0][2]
    assert ctx.receipts[0][3]['judge'] == 'none'
    assert 'vlm_text_boxes' not in ctx.pipeline_state


# ── the outcomes line ────────────────────────────────────────────────────────


def test_the_gate_outcomes_line_is_info_only_when_nothing_went_wrong():
    ctx = _ctx()
    so = rep.slot_outcomes(
        {0: {'anatomy': 'ok', 'typography': 'ok', 'era': 'ok'}}, [], qc_enabled=True, era_enabled=True
    )
    rep.report_slot_outcomes(SimpleNamespace(_shipped_flagged=[], _VLM_ERA_ENABLED=False), ctx, so)
    assert [lvl for lvl, _s, _m in ctx.logs] == ['INFO']
    assert 'GATE OUTCOMES — 1/1 slots fully reviewed and clean' in ctx.logs[0][2]
    assert 'unreviewed by era judge' not in ctx.logs[0][2]
    assert ctx.pipeline_state['shipped_flagged'] == []
    assert ctx.pipeline_state['slot_gate_outcomes'] is so.outcomes


def test_a_slot_that_shipped_flagged_makes_the_line_a_warning_and_names_it():
    ctx = _ctx()
    flagged = [{'slot': 7, 'why': 'hands'}]
    so = rep.slot_outcomes(
        {7: {'anatomy': 'ok', 'typography': 'ok', 'era': 'ok'}}, flagged, qc_enabled=True, era_enabled=True
    )
    rep.report_slot_outcomes(SimpleNamespace(_shipped_flagged=flagged, _VLM_ERA_ENABLED=True), ctx, so)
    assert [lvl for lvl, _s, _m in ctx.logs] == ['WARNING', 'WARNING']
    assert 'shipped flagged: [7]' in ctx.logs[0][2]
    assert 'unreviewed by era judge: none;' in ctx.logs[0][2]
    assert '1 slot(s) shipped with an unresolved gate flag' in ctx.logs[1][2]
    assert ctx.pipeline_state['shipped_flagged'] == flagged


# ── the era and retry-ladder receipts ────────────────────────────────────────


def _era_stats(**over):
    stats = {
        'checked': 0,
        'flagged': 0,
        'gore': 0,
        'subject_missing': 0,
        'unavailable': 0,
        'judge': 'j',
        'seconds': 1.234,
        'by_id': {},
    }
    stats.update(over)
    return stats


def test_a_modern_episode_files_an_era_receipt_saying_so():
    ctx = _ctx(_era_lock={'is_historical': False})
    so = rep.slot_outcomes({}, [], qc_enabled=True, era_enabled=False)
    rep.report_era_and_ladder(
        SimpleNamespace(
            _VLM_ERA_ENABLED=False,
            _era_gate_stats=_era_stats(),
            _ladder_stats={'slots': 0},
        ),
        ctx,
        so,
    )
    assert ctx.receipts[0] == ('era', False, 'modern episode')
    assert ctx.receipts[1][:3] == ('retry_ladder', False, 'no slot reached the ladder')


def test_a_historical_episode_with_the_gate_off_names_the_switch():
    ctx = _ctx()
    so = rep.slot_outcomes({}, [], qc_enabled=True, era_enabled=False)
    rep.report_era_and_ladder(
        SimpleNamespace(_VLM_ERA_ENABLED=False, _era_gate_stats=_era_stats(), _ladder_stats={'slots': 0}),
        ctx,
        so,
    )
    assert ctx.receipts[0] == ('era', False, 'ZYG_SCHOLARLY_VLM_ERA=0')


def test_the_ladder_receipt_carries_how_far_the_ladder_actually_climbed():
    ctx = _ctx()
    so = rep.slot_outcomes(
        {1: {'anatomy': 'unreviewed', 'score': 0.4, 'anatomy_shot': True}}, [], qc_enabled=True, era_enabled=True
    )
    rep.report_era_and_ladder(
        SimpleNamespace(
            _VLM_ERA_ENABLED=True,
            _era_gate_stats=_era_stats(checked=3, flagged=1, seconds=2.449),
            _ladder_stats={'slots': 4, 'rung2': 1},
        ),
        ctx,
        so,
    )
    era, ladder = ctx.receipts
    assert (era[0], era[1], era[2]) == ('era', True, '')
    assert era[3]['seconds'] == 2.4 and era[3]['unreviewed_slots'] == []
    assert ctx.pipeline_state['era_gate_stats'] == _era_stats(checked=3, flagged=1, seconds=2.449)
    assert ladder[0] == 'retry_ladder' and ladder[1] is True
    assert ladder[3]['slots'] == 4 and ladder[3]['rung2'] == 1
    assert ladder[3]['unreviewed_anatomy'] == [1]
    assert ladder[3]['sub_threshold'] == [1]


# ── the throughput estimate ──────────────────────────────────────────────────


def test_an_empty_run_logs_the_count_line_and_estimates_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(rep, '_update_flux_seconds_per_image_estimate', lambda *a, **k: called.append(a) or 1.0)
    ctx = _ctx()
    rep.report_throughput(SimpleNamespace(_flux_generated_paths=[], _sch_family_label='FLUX'), ctx, 12.0)
    assert called == []
    assert ctx.logs == [('INFO', 'Stage 3.5', 'Generated 0 FLUX images')]
    assert ctx.pipeline_state == {}


def test_the_observed_seconds_per_image_is_folded_into_the_next_run_estimate(monkeypatch):
    seen = {}

    def _fake(observed, *, image_count, family, pipeline_id):
        seen.update(observed=observed, image_count=image_count, family=family, pipeline_id=pipeline_id)
        return 7.5

    monkeypatch.setattr(rep, '_update_flux_seconds_per_image_estimate', _fake)
    ctx = _ctx(_sch_qwen_stills=True, pipeline_id=42)
    rep.report_throughput(
        SimpleNamespace(_flux_generated_paths=['a', 'b', 'c', 'd'], _sch_family_label='Qwen'), ctx, 40.0
    )
    assert seen == {'observed': 10.0, 'image_count': 4, 'family': 'qwen', 'pipeline_id': 42}
    assert ctx.pipeline_state['flux_seconds_per_image_estimate'] == 7.5
    assert ctx.pipeline_state['flux_gen_elapsed_s'] == 40.0
    assert '~10.00s/image' in ctx.logs[0][2]
    assert 'next-run estimate ~7.50s/image' in ctx.logs[0][2]
    assert ctx.logs[1][2] == 'Generated 4 Qwen images'


# ── the orchestrator is only the call order ──────────────────────────────────


def test_the_orchestrator_runs_the_six_stages_in_the_order_the_loop_always_did(monkeypatch):
    order = []
    monkeypatch.setattr(rep, 'render_slots', lambda fs, ctx: order.append('render') or 9.0)
    monkeypatch.setattr(rep, 'report_throughput', lambda fs, ctx, s: order.append(('throughput', s)))
    monkeypatch.setattr(rep, 'report_vlm_gate', lambda fs, ctx: order.append('vlm'))
    monkeypatch.setattr(rep, 'report_typography', lambda fs, ctx: order.append('typography'))
    monkeypatch.setattr(rep, 'report_slot_outcomes', lambda fs, ctx, so: order.append(('outcomes', so.slots)))
    monkeypatch.setattr(rep, 'report_era_and_ladder', lambda fs, ctx, so: order.append('era'))
    fs = SimpleNamespace(
        _slot_review={0: {'anatomy': 'ok', 'typography': 'ok', 'era': 'ok'}},
        _shipped_flagged=[],
        _VLM_QC_ENABLED=True,
        _VLM_ERA_ENABLED=True,
    )
    loop.run_slot_loop(fs, _ctx())
    assert order == ['render', ('throughput', 9.0), 'vlm', 'typography', ('outcomes', 1), 'era']


def test_the_reports_module_never_imports_the_orchestrator_back():
    src = open(rep.__file__).read()
    assert 'stages_37_54_flux_loop ' not in src.replace('stages_37_54_flux_loop_reports', '')
    # and the orchestrator stayed where its callers look for it
    assert not hasattr(rep, 'run_slot_loop')
    assert callable(loop.run_slot_loop)
