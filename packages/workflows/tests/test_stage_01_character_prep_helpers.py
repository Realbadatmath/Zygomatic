# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the Stage 1 character-prep step helpers.

Only the pure, CPU-only seams of ``stage_01_character_prep_steps`` are covered:
the voice choices, the public ``extra_prompt`` sanitiser seam, the
bible-beats-client params reconciliation and the generated-preview blacklist.
The LoRA wait, the bible loader, the manifest read and the reference picker all
touch the trainer, the disk or a sibling service and are left to the pipeline's
own integration coverage."""

import types

import pytest
from zyg_workflows.storyteller import stage_01_character_prep_steps as steps


def _ctx(**extra):
    """A stand-in pipeline context that records every log line."""
    logs: list[tuple[str, str]] = []
    ctx = types.SimpleNamespace(
        pipeline_state={},
        job={},
        char_id='abc123',
        model_family='flux',
        narrator_voice='',
        character_voice='',
        voice_style='narrator',
        logs=logs,
    )
    ctx._log = lambda lvl, _stage, msg: logs.append((lvl, msg))
    for k, v in extra.items():
        setattr(ctx, k, v)
    return ctx


# ── legacy_narrator_voice ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('gender', 'expected'),
    [
        ('female', 'en-US-JennyNeural'),
        ('f', 'en-US-JennyNeural'),
        ('young female', 'en-US-JennyNeural'),
        ('male', 'en-US-BrianNeural'),
        ('m', 'en-US-BrianNeural'),
        ('', 'en-US-BrianNeural'),
        ('nonbinary', 'en-US-BrianNeural'),
    ],
)
def test_legacy_narrator_voice_is_jenny_for_female_and_brian_otherwise(gender, expected):
    assert steps.legacy_narrator_voice(gender) == expected


# ── is_generated_preview ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    'name',
    ['preview_flux_front.png', 'PREVIEW_sdxl.png', 'style_preview_01.jpg', 'style_previewB.png'],
)
def test_is_generated_preview_rejects_renders(name):
    assert steps.is_generated_preview(f'/data/chars/abc123/{name}') is True


@pytest.mark.parametrize('name', ['still_004.png', 'face_crop.png', 'my_preview_shot.png', 'contact_sheet.png'])
def test_is_generated_preview_accepts_training_stills(name):
    assert steps.is_generated_preview(f'/data/chars/abc123/{name}') is False


def test_is_generated_preview_only_looks_at_the_basename():
    assert steps.is_generated_preview('/data/preview_runs/still_001.png') is False


# ── record_clean_extra_prompt ────────────────────────────────────────────────


def test_record_clean_extra_prompt_keeps_a_harmless_phrase():
    ctx = _ctx()
    steps.record_clean_extra_prompt(ctx, {'extra_prompt': ' holding a lantern '})
    assert ctx.pipeline_state['_st_extra_prompt_clean'] == 'holding a lantern'
    assert [lvl for lvl, _ in ctx.logs] == ['INFO']
    assert "accepted='holding a lantern'" in ctx.logs[0][1]
    assert "raw='holding a lantern'" in ctx.logs[0][1]


def test_record_clean_extra_prompt_drops_everything_for_a_minor():
    ctx = _ctx()
    steps.record_clean_extra_prompt(ctx, {'extra_prompt': 'holding a lantern', 'age': 12})
    assert ctx.pipeline_state['_st_extra_prompt_clean'] == ''
    assert ctx.logs[0][0] == 'WARNING'
    assert 'minor' in ctx.logs[0][1]


def test_record_clean_extra_prompt_is_silent_when_the_client_sent_nothing():
    ctx = _ctx()
    steps.record_clean_extra_prompt(ctx, {})
    assert ctx.pipeline_state['_st_extra_prompt_clean'] == ''
    assert ctx.logs == []


def test_record_clean_extra_prompt_tolerates_a_missing_params_dict():
    ctx = _ctx()
    steps.record_clean_extra_prompt(ctx, None)
    assert ctx.pipeline_state['_st_extra_prompt_clean'] == ''


def test_record_clean_extra_prompt_off_uses_the_client_string_verbatim(monkeypatch):
    monkeypatch.setenv('ZYG_ST_SANITIZE_EXTRA_PROMPT', '0')
    ctx = _ctx()
    steps.record_clean_extra_prompt(ctx, {'extra_prompt': '  nude, nsfw  ', 'age': 12})
    assert ctx.pipeline_state['_st_extra_prompt_clean'] == 'nude, nsfw'
    assert ctx.logs == [('WARNING', 'ZYG_ST_SANITIZE_EXTRA_PROMPT=0 — client extra_prompt used VERBATIM')]


# ── reconcile_character_params ───────────────────────────────────────────────


def test_reconcile_character_params_without_a_bible_leaves_the_client_values():
    ctx = _ctx()
    client = {'gender': 'female', 'age': 25}
    assert steps.reconcile_character_params(ctx, client) is client
    assert ctx.logs == []
    assert 'character_params_resolved' not in ctx.job


def test_reconcile_character_params_lets_the_bible_win_and_names_the_conflicts(monkeypatch):
    ctx = _ctx()
    ctx.pipeline_state['character_bible'] = {'identity': {'gender': 'male', 'age': 12}}
    monkeypatch.setattr(
        steps,
        '_st_reconcile_params_with_bible',
        lambda params, bible: ({'gender': 'male', 'age': 12}, ['gender: female → male']),
    )
    out = steps.reconcile_character_params(ctx, {'gender': 'female', 'age': 25})
    assert out == {'gender': 'male', 'age': 12}
    assert ctx.job['character_params_resolved'] == {'gender': 'male', 'age': 12}
    assert ctx.job['character_params_resolved'] is not out
    assert ctx.logs[0][0] == 'WARNING'
    assert 'OVERRIDDEN' in ctx.logs[0][1]
    assert 'gender: female → male' in ctx.logs[0][1]


def test_reconcile_character_params_says_so_when_client_and_bible_agree(monkeypatch):
    ctx = _ctx()
    ctx.pipeline_state['character_bible'] = {'identity': {'gender': 'male'}}
    monkeypatch.setattr(
        steps,
        '_st_reconcile_params_with_bible',
        lambda params, bible: ({'gender': 'male'}, []),
    )
    steps.reconcile_character_params(ctx, {'gender': 'male'})
    assert ctx.logs == [
        ('INFO', 'character_params reconciled with the character bible — no client/server disagreement')
    ]


def test_reconcile_character_params_keeps_the_client_values_when_reconciling_raises(monkeypatch):
    ctx = _ctx()
    ctx.pipeline_state['character_bible'] = {'identity': {}}

    def _boom(params, bible):
        raise ValueError('bible is malformed')

    monkeypatch.setattr(steps, '_st_reconcile_params_with_bible', _boom)
    client = {'gender': 'female'}
    assert steps.reconcile_character_params(ctx, client) is client
    assert ctx.logs[0][0] == 'WARNING'
    assert 'reconciliation failed' in ctx.logs[0][1]
    assert 'client-controlled' in ctx.logs[0][1]
    assert 'character_params_resolved' not in ctx.job


def test_reconcile_character_params_bible_wins_off_is_loud(monkeypatch):
    monkeypatch.setenv('ZYG_ST_BIBLE_WINS', '0')
    ctx = _ctx()
    ctx.pipeline_state['character_bible'] = {'identity': {'gender': 'male'}}
    client = {'gender': 'female'}
    assert steps.reconcile_character_params(ctx, client) is client
    assert ctx.logs[0][0] == 'WARNING'
    assert 'ZYG_ST_BIBLE_WINS=0' in ctx.logs[0][1]
    assert 'NOT server-validated' in ctx.logs[0][1]


# ── pick_narrator_voice ──────────────────────────────────────────────────────


def test_pick_narrator_voice_lets_the_user_choice_win(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(steps, '_st_pick_voice', lambda *a, **k: pytest.fail('catalog must not be consulted'))
    assert steps.pick_narrator_voice(ctx, 'female', 'en-GB-SoniaNeural', True) == 'en-GB-SoniaNeural'
    assert ctx.logs == [('INFO', 'Using user-selected narrator voice: en-GB-SoniaNeural')]


def test_pick_narrator_voice_takes_the_catalog_hit(monkeypatch):
    ctx = _ctx()
    seen = {}

    def _pick(gender, age, *, kind, prefer=()):
        seen.update(gender=gender, age=age, kind=kind, prefer=prefer)
        return 'en-US-AriaNeural', 'narrator-eligible, gender match'

    monkeypatch.setattr(steps, '_st_pick_voice', _pick)
    assert steps.pick_narrator_voice(ctx, 'female', '', True) == 'en-US-AriaNeural'
    assert seen == {
        'gender': 'female',
        'age': None,
        'kind': 'narrator',
        'prefer': ('en-US-JennyNeural', 'en-US-BrianNeural'),
    }
    assert ctx.logs[0][0] == 'INFO'
    assert 'Auto-selected narrator voice: en-US-AriaNeural' in ctx.logs[0][1]
    assert 'bible gender=female' in ctx.logs[0][1]


def test_pick_narrator_voice_falls_back_to_the_legacy_pair_on_a_catalog_miss(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(steps, '_st_pick_voice', lambda *a, **k: (None, 'no narrator-eligible voice'))
    assert steps.pick_narrator_voice(ctx, 'female', '', True) == 'en-US-JennyNeural'
    assert ctx.logs[0][0] == 'WARNING'
    assert 'catalog lookup failed (no narrator-eligible voice)' in ctx.logs[0][1]
    assert 'en-US-JennyNeural' in ctx.logs[0][1]


def test_pick_narrator_voice_from_bible_off_uses_the_legacy_pair(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(steps, '_st_pick_voice', lambda *a, **k: pytest.fail('catalog must not be consulted'))
    assert steps.pick_narrator_voice(ctx, '', '', False) == 'en-US-BrianNeural'
    assert ctx.logs[0][0] == 'INFO'
    assert 'gender: unspecified' in ctx.logs[0][1]
    assert 'ZYG_ST_VOICE_FROM_BIBLE=0' in ctx.logs[0][1]


# ── pick_character_voice ─────────────────────────────────────────────────────


def test_pick_character_voice_matches_gender_and_age(monkeypatch):
    ctx = _ctx()
    seen = {}

    def _pick(gender, age, *, kind, prefer=()):
        seen.update(gender=gender, age=age, kind=kind)
        return 'en-US-AnaNeural', 'child, gender match'

    monkeypatch.setattr(steps, '_st_pick_voice', _pick)
    got = steps.pick_character_voice(ctx, 'male', 12, 'en-US-BrianNeural', '', 'character', True)
    assert got == 'en-US-AnaNeural'
    assert seen == {'gender': 'male', 'age': 12, 'kind': 'character'}
    assert ctx.logs[0][0] == 'INFO'
    assert 'Auto-selected CHARACTER voice: en-US-AnaNeural' in ctx.logs[0][1]
    assert 'age=12' in ctx.logs[0][1]


def test_pick_character_voice_reports_an_unknown_age(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(steps, '_st_pick_voice', lambda *a, **k: ('en-US-AnaNeural', 'why'))
    steps.pick_character_voice(ctx, 'male', None, 'en-US-BrianNeural', '', 'character', True)
    assert 'age=unknown' in ctx.logs[0][1]


def test_pick_character_voice_keeps_the_narrator_on_a_catalog_miss(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(steps, '_st_pick_voice', lambda *a, **k: (None, 'no child male voice'))
    got = steps.pick_character_voice(ctx, 'male', 12, 'en-US-BrianNeural', '', 'character', True)
    assert got == ''
    assert ctx.logs[0][0] == 'WARNING'
    assert 'no child male voice' in ctx.logs[0][1]
    assert 'falls back to en-US-BrianNeural' in ctx.logs[0][1]


@pytest.mark.parametrize(
    ('character_voice', 'voice_style', 'from_bible'),
    [('', 'narrator', True), ('en-US-AnaNeural', 'character', True), ('', 'character', False)],
)
def test_pick_character_voice_leaves_the_decision_alone(monkeypatch, character_voice, voice_style, from_bible):
    ctx = _ctx()
    monkeypatch.setattr(steps, '_st_pick_voice', lambda *a, **k: pytest.fail('catalog must not be consulted'))
    got = steps.pick_character_voice(ctx, 'male', 12, 'en-US-BrianNeural', character_voice, voice_style, from_bible)
    assert got == character_voice
    assert ctx.logs == []


# ── select_voices ────────────────────────────────────────────────────────────


def test_select_voices_reads_gender_off_the_reconciled_params(monkeypatch):
    ctx = _ctx()
    seen = []
    monkeypatch.setattr(
        steps,
        '_st_pick_voice',
        lambda gender, age, **k: (seen.append((gender, age, k['kind'])), ('en-US-AriaNeural', 'why'))[1],
    )
    narrator, character, effective = steps.select_voices(ctx, {'gender': ' FEMALE ', 'age': 25})
    assert narrator == 'en-US-AriaNeural'
    assert character == ''
    assert effective == 'en-US-AriaNeural'
    assert seen == [('female', None, 'narrator')]


def test_select_voices_lets_the_character_voice_override_tts_in_character_mode(monkeypatch):
    ctx = _ctx(voice_style='character')
    monkeypatch.setattr(
        steps,
        '_st_pick_voice',
        lambda gender, age, **k: (
            ('en-US-AnaNeural', 'child') if k['kind'] == 'character' else ('en-US-BrianNeural', 'adult')
        ),
    )
    narrator, character, effective = steps.select_voices(ctx, {'gender': 'male', 'age': 12})
    assert narrator == 'en-US-BrianNeural'
    assert character == 'en-US-AnaNeural'
    assert effective == 'en-US-AnaNeural'
    assert ('INFO', 'Character voice mode — using character voice: en-US-AnaNeural') in ctx.logs


def test_select_voices_falls_back_to_the_narrator_when_character_mode_finds_no_voice(monkeypatch):
    ctx = _ctx(voice_style='character')
    monkeypatch.setattr(
        steps,
        '_st_pick_voice',
        lambda gender, age, **k: ('en-US-BrianNeural', 'adult') if k['kind'] == 'narrator' else (None, 'none'),
    )
    narrator, character, effective = steps.select_voices(ctx, {'gender': 'male', 'age': 12})
    assert (narrator, character, effective) == ('en-US-BrianNeural', '', 'en-US-BrianNeural')
    assert not any('using character voice' in m for _, m in ctx.logs)


def test_select_voices_tolerates_a_params_dict_without_a_gender(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(steps, '_st_pick_voice', lambda gender, age, **k: (None, f'gender={gender!r}'))
    narrator, _character, effective = steps.select_voices(ctx, {})
    assert narrator == 'en-US-BrianNeural'
    assert effective == 'en-US-BrianNeural'
    assert "gender=''" in ctx.logs[0][1]
