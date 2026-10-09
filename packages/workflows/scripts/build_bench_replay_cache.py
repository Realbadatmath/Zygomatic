#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
build_bench_replay_cache.py
============================
One-time script: extract real Claude outputs from existing pipeline state files
and write them to data/runtime/bench_replay_cache.json.

The benchmark then uses this cache (ZYG_BENCH_REPLAY=1) to replay those same
outputs instead of making live API calls — zero cost, real data.

Extracted per pipeline:
  stage_3        → narration script + scene list + YouTube meta
  stage_3b       → visual scene descriptions (one per narration sentence)
  stage_3_5a     → time-locked scene list (reuses scene_descs, N-image count)
  stage_3_5      → FLUX image prompts (from essay_images[].prompt)
  stage_3_5_ref  → one refined prompt sample (first essay_image prompt)

Usage:
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  ../.venv/bin/python scripts/build_bench_replay_cache.py

  # Override which pipeline to use as primary source:
  ZYG_BENCH_REPLAY_SRC=<pipeline_id> \\
    ../.venv/bin/python scripts/build_bench_replay_cache.py

Output: data/runtime/bench_replay_cache.json
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

_CREWS = Path(__file__).resolve().parents[1]
_RUNTIME = _CREWS / 'data' / 'runtime'
_OUT = _RUNTIME / 'bench_replay_cache.json'

_PREFERRED_SRC = os.environ.get('ZYG_BENCH_REPLAY_SRC', '').strip()

# Minimum thresholds for a pipeline to be usable as a source.
_MIN_SCRIPT_WORDS = 400
_MIN_FLUX_IMAGES = 10
_MIN_VISUAL_TAGS = 20


def _log(msg: str) -> None:
    print(f'[build-replay] {msg}', flush=True)


def _score_pipeline(d: dict) -> int:
    """Higher = better source candidate."""
    score = 0
    score += min(len((d.get('script') or '').split()), 2000)
    score += len(d.get('essay_images') or []) * 10
    score += len(d.get('visual_tags') or []) * 2
    score += 500 if d.get('youtube_title') else 0
    score += 200 if d.get('youtube_description') else 0
    # Prefer pipelines where visual_tags have scene_desc filled in
    vt = d.get('visual_tags') or []
    score += sum(1 for v in vt if v.get('scene_desc')) * 3
    return score


def _find_best_pipeline() -> tuple[str, dict] | None:
    state_files = sorted(
        glob.glob(str(_RUNTIME / 'pipeline_*_state.json')),
        key=os.path.getsize,
        reverse=True,
    )
    if not state_files:
        _log('ERROR: no pipeline state files found')
        return None

    # If a preferred source was specified, try it first.
    if _PREFERRED_SRC:
        for f in state_files:
            if _PREFERRED_SRC in f:
                try:
                    with open(f, encoding='utf-8') as fh:
                        d = json.load(fh)
                    if d.get('department') == 'scholarly':
                        _log(f'Using preferred source: {Path(f).name}')
                        return f, d
                except Exception as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        _log(f'WARN: preferred source {_PREFERRED_SRC} not found or not scholarly — scanning all')

    best_f, best_d, best_score = None, None, -1
    for f in state_files:
        try:
            with open(f, encoding='utf-8') as fh:
                d = json.load(fh)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        if d.get('department') != 'scholarly':
            continue
        script_words = len((d.get('script') or '').split())
        n_images = len(d.get('essay_images') or [])
        n_vt = len(d.get('visual_tags') or [])
        if script_words < _MIN_SCRIPT_WORDS or n_images < _MIN_FLUX_IMAGES or n_vt < _MIN_VISUAL_TAGS:
            continue
        score = _score_pipeline(d)
        if score > best_score:
            best_f, best_d, best_score = f, d, score

    if best_f:
        _log(f'Best source (score={best_score}): {Path(best_f).name}')
        return best_f, best_d
    return None


def _build_cache(src_file: str, d: dict) -> dict:
    pid = d.get('pipeline_id', Path(src_file).stem.replace('pipeline_', '').replace('_state', ''))
    script = (d.get('script') or '').strip()
    vt = d.get('visual_tags') or []
    ei = d.get('essay_images') or []
    yt_title = d.get('youtube_title') or ''
    yt_desc = d.get('youtube_description') or ''
    yt_tags = d.get('youtube_tags') or []

    # ── stage_3: script + scene list + YouTube metadata ─────────────────────
    # scene_list mirrors what _parse_stage3_resp returns from [VISUAL_SCENES].
    # We reconstruct it from visual_tags scene_desc values (same data, already extracted).
    scene_descs_from_vt = [v.get('scene_desc', '') for v in vt if v.get('scene_desc')]

    stage_3 = {
        'script': script,
        'scene_list': scene_descs_from_vt,
        'youtube_title': yt_title,
        'youtube_description': yt_desc,
        'youtube_tags': yt_tags,
        # Synthetic usage numbers (realistic approximations for _record_token_usage)
        'usage': {
            'input_tokens': min(len(script.split()) * 2, 8000),
            'output_tokens': len(script.split()),
        },
    }
    _log(f'stage_3: {len(script.split())} words, {len(scene_descs_from_vt)} scene descs')

    # ── stage_3b: scene descriptions (one per narration sentence) ───────────
    # Used by _llm_scene_batch — returns a list of scene_desc strings.
    # We store a flat list; the batch function cycles through it for any length batch.
    stage_3b_scene_descs = [v.get('scene_desc', v.get('tag', '')) for v in vt]
    _log(f'stage_3b: {len(stage_3b_scene_descs)} sentence scene descs')

    # ── stage_3_5a: time-locked scene list ──────────────────────────────────
    # Stage 3.5a assigns N scene descriptions (one per image slot) keyed to
    # word timings. We provide the same scene_descs pool; the pipeline will
    # truncate to _tls_n_images automatically.
    stage_3_5a_scene_list = scene_descs_from_vt
    _log(f'stage_3_5a: {len(stage_3_5a_scene_list)} scene descs (pipeline will truncate to N images)')

    # ── stage_3_5: FLUX image prompts ───────────────────────────────────────
    # essay_images[].prompt is the exact FLUX prompt that was generated and used.
    flux_prompts = [img.get('prompt', '') for img in ei if img.get('prompt')]
    _log(f'stage_3_5: {len(flux_prompts)} FLUX prompts')

    # ── stage_3_5_ref: refined prompt sample ────────────────────────────────
    # Used by the per-segment FLUX anchor refinement call (returns one prompt string).
    # We pick the longest prompt as the most complete example.
    stage_3_5_refined = max(flux_prompts, key=len) if flux_prompts else ''
    _log(f'stage_3_5_ref: {len(stage_3_5_refined)} chars')

    return {
        'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source_pipeline_id': pid,
        'source_file': Path(src_file).name,
        'source_topic': d.get('scholarly_topic') or d.get('essay_title') or '',
        'stage_3': stage_3,
        'stage_3b_scene_descs': stage_3b_scene_descs,
        'stage_3_5a_scene_list': stage_3_5a_scene_list,
        'stage_3_5_flux_prompts': flux_prompts,
        'stage_3_5_refined_prompt': stage_3_5_refined,
    }


def main() -> int:
    result = _find_best_pipeline()
    if not result:
        _log('FATAL: no suitable scholarly pipeline found — run at least one full pipeline first')
        return 1

    src_file, d = result
    cache = _build_cache(src_file, d)

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding='utf-8')
    _log(f'Cache written: {_OUT}')
    _log(f'  source topic:   {cache["source_topic"]}')
    _log(f'  script words:   {len((cache["stage_3"]["script"]).split())}')
    _log(f'  scene descs:    {len(cache["stage_3b_scene_descs"])}')
    _log(f'  flux prompts:   {len(cache["stage_3_5_flux_prompts"])}')
    _log('')
    _log('Run benchmarks with ZYG_BENCH_REPLAY=1 to use this cache instead of live API calls.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
