# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.music — the music-cues section — track resolution and cue segmentation (lines 819-980).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    _MUSIC_DIR,
    _SR,
    _log_noop,
    exe,
    np,
    os,
    subprocess,
)
from zyg_workflows.storyteller_scene_service.audio import (
    _audio_asset,
    _read_mono48k,
)

# ── music cues ───────────────────────────────────────────────────────────────


def _music_track(cue: dict, out_dir: str, log_fn=None) -> str | None:
    """Resolve a cue's audio: an explicit file, a soundtracks-library entry, or
    a track GENERATED on the spot by ACE-Step 1.5 (MIT weights, so a cue is
    licence-clean for a monetised channel without hunting for CC0 music).

    Generated tracks are written into the soundtracks library, keyed by cue
    name, so the second scene that asks for the same cue reuses the file rather
    than re-rolling the music — a score has to stay the same between renders.
    """
    log = log_fn or _log_noop
    f = cue.get('file')
    if f:
        for cand in (f, os.path.join(_MUSIC_DIR, f), _audio_asset(f)):
            if os.path.isfile(cand):
                return cand
        log(f'[scene] music file not found: {f}')
    gen = cue.get('generate')
    if not gen:
        return None
    os.makedirs(_MUSIC_DIR, exist_ok=True)
    dst = os.path.join(_MUSIC_DIR, f'{cue.get("name", "cue")}.mp3')
    if os.path.isfile(dst) and os.path.getsize(dst) > 10_000:
        return dst
    try:
        from zyg_workflows import ace_step_service as ace
    except ImportError:
        log('[scene] ACE-Step service unavailable — cue unscored')
        return None
    if not ace.is_available():
        log('[scene] ACE-Step unavailable (ComfyUI down or checkpoint missing)')
        return None
    ok = ace.generate(
        gen['prompt'], dst, duration_s=int(gen.get('seconds', 60)), seed=int(gen.get('seed', 1672)), log_fn=log
    )
    return dst if ok else None


def _music_segment(
    src: str,
    dur_s: float,
    lufs: float,
    fade_in_s: float,
    fade_out_s: float,
    work_wav: str,
    audio_mix,
    start_s: float = 0.0,
    compress: bool = True,
    settle: dict | None = None,
    log_fn=None,
) -> np.ndarray | None:
    """A dur_s slice of `src` normalised to `lufs`, with head/tail fades.

    `settle` (2026-08-25) gives the cue a MIDDLE shape as well: after the entry
    it is held at full for `hold_s`, then over `over_s` it recedes to `db`
    below full and stays THERE until the fade-out, which then runs from that
    softer level to silence. That is "screams rising out of the dark, holding,
    then falling back to a murmur he speaks over" — a shape a fade-in and a
    fade-out alone cannot author, because between them a cue can only be full.
    The drop is linear in dB so it reads as one even recession rather than a
    fast start that stalls; the hold that follows is a flat multiplier. All
    times are cue-relative seconds. Absent, the cue is exactly what it was.

    ORDER MATTERS: the excerpt is cut FIRST and levelled second. Levelling the
    whole track and then slicing sets the level of music that is never heard —
    a generated cue that opens with a slow build measured -28 LUFS over its
    full 60 s while the 11 s actually used sat ~10 dB lower, i.e. inaudible
    under the bed. Normalising the excerpt makes the authored number describe
    what the viewer hears.

    The fades are the cue's dramatic shape — 'softly in under the last line,
    out just before the card' lives here, not in a gain ride elsewhere — so
    they go on AFTER levelling and are never re-normalised.
    """
    import soundfile as sf

    log = log_fn or _log_noop
    if dur_s <= 0.05:
        return None
    d = _read_mono48k(src)
    a = int(max(0.0, start_s) * _SR)
    need = int(dur_s * _SR)
    seg = d[a : a + need]
    if len(seg) < need:  # loop a short track to fill the cue
        if len(seg) < _SR:
            log(f'[scene] music source too short ({len(d) / _SR:.1f}s) — cue skipped')
            return None
        xf = min(int(1.5 * _SR), len(seg) // 4)
        out = seg.copy()
        while len(out) < need:
            head = seg.copy()
            out[-xf:] = out[-xf:] * np.linspace(1, 0, xf) + head[:xf] * np.linspace(0, 1, xf)
            out = np.concatenate([out, head[xf:]])
        seg = out[:need]
    raw_wav = work_wav.replace('.wav', '_cut.wav')
    sf.write(raw_wav, seg, _SR)
    if compress:
        # Underscore has to hold ONE quiet level: generated cues swing ~20 dB
        # internally, so at an average that sits politely under the dialogue the
        # soft bars vanish into the bed and the loud ones jump out. Compressing
        # to a ~6 dB range makes 'just loud enough to hear' true for the whole
        # cue instead of on average.
        comp_wav = work_wav.replace('.wav', '_comp.wav')
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-loglevel',
                'error',
                '-y',
                '-i',
                raw_wav,
                '-af',
                'acompressor=threshold=-26dB:ratio=4:attack=20:release=400:makeup=2',
                '-ar',
                str(_SR),
                '-ac',
                '1',
                '-c:a',
                'pcm_s16le',
                comp_wav,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and os.path.isfile(comp_wav):
            raw_wav = comp_wav
        else:
            log(f'[scene] music compressor failed ({r.stderr[:150]}) — using raw cue')
    norm = audio_mix.loudnorm_two_pass(raw_wav, work_wav, i=float(lufs), tp=-3.0, log_fn=log)
    seg = _read_mono48k(norm['out'] if norm else raw_wav)[:need].copy()
    ni, no = int(fade_in_s * _SR), int(fade_out_s * _SR)
    ni, no = max(0, min(ni, len(seg))), max(0, min(no, len(seg)))
    if settle:
        # Applied BEFORE the edge fades so the fade-out multiplies the settled
        # level (soft → silence) rather than the full one. The regions cannot
        # overlap: the settle begins after the fade-in and is clipped to end
        # before the fade-out starts.
        hold = int(max(0.0, float(settle.get('hold_s', 0.0))) * _SR)
        over = int(max(0.0, float(settle.get('over_s', 1.0))) * _SR)
        db = float(settle.get('db', -12.0))
        a = ni + hold
        b_max = len(seg) - no
        if a >= b_max:
            log(
                f'[scene] WARN music settle skipped: the cue is too short for '
                f'fade-in {fade_in_s:g}s + hold {settle.get("hold_s", 0.0)}s '
                f'before its {fade_out_s:g}s fade-out ({len(seg) / _SR:.2f}s)'
            )
        else:
            b = min(b_max, a + over)
            if b > a:
                seg[a:b] *= 10.0 ** (np.linspace(0.0, db, b - a) / 20.0)
            seg[b:] *= 10.0 ** (db / 20.0)
    if ni > 0:
        seg[:ni] *= np.linspace(0.0, 1.0, ni) ** 1.5  # slow, unhurried entry
    if no > 0:
        seg[-no:] *= np.linspace(1.0, 0.0, no) ** 1.5
    return seg
