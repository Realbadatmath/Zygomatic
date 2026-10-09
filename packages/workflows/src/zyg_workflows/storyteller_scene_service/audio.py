# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.audio — the audio-helpers section — asset lookup, cuts, islands and ASR verification (lines 602-818).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    _AUDIO_DIRS,
    _SFX_DIR,
    _SR,
    _log_noop,
    _zyg_log,
    exe,
    json,
    np,
    os,
    paths,
    subprocess,
)

# ── audio helpers ────────────────────────────────────────────────────────────


def _read_mono48k(path: str) -> np.ndarray:
    import soundfile as sf

    d, sr = sf.read(path, dtype='float64')
    if d.ndim > 1:
        d = d.mean(axis=1)
    if sr != _SR:
        n_out = int(round(len(d) * _SR / sr))
        x_old = np.linspace(0.0, 1.0, num=len(d), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        d = np.interp(x_new, x_old, d)
    return d.astype(np.float64)


def _audio_asset(name: str) -> str:
    """Resolve a bare library filename across the audio categories.

    Returns the first existing path, else the sfx-dir path — so a miss still
    reaches the caller as a normal "file not found" against the primary
    library rather than a silent empty layer.
    """
    n = os.path.basename(str(name or ''))
    for d in _AUDIO_DIRS:
        p = os.path.join(d, n)
        if os.path.isfile(p):
            return p
    return os.path.join(_SFX_DIR, n)


def _audio_dur(path: str) -> float:
    """Length of an audio file in seconds; 0.0 when it cannot be probed."""
    r = subprocess.run(
        [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
        capture_output=True,
        text=True,
    )
    try:
        return float(r.stdout.strip())
    except (TypeError, ValueError):
        return 0.0


def _sfx_cut(src: str, start_s: float, dur_s: float, gain_db: float = 0.0, fade_s: float = 0.15) -> np.ndarray:
    d = _read_mono48k(src)
    a = int(start_s * _SR)
    b = min(len(d), a + int(dur_s * _SR))
    seg = d[a:b].copy()
    n_f = max(1, int(fade_s * _SR))
    if len(seg) > 2 * n_f:
        seg[:n_f] *= np.linspace(0.0, 1.0, n_f)
        seg[-n_f:] *= np.linspace(1.0, 0.0, n_f)
    return seg * (10.0 ** (gain_db / 20.0))


def _speech_islands(
    d: np.ndarray, floor_db: float = -42.0, pad_s: float = 0.06, min_gap_s: float = 0.20, min_len_s: float = 0.10
) -> list[tuple[int, int]]:
    """Contiguous runs of actual SPEECH, silences excluded.

    A line placed in the running order only has to start after the previous one,
    so the silence the TTS pads its renders with never mattered. An ANCHORED
    line has to hit a named instant on the timeline, and the padding is a large
    fraction of a one-word render — placing the file would put the word
    somewhere in a ±0.4 s window instead of on the mark.

    It returns ISLANDS rather than one outer span because Chatterbox SAYS A
    SHORT PROMPT TWICE. Measured on this scene's 'Home.' render: the word at
    0.05-0.55 s, silence, then the whole word again at 0.90-1.50 s, 8 dB louder.
    An outer first-to-last span would have placed 1.5 s of "Home … Home" on a
    mark meant for one word. Splitting on the gap makes the repeat visible so
    the caller can pick a take and log the defect instead of shipping it.

    Envelope-gated in numpy rather than via ffmpeg's silenceremove, which
    rewrites the audio; this only reports indices, so the word is never touched.
    """
    if not len(d):
        return []
    win = max(1, int(0.02 * _SR))
    n = (len(d) // win) * win
    if n < win:
        return [(0, len(d))]
    rms = np.sqrt((d[:n].reshape(-1, win) ** 2).mean(axis=1) + 1e-12)
    thr = max(rms.max() * (10.0 ** (floor_db / 20.0)), 1e-5)
    loud = np.flatnonzero(rms > thr)
    if not len(loud):
        return [(0, len(d))]
    # split wherever the quiet run between two loud blocks exceeds min_gap_s
    gap = max(1, int(min_gap_s * _SR / win))
    cuts = np.flatnonzero(np.diff(loud) > gap)
    groups = np.split(loud, cuts + 1)
    pad = int(pad_s * _SR)
    out = []
    for g in groups:
        a = max(0, int(g[0]) * win - pad)
        b = min(len(d), (int(g[-1]) + 1) * win + pad)
        if (b - a) / _SR >= min_len_s:
            out.append((a, b))
    return out or [(0, len(d))]


# The transcriber venv's interpreter (see _transcribe).
_ASR_PY = paths.ZYG_ASR_PYTHON


def _transcribe(wav: str, log_fn=None) -> str | None:
    """Transcribe one short wav. Returns the text, or None if no ASR is reachable.

    `zyg_whisper` is not importable under the interpreter this service runs on
    (/usr/bin/python3), so the check that the notes call the most necessary one
    was silently absent on every build — it logged "unavailable" and moved on.
    faster_whisper IS installed in the transcriber's venv, so that interpreter is
    the fallback: a subprocess, but this only ever runs on lines a spec asked to
    have verified, and a wrong take shipping is far more expensive.
    """
    log = log_fn or _log_noop
    try:
        import zyg_whisper

        segs, _ = zyg_whisper.transcribe_segments(wav, language='en')
        return ' '.join((s.get('text') or '') for s in segs).strip()
    except Exception as _exc:
        _zyg_log.debug('in-process zyg_whisper transcription unavailable, trying the transcriber venv: %s', _exc)
    if not os.path.isfile(_ASR_PY):
        return None
    code = (
        'import sys, json\n'
        'from faster_whisper import WhisperModel\n'
        'm = WhisperModel("small", device="cpu", compute_type="int8")\n'
        'segs, _ = m.transcribe(sys.argv[1], language="en")\n'
        'print(json.dumps(" ".join(s.text for s in segs).strip()))\n'
    )
    try:
        r = subprocess.run([_ASR_PY, '-c', code, wav], capture_output=True, text=True, timeout=300)
    except Exception as exc:
        log(f'[scene] ASR fallback failed: {exc}')
        return None
    if r.returncode != 0:
        log(f'[scene] ASR fallback failed: {r.stderr.strip()[-200:]}')
        return None
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def _verify_line_text(seg: np.ndarray, text: str, out_dir: str, tag: str, log_fn=None) -> bool | None:
    """Does the audio being shipped actually SAY the line? Warn-only.

    Aimed at anchored lines, which are short, and short prompts are where this
    TTS misbehaves. Measured on 'Home.': seed 1672 rendered a spurious word
    before it (whisper: "Q. Home." / "Here. Home."), seed 7 "You know, home.",
    and seed 1673 rendered ONE island that is not the word at all ("Kewaum.").
    That last one is the reason the island split is not enough on its own — a
    clean-looking single take can still be the wrong sound, and nothing else in
    the audio chain would notice: it has correct loudness, no clipping and no
    silence defect. Fail-safe like every other gate here (missing ASR → skip).

    Returns True/False, or None when the check could not run.
    """
    log = log_fn or _log_noop
    try:
        import soundfile as sf
    except ImportError:
        return None
    probe = os.path.join(out_dir, '_verify_probe.wav')
    try:
        sf.write(probe, seg, _SR)
        heard = _transcribe(probe, log_fn=log)
    except Exception as exc:  # ASR is a QC aid, never a gate
        log(f'[scene] {tag}: transcript check unavailable ({exc})')
        return None
    finally:
        if os.path.isfile(probe):
            os.remove(probe)
    if heard is None:
        log(f'[scene] {tag}: transcript check unavailable (no ASR interpreter)')
        return None
    norm = lambda s: ''.join(c for c in s.lower() if c.isalnum() or c == ' ').split()
    want, got = norm(text), norm(heard)
    if want == got:
        log(f'[scene] {tag}: transcript check OK — "{heard}"')
        return True
    log(
        f'[scene] WARN {tag}: expected "{text}" but the render transcribes as '
        f'"{heard}" — check this take before shipping'
    )
    return False


def _pick_island(d: np.ndarray, islands: list[tuple[int, int]], take: str = 'loudest') -> tuple[int, int]:
    """Which island an anchored line ships. 'loudest' is the default because the
    TTS's repeat is a fading restatement — the take it commits to is the one it
    says at full voice.

    'span' keeps EVERYTHING from the first island to the last, trimming only the
    outer padding. Use it for any anchored line longer than a few words: the
    single-island modes exist because a SHORT prompt makes Chatterbox restate
    itself, but a sentence pauses at its own commas, so `min_gap_s` splits it
    into clauses and picking one of them silently ships half the line. The
    failure modes are opposite — short lines risk a repeat, long lines risk
    truncation — so the take mode has to follow the line's length."""
    if len(islands) <= 1:
        return islands[0] if islands else (0, len(d))
    if take == 'span':
        return islands[0][0], islands[-1][1]
    if take == 'first':
        return islands[0]
    if take == 'last':
        return islands[-1]
    if take == 'longest':
        return max(islands, key=lambda s: s[1] - s[0])
    return max(islands, key=lambda s: float(np.abs(d[s[0] : s[1]]).max()))
