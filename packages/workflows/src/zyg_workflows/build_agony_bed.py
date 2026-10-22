# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_agony_bed.py — a crowd screaming in agony, built from the vocal_fx library.

Operator asked for "soundtrack with people screaming in agony, softly" under the
Cornelis Day 1 cut. Two routes were tried; only one works.

ACE-STEP CANNOT DO THIS, AND IT WAS MEASURED, NOT GUESSED. It is the scene's
music generator (MIT weights, licence-clean, already scoring this episode), so it
was the obvious first try. Three prompts, all explicitly asking for screams,
agony and "no melody" — CLAP (laion/clap-htsat-fused, the same zero-shot gate the
narration stack uses) scored every one of them highest on "a singing choir with
melody":
        candidate a   0.488 anguished cries / 0.354 singing choir   (best)
        candidate b   0.130 anguished cries / 0.756 singing choir
        candidate c   0.266 anguished cries / 0.719 singing choir
It is a MUSIC model: asked for screams it sings. That is a property of the
model, not of the prompt, so no amount of rewording fixes it.

SO THE CROWD IS BUILT, NOT GENERATED. The 344 Audio library holds ~20 real human
pain vocalisations — pained groans, strained grunts, sharp intakes of breath —
across both sexes. A crowd is what a sound designer makes from those: many
voices, each at a different pitch, each entering at a different instant, pushed
back with distance treatment. That is exactly what the licence permits ("You may
modify, edit, and combine the Sounds"), and it is pure DSP — resampling and
filtering — so the no-AI-training clause is never engaged. The derived bed
INHERITS the source restrictions: mix-only, no redistribution, no model input.

WHY PITCH SPREAD IS THE WHOLE TRICK. The library is one male and one female
recordist. Layering their takes unshifted gives two people overlapping, not a
crowd — the ear identifies a repeated timbre instantly. Each layer is resampled
to its own pitch (a resample moves formants WITH the pitch, so it changes the
apparent body, unlike a formant-preserving shift which would leave every voice
the same size). Upward shifts also turn a groan into something nearer a cry:
a scream sits above a groan in pitch, so the spread does double duty.

DISTANCE TREATMENT NEARLY DESTROYED IT, AND CLAP CAUGHT THAT TOO. The brief was
"softly, not loud" in a cabin below deck, so the obvious move was to put the
crowd behind the timber: lowpass at 2.6 kHz, generous reverb. Scored, that
version reads as ORCHESTRAL STRINGS almost as strongly as it reads as screaming
(0.453 anguished / 0.386 strings). Five treatments were swept against the same
CLAP prompts:

    highpass 140 · lowpass 2600 · big echo · dynaudnorm    0.480   <- "distant"
    highpass 140 · lowpass 4500 · medium echo              0.780
    highpass 160 · lowpass 6000 · light echo               0.877
    highpass 160 · lowpass 7000 · one short slap           0.963   <- SHIPPING
    highpass 160 · lowpass 8000 · no echo                  0.933

A scream lives in the 1-4 kHz band — that is the part that says "human voice in
distress" rather than "a swelling pad". Cutting at 2.6 kHz removes precisely the
evidence, and reverb smears the attacks that make it read as separate people
crying out. So the bed is kept OPEN and nearly dry, and "soft" is delivered where
it belongs: by the cue's level in the mix, not by mangling the source. Distance
that costs identity is not distance, it is mud.

    python3 build_agony_bed.py                 # build, CLAP-verify, register (9 s)
    python3 build_agony_bed.py --seconds 16    # a longer bed, as crowd_agony_16s.wav
    python3 build_agony_bed.py --check         # just re-score what is already built
"""

from __future__ import annotations

import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

SR = 48000
VOCAL_DIR = os.path.join(_HERE, 'data', 'asset_libraries', 'vocal_fx')
OUT_NAME = 'crowd_agony.wav'
DUR_S = 9.0  # the cue needs 5.5 s; the tail is slicing room

# LONGER BEDS ARE BUILT, NOT LOOPED (2026-08-25). The Cornelis intro now opens on
# the screams and holds them for ~14 s, and the 9 s asset carries only ~7.3 s of
# crowd before its slicing-room tail goes silent — so the scene service's loop
# would have crossfaded 1.5 s of SILENCE into the loud head of a second copy,
# i.e. the crowd vanishes for a moment and then restarts at its densest. Instead
# the entry list is laid down again as a second (third…) WAVE: same recordings,
# but each wave carries its own pitch offset and the odd waves run the list in
# reverse, so no voice comes back at the same pitch in the same order and the
# ear does not catch a repeat. Waves are spaced so the next one enters while the
# previous is thinning out — WAVE_S is a little under the ~7.3 s a wave lasts.
WAVE_S = 5.6
WAVE_SHIFT_ST = (0.0, +1.5, -1.0, +0.5)  # per-wave semitone offset (cycled)

# Curated by DESCRIPTOR, not by folder: 'Annoyed Groan' and 'Petulant Groan' are
# the wrong emotion entirely, retching is nausea, and the yawns are in the groan
# folders only because a yawn ends in one.
SOURCES = [
    # (file, base semitone shift, gain_db, start_s)  — hand-placed so the entries
    # stagger into a swell instead of landing as one hit.
    ('m_groans_pained_groan.wav', 0.0, -3.0, 0.00),
    ('f_groans_grunts_strained_grunt_1.wav', +2.0, -5.0, 0.35),
    ('m_groans_ahhh_groan.wav', -2.0, -4.0, 0.60),
    ('f_general_reactions_sharp_intake_of_breath_ah_pain_1.wav', +1.0, -6.0, 0.95),
    ('m_groans_hnnnng_groan.wav', +4.0, -6.0, 1.20),
    ('f_groans_grunts_strained_grunt_3.wav', +5.0, -7.0, 1.55),
    ('m_groans_groan.wav', -4.0, -5.0, 1.90),
    ('f_general_reactions_sharp_intake_of_breath_ah_pain_2.wav', +3.0, -7.0, 2.25),
    ('m_groans_strained_grunt.wav', +6.0, -6.0, 2.60),
    ('f_groans_grunts_strained_grunt_5.wav', +7.0, -8.0, 2.95),
    ('m_groans_pained_groan.wav', +2.5, -6.0, 3.30),
    ('f_groans_grunts_strained_grunt_2.wav', -1.0, -6.0, 3.70),
    ('m_groans_groan_2.wav', +5.0, -7.0, 4.05),
    ('f_general_reactions_sharp_intake_of_breath_pain.wav', +4.0, -7.0, 4.40),
    ('m_groans_ahhh_groan.wav', +7.0, -8.0, 4.75),
    ('f_groans_grunts_strained_grunt_4.wav', +1.5, -7.0, 5.10),
    ('m_groans_hnnnng_groan.wav', -3.0, -6.0, 5.45),
    ('m_groans_pained_groan.wav', +8.0, -9.0, 5.85),
    ('f_groans_grunts_strained_grunt_1.wav', +6.5, -9.0, 6.25),
    ('m_groans_groan.wav', +3.5, -8.0, 6.70),
]

LICENCE = {
    'source': '344 Audio Limited — Human Mouth Noises (DERIVED)',
    'license_id': 'royalty-free-verified',
    'commercial_ok': True,
    'attribution_required': False,
    'attribution': '',
    'purchased_from': 'Sonniss (1-user licence)',
    'purchase_date': '2026-08-21',
    'no_ai_training': True,
    'no_redistribute': True,
    'derived': True,
    # {layers}/{waves}/{seconds} are filled in at registration — the 16 s bed
    # is 55 layers in 3 waves, and a sidecar that said "20 layered" would
    # misdescribe the derived work it is the provenance of.
    'notes': (
        'Crowd-in-agony bed built by build_agony_bed.py from {layers} '
        'layered, pitch-spread pain vocalisations in the vocal_fx library '
        '({waves} wave(s), {seconds:.0f} s), with distance treatment. A '
        'DERIVED work: the 344 Audio EULA permits '
        'modify/edit/combine, and it carries the SAME restrictions as its '
        'sources — mix-only, never a model input, never redistributed. '
        'Built with ffmpeg DSP only (resample + filters); no model was '
        'involved, so the no-AI-training clause is not engaged.'
    ),
}


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _entries(dur_s: float):
    """The (file, semitones, gain_db, start_s) list for a bed of dur_s seconds:
    SOURCES once for the classic 9 s bed, and repeated as offset waves for a
    longer one (see WAVE_S). A wave that would start with under 1.5 s of bed
    left is not laid — it could only contribute a clipped entry or two."""
    out = []
    k = 0
    while True:
        t_wave = k * WAVE_S
        if k > 0 and t_wave > dur_s - 1.5:
            break
        # The SLOTS (entry time + gain) always run forward — that stagger is
        # the swell. Odd waves put the RECORDINGS through them in reverse, so
        # the second wave opens on the voice the first one closed with.
        voices = [(fn, semis) for fn, semis, _g, _t in SOURCES]
        slots = [(gain_db, t0) for _f, _s, gain_db, t0 in SOURCES]
        if k % 2:
            voices = list(reversed(voices))
        off = WAVE_SHIFT_ST[k % len(WAVE_SHIFT_ST)]
        for (fn, semis), (gain_db, t0) in zip(voices, slots):
            out.append((fn, semis + off, gain_db, t_wave + t0))
        k += 1
        if dur_s <= DUR_S:
            break
    return out, k


def build(out_wav: str, log=print, dur_s: float = DUR_S) -> str | None:
    import numpy as np
    import soundfile as sf

    work = os.path.join(_HERE, 'data', 'runtime', '_agony_work')
    os.makedirs(work, exist_ok=True)
    dur_s = float(dur_s)
    n_total = int(dur_s * SR)
    mix = np.zeros(n_total, dtype=np.float64)
    used = 0
    entries, n_waves = _entries(dur_s)
    for i, (fn, semis, gain_db, t0) in enumerate(entries):
        src = os.path.join(VOCAL_DIR, fn)
        if not os.path.isfile(src):
            log(f'  missing source, skipped: {fn}')
            continue
        # Resample-based shift: pitch AND formants together, so every layer is a
        # different-SIZED body.
        #
        # NOTE (2026-08-25, found in review): this chain does NOT put the
        # duration back, whatever the first version of this comment said.
        # asetrate by r plays the take r× faster; atempo=r then speeds it up
        # AGAIN, so a layer lands r² shorter (+8 st → 2.5× shorter, −4 st →
        # 1.6× longer). Restoring it would be atempo=1/r. It is left as it is
        # ON PURPOSE: the registered crowd_agony.wav and crowd_agony_16s.wav
        # were built through exactly this chain and CLAP-verified (0.963 /
        # 0.975) — the clipped, urgent high shifts are part of what reads as a
        # crowd — and "fixing" it would silently change an approved asset's
        # sound. Change it only together with a re-verify and a re-listen.
        r = 2.0 ** (float(semis) / 12.0)
        tmp = os.path.join(work, f'l{i:02d}.wav')
        # atempo only accepts 0.5-2.0 per stage; these shifts stay inside it.
        cmd = [
            'ffmpeg',
            '-loglevel',
            'error',
            '-y',
            '-i',
            src,
            '-af',
            f'aresample={SR},asetrate={int(SR * r)},aresample={SR},atempo={r:.6f}',
            '-ar',
            str(SR),
            '-ac',
            '1',
            '-c:a',
            'pcm_s16le',
            tmp,
        ]
        if _run(cmd).returncode != 0 or not os.path.isfile(tmp):
            log(f'  shift failed: {fn} {semis:+.1f}st')
            continue
        d, _sr = sf.read(tmp, dtype='float64')
        if d.ndim > 1:
            d = d.mean(axis=1)
        d = d * (10.0 ** (gain_db / 20.0))
        a = int(t0 * SR)
        if a >= n_total:
            continue
        seg = d[: n_total - a]
        # 20 ms edges — a cut into a vocalisation clicks
        e = min(len(seg) // 4, int(0.02 * SR))
        if e > 0:
            seg[:e] *= np.linspace(0.0, 1.0, e)
            seg[-e:] *= np.linspace(1.0, 0.0, e)
        mix[a : a + len(seg)] += seg
        used += 1
    if not used:
        log('no layers built')
        return None
    build.last = {'layers': used, 'waves': n_waves, 'seconds': dur_s}
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= 0.89 / peak
    raw = os.path.join(work, 'crowd_raw.wav')
    sf.write(raw, mix, SR)

    # DISTANCE. Through timber and across a space: drop the top so it is muffled,
    # keep it out of the voice's chest register, and let a room put it behind the
    # wall. aecho is a crude reverb, but crude is right here — a convolution tail
    # would need an IR that is itself a licensed asset.
    # Swept, not chosen — see the module docstring. One short slap for a hint of
    # room; the top stays open because that is where the screaming actually is.
    # No dynaudnorm: it flattens the entries into a single swell, which is what
    # made the first attempt read as strings.
    cmd = [
        'ffmpeg',
        '-loglevel',
        'error',
        '-y',
        '-i',
        raw,
        '-af',
        'highpass=f=160,lowpass=f=7000,aecho=0.9:0.7:29:0.15',
        '-ar',
        str(SR),
        '-ac',
        '1',
        '-c:a',
        'pcm_s16le',
        out_wav,
    ]
    if _run(cmd).returncode != 0 or not os.path.isfile(out_wav):
        log('distance chain failed')
        return None
    log(f'built {out_wav} from {used} layers ({dur_s:.0f}s, {n_waves} wave{"s" if n_waves != 1 else ""})')
    return out_wav


POS = [
    'people screaming in agony',
    'a crowd of humans screaming in pain',
    'anguished human cries and wailing',
    'human screams of suffering',
]
NEG = [
    'instrumental music',
    'a singing choir with melody',
    'silence or room tone',
    'ocean waves and wind',
    'orchestral strings',
]


def check(path: str, log=print) -> dict:
    """Does it actually read as a crowd in agony? CLAP, not opinion."""
    from zyg_workflows import audio_qc

    r = audio_qc.qc_clap(path, POS, NEG, log_fn=lambda m: None)
    log(f'CLAP positive_prob={r.get("positive_prob")} ok={r.get("ok")} {r.get("reason", "")}')
    for k, v in sorted((r.get('scores') or {}).items(), key=lambda kv: -kv[1])[:5]:
        log(f'   {v:.3f}  {k}')
    return r


def _out_name(dur_s: float) -> str:
    """crowd_agony.wav for the classic 9 s bed; crowd_agony_16s.wav etc. for a
    longer one. Separate names, so building a long bed for one scene never
    silently replaces the asset another cut was approved on."""
    return OUT_NAME if abs(dur_s - DUR_S) < 1e-6 else f'crowd_agony_{int(round(dur_s))}s.wav'


if __name__ == '__main__':  # the CLI lives in build_agony_bed_cli
    from zyg_workflows.build_agony_bed_cli import main as _cli_main

    raise SystemExit(_cli_main())
