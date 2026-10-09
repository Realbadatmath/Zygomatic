# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stages 3.7, 3.8 and 3.9 — hand QC, the TTS rhythm refresh and LTX motion."""

from ._common import (
    UNSET,
    _SCHOLARLY_SEC_PER_WORD,
    _scholarly_motion,
    _update_marker,
    os,
)


def stage_12_hand_qc(ctx):
    _assert_not_stopped = ctx._assert_not_stopped
    _debug = ctx._debug
    _done = ctx._done
    _essay_title_for_prompt = ctx._essay_title_for_prompt
    _flux_generated_paths = ctx._flux_generated_paths
    _flux_image_meta = ctx._flux_image_meta
    _gate_receipt = ctx._gate_receipt
    _log = ctx._log
    _murch_image_debug = ctx._murch_image_debug
    _n_flux_images = ctx._n_flux_images
    _save = ctx._save
    _sch_fw = ctx._sch_fw
    _stage_start = ctx._stage_start
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    topic = ctx.topic
    if ctx._sch_typography_pass is not UNSET:
        _sch_typography_pass = ctx._sch_typography_pass
    if ctx._sch_hand_qc_pass is not UNSET:
        _sch_hand_qc_pass = ctx._sch_hand_qc_pass

    # ── Stage 3.7: Hand QC ───────────────────────────────────────────────
    # Deliberately out HERE, after the FLUX section's `finally` has released
    # the pipe slot and the GPU lock. Inside that section the card is still
    # held: measured 6.5 GB free there, against 36.1 GB once the worker lets
    # go — and the judge is a 6.6 GB model, so the difference is the whole
    # gate. See _hand_qc_post_pass for the two earlier placements and what
    # each of them actually reported.
    # ── Free the card for the QC judges ──────────────────────────────────
    # Both post-passes need a vision model on the GPU, and both were still
    # reading 6.5 GB free here. Releasing the pipe slot is not enough: with
    # ZYG_SCHOLARLY_FLUX_PERSISTENT=1 the worker deliberately KEEPS FLUX
    # loaded for the next batch, and only drops it when its idle timer
    # expires — which landed in the middle of Stage 6 on the measured runs.
    # Waiting on that timer is a race, so ask the worker to stand down.
    #
    # emergency_stop() only tears down when the pipe lock is free, i.e. when
    # no other pipeline is mid-inference, so this cannot interrupt a
    # concurrent batch. The cost is one FLUX reload for whoever comes next:
    # 20 s, measured. Hand QC coverage is worth 20 s.
    def _free_gpu_for_qc(need_gb: float = 14.0) -> float:
        def _free():
            try:
                from zyg_workflows.vram_manager import _get_free_vram_gb as _fv

                return float(_fv())
            except Exception:
                return -1.0

        _f = _free()
        if _f < 0 or _f >= need_gb:
            return _f
        try:
            _fw_q = _sch_fw
        except NameError:
            _fw_q = None
        if _fw_q is None:
            return _f
        _log(
            'INFO',
            'Stage 3.6',
            f'{_f:.1f} GB free — asking the persistent FLUX worker to stand '
            f'down so the QC judges can load (needs ~{need_gb:.0f} GB)',
        )
        try:
            _fw_q.emergency_stop(lambda m: _log('INFO', 'Stage 3.6', m))
        except Exception as _fw_e:
            _log('WARNING', 'Stage 3.6', f'worker stop failed: {_fw_e!r}')
            return _f
        import time as _t_q

        for _ in range(30):
            _t_q.sleep(2)
            _f = _free()
            if _f >= need_gb:
                break
        _log('INFO', 'Stage 3.6', f'VRAM after worker stand-down: {_f:.1f} GB free')
        return _f

    try:
        _free_gpu_for_qc(14.0)
    except Exception as _fq_e:
        _log('WARNING', 'Stage 3.6', f'VRAM reclaim for QC failed: {_fq_e!r}')

    # Typography first: it is the gate whose verdict the ladder needed and
    # never got, so its numbers belong next to the flagged-shipment report.
    try:
        _sch_typography_pass()
    except NameError:
        _gate_receipt('typography', False, 'FLUX stage did not run — no frames to judge')
    except Exception as _tp_call_e:
        _gate_receipt('typography', False, f'sweep call failed: {_tp_call_e!r}')

    try:
        _sch_hand_qc_pass()
    except NameError:
        # FLUX never ran, so there is no closure and there are no frames.
        _gate_receipt('hand_qc', False, 'FLUX stage did not run — no frames to judge')
    except Exception as _hq_call_e:
        _gate_receipt('hand_qc', False, f'post-pass call failed: {_hq_call_e!r}')

    # Inject generated images into essay_images for Stage 6 slideshow
    # Each entry carries full metadata so asset manager can display, search and filter properly.
    if _flux_generated_paths:
        _existing = pipeline_state.get('essay_images', [])
        _flux_entries = [
            {
                'path': m['path'],
                'index': m['index'],
                'source': 'flux',
                'model': m.get('model') or 'FLUX.1-schnell',
                'alt': f'{m["subject"]} — {m["tag"]} (slot {m["index"] + 1}/{_n_flux_images})',
                'caption': m['narration_segment'],
                'prompt': m['prompt'],
                'subject': m['subject'],
                'tag': m['tag'],
                'shot_type': m.get('shot_type', ''),
                'emotion': m.get('emotion', ''),
                'focal_zone': m.get('focal_zone', 'center'),
                'slot_seconds': m['slot_seconds'],
                'pipeline_id': pipeline_id,
                'topic': topic,
                'essay_title': _essay_title_for_prompt,
            }
            for m in _flux_image_meta
        ]
        # FLUX images first (time-locked to narration), Wikimedia as fillers after
        pipeline_state['essay_images'] = _flux_entries + _existing
        _log('INFO', 'Stage 3.5', f'Essay images updated: {len(_flux_entries)} FLUX + {len(_existing)} existing')

    # Store murch per-image debug events
    for _mde in _murch_image_debug:
        _debug(f'3.5/murch/{_mde["fn"]}', _mde['msg'], level=_mde.get('level', 'DEBUG'))
    pipeline_state['murch_image_debug'] = _murch_image_debug
    cp_count = sum(1 for m in _flux_image_meta if m.get('counterpoint'))
    _debug(
        'Stage 3.5',
        f'Counterpoint images: {cp_count}/{len(_flux_image_meta)} | '
        f'focal zones: {[m.get("focal_zone", "?") for m in _flux_image_meta]}',
    )
    _save()
    # Named distinctly from the real Stage 4 above: TTS already ran before
    # Stage 3.5, and this pass only refreshes rhythm cuts. Reusing the same
    # stage name meant _done() found no *running* entry (the first was
    # already completed) and appended a second 0.0s "Stage 4: TTS Narration"
    # row to every run's timeline.
    _stage_start('Stage 4b: Rhythm Refresh')
    _done(
        'Stage 3.5: AI Image Generation',
        {
            'flux_images': len(_flux_generated_paths),
            'counterpoint_images': cp_count,
        },
    )

    _assert_not_stopped('Stage 4')


def stage_13_tts_rhythm_refresh(ctx):
    _debug = ctx._debug
    _done = ctx._done
    _log = ctx._log
    _pipeline_marker = ctx._pipeline_marker
    _save = ctx._save
    _slug = ctx._slug
    job = ctx.job
    narration_script = ctx.narration_script
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    # ── Stage 4: TTS Narration (rhythm refresh — TTS done in pre-image pass) ─
    # TTS was already generated before Stage 3.5 for semantic image alignment.
    # Here we only refresh rhythm cuts using the now-final essay_images count.
    job['current_stage'] = 'Stage 4b: Rhythm Refresh'
    _update_marker(_pipeline_marker, label=f'🔄 Scholarly {pipeline_id[:8]} — Stage 4b (rhythm refresh)')
    _log('INFO', 'Stage 4', 'TTS pre-generated — refreshing rhythm cuts with final image count')

    tts_path = pipeline_state.get('tts_path', os.path.join(out_dir, f'{_slug}_narration.mp3'))
    tts_duration = pipeline_state.get('tts_duration', len(narration_script.split()) * _SCHOLARLY_SEC_PER_WORD)
    _word_timings_raw = pipeline_state.get('word_timings_raw', [])
    _whisper_timings = pipeline_state.get('whisper_timings', [])
    _final_word_timings = pipeline_state.get('final_word_timings', [])
    _sch_voice = pipeline_state.get('tts_voice', 'pre-image TTS')
    tts_ok = bool(tts_path and os.path.exists(tts_path))

    _rhythm_cuts = []
    _murch_rhythm_debug = []
    if tts_ok:
        try:
            from zyg_workflows import murch_engine as _mer

            n_images = len(pipeline_state.get('essay_images', []))
            _rhythm_cuts = _mer.extract_audio_rhythm(
                tts_path,
                n_cuts=max(n_images - 1, 0),
                debug_log=_murch_rhythm_debug,
            )
            _log('INFO', 'Stage 4', f'Rhythm refresh: {len(_rhythm_cuts)} cut cues for {n_images} images')
            for _mde in _murch_rhythm_debug:
                _debug(f'4/rhythm/{_mde["fn"]}', _mde['msg'], level=_mde.get('level', 'DEBUG'))
        except Exception as _re:
            _log('WARNING', 'Stage 4', f'Rhythm refresh failed: {_re}')

    pipeline_state['rhythm_cuts'] = _rhythm_cuts
    pipeline_state['wan_enabled'] = False
    pipeline_state['wan_clips'] = []

    _save()
    _done(
        'Stage 4b: Rhythm Refresh',
        {
            'duration_s': round(tts_duration, 1),
            'voice': _sch_voice,
            'whisper_words': len(_whisper_timings),
            'rhythm_cuts': len(_rhythm_cuts),
        },
    )

    ctx._sch_voice = _sch_voice
    ctx.tts_duration = tts_duration
    ctx.tts_path = tts_path


def stage_14_ltx_motion(ctx):
    _assert_not_stopped = ctx._assert_not_stopped
    _done = ctx._done
    _log = ctx._log
    _pipeline_marker = ctx._pipeline_marker
    _save = ctx._save
    _should_stop = ctx._should_stop
    _stage_start = ctx._stage_start
    job = ctx.job
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    # ── Stage 5: LTX-2.5 Motion ───────────────────────────────────────
    # Every picture becomes a filmed shot instead of a Ken Burns pan. The
    # clips land in ltx_clips/ and Stage 6 substitutes them for the PIL
    # moves it would otherwise render, so a fully covered episode skips the
    # Ken Burns leg entirely. Coverage below 1.0 is reported, not hidden.
    _stage_start('Stage 5: LTX Motion')
    _save()
    _assert_not_stopped('Stage 5')
    job['current_stage'] = 'Stage 5: LTX Motion'
    _update_marker(_pipeline_marker, label=f'🔄 Scholarly {pipeline_id[:8]} — LTX Motion')
    _motion_imgs = [img for img in (pipeline_state.get('essay_images') or []) if os.path.exists(img.get('path', ''))]
    _motion_total = float(pipeline_state.get('tts_duration') or 0.0)
    _motion_grid = pipeline_state.get('n_flux_images') or len(_motion_imgs)
    _motion_slot = (_motion_total / max(_motion_grid, 1)) if _motion_total else 0.0
    try:
        _motion_rec = _scholarly_motion.animate_stills(
            _motion_imgs,
            out_dir,
            durations=[_motion_slot] * len(_motion_imgs) if _motion_slot else None,
            total_s=_motion_total,
            seed=abs(hash(pipeline_id)) & 0xFFFFFF,
            log_fn=lambda m: _log('INFO', 'Stage 5', m),
            should_abort=_should_stop,
        )
    except Exception as _mo_e:
        _log('WARNING', 'Stage 5', f'LTX motion failed: {_mo_e!r} — Ken Burns kept')
        _motion_rec = {
            'clips': 0,
            'kenburns': len(_motion_imgs),
            'motion_coverage': 0.0,
            'reason': f'{type(_mo_e).__name__}: {_mo_e}',
        }
    pipeline_state['ltx_motion'] = _motion_rec
    pipeline_state['motion_coverage'] = _motion_rec.get('motion_coverage', 0.0)
    _save()
    _done(
        'Stage 5: LTX Motion',
        {
            'clips': _motion_rec.get('clips', 0),
            'pictures': len(_motion_imgs),
            'motion_coverage': _motion_rec.get('motion_coverage', 0.0),
            'kenburns': _motion_rec.get('kenburns', 0),
            'clip_seconds': _motion_rec.get('clip_seconds_total', 0),
        },
    )

    stock_clips = []
    pipeline_state['stock_clips'] = stock_clips

    _stage_start('Stage 6: Video Assembly')
    _save()
    _assert_not_stopped('Stage 6')
