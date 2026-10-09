# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 2 of stage 3b: the LLM scene-description pass, and its Ollama probe.

Lifted out of `stage_05_visual_intent_tagging`. `_llm_scene_batch` was a closure
over five stage locals (`topic`, `pipeline_id`, the API key, the benchmark replay
list and `_debug`); they travel here in one `SceneDescJob` so the prompt builder
and the two provider calls are plain functions that can be exercised without a
pipeline. `_ollama_model_loaded` was a nested def published as
`ctx._ollama_model_loaded` for `stages_06_07`; it read no stage local at all.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from ._common import (
    _LLM_SMALL,
    _MURCH_MODEL,
    _OLLAMA_BASE_URL,
    _llm_client,
    _log_prompt,
    _murch_ollama_text,
    _record_token_usage,
    safe_urlopen,
)

SCENE_BATCH = 20  # sentences per API call — keeps prompts under ~1500 tokens


@dataclass
class SceneDescJob:
    """Everything the scene-description pass needs from the stage's locals.

    `api_key` empty means Claude is skipped, `replay_descs` non-empty means the
    benchmark replay answers instead of either provider, and `debug` is the
    pipeline's `_debug(stage, message)` logger used for provider failures.
    """

    topic: str
    pipeline_id: Any
    api_key: str
    replay_descs: Any
    debug: Any


def _ollama_model_loaded(model_name: str) -> bool:
    """Check if a model is already resident in Ollama VRAM via /api/ps."""
    try:
        _ps = json.loads(safe_urlopen(_OLLAMA_BASE_URL + '/api/ps', timeout=5).read())
        return any(model_name in m.get('name', '') for m in _ps.get('models', []))
    except Exception:
        return False


def _scene_batch_prompt(sents: list, topic: str) -> str:
    """The cinematographer prompt for one batch: the numbered sentences plus the
    rules that ask for a JSON array of 15-30 word scene descriptions."""
    _numbered = '\n'.join(f'{i + 1}. {s}' for i, s in enumerate(sents))
    return (
        f'You are a documentary cinematographer. '
        f'For each numbered narration sentence below, write a SHORT, SPECIFIC visual '
        f'scene description (15–30 words) of exactly what should appear on screen — '
        f'a concrete image, not a vague category.\n\n'
        f'Topic: {topic}\n\n'
        f'Rules:\n'
        f'  - Be specific to THIS sentence (person, place, object, action)\n'
        f'  - Never write generic phrases like "related imagery" or "historical scene"\n'
        f'  - 15–30 words per description\n'
        f'  - Output ONLY a valid JSON array of strings, one per sentence, same order\n'
        f'  - Example for gladiators: '
        f'["Roman gladiator in iron helmet striking training post with gladius, sand floor arena", ...]\n\n'
        f'Sentences:\n{_numbered}'
    )


def _padded_descs(parsed: Any, n: int) -> list:
    """The parsed JSON array as `n` stripped strings, or `[]` when it is not a
    list: a short answer is padded with empty strings so sentence indexing stays
    correct, a long one is left long exactly as the pre-split code did."""
    if not isinstance(parsed, list):
        return []
    _descs = [str(d).strip() for d in parsed]
    if len(_descs) == n:
        return _descs
    return _descs + [''] * (n - len(_descs))


def _claude_scene_batch(job: SceneDescJob, sents: list, prompt: str) -> list:
    """One scene-description batch through Claude Haiku (scene descriptions are
    mechanical — no Sonnet needed), logging the prompt and the reply and
    recording token usage. Returns `[]` when there is no key or the call fails."""
    if not job.api_key:
        return []
    _meta = {'topic': job.topic, 'pipeline_type': 'scholarly', 'n_sents': len(sents)}
    try:
        _log_prompt(
            'claude_scene_desc',
            'Stage 3b',
            job.pipeline_id,
            prompt,
            meta=_meta,
            direction='sent',
            role='user',
            llm=_LLM_SMALL,
            from_who='system',
            to_who=_LLM_SMALL,
        )
        _r3b = _llm_client(job.api_key).messages.create(
            model=_LLM_SMALL,
            max_tokens=2000,
            temperature=0.7,
            messages=[{'role': 'user', 'content': prompt}],
        )
        _record_token_usage(
            model=_LLM_SMALL,
            prompt_tokens=_r3b.usage.input_tokens,
            completion_tokens=_r3b.usage.output_tokens,
            pipeline_id=job.pipeline_id,
            stage='Stage 3b',
            pipeline_type='scholarly',
        )
        _raw3b = re.sub(r'```(?:json)?|```', '', _r3b.content[0].text).strip()
        _log_prompt(
            'claude_scene_desc',
            'Stage 3b',
            job.pipeline_id,
            _raw3b,
            meta=_meta,
            direction='received',
            role='assistant',
            llm=_LLM_SMALL,
            from_who=_LLM_SMALL,
            to_who='system',
        )
        return _padded_descs(json.loads(_raw3b), len(sents))
    except Exception as _3be:
        job.debug('Stage 3b', f'Claude scene desc failed: {_3be}')
        return []


def _ollama_scene_batch(job: SceneDescJob, sents: list, prompt: str) -> list:
    """One scene-description batch through the local roster model via Ollama.

    Was hardcoded to gpt-oss:20b through the crewai Ollama wrapper. Two things
    were wrong with that. gpt-oss was swapped out of the Aug-2026 roster, and on
    ollama 0.17.7 it answers a JSON request with an EMPTY response — so this
    fallback could only ever return nothing on the day Anthropic was down, which
    is the only day it runs. And the roster model that replaced it (qwen3.5) is a
    THINKING model: it routes its whole answer into the 'thinking' field and
    leaves 'response' empty unless asked not to.

    So this speaks to Ollama the same way murch_engine does — raw /api/generate
    with think:False and the same response/thinking fallback reader — and takes
    its model from the same constant, so the roster is defined in exactly one
    place. Returns `[]` when no model is configured or the call fails.
    """
    _sd_model = os.environ.get('ZYG_SCHOLARLY_SCENE_LLM', '') or _MURCH_MODEL
    if not _sd_model:
        return []
    _meta = {'topic': job.topic, 'pipeline_type': 'scholarly', 'n_sents': len(sents)}
    try:
        _log_prompt(
            'ollama_scene_desc',
            'Stage 3b',
            job.pipeline_id,
            prompt,
            meta=_meta,
            direction='sent',
            role='user',
            llm=_sd_model,
            from_who='system',
            to_who=_sd_model,
        )
        _body3b = json.dumps(
            {
                'model': _sd_model,
                'prompt': prompt,
                'stream': False,
                'think': False,
                'options': {'temperature': 0.1},
                'keep_alive': '5m',
            }
        ).encode()
        with safe_urlopen(_OLLAMA_BASE_URL + '/api/generate', data=_body3b, timeout=300) as _rsp3b:
            _ts3b = _murch_ollama_text(_rsp3b.read())
        _log_prompt(
            'ollama_scene_desc',
            'Stage 3b',
            job.pipeline_id,
            _ts3b,
            meta=_meta,
            direction='received',
            role='assistant',
            llm=_sd_model,
            from_who=_sd_model,
            to_who='system',
        )
        _ts3b = re.sub(r'```(?:json)?|```', '', _ts3b).strip()
        _m3b = re.search(r'\[.*\]', _ts3b, re.S)
        return _padded_descs(json.loads(_m3b.group(0) if _m3b else _ts3b), len(sents))
    except Exception as _3boe:
        job.debug('Stage 3b', f'Ollama scene desc failed: {_3boe}')
        return []


def _llm_scene_batch(job: SceneDescJob, sents: list) -> list:
    """
    Returns a list of scene description strings (same length as sents).
    Tries Claude Sonnet first, then Mistral via Ollama, then returns [].
    """
    # Benchmark replay: cycle through pre-recorded scene descs, no API call.
    if job.replay_descs:
        _pool = job.replay_descs or ['documentary scene']
        return [_pool[i % len(_pool)] for i in range(len(sents))]
    _sp = _scene_batch_prompt(sents, job.topic)
    _descs = _claude_scene_batch(job, sents, _sp)
    if _descs:
        return _descs
    return _ollama_scene_batch(job, sents, _sp)  # both failed — caller uses the keyword tag


def _prefill_inline_scenes(visual_tags: list, inline_scenes: list) -> int:
    """Fill `scene_desc` from the scene descriptions Stage 3's script call
    returned inline — they are already aligned to the sentences by index — and
    return how many entries were filled. Blank and non-string entries are left
    alone so the LLM batch below still covers them."""
    _count = 0
    for _ii, _isc in enumerate(inline_scenes):
        if _ii < len(visual_tags) and isinstance(_isc, str) and _isc.strip():
            visual_tags[_ii]['scene_desc'] = _isc.strip()
            _count += 1
    return _count


def _fill_scene_descs(visual_tags: list, sentences: list, job: SceneDescJob, batch: int = SCENE_BATCH) -> int:
    """Give every `visual_tags` entry without a `scene_desc` one, in batches of
    *batch* sentences, and return how many the LLM supplied.

    A batch whose sentences all already carry a `scene_desc` (prefilled from
    Stage 3) is skipped without an API call; an entry the LLM returned nothing
    for falls back to its keyword `tag`, so downstream always has something.
    """
    _filled = 0
    for _bi3b in range(0, len(sentences), batch):
        _sbatch = sentences[_bi3b : _bi3b + batch]
        # Skip this batch entirely if every sentence already has a scene_desc from Stage 3
        _batch_idxs = range(_bi3b, min(_bi3b + batch, len(visual_tags)))
        if all(visual_tags[_i3b].get('scene_desc') for _i3b in _batch_idxs):
            continue
        _descs = _llm_scene_batch(job, _sbatch)
        for _ti3b, _sent3b in enumerate(_sbatch):
            _vt_idx3b = _bi3b + _ti3b
            if _vt_idx3b >= len(visual_tags):
                break
            # Don't overwrite an inline scene from Stage 3
            if visual_tags[_vt_idx3b].get('scene_desc'):
                continue
            _sd = _descs[_ti3b].strip() if _ti3b < len(_descs) else ''
            if _sd:
                visual_tags[_vt_idx3b]['scene_desc'] = _sd
                _filled += 1
            else:
                # Graceful fallback: use keyword tag so downstream always has something
                visual_tags[_vt_idx3b]['scene_desc'] = visual_tags[_vt_idx3b]['tag']
    return _filled


def _generic_fallback_stats(visual_tags: list, topic: str) -> tuple:
    """`(count, pct)` of entries whose scene description is still the generic
    `'<topic> related imagery'` keyword tag — the stage's quality gate warns
    above 30%. An entry with no `scene_desc` counts by its `tag`."""
    _generic_tag = topic + ' related imagery'
    _generic_count = sum(1 for vt in visual_tags if vt.get('scene_desc', vt['tag']) == _generic_tag)
    return _generic_count, _generic_count / max(len(visual_tags), 1) * 100
