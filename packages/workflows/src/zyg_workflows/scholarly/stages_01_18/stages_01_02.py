# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 1 (topic setup) and stage 2 (academic research) of the scholarly pipeline."""

from ._common import _update_marker, _zyg_log


def stage_01_topic_setup(ctx):
    # ── Stage 1: Topic Setup ────────────────────────────────────────────
    ctx.job['current_stage'] = 'Stage 1: Topic Setup'
    ctx._stage_start('Stage 1: Topic Setup')
    _update_marker(ctx._pipeline_marker, label=f'🔄 Scholarly {ctx.pipeline_id[:8]} — Topic: {ctx.topic}')
    ctx._log('INFO', 'Stage 1', f'Scholarly pipeline starting for topic: {ctx.topic}')
    ctx._log(
        'INFO',
        'Stage 1',
        f'Visual intensity: {ctx._sch_intensity["level"]} (opening hook slot: {ctx._sch_intensity["hook_level"]})',
    )
    ctx.pipeline_state['image_intensity'] = ctx._sch_intensity['level']
    ctx.pipeline_state['hook_image_intensity'] = ctx._sch_intensity['hook_level']
    if ctx.directive:
        ctx._log('INFO', 'Stage 1', f'Directive: {ctx.directive}')
    ctx._done('Stage 1: Topic Setup', {'topic': ctx.topic})

    ctx._assert_not_stopped('Stage 2')


def stage_02_academic_research(ctx):
    # ── Stage 2: Academic Research ──────────────────────────────────────
    ctx.job['current_stage'] = 'Stage 2: Academic Research'
    ctx._stage_start('Stage 2: Academic Research')
    _update_marker(ctx._pipeline_marker, label=f'🔄 Scholarly {ctx.pipeline_id[:8]} — Academic Research')
    ctx._log('INFO', 'Stage 2', f'Launching ScholarlyResearchAgent for topic: {ctx.topic}')
    ctx.essay_text = ''
    ctx._preempt_state = {}
    if ctx._preempt_mode == 'replay' and ctx._pbank is not None:
        try:
            ctx._preempt_state = ctx._pbank.replay_state(ctx._preempt_entry) or {}
        except Exception:  # noqa: BLE001
            ctx._preempt_state = {}
        if len(str(ctx._preempt_state.get('essay_text') or '')) >= 300:
            ctx.essay_text = str(ctx._preempt_state['essay_text'])
            ctx.pipeline_state['research_meta'] = dict(
                ctx._preempt_state.get('research_meta') or {}, preempt_entry=ctx._preempt_entry
            )
            for _pk in ('essay_title', 'essay_authors'):
                if ctx._preempt_state.get(_pk):
                    ctx.pipeline_state[_pk] = ctx._preempt_state[_pk]
            ctx._log(
                'INFO',
                'Stage 2',
                f'[preempt] essay taken from bank entry {ctx._preempt_entry} '
                f'({len(ctx.essay_text)} chars, recorded {ctx._preempt_state.get("snapshot_at", "?")}) — no scrape',
            )
        else:
            ctx._log(
                'WARNING', 'Stage 2', f'[preempt] bank entry {ctx._preempt_entry} has no essay snapshot — scraping'
            )

    if not ctx.essay_text:
        try:
            # scholarly_research_agent.py became a package in the 2026-10 modularization, so the
            # by-path exec of the single file gives way to an ordinary import of the package.
            import importlib as _importlib

            _sch_mod = _importlib.import_module('zyg_workflows.scholarly_research_agent')
            _sra = _sch_mod.ScholarlyResearchAgent(
                topic=ctx.directive or ctx.topic,
                pipeline_id=ctx.pipeline_id,
                log_fn=ctx._log,
                stop_event=ctx.job.get('stop_event'),
            )
            ctx._research_result = _sra.run()
            ctx.essay_text = ctx._research_result.get('research_text', '')
            ctx._selected_essay_id = ctx._research_result.get('selected_essay_id')
            ctx.pipeline_state['research_meta'] = {
                'topic': ctx.topic,
                'sources_used': ctx._research_result.get('sources_used', []),
                'total_chars': ctx._research_result.get('total_chars', 0),
                'elapsed_s': ctx._research_result.get('elapsed_s', 0),
                'papers_found': ctx._research_result.get('papers_found', []),
                'selected_essay_id': ctx._selected_essay_id,
            }
            ctx._log(
                'INFO',
                'Stage 2',
                (
                    f'Academic research complete: {ctx._research_result.get("total_chars", 0)} chars '
                    f'from {len(ctx._research_result.get("sources_used", []))} sources '
                    f'in {ctx._research_result.get("elapsed_s", 0)}s'
                ),
            )
            ctx._log(
                'INFO', 'Stage 2', f'Papers/articles collected: {len(ctx._research_result.get("papers_found", []))}'
            )
        except Exception as _sra_err:
            ctx._log('WARNING', 'Stage 2', f'ScholarlyResearchAgent failed: {_sra_err} — using minimal fallback')

    # Fallback: plain text stub so pipeline can continue
    if not ctx.essay_text or len(ctx.essay_text) < 300:
        ctx.essay_text = (
            f'Topic: {ctx.topic.title()}\n\n'
            f'This episode explores academic research and scholarly analysis '
            f'relating to the subject of {ctx.topic}. '
            f'Drawing from university research papers, dissertations, and expert '
            f'academic essays, we examine the theoretical frameworks, historical '
            f'context, and societal implications identified by researchers and '
            f'scholars across leading institutions.\n\n'
            f'Directive context: {ctx.directive or "General scholarly overview"}'
        )
        ctx._log('WARNING', 'Stage 2', f'Using fallback stub text ({len(ctx.essay_text)} chars)')

    if len(ctx.essay_text.split()) < 150:
        ctx._log('WARNING', 'Stage 2', f'Low source material ({len(ctx.essay_text.split())} words)')

    ctx.pipeline_state['essay_text'] = ctx.essay_text
    ctx._save()
    ctx._log('INFO', 'Stage 2', f'Combined essay material: {len(ctx.essay_text)} chars')

    # ── Language filter: strip Cyrillic/CJK/Arabic from essay before passing to AI.
    #    Don't abort — just clean the text and continue. The AI always narrates in English.
    _non_latin_chars = set()
    _cleaned_chars = []
    for c in ctx.essay_text:
        if (
            '\u0400' <= c <= '\u04ff'  # Cyrillic
            or '\u4e00' <= c <= '\u9fff'  # CJK
            or '\u0600' <= c <= '\u06ff'  # Arabic
        ):
            _cleaned_chars.append(' ')
        else:
            _cleaned_chars.append(c)
    _essay_cleaned = ''.join(_cleaned_chars).strip()
    _non_latin_ratio = 1 - (len(_essay_cleaned.replace(' ', '')) / max(len(ctx.essay_text.replace(' ', '')), 1))
    if _non_latin_ratio > 0.3:
        # More than 30% was non-Latin — blacklist the source and skip
        ctx._log(
            'WARNING',
            'Stage 2',
            f'Essay source is predominantly non-English ({_non_latin_ratio:.0%}) — blacklisting and trying fallback',
        )
        try:
            from zyg_workflows import pgdb as _bl_pg

            _bl_src = (ctx._research_result.get('sources_used') or [''])[0] if '_research_result' in dir() else ''
            if _bl_src:
                # The old statement filtered on a column `url` that essays has never
                # had, so it has silently blacklisted nothing since it was written;
                # the port targets the two real URL columns instead.
                _bl_pg.execute(
                    "UPDATE essays SET used=2, blacklist_reason='non_english' WHERE full_text_url=%s OR pdf_url=%s",
                    (_bl_src, _bl_src),
                )
        except Exception as _exc:  # noqa: BLE001 — psycopg raises its own hierarchy
            _zyg_log.warning('non-English essay not blacklisted, a later run may pick the same one: %s', _exc)
        raise RuntimeError('Stage 2: Essay is non-English — skipped')
    if _non_latin_ratio > 0.05:
        ctx._log(
            'WARNING',
            'Stage 2',
            f'Essay contained {_non_latin_ratio:.0%} non-Latin characters — stripped, continuing',
        )
        ctx.essay_text = _essay_cleaned
        ctx.pipeline_state['essay_text'] = ctx.essay_text

    ctx._done('Stage 2: Academic Research', {'chars': len(ctx.essay_text)})

    ctx._assert_not_stopped('Stage 3')
