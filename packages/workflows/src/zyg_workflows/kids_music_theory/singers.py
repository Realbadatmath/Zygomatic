# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""singers.py — Who sings the song: the measured singer vocabulary and GM lead gains.

Moved verbatim out of ``kids_music_theory.py`` (original lines 1099-1292).
"""

from __future__ import annotations


# Who SINGS the song.  The songs are for children; the singer is an adult.
#
# This is a measured vocabulary, not a wish-list. ACE-Step's caption is the only
# steering lever the model has, and on 2026-08-29 it was measured with three
# seeds per arm on demucs-separated vocal stems: the adult-male caption landed
# 164-261 Hz and the adult-female caption 295-391 Hz, non-overlapping 3 of 3.
# The children's-choir caption (300-424 Hz) was statistically indistinguishable
# from adult female and is therefore NOT offered — nor is a teen option, for
# three independent reasons recorded in the audit: the choir/female captions do
# not separate at n=3, voice_qc documents that it cannot separate teen male from
# adult female on F0+VTL, and the voice bank holds zero teen-female voices.
#
# `band` is the F0 window gate_singer_age holds the rendered vocal stem to,
# `measured` is the observed spread it was drawn from, `meter` names the
# instrument those numbers came off (they are NOT comparable between meters —
# see the overlap note below the table), and `age_class` is the voice_qc class
# name. Widen a band only from a distribution, never from one render:
# within-caption seed spread measured 88-124 Hz, which is why the gate re-seeds
# rather than trusting a single take.
SINGERS = {
    'adult_female': {
        'label': 'Adult female',
        'age_class': 'adult_female',
        'caption': 'clear adult female lead vocal, warm friendly grown-up woman singing',
        # RE-MEASURED 2026-09-06 with sung_pitch (RMVPE, fmax 1400 Hz) over all
        # 31 surviving Farmyard takes — the ten voice_sweep masters, the ten
        # untreated natural_voices takes, the ten register_sweep masters and the
        # shipped song: medians 309.0-492.4 Hz, median of medians 410.7. Rows in
        # data/runtime/kidsmusic_singer_calibration.json.
        #
        # The OLD band 295-440 was read off Praat at pitch_ceiling 550 Hz, which
        # censors every frame a sung take spends above it, so it recorded medians
        # 40-200 Hz LOW (husky_alto: 293.5 Praat vs 492.4 RMVPE) and the ceiling
        # did the narrowing, not the singer. Keeping it against the honest meter
        # would fail most of the catalogue and — worse — would keep encoding
        # SHRILLNESS as a pass criterion, because only the brightest takes ever
        # read inside it. 230-560 Hz (A#3-C#5) is wide enough for the lowered
        # tunes sung_window now asks for and for the belted top of the range;
        # brightness is judged on its own axis (sharpness/HF), not by this band.
        'band': (230.0, 560.0),
        'measured': (309.0, 492.4),
        'n': 31,
        'meter': 'rmvpe (sung_pitch)',
        # The operator's default female voice (2026-09-10): the female twin of
        # 'Warm Control' below — this caption at the SAME seed, which is exactly
        # the shipped Red Train master (job 1ba342d5cd75, a2a at denoise 0.45,
        # first attempt). See the adult_male entry for what a seed does and does
        # not carry to a new song.
        'voice': 'Warm Control (female)',
        'ace_seed': 1669026733,
        # D4-B4, median target <= G4 (67). The age band says what a CHILD can
        # reach; this says where the ADULT who actually sings it stays warm.
        # From Miller's passaggi (mezzo primo passaggio E4, contralto G#4-A4 —
        # so every female voice crosses its first break below A4) and Kuhn 1979
        # (98 % of untrained adults comfortable Bb3-G4, 84 % reach B4). A tune
        # living at A4-D5 forces a belt or a flip on every take; B4 is the top
        # that keeps the sing-along child in range without pushing the woman
        # into the C5-D5 gear change.
        'sung_window': (62, 71),
    },
    'adult_male': {
        'label': 'Adult male',
        'age_class': 'adult_male',
        # n=6: the audit's 164/230/261 plus 189, 223 and 281 measured
        # 2026-08-29. The 281 is why the upper edge is 285 and not 280 — the
        # first live male render missed a 280 ceiling by ONE hertz, which is the
        # audit's own "calibrate before you make it a hard fail" arriving on
        # schedule. The male arm is the thinner of the two; treat 285 as
        # provisional until the 20-render sweep runs.
        'caption': 'clear adult male lead vocal, warm friendly grown-up man singing',
        'band': (110.0, 285.0),
        'measured': (164.0, 281.0),
        'n': 6,
        'meter': 'praat (uncalibrated, n=6)',
        # 'Warm Control' — picked BY EAR by the operator on 2026-09-10 from the
        # ten Red Train male takes (bench redtrain_male, rt_m01_warm_control):
        # this stock caption at the seed the shipped female master drew. An
        # ACE-Step voice is (caption, seed) and nothing else, so this pair IS
        # the voice. What it is not is a timbre lock: the seed reproduces that
        # take exactly only on that song — on new lyrics, tags or length the
        # same seed is a fresh draw of the same recipe. run() starts the
        # singer-gate re-seed loop here (ace_seed, +1, +2 ...) instead of at a
        # random seed, so every sung song opens on this voice.
        'voice': 'Warm Control',
        'ace_seed': 1669026733,
        # WHAT HAPPENS WHEN WARM CONTROL SINGS HIGH (2026-09-14). The register
        # is drawn by ACE-Step's LM from the TEXT, so new lyrics are a new coin
        # flip whatever the seed: the bumblebee song sang 372/331/415 Hz on
        # seeds +0/+1/+2 and shipped instrumental. Bench
        # tools/kidsmusic_male_octave_bench.py, 12 songs, first take on this
        # seed: score conditioning male 6/12; the Melody track -12 st male
        # 8/12 — but NEITHER is a first-take fix, because the failures belong
        # to the song: -12 st turns bee and marching male on every seed and
        # dinosaur and frog high on every seed. So the re-seed loop ALTERNATES
        # the two — take 1 is exactly Warm Control, take 2 the same seed on a
        # melody an octave down, then seed +1 both ways ... — which on the
        # measured takes ships male on 10/12 songs within 3 takes and 11/12
        # within 6 (score-only: 9/12 within 3). LM temperature 0.5/0.3 and
        # cover mode were measured too and lost (cover mostly sang nothing).
        # ZYG_KIDSMUSIC_SINGER_RETRIES still overrides the budget.
        'retry_lead_shift_st': -12,
        'singer_retries': 6,
        # PER-LINE register ceiling for the voice review (vocal_analysis.problems).
        # 2026-09-15, calibrated takes: lines of takes that passed as male sit at
        # median 218-219 Hz; lines of takes that sang the octave up at 367-373.
        # 300 sits between. A line is flagged when >= 50 % of its voiced time is
        # above it (vocal_analysis.LINE_HIGH_SHARE — the line median is unstable
        # on a line that jumps the octave half way). A take whose MEDIAN passed
        # can still sing whole lines up there — the band above never looked line
        # by line.
        'line_ceiling_hz': 300.0,
        # VOICE CONVERSION (2026-09-15, voice_conversion.py). The shipped take's
        # vocal is converted to one trained Warm Control voice with Applio RVC,
        # because the seed above is not a timbre lock. Bench tools/vc_bench.py,
        # 8 held-out songs, criteria fixed first: melody 5.4 c, lyrics -1 line
        # worst, voice moved toward Warm Control on 7/8 → PASS. The weights file
        # is PINNED so a retrain cannot change the voice that ships; every song
        # is re-checked (voice_conversion.ship_check) and the unconverted master
        # is kept beside it for A/B. ZYG_KIDSMUSIC_VC=0 turns it off.
        'vc_model': 'warm_control_v2',
        'vc_weights': 'warm_control_v2_300e_9900s.pth',
        'vc_index_rate': 0.5,
        'vc_protect': 0.33,
        # None = unchanged behaviour, the whole age band. The male renders were
        # never the complaint, and ACE-Step does not follow the score's octave
        # anyway — it sings the male part where a male part goes. Narrowing a
        # window that nothing downstream obeys would only cost tune.
        'sung_window': None,
    },
}
# THE TWO BANDS NOW OVERLAP, 230-285 Hz, and that is a statement about the
# instruments and not about the voices. Until 2026-09-06 there was a deliberate
# 285-295 Hz gap — male topped out at 281, female bottomed out at 295 — and a
# render landing inside it failed rather than being guessed. Re-measuring the
# female arm with RMVPE moved its floor down to 230 while the male arm is still
# the Praat n=6 numbers from 2026-08-29, so the edges of the two bands are no
# longer read off the same meter and the "gap" they used to describe cannot be
# computed. Nothing is being claimed about 230-285 Hz: a take landing there now
# satisfies BOTH bands, so the gate can no longer separate the sexes down there.
# Restore a real gap by re-measuring the male arm with sung_pitch (20 renders,
# same procedure as tools/measure_kidsmusic_takes.py) — not by narrowing the
# female floor back up, which would only re-encode the censored meter.
# Male since 2026-09-10, on the operator's call: 'Warm Control' is the default
# voice; ask for adult_female to get its female twin.
DEFAULT_SINGER = 'adult_male'

# Everything the caption must NOT ask for. Second line of defence behind the
# positive caption and the gate: on the current graph the KSampler negative is
# inert (cfg 1.0 skips the uncond pass) and the LM's caption_negative is the slot
# that actually carries this.
SINGER_NEGATIVE = 'children singing, childrens choir, kids chorus, young child singer, toddler voice, boy soprano'

# How loud each GM lead patch actually RENDERS through the SoundFont.
#
# The whole corpus used exactly five velocities, byte-identical across every
# song, and nothing accounted for the fact that a music box at velocity 104 and
# a trumpet at velocity 104 are nowhere near the same loudness. Measured on the
# six shipped songs, the composed melody was the QUIETEST element in five of
# them — bass minus melody RMS of +8.7, +8.4, +7.9, +0.8 and +0.1 dB — and only
# the ocarina-lead song had the tune on top.
#
# Keyed on the lead's GM program: (melody_strong, melody_weak, bass, pad_top).
# Quiet mallet/box patches are pushed to the top of the velocity range and the
# bass is pulled down under them; patches that already cut through keep the
# original values. Verified by the render regression in kids_music_service,
# which asserts melody RMS >= bass + 4 dB for all seven moods.
# Bass velocities are MEASURED, not chosen. A first pass of plausible-looking
# numbers left four of seven moods still failing the melody >= bass + 4 dB gate,
# because velocity maps to loudness differently for every patch. Each row's bass
# value is the largest velocity that still holds a >= 6 dB margin, found by
# binary search over real fluidsynth renders (2026-08-29, 6 renders per patch,
# 40 s). 6 dB rather than 4 so seed variation cannot dip under the gate.
#
# Searched against the TODDLER band, not preschool. The toddler melody is the
# sparsest the composer writes, so it has the lowest melody RMS and is the worst
# case every patch has to clear — calibrating on preschool left toddler/happy at
# +3.3 dB, under the gate. Where a patch serves several moods (GM 10 is both
# `gentle` and `lullaby`) the lower value wins, because a table keyed on the
# patch has to hold for every mood that reaches it.
GM_LEAD_GAIN = {
    10: (127, 112, 33, 46),  # music box       — gentle, lullaby
    11: (124, 108, 51, 48),  # vibraphone      — curious
    12: (122, 106, 48, 50),  # marimba         — happy
    13: (124, 108, 31, 48),  # xylophone       — playful
    56: (104, 88, 45, 54),  # trumpet         — marching
    79: (108, 92, 70, 52),  # ocarina         — silly
}
# Anything not in the table keeps the original arrangement values.
GM_LEAD_GAIN_DEFAULT = (104, 88, 76, 54)


def lead_gain(program):
    """(melody_strong, melody_weak, bass, pad_top) velocities for a GM lead."""
    return GM_LEAD_GAIN.get(int(program), GM_LEAD_GAIN_DEFAULT)
