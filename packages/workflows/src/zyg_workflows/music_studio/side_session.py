# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE bar — the SESSION: transport, timeline, layer, chain, presets,
measure, library, view.  These are the LIVE half."""

from ._defs import _sec, _t


# ══ SIDE (right) — the SESSION ═════════════════════════════════════════════
# These are the LIVE half.  Every one is wired to a real function in the page
# (MST_FN, keyed by the id below), inherited from the Sfx Studio toolbox this
# tab was cloned from: the merger, its lane board, its chains and its saves
# are the same code on the same server routes.  live=True is a promise the
# page keeps — if an id here has no entry in MST_FN it is drawn as a
# placeholder anyway, so the marking can never over-claim.

_sec(
    'transport',
    'Transport',
    'side',
    [
        _t('t_play', 'Play / pause', 'play or pause the board as it stands', '<path d="M7 4l13 8-13 8z"/>', True),
        _t(
            't_stop',
            'Stop',
            'stop and rewind to the start',
            '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
            True,
        ),
        _t(
            't_replay',
            'Replay',
            'play again from the start',
            '<path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M3 3v5h5"/>',
            True,
        ),
        _t(
            't_loop',
            'Loop',
            'loop the board — a layer added while looping keeps it looping',
            '<path d="M5 8h11a3 3 0 0 1 0 6H8"/><path d="M8 11l-3 3 3 3"/>',
            True,
        ),
        _t(
            't_solo',
            'Solo layer',
            'play the selected layer alone, with its chain applied',
            '<path d="M5 15v-3a7 7 0 0 1 14 0v3"/><rect x="3" y="14" width="4" height="6" rx="1.6"/>'
            '<rect x="17" y="14" width="4" height="6" rx="1.6"/>',
            True,
        ),
    ],
)

_sec(
    'timeline',
    'Timeline',
    'side',
    [
        _t(
            't_zoomin',
            'Zoom in',
            'zoom the ruler in',
            '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5M11 8.5v5M8.5 11h5"/>',
            True,
        ),
        _t(
            't_zoomout',
            'Zoom out',
            'zoom the ruler out',
            '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5M8.5 11h5"/>',
            True,
        ),
        _t(
            't_zoomfit',
            'Fit',
            'fit the whole board on screen',
            '<path d="M3 8V4h4M17 4h4v4M21 16v4h-4M7 20H3v-4"/><path d="M8 12h8"/>',
            True,
        ),
        _t(
            't_taller',
            'Taller lanes',
            'make every lane taller',
            '<path d="M12 4v16"/><path d="M8 8l4-4 4 4M8 16l4 4 4-4"/>',
            True,
        ),
        _t(
            't_shorter',
            'Shorter lanes',
            'make every lane shorter',
            '<path d="M4 12h16"/><path d="M8 6l4 4 4-4M8 18l4-4 4 4"/>',
            True,
        ),
        _t(
            't_nudgel',
            'Nudge earlier',
            'move the selected layer 10 ms earlier',
            '<path d="M20 12H6"/><path d="M11 7l-5 5 5 5"/><path d="M3 5v14" stroke-dasharray="2 2"/>',
            True,
        ),
        _t(
            't_nudger',
            'Nudge later',
            'move the selected layer 10 ms later',
            '<path d="M4 12h14"/><path d="M13 7l5 5-5 5"/><path d="M21 5v14" stroke-dasharray="2 2"/>',
            True,
        ),
        _t(
            't_stamp',
            'Set timestamp',
            'type an exact start time for the selected layer',
            '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
            True,
        ),
    ],
)

_sec(
    'layer',
    'Layer',
    'side',
    [
        _t(
            't_addlayer',
            'Add sound',
            'add the sound playing in the library as a new layer',
            '<rect x="3" y="9" width="12" height="5" rx="1.4"/><rect x="3" y="16" width="12" height="5" rx="1.4"/>'
            '<path d="M19 3v8M15 7h8"/>',
            True,
        ),
        _t(
            't_dup',
            'Duplicate',
            'copy the selected layer, chain and all',
            '<rect x="3" y="7" width="11" height="12" rx="1.6"/><path d="M7 4h10a3 3 0 0 1 3 3v10"/>',
            True,
        ),
        _t(
            't_dellayer',
            'Remove layer',
            'take the selected layer off the board',
            '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>',
            True,
        ),
        _t(
            't_mute',
            'Mute',
            'mute or unmute the selected layer',
            '<path d="M4 9h3l4-4v14l-4-4H4z"/><path d="M15 9l5 6M20 9l-5 6"/>',
            True,
        ),
        _t(
            't_colour',
            'Name & colour',
            'rename the selected layer or give it a colour',
            '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17" fill="currentColor" stroke="none"/>',
            True,
        ),
        _t(
            't_up',
            'Move up',
            'move the selected layer one lane up',
            '<path d="M12 20V5"/><path d="M6 11l6-6 6 6"/>',
            True,
        ),
        _t(
            't_down',
            'Move down',
            'move the selected layer one lane down',
            '<path d="M12 4v15"/><path d="M6 13l6 6 6-6"/>',
            True,
        ),
        _t(
            't_clearall',
            'Clear board',
            'empty the layer list (undoable)',
            '<path d="M4 6h16"/><path d="M7 6l1 14h8l1-14"/><path d="M9 3h6"/>'
            '<path d="M10 10v7M14 10v7" stroke-dasharray="2 2"/>',
            True,
        ),
    ],
)

_sec(
    'chain',
    'Chain',
    'side',
    [
        _t(
            't_mixer',
            'Mixer',
            'open the slot list for the selected layer',
            '<path d="M6 4v5M6 15v5M12 4v9M12 19v1M18 4v2M18 12v8"/>'
            '<circle cx="6" cy="12" r="2.4"/><circle cx="12" cy="16" r="2.4"/><circle cx="18" cy="9" r="2.4"/>',
            True,
        ),
        _t(
            't_bypass',
            'Bypass (A/B)',
            'silence the whole chain on the selected layer and put it back — the only honest way to hear what it did',
            '<path d="M4 16h4l3-8h5"/><path d="M13 5l3 3-3 3"/><path d="M4 20h16" stroke-dasharray="2 2"/>',
            True,
        ),
        _t(
            't_chainclear',
            'Clear chain',
            'take every effect off the selected layer',
            '<path d="M9 12H5a3 3 0 0 1 0-6h3"/><path d="M15 6h4a3 3 0 0 1 0 6h-3"/><path d="M4 20L20 4"/>',
            True,
        ),
        _t(
            't_copy',
            'Copy chain',
            'copy the selected layer’s whole effect chain',
            '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>',
            True,
        ),
        _t(
            't_paste',
            'Paste chain',
            'replace the selected layer’s chain with the copied one',
            '<rect x="5" y="5" width="14" height="16" rx="2"/><path d="M9 5V3h6v2"/><path d="M9 12h6M9 16h4"/>',
            True,
        ),
        _t(
            't_applyall',
            'Apply to every layer',
            'give every layer on the board the copied chain',
            '<path d="M4 7h9M4 12h9M4 17h9"/><path d="M15 9l3 3 5-6"/>',
            True,
        ),
        _t(
            't_undo',
            'Undo',
            'undo the last board or chain edit',
            '<path d="M4 10h9a5 5 0 0 1 0 10H8"/><path d="M8 5l-5 5 5 5"/>',
            True,
        ),
        _t(
            't_redo',
            'Redo',
            'redo what you just undid',
            '<path d="M20 10h-9a5 5 0 0 0 0 10h5"/><path d="M16 5l5 5-5 5"/>',
            True,
        ),
    ],
)

_sec(
    'presets',
    'Presets',
    'side',
    [
        _t(
            't_presetsave',
            'Save chain preset',
            'store the selected layer’s chain under a name',
            '<path d="M12 3l2.5 5.5L20 10l-5.5 1.5L12 17l-2.5-5.5L4 10l5.5-1.5z"/><path d="M17 17h5M19.5 14.5v5"/>',
            True,
        ),
        _t(
            't_presetload',
            'Load chain preset',
            'put a stored chain onto the selected layer',
            '<path d="M12 3l2.5 5.5L20 10l-5.5 1.5L12 17l-2.5-5.5L4 10l5.5-1.5z"/><path d="M17 19h5M19.5 21.5l2.5-2.5-2.5-2.5"/>',
            True,
        ),
    ],
)

_sec(
    'measure',
    'Measure',
    'side',
    [
        _t(
            't_stats',
            'Analyse',
            'peak, RMS, LUFS, true peak, crest, DC, dynamic range — measured on the sound as it stands',
            '<path d="M4 20V9M10 20V4M16 20v-8M22 20h-20"/>',
            True,
        ),
        _t(
            't_spectro',
            'Spectrogram',
            'draw the spectrogram of the selected sound after its chain',
            '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M6 17v-4M9 17v-8M12 17v-6M15 17v-9M18 17v-5"/>',
            True,
        ),
        _t(
            't_wave',
            'Waveform',
            'draw the full waveform of the selected sound after its chain',
            '<path d="M2 12h2l2-6 3 12 3-16 3 14 2-6 2 2h3"/>',
            True,
        ),
        _t(
            't_lufs',
            'Loudness',
            'EBU R128 integrated loudness and range',
            '<path d="M4 18a8 8 0 0 1 16 0"/><path d="M12 18l6-5"/><path d="M3 21h18"/>',
            True,
        ),
        _t(
            't_clipcheck',
            'Clip check',
            'true peak against 0 dBFS — is this layer clipping right now?',
            '<path d="M3 6h18" stroke-dasharray="3 2"/><path d="M3 18c3 0 2-12 5-12s3 12 6 12"/><path d="M17 12l2 2 4-4"/>',
            True,
        ),
    ],
)

_sec(
    'library',
    'Library',
    'side',
    [
        _t(
            't_record',
            'Record',
            'record from an input device straight into a new layer',
            '<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="2.6" fill="currentColor"/>',
            True,
        ),
        _t(
            't_import',
            'Import file',
            'bring an audio file in from this machine as a new sound',
            '<path d="M12 3v11"/><path d="M8 10l4 4 4-4"/><path d="M4 17v3h16v-3"/>',
            True,
        ),
        _t(
            't_savemerge',
            'Save mix',
            'save every layer as one new file in the Merged library',
            '<path d="M5 3h11l3 3v15H5z"/><path d="M9 3v6h6V3"/><rect x="8" y="13" width="8" height="6"/>',
            True,
        ),
        _t(
            't_savelayer',
            'Save this layer',
            'save the selected layer alone — this is how an edited instrument goes back into the library',
            '<rect x="3" y="4" width="18" height="6" rx="1.6"/><path d="M5 14h11l3 3v4H5z"/>',
            True,
        ),
        _t(
            't_export',
            'Export file',
            'render and download: wav 16/24/32, flac, mp3, ogg, opus, aiff, any sample rate',
            '<path d="M12 14V3"/><path d="M8 7l4-4 4 4"/><path d="M4 15v5h16v-5"/>',
            True,
        ),
        _t(
            't_recipe',
            'Open recipe',
            'reopen a saved mix as its layers, chains and timings',
            '<path d="M5 4h12l3 3v13H5z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
            True,
        ),
        _t(
            't_licence',
            'Licence',
            'the licence the selected sound carries, and what a mix of it would inherit',
            '<circle cx="12" cy="9" r="5"/><path d="M9 13l-2 8 5-3 5 3-2-8"/>',
            True,
        ),
    ],
)

_sec(
    'view',
    'View',
    'side',
    [
        _t(
            't_rail',
            'Hide the bars',
            'hide or show the two icon bars and the dock',
            '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/><path d="M18 9v6" stroke-dasharray="2 2"/>',
            True,
        ),
        _t(
            't_help',
            'Help',
            'what every part of this toolbox does',
            '<circle cx="12" cy="12" r="9"/>'
            '<path d="M9.5 9a2.6 2.6 0 1 1 3.4 2.5c-.6.3-.9.8-.9 1.5v.5"/><circle cx="12" cy="17" r="1"/>',
            True,
        ),
    ],
)
