# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DOCK bar, part 2 — mix, master, score."""

from ._defs import _sec, _t


_sec(
    'mix',
    'Mix',
    'dock',
    [
        _t(
            'mx_fader',
            'Fader',
            "the layer's level",
            '<path d="M6 3v18M12 3v18M18 3v18"/><rect x="4" y="8" width="4" height="3" rx="1" fill="currentColor"/><rect x="10" y="13" width="4" height="3" rx="1" fill="currentColor"/><rect x="16" y="6" width="4" height="3" rx="1" fill="currentColor"/>',
        ),
        _t(
            'mx_pan',
            'Pan',
            'where the layer sits between the speakers',
            '<path d="M4 16a8 8 0 0 1 16 0"/><path d="M12 16l5-5"/><circle cx="12" cy="16" r="1.4"/>',
        ),
        _t(
            'mx_trim',
            'Input trim',
            'level BEFORE the chain, so the chain sees the same input',
            '<path d="M12 3v18"/><rect x="6" y="8" width="12" height="5" rx="1.6"/><path d="M9 3h6"/>',
        ),
        _t(
            'mx_phase',
            'Phase invert',
            "flip the layer's polarity",
            '<circle cx="12" cy="12" r="9"/><path d="M3 12c3-6 6 6 9 0s6-6 9 0"/>',
        ),
        _t(
            'mx_bus',
            'Bus',
            'send several layers to one place',
            '<path d="M4 5v4a3 3 0 0 0 3 3h10"/><path d="M4 19v-4a3 3 0 0 1 3-3"/><path d="M15 9l3 3-3 3"/>',
        ),
        _t(
            'mx_send',
            'Aux send',
            'a copy of the layer to a shared effect',
            '<path d="M4 12h9"/><path d="M10 8l4 4-4 4"/><path d="M17 5v14"/><path d="M20 8v8"/>',
        ),
        _t(
            'mx_return',
            'Return',
            'the shared effect coming back into the mix',
            '<path d="M20 12h-9"/><path d="M14 8l-4 4 4 4"/><path d="M7 5v14"/><path d="M4 8v8"/>',
        ),
        _t(
            'mx_prepost',
            'Pre / post',
            'whether the send is taken before or after the fader',
            '<path d="M4 12h16"/><path d="M9 6v12" stroke-dasharray="2 2"/><circle cx="9" cy="12" r="2.4"/><path d="M15 8v8"/>',
        ),
        _t(
            'mx_vca',
            'Group / VCA',
            'one fader that moves a set of others',
            '<path d="M6 21V9M12 21V6M18 21v-9"/><path d="M3 5h18"/><rect x="3" y="3" width="18" height="4" rx="1.6"/>',
        ),
        _t(
            'mx_sidechain',
            'Sidechain',
            'one layer ducking under another',
            '<path d="M3 8h7c3 0 3 8 6 8h5"/><path d="M3 18h5"/><path d="M8 21V15"/><path d="M6 17l2-2 2 2"/>',
        ),
        _t(
            'mx_route',
            'Routing',
            "where this layer's audio goes",
            '<circle cx="5" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="12" r="2"/><path d="M7 6c6 0 4 6 10 6M7 18c6 0 4-6 10-6"/>',
        ),
        _t(
            'mx_insert',
            'Insert slot',
            "an effect in the layer's own chain",
            '<path d="M3 12h4M17 12h4"/><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 12h4"/>',
        ),
        _t(
            'mx_meter',
            'Meter',
            'the level as it plays',
            '<path d="M5 21V8M10 21V4M15 21v-9M20 21v-6"/><path d="M3 21h18"/>',
        ),
        _t(
            'mx_pfl',
            'PFL / solo bus',
            'listen to one layer without changing the mix',
            '<path d="M5 15v-3a7 7 0 0 1 14 0v3"/><rect x="3" y="14" width="4" height="6" rx="1.6"/><rect x="17" y="14" width="4" height="6" rx="1.6"/><circle cx="12" cy="6" r="1.2"/>',
        ),
        _t(
            'mx_width',
            'Stereo image',
            'how wide the layer sits — read-out, not the effect',
            '<path d="M12 4v16"/><path d="M4 8v8M20 8v8"/><path d="M6 12h12" stroke-dasharray="2 2"/>',
        ),
        _t(
            'mx_balance',
            'Balance',
            'the left/right balance of an already-stereo layer',
            '<path d="M12 4v16"/><path d="M4 12h16"/><circle cx="15" cy="12" r="2.4"/>',
        ),
        _t(
            'mx_snapshot',
            'Mix snapshot',
            "store and recall the whole board's levels",
            '<rect x="3" y="6" width="18" height="13" rx="2"/><circle cx="12" cy="12.5" r="3.6"/><path d="M8 6l1.5-2h5L16 6"/>',
        ),
        _t(
            'mx_autom',
            'Automation',
            'a control that moves over time',
            '<path d="M3 17l5-7 4 4 4-8 5 5"/><circle cx="8" cy="10" r="1.4"/><circle cx="16" cy="6" r="1.4"/>',
        ),
    ],
)

_sec(
    'master',
    'Master',
    'dock',
    [
        _t(
            'ma_bounce',
            'Bounce',
            'render the whole board to one file',
            '<path d="M12 3v11"/><path d="M8 10l4 4 4-4"/><path d="M4 17v4h16v-4"/>',
        ),
        _t(
            'ma_stems',
            'Stems',
            'render every layer or group as its own file',
            '<path d="M3 5h18v4H3zM3 10h18v4H3zM3 15h18v4H3z"/><path d="M12 2v2"/>',
        ),
        _t(
            'ma_sr',
            'Sample rate',
            '44.1 / 48 / 88.2 / 96 / 192 kHz out',
            '<path d="M3 18h18"/><path d="M4 12v6M7 8v10M10 12v6M13 6v12M16 12v6M19 9v9"/>',
        ),
        _t(
            'ma_bits',
            'Bit depth',
            '16, 24 or 32-bit float out',
            '<path d="M4 5h6v6H4zM14 13h6v6h-6z"/><path d="M14 5h6M14 8h6M4 16h6M4 19h6"/>',
        ),
        _t(
            'ma_dither',
            'Dither',
            'the noise that makes a bit-depth cut honest',
            '<circle cx="6" cy="7" r=".8"/><circle cx="12" cy="5" r=".8"/><circle cx="18" cy="8" r=".8"/><circle cx="8" cy="13" r=".8"/><circle cx="15" cy="12" r=".8"/><circle cx="6" cy="18" r=".8"/><circle cx="13" cy="18" r=".8"/><circle cx="19" cy="16" r=".8"/>',
        ),
        _t(
            'ma_target',
            'Loudness target',
            '−14 LUFS for streaming, −23 for broadcast, and the rest',
            '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/><path d="M12 1.5v3M12 19.5v3"/>',
        ),
        _t(
            'ma_truepeak',
            'True peak',
            'the inter-sample peak a converter would actually see',
            '<path d="M3 6h18" stroke-dasharray="3 2"/><path d="M3 18c4 0 3-13 6-13s4 13 6 13 3-8 6-8"/>',
        ),
        _t(
            'ma_spectrum',
            'Spectrum',
            'the live frequency read-out of the master',
            '<path d="M3 20V12M6 20V7M9 20v-9M12 20V5M15 20v-8M18 20v-6M21 20v-3"/>',
        ),
        _t(
            'ma_correl',
            'Phase meter',
            'mono compatibility — what a phone speaker keeps',
            '<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M6 16c3-6 9-6 12 0"/>',
        ),
        _t(
            'ma_gonio',
            'Goniometer',
            'the stereo field drawn as a shape',
            '<path d="M12 3l7 9-7 9-7-9z"/><path d="M5 12h14"/>',
        ),
        _t(
            'ma_refmatch',
            'Reference match',
            'compare the mix against a track you trust',
            '<path d="M4 6h7v12H4z"/><path d="M13 6h7v12h-7z"/><path d="M11 12h2"/>',
        ),
        _t(
            'ma_mono',
            'Mono check',
            'fold to mono and listen for what disappears',
            '<circle cx="12" cy="12" r="6"/><path d="M3 12h3M18 12h3"/><path d="M12 3v3M12 18v3"/>',
        ),
        _t(
            'ma_fmt',
            'Export format',
            'wav, flac, mp3, ogg, opus, aiff, m4a',
            '<path d="M5 3h9l5 5v13H5z"/><path d="M14 3v5h5"/><path d="M8 14h8M8 17h5"/>',
        ),
        _t(
            'ma_meta',
            'Metadata',
            'title, artist, BPM, key and ISRC written into the file',
            '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 13h10M7 17h6"/>',
        ),
        _t(
            'ma_cue',
            'Cue sheet',
            'the marker list a mastering house or a DAW can read',
            '<path d="M4 4h16v16H4z"/><path d="M8 4v16"/><path d="M11 8h6M11 12h6M11 16h4"/>',
        ),
        _t(
            'ma_licence',
            'Licence roll-up',
            'what every source in the board allows, together',
            '<path d="M4 4v6M10 4v6M16 4v6"/><path d="M4 10c0 3 5 2 6 5M10 10v5M16 10c0 3-5 2-6 5"/>'
            '<circle cx="10" cy="18" r="3"/>',
        ),
    ],
)

_sec(
    'score',
    'Score',
    'dock',
    [
        _t('sc_staff', 'Staff', 'draw the part on a stave', '<path d="M3 6h18M3 10h18M3 14h18M3 18h18"/>'),
        _t(
            'sc_clef',
            'Clef',
            'treble, bass, alto and tenor',
            '<path d="M12 21c-3 0-4-2-4-4s2-3 4-3 5 2 5 5-3 4-5 4"/><path d="M12 14V5a2 2 0 0 1 4 0c0 4-8 6-8 11"/>',
        ),
        _t(
            'sc_notevals',
            'Note values',
            'whole down to thirty-second notes',
            '<ellipse cx="7" cy="16" rx="3.2" ry="2.4"/><path d="M10.2 16V4"/><ellipse cx="16" cy="16" rx="3.2" ry="2.4" fill="currentColor"/><path d="M19.2 16V4"/>',
        ),
        _t(
            'sc_rest',
            'Rests',
            'silence, written',
            '<path d="M8 5l6 6-4 2 5 6"/><path d="M4 3v18" stroke-dasharray="2 2"/>',
        ),
        _t(
            'sc_tie',
            'Tie & slur',
            'joined notes and phrased groups',
            '<circle cx="6" cy="16" r="2.4"/><circle cx="18" cy="16" r="2.4"/><path d="M6 11c4-5 8-5 12 0"/>',
        ),
        _t(
            'sc_beam',
            'Beams',
            'how the note stems are grouped',
            '<path d="M6 18V7M12 18V6M18 18V5"/><path d="M6 7l12-2"/><path d="M6 10l12-2"/>',
        ),
        _t(
            'sc_dynmark',
            'Dynamic marks',
            'p, f, hairpins and their placement',
            '<path d="M4 16V9h2.5a2.5 2.5 0 0 1 0 5H4"/><path d="M12 10h9M12 10l9 4-9 4" transform="translate(0,-2)"/>',
        ),
        _t(
            'sc_articmark',
            'Articulation marks',
            'the dots, wedges and lines above the notes',
            '<circle cx="6" cy="6" r="1.2"/><path d="M10 5l2 3 2-3"/><path d="M18 5h4"/><path d="M3 12h18M3 16h18"/>',
        ),
        _t(
            'sc_chordsym',
            'Chord symbols',
            'the letter names above the stave',
            '<path d="M5 4v6M5 7h4M9 4v6"/><path d="M13 4a3 3 0 0 0 0 6"/><path d="M17 10V4h2a1.5 1.5 0 0 1 0 3h-2"/><path d="M3 14h18M3 18h18"/>',
        ),
        _t(
            'sc_lyrics',
            'Lyrics',
            'words under the notes',
            '<path d="M3 5h18M3 9h18"/><path d="M5 15h3M11 15h4M18 15h2"/><path d="M5 19h14"/>',
        ),
        _t(
            'sc_layout',
            'Page layout',
            'systems, margins and page turns',
            '<rect x="5" y="3" width="14" height="18" rx="1.6"/><path d="M8 8h8M8 12h8M8 16h5"/>',
        ),
        _t(
            'sc_part',
            'Extract parts',
            "one player's stave pulled out of the score",
            '<rect x="3" y="3" width="12" height="16" rx="1.6"/><path d="M9 21h12V7"/><path d="M6 8h6M6 12h6"/>',
        ),
        _t(
            'sc_midiexp',
            'Export MIDI',
            'write the parts out as a MIDI file',
            '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10v4M10 10v4M13 10v4M16 10v4"/><path d="M12 21v-3"/>',
        ),
        _t(
            'sc_xmlexp',
            'Export MusicXML',
            'write the score out for a notation program',
            '<path d="M5 3h9l5 5v13H5z"/><path d="M14 3v5h5"/><path d="M8 16l2-3-2-3M16 16l-2-3 2-3"/>',
        ),
        _t(
            'sc_pdf',
            'Print / PDF',
            'the score as paper',
            '<path d="M7 3h10v5H7z"/><rect x="4" y="8" width="16" height="7" rx="1.6"/><path d="M7 15h10v6H7z"/>',
        ),
    ],
)
