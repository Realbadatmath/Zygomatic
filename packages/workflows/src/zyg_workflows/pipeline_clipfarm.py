# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import json
import os
import threading
from zyg_workflows import gui_state

from zyg_workflows import provenance_seal as _seal
from zyg_workflows import runtime as _runtime
from zyg_workflows.stage_runner import (
    _build_task_desc,
    _load_workflow_overrides,
    _run_stage_agent,
    _scp_output_to_windows,
    _stage_preflight,
)
from zyg_workflows.subproc_registry import _register_marker, _update_marker
from zyg_workflows.vram_manager import _hw_monitor_loop, _wait_for_hardware_headroom
from zyg_workflows.pipeline_config import (
    _CLIPFARM_STAGES,
    _DEMONET_TIER1,
    _DEMONET_TIER3_TITLE,
    _PUBLISH_STAGE_NAME,
    _RUNTIME_DIR,
    _UPLOAD_AGENTS,
)
from zyg_workflows.runtime import (
    _agent_log,
    _ams_iso,
    _ams_now,
    _parse_iso_to_ams,
    _runtime_path,
    workflow_jobs as _workflow_jobs,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _run_clipfarm_pipeline(pipeline_id: str, directive: str = None):
    """
    Execute all Clipfarm pipeline stages with proper dependency ordering.
    Parallel stages use a ThreadPoolExecutor; sequential stages run in order.
    Respects workflow overrides set by the user via Zero (skip/fix per issue).
    """
    pass  # (global stmt removed: names moved to gui_state)
    import concurrent.futures

    job = _workflow_jobs[pipeline_id]
    job['stages'] = {}
    overrides = _load_workflow_overrides()

    # Kick off asset downloader in background — runs silently while stages 1-3 execute,
    # so SFX/reaction clips are ready by the time Stage 4b post-processing needs them.
    threading.Thread(target=_runtime.download_assets_background, name='asset-downloader', daemon=True).start()

    # Register pipeline-level marker immediately — visible in Tail Subs from first second
    _pipeline_marker = _register_marker(
        f'🚀 Pipeline {pipeline_id[:8]} — starting', pipeline_id=pipeline_id, status='pipeline'
    )

    # Start hardware monitor for this pipeline run
    threading.Thread(
        target=_hw_monitor_loop, args=(pipeline_id,), daemon=True, name=f'hw-monitor-{pipeline_id[:8]}'
    ).start()
    # Activate per-run telemetry CSV logging
    gui_state._TELEMETRY_LOG_PIPELINE_ID = pipeline_id
    skip_upload = overrides.get('no_upload_platforms') == 'skip'

    # ── Shared pipeline state ────────────────────────────────────────────────
    # 2026-07-25: clipfarm writes to its OWN output folder (output/clipfarm/) instead
    # of the shared output/clips/. Previously its finished .mp4 clips landed in
    # output/clips with NO department in state, so the documentary auto-uploader's
    # department gate (which only skips KNOWN non-doc departments) failed to skip
    # them — clipfarm clips could leak to the documentary YouTube channel. Owning a
    # separate folder removes them from the scanner entirely.
    out_dir = os.path.join(os.path.dirname(_RUNTIME_DIR), 'output', 'clipfarm', pipeline_id)
    os.makedirs(out_dir, exist_ok=True)
    job['output_dir'] = out_dir
    state_file = _runtime_path(f'pipeline_{pipeline_id}_state.json')
    channels = []
    try:
        ch_path = _runtime_path('clipfarm_channels.json')
        if os.path.exists(ch_path):
            with open(ch_path) as _cf:
                channels = json.load(_cf)
    except Exception as _exc:
        _zyg_log.warning('clipfarm channel config unreadable, continuing with the defaults: %s', _exc)
    pipeline_state = {
        'pipeline_id': pipeline_id,
        'department': 'clipfarm',  # 2026-07-25: persist dept so the documentary
        # auto-uploader's gate also skips any clipfarm
        # clip that ever lands in output/clips (belt-and-
        # suspenders on top of the output/clipfarm move).
        'started': _ams_iso(),
        'channels': channels,
        'video_candidates': [],
        'approved_clips': [],
        'fetched_files': {},
        'processed_clips': [],
        'output_dir': out_dir,
    }
    try:
        with open(state_file, 'w') as _sf:
            json.dump(pipeline_state, _sf, indent=2)
    except Exception as _exc:
        _zyg_log.warning('pipeline state write to %s failed, the dashboard will not see this run: %s', state_file, _exc)

    try:
        for stage in _CLIPFARM_STAGES:
            stage_name = stage['name']
            agent_ids = stage['agents']
            job['current_stage'] = stage_name
            _update_marker(_pipeline_marker, label=f'🔄 Pipeline {pipeline_id[:8]} — {stage_name}')

            # Reload state so each stage sees outputs from the previous one
            try:
                with open(state_file) as _sf:
                    pipeline_state = json.load(_sf)
            except Exception as _exc:
                _zyg_log.warning(
                    'pipeline state re-read from %s failed, using the in-memory copy: %s', state_file, _exc
                )

            # Guard: stages 5/6 require actual processed clips — skip if pipeline ran dry
            _post_processing_stages = ('Stage 5', 'Stage 6')
            if any(stage_name.startswith(s) for s in _post_processing_stages):
                if not pipeline_state.get('fetched_files') and not pipeline_state.get('processed_clips'):
                    job['stages'][stage_name] = {
                        'status': 'skipped',
                        'reason': 'No clips produced by Stage 4 — skipping downstream stage',
                    }
                    _zyg_log.info(f'[PIPELINE] {stage_name} skipped — no clips available')
                    continue

            # Block until GPU wattage, CPU%, and RAM are under calibration hard ceilings
            _wait_for_hardware_headroom(stage_name)

            # Run critical tools directly in Python BEFORE the LLM agent —
            # guarantees real video URLs / file paths are in the state file.
            _stage_preflight(stage_name, state_file, pipeline_state)

            # Reload again after preflight so task description has fresh data
            try:
                with open(state_file) as _sf:
                    pipeline_state = json.load(_sf)
            except Exception as _exc:
                _zyg_log.warning(
                    'pipeline state re-read from %s failed, using the in-memory copy: %s', state_file, _exc
                )

            # Build concrete task description with real URLs / file paths injected
            task_desc = _build_task_desc(stage_name, stage['task'], state_file, pipeline_state)

            # Publish stage override when no upload platform is configured
            if skip_upload and stage_name == _PUBLISH_STAGE_NAME:
                task_desc = _build_task_desc(stage_name, stage['task'], state_file, pipeline_state)

            # Filter to agents that exist (no dashboard controller → no agents)
            _known_agents = getattr(_runtime.controller, 'agents', None) or {}
            available = [a for a in agent_ids if a in _known_agents]

            # When skipping upload, exclude pure upload agents from this stage
            if skip_upload and stage_name == _PUBLISH_STAGE_NAME:
                available = [a for a in available if a not in _UPLOAD_AGENTS]

            if not available:
                job['stages'][stage_name] = {'status': 'skipped', 'reason': 'no agents available'}
                continue

            if stage['parallel'] and len(available) > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(available)) as pool:
                    futures = {
                        pool.submit(_run_stage_agent, aid, task_desc, pipeline_id, stage_name): aid for aid in available
                    }
                    concurrent.futures.wait(futures)
            else:
                for aid in available:
                    _run_stage_agent(aid, task_desc, pipeline_id, stage_name)

            # Save stage completion marker to state file
            try:
                with open(state_file) as _sf:
                    _st = json.load(_sf)
                _st.setdefault('stage_results', {})[stage_name] = {
                    'completed_at': _ams_iso(),
                    'agents': list(job['stages'].get(stage_name, {}).keys()),
                }
                with open(state_file, 'w') as _sf:
                    json.dump(_st, _sf, indent=2)
            except Exception as _exc:
                _zyg_log.warning('stage result for %s not recorded in %s: %s', stage_name, state_file, _exc)

        # ── Final delivery audit: scan output clips for bad words in filename ──
        try:
            import re as _re_audit

            _held = []
            for _f in os.listdir(out_dir):
                if not _f.endswith('.mp4'):
                    continue
                _stem = os.path.splitext(_f)[0].replace('_', ' ')
                _all_bad = _DEMONET_TIER1 | _DEMONET_TIER3_TITLE
                for _bw in _all_bad:
                    if _re_audit.search(r'\b' + _re_audit.escape(_bw) + r'\b', _stem, _re_audit.IGNORECASE):
                        _held.append(_f)
                        _agent_log(
                            'ERROR',
                            'AUDIT',
                            pipeline_id,
                            'Output Transfer',
                            f'🚫 HELD — clip "{_f}" filename still contains policy-violating word '
                            f'"{_bw}". File kept in output folder but NOT transferred.',
                        )
                        break
            # Remove held clips from out_dir temporarily so SFTP won't pick them up
            _held_dir = os.path.join(out_dir, '_held')
            if _held:
                os.makedirs(_held_dir, exist_ok=True)
                for _hf in _held:
                    try:
                        import shutil as _shu_h

                        _shu_h.move(os.path.join(out_dir, _hf), os.path.join(_held_dir, _hf))
                    except Exception as _exc:
                        _zyg_log.warning(
                            'flagged clip %s could not be moved to _held, it stays in the delivery set: %s', _hf, _exc
                        )
        except Exception as _audit_e:
            _agent_log('WARNING', 'AUDIT', pipeline_id, 'Output Transfer', f'⚠ Delivery audit exception: {_audit_e}')

        # ── Content credentials on what survived the audit ─────────────────────
        # The held clips are in _held/ and are deliberately not signed: clipfarm does
        # not claim authorship of something it refuses to ship. Signing here rather
        # than in the SFTP leg means the credential names the pipeline that made the
        # clip ('clipfarm'), not the transport that moved it.
        try:
            for _f in sorted(os.listdir(out_dir)):
                if not _f.endswith('.mp4'):
                    continue
                _seal.seal(
                    os.path.join(out_dir, _f),
                    pipeline='clipfarm',
                    run_id=pipeline_id,
                    log_fn=lambda _m: print(_m, flush=True),
                )
        except Exception as _seal_e:
            _agent_log('WARNING', 'AUDIT', pipeline_id, 'Output Transfer', f'⚠ Content credential exception: {_seal_e}')

        # ── Deliver clips to Windows desktop via SFTP (tracked in chart) ──
        job['current_stage'] = 'Delivering to Desktop'
        job['stages']['Delivering to Desktop'] = {'SFTP-Delivery': {'status': 'running', 'started': _ams_iso()}}
        _scp_output_to_windows(out_dir, pipeline_id)
        job['stages']['Delivering to Desktop']['SFTP-Delivery']['status'] = 'completed'
        job['stages']['Delivering to Desktop']['SFTP-Delivery']['ended'] = _ams_iso()

        # Move held clips back to output folder now that SFTP is done
        try:
            _held_dir_back = os.path.join(out_dir, '_held')
            if os.path.isdir(_held_dir_back):
                import shutil as _shu_hb

                for _hf in os.listdir(_held_dir_back):
                    _shu_hb.move(os.path.join(_held_dir_back, _hf), os.path.join(out_dir, _hf))
                os.rmdir(_held_dir_back)
        except Exception as _exc:
            _zyg_log.warning('held clips could not be restored from %s: %s', _held_dir_back, _exc)

        job['status'] = 'completed'
        job['ended'] = _ams_iso()
        job['current_stage'] = None
        # Stop telemetry logging for this run
        gui_state._TELEMETRY_LOG_PIPELINE_ID = ''
        try:
            with open(state_file) as _sf:
                _final = json.load(_sf)
            processed_count = len(_final.get('processed_clips', []))
            # Compute elapsed time
            try:
                _t_start = _parse_iso_to_ams(_final.get('started', pipeline_state.get('started', '')))
                if _t_start is not None:
                    _elapsed = (_ams_now() - _t_start).total_seconds()
                    _h, _rem = divmod(int(_elapsed), 3600)
                    _m, _s = divmod(_rem, 60)
                    _dur = f'{_h}h {_m}m {_s}s' if _h else f'{_m}m {_s}s'
                else:
                    _dur = None
            except Exception:
                _dur = None
            job['result'] = (
                f'Pipeline completed. {len(_CLIPFARM_STAGES)} stages executed. '
                f'{processed_count} clips processed. ' + (f'Duration: {_dur}. ' if _dur else '') + f'Output: {out_dir}'
            )
        except Exception:
            job['result'] = f'Pipeline completed. {len(_CLIPFARM_STAGES)} stages executed. Output: {out_dir}'
        if skip_upload:
            job['result'] += f' Clips saved to: {job.get("output_dir", "data/output/clipfarm/")}'
        _runtime.bm_record_pipeline(job)
        _update_marker(_pipeline_marker, status='done', label=f'✅ Pipeline {pipeline_id[:8]} — completed')

    except Exception as exc:
        import traceback

        full_error = traceback.format_exc()
        job['status'] = 'failed'
        job['error'] = str(exc)
        job['error_traceback'] = full_error
        job['current_stage'] = None
        # Stop telemetry logging for this run
        gui_state._TELEMETRY_LOG_PIPELINE_ID = ''
        try:
            log_path = _runtime_path('clipfarm_processing_log.json')
            entries = []
            if os.path.exists(log_path):
                with open(log_path) as _f:
                    entries = json.load(_f)
            entries.append(
                {
                    'level': 'ERROR',
                    'agent': 'pipeline',
                    'pipeline_id': pipeline_id,
                    'message': str(exc),
                    'traceback': full_error,
                    'timestamp': _ams_iso(),
                }
            )
            with open(log_path, 'w') as _f:
                # Preserve all WARNING/ERROR; rotate INFO to last 500
                _kept = [e for e in entries if e.get('level') in ('WARNING', 'ERROR')]
                _info = [e for e in entries if e.get('level') not in ('WARNING', 'ERROR')]
                json.dump(_kept + _info[-500:], _f, indent=2)
        except Exception as _exc:
            _zyg_log.warning('clipfarm error log write failed, this failure leaves no log entry: %s', _exc)
