# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3 fact-check: Haiku flags claims the source material does not support."""

import os

from ._common import _LLM_SMALL, _llm_client, _record_token_usage


def stage_04_fact_check(ctx):
    # ── Stage 3 fact-check: Haiku flags unverifiable claims ───────────────
    # Compares the generated script against the Wikipedia source material and
    # logs any specific claims (dates, names, statistics) not found in sources.
    # Non-fatal — pipeline continues regardless; issues are logged for review.
    _factcheck_issues = []
    _fc_block_reason = ''
    if ctx.narration_script and ctx._wiki_source_block:
        try:
            import json as _json_fc
            import re as _re_fc

            _fc_prompt = (
                'You are a documentary fact-checker. Read the narration script and '
                'identify any specific claims (exact dates, statistics, named quotes, '
                'causality assertions, numeric figures) that are NOT supported by or '
                'directly contradict the verified source material provided.\n\n'
                f'VERIFIED SOURCE:\n{ctx._wiki_source_block[:3000]}\n\n'
                f'NARRATION SCRIPT:\n{ctx.narration_script[:5000]}\n\n'
                'Return ONLY a JSON array. Each item: '
                '{"claim": "exact phrase from script", "issue": "not in sources | contradicts sources | unverifiable"}\n'
                'If no issues, return: []\n'
                'JSON only, no other text:'
            )
            _fc_resp = _llm_client(ctx._anthropic_key).messages.create(
                model=_LLM_SMALL,
                max_tokens=1500,
                temperature=0.0,
                messages=[{'role': 'user', 'content': _fc_prompt}],
            )
            _fc_raw = _fc_resp.content[0].text.strip()
            _fc_clean = _re_fc.sub(r'^```(?:json)?\s*|\s*```$', '', _fc_raw, flags=_re_fc.DOTALL).strip()
            _factcheck_issues = _json_fc.loads(_fc_clean)
            _record_token_usage(
                model=_LLM_SMALL,
                prompt_tokens=_fc_resp.usage.input_tokens,
                completion_tokens=_fc_resp.usage.output_tokens,
                pipeline_id=ctx.pipeline_id,
                stage='Stage 3 FC',
                pipeline_type='scholarly',
            )
            if _factcheck_issues:
                _fc_contra = [_i for _i in _factcheck_issues if 'contradict' in str(_i.get('issue', '')).lower()]
                ctx._log(
                    'WARNING',
                    'Stage 3',
                    f'Fact-check: {len(_factcheck_issues)} potentially unverifiable claim(s)'
                    + (f', {len(_fc_contra)} CONTRADICTING sources' if _fc_contra else '')
                    + ' — review before publishing:',
                )
                for _fc_item in _factcheck_issues[:10]:
                    ctx._log(
                        'WARNING',
                        'Stage 3',
                        f'  [{_fc_item.get("issue", "?")}] "{_fc_item.get("claim", "")[:120]}"',
                    )
                # A claim that CONTRADICTS the verified source is a different
                # class from one that is merely unsourced, and on the Sikh
                # Empire run it was the film's opening line. Off by default so
                # production pacing is unchanged; set the env var to make it
                # stop the run instead of narrating something false. Recorded
                # here and raised BELOW the except — this try/except swallows
                # everything as non-fatal, which would eat the block itself.
                if _fc_contra and os.environ.get('ZYG_SCHOLARLY_FACTCHECK_BLOCK', '0').lower() not in (
                    '0',
                    'false',
                    'no',
                    '',
                ):
                    _fc_block_reason = (
                        f'Fact-check block: {len(_fc_contra)} claim(s) contradict the '
                        f'verified sources (first: '
                        f'"{_fc_contra[0].get("claim", "")[:100]}"). '
                        f'Unset ZYG_SCHOLARLY_FACTCHECK_BLOCK to ship anyway.'
                    )
            else:
                ctx._log('INFO', 'Stage 3', 'Fact-check: all claims traceable to verified sources')
        except Exception as _fc_e:
            ctx._log('WARNING', 'Stage 3', f'Fact-check pass failed (non-fatal): {_fc_e}')
    elif not ctx._wiki_source_block:
        ctx._log('WARNING', 'Stage 3', 'Fact-check skipped — no Wikipedia source available for this topic')
    ctx.pipeline_state['factcheck_issues'] = _factcheck_issues
    if _fc_block_reason:
        raise RuntimeError(_fc_block_reason)

    ctx._done(
        'Stage 3: Script Preparation',
        {
            'word_count': ctx.pipeline_state['word_count'],
            'llm': ctx._stage3_llm_model,
            'factcheck_flags': len(_factcheck_issues),
        },
    )

    ctx._stage_start('Stage 3b: Visual Tagging')
