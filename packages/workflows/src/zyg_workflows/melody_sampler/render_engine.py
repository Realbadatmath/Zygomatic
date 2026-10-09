# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""melody_sampler.render_engine — sample loading, the one-shot renderer and the per-voice level calibration.

Moved verbatim out of the 1,177-line melody_sampler.py; original lines 341-616.
"""

from zyg_workflows.melody_sampler.constants import LIB_DIR, SR, _PH_LENGTH_S, _zyg_log, os, random

from zyg_workflows.melody_sampler.sample_index import index

# ── Sample loading ───────────────────────────────────────────────────────────

_AUDIO_CACHE = {}


def _resample(mono_or_stereo, src_sr, dst_sr):
    import numpy as np

    if src_sr == dst_sr:
        return mono_or_stereo
    n_src = mono_or_stereo.shape[0]
    n_dst = max(1, int(round(n_src * dst_sr / float(src_sr))))
    src_t = np.arange(n_src, dtype=np.float64)
    dst_t = np.arange(n_dst, dtype=np.float64) * (src_sr / float(dst_sr))
    return np.stack(
        [np.interp(dst_t, src_t, mono_or_stereo[:, c]) for c in range(mono_or_stereo.shape[1])], axis=1
    ).astype('float32')


def _read_stereo(path, sr):
    """(frames, 2) float32 at `sr`. Mono is duplicated, not panned."""
    import numpy as np
    import soundfile as sf

    data, file_sr = sf.read(path, dtype='float32', always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    return _resample(np.ascontiguousarray(data), file_sr, sr)


def _sample_audio(file_id, sr):
    hit = _AUDIO_CACHE.get((file_id, sr))
    if hit is None:
        hit = _read_stereo(os.path.join(LIB_DIR, file_id), sr)
        _AUDIO_CACHE[(file_id, sr)] = hit
    return hit


def _dyn_rank(dynamic, velocity):
    """0 when the recorded dynamic matches how hard the note is struck."""
    if velocity <= 45:
        want = ('pianissimo', 'piano')
    elif velocity <= 75:
        want = ('mezzo-piano', 'mezzo-forte')
    elif velocity <= 105:
        want = ('forte',)
    else:
        want = ('fortissimo',)
    return 0 if dynamic in want else 1


def _pick(rows, by_midi, target, velocity, dur_s):
    """Nearest recorded pitch; ties broken by dynamic, then by sample length.

    Fully deterministic — file_id is the last key, so the same note always
    selects the same recording and a re-render is bit-identical.
    """
    best_d = min(abs(m - target) for m in by_midi)
    cands = [r for r in rows if abs(r['midi'] - target) == best_d]
    return min(
        cands,
        key=lambda r: (
            _dyn_rank(r['dynamic'], velocity),
            abs(_PH_LENGTH_S.get(r['length'], dur_s) - dur_s),
            r['file_id'],
        ),
    )


def render_events(events, voice_key, *, sr=SR, transpose=0, gain=1.0, release_s=0.08, max_shift=7):
    """Play (start_s, dur_s, midi, velocity) events on one sampled voice.

    Returns ``(audio, stats)`` where audio is float32 (frames, 2) and stats is
    ``dict(notes, shifted_octave, max_shift_used, files)``.

    Events use the same 4-tuple shape ``kids_music_service.write_midi`` builds,
    except that the times here are SECONDS — the caller multiplies beats by
    60/bpm.

    Pitch shifting is varispeed (plain resampling): a semitone up is the sample
    played 2**(1/12) faster, so it also gets shorter and brighter. That is the
    correct and expected behaviour for one-shots and is why `max_shift` is
    small: past about a fifth the instrument starts sounding like a different,
    smaller instrument. A note that cannot be reached within `max_shift` is
    moved by whole octaves into the voice's range instead, and counted.
    """
    import numpy as np

    rows = index().get(voice_key) or []
    stats = {'notes': 0, 'shifted_octave': 0, 'max_shift_used': 0, 'files': set()}
    if not rows or not events:
        return np.zeros((int(2.5 * sr), 2), dtype='float32'), stats

    by_midi = [r['midi'] for r in rows]
    lo, hi = by_midi[0], by_midi[-1]

    total_s = max(float(e[0]) + float(e[1]) for e in events)
    n_total = int(round((total_s + 2.5) * sr))
    buf = np.zeros((n_total, 2), dtype='float32')

    attack_n = max(1, int(round(0.002 * sr)))
    release_n = max(1, int(round(release_s * sr)))

    for start_s, dur_s, midi, velocity in events:
        start_s, dur_s = float(start_s), max(0.01, float(dur_s))
        velocity = int(max(1, min(127, velocity)))
        target = int(midi) + int(transpose)

        # Out of reach: octave-fold toward the recorded range rather than
        # resampling a cello into a cartoon.
        folded = target
        while folded < lo - max_shift:
            folded += 12
        while folded > hi + max_shift:
            folded -= 12
        if folded != target:
            stats['shifted_octave'] += 1
            target = folded

        row = _pick(rows, by_midi, target, velocity, dur_s)
        shift = target - row['midi']
        stats['max_shift_used'] = max(stats['max_shift_used'], abs(shift))
        stats['files'].add(row['file_id'])
        stats['notes'] += 1

        src = _sample_audio(row['file_id'], sr)
        n_out = int(round((dur_s + release_s) * sr))
        if n_out < 2:
            continue
        ratio = 2.0 ** (shift / 12.0)
        pos = np.arange(n_out, dtype=np.float64) * ratio
        avail = int(src.shape[0])
        keep = int(np.searchsorted(pos, avail - 1, side='left'))
        if keep < 2:
            continue
        pos = pos[:keep]
        src_t = np.arange(avail, dtype=np.float64)
        seg = np.stack([np.interp(pos, src_t, src[:, c]) for c in range(2)], axis=1).astype('float32')

        env = np.ones(seg.shape[0], dtype='float32')
        a = min(attack_n, seg.shape[0])
        env[:a] = np.linspace(0.0, 1.0, a, dtype='float32')
        r = min(release_n, seg.shape[0])
        env[-r:] *= np.linspace(1.0, 0.0, r, dtype='float32')
        seg *= env[:, None] * float(gain) * (velocity / 127.0) ** 1.6

        i0 = int(round(start_s * sr))
        if i0 >= n_total:
            continue
        i1 = min(n_total, i0 + seg.shape[0])
        buf[i0:i1] += seg[: i1 - i0]

    return buf, stats


# ── Plan render ──────────────────────────────────────────────────────────────

# Fixed velocities. kids_music_theory.lead_gain() is keyed on GM program
# numbers, which mean nothing to a sampled voice — a recorded flute is not the
# GM flute patch and does not need its compensation curve.
V_MEL_STRONG, V_MEL_WEAK = 112, 96
V_PAD_TOP, V_BASS = 70, 84

_ROLE_DB = {'lead': 0.0, 'pad': -9.0, 'bass': -6.0}
_PERC_DB = -4.0

# ── Per-voice level calibration ──────────────────────────────────────────────
#
# _ROLE_DB is a MIXER, and a mixer's numbers only mean anything if the sources
# reaching it are level-matched. They are not: these are 66k one-shots from five
# unrelated packs, recorded at whatever level each project chose. Measured
# 2026-09-06 on a 25 s 'counting' plan (marimba / guitar_steel / lately-bass):
# the melody stem came out 16.1 dB UNDER the bass and kids_music_service's
# mix_balance gate correctly refused to ship it — freepats' 'lately bass' peaks
# around 0.55 where the VCSL marimba peaks around 0.13, an 8 dB difference
# before a single fader moves.
#
# So each voice is brought to one reference peak first, and only then does
# _ROLE_DB decide the balance. This is calibration of the LIBRARY, not of the
# render: the gain depends on the voice's own recordings and on nothing about
# the plan, which is exactly why mix_balance stays a real gate afterwards — a
# sparse melody under a dense bass can still fail it.
CAL_PEAK = 0.45  # reference peak every voice is normalised to
_CAL_PROBE = 12  # samples read per voice to measure it
_CAL_CACHE = {}


def _db(x):
    return 10.0 ** (x / 20.0)


def voice_gain(key):
    """Linear gain that brings voice `key` to the CAL_PEAK reference.

    Measured from up to `_CAL_PROBE` evenly spaced recordings of the voice, by
    MEDIAN peak: the median ignores the one clipped or one near-silent sample a
    pack of a few hundred usually contains, where a max or a mean would let it
    set the level for the whole instrument.
    """
    import numpy as np

    if key in _CAL_CACHE:
        return _CAL_CACHE[key]
    rows = index().get(key) or []
    peaks = []
    if rows:
        step = max(1, len(rows) // _CAL_PROBE)
        for r in rows[::step][:_CAL_PROBE]:
            try:
                a = _sample_audio(r['file_id'], SR)
            except Exception as _exc:  # noqa: BLE001 — an unreadable file
                _zyg_log.debug('voice sample unreadable, left out of the peak scan: %s', _exc)
                continue
            if a.size:
                peaks.append(float(np.abs(a).max()))
    med = float(np.median(peaks)) if peaks else 0.0
    # A voice whose recordings are already silent-ish cannot be rescued by gain;
    # 1.0 leaves it exactly as it was rather than multiplying noise by 400.
    g = 1.0 if med < 1e-3 else min(8.0, CAL_PEAK / med)
    _CAL_CACHE[key] = g
    return g


def _plan_events(plan):
    """The plan's three roles as second-based event lists.

    The shaping — section scaling and the ±6 ms micro-timing — is copied from
    ``kids_music_service.write_midi`` (and consumes the jitter stream in the
    same order) so that the SoundFont render and the sampled render of one plan
    are the same performance played by different players, not two different
    performances.
    """
    from zyg_workflows import kids_music_theory as T

    bpm = float(plan['bpm'])
    spb = 60.0 / bpm
    bar_beats = float(plan['bar_beats'])
    n_sec = max(1, len(plan.get('order') or [1]))

    def _sec_scale(idx):
        if idx is None or idx < 0:
            return 0.90
        return 0.94 + 0.12 * (idx / max(1, n_sec - 1)) if n_sec > 1 else 1.0

    _jit = random.Random(int(plan.get('seed', 0)) ^ 0x5EED)
    _JIT_BEATS = (6.0 / 1000.0) * bpm / 60.0

    def _j(t, amount=1.0):
        return max(0.0, t + _jit.uniform(-_JIT_BEATS, _JIT_BEATS) * amount)

    def _clip(v):
        return int(max(1, min(127, round(v))))

    mel = []
    for n in plan['melody']:
        base = V_MEL_STRONG if n['strong'] else V_MEL_WEAK
        v = _clip(base * _sec_scale(n.get('section')))
        mel.append((_j(n['t']) * spb, max(0.12, n['d'] * 0.92) * spb, n['p'], v))

    pad = []
    for c in plan['chords']:
        sc = _sec_scale(c.get('section'))
        for k, m in enumerate(c['midi']):
            v = _clip((V_PAD_TOP - k * 4) * sc)
            pad.append((_j(c['t'], 0.5) * spb, bar_beats * 0.96 * spb, m, v))

    bass = []
    for c in plan['chords']:
        sc = _sec_scale(c.get('section'))
        for st in T.METERS[plan['meter']]['strong']:
            v = _clip(V_BASS * sc)
            bass.append((_j(c['t'] + st, 0.5) * spb, min(bar_beats, 1.4) * spb, c['bass'], v))

    return {'lead': mel, 'pad': pad, 'bass': bass}
