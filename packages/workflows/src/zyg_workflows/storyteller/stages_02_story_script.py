# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 2 and Stage 2a of the storyteller pipeline — the story script.

``stage_02_scene_budget`` derives the scene count and the per-scene word budget
from the requested duration; ``stage_02a_sonnet_story`` is the single Sonnet
call that writes the story arc, the narration and the visual concept of every
scene. Stage 2b, which turns those concepts into FLUX prompts, is next door in
``stage_02b_render_prompts.py``. Cut verbatim out of
``pipeline_storyteller._run_storyteller_pipeline`` (lines 916-1040 and
1044-1359 of commit 770c30a); see ``SPLIT_LOG.md``.

``stage_02a_sonnet_story`` is now the orchestrator only: the prompt assembly,
the streaming call, the JSON parse, the stock fallback script and the two
rewrite round-trips live in ``stages_02_story_script_sonnet.py``, where they can
be unit-tested without an Anthropic client."""

import logging as _zyg_logging

from zyg_workflows.pipeline_config import _dsl
from zyg_workflows.storyteller.stages_02_story_script_sonnet import (
    build_sonnet_prompts,
    expand_short_scenes,
    fallback_scenes,
    narration_word_count,
    parse_story_scenes,
    run_sonnet_story_call,
    trim_long_scenes,
)

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')


def stage_02_scene_budget(ctx):
    _check_stop = ctx._check_stop
    _log = ctx._log
    _update_stage = ctx._update_stage
    camera_mode = ctx.camera_mode
    character_params = ctx.character_params
    duration_min = ctx.duration_min
    voice_style = ctx.voice_style
    # ── Stage 2: Story Script (Claude) ────────────────────────────────────────
    _update_stage('Stage 2 — Story Script', 8)
    _check_stop()

    # Word-budget scene planning — drives predictable TTS duration.
    # Narration with natural pacing runs ≈ 130–140 WPM including pauses.
    # Using 135 WPM provides a realistic estimate aligned with actual Azure output.
    # Derive n_scenes from word budget so TTS duration ≈ requested duration.
    # Character mode speaks slower (conversational, no stage-direction padding) → 125 WPM.
    # Narration mode uses standard broadcast pace → 135 WPM.
    _WPM = 125 if voice_style == 'character' else 135
    _WORDS_PER_SCENE = 55  # cinematic average: ~55 words / ~22s per scene
    target_words = max(40, int(duration_min * _WPM))
    n_scenes = max(4, min(120, round(target_words / _WORDS_PER_SCENE)))

    # Dynamic per-scene word budgets following story arc tension curve.
    # Hooks and climax scenes get more words; transitions get fewer.
    _arc_budgets = []
    for _ai in range(n_scenes):
        _pct = _ai / max(n_scenes - 1, 1)
        if _pct < 0.10:  # opening hook — punchy
            _w = 0.70
        elif _pct < 0.20:  # early rising action
            _w = 1.00
        elif 0.40 < _pct < 0.60:  # midpoint climax — most words
            _w = 1.30
        elif _pct > 0.85:  # emotional resolution
            _w = 1.20
        else:
            _w = 1.00
        _arc_budgets.append(_w)
    _arc_total = sum(_arc_budgets)
    _scene_word_budgets = [max(20, int(target_words * w / _arc_total)) for w in _arc_budgets]
    _log(
        'INFO',
        'Stage 2',
        f'Word budget: {target_words} words → {n_scenes} scenes '
        f'(avg {target_words // n_scenes} words/scene, {duration_min:.1f} min target)',
    )

    # Build a rich character description for the storywriter using every
    # descriptor we now persist in character_params.  Auto-filled fields
    # behave the same as user-chosen ones.
    # 2026-07-31: character_params was reconciled against the character
    # bible in Stage 1 (ZYG_ST_BIBLE_WINS) — for a char_id with a bible
    # every identity field below is the SERVER's value, not the browser's.
    gender_str = character_params.get('gender', 'person')
    hair_str = character_params.get('hair_color', 'brown-haired')
    eyes_str = character_params.get('eye_color', '')
    style_str = character_params.get('style') or character_params.get('render_style', 'animated')
    _age_d = character_params.get('age')
    _face_d = character_params.get('face_shape', '')
    _build_d = character_params.get('body_build', '')
    _hairstyle = character_params.get('hair_style', '')
    _clothes_d = character_params.get('default_clothing', '')
    _accs_d = character_params.get('accessories', '')
    _expr_d = character_params.get('default_expression', '')
    _marks_d = character_params.get('distinctive_marks', '')
    _heritage = character_params.get('ethnic_heritage', '')

    _desc_bits: list[str] = []
    if _age_d and str(_age_d).strip().isdigit():
        _desc_bits.append(f'a {int(_age_d)}-year-old {gender_str}')
    else:
        # 2026-07-31: an ageless 'a male character' let Claude write (and
        # Stage 2b render) an adult for a bible that says age_range='child'.
        _age_adj = {
            'child': 'young child',
            'teen': 'teenage',
            'young': 'young adult',
            'adult': 'adult',
            'mature': 'middle-aged',
            'elder': 'elderly',
        }.get(str(character_params.get('age_range') or '').strip().lower(), '')
        _desc_bits.append(f'a {_age_adj} {gender_str}'.replace('  ', ' ') if _age_adj else f'a {gender_str} character')
    if _heritage:
        _desc_bits.append(f'{_heritage} heritage')
    if _face_d:
        _desc_bits.append(f'{_face_d} face')
    if _build_d:
        _desc_bits.append(_build_d)
    if hair_str:
        _hair_phrase = hair_str + (' hair' if not hair_str.endswith('hair') else '')
        if _hairstyle and _hairstyle.lower() not in (hair_str.lower(), ''):
            _hair_phrase = f'{_hairstyle} {hair_str} hair'
        _desc_bits.append(_hair_phrase)
    if eyes_str:
        _desc_bits.append(f'{eyes_str} eyes')
    if _clothes_d:
        _desc_bits.append(f'wearing {_clothes_d}')
    if _accs_d and _accs_d.lower() not in ('', 'none'):
        _desc_bits.append(_accs_d)
    if _expr_d:
        _desc_bits.append(f'{_expr_d} expression')
    if _marks_d and _marks_d.lower() not in ('', 'none'):
        _desc_bits.append(_marks_d)
    if style_str:
        _desc_bits.append(f'rendered in {style_str} style')
    char_desc = ', '.join(_desc_bits)

    # Camera angle selection
    _ANGLE_MAP = {
        'front': 'front-facing shot',
        'side': 'side profile shot',
        'back': 'rear three-quarter shot',
        '3quarter': 'three-quarter angle shot',
        'closeup': 'close-up portrait shot',
        'overhead': 'overhead bird-eye shot',
        'low': 'low-angle heroic shot',
    }
    if camera_mode == 'automatic':
        angle_instruction = (
            'Vary camera angles organically: mix close-ups, medium shots, '
            'wide establishing shots, and over-the-shoulder angles. '
            'Each scene should have a different angle for visual variety.'
        )
    elif camera_mode in _ANGLE_MAP:
        angle_instruction = (
            f'Use {_ANGLE_MAP[camera_mode]} consistently for all scenes, unless a dramatic moment calls for a close-up.'
        )
    else:
        angle_instruction = 'Use varied camera angles appropriate to each scene.'

    ctx._WPM = _WPM
    ctx._scene_word_budgets = _scene_word_budgets
    ctx.angle_instruction = angle_instruction
    ctx.char_desc = char_desc
    ctx.n_scenes = n_scenes
    ctx.style_str = style_str
    ctx.target_words = target_words


def stage_02a_sonnet_story(ctx):
    _WPM = ctx._WPM
    _check_stop = ctx._check_stop
    _log = ctx._log
    _save = ctx._save
    _scene_word_budgets = ctx._scene_word_budgets
    char_desc = ctx.char_desc
    duration_min = ctx.duration_min
    era_str = ctx.era_str
    n_scenes = ctx.n_scenes
    pipeline_id = ctx.pipeline_id
    story_prompt = ctx.story_prompt
    style_str = ctx.style_str
    target_words = ctx.target_words
    trigger_token = ctx.trigger_token
    voice_style = ctx.voice_style
    # ── Stage 2a: Sonnet — story arc, narration, visual concept ─────────────
    # Only writes what Sonnet is uniquely good at: narrative voice and story structure.
    # FLUX-specific fields (flux_prompt, shot_type, focal_zone) are deferred to Haiku.
    _s2a_sys, _s2a_user = build_sonnet_prompts(
        char_desc,
        duration_min,
        era_str,
        n_scenes,
        _scene_word_budgets,
        story_prompt,
        style_str,
        target_words,
        voice_style,
    )

    import anthropic as _anthropic_st
    import re as _re_json_st

    _claude_client_st = _anthropic_st.Anthropic()
    if _dsl is not None:
        _s2a_sys = _dsl.wrap_system_planner(_s2a_sys, 'storyteller')
    _story_raw = run_sonnet_story_call(
        _claude_client_st,
        _s2a_sys,
        _s2a_user,
        n_scenes,
        duration_min,
        era_str,
        pipeline_id,
        _log,
    )
    _save()
    _check_stop()

    # ── Parse Stage 2a response ───────────────────────────────────────────────
    scenes, story_title = parse_story_scenes(_story_raw, _re_json_st, story_prompt[:60], _log)
    if not scenes:
        # Fallback: build varied scenes that cycle through shot types, emotions, locations
        scenes = fallback_scenes(n_scenes, char_desc, era_str, trigger_token)

    # ── Word-count validator + trimmer ───────────────────────────────────────
    # Never trust the LLM to self-regulate duration. Validate and trim if needed.
    if scenes:
        _actual_words = narration_word_count(scenes)
        _predicted_min = _actual_words / _WPM
        _tolerance_min = 0.5  # allow ±30s overrun before trimming
        _log(
            'INFO',
            'Stage 2a',
            f'Narration validation: {_actual_words} words → predicted {_predicted_min:.1f} min '
            f'(target {duration_min:.1f} min)',
        )
        if _predicted_min > duration_min + _tolerance_min:
            try:
                trim_long_scenes(
                    scenes,
                    _claude_client_st,
                    _re_json_st,
                    _actual_words,
                    target_words,
                    duration_min,
                    era_str,
                    _scene_word_budgets,
                    _WPM,
                    _log,
                )
            except Exception as _trim_e:
                _log('WARNING', 'Stage 2a', f'Claude trim call failed ({_trim_e}) — keeping original script')

        elif _actual_words < int(
            (0.93 if voice_style == 'character' else 0.92) * target_words
        ):  # 2026-07-24: 0.85 let an 8.4-min script through a 10-min target
            # Character mode: tighter 90% threshold (no stage-direction padding to inflate duration).
            # Narration mode: 85% threshold (some natural variation expected).
            _log(
                'INFO',
                'Stage 2a',
                f'Script under-length ({_actual_words}/{target_words} words, '
                f'{_predicted_min:.1f}/{duration_min:.1f} min) — requesting expansion',
            )
            try:
                expand_short_scenes(
                    scenes,
                    _claude_client_st,
                    _re_json_st,
                    target_words,
                    duration_min,
                    era_str,
                    _scene_word_budgets,
                    _WPM,
                    _log,
                )
            except Exception as _exp_e:
                _log('WARNING', 'Stage 2a', f'Expansion call failed ({_exp_e}) — proceeding with shorter script')

    ctx._claude_client_st = _claude_client_st
    ctx._re_json_st = _re_json_st
    ctx.scenes = scenes
    ctx.story_title = story_title
