# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_benchmark — frequency, calibration and benchmark-history routes.

Moved verbatim out of bp_benchmark.py; see the package __init__ for the full rationale.
"""

from zyg_dashboard.gui.telemetry import _TELEMETRY_CACHE
from zyg_dashboard.gui.timeutil import _ams_iso
from zyg_dashboard.crewai_web_gui import _apply_gpu_power_limit
from zyg_dashboard.gui.telemetry import _backend_debug
from zyg_dashboard.crewai_web_gui import _bm_infra_lock
from zyg_dashboard.gui.runtime_state import _runtime_path
from zyg_dashboard.gui.runtime_state import _workflow_jobs
from zyg_workflows import gui_state
import json
from flask import jsonify
import os
from flask import request
from zyg_dashboard.bp_benchmark.state import _bm_infra_runs, _recent_state_files, _zyg_log, bp
from zyg_dashboard.bp_benchmark.infra_worker import _bm_infra_worker


@bp.route('/api/frequency/data')
def api_frequency_data():
    """GET live telemetry snapshot for the Frequency waveform tab.
    Returns overall hardware metrics + active stage/entity information."""
    telem = dict(_TELEMETRY_CACHE)
    gpu0 = (telem.get('gpus') or [{}])[0]
    import psutil as _ps

    _ram = _ps.virtual_memory()

    # Determine active pipeline and stage
    active_pipeline_id = ''
    active_stages = []
    active_entities = []
    pipeline_topic = ''
    for _pid, _job in list(_workflow_jobs.items()):
        if _job.get('status') == 'running':
            active_pipeline_id = _pid
            _stage = _job.get('stage', '')
            if _stage:
                active_stages.append(_stage)
            break

    # Map stage → primary entities (used for amplitude attribution).
    # These are entity *labels*, not programs to run, so they stay bare names.
    _ENT_FFMPEG = 'ffmpeg'
    _STAGE_ENTITY_MAP = {
        'Stage 1': ['claude-sonnet-4-6'],
        'Stage 2': ['claude-sonnet-4-6'],
        'Stage 3': ['claude-sonnet-4-6'],
        'Stage 3b': ['qwen3.5:9b'],
        # qwen2.5:72b REMOVED 2026-08-26 — Qwen Research licence, non-commercial only.
        'Stage 3.1': ['qwen3.6:35b-a3b'],
        'Stage 3.5': ['flux.1-schnell', 'controlnet', 'ipadapter'],
        'Stage 3.6': ['controlnet', 'realesrgan'],
        'Stage 4': ['indextts2', 'chatterbox', 'whisper'],
        'Stage 5': [_ENT_FFMPEG],
        'Stage 6': [_ENT_FFMPEG, 'rife'],
    }
    for _s in active_stages:
        for _k, _ents in _STAGE_ENTITY_MAP.items():
            if _k.lower() in _s.lower():
                active_entities.extend(_ents)
                break

    # Try to get topic from state file
    if active_pipeline_id:
        _sf = _runtime_path(f'pipeline_{active_pipeline_id}_state.json')
        if os.path.isfile(_sf):
            try:
                with open(_sf, 'r', encoding='utf-8') as _f:
                    _st = json.load(_f)
                pipeline_topic = _st.get('scholarly_topic') or _st.get('essay_title') or _st.get('topic', '')
            except Exception as _exc:
                _zyg_log.debug('pipeline topic lookup failed, leaving it blank: %s', _exc)

    return jsonify(
        {
            'timestamp': _ams_iso(),
            'live': {
                'gpu_util_pct': float(gpu0.get('utilization_pct', 0) or 0),
                'vram_used_mb': float(gpu0.get('memory_used_mb', 0) or 0),
                'vram_total_mb': float(gpu0.get('memory_total_mb', 49140) or 49140),
                'gpu_temp_c': float(gpu0.get('temperature_c', 0) or 0),
                'gpu_power_w': float(gpu0.get('power_w', 0) or 0),
                'cpu_pct': float(telem.get('cpu_pct', 0) or 0),
                'ram_used_mb': float(_ram.used / 1024 / 1024),
                'ram_total_mb': float(_ram.total / 1024 / 1024),
                'ram_pct': float(_ram.percent),
            },
            'calibration': dict(gui_state._CALIBRATION),
            'active_pipeline_id': active_pipeline_id,
            'active_stages': active_stages,
            'active_entities': list(set(active_entities)),
            'pipeline_topic': pipeline_topic,
        }
    )


@bp.route('/api/frequency/history')
def api_frequency_history():
    """GET list of pipeline runs that have telemetry CSVs, newest first."""

    runs = []
    for sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 200):
        try:
            with open(sf, 'r', encoding='utf-8') as _f:
                st = json.load(_f)
            pid = st.get('pipeline_id', '')
            if not pid:
                continue
            has_telem = os.path.isfile(_runtime_path(f'telemetry_{pid}.csv'))
            runs.append(
                {
                    'id': pid,
                    'department': st.get('department', 'unknown'),
                    'topic': st.get('scholarly_topic') or st.get('essay_title') or st.get('topic', ''),
                    'started': st.get('started', ''),
                    'ended': st.get('ended', ''),
                    'status': 'failed' if st.get('error') else ('completed' if st.get('ended') else 'unknown'),
                    'has_telemetry': has_telem,
                    'stages': len(st.get('stage_timeline', [])),
                    'elapsed_s': float(st.get('total_elapsed_s', 0) or 0),
                }
            )
        except Exception as _exc:
            _zyg_log.debug('skipping run whose state could not be summarised: %s', _exc)
    return jsonify({'runs': runs, 'total': len(runs)})


@bp.route('/api/frequency/history/<pipeline_id>')
def api_frequency_history_run(pipeline_id):
    """GET full telemetry data + stage timeline for a specific pipeline run."""
    import re
    import csv as _csv

    if not re.match(r'^[0-9a-zA-Z\-]{8,64}$', pipeline_id):
        return jsonify({'error': 'invalid pipeline_id'}), 400

    sf = _runtime_path(f'pipeline_{pipeline_id}_state.json')
    tcsvp = _runtime_path(f'telemetry_{pipeline_id}.csv')

    if not os.path.isfile(sf):
        return jsonify({'error': 'pipeline not found'}), 404

    try:
        with open(sf, 'r', encoding='utf-8') as _f:
            st = json.load(_f)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Read telemetry CSV
    telemetry_rows = []
    if os.path.isfile(tcsvp):
        try:
            with open(tcsvp, 'r', encoding='utf-8') as _f:
                reader = _csv.DictReader(_f)
                for row in reader:
                    try:
                        telemetry_rows.append(
                            {
                                'ts': row.get('timestamp', ''),
                                'cpu_pct': float(row.get('cpu_pct_raw', 0) or 0),
                                'gpu_util_pct': float(row.get('gpu_util_pct', 0) or 0),
                                'vram_used_mb': float(row.get('gpu_mem_used_mb', 0) or 0),
                                'vram_total_mb': float(row.get('gpu_mem_total_mb', 49140) or 49140),
                                'gpu_power_w': float(row.get('gpu_power_w', 0) or 0),
                                'gpu_temp_c': float(row.get('gpu_temp_c', 0) or 0),
                            }
                        )
                    except Exception as _exc:
                        _zyg_log.debug('skipping telemetry row with unusable numbers: %s', _exc)
        except Exception as _exc:
            _zyg_log.warning('telemetry read failed, the run chart has no samples: %s', _exc)

    # Build stage offsets relative to pipeline start
    started = st.get('started', '')
    stages = []
    for stg in st.get('stage_timeline', []):
        stages.append(
            {
                'name': stg.get('name', ''),
                'started_at': stg.get('started_at', ''),
                'ended_at': stg.get('ended_at', ''),
                'elapsed_s': float(stg.get('elapsed_s', 0) or 0),
                'extra': stg.get('extra', {}),
            }
        )

    return jsonify(
        {
            'pipeline_id': pipeline_id,
            'department': st.get('department', ''),
            'topic': st.get('scholarly_topic') or st.get('essay_title') or st.get('topic', ''),
            'started': started,
            'ended': st.get('ended', ''),
            'total_elapsed_s': float(st.get('total_elapsed_s', 0) or 0),
            'telemetry': telemetry_rows,
            'stages': stages,
        }
    )


@bp.route('/api/calibrate', methods=['GET'])
def api_calibrate_get():
    """GET current hardware calibration hard limits."""
    return jsonify({'success': True, 'calibration': dict(gui_state._CALIBRATION)})


@bp.route('/api/calibrate', methods=['POST'])
def api_calibrate_post():
    """POST updated calibration hard limits. Applies immediately to all pipeline stage gates."""
    pass  # (global stmt removed: names moved to gui_state)
    data = request.get_json(force=True, silent=True) or {}
    _BOUNDS = {
        'max_vram_gb': (4.0, 128.0, 48.0),
        'max_gpu_watts': (50.0, 600.0, 450.0),
        'max_cpu_pct': (10.0, 100.0, 80.0),
        'max_ram_gb': (4.0, 512.0, 56.0),
    }
    errors, updates = [], {}
    for key, (lo, hi, _default) in _BOUNDS.items():
        if key in data:
            try:
                v = float(data[key])
                if not (lo <= v <= hi):
                    errors.append(f'{key} must be {lo}–{hi}, got {v}')
                else:
                    updates[key] = v
            except (ValueError, TypeError):
                errors.append(f'{key} must be a number')
    if errors:
        return jsonify({'success': False, 'errors': errors}), 400
    gui_state._CALIBRATION.update(updates)
    # Apply GPU power limit at driver level whenever wattage changes
    hw_msg = ''
    if 'max_gpu_watts' in updates:
        _pw_err = _apply_gpu_power_limit(updates['max_gpu_watts'])
        if _pw_err:
            _backend_debug(f'nvidia-smi power-limit warning: {_pw_err}')
            hw_msg = f'Warning: nvidia-smi power-limit: {_pw_err}'
        else:
            hw_msg = f'GPU driver power limit set to {int(updates["max_gpu_watts"])}W'
    _backend_debug(f'Calibration updated: {gui_state._CALIBRATION}')
    return jsonify({'success': True, 'calibration': dict(gui_state._CALIBRATION), 'hw_msg': hw_msg})


@bp.route('/api/benchmark/pipeline_history')
def api_benchmark_pipeline_history():
    """Aggregate stage timing from all completed pipeline state files."""

    PIPELINE_TYPES = ('scholarly', 'crime', 'video', 'manga', 'storyteller')
    STAGE_ORDER = {
        'scholarly': [
            'Stage 1: Topic Setup',
            'Stage 2: Academic Research',
            'Stage 3: Script Preparation',
            'Stage 3b: Visual Tagging',
            'Stage 3.1: Emotion Analysis',
            'Stage 3.5: AI Image Generation',
            'Stage 3.6: Anatomy Repair',
            'Stage 4: TTS Narration',
            'Stage 5: Stock Footage',
            'Stage 6: Video Assembly',
            'Color Grade',
            'Subtitle Burn',
        ],
        'crime': [
            'Stage 1: Topic Setup',
            'Stage 2: Academic Research',
            'Stage 3: Script Preparation',
            'Stage 3b: Visual Tagging',
            'Stage 3.1: Emotion Analysis',
            'Stage 3.5: AI Image Generation',
            'Stage 3.6: Anatomy Repair',
            'Stage 4: TTS Narration',
            'Stage 5: Stock Footage',
            'Stage 6: Video Assembly',
            'Color Grade',
            'Subtitle Burn',
        ],
        'video': [
            'Stage 0: Pipeline Startup',
            'Stage 1: Scene Planning',
            'Stage 2: Image Prep',
            'Stage 3.5: AI Image Generation',
            'Stage 4: TTS Narration',
            'Stage 5: Video Generation',
            'Stage 6: Video Assembly',
            'Color Grade',
        ],
        'manga': [
            'Stage 0: Pipeline Startup',
            'Stage 1: Scene Planning',
            'Stage 2: Image Prep',
            'Stage 3.5: AI Image Generation',
            'Stage 4: TTS Narration',
            'Stage 6: Video Assembly',
            'Color Grade',
        ],
        'storyteller': [
            'Stage 1: Character Prep',
            'Stage 2: Story Script',
            'Stage 3: TTS Narration',
            'Stage 3.5: AI Image Generation',
            'Stage 4: Ken Burns',
            'Stage 5: Final Assembly',
        ],
    }

    buckets: dict = {pt: {'samples': {}, 'runs': []} for pt in PIPELINE_TYPES}

    state_files = _recent_state_files(_runtime_path('pipeline_*_state.json'), 500)

    for _sf in state_files:
        try:
            with open(_sf, 'r', encoding='utf-8') as _fh:
                _st = json.load(_fh)
            dept = (_st.get('department') or '').lower()
            if dept not in buckets:
                continue
            if not _st.get('ended') and _st.get('status') != 'completed':
                continue
            timeline = _st.get('stage_timeline') or []
            if not timeline:
                continue

            total_s = None
            try:
                from datetime import datetime as _dt

                _ts = (_st.get('started') or '').replace('Z', '+00:00')
                _te = (_st.get('ended') or '').replace('Z', '+00:00')
                if _ts and _te:
                    total_s = round((_dt.fromisoformat(_te) - _dt.fromisoformat(_ts)).total_seconds(), 1)
            except Exception as _exc:
                _zyg_log.debug('run start/end timestamps unparseable, total elapsed left unset: %s', _exc)

            run_stages: dict = {}
            for _stage in timeline:
                if _stage.get('status') != 'completed':
                    continue
                _name = (_stage.get('name') or '').strip()
                _elapsed = float(_stage.get('elapsed_s') or 0)
                if not _name or _elapsed <= 0:
                    continue
                buckets[dept]['samples'].setdefault(_name, []).append(_elapsed)
                run_stages[_name] = round(_elapsed, 1)

            buckets[dept]['runs'].append(
                {
                    'id': (_st.get('pipeline_id') or '')[:12],
                    'started': (_st.get('started') or '')[:10],
                    'total_s': total_s,
                    'stages': run_stages,
                }
            )
        except Exception as _exc:
            _zyg_log.debug('skipping run that could not be bucketed: %s', _exc)

    result: dict = {}
    for dept, data in buckets.items():
        order_map = {n: i for i, n in enumerate(STAGE_ORDER.get(dept, []))}
        stage_stats: dict = {}
        for sname, times in data['samples'].items():
            times_s = sorted(times)
            n = len(times_s)
            stage_stats[sname] = {
                'avg_s': round(sum(times_s) / n, 1),
                'min_s': round(min(times_s), 1),
                'max_s': round(max(times_s), 1),
                'p50_s': round(times_s[int(n * 0.50)], 1),
                'p95_s': round(times_s[min(int(n * 0.95), n - 1)], 1),
                'last_s': round(times_s[-1], 1),
                'count': n,
                'order': order_map.get(sname, 999),
            }
        result[dept] = {
            'run_count': len(data['runs']),
            'stages': stage_stats,
            'trend': data['runs'][-20:],
        }

    return jsonify(result)


@bp.route('/api/benchmark/seeds')
def api_benchmark_seeds():
    """Return most-recent completed job per pipeline that still has assets on disk."""

    PIPELINE_TYPES = ('scholarly', 'crime', 'video', 'manga', 'storyteller')
    seeds: dict = {}

    for _sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 300):
        if len(seeds) == len(PIPELINE_TYPES):
            break
        try:
            with open(_sf, 'r', encoding='utf-8') as _fh:
                _st = json.load(_fh)
            dept = (_st.get('department') or '').lower()
            if dept not in PIPELINE_TYPES or dept in seeds:
                continue
            if not _st.get('ended') and _st.get('status') != 'completed':
                continue
            video_path = _st.get('video_path') or ''
            image_paths = _st.get('image_paths') or []
            has_video = bool(video_path and os.path.exists(video_path))
            has_images = bool(image_paths and os.path.exists(image_paths[0]))
            video_mb = round(os.path.getsize(video_path) / 1_048_576, 1) if has_video else None
            topic = _st.get('scholarly_topic') or _st.get('essay_title') or _st.get('directive') or ''
            seeds[dept] = {
                'pipeline_id': _st.get('pipeline_id', ''),
                'started': (_st.get('started') or '')[:10],
                'topic': str(topic)[:80],
                'has_video': has_video,
                'has_images': has_images,
                'image_count': len(image_paths),
                'video_mb': video_mb,
                'stage_count': len(_st.get('stage_timeline') or []),
            }
        except Exception as _exc:
            _zyg_log.debug('skipping seed run that could not be summarised: %s', _exc)

    return jsonify(seeds)


@bp.route('/api/benchmark/run', methods=['POST'])
def api_benchmark_run_infra():
    """Start a quick infrastructure benchmark test."""
    import time as _t
    import uuid as _u

    body = request.get_json(force=True, silent=True) or {}
    pipeline = (body.get('pipeline') or '').lower().strip()
    seed_id = (body.get('seed_job_id') or '').strip()
    if not pipeline:
        return jsonify({'error': 'pipeline is required'}), 400
    run_id = 'bm_' + _u.uuid4().hex[:10]
    with _bm_infra_lock:
        _bm_infra_runs[run_id] = {
            'id': run_id,
            'pipeline': pipeline,
            'seed_id': seed_id,
            'status': 'starting',
            'stages': [],
            'started_at': _t.time(),
            'ended_at': None,
        }
    import threading as _thr

    _thr.Thread(target=_bm_infra_worker, args=(run_id, pipeline, seed_id), daemon=True).start()
    return jsonify({'run_id': run_id})


@bp.route('/api/benchmark/status/<run_id>')
def api_benchmark_status(run_id: str):
    """Poll the status of a running infrastructure benchmark."""
    with _bm_infra_lock:
        run = dict(_bm_infra_runs.get(run_id) or {})
    if not run:
        return jsonify({'error': 'not found'}), 404
    return jsonify(run)
