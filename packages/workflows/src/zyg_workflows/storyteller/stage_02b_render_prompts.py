# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 2b of the storyteller pipeline — visual concept to FLUX prompt.

One Sonnet call (Haiku on retry) converts every scene's ``visual_concept`` into
a ``flux_prompt`` plus the shot metadata the image stage and the Ken Burns pass
read: ``shot_type``, ``focal_zone`` and ``character_state``. Cut verbatim out of
``pipeline_storyteller._run_storyteller_pipeline`` (lines 1365-1622 of commit
770c30a); see ``SPLIT_LOG.md``."""

import json
import logging as _zyg_logging
import os
import time

from zyg_workflows.pipeline_config import _caveman_kw, _dsl
from zyg_workflows.runtime import _record_token_usage

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')


def stage_02b_render_prompts(ctx):
    _animated_render = ctx._animated_render
    _claude_client_st = ctx._claude_client_st
    _log = ctx._log
    _re_json_st = ctx._re_json_st
    _save = ctx._save
    _scene_word_budgets = ctx._scene_word_budgets
    angle_instruction = ctx.angle_instruction
    char_desc = ctx.char_desc
    era_str = ctx.era_str
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    scenes = ctx.scenes
    story_title = ctx.story_title
    trigger_token = ctx.trigger_token
    visual_style = ctx.visual_style
    # ── Stage 2b: Claude — convert visual_concept → FLUX prompt + shot metadata ──
    # Sonnet 4.6 for parity with video/scholarly planners (Haiku retained as retry fallback).
    # Input: list of {scene_number, visual_concept, emotion}
    # Output: list of {scene_number, flux_prompt, shot_type, focal_zone}
    # Scenes that already have flux_prompt (from fallback) are left untouched.
    _scenes_needing_flux = [
        {'n': s['scene_number'], 'concept': s.get('visual_concept', ''), 'emotion': s.get('emotion', 'calm')}
        for s in scenes
        if not s.get('flux_prompt')
    ]

    if _scenes_needing_flux:
        _s2b_model = 'claude-sonnet-4-6'
        _log('INFO', 'Stage 2b', f'Sonnet: generating FLUX prompts for {len(_scenes_needing_flux)} scenes…')
        # 2026-07-24 r3: re-assert canonical identity + render medium. The
        # LLM previously re-described the character generically ('brown-
        # haired girl' for box-braided Runa) and drifted into 'animated
        # cinematic' wording against a photorealistic character.
        _ident_2b = ''
        _rs_2b = ''
        try:
            from zyg_workflows import character_bible_service as _cbs_2b

            _pkg_2b = pipeline_state.get('character_bible') or {}
            _ident_2b = _cbs_2b.storyteller_identity_snippet(_pkg_2b)
            _rs_2b = ((_pkg_2b.get('style_profile') or {}).get('render_style') or '').lower()
        except Exception as _exc:
            _zyg_log.warning('character identity snippet unavailable, scene prompts continue without it: %s', _exc)
        # 2026-07-25: an SDXL run is the 3D-toon twin — the scene prompts
        # must be animated-styled, not photoreal (the bible render_style is
        # photoreal for the FLUX primary).
        _photo_2b = (not _animated_render) and not any(
            t in _rs_2b for t in ('toon', 'anime', 'cartoon', 'animat', 'illustrat', 'comic', 'drawn')
        )
        _s2b_sys = (
            f'You are a FLUX image-prompt specialist. '
            f'The character trigger token is "{trigger_token or char_desc}". '
            f'Always include the trigger token at the start of every flux_prompt. '
            + (
                f'Canonical character appearance (use these attributes, never contradict '
                f'or genericize them): {_ident_2b}. '
                if _ident_2b
                else ''
            )
            + (
                'The renders are PHOTOREALISTIC live-action stills — never describe them '
                'as animated, cartoon, anime, illustration, or drawing. '
                if _photo_2b
                else ''
            )
            + (
                'The renders are 3D Pixar-style ANIMATED stills — describe scenes as a '
                'stylized 3d animated movie; do not ask for photorealism or film grain. '
                if _animated_render
                else ''
            )
            + 'Match flux_prompt framing to shot_type (medium = waist up, wide = full body + environment). '
            'Return only raw JSON — no markdown, no explanation.'
        )
        _s2b_user = (
            f'Character: {char_desc}. Style: {visual_style}. Era: {era_str}.\n'
            f'Camera direction: {angle_instruction}\n\n'
            f'For each scene below produce a JSON array entry:\n'
            f'{{"scene_number":N,"flux_prompt":"≤40 words, trigger token first, vivid bright description",'
            f'"shot_type":"close-up|medium|wide|establishing|over-the-shoulder",'
            f'"focal_zone":"center|left|right|top|bottom",'
            f'"character_state":{{"clothing":"≤15 words","hair":"≤8 words","lighting":"≤8 words"}}}}\n\n'
            f'SHOT VARIETY RULES — follow strictly:\n'
            f'- Distribute shot_type across the whole sequence: ~30% medium, ~25% close-up, '
            f'~20% wide, ~15% establishing, ~10% over-the-shoulder\n'
            f'- Never use the same shot_type more than twice in a row\n'
            f'- Reserve close-up for emotional peaks; wide/establishing for scene transitions\n\n'
            f'Scenes:\n{json.dumps(_scenes_needing_flux)}'
        )
        _s2b_max_tokens = max(4096, len(_scenes_needing_flux) * 100 + 1024)
        _s2b_succeeded = False
        for _s2b_attempt in range(3):
            try:
                if _s2b_attempt > 0:
                    _backoff = 2**_s2b_attempt  # 2s, 4s, 8s
                    _log('INFO', 'Stage 2b', f'{_s2b_model} retry {_s2b_attempt}/2 — waiting {_backoff}s…')
                    time.sleep(_backoff)
                with _claude_client_st.messages.stream(
                    model=_s2b_model,
                    max_tokens=_s2b_max_tokens,
                    system=_s2b_sys,
                    messages=[{'role': 'user', 'content': _s2b_user}],
                ) as _s2b_stream:
                    _s2b_response = _s2b_stream.get_final_message()
                _s2b_raw = _s2b_response.content[0].text if _s2b_response.content else ''
                _s2b_out_tokens = getattr(_s2b_response.usage, 'output_tokens', '?')
                if getattr(_s2b_response, 'usage', None):
                    _record_token_usage(
                        model=_s2b_model,
                        prompt_tokens=_s2b_response.usage.input_tokens,
                        completion_tokens=_s2b_response.usage.output_tokens,
                        pipeline_id=pipeline_id,
                        stage='Stage 2b',
                        pipeline_type='storyteller',
                        **_caveman_kw('planner'),
                    )
                _log(
                    'INFO',
                    'Stage 2b',
                    f'{_s2b_model} response: {len(_s2b_raw)} chars, output_tokens={_s2b_out_tokens}',
                )

                # Parse and merge Haiku output back into scenes by scene_number
                _s2b_jm = _re_json_st.search(r'\[.*\]', _s2b_raw, _re_json_st.DOTALL)
                if _s2b_jm:
                    try:
                        _s2b_parsed = json.loads(_s2b_jm.group(0))
                    except json.JSONDecodeError:
                        from json_repair import repair_json as _repair_json2

                        _s2b_parsed = json.loads(_repair_json2(_s2b_jm.group(0)))
                    _flux_by_scene = {item['scene_number']: item for item in _s2b_parsed}
                    _merged = 0
                    for _sc in scenes:
                        _fl = _flux_by_scene.get(_sc['scene_number'])
                        if _fl:
                            _sc['flux_prompt'] = _fl.get('flux_prompt', '')
                            _sc['shot_type'] = _fl.get('shot_type', 'medium')
                            _sc['focal_zone'] = _fl.get('focal_zone', 'center')
                            _sc['character_state'] = _fl.get('character_state', {})
                            _merged += 1
                    _log('INFO', 'Stage 2b', f'Merged FLUX fields into {_merged}/{len(scenes)} scenes')
                _s2b_succeeded = True
                break  # success — exit retry loop
            except Exception as _s2b_e:
                _err_str = str(_s2b_e)
                _is_overload = 'overloaded' in _err_str.lower() or '529' in _err_str
                if _s2b_attempt < 2:
                    _log(
                        'WARNING',
                        'Stage 2b',
                        f'{_s2b_model} attempt {_s2b_attempt + 1}/3 failed '
                        f'({"overloaded" if _is_overload else "error"}: {_err_str[:80]}) — will retry',
                    )
                else:
                    _log(
                        'WARNING',
                        'Stage 2b',
                        f'{_s2b_model} call failed after 3 attempts ({_err_str[:80]}) — falling back to Haiku',
                    )
        if not _s2b_succeeded:
            _log('INFO', 'Stage 2b', 'Attempting Haiku fallback for FLUX prompts…')
            try:
                with _claude_client_st.messages.stream(
                    model='claude-haiku-4-5',
                    max_tokens=_s2b_max_tokens,
                    system=_s2b_sys,
                    messages=[{'role': 'user', 'content': _s2b_user}],
                ) as _s2b_fallback_stream:
                    _s2b_fallback_resp = _s2b_fallback_stream.get_final_message()
                _s2b_fb_raw = _s2b_fallback_resp.content[0].text if _s2b_fallback_resp.content else ''
                _s2b_jm_fb = _re_json_st.search(r'\[.*\]', _s2b_fb_raw, _re_json_st.DOTALL)
                if _s2b_jm_fb:
                    try:
                        _s2b_fb_parsed = json.loads(_s2b_jm_fb.group(0))
                    except json.JSONDecodeError:
                        from json_repair import repair_json as _repair_json3

                        _s2b_fb_parsed = json.loads(_repair_json3(_s2b_jm_fb.group(0)))
                    _flux_by_scene_fb = {item['scene_number']: item for item in _s2b_fb_parsed}
                    for _sc in scenes:
                        _fl = _flux_by_scene_fb.get(_sc['scene_number'])
                        if _fl:
                            _sc['flux_prompt'] = _fl.get('flux_prompt', '')
                            _sc['shot_type'] = _fl.get('shot_type', 'medium')
                            _sc['focal_zone'] = _fl.get('focal_zone', 'center')
                            _sc['character_state'] = _fl.get('character_state', {})
                    _log('INFO', 'Stage 2b', 'Haiku fallback FLUX prompts merged successfully')
            except Exception as _s2b_fb_e:
                _log(
                    'WARNING',
                    'Stage 2b',
                    f'Haiku fallback also failed ({_s2b_fb_e}) — using inline visual_concept prompts',
                )

    # Ensure every scene has required fields (fill any gaps from fallback or Haiku skip)
    _shot_cycle_fb2 = ['medium', 'wide', 'close-up', 'establishing', 'over-the-shoulder']
    for _si2, _sc in enumerate(scenes):
        if not _sc.get('flux_prompt'):
            _concept = _sc.get('visual_concept', f'{char_desc} in {era_str}')
            _sc['flux_prompt'] = (
                f'{trigger_token} {_concept}, {era_str}, '
                f'{_sc.get("emotion", "calm")}, cinematic lighting, {visual_style} style'
            )
        if not _sc.get('shot_type'):
            _sc['shot_type'] = _shot_cycle_fb2[_si2 % len(_shot_cycle_fb2)]
        if not _sc.get('focal_zone'):
            _sc['focal_zone'] = ['center', 'left', 'right'][_si2 % 3]

    # 2026-07-24 r3: photoreal characters must not carry animation-medium
    # words into FLUX prompts regardless of which path produced them.
    try:
        _rs_san = ''
        try:
            _rs_san = (
                ((pipeline_state.get('character_bible') or {}).get('style_profile') or {}).get('render_style') or ''
            ).lower()
        except (AttributeError, TypeError) as _exc:
            _zyg_log.debug('bible render_style unreadable, treating it as empty: %s', _exc)
        if not _animated_render and not any(
            t in _rs_san for t in ('toon', 'anime', 'cartoon', 'animat', 'illustrat', 'comic', 'drawn')
        ):
            import re as _re_san

            # r3 review fix: ambiguous nouns only strip in medium-sense
            # contexts ('comic book style', 'an illustration of') — a scene
            # where the character is literally drawing at her desk keeps
            # its verbs. Unambiguous medium adjectives strip everywhere.
            _san_pat = _re_san.compile(
                r'\b(animated|anime|cartoon(?:ish|y)?|cel[- ]?shaded|'
                r'illustration\s+(?:of|style)|illustrated\s+style|'
                r'comic\s+book(?:\s+style)?|line\s+drawing|'
                r'2d\s+(?:art|style|animation))\b[ ,]*',
                _re_san.IGNORECASE,
            )
            for _sc in scenes:
                _fp_san = _sc.get('flux_prompt') or ''
                _fp_new = _san_pat.sub('', _fp_san)
                if _fp_new != _fp_san:
                    _sc['flux_prompt'] = _re_san.sub(r'\s{2,}', ' ', _fp_new).strip(' ,')
    except Exception as _exc:
        _zyg_log.warning('animation-word sanitiser failed, flux prompts kept as generated: %s', _exc)

    pipeline_state['script'] = scenes
    pipeline_state['story_title'] = story_title
    n_scenes = len(scenes)
    _log('INFO', 'Stage 2b', f'Story ready: {n_scenes} scenes (all fields populated)')
    _save()

    # ── DSL: persist a Scene DSL per storyteller scene (env-gated) ──
    if _dsl is not None and _dsl.is_enabled('storyteller'):
        try:
            _st_dsl_dir = os.path.join(out_dir, 'dsl')
            for _si_st, _sc_st in enumerate(scenes):
                _scene_obj_st = _dsl.build_scene_from_metadata(
                    {
                        'duration': float(_scene_word_budgets[_si_st]) / 2.5
                        if _si_st < len(_scene_word_budgets)
                        else 15.0,
                        'subject': str(_sc_st.get('visual_concept', ''))[:200],
                        'setting': era_str,
                        'lighting_style': 'warm_accent'
                        if _sc_st.get('emotion') in ('joyful', 'peaceful')
                        else 'cool_blue',
                        'aspect_ratio': '16:9',
                        'composition': str(_sc_st.get('shot_type', '') or ''),
                        'focus_point': str(_sc_st.get('focal_zone', '') or ''),
                        'tags': ['storyteller', visual_style, str(_sc_st.get('emotion', ''))],
                    },
                    pipeline='storyteller',
                    scene_id=f'story_{pipeline_id[:8]}_s{_si_st:02d}',
                    sequence=_si_st,
                )
                _dsl.persist_scene(_scene_obj_st, _st_dsl_dir, filename=f'scene_{_si_st:02d}.yaml')
            _log('INFO', 'Stage 2b', f'DSL: {_dsl.status_summary("storyteller")}')
        except Exception as _dsl_e:
            _log('WARNING', 'Stage 2b', f'DSL hook failed (non-fatal): {_dsl_e}')

    ctx.n_scenes = n_scenes
