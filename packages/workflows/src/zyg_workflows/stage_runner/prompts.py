# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prompt logging and the prompt registry: _is_test_pid, _log_prompt, _register_prompt."""

import json
import os
from zyg_workflows.runtime import _AGENT_LOG_LOCK
from zyg_workflows.runtime import _ams_iso
from zyg_workflows.runtime import _runtime_path

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')


# P-03 (2026-08-25): shared test-run predicate. Resolved lazily (pipeline_common
# is imported two lines AFTER this module at the bottom of crewai_web_gui.py)
# and FAIL-CLOSED on a literal prefix list, because the consumer that matters
# most here is Desktop delivery — a smoke must never ship on an import hiccup.
_TEST_ID_PREFIXES_FALLBACK = ('docsmoke-', 'gatecheck-', 'introsmoke-', 'smoke')


def _is_test_pid(pipeline_id) -> bool:
    try:
        from zyg_workflows.pipeline_common import is_test_pipeline_id

        return is_test_pipeline_id(pipeline_id)
    except Exception:
        return isinstance(pipeline_id, str) and pipeline_id.strip().lower().startswith(_TEST_ID_PREFIXES_FALLBACK)


def _log_prompt(
    prompt_type: str,
    stage: str,
    pipeline_id: str,
    prompt: str,
    meta: dict = None,
    direction: str = 'sent',
    role: str = 'user',
    llm: str = '',
    from_who: str = 'system',
    to_who: str = '',
    system_prompt: str = '',
):
    """Append one entry to prompt_log.json for every AI-generated prompt (image, video, script).
    Thread-safe. Keeps last 10000 entries.

    direction: 'sent' | 'received' | 'template'
    role:      'system' | 'user' | 'assistant'
    llm:       model name (e.g. 'claude-sonnet-4-6', 'gpt-4o', 'qwen2.5:72b')
    from_who:  who sent it ('system' for us, or the llm name when receiving)
    to_who:    recipient ('claude-sonnet-4-6' when sending, 'system' when receiving)
    system_prompt: optional system/template portion of the call (logged separately)
    """
    try:
        # Permanent copy first: if the big-JSON rewrite below fails or the
        # process dies mid-write, the durable line is already on disk.
        try:
            from zyg_workflows import llm_audit as _la_lp

            if not str(llm or '').startswith('claude-'):
                _la_lp.record(
                    source='explicit',
                    direction=direction,
                    llm=llm or to_who or from_who or '',
                    stage=stage,
                    pipeline_id=pipeline_id,
                    type=prompt_type,
                    prompt=prompt,
                    system_prompt=system_prompt or '',
                    role=role,
                    from_who=from_who,
                    to_who=to_who,
                    **(meta or {}),
                )
        except Exception as _exc:
            _zyg_log.warning('llm audit record for stage %s failed, only the prompt log was written: %s', stage, _exc)
        with _AGENT_LOG_LOCK:
            log_path = _runtime_path('prompt_log.json')
            entry = {
                'type': prompt_type,
                'stage': stage,
                'pipeline_id': pipeline_id,
                'prompt': prompt,
                'timestamp': _ams_iso(),
                'direction': direction,
                'role': role,
                'llm': llm or to_who or from_who or '',
                'from_who': from_who,
                'to_who': to_who,
            }
            if system_prompt:
                entry['system_prompt'] = system_prompt
            if meta:
                entry.update(meta)
            entries = []
            if os.path.exists(log_path):
                try:
                    with open(log_path) as _plf:
                        entries = json.load(_plf)
                except Exception:
                    entries = []
            entries.append(entry)
            if len(entries) > 10000:
                entries = entries[-10000:]  # recent-activity VIEW only —
                # the permanent copy is the append-only JSONL written below,
                # so trimming here no longer destroys the oldest runs.
            with open(log_path, 'w') as _plf:
                json.dump(entries, _plf, indent=2)
        _dir_tag = direction.upper()[:4]
        _zyg_log.info(f'[PROMPT LOG] [{_dir_tag}|{prompt_type}] {stage} | {pipeline_id} — {prompt[:80]}')
        # Also register runtime prompts (flux images, wan video) in the prompt registry
        _RUNTIME_PROMPT_META = {
            'flux_image': (
                'image_generation',
                'FLUX Image Generation',
                'FLUX.1-schnell prompt — unique per narration slot, '
                'built by Murch engine + Claude Haiku scene description',
            ),
            'wan_video': (
                'video_generation',
                'Wan Video Generation',
                'Wan video generation prompt (retired — video generation disabled)',
            ),
        }
        if prompt_type in _RUNTIME_PROMPT_META:
            _cat, _pname, _pdesc = _RUNTIME_PROMPT_META[prompt_type]
            _topic = (meta or {}).get('topic', '')
            _register_prompt(
                _cat, _pname, _pdesc, prompt, pipeline_id=pipeline_id, stage=stage, topic=_topic, runtime=True
            )
    except Exception as _ple:
        _zyg_log.info(f'[PROMPT LOG FAILED] {stage}: {_ple}')


def _register_prompt(
    category: str,
    name: str,
    function_desc: str,
    prompt_text: str,
    pipeline_id: str = '',
    stage: str = '',
    topic: str = '',
    runtime: bool = False,
    created_by: str = 'system',
    change_notes: str = '',
) -> str:
    """Register or update a prompt in the prompt registry (data/runtime/prompt_registry.json).

    runtime=False (default): stable template prompt.
        ID is based on text hash. When the template text changes, the old entry
        is marked inactive (retired) and a new entry is created with version+1
        and parent_id pointing to the old entry — full version chain is preserved.
        Old prompts are NEVER deleted so every historical state is recoverable.

    runtime=True: dynamic/runtime prompt (unique text per call, e.g. FLUX images).
        ID is based on category+name only. prompt_text field always shows the
        latest example; history records every individual use.

    Returns the prompt_id string.
    """
    import hashlib as _hl

    now_iso = _ams_iso()
    if runtime:
        prompt_id = 'pr_' + _hl.sha256((category + ':' + name).encode()).hexdigest()[:12]
    else:
        # Include first 400 chars of text in hash so small edits create a new version
        prompt_id = 'pt_' + _hl.sha256((category + ':' + name + ':' + prompt_text[:400]).encode()).hexdigest()[:12]

    reg_path = _runtime_path('prompt_registry.json')
    try:
        with _AGENT_LOG_LOCK:
            reg = {}
            if os.path.exists(reg_path):
                try:
                    with open(reg_path) as _rf:
                        reg = json.load(_rf)
                except Exception:
                    reg = {}
            prompts = reg.get('prompts', {})

            # For stable templates: retire any active entry with same category+name but different id
            # Track highest version number and the retiring entry's id for parent_id linkage
            _parent_id = ''
            _next_version = 1
            if not runtime:
                for eid, ep in list(prompts.items()):
                    if ep.get('category') == category and ep.get('name') == name:
                        _v = ep.get('version', 1)
                        if _v >= _next_version:
                            _next_version = _v + 1
                        if eid != prompt_id and ep.get('active', True):
                            ep['active'] = False
                            ep['retired_at'] = now_iso
                            _parent_id = eid  # most recently active version becomes parent

            if prompt_id not in prompts:
                entry_data = {
                    'id': prompt_id,
                    'name': name,
                    'category': category,
                    'function_desc': function_desc,
                    'prompt_text': prompt_text,
                    'runtime': runtime,
                    'active': True,
                    'version': _next_version,
                    'parent_id': _parent_id,
                    'created_at': now_iso,
                    'created_by': created_by,
                    'change_notes': change_notes,
                    'last_used_at': now_iso,
                    'use_count': 0,
                    'use_history': [],
                }
                prompts[prompt_id] = entry_data

            entry = prompts[prompt_id]
            if runtime:
                entry['prompt_text'] = prompt_text  # always update to latest example
            entry['last_used_at'] = now_iso
            entry['use_count'] = entry.get('use_count', 0) + 1
            # Backfill version/parent_id on old entries that predate this feature
            if 'version' not in entry:
                entry['version'] = _next_version
            if 'parent_id' not in entry:
                entry['parent_id'] = _parent_id
            if 'created_by' not in entry:
                entry['created_by'] = 'system'

            use_evt = {'ts': now_iso}
            if pipeline_id:
                use_evt['pipeline_id'] = pipeline_id
            if stage:
                use_evt['stage'] = stage
            if topic:
                use_evt['topic'] = topic

            hist = entry.get('use_history', [])
            # P-03: smoke/gatecheck runs leave no use_history trail — the
            # registry is a production provenance record.
            if not _is_test_pid(pipeline_id):
                hist.append(use_evt)
            if len(hist) > 500:
                hist = hist[-500:]
            entry['use_history'] = hist

            reg['prompts'] = prompts
            with open(reg_path, 'w') as _wf:
                json.dump(reg, _wf, indent=2)
    except Exception as _rpe:
        _zyg_log.info(f'[PROMPT REGISTRY] Failed: {_rpe}')
    return prompt_id
