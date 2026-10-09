# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Stage 2a Sonnet call, broken into testable pieces.

``stages_02_story_script.stage_02a_sonnet_story`` used to be one 338-line
function: prompt assembly, the streaming call, the JSON parse with its
json-repair fallback, the stock fallback script, and the two rewrite round-trips
that bring the narration inside the requested duration. Everything here was cut
out of it unchanged; the stage function is now the orchestrator that calls these
in the same order.

The pure pieces — prompt assembly, the parses, the budget list, the narration
accounting — are the first part of Stage 2a that can be exercised without an
Anthropic client.
"""

import json

from zyg_workflows.pipeline_config import _caveman_kw
from zyg_workflows.runtime import _record_token_usage
from zyg_workflows.stage_runner import _log_prompt

# How many of the longest/shortest scenes a rewrite round-trip may touch.
_REWRITE_SCENE_LIMIT = 8
# The word budget assumed for a scene the budget list does not cover.
_DEFAULT_SCENE_WORDS = 60


def build_sonnet_prompts(
    char_desc,
    duration_min,
    era_str,
    n_scenes,
    scene_word_budgets,
    story_prompt,
    style_str,
    target_words,
    voice_style,
):
    """The Stage 2a system and user prompt, as ``(system, user)``.

    Takes the scene plan Stage 2 derived (``n_scenes``, ``target_words``,
    ``scene_word_budgets``) plus the character description, style and era, and
    returns the two prompt strings. Only what Sonnet is uniquely good at is
    asked for — narrative voice and story structure; the FLUX-specific fields
    are deferred to Haiku in Stage 2b. The user prompt previews the first eight
    per-scene budgets and names the total when there are more, and
    ``voice_style == 'character'`` adds the first-person narration block in
    which only ``(pause)`` and ``(long pause)`` survive the pre-TTS strip.
    """
    system_prompt = (
        f'You are a professional screenwriter. '
        f'The main character is {char_desc}. '
        f'Write compact, vivid scene entries with STRICT word counts per scene. '
        f'Return only raw JSON — no markdown, no explanation.'
    )
    # Build per-scene word budget string for the prompt
    _budget_preview = ', '.join(str(b) for b in scene_word_budgets[:8])
    if n_scenes > 8:
        _budget_preview += f', … (total {n_scenes} values)'

    # Character voice mode: instruct Claude to write first-person narration.
    # Only (pause) and (long pause) are allowed — all other stage directions
    # (sighs, gasps, exhales, etc.) are stripped before TTS and should NOT appear.
    _char_voice_instruction = ''
    if voice_style == 'character':
        _char_voice_instruction = (
            '\n\nVOICE MODE: CHARACTER (first-person dialogue)\n'
            '- Write narration as the character speaking directly ("I walked in…")\n'
            '- You may use (pause) or (long pause) inside the narration text at '
            'natural breath or beat moments — use sparingly (0–1 per scene)\n'
            '- Do NOT use (sighs), (exhales), (gasps), (chuckles), (inhales), '
            '(coughs), or any other vocal stage directions — they are removed before TTS\n'
            '- Stage directions do NOT count toward the word budget\n'
        )

    user_prompt = (
        f'Write a {duration_min:.0f}-minute {style_str} story called:\n'
        f'"{story_prompt}"\n\n'
        f'Era/Setting: {era_str}\n\n'
        f'STRICT REQUIREMENTS — follow exactly:\n'
        f'- Exactly {n_scenes} scenes\n'
        f'- Total narration: approximately {target_words} words\n'
        f'- Per-scene word budgets (follow closely ±5 words): [{_budget_preview}]\n'
        f'- Each narration must NOT exceed {max(scene_word_budgets) + 10} words\n'
        f'- Clear beginning, middle, and end\n'
        f'{_char_voice_instruction}\n'
        f'Return this JSON structure (no markdown):\n'
        f'{{"title":"...","genre":"...","tone":"...","scenes":['
        f'{{"scene_number":1,'
        f'"narration":"TTS narration matching the word budget for this scene",'
        f'"visual_concept":"one concise sentence: who, what, where",'
        f'"emotion":"calm|tense|joyful|sad|mysterious|dramatic|peaceful"'
        f'}}]}}'
    )
    return system_prompt, user_prompt


def run_sonnet_story_call(
    client,
    system_prompt,
    user_prompt,
    n_scenes,
    duration_min,
    era_str,
    pipeline_id,
    log,
):
    """Make the single Sonnet streaming call that writes the story.

    Logs the prompt under ``claude_story_script``, records the token usage
    against ``pipeline_id`` and logs the response size, then returns the raw
    response text (``''`` when the reply carried no content block). The token
    ceiling is ~100 tokens per scene with a 4096-token floor.
    """
    log('INFO', 'Stage 2a', f'Sonnet: writing {n_scenes}-scene story + narration…')
    _log_prompt(
        'claude_story_script',
        'Stage 2a',
        pipeline_id,
        user_prompt,
        {'n_scenes': n_scenes, 'duration_min': duration_min, 'era': era_str},
    )

    # ~100 tokens/scene for compact schema (narration ~250 chars + visual_concept ~80 chars)
    _s2a_max_tokens = max(4096, n_scenes * 100 + 1024)
    with client.messages.stream(
        model='claude-sonnet-4-6',
        max_tokens=_s2a_max_tokens,
        system=system_prompt,
        messages=[{'role': 'user', 'content': user_prompt}],
    ) as _s2a_stream:
        _s2a_response = _s2a_stream.get_final_message()
    _story_raw = _s2a_response.content[0].text if _s2a_response.content else ''
    _s2a_out_tokens = getattr(_s2a_response.usage, 'output_tokens', '?')
    if getattr(_s2a_response, 'usage', None):
        _record_token_usage(
            model='claude-sonnet-4-6',
            prompt_tokens=_s2a_response.usage.input_tokens,
            completion_tokens=_s2a_response.usage.output_tokens,
            pipeline_id=pipeline_id,
            stage='Stage 2a',
            pipeline_type='storyteller',
            **_caveman_kw('planner'),
        )
    log(
        'INFO',
        'Stage 2a',
        f'Sonnet response: {len(_story_raw)} chars, '
        f'stop_reason={_s2a_response.stop_reason}, '
        f'output_tokens={_s2a_out_tokens}',
    )
    return _story_raw


def parse_story_scenes(story_raw, re_mod, default_title, log):
    """Sonnet's reply as ``(scenes, title)``.

    The first ``{...}`` block of ``story_raw`` is parsed; json-repair is tried
    when ``json.loads`` refuses, and a reply nothing can read yields
    ``([], default_title)`` so the caller falls back to :func:`fallback_scenes`.
    ``re_mod`` is the ``re`` module, passed in so the stage keeps the single
    import it hands on to later stages.
    """
    scenes = []
    story_title = default_title
    try:
        _jm = re_mod.search(r'\{.*\}', story_raw, re_mod.DOTALL)
        if _jm:
            _json_block = _jm.group(0)
            try:
                _parsed = json.loads(_json_block)
            except json.JSONDecodeError as _jex1:
                log('WARNING', 'Stage 2a', f'json.loads failed ({_jex1}) — trying json-repair…')
                try:
                    from json_repair import repair_json as _repair_json

                    _parsed = json.loads(_repair_json(_json_block))
                    log('INFO', 'Stage 2a', 'json-repair recovered the response ✓')
                except Exception as _jex2:
                    log('WARNING', 'Stage 2a', f'json-repair also failed ({_jex2}) — building fallback scenes')
                    _parsed = {}
            scenes = _parsed.get('scenes', [])
            story_title = _parsed.get('title', story_title)
            if scenes:
                log('INFO', 'Stage 2a', f'Script parsed: {len(scenes)} scenes, title: "{story_title}"')
    except (json.JSONDecodeError, AttributeError) as _jex:
        log('WARNING', 'Stage 2a', f'JSON parse failed ({_jex}) — building fallback scenes')
    return scenes, story_title


def fallback_scenes(n_scenes, char_desc, era_str, trigger_token):
    """The stock script used when Sonnet's reply could not be parsed.

    Builds ``n_scenes`` varied scenes that cycle through shot types, emotions,
    locations and actions, with a narration drawn from a ten-beat arc indexed by
    the scene's position in the story, so an unparseable reply still yields a
    renderable and non-repetitive script. Unlike a parsed scene these carry
    ``flux_prompt``, ``shot_type`` and ``focal_zone`` already, because Stage 2b
    has nothing better to derive them from.
    """
    _fb_shot_cycle = ['wide', 'medium', 'close-up', 'establishing', 'medium', 'wide', 'over-the-shoulder']
    _fb_emotion_cycle = ['calm', 'tense', 'joyful', 'mysterious', 'dramatic', 'peaceful', 'sad']
    _fb_location_cycle = [
        'in a sunlit room',
        'outside in a park',
        'on a busy city street',
        'in a quiet café',
        'at home',
        'in a forest',
        'on a rooftop at sunset',
    ]
    _fb_action_cycle = [
        'thinking deeply',
        'looking out the window',
        'walking slowly',
        'sitting quietly',
        'standing still',
        'gazing at the horizon',
        'reflecting',
    ]
    _fb_narration_arcs = [
        'The story begins as {char} finds themselves alone with their thoughts, the world quiet around them.',
        'A moment of reflection washes over {char} as familiar memories surface, each one carrying its own weight.',
        'The day unfolds around {char}, ordinary in its details yet full of unspoken feeling.',
        'Time seems to slow as {char} considers the small moments that shape a life.',
        'There is a particular kind of solitude {char} knows well — not lonely, but full of quiet conversation with oneself.',
        'The world outside continues its pace, but for {char}, there is only this moment.',
        'Something shifts. A small thought grows louder, insisting on being heard.',
        'The weight of the day settles around {char}, familiar and yet somehow new.',
        'In the space between one breath and the next, {char} finds a kind of peace.',
        'The story draws toward its end, leaving {char} standing in the same world, yet changed.',
    ]
    scenes = []
    for _si in range(n_scenes):
        _arc_pct = _si / max(n_scenes - 1, 1)
        _arc_idx = min(int(_arc_pct * len(_fb_narration_arcs)), len(_fb_narration_arcs) - 1)
        _shot = _fb_shot_cycle[_si % len(_fb_shot_cycle)]
        _emotion = _fb_emotion_cycle[_si % len(_fb_emotion_cycle)]
        _location = _fb_location_cycle[_si % len(_fb_location_cycle)]
        _action = _fb_action_cycle[_si % len(_fb_action_cycle)]
        _narration = _fb_narration_arcs[_arc_idx].format(char=char_desc)
        scenes.append(
            {
                'scene_number': _si + 1,
                'narration': _narration,
                'visual_concept': f'{char_desc} {_action} {_location}',
                'emotion': _emotion,
                'flux_prompt': (
                    f'{trigger_token} {char_desc} {_action} {_location}, {era_str}, {_emotion}, cinematic lighting'
                ),
                'shot_type': _shot,
                'focal_zone': ['center', 'left', 'right'][_si % 3],
            }
        )
    return scenes


def narration_word_count(scenes):
    """Total whitespace-separated words across every scene's narration.

    This is the number the duration prediction divides by the words-per-minute
    rate, so a scene without a ``narration`` key counts as zero rather than
    raising.
    """
    return sum(len(s.get('narration', '').split()) for s in scenes)


def scene_budget_list(scenes, scene_word_budgets, longest_first):
    """The scenes a rewrite round-trip should touch, with their word budgets.

    Picks at most eight scenes that have a narration — the longest ones when
    ``longest_first`` (trimming), the shortest ones otherwise (expanding) — and
    returns ``[{'scene_number', 'narration', 'target_words'}]``. A scene whose
    index is past the end of ``scene_word_budgets`` gets the default budget.
    """
    picked = sorted(
        [(i, s) for i, s in enumerate(scenes) if s.get('narration')],
        key=lambda x: len(x[1]['narration'].split()),
        reverse=bool(longest_first),
    )[:_REWRITE_SCENE_LIMIT]
    return [
        {
            'scene_number': s['scene_number'],
            'narration': s['narration'],
            'target_words': scene_word_budgets[i] if i < len(scene_word_budgets) else _DEFAULT_SCENE_WORDS,
        }
        for i, s in picked
    ]


def parse_rewrite_array(raw, re_mod):
    """The ``[{"scene_number":N,"narration":"…"}]`` array out of a rewrite reply.

    Returns the parsed list, or ``None`` when the reply held no JSON array at
    all — which the caller reports as "keeping original". json-repair is tried
    when ``json.loads`` refuses the array it did find.
    """
    jm = re_mod.search(r'\[.*\]', raw, re_mod.DOTALL)
    if not jm:
        return None
    try:
        return json.loads(jm.group(0))
    except json.JSONDecodeError:
        from json_repair import repair_json as _repair_json

        return json.loads(_repair_json(jm.group(0)))


def apply_rewritten_narrations(scenes, rewritten, want_shorter):
    """Fold a rewrite reply back into ``scenes`` in place; return how many changed.

    ``rewritten`` is the ``[{scene_number, narration}]`` array. A replacement is
    taken only when it moved the right way — strictly fewer words when
    ``want_shorter``, strictly more otherwise — so a model that ignored the
    instruction cannot make the script worse.
    """
    by_scene = {item['scene_number']: item['narration'] for item in rewritten}
    updated = 0
    for _sc in scenes:
        _new_nar = by_scene.get(_sc['scene_number'])
        if not _new_nar:
            continue
        _was = len(_sc.get('narration', '').split())
        _now = len(_new_nar.split())
        if (_now < _was) if want_shorter else (_now > _was):
            _sc['narration'] = _new_nar
            updated += 1
    return updated


def trim_long_scenes(
    scenes,
    client,
    re_mod,
    actual_words,
    target_words,
    duration_min,
    era_str,
    scene_word_budgets,
    wpm,
    log,
):
    """Ask Sonnet to shorten the eight longest narrations, in place.

    Mutates ``scenes`` and logs the before/after word counts and the new
    predicted duration. A reply with no JSON array is logged and the original
    narrations are kept. Whatever the API call raises is propagated — the stage
    function logs it and keeps the untrimmed script.
    """
    _trim_list = scene_budget_list(scenes, scene_word_budgets, longest_first=True)
    _trim_prompt = (
        f'The narration is {actual_words} words but should be ~{target_words} words '
        f'({duration_min:.0f} minutes). '
        f'Shorten only the scenes listed below by removing filler phrases, '
        f'redundant description, and slow passages while keeping the story coherent. '
        f'Match the existing tone and era ({era_str}). '
        f'Do NOT remove scenes — only shorten these {len(_trim_list)} scenes. '
        f'Return a JSON array: [{{"scene_number":N,"narration":"..."}}]. '
        f'No markdown.\n\nScenes to shorten:\n{json.dumps(_trim_list)}'
    )
    with client.messages.stream(
        model='claude-sonnet-4-5',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': _trim_prompt}],
    ) as _trim_stream:
        _trim_resp = _trim_stream.get_final_message()
    _trim_raw = _trim_resp.content[0].text if _trim_resp.content else ''
    _trim_parsed = parse_rewrite_array(_trim_raw, re_mod)
    if _trim_parsed is None:
        log('WARNING', 'Stage 2a', 'Claude trim response had no JSON — keeping original')
        return
    _updated_trim = apply_rewritten_narrations(scenes, _trim_parsed, want_shorter=True)
    _trim_total = narration_word_count(scenes)
    log(
        'INFO',
        'Stage 2a',
        f'Claude trimmed {_updated_trim} scenes: {actual_words} → {_trim_total} words '
        f'(predicted {_trim_total / wpm:.1f} min)',
    )


def expand_short_scenes(
    scenes,
    client,
    re_mod,
    target_words,
    duration_min,
    era_str,
    scene_word_budgets,
    wpm,
    log,
):
    """Ask Sonnet to lengthen the eight shortest narrations, in place.

    Mutates ``scenes`` and logs the before/after word counts and the new
    predicted duration. Whatever the API call raises is propagated — the stage
    function logs it and proceeds with the shorter script.
    """
    _expand_list = scene_budget_list(scenes, scene_word_budgets, longest_first=False)
    _words_short = narration_word_count(scenes)
    _expand_prompt = (
        f'The narration is {_words_short} words but should be ~{target_words} words '
        f'({duration_min:.0f} minutes). '
        f'Expand only the scenes listed below by adding more descriptive detail, '
        f'atmosphere, and character reflection. '
        f'Match the existing tone and era ({era_str}). '
        f'Do NOT add new scenes — only lengthen these {len(_expand_list)} scenes. '
        f'Return a JSON array: [{{"scene_number":N,"narration":"..."}}]. '
        f'No markdown.\n\nScenes to expand:\n{json.dumps(_expand_list)}'
    )
    with client.messages.stream(
        model='claude-sonnet-4-5',
        max_tokens=3000,
        messages=[{'role': 'user', 'content': _expand_prompt}],
    ) as _exp_stream:
        _exp_resp = _exp_stream.get_final_message()
    _exp_raw = _exp_resp.content[0].text if _exp_resp.content else ''
    _exp_parsed = parse_rewrite_array(_exp_raw, re_mod)
    if _exp_parsed is None:
        return
    _updated = apply_rewritten_narrations(scenes, _exp_parsed, want_shorter=False)
    _exp_total = narration_word_count(scenes)
    log(
        'INFO',
        'Stage 2a',
        f'Expansion updated {_updated} scenes: {_words_short} → {_exp_total} words '
        f'(predicted {_exp_total / wpm:.1f} min)',
    )
