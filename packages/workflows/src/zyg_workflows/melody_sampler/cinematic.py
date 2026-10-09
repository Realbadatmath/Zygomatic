# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""melody_sampler.cinematic — the cinematic arrangement and the plan renderer.

Moved verbatim out of the 1,177-line melody_sampler.py; original lines 619-1024.
"""

from zyg_workflows.melody_sampler.constants import SR, VOICES, VOICE_TRANSPOSE, _log_noop, os

from zyg_workflows.melody_sampler.sample_index import index, voice_info

from zyg_workflows.melody_sampler.render_engine import (
    _PERC_DB,
    _ROLE_DB,
    _db,
    _plan_events,
    _read_stereo,
    render_events,
    voice_gain,
)

# ── The cinematic arrangement ────────────────────────────────────────────────
#
# A children's song is three parts played the same way from bar 1 to the end:
# tune, chord on every bar, bass on every strong beat. A cue is not. What makes
# sixty seconds of orchestra sound composed rather than looped is (a) a FOURTH
# line — a doubling, a counter-melody, an ostinato or an arpeggio — (b) a
# dynamic ARC, so the last section is the loudest and the first is held back,
# and (c) a pad that SWELLS: one chord held across every bar that shares it,
# crossfading into the next, instead of restriking on every downbeat.
#
# So `arrange_cinematic` is a second, parallel event builder to `_plan_events`.
# It deliberately does NOT share that function's ±6 ms micro-timing jitter: the
# jitter exists so the SoundFont and sampled renders of a children's song are
# the same performance, and a section string playing dead on the beat is what
# an orchestral cue actually sounds like. It is therefore fully deterministic
# with no RNG at all.

# Mix for the four cinematic layers, in dB. The extra layer sits under the pad
# because it is colour, not counterpoint you are meant to follow — except an
# ostinato, which repeats sixteen times a bar and has to be further down still
# or it becomes the piece.
_CIN_ROLE_DB = {'lead': 0.0, 'pad': -8.0, 'bass': -5.0, 'extra': -7.0}
_CIN_EXTRA_DB = {'ostinato': -10.0}

_CIN_ROLES = ('lead', 'pad', 'bass', 'extra')
_CIN_EXTRA_ROLES = ('double', 'counter', 'ostinato', 'arpeggio')

V_CIN_MEL_STRONG, V_CIN_MEL_WEAK = 108, 92
V_CIN_PAD_TOP, V_CIN_BASS, V_CIN_BASS_8TH = 62, 76, 70
V_CIN_COUNTER, V_CIN_OSTINATO, V_CIN_ARPEGGIO = 68, 60, 64

CIN_PAD_OVERLAP_S = 0.25  # the pad's crossfade into the next held chord
CIN_LEGATO_TAIL_S = 0.06  # the lead's overlap into its own next note
CIN_CHASE_BPM = 130  # at or above this the bass drives in eighths


def _vel(v):
    return int(max(1, min(127, round(v))))


def _cin_arc(section_idx, n_sec):
    """The dynamic arc: 0.78 at the first section, 1.00 at the last.

    Intro bars (section -1) take the opening level and the outro (-2) the
    closing one, so the curve is monotone across the whole piece and there is
    no step at either seam.
    """
    if n_sec <= 1:
        return 1.0
    if section_idx is None:
        k = 0
    elif section_idx == -2:
        k = n_sec - 1
    elif section_idx < 0:
        k = 0
    else:
        k = max(0, min(n_sec - 1, int(section_idx)))
    return 0.78 + 0.22 * (k / float(n_sec - 1))


def _cin_triad(chord):
    """(root_pc, third_interval, fifth_interval) for one plan chord.

    ``chord['midi']`` is already a close, often INVERTED voicing — the V of D
    major arrives as [49, 52, 57] (C#, E, A) — so the root cannot be read off
    the lowest note. ``chord['bass']`` is the root, and everything else is
    measured as an interval above its pitch class.
    """
    root_pc = int(chord['bass']) % 12
    third_iv = fifth_iv = None
    for m in chord.get('midi') or []:
        iv = (int(m) - root_pc) % 12
        if iv in (3, 4):
            third_iv = iv
        elif iv in (6, 7, 8):
            fifth_iv = iv
    if third_iv is None:
        third_iv = 3 if 'min' in str(chord.get('quality') or '') else 4
    if fifth_iv is None:
        fifth_iv = 6 if 'dim' in str(chord.get('quality') or '') else 7
    return root_pc, third_iv, fifth_iv


def _cin_chord_id(chord):
    """What counts as "the same chord" for the pad's merge."""
    return (chord.get('symbol'), chord.get('root_deg'), chord.get('quality'))


def _cin_pad_runs(chords):
    """Consecutive bars sharing a chord, merged into one held event.

    This is the swell. Returned as ``(first_chord, start_beat, beats, section)``.
    """
    runs = []
    for c in chords:
        cid = _cin_chord_id(c)
        if runs and runs[-1][0] == cid:
            runs[-1][2] += float(c.get('beats') or 0.0)
            continue
        runs.append([cid, c, float(c.get('beats') or 0.0), float(c['t']), c.get('section')])
    return [(r[1], r[3], r[2], r[4]) for r in runs]


def _cin_octave_near(pitch_class, centre):
    """The placement of `pitch_class` closest to `centre`."""
    base = centre - (centre % 12) + (int(pitch_class) % 12)
    return min((base - 12, base, base + 12), key=lambda m: (abs(m - centre), m))


def arrange_cinematic(plan):
    """A cinematic plan as four event lists: lead, pad, bass, extra.

    Events are ``(start_s, dur_s, midi, velocity)``, the tuple
    ``render_events`` consumes. ``plan['extra']`` — ``{'voice': key, 'role':
    double|counter|ostinato|arpeggio}`` — decides the fourth line; without it
    the 'extra' list is empty and the piece is an ordinary trio.
    """
    spb = 60.0 / float(plan['bpm'])
    bar_beats = float(plan['bar_beats'])
    chords = list(plan.get('chords') or [])
    n_sec = max(1, len(plan.get('sections') or plan.get('order') or [1]))
    body = [c for c in chords if (c.get('section') or 0) >= 0]

    def arc(idx):
        return _cin_arc(idx, n_sec)

    # ── LEAD: the tune, legato, riding the arc ───────────────────────────────
    mel = sorted(plan.get('melody') or [], key=lambda n: (n['t'], n['p']))
    lead = []
    for i, n in enumerate(mel):
        gap = (mel[i + 1]['t'] - n['t']) if i + 1 < len(mel) else float(n['d'])
        dur_s = max(0.05, min(float(n['d']), gap)) * spb + CIN_LEGATO_TAIL_S
        base = V_CIN_MEL_STRONG if n.get('strong') else V_CIN_MEL_WEAK
        lead.append((float(n['t']) * spb, dur_s, int(n['p']), _vel(base * arc(n.get('section')))))

    # ── PAD: held, wide, crossfaded ──────────────────────────────────────────
    pad = []
    for chord, t0, beats, sec in _cin_pad_runs(chords):
        root_pc, third_iv, fifth_iv = _cin_triad(chord)
        lo = min(int(m) for m in chord['midi'])
        root = lo + ((root_pc - lo) % 12)
        # (root, fifth, third+12): the third on top and an empty tenth below it
        # is the spread every string section is voiced in, and it is what makes
        # the same three pitch classes sound like an orchestra instead of a
        # guitar chord.
        voicing = (root, root + fifth_iv, root + third_iv + 12)
        sc = arc(sec)
        dur_s = beats * spb + CIN_PAD_OVERLAP_S
        for k, m in enumerate(voicing):
            pad.append((float(t0) * spb, dur_s, int(m), _vel((V_CIN_PAD_TOP - 4 * k) * sc)))

    # ── BASS: one root per bar, or eighths when the cue is a chase ───────────
    # The outro is the pad alone, so the bass stops with the last section.
    bass = []
    driving = float(plan['bpm']) >= CIN_CHASE_BPM
    for c in chords:
        sec = c.get('section')
        if sec is not None and sec == -2:
            continue
        beats = float(c.get('beats') or bar_beats)
        sc = arc(sec)
        if driving:
            n8 = max(1, int(round(beats / 0.5)))
            for i in range(n8):
                bass.append(
                    ((float(c['t']) + i * 0.5) * spb, 0.5 * spb * 0.9, int(c['bass']), _vel(V_CIN_BASS_8TH * sc))
                )
        else:
            bass.append((float(c['t']) * spb, beats * spb * 0.96, int(c['bass']), _vel(V_CIN_BASS * sc)))

    return {'lead': lead, 'pad': pad, 'bass': bass, 'extra': _cin_extra(plan, body, spb, bar_beats, arc)}


def _cin_extra(plan, body, spb, bar_beats, arc):
    """The fourth layer. Empty unless ``plan['extra']`` names a role."""
    from zyg_workflows import kids_music_theory as T

    spec = plan.get('extra') or {}
    role = str(spec.get('role') or '').strip().lower()
    voice = spec.get('voice')
    if role not in _CIN_EXTRA_ROLES or not body:
        return []
    info = voice_info(voice) if voice in VOICES else {'midi_lo': None, 'midi_hi': None}
    lo_v, hi_v = info.get('midi_lo'), info.get('midi_hi')
    centre = ((lo_v + hi_v) // 2) if (lo_v is not None and hi_v is not None) else 60

    out = []

    if role == 'double':
        mel = sorted(plan.get('melody') or [], key=lambda n: (n['t'], n['p']))
        if not mel:
            return []
        delta = -12
        lo_p = min(int(n['p']) for n in mel)
        hi_p = max(int(n['p']) for n in mel)
        # -12 is the default because a doubling below the tune thickens it; a
        # glockenspiel or a piccolo simply cannot go there, and for those the
        # doubling goes up instead.
        if lo_v is not None and lo_p - 12 < lo_v:
            if hi_v is None or hi_p + 12 <= hi_v:
                delta = 12
        for i, n in enumerate(mel):
            gap = (mel[i + 1]['t'] - n['t']) if i + 1 < len(mel) else float(n['d'])
            dur_s = max(0.05, min(float(n['d']), gap)) * spb + CIN_LEGATO_TAIL_S
            base = V_CIN_MEL_STRONG if n.get('strong') else V_CIN_MEL_WEAK
            out.append((float(n['t']) * spb, dur_s, int(n['p']) + delta, _vel(base * arc(n.get('section')) * 0.7)))
        return out

    if role == 'counter':
        offsets = list(T.METERS[plan['meter']]['strong'])
        marks = []
        for c in body:
            beats = float(c.get('beats') or bar_beats)
            for off in offsets:
                if off < beats:
                    marks.append((float(c['t']) + off, c))
        marks.sort(key=lambda x: x[0])
        prev = centre
        for i, (t, c) in enumerate(marks):
            root_pc, third_iv, fifth_iv = _cin_triad(c)
            cands = [_cin_octave_near(root_pc + iv, prev) for iv in (0, third_iv, fifth_iv)]
            # Nearest chord tone to where the line already is: that is what
            # makes a counter-line move by step rather than leap about.
            note = min(cands, key=lambda m: (abs(m - prev), m))
            nxt = marks[i + 1][0] if i + 1 < len(marks) else t + (float(c.get('beats') or bar_beats))
            out.append((t * spb, max(0.2, (nxt - t)) * spb, int(note), _vel(V_CIN_COUNTER * arc(c.get('section')))))
            prev = note
        return out

    if role == 'ostinato':
        for c in body:
            root_pc, third_iv, fifth_iv = _cin_triad(c)
            root = int(c['bass']) + 12
            cycle = (root, root + third_iv, root + fifth_iv, root + third_iv)
            beats = float(c.get('beats') or bar_beats)
            n8 = max(1, int(round(beats / 0.5)))
            sc = arc(c.get('section'))
            for i in range(n8):
                out.append(
                    ((float(c['t']) + i * 0.5) * spb, 0.5 * spb * 0.9, int(cycle[i % 4]), _vel(V_CIN_OSTINATO * sc))
                )
        return out

    # arpeggio: one broken chord a bar, root-fifth-third-octave
    for c in body:
        root_pc, third_iv, fifth_iv = _cin_triad(c)
        root = int(c['bass']) + 12
        notes = (root, root + fifth_iv, root + third_iv + 12, root + 12)
        beats = float(c.get('beats') or bar_beats)
        step = 1.0 if beats >= 4.0 else beats / 4.0
        sc = arc(c.get('section'))
        for i, m in enumerate(notes):
            out.append(((float(c['t']) + i * step) * spb, step * spb * 1.4, int(m), _vel(V_CIN_ARPEGGIO * sc)))
    return out


def _is_cinematic(plan):
    return str((plan or {}).get('family') or '') == 'cinematic'


def _role_events(plan):
    return arrange_cinematic(plan) if _is_cinematic(plan) else _plan_events(plan)


def _role_db(plan, role):
    if not _is_cinematic(plan):
        return _ROLE_DB[role]
    if role == 'extra':
        er = str(((plan.get('extra') or {}).get('role') or '')).lower()
        return _CIN_EXTRA_DB.get(er, _CIN_ROLE_DB['extra'])
    return _CIN_ROLE_DB[role]


def render_role(plan, role, voice, *, sr=SR):
    """One role of a plan, rendered alone, at the gain it gets in the mix.

    The measurement leg for ``kids_music_service.mix_balance``: the SoundFont
    path measures melody-against-bass by re-rendering two stripped MIDI files,
    and the sampled path needs the same two numbers from the same events. The
    role gain from ``_ROLE_DB`` is applied here precisely because the margin is
    a claim about the SHIPPED balance, not about the raw stems.

    Returns ``(audio, stats)`` in the shape ``render_events`` returns. On a
    cinematic plan the events are the arrangement's, and 'extra' is a role.
    """
    by_role = _role_events(plan)
    if role not in by_role:
        raise KeyError(f'unknown role {role!r}')
    audio, stats = render_events(
        by_role[role],
        voice,
        sr=sr,
        transpose=VOICE_TRANSPOSE.get(voice, 0),
        gain=voice_gain(voice),
        release_s=(CIN_PAD_OVERLAP_S if role == 'pad' and _is_cinematic(plan) else 0.08),
    )
    return audio * _db(_role_db(plan, role)), stats


def render_plan(plan, out_wav, *, voices, log_fn=None, perc_wav=None):
    """Render a composed plan to a 48 kHz stereo wav with sampled instruments.

    `voices` is ``{'lead': key, 'pad': key, 'bass': key}`` — plus ``'extra'``
    for a cinematic plan, which may also be taken from ``plan['extra']['voice']``.
    Returns the manifest the workflow records: which voices, which actual files,
    how many notes had to be octave-folded, the peak and the duration.
    """
    import numpy as np
    import soundfile as sf

    log = log_fn or _log_noop
    result = {
        'ok': False,
        'path': None,
        'voices': {},
        'files': {},
        'out_of_range_notes': 0,
        'peak': 0.0,
        'seconds': 0.0,
        'layers': {},
    }

    cinematic = _is_cinematic(plan)
    events = _role_events(plan)
    roles = ['lead', 'pad', 'bass']
    picked = dict(voices or {})
    if cinematic and events.get('extra'):
        if not picked.get('extra'):
            picked['extra'] = (plan.get('extra') or {}).get('voice')
        roles.append('extra')

    idx = index(log_fn=log)
    for role in roles:
        key = picked.get(role)
        if key not in VOICES:
            log(f'melody_sampler: role {role} has unknown voice {key!r}')
            return result
        info = voice_info(key)
        result['voices'][role] = info
        result['layers'][role] = key
        if not idx.get(key):
            log(f'melody_sampler: voice {key!r} ({role}) resolved to 0 samples')
            return result

    stems = {}
    for role in roles:
        key = picked[role]
        audio, stats = render_events(
            events[role],
            key,
            transpose=VOICE_TRANSPOSE.get(key, 0),
            gain=voice_gain(key),
            release_s=(CIN_PAD_OVERLAP_S if role == 'pad' and cinematic else 0.08),
        )
        stems[role] = audio
        result['files'][role] = sorted(stats['files'])
        result['out_of_range_notes'] += stats['shifted_octave']
        log(
            f'melody_sampler: {role}={key} {stats["notes"]} notes, '
            f'{len(stats["files"])} samples, max shift '
            f'{stats["max_shift_used"]} st, {stats["shifted_octave"]} folded'
        )

    n = max(a.shape[0] for a in stems.values())
    mix = np.zeros((n, 2), dtype='float32')
    for role, audio in stems.items():
        mix[: audio.shape[0]] += audio * _db(_role_db(plan, role))

    # A cue is scored, not drummed: the percussion stem the children's path
    # mixes in is ignored outright for the cinematic family.
    if cinematic and perc_wav:
        log('melody_sampler: cinematic family — percussion stem ignored')
        perc_wav = None

    if perc_wav and os.path.isfile(perc_wav):
        perc = _read_stereo(perc_wav, SR) * _db(_PERC_DB)
        if perc.shape[0] > n:
            perc = perc[:n]
        mix[: perc.shape[0]] += perc
        log(f'melody_sampler: mixed percussion {os.path.basename(perc_wav)}')

    raw_peak = float(np.abs(mix).max())
    result['peak_raw'] = raw_peak
    result['normalised'] = False
    if raw_peak > 0.98:
        mix *= 0.95 / raw_peak
        result['normalised'] = True
    peak = float(np.abs(mix).max())

    os.makedirs(os.path.dirname(out_wav) or '.', exist_ok=True)
    sf.write(out_wav, mix, SR, subtype='PCM_16')

    result.update(
        {
            'ok': True,
            'path': out_wav,
            'peak': peak,
            'seconds': round(n / float(SR), 3),
            'packs': sorted({p for v in result['voices'].values() for p in v['packs']}),
        }
    )
    log(
        f'melody_sampler: wrote {os.path.basename(out_wav)} '
        f'{result["seconds"]:.1f}s peak={peak:.2f}' + (' (normalised)' if result['normalised'] else '')
    )
    return result
