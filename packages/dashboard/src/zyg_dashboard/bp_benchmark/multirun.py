# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_benchmark — the multi-run sampler, worker and its routes.

Moved verbatim out of bp_benchmark.py; see the package __init__ for the full rationale.
"""

from zyg_dashboard.crewai_web_gui import _BENCHMARK_PATH
from zyg_dashboard.crewai_web_gui import _FLUX_PERF_TELEMETRY_PATH
from zyg_dashboard.crewai_web_gui import _bm_mr_lock
from zyg_dashboard.gui.runtime_state import _runtime_path
from zyg_dashboard.gui.scholarly import _start_scholarly_pipeline_internal
from zyg_dashboard.gui.runtime_state import _workflow_jobs
import json
from flask import jsonify
import os
from flask import request
from zyg_dashboard.bp_benchmark.state import _bm_mr_sessions, _zyg_log, bp


def _bm_mr_sample() -> dict:
    """Snapshot current GPU/CPU/RAM. Returns a plain dict, never raises."""
    import subprocess as _sp

    s: dict = {
        'gpu_pct': 0.0,
        'vram_used_mb': 0.0,
        'vram_total_mb': 49152.0,
        'cpu_pct': 0.0,
        'ram_pct': 0.0,
        'power_w': 0.0,
    }
    try:
        import psutil as _ps

        _vm = _ps.virtual_memory()
        s['ram_pct'] = round(_vm.percent, 1)
        s['cpu_pct'] = round(_ps.cpu_percent(interval=0.1), 1)
    except Exception as _exc:
        _zyg_log.warning('psutil cpu/ram sample failed, reporting zeros: %s', _exc)
    try:
        _r = _sp.run(
            [
                'nvidia-smi',
                '--query-gpu=utilization.gpu,memory.used,memory.total,power.draw',
                '--format=csv,noheader,nounits',
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if _r.returncode == 0:
            _pts = [p.strip() for p in _r.stdout.strip().split(',')]

            def _f(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0.0

            s['gpu_pct'] = _f(_pts[0]) if _pts else 0.0
            s['vram_used_mb'] = _f(_pts[1]) if len(_pts) > 1 else 0.0
            s['vram_total_mb'] = _f(_pts[2]) if len(_pts) > 2 else 49152.0
            s['power_w'] = _f(_pts[3]) if len(_pts) > 3 else 0.0
    except Exception as _exc:
        _zyg_log.warning('nvidia-smi query failed, reporting gpu defaults: %s', _exc)
    return s


def _bm_multirun_worker(session_id: str, configs: list) -> None:
    """
    Starts N concurrent scholarly pipeline runs with configurable staggered offsets.
    Each run uses a fixed canned directive and a reduced total_duration_sec so it
    completes in ~3–15 min.  Resource utilisation is sampled every 2 s throughout
    so the frontend can render a live Gantt chart and a resource line chart.
    The goal is to measure how concurrent stages interact on the same hardware
    (GPU contention during image generation, CPU/RAM overlap during TTS + assembly).
    """
    import time as _tt

    def _upd(**kw):
        with _bm_mr_lock:
            for k, v in kw.items():
                _bm_mr_sessions[session_id][k] = v

    # 'full' = no duration cap, all production flags on — matches actual documentary output.
    # short/medium/long remain for quick smoke tests; use 'full' for realism benchmarks.
    _SIZE_SECS = {'short': 60, 'medium': 120, 'long': 240, 'full': None}

    # 12 directives matching the Zero topic pool categories — gives realistic
    # distribution of research depth, script length, and image generation count.
    _DIRECTIVES = [
        'industrial revolution in 19th century britain',
        'ancient roman gladiators in the colosseum',
        'the apollo 11 moon landing 1969',
        'the silk road ancient trade route between east and west',
        'the black death plague in medieval europe',
        'world war one trench warfare western front',
        'the first flight of the wright brothers at kitty hawk',
        'the rise and fall of the roman empire',
        'charles darwin and the theory of evolution',
        'the french revolution and the reign of terror',
        'the manhattan project and the atomic bomb',
        'the voyager 1 spacecraft journey to interstellar space',
    ]

    session_start = _tt.time()
    _upd(status='running', session_start=session_start)

    sorted_cfgs = sorted(configs, key=lambda c: c.get('offset_s', 0))
    pipelines_meta = []

    try:
        for idx, cfg in enumerate(sorted_cfgs):
            offset = float(cfg.get('offset_s', 0))
            wait = offset - (_tt.time() - session_start)
            if wait > 0:
                _tt.sleep(wait)

            size = cfg.get('size', 'short')
            dur = _SIZE_SECS.get(size, 60)  # None = production default (no cap)
            directive = _DIRECTIVES[idx % len(_DIRECTIVES)]

            # 'full' size: use production defaults — no duration cap, all features on.
            # Other sizes: disable bgm/watermark/subtitles to keep runs short.
            if dur is None:
                pipeline_opts: dict = {}
            else:
                pipeline_opts = {
                    'total_duration_sec': dur,
                    'enable_bgm': False,
                    'enable_watermark': False,
                    'burn_subtitles': False,
                    'scene_duration_sec': 15,
                }

            result = _start_scholarly_pipeline_internal(
                directive=directive,
                topic='scholarly',
                narration_enabled=True,
                visual_style='cinematic',
                pipeline_options=pipeline_opts or None,
            )
            job_id = result['job_id']
            pipelines_meta.append(
                {
                    'label': cfg.get('label', f'Pipeline {chr(65 + idx)}'),
                    'size': cfg.get('size', 'short'),
                    'offset_s': offset,
                    'job_id': job_id,
                    'started_at': _tt.time(),
                }
            )
            with _bm_mr_lock:
                _bm_mr_sessions[session_id]['pipelines'] = list(pipelines_meta)

        # Monitor until every pipeline reaches a terminal state, sampling resources every 2 s
        while True:
            all_done = True
            pipes_status = []
            for pm in pipelines_meta:
                jid = pm['job_id']
                job = _workflow_jobs.get(jid, {})
                st = job.get('status', 'unknown')
                tl = []
                try:
                    with open(_runtime_path(f'pipeline_{jid}_state.json')) as _sf:
                        _sdata = json.load(_sf)
                    tl = _sdata.get('stage_timeline', [])
                except Exception as _exc:
                    _zyg_log.debug('stage timeline unavailable for job %s: %s', jid, _exc)
                pipes_status.append(
                    {
                        'label': pm['label'],
                        'job_id': jid,
                        'started_at': pm['started_at'],
                        'offset_s': pm['offset_s'],
                        'size': pm['size'],
                        'status': st,
                        'current_stage': job.get('current_stage') or '',
                        'stage_timeline': tl,
                    }
                )
                if st not in ('completed', 'failed', 'error', 'stopped'):
                    all_done = False

            sample = _bm_mr_sample()
            sample['t_rel'] = round(_tt.time() - session_start, 1)

            with _bm_mr_lock:
                sess = _bm_mr_sessions[session_id]
                sess['pipelines_status'] = pipes_status
                tl_list = sess.setdefault('resource_timeline', [])
                tl_list.append(sample)
                if len(tl_list) > 900:  # cap at 30 min of 2 s samples
                    sess['resource_timeline'] = tl_list[-900:]

            if all_done:
                break
            _tt.sleep(2)

        _upd(status='completed', total_elapsed_s=round(_tt.time() - session_start, 1))

    except Exception as _mre:
        _upd(status='error', error=str(_mre), total_elapsed_s=round(_tt.time() - session_start, 1))


@bp.route('/api/benchmark/multirun', methods=['POST'])
def api_benchmark_multirun_start():
    """Start a concurrent multi-pipeline benchmark session."""
    import uuid as _uuid
    import threading as _thr

    body = request.get_json(force=True, silent=True) or {}
    configs = body.get('pipelines', [])
    if len(configs) < 2:
        return jsonify({'error': 'Minimum 2 pipelines required'}), 400
    if len(configs) > 4:
        return jsonify({'error': 'Maximum 4 pipelines'}), 400
    session_id = 'mr_' + _uuid.uuid4().hex[:10]
    with _bm_mr_lock:
        _bm_mr_sessions[session_id] = {
            'id': session_id,
            'status': 'starting',
            'configs': configs,
            'pipelines': [],
            'pipelines_status': [],
            'resource_timeline': [],
            'session_start': None,
            'total_elapsed_s': None,
            'error': None,
        }
    _thr.Thread(
        target=_bm_multirun_worker, args=(session_id, configs), daemon=True, name=f'bm-multirun-{session_id}'
    ).start()
    return jsonify({'session_id': session_id})


@bp.route('/api/benchmark/multirun/<session_id>')
def api_benchmark_multirun_status(session_id: str):
    """Poll the status of a running multi-pipeline benchmark session."""
    with _bm_mr_lock:
        sess = dict(_bm_mr_sessions.get(session_id) or {})
    if not sess:
        return jsonify({'error': 'not found'}), 404
    return jsonify(sess)


@bp.route('/api/benchmark/system')
def api_benchmark_system():
    """Return live GPU, VRAM, and RAM stats for the benchmark system-resources panel."""
    import subprocess as _sp

    result: dict = {'ram': {}, 'gpu': [], 'cpu': {}}
    try:
        import psutil as _ps

        _vm = _ps.virtual_memory()
        result['ram'] = {
            'total_gb': round(_vm.total / 1_073_741_824, 1),
            'used_gb': round(_vm.used / 1_073_741_824, 1),
            'avail_gb': round(_vm.available / 1_073_741_824, 1),
            'pct': _vm.percent,
        }
        result['cpu'] = {
            'cores': _ps.cpu_count(logical=False) or 0,
            'threads': _ps.cpu_count(logical=True) or 0,
            'pct': _ps.cpu_percent(interval=0.2),
        }
    except Exception as _e:
        result['ram'] = {'error': str(_e)}
    try:
        _r = _sp.run(
            [
                'nvidia-smi',
                '--query-gpu=name,memory.used,memory.free,memory.total,'
                'utilization.gpu,temperature.gpu,power.draw,power.limit',
                '--format=csv,noheader,nounits',
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if _r.returncode == 0:
            for _line in _r.stdout.strip().splitlines():
                _parts = [p.strip() for p in _line.split(',')]

                def _f(v):
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return None

                if len(_parts) >= 4:
                    result['gpu'].append(
                        {
                            'name': _parts[0],
                            'mem_used_mb': _f(_parts[1]),
                            'mem_free_mb': _f(_parts[2]),
                            'mem_total_mb': _f(_parts[3]),
                            'util_pct': _f(_parts[4]) if len(_parts) > 4 else None,
                            'temp_c': _f(_parts[5]) if len(_parts) > 5 else None,
                            'power_w': _f(_parts[6]) if len(_parts) > 6 else None,
                            'power_limit_w': _f(_parts[7]) if len(_parts) > 7 else None,
                        }
                    )
    except Exception as _e:
        result['gpu_error'] = str(_e)
    return jsonify(result)


@bp.route('/api/benchmark', methods=['GET'])
def api_benchmark():
    """Return aggregated benchmark timing data for all AI tools."""
    rows = []
    try:
        # Load benchmark_telemetry.json
        data: dict = {}
        if os.path.exists(_BENCHMARK_PATH):
            with open(_BENCHMARK_PATH) as _bm_r:
                data = json.load(_bm_r)

        # Merge existing FLUX perf telemetry into data if not already present
        if 'flux_schnell' not in data and os.path.exists(_FLUX_PERF_TELEMETRY_PATH):
            try:
                with open(_FLUX_PERF_TELEMETRY_PATH) as _ft:
                    _ft_d = json.load(_ft)
                    _est = float(_ft_d.get('estimate_s_per_image', 0))
                    _last = float(_ft_d.get('last_observed_s_per_image', 0))
                    _cnt = int(_ft_d.get('last_image_count', 0))
                    if _est > 0:
                        data['flux_schnell'] = {
                            'total_elapsed': round(_est * _cnt, 2),
                            'total_count': _cnt,
                            'last_elapsed': round(_last, 2),
                            'last_count': 1,
                            'last_ts': '',
                        }
            except Exception as _exc:
                _zyg_log.debug('flux schnell estimate unavailable: %s', _exc)

        _TOOL_LABELS = {
            'flux_dev': {'label': 'FLUX.1-dev', 'unit': 'image', 'emoji': '🖼'},
            'flux_schnell': {'label': 'FLUX.1-schnell', 'unit': 'image', 'emoji': '⚡'},
            'tts': {'label': 'Azure TTS', 'unit': 'request', 'emoji': '🎙'},
            'claude': {'label': 'Claude AI', 'unit': 'call', 'emoji': '🤖'},
            'blender': {'label': 'Blender Render', 'unit': 'image', 'emoji': '🎨'},
            'lora': {'label': 'LoRA Training', 'unit': 'step', 'emoji': '🧠'},
        }

        for tool_key, entry in data.items():
            meta = _TOOL_LABELS.get(tool_key, {'label': tool_key, 'unit': 'run', 'emoji': '📊'})
            total_e = float(entry.get('total_elapsed', 0))
            total_c = max(int(entry.get('total_count', 0)), 1)
            last_e = float(entry.get('last_elapsed', 0))
            last_c = max(int(entry.get('last_count', 1)), 1)
            rows.append(
                {
                    'tool': meta['label'],
                    'emoji': meta['emoji'],
                    'unit': meta['unit'],
                    'avg_s_per_unit': round(total_e / total_c, 2) if total_e > 0 else 0,
                    'last_s_per_unit': round(last_e / last_c, 2) if last_e > 0 else 0,
                    'total_samples': int(entry.get('total_count', 0)),
                    'last_ts': entry.get('last_ts', ''),
                }
            )
    except Exception as _be:
        return jsonify({'error': str(_be), 'rows': []}), 500

    rows.sort(key=lambda r: r['tool'])
    return jsonify({'rows': rows})
