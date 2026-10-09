# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The SoundFont render — the score leg, and the melody ACE-Step is conditioned on.

Moved verbatim out of the old single-file kids_music_service.py (lines 489-619).
"""

from __future__ import annotations

import os

from zyg_workflows.kids_music_service.base import (
    SOUNDFONT,
    SR,
    _log_noop,
    _zyg_log,
)

# ── SoundFont render ─────────────────────────────────────────────────────────


def render_soundfont(midi_path, wav_path, *, gain=0.9, tail_s=2.5, log_fn=None):
    """Render a MIDI file offline through libfluidsynth + the MIT SoundFont.

    Offline (get_samples in the gaps between events) rather than through an audio
    device: there is no sound card in play, the result must be bit-reproducible,
    and a real-time driver would make the render take as long as the song.
    """
    import numpy as np
    import mido
    import fluidsynth
    import soundfile as sf

    log_fn = log_fn or _log_noop
    if not os.path.isfile(SOUNDFONT):
        log_fn(f'render: SoundFont missing at {SOUNDFONT}')
        return None

    mid = mido.MidiFile(midi_path)
    fs = fluidsynth.Synth(gain=gain, samplerate=float(SR))
    try:
        sfid = fs.sfload(SOUNDFONT)
        if sfid == -1:
            log_fn('render: sfload failed (sf3 support missing in libfluidsynth?)')
            return None
        # Channel 9 is GM percussion (bank 128) and carries no program_change,
        # so nothing in the event loop below would ever select a kit for it.
        try:
            fs.program_select(9, sfid, 128, 0)
        except Exception as _exc:  # noqa: BLE001 — kit-less soundfont
            _zyg_log.debug('drum-kit program select skipped (kit-less soundfont): %s', _exc)
        # Reverb makes a bare GM patch sound like a room rather than a ringtone.
        for k, v in (('synth.reverb.active', 1), ('synth.chorus.active', 0)):
            try:
                fs.setting(k, v)
            except Exception as _exc:  # noqa: BLE001 — older bindings
                _zyg_log.debug('fluidsynth setting %s not supported by this binding: %s', k, _exc)

        # Flatten to absolute-time events. mido's iteration over a MidiFile
        # already merges tracks and resolves tempo, so `msg.time` is seconds.
        events, t = [], 0.0
        for msg in mid:
            t += msg.time
            if msg.is_meta:
                continue
            events.append((t, msg))
        total = (events[-1][0] if events else 0.0) + tail_s

        chunks = []
        cursor = 0.0
        for when, msg in events:
            gap = when - cursor
            if gap > 0:
                n = int(round(gap * SR))
                if n > 0:
                    chunks.append(np.asarray(fs.get_samples(n), dtype=np.int16))
                    cursor += n / SR
            if msg.type == 'note_on' and msg.velocity > 0:
                fs.noteon(msg.channel, msg.note, msg.velocity)
            elif msg.type in ('note_off',) or (msg.type == 'note_on' and msg.velocity == 0):
                fs.noteoff(msg.channel, msg.note)
            elif msg.type == 'program_change':
                bank = 128 if msg.channel == 9 else 0
                fs.program_select(msg.channel, sfid, bank, msg.program)
            elif msg.type == 'control_change':
                fs.cc(msg.channel, msg.control, msg.value)
        n = int(round(max(0.0, total - cursor) * SR))
        if n > 0:
            chunks.append(np.asarray(fs.get_samples(n), dtype=np.int16))
    finally:
        try:
            fs.delete()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('fluidsynth teardown skipped: %s', _exc)

    if not chunks:
        log_fn('render: no audio produced')
        return None
    audio = np.concatenate(chunks).reshape(-1, 2)
    peak = int(np.abs(audio).max())
    if peak == 0:
        log_fn('render: silent output — every note was dropped')
        return None
    os.makedirs(os.path.dirname(wav_path) or '.', exist_ok=True)
    sf.write(wav_path, audio, SR, subtype='PCM_16')
    log_fn(f'render: {os.path.basename(wav_path)} {audio.shape[0] / SR:.1f}s peak={peak / 32768:.2f}')
    return wav_path


def lowered_lead_wav(midi_path, wav_path, semitones, *, log_fn=None):
    """The score render again, with ONLY the Melody track moved `semitones`.

    A conditioning source for a singer whose re-seeds alternate registers
    (kids_music_theory.SINGERS[*]['retry_lead_shift_st']): the tune a man would
    sing an octave down, with the chords, bass and drums where the band plays
    them. Transposed in the MIDI and rendered through the same SoundFont, not
    pitch-shifted as audio, so there are no stretcher artefacts in the latent
    and a -12 st glockenspiel is still a glockenspiel. Returns the wav path, or
    None — the caller then re-seeds on the plain score render.
    """
    log_fn = log_fn or _log_noop
    low_mid = os.path.splitext(wav_path)[0] + '.mid'
    try:
        import mido

        mid = mido.MidiFile(midi_path)
        moved = 0
        for tr in mid.tracks:
            if not any(m.type == 'track_name' and m.name == 'Melody' for m in tr):
                continue
            for m in tr:
                if m.type in ('note_on', 'note_off'):
                    m.note = max(0, min(127, m.note + int(semitones)))
                    moved += 1
        if not moved:
            log_fn('ace: no Melody track to lower — re-seeding on the score render')
            return None
        mid.save(low_mid)
        return render_soundfont(low_mid, wav_path, log_fn=log_fn)
    except Exception as e:  # noqa: BLE001 — a retry aid, never fatal
        log_fn(f'ace: could not lower the melody ({type(e).__name__}: {e})')
        return None
    finally:
        try:
            os.remove(low_mid)
        except OSError as _exc:
            _zyg_log.debug('lowered midi %s removal skipped: %s', low_mid, _exc)
