# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tts_service.py — _tts_shared and the service entry points (lines 1064-1444 of the pre-split file, verbatim)."""

import logging as _zyg_logging
from .constants import (
    json,
    os,
    shutil,
    subprocess,
    gui_state,
    _register_subproc,
    _finish_subproc,
    _DEMONET_TIER1,
    _DEMONET_TIER2,
    _DEMONET_TIER3_TITLE,
    _TITLE_SYNONYMS,
    _SEED_POOL_DIR,
    _voice_seed_for,
    exe,
    paths,
)
from .text import _tts_clean_text, _tts_split_sentences
from .engines import _indextts_segments, _chatterbox_segments, _tts_segment_indices, _tts_assemble
from .asr import _tts_asr_read_back

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.tts_service')


def _tts_shared(
    text_: str,
    out_path_: str,
    stage_label: str,
    log_fn=None,
    voice_id: str = '',
    azure_voice: str = '',
    engine_out: dict = None,
    loudnorm: bool = True,
    seed_wav: str = '',
    emo_alpha: float = None,
    emo_text: bool = None,
    **_legacy,
) -> 'tuple[bool, list]':
    """Synthesise speech. PRIMARY IndexTTS-2 → FALLBACK Chatterbox.

    Returns (ok, word_timings). word_timings is always [] — neither cloner emits
    them; pipelines that need word-level subtitles use the Whisper backfill.

    `voice_id` (alias: the legacy `azure_voice` keyword) selects the reference
    voice from the seed pool, gender-matched and deterministic. `seed_wav` names a
    reference wav outright and overrides that pick — used by the per-channel
    briefing voices. When `engine_out` is a dict it receives
    {'engine': ..., 'seed': ..., 'asr': {...}} for the caller's badges, plus
    (2026-08-25, P-14) 'segments_requested', 'segments_rendered', 'partial'
    (bool: fewer rendered than requested), 'contiguous' (bool: the rendered set
    is a prefix of the request) and 'segment_indices' (original index of each
    rendered segment) — a partial read is still delivered, with a WARNING, and
    these are how the caller finds out.

    `emo_alpha`/`emo_text` (2026-08-12) reach IndexTTS-2's per-call emotion
    controls, which until now only `_indextts_segments` callers could set — the
    briefing channels went around this function entirely to get a calmer read.
    None keeps the process-wide env defaults, so every existing caller is
    unchanged. Chatterbox has no equivalent knob (its own read is governed by
    ZYG_CHATTERBOX_EXAGGERATION), so a fallback run ignores both.
    """

    def _l(level, msg):
        if log_fn:
            try:
                log_fn(level, stage_label, msg)
                return
            except Exception as _exc:
                _zyg_log.debug('stage log callback failed, printing instead: %s', _exc)
        _zyg_log.info(f'[TTS] {msg}')

    _clean = _tts_clean_text(text_)
    if not _clean:
        return False, []
    _segments = _tts_split_sentences(_clean)
    if not _segments:
        return False, []

    _vid = (voice_id or azure_voice or '').strip()
    _seed_name, _ref = _voice_seed_for(_vid, seed_wav=seed_wav)
    if not _ref:
        _l('ERROR', f'No voice seed available in {_SEED_POOL_DIR} — cannot clone a voice; TTS cannot run')
        return False, []

    _l(
        'INFO',
        f'TTS: {len(_clean.split())} words → {len(_segments)} segment(s), '
        f'voice {_vid or "(default)"} → seed {_seed_name}',
    )

    _work = os.path.abspath(out_path_) + '.tts_segments'
    try:
        _paths = _indextts_segments(_segments, _work, _ref, _l, emo_alpha=emo_alpha, emo_text=emo_text)
        _engine = 'indextts2'
        if not _paths:
            _l('WARNING', 'IndexTTS-2 unavailable — falling back to Chatterbox')
            _paths = _chatterbox_segments(_segments, _work, _ref, _l)
            _engine = 'chatterbox-fallback'
        if not _paths:
            _l('ERROR', 'ALL TTS engines failed — no narration audio produced')
            return False, []
        # ── Pair text to audio by ORIGINAL index (2026-08-25, P-14) ──────
        # Was `_segments[:len(_paths)]`: right for a truncated tail, wrong for
        # a hole — Chatterbox filters missing files OUT of its list, so a
        # missing seg_0007 shifted every later sentence's text (pause map, ASR
        # read-back and assembly all pair by list position) onto the following
        # sentence's audio. The index is recovered from the seg_%04d name the
        # batch writer assigned, so the pairing survives any gap.
        _idx = _tts_segment_indices(_paths, len(_segments))
        _n_req, _n_ren = len(_segments), len(_paths)
        _contiguous = _idx == list(range(_n_ren))
        _partial = _n_ren < _n_req
        if _partial:
            _missing = sorted(set(range(_n_req)) - set(_idx))
            _l(
                'WARNING',
                f'TTS: partial read — {_n_ren}/{_n_req} segments rendered, '
                f'missing index(es) {_missing[:12]}'
                f'{"…" if len(_missing) > 12 else ""} '
                f'({"truncated tail" if _contiguous else "NON-contiguous gap"}); '
                f'pairing text to audio by original index — later segments '
                f'are not shifted',
            )
        _segs_used = [_segments[_k] for _k in _idx]
        # Verify the read BEFORE assembly — a re-rolled segment has to be in
        # place before the segments are concatenated into the final file.
        _asr_stats = _tts_asr_read_back(
            _segs_used, _paths, _work, _ref, _engine, _l, emo_alpha=emo_alpha, emo_text=emo_text
        )
        if isinstance(engine_out, dict):
            engine_out['engine'] = _engine
            engine_out['seed'] = _seed_name
            engine_out['asr'] = _asr_stats
            engine_out['segments_requested'] = _n_req
            engine_out['segments_rendered'] = _n_ren
            engine_out['partial'] = _partial
            engine_out['contiguous'] = _contiguous
            engine_out['segment_indices'] = list(_idx)
        _ok = _tts_assemble(_paths, _segs_used, out_path_, _l, loudnorm=loudnorm)
        if _ok:
            _l(
                'INFO',
                f'🎙️ {_engine} OK → {os.path.getsize(os.path.abspath(out_path_)) // 1024} KB '
                f'({len(_paths)}/{len(_segments)} segments, seed {_seed_name})',
            )
        return _ok, []
    finally:
        if os.environ.get('ZYG_TTS_KEEP_SEGMENTS', '0').strip().lower() not in ('1', 'true', 'yes', 'on'):
            try:
                shutil.rmtree(_work, ignore_errors=True)
            except Exception as _exc:
                _zyg_log.debug('work dir cleanup skipped: %s', _exc)


def _mask_bad_words(text: str) -> str:
    """Replace Tier 1 + Tier 2 words in text with * × word length."""
    import re as _re

    result = text
    all_bad = _DEMONET_TIER1 | _DEMONET_TIER2
    # Sort longest first so 'motherfucker' matches before 'fuck'
    for word in sorted(all_bad, key=len, reverse=True):
        pattern = _re.compile(r'\b' + _re.escape(word) + r'\b', _re.IGNORECASE)
        result = pattern.sub(lambda m: '*' * len(m.group()), result)
    return result


def _sanitize_title(title: str) -> str:
    """Remove/replace Tier 1 + Tier 3 bad words from clip titles using synonym table.
    Logs a warning for every replacement made."""
    import re as _re

    result = title
    all_title_bad = _DEMONET_TIER1 | _DEMONET_TIER2 | _DEMONET_TIER3_TITLE
    for word in sorted(all_title_bad, key=len, reverse=True):
        replacement = _TITLE_SYNONYMS.get(word.lower())
        if replacement is None:
            continue  # skip words with no synonym (leave as-is rather than delete)
        pattern = _re.compile(r'\b' + _re.escape(word) + r'\b', _re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(replacement, result)
    # Clean up double spaces
    result = _re.sub(r'\s{2,}', ' ', result).strip()
    return result


def _bleep_audio_in_clip(
    clip_path: str,
    tx_path: str,
    clip_start: float,
    clip_dur: float,
    vid_id: str,
    clip_idx: int,
    log_fn,
    pipeline_id: str = '',
) -> None:
    """Bleep audio over Tier 1+2 word timestamps. Edits clip in-place.
    Uses ffmpeg volume filter + 1kHz sine tone. Video stream is copied unchanged."""
    import re as _re2
    import subprocess as _sp_b
    import tempfile as _tmp_b
    import shutil as _shu_b

    try:
        if not os.path.exists(tx_path):
            return
        with open(tx_path) as _tf:
            segs = json.load(_tf).get('segments', [])
    except Exception:
        return

    all_bad = _DEMONET_TIER1 | _DEMONET_TIER2
    bleep_windows = []  # list of (rel_start, rel_end)

    for seg in segs:
        seg_start = float(seg.get('start', 0))
        seg_end = float(seg.get('end', seg_start + 1))
        if seg_end < clip_start or seg_start > clip_start + clip_dur:
            continue
        text = seg.get('text', '').lower()
        for word in all_bad:
            pat = _re2.compile(r'\b' + _re2.escape(word) + r'\b')
            if pat.search(text):
                rel_s = max(0.0, seg_start - clip_start - 0.05)
                rel_e = min(clip_dur, seg_end - clip_start + 0.1)
                bleep_windows.append((rel_s, rel_e))
                break  # one bleep per segment is enough

    if not bleep_windows:
        return

    # Check stop flag before starting
    if gui_state._pipeline_stop_flag:
        return

    # Build ffmpeg audio filter: silence + sine bleep for each window
    # Chain: volume filters to mute, then mix in a sine tone for each window
    mute_parts = []
    sine_parts = []
    mix_inputs = ['[0:a]']
    for idx2, (rs, re2) in enumerate(bleep_windows):
        mute_parts.append(f"volume=0:enable='between(t,{rs:.3f},{re2:.3f})'")
        sine_parts.append(
            f'sine=frequency=1000:duration={re2 - rs:.3f}[bleep{idx2}];'
            f'[bleep{idx2}]adelay={int(rs * 1000)}|{int(rs * 1000)},volume=0.4[b{idx2}]'
        )
        mix_inputs.append(f'[b{idx2}]')

    mute_chain = ','.join(mute_parts)

    filter_complex = (
        f'[0:a]{mute_chain}[muted];'
        + ';'.join(sine_parts)
        + ';[muted]'
        + ''.join(f'[b{i}]' for i in range(len(bleep_windows)))
        + f'amix=inputs={1 + len(bleep_windows)}:duration=first:dropout_transition=0[aout]'
    )

    tmp_dir = _tmp_b.mkdtemp(prefix='zyg_bleep_')
    out_path = os.path.join(tmp_dir, 'bleeped.mp4')
    try:
        cmd = [
            exe('ffmpeg'),
            '-y',
            '-i',
            clip_path,
            '-filter_complex',
            filter_complex,
            '-map',
            '0:v',
            '-map',
            '[aout]',
            '-c:v',
            'copy',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            out_path,
        ]
        _proc_b = _sp_b.Popen(cmd, stdout=_sp_b.PIPE, stderr=_sp_b.PIPE)
        _register_subproc(_proc_b.pid, f'bleep {vid_id} clip{clip_idx}', pipeline_id)
        _stdout_b, _stderr_b = _proc_b.communicate(timeout=600)
        _finish_subproc(_proc_b.pid, ok=(_proc_b.returncode == 0))
        if _proc_b.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            _shu_b.move(out_path, clip_path)
            log_fn(f'Stage 4b BLEEP {vid_id} clip{clip_idx}: bleeped {len(bleep_windows)} segment(s) ✓')
        else:
            log_fn(
                f'Stage 4b BLEEP {vid_id} clip{clip_idx}: ⚠ bleep ffmpeg failed '
                f'(rc={_proc_b.returncode}) — {_stderr_b.decode(errors="replace")[-200:].strip()}'
            )
    except Exception as _be:
        log_fn(f'Stage 4b BLEEP {vid_id} clip{clip_idx}: ⚠ bleep exception — {_be}')
    finally:
        try:
            import shutil as _shu_b2

            _shu_b2.rmtree(tmp_dir, ignore_errors=True)
        except Exception as _exc:
            _zyg_log.debug('bleep work dir cleanup skipped: %s', _exc)


def _selected_voice_id() -> str:
    """The operator-selected voice id, or the house default."""
    _v = os.environ.get('ZYG_TTS_VOICE', '').strip()
    if _v:
        return _v
    try:
        _p = str(paths.DATA_DIR / 'runtime' / 'tts_config.json')
        with open(_p, encoding='utf-8') as _f:
            _v = (json.load(_f).get('voice') or '').strip()
        if _v:
            return _v
    except Exception as _exc:
        _zyg_log.warning('tts_config.json unreadable, falling back to the legacy voice config: %s', _exc)
    try:
        # Legacy read: the selected voice used to live in the speech config.
        # Kept so existing installs keep their narrator until they re-save.
        from zyg_workflows.azure_integrations import load_config as _legacy_cfg

        _v = (_legacy_cfg().get('speech_voice', '') or '').strip()
    except Exception:
        _v = ''
    return _v or 'en-GB-RyanNeural'


def _synthesise_tts(
    narration_text: str,
    out_dir: str,
    pipeline_id: str,
    voice_mode: str = 'narration',
    voice_override: str = '',
    log_fn=None,
):
    """Synthesise narration. PRIMARY: IndexTTS-2 (local, cloned reference voice).
    FALLBACK: Chatterbox (local, lighter — survives a VRAM-starved GPU).

    2026-08-06: engine policy set by operator bake-off — IndexTTS-2 won a blind
    A/B over Chatterbox, Qwen3-TTS, MOSS-TTS and the outgoing Kokoro on a
    20-sentence emotional-range script. Both engines are cloners, so the voice
    id resolves to a reference wav from the seed pool rather than a preset name.

    log_fn: pipeline logger (level, stage, msg); when provided, engine progress
    and failures are loudly visible in the job log.

    Returns (tts_path, duration_seconds, word_timings, engine) — engine in
    ('indextts2', 'chatterbox-fallback', ''); word_timings is always [] (neither
    cloner emits them — pipelines needing word subtitles use the Whisper backfill).
    """
    _tts_out = os.path.join(out_dir, 'narration.wav')

    def _emit(level: str, msg: str) -> None:
        if log_fn:
            try:
                log_fn(level, 'Stage 3', msg)
                return
            except Exception as _exc:
                _zyg_log.debug('stage log callback failed, printing instead: %s', _exc)
        _zyg_log.info(f'[TTS] {msg}')

    def _wav_duration(path: str) -> float:
        try:
            _dur_r = subprocess.run(
                [
                    exe('ffprobe'),
                    '-v',
                    'error',
                    '-show_entries',
                    'format=duration',
                    '-of',
                    'default=noprint_wrappers=1:nokey=1',
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return float(_dur_r.stdout.strip())
        except Exception:
            import wave

            with wave.open(path) as _wf:
                return _wf.getnframes() / float(_wf.getframerate())

    _sel_voice = (voice_override or '').strip() or _selected_voice_id()
    _engine_out: dict = {}
    try:
        _ok, _timings = _tts_shared(
            narration_text,
            _tts_out,
            'Stage 3 — TTS Narration',
            log_fn=log_fn,
            voice_id=_sel_voice,
            engine_out=_engine_out,
        )
        if _ok and os.path.isfile(_tts_out) and os.path.getsize(_tts_out) > 1000:
            return (_tts_out, _wav_duration(_tts_out), _timings, _engine_out.get('engine', 'indextts2'))
    except Exception as _tts_e:
        import traceback as _tb_tts

        _emit('WARNING', f'TTS raised: {_tts_e!r}\n{_tb_tts.format_exc()}')

    _emit('ERROR', 'ALL TTS engines failed — no narration audio produced')
    return None, 0, [], ''
