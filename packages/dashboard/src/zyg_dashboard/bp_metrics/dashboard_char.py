# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The character-generation, caveman-token and per-pipeline aggregations of
_compute_metrics_dashboard().

Each function below is one of the former bp_metrics.py's banner-delimited blocks,
lifted out of the 947-line _compute_metrics_dashboard() at its original four-space
indent so the moved code is byte-for-byte what it was; the parameters and the
returned tuples are exactly that block's inbound and outbound locals.
"""

import json
import os

from zyg_dashboard.bp_metrics import _dsl, _zyg_log
from zyg_dashboard.bp_metrics.aggregate import _metrics_fmt_duration, _metrics_normalize_stage
from zyg_dashboard.crewai_web_gui import _METRICS_PIPELINE_LABELS
from zyg_dashboard.gui.timeutil import _parse_iso_to_ams


def _aggregate_char_gen(_glob, runtime_dir, calls_by_pipeline_type, cost_by_pipeline_type):
    # ── Character generation aggregation ──────────────────────────────────────
    # Reads char_gen_<id>.json files written by _char_save_state(). Each file
    # is a snapshot of a single character generation job including its
    # stage_timeline, started/ended timestamps, render_mode and dataset size.
    char_state_files = _glob.glob(os.path.join(runtime_dir, 'char_gen_*.json'))
    char_total = 0
    char_done = 0
    char_failed = 0
    char_running = 0
    char_durations: list[float] = []
    char_stage_totals: dict[str, list[float]] = {}
    char_render_mode_counts: dict[str, int] = {}
    char_image_count_samples: list[int] = []
    char_mf_counts: dict[str, int] = {}
    char_style_counts: dict[str, int] = {}
    char_genre_counts: dict[str, int] = {}
    char_brief_prose_count = 0
    char_lora_flux_durations: list[float] = []
    char_lora_sdxl_durations: list[float] = []
    recent_char_runs: list[dict] = []
    lora_attempts = 0
    lora_successes = 0
    lora_durations: list[float] = []
    lora_total_steps: list[int] = []
    preview_render_durations: list[float] = []
    blender_durations: list[float] = []
    most_recent_char_done_iso: str | None = None
    most_recent_char_done_id: str | None = None

    for _cf in char_state_files:
        try:
            with open(_cf) as _fh:
                cs = json.load(_fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('skipping character state that could not be read: %s', _exc)
            continue
        char_total += 1
        _status = (cs.get('status') or '').lower()
        if _status == 'done':
            char_done += 1
            # Track most recent completion for the dashboard "last character" stat
            _ended = cs.get('ended') or ''
            if _ended and (most_recent_char_done_iso is None or _ended > most_recent_char_done_iso):
                most_recent_char_done_iso = _ended
                most_recent_char_done_id = cs.get('char_id') or ''
        elif _status == 'error':
            char_failed += 1
        elif _status == 'running':
            char_running += 1

        _cparams = cs.get('params') or {}
        _cmf = (cs.get('model_family') or _cparams.get('model_family') or 'unknown').strip().lower()
        char_mf_counts[_cmf] = char_mf_counts.get(_cmf, 0) + 1
        _cstyle = (_cparams.get('style') or _cparams.get('render_style') or 'unknown').strip().lower()
        char_style_counts[_cstyle] = char_style_counts.get(_cstyle, 0) + 1
        _cgenre = (_cparams.get('genre') or 'general').strip().lower()
        char_genre_counts[_cgenre] = char_genre_counts.get(_cgenre, 0) + 1
        if (_cparams.get('character_brief_prose') or '').strip():
            char_brief_prose_count += 1

        _char_dur = None
        # Wall-clock duration (start → end)
        if cs.get('started') and cs.get('ended'):
            try:
                _cs_s = _parse_iso_to_ams(cs['started'])
                _cs_e = _parse_iso_to_ams(cs['ended'])
                if _cs_s and _cs_e:
                    _char_dur = (_cs_e - _cs_s).total_seconds()
                    if _char_dur >= 0:
                        char_durations.append(_char_dur)
            except Exception as _exc:
                _zyg_log.debug('character start/end timestamps unparseable, duration skipped: %s', _exc)

        recent_char_runs.append(
            {
                'id': (cs.get('char_id') or '')[:12],
                'name': (_cparams.get('name') or '')[:24],
                'status': _status,
                'model_family': _cmf,
                'style': _cstyle,
                'genre': _cgenre,
                'started': cs.get('started') or '',
                'duration_s': _char_dur,
                'has_brief': bool((_cparams.get('character_brief_prose') or '').strip()),
            }
        )

        # Wall-clock duration (start → end) — legacy path removed (handled above)

        # Render mode + dataset size
        _rm = cs.get('render_mode') or 'unknown'
        char_render_mode_counts[_rm] = char_render_mode_counts.get(_rm, 0) + 1
        if isinstance(cs.get('image_count'), int) and cs['image_count'] > 0:
            char_image_count_samples.append(int(cs['image_count']))

        # Per-stage timings
        for _st in cs.get('stage_timeline') or []:
            _name = _metrics_normalize_stage(_st.get('name') or '')
            _elapsed = _st.get('elapsed_s')
            if not _name or _elapsed is None:
                continue
            try:
                _elapsed = float(_elapsed)
            except (TypeError, ValueError) as _exc:
                _zyg_log.debug('skipping stage with a non-numeric elapsed_s: %s', _exc)
                continue
            char_stage_totals.setdefault(_name, []).append(_elapsed)

            _raw_name = _st.get('name') or ''
            # Specialised buckets
            if 'LoRA Training' in _raw_name or 'LoRA' in _raw_name:
                lora_attempts += 1
                if (_st.get('status') or '').lower() == 'completed':
                    lora_successes += 1
                    lora_durations.append(_elapsed)
                    _extra = _st.get('extra') or {}
                    if isinstance(_extra.get('total_steps'), int):
                        lora_total_steps.append(int(_extra['total_steps']))
                    if 'FLUX' in _raw_name.upper():
                        char_lora_flux_durations.append(_elapsed)
                    elif 'SDXL' in _raw_name.upper():
                        char_lora_sdxl_durations.append(_elapsed)
            elif 'Preview Render' in _raw_name and (_st.get('status') or '').lower() == 'completed':
                preview_render_durations.append(_elapsed)
            elif ('Character Render' in _raw_name or 'Blender' in _raw_name) and (
                _st.get('status') or ''
            ).lower() == 'completed':
                blender_durations.append(_elapsed)

    char_success_rate = round(char_done / char_total * 100, 1) if char_total else 0
    avg_char_duration = round(sum(char_durations) / len(char_durations)) if char_durations else 0
    lora_success_rate = round(lora_successes / lora_attempts * 100, 1) if lora_attempts else 0
    avg_lora_duration = round(sum(lora_durations) / len(lora_durations)) if lora_durations else 0
    avg_lora_flux = (
        round(sum(char_lora_flux_durations) / len(char_lora_flux_durations)) if char_lora_flux_durations else 0
    )
    avg_lora_sdxl = (
        round(sum(char_lora_sdxl_durations) / len(char_lora_sdxl_durations)) if char_lora_sdxl_durations else 0
    )
    avg_preview_duration = (
        round(sum(preview_render_durations) / len(preview_render_durations)) if preview_render_durations else 0
    )
    avg_blender_duration = round(sum(blender_durations) / len(blender_durations)) if blender_durations else 0
    avg_dataset_size = (
        round(sum(char_image_count_samples) / len(char_image_count_samples), 1) if char_image_count_samples else 0
    )
    avg_lora_steps = int(round(sum(lora_total_steps) / len(lora_total_steps))) if lora_total_steps else 0
    recent_char_runs.sort(key=lambda x: x.get('started') or '', reverse=True)
    recent_char_runs = recent_char_runs[:10]
    char_brief_token_calls = calls_by_pipeline_type.get('character_brief', 0)
    char_brief_token_cost = cost_by_pipeline_type.get('character_brief', 0.0)

    return (
        avg_blender_duration,
        avg_char_duration,
        avg_dataset_size,
        avg_lora_duration,
        avg_lora_flux,
        avg_lora_sdxl,
        avg_lora_steps,
        avg_preview_duration,
        blender_durations,
        char_brief_prose_count,
        char_brief_token_calls,
        char_brief_token_cost,
        char_done,
        char_durations,
        char_failed,
        char_genre_counts,
        char_image_count_samples,
        char_mf_counts,
        char_render_mode_counts,
        char_running,
        char_stage_totals,
        char_style_counts,
        char_success_rate,
        char_total,
        lora_attempts,
        lora_success_rate,
        lora_successes,
        most_recent_char_done_id,
        most_recent_char_done_iso,
        preview_render_durations,
        recent_char_runs,
    )


def _aggregate_caveman(tok_entries):
    # ── Caveman token impact (tagged calls only; legacy rows lack caveman_mode) ─
    _env_caveman_level = 'off'
    try:
        if _dsl is not None and _dsl.caveman_active():
            _lvl = _dsl.caveman_level()
            _env_caveman_level = _lvl.value if _lvl is not None else 'extended'
    except Exception as _exc:
        _zyg_log.debug('caveman level unavailable, reporting off: %s', _exc)

    def _avg_tok(entries: list, field: str) -> int:
        vals = [int(e.get(field, 0)) for e in entries if e.get(field) is not None]
        return round(sum(vals) / len(vals)) if vals else 0

    _cave_tagged = [e for e in tok_entries if (e.get('caveman_mode') or '').strip()]
    _cave_untagged = [e for e in tok_entries if not (e.get('caveman_mode') or '').strip()]
    _avg_comp_tagged = _avg_tok(_cave_tagged, 'completion_tokens')
    _avg_comp_untagged = _avg_tok(_cave_untagged, 'completion_tokens')
    _avg_total_tagged = _avg_tok(_cave_tagged, 'total_tokens')
    _avg_total_untagged = _avg_tok(_cave_untagged, 'total_tokens')
    _completion_savings_pct = None
    _total_savings_pct = None
    if _avg_comp_untagged and _avg_comp_tagged and _cave_tagged:
        _completion_savings_pct = round((1 - _avg_comp_tagged / _avg_comp_untagged) * 100, 1)
    if _avg_total_untagged and _avg_total_tagged and _cave_tagged:
        _total_savings_pct = round((1 - _avg_total_tagged / _avg_total_untagged) * 100, 1)

    _cave_by_mode: dict[str, dict] = {}
    for _ce in _cave_tagged:
        _cm = _ce.get('caveman_mode') or 'unknown'
        _cave_by_mode.setdefault(_cm, {'calls': 0, 'completion_tokens': 0, 'total_tokens': 0})
        _cave_by_mode[_cm]['calls'] += 1
        _cave_by_mode[_cm]['completion_tokens'] += int(_ce.get('completion_tokens', 0))
        _cave_by_mode[_cm]['total_tokens'] += int(_ce.get('total_tokens', 0))
    _cave_modes_out = [
        {
            'mode': m,
            'label': {
                'planner': 'System planner (JSON)',
                'user_planner': 'User planner (JSON)',
                'system': 'System chat (Agent Zero)',
            }.get(m, m),
            'calls': d['calls'],
            'avg_completion': round(d['completion_tokens'] / d['calls']) if d['calls'] else 0,
            'avg_total': round(d['total_tokens'] / d['calls']) if d['calls'] else 0,
        }
        for m, d in sorted(_cave_by_mode.items(), key=lambda x: -x[1]['calls'])
    ]

    _cave_by_pt: dict[str, dict] = {}
    for _ce in _cave_tagged:
        _cpt = _ce.get('pipeline_type') or 'unknown'
        _cave_by_pt.setdefault(_cpt, {'calls': 0, 'completion_tokens': 0})
        _cave_by_pt[_cpt]['calls'] += 1
        _cave_by_pt[_cpt]['completion_tokens'] += int(_ce.get('completion_tokens', 0))
    _cave_pipelines_out = [
        {
            'type': pt,
            'label': _METRICS_PIPELINE_LABELS.get(pt, pt.replace('_', ' ').title()),
            'calls': d['calls'],
            'avg_completion': round(d['completion_tokens'] / d['calls']) if d['calls'] else 0,
        }
        for pt, d in sorted(_cave_by_pt.items(), key=lambda x: -x[1]['calls'])
    ]

    caveman_detail = {
        'env_level': _env_caveman_level,
        'active': _env_caveman_level != 'off',
        'tagged_calls': len(_cave_tagged),
        'untagged_calls': len(_cave_untagged),
        'avg_completion_tagged': _avg_comp_tagged,
        'avg_completion_untagged': _avg_comp_untagged,
        'avg_total_tagged': _avg_total_tagged,
        'avg_total_untagged': _avg_total_untagged,
        'completion_savings_pct': _completion_savings_pct,
        'total_savings_pct': _total_savings_pct,
        'by_mode': _cave_modes_out,
        'by_pipeline_type': _cave_pipelines_out,
        'deployed_sites': [
            'JSON planners (video, manga, storyteller, character brief)',
            'Clipfarm director + clip picker',
            'Crime visual tags + Haiku prefill',
            'Agent Zero chat (system)',
        ],
    }

    return _cave_tagged, _env_caveman_level, caveman_detail


def _build_pipelines_out(pipelines_by_dept, cost_by_pipeline_type, calls_by_pipeline_type, char_stage_totals):
    # Build pipeline list for API (story departments + token-only types)
    pipelines_out: list[dict] = []
    for dept_key, pb in sorted(pipelines_by_dept.items(), key=lambda x: -x[1]['total']):
        _durs = pb['durations']
        _avg_d = round(sum(_durs) / len(_durs)) if _durs else 0
        _stages_out = [
            {
                'name': sn,
                'avg_s': round(sum(ts) / len(ts)),
                'avg_label': _metrics_fmt_duration(sum(ts) / len(ts)),
                'runs': len(ts),
            }
            for sn, ts in sorted(pb['stages'].items(), key=lambda x: -sum(x[1]))
        ]
        pipelines_out.append(
            {
                'id': dept_key,
                'label': pb['label'],
                'total': pb['total'],
                'completed': pb['completed'],
                'failed': pb['failed'],
                'running': pb['running'],
                'success_rate': round(pb['completed'] / pb['total'] * 100, 1) if pb['total'] else 0,
                'avg_duration_s': _avg_d,
                'avg_duration_label': _metrics_fmt_duration(_avg_d),
                'stages': _stages_out,
                'api_cost_usd': round(cost_by_pipeline_type.get(dept_key, 0.0), 4),
                'api_calls': calls_by_pipeline_type.get(dept_key, 0),
            }
        )
    for pt_key, pt_cost in sorted(cost_by_pipeline_type.items(), key=lambda x: -x[1]):
        if pt_key in pipelines_by_dept:
            continue
        if pt_cost <= 0 and calls_by_pipeline_type.get(pt_key, 0) <= 0:
            continue
        pipelines_out.append(
            {
                'id': pt_key,
                'label': _METRICS_PIPELINE_LABELS.get(pt_key, pt_key.replace('_', ' ').title()),
                'total': calls_by_pipeline_type.get(pt_key, 0),
                'completed': calls_by_pipeline_type.get(pt_key, 0),
                'failed': 0,
                'running': 0,
                'success_rate': 100.0 if calls_by_pipeline_type.get(pt_key, 0) else 0,
                'avg_duration_s': 0,
                'avg_duration_label': '—',
                'stages': [],
                'api_cost_usd': round(pt_cost, 4),
                'api_calls': calls_by_pipeline_type.get(pt_key, 0),
                'token_only': True,
            }
        )

    char_stages_out = [
        {
            'name': sn,
            'avg_s': round(sum(ts) / len(ts)),
            'avg_label': _metrics_fmt_duration(sum(ts) / len(ts)),
            'runs': len(ts),
        }
        for sn, ts in sorted(char_stage_totals.items(), key=lambda x: -sum(x[1]))
    ]

    return pipelines_out, char_stages_out
