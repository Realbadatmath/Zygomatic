# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import glob
import json
import os
import re
import sys
from zyg_workflows import gui_state
from zyg_workflows import runtime as _runtime
from zyg_workflows.pipeline_config import _FLUX_PERF_TELEMETRY_PATH
from zyg_workflows.runtime import (
    _ams_iso,
    _creature_gen_jobs,
    _push_error_log,
    _workflow_pipeline_worker_alive,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── P-03 (2026-08-25): test-run predicates — STANDARD LIBRARY ONLY ──────────
# The Florence autopsy found that nothing in the codebase could tell a
# docsmoke-/gatecheck- run from a production run: smoke renders went to the
# Desktop, the Videos tab, the approvals queue, every audit listing and the
# throughput telemetry. These helpers are the one shared answer. They sit
# ABOVE the GUI-bound import block and use nothing but the standard library
# because two of their consumers never load the GUI: kanban_server.py (:8899,
# a bare http.server) and the smoke harness itself.
_PC_HERE = os.path.dirname(os.path.abspath(__file__))
_PC_DATA_DIR = os.path.join(_PC_HERE, 'data')  # == crewai_web_gui.DATA_DIR

# Keep in sync with the literal fallbacks in stage_runner.py, schedule_service.py
# and kanban_server.py (stdlib-only / import-order-sensitive consumers).
TEST_ID_PREFIXES = ('docsmoke-', 'gatecheck-', 'introsmoke-', 'smoke')
SMOKE_MARKER_FILE = 'SMOKE_RUN'


def is_test_pipeline_id(pipeline_id) -> bool:
    """True when ``pipeline_id`` names a smoke / gatecheck / other TEST run.

    Case-insensitive ``startswith`` on any of ``TEST_ID_PREFIXES``.
    False for None, empty and non-string values — never raises."""
    if not isinstance(pipeline_id, str):
        return False
    pid = pipeline_id.strip().lower()
    if not pid:
        return False
    return any(pid.startswith(p.lower()) for p in TEST_ID_PREFIXES)


def is_smoke_output_dir(out_dir) -> bool:
    """True when ``out_dir`` holds the ``SMOKE_RUN`` marker file OR its basename
    is itself a test id. Tolerates None / missing dirs (returns False)."""
    if not isinstance(out_dir, str) or not out_dir.strip():
        return False
    try:
        if is_test_pipeline_id(os.path.basename(os.path.normpath(out_dir))):
            return True
        return os.path.isfile(os.path.join(out_dir, SMOKE_MARKER_FILE))
    except Exception:
        return False


def smoke_output_root() -> str:
    """``<data>/output/smoke`` — sibling of ``<data>/output/clips`` — where test
    runs should write instead of the production clips tree. Created on demand."""
    root = os.path.join(_PC_DATA_DIR, 'output', 'smoke')
    try:
        os.makedirs(root, exist_ok=True)
    except OSError as _exc:
        _zyg_log.warning('runtime dir %s could not be created, writes under it will fail: %s', root, _exc)
    return root


def state_file_pipeline_id(path) -> str:
    """``.../pipeline_<id>_state.json`` → ``<id>`` (also ``storyteller_<id>_state.json``).
    Empty string when the name does not follow that shape."""
    try:
        base = os.path.basename(str(path or ''))
    except Exception:
        return ''
    m = re.match(r'^[a-z_]+?_(.+)_state\.json$', base)
    return m.group(1) if m else ''


def recent_state_files(pattern: str, limit: int = 0, include_tests: bool = False) -> list:
    """glob ``pattern`` and return the paths NEWEST-FIRST BY MTIME.

    Replaces ``sorted(glob(...), reverse=True)``: that sorted by FILENAME, and
    because ``'g'`` sorts above every hex digit the gatecheck-* states sat
    permanently on top of every "recent" list (P-03). Test ids are dropped
    (by filename, so no file is opened) unless ``include_tests``.
    ``limit`` <= 0 means no cap."""
    try:
        paths = glob.glob(pattern)
    except Exception:
        return []
    if not include_tests:
        paths = [p for p in paths if not is_test_pipeline_id(state_file_pipeline_id(p))]

    def _mt(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0

    paths.sort(key=_mt, reverse=True)
    return paths[:limit] if limit and limit > 0 else paths


# ── GUI-bound names ──────────────────────────────────────────────────────────
# Contract (unchanged): in the GUI process this module is imported at the
# BOTTOM of crewai_web_gui.py, and crewai_web_gui.py aliases its own __main__
# instance as sys.modules['zyg_dashboard.crewai_web_gui'] on its line ~22 — so the running
# GUI is ALWAYS already in sys.modules when this block executes, and the
# guard is a no-op there. What the guard prevents is a STANDALONE import
# (kanban_server, scripts, `python -c`) booting a SECOND GUI just to reach the
# helpers above — the very mechanism (P-01) by which an out-of-process run
# kills the production service. In the standalone branch the GUI-bound names
# are inert stand-ins: no job exists in such a process, so
# _run_creature_training returns at its first line.
# 2026-10-05 layering: the telemetry path, the clock, the creature registry and
# the two log/liveness helpers used to be read from the GUI in the first branch
# and stubbed in the second. They live in the base library now, so the plain
# imports at the top of this file serve both processes.
if 'crewai_web_gui' in sys.modules:
    from zyg_workflows.char_state_service import _creature_save_state, _creature_stage_key
    from zyg_workflows.vram_manager import _ensure_comfy_offload_env
else:

    def _creature_save_state(creature_id) -> None:
        return None

    def _creature_stage_key(name) -> str:
        return str(name or '')

    def _ensure_comfy_offload_env() -> None:
        return None


def _cleanup_pipeline_output(out_dir: str, final_video_path: str, log_fn=None, keep_stills: bool = False) -> None:
    """Delete intermediate/temporary files after a pipeline completes.

    Keeps: the final video, any .srt subtitle, any .mp3 narration audio.
    Deletes: every other .mp4 (slideshow, graded, subtitled, …), flux_images/,
             concat.txt, scene YAML files, zero-byte chunk audio files.
    keep_stills=True (2026-08-25, P-03) leaves flux_images/ untouched — smoke
    runs need the stills on disk for the harness assertions that run AFTER
    Cleanup (the Florence run "passed" its image assertion on the thumbnail
    because flux_images/ was already gone).
    """
    if not out_dir or not os.path.isdir(out_dir):
        return
    keep_basename = os.path.basename(final_video_path) if final_video_path else ''
    freed = 0
    try:
        for fname in list(os.listdir(out_dir)):
            fpath = os.path.join(out_dir, fname)
            if not os.path.isfile(fpath):
                continue

            # Keep the final video
            if fname == keep_basename:
                continue

            # Delete every other .mp4 (slideshow, graded, subtitled, raw, etc.)
            if fname.endswith('.mp4'):
                try:
                    freed += os.path.getsize(fpath)
                    os.remove(fpath)
                    if log_fn:
                        log_fn(f'Cleanup: removed {fname}')
                except OSError as _exc:
                    _zyg_log.debug('cleanup of %s skipped: %s', fpath, _exc)
                continue

            # Delete ffmpeg concat list
            if fname == 'concat.txt':
                try:
                    os.remove(fpath)
                except OSError as _exc:
                    _zyg_log.debug('cleanup of %s skipped: %s', fpath, _exc)
                continue

            # Delete scene/pipeline YAML files
            if fname.endswith(('.yaml', '.yml')):
                try:
                    os.remove(fpath)
                except OSError as _exc:
                    _zyg_log.debug('cleanup of %s skipped: %s', fpath, _exc)
                continue

            # Delete zero-byte audio chunk files (_az_chunk_*.mp3)
            if fname.startswith('_az_chunk_') and fname.endswith('.mp3'):
                try:
                    if os.path.getsize(fpath) == 0:
                        os.remove(fpath)
                except OSError as _exc:
                    _zyg_log.debug('cleanup of %s skipped: %s', fpath, _exc)

        # Delete flux_images/ directory — biggest space consumer
        flux_dir = os.path.join(out_dir, 'flux_images')
        if keep_stills and os.path.isdir(flux_dir):
            if log_fn:
                log_fn('Cleanup: kept flux_images/ (keep_stills)')
        elif os.path.isdir(flux_dir):
            import shutil as _shu_cl

            try:
                for _fi in os.listdir(flux_dir):
                    _fp = os.path.join(flux_dir, _fi)
                    if os.path.isfile(_fp):
                        freed += os.path.getsize(_fp)
                _shu_cl.rmtree(flux_dir, ignore_errors=True)
                if log_fn:
                    log_fn('Cleanup: removed flux_images/')
            except OSError as _exc:
                _zyg_log.debug('flux_images cleanup skipped: %s', _exc)

        if log_fn and freed:
            log_fn(f'Cleanup complete — freed {freed // 1_048_576} MB')
    except Exception as _ce:
        if log_fn:
            log_fn(f'Cleanup warning (non-fatal): {_ce}')


def _flux_perf_family(family) -> str:
    """Normalise a renderer family key: 'flux' (default), 'qwen', 'sdxl', …"""
    fam = re.sub(r'[^a-z0-9_]+', '_', str(family or 'flux').strip().lower()).strip('_')
    return fam or 'flux'


def _flux_perf_clamp(family: str) -> tuple:
    """Plausible seconds-per-image window per family. FLUX keeps its historic
    3-60 s; every other family (Qwen-Image-2512 at 1280x720/20 steps runs
    well past 60 s) gets 3-120 s so a real observation is not pinned to the
    wall the way the Florence smoke's 72.7 s was."""
    return (3.0, 60.0) if family == 'flux' else (3.0, 120.0)


def _flux_perf_telemetry_path(family: str = 'flux') -> str:
    """Per-family telemetry file. 'flux' keeps data/runtime/flux_perf_telemetry.json
    exactly as before (backward compatible); any other family lives beside it as
    flux_perf_telemetry_<family>.json so two renderers never share one number."""
    fam = _flux_perf_family(family)
    if fam == 'flux':
        return _FLUX_PERF_TELEMETRY_PATH
    base, ext = os.path.splitext(_FLUX_PERF_TELEMETRY_PATH)
    return f'{base}_{fam}{ext or ".json"}'


def _load_flux_seconds_per_image_estimate(default: float = 10.0, family: str = 'flux') -> float:
    """Load the learned seconds-per-image estimate for ``family`` from runtime telemetry."""
    fam = _flux_perf_family(family)
    lo, hi = _flux_perf_clamp(fam)
    try:
        with open(_flux_perf_telemetry_path(fam)) as _fpt:
            data = json.load(_fpt)
        est = float(data.get('estimate_s_per_image', default))
        if est <= 0:
            return default
        return max(lo, min(hi, est))
    except Exception:
        return default


def _update_flux_seconds_per_image_estimate(
    observed_s_per_image: float, image_count: int = 0, family: str = 'flux', pipeline_id: str = ''
) -> float:
    """Update the learned seconds-per-image estimate for ``family`` with exponential smoothing.

    Test runs (``is_test_pipeline_id(pipeline_id)``) never write: a 512x288
    8-step smoke render is not a production observation, yet one such run
    dragged the shared estimate to 23.9 s/img (P-03/P-13). For those the
    current estimate is returned unchanged."""
    fam = _flux_perf_family(family)
    lo, hi = _flux_perf_clamp(fam)
    if is_test_pipeline_id(pipeline_id):
        _zyg_log.info(f'[FLUX-PERF] test run {pipeline_id} — {fam} estimate left unchanged')
        return _load_flux_seconds_per_image_estimate(default=10.0, family=fam)
    observed = float(observed_s_per_image)
    if observed <= 0:
        return _load_flux_seconds_per_image_estimate(default=10.0, family=fam)

    observed = max(lo, min(hi, observed))
    prior = _load_flux_seconds_per_image_estimate(default=10.0, family=fam)
    alpha = 0.35
    updated = round((1.0 - alpha) * prior + alpha * observed, 3)

    payload = {
        'updated_at': _ams_iso(),
        'estimate_s_per_image': updated,
        'last_observed_s_per_image': round(observed, 3),
        'last_image_count': int(max(0, image_count)),
    }
    if fam != 'flux':
        payload['family'] = fam  # the flux file keeps its exact legacy shape
    try:
        with open(_flux_perf_telemetry_path(fam), 'w') as _fpt:
            json.dump(payload, _fpt, indent=2)
    except Exception as _exc:
        _zyg_log.warning('flux perf telemetry write failed, the run is not counted: %s', _exc)
    return updated


def _parse_pipeline_model_family(raw) -> str:
    """Normalize per-run image backend selection (FLUX vs SDXL)."""
    mf = (raw or '').strip().lower()
    return mf if mf in ('flux', 'sdxl') else 'flux'


def _resolve_video_timing(
    pipeline_options: dict | None,
    video_duration_minutes: float,
) -> dict:
    """Derive scene count, per-scene length, and total runtime for video/manga."""
    po = pipeline_options or {}
    if po.get('test_scene'):
        # ~5s single-scene TEST render: exactly one short scene for fast inspection
        # before committing to a full multi-scene run. (Sub-clip count + frames are
        # further capped downstream in pipeline_video / wan_video_service.)
        return {'n_scenes': 1, 'scene_duration': 5.0, 'total_duration_sec': 5.0}
    total_sec = po.get('total_duration_sec')
    try:
        total_sec = float(total_sec) if total_sec else None
    except (TypeError, ValueError):
        total_sec = None
    if not total_sec:
        _dur_min = max(0.25, min(3.0, float(video_duration_minutes or 0.5)))
        total_sec = _dur_min * 60.0

    try:
        scene_duration = float(po.get('scene_duration_sec') or 15)
    except (TypeError, ValueError):
        scene_duration = 15.0
    scene_duration = max(3.5, min(20.0, scene_duration))

    auto_scenes = max(1, min(12, int(round(total_sec / scene_duration)) or 1))
    sc_ov = po.get('scene_count')
    if sc_ov is not None:
        try:
            n_scenes = max(1, min(12, int(sc_ov)))
        except (TypeError, ValueError):
            n_scenes = auto_scenes
        max_for_target = max(1, int(total_sec / scene_duration))
        n_scenes = min(n_scenes, max_for_target)
    else:
        n_scenes = auto_scenes

    if n_scenes == 1:
        scene_duration = max(3.5, min(20.0, float(total_sec)))

    return {
        'n_scenes': n_scenes,
        'scene_duration': scene_duration,
        'total_duration_sec': float(total_sec),
    }


def _normalize_pipeline_options(raw) -> dict:
    """Sanitize Advanced Settings / UI pipeline_options payload."""
    po = raw if isinstance(raw, dict) else {}

    def _as_bool(v, default: bool) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return default
        return str(v).strip().lower() not in ('false', '0', 'no', 'off')

    out: dict = {
        'enable_bgm': _as_bool(po.get('enable_bgm'), True),
        'burn_subtitles': _as_bool(po.get('burn_subtitles'), True),
        'enable_watermark': _as_bool(po.get('enable_watermark'), False),
        'test_scene': _as_bool(po.get('test_scene'), False),
    }
    try:
        sc = int(po.get('scene_count') or 0)
        if sc > 0:
            out['scene_count'] = max(1, min(12, sc))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('scene_count not numeric, left at the default: %s', _exc)
    try:
        td = float(po.get('total_duration_sec') or 0)
        if td > 0:
            out['total_duration_sec'] = max(3.5, min(1800.0, td))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('total_duration_sec not numeric, left at the default: %s', _exc)
    try:
        sds = float(po.get('scene_duration_sec') or 0)
        if sds > 0:
            out['scene_duration_sec'] = max(3.5, min(20.0, sds))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('scene_duration_sec not numeric, left at the default: %s', _exc)
    try:
        mpf = int(po.get('manga_panel_fps') or 0)
        if mpf > 0:
            out['manga_panel_fps'] = max(1, min(30, mpf))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('manga_panel_fps not numeric, left at the default: %s', _exc)
    # Visual intensity dial for generated stills. Always emitted so downstream
    # code reads one key instead of guessing a default per pipeline.
    # 'standard' reproduces the pre-dial behaviour; 'high' is the documentary
    # default (the opening frame is then pushed one level to 'extreme').
    _iv = str(po.get('image_intensity') or '').strip().lower()
    out['image_intensity'] = _iv if _iv in ('standard', 'high', 'extreme') else 'high'
    # Pre-Emptive bank (preempt_bank.py, 2026-09-20): {'mode': 'record'|'replay', 'entry': id}.
    # Only these two keys pass; anything else is dropped so a stray payload cannot steer a run.
    _pe = po.get('preempt')
    if isinstance(_pe, dict) and _pe.get('mode') in ('record', 'replay') and _pe.get('entry'):
        out['preempt'] = {
            'mode': _pe['mode'],
            'entry': str(_pe['entry'])[:120],
            'dry_run': _as_bool(_pe.get('dry_run'), False),
        }
    return out


def _run_creature_training(creature_id: str, directive: str, image_paths: list | None = None, phase: str = 'full'):
    """Background worker — creature sheet (+ LoRA). ``phase`` = full | sheet | train
    (2026-08-25 review gate: 'train' resumes an approved sheet)."""
    job = _creature_gen_jobs.get(creature_id)
    if not job:
        return

    def _check_creature_stop():
        from zyg_workflows import pipeline_control as _pc_ct

        ev = job.get('stop_event')
        if gui_state._pipeline_stop_flag or _pc_ct.halt_requested() or (ev is not None and ev.is_set()):
            raise RuntimeError('Creature training stopped by user')

    def _log(level, stage, msg):
        ts = _ams_iso()
        ev = {'ts': ts, 'level': level, 'stage': stage, 'msg': msg}
        job.setdefault('debug_events', []).append(ev)
        if len(job['debug_events']) > 500:
            job['debug_events'] = job['debug_events'][-300:]
        _zyg_log.info(f'[CREATURE-TRAIN][{level}][{stage}] {msg}')
        _push_error_log(level, stage, msg, creature_id)

    def _set_stage(name, status='running'):
        job['current_stage'] = name
        job['stage'] = _creature_stage_key(name)
        tl = job.setdefault('stage_timeline', [])
        for entry in tl:
            if entry['name'] == name:
                entry['status'] = status
                if status == 'completed' and not entry.get('ended_at'):
                    entry['ended_at'] = _ams_iso()
                return
        tl.append(
            {
                'name': name,
                'status': status,
                'ts': _ams_iso(),
                'started_at': _ams_iso(),
            }
        )
        _creature_save_state(creature_id)

    def _complete_stage(name):
        _set_stage(name, 'completed')

    def _fail_stage(name, err):
        _set_stage(name, 'failed')
        job['error'] = err
        job['status'] = 'failed'
        job['ended'] = _ams_iso()
        _creature_save_state(creature_id)
        _log('ERROR', name, err)

    try:
        _check_creature_stop()
        _ensure_comfy_offload_env()
        from zyg_workflows import creature_training_service as _cts

        _cts.run_creature_training(
            job,
            creature_id,
            directive,
            image_paths=image_paths or [],
            model_family=job.get('model_family', 'flux'),
            set_stage=lambda n: (_check_creature_stop(), _set_stage(n, 'running'))[1],
            complete_stage=_complete_stage,
            fail_stage=_fail_stage,
            log_fn=_log,
            halt_check=_check_creature_stop,
            phase=phase,
        )
        if job.get('status') == 'stopped':
            return
        if job.get('status') == 'awaiting_review':
            # Review gate: the sheet is on disk, nothing else runs until approve.
            _creature_save_state(creature_id)
            return
        if job.get('status') != 'failed':
            job['status'] = 'completed'
            job['stage'] = 'done'
            job['current_stage'] = 'done'
            job['ended'] = _ams_iso()
            _runtime.bm_record_pipeline(job)
        _creature_save_state(creature_id)
    except RuntimeError as _ct_stop:
        if 'stopped by user' in str(_ct_stop).lower():
            job['status'] = 'stopped'
            job['error'] = str(_ct_stop)
            _creature_save_state(creature_id)
            _log('WARN', 'Creature Training', str(_ct_stop))
            return
        raise
    except Exception as _cte:
        import traceback

        _fail_stage('Creature Training', str(_cte))
        _log('ERROR', 'Creature Training', traceback.format_exc()[-800:])


def _resolve_pipeline_public_status(job: dict) -> str:
    """Status for Zero Public: completed | failed | stopped | running | interrupted."""
    pid = (job.get('pipeline_id') or '').strip()
    if pid and _workflow_pipeline_worker_alive(pid):
        return 'running'
    if job.get('ended') and not (job.get('error') or '').strip():
        return 'completed'
    if (job.get('error') or '').strip():
        return 'failed'
    explicit = (job.get('status') or '').strip().lower()
    if explicit in ('completed', 'done'):
        return 'completed'
    if explicit == 'stopped':
        return 'stopped'
    if explicit == 'interrupted':
        return 'interrupted'
    if pid and not job.get('ended'):
        return 'interrupted'
    if explicit in ('failed', 'error'):
        return 'failed'
    return 'unknown'


def _pipeline_current_stage_from_job(job: dict) -> str:
    cs = (job.get('current_stage') or '').strip()
    if cs:
        return cs
    for ev in reversed(job.get('debug_events') or []):
        st = (ev.get('stage') or '').strip()
        if st:
            return st
    return ''


def _normalize_word_timings_for_subs(raw_timings: list | None) -> list[tuple[str, float]]:
    """Normalize (word, t) or (word, t, duration) streams for subtitle alignment."""
    out: list[tuple[str, float]] = []
    for item in raw_timings or []:
        try:
            if not item:
                continue
            word = str(item[0]).strip()
            if not word:
                continue
            out.append((word, float(item[1])))
        except (IndexError, TypeError, ValueError) as _exc:
            _zyg_log.debug('malformed word timing skipped: %s', _exc)
            continue
    return out


def _align_narration_word_timings(
    narration: str,
    raw_timings: list | None,
    *,
    voice_mode: str = 'narration',
    min_coverage: float = 0.5,
) -> tuple[list[tuple[str, float]], float]:
    """Script-first captions: keep narration punctuation, use TTS/Whisper for when."""
    timings = _normalize_word_timings_for_subs(raw_timings)
    if not narration or not timings:
        return timings, 0.0
    try:
        from zyg_workflows import murch_engine as _murch

        return _murch.align_script_to_word_timings(
            timings,
            narration,
            voice_mode=voice_mode,
            min_coverage=min_coverage,
        )
    except Exception as _ale:
        _zyg_log.info(f'[SUBTITLES] Script alignment failed: {_ale}')
        return timings, 0.0
