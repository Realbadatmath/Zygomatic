# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The crime pipeline orchestrator: the function body's head, the stage calls and its tail.

The stage bodies live in the sibling modules and are called in the original order; every
local the next stage reads is handed to it as an argument and handed back as a result, so
the data flow is the one the single function had.
"""

from .constants import (
    _RUNTIME_DIR,
    _agent_log,
    _ams_iso,
    _ams_now,
    _hw_monitor_loop,
    _parse_iso_to_ams,
    _push_error_log,
    _register_marker,
    _runtime_path,
    _scp_output_to_windows,
    _seal,
    _update_marker,
    _workflow_jobs,
    _zyg_log,
    gui_state,
    json,
    os,
    threading,
)

from .stage3_script import _crime_stage_3_script
from .stage3b_to_6b import _crime_stages_3b_to_6b
from .stage6_assembly import _crime_stage_6d_assembly
from .stage6_segments import _crime_stage_6c_segments
from .stages_1_2 import _crime_stages_1_2


def _run_crime_pipeline(pipeline_id: str, directive: str = None):
    """
    Crime department pipeline: narrate a court case with TTS + stock footage.
    Produces one episode per run (8.5-17 min). Selects the next unprocessed case
    by severity_rank from court_cases.json.
    """
    import subprocess as _sp_crime
    import re as _re_crime
    import urllib.parse as _up_crime

    pass  # (global stmt removed: names moved to gui_state)
    job = _workflow_jobs[pipeline_id]
    job['stages'] = {}
    job['department'] = 'crime'

    # 2026-07-25: crime writes to its OWN output folder (output/crime/) instead of
    # the shared output/clips/, so it can never be caught by the documentary
    # auto-uploader (Creator Nexus scans output/clips only). Every artifact below
    # derives from out_dir, so this single line relocates the whole run.
    out_dir = os.path.join(os.path.dirname(_RUNTIME_DIR), 'output', 'crime', pipeline_id)
    os.makedirs(out_dir, exist_ok=True)
    job['output_dir'] = out_dir
    state_file = _runtime_path(f'pipeline_{pipeline_id}_state.json')

    pipeline_state = {
        'pipeline_id': pipeline_id,
        'department': 'crime',
        'started': _ams_iso(),
        'case': None,
        'court_text': '',
        'script': '',
        'tts_path': '',
        'tts_duration': 0,
        'stock_clips': [],
        'video_path': '',
        'processed_clips': [],
        'output_dir': out_dir,
    }

    _pipeline_marker = _register_marker(
        f'🚔 Crime Pipeline {pipeline_id[:8]} — starting', pipeline_id=pipeline_id, status='pipeline'
    )
    threading.Thread(
        target=_hw_monitor_loop, args=(pipeline_id,), daemon=True, name=f'hw-monitor-{pipeline_id[:8]}'
    ).start()
    gui_state._TELEMETRY_LOG_PIPELINE_ID = pipeline_id

    def _save():
        try:
            with open(state_file, 'w') as _f:
                json.dump(pipeline_state, _f, indent=2)
        except Exception as _exc:
            _zyg_log.warning(
                'pipeline state write to %s failed, the dashboard will not see this run: %s', state_file, _exc
            )

    def _log(level, stage, msg):
        from zoneinfo import ZoneInfo as _ZI

        _ams = _ZI('Europe/Amsterdam')
        _zyg_log.info(f'[CRIME-{level}] {stage}: {msg}')
        _agent_log(level, 'CRIME-PIPELINE', pipeline_id, stage, msg)
        _push_error_log(level, stage, msg, pipeline_id)
        ev = {
            'ts': _ams_iso(),
            'level': level,
            'stage': stage,
            'msg': str(msg)[:400],
        }
        events = job.setdefault('debug_events', [])
        events.append(ev)
        if len(events) > 1000:
            del events[0]

    def _done(stage, extra=None):
        d = {'status': 'completed'}
        if extra:
            d.update(extra)
        job['stages'][stage] = d

    try:
        court_text, selected, used_cases_path, used_ids = _crime_stages_1_2(
            _done, _log, _pipeline_marker, _save, _up_crime, job, pipeline_id, pipeline_state
        )
        _stage3_llm_inst, _stage3_llm_model, narration_script = _crime_stage_3_script(
            _done, _log, _pipeline_marker, _save, court_text, job, out_dir, pipeline_id, pipeline_state, selected
        )
        (
            _case_name,
            _doc_cards,
            _word_timings,
            final_video_path,
            stock_clips,
            stock_images,
            tts_duration,
            tts_path,
            video_assembled,
        ) = _crime_stages_3b_to_6b(
            _done,
            _log,
            _pipeline_marker,
            _re_crime,
            _save,
            _sp_crime,
            _stage3_llm_inst,
            _stage3_llm_model,
            job,
            narration_script,
            out_dir,
            pipeline_id,
            pipeline_state,
            selected,
        )
        _img_to_clip, _person_infobox_clip, _person_time_triggers, _shown_persons, named_persons = (
            _crime_stage_6c_segments(
                _log, _sp_crime, _word_timings, narration_script, out_dir, pipeline_state, tts_duration
            )
        )
        _crime_stage_6d_assembly(
            _case_name,
            _doc_cards,
            _img_to_clip,
            _log,
            _person_infobox_clip,
            _person_time_triggers,
            _shown_persons,
            _sp_crime,
            _word_timings,
            final_video_path,
            named_persons,
            out_dir,
            pipeline_id,
            pipeline_state,
            stock_clips,
            stock_images,
            tts_duration,
            tts_path,
            video_assembled,
        )

        # ── Content credential: the episode, after the loudness pass ────────
        # The loudnorm move above is the last rewrite of final_video_path, so
        # the delivered bytes are final here. Fail-safe: a missing key logs and
        # leaves the file untouched rather than losing a finished episode.
        _seal.seal(
            final_video_path,
            pipeline='crime',
            run_id=pipeline_id,
            title=f'Crime Chronicles: {_case_name}',
            extra={'case_id': str(selected.get('case_id') or '')},
            log_fn=lambda m: _log('INFO', 'Content Credential', m),
        )

        pipeline_state['video_path'] = final_video_path
        pipeline_state['processed_clips'] = [
            {
                'video_id': f'crime_{selected.get("case_id", pipeline_id[:8])}',
                'clip_index': 1,
                'path': final_video_path,
                'source_ts': 0,
                'case_name': _case_name,
                'department': 'crime',
                'title': f'Crime Chronicles: {_case_name}',
            }
        ]
        _save()
        _done(
            'Stage 6: Video Assembly',
            {'path': final_video_path, 'size_mb': round(os.path.getsize(final_video_path) / 1024 / 1024, 1)},
        )

        # ── Mark case as used ───────────────────────────────────────────────
        used_ids.add(selected.get('case_id'))
        try:
            with open(used_cases_path, 'w') as _uf:
                json.dump(list(used_ids), _uf)
        except Exception as _exc:
            _zyg_log.warning('used-cases list write to %s failed, a case may be reused: %s', used_cases_path, _exc)

        # ── SFTP Delivery ────────────────────────────────────────────────────
        job['current_stage'] = 'Delivering to Desktop'
        _update_marker(_pipeline_marker, label=f'🔄 Crime {pipeline_id[:8]} — SFTP Delivery')
        _scp_output_to_windows(out_dir, pipeline_id)

        # ── Complete ─────────────────────────────────────────────────────────
        job['status'] = 'completed'
        job['current_stage'] = None
        gui_state._TELEMETRY_LOG_PIPELINE_ID = ''
        try:
            _t_start = _parse_iso_to_ams(pipeline_state.get('started', ''))
            if _t_start is not None:
                _elapsed = (_ams_now() - _t_start).total_seconds()
                _m, _s = divmod(int(_elapsed), 60)
                _dur = f'{_m}m {_s}s'
            else:
                _dur = None
        except Exception:
            _dur = None

        job['result'] = (
            f'Crime pipeline completed. Case: {_case_name}. '
            f'1 episode processed. ' + (f'Duration: {_dur}. ' if _dur else '') + f'Output: {final_video_path}'
        )
        _update_marker(_pipeline_marker, status='done', label=f'✅ Crime {pipeline_id[:8]} — {_case_name} complete')
        _log('INFO', 'COMPLETE', job['result'])

    except Exception as exc:
        import traceback

        job['status'] = 'failed'
        job['error'] = str(exc)
        job['error_traceback'] = traceback.format_exc()
        job['current_stage'] = None
        gui_state._TELEMETRY_LOG_PIPELINE_ID = ''
        _update_marker(_pipeline_marker, status='error', label=f'❌ Crime {pipeline_id[:8]} — failed: {str(exc)[:60]}')
        _log('ERROR', 'PIPELINE', f'Crime pipeline failed: {exc}\n{traceback.format_exc()}')
