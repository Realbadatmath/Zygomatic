# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tts_service.py — the engine legs: IndexTTS-2, Chatterbox, loudness and assembly (lines 292-809 of the pre-split file, verbatim)."""

import logging as _zyg_logging
from .constants import (
    json,
    os,
    re,
    shutil,
    subprocess,
    time,
    _register_subproc,
    _finish_subproc,
    paths,
    exe,
    _TTS_LOUDNORM,
)
from .text import _tts_trim_edge_silence

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.tts_service')


# ── engine legs ─────────────────────────────────────────────────────────────
# Both engines live in their own venvs (IndexTTS-2 pins python <3.12), so they
# are driven over subprocess + JSON, the same contract as maya1_worker.py.
_INDEXTTS_DIR = paths.ZYG_INDEXTTS_DIR
_INDEXTTS_PY = os.path.join(_INDEXTTS_DIR, '.venv', 'bin', 'python')
_INDEXTTS_WORKER = os.path.join(_INDEXTTS_DIR, 'indextts2_worker.py')
_CHATTERBOX_DIR = os.environ.get('ZYG_CHATTERBOX_DIR', str(paths.ZYG_LEGACY_MODELS / 'tts_chatterbox'))
_CHATTERBOX_PY = os.path.join(_CHATTERBOX_DIR, '.venv', 'bin', 'python')
_CHATTERBOX_WORKER = os.path.join(_CHATTERBOX_DIR, 'chatterbox_worker.py')
# Never saturate the box: workers are pinned and thread-capped (20 of 24 cores).
_TTS_TASKSET_CORES = os.environ.get('ZYG_TTS_CORES', '0-19')
_TTS_WORKER_THREADS = os.environ.get('ZYG_TTS_THREADS', '8')


def _tts_worker_env() -> dict:
    _e = dict(os.environ)
    for _k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        _e[_k] = _TTS_WORKER_THREADS
    return _e


def _tts_run_worker(cmd: list, timeout_s: float, log) -> 'tuple[int, dict]':
    """Run a TTS worker; return (returncode, parsed_json_or_{})."""
    if _TTS_TASKSET_CORES and shutil.which('taskset'):
        cmd = ['taskset', '-c', _TTS_TASKSET_CORES] + cmd
    _proc = None
    try:
        _proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_tts_worker_env())
        try:
            _register_subproc(_proc)
        except Exception as _exc:
            _zyg_log.debug('subprocess registration skipped: %s', _exc)
        _out, _err = _proc.communicate(timeout=timeout_s)
        _rc = _proc.returncode
    except subprocess.TimeoutExpired:
        try:
            _proc.kill()
            _proc.communicate(timeout=30)
        except Exception as _exc:
            _zyg_log.debug('killing the timed-out TTS worker was incomplete: %s', _exc)
        log('WARNING', f'TTS worker timed out after {timeout_s:.0f}s')
        return 124, {}
    except Exception as _run_e:
        log('WARNING', f'TTS worker failed to start: {_run_e!r}')
        return 125, {}
    finally:
        try:
            if _proc is not None:
                _finish_subproc(_proc)
        except Exception as _exc:
            _zyg_log.debug('subprocess deregistration skipped: %s', _exc)
    for _line in reversed((_out or '').strip().splitlines()):
        _line = _line.strip()
        if _line.startswith('{'):
            try:
                return _rc, json.loads(_line)
            except ValueError as _exc:
                _zyg_log.debug('non-JSON worker line ignored: %s', _exc)
                continue
    if _rc != 0:
        _tail = '\n'.join((_err or '').strip().splitlines()[-4:])
        log('WARNING', f'TTS worker rc={_rc}: {_tail}')
    return _rc, {}


def _tts_batch_file(segments: list, work_dir: str) -> 'tuple[str, list]':
    """Write the worker batch JSON; return (batch_path, expected_out_paths)."""
    os.makedirs(work_dir, exist_ok=True)
    _items, _outs = [], []
    for _i, (_sent, _pause) in enumerate(segments):
        _o = os.path.join(work_dir, f'seg_{_i:04d}.wav')
        _items.append({'text': _sent, 'out': _o})
        _outs.append(_o)
    _bp = os.path.join(work_dir, 'batch.json')
    with open(_bp, 'w', encoding='utf-8') as _f:
        json.dump(_items, _f)
    return _bp, _outs


_GPU_PROBE: dict = {'ts': 0.0, 'ok': True}


def _gpu_usable() -> bool:
    """Is CUDA plausibly alive? nvidia-smi failing (e.g. the 2026-08-07 NVML
    driver/library mismatch after an apt driver update) means the engines run on
    CPU at ~4-6 s/word instead of ~1 s/word. Cached for 5 min."""
    if time.time() - _GPU_PROBE['ts'] < 300:
        return _GPU_PROBE['ok']
    ok = True
    try:
        _r = subprocess.run([exe('nvidia-smi'), '-L'], capture_output=True, timeout=15)
        ok = _r.returncode == 0
    except Exception:
        ok = False
    _GPU_PROBE.update(ts=time.time(), ok=ok)
    return ok


def _tts_timeout_for(segments: list) -> float:
    """Generous per-run budget: model load + ~RTF 1.0 with headroom.

    On a dead/absent GPU the same words take 4-6 s each on CPU (measured
    2026-08-07: 8 segments ≈ 240 words in 22 min), so the budget scales up —
    otherwise the batch worker is killed mid-run at ~50 min and a healthy
    episode silently downgrades to the fallback engine."""
    _words = sum(len(s.split()) for s, _ in segments)
    if _gpu_usable():
        return min(7200.0, 420.0 + 1.4 * _words)
    return min(16200.0, 900.0 + 8.0 * _words)


def _indextts_segments(
    segments: list, work_dir: str, ref_wav: str, log, emo_alpha: float = None, emo_text: bool = None, seed: int = None
) -> list:
    """PRIMARY engine. Returns per-segment wav paths ([] on failure/VRAM gate).

    `emo_alpha`/`emo_text` (2026-08-07) override the process-wide env defaults per
    CALL. The briefing channels need a calmer read than the story departments
    (operator: the presenter "gets too excited at times"), and flipping the env
    vars would change every concurrent caller in this shared process.
    """
    if not (os.path.isfile(_INDEXTTS_PY) and os.path.isfile(_INDEXTTS_WORKER)):
        log('WARNING', 'IndexTTS-2 worker/venv missing — falling back')
        return []
    _bp, _outs = _tts_batch_file(segments, work_dir)
    if emo_alpha is None:
        emo_alpha = float(os.environ.get('ZYG_INDEXTTS_EMO_ALPHA', '0.6') or 0.6)
    if emo_text is None:
        emo_text = os.environ.get('ZYG_INDEXTTS_EMO_TEXT', '1').strip().lower() not in ('0', 'false', 'no', 'off')
    # `seed` overrides the process-wide seed for THIS call. The worker only
    # varies its seed on its own internal retries (attempt 0 always uses
    # --seed verbatim), so re-synthesising the same text with the same seed
    # reproduces the same audio bit for bit. Anything that wants a genuinely
    # different read — the ASR read-back gate below — has to ask for one.
    _seed_arg = str(int(seed)) if seed is not None else os.environ.get('ZYG_INDEXTTS_SEED', '1672')
    _cmd = [
        _INDEXTTS_PY,
        _INDEXTTS_WORKER,
        '--batch',
        _bp,
        '--ref',
        ref_wav,
        '--seed',
        _seed_arg,
        '--emo-alpha',
        f'{float(emo_alpha):g}',
        '--threads',
        _TTS_WORKER_THREADS,
    ]
    if not emo_text:
        _cmd.append('--no-emo-text')
    # ── VRAM gate: WAIT, do not give up ──────────────────────────────────────
    # The worker exits 3 when free VRAM is under ZYG_INDEXTTS_MIN_VRAM_MB. That
    # shortage is almost always TRANSIENT — another department's pipeline is
    # mid-render and will release the card. Treating it as "engine unavailable"
    # threw away a whole documentary on 2026-10-02: a children's song was in its
    # Illustrate leg, 18508 MiB was free against the 21000 MiB gate, the fallback
    # (Chatterbox) has no .venv any more, and the episode died at Stage 4
    # after completing research, script, tagging and emotion analysis.
    # Re-running the worker is cheap when the gate trips — it checks VRAM and
    # exits before loading anything.
    _rc, _res = _tts_run_worker(_cmd, _tts_timeout_for(segments), log)
    if _rc == 3:
        _waits = max(0, int(os.environ.get('ZYG_TTS_VRAM_WAITS', '30') or 0))
        _wait_s = max(1.0, float(os.environ.get('ZYG_TTS_VRAM_WAIT_S', '20') or 20))
        _t_gate = time.time()
        for _attempt in range(_waits):
            log(
                'INFO',
                f'IndexTTS-2 VRAM gate: {_res.get("free_vram_mib", "?")} MiB free < '
                f'{_res.get("required_vram_mib", "?")} MiB — another job holds the card; '
                f'waiting {_wait_s:.0f}s (attempt {_attempt + 1}/{_waits}, '
                f'{time.time() - _t_gate:.0f}s so far)',
            )
            time.sleep(_wait_s)
            _rc, _res = _tts_run_worker(_cmd, _tts_timeout_for(segments), log)
            if _rc != 3:
                log('INFO', f'IndexTTS-2 VRAM gate cleared after {time.time() - _t_gate:.0f}s — synthesising')
                break
    if _rc == 3:
        # Only now is it a real failure. Name the fallback honestly: saying
        # "falling back to Chatterbox" when Chatterbox is not installed is how
        # a hard stop read as a graceful degrade in the log.
        _fb = (
            'falling back to Chatterbox'
            if _chatterbox_installed()
            else 'and the Chatterbox fallback cannot run (its .venv was deleted 2026-10-02) — this run has no narration'
        )
        log(
            'WARNING',
            f'IndexTTS-2 VRAM gate still shut after '
            f'{_waits} wait(s): {_res.get("free_vram_mib", "?")} MiB free < '
            f'{_res.get("required_vram_mib", "?")} MiB — {_fb}',
        )
        return []
    _good = [_p for _p in _outs if os.path.isfile(_p) and os.path.getsize(_p) > 512]
    if _rc != 0 and len(_good) < len(_outs):
        log(
            'WARNING', f'IndexTTS-2 produced {len(_good)}/{len(_outs)} segments (rc={_rc}) — falling back to Chatterbox'
        )
        return []
    if _res.get('rtf'):
        log(
            'INFO',
            f'IndexTTS-2: {len(_good)}/{len(_outs)} segments, rtf={_res["rtf"]}, load={_res.get("model_load_s", "?")}s',
        )
    return _good if len(_good) == len(_outs) else []


def _chatterbox_installed() -> bool:
    """Is the fallback engine actually runnable on this box?

    It is NOT, as of 2026-10-02. chatterbox_worker.py is still there, untouched
    since 2026-07-30, but the sibling .venv was deleted during that morning's
    disk sweep (the directory mtime is 02:36 that day) — so the worker exists
    and nothing can run it. Every "falling back to Chatterbox" line logged after
    that point therefore means "giving up", and the documentary pipeline has had
    exactly ONE working TTS engine since. Reinstall with install_chatterbox.sh
    in that directory. Callers use this to say which of the two they mean.
    """
    return os.path.isfile(_CHATTERBOX_PY) and os.path.isfile(_CHATTERBOX_WORKER)


def _chatterbox_segments(segments: list, work_dir: str, ref_wav: str, log) -> list:
    """FALLBACK engine. Returns per-segment wav paths ([] on failure)."""
    if not _chatterbox_installed():
        log('WARNING', f'Chatterbox worker/venv missing at {_CHATTERBOX_DIR} — no fallback available')
        return []
    _bp, _outs = _tts_batch_file(segments, work_dir)
    # 2026-08-06: clear the primary engine's leftovers FIRST. IndexTTS-2 returns
    # [] on a partial run but leaves the segments it did write on disk, under the
    # same seg_%04d.wav names this engine uses. Without this wipe, a Chatterbox
    # run that is itself partial reports success for every file that merely
    # EXISTS — so the caller gets a mix of both engines and the episode changes
    # voice mid-sentence. Observed on a 65-segment batch where IndexTTS-2
    # produced 63. Anything not regenerated below is genuinely missing, which is
    # the honest answer.
    for _stale in _outs:
        try:
            os.remove(_stale)
        except OSError as _exc:
            _zyg_log.debug('stale batch file cleanup skipped: %s', _exc)
    _cmd = [
        _CHATTERBOX_PY,
        _CHATTERBOX_WORKER,
        '--batch',
        _bp,
        '--ref',
        ref_wav,
        '--exaggeration',
        os.environ.get('ZYG_CHATTERBOX_EXAGGERATION', '0.3'),
        '--cfg-weight',
        os.environ.get('ZYG_CHATTERBOX_CFG', '0.4'),
        '--seed',
        os.environ.get('ZYG_CHATTERBOX_SEED', '1672'),
    ]
    _rc, _res = _tts_run_worker(_cmd, _tts_timeout_for(segments), log)
    _good = [_p for _p in _outs if os.path.isfile(_p) and os.path.getsize(_p) > 512]
    if not _good:
        log('WARNING', f'Chatterbox produced no audio (rc={_rc})')
        return []
    if len(_good) < len(_outs):
        # Explicit contiguity check (2026-08-25, P-14). The returned list keeps
        # its shape (good paths, original order) but says WHICH indices are
        # missing: a truncated tail and a hole in the middle are different
        # failures, and only the caller pairing text to audio by ORIGINAL
        # index (see _tts_shared) keeps a hole from shifting every later
        # sentence onto the following sentence's audio.
        _good_set = set(_good)
        _missing = [_i for _i, _p in enumerate(_outs) if _p not in _good_set]
        _contig = _missing == list(range(len(_good), len(_outs)))
        log(
            'WARNING',
            f'Chatterbox produced {len(_good)}/{len(_outs)} segments — '
            f'delivering the partial read ('
            + (
                'truncated tail'
                if _contig
                else f'NON-contiguous: missing index(es) {_missing[:12]}' + ('…' if len(_missing) > 12 else '')
            )
            + '); the caller pairs text to audio by original index',
        )
    return _good


_TTS_SEG_NAME_RE = re.compile(r'seg_(\d{4,})\.wav$')


def _tts_segment_indices(paths: list, n_segments: int) -> list:
    """Original segment index of each rendered path, recovered from the
    seg_%04d.wav name _tts_batch_file assigned.

    Falls back to plain list position when a path carries no such name, an
    out-of-range one, or the recovered indices are not unique and ascending —
    so a caller that hands in its own file names pairs positionally exactly as
    before."""
    _out = []
    for _i, _p in enumerate(paths):
        _m = _TTS_SEG_NAME_RE.search(os.path.basename(str(_p)))
        _k = int(_m.group(1)) if _m else _i
        if not (0 <= _k < n_segments):
            _k = _i
        _out.append(_k)
    if len(set(_out)) != len(_out) or _out != sorted(_out):
        return list(range(len(paths)))
    return _out


def _tts_loudnorm_targets() -> 'tuple[float, float]':
    """(I, TP) parsed from _TTS_LOUDNORM ('I=-16:TP=-1.5:LRA=11'), so the
    ZYG_TTS_LOUDNORM override keeps steering the linear pre-gain too."""
    _i, _tp = -16.0, -1.5
    for _part in str(_TTS_LOUDNORM).split(':'):
        _k, _, _v = _part.partition('=')
        try:
            if _k.strip().upper() == 'I':
                _i = float(_v)
            elif _k.strip().upper() == 'TP':
                _tp = float(_v)
        except ValueError as _exc:
            _zyg_log.debug('loudnorm value %r is not numeric, keeping the default: %s', _v, _exc)
    return _i, _tp


def _tts_measure_loudness(path: str, log) -> 'tuple':
    """(integrated LUFS, true peak dBTP) of `path`; either is None when it could
    not be measured.

    LUFS via audio_mix.measure_lufs — the one ebur128 reader every pipeline
    stage shares — and true peak from a second ebur128 pass with peak=true.
    A file of digital silence measures -70.0 LUFS and '-inf dBFS', which the
    peak regex does not match, so it comes back (-70.0, None)."""
    _lufs = None
    try:
        from zyg_workflows import audio_mix as _am_t

        _lufs = _am_t.measure_lufs(path)
    except Exception as _lm_e:
        log('WARNING', f'TTS: audio_mix.measure_lufs unavailable ({_lm_e!r})')
    _tp = None
    try:
        _r = subprocess.run(
            [
                exe('ffmpeg'),
                '-hide_banner',
                '-nostats',
                '-i',
                path,
                '-map',
                '0:a',
                '-filter:a',
                'ebur128=peak=true',
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        _err = _r.stderr or ''
        _pm = re.findall(r'Peak:\s*(-?[0-9.]+)\s*dBFS', _err)
        if _pm:
            _tp = float(_pm[-1])
        if _lufs is None:
            _im = re.findall(r'I:\s*(-?[0-9.]+)\s*LUFS', _err)
            if _im:
                _lufs = float(_im[-1])
    except Exception as _tp_e:
        log('WARNING', f'TTS: true-peak measurement failed ({_tp_e!r})')
    return _lufs, _tp


def _tts_assemble(seg_paths: list, segments: list, out_path_: str, log, loudnorm: bool = True) -> bool:
    """Concatenate segments with their designed pauses, then bring the level up.

    seg_paths[i] is paired with segments[i] (its text and its designed pause)
    by LIST POSITION — hand in lists that are already paired by original
    segment index (see _tts_segment_indices) when the read is partial.

    loudnorm=True (2026-08-25, P-14) no longer means a bare single-pass
    `loudnorm=...`: that ran ffmpeg's DYNAMIC AGC (no measured values), which
    reshaped the pauses the segment pause map had just authored, and Stage 4
    then applied its own limiter-first pass on top — the voice was dynamics-
    processed twice and lossy-encoded three times. Now the raw WAV is measured
    once and ONE plain gain is applied at the final encode: the deficit to the
    configured I target, capped by the true-peak headroom to the TP target.
    Level, not dynamics; the downstream stage limits exactly once. If the
    measurement fails the old loudnorm filter is used and the fallback logged.

    loudnorm=False delivers the raw concatenation — for callers that master the
    whole programme themselves (narration_service ducks and masters at -14 LUFS;
    per-segment normalization would flatten the dynamics between segments).
    """
    try:
        import numpy as _np_a
        import soundfile as _sf_a
    except ImportError as _imp_e:
        log('WARNING', f'TTS assemble: missing dependency — {_imp_e}')
        return False
    _pieces, _sr = [], None
    for _i, _p in enumerate(seg_paths):
        try:
            _data, _this_sr = _sf_a.read(_p, dtype='float32', always_2d=False)
        except Exception as _rd_e:
            log('WARNING', f'TTS assemble: unreadable segment {_p} ({_rd_e!r}) — skipped')
            continue
        if getattr(_data, 'ndim', 1) > 1:
            _data = _data.mean(axis=1)
        if _sr is None:
            _sr = int(_this_sr)
        elif int(_this_sr) != _sr:
            log('WARNING', f'TTS assemble: sample-rate mismatch ({_this_sr} != {_sr}) — skipping segment {_i}')
            continue
        _pieces.append(_tts_trim_edge_silence(_data, _np_a, sample_rate=_sr))
        _pause_ms = segments[_i][1] if _i < len(segments) else 420
        _pieces.append(_np_a.zeros(int(_pause_ms * _sr / 1000), dtype=_np_a.float32))
    if not _pieces or _sr is None:
        return False

    _full = _np_a.concatenate(_pieces)
    _out_abs = os.path.abspath(out_path_)
    _out_ext = os.path.splitext(_out_abs)[1].lower()
    os.makedirs(os.path.dirname(_out_abs) or '.', exist_ok=True)
    _raw = _out_abs + '.tts_raw.wav'
    try:
        _sf_a.write(_raw, _full, _sr)
        if not loudnorm:
            shutil.move(_raw, _out_abs)
            _raw = None
            return os.path.isfile(_out_abs) and os.path.getsize(_out_abs) > 1000
        # ── Linear pre-gain, measured on the intermediate WAV ──────────────
        _tgt_i, _tgt_tp = _tts_loudnorm_targets()
        _lufs, _tp = _tts_measure_loudness(_raw, log)
        if _lufs is not None and _lufs > -69.0 and _tp is not None:
            _deficit = _tgt_i - _lufs  # dB to the loudness target
            _headroom = _tgt_tp - _tp  # dB before the peak ceiling
            _gain = _deficit
            if _headroom >= _deficit - 0.05:
                _af = f'volume={_gain:.3f}dB' if abs(_gain) >= 0.05 else None
                _mode = 'linear pre-gain'
                log(
                    'INFO',
                    f'TTS: linear pre-gain {_gain:+.2f} dB (raw {_lufs:.1f} LUFS / '
                    f'{_tp:.1f} dBTP → target I={_tgt_i:g} TP={_tgt_tp:g})',
                )
            else:
                # Not enough peak headroom for a purely linear lift. Apply the
                # full gain and let a brick-wall limiter hold the ceiling
                # (limiter-first, the same shape audio_mix.level_to uses).
                # Shipping the peak-capped shortfall instead left every caller
                # WITHOUT a downstream leveller — pipeline_video per-scene
                # mp3s, the storyteller synth path, the voice previews —
                # 3-5 dB under target.
                _lim_db = _tgt_tp - 1.0  # sample-peak ceiling under the TP target
                _lim = 10 ** (_lim_db / 20.0)
                _af = f'volume={_gain:.3f}dB,alimiter=limit={_lim:.5f}:attack=5:release=60:level=disabled'
                _mode = 'linear pre-gain + limiter'
                log(
                    'INFO',
                    f'TTS: linear pre-gain {_gain:+.2f} dB + limiter at '
                    f'{_lim_db:.1f} dBFS (raw {_lufs:.1f} LUFS / {_tp:.1f} dBTP; '
                    f'only {_headroom:.1f} dB of peak headroom for a '
                    f'{_deficit:.1f} dB lift → target I={_tgt_i:g} TP={_tgt_tp:g})',
                )
        else:
            # Measurement failed or the assembly is digital silence: the old
            # single-pass filter is the known-safe path (on silence it is a
            # no-op, and a silent voice is the caller's problem to detect).
            _af = f'loudnorm={_TTS_LOUDNORM}'
            _mode = 'loudnorm fallback'
            log(
                'WARNING',
                f'TTS: raw assembly unmeasurable or silent (I={_lufs}, '
                f'TP={_tp}) — falling back to single-pass loudnorm',
            )
        _filt = ['-af', _af] if _af else []
        if _out_ext in ('.mp3', '.m4a', '.aac'):
            _enc = subprocess.run(
                [exe('ffmpeg'), '-y', '-i', _raw] + _filt + ['-ar', str(_sr), '-q:a', '2', _out_abs],
                capture_output=True,
                timeout=600,
            )
            if _enc.returncode != 0:
                # Degrade gracefully: un-normalized beats no audio.
                log('WARNING', f'TTS: {_mode} encode failed — retrying plain {_out_ext}')
                _enc = subprocess.run(
                    [exe('ffmpeg'), '-y', '-i', _raw, '-q:a', '2', _out_abs], capture_output=True, timeout=600
                )
            if _enc.returncode != 0:
                log('WARNING', f'TTS: ffmpeg encode to {_out_ext} failed')
                return False
        elif not _filt:
            # Already on target — the raw WAV IS the deliverable.
            shutil.move(_raw, _out_abs)
            _raw = None
        else:
            _ln = subprocess.run(
                [exe('ffmpeg'), '-y', '-i', _raw] + _filt + ['-ar', str(_sr), '-c:a', 'pcm_s16le', _out_abs],
                capture_output=True,
                timeout=600,
            )
            if _ln.returncode != 0:
                log('WARNING', f'TTS: {_mode} failed — delivering un-normalized audio')
                shutil.move(_raw, _out_abs)
                _raw = None
        return os.path.isfile(_out_abs) and os.path.getsize(_out_abs) > 1000
    except Exception as _asm_e:
        log('WARNING', f'TTS assemble failed: {_asm_e!r}')
        return False
    finally:
        if _raw and os.path.isfile(_raw):
            try:
                os.remove(_raw)
            except Exception as _exc:
                _zyg_log.debug('raw segment cleanup skipped: %s', _exc)
