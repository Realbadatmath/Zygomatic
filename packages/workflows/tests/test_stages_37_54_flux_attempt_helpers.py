# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the helpers split out of Stage 3.5's `run_attempt`.

`run_attempt` was the 638-line body of `for _attempt in range(3):`, so every
decision below could only ever be reached by a GPU render: which rung of the
retry ladder an attempt climbs, whether it keeps the seed or re-rolls it, what
the Qwen live negative says, how CLIP-L sees the prompt, and which `Attempt`
sentinel each verdict hands back to the ladder. None of them had been exercised
in isolation before this file.

Nothing here loads a model, opens a socket or touches a service: the four
sibling gates are replaced on the `AttemptEnv` after it is built, and the slot
is a plain `SlotState`.
"""

import collections
import types

import pytest

from zyg_workflows.scholarly import stages_37_54_flux_attempt_ladder as ladder
from zyg_workflows.scholarly import stages_37_54_flux_attempt_render as render
from zyg_workflows.scholarly.context import UNSET
from zyg_workflows.scholarly.stages_37_54_flux_state import Attempt, SlotState

# Every name `AttemptEnv.build` reads off `ctx`, and off `fs`. Kept here so a
# field added to the carrier without a source shows up as a test failure rather
# than as an attempt that silently renders with None.
_CTX_NAMES = (
    '_FLUX_NEGATIVE',
    '_debug',
    '_era_lock',
    '_flux_lever_guard',
    '_log',
    '_sch_qwen_stills',
    '_sch_use_comfy_images',
    'job',
    'out_dir',
    'pipeline_id',
    'pipeline_state',
    'visual_style',
)
_FS_NAMES = (
    '_cn_pipe',
    '_cns',
    '_flux_images_dir',
    '_flux_pipe',
    '_ipa',
    '_ipa_ready',
    '_ladder_stats',
    '_torch_flux',
)


def _env(**over):
    """An `AttemptEnv` over stand-in `fs`/`ctx` objects, with recording log sinks.

    `_log_lines` and `_debug_lines` are the two lists every assertion about a
    log line reads; `_ladder_stats` is a counting dict so a rung may bump a key
    nobody declared.
    """
    log_lines: list = []
    debug_lines: list = []
    ctx = types.SimpleNamespace(
        _FLUX_NEGATIVE='blurry, low quality',
        _debug=lambda stage, msg, level='INFO': debug_lines.append((stage, msg, level)),
        _era_lock={'is_historical': False, 'period_label': '14th century Florence'},
        _flux_lever_guard=lambda *a: None,
        _log=lambda level, stage, msg: log_lines.append((level, stage, msg)),
        _sch_qwen_stills=False,
        _sch_use_comfy_images=False,
        job={},
        out_dir='/tmp/zyg-attempt-tests-does-not-exist',  # noqa: S108
        pipeline_id='pid-1',
        pipeline_state={},
        visual_style='cinematic',
    )
    fs = types.SimpleNamespace(
        _cn_pipe=None,
        _cns=None,
        _flux_images_dir='/tmp/zyg-attempt-tests-does-not-exist/images',  # noqa: S108
        _flux_pipe=None,
        _ipa=None,
        _ipa_ready=False,
        _ladder_stats=collections.defaultdict(int),
        _torch_flux=None,
    )
    for name, value in over.items():
        target = ctx if hasattr(ctx, name) else fs
        setattr(target, name, value)
    env = ladder.AttemptEnv.build(fs, ctx)
    env._log_lines = log_lines
    env._debug_lines = debug_lines
    return env


def _slot(**over):
    """A `SlotState` with the sixteen fields `generate_one` binds before the ladder."""
    slot = SlotState(
        idx=3,
        _prompt='a plague doctor in a narrow street',
        _subj='a plague doctor',
        _n_steps=8,
        _g_scale=0.0,
        _gen_seed=1000,
        _is_anatomy_shot=True,
    )
    for name, value in over.items():
        setattr(slot, name, value)
    return slot


# ── ladder_exhausted: which attempts are allowed to render at all ───────────


def test_attempt_zero_always_renders():
    """The first attempt is never skipped, whatever the flags say."""
    assert ladder.ladder_exhausted(_slot(_is_anatomy_shot=False), 0) is False


def test_anatomy_shots_always_retry():
    """An anatomy shot gets its three attempts even with the gate clean."""
    assert ladder.ladder_exhausted(_slot(_is_anatomy_shot=True), 1) is False


def test_unflagged_environment_shot_stops_after_one_attempt():
    """An environment shot nothing flagged does not pay for a retry."""
    slot = _slot(_is_anatomy_shot=False, _vlm_fail_prev=False)
    assert ladder.ladder_exhausted(slot, 1) is True
    assert ladder.ladder_exhausted(slot, 2) is True


def test_flagged_environment_shot_retries():
    """A VLM defect on the last attempt buys an environment shot another one."""
    slot = _slot(_is_anatomy_shot=False, _vlm_fail_prev=True)
    assert ladder.ladder_exhausted(slot, 1) is False


def test_always_reroll_buys_one_extra_attempt_only():
    """`_always_reroll` reaches attempt 2 and stops; it never reaches attempt 3."""
    slot = _slot(_is_anatomy_shot=False, _vlm_fail_prev=False, _always_reroll=True)
    assert ladder.ladder_exhausted(slot, 1) is False
    assert ladder.ladder_exhausted(slot, 2) is True


# ── choose_rung: the eight-way ladder, in its original order ────────────────


def test_first_attempt_renders_the_prompt_as_written():
    """Attempt 0 renders the composed prompt at the slot's own steps and scale."""
    env, slot = _env(), _slot()
    prompt, anat_neg = ladder.choose_rung(env, slot, 0)
    assert prompt == slot._prompt
    assert anat_neg is False
    assert (slot._steps_attempt, slot._scale_attempt) == (8, 0.0)


def test_typography_defect_skips_the_reroll_for_the_suppression_clause():
    """A text failure at attempt 1 asks for no lettering instead of re-rolling."""
    env, slot = _env(), _slot(_vlm_text_fail_prev=True)
    prompt, _ = ladder.choose_rung(env, slot, 1)
    assert prompt.startswith(slot._prompt)
    assert 'no readable lettering anywhere in frame' in prompt
    assert slot._clause_used is True
    assert env._ladder_stats['text_clause'] == 1
    assert (slot._steps_attempt, slot._scale_attempt) == (8, 0.0)


def test_era_defect_appends_the_gates_own_qualifier_and_keeps_the_steps():
    """The first anachronism rung uses the era gate's fix phrase, nothing else."""
    env, slot = _env(), _slot(_vlm_era_fail_prev=True)
    env._era_ladder_qualifier = lambda idx: ', a linen coif, not a modern cap'
    prompt, _ = ladder.choose_rung(env, slot, 1)
    assert prompt == slot._prompt + ', a linen coif, not a modern cap'
    assert slot._era_rung_used == 1
    assert env._ladder_stats['era_edit'] == 1


def test_era_rung_falls_back_to_the_period_label():
    """With no object-specific phrase the rung restates the period generically."""
    env, slot = _env(), _slot(_vlm_era_fail_prev=True)
    env._era_ladder_qualifier = lambda idx: ''
    prompt, _ = ladder.choose_rung(env, slot, 1)
    assert prompt.endswith(', strictly period-accurate 14th century Florence, historical reconstruction')


def test_second_attempt_is_a_pure_reroll_when_nothing_was_flagged_by_name():
    """Anatomy-only defects get the identical prompt at a new seed."""
    env, slot = _env(), _slot()
    prompt, anat_neg = ladder.choose_rung(env, slot, 1)
    assert (prompt, anat_neg) == (slot._prompt, False)
    assert env._ladder_stats['reroll'] == 1


def test_third_attempt_strips_the_written_subject(monkeypatch):
    """Attempt 3 on a text failure drops the written object and raises the steps."""
    monkeypatch.setattr(ladder, '_smoke_cap', lambda: 0)
    monkeypatch.setattr(ladder, '_strip_written_subject', lambda p: 'two women talking')
    env, slot = _env(), _slot(_vlm_text_fail_prev=True, _clause_used=True)
    prompt, _ = ladder.choose_rung(env, slot, 2)
    assert prompt.startswith('two women talking, no readable lettering')
    assert 'no printed words' in prompt
    assert slot._steps_attempt == 20
    assert env._ladder_stats['text_strip'] == 1
    assert 'lettering survived the suppression clause' in env._log_lines[-1][2]


def test_the_text_strip_rung_names_the_reroll_when_no_clause_ran(monkeypatch):
    """A slot whose first defect was anatomy survived the re-roll, not the clause."""
    monkeypatch.setattr(ladder, '_smoke_cap', lambda: 0)
    env, slot = _env(), _slot(_vlm_text_fail_prev=True, _clause_used=False)
    ladder.choose_rung(env, slot, 2)
    assert 'lettering survived the re-roll' in env._log_lines[-1][2]


def test_the_text_strip_rung_stays_cheap_under_the_smoke_cap(monkeypatch):
    """A smoke run keeps four steps rather than paying for twenty."""
    monkeypatch.setattr(ladder, '_smoke_cap', lambda: 2)
    env, slot = _env(), _slot(_vlm_text_fail_prev=True)
    ladder.choose_rung(env, slot, 2)
    assert slot._steps_attempt == 4


def test_the_second_era_rung_keeps_the_qualifier_and_restates_the_period(monkeypatch):
    """Rung two of the anachronism ladder adds the generic restatement on top."""
    monkeypatch.setattr(ladder, '_smoke_cap', lambda: 0)
    env, slot = _env(), _slot(_vlm_era_fail_prev=True, _era_rung_used=1)
    env._era_ladder_qualifier = lambda idx: ', a linen coif'
    prompt, _ = ladder.choose_rung(env, slot, 2)
    assert prompt.startswith(slot._prompt + ', a linen coif, strictly period-accurate 14th century Florence, ')
    assert 'lit only by daylight fire candle or oil lamp' in prompt
    assert slot._era_rung_used == 2
    assert slot._steps_attempt == 20
    assert env._ladder_stats['era_escalation'] == 1


def test_qwen_takes_a_real_guidance_step_on_the_second_era_rung(monkeypatch):
    """On Qwen the negatives are live, so cfg 3.5 / 28 steps actually bites."""
    monkeypatch.setattr(ladder, '_smoke_cap', lambda: 0)
    env, slot = _env(_sch_qwen_stills=True), _slot(_vlm_era_fail_prev=True, _era_rung_used=1)
    env._era_ladder_qualifier = lambda idx: ''
    ladder.choose_rung(env, slot, 2)
    assert (slot._steps_attempt, slot._scale_attempt) == (28, 3.5)


def test_the_last_rung_is_the_anatomy_escalation(monkeypatch):
    """With nothing named by the gate, attempt 3 asks for correct anatomy."""
    monkeypatch.setattr(ladder, '_smoke_cap', lambda: 0)
    env, slot = _env(), _slot()
    prompt, anat_neg = ladder.choose_rung(env, slot, 2)
    assert prompt.endswith(', perfectly formed hands, correct number of fingers, natural human anatomy')
    assert anat_neg is True
    assert slot._steps_attempt == 28
    assert env._ladder_stats['anatomy_escalation'] == 1


# ── attempt_seed / attempt_path ─────────────────────────────────────────────


def test_each_retry_explores_a_new_seed():
    """A plain retry adds the attempt number to the slot's seed."""
    slot = _slot(_gen_seed=1000)
    assert [ladder.attempt_seed(slot, n) for n in range(3)] == [1000, 1001, 1002]


def test_an_era_prompt_edit_keeps_the_seed():
    """The composition was fine, so an era edit must not re-roll it away."""
    slot = _slot(_gen_seed=1000, _vlm_era_fail_prev=True)
    assert ladder.attempt_seed(slot, 1) == 1000


def test_a_text_failure_beats_the_era_seed_lock():
    """A slot flagged for both takes the typography rung, which re-rolls."""
    slot = _slot(_gen_seed=1000, _vlm_era_fail_prev=True, _vlm_text_fail_prev=True)
    assert ladder.attempt_seed(slot, 1) == 1001


def test_the_seed_stays_inside_the_31_bit_range():
    """diffusers rejects a seed over 2**31, so the sum is wrapped."""
    slot = _slot(_gen_seed=2**31 - 1)
    assert ladder.attempt_seed(slot, 2) == 1


def test_the_first_attempt_writes_the_unsuffixed_path():
    """Attempt 0 writes `flux_NNN.jpg`; the retries get `_r1` and `_r2`."""
    assert ladder.attempt_path('/img', 7, 0) == '/img/flux_007.jpg'
    assert ladder.attempt_path('/img', 7, 1) == '/img/flux_007_r1.jpg'
    assert ladder.attempt_path('/img', 12, 2) == '/img/flux_012_r2.jpg'


# ── AttemptEnv.build: the glue block that opened `run_attempt` ──────────────


def test_every_carrier_field_comes_from_fs_or_ctx():
    """A field with no source would make the attempt render against None."""
    env = _env()
    for name in _CTX_NAMES + _FS_NAMES:
        assert getattr(env, name) is not None or name in ('_cn_pipe', '_cns', '_flux_pipe', '_ipa', '_torch_flux')
    assert set(_CTX_NAMES) | set(_FS_NAMES) < set(ladder.AttemptEnv.__dataclass_fields__)


def test_the_four_gates_arrive_pre_bound_to_fs_and_ctx():
    """Every gate is called as `env._gate(args)`, as the inline body called it."""
    env = _env()
    for gate in ('_era_ladder_qualifier', '_mediapipe_qa_score', '_record_slot_review', '_vlm_render_gate'):
        assert callable(getattr(env, gate))
        assert getattr(env, gate).args is not None


# ── clip_prompt: what CLIP-L actually sees ──────────────────────────────────


def test_a_short_prompt_reaches_clip_unchanged():
    """Under the 77-token budget nothing is dropped."""
    assert render.clip_prompt('a plague doctor') == 'a plague doctor'


def test_a_long_prompt_is_cut_on_a_word_boundary():
    """Truncation mid-word would hand CLIP-L a nonsense token."""
    long_prompt = 'word ' * 100
    cut = render.clip_prompt(long_prompt)
    assert len(cut) <= 320
    assert cut == ('word ' * 100)[:320].rsplit(' ', 1)[0]
    assert not cut.endswith('wor')


# ── comfy_extra_negative: live negatives, Qwen only ─────────────────────────


def test_flux_on_comfy_gets_no_live_negative():
    """At guidance 0 on schnell a negative prompt is inert, so none is sent."""
    assert render.comfy_extra_negative(_env(), True) == ''


def test_qwen_sends_the_run_negative():
    """Real CFG means the negative finally does something."""
    assert render.comfy_extra_negative(_env(_sch_qwen_stills=True), False) == 'blurry, low quality'


def test_a_historical_run_adds_the_era_negative():
    """Period runs carry the anachronism terms too."""
    env = _env(_sch_qwen_stills=True, _era_lock={'is_historical': True, 'period_label': 'x'})
    neg = render.comfy_extra_negative(env, False)
    assert neg.startswith('blurry, low quality, ')
    assert len(neg) > len('blurry, low quality, ')


def test_the_anatomy_rung_puts_its_defect_terms_in_the_negative():
    """On Qwen the defect terms belong here, not as negated phrases in the positive."""
    neg = render.comfy_extra_negative(_env(_sch_qwen_stills=True), True)
    assert neg.endswith(', deformed hands, wrong number of fingers, extra limbs, missing limbs, deformities')


# ── comfy_style_lora ────────────────────────────────────────────────────────


def test_an_unknown_visual_style_falls_back_to_cinematic():
    """A style the LoRA table has never heard of still renders."""
    from zyg_workflows.pipeline_config import _STYLE_LORA_CONFIG

    config, path = render.comfy_style_lora('no-such-style')
    assert config is _STYLE_LORA_CONFIG['cinematic']
    assert path is None


def test_the_lora_file_is_only_offered_when_it_exists(tmp_path, monkeypatch):
    """A configured directory with no weights in it must not be passed to Comfy."""
    from zyg_workflows.pipeline_config import _STYLE_LORA_CONFIG

    monkeypatch.setitem(_STYLE_LORA_CONFIG, 'zyg-test-style', {'lora_dir': str(tmp_path)})
    assert render.comfy_style_lora('zyg-test-style')[1] is None
    (tmp_path / 'pytorch_lora_weights.safetensors').write_bytes(b'')
    assert render.comfy_style_lora('zyg-test-style')[1] == str(tmp_path / 'pytorch_lora_weights.safetensors')


# ── no_pipe_outcome: nothing rendered and nothing to render with ────────────


def test_qwen_retries_once_at_a_new_seed_before_giving_the_slot_up():
    """A ComfyUI timeout is not a property of the prompt, so it is worth one retry."""
    env, slot = _env(_sch_qwen_stills=True), _slot(_bk_cg='qwen_txt2img')
    assert render.no_pipe_outcome(env, slot, 0) is Attempt.CONTINUE
    assert slot._vlm_fail_prev is True
    assert 'Qwen render failed (qwen_txt2img)' in env._log_lines[-1][2]


def test_a_second_qwen_failure_breaks_out():
    """One retry only; a missing slot is better than a stalled run."""
    env, slot = _env(_sch_qwen_stills=True), _slot()
    assert render.no_pipe_outcome(env, slot, 1) is Attempt.BREAK


def test_an_unwritten_backend_label_reads_as_no_output():
    """`_bk_cg` is UNSET until the Comfy call returns, and the log says so."""
    env, slot = _env(), _slot()
    assert slot._bk_cg is UNSET
    assert render.no_pipe_outcome(env, slot, 0) is Attempt.BREAK
    assert 'ComfyGen failed (no output)' in env._log_lines[-1][2]


def test_a_retry_with_no_pipe_is_silent():
    """The first attempt already said it; the ladder does not repeat itself."""
    env, slot = _env(), _slot()
    assert render.no_pipe_outcome(env, slot, 2) is Attempt.BREAK
    assert env._log_lines == []


# ── score_and_gate and the two verdicts ─────────────────────────────────────


def _scored(env, score=0.9, issues=(), gate=(True, '')):
    """Point *env*'s QA and VLM gates at fixed answers and record the review calls."""
    env._reviews: list = []
    env._mediapipe_qa_score = lambda path: (score, list(issues))
    env._vlm_render_gate = lambda path, **kw: gate
    env._record_slot_review = lambda idx, attempt: env._reviews.append((idx, attempt))
    return env


def test_a_clean_still_keeps_its_score_and_clears_every_flag():
    """A passing gate is what tells the next attempt there is nothing to fix."""
    env, slot = _scored(_env()), _slot(_vlm_fail_prev=True, _vlm_text_fail_prev=True)
    qa_s, qa_iss, vlm_ok = render.score_and_gate(env, slot, 0, '/img/a.jpg', 'a prompt')
    assert (qa_s, qa_iss, vlm_ok) == (0.9, [], True)
    assert (slot._vlm_fail_prev, slot._vlm_era_fail_prev, slot._vlm_text_fail_prev) == (False, False, False)
    assert env._reviews == [(3, 0)]


def test_a_gate_defect_caps_the_score_and_names_itself():
    """A flagged still must never outscore a clean one, so 0.45 is the ceiling."""
    env = _scored(_env(), score=0.95, gate=(False, 'typography: reads RUSSIA'))
    slot = _slot()
    qa_s, qa_iss, vlm_ok = render.score_and_gate(env, slot, 1, '/img/a.jpg', 'a prompt')
    assert (qa_s, vlm_ok) == (0.45, False)
    assert qa_iss == ['vlm_defect: typography: reads RUSSIA']
    assert slot._vlm_text_fail_prev is True
    assert slot._vlm_era_fail_prev is False
    assert 'VLM gate DEFECT' in env._log_lines[-1][2]


def test_an_anachronism_verdict_routes_to_the_era_rung():
    """The flag the gate sets is what `choose_rung` dispatches on next attempt."""
    env = _scored(_env(), gate=(False, 'anachronism: a modern cap'))
    slot = _slot()
    render.score_and_gate(env, slot, 0, '/img/a.jpg', 'a prompt')
    assert (slot._vlm_era_fail_prev, slot._vlm_text_fail_prev) == (True, False)


def test_the_best_scoring_attempt_is_the_one_that_ships():
    """`promote_best` only moves the winner forward, never backward."""
    slot = _slot()
    render.promote_best(slot, '/img/a.jpg', 0.5)
    render.promote_best(slot, '/img/b.jpg', 0.3)
    assert (slot._best_path, slot._best_qa_score) == ('/img/a.jpg', 0.5)
    render.promote_best(slot, '/img/c.jpg', 0.8)
    assert (slot._best_path, slot._best_qa_score) == ('/img/c.jpg', 0.8)


def test_every_attempt_leaves_a_qa_row():
    """The slot summary and the receipt both read `_qa_attempts`."""
    slot = _slot()
    render.record_attempt(slot, 1, '/img/a.jpg', 0.6, ['hands'])
    assert slot._qa_attempts == [{'attempt': 1, 'score': 0.6, 'path': '/img/a.jpg', 'issues': ['hands']}]


@pytest.mark.parametrize(
    ('anatomy', 'score', 'gate_ok', 'ships'),
    [
        (True, 0.8, True, True),
        (True, 0.5, True, False),
        (False, 0.1, True, True),
        (False, 0.99, False, False),
        (True, 0.8, False, False),
    ],
)
def test_only_a_gated_and_well_scored_still_ships(anatomy, score, gate_ok, ships):
    """An environment shot only has to clear the gate; anatomy also needs 0.72."""
    assert render.accepted(_slot(_is_anatomy_shot=anatomy), score, gate_ok) is ships


def test_a_comfy_still_that_clears_both_tests_breaks_the_ladder():
    """ComfyGen judges its own output and never falls through to diffusers."""
    env, slot = _env(), _slot()
    assert render.comfy_verdict(env, slot, 0, '/img/a.jpg', 0.9, [], True) is Attempt.BREAK
    assert slot._best_path == '/img/a.jpg'
    assert len(slot._qa_attempts) == 1


def test_a_flagged_comfy_still_asks_for_another_attempt():
    """CONTINUE is the `continue` the inline loop body made here."""
    env, slot = _env(), _slot()
    assert render.comfy_verdict(env, slot, 0, '/img/a.jpg', 0.4, [], False) is Attempt.CONTINUE
    assert 'retrying (attempt 2/3)' in env._log_lines[-1][2]


def test_the_last_comfy_attempt_continues_without_promising_a_retry():
    """Attempt 3 of 3 has nothing left to retry, so it says nothing."""
    env, slot = _env(), _slot()
    assert render.comfy_verdict(env, slot, 2, '/img/a.jpg', 0.4, [], False) is Attempt.CONTINUE
    assert env._log_lines == []


def test_a_cleared_flux_still_records_which_rung_cleared_it():
    """`cleared_at_N` is how the run report says the ladder paid for itself."""
    env, slot = _env(), _slot()
    assert render.flux_verdict(env, slot, 1, '/img/a.jpg', 0.9, [], True) is Attempt.BREAK
    assert env._ladder_stats['cleared_at_2'] == 1
    assert slot._best_path == '/img/a.jpg'


def test_a_flux_still_that_fails_runs_off_the_end_of_the_body():
    """None is the end of the loop body: take the next attempt."""
    env, slot = _env(), _slot()
    assert render.flux_verdict(env, slot, 0, '/img/a.jpg', 0.4, ['hands'], True) is None
    assert any('issues=' in msg for _s, msg, _lvl in env._debug_lines)
    assert 'retrying (attempt 2/3)' in env._log_lines[-1][2]


def test_a_clean_flux_still_logs_an_ok_line_not_an_issues_line():
    """The QA debug line is the one place a reader sees the score per attempt."""
    env, slot = _env(), _slot(_is_anatomy_shot=True)
    render.flux_verdict(env, slot, 0, '/img/a.jpg', 0.5, [], True)
    assert env._debug_lines[-1][1].endswith('score=0.50 — OK')
