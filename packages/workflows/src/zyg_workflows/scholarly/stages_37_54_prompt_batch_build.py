# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The derivations `batch_generate_flux_prompts` hands to the Sonnet batch call.

`batch_generate_flux_prompts` was 403 lines, of which 360 were one straight run of
prompt-text derivation: the combat verdict, the style register, the quality tag, three
directives, the period lock, two renderer rules and the system prompt. None of it calls
anything, nothing is ever rebound and the only side effect in the whole stretch is the two
`_log` lines the combat verdict emits. So each piece is a function here, taking plain
values and returning a string, and the orchestrator is the sequence of calls.

That makes every piece unit-testable without a pipeline, a context object or an API key,
which is the point: the exact wording of these strings is the stage's entire behaviour and
until now nothing exercised it. Nothing takes `ctx` — the orchestrator unpacks it once, as
it always did — and the derived values stay **keyword-only** on the way in, because most
of them are strings and a positional list of strings is a silent bug waiting for an edit.

Statement order, every log line and every character of prompt text is the monolith's.
"""

from zyg_workflows.pipeline_config import _STYLE_LORA_CONFIG
from zyg_workflows.pipeline_scholarly import _INTENSITY_STYLE_CTX

BATTLE_KEYWORDS = {
    'gladiator',
    'gladiatorial',
    'gladius',
    'spartacus',
    'colosseum',
    'war',
    'warfare',
    'battle',
    'combat',
    'warrior',
    'military',
    'siege',
    'army',
    'soldier',
    'knight',
    'viking',
    'samurai',
    'spartan',
    'sparta',
    'crusade',
    'crusader',
    'roman',
    'legionnaire',
    'centurion',
    'trojan',
    'mongol',
    'conquest',
    'invasion',
    'assassin',
    'mercenary',
    'pirate',
    'barbarian',
    'warlord',
    'revolution',
    'uprising',
    'rebellion',
    'berserker',
    'medieval',
    'ancient',
}

BATTLE_DIRECTIVE = (
    ' When the documentary topic involves combat, warfare, gladiators, '
    'military history, or historical violence: ALWAYS prioritize visceral, '
    'physically intense imagery — bloodied armor, sweat-drenched skin, '
    'straining muscles, clashing weapons with motion blur, dust and chaos '
    'of battle, grim warrior faces, fire and torch smoke, brutal crowd '
    'reactions, fallen bodies, impact moments, blood on sand. '
    'The viewer must FEEL the violence and physicality in every frame. '
    'Avoid archaeological artifacts, scholarly scrolls, stone inscriptions, '
    'maps, and museum-style objects UNLESS the Murch brief explicitly calls '
    'for a calm/exposition or resolution arc zone.'
)

# HANDS (2026-08-25): faces stop a scroll; hands are what the renderer
# ruins (wrong finger counts, fused hands — hand QC flagged 0/40 on the
# Black Death run with three-finger hands in frame, and no VLM counts
# fingers). The intensity directive used to list "the hand" among the
# things to get close to. It no longer does, and this rule keeps hands
# out of the foreground at every level; anatomy mode (ControlNet +
# more steps) is the only place a hand may lead.
HANDS_RULE = (
    '  - HANDS: keep hands out of the foreground and never make a hand the '
    'subject or the near-camera element — the renderer ruins them. Hands may '
    'appear small, in shadow, mid-frame or holding something; never a '
    'close-up of a hand, never fingers presented to camera\n'
)

# DISEASE / FAMINE (2026-08-25): "bubo... grotesque swelling" rendered an
# eviscerated chest, "emaciated... ribs" rendered bone through skin. The
# renderer reads medical nouns graphically. Below 'extreme' the writer
# describes illness on intact skin and famine in the face.
SKIN_RULE = (
    '  - DISEASE AND FAMINE ON THE SKIN, NOT THROUGH IT: describe illness as '
    'intact skin — "dark egg-sized swelling under the skin at the neck", '
    '"blackened fingertips", "bruise-dark blotches" — and famine as faces — '
    '"hollow cheeks, sunken eyes, loose skin at the collarbone". Never write '
    'ribs, bone, exposed, open wound, entrails or eviscerated: the renderer '
    'paints those literally and the frame becomes gore\n'
)


def is_battle_topic(*, topic, directive, pipeline_state, era_lock, log) -> bool:
    """Is this episode substantially ABOUT warfare? In: the episode's words and the
    era-lock verdict. Out: the flag that gates the combat directive and the battle
    style register.

    A keyword scan cannot tell a war documentary from a political one, so the era-lock
    classifier (which has read the finished script) is believed when it has an opinion and
    the keyword scan survives only as the fallback for when it could not run. Logs the
    fallback, and logs any disagreement between the two — both lines, in that order, are
    the monolith's.
    """
    # Match on what the episode is ABOUT, not the department bucket:
    # `topic` is 'general' for every free-text run, so an episode built on
    # the Khalsa army and the Anglo-Sikh wars never matched a single
    # battle keyword and never got the combat directive.
    _topic_lower = ' '.join(
        (
            topic or '',
            directive or '',
            pipeline_state.get('essay_title', '') or '',
        )
    ).lower()
    # A keyword scan cannot tell a war documentary from a political one.
    # `BATTLE_KEYWORDS` contains 'revolution', 'uprising', 'rebellion',
    # 'medieval', 'ancient' and 'roman', so "Revolutions of 1848" — an
    # episode about parliamentary reform, potato blight and press
    # censorship — matched, and the system prompt then demanded
    # "bloodied armor... blood on sand" and set the visual style for all
    # 45 prompts to 'battle-worn'.
    #
    # The era-lock call already reads the finished script, so ask it
    # whether this is substantially ABOUT warfare and believe that
    # instead. The keyword scan survives only as the fallback for when
    # the classifier could not run (no API key, malformed reply), where
    # a crude signal still beats none.
    _combat_verdict = era_lock.get('is_combat')
    if _combat_verdict is None:
        _is_battle_topic = any(kw in _topic_lower for kw in BATTLE_KEYWORDS)
        log(
            'INFO',
            'Stage 3.5',
            f'Combat directive: no classifier verdict — keyword fallback says {_is_battle_topic}',
        )
    else:
        _is_battle_topic = bool(_combat_verdict)
        _kw_would = any(kw in _topic_lower for kw in BATTLE_KEYWORDS)
        if _kw_would != _is_battle_topic:
            log(
                'INFO',
                'Stage 3.5',
                f'Combat directive: classifier says {_is_battle_topic}, '
                f'keyword scan would have said {_kw_would} — using the '
                f'classifier',
            )
    return _is_battle_topic


def build_style_ctx(
    *,
    is_battle,
    subject_type,
    is_modern_topic,
    family_early,
    visual_style,
    era_lock,
    intensity,
) -> str:
    """The one style register every prompt in the batch is written in.

    In: the combat verdict, the subject type, the modern-topic flag, the renderer family,
    the configured visual style, the era lock and the intensity dial. Out: the
    `_style_ctx` string, which the writer is handed twice — as "Visual style" and as
    framework item 5 — and which therefore is the cheapest place to state the period and
    to raise the pitch of all N prompts at once.
    """
    if is_battle:
        _style_ctx = 'historical cinematic, photorealistic gritty realism, battle-worn period-accurate'
    elif subject_type == 'person' and not is_modern_topic:
        _style_ctx = 'intimate biographical portrait, cinematic character study, period-accurate environment'
    elif subject_type == 'gold' and not is_modern_topic:
        _style_ctx = 'noir cinematic, high-contrast shadows, gritty realism, crime documentary aesthetic'
    elif is_modern_topic:
        _style_ctx = 'cinematic documentary, photorealistic, modern setting'
    else:
        _style_ctx = 'historical cinematic, oil painting realism, period-accurate'
        # One style register per slot (P-12): every render prompt is
        # prefixed with the visual style ("cinematic photograph" by
        # default), and Qwen obeys both — so "oil painting realism"
        # fought "photograph" inside the same frame. On Qwen with a
        # photographic prefix the writer's brief stays photographic.
        try:
            _vs_prefix_early = str(
                _STYLE_LORA_CONFIG.get(visual_style, _STYLE_LORA_CONFIG['cinematic']).get('prefix', '') or ''
            )
        except Exception:
            _vs_prefix_early = 'cinematic photograph'
        if family_early == 'qwen' and 'photograph' in _vs_prefix_early.lower():
            _style_ctx = 'historical cinematic, photorealistic period reconstruction, period-accurate'
    # The period is stated here because _style_ctx is what the prompt-writing
    # model is handed as "Visual style" AND as framework item 5. Leaving it at
    # "modern setting" for a historical episode is what put a contemporary
    # street scene four slots into the Sikh Empire episode.
    if era_lock['is_historical'] and era_lock['period_label']:
        _style_ctx += f', set entirely in {era_lock["period_label"]}'
    # INTENSITY DIAL: _style_ctx is handed to the writer twice — as
    # "Visual style" and as framework item 5 — so it is the cheapest
    # place to raise the pitch of every prompt in the batch at once.
    if _INTENSITY_STYLE_CTX[intensity['level']]:
        _style_ctx += ', ' + _INTENSITY_STYLE_CTX[intensity['level']]
    return _style_ctx


def build_quality_tag(*, is_modern_topic, subject_type) -> str:
    """In: the modern-topic flag and the subject type. Out: the quality tag appended to
    every prompt. It is style-aware because "8k" fights historical and portrait
    aesthetics."""
    # Quality tag is style-aware — "8k" fights historical/portrait aesthetics
    if is_modern_topic:
        return 'photorealistic, 8k, sharp detail, crisp documentary style'
    if subject_type == 'person':
        return 'photorealistic portrait, shallow depth of field, cinematic grain, sharp subject focus'
    return 'cinematic grain, textured surfaces, photorealistic period reconstruction, natural light'


def build_intensity_directive(intensity) -> str:
    """In: the intensity dial. Out: the always-on, topic-independent impact directive —
    empty when the dial is off, with one paragraph added at rank >= 2 and another when the
    hook rank is >= 2.

    The combat instruction is gated behind the combat verdict, so every non-combat episode
    — plague, famine, industrial disaster, a life ending badly — was written at a flat
    scholarly pitch no matter what the emotion curve said. This directive runs regardless
    of topic and scales with the dial.

    It deliberately does NOT reuse the battle wording. That block has a documented misfire
    history: the keyword scan matched "Revolutions of 1848" and demanded "blood on sand"
    for an episode about parliamentary reform. Combat-specific nouns stay behind the
    classifier; this asks for dramatic FORCE in whatever form the subject actually has,
    which is what generalises. The "not shock value" sentence is load-bearing, not a
    disclaimer: a model told only to be intense reaches for gore as the cheapest reading of
    the word, and a documentary about Roman aqueducts does not need blood to be arresting —
    it needs to get close to a face.
    """
    _intensity_directive = ''
    if intensity['enabled']:
        _intensity_directive = (
            ' This documentary is cut for maximum visual impact and every frame '
            'must earn attention on its own — the test is whether a viewer '
            'scrolling past would stop. Get close. Find the face, the '
            'body under strain, the moment of danger or exhaustion or defiance. '
            'Use crushing scale, fire, smoke, weather, darkness and ruin. Put '
            'something at stake inside the frame. Prefer a human presence to an '
            'artifact, an empty room or a museum object whenever the words allow '
            'one. Reach for the most striking image the narration honestly '
            'supports rather than the safest one. Intensity here means dramatic '
            'force and physical stakes, NOT shock value — do not reach for '
            'gratuitous gore or cruelty; reach for the image nobody can look away '
            'from.'
        )
        if intensity['rank'] >= 2:
            _intensity_directive += (
                ' Push all the way: the hardest, most confronting moment the '
                'subject genuinely contains, rendered with photographic '
                'specificity rather than implication. Difficult imagery — injury, '
                'death, suffering, ruin — is in scope where the subject is '
                'actually about those things, and never as decoration where it '
                'is not.'
            )
        if intensity['hook_rank'] >= 2:
            _intensity_directive += (
                ' SLOT 1 IS THE HOOK. It is the first frame a viewer sees and it '
                'alone decides whether they watch the rest. It must be the single '
                'most arresting image in the entire episode: close, direct and '
                'impossible to scroll past — a face filling the frame, a body '
                'mid-action, a moment of danger, a detail nobody expects. It is '
                'NEVER an establishing shot, never a landscape, never an object, '
                'never a wide view of a place. If the narration in slot 1 is calm, '
                'ignore that and pull the imagery forward from the most compelling '
                'thing the episode is about — the hook answers to the episode, not '
                'to its own twenty seconds of script. It must also carry ONE '
                "unmistakable cue of THIS episode's subject — the object, costume, "
                'symptom, weapon or setting a viewer would name the topic from — so '
                'the frame could belong to no other film.'
            )
    return _intensity_directive


def build_subject_directive(*, subject_type, is_battle) -> str:
    """In: the subject type and the combat verdict. Out: the biographical or noir
    directive, or '' — a combat episode gets the battle directive instead and never
    both."""
    if subject_type == 'person' and not is_battle:
        return (
            ' This is a biographical documentary about a specific individual. '
            "Ground every prompt in that person's physical world — their era, "
            'their environments, their possessions, the faces of people around them. '
            "Alternate between intimate close-ups implying the subject's presence "
            'and wide shots of the spaces they inhabited. The individual should be '
            'felt in every frame, even when not literally depicted.'
        )
    if subject_type == 'gold' and not is_battle:
        return (
            ' This documentary covers resources, power, or crime. Lean into noir '
            'visual language: stark shadows, high contrast, close-ups of hands '
            'exchanging objects, wealth and squalor in the same frame, surveillance '
            'angles, faces half-obscured by shadow. Show human cost alongside '
            'power structures.'
        )
    return ''


def build_period_lock(*, era_lock, n) -> tuple:
    """In: the era lock and the slot count. Out: `(section, rule)` — the PERIOD LOCK block
    of the user message and the two prompt rules that enforce it — or `('', '')` for a
    modern episode.

    A documentary script constantly reaches into the present — "and yet today, most of the
    world barely knows it existed", "still echoes", "what remains now". Those clauses are
    RHETORICAL. Without this the model reads them as stage directions and photographs the
    present day in the middle of a historical sequence.
    """
    if not era_lock['is_historical']:
        return '', ''
    _era_anchor_lines = ''.join(f'    - {_a}\n' for _a in (era_lock.get('anchors') or []))
    _period_lock_section = (
        f'PERIOD LOCK — every image in this episode depicts '
        f'{era_lock["period_label"]}. This is absolute and applies to '
        f'ALL {n} slots including the first and the last.\n'
        + (f'  Period-accurate detail for this exact time and place:\n{_era_anchor_lines}' if _era_anchor_lines else '')
        + '  The narration will use words like "today", "still", "now", '
        '"modern", "remains" and "what survives". These are RHETORICAL '
        'devices about legacy — they are NEVER an instruction to depict '
        'the present day. When a beat says the subject still matters '
        'today, photograph the HISTORICAL subject it refers to: the '
        'weathered monument, the empty hall, the worn object, the '
        'descendants in period dress — never a contemporary scene.\n\n'
    )
    # Era-bucketed examples for the bare-noun rule, so a Roman
    # episode is shown galleys and sandals, not cogs and turnshoes.
    try:
        from zyg_workflows import era_gate as _eg_rule

        _bn_vocab = _eg_rule.PERIOD_VOCAB[_eg_rule.period_bucket(era_lock)]
    except Exception:
        _bn_vocab = {}
    _bn_examples = '; '.join(
        f'"{_bn_vocab[_k]}"'
        for _k in ('boat', 'clothing', 'footwear', 'lighting', 'window', 'hair')
        if _bn_vocab.get(_k)
    )
    _period_lock_rule = (
        '  - PERIOD LOCK: absolutely no present-day content in any prompt — '
        'no cars, motorbikes, bicycles, tarmac, electric or neon light, '
        'power lines, glass shopfronts, billboards, printed signage, '
        'phones, cameras, plastic, modern clothing (jeans, t-shirts, suits, '
        'trainers, sunglasses), tourists, or museum display cases. '
        'Never use the words "contemporary", "modern", "present-day" or '
        '"today" to describe a scene. This applies to C prompts too.\n'
        # NO BARE NOUNS (2026-08-25). "No modern words" was the rule
        # and the Black Death prompts obeyed it — and rendered a
        # motor boat, sneakers, a wristwatch, louvred shutters and
        # virus icons on a map, because the renderer gives an
        # unqualified noun its modern default. The rule is now on
        # the NOUN: every object carries its period descriptor.
        '  - NO BARE NOUNS: the renderer gives any unqualified object its '
        'modern default — "vessel" becomes a motor boat, "shoe" a sneaker, '
        '"lantern" a gas lamp, "shutters" louvres, "bracelet" a wristwatch, '
        'and any head without a described hairstyle a 2020s haircut. Every '
        'garment, vessel, light source, window, tool, weapon, piece of '
        'furniture and hairstyle MUST carry a period descriptor, taken from '
        'the period-accurate detail lines above, ON THE NOUN ITSELF'
        + (f' — e.g. {_bn_examples}' if _bn_examples else '')
        + '. Every visible head gets its hair or head-covering described. '
        'Maps and documents show faded hand-inked outlines only, never '
        'icons, symbols or markers. This applies to C prompts too.\n'
    )
    return _period_lock_section, _period_lock_rule


def build_system_prompt(
    *,
    family_early,
    intensity_directive,
    battle_directive,
    subject_directive,
    era_lock,
) -> str:
    """In: the renderer family, the three directives and the era lock. Out: the Sonnet
    system prompt.

    The renderer is NAMED (P-12): this said "FLUX" on every Qwen run, and the two need
    opposite handling of text (Qwen prints it legibly) and of style stacking.
    """
    # Name the renderer that will actually paint the prompt (P-12):
    # this said "FLUX" on every Qwen run, and the two need opposite
    # handling of text (Qwen prints it legibly) and style stacking.
    _renderer_name = 'Qwen-Image-2512' if family_early == 'qwen' else 'FLUX.1-schnell'
    return (
        'You are a professional documentary cinematographer and visual director. '
        f'You write precise, vivid {_renderer_name} image generation prompts for video slideshows. '
        'Every prompt is internally consistent, camera-ready, and visually distinct.'
        + intensity_directive
        + battle_directive
        + subject_directive
        + (
            (
                ' Every image you write is set in '
                + era_lock['period_label']
                + '. You never depict the present day, whatever the narration says.'
            )
            if era_lock['is_historical']
            else ''
        )
    )
