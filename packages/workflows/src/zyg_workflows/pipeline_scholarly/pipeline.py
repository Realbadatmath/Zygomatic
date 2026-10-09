"""pipeline_scholarly.pipeline — the _run_scholarly_pipeline stage ladder.

Lines 1166-1424 of the original pipeline_scholarly.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from zyg_workflows import gui_state
from zyg_workflows import runtime
from zyg_workflows.pipeline_common import SMOKE_MARKER_FILE
from zyg_workflows.pipeline_common import is_test_pipeline_id
from zyg_workflows.pipeline_common import smoke_output_root
from zyg_workflows.pipeline_config import _RUNTIME_DIR
from zyg_workflows.runtime import _ams_iso
from zyg_workflows.runtime import _runtime_path
from zyg_workflows.runtime import workflow_jobs as _workflow_jobs
from zyg_workflows.subproc_registry import _register_marker
from zyg_workflows.vram_manager import _hw_monitor_loop
import os
import threading
import logging as _zyg_logging

from .constants import (
    _MODULE_IMPORTED_AT,
    _scholarly_duration_targets,
    _scholarly_image_intensity,
    _smoke_cap,
)

# The single-file module logged under its own module name; __package__ is
# that same dotted name now that the module is a package, so the logger's
# name is unchanged.
_zyg_log = _zyg_logging.getLogger(__package__)


def _run_scholarly_pipeline(
    pipeline_id: str,
    topic: str = 'crime',
    directive: str = None,
    narration_enabled: bool = True,
    visual_style: str = 'cinematic',
):
    """
    Scholarly pipeline: scrape open-access academic repositories for essays/papers
    on the chosen topic, then narrate them as a documentary-style video.
    Shares Stages 3–6 with the crime pipeline (TTS, visuals, video assembly).
    """
    import importlib.util as _ilu_sch

    pass  # (global stmt removed: names moved to gui_state)
    job = _workflow_jobs[pipeline_id]
    job['stages'] = {}
    job['department'] = 'scholarly'
    pipeline_options = job.get('pipeline_options') or {}
    if directive:
        job['directive'] = directive
    # ── Pre-Emptive bank (preempt_bank.py, 2026-09-20) ──────────────────────
    # record: every text Claude call is written to the bank entry and the run stops
    # before the first image; replay: Stage 2 takes the banked essay and every text
    # call is answered from the ledger (subscription_llm.run_turn does the lookup).
    _preempt_opt = pipeline_options.get('preempt') if isinstance(pipeline_options.get('preempt'), dict) else None
    _preempt_mode = str((_preempt_opt or {}).get('mode') or '')
    _preempt_entry = str((_preempt_opt or {}).get('entry') or '')
    _preempt_dry = bool((_preempt_opt or {}).get('dry_run'))  # replay verify: stop where a record run stops
    _preempt_token = None
    _pbank = None
    if _preempt_mode in ('record', 'replay') and _preempt_entry:
        try:
            # The bank is a dashboard feature; runtime holds the slot the
            # dashboard registers, and it is None when running headless.
            _pbank = runtime.preempt_bank
            if _pbank is None:
                raise RuntimeError('preempt_bank not registered (headless run)')
            _preempt_token = _pbank.set_context(_preempt_mode, _preempt_entry)
            job['preempt'] = {'mode': _preempt_mode, 'entry': _preempt_entry}
        except Exception as _pe_err:  # noqa: BLE001 — the bank is optional
            _pbank = None
            _preempt_mode = ''
            _zyg_log.info(f'[PREEMPT] context unavailable: {_pe_err!r}')
    _sch_duration_targets = _scholarly_duration_targets(pipeline_options)
    _sch_intensity = _scholarly_image_intensity(pipeline_options)
    _sch_family_label = 'FLUX.1-schnell'  # re-derived at Stage 3.5 from the real still family

    # Smoke provenance (S-02 / P-03): a test run is identified by the live
    # image cap, ZYG_SMOKE_RUN=1, or a test-shaped pipeline id — and lands
    # under <data>/output/smoke/ with a SMOKE_RUN marker, so Cleanup, the
    # Videos tab and the Desktop SFTP copy can tell it from an episode.
    # 28 docsmoke-/gatecheck- folders (≈4 GB) sat beside production runs.
    is_smoke = bool(_smoke_cap() > 0 or os.environ.get('ZYG_SMOKE_RUN') == '1' or is_test_pipeline_id(pipeline_id))
    if is_smoke:
        out_dir = os.path.join(smoke_output_root(), pipeline_id)
    else:
        out_dir = os.path.join(os.path.dirname(_RUNTIME_DIR), 'output', 'clips', pipeline_id)
    os.makedirs(out_dir, exist_ok=True)
    if is_smoke:
        try:
            with open(os.path.join(out_dir, SMOKE_MARKER_FILE), 'w') as _smk_f:
                _smk_f.write(
                    f'pipeline_id={pipeline_id}\n'
                    f'started={_ams_iso()}\n'
                    f'smoke_cap={_smoke_cap()}\n'
                    f'narration_enabled={bool(narration_enabled)}\n'
                    f'visual_style={visual_style}\n'
                )
        except OSError as _exc:
            _zyg_log.warning(
                'SMOKE_RUN marker not written to %s; Cleanup and the Videos tab cannot tell '
                'this run from an episode: %s',
                out_dir,
                _exc,
            )
        job['smoke'] = True
    job['output_dir'] = out_dir
    state_file = _runtime_path(f'pipeline_{pipeline_id}_state.json')

    # Derive a clean slug from the user's directive for output file naming
    import re as _re_slug

    _raw_slug = (directive or topic or 'scholarly').lower()
    _slug = _re_slug.sub(r'[^a-z0-9]+', '_', _raw_slug).strip('_')[:45].rstrip('_') or 'scholarly'

    _sch_char_id = (job.get('char_id') or '').strip()
    pipeline_state = {
        'pipeline_id': pipeline_id,
        'department': 'scholarly',
        'scholarly_topic': topic,
        'char_id': _sch_char_id,
        'started': _ams_iso(),
        'essay_text': '',
        'script': '',
        'tts_path': '',
        'tts_duration': 0,
        'stock_clips': [],
        'video_path': '',
        'processed_clips': [],
        'output_dir': out_dir,
        # Provenance (S-02): the state file used to carry none of the switches
        # that produced the run — only the id prefix and tts_voice='silent'.
        'smoke': is_smoke,
        'narration_enabled': bool(narration_enabled),
        'visual_style': visual_style,
        'scholarly_duration_targets': _sch_duration_targets,
    }

    try:
        from zyg_workflows import llm_audit as _la_init

        _la_init.set_context(pipeline_id=pipeline_id, pipeline_type='scholarly', stage='Stage 1')
    except Exception as _exc:  # noqa: BLE001 — the audit sink is optional
        _zyg_log.warning("llm_audit context not set, this run's LLM calls land unattributed: %s", _exc)

    _pipeline_marker = _register_marker(
        f'📚 Scholarly Pipeline {pipeline_id[:8]} — {topic} — starting', pipeline_id=pipeline_id, status='pipeline'
    )
    threading.Thread(
        target=_hw_monitor_loop, args=(pipeline_id,), daemon=True, name=f'hw-monitor-{pipeline_id[:8]}'
    ).start()
    gui_state._TELEMETRY_LOG_PIPELINE_ID = pipeline_id

    # ── The run scaffold lives in zyg_workflows.scholarly.stages_55_73 ──────
    # Eleven nested helpers — _log, _save, _debug, _done, _stage_start, the gate
    # registry, the stop probes and the inert-lever guard — used to be defined
    # here, over this function's job, state file and gate dict. They are
    # closures, so one factory builds them and hands them back on a RunGlue;
    # unpacked into the same plain locals, every statement below reads as it did
    # when they were nested.
    from zyg_workflows.scholarly.stages_55_73 import (
        stage_55_run_glue,
        stage_56_staleness_gate,
        stage_71_on_user_stop,
        stage_72_on_error,
        stage_73_finalise,
    )

    _glue = stage_55_run_glue(job, pipeline_state, pipeline_id, state_file)
    _log = _glue._log
    _save = _glue._save
    _debug = _glue._debug
    _done = _glue._done
    _stage_start = _glue._stage_start
    _should_stop = _glue._should_stop
    _assert_not_stopped = _glue._assert_not_stopped
    _gate_receipt = _glue._gate_receipt
    _flux_lever_guard = _glue._flux_lever_guard
    _stop_event_scholarly = _glue._stop_event_scholarly

    stage_56_staleness_gate(_glue, __file__, _MODULE_IMPORTED_AT)

    # Record pipeline start time on the job
    if not job.get('started'):
        job['started'] = _ams_iso()

    # ── Every stage lives in zyg_workflows.scholarly ────────────────────────
    # Imported here and not at module level: the stage modules import helpers
    # back out of this one, so a module-level import would close the cycle.
    from zyg_workflows.scholarly.context import RunContext, StageExit
    from zyg_workflows.scholarly.stages_37_54 import (
        stage_11_flux_prompt_batch,
        stage_11b_flux_preflight,
        stage_11c_flux_image_loop,
    )
    from zyg_workflows.scholarly.stages_19_36 import (
        stage_10_flux_image_generation,
        stage_12_hand_qc,
        stage_13_tts_rhythm_refresh,
        stage_14_ltx_motion,
        stage_15_video_assembly,
        stage_16_music_bed,
        stage_17_colour_grade,
        stage_18_book_intro,
        stage_19_burn_subtitles,
    )
    from zyg_workflows.scholarly.stages_01_18 import (
        stage_01_topic_setup,
        stage_02_academic_research,
        stage_03_script_preparation,
        stage_04_fact_check,
        stage_05_visual_intent_tagging,
        stage_06_turning_points_and_emotions,
        stage_07_emotion_curve,
        stage_08_tts_pre_image_pass,
        stage_09_time_locked_scene_descriptions,
    )

    # One object for every local that crosses a stage boundary. The nested
    # closures above travel on it too, so a stage calls the very same _log /
    # _save / _done this function would have called.
    ctx = RunContext(
        pipeline_id=pipeline_id,
        topic=topic,
        directive=directive,
        narration_enabled=narration_enabled,
        visual_style=visual_style,
        job=job,
        pipeline_state=pipeline_state,
        out_dir=out_dir,
        _slug=_slug,
        _pipeline_marker=_pipeline_marker,
        _sch_char_id=_sch_char_id,
        _sch_duration_targets=_sch_duration_targets,
        _sch_intensity=_sch_intensity,
        _stop_event_scholarly=_stop_event_scholarly,
        _ilu_sch=_ilu_sch,
        _pbank=_pbank,
        _preempt_mode=_preempt_mode,
        _preempt_entry=_preempt_entry,
        _preempt_dry=_preempt_dry,
        _log=_log,
        _save=_save,
        _debug=_debug,
        _done=_done,
        _stage_start=_stage_start,
        _assert_not_stopped=_assert_not_stopped,
        _should_stop=_should_stop,
        _gate_receipt=_gate_receipt,
        _flux_lever_guard=_flux_lever_guard,
    )

    try:
        stage_01_topic_setup(ctx)
        stage_02_academic_research(ctx)
        stage_03_script_preparation(ctx)
        stage_04_fact_check(ctx)
        stage_05_visual_intent_tagging(ctx)
        stage_06_turning_points_and_emotions(ctx)
        stage_07_emotion_curve(ctx)
        stage_08_tts_pre_image_pass(ctx)
        stage_09_time_locked_scene_descriptions(ctx)
        stage_10_flux_image_generation(ctx)
        stage_11_flux_prompt_batch(ctx)
        # The pre-emptive record run and the replay verify run both end the
        # pipeline here; a stage cannot return for its caller, so it says so.
        _preempt_exit = stage_11b_flux_preflight(ctx)
        if isinstance(_preempt_exit, StageExit):
            return _preempt_exit.value
        stage_11c_flux_image_loop(ctx)
        stage_12_hand_qc(ctx)
        stage_13_tts_rhythm_refresh(ctx)
        stage_14_ltx_motion(ctx)
        stage_15_video_assembly(ctx)
        stage_16_music_bed(ctx)
        stage_17_colour_grade(ctx)
        stage_18_book_intro(ctx)
        stage_19_burn_subtitles(ctx)

    except StopIteration:
        # Clean stop requested by user — not an error
        stage_71_on_user_stop(_glue, _pipeline_marker)

    except Exception as exc:
        stage_72_on_error(_glue, _pipeline_marker, exc)

    finally:
        stage_73_finalise(_glue, _pbank, _preempt_token)
