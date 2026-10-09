# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3 helpers: prompt assembly and the Haiku/Claude/GPT/Ollama script chain.

Extracted from ``_crime_stage_3_script`` (606 lines) so each link of the chain can be
exercised on its own. Nothing here changes behaviour: the prompts, the log lines, the
token accounting and the order in which the providers are tried are the originals.
"""

from .constants import (
    OLLAMA_AVAILABLE,
    Ollama,
    _LARGE_MODEL_THRESHOLD_GB,
    _MODEL_VRAM_GB,
    _caveman_kw,
    _dsl,
    _large_llm_semaphore,
    _log_prompt,
    _ollama_semaphore,
    _register_prompt,
    _runtime,
    _wait_for_vram,
    _wait_ollama_unload,
    json,
    os,
    paths,
    requests,
    safe_urlopen,
    topic,
)

# qwen3.6:35b-a3b first (2026-08-09 swap; the old llama3:70b measurement
# 'reliably hits 1300+ words' must be re-validated on the new chain —
# first run logs the word count below). gpt-oss:20b is the light fallback.
# qwen2.5:72b excluded — at 47.4 GB it fills the 4090 and trips the hw_monitor block
_OLLAMA_MODELS = ['qwen3.6:35b-a3b', 'gpt-oss:20b']
_MIN_WORDS = 1300  # hard floor; pipeline needs ≥1232 for 8.5 min TTS

# Strip common LLM preamble phrases that appear before the actual narration
_PREAMBLE_PATTERNS = [
    r'^here\s+is\s+(the\s+)?(expanded|full|complete|narration|documentary).*?(?:script|narration)[:\s]*\n?',
    r'^(expanded|full|complete)\s+(narration\s+)?script[:\s]*\n?',
    r'^certainly[!,.].*?\n',
    r'^sure[!,.].*?\n',
    r'^of\s+course[!,.].*?\n',
    r'^i\'ve\s+(expanded|written|created).*?\n',
    r'^\[note:.*?\]\s*\n?',
    r'^note:.*?\n',
    r'^\*{1,3}.*?\*{1,3}\s*\n?',  # **Note:** etc.
    r'^script\s*:\s*',  # "Script: ..." prefix
    r'^narration\s*:\s*',  # "Narration: ..." prefix
    r'^episode\s*:\s*',  # "Episode: ..." prefix
    r'^title\s*:.*?\n',  # "Title: ..." line
]


def _strip_llm_preamble(text: str) -> str:
    """Return ``text`` with the usual assistant preamble lines removed.

    In: whatever an LLM returned. Out: the same text stripped of meta-commentary
    openers ('Here is the full script:', '**Note:** …', 'Title: …') and of
    surrounding whitespace.
    """
    import re as _re_s

    # Remove lines that are meta-commentary, not narration
    _preamble_patterns = _PREAMBLE_PATTERNS
    result = text.strip()
    for pat in _preamble_patterns:
        result = _re_s.sub(pat, '', result, flags=_re_s.IGNORECASE | _re_s.MULTILINE)
    return result.strip()


def _build_haiku_prefill_prompt(selected: dict) -> str:
    """Return the seven-question research prompt sent to Haiku for a thin case.

    In: the selected case dict (``name``, ``crime_category``, ``year``).
    Out: the prompt text, already wrapped by the DSL user-planner when the DSL is on.
    """
    _hk_prompt = (
        f'You are a documentary research analyst. Based on what is commonly known about '
        f'"{selected.get("name", "this subject")}" ({selected.get("crime_category", "crime")} case, '
        f'{selected.get("year", "")}), answer these questions briefly and factually:\n\n'
        f'1. Who is this person? What are their defining characteristics?\n'
        f'2. What was their background and upbringing?\n'
        f'3. What motivated their actions?\n'
        f'4. What was the community impact and public reaction?\n'
        f'5. What controversies or legal debates surrounded the case?\n'
        f'6. What legacy or societal impact did this case leave?\n'
        f'7. What philosophical or moral questions does this case raise?\n\n'
        f'Be factual and concise. 300-400 words total. No preamble.'
    )
    if _dsl is not None:
        _hk_prompt = _dsl.wrap_user_planner(_hk_prompt, 'crime')
    return _hk_prompt


def _run_haiku_prefill(selected: dict, court_text: str, pipeline_id: str, _log) -> str:
    """Enrich thin case facts with a Haiku research supplement.

    In: the case dict, the court text, the pipeline id and the stage logger.
    Out: the prefill text, or '' when no API key is set, the source is already
    rich (≥400 words), or the call failed (non-fatal, logged as a warning).
    """
    _haiku_prefill = ''
    _anthropic_key_pre = os.environ.get('ANTHROPIC_API_KEY', '')
    if not (_anthropic_key_pre and len(court_text.split()) < 400):
        return _haiku_prefill
    # Only run Haiku prefill when source material is thin (< 400 words)
    try:
        import anthropic as _anth_pre

        _hk_client = _anth_pre.Anthropic(api_key=_anthropic_key_pre)
        _hk_prompt = _build_haiku_prefill_prompt(selected)
        _log_prompt(
            'haiku_prefill',
            'Stage 3',
            pipeline_id,
            _hk_prompt,
            meta={'pipeline_type': 'crime', 'subject': selected.get('name', '')},
            direction='sent',
            role='user',
            llm='claude-haiku-4-5',
            from_who='system',
            to_who='claude-haiku-4-5',
        )
        _hk_resp = _hk_client.messages.create(
            model='claude-haiku-4-5',
            max_tokens=600,
            temperature=0.3,
            messages=[{'role': 'user', 'content': _hk_prompt}],
        )
        _haiku_prefill = _hk_resp.content[0].text.strip()
        if getattr(_hk_resp, 'usage', None):
            _runtime.record_token_usage(
                model='claude-haiku-4-5',
                prompt_tokens=_hk_resp.usage.input_tokens,
                completion_tokens=_hk_resp.usage.output_tokens,
                pipeline_id=pipeline_id,
                stage='Stage 3 prefill',
                pipeline_type='crime',
                **_caveman_kw('user_planner'),
            )
        _log_prompt(
            'haiku_prefill',
            'Stage 3',
            pipeline_id,
            _haiku_prefill,
            meta={'pipeline_type': 'crime', 'subject': selected.get('name', '')},
            direction='received',
            role='assistant',
            llm='claude-haiku-4-5',
            from_who='claude-haiku-4-5',
            to_who='system',
        )
        _log('INFO', 'Stage 3', f'Haiku prefill: {len(_haiku_prefill.split())} words added')
    except Exception as _hk_e:
        _log('WARNING', 'Stage 3', f'Haiku prefill failed (non-fatal): {_hk_e}')
        _haiku_prefill = ''
    return _haiku_prefill


def _build_enriched_source(haiku_prefill: str, court_text: str) -> str:
    """Return the case-facts block the script prompt quotes.

    In: the Haiku prefill (possibly '') and the court text. Out: the court text
    alone, or the prefill labelled 'ENRICHED CONTEXT' ahead of it.
    """
    # Build enriched source block: prefill (if any) + original court_text
    if haiku_prefill:
        return (
            f'ENRICHED CONTEXT (AI research supplement):\n{haiku_prefill}\n\n--- PRIMARY CASE FACTS ---\n{court_text}'
        )
    return court_text


def _build_script_prompt(framework_block: str, enriched_source: str, selected: dict) -> str:
    """Return the full narration-script prompt for this case.

    In: the documentary framework block, the enriched case facts and the case
    dict. Out: the instruction template with the ten sections, the banned-word
    rule and the case metadata appended.
    """
    return (
        'You are a calm, authoritative documentary narrator for a true crime channel called Crime Chronicles.\n'
        'Write a narration script for an episode about the following court case.\n\n'
        'STRICT RULES:\n'
        '- Base your script on the facts provided, but you MAY expand with well-known historical context, '
        'societal impact, investigative background, and courtroom atmosphere to reach the required length.\n'
        '- Write in present tense, documentary style. Be factual and measured.\n'
        '- Be respectful to victims and their families.\n'
        '- MINIMUM 1400 words. Target: 1400 to 2000 words (approximately 9.5 to 14 minutes when spoken aloud).\n'
        '- You MUST write at least 1400 words.\n'
        '- Structure your narration across these sections:\n'
        '  1. INTRODUCTION — who, when, where. A cinematic hook that draws the viewer in.\n'
        '  2. BACKGROUND — early life, circumstances, and context that explain how this came to be.\n'
        '  3. THE EVENTS — what happened, in vivid documentary detail.\n'
        '  4. THE INVESTIGATION — how authorities uncovered the truth, forensic and human elements.\n'
        '  5. THE ARREST — the moment of capture, dramatic and factual.\n'
        '  6. THE TRIAL — key arguments, evidence, atmosphere in the courtroom.\n'
        '  7. VERDICT AND SENTENCING — the outcome and immediate reaction.\n'
        '  8. HUMAN IMPACT — how this affected victims, families, and the community.\n'
        '  9. LEGACY AND SOCIETAL IMPACT — what changed in law, policy, or public consciousness.\n'
        ' 10. PHILOSOPHICAL REFLECTION — what this case reveals about human nature and society.\n'
        '- Avoid words: kill, murder, shoot, stab, rape, abuse. '
        "Use neutral terms: 'fatally attacked', 'fired a weapon', 'the assault', 'the offense', 'the act'.\n"
        '- Start immediately with the narration. No preamble, no headings, no word count note.\n\n'
        f'{framework_block}\n'
        f'CASE FACTS:\n{enriched_source}\n\n'
        f'SUBJECT: {selected.get("name", "")}\n'
        f'CRIME CATEGORY: {selected.get("crime_category", "")}\n'
        f'YEAR: {selected.get("year", "")}\n\n'
        'Write the full narration script now (minimum 1400 words):'
    )


# Register the stable instruction template (without dynamic case facts)
_CRIME_NARR_TEMPLATE = (
    'You are a calm, authoritative documentary narrator for a true crime channel called Crime Chronicles.\n'
    'Write a narration script for an episode about the following court case.\n\n'
    'STRICT RULES:\n'
    '- Base your script on the facts provided, but you MAY expand with well-known historical context, '
    'societal impact, investigative background, and courtroom atmosphere to reach the required length.\n'
    '- Write in present tense, documentary style. Be factual and measured.\n'
    '- Be respectful to victims and their families.\n'
    '- MINIMUM 1400 words. Target: 1400 to 2000 words (approximately 9.5 to 14 minutes when spoken aloud).\n'
    '- You MUST write at least 1400 words.\n'
    '- Structure your narration across these 10 sections:\n'
    '  1. INTRODUCTION — cinematic hook, who/when/where.\n'
    '  2. BACKGROUND — early life, context, circumstances.\n'
    '  3. THE EVENTS — what happened, vivid documentary detail.\n'
    '  4. THE INVESTIGATION — how authorities uncovered the truth.\n'
    '  5. THE ARREST — the moment of capture.\n'
    '  6. THE TRIAL — arguments, evidence, courtroom atmosphere.\n'
    '  7. VERDICT AND SENTENCING — outcome and reaction.\n'
    '  8. HUMAN IMPACT — victims, families, community.\n'
    '  9. LEGACY AND SOCIETAL IMPACT — what changed in law and public consciousness.\n'
    ' 10. PHILOSOPHICAL REFLECTION — what this reveals about human nature.\n'
    '- Avoid words: kill, murder, shoot, stab, rape, abuse. '
    "Use neutral terms: 'fatally attacked', 'fired a weapon', 'the assault', 'the offense', 'the act'.\n"
    '- Start immediately with the narration. No preamble, no headings, no word count note.\n\n'
    '[DOCUMENTARY FRAMEWORK BLOCK + CASE FACTS + SUBJECT + CRIME CATEGORY + YEAR — injected at runtime]\n\n'
    'Write the full narration script now (minimum 1400 words):'
)


def _register_narration_template(pipeline_id: str) -> None:
    """Register the stable 'narration_crime' prompt template for this run.

    In: the pipeline id. Out: nothing — the template is filed in the prompt
    registry so the GUI can show it without the dynamic case facts.
    """
    _register_prompt(
        'narration_crime',
        'Crime Narration Script',
        'Generates a true crime documentary narration script (1400–2000 words, documentary style)',
        _CRIME_NARR_TEMPLATE,
        pipeline_id=pipeline_id,
        stage='Stage 3',
        topic='crime',
    )


def _try_claude_script(script_prompt: str, pipeline_id: str, _log) -> str:
    """Ask Claude Sonnet for the narration script (first priority, no VRAM cost).

    In: the script prompt, the pipeline id and the stage logger. Out: the
    stripped script when it is at least 200 words, else '' (no key, too short,
    or a logged failure).
    """
    # Try Claude Sonnet (first priority — best quality, no VRAM cost)
    _out = ''
    _anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not _anthropic_key:
        return _out
    try:
        import anthropic as _anthropic_sdk

        _claude_client = _anthropic_sdk.Anthropic(api_key=_anthropic_key)
        _log_prompt(
            'claude_script',
            'Stage 3',
            pipeline_id,
            script_prompt,
            meta={'topic': topic, 'pipeline_type': 'crime'},
            direction='sent',
            role='user',
            llm='claude-sonnet-4-6',
            from_who='system',
            to_who='claude-sonnet-4-6',
        )
        with _claude_client.messages.stream(
            model='claude-sonnet-4-6',
            max_tokens=4500,
            temperature=0.4,
            messages=[{'role': 'user', 'content': script_prompt}],
        ) as _st_cr:
            _claude_resp = _st_cr.get_final_message()
        _claude_out = _strip_llm_preamble(_claude_resp.content[0].text.strip())
        _log_prompt(
            'claude_script',
            'Stage 3',
            pipeline_id,
            _claude_out,
            meta={'topic': topic, 'pipeline_type': 'crime', 'words': len(_claude_out.split())},
            direction='received',
            role='assistant',
            llm='claude-sonnet-4-6',
            from_who='claude-sonnet-4-6',
            to_who='system',
        )
        if len(_claude_out.split()) >= 200:
            _out = _claude_out
            _log('INFO', 'Stage 3', f'Claude Sonnet: {len(_out.split())} words')
            _runtime.record_token_usage(
                model='claude-sonnet-4-6',
                prompt_tokens=_claude_resp.usage.input_tokens,
                completion_tokens=_claude_resp.usage.output_tokens,
                pipeline_id=pipeline_id,
                stage='Stage 3',
                pipeline_type='crime',
            )
    except Exception as _ce:
        _log('WARNING', 'Stage 3', f'Claude Sonnet failed: {_ce}')
    return _out


def _try_gpt_script(script_prompt: str, pipeline_id: str, _log) -> str:
    """Ask GPT-4o for the narration script (second priority).

    In: the script prompt, the pipeline id and the stage logger. Out: the
    stripped script, or '' when no key is set, the HTTP status is not 200, or
    the call raised (logged as a warning).
    """
    # Try GPT-4o
    _out = ''
    _gpt_key = os.environ.get('OPENAI_API_KEY', '')
    if not _gpt_key:
        return _out
    try:
        _log_prompt(
            'gpt_script',
            'Stage 3',
            pipeline_id,
            script_prompt,
            meta={'topic': topic, 'pipeline_type': 'crime'},
            direction='sent',
            role='user',
            llm='gpt-4o',
            from_who='system',
            to_who='gpt-4o',
        )
        _gpt_r = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Authorization': f'Bearer {_gpt_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'gpt-4o',
                'messages': [{'role': 'user', 'content': script_prompt}],
                'max_tokens': 4500,
                'temperature': 0.4,
            },
            timeout=60,
        )
        if _gpt_r.status_code == 200:
            _gpt_rj = _gpt_r.json()
            _out = _strip_llm_preamble(_gpt_rj['choices'][0]['message']['content'].strip())
            _log_prompt(
                'gpt_script',
                'Stage 3',
                pipeline_id,
                _out,
                meta={'topic': topic, 'pipeline_type': 'crime', 'words': len(_out.split())},
                direction='received',
                role='assistant',
                llm='gpt-4o',
                from_who='gpt-4o',
                to_who='system',
            )
            _log('INFO', 'Stage 3', f'GPT-4o: {len(_out.split())} words')
            _gpt_u = _gpt_rj.get('usage', {})
            if _gpt_u:
                _runtime.record_token_usage(
                    model='gpt-4o',
                    prompt_tokens=_gpt_u.get('prompt_tokens', 0),
                    completion_tokens=_gpt_u.get('completion_tokens', 0),
                    pipeline_id=pipeline_id,
                    stage='Stage 3',
                    pipeline_type='crime',
                )
    except Exception as _ge:
        _log('WARNING', 'Stage 3', f'GPT-4o failed: {_ge}')
    return _out


def _evict_ollama_model(model_name: str, _log) -> None:
    """Tell Ollama to immediately unload a model from VRAM (keep_alive=0)
    and then poll until the model is confirmed absent from /api/ps.
    This prevents the previous model sitting in VRAM for 5 min while the
    next (larger) model tries to load and hits a VRAM timeout."""
    try:
        _payload = json.dumps({'model': model_name, 'prompt': ' ', 'keep_alive': 0, 'stream': False}).encode()
        safe_urlopen(paths.ZYG_OLLAMA_URL + '/api/generate', data=_payload, timeout=10).read()
        _log('INFO', 'Stage 3', f'Evicted {model_name} from VRAM')
    except Exception as _ev_err:
        _log('WARNING', 'Stage 3', f'Evict {model_name} failed (non-fatal): {_ev_err}')
    # Confirm eviction before returning so callers don't race to load next model
    _wait_ollama_unload(model_name, timeout=30)


def _build_expansion_prompt(script: str, word_count: int, min_words: int) -> str:
    """Return the prompt that asks a local model to lengthen a short script.

    In: the script so far, its word count and the floor to reach. Out: the
    expansion instruction, asking for ``min_words - word_count + 200`` more
    words and the original text echoed back.
    """
    _still_need = min_words - word_count + 200  # ask for a bit more than minimum
    return (
        f'The following narration script needs to be longer. '
        f'Add approximately {_still_need} more words by expanding on: '
        f'the historical context of the era, forensic investigation details, '
        f'courtroom atmosphere, key witness testimony, community reaction, '
        f'the broader legal impact, and a reflective closing. '
        f'Output ONLY the full combined narration — include the original text plus your additions. '
        f'No preamble, no headings, no commentary. Minimum {min_words} words total.\n\n'
        f'EXISTING SCRIPT:\n{script}\n\nCONTINUE AND EXPAND:'
    )


def _llm_text(resp) -> str:
    """Return the plain text of an Ollama/LiteLLM response.

    In: whatever ``LLM.call`` returned. Out: the string itself, its ``content``
    attribute, or ``str(resp)`` as the last resort.
    """
    return resp if isinstance(resp, str) else getattr(resp, 'content', str(resp))


def _expand_to_min_words(_llm, script: str, word_count: int, model_name: str, min_words: int, _log):
    """Ask the model up to three times to grow a short script past the floor.

    In: the live LLM, the script and its word count, the model name for the log
    lines, the word floor and the stage logger. Out: ``(script, word_count)`` —
    the longest version seen; a round that comes back shorter is discarded.
    """
    _resp_str, _wc = script, word_count
    # Expand up to 3 rounds until we reach min_words
    for _round in range(3):
        if _wc >= min_words:
            break
        _log(
            'WARNING',
            'Stage 3',
            f'Ollama ({model_name}): only {_wc} words — requesting expansion (round {_round + 1})',
        )
        _expand_prompt = _build_expansion_prompt(_resp_str, _wc, min_words)
        _resp2_str = _strip_llm_preamble(_llm_text(_llm.call([{'role': 'user', 'content': _expand_prompt}])))
        if len(_resp2_str.split()) > _wc:
            _resp_str = _resp2_str
            _wc = len(_resp_str.split())
    return _resp_str, _wc


def _try_ollama_script(script_prompt: str, _log, min_words: int = _MIN_WORDS):
    """Try the local Ollama models in order until one returns a usable script.

    In: the script prompt, the stage logger and the word floor. Out:
    ``(llm_instance, model_name, script)`` for Stage 3b to reuse, or
    ``(None, None, '')`` when Ollama is absent or every model fell short.
    """
    _stage3_llm_model = None  # remember which model succeeded so Stage 3b reuses it
    _stage3_llm_inst = None  # keep the live Ollama instance for Stage 3b reuse
    narration_script = ''
    if not (OLLAMA_AVAILABLE and Ollama is not None):
        return (_stage3_llm_inst, _stage3_llm_model, narration_script)
    for _m in _OLLAMA_MODELS:
        _m_vram = _MODEL_VRAM_GB.get(_m, 5)
        _is_large = _m_vram >= _LARGE_MODEL_THRESHOLD_GB
        _sem = _large_llm_semaphore if _is_large else _ollama_semaphore
        try:
            with _sem:
                # Wait for VRAM headroom before loading a large model
                if _is_large:
                    _headroom = _m_vram + 4  # model + 4 GB OS/KV-cache buffer
                    if not _wait_for_vram(_headroom, timeout=180, label=f'Stage 3 {_m}'):
                        _log('WARNING', 'Stage 3', f'Ollama ({_m}): VRAM timeout — skipping')
                        continue
                _llm = Ollama(model=f'ollama/{_m}', base_url=paths.ZYG_OLLAMA_URL, temperature=0.4)
                _resp_str = _strip_llm_preamble(_llm_text(_llm.call([{'role': 'user', 'content': script_prompt}])))
                _wc = len(_resp_str.split())
                _resp_str, _wc = _expand_to_min_words(_llm, _resp_str, _wc, _m, min_words, _log)
                if _wc >= 200:
                    narration_script = _resp_str
                    _stage3_llm_model = _m
                    _stage3_llm_inst = _llm
                    _log('INFO', 'Stage 3', f'Ollama ({_m}): {len(narration_script.split())} words')
                    if _wc >= min_words:
                        break  # good enough — move on
                    # Not long enough but it's something; keep trying other models
                    _log(
                        'WARNING',
                        'Stage 3',
                        f'Ollama ({_m}): still only {_wc} words after expansion — trying next model',
                    )
                    narration_script = ''
                    _stage3_llm_model = None
                    _stage3_llm_inst = None
                    _evict_ollama_model(_m, _log)
        except Exception as _oe:
            _log('WARNING', 'Stage 3', f'Ollama ({_m}) failed: {_oe}')
            _evict_ollama_model(_m, _log)
            continue
    return (_stage3_llm_inst, _stage3_llm_model, narration_script)
