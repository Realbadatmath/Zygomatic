# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The derivations `batch_generate_flux_prompts` hands to the Sonnet batch call.

`batch_generate_flux_prompts` was a 403-line def of which 360 lines were one straight run
of prompt-text assembly, so none of it had ever been called in isolation: the only way to
ask "does a historical episode get a PERIOD LOCK?" was to run a stage and spend an API
call. The 2026-10-09 split gave each derivation its own function in
`stages_37_54_prompt_batch_build`, and these tests pin the branch each one takes and the
wording that branch is load-bearing for — every documented misfire in that file
("Revolutions of 1848", the Qwen/oil-painting clash, bare nouns, "blood on sand") is a
case below. No network, no GPU, no services: every helper takes plain values.
"""

from __future__ import annotations

from zyg_workflows.scholarly import stages_37_54_prompt_batch_build as B

ERA_MODERN = {'is_historical': False, 'period_label': '', 'anchors': [], 'is_combat': False}
ERA_ROME = {
    'is_historical': True,
    'period_label': 'the Roman Republic, 1st century BC',
    'anchors': ['linen tunics', 'oil lamps'],
    'is_combat': True,
}
STANDARD = {'enabled': False, 'level': 'standard', 'rank': 0, 'hook_rank': 0}
HIGH = {'enabled': True, 'level': 'high', 'rank': 1, 'hook_rank': 1}
EXTREME = {'enabled': True, 'level': 'extreme', 'rank': 2, 'hook_rank': 2}


def logger():
    """A `_log` stand-in plus the list it appends (level, stage, message) tuples to."""
    lines = []
    return (lambda level, stage, msg: lines.append((level, stage, msg))), lines


# ── is_battle_topic ───────────────────────────────────────────────────────────


def test_the_classifier_verdict_beats_the_keyword_scan():
    """'Revolutions of 1848' matches 'revolution' in the keyword set, and that misfire is
    exactly what the era-lock classifier was introduced to overrule."""
    log, lines = logger()
    era = dict(ERA_ROME, is_combat=False)
    assert (
        B.is_battle_topic(
            topic='Revolutions of 1848',
            directive='parliamentary reform and press censorship',
            pipeline_state={'essay_title': 'Revolutions of 1848'},
            era_lock=era,
            log=log,
        )
        is False
    )
    assert 'revolution' in B.BATTLE_KEYWORDS
    # the disagreement is said out loud, and only the disagreement
    assert len(lines) == 1
    assert lines[0][:2] == ('INFO', 'Stage 3.5')
    assert 'classifier says False' in lines[0][2]
    assert 'keyword scan would have said True' in lines[0][2]


def test_no_classifier_verdict_falls_back_to_the_keyword_scan_and_says_so():
    """A missing `is_combat` (no API key, malformed reply) is the only case the crude
    keyword signal is still used for, and it is logged as a fallback."""
    log, lines = logger()
    era = dict(ERA_ROME, is_combat=None)
    assert B.is_battle_topic(
        topic='general', directive='', pipeline_state={'essay_title': 'a gladiator school'}, era_lock=era, log=log
    )
    assert len(lines) == 1
    assert 'no classifier verdict — keyword fallback says True' in lines[0][2]


def test_the_scan_reads_the_essay_title_not_only_the_topic():
    """`topic` is 'general' for every free-text run, so the directive and the essay title
    are part of the text the fallback scans — the Khalsa-army bug."""
    log, _ = logger()
    era = dict(ERA_ROME, is_combat=None)
    assert B.is_battle_topic(
        topic='general',
        directive='the Anglo-Sikh wars',
        pipeline_state={'essay_title': ''},
        era_lock=era,
        log=log,
    )
    assert not B.is_battle_topic(
        topic='general', directive='beekeeping', pipeline_state={'essay_title': 'honey'}, era_lock=era, log=log
    )


def test_an_agreeing_classifier_logs_nothing():
    """Silence is the normal case: a line per prompt batch that says nothing is noise."""
    log, lines = logger()
    assert B.is_battle_topic(
        topic='a roman siege',
        directive='',
        pipeline_state={'essay_title': ''},
        era_lock=ERA_ROME,
        log=log,
    )
    assert lines == []


# ── build_style_ctx ───────────────────────────────────────────────────────────


def test_the_battle_register_wins_over_every_other_branch():
    s = B.build_style_ctx(
        is_battle=True,
        subject_type='person',
        is_modern_topic=True,
        family_early='flux',
        visual_style='cinematic',
        era_lock=ERA_MODERN,
        intensity=STANDARD,
    )
    assert s == 'historical cinematic, photorealistic gritty realism, battle-worn period-accurate'


def test_qwen_never_gets_oil_painting_realism():
    """P-12: every render prompt is prefixed with the visual style ('cinematic
    photograph'), and Qwen obeys both — so 'oil painting realism' fought 'photograph'
    inside the same frame. On a photographic prefix the brief stays photographic."""
    kw = dict(
        is_battle=False,
        subject_type='event',
        is_modern_topic=False,
        visual_style='cinematic',
        era_lock=ERA_MODERN,
        intensity=STANDARD,
    )
    assert B.build_style_ctx(family_early='flux', **kw) == (
        'historical cinematic, oil painting realism, period-accurate'
    )
    assert B.build_style_ctx(family_early='qwen', **kw) == (
        'historical cinematic, photorealistic period reconstruction, period-accurate'
    )


def test_the_period_and_the_intensity_dial_are_appended_in_that_order():
    """`_style_ctx` is handed to the writer twice, so it is where the period is stated and
    where the pitch of all N prompts is raised at once."""
    s = B.build_style_ctx(
        is_battle=False,
        subject_type='person',
        is_modern_topic=False,
        family_early='flux',
        visual_style='cinematic',
        era_lock=ERA_ROME,
        intensity=EXTREME,
    )
    assert s.startswith('intimate biographical portrait')
    assert ', set entirely in the Roman Republic, 1st century BC,' in s
    assert s.endswith('maximally arresting, unflinching — the strongest single image in the film')


def test_a_standard_intensity_appends_nothing():
    s = B.build_style_ctx(
        is_battle=False,
        subject_type='gold',
        is_modern_topic=False,
        family_early='flux',
        visual_style='cinematic',
        era_lock=ERA_MODERN,
        intensity=STANDARD,
    )
    assert s == 'noir cinematic, high-contrast shadows, gritty realism, crime documentary aesthetic'


# ── build_quality_tag ─────────────────────────────────────────────────────────


def test_8k_is_only_for_modern_topics():
    """'8k' fights historical and portrait aesthetics, which is why the tag is
    style-aware at all; the modern branch wins over the subject type."""
    assert '8k' in B.build_quality_tag(is_modern_topic=True, subject_type='person')
    assert '8k' not in B.build_quality_tag(is_modern_topic=False, subject_type='person')
    assert B.build_quality_tag(is_modern_topic=False, subject_type='person').startswith('photorealistic portrait')
    assert B.build_quality_tag(is_modern_topic=False, subject_type='event').startswith('cinematic grain')


# ── build_intensity_directive ─────────────────────────────────────────────────


def test_the_dial_off_means_no_directive_at_all():
    assert B.build_intensity_directive(STANDARD) == ''


def test_the_directive_grows_by_rank_and_by_hook_rank():
    """Rank 2 adds the "push all the way" paragraph; hook rank 2 adds SLOT 1 IS THE HOOK.
    Each is appended, never substituted."""
    high = B.build_intensity_directive(HIGH)
    extreme = B.build_intensity_directive(EXTREME)
    hook_only = B.build_intensity_directive({'enabled': True, 'level': 'high', 'rank': 1, 'hook_rank': 2})
    assert 'Push all the way' not in high
    assert 'SLOT 1 IS THE HOOK' not in high
    assert extreme.startswith(high)
    assert 'Push all the way' in extreme
    assert 'SLOT 1 IS THE HOOK' in extreme
    assert hook_only.startswith(high)
    assert 'Push all the way' not in hook_only
    assert 'SLOT 1 IS THE HOOK' in hook_only


def test_the_not_shock_value_sentence_is_always_there():
    """Load-bearing, not a disclaimer: a model told only to be intense reaches for gore as
    the cheapest reading of the word."""
    for intensity in (HIGH, EXTREME):
        assert 'NOT shock value' in B.build_intensity_directive(intensity)


def test_the_intensity_directive_never_borrows_the_battle_wording():
    """Combat-specific nouns stay behind the classifier — that is the whole reason this
    directive exists separately from `BATTLE_DIRECTIVE`."""
    text = B.build_intensity_directive(EXTREME)
    for noun in ('blood on sand', 'bloodied armor', 'gladiator', 'clashing weapons'):
        assert noun not in text
    assert 'blood on sand' in B.BATTLE_DIRECTIVE


# ── build_subject_directive ───────────────────────────────────────────────────


def test_a_combat_episode_gets_no_subject_directive():
    """A combat episode gets `BATTLE_DIRECTIVE` instead, and never both."""
    for subject in ('person', 'gold'):
        assert B.build_subject_directive(subject_type=subject, is_battle=True) == ''


def test_the_person_and_gold_registers_are_distinct():
    person = B.build_subject_directive(subject_type='person', is_battle=False)
    gold = B.build_subject_directive(subject_type='gold', is_battle=False)
    assert 'biographical documentary about a specific individual' in person
    assert 'noir' in gold
    assert B.build_subject_directive(subject_type='event', is_battle=False) == ''


# ── build_period_lock ─────────────────────────────────────────────────────────


def test_a_modern_episode_gets_no_period_lock():
    assert B.build_period_lock(era_lock=ERA_MODERN, n=45) == ('', '')


def test_the_lock_names_the_period_and_the_slot_count():
    """The lock says ALL N slots including the first and the last, because the misfire it
    exists for was a contemporary street scene four slots in."""
    section, rule = B.build_period_lock(era_lock=ERA_ROME, n=45)
    assert 'PERIOD LOCK — every image in this episode depicts the Roman Republic, 1st century BC.' in section
    assert 'ALL 45 slots including the first and the last' in section
    assert 'These are RHETORICAL' in section
    assert rule.lstrip().startswith('- PERIOD LOCK:')
    assert '- NO BARE NOUNS:' in rule


def test_the_anchors_are_listed_only_when_there_are_any():
    section, _ = B.build_period_lock(era_lock=ERA_ROME, n=10)
    assert 'Period-accurate detail for this exact time and place:' in section
    assert '    - linen tunics\n' in section
    bare, _ = B.build_period_lock(era_lock=dict(ERA_ROME, anchors=[]), n=10)
    assert 'Period-accurate detail' not in bare


def test_the_bare_noun_rule_carries_era_bucketed_examples():
    """A Roman episode must be shown galleys and sandals, not cogs and turnshoes, so the
    examples come from the era bucket rather than from one hardcoded list."""
    _, roman = B.build_period_lock(era_lock=ERA_ROME, n=10)
    assert 'ON THE NOUN ITSELF — e.g. ' in roman
    unknown_era = {'is_historical': True, 'period_label': 'somewhen', 'anchors': ['a thing']}
    _, other = B.build_period_lock(era_lock=unknown_era, n=10)
    assert 'ON THE NOUN ITSELF' in other
    assert roman != other


# ── build_system_prompt ───────────────────────────────────────────────────────


def test_the_system_prompt_names_the_renderer_that_will_paint_it():
    """P-12: this said 'FLUX' on every Qwen run, and the two need opposite handling of
    text and of style stacking."""
    kw = dict(intensity_directive='', battle_directive='', subject_directive='', era_lock=ERA_MODERN)
    assert 'Qwen-Image-2512' in B.build_system_prompt(family_early='qwen', **kw)
    assert 'FLUX.1-schnell' in B.build_system_prompt(family_early='flux', **kw)


def test_the_directives_are_concatenated_in_a_fixed_order():
    out = B.build_system_prompt(
        family_early='flux',
        intensity_directive=' INT.',
        battle_directive=' BAT.',
        subject_directive=' SUB.',
        era_lock=ERA_ROME,
    )
    assert out.index(' INT.') < out.index(' BAT.') < out.index(' SUB.')
    assert out.endswith('. You never depict the present day, whatever the narration says.')
    assert 'Every image you write is set in the Roman Republic, 1st century BC' in out


def test_a_modern_episode_gets_no_period_sentence():
    out = B.build_system_prompt(
        family_early='flux',
        intensity_directive='',
        battle_directive='',
        subject_directive='',
        era_lock=ERA_MODERN,
    )
    assert out.endswith('Every prompt is internally consistent, camera-ready, and visually distinct.')


# ── the constants the orchestrator gates ──────────────────────────────────────


def test_the_skin_rule_describes_illness_on_intact_skin():
    """'bubo... grotesque swelling' rendered an eviscerated chest, so below 'extreme' the
    writer is told to describe illness as intact skin. `rank >= 2` drops the rule."""
    assert 'NOT THROUGH IT' in B.SKIN_RULE
    assert 'Never write' in B.SKIN_RULE
    assert 'eviscerated' in B.SKIN_RULE


def test_the_hands_rule_keeps_hands_out_of_the_foreground():
    """Hand QC flagged 0/40 on the Black Death run and no VLM counts fingers."""
    assert 'never make a hand the subject' in B.HANDS_RULE
    assert B.HANDS_RULE.endswith('\n')
