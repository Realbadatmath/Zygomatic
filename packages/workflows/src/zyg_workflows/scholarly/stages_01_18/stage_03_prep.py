# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The steps of stage 3 of the scholarly pipeline (the script-preparation pass).

`stage_03_script_preparation` used to be one 680-line function. The steps it
runs, in the order it ran them — essay metadata, the duration targets, the
topic reject, the Wikipedia RAG fetch, the narration clean-ups, the
publishable-prose gate and the final pipeline-state write — live here as
helpers with explicit parameters, so each one can be exercised on its own.
The Claude scripting call itself is in `stage_03_llm.py`; `stage_03.py` keeps
only their call order.

Nothing below changes behaviour: every log line, every raised message and
every side effect is the one the stage had, in the same sequence.
"""

import os
import re
import time
from dataclasses import dataclass

import requests

from ._common import (
    _SCHOLARLY_SEC_PER_WORD,
    _bench_replay_get,
    _dsl,
    _register_prompt,
    _research_title_matches_directive,
    _title_from_directive,
)

_10_SECTION_STRUCTURE = (
    'Structure your narration across exactly these 10 sections (flow seamlessly — '
    'no visible headers in the output):\n'
    '  1. INTRODUCTION & OVERVIEW — cinematic hook, establish what this is and why it matters.\n'
    '  2. ORIGINS & HISTORICAL BACKGROUND — where it came from, what conditions created it, '
    'what existed before.\n'
    '  3. HOW IT WORKS / FUNCTIONS — the mechanism, the hidden processes, what most people '
    'never see.\n'
    '  4. IMPORTANT PEOPLE INVOLVED — key figures, their roles, motivations, contradictions.\n'
    '  5. MAJOR CONFLICTS & CONTROVERSIES — the struggles, battles, scandals, dangers, '
    'power clashes.\n'
    '  6. HUMAN IMPACT & EMOTIONAL STORIES — how ordinary people were affected, personal '
    'stories, suffering and triumph.\n'
    '  7. HIDDEN FACTS & LESSER KNOWN DETAILS — surprising truths, secrets, '
    'things most people never hear.\n'
    '  8. PHILOSOPHICAL MEANING & DEEPER IMPLICATIONS — what this reveals about humanity, '
    'moral questions, patterns.\n'
    '  9. PRESENT DAY RELEVANCE — what is happening now, how this still shapes the world.\n'
    ' 10. FUTURE POSSIBILITIES — where this is heading, what might change, what lessons apply.\n'
)
_SHORT_DOC_STRUCTURE = (
    'Structure as a tight short documentary (3–4 beats only — NOT a 10-part series):\n'
    '  1. Hook + what this is (2–3 sentences).\n'
    '  2. Core mechanism or key insight (main body, stay brief).\n'
    '  3. Human stakes or consequence (1–2 sentences).\n'
    '  4. Closing line (1 sentence).\n'
)


@dataclass(frozen=True)
class Stage03Targets:
    """The word-count budget of one stage-3 run and the prompt rules it implies.

    `min_words`/`target_words`/`max_words`/`word_gate` come straight from the
    pipeline's duration targets; `accept_words` is the floor a Claude draft
    must clear to be used, `retry_words` the floor that would trigger a retry,
    and `hard_cap_rule`/`structure_block` are the prompt fragments the cap
    selects.
    """

    min_words: int
    target_words: int
    max_words: int
    word_gate: int
    duration_capped: bool
    retry_words: int
    accept_words: int
    hard_cap_rule: str
    structure_block: str


def _essay_metadata_to_state(ctx):
    """Publish the research result's metadata (images, title, authors) on
    `ctx.pipeline_state` for stage 5 and pick the display title, then save.

    The `'_research_result' in dir()` tests are the stage's own: `dir()` with no
    argument lists the *local* names, and `_research_result` was never a local,
    so each one takes its else branch. Kept verbatim — this helper changes the
    file layout, not the pipeline.
    """
    _essay_title = (
        ctx._research_result.get('title', ctx.topic.title()) if '_research_result' in dir() else ctx.topic.title()
    )
    _essay_authors = ctx._research_result.get('authors', '') if '_research_result' in dir() else ''
    _essay_wc = (
        ctx._research_result.get('word_count', len(ctx.essay_text.split()))
        if '_research_result' in dir()
        else len(ctx.essay_text.split())
    )
    _essay_images = ctx._research_result.get('images', []) if '_research_result' in dir() else []
    _episode_split_flag = (
        ctx._research_result.get('episode_split', False) if '_research_result' in dir() else (_essay_wc > 7000)
    )

    # Store images in pipeline state for Stage 5
    ctx.pipeline_state['essay_images'] = _essay_images
    ctx.pipeline_state['essay_title'] = _essay_title
    ctx.pipeline_state['essay_authors'] = _essay_authors
    # Display title: prefer cleaned directive; use research title only if relevant.
    _directive_title = _title_from_directive(ctx.directive or '')
    if (
        _essay_title
        and _essay_title.lower() not in ('general', 'unknown', '')
        and _research_title_matches_directive(_essay_title, ctx.directive or ctx.topic or '')
    ):
        ctx.pipeline_state['scholarly_topic'] = _essay_title
    elif _directive_title:
        ctx.pipeline_state['scholarly_topic'] = _directive_title
    ctx._save()


def _duration_targets(ctx):
    """The `Stage03Targets` for this run, read off the pipeline's duration
    targets, and the short-doc notice logged when the duration is capped."""
    _sch_tgt = ctx.pipeline_state.get('scholarly_duration_targets') or ctx._sch_duration_targets
    _sch_min_w = int(_sch_tgt['min_words'])
    _sch_target_w = int(_sch_tgt['target_words'])
    _sch_max_w = int(_sch_tgt['max_words'])
    _sch_word_gate = int(_sch_tgt['min_word_gate'])
    _sch_duration_capped = bool(_sch_tgt.get('duration_capped'))
    if _sch_duration_capped:
        _sch_retry_w = max(50, int(_sch_target_w * 0.6))
        _sch_accept_w = max(80, int(_sch_min_w * 0.75))
    else:
        _sch_retry_w = max(800, int(_sch_target_w * 0.67))
        _sch_accept_w = max(600, int(_sch_word_gate * 0.85))
    if _sch_duration_capped:
        ctx._log(
            'INFO',
            'Stage 3',
            f'Short-doc mode: target {_sch_target_w} words '
            f'(range {_sch_min_w}–{_sch_max_w}, min gate {_sch_word_gate})',
        )

    _sch_hard_cap_rule = ''
    if _sch_duration_capped:
        _sch_hard_cap_rule = (
            f'CRITICAL HARD CAP: The narration MUST be between {_sch_min_w} and '
            f'{_sch_max_w} words (absolute maximum {_sch_max_w} words). '
            f'Do NOT write a long-form essay. Count words before you finish; '
            f'if over {_sch_max_w} words, shorten until compliant.\n\n'
        )
    return Stage03Targets(
        min_words=_sch_min_w,
        target_words=_sch_target_w,
        max_words=_sch_max_w,
        word_gate=_sch_word_gate,
        duration_capped=_sch_duration_capped,
        retry_words=_sch_retry_w,
        accept_words=_sch_accept_w,
        hard_cap_rule=_sch_hard_cap_rule,
        structure_block=_SHORT_DOC_STRUCTURE if _sch_duration_capped else _10_SECTION_STRUCTURE,
    )


def _reject_disallowed_topic(ctx):
    """Raise `RuntimeError` when the topic names anatomy/medical subject matter.

    Whole words only. 2026-09-23: "Voyager 2: First Spacecraft to Visit Uranus"
    was rejected because Uranus contains "anus" — a substring match on a
    keyword list rejects planets, place names and anything else that happens to
    contain one.
    """
    _ANATOMY_REJECT_KW = {
        'vagina',
        'vulva',
        'uterus',
        'cervix',
        'ovary',
        'penis',
        'genitalia',
        'genitals',
        'anus',
        'rectum',
        'labia',
        'clitoris',
        'scrotum',
        'hymen',
        'fornix',
        'introitus',
        'vulvar',
        'vaginal',
        'pubic',
        'groin',
        'anatomy',
        'anatomical',
    }
    _topic_lo = (ctx.directive or ctx.topic or '').lower()
    _rejected_kw = next((kw for kw in _ANATOMY_REJECT_KW if re.search(rf'\b{re.escape(kw)}\b', _topic_lo)), None)
    if _rejected_kw:
        ctx._log(
            'ERROR',
            'Stage 3',
            f'Topic rejected: contains disallowed keyword "{_rejected_kw}". '
            f'Anatomy/medical topics are not supported by this pipeline.',
        )
        raise RuntimeError(f'Stage 3: topic rejected — disallowed keyword "{_rejected_kw}"')


def _fetch_wiki_source_block(ctx):
    """Fetch verified source material from Wikipedia into `ctx._wiki_source_block`.

    Injected into the Stage 3 prompt so Claude is grounded in real facts rather
    than compressed training-data memory. Non-fatal — falls back to
    essay_text only if Wikipedia is unreachable or returns nothing.
    """
    ctx._wiki_source_block = ''
    try:
        import urllib.parse as _up_wiki

        _wiki_slug = _up_wiki.quote((ctx.directive or ctx.topic or '').strip().replace(' ', '_'))
        _wiki_ua = {'User-Agent': 'ZygomaticsDocPipeline/1.0'}

        # REST summary (lead paragraph, often 200–600 words of clean prose)
        _wiki_summary_text = (
            requests.get(
                f'https://en.wikipedia.org/api/rest_v1/page/summary/{_wiki_slug}',
                headers=_wiki_ua,
                timeout=15,
            )
            .json()
            .get('extract', '')
        )

        # MediaWiki intro sections (up to 40 sentences of plain text)
        _mw_url = (
            f'https://en.wikipedia.org/w/api.php'
            f'?action=query&prop=extracts&exintro=false&explaintext=true'
            f'&exsectionformat=plain&exsentences=40'
            f'&titles={_wiki_slug}&format=json'
        )
        _mw_pages = requests.get(_mw_url, headers=_wiki_ua, timeout=15).json().get('query', {}).get('pages', {})
        _mw_text = next(iter(_mw_pages.values()), {}).get('extract', '')

        _wiki_combined = (_wiki_summary_text + '\n\n' + _mw_text[:3000]).strip()
        if len(_wiki_combined) > 100:
            ctx._wiki_source_block = (
                '[VERIFIED SOURCE MATERIAL — Wikipedia]\n' + _wiki_combined[:4500] + '\n[/VERIFIED SOURCE MATERIAL]'
            )
            ctx._log(
                'INFO',
                'Stage 3',
                f'Wikipedia source fetched: {len(_wiki_combined.split())} words for "{ctx.directive or ctx.topic}"',
            )
        else:
            ctx._log('WARNING', 'Stage 3', 'Wikipedia returned empty extract — proceeding with essay only')
    except Exception as _wiki_e:
        ctx._log('WARNING', 'Stage 3', f'Wikipedia fetch failed (non-fatal — essay only): {_wiki_e}')


def _register_narration_prompt(ctx, targets):
    """Register the scholarly narration template (instructions without essay source material)."""
    _register_prompt(
        'narration_scholarly',
        'Scholarly Narration Script',
        f'Converts a scholarly essay into a {targets.min_words}–{targets.max_words} '
        f'word 10-section documentary narration script',
        f'You are a documentary scriptwriter. Using the source material as research background, '
        f'write a compelling {targets.min_words}–{targets.max_words} word narrative documentary.\n\n'
        'RULES:\n'
        '1. Documentary narration style — vivid, cinematic, engaging. Third person or "we". Active voice.\n'
        '2. Open with a strong scene-setting hook.\n'
        '3. Weave in specific facts, names, and details from the source.\n'
        '4. No citations, footnotes, section headers, or academic language in output.\n'
        '5. Output ONLY the story text. No title, no preamble, no commentary.\n'
        f'6. Must be between {targets.min_words} and {targets.max_words} words — count carefully.\n\n'
        '10-SECTION STRUCTURE: [intro/overview → origins → mechanism → key people → '
        'conflicts → human impact → hidden facts → philosophy → present day → future]\n\n'
        'DOCUMENTARY FRAMEWORK BLOCK: [subject-type questions injected at runtime]\n\n'
        'SOURCE MATERIAL: [essay text injected at runtime — up to 8000 chars]',
        pipeline_id=ctx.pipeline_id,
        stage='Stage 3',
        topic=ctx.topic,
    )


def _apply_bench_replay(ctx):
    """Inject the cached stage-3 script instead of calling Claude, when the
    benchmark replay holds one. Returns the replay record, or None."""
    _rep_s3 = _bench_replay_get('stage_3')
    if _rep_s3:
        ctx.narration_script = _rep_s3['script']
        ctx._stage3_llm_model = 'bench_replay'
        ctx.pipeline_state['_stage3_scene_list'] = _rep_s3.get('scene_list') or []
        if _rep_s3.get('youtube_title'):
            ctx.pipeline_state['youtube_title'] = _rep_s3['youtube_title']
        if _rep_s3.get('youtube_description'):
            ctx.pipeline_state['youtube_description'] = _rep_s3['youtube_description']
        if _rep_s3.get('youtube_tags'):
            ctx.pipeline_state['youtube_tags'] = _rep_s3['youtube_tags']
        ctx._log(
            'INFO',
            'Stage 3',
            f'[bench_replay] script={len(ctx.narration_script.split())}w '
            f'scene_list={len(ctx.pipeline_state["_stage3_scene_list"])} entries',
        )
    return _rep_s3


def _persist_dsl_scene(ctx):
    """DSL: persist a Scene snapshot for the scholarly script (env-gated, non-fatal)."""
    if _dsl is None or not _dsl.is_enabled('documentary'):
        return
    try:
        _wc_for_dsl = len(ctx.narration_script.split())
        _doc_scene = _dsl.build_scene_from_metadata(
            {
                'duration': max(60.0, _wc_for_dsl * _SCHOLARLY_SEC_PER_WORD),
                'subject': (ctx.directive or ctx.topic or 'scholarly subject')[:120],
                'setting': f'documentary on {ctx.topic}',
                'lighting_style': 'cool_blue',
                'aspect_ratio': '16:9',
                'tags': ['documentary', 'scholarly', ctx.topic],
            },
            pipeline='documentary',
            scene_id=f'scholarly_{ctx.pipeline_id[:8]}',
        )
        _doc_yaml = _dsl.persist_scene(_doc_scene, ctx.out_dir)
        if _doc_yaml:
            ctx._log('INFO', 'Stage 3', f'DSL: persisted scene → {_doc_yaml}')
        else:
            ctx._log('INFO', 'Stage 3', f'DSL: {_dsl.status_summary("documentary")}')
    except Exception as _dsl_e:
        ctx._log('WARNING', 'Stage 3', f'DSL hook failed (non-fatal): {_dsl_e}')


def _enforce_word_gate(ctx, targets):
    """Post-cleaning narrative word count gate: blacklist the essay and raise
    when the narration is shorter than `targets.word_gate`."""
    _cleaned_wc = len(ctx.narration_script.split())
    if _cleaned_wc >= targets.word_gate:
        return
    ctx._log(
        'WARNING',
        'Stage 3',
        f'Story too short ({_cleaned_wc} words < {targets.word_gate}) — '
        f'LLM failed to produce adequate story. Blacklisting.',
    )
    _sel_id = ctx.pipeline_state.get('research_meta', {}).get('selected_essay_id') or ctx._selected_essay_id
    if _sel_id:
        try:
            from zyg_workflows import pgdb as _sq_pg

            _sq_pg.execute(
                "UPDATE essays SET used=2, blacklist_reason='too_short', date_used=%s WHERE id=%s",
                (time.strftime('%Y-%m-%dT%H:%M:%S'), _sel_id),
            )
            ctx._log('INFO', 'Stage 3', f'Essay id={_sel_id} blacklisted as too_short in DB')
        except Exception as _bl_err:
            ctx._log('WARNING', 'Stage 3', f'Could not blacklist essay in DB: {_bl_err}')
    raise RuntimeError(
        f'Stage 3: cleaned narration only {_cleaned_wc} words — '
        f'essay has insufficient narrative content (technical/math paper). Run aborted.'
    )


def _drop_title_echoes(script, title):
    """Drop paragraph-opening sentences that only repeat *title* or the sentence
    before them. Returns (new_script, removed_sentences).

    The essay body tends to open by restating its own title, which is fine on a
    page and wrong in a voice track: after the hook rewrite the Sikh Empire film
    narrated "…And how it fell. This is the Sikh Empire." and then immediately
    "The Sikh Empire. For fifty years, it stood…" — the heading read aloud as a
    sentence.
    """
    _te_title = re.sub(r'[^a-z0-9 ]', '', (title or '').lower()).strip()
    _te_paras = script.split('\n\n')
    _te_removed = []
    _te_prev_tail = ''
    for _pi_te, _para_te in enumerate(_te_paras):
        _p = _para_te.strip()
        if not _p:
            continue
        _m_te = re.match(r'\s*([^.!?]{1,80}[.!?])\s*(.*)$', _p, flags=re.DOTALL)
        if not _m_te:
            _te_prev_tail = _p
            continue
        _first_te, _rest_te = _m_te.group(1).strip(), _m_te.group(2).strip()
        _norm_te = re.sub(r'[^a-z0-9 ]', '', _first_te.lower()).strip()
        _is_title_echo = (
            bool(_norm_te)
            and len(_norm_te.split()) <= 8
            and (
                _norm_te == _te_title
                or (_te_title and _norm_te in (_te_title, f'the {_te_title}', f'this is {_te_title}'))
            )
        )
        _is_dupe = bool(_norm_te) and _norm_te and _norm_te in re.sub(r'[^a-z0-9 ]', '', _te_prev_tail.lower())
        # Only drop when something is left to say in the paragraph.
        if (_is_title_echo or (_is_dupe and len(_norm_te.split()) <= 8)) and _rest_te:
            _te_removed.append(_first_te)
            _te_paras[_pi_te] = _rest_te
            _te_prev_tail = _rest_te
        else:
            _te_prev_tail = _p
    return ('\n\n'.join(_te_paras) if _te_removed else script), _te_removed


def _tidy_narration(ctx, targets):
    """The three narration clean-ups, in the order the stage ran them: the
    short-doc word ceiling, the markdown horizontal rules and the title echoes."""
    # ── Episode splitting based on word count ────────────────────────
    # Rules:
    #   < 2500 words  → 1 episode (short)
    #   2500–7000     → 1 episode (ideal)
    #   7000–10000    → 3 episodes (split at ~33% and ~66%)
    #   > 10000       → truncate at 10000 words, then 3 episodes
    # Short-doc: enforce pipeline_options word ceiling before TTS
    if targets.duration_capped:
        _sd_words = ctx.narration_script.split()
        if len(_sd_words) > targets.max_words:
            ctx._log(
                'WARNING', 'Stage 3', f'Short-doc script {len(_sd_words)} words > {targets.max_words} — truncating'
            )
            ctx.narration_script = ' '.join(_sd_words[: targets.max_words])

    # ── Strip markdown horizontal rules ────────────────────────────────
    # The script LLM separates sections with "\n\n---\n\n". That is layout,
    # not language, and it reached BOTH outputs: IndexTTS-2 vocalised the
    # rule as a syllable per dash — the Byzantine run says "Jian, Jian,
    # Jian" out loud at 6 of its 9 separators (382s, 658s, 752s, 830s,
    # 951s, 1034s) — and all 9 also rendered as "---" on screen in the SRT.
    # Removing the rule while leaving the blank lines keeps the paragraph
    # break, so _tts_split_sentences still gets its 800 ms breath.
    _hr_n = len(re.findall(r'(?m)^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$', ctx.narration_script))
    if _hr_n:
        ctx.narration_script = re.sub(r'(?m)^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$', '', ctx.narration_script)
        ctx.narration_script = re.sub(r'\n{3,}', '\n\n', ctx.narration_script).strip()
        ctx._log(
            'INFO',
            'Stage 3',
            f'Removed {_hr_n} markdown separator(s) from narration — they were '
            f'being spoken aloud and burned into subtitles',
        )

    # ── Strip title-echo sentences ─────────────────────────────────────
    try:
        _te_script, _te_removed = _drop_title_echoes(
            ctx.narration_script, ctx.pipeline_state.get('essay_title') or ctx.topic or ''
        )
        if _te_removed:
            ctx.narration_script = _te_script
            ctx._log(
                'INFO',
                'Stage 3',
                f'Removed {len(_te_removed)} title-echo sentence(s) from narration: '
                + '; '.join(f'"{_r}"' for _r in _te_removed[:3]),
            )
    except Exception as _te_e:
        ctx._log('WARNING', 'Stage 3', f'Title-echo strip skipped (non-fatal): {_te_e}')


def _prose_gate_failure(script, llm_model):
    """Why *script* is not publishable prose, or '' when it passes.

    Measured over 225 scholarly scripts on disk: every script the LLM wrote is
    clean (0 of 145 across claude-sonnet-4-6 and 4-5), while the regex fallback
    produced raw research text 25% of the time (6 of 24) — narration that opens
    "Heliyon 7 (2021) e06580 Contents lists available at ScienceDirect", or
    reads an author list aloud. The existing word-count abort cannot see this:
    those scripts are a full 4000 words. Two layers, because the count is not
    the signal — provenance is:
      1. the fallback did not WRITE anything, it forwarded source text
      2. a furniture scan as a backstop for any other path
    An empty/short script is the word-count abort's business, and it says so
    far more clearly than "the fallback wrote this" would.
    """
    if len(script.split()) < 50:
        return ''
    if not llm_model or llm_model == 'regex':
        return (
            f'script came from the regex fallback (llm={llm_model or "none"}), '
            f'which forwards raw research text rather than writing narration'
        )
    _FURNITURE = (
        r'contents lists available',
        r'sciencedirect',
        r'journal homepage',
        r'doi\s*:',
        r'doi\.org',
        r'\barxiv\b',
        r'institutional research online',
        r'open access article',
        r'\bcc by\b',
        r'all rights reserved',
        r'(?:[A-Z] ){5,}[A-Z]',  # letter-spaced header: "A R T I C L E"
        r'(?:\w+ & ){3,}',  # author list: "Vuuren & Edmonds & Kainuma &"
    )
    _hits = [_p for _p in _FURNITURE if re.search(_p, script, re.I)]
    if _hits:
        return f'narration contains research-paper furniture ({len(_hits)} marker(s): {", ".join(_hits[:3])})'
    return ''


def _apply_prose_gate(ctx):
    """Abort the run when the narration is not publishable prose.

    On a monetised channel a missing episode beats one that narrates a journal
    masthead; the kanban marks the topic failed and moves to the next.
    ZYG_SCHOLARLY_ALLOW_RAW_SOURCE=1 ships it anyway with a warning.
    """
    _allow_raw = os.environ.get('ZYG_SCHOLARLY_ALLOW_RAW_SOURCE', '0').lower() not in ('0', 'false', 'no', '')
    _prose_fail = _prose_gate_failure(ctx.narration_script, ctx._stage3_llm_model)
    if not _prose_fail:
        return
    if _allow_raw:
        ctx._log(
            'WARNING',
            'Stage 3',
            f'Publishable-prose gate: {_prose_fail} — shipping anyway '
            f'(ZYG_SCHOLARLY_ALLOW_RAW_SOURCE=1). Listen before publishing.',
        )
    else:
        raise RuntimeError(
            f'Stage 3: {_prose_fail}. Refusing to narrate it — set ZYG_SCHOLARLY_ALLOW_RAW_SOURCE=1 to override.'
        )


def _finalise_script_state(ctx, yt_meta):
    """Enforce the 10000-word maximum, publish the script, its word count and
    the YouTube metadata on `ctx.pipeline_state`, save, and raise when cleaning
    left nothing to narrate."""
    # Enforce 10000-word maximum
    _all_words = ctx.narration_script.split()
    if len(_all_words) > 10000:
        ctx._log('INFO', 'Stage 3', f'Essay {len(_all_words)} words > 10000 — truncating')
        ctx.narration_script = ' '.join(_all_words[:10000])

    ctx.pipeline_state['script'] = ctx.narration_script
    ctx.pipeline_state['word_count'] = len(ctx.narration_script.split())
    if yt_meta:
        ctx.pipeline_state['youtube_title'] = yt_meta.get('title', '')
        ctx.pipeline_state['youtube_description'] = yt_meta.get('description', '')
        ctx.pipeline_state['youtube_tags'] = yt_meta.get('tags', [])
        ctx.pipeline_state['youtube_language'] = yt_meta.get('language', 'en') or 'en'
        ctx.pipeline_state['youtube_audience'] = yt_meta.get('audience', 'general') or 'general'
        ctx._log(
            'INFO',
            'Stage 3',
            f'YouTube meta: "{ctx.pipeline_state["youtube_title"]}" '
            f'| {len(ctx.pipeline_state["youtube_tags"])} tags | lang={ctx.pipeline_state["youtube_language"]}',
        )
    ctx._save()

    # Guard: if cleaning left us with nothing, fail cleanly before TTS
    if ctx.pipeline_state['word_count'] < 50:
        ctx._log(
            'ERROR',
            'Stage 3',
            f'narration_script is empty after cleaning ({ctx.pipeline_state["word_count"]} words) — aborting',
        )
        raise RuntimeError('Stage 3: narration script empty after cleaning — essay skipped')

    ctx._log(
        'INFO',
        'Stage 3',
        f'Essay ready for narration: {ctx.pipeline_state["word_count"]} words '
        f'(LLM: {ctx._stage3_llm_model or "regex fallback"})',
    )
