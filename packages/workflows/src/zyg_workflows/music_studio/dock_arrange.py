# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DOCK bar, part 1 — arrange, time & groove, compose."""

from ._defs import _sec, _t


# ══ DOCK — what is DONE to it ══════════════════════════════════════════════
# The live EFFECT families are deliberately absent: `sfx_fx.py` already owns
# reverb, delay, chorus, EQ, compression, pitch, width and the rest, and the
# page folds them into this dock from the merger spec.  Listing `reverb` here
# too would put one option in two bars with two pictures — the duplicate this
# whole registry is arranged to avoid.

_sec(
    'arrange',
    'Arrange',
    'dock',
    [
        _t(
            'ar_grid',
            'Grid',
            'the bar/beat grid the board snaps to',
            '<path d="M3 3h18v18H3z"/><path d="M9 3v18M15 3v18M3 9h18M3 15h18"/>',
        ),
        _t(
            'ar_snap',
            'Snap',
            'snap on or off, and to what division',
            '<path d="M4 4v16"/><path d="M8 12h12"/><path d="M8 8v8" stroke-dasharray="2 2"/><path d="M17 9l3 3-3 3"/>',
        ),
        _t(
            'ar_bars',
            'Bars & beats',
            'read the ruler in bars and beats, not seconds',
            '<path d="M3 6h18"/><path d="M7 6v12M11 6v9M15 6v12M19 6v9"/><path d="M3 6v12"/>',
        ),
        _t(
            'ar_sect',
            'Song sections',
            'intro, verse, chorus, bridge, outro as regions',
            '<path d="M3 8h5v8H3zM10 8h4v8h-4zM16 8h5v8h-5z"/><path d="M3 5h18"/>',
        ),
        _t(
            'ar_marker',
            'Markers',
            'named points on the timeline',
            '<path d="M5 3v18"/><path d="M5 4h11l-2.5 3.5L16 11H5z"/>',
        ),
        _t(
            'ar_loopreg',
            'Loop region',
            'the in/out bracket the transport cycles inside',
            '<path d="M5 6v12M19 6v12"/><path d="M8 12h8"/><path d="M9 9l-3 3 3 3M15 9l3 3-3 3"/>',
        ),
        _t(
            'ar_split',
            'Split',
            'cut the selected layer at the playhead',
            '<path d="M4 8h7M13 8h7M4 16h7M13 16h7"/><path d="M12 2v20" stroke-dasharray="3 2"/>',
        ),
        _t(
            'ar_join',
            'Join',
            'weld two adjacent layers into one',
            '<path d="M3 8h9v8H3zM12 8h9v8h-9z"/><path d="M12 5v14"/>',
        ),
        _t(
            'ar_trim',
            'Trim',
            'shorten the layer from either end',
            '<path d="M6 5v14M18 5v14"/><path d="M6 12h12"/><path d="M9 9l-3 3 3 3M15 9l3 3-3 3"/>',
        ),
        _t('ar_fadein', 'Fade in', 'ramp the layer up from silence', '<path d="M3 19L21 5"/><path d="M3 19h18"/>'),
        _t('ar_fadeout', 'Fade out', 'ramp the layer down to silence', '<path d="M3 5l18 14"/><path d="M3 19h18"/>'),
        _t(
            'ar_xfade',
            'Crossfade',
            'fade one layer out as the next fades in',
            '<path d="M3 18L12 6l9 12"/><path d="M3 6l9 12L21 6" stroke-dasharray="2 2"/>',
        ),
        _t(
            'ar_slip',
            'Slip',
            'move the audio inside a fixed region',
            '<path d="M4 7h16v10H4z"/><path d="M7 12h10"/><path d="M9 9l-2 3 2 3M15 9l2 3-2 3"/>',
        ),
        _t(
            'ar_ripple',
            'Ripple edit',
            'an edit pushes everything after it along',
            '<path d="M3 9h6v6H3z"/><path d="M11 9h4v6h-4zM17 9h4v6h-4z"/><path d="M9 12h2M15 12h2"/>',
        ),
        _t(
            'ar_dupbar',
            'Repeat bars',
            'copy a span of bars N times down the line',
            '<path d="M4 6h6v12H4z"/><path d="M12 6h6v12h-6z" stroke-dasharray="3 2"/><path d="M20 6v12"/>',
        ),
        _t(
            'ar_comp',
            'Comp takes',
            'build one part out of several recorded takes',
            '<path d="M3 5h18v4H3zM3 10h18v4H3zM3 15h18v4H3z"/><path d="M7 5v4M13 10v4M17 15v4" stroke-width="3"/>',
        ),
        _t(
            'ar_freeze',
            'Freeze layer',
            'bounce the chain in place to stop re-rendering it',
            '<path d="M12 2v20M4 7l16 10M20 7L4 17"/><path d="M9 4l3-2 3 2M9 20l3 2 3-2"/>',
        ),
        _t(
            'ar_group',
            'Group layers',
            'move several layers as one',
            '<path d="M3 6h8v5H3zM3 13h8v5H3z"/><path d="M14 4v16"/><path d="M14 12h7"/>',
        ),
        _t(
            'ar_lock',
            'Lock layer',
            'stop a finished layer being moved by accident',
            '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
        ),
        _t(
            'ar_lanes',
            'Lane height',
            'how tall each lane is drawn',
            '<path d="M3 5h18v4H3zM3 11h18v3H3zM3 16h18v3H3z"/>',
        ),
    ],
)

_sec(
    'time',
    'Time & groove',
    'dock',
    [
        _t(
            'tm_tempo',
            'Tempo',
            'the BPM the grid and every generator work to',
            '<path d="M9 3h6l4 18H5z"/><path d="m12 18 4-11"/><path d="M6.5 15h11"/>',
        ),
        _t(
            'tm_tap',
            'Tap tempo',
            'tap the tempo in instead of typing it',
            '<path d="M9 3h6l4 18H5z"/><path d="M12 18V8"/><circle cx="19" cy="6" r="2"/>',
        ),
        _t(
            'tm_tempomap',
            'Tempo map',
            'tempo that changes across the piece',
            '<path d="M3 18l5-4 4 3 5-7 4 2"/><path d="M3 21h18"/><path d="M3 3v18"/>',
        ),
        _t(
            'tm_meter',
            'Time signature',
            '4/4, 3/4, 6/8, 7/8 and the odd ones',
            '<path d="M8 4v7M5 7h6"/><path d="M4 13h16" stroke-dasharray="0"/><path d="M8 15v6M5 18h6"/><path d="M15 4l3 7M15 15l3 6"/>',
        ),
        _t(
            'tm_click',
            'Metronome',
            'the click, and whether it counts you in',
            '<path d="M9 3h6l4 18H5z"/><path d="M12 8v10"/><path d="M3 12h3M18 12h3"/>',
        ),
        _t(
            'tm_countin',
            'Count-in',
            'how many bars before recording starts',
            '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/><path d="M2 12h3"/>',
        ),
        _t(
            'tm_quant',
            'Quantize',
            'pull the notes onto the grid',
            '<path d="M3 4v16M9 4v16M15 4v16M21 4v16" stroke-dasharray="2 3"/><path d="M5 8h4M13 13h4M7 17h4"/><path d="M5 8L3 8M13 13l2 0" stroke-dasharray="0"/>',
        ),
        _t(
            'tm_qstrength',
            'Quantize strength',
            'how far towards the grid, not all the way',
            '<path d="M6 4v16M18 4v16" stroke-dasharray="2 3"/><path d="M9 12h6"/><path d="M12 9l3 3-3 3"/>',
        ),
        _t(
            'tm_swing',
            'Swing',
            'push the off-beats late by a percentage',
            '<path d="M4 12h4M12 12h3M19 12h1"/><path d="M4 17c3-6 6 6 9 0s5-6 7-3"/>',
        ),
        _t(
            'tm_groove',
            'Groove template',
            'borrow the timing feel of another performance',
            '<path d="M3 8h18M3 16h18"/><path d="M6 8v-3M11 8v-3M17 8v-3"/><path d="M7 16v3M12 16v3M19 16v3"/>',
        ),
        _t(
            'tm_humanize',
            'Humanize',
            'scatter timing and velocity off the machine grid',
            '<path d="M4 16h2M9 16h2M14 16h2M19 16h1"/><path d="M5 13v-4M10 12v-5M15 14v-3M19 11v-4"/>',
        ),
        _t(
            'tm_nudgegrid',
            'Track offset',
            'shift a whole layer early or late by a fixed amount',
            '<path d="M3 6h18M3 18h18"/><path d="M6 6v12"/><path d="M9 18l3-3 3 3" transform="translate(0,-6)"/>',
        ),
        _t(
            'tm_stretchfit',
            'Fit to tempo',
            'stretch the picked sample onto the current BPM',
            '<path d="M3 12h18"/><path d="M6 8l-3 4 3 4M18 8l3 4-3 4"/><path d="M9 5h6v14H9z" stroke-dasharray="2 2"/>',
        ),
        _t(
            'tm_polyrhy',
            'Polyrhythm',
            'two divisions of the bar running against each other',
            '<path d="M3 8h18"/><path d="M7 8V5M13 8V5M19 8V5"/><path d="M3 16h18"/><path d="M6 16v3M11 16v3M16 16v3M21 16v3"/>',
        ),
        _t(
            'tm_rubato',
            'Rubato',
            'stretch the phrase, put the time back at the end',
            '<path d="M3 16c4-8 6 8 9 0s6-8 9 0"/><path d="M3 20h18" stroke-dasharray="2 2"/>',
        ),
        _t(
            'tm_gridres',
            'Grid division',
            '1/4, 1/8, 1/16, triplets and dotted',
            '<path d="M3 4v16M21 4v16"/><path d="M7 6v12M11 6v12M15 6v12M18 8v8" stroke-dasharray="2 2"/>',
        ),
    ],
)

_sec(
    'compose',
    'Compose',
    'dock',
    [
        _t(
            'co_pianoroll',
            'Piano roll',
            'the note editor — pitch against time',
            '<path d="M3 4h4v16H3z"/><path d="M3 8h4M3 12h4M3 16h4"/><path d="M9 6h7v2.5H9zM13 10h8v2.5h-8zM9 14h5v2.5H9z"/>',
        ),
        _t(
            'co_chord',
            'Chord',
            'build a chord under the picked root',
            '<circle cx="7" cy="17" r="2.4"/><circle cx="12" cy="14" r="2.4"/><circle cx="17" cy="11" r="2.4"/><path d="M9.4 17V6M14.4 14V4M19.4 11V3"/>',
        ),
        _t(
            'co_prog',
            'Progression',
            'a sequence of chords, in key',
            '<path d="M3 16h4v5H3zM10 12h4v9h-4zM17 8h4v13h-4z"/><path d="M2 4h20" stroke-dasharray="3 2"/>',
        ),
        _t(
            'co_voicing',
            'Voicing',
            'how the notes of the chord are spaced',
            '<path d="M4 20h16"/><circle cx="8" cy="17" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="16" cy="5" r="1.6"/><path d="M8 15.4V4M12 10.4V4M16 3.4V3"/>',
        ),
        _t(
            'co_invert',
            'Inversion',
            'rotate the chord tones through the octave',
            '<circle cx="6" cy="16" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="18" cy="8" r="1.8"/><path d="M6 14a10 10 0 0 1 12-8" stroke-dasharray="2 2"/>',
        ),
        _t(
            'co_strum',
            'Strum',
            "spread a chord's notes across a few milliseconds",
            '<path d="M4 4v16"/><path d="M6 6l14 3M6 10l14 3M6 14l14 3"/>',
        ),
        _t(
            'co_melody',
            'Melody',
            'write or generate a line over the harmony',
            '<path d="M4 16l4-6 4 4 4-9 4 6"/><circle cx="4" cy="16" r="1.2"/><circle cx="20" cy="11" r="1.2"/>',
        ),
        _t(
            'co_bassline',
            'Bass line',
            'the low part that follows the progression',
            '<path d="M3 8h18"/><path d="M4 16v3M9 14v5M14 16v3M19 13v6"/><path d="M3 21h18"/>',
        ),
        _t(
            'co_drums',
            'Drum pattern',
            'a kit pattern on the grid',
            '<path d="M3 5h18v4H3zM3 10h18v4H3zM3 15h18v4H3z"/><circle cx="6" cy="7" r="1"/><circle cx="14" cy="7" r="1"/><circle cx="10" cy="12" r="1"/><circle cx="18" cy="12" r="1"/><circle cx="6" cy="17" r="1"/><circle cx="12" cy="17" r="1"/>',
        ),
        _t(
            'co_counter',
            'Counterpoint',
            'a second independent line against the first',
            '<path d="M3 8c4-4 8 4 12 0s5-2 6-1"/><path d="M3 16c4 4 8-4 12 0s5 2 6 1"/>',
        ),
        _t(
            'co_harmonize',
            'Harmonize',
            'add parallel voices a chosen interval away',
            '<path d="M3 15l5-5 5 4 5-7 3 4"/><path d="M3 20l5-5 5 4 5-7 3 4" opacity=".6"/>',
        ),
        _t(
            'co_scalelock',
            'Scale lock',
            'force every generated note into the key',
            '<path d="M4 20l4-4 4-4 4-4 4-4"/><rect x="14" y="13" width="7" height="6" rx="1.6"/><path d="M16 13v-2a1.5 1.5 0 0 1 3 0v2"/>',
        ),
        _t(
            'co_noterepeat',
            'Note repeat',
            'retrigger the held note on a division',
            '<path d="M5 6v12M9 8v8M13 8v8M17 8v8M21 8v8"/>',
        ),
        _t(
            'co_euclid',
            'Euclidean',
            'spread N hits as evenly as possible over M steps',
            '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="3" r="1.6" fill="currentColor"/><circle cx="19.8" cy="16.5" r="1.6" fill="currentColor"/><circle cx="4.2" cy="16.5" r="1.6" fill="currentColor"/>',
        ),
        _t(
            'co_random',
            'Randomize',
            'reroll the generated part on a new seed',
            '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1.2"/><circle cx="15" cy="15" r="1.2"/><circle cx="15" cy="9" r="1.2"/><circle cx="9" cy="15" r="1.2"/>',
        ),
        _t(
            'co_variation',
            'Variation',
            'a version of the part that is near, not identical',
            '<path d="M4 8c4-4 8 4 12 0s3-2 4-1"/><path d="M4 16c4-4 8 4 12 0s3-2 4-1" stroke-dasharray="3 2"/>',
        ),
        _t(
            'co_transpose',
            'Transpose part',
            'move the whole part by an interval',
            '<path d="M4 18h16"/><path d="M7 15V9M12 15V6M17 15v-9"/><path d="M14 4l3-3 3 3"/>',
        ),
        _t(
            'co_velocity',
            'Note velocity',
            'edit how hard each note is played',
            '<path d="M3 21h18"/><path d="M5 21v-6M9 21v-11M13 21v-4M17 21v-14M21 21v-8"/>',
        ),
        _t(
            'co_length',
            'Note length',
            'legato, staccato and everything between',
            '<path d="M3 8h11v3H3z"/><path d="M3 15h5v3H3z"/><path d="M17 6v14"/>',
        ),
        _t(
            'co_midiin',
            'MIDI in',
            'play the picked instrument from a controller',
            '<rect x="2" y="7" width="20" height="10" rx="4"/><circle cx="7" cy="12" r="1"/><circle cx="10" cy="9.6" r="1"/><circle cx="14" cy="9.6" r="1"/><circle cx="17" cy="12" r="1"/>',
        ),
        _t(
            'co_midifile',
            'Import MIDI',
            'read a MIDI file in as parts',
            '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9v6M10 9v6M13 9v6M16 9v6"/><path d="M3 15h18"/>',
        ),
        _t(
            'co_step',
            'Step sequencer',
            'enter the part one step at a time',
            '<path d="M3 6h3v12H3zM8 6h3v12H8zM13 6h3v12h-3zM18 6h3v12h-3"/><path d="M3 12h3M13 12h3" stroke-width="3"/>',
        ),
    ],
)
