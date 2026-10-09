# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LEFT bar, part 2 — dynamic, pitch & register, sampler, synthesis."""

from ._defs import _sec, _t


_sec(
    'dynamic',
    'Dynamic',
    'left',
    [
        _t(
            'dy_pp',
            'pp',
            'pianissimo layer',
            '<path d="M5 20V8h3a3 3 0 0 1 0 6H5"/><path d="M13 20V8h3a3 3 0 0 1 0 6h-3"/>',
        ),
        _t('dy_p', 'p', 'piano layer', '<path d="M9 21V7h3.5a3.5 3.5 0 0 1 0 7H9"/>'),
        _t('dy_mp', 'mp', 'mezzo-piano layer', '<path d="M3 18V9l3 4 3-4v9"/><path d="M13 21V9h3a3 3 0 0 1 0 6h-3"/>'),
        _t(
            'dy_mf',
            'mf',
            'mezzo-forte layer',
            '<path d="M3 18V9l3 4 3-4v9"/><path d="M13 21V11a3 3 0 0 1 3-3h2"/><path d="M12 14h5"/>',
        ),
        _t('dy_f', 'f', 'forte layer', '<path d="M8 21V8a4 4 0 0 1 4-4h2"/><path d="M6 13h8"/>'),
        _t(
            'dy_ff',
            'ff',
            'fortissimo layer',
            '<path d="M4 21V9a3.5 3.5 0 0 1 3.5-3.5H9"/><path d="M2 13h7"/><path d="M14 21V9a3.5 3.5 0 0 1 3.5-3.5H19"/><path d="M12 13h7"/>',
        ),
        _t(
            'dy_sfz',
            'sforzando',
            'the struck accent inside a quieter line',
            '<path d="M4 18l6-12v9l6-9v12"/><path d="M3 21h18"/>',
        ),
        _t(
            'dy_cresc',
            'Crescendo',
            'growing louder across the phrase',
            '<path d="M3 12h18"/><path d="M21 5L3 12l18 7"/>',
        ),
        _t('dy_dim', 'Diminuendo', 'falling away across the phrase', '<path d="M3 12h18"/><path d="M3 5l18 7L3 19"/>'),
        _t(
            'dy_layer',
            'Velocity layers',
            'how many sampled dynamics the note has',
            '<path d="M4 18h16M4 14h16M4 10h16M4 6h16" stroke-dasharray="0 0"/><path d="M4 18l16-12" stroke-dasharray="2 2"/>',
        ),
        _t(
            'dy_curve',
            'Velocity curve',
            'the map from played force to layer and level',
            '<path d="M4 20V4M4 20h16"/><path d="M4 20c8 0 10-14 16-14"/>',
        ),
        _t(
            'dy_xfade',
            'Layer crossfade',
            'blend between dynamic layers instead of switching',
            '<path d="M4 18L20 6"/><path d="M4 6l16 12"/><path d="M3 21h18"/>',
        ),
    ],
)

_sec(
    'register',
    'Pitch & register',
    'left',
    [
        _t(
            'pi_key',
            'Key',
            'the key the picked material is in',
            '<circle cx="8" cy="14" r="3.4"/><path d="M11.4 14V4l8 2"/><path d="M11.4 8l8 2"/>',
        ),
        _t(
            'pi_scale',
            'Scale',
            'major, minor, modal, pentatonic, whole tone, custom',
            '<path d="M4 20l3-3 3-3 3-3 3-3 4-4"/><path d="M4 20h16"/>',
        ),
        _t(
            'pi_root',
            'Root note',
            "the sample's own root pitch",
            '<circle cx="8" cy="16" r="3"/><path d="M11 16V5l8-2v11"/><circle cx="16" cy="14" r="3"/>',
        ),
        _t(
            'pi_range',
            'Key range',
            'the low and high notes this material covers',
            '<path d="M3 8h18v8H3z"/><path d="M7 8v8M17 8v8"/><path d="M3 8h4v5H3zM17 8h4v5h-4z" fill="currentColor" stroke="none" opacity=".35"/>',
        ),
        _t(
            'pi_oct_up',
            'Octave up',
            'shift the picked material an octave up',
            '<path d="M12 20V6"/><path d="M6 12l6-6 6 6"/><path d="M4 21h16"/>',
        ),
        _t(
            'pi_oct_dn',
            'Octave down',
            'shift the picked material an octave down',
            '<path d="M12 4v14"/><path d="M6 12l6 6 6-6"/><path d="M4 3h16"/>',
        ),
        _t(
            'pi_transp',
            'Transpose',
            'move by any number of semitones',
            '<path d="M4 16h6M14 8h6"/><path d="M8 12h8"/><path d="M14 5l3 3-3 3M10 13l-3 3 3 3"/>',
        ),
        _t(
            'pi_tune',
            'Fine tune',
            'cents off concert pitch',
            '<path d="M12 3v10"/><path d="M4 13a8 8 0 0 0 16 0"/><path d="M8 20h8"/>',
        ),
        _t(
            'pi_a440',
            'Reference A',
            'A=440, 432, 415 and other reference pitches',
            '<circle cx="12" cy="12" r="9"/><path d="M12 3v3M21 12h-3M12 21v-3M3 12h3"/><path d="M12 12l4-4"/>',
        ),
        _t(
            'pi_temper',
            'Temperament',
            'equal, just, meantone, well and historical tunings',
            '<path d="M3 18V6M8 18V8M13 18V7M18 18V9M21 18V6"/><path d="M2 21h20"/>',
        ),
        _t(
            'pi_micro',
            'Microtonal',
            'quarter tones and non-12 divisions',
            '<path d="M6 20V4"/><path d="M6 8h4M6 12h6M6 16h3"/><path d="M16 4v16" stroke-dasharray="2 2"/>',
        ),
        _t(
            'pi_detect',
            'Detect pitch',
            'read the pitch of the selected sound and label it',
            '<circle cx="10" cy="10" r="6"/><path d="M14.5 14.5L21 21"/><path d="M8 12V7l4-1v5"/>',
        ),
    ],
)

_sec(
    'sampler',
    'Sampler',
    'left',
    [
        _t(
            'sm_start',
            'Sample start',
            'where in the file the note begins',
            '<path d="M5 4v16"/><path d="M8 12h11"/><path d="M16 9l3 3-3 3"/>',
        ),
        _t(
            'sm_end',
            'Sample end',
            'where the note stops reading',
            '<path d="M19 4v16"/><path d="M5 12h11"/><path d="M13 9l3 3-3 3"/>',
        ),
        _t(
            'sm_loop',
            'Loop points',
            'the sustain loop inside the sample',
            '<path d="M7 8h10a3 3 0 0 1 0 6H7a3 3 0 0 1 0-6z"/><path d="M9 6v12M15 6v12" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sm_loopxf',
            'Loop crossfade',
            'smooth the seam at the loop join',
            '<path d="M3 16c5 0 5-8 9-8s5 8 9 8"/><path d="M12 4v16" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sm_rev',
            'Reverse',
            'play the sample backwards',
            '<path d="M20 12H6"/><path d="M11 7l-5 5 5 5"/><path d="M3 5v14"/>',
        ),
        _t(
            'sm_onepad',
            'One-shot',
            'ignore note-off — the sample always plays to the end',
            '<path d="M6 5l12 7-12 7z"/><path d="M20 5v14"/>',
        ),
        _t(
            'sm_slice',
            'Slice',
            'cut the sample at transients and map the pieces',
            '<path d="M3 18h18"/><path d="M5 18V8M11 18V5M17 18V10"/><path d="M4 3l3 3M10 2l3 3M16 5l3 3"/>',
        ),
        _t(
            'sm_chop',
            'Chop to grid',
            'slice on the beat instead of on the transient',
            '<path d="M3 5h18v14H3z"/><path d="M8 5v14M13 5v14M18 5v14" stroke-dasharray="3 2"/>',
        ),
        _t(
            'sm_stretch',
            'Time stretch',
            'change length without changing pitch',
            '<path d="M3 12h18"/><path d="M6 8l-3 4 3 4M18 8l3 4-3 4"/><path d="M9 7v10M15 7v10"/>',
        ),
        _t(
            'sm_warp',
            'Warp markers',
            'pin points in the sample to points on the grid',
            '<path d="M3 16c4-8 8 8 12 0s5-4 6-3"/><path d="M7 4v16M15 4v16" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sm_pitchsh',
            'Pitch shift',
            'change pitch without changing length',
            '<path d="M4 20V4"/><path d="M4 14c6 0 8-8 14-8"/><path d="M15 3l3 3-3 3"/>',
        ),
        _t(
            'sm_formant',
            'Formant',
            'move the formants independently of the pitch',
            '<path d="M3 20V8M8 20V4M13 20v-9M18 20V6M21 20v-5"/><path d="M2 14h20" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sm_mic',
            'Microphone mix',
            'close / overhead / room balance where the pack has them',
            '<rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M3 20h6M15 20h6"/>',
        ),
        _t(
            'sm_rrmode',
            'Round-robin mode',
            'cycle, random, random-no-repeat, velocity-locked',
            '<path d="M4 9h12a3 3 0 0 1 0 6H8"/><path d="M8 12l-4 3 4 3" transform="translate(0,-3)"/><circle cx="19" cy="6" r="1.5"/><circle cx="19" cy="18" r="1.5"/>',
        ),
        _t(
            'sm_poly',
            'Polyphony',
            'how many notes may sound at once, and what steals',
            '<path d="M4 18h4V6M10 18h4V9M16 18h4v-6"/><path d="M3 21h18"/>',
        ),
        _t(
            'sm_glide',
            'Glide',
            'portamento time between successive notes',
            '<path d="M4 18c4 0 6-12 16-12"/><circle cx="4" cy="18" r="1.5"/><circle cx="20" cy="6" r="1.5"/>',
        ),
        _t(
            'sm_legatomd',
            'Legato mode',
            'monophonic retrigger versus true legato transitions',
            '<circle cx="6" cy="14" r="2"/><circle cx="18" cy="14" r="2"/><path d="M6 10c4-5 8-5 12 0"/><path d="M8 14h8" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sm_resonate',
            'Sympathetic',
            'string resonance, pedal-down and body modelling',
            '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7" stroke-dasharray="3 3"/><path d="M12 1v3M12 20v3M1 12h3M20 12h3"/>',
        ),
        _t(
            'sm_keyswitch',
            'Key switch',
            'the notes that select articulation instead of sounding',
            '<path d="M3 9h18v8H3z"/><path d="M7 9v8M11 9v8M15 9v8"/><path d="M3 9h4v8H3z" fill="currentColor" stroke="none" opacity=".4"/><path d="M5 6l2-3 2 3"/>',
        ),
        _t(
            'sm_velcurve',
            'Velocity map',
            'how played force picks a layer and a level',
            '<path d="M4 20V4M4 20h16"/><path d="M4 20l7-8 9-6"/>',
        ),
    ],
)

_sec(
    'synth',
    'Synthesis',
    'left',
    [
        _t(
            'sy_osc',
            'Oscillator',
            'how many, and what each one is',
            '<path d="M3 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0"/><circle cx="12" cy="12" r="10" stroke-dasharray="3 3"/>',
        ),
        _t('sy_sine', 'Sine', 'the pure tone', '<path d="M3 12c3-8 6 8 9 0s6-8 9 0"/>'),
        _t('sy_saw', 'Saw', 'the bright buzzing wave', '<path d="M3 18l5-12v12l5-12v12l5-12v12"/>'),
        _t('sy_square', 'Square', 'the hollow wave, with pulse width', '<path d="M3 17V7h5v10h5V7h5v10h3"/>'),
        _t('sy_tri', 'Triangle', 'the soft-cornered wave', '<path d="M3 16l4-9 5 9 5-9 4 6"/>'),
        _t(
            'sy_noise',
            'Noise',
            'white, pink and brown noise sources',
            '<path d="M2 12l2-5 2 8 2-10 2 12 2-9 2 7 2-11 2 9 2-5 2 6"/>',
        ),
        _t(
            'sy_sub',
            'Sub oscillator',
            'the octave-down reinforcement',
            '<path d="M3 10c3-6 6 6 9 0s6-6 9 0"/><path d="M3 18c6-8 12 8 18 0"/>',
        ),
        _t(
            'sy_fm',
            'FM',
            'frequency modulation — operators and ratios',
            '<path d="M3 12c2-6 3 6 5 0s3 6 5 0"/><path d="M14 12c1-4 2 4 3 0s2 4 4 0"/><circle cx="13.5" cy="12" r="1"/>',
        ),
        _t(
            'sy_am',
            'AM / ring',
            'amplitude and ring modulation',
            '<path d="M3 12c3-9 6 9 9 0s6-9 9 0"/><path d="M3 12c3 9 6-9 9 0s6 9 9 0" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sy_wavetab',
            'Wavetable',
            'sweeping a position through a table of waves',
            '<path d="M3 18c3-4 6 4 9 0s6-4 9 0"/><path d="M3 13c3-4 6 4 9 0s6-4 9 0" opacity=".7"/><path d="M3 8c3-4 6 4 9 0s6-4 9 0" opacity=".45"/>',
        ),
        _t(
            'sy_additive',
            'Additive',
            'building the timbre from its partials',
            '<path d="M4 20V6M8 20v-9M12 20V9M16 20v-6M20 20v-4"/><path d="M3 21h18"/>',
        ),
        _t(
            'sy_granular',
            'Granular',
            'clouds of very short grains',
            '<circle cx="6" cy="8" r="1"/><circle cx="11" cy="6" r="1"/><circle cx="17" cy="9" r="1"/><circle cx="8" cy="14" r="1"/><circle cx="14" cy="13" r="1"/><circle cx="19" cy="16" r="1"/><circle cx="5" cy="18" r="1"/><circle cx="11" cy="19" r="1"/>',
        ),
        _t(
            'sy_physical',
            'Physical model',
            'strings, tubes, membranes and exciters',
            '<path d="M4 6v12"/><path d="M4 12h16"/><path d="M20 6v12"/><path d="M8 10c2 4 6-4 8 0" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sy_filter',
            'Filter',
            'low pass, high pass, band, notch, comb',
            '<path d="M3 8h9c3 0 3 10 6 10h3"/><path d="M3 18h18" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sy_cutoff',
            'Cutoff',
            'where the filter starts working',
            '<path d="M3 8h8c4 0 3 10 7 10"/><path d="M11 3v18" stroke-dasharray="3 2"/>',
        ),
        _t('sy_reso', 'Resonance', 'the peak at the cutoff', '<path d="M3 16h6l2-9 2 9h8"/>'),
        _t(
            'sy_env',
            'Envelope',
            'attack, decay, sustain, release',
            '<path d="M3 20L7 5l3 9h5l6 6"/><path d="M3 20h18"/>',
        ),
        _t(
            'sy_attack',
            'Attack',
            'how fast the note arrives',
            '<path d="M3 20L9 5v15"/><path d="M3 20h18"/><path d="M9 20h12" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sy_release2',
            'Release',
            'how long the note takes to disappear',
            '<path d="M3 5v9l6 6"/><path d="M3 20h18" stroke-dasharray="2 2"/><path d="M9 20h12"/>',
        ),
        _t(
            'sy_lfo',
            'LFO',
            'the slow modulator, and what it is aimed at',
            '<path d="M3 14c2-6 4-6 6 0s4 6 6 0"/><path d="M17 14h4"/><circle cx="21" cy="14" r="1.4"/>',
        ),
        _t(
            'sy_modmx',
            'Mod matrix',
            'every source routed to every destination',
            '<path d="M4 4h16v16H4z"/><path d="M4 9h16M4 14h16M9 4v16M14 4v16"/><circle cx="11.5" cy="11.5" r="1.2" fill="currentColor"/>',
        ),
        _t(
            'sy_unison',
            'Unison & detune',
            'stacked voices, spread apart',
            '<path d="M4 12h16" stroke-dasharray="2 2"/><path d="M4 8h16M4 16h16"/><path d="M18 6l2 2-2 2M18 14l2 2-2 2"/>',
        ),
        _t(
            'sy_arp',
            'Arpeggiator',
            'a held chord played as a pattern',
            '<path d="M4 18l4-4 4 4 4-8 4 4"/><circle cx="4" cy="18" r="1.2"/><circle cx="8" cy="14" r="1.2"/><circle cx="12" cy="18" r="1.2"/><circle cx="16" cy="10" r="1.2"/>',
        ),
        _t(
            'sy_voicemd',
            'Voice mode',
            'mono, legato, poly, paraphonic',
            '<circle cx="6" cy="12" r="2.4"/><circle cx="12" cy="12" r="2.4"/><circle cx="18" cy="12" r="2.4"/><path d="M8.4 12h1.2M14.4 12h1.2"/>',
        ),
    ],
)
