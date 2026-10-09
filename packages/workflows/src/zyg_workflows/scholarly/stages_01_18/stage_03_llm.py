# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Claude scripting call of stage 3 of the scholarly pipeline.

The story-writing pass `stage_03_script_preparation` makes: the prompt it
assembles, the response parser that splits the narration from the
`[VISUAL_SCENES]` and `[YOUTUBE_META]` blocks, the acceptance of a draft and
the follow-up hook rewrite. Extracted from the 680-line stage function
unchanged — same prompt text, same log lines, same order.
"""

import json
import re

from ._common import (
    _LLM_SCRIPT,
    _LLM_SMALL,
    _llm_client,
    _log_prompt,
    _record_token_usage,
    _zyg_log,
)


def _parse_stage3_resp(raw: str):
    """Split narration from [VISUAL_SCENES] and [YOUTUBE_META] blocks.
    Returns (clean_narration_text, scenes_list, yt_meta_dict)."""
    yt_meta = {}
    # Extract [YOUTUBE_META] first (it appears after [/VISUAL_SCENES])
    if '[YOUTUBE_META]' in raw:
        _ym_idx = raw.index('[YOUTUBE_META]')
        _ym_raw = raw[_ym_idx + len('[YOUTUBE_META]') :]
        if '[/YOUTUBE_META]' in _ym_raw:
            _ym_raw = _ym_raw[: _ym_raw.index('[/YOUTUBE_META]')]
        _ym_raw = re.sub(r'```(?:json)?|```', '', _ym_raw).strip()
        try:
            _parsed = json.loads(_ym_raw)
            if isinstance(_parsed, dict):
                yt_meta = _parsed
        except ValueError as _exc:
            _zyg_log.warning('YOUTUBE_META did not parse, the episode ships with no title/description: %s', _exc)
        raw = raw[:_ym_idx].strip()
    if '[VISUAL_SCENES]' in raw:
        _idx = raw.index('[VISUAL_SCENES]')
        _txt = raw[:_idx].strip()
        _vis = raw[_idx + len('[VISUAL_SCENES]') :]
        if '[/VISUAL_SCENES]' in _vis:
            _vis = _vis[: _vis.index('[/VISUAL_SCENES]')]
        _vis = re.sub(r'```(?:json)?|```', '', _vis).strip()
        try:
            _sc = json.loads(_vis)
            return _txt, (_sc if isinstance(_sc, list) else []), yt_meta
        except Exception:
            return _txt, [], yt_meta
    return raw.strip(), [], yt_meta


def _build_script_prompt(ctx, targets, framework):
    """The single user prompt of the Claude scripting call: the rules, the word
    budget, the structure and framework blocks, then the source material."""
    return (
        f'You are a documentary scriptwriter.\n\n'
        f'The user has requested a documentary about: "{ctx.directive or ctx.topic}".\n\n'
        f'Write a compelling narrative documentary of {targets.min_words} to {targets.max_words} words '
        f'(target ~{targets.target_words}) about that topic. Use the source material below as '
        f'research background — incorporate relevant facts and details, but the '
        f'documentary MUST be about what the user requested.\n\n'
        f'RULES:\n'
        f'1. Write in the style of a documentary narration — vivid, '
        f'cinematic, engaging. Use "we" or third person. Active voice.\n'
        f'2. Open with a strong scene-setting hook.\n'
        f'3. Weave in specific facts, names, and details from the source.\n'
        f'4. No citations, footnotes, section headers, or academic language.\n'
        f'5. Write the story text first. No title, no preamble, no commentary.\n'
        f'6. Must be between {targets.min_words} and {targets.max_words} words — count carefully.\n'
        f'7. After the full narration, on a new line write exactly [VISUAL_SCENES] then a\n'
        f'   JSON array — one string per sentence (splitting the narration on .!?) — each\n'
        f'   string a 12-18 word specific visual description of what appears on screen for\n'
        f'   that sentence. End with [/VISUAL_SCENES]. Never use generic phrases.\n'
        f'8. After [/VISUAL_SCENES], write [YOUTUBE_META] then a JSON object with exactly '
        f'five keys: "title" (compelling YouTube title, max 70 chars, hook-driven, no clickbait, '
        f'no "Create A Documentary" phrasing — sound like a real documentary title), '
        f'"description" (3-4 engaging sentences for YouTube audience about what viewers will '
        f'learn and experience), '
        f'"tags" (JSON array of 12-15 topically accurate keyword phrases, lowercase, relevant '
        f'to the documentary — specific subjects, people, places, time periods, themes), '
        f'"language" (ISO 639-1 language code, e.g. "en"), '
        f'"audience" ("general" or "kids" — only "kids" if content is primarily for children). '
        f'End with [/YOUTUBE_META].\n'
        f'9. FACTUAL ACCURACY: All specific dates, statistics, quotes, and named claims '
        f'MUST be grounded in the [VERIFIED SOURCE MATERIAL] below. If a specific detail '
        f'is not present in those sources, use hedged language: "reportedly", '
        f'"historians believe", "approximately", "around". Never invent a date, '
        f'figure, or quotation.\n\n'
        f'{targets.hard_cap_rule}'
        f'{targets.structure_block}\n'
        f'{framework}\n'
        + (f'{ctx._wiki_source_block}\n\n' if ctx._wiki_source_block else '')
        + f'ADDITIONAL SOURCE MATERIAL:\n{ctx.essay_text[:6000]}'
        # 2026-09-20: the prompt used to END on the truncated essay, and Opus 5 on the
        # subscription path then CONTINUED the essay (mid-sentence, 400-900 words of
        # encyclopaedia text, no script) — reproduced 3/3 on the Marconi brain run.
        # Close the excerpt and restate the task after it.
        + '\n[END OF SOURCE MATERIAL — research background only; it may stop mid-sentence; '
        'do not continue or copy it]\n\n'
        + f'Now write the documentary narration about "{ctx.directive or ctx.topic}" exactly as '
        f'instructed above (rules 1-9): begin with the scene-setting hook of section 1, '
        f'{targets.min_words} to {targets.max_words} words, then [VISUAL_SCENES] and [YOUTUBE_META].'
    )


def _accept_script(ctx, claude_out, scenes, claude_resp):
    """Adopt a Claude draft as the narration script: record the model, the token
    usage and the inline scene descriptions Stage 3b reuses."""
    ctx.narration_script = claude_out
    ctx._stage3_llm_model = _LLM_SCRIPT
    ctx._log(
        'INFO',
        'Stage 3',
        f'Claude story writing pass: {len(ctx.narration_script.split())} words'
        + (f', {len(scenes)} inline scene descs' if scenes else ''),
    )
    _record_token_usage(
        model=_LLM_SCRIPT,
        prompt_tokens=claude_resp.usage.input_tokens,
        completion_tokens=claude_resp.usage.output_tokens,
        pipeline_id=ctx.pipeline_id,
        stage='Stage 3',
        pipeline_type='scholarly',
    )
    # Store inline scene descriptions for Stage 3b — eliminates LLM batch calls
    if scenes:
        ctx.pipeline_state['_stage3_scene_list'] = scenes


def _sharpen_hook(ctx, claude_client, yt_meta):
    """Rewrite the opening paragraph with the energy of the YouTube description.

    The YouTube description is written after the full arc is known, in pitch
    mode — it naturally produces stronger hooks than the narration opener. This
    call converts that energy into spoken prose. Non-fatal.
    """
    _yt_desc_hook = (yt_meta.get('description') or '').strip()
    if not _yt_desc_hook:
        return
    try:
        _paras = ctx.narration_script.split('\n\n')
        _first_para = _paras[0].strip()
        _rest_narr = '\n\n'.join(_paras[1:]) if len(_paras) > 1 else ''
        _hook_prompt = (
            f'A documentary narrator wrote this opening paragraph:\n\n'
            f'"""\n{_first_para}\n"""\n\n'
            f'The YouTube description for the same documentary is:\n\n'
            f'"""\n{_yt_desc_hook}\n"""\n\n'
            f'The description has the right energy — high contrast, immediate stakes, '
            f'subverts expectations, no scene-setting throat-clearing. '
            f'Rewrite ONLY the opening paragraph to match that energy as SPOKEN narration.\n'
            f'Rules:\n'
            f'- No meta language ("This documentary explores..." is wrong — speak directly)\n'
            f'- Keep the same approximate length as the original opening paragraph\n'
            f'- Lead with the most dramatic truth; flip the biggest assumption first\n'
            f'- Output only the rewritten paragraph — no preamble, no commentary\n'
        )
        _hook_resp = claude_client.messages.create(
            model=_LLM_SMALL,
            max_tokens=400,
            temperature=0.7,
            messages=[{'role': 'user', 'content': _hook_prompt}],
        )
        _new_opening = _hook_resp.content[0].text.strip()
        if _new_opening and len(_new_opening.split()) >= 20:
            ctx.narration_script = _new_opening + ('\n\n' + _rest_narr if _rest_narr else '')
            ctx._log(
                'INFO',
                'Stage 3',
                f'Hook rewrite: opening sharpened ({len(_new_opening.split())} words)',
            )
            _record_token_usage(
                model=_LLM_SMALL,
                prompt_tokens=_hook_resp.usage.input_tokens,
                completion_tokens=_hook_resp.usage.output_tokens,
                pipeline_id=ctx.pipeline_id,
                stage='Stage 3 hook',
                pipeline_type='scholarly',
            )
    except Exception as _hook_e:
        ctx._log('WARNING', 'Stage 3', f'Hook rewrite skipped (non-fatal): {_hook_e}')


def _run_claude_script_pass(ctx, targets, framework, strip_llm_preamble):
    """The Claude Sonnet story-writing pass — first priority: best quality, it
    handles large essays fine and costs no VRAM.

    Sets `ctx.narration_script` and `ctx._stage3_llm_model` when the draft
    clears `targets.accept_words`; returns the [YOUTUBE_META] dict (empty when
    the response carried none or the call failed).
    """
    _yt_meta = {}
    try:
        _claude_client = _llm_client(ctx._anthropic_key)
        _sch_prompt_1 = _build_script_prompt(ctx, targets, framework)
        # Extra tokens for [VISUAL_SCENES] section (~1 sentence worth of output per
        # narration sentence; a 1200-word script ≈ 80 sentences → ~1200 extra tokens).
        # Scale token budget to word count: ~1.3 tokens/word narration +
        # ~2.2 tokens/word for [VISUAL_SCENES] block (≈10 words/sentence).
        # Ensures visual scenes are never cut off regardless of duration cap.
        _claude_max_tokens = min(8000, max(2500, int(targets.max_words * 3.5) + 600))
        _log_prompt(
            'claude_script',
            'Stage 3',
            ctx.pipeline_id,
            _sch_prompt_1,
            meta={'topic': ctx.topic, 'pipeline_type': 'scholarly', 'attempt': 1},
            direction='sent',
            role='user',
            llm=_LLM_SCRIPT,
            from_who='system',
            to_who=_LLM_SCRIPT,
        )
        with _claude_client.messages.stream(
            model=_LLM_SCRIPT,
            max_tokens=_claude_max_tokens,
            temperature=0.7,
            messages=[{'role': 'user', 'content': _sch_prompt_1}],
        ) as _st_s1:
            _claude_resp = _st_s1.get_final_message()
        _claude_raw_a1 = _claude_resp.content[0].text.strip()
        _claude_out_parsed, _stage3_scenes, _yt_meta = _parse_stage3_resp(_claude_raw_a1)
        _claude_out = strip_llm_preamble(_claude_out_parsed)
        _log_prompt(
            'claude_script',
            'Stage 3',
            ctx.pipeline_id,
            _claude_out,
            meta={
                'topic': ctx.topic,
                'pipeline_type': 'scholarly',
                'attempt': 1,
                'words': len(_claude_out.split()),
                'inline_scenes': len(_stage3_scenes),
            },
            direction='received',
            role='assistant',
            llm=_LLM_SCRIPT,
            from_who=_LLM_SCRIPT,
            to_who='system',
        )
        if targets.duration_capped and len(_claude_out.split()) > targets.max_words:
            _claude_out = ' '.join(_claude_out.split()[: targets.max_words])
            ctx._log('WARNING', 'Stage 3', f'Claude exceeded short-doc cap — trimmed to {targets.max_words} words')
        _input_wc = len(ctx.essay_text.split())
        if len(_claude_out.split()) >= targets.accept_words:
            _accept_script(ctx, _claude_out, _stage3_scenes, _claude_resp)
            _sharpen_hook(ctx, _claude_client, _yt_meta)
        else:
            ctx._log('WARNING', 'Stage 3', 'Claude output too short after all attempts — falling back')
    except Exception as _ce:
        ctx._log('WARNING', 'Stage 3', f'Claude Sonnet failed: {_ce}')
    return _yt_meta
