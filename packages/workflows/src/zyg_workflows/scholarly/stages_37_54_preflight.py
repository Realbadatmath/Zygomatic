# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The six independent steps of `stage_11b_flux_preflight`, one function each.

`stage_11b_flux_preflight` in `stages_37_54` ran 445 lines of flat, unrelated
work: the two pre-emptive record/replay exits, the pre-FLUX Murch self-eval,
the "is the checkpoint downloaded" probe, the stills-backend choice and the
persistent-FluxWorker claim. Nothing crosses between those steps except the
`_flux_ready` flag and the backend decision, so each is a function here and the
stage is the orchestrator that calls them in the monolith's order. Every log
line, every `pipeline_state`/`job` write and their order are the stage's own.

The logger name is the monolith's, as in `stages_37_54`, so one run's debug
lines all stay under `zyg_workflows.pipeline_scholarly`.
"""

import logging as _zyg_logging
import os
import time
from dataclasses import dataclass
from typing import Any

from zyg_workflows import gui_state
from zyg_workflows.pipeline_config import (
    _OLLAMA_BASE_URL,
)
from zyg_workflows.pipeline_scholarly import (
    _ERA_GATE_DEFAULT,
)
from zyg_workflows.runtime import (
    _ams_iso,
)
from zyg_workflows.scholarly.context import StageExit
from zyg_workflows.subproc_registry import _update_marker
from zyg_workflows.subscription_llm import (
    api_key_or_login as _llm_key,
)
from zyg_workflows.vram_manager import (
    _deep_unload_flux_pipeline_cache,
    _release_pipeline_vram,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')

# The arc zone of a slot, by its position in the episode, when the script's own
# visual tags carry none. Fractions are the monolith's ladder.
_ARC_ZONE_BOUNDS = (
    (0.15, 'exposition'),
    (0.45, 'rising'),
    (0.65, 'climax'),
    (0.85, 'falling'),
)

# Intensity → shot size, for the arc zones that do not pin a shot themselves.
_SHOT_BY_INTENSITY = (
    (0.85, 'extreme close-up'),
    (0.65, 'close-up'),
    (0.45, 'medium shot'),
)

# Arc zones that pin their own shot regardless of intensity.
_SHOT_BY_ARC = {
    'exposition': 'wide establishing shot',
    'resolution': 'medium wide shot, reflective',
}


def preempt_replay_exit(ctx) -> StageExit:
    """End a pre-emptive replay-verify run: report the bank's hit rate and stop.

    The brain replayed from the bank up to this point and no image is rendered,
    so the job is completed here, the scratch folder is dropped and `StageExit`
    tells the call site to return out of the pipeline.
    """
    job = ctx.job
    pipeline_state = ctx.pipeline_state
    directive = ctx.directive
    topic = ctx.topic
    out_dir = ctx.out_dir
    _prebuilt_prompts = ctx._prebuilt_prompts
    _pctx_dry = ctx._pbank.current() or {}
    job['status'] = 'completed'
    job['ended'] = _ams_iso()
    job['current_stage'] = None
    job['preempt_stats'] = {k: _pctx_dry.get(k) for k in ('hits', 'misses', 'live', 'refused')}
    job['result'] = (
        f'Pre-emptive replay verified for "{directive or topic}": '
        f'{_pctx_dry.get("hits", 0)} replayed, {_pctx_dry.get("misses", 0)} missed, '
        f'{_pctx_dry.get("live", 0)} live, {_pctx_dry.get("refused", 0)} refused; '
        f'{len(_prebuilt_prompts or [])} prompt pairs, no render.'
    )
    pipeline_state['department'] = 'scholarly-preempt'
    pipeline_state['preempt'] = {
        'mode': 'replay',
        'dry_run': True,
        'entry': ctx._preempt_entry,
        'stats': job['preempt_stats'],
    }
    pipeline_state['ended'] = job['ended']
    pipeline_state['status'] = 'completed'
    pipeline_state['stage_timeline'] = job.get('stage_timeline', [])
    ctx._save()
    _update_marker(
        ctx._pipeline_marker,
        status='done',
        label=f'🧠 Replay check {ctx.pipeline_id[:8]} — {(directive or topic)[:40]}',
    )
    ctx._log('INFO', 'COMPLETE', job['result'])
    gui_state._TELEMETRY_LOG_PIPELINE_ID = ''
    try:
        import shutil as _sh_dry

        _sh_dry.rmtree(out_dir, ignore_errors=True)
    except OSError as _exc:
        _zyg_log.debug('dry-run scratch folder %s not removed: %s', out_dir, _exc)
    return StageExit()


def record_era_checks(ctx) -> None:
    """Extract the era-gate checks now so a replay run finds them in the ledger.

    The render gate builds the same inputs at its own start, one text call per 20
    prompts; a record run must make that call while it is still making text calls
    at all. A failure here only skips the recording — the run still snapshots.
    """
    _era_lock = ctx._era_lock
    _prebuilt_prompts = ctx._prebuilt_prompts
    _log = ctx._log
    _debug = ctx._debug
    try:
        _era_on = _era_lock.get('is_historical') and os.environ.get(
            'ZYG_SCHOLARLY_VLM_ERA', _ERA_GATE_DEFAULT
        ).lower() not in ('0', 'false', 'no', '')
        if _era_on and _prebuilt_prompts:
            from zyg_workflows import era_gate as _eg_rec

            _s_rec = []
            for _pi in range(ctx._n_flux_images):
                _pb_rec = _prebuilt_prompts[_pi] if _prebuilt_prompts and _pi < len(_prebuilt_prompts) else ''
                _s_rec.append(_pb_rec.get('standard', '') if isinstance(_pb_rec, dict) else str(_pb_rec or ''))
            _t_rec = time.time()
            _rec_checks = _eg_rec.extract_checks(
                _s_rec, _era_lock, api_key=_llm_key(), log=lambda m: _debug('Stage 3.5', m)
            )
            _log(
                'INFO',
                'Stage 3.5',
                f'[preempt] era checks recorded for {len(_rec_checks)} slots in {time.time() - _t_rec:.1f}s',
            )
    except Exception as _rec_e:
        _log('WARNING', 'Stage 3.5', f'[preempt] era check recording skipped: {_rec_e!r}')


def preempt_record_exit(ctx) -> StageExit:
    """End a pre-emptive record run: snapshot the brain and stop before any render.

    Every text Claude call has been made by now, so the era checks are recorded,
    `pipeline_state` plus the era lock and the prompt-pair count are snapshotted
    into the bank, the job is completed and the scratch folder — a record run's
    working folder is not an episode — is dropped.
    """
    record_era_checks(ctx)
    job = ctx.job
    pipeline_state = ctx.pipeline_state
    directive = ctx.directive
    topic = ctx.topic
    out_dir = ctx.out_dir
    _preempt_entry = ctx._preempt_entry
    _prebuilt_prompts = ctx._prebuilt_prompts
    _snap = dict(pipeline_state)
    _snap['script'] = pipeline_state.get('script') or ctx.narration_script
    _snap['era_lock'] = ctx._era_lock
    _snap['directive'] = directive
    _snap['flux_prompt_pairs'] = len(_prebuilt_prompts or [])
    ctx._pbank.snapshot(_preempt_entry, _snap)
    _n_rec = ctx._pbank.turn_count(_preempt_entry)
    job['status'] = 'completed'
    job['ended'] = _ams_iso()
    job['current_stage'] = None
    job['result'] = (
        f'Pre-emptive brain recorded for "{directive or topic}": {_n_rec} Claude turns, '
        f'{len(_prebuilt_prompts or [])} prompt pairs, no render.'
    )
    job['preempt_turns'] = _n_rec
    pipeline_state['department'] = 'scholarly-preempt'  # not a produced episode (topic dedup)
    pipeline_state['preempt'] = {'mode': 'record', 'entry': _preempt_entry, 'turns': _n_rec}
    pipeline_state['ended'] = job['ended']
    pipeline_state['status'] = 'completed'
    pipeline_state['stage_timeline'] = job.get('stage_timeline', [])
    ctx._save()
    _update_marker(
        ctx._pipeline_marker,
        status='done',
        label=f'🧠 Pre-emptive {ctx.pipeline_id[:8]} — {(directive or topic)[:40]} recorded',
    )
    ctx._log('INFO', 'COMPLETE', job['result'])
    gui_state._TELEMETRY_LOG_PIPELINE_ID = ''
    try:
        import shutil as _sh_rec

        _sh_rec.rmtree(out_dir, ignore_errors=True)
    except OSError as _exc:
        _zyg_log.debug('record-run scratch folder %s not removed: %s', out_dir, _exc)
    return StageExit()


def arc_zone_for_fraction(frac: float) -> str:
    """Return the narrative arc zone of a slot `frac` of the way through the episode."""
    for _bound, _zone in _ARC_ZONE_BOUNDS:
        if frac < _bound:
            return _zone
    return 'resolution'


def shot_type_for_slot(arc, intensity: float) -> str:
    """Return the shot size for a slot in arc zone `arc` at emotional `intensity`.

    Exposition and resolution pin their own shot; everything else gets tighter as
    the intensity rises.
    """
    if arc in _SHOT_BY_ARC:
        return _SHOT_BY_ARC[arc]
    for _floor, _shot in _SHOT_BY_INTENSITY:
        if intensity >= _floor:
            return _shot
    return 'medium wide shot'


def build_pre_eval_sequence(n_flux_images, pipeline_state, prebuilt_prompts, topic) -> list:
    """Build the slot sequence the Murch self-eval scores, before any image exists.

    One dict per planned still, carrying the emotion and intensity sampled from
    `emotion_curve`, the arc zone (from `visual_tags` when the script supplied
    one, else from the slot's position), the shot size that follows from both,
    the first 60 characters of the slot's prompt and the slot's share of
    `tts_duration`. `transition` is a placeholder the caller replaces with the
    real plan.
    """
    _ec_pre = pipeline_state.get('emotion_curve', [])
    _vt_pre = pipeline_state.get('visual_tags', [])
    _n_pre = max(n_flux_images, 1)
    _pre_seq = []
    for _pi in range(_n_pre):
        _frac_pi = _pi / max(_n_pre - 1, 1)
        _ec_i = min(int(_pi * len(_ec_pre) / _n_pre), len(_ec_pre) - 1) if _ec_pre else 0
        _emo_pi = _ec_pre[_ec_i].get('emotion', 'calm') if _ec_pre else 'calm'
        _int_pi = round(_ec_pre[_ec_i].get('intensity', 0.2), 2) if _ec_pre else 0.2
        _arc_pi = _vt_pre[min(_pi, len(_vt_pre) - 1)].get('arc') if _vt_pre else arc_zone_for_fraction(_frac_pi)
        _shot_pi = shot_type_for_slot(_arc_pi, _int_pi)
        _pb_pi = prebuilt_prompts[_pi] if _pi < len(prebuilt_prompts) else None
        _prompt_pi = (
            (_pb_pi['standard'] if isinstance(_pb_pi, dict) else _pb_pi)[:60]
            if _pb_pi
            else (_vt_pre[min(_pi, len(_vt_pre) - 1)].get('tag', topic)[:60] if _vt_pre else topic)
        )
        _pre_seq.append(
            {
                'idx': _pi,
                'shot_type': _shot_pi,
                'emotion': _emo_pi,
                'intensity': _int_pi,
                'duration': max(3.0, pipeline_state.get('tts_duration', 300) / _n_pre),
                'prompt': _prompt_pi,
                'counterpoint': False,
                'transition': 'dissolve',  # replaced below with the real plan
                'description': _arc_pi,
            }
        )
    return _pre_seq


def apply_transition_plan(pre_seq, murch_engine, debug) -> None:
    """Replace each slot's placeholder transition with the one Stage 6 will cut.

    Every slot used to be reported as 'dissolve', so the evaluator kept returning
    "relies too heavily on repetitive dissolves" — a faithful reading of data that
    was simply wrong. The Sikh Empire run actually cut 6 distinct transition types
    (18 dissolve, 6 cut, 4 smoothleft, 3 zoomin, fadewhite…). The Stage 6 planner
    is deterministic given durations + emotions + shot types, all of which are
    known here, so it is run now and what it chose is reported. On failure the
    eval sees all-dissolve, as it did before.
    """
    try:
        _, _pre_xf_manifest = murch_engine.build_xfade_filter_graph(
            [_s['duration'] for _s in pre_seq],
            [_s['emotion'] for _s in pre_seq],
            shot_types=[_s['shot_type'] for _s in pre_seq],
        )
        _pre_xf_by_idx = {_m.get('idx'): _m.get('transition') for _m in (_pre_xf_manifest or [])}
        for _s in pre_seq:
            if _pre_xf_by_idx.get(_s['idx']):
                _s['transition'] = _pre_xf_by_idx[_s['idx']]
        from collections import Counter as _CtrXf

        debug(
            '3.5/pre-eval',
            'Transition plan fed to self-eval: '
            + ', '.join(f'{_k}×{_v}' for _k, _v in _CtrXf(_s['transition'] for _s in pre_seq).most_common()),
        )
    except Exception as _pre_xf_e:
        debug('3.5/pre-eval', f'Transition pre-plan failed, eval sees all-dissolve: {_pre_xf_e}', level='WARN')


def report_self_eval(pre_eval, pre_eval_debug, pipeline_state, job, log, debug) -> None:
    """Record the self-eval verdict and surface a score below the Murch floor.

    The score was recorded and never read: the last four runs scored 4, 6, 4, 4
    out of 10 and shipped unremarked. A score under `ZYG_SCHOLARLY_MURCH_FLOOR`
    (6) is logged as a warning with up to three of its suggestions attached, so
    the sequence plan gets looked at instead of silently accepted.
    """
    pipeline_state['murch_eval'] = pre_eval
    job['murch_eval'] = pre_eval
    log(
        'INFO',
        'Stage 3.5',
        f'Pre-FLUX Murch self-eval: score={pre_eval.get("score", "?")} '
        f'weakest={pre_eval.get("weakest_cuts", "?")} — '
        f'{pre_eval.get("overall_notes", "")[:80]}',
    )
    try:
        _pre_score = int(pre_eval.get('score') or 0)
    except (TypeError, ValueError):
        _pre_score = 0
    _pre_floor = int(os.environ.get('ZYG_SCHOLARLY_MURCH_FLOOR', '6') or 6)
    if 0 < _pre_score < _pre_floor:
        log(
            'WARNING',
            'Stage 3.5',
            f'Murch self-eval score {_pre_score}/10 is below the {_pre_floor} floor '
            f'— sequence plan is weak: {pre_eval.get("overall_notes", "")[:160]}',
        )
        for _pre_sug in (pre_eval.get('suggestions') or [])[:3]:
            log('WARNING', 'Stage 3.5', f'  murch: {str(_pre_sug)[:160]}')
    for _mde in pre_eval_debug:
        debug(f'3.5/pre-eval/{_mde["fn"]}', _mde['msg'], level=_mde.get('level', 'DEBUG'))


def run_pre_flux_self_eval(ctx) -> None:
    """Score the planned shot sequence with Murch before FLUX takes the VRAM.

    Option A: the scoring runs now, while Ollama is still unloaded and FLUX has
    not started. This avoids the OOM crash that happens when the self-eval runs
    after FLUX + TTS have already saturated the 4090. A failure anywhere in here
    is a warning — the run goes on without a score.
    """
    _log = ctx._log
    _debug = ctx._debug
    try:
        from zyg_workflows import murch_engine as _me_pre

        _pre_seq = build_pre_eval_sequence(ctx._n_flux_images, ctx.pipeline_state, ctx._prebuilt_prompts, ctx.topic)
        apply_transition_plan(_pre_seq, _me_pre, _debug)
        _pre_eval_debug: list = []
        _pre_eval = _me_pre.self_evaluate_sequence(
            _pre_seq,
            ollama_url=_OLLAMA_BASE_URL,
            debug_log=_pre_eval_debug,
            pipeline_id=ctx.pipeline_id,
        )
        report_self_eval(_pre_eval, _pre_eval_debug, ctx.pipeline_state, ctx.job, _log, _debug)
    except Exception as _pre_eval_err:
        _log('WARNING', 'Stage 3.5', f'Pre-FLUX Murch self-eval failed: {_pre_eval_err}')
        _debug('Stage 3.5', f'Self-eval exception: {_pre_eval_err}', level='ERROR')


def probe_flux_ready(flux_model_path, log) -> bool:
    """Return True when every transformer shard of the FLUX checkpoint is on disk.

    The shards total more than 20 GB once complete, so the summed size of the
    `.safetensors` files in `<model>/transformer` is the download probe. A missing
    directory is "not ready" and logs nothing.
    """
    _flux_ready = False
    _transformer_dir = os.path.join(flux_model_path, 'transformer')
    if os.path.isdir(_transformer_dir):
        _safetensors = [
            f for f in os.listdir(_transformer_dir) if f.endswith('.safetensors') and not f.endswith('.index.json')
        ]
        _total_size = sum(os.path.getsize(os.path.join(_transformer_dir, f)) for f in _safetensors)
        _flux_ready = _total_size > 20 * 1024**3  # >20GB means all shards present
        log(
            'INFO',
            'Stage 3.5',
            f'Transformer size: {_total_size / 1024**3:.1f}GB — {"ready" if _flux_ready else "still downloading"}',
        )
    return _flux_ready


def probe_qwen_t2i(comfy_service) -> tuple:
    """Return `(available, why_not)` for the Qwen-Image-2512 stills path.

    `why_not` is the empty string when Qwen is usable, and otherwise the reason a
    run must say out loud before falling back to FLUX.
    """
    _qwen_ok = False
    _qwen_why = ''
    try:
        if not comfy_service.is_available():
            _qwen_why = 'ComfyUI not available (ZYG_USE_COMFYUI / server / breaker)'
        elif not comfy_service.has_qwen_t2i():
            _qwen_why = 'Qwen-Image-2512 checkpoint not found in the ComfyUI unet dir'
        else:
            _qwen_ok = True
    except Exception as _qwen_e:
        _qwen_why = f'probe failed: {_qwen_e!r}'
    return _qwen_ok, _qwen_why


@dataclass
class StillsBackendChoice:
    """Which renderer Stage 3.5 will use for the stills, and what that implies."""

    still_family: str
    qwen_stills: bool
    use_comfy_images: bool
    skip_local_flux: bool
    comfy_only: bool


def choose_stills_backend(ctx, sch_backend, flux_ready, log) -> StillsBackendChoice:
    """Pick the stills backend for this run — Qwen via Comfy, Comfy curation, or FLUX.

    See `scholarly_stills_backend`: still family 'qwen' (the default since
    2026-08-25) is Qwen-Image-2512 through ComfyUI — Apache-2.0, real CFG (so
    negatives are LIVE, unlike schnell at guidance 0), the full prompt reaches a
    7B text encoder (no 320-char CLIP-L window) and prompt adherence is far
    stronger; the Black Death audit traced subject-absent renders, the CG nave,
    baked-in letterbox bars, eight cloned faces and the modern-object priors to a
    4-step distilled model at guidance 0. Still family 'flux' is the in-process
    FLUX.1-schnell + diffusers path, byte-for-byte the pre-08-25 production one
    (`ZYG_SCHOLARLY_STILL_FAMILY=flux`), and `ZYG_SCHOLARLY_COMFY_IMAGES=1` is the
    FLUX-on-Comfy curation path (HandFixer + pose/IP), unchanged.

    If Qwen is asked for and ComfyUI / the 2512 checkpoint is not there, the run
    falls back to FLUX and SAYS so — never silently. Whichever path wins, the
    VRAM the previous stage left behind is released before it starts.
    """
    _sch_skip_local_flux = False
    _sch_comfy_only = False
    _sch_use_comfy_images = sch_backend.scholarly_comfy_curation_enabled()
    _sch_still_family = sch_backend.scholarly_still_family()
    _sch_qwen_stills = False
    ctx._sch_qwen_stills = _sch_qwen_stills
    try:
        from zyg_workflows import comfy_generation_service as _cgs_sch_gate

        _force_flux_local_sch = os.environ.get('ZYG_FORCE_FLUX_LOCAL', '').strip().lower() in (
            '1',
            'true',
            'yes',
            'on',
        )
        if _sch_still_family == 'qwen' and not _force_flux_local_sch:
            _qwen_ok, _qwen_why = probe_qwen_t2i(_cgs_sch_gate)
            if _qwen_ok:
                _sch_qwen_stills = True
                ctx._sch_qwen_stills = _sch_qwen_stills
                _sch_use_comfy_images = True
                log(
                    'INFO',
                    'Stage 3.5',
                    'Documentary stills: Qwen-Image-2512 via ComfyUI (Apache-2.0, real CFG, '
                    'negatives live) — ZYG_SCHOLARLY_STILL_FAMILY=flux restores FLUX.1-schnell',
                )
            else:
                _sch_still_family = 'flux'
                log(
                    'WARNING',
                    'Stage 3.5',
                    f'Qwen stills requested but unavailable — {_qwen_why}. Falling back to '
                    f'in-process FLUX.1-schnell for this run.',
                )
        if _sch_use_comfy_images and _cgs_sch_gate.is_available() and not _force_flux_local_sch:
            _sch_skip_local_flux = True
            _sch_comfy_only = True
            log(
                'INFO',
                'Stage 3.5',
                (
                    'Qwen-Image path — scholarly stills via Comfy only (skipping in-process FLUX)'
                    if _sch_qwen_stills
                    else 'Comfy curation path — scholarly stills via Comfy only '
                    f'(skipping in-process FLUX; {sch_backend.SCHOLARLY_COMFY_CURATION_ENV}=1). '
                    f'{sch_backend.scholarly_comfy_curation_hint()}'
                ),
            )
            _deep_unload_flux_pipeline_cache(log_fn=lambda m: log('INFO', 'Stage 3.5', m))
            try:
                from zyg_workflows import _comfy_client as _cc_sch35

                _ok_vg_s35, _free_s35 = _cc_sch35.wait_for_free_vram_gb(
                    min_free_gb=20.0,
                    timeout_s=180.0,
                    poll_s=5.0,
                    try_evict=True,
                    log_fn=lambda m: log('INFO', 'Stage 3.5', m),
                )
                log(
                    'INFO',
                    'Stage 3.5',
                    f'Pre-Comfy VRAM wait: ok={_ok_vg_s35} free={_free_s35:.1f} GB',
                )
            except Exception as _vg_s35_e:
                log('WARNING', 'Stage 3.5', f'Pre-Comfy VRAM wait failed: {_vg_s35_e}')
        elif flux_ready and not _force_flux_local_sch:
            log(
                'INFO',
                'Stage 3.5',
                f'Documentary stills — production default: in-process FLUX.1-schnell + '
                f'diffusers ({sch_backend.SCHOLARLY_PRODUCTION_BACKEND}). '
                f'{sch_backend.scholarly_comfy_curation_hint()}',
            )
            _deep_unload_flux_pipeline_cache(log_fn=lambda m: log('INFO', 'Stage 3.5', m))
            try:
                _release_pipeline_vram(
                    'Stage 3.5',
                    log_fn=lambda m: log('INFO', 'Stage 3.5', m),
                    wait_comfy=True,
                )
            except Exception as _rel_s35_e:
                log('WARNING', 'Stage 3.5', f'Pre-FLUX Comfy release failed: {_rel_s35_e}')
    except ImportError as _exc:
        _zyg_log.debug(
            'comfy_generation_service unavailable — the Comfy stills gate is skipped '
            'and the stills stay on in-process FLUX: %s',
            _exc,
        )
    return StillsBackendChoice(
        still_family=_sch_still_family,
        qwen_stills=_sch_qwen_stills,
        use_comfy_images=_sch_use_comfy_images,
        skip_local_flux=_sch_skip_local_flux,
        comfy_only=_sch_comfy_only,
    )


def claim_flux_worker(sch_backend, flux_ready, comfy_only, log) -> tuple:
    """Join or claim the persistent FluxWorker; return `(worker, active, claimed_start)`.

    A worker already running means this run skips the FLUX load and the GPU lock
    entirely (`active`). Winning `claim_start` means this run loads FLUX and then
    starts the worker (`claimed_start`). Losing the claim race falls back to
    joining the winner, and any failure on either path returns `(None, False,
    False)` — a per-pipeline load, as before the worker existed.
    """
    _sch_fw: Any = None
    _sch_fw_active = False
    _fw_claimed_start = False
    if not (flux_ready and not comfy_only and sch_backend.scholarly_flux_persistent_enabled()):
        return _sch_fw, _sch_fw_active, _fw_claimed_start
    _sch_fw = sch_backend.ScholarlyFluxWorker.get()
    if _sch_fw.is_running_or_starting():
        try:
            _sch_fw.wait_until_running(timeout=120.0)
            _sch_fw_active = True
            log('INFO', 'Stage 3.5', '[FluxWorker] joining running persistent worker — FLUX load/lock skipped')
        except Exception as _fw_join_e:
            log(
                'WARNING',
                'Stage 3.5',
                f'[FluxWorker] join failed ({_fw_join_e}) — falling back to per-pipeline load',
            )
            _sch_fw = None
    elif _sch_fw.claim_start():
        _fw_claimed_start = True
        log('INFO', 'Stage 3.5', '[FluxWorker] claimed start — will start persistent worker after FLUX load')
    else:
        # Race: someone else claimed start between our check and our claim
        try:
            _sch_fw.wait_until_running(timeout=120.0)
            _sch_fw_active = True
            log('INFO', 'Stage 3.5', '[FluxWorker] claim race resolved — joining running worker')
        except Exception as _fw_race_e:
            log(
                'WARNING',
                'Stage 3.5',
                f'[FluxWorker] claim race fallback failed ({_fw_race_e}) — per-pipeline load',
            )
            _sch_fw = None
    return _sch_fw, _sch_fw_active, _fw_claimed_start
