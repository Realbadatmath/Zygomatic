# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service_steps — Steps 4 and 5: the voice+sfx stem, the ambience bed, the scored music cues and the master."""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service_steps.stills import (
    _svc,
    np,
    os,
    shutil,
)
from zyg_workflows.storyteller_scene_service_steps.timeline import (
    _at_time,
)

# ── 4 ── voice+sfx stem ──────────────────────────────────────────────────────


def _step_stem(spec: dict, out_dir: str, log, tl: dict, audio_mix, sf) -> str:
    """Stage 4: sum every line and one-shot into the voice+sfx stem, then
    loudnorm it to the fixed reference the mix is authored against."""
    audio_end = tl['audio_end']
    n_total = int((audio_end + 1.0) * _svc()._SR)
    stem = np.zeros(n_total, dtype=np.float64)
    for ev in tl['events']:
        if ev['kind'] == 'line':
            d = _svc()._read_mono48k(ev['wav'])
            if ev.get('span'):  # anchored line: word only
                a_sp, b_sp = ev['span']
                d = d[a_sp:b_sp].copy()
                n_f = min(len(d) // 4, int(0.02 * _svc()._SR))
                if n_f > 0:  # the trim is a cut — don't click
                    d[:n_f] *= np.linspace(0.0, 1.0, n_f)
                    d[-n_f:] *= np.linspace(1.0, 0.0, n_f)
            if ev.get('gain_db'):
                d = d * (10.0 ** (float(ev['gain_db']) / 20.0))
        elif ev['kind'] == 'sfx':
            # dur_s on the event is the PLACED length (already divided by tempo
            # in the timeline), so the source slice has to be multiplied back up
            # or a stretched take would be cut short before it is stretched.
            _tempo = float(ev.get('tempo', 1.0))
            _src = _svc()._audio_asset(ev['sfx'])
            # pitch_semitones re-voices a stock one-shot INTO a character. The
            # library is one recordist, so a bought sigh arrives in his body,
            # not the character's — the sigh benched for Cornelis measures
            # F0 119.9 Hz against his 79.2. formant='shifted' drags the formants
            # with the pitch, which is what moves the apparent VOCAL TRACT and
            # therefore the apparent body; pitch alone would just sound detuned.
            # It is a plain resample (see _pitch_shift), NOT a neural voice
            # conversion — which also keeps this library's no-AI-training
            # licence clause satisfied: the audio never becomes model input.
            _semi = float(ev.get('pitch_semitones', 0.0))
            if abs(_semi) > 1e-3:
                _ps = os.path.join(out_dir, f'sfx_{ev["sfx"]}.pitched.wav')
                if _svc()._pitch_shift(_src, _ps, _semi, formant=ev.get('formant', 'shifted'), log_fn=log):
                    _src = _ps
            d = _svc()._sfx_cut(
                _src,
                float(ev.get('src_start_s', 0.0)),
                float(ev['dur_s']) * _tempo,
                gain_db=float(ev.get('gain_db', 0.0)),
                fade_s=float(ev.get('fade_s', 0.15)),
            )
            if abs(_tempo - 1.0) > 1e-3:
                # Reuse the LINE stretch rather than writing a second one: its
                # ffmpeg filter order is load-bearing (resample before atempo,
                # or short inputs hang the build — see _time_stretch).
                _a = os.path.join(out_dir, f'sfx_{ev["sfx"]}.raw.wav')
                _b = _a.replace('.raw.wav', '.stretched.wav')
                sf.write(_a, d, _svc()._SR)
                if _svc()._time_stretch(_a, _b, _tempo, log_fn=log):
                    d = _svc()._read_mono48k(_b)
        else:
            continue
        a = int(ev['t0'] * _svc()._SR)
        stem[a : a + len(d)] += d[: max(0, n_total - a)]
    peak = np.abs(stem).max()
    if peak > 0.98:
        stem *= 0.98 / peak
    stem_wav = os.path.join(out_dir, 'voice_sfx_stem.wav')
    sf.write(stem_wav, stem, _svc()._SR)
    # Loudnorm the stem to a FIXED reference before anything is mixed under it.
    # Two reasons, both learned the hard way on this scene:
    #  • Raw Chatterbox narration lands ~-22 LUFS with peaks at 0 dBFS. Asking
    #    the FINAL master for -14 then needs ~+9 dB of linear gain, which would
    #    breach the true-peak ceiling — so ffmpeg silently falls back to DYNAMIC
    #    normalisation, and dynamic AGC pulls the quiet passages back up. That
    #    is exactly the pumping that makes a "barely noticeable" bed audible
    #    again in the pauses.
    #  • It makes the authored bed/music LUFS numbers MEAN something: they are
    #    absolute levels against a known voice level, not against whatever this
    #    particular take happened to render at.
    # This is the chain abel_voice documents (stem -16 → bed ~20 LU under →
    # duck → master -14); the scene service was the one path skipping step one.
    stem_ref = float(spec.get('stem_lufs', -16.0))
    _svc()._level_to(stem_wav, stem_ref, stem_wav.replace('.wav', '_n.wav'), audio_mix, tp_db=-2.0, log_fn=log)
    return stem_wav


# ── 5 ── ambience bed + scored music cues ────────────────────────────────────


def _bed_track(spec: dict, out_dir: str, log, tl: dict, amb: np.ndarray, amb_len: int, audio_mix) -> float | None:
    """Lay the ambience bed into `amb` in place. Returns the hand-over instant
    (the time the bed is silent from) or None when there is no fade-out.

    Where the ambience bed hands over to the score. Two elements competing for
    the same "just under the voice" slot read as noise, not atmosphere, so the
    bed is ramped to SILENCE and ends just before the first cue enters — the
    gap between the two is a held breath, not a dropout."""
    bed_wav = os.path.join(out_dir, 'bed.wav')
    bed_layers = [
        {'path': _svc()._audio_asset(f), 'gain_db': g}
        for f, g in spec.get('bed', [('waves_hull_01.wav', 0.0), ('ship_creak_02.wav', -7.0)])
    ]
    bed_out_t = None
    bfo = spec.get('bed_fade_out')
    if bfo:
        bfo = {} if bfo is True else dict(bfo)
        anchor = bfo.get('at')
        if anchor is None:  # default: the earliest music cue
            cue_ins = [_at_time(c.get('t_in'), tl, 0.0) for c in (spec.get('music') or [])]
            anchor = min(cue_ins) if cue_ins else None
        if anchor is not None:
            bed_out_t = max(0.0, _at_time(anchor, tl) - float(bfo.get('lead_s', 0.0)))

    if audio_mix.prep_bed(bed_layers, tl['audio_end'], bed_wav, log_fn=log):
        bed_n = audio_mix.loudnorm_two_pass(
            bed_wav, bed_wav.replace('.wav', '_n.wav'), i=float(spec.get('bed_lufs', -42.0)), tp=-2.0, log_fn=log
        )
        bd = _svc()._read_mono48k(bed_n['out'] if bed_n else bed_wav).copy()
        bed_in_s = float(spec.get('bed_fade_in_s', 0.0))
        if bed_in_s > 0:
            # The water arrives rather than being switched on: a ramp from
            # silence over the head of the scene. Applied after loudnorm for
            # the same reason as the fade-out below — ramping first would let
            # the two-pass measurement average the quiet head in and push the
            # whole bed up to compensate.
            ni = min(len(bd), int(bed_in_s * _svc()._SR))
            if ni > 0:
                bd[:ni] *= np.linspace(0.0, 1.0, ni)
            log(f'[scene] ambience bed fades in 0.0→{bed_in_s:.1f}s')
        if bed_out_t is not None:
            # Ramp on the LEVELLED bed, after loudnorm — fading first would let
            # the two-pass measurement average the silence in and push the whole
            # bed back up to hit its target.
            i1 = min(len(bd), int(bed_out_t * _svc()._SR))
            i0 = max(0, i1 - int(float(bfo.get('fade_s', 2.5)) * _svc()._SR))
            if i1 > i0:
                bd[i0:i1] *= np.linspace(1.0, 0.0, i1 - i0)
            bd[i1:] = 0.0
            log(f'[scene] ambience bed fades out {i0 / _svc()._SR:.1f}→{bed_out_t:.1f}s (silent thereafter)')
        amb[: min(len(bd), amb_len)] += bd[:amb_len]
    return bed_out_t


def _music_cues(spec: dict, out_dir: str, log, tl: dict, amb: np.ndarray, amb_len: int, audio_mix) -> list[dict]:
    """Sum every scored cue into `amb` in place; returns the state-file log."""
    music_log: list[dict] = []
    for ci, cue in enumerate(spec.get('music') or []):
        src = _svc()._music_track(cue, out_dir, log_fn=log)
        if not src:
            log(f'[scene] WARN music cue {ci} unavailable — scene continues unscored')
            continue
        t_in, t_out = _at_time(cue.get('t_in'), tl, 0.0), _at_time(cue.get('t_out'), tl, tl['audio_end'])
        settle = cue.get('settle')
        seg = _svc()._music_segment(
            src,
            t_out - t_in,
            float(cue.get('lufs', -30.0)),
            float(cue.get('fade_in_s', 2.0)),
            float(cue.get('fade_out_s', 2.0)),
            os.path.join(out_dir, f'music_{ci}_{cue.get("name", "cue")}.wav'),
            audio_mix,
            start_s=float(cue.get('src_start_s', 0.0)),
            compress=bool(cue.get('compress', True)),
            settle=settle,
            log_fn=log,
        )
        if seg is None:
            continue
        a = int(t_in * _svc()._SR)
        amb[a : a + len(seg)] += seg[: max(0, amb_len - a)]
        entry = {
            'name': cue.get('name', f'cue{ci}'),
            't_in': round(t_in, 2),
            't_out': round(t_out, 2),
            'lufs': float(cue.get('lufs', -30.0)),
            'track': os.path.basename(src),
            # the source slice matters as much as the level — two builds
            # that differ only in src_start_s must be tellable apart from
            # their state files (found in review)
            'src_start_s': float(cue.get('src_start_s', 0.0)),
            'fade_in_s': float(cue.get('fade_in_s', 2.0)),
            'fade_out_s': float(cue.get('fade_out_s', 2.0)),
        }
        settle_note = ''
        if settle:
            # The settle in TIMELINE seconds, so a measurement window can be
            # read straight off the state — and the APPLIED window, mirroring
            # _music_segment's clipping: the ramp cannot run into the fade-out,
            # and a cue too short for fade-in + hold before its fade-out gets
            # no settle at all (the segment logs a WARN). Reporting the
            # authored numbers here would describe a shape that did not ship.
            s_db = float(settle.get('db', -12.0))
            s_a = t_in + float(cue.get('fade_in_s', 2.0)) + max(0.0, float(settle.get('hold_s', 0.0)))
            s_max = t_out - float(cue.get('fade_out_s', 2.0))
            applied = s_a < s_max
            s_b = min(s_max, s_a + max(0.0, float(settle.get('over_s', 1.0)))) if applied else s_a
            entry['settle'] = {
                'applied': applied,
                'from_s': round(s_a, 2),
                'to_s': round(s_b, 2),
                'db': s_db,
                'held_until_s': round(s_max, 2),
            }
            settle_note = (
                f', settles {s_db:+g} dB over {s_a:.1f}→{s_b:.1f}s and holds'
                if applied
                else ', settle SKIPPED (cue too short)'
            )
        music_log.append(entry)
        log(
            f"[scene] music '{cue.get('name', ci)}' {t_in:.1f}→{t_out:.1f}s "
            f'@ {cue.get("lufs", -30.0)} LUFS '
            f'(fade {cue.get("fade_in_s", 2.0)}s in / {cue.get("fade_out_s", 2.0)}s out'
            f'{settle_note})'
        )
    return music_log


def _step_master(spec: dict, out_dir: str, slug: str, log, tl: dict, stem_wav: str, audio_mix, sf) -> dict:
    """Stage 5: ambience bed + scored music cues, ducked under the stem and
    levelled into the delivered master.

    Bed and music are levelled SEPARATELY and summed into one ambience track,
    because they answer to different notes: the bed must sit far enough under
    the voice to be barely noticed, while a music cue has to be heard. Both
    then pass through the same sidechain duck, so both step back under a line
    and swell in the pauses.

    Levels are authored in LUFS against the UNNORMALISED voice stem, and the
    final master loudnorm scales everything together — so the authored
    music-to-voice and bed-to-voice distances are what actually ship."""
    audio_end = tl['audio_end']
    mix_wav = os.path.join(out_dir, 'mix.wav')
    master = os.path.join(out_dir, f'{slug}_master.wav')
    amb_len = int(audio_end * _svc()._SR)
    amb = np.zeros(amb_len, dtype=np.float64)
    stem_lufs = audio_mix.measure_lufs(stem_wav, log_fn=log)  # float LUFS
    log(f'[scene] voice stem measures {stem_lufs} LUFS (music/bed levels are authored against this)')

    bed_out_t = _bed_track(spec, out_dir, log, tl, amb, amb_len, audio_mix)
    music_log = _music_cues(spec, out_dir, log, tl, amb, amb_len, audio_mix)

    amb_wav = os.path.join(out_dir, 'ambience.wav')
    apk = np.abs(amb).max()
    if apk > 0.98:
        amb *= 0.98 / apk
    sf.write(amb_wav, amb, _svc()._SR)
    if not audio_mix.duck_mix(stem_wav, amb_wav, mix_wav, log_fn=log):
        shutil.copyfile(stem_wav, mix_wav)
    shutil.copyfile(mix_wav, master)
    _svc()._level_to(
        master,
        float(spec.get('master_lufs', -14.0)),
        os.path.join(out_dir, '_master_work.wav'),
        audio_mix,
        tp_db=-1.5,
        log_fn=log,
    )

    # End fade on the master. This is a GUARD that lands the file on digital
    # silence — the musical shape of the ending is the last cue's own fade_out_s
    # (authored against the 'audio_end' mark). Keep it short when a cue is
    # already fading: two linear ramps multiply into a much steeper one, which
    # takes the score out well before the picture goes.
    md = _svc()._read_mono48k(master)
    md = md[: int(audio_end * _svc()._SR)]
    nf = int(float(spec.get('master_fade_s', tl['end_fade'])) * _svc()._SR)
    if len(md) > nf > 0:
        md[-nf:] *= np.linspace(1.0, 0.0, nf)
    sf.write(master, md, _svc()._SR)
    return {'master': master, 'stem_lufs': stem_lufs, 'bed_out_t': bed_out_t, 'music_log': music_log}
