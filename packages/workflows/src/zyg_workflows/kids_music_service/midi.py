# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The MIDI stem: the composed plan written out as a playable file.

Moved verbatim out of the old single-file kids_music_service.py (lines 319-488).
"""

from __future__ import annotations

import os
from zyg_workflows import kids_music_theory as T

from zyg_workflows.kids_music_service.base import (
    TICKS_PER_BEAT,
    _log_noop,
)

# ── MIDI ─────────────────────────────────────────────────────────────────────


def write_midi(plan, path, log_fn=None):
    """Write the plan as a 4-track type-1 MIDI file (melody / chords / bass /
    percussion).  The MIDI is a deliverable in its own right — it is what a
    music teacher or an arranger would actually want out of this workflow."""
    import mido

    log_fn = log_fn or _log_noop
    bpm = plan['bpm']
    inst = plan['instruments']
    bar_beats = plan['bar_beats']
    mid = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)

    def _tick(beats):
        return int(round(beats * TICKS_PER_BEAT))

    # Track 0 — conductor: tempo, meter, key.
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(bpm), time=0))
    num = int(plan['ts'])
    den = 8 if plan['meter'] == '6/8' else 4
    meta.append(mido.MetaMessage('time_signature', numerator=num, denominator=den, time=0))
    meta.append(mido.MetaMessage('track_name', name=(plan['brief'].get('title') or "Children's song")[:60], time=0))
    mid.tracks.append(meta)

    def _track(name, channel, program, events):
        """events: list of (start_beats, dur_beats, note, velocity)."""
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage('track_name', name=name, time=0))
        if channel != 9:
            tr.append(mido.Message('program_change', channel=channel, program=int(program), time=0))
        # A note list must become an ordered on/off stream before deltas can be
        # computed; sorting by (time, is_off) keeps a note-off ahead of a
        # note-on at the same tick so repeated pitches retrigger cleanly.
        stream = []
        for st, du, note, vel in events:
            stream.append((_tick(st), 1, note, vel))
            stream.append((_tick(st + du), 0, note, 0))
        stream.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for tick, on, note, vel in stream:
            tr.append(
                mido.Message(
                    'note_on' if on else 'note_off',
                    channel=channel,
                    note=int(max(0, min(127, note))),
                    velocity=int(vel) if on else 0,
                    time=max(0, tick - last),
                )
            )
            last = tick
        mid.tracks.append(tr)

    # ── Velocities and dynamics ────────────────────────────────────────────
    #
    # The whole corpus used five fixed velocities, byte-identical across every
    # song, with no account of how loud each GM patch actually renders — which
    # is how the composed melody ended up the QUIETEST element in five of six
    # songs (bass minus melody RMS up to +8.7 dB). The table is keyed on the
    # lead's GM program; see kids_music_theory.GM_LEAD_GAIN.
    v_mel_strong, v_mel_weak, v_bass, v_pad_top = T.lead_gain(inst['lead'])

    n_sec = max(1, len(plan.get('order') or [1]))

    # Per-section shaping using the section index already on every note. A
    # children's song is not flat: it opens a little under, lifts into the
    # middle, and comes home. +-6% is enough to be felt and small enough that no
    # section drops out of the mix.
    def _sec_scale(idx):
        if idx is None or idx < 0:
            return 0.90  # intro / outro material
        return 0.94 + 0.12 * (idx / max(1, n_sec - 1)) if n_sec > 1 else 1.0

    # Deterministic micro-timing, seeded from the plan's own seed so a re-render
    # of the same plan is still bit-identical. Every event used to sit exactly on
    # the tick grid, which is what makes a MIDI render sound like a MIDI render.
    import random as _rnd

    _jit = _rnd.Random(int(plan.get('seed', 0)) ^ 0x5EED)
    _JIT_BEATS = (6.0 / 1000.0) * bpm / 60.0  # +-6 ms expressed in beats

    def _j(t, amount=1.0):
        return max(0.0, t + _jit.uniform(-_JIT_BEATS, _JIT_BEATS) * amount)

    # Melody — accented on strong beats so the metre is audible in the render.
    mel_events = []
    for n in plan['melody']:
        base = v_mel_strong if n['strong'] else v_mel_weak
        v = int(max(1, min(127, round(base * _sec_scale(n.get('section'))))))
        mel_events.append((_j(n['t']), max(0.12, n['d'] * 0.92), n['p'], v))
    _track('Melody', 0, inst['lead'], mel_events)

    # Chords — one soft sustained triad per bar.
    ch_events = []
    for c in plan['chords']:
        sc = _sec_scale(c.get('section'))
        for k, m in enumerate(c['midi']):
            v = int(max(1, min(127, round((v_pad_top - k * 4) * sc))))
            ch_events.append((_j(c['t'], 0.5), bar_beats * 0.96, m, v))
    _track('Chords', 1, inst['pad'], ch_events)

    # Bass — root on every strong position of the bar; that is the pulse a child
    # marches to, and it is also what keeps the harmony legible under the tune.
    bass_events = []
    for c in plan['chords']:
        sc = _sec_scale(c.get('section'))
        for st in T.METERS[plan['meter']]['strong']:
            v = int(max(1, min(127, round(v_bass * sc))))
            bass_events.append((_j(c['t'] + st, 0.5), min(bar_beats, 1.4), c['bass'], v))
    _track('Bass', 2, inst['bass'], bass_events)

    if plan.get('percussion'):
        perc = []
        n_bars = plan['bars']
        body_lo, body_hi = plan['intro_bars'], n_bars - plan['outro_bars']
        # Which bar each section starts on, so a fill can mark the seam. The
        # arrangement had no intro build, no fill and no ending gesture: one
        # percussion pattern was regenerated bit-identically in every bar, and
        # rendered stems matched to four decimal places across different songs.
        sec_starts = {sec['bar_start'] for sec in plan.get('sections') or []}
        for b in range(body_lo, n_bars):
            t0 = b * bar_beats
            # Intro ramp and outro taper. The first body bar enters under, the
            # outro bars fall away, so the song starts and stops rather than
            # being switched on and off.
            if b < body_lo + 1:
                amp = 0.72
            elif b >= body_hi:
                amp = max(0.35, 0.85 - 0.25 * (b - body_hi + 1))
            else:
                amp = 1.0

            def _v(x, amp=amp):
                return int(max(1, min(127, round(x * amp))))

            # 37 = side stick, 39 = hand clap, 82 = shaker: a nursery kit, not a
            # drum kit. The clap lands on the backbeat only in simple metres —
            # 6/8 gets the shaker pulse instead, because a backbeat in compound
            # time is a different genre entirely.
            step = 0.5 if plan['meter'] == '6/8' else 1.0
            k = 0
            t = 0.0
            while t < bar_beats - 1e-6:
                perc.append((_j(t0 + t, 0.6), 0.2, 82, _v(52 if k else 68)))
                t += step
                k += 1
            if plan['meter'] in ('4/4', '2/4'):
                for st in [1.0, 3.0] if plan['meter'] == '4/4' else [1.0]:
                    perc.append((_j(t0 + st, 0.6), 0.2, 39, _v(80)))
            perc.append((_j(t0, 0.4), 0.2, 37, _v(86)))

            # One-bar fill going INTO a new section: shaker sixteenths across the
            # last beat, so the seam is heard rather than merely being there.
            if (b + 1) in sec_starts and b + 1 < body_hi:
                for f in range(4):
                    perc.append((_j(t0 + bar_beats - 1.0 + f * 0.25, 0.4), 0.12, 82, _v(58 + f * 8)))
        # Ending gesture: one side stick on the first outro downbeat, and nothing
        # after it.
        if body_hi < n_bars:
            perc.append((body_hi * bar_beats, 0.3, 37, 70))
        _track('Percussion', 9, 0, perc)

    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    mid.save(path)
    log_fn(f'midi: wrote {os.path.basename(path)} ({len(mid.tracks)} tracks, {len(plan["melody"])} melody notes)')
    return path
