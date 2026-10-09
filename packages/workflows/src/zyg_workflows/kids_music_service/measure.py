# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Measurement: key, tempo, level, duration, dead tail and the audio gate.

Moved verbatim out of the old single-file kids_music_service.py (lines 1860-2219).
"""

from __future__ import annotations

import os
import re
import subprocess
from zyg_workflows import kids_music_theory as T
from zyg_workflows.bin import exe

from zyg_workflows.kids_music_service.base import (
    _ff,
    _log_noop,
)
from zyg_workflows.kids_music_service.ace import _family_of

# ── Measurement ──────────────────────────────────────────────────────────────

# Krumhansl-Kessler key profiles: the standard correlation template for "what
# key is this recording in". Used to check that the produced track actually
# landed in the key the plan asked for.
_KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((x - mb) ** 2 for x in b) ** 0.5
    if va == 0 or vb == 0:
        return 0.0
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (va * vb)


def detect_key(path, log_fn=None):
    """Best-matching key of a rendered file, by chroma vs the KK profiles."""
    log_fn = log_fn or _log_noop
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(path, sr=22050, mono=True)
        if y.size < sr:
            return None
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        prof = np.mean(chroma, axis=1).tolist()
        best = None
        for pc in range(12):
            rot = prof[pc:] + prof[:pc]
            for mode, tmpl in (('major', _KK_MAJOR), ('minor', _KK_MINOR)):
                c = _corr(rot, tmpl)
                if best is None or c > best[2]:
                    best = (pc, mode, c)
        return {'tonic_pc': best[0], 'tonic': T.PITCH_NAMES[best[0]], 'mode': best[1], 'correlation': round(best[2], 3)}
    except Exception as e:  # noqa: BLE001
        log_fn(f'key detection unavailable: {type(e).__name__}: {e}'[:160])
        return None


def detect_tempo(path, log_fn=None):
    log_fn = log_fn or _log_noop
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(path, sr=22050, mono=True)
        if y.size < sr:
            return None
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        t = float(np.atleast_1d(tempo)[0])
        return round(t, 1) if t > 0 else None
    except Exception as e:  # noqa: BLE001
        log_fn(f'tempo detection unavailable: {type(e).__name__}: {e}'[:160])
        return None


def _peak_dbfs(path):
    """Sample peak in dBFS via ffmpeg astats. Separate from the LUFS scan
    because loudness and clipping are different questions."""
    try:
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-hide_banner',
                '-nostats',
                '-i',
                path,
                '-map',
                '0:a',
                '-af',
                'astats=measure_overall=Peak_level:measure_perchannel=none',
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        m = re.findall(r'Peak level dB:\s*(-?[0-9.]+|-inf)', r.stderr or '')
        if not m:
            return None
        return None if m[-1] == '-inf' else round(float(m[-1]), 2)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def _duration(path):
    try:
        r = subprocess.run(
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
            timeout=60,
        )
        return round(float((r.stdout or '0').strip()), 2)
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0


# A tail below this, relative to the track's own loud body, is silence.
_TAIL_FLOOR_DB = -45.0
# Warn past this many seconds of dead air. The worst shipped take carried 11.13 s
# (20.7% of the file) and reported "duration within 0.05 s of planned".
DEAD_TAIL_WARN_S = float(os.environ.get('ZYG_KIDSMUSIC_TAIL_WARN_S', '2.5'))


def music_end(path, log_fn=None):
    """Where the music actually STOPS, from short-term RMS.

    The duration gate compares the container length against plan['seconds'] — but
    ace_render forces the latent length from that same value, so the gate is
    measuring the number it just set. It cannot fail, and all six shipped songs
    reported "duration within 0.05 s of planned" while carrying 2.5-11.1 s of
    silence at the end. This measures the audio instead.

    Returns (music_end_s, dead_tail_s, total_s) or (None, None, None).
    """
    try:
        import numpy as np

        r = subprocess.run(
            [exe('ffmpeg'), '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', '8000', '-'],
            capture_output=True,
            timeout=300,
        )
        if r.returncode != 0 or not r.stdout:
            return None, None, None
        x = np.frombuffer(r.stdout, dtype='<f4')
        sr = 8000
        hop = sr // 20  # 50 ms frames
        n = len(x) // hop
        if n < 4:
            return None, None, None
        frames = x[: n * hop].reshape(n, hop)
        rms = np.sqrt(np.mean(np.square(frames.astype('float64')), axis=1))
        db = 20.0 * np.log10(np.maximum(rms, 1e-12))
        # Relative to the track's own body, so a quiet lullaby is not read as
        # silence and a loud mix does not hide a fade.
        ref = float(np.percentile(db, 95))
        loud = np.where(db > ref + _TAIL_FLOOR_DB)[0]
        total = len(x) / float(sr)
        if not len(loud):
            return None, None, round(total, 2)
        end = float((loud[-1] + 1) * hop) / sr
        return round(end, 2), round(max(0.0, total - end), 2), round(total, 2)
    except Exception as e:  # noqa: BLE001 — a measurement, never fatal
        if log_fn:
            log_fn(f'tail: unmeasured ({type(e).__name__})')
        return None, None, None


def trim_tail(src, dst, *, keep_s=1.2, log_fn=None):
    """Trim dead air off the end, for the file that FEEDS THE MASTER only.

    The untrimmed take is kept on disk for inspection — the trim is a mastering
    decision, and throwing away the evidence of what the model actually emitted
    would be the same mistake as a gate that cannot fail. `keep_s` leaves a
    natural release rather than cutting on the last audible sample.

    Returns (path, trimmed_seconds). Falls back to the source on any failure.
    """
    log_fn = log_fn or _log_noop
    end, tail, total = music_end(src, log_fn=log_fn)
    if end is None or not tail or tail <= keep_s + 0.4:
        return src, 0.0
    cut = min(total, end + keep_s)
    if _ff(['-i', src, '-t', f'{cut:.3f}', '-c:a', 'pcm_s16le', '-ar', '48000', dst], log_fn=log_fn):
        log_fn(f'trim: removed {total - cut:.1f}s of dead air ({total:.1f}s -> {cut:.1f}s)')
        return dst, round(total - cut, 2)
    return src, 0.0


def gate_audio(path, plan, *, leg='render', want_clap=True, log_fn=None):
    """Measure one rendered leg against the plan it came from.

    Hard gates (a failure here means the file is not the song): it exists, it is
    not silent, and its duration is within a third of the plan.  Everything else
    is reported as a measurement with a verdict, because "ACE-Step drifted 6 bpm"
    is information, not a reason to throw a finished track away.
    """
    log_fn = log_fn or _log_noop
    g = {
        'leg': leg,
        'path': os.path.basename(path) if path else '',
        'checks': {},
        'ok': False,
        'fails': [],
        'warnings': [],
    }
    if not path or not os.path.isfile(path):
        g['fails'].append('file missing')
        return g

    dur = _duration(path)
    g['checks']['duration_s'] = dur
    g['checks']['planned_s'] = plan['seconds']
    if dur < 5.0:
        g['fails'].append(f'only {dur:.1f}s of audio')
    elif abs(dur - plan['seconds']) > max(8.0, plan['seconds'] * 0.34):
        g['warnings'].append(f'duration {dur:.1f}s vs planned {plan["seconds"]:.1f}s')

    # Container length is not musical length — see music_end().
    m_end, tail, _tot = music_end(path, log_fn=log_fn)
    if m_end is not None:
        g['checks']['music_end_s'] = m_end
        g['checks']['dead_tail_s'] = tail
        g['checks']['dead_tail_pct'] = round(100.0 * tail / max(1e-6, dur), 1)
        if tail and tail > DEAD_TAIL_WARN_S:
            g['warnings'].append(
                f'{tail:.1f}s of dead air at the end ({g["checks"]["dead_tail_pct"]:.0f}% of the file)'
            )

    try:
        from zyg_workflows import audio_mix

        i_lufs = audio_mix.measure_lufs(path, log_fn=None)
        if i_lufs is not None:
            g['checks']['lufs'] = round(float(i_lufs), 2)
            # ebur128 reports digital silence as exactly -70 LUFS; audio_mix
            # treats anything at or under -69 as zeros, so use the same floor.
            if float(i_lufs) <= -60.0:
                g['fails'].append('audio is silent')
        pk = _peak_dbfs(path)
        if pk is not None:
            g['checks']['peak_dbfs'] = pk
            if pk > 0.0:
                # NOT "likely clipped". Measured on all six ACE takes: true peak
                # is indeed positive (+0.06 to +0.62 dBTP) but astats reports
                # flat factor 0.000000 and an absolute-peak count of 1, and the
                # float decode's above-0.99 samples are all at distinct values.
                # That is inter-sample overshoot with intact waveform tops, which
                # the master's limiter handles. Saying "clipped" was the gate
                # over-reading its own measurement.
                g['warnings'].append(
                    f'true peak {pk:.2f} dBFS is above 0 — will be limited on '
                    f'master (not clipping: sample tops are intact)'
                )
    except Exception as e:  # noqa: BLE001
        g['warnings'].append(f'loudness unmeasured ({type(e).__name__})')

    bpm = detect_tempo(path, log_fn=log_fn)
    if bpm:
        g['checks']['detected_bpm'] = bpm
        want = float(plan['bpm'])
        # Beat trackers routinely lock to half or double time; that is an
        # octave error in the tempo domain, not a wrong tempo, so all three
        # are accepted and the ratio is reported.
        ratios = [abs(bpm - want) / want, abs(bpm * 2 - want) / want, abs(bpm / 2 - want) / want]
        err = min(ratios)
        g['checks']['bpm_error'] = round(err, 3)
        g['checks']['bpm_relation'] = ['same', 'half-time', 'double-time'][ratios.index(err)]
        if err > 0.12:
            g['warnings'].append(f'tempo drifted: {bpm:.0f} detected vs {want:.0f} asked')

    k = detect_key(path, log_fn=log_fn)
    if k:
        g['checks']['detected_key'] = f'{k["tonic"]} {k["mode"]}'
        g['checks']['key_correlation'] = k['correlation']
        want_pc = plan['key']['tonic_pc']
        want_mode = 'minor' if 'minor' in plan['key']['mode'] else 'major'
        # The relative major/minor share a pitch-class set, so a chroma template
        # cannot separate them and reporting that as a miss would be a false
        # alarm on every pentatonic tune. The dominant and subdominant share six
        # of seven, which is why a KK correlation on a dense mix so often lands a
        # fifth away from the truth.
        rel_pc = (want_pc + 9) % 12 if want_mode == 'major' else (want_pc + 3) % 12
        if k['correlation'] < 0.60:
            # Below this the template is not choosing a key, it is choosing the
            # least-bad of twenty-four poor fits. Calling that a drift would be
            # asserting something the measurement does not support.
            g['checks']['key_match'] = 'undetermined'
            g['warnings'].append(
                f'key undetermined (correlation {k["correlation"]:.2f}) — best '
                f'guess {k["tonic"]} {k["mode"]}, planned {plan["key"]["tonic"]} '
                f'{want_mode}'
            )
        elif k['tonic_pc'] == want_pc and k['mode'] == want_mode:
            g['checks']['key_match'] = 'exact'
        elif k['tonic_pc'] == rel_pc:
            g['checks']['key_match'] = 'relative'
        elif k['tonic_pc'] in ((want_pc + 7) % 12, (want_pc + 5) % 12):
            g['checks']['key_match'] = 'fifth-related'
            g['warnings'].append(
                f'key reads a fifth away: {k["tonic"]} {k["mode"]} vs planned {plan["key"]["tonic"]} {want_mode}'
            )
        else:
            g['checks']['key_match'] = 'different'
            g['warnings'].append(f'key drifted: {k["tonic"]} {k["mode"]} vs planned {plan["key"]["tonic"]} {want_mode}')

    if want_clap:
        try:
            from zyg_workflows import audio_qc

            # The positives must describe the song the style asked for: a
            # lullaby measured against "a cheerful children's song" fails its
            # content gate for being what it was commissioned to be. Without a
            # style clap_captions returns the old hard-coded list unchanged.
            fam = _family_of(plan)
            pos = T.clap_captions(plan.get('style'), fam)
            # Family-aware too: 'horror drone' is a fail in a nursery rhyme and
            # an instrument in a Suspense cue, so the children's negatives would
            # fail a cinematic render for being what it was commissioned to be.
            neg = T.clap_negatives(fam)
            c = audio_qc.qc_clap(path, pos, neg, threshold=0.45, log_fn=log_fn)
            if isinstance(c, dict):
                # qc_clap returns positive_prob / effective_threshold / scores.
                # The old harvest asked for 'score', 'best_positive' and
                # 'best_negative' — none of which exist — so a bare boolean was
                # all that survived into the manifest and the panel had nothing
                # to draw.
                scores = c.get('scores') or {}
                best_pos = max(((t, v) for t, v in scores.items() if t in pos), key=lambda kv: kv[1], default=None)
                best_neg = max(((t, v) for t, v in scores.items() if t in neg), key=lambda kv: kv[1], default=None)
                g['checks']['clap'] = {
                    'ok': c.get('ok'),
                    # None is NOT False. ok is None when CLAP could not run at
                    # all, and the old `is False` test swallowed that silently:
                    # a check that never ran left no trace and read as a pass.
                    'ran': c.get('ok') is not None,
                    'reason': c.get('reason', ''),
                    'positive_prob': c.get('positive_prob'),
                    'threshold': c.get('effective_threshold'),
                    'coverage_s': c.get('coverage_s'),
                    'best_positive': list(best_pos) if best_pos else None,
                    'best_negative': list(best_neg) if best_neg else None,
                    'scores': scores,
                }
                if c.get('ok') is False:
                    bn = f'{best_neg[0]!r} at {best_neg[1]:.3f}' if best_neg else 'n/a'
                    bp = f'{best_pos[1]:.3f}' if best_pos else 'n/a'
                    g['warnings'].append(
                        'CLAP does not hear '
                        + ('an orchestral cue' if fam == 'cinematic' else "a children's song")
                        + f' (best positive {bp}, top negative {bn})'
                    )
                elif c.get('ok') is None:
                    g['warnings'].append(f'CLAP did not run — {c.get("reason") or "unknown"}')
        except Exception as e:  # noqa: BLE001 — soft gate, never fatal
            g['checks']['clap'] = {'ok': None, 'ran': False, 'reason': f'{type(e).__name__}: {e}'[:160]}
            g['warnings'].append(f'CLAP unavailable ({type(e).__name__})')

    g['ok'] = not g['fails']
    return g
