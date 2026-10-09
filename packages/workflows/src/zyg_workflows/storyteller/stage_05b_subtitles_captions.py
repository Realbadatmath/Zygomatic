# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The steps of Stage 5b — caption building and the delivery gates.

``stage_05b_burn_subtitles`` was one 458-line function with five nested ``def``s
and two unrelated halves: build the SRT (timestamp formatting, caption
cleaning/wrapping/chunking, cue timing from the TTS word stream or from a
proportional character share, the write and the ``<video stem>.srt`` copy), then
run the delivery gates (final video present and non-trivial, narration audio
really carried by the file, the near-duplicate frame scan and the degradation
report). Each seam is a function here; the stage is the order they run in.

Nothing here changes a decision, a log line, an environment switch or the order
of the writes into ``job``/``pipeline_state``. The ``_seal.seal(...)`` call
deliberately stayed in :mod:`stage_05b_subtitles` — ``tests/test_storyteller_seal.py``
points ``scripts/check_seal_hooks.py`` at that module and that function.

2026-10-09: the only line of the original that is gone is a dead
``_words_only`` list that was built from the word timings and never read."""

import logging as _zyg_logging
import os

from zyg_workflows.bin import exe
from zyg_workflows.pipeline_common import _align_narration_word_timings
from zyg_workflows.subproc_registry import _update_marker

# The monolith's logger name, so a run's log lines stay under one channel.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_storyteller')

# Cue growth bounds for the script-aligned path: a cue is at most 12 words and
# may only break on sentence punctuation once it holds 5.
MAX_CUE_WORDS = 12
MIN_CUE_WORDS = 5


# ── caption text ─────────────────────────────────────────────────────────────


def srt_timestamp(seconds):
    """Format a second offset as an SRT ``HH:MM:SS,mmm`` timestamp."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    sec = seconds % 60
    return f'{h:02d}:{m:02d}:{sec:06.3f}'.replace('.', ',')


def clean_caption_text(txt: str) -> str:
    """Strip the unspoken stage directions out of one caption and collapse its spaces.

    Keeps captions aligned with speech: stage directions like ``(pause)`` create
    mismatch because they are not spoken words. Returns the cleaned text."""
    try:
        import re as _re_cap

        txt = _re_cap.sub(r'\(\s*pause\s*\)', '', txt, flags=_re_cap.IGNORECASE)
        txt = _re_cap.sub(r'\(\s*beat\s*\)', '', txt, flags=_re_cap.IGNORECASE)
        txt = _re_cap.sub(r'\s+', ' ', txt).strip()
    except Exception as _exc:
        _zyg_log.debug('caption stage-direction cleanup skipped: %s', _exc)
    return (txt or '').strip()


def wrap_srt_text(txt: str, max_chars: int = 42) -> str:
    """Word-wrap one cue to ``max_chars`` per line, returning the newline-joined lines.

    Wraps without truncating. 2026-07-24 r3: the previous version still sliced
    to 3 lines at return, silently dropping ~64% of each proportional cue (run
    dd36662e: every cue clipped mid-sentence at ~120 chars). Cue LENGTH is
    bounded by :func:`split_caption_chunks`, not by dropping text here."""
    _words = (txt or '').split()
    _lines, _cur = [], ''
    for _w in _words:
        if len(_cur) + len(_w) + (1 if _cur else 0) > max_chars and _cur:
            _lines.append(_cur.strip())
            _cur = _w
        else:
            _cur += (' ' if _cur else '') + _w
    if _cur:
        _lines.append(_cur.strip())
    return '\n'.join(_lines).strip()


def split_caption_chunks(txt: str, max_chars: int = 84) -> list:
    """Split one scene's narration into caption-sized chunks, returning the chunk list.

    Splits at sentence boundaries (long sentences fall back to word packing) so
    the proportional path emits several short cues per scene instead of one
    25-50s wall of text."""
    import re as _re_cc

    _sents = [s.strip() for s in _re_cc.split(r'(?<=[.!?])\s+', (txt or '').strip()) if s.strip()]
    _chunks: list = []
    _cur = ''
    for _s in _sents:
        while len(_s) > max_chars:
            if _cur:
                _chunks.append(_cur)
                _cur = ''
            _cut = _s.rfind(' ', 1, max_chars)
            if _cut <= 0:
                _cut = max_chars
            _chunks.append(_s[:_cut].strip())
            _s = _s[_cut:].strip()
        if _cur and len(_cur) + len(_s) + 1 > max_chars:
            _chunks.append(_cur)
            _cur = _s
        else:
            _cur += (' ' if _cur else '') + _s
    if _cur:
        _chunks.append(_cur)
    return _chunks or ([txt.strip()] if (txt or '').strip() else [])


# ── cue timing ───────────────────────────────────────────────────────────────


def entries_from_word_timings(word_timings):
    """Group a timed word stream into cues: ``[(word, start_sec), ...]`` in, cues out.

    A cue holds 5-12 words, breaks early on sentence punctuation, starts at its
    first word's timestamp and ends 0.35s after its last one — clamped to stay
    0.05s clear of the next word and to last at least 0.5s. Returns
    ``[(text, start_sec, end_sec), ...]``."""
    _entries: list[tuple[str, float, float]] = []
    _idx = 0
    _total = len(word_timings)
    while _idx < _total:
        # Find start
        try:
            _t_start_st = float(word_timings[_idx][1])
        except Exception:
            _idx += 1
            continue

        # Grow segment
        _seg_words = []
        _seg_end_idx = _idx
        for _j in range(_idx, min(_total, _idx + MAX_CUE_WORDS)):
            try:
                _w = str(word_timings[_j][0]).strip()
            except Exception:
                _w = ''
            if _w:
                _seg_words.append(_w)
                _seg_end_idx = _j
            # Prefer breaking on sentence-like punctuation, but only
            # after we have a minimum density of words.
            if len(_seg_words) >= MIN_CUE_WORDS and _w and _w[-1] in '.?!':
                break

        # Compute end time
        try:
            _t_end_st = float(word_timings[_seg_end_idx][1])
        except Exception:
            _t_end_st = _t_start_st + 1.0

        # Trailing buffer, clamped not to overlap next word
        _next_idx = min(_seg_end_idx + 1, _total - 1)
        _t_end_buf = _t_end_st + 0.35
        try:
            if _next_idx > _seg_end_idx:
                _t_end_buf = min(_t_end_buf, float(word_timings[_next_idx][1]) - 0.05)
        except (IndexError, KeyError, TypeError, ValueError) as _exc:
            _zyg_log.debug('caption end clamp to the next word skipped: %s', _exc)

        _txt_st = clean_caption_text(' '.join(_seg_words))
        if _txt_st:
            _entries.append((_txt_st, _t_start_st, max(_t_end_buf, _t_start_st + 0.5)))

        _idx = _seg_end_idx + 1
    return _entries


def entries_proportional(scene_texts, video_dur):
    """Time the cues by character share when no word timings exist.

    2026-07-24 r3: each scene is split into caption-sized chunks with time
    distributed by char share — one cue per SCENE meant 25-50s cues that
    :func:`wrap_srt_text` then clipped to ~120 chars (36% narration coverage in
    run dd36662e). Takes the per-scene narration texts and the video duration in
    seconds, returns ``[(text, start_sec, end_sec), ...]``."""
    _scene_texts_st = [clean_caption_text(t) for t in scene_texts]
    _char_counts = [max(len(t), 1) for t in _scene_texts_st if t]
    _total_chars = sum(_char_counts)
    _entries: list[tuple[str, float, float]] = []
    _cum_t = 0.0
    for _txt_st, _chars_st in zip([t for t in _scene_texts_st if t], _char_counts):
        _dur_st = (_chars_st / _total_chars) * video_dur
        _chunks_st = split_caption_chunks(_txt_st)
        _chunk_chars = sum(max(len(c), 1) for c in _chunks_st)
        _cc_t = _cum_t
        for _ck in _chunks_st:
            _ck_dur = (max(len(_ck), 1) / _chunk_chars) * _dur_st
            _entries.append((_ck, _cc_t, _cc_t + _ck_dur))
            _cc_t += _ck_dur
        _cum_t += _dur_st
    return _entries


def caption_entries(ctx, scene_texts, video_dur, log):
    """Pick the cue source for this run and return its cues.

    Script-aligned word timings when the TTS produced any (the alignment
    coverage is logged above 50%), else the proportional character share."""
    _narr_st = ctx.pipeline_state.get('narration_script') or ctx.full_narration or ''
    if ctx.tts_word_timings and len(ctx.tts_word_timings) > 0:
        _timings, _st_cov = _align_narration_word_timings(
            _narr_st,
            ctx.tts_word_timings,
            voice_mode=ctx.voice_style,
        )
        if _st_cov >= 0.5:
            log('INFO', 'Stage 5b', f'Caption timings script-aligned ({_st_cov:.0%} coverage)')
        # Build captions from script-aligned timed word stream.
        _entries = entries_from_word_timings(_timings)
        log('INFO', 'Stage 5b', f'SRT built from script-aligned word timings: {len(_entries)} entries')
    else:
        _entries = entries_proportional(scene_texts, video_dur)
        log('INFO', 'Stage 5b', f'SRT built from proportional char timing: {len(_entries)} entries')
    return _entries


# ── writing the SRT ──────────────────────────────────────────────────────────


def write_srt(path, entries):
    """Write the cues to ``path`` as SRT: 1-based index, timestamps, wrapped text."""
    with open(path, 'w', encoding='utf-8') as _sf_st:
        for _idx_st, (_txt_st, _t_start_st, _t_end_st) in enumerate(entries, 1):
            _sf_st.write(f'{_idx_st}\n')
            _sf_st.write(f'{srt_timestamp(_t_start_st)} --> {srt_timestamp(_t_end_st)}\n')
            _sf_st.write(wrap_srt_text(_txt_st) + '\n\n')


def copy_srt_beside_video(srt_path, video_path, log):
    """Copy the SRT to ``<video stem>.srt`` so the uploader finds it; failure is logged.

    2026-07-24: the YouTube uploader derives caption_path as
    ``splitext(video)[0] + '.srt'``, so the ``_subtitles.srt`` name was never
    picked up and storyteller uploads went caption-less."""
    try:
        if video_path:
            _srt_match = os.path.splitext(video_path)[0] + '.srt'
            if os.path.abspath(_srt_match) != os.path.abspath(srt_path):
                import shutil as _sh_srt

                _sh_srt.copyfile(srt_path, _srt_match)
    except Exception as _srt_cp_e:
        log('WARNING', 'Stage 5b', f'Caption-name copy failed: {_srt_cp_e!r}')


def write_subtitles(ctx):
    """Build this run's SRT and save it; every failure in here is non-fatal and logged.

    The SRT is saved to ``out_dir`` and delivered to YouTube directly — there is
    no burn-in pass. A run with no narration text logs and writes nothing."""
    log = ctx._log
    try:
        _srt_sub_path = os.path.join(ctx.out_dir, f'{ctx._slug_st}_subtitles.srt')
        _video_dur_st = ctx.tts_duration if ctx.tts_duration and ctx.tts_duration > 0 else (ctx.duration_min * 60)
        _scene_texts_st = [s.get('narration', '').strip() for s in ctx.scenes if s.get('narration', '').strip()]
        if _scene_texts_st and _video_dur_st > 0:
            _srt_entries_st = caption_entries(ctx, _scene_texts_st, _video_dur_st, log)
            write_srt(_srt_sub_path, _srt_entries_st)
            copy_srt_beside_video(
                _srt_sub_path,
                ctx.pipeline_state.get('video_path') or ctx.final_path,
                log,
            )
            log('INFO', 'Stage 5b', f'SRT saved: {_srt_sub_path} ({len(_srt_entries_st)} entries)')
        else:
            log('INFO', 'Stage 5b', 'No narration text — skipping subtitles')
    except Exception as _sub_e:
        log('WARNING', 'Stage 5b', f'Subtitle burn error (non-fatal): {_sub_e}')


# ── delivery gates ───────────────────────────────────────────────────────────


def gate_final_video(ctx):
    """Fail the job when the delivered video is missing or under 1 MB.

    2026-07-24 fix (2nd gating hole, exposed by run a6f458bc): completion must
    verify the final video actually exists and is non-trivial — the ffmpeg
    colorspace failure produced a 0-byte slideshow yet the job still logged
    "✅ complete" pointing at it. Returns True when the run is over."""
    job = ctx.job
    final_path = ctx.final_path
    if final_path and os.path.isfile(final_path) and os.path.getsize(final_path) > 1_000_000:
        return False
    _fsz = os.path.getsize(final_path) if (final_path and os.path.isfile(final_path)) else 0
    job['status'] = 'failed'
    job['error'] = (
        f'Final video missing or empty ({final_path}, {_fsz} bytes) — assembly failed; see Stage 5 errors in the log'
    )
    job['current_stage'] = 'Failed — no final video'
    _update_marker(ctx._pipeline_marker, status='error', label='Storyteller FAILED (no final video)')
    ctx._log('ERROR', 'PIPELINE', f'❌ Storyteller failed: final video missing/empty ({_fsz} bytes)')
    ctx._save()
    return True


def delivered_has_audio(final_path, log):
    """ffprobe ``final_path`` for an audio stream; a probe that fails returns True.

    Defense-in-depth: the delivered file must really CARRY the audio — a mux bug
    must not ship silently again. A broken probe must not gate the run, so it
    logs and reports an audio stream."""
    try:
        import subprocess as _sp_ag

        _ap = _sp_ag.run(
            [
                exe('ffprobe'),
                '-v',
                'error',
                '-select_streams',
                'a',
                '-show_entries',
                'stream=codec_type',
                '-of',
                'csv=p=0',
                final_path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return 'audio' in (_ap.stdout or '')
    except Exception as _ag_e:
        log('WARNING', 'PIPELINE', f'Audio-stream probe failed ({_ag_e!r}) — not gating on it')
        return True


def gate_narration_audio(ctx):
    """Fail a narrated run whose audio is missing from the pipeline or from the file.

    2026-07-24 audio-loss gates (run 6278904c shipped a 600s SILENT slideshow as
    'completed DEGRADED': total TTS failure set no flag and the completion gate
    only checked file size). A narrated product with no narration is a FAILED
    product; the video is kept for inspection. Returns True when the run is
    over."""
    job = ctx.job
    final_path = ctx.final_path
    pipeline_state = ctx.pipeline_state
    if ctx.narration_enabled and pipeline_state.get('narration_missing'):
        job['status'] = 'failed'
        job['error'] = (
            'No narration audio — every TTS engine failed '
            '(see Stage 3 [KOKORO]/[TTS] log lines); silent video kept at '
            f'{final_path} for inspection'
        )
        job['result'] = final_path
        job['final_output_file'] = final_path
        job['current_stage'] = 'Failed — no narration audio'
        _update_marker(ctx._pipeline_marker, status='error', label='Storyteller FAILED (no narration audio)')
        ctx._log('ERROR', 'PIPELINE', '❌ Storyteller failed: no narration audio (all TTS engines failed)')
        ctx._save()
        return True
    if ctx.narration_enabled and pipeline_state.get('tts_path'):
        if not delivered_has_audio(final_path, ctx._log):
            job['status'] = 'failed'
            job['error'] = (
                f'Delivered video has NO audio stream despite narration '
                f'({pipeline_state.get("tts_path")}) — mux failed; '
                f'video kept at {final_path} for inspection'
            )
            job['result'] = final_path
            job['final_output_file'] = final_path
            job['current_stage'] = 'Failed — video has no audio stream'
            _update_marker(ctx._pipeline_marker, status='error', label='Storyteller FAILED (video has no audio stream)')
            ctx._log('ERROR', 'PIPELINE', '❌ Storyteller failed: delivered video has no audio stream')
            ctx._save()
            return True
    return False


def duplicate_signature(np_mod, image_mod, path):
    """Normalised 64×64 grayscale signature of one frame, for the clone check."""
    _a = np_mod.asarray(image_mod.open(path).convert('L').resize((64, 64), image_mod.LANCZOS), dtype=np_mod.float32)
    _s = _a.std()
    return (_a - _a.mean()) / (_s if _s > 1e-6 else 1.0)


def scan_near_duplicates(pipeline_state, log, threshold):
    """Return the 1-based scene numbers whose frame is a near-duplicate.

    2026-07-24 r3: run dd36662e delivered 24 scenes that were re-paints of one
    portrait — every per-scene gate passed because each frame was individually
    fine. Structural check: normalized 64×64 grayscale correlation. Same-
    composition re-paints measure ≥0.95; even the same character freshly
    rendered in another run measures ≤0.60 (calibrated on
    dd36662e/50e5ee67/73c12470), so 0.90 flags only true clones. A scene is a
    duplicate when it matches any earlier scene or the character reference
    image. Fewer than three frames, or a scan that raises, yields no hits."""
    _dupe_scenes: list = []
    try:
        import numpy as _np_dup
        from PIL import Image as _PIL_dup

        _dup_paths = [p for p in (pipeline_state.get('flux_images') or []) if p and os.path.isfile(p)]
        if len(_dup_paths) >= 3:
            _dup_sigs = [duplicate_signature(_np_dup, _PIL_dup, p) for p in _dup_paths]
            _dup_ref = None
            _dup_ref_p = pipeline_state.get('char_reference_image')
            if _dup_ref_p and os.path.isfile(_dup_ref_p):
                _dup_ref = duplicate_signature(_np_dup, _PIL_dup, _dup_ref_p)
            # r3 review fix: compare against ALL prior scenes, not just the
            # predecessor — the shot-type rotation rule makes clone pairs
            # systematically non-adjacent (A,B,A,B evades a neighbor check).
            # 25 sigs at 64×64 is ~300 dot products, negligible.
            for _di, _dsig in enumerate(_dup_sigs):
                _hit = any(float((_dsig * _dup_sigs[_dj]).mean()) > threshold for _dj in range(_di))
                if not _hit and _dup_ref is not None:
                    _hit = float((_dsig * _dup_ref).mean()) > threshold
                if _hit:
                    _dupe_scenes.append(_di + 1)
    except Exception as _dup_e:
        log('WARNING', 'PIPELINE', f'Near-duplicate scan failed: {_dup_e!r}')
    return _dupe_scenes


def delivered_scene_count(pipeline_state):
    """How many scenes the run delivered — the denominator of the bad-frame share.

    r3 review fix: 'scene_count'/'scene_prompts' are never written to
    pipeline_state, so the old expression always evaluated to 25 — a 12-scene
    run with 5 bad frames measured 20% instead of 42%. The delivered frame list
    is the true denominator."""
    return max(
        1,
        len(pipeline_state.get('flux_images') or [])
        or int(pipeline_state.get('scene_count') or 0)
        or len(pipeline_state.get('scene_prompts') or [])
        or 25,
    )


def degradation_report(pipeline_state, n_scenes, dupe_scenes):
    """Collect the bad-frame scenes and the human-readable degradation reasons.

    2026-07-24 fix: a run whose frames are mostly tinted reference stills must
    not report success (job 10c84d83 shipped 17/25 fallback frames as
    "completed"). Returns ``(bad_scenes, degraded_bits)``; records
    ``_st_duplicate_scenes`` in ``pipeline_state`` when there were duplicates.
    Hand-flagged scenes are reported but deliberately NOT bad frames (see
    Stage 3.6)."""
    _fb_scenes = pipeline_state.get('_st_fallback_scenes') or []
    _drift_scenes = [s for (s, _sim) in (pipeline_state.get('_st_identity_drift_scenes') or [])]
    _rescued_scenes = pipeline_state.get('_st_rescued_scenes') or []
    _noface_scenes = pipeline_state.get('_st_no_face_scenes') or []
    # 2026-07-31: scenes that failed outright now that the portrait
    # substitution is gone — they must count as bad frames, not vanish.
    _failed_scenes = pipeline_state.get('_st_failed_scenes') or []
    _bad_scenes = sorted(
        set(_fb_scenes)
        | set(_drift_scenes)
        | set(_rescued_scenes)
        | set(_noface_scenes)
        | set(dupe_scenes)
        | set(_failed_scenes)
    )
    _degraded_bits = []
    if _fb_scenes:
        _degraded_bits.append(
            f'{len(_fb_scenes)}/{n_scenes} scenes are tinted reference-photo fallbacks (scenes {_fb_scenes})'
        )
    if _drift_scenes:
        _degraded_bits.append(f'{len(_drift_scenes)}/{n_scenes} scenes failed identity QC (scenes {_drift_scenes})')
    if _rescued_scenes:
        _degraded_bits.append(
            f'{len(_rescued_scenes)}/{n_scenes} scenes shipped via '
            f'best-attempt rescue below strict QC (scenes {_rescued_scenes})'
        )
    if _failed_scenes:
        _degraded_bits.append(
            f'{len(_failed_scenes)}/{n_scenes} scenes FAILED to render a usable frame (scenes {_failed_scenes})'
        )
    if _noface_scenes:
        _degraded_bits.append(
            f'{len(_noface_scenes)}/{n_scenes} scenes have no detectable face (scenes {_noface_scenes})'
        )
    if dupe_scenes:
        pipeline_state['_st_duplicate_scenes'] = dupe_scenes
        _degraded_bits.append(
            f'{len(dupe_scenes)}/{n_scenes} scenes are near-duplicates '
            f'of the reference/previous scene (scenes {dupe_scenes})'
        )
    _hand_flag_gate = pipeline_state.get('_st_hand_flagged_scenes') or []
    if _hand_flag_gate:
        # Informational only — deliberately NOT in _bad_scenes (see Stage 3.6).
        _degraded_bits.append(
            f'{len(_hand_flag_gate)}/{n_scenes} scenes have a minor '
            f'hand imperfection (scenes {_hand_flag_gate}; non-fatal)'
        )
    if pipeline_state.get('narration_voice_fallback'):
        _degraded_bits.append('IndexTTS-2 primary TTS failed — narration rendered by the Chatterbox fallback engine')
    if pipeline_state.get('narration_truncated'):
        _degraded_bits.append('narration audio is suspiciously short vs the script (TTS truncation suspected)')
    return _bad_scenes, _degraded_bits


def fail_degraded(ctx, bad_scenes, n_scenes, degraded_bits):
    """Reject the run: >30% bad frames fails the job and keeps the video for inspection."""
    job = ctx.job
    final_path = ctx.final_path
    job['status'] = 'failed'
    job['error'] = (
        'Degraded output rejected: ' + '; '.join(degraded_bits) + f' — video kept at {final_path} for inspection'
    )
    job['result'] = final_path
    job['final_output_file'] = final_path
    job['current_stage'] = 'Failed — degraded output'
    _update_marker(
        ctx._pipeline_marker,
        status='error',
        label=f'Storyteller DEGRADED ({len(bad_scenes)}/{n_scenes} bad frames)',
    )
    ctx._log('ERROR', 'PIPELINE', f'❌ Storyteller output rejected as degraded: {"; ".join(degraded_bits)}')
    ctx._save()
