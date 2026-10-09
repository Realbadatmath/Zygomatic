# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the helpers split out of Stage 3.5's `generate_one`.

Every one of these decisions used to live inside a 646-line function that only a
GPU render could reach, so none of them had ever been exercised in isolation:
which shot counts as an anatomy shot, which tier it renders at, when a subject's
seed is locked, what the era anchor does to a prompt, which defect a flagged
shipment is reported under, and what the canonical rename leaves on disk.
"""

import types

import pytest

from zyg_workflows import gui_state
from zyg_workflows.scholarly import stages_37_54_flux_slot_prompt as sp
from zyg_workflows.scholarly import stages_37_54_flux_slot_ship as ship
from zyg_workflows.scholarly.context import UNSET


class _Rnd:
    """A `random.Random` stand-in handing out a fixed queue of seeds."""

    def __init__(self, *seeds):
        self.queue = list(seeds)
        self.calls = 0

    def randint(self, _lo, _hi):
        """Return the next queued seed and count the call."""
        self.calls += 1
        return self.queue.pop(0)


def _ctx(**over):
    """A RunContext stand-in: only the attributes the helpers under test read."""
    log_lines: list = []
    debug_lines: list = []
    ctx = types.SimpleNamespace(
        _debug=lambda stage, msg, level='INFO': debug_lines.append((stage, msg, level)),
        _log=lambda level, stage, msg: log_lines.append((level, stage, msg)),
        _log_lines=log_lines,
        _debug_lines=debug_lines,
        _era_lock={'is_historical': False},
        _fallback_subject='the black death',
        _n_flux_images=4,
        _narration_sentences=['one', 'two'],
        _murch_turning_points=[],
        _murch_image_debug=False,
        _essay_title_for_prompt='An Essay',
        _sch_qwen_stills=False,
        _sch_intensity={'rank': 0},
        _STYLE_SUFFIXES=['-A', '-B'],
        _FLUX_PROMPT_TEMPLATES={'person': '{subject} standing'},
        _DEFAULT_FLUX_PROMPT='{subject}',
        pipeline_state={},
        pipeline_id='pid-1',
        topic='Florence',
        visual_style='cinematic',
        out_dir='/tmp/does-not-exist',
        job={},
    )
    for key, val in over.items():
        setattr(ctx, key, val)
    return ctx


def _fs(**over):
    """A FluxLoopState stand-in: only the fields the helpers under test touch."""
    fs = types.SimpleNamespace(
        _last_prompt=None,
        _prev_focal_zone=None,
        _IDENTITY_TAGS={'person'},
        _subject_seed_registry={},
        _rnd_flux=_Rnd(11, 22, 33),
        _slot_review={},
        _shipped_flagged=[],
        _era_last_flags={},
        _ladder_stats={'repair_tried': 0, 'repair_ok': 0, 'era_repair_tried': 0, 'era_repair_ok': 0},
        _flux_images_dir='/tmp/does-not-exist',
        _TYPO_REPAIR_ENABLED=False,
        _VLM_TEXT_MODEL='claude-haiku',
        _slot_clock_total=60.0,
        _cn_pipe=None,
        _cns=None,
        _ipa=None,
        _ipa_ready=False,
        _flux_image_meta=[],
    )
    for key, val in over.items():
        setattr(fs, key, val)
    return fs


def _plain_prompt(**over):
    """A `_build_image_prompt` stand-in returning one fixed nine-tuple."""
    fields = {
        'prompt': 'a street in Florence',
        'subj': 'cosimo de medici',
        'tag': 'person',
        'seg_preview': 'segment',
        'shot_type': 'medium close-up',
        'emotion': 'calm',
        'seed_override': None,
        'cp_used': False,
        'subj_is_entity': True,
    }
    fields.update(over)

    def _build(*_a, **_kw):
        return tuple(fields.values())

    return _build


def _no_rewrites(monkeypatch):
    """Neutralise the period and render-safety passes so a test sees composition only."""
    monkeypatch.setattr(sp, '_period_noun_rewrite', lambda p, lock: (p, []))
    monkeypatch.setattr(sp, '_period_hair_backstop', lambda p, lock: (p, False))
    monkeypatch.setattr(sp, '_render_safety_rewrite', lambda p, rank: (p, []))
    monkeypatch.setattr(sp, '_STYLE_LORA_CONFIG', {'cinematic': {'prefix': '', 'suffix': ''}})


# ── classify_anatomy_shot / quality_tier ────────────────────────────────────


@pytest.mark.parametrize(
    'shot_type',
    ['medium close-up', 'tight portrait', 'a figure at a desk', 'waist-up of a person'],
)
def test_an_anatomy_word_makes_it_an_anatomy_shot(shot_type):
    assert sp.classify_anatomy_shot(shot_type) is True


@pytest.mark.parametrize(
    'shot_type',
    ['wide establishing shot of a person', 'aerial of a figure', 'landscape', 'a bowl of soup'],
)
def test_a_wide_word_vetoes_the_anatomy_class(shot_type):
    assert sp.classify_anatomy_shot(shot_type) is False


def test_qwen_has_one_tier_and_the_smoke_cap_only_cuts_its_steps():
    assert sp.quality_tier(True, False, False) == (20, 2.5, 'Qwen-Image-2512')
    assert sp.quality_tier(True, True, True) == (8, 2.5, 'Qwen-Image-2512')


def test_on_flux_only_anatomy_shots_pay_for_the_quality_tier():
    assert sp.quality_tier(False, True, False) == (20, 3.5, 'FLUX.1-schnell/quality')
    assert sp.quality_tier(False, True, True) == (4, 0.0, 'FLUX.1-schnell')
    assert sp.quality_tier(False, False, False) == (4, 0.0, 'FLUX.1-schnell')


def test_choose_quality_tier_writes_the_plan_and_logs_the_mode():
    ctx = _ctx()
    plan = sp.SlotPlan(idx=3, shot_type='tight portrait')
    sp.choose_quality_tier(ctx, plan)
    assert plan.is_anatomy_shot is True
    assert (plan.n_steps, plan.g_scale, plan.model_label) in (
        (20, 3.5, 'FLUX.1-schnell/quality'),
        (4, 0.0, 'FLUX.1-schnell'),  # under a smoke cap
    )
    assert any('Slot 3: anatomy mode' in msg for _stage, msg, _lvl in ctx._debug_lines)


# ── abort_before_cuda ───────────────────────────────────────────────────────


def test_a_set_stop_event_aborts_the_slot_before_the_cuda_call(monkeypatch):
    monkeypatch.setattr(gui_state, '_pipeline_stop_flag', False)
    ctx = _ctx(job={'stop_event': types.SimpleNamespace(is_set=lambda: True)})
    assert sp.abort_before_cuda(ctx, 7) is True
    assert ctx._debug_lines[-1][2] == 'WARN'


def test_no_stop_anywhere_lets_the_slot_render(monkeypatch):
    monkeypatch.setattr(gui_state, '_pipeline_stop_flag', False)
    ctx = _ctx(job={'stop_event': types.SimpleNamespace(is_set=lambda: False)})
    assert sp.abort_before_cuda(ctx, 7) is False
    assert ctx._debug_lines == []


def test_the_global_stop_flag_aborts_even_with_no_event(monkeypatch):
    monkeypatch.setattr(gui_state, '_pipeline_stop_flag', True)
    assert sp.abort_before_cuda(_ctx(job={}), 7) is True


# ── compose_prompt ──────────────────────────────────────────────────────────


def test_a_prompt_identical_to_the_last_slot_is_rebuilt_on_the_next_style(monkeypatch):
    _no_rewrites(monkeypatch)
    ctx = _ctx(_build_image_prompt=_plain_prompt(prompt='a street in Florence'))
    fs = _fs(_last_prompt='a street in Florence')
    plan = sp.compose_prompt(fs, ctx, 0)
    assert plan.prompt == 'cosimo de medici standing-B'
    assert fs._last_prompt == 'cosimo de medici standing-B'


def test_a_fresh_prompt_is_kept_and_becomes_the_dedup_reference(monkeypatch):
    _no_rewrites(monkeypatch)
    ctx = _ctx(_build_image_prompt=_plain_prompt())
    fs = _fs()
    plan = sp.compose_prompt(fs, ctx, 0)
    assert plan.prompt == 'a street in Florence'
    assert fs._last_prompt == 'a street in Florence'
    assert (plan.subj, plan.tag, plan.shot_type) == ('cosimo de medici', 'person', 'medium close-up')


def test_the_visual_style_wraps_the_prompt_in_its_prefix_and_suffix(monkeypatch):
    _no_rewrites(monkeypatch)
    monkeypatch.setattr(
        sp,
        '_STYLE_LORA_CONFIG',
        {'cinematic': {'prefix': 'cinematic photograph', 'suffix': 'shot on film'}},
    )
    ctx = _ctx(_build_image_prompt=_plain_prompt())
    plan = sp.compose_prompt(_fs(), ctx, 1)
    assert plan.prompt == 'cinematic photograph, a street in Florence, shot on film'


def test_qwen_keeps_one_register_and_drops_oil_painting_realism(monkeypatch):
    _no_rewrites(monkeypatch)
    ctx = _ctx(
        _sch_qwen_stills=True,
        _build_image_prompt=_plain_prompt(prompt='a photograph of a street, oil painting realism'),
    )
    plan = sp.compose_prompt(_fs(), ctx, 2)
    assert plan.prompt == 'a photograph of a street'
    assert any('oil painting realism' in msg for _stage, msg, _lvl in ctx._debug_lines)


def test_a_historical_slot_runs_both_backstops_then_anchors_the_era_in_front(monkeypatch):
    _no_rewrites(monkeypatch)
    order: list = []

    def _noun(prompt, _lock):
        order.append('noun')
        return f'{prompt} +noun', ['doublet']

    def _hair(prompt, _lock):
        order.append('hair')
        return f'{prompt} +hair', True

    def _safety(prompt, _rank):
        order.append('safety')
        return f'{prompt} +safe', []

    monkeypatch.setattr(sp, '_period_noun_rewrite', _noun)
    monkeypatch.setattr(sp, '_period_hair_backstop', _hair)
    monkeypatch.setattr(sp, '_render_safety_rewrite', _safety)
    ctx = _ctx(
        _era_lock={'is_historical': True, 'period_label': '14th-century Florence.'},
        _build_image_prompt=_plain_prompt(),
    )
    plan = sp.compose_prompt(_fs(), ctx, 0)
    assert order == ['noun', 'hair', 'safety']
    assert plan.prompt == '14th-century Florence, a street in Florence +noun +hair +safe'


def test_an_era_already_named_up_front_is_not_anchored_twice(monkeypatch):
    _no_rewrites(monkeypatch)
    ctx = _ctx(
        _era_lock={'is_historical': True, 'period_label': '14th-century Florence'},
        _build_image_prompt=_plain_prompt(prompt='14th-century Florence, a street'),
    )
    plan = sp.compose_prompt(_fs(), ctx, 0)
    assert plan.prompt == '14th-century Florence, a street'


# ── resolve_seed ────────────────────────────────────────────────────────────


def _person_plan(**over):
    """A plan for a two-word named person — the case that locks a seed."""
    fields = {
        'idx': 0,
        'prompt': 'cosimo de medici standing in a street',
        'subj': 'cosimo de medici',
        'tag': 'person',
        'subj_is_entity': True,
        'seed_override': None,
    }
    fields.update(over)
    return sp.SlotPlan(**fields)


def test_a_named_person_locks_a_seed_and_every_later_slot_reuses_it():
    fs = _fs(_rnd_flux=_Rnd(4242, 9999))
    ctx = _ctx()
    first = sp.resolve_seed(fs, ctx, _person_plan())
    second = sp.resolve_seed(fs, ctx, _person_plan(idx=5))
    assert first == second == 4242
    assert fs._subject_seed_registry == {'cosimo de medici': 4242}
    assert fs._rnd_flux.calls == 1


def test_a_murch_seed_override_is_what_gets_locked():
    fs = _fs(_rnd_flux=_Rnd(4242))
    sp.resolve_seed(fs, _ctx(), _person_plan(seed_override=777))
    assert fs._subject_seed_registry == {'cosimo de medici': 777}
    assert fs._rnd_flux.calls == 0


def test_an_environment_tag_always_gets_a_fresh_seed_and_locks_nothing():
    fs = _fs(_rnd_flux=_Rnd(11, 22))
    ctx = _ctx()
    plan = _person_plan(tag='environment')
    assert sp.resolve_seed(fs, ctx, plan) == 11
    assert sp.resolve_seed(fs, ctx, plan) == 22
    assert fs._subject_seed_registry == {}


def test_the_essay_title_fallback_subject_is_never_locked():
    fs = _fs(_rnd_flux=_Rnd(11))
    ctx = _ctx(_fallback_subject='The Black Death')
    plan = _person_plan(subj='the black death', prompt='the black death over a city')
    assert sp.resolve_seed(fs, ctx, plan) == 11
    assert fs._subject_seed_registry == {}
    assert any('not locked (title fallback)' in msg for _stage, msg, _lvl in ctx._debug_lines)


def test_a_single_word_subject_with_no_person_in_the_prompt_is_not_locked():
    fs = _fs(_rnd_flux=_Rnd(11))
    ctx = _ctx()
    plan = _person_plan(subj='plague', prompt='a deserted market square at dusk')
    assert sp.resolve_seed(fs, ctx, plan) == 11
    assert fs._subject_seed_registry == {}


# ── always_reroll_enabled / new_slot_state ──────────────────────────────────


@pytest.mark.parametrize('raw,expected', [('1', True), ('TRUE', True), ('yes', True), ('0', False), ('', False)])
def test_always_reroll_reads_the_flag_case_insensitively(raw, expected):
    assert sp.always_reroll_enabled({'ZYG_SCHOLARLY_ALWAYS_REROLL': raw}) is expected


def test_always_reroll_is_off_when_the_flag_is_absent():
    assert sp.always_reroll_enabled({}) is False


def test_new_slot_state_opens_an_unreviewed_record_and_carries_the_plan():
    fs = _fs()
    plan = sp.SlotPlan(
        idx=4,
        prompt='a street',
        subj='cosimo',
        gen_seed=8,
        is_anatomy_shot=True,
        n_steps=20,
        g_scale=3.5,
    )
    slot = sp.new_slot_state(fs, plan)
    assert fs._slot_review[4]['anatomy'] == 'unreviewed'
    assert fs._slot_review[4]['winner_attempt'] is None
    assert (slot.idx, slot._prompt, slot._gen_seed, slot._n_steps, slot._g_scale) == (4, 'a street', 8, 20, 3.5)
    assert slot._is_anatomy_shot is True
    assert slot._qa_attempts == []
    assert slot._best_path is None
    assert slot._active_pipe is UNSET


# ── the shipping half ───────────────────────────────────────────────────────


def test_the_winner_record_is_found_by_path_and_its_issues_are_copied():
    best = {'path': '/img/b.jpg', 'issues': ['typography: sign']}
    rec, issues = ship._winner_record([{'path': '/img/a.jpg'}, best], '/img/b.jpg')
    assert rec is best
    assert issues == ['typography: sign']
    issues.clear()
    assert best['issues'] == ['typography: sign']


def test_an_unknown_winner_path_yields_no_record_and_no_issues():
    assert ship._winner_record([{'path': '/img/a.jpg'}], '/img/zz.jpg') == (None, [])


@pytest.mark.parametrize(
    'issues,kind',
    [
        (['typography: gibberish sign'], 'typography'),
        (['anachronism: wristwatch'], 'anachronism'),
        (['gore: exposed bone'], 'gore'),
        (['subject: missing'], 'subject'),
        (['anatomy: six fingers'], 'anatomy'),
        (['something nobody named'], 'defect'),
        (['anatomy: six fingers', 'typography: sign'], 'typography'),
        (['gore: bone', 'anachronism: bulb'], 'anachronism'),
    ],
)
def test_the_worst_flag_names_the_defect_a_flagged_shipment_reports(issues, kind):
    assert ship.defect_kind(issues) == kind


def test_a_clean_winner_is_summarised_without_a_flagged_warning():
    fs = _fs()
    ctx = _ctx()
    plan = sp.SlotPlan(idx=2, is_anatomy_shot=True)
    sp.new_slot_state(fs, plan)
    fs._slot_review[2]['anatomy_a1'] = 'moondream'
    attempts = [{'path': '/img/w.jpg', 'attempt': 1, 'issues': []}]
    ship.summarize_slot_review(fs, ctx, plan, '/img/w.jpg', 0.91267, attempts)
    review = fs._slot_review[2]
    assert review['winner_attempt'] == 1
    assert review['score'] == 0.913
    assert review['anatomy'] == 'moondream'
    assert review['typography'] == 'unreviewed'
    assert review['flagged'] == []
    assert review['anatomy_shot'] is True
    assert fs._shipped_flagged == []
    assert ctx._log_lines == []


def test_a_still_flagged_winner_is_warned_about_and_recorded():
    fs = _fs()
    ctx = _ctx()
    plan = sp.SlotPlan(idx=2, is_anatomy_shot=False)
    sp.new_slot_state(fs, plan)
    attempts = [
        {'path': '/img/a.jpg', 'attempt': 1, 'issues': []},
        {'path': '/img/w.jpg', 'attempt': 2, 'issues': ['typography: a sign reads PAILAT']},
    ]
    ship.summarize_slot_review(fs, ctx, plan, '/img/w.jpg', 0.42, attempts)
    assert fs._slot_review[2]['flagged'] == ['typography: a sign reads PAILAT']
    assert fs._shipped_flagged == [
        {
            'slot': 2,
            'attempts': 2,
            'score': 0.42,
            'kind': 'typography',
            'issues': ['typography: a sign reads PAILAT'],
        }
    ]
    assert ctx._log_lines[0][0] == 'WARNING'
    assert 'SHIPPED FLAGGED' in ctx._log_lines[0][2]


def test_a_missing_review_record_does_not_stop_the_image_shipping():
    fs = _fs()
    ctx = _ctx()
    plan = sp.SlotPlan(idx=9)
    attempts = [{'path': '/img/w.jpg', 'attempt': 1, 'issues': ['gore: bone']}]
    ship.summarize_slot_review(fs, ctx, plan, '/img/w.jpg', 0.5, attempts)
    assert fs._shipped_flagged[0]['kind'] == 'gore'


def test_the_winner_becomes_flux_nnn_and_the_losing_attempts_are_deleted(tmp_path):
    winner = tmp_path / 'flux_003_r2.jpg'
    loser = tmp_path / 'flux_003_r1.jpg'
    winner.write_bytes(b'win')
    loser.write_bytes(b'lose')
    fs = _fs(_flux_images_dir=str(tmp_path))
    out = ship.canonicalize_winner(
        fs,
        _ctx(),
        sp.SlotPlan(idx=3),
        str(winner),
        [{'path': str(loser)}, {'path': str(winner)}],
    )
    assert out == str(tmp_path / 'flux_003.jpg')
    assert (tmp_path / 'flux_003.jpg').read_bytes() == b'win'
    assert not loser.exists()
    assert not winner.exists()


def test_a_winner_already_canonical_is_left_alone(tmp_path):
    canon = tmp_path / 'flux_007.jpg'
    canon.write_bytes(b'win')
    fs = _fs(_flux_images_dir=str(tmp_path))
    out = ship.canonicalize_winner(fs, _ctx(), sp.SlotPlan(idx=7), str(canon), [{'path': str(canon)}])
    assert out == str(canon)
    assert canon.read_bytes() == b'win'


def test_a_rename_that_cannot_happen_keeps_the_original_path(tmp_path):
    missing = tmp_path / 'gone.jpg'
    fs = _fs(_flux_images_dir=str(tmp_path))
    ctx = _ctx()
    out = ship.canonicalize_winner(fs, ctx, sp.SlotPlan(idx=1), str(missing), [])
    assert out == str(missing)
    assert any('canonical rename failed' in msg for _stage, msg, _lvl in ctx._debug_lines)


def test_typography_repair_is_skipped_when_the_gate_is_off():
    fs = _fs(_TYPO_REPAIR_ENABLED=False)
    attempts = [{'path': '/img/w.jpg', 'issues': ['typography: sign']}]
    assert ship.repair_typography(fs, _ctx(), sp.SlotPlan(idx=1), '/img/w.jpg', attempts, None) is False
    assert fs._ladder_stats['repair_tried'] == 0
    assert attempts[0]['issues'] == ['typography: sign']


def test_typography_repair_is_skipped_when_nothing_is_flagged():
    fs = _fs(_TYPO_REPAIR_ENABLED=True)
    attempts = [{'path': '/img/w.jpg', 'issues': ['anatomy: hands']}]
    assert ship.repair_typography(fs, _ctx(), sp.SlotPlan(idx=1), '/img/w.jpg', attempts, None) is False
    assert fs._ladder_stats['repair_tried'] == 0


def test_era_region_repair_needs_a_small_boxed_flag_to_run(monkeypatch):
    monkeypatch.setenv('ZYG_SCHOLARLY_ERA_REPAIR', '1')
    fs = _fs(_era_last_flags={1: [{'id': 'wristwatch', 'small': False, 'bbox': None}]})
    attempts = [{'path': '/img/w.jpg', 'issues': ['anachronism: wristwatch']}]
    ship.repair_era_regions(fs, _ctx(), sp.SlotPlan(idx=1), '/img/w.jpg', attempts)
    assert fs._ladder_stats['era_repair_tried'] == 0
    assert attempts[0]['issues'] == ['anachronism: wristwatch']
