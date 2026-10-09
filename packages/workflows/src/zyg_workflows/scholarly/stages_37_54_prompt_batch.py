# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3.5 Pre-generation, part one: the single Claude Sonnet prompt batch.

`stage_11_flux_prompt_batch(ctx)` — the stage `pipeline_scholarly` calls, and
still imports from `stages_37_54` — plus the closure that did all of its work.

It was 981 lines in `stages_37_54.py`: a 16-line glue head, a 944-line nested
`def` holding five more nested `def`s, and a 12-line tail. The nesting bought
nothing but depth — no name was ever rebound across a scope boundary, neither
in an enclosing scope nor at module level — so each `def` is now a module-level
function that takes what it reads:

* `batch_generate_flux_prompts(ctx, n)` — the former closure, minus the five
  `def`s. It still derives `_style_ctx`, `_quality_tag`, the directives, the
  period lock and `_system` in exactly that order, but each derivation is now
  one call into `stages_37_54_prompt_batch_build` (it was 403 lines of straight
  string assembly, none of it unit-testable); then it runs the same four steps
  in the same `try`: one or two `call_claude` passes, then the period, bare-noun
  and text-subject guards;
* `call_claude(ctx, slot_start, slot_end, …)` — one Sonnet call and the `S`/`C`
  line parse;
* `make_user_msg` and the three guards live in `stages_37_54_prompt_guards`.

The derived values travel as **keyword-only** arguments; see that module's
docstring for why. Statement order, every log line and all three
`ctx._prebuilt_prompts` stores are the monolith's. No `os.environ` read moved, so
`settings.py`'s file tuples are unaffected by this split.
"""

import re as _re_bp

from zyg_workflows.runtime import _bench_replay_get, _record_token_usage
from zyg_workflows.scholarly.stages_37_54_prompt_batch_build import (
    BATTLE_DIRECTIVE,
    HANDS_RULE,
    SKIN_RULE,
    build_intensity_directive,
    build_period_lock,
    build_quality_tag,
    build_style_ctx,
    build_subject_directive,
    build_system_prompt,
    is_battle_topic,
)
from zyg_workflows.scholarly.stages_37_54_prompt_guards import (
    bare_noun_guard,
    make_user_msg,
    period_guard,
    text_subject_guard,
)
from zyg_workflows.stage_runner import _log_prompt
from zyg_workflows.subscription_llm import (
    MODEL_LARGE as _LLM_LARGE,
    anthropic_client as _llm_client,
    api_key_or_login as _llm_key,
)


def stage_11_flux_prompt_batch(ctx):
    _log = ctx._log
    _n_flux_images = ctx._n_flux_images
    # ── Stage 3.5 Pre-generation: single Claude Sonnet batch call ─────────
    # One call generates ALL N prompts upfront using the 10-part framework,
    # so Claude can plan visual variety across the full sequence like a director.
    # Per-image Claude calls are only used as fallback when this fails.
    _prebuilt_prompts: list = []
    ctx._prebuilt_prompts = _prebuilt_prompts
    _prebuilt_prompts = batch_generate_flux_prompts(ctx, _n_flux_images)
    ctx._prebuilt_prompts = _prebuilt_prompts
    if _prebuilt_prompts:
        _log(
            'INFO',
            'Stage 3.5',
            f'Using {len(_prebuilt_prompts)} pre-built Claude Sonnet prompt pairs '
            f'(standard + counterpoint per slot, 10-part framework, 1 API call)',
        )
    else:
        _log('INFO', 'Stage 3.5', 'Batch prompt generation unavailable — using per-image fallback')
    ctx._prebuilt_prompts = _prebuilt_prompts


def batch_generate_flux_prompts(ctx, n: int) -> list:
    """
    Call Claude Sonnet once to generate all N FLUX prompts using the
    10-part framework. Returns a list of N prompt strings, or [] on failure.
    Splits into 2 batches when n > 50 to stay within output token limits.
    """
    _era_lock = ctx._era_lock
    _is_modern_topic = ctx._is_modern_topic
    _log = ctx._log
    _sch_family_early = ctx._sch_family_early
    _sch_intensity = ctx._sch_intensity
    _sch_subject_type = ctx._sch_subject_type
    directive = ctx.directive
    pipeline_state = ctx.pipeline_state
    topic = ctx.topic
    visual_style = ctx.visual_style
    # Benchmark replay: return pre-built prompts, cycling to length n.
    _rep_fp = _bench_replay_get('stage_3_5_flux_prompts')
    if _rep_fp:
        _pool = _rep_fp or []
        if _pool:
            return [_pool[i % len(_pool)] for i in range(n)]
        return []

    _ak = _llm_key()
    if not _ak:
        return []

    _is_battle_topic = is_battle_topic(
        topic=topic,
        directive=directive,
        pipeline_state=pipeline_state,
        era_lock=_era_lock,
        log=_log,
    )
    _style_ctx = build_style_ctx(
        is_battle=_is_battle_topic,
        subject_type=_sch_subject_type,
        is_modern_topic=_is_modern_topic,
        family_early=_sch_family_early,
        visual_style=visual_style,
        era_lock=_era_lock,
        intensity=_sch_intensity,
    )
    _quality_tag = build_quality_tag(is_modern_topic=_is_modern_topic, subject_type=_sch_subject_type)
    _battle_directive = BATTLE_DIRECTIVE if _is_battle_topic else ''
    _intensity_directive = build_intensity_directive(_sch_intensity)
    _subject_directive = build_subject_directive(subject_type=_sch_subject_type, is_battle=_is_battle_topic)
    _period_lock_section, _period_lock_rule = build_period_lock(era_lock=_era_lock, n=n)
    _hands_rule = HANDS_RULE
    _skin_rule = SKIN_RULE if _sch_intensity['rank'] < 2 else ''
    _system = build_system_prompt(
        family_early=_sch_family_early,
        intensity_directive=_intensity_directive,
        battle_directive=_battle_directive,
        subject_directive=_subject_directive,
        era_lock=_era_lock,
    )
    # The ten values derived above that `call_claude` — and through it
    # `make_user_msg` — reads and never changes. They are keyword-only on both
    # functions and named once here: seven of the ten are strings, and a
    # positional list of seven strings is a silent bug waiting for an edit.
    _call_kw = dict(
        n=n,
        _ak=_ak,
        _system=_system,
        _style_ctx=_style_ctx,
        _quality_tag=_quality_tag,
        _is_battle_topic=_is_battle_topic,
        _period_lock_section=_period_lock_section,
        _period_lock_rule=_period_lock_rule,
        _hands_rule=_hands_rule,
        _skin_rule=_skin_rule,
    )

    try:
        if n <= 50:
            _parsed = call_claude(ctx, 0, n, **_call_kw)
        else:
            # Split into two batches to stay within output token limits
            _mid = n // 2
            _parsed = call_claude(ctx, 0, _mid, **_call_kw) + call_claude(ctx, _mid, n, **_call_kw)

        _parsed = period_guard(ctx, _parsed, n=n, _ak=_ak, _system=_system, _period_lock_rule=_period_lock_rule)
        _parsed = bare_noun_guard(ctx, _parsed)
        _parsed = text_subject_guard(ctx, _parsed)
        _log('INFO', 'Stage 3.5', f'Batch Claude Sonnet prompts: {len(_parsed)}/{n} generated')
        return _parsed
    except Exception as _be:
        _log('WARNING', 'Stage 3.5', f'Batch Claude prompt generation failed: {_be}')
        return []


def call_claude(
    ctx,
    slot_start: int,
    slot_end: int,
    *,
    n: int,
    _ak: str,
    _system: str,
    _style_ctx: str,
    _quality_tag: str,
    _is_battle_topic: bool,
    _period_lock_section: str,
    _period_lock_rule: str,
    _hands_rule: str,
    _skin_rule: str,
) -> list:
    """One Claude Sonnet batch call for slots `slot_start`..`slot_end`, parsed into S/C pairs."""
    pipeline_id = ctx.pipeline_id
    topic = ctx.topic
    _msg = make_user_msg(
        ctx,
        slot_start,
        slot_end,
        n=n,
        _style_ctx=_style_ctx,
        _quality_tag=_quality_tag,
        _is_battle_topic=_is_battle_topic,
        _period_lock_section=_period_lock_section,
        _period_lock_rule=_period_lock_rule,
        _hands_rule=_hands_rule,
        _skin_rule=_skin_rule,
    )
    _log_prompt(
        'claude_flux_batch',
        'Stage 3.5',
        pipeline_id,
        _msg,
        meta={'topic': topic, 'pipeline_type': 'scholarly', 'slot_start': slot_start, 'slot_end': slot_end},
        direction='sent',
        role='user',
        llm=_LLM_LARGE,
        from_who='system',
        to_who=_LLM_LARGE,
        system_prompt=_system,
    )
    _r = _llm_client(_ak).messages.create(
        model=_LLM_LARGE,
        max_tokens=12000,
        temperature=0.9,
        system=_system,
        messages=[{'role': 'user', 'content': _msg}],
    )
    _raw = _r.content[0].text.strip()
    _log_prompt(
        'claude_flux_batch',
        'Stage 3.5',
        pipeline_id,
        _raw,
        meta={'topic': topic, 'pipeline_type': 'scholarly', 'slot_start': slot_start, 'slot_end': slot_end},
        direction='received',
        role='assistant',
        llm=_LLM_LARGE,
        from_who=_LLM_LARGE,
        to_who='system',
    )
    _record_token_usage(
        model=_LLM_LARGE,
        prompt_tokens=_r.usage.input_tokens,
        completion_tokens=_r.usage.output_tokens,
        pipeline_id=pipeline_id,
        stage='Stage 3.5',
        pipeline_type='scholarly',
    )
    _s_by_num = {}
    _c_by_num = {}
    _cur_n = None
    _cur_t = None
    _buf = []

    def _flush_pair():
        if _cur_n is not None and _buf:
            _txt = ' '.join(' '.join(_buf).split())
            if _cur_t == 'S':
                _s_by_num[_cur_n] = _txt
            else:
                _c_by_num[_cur_n] = _txt

    for _ln in _raw.split('\n'):
        _ls = _ln.strip()
        _ms = _re_bp.match(r'^(\d+)S\.\s+(.*)', _ls)
        _mc = _re_bp.match(r'^(\d+)C\.\s+(.*)', _ls)
        if _ms:
            _flush_pair()
            _cur_n, _cur_t, _buf = int(_ms.group(1)), 'S', [_ms.group(2)]
        elif _mc:
            _flush_pair()
            _cur_n, _cur_t, _buf = int(_mc.group(1)), 'C', [_mc.group(2)]
        elif _cur_n is not None and _ls:
            _buf.append(_ls)
    _flush_pair()
    _pairs = []
    for _si in range(slot_start + 1, slot_end + 1):
        _s = _s_by_num.get(_si, '')
        _c = _c_by_num.get(_si, '')
        if _s and len(_s.split()) >= 10:
            _pairs.append({'standard': _s, 'counterpoint': _c or _s})
    return _pairs
