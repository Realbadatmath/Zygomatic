# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LEFT bar, part 1 — what the SOUND IS: instrument families, articulation."""

from ._defs import _sec, _t


# ══ LEFT — what the SOUND IS ═══════════════════════════════════════════════

# The instrument families the `instruments` library actually holds (343
# distinct instruments across freepats / philharmonia / vcsl / vsco2ce /
# sfzinstruments / guitarset).  A family here is a FILTER over the library
# tree, not a synth patch: picking Brass would narrow the rail the same way
# the search box does.
_sec(
    'instrument',
    'Instrument',
    'left',
    [
        _t(
            'in_piano',
            'Piano',
            'grand, upright and prepared piano samples',
            '<path d="M3 6h18v12H3z"/><path d="M7 6v7M11 6v7M15 6v7M19 6v7"/><path d="M6 6v4h1.6V6M9.6 6v4h1.6V6M14 6v4h1.6V6M17.6 6v4h1.6V6" fill="currentColor"/>',
        ),
        _t(
            'in_epiano',
            'Electric piano',
            'Rhodes, Wurlitzer, tine and reed electrics',
            '<path d="M3 8h18v9H3z"/><path d="M7 8v5M11 8v5M15 8v5"/><path d="M5 20h14"/><path d="M12 5V3"/>',
        ),
        _t(
            'in_organ',
            'Organ',
            'pipe, reed, tonewheel and combo organs',
            '<path d="M4 20V8l2-3 2 3v12M10 20V6l2-3 2 3v14M16 20V8l2-3 2 3v12"/><path d="M3 20h18"/>',
        ),
        _t(
            'in_harpsi',
            'Harpsichord',
            'harpsichord, clavichord, virginal',
            '<path d="M3 9h14l4 4v5H3z"/><path d="M7 9v5M11 9v5M15 9v5"/><path d="M3 6h11"/>',
        ),
        _t(
            'in_accordion',
            'Accordion',
            'accordion, bandoneon, concertina, harmonium',
            '<path d="M4 5h4v14H4zM16 5h4v14h-4z"/><path d="M8 7l8-1M8 10l8-1M8 13l8-1M8 16l8-1"/>',
        ),
        _t(
            'in_guitar_ac',
            'Acoustic guitar',
            'steel and nylon string acoustics',
            '<circle cx="10" cy="15" r="5.5"/><circle cx="10" cy="15" r="1.8"/><path d="M13 11l6-6"/><path d="M17 3l4 4"/>',
        ),
        _t(
            'in_guitar_el',
            'Electric guitar',
            'single coil, humbucker, clean and driven',
            '<path d="M6 18a4 4 0 0 0 6-2l5-9"/><path d="M6 18a4 4 0 0 1 2-6l9-5"/><path d="M16 3l5 5"/><path d="M9 15h3"/>',
        ),
        _t(
            'in_bass',
            'Bass',
            'electric, fretless, upright and synth bass',
            '<circle cx="9" cy="16" r="4.5"/><path d="M12 13l7-8"/><path d="M17 2l5 5"/><path d="M6 20h6"/>',
        ),
        _t(
            'in_ukulele',
            'Ukulele / mandolin',
            'small-bodied plucked strings',
            '<circle cx="9" cy="16" r="4"/><path d="M12 13l5-6"/><path d="M15 5l4 4"/><path d="M7 14h4"/>',
        ),
        _t(
            'in_harp',
            'Harp',
            'concert and folk harp',
            '<path d="M5 20C5 9 10 4 19 4"/><path d="M5 20h14"/><path d="M9 20V9M12 20V6.5M15 20V5.2M18 20V4.4"/>',
        ),
        _t(
            'in_banjo',
            'Banjo / lute',
            'banjo, oud, lute, saz and long-neck plucks',
            '<circle cx="8" cy="16" r="5"/><path d="M8 11v10" stroke-dasharray="2 2"/><path d="M12 13l8-9"/>',
        ),
        _t(
            'in_violin',
            'Violin',
            'solo violin, all articulations',
            '<path d="M9 21c-3 0-4-3-4-5s2-3 2-5-2-2-2-4 2-3 4-3 3 2 3 4"/><path d="M12 4l7 15"/><path d="M8 12h4"/>',
        ),
        _t(
            'in_viola',
            'Viola / cello',
            'the middle and low bowed voices',
            '<path d="M10 21c-3.5 0-5-3.5-5-6s2.5-3.5 2.5-6S5 6 5 4"/><path d="M12 3v18"/><path d="M9 9h6M9 14h6"/>',
        ),
        _t(
            'in_dbass',
            'Double bass',
            'arco and pizzicato upright bass',
            '<path d="M12 2v20"/><path d="M8 21c-3.5 0-5-4-5-7s3-4 3-7"/><path d="M16 21c3.5 0 5-4 5-7s-3-4-3-7"/>',
        ),
        _t(
            'in_strings',
            'String section',
            'ensemble strings, divisi and full',
            '<path d="M4 21V6M9 21V4M14 21V6M19 21V4"/><path d="M3 12h18" stroke-dasharray="2 3"/>',
        ),
        _t(
            'in_trumpet',
            'Trumpet',
            'trumpet, cornet, flugelhorn, piccolo trumpet',
            '<path d="M3 12h11"/><path d="M14 8l6-3v14l-6-3z"/><path d="M6 12v3M9 12v3M12 12v3"/>',
        ),
        _t(
            'in_trombone',
            'Trombone',
            'tenor and bass trombone, slide',
            '<path d="M3 9h13"/><path d="M16 6l5-2v10l-5-2z"/><path d="M3 9v7h6"/>',
        ),
        _t(
            'in_horn',
            'French horn',
            'horn, Wagner tuba, alphorn',
            '<circle cx="10" cy="13" r="7"/><circle cx="10" cy="13" r="3"/><path d="M17 13h4v5"/>',
        ),
        _t(
            'in_tuba',
            'Tuba',
            'tuba, euphonium, sousaphone, low brass',
            '<path d="M8 21V9a5 5 0 0 1 10 0v2"/><path d="M3 8l7-4v9L3 16z"/><path d="M14 21h8"/>',
        ),
        _t(
            'in_brass',
            'Brass section',
            'ensemble brass, stabs and swells',
            '<path d="M3 8l5-2v7L3 15z"/><path d="M11 6l5-2v11l-5-2z"/><path d="M19 9l3-1v7l-3-1z"/>',
        ),
        _t(
            'in_sax',
            'Saxophone',
            'soprano to baritone saxophone',
            '<path d="M12 3v9a5 5 0 0 0 5 5h1"/><path d="M18 13l3 4-4 3-2-3"/><path d="M10 7h4M10 10h4"/>',
        ),
        _t(
            'in_clarinet',
            'Clarinet',
            'clarinet family, basset horn',
            '<path d="M11 2h2v16l3 4H8l3-4z"/><circle cx="12" cy="6" r=".9"/><circle cx="12" cy="10" r=".9"/><circle cx="12" cy="14" r=".9"/>',
        ),
        _t(
            'in_oboe',
            'Oboe / bassoon',
            'double reeds — oboe, cor anglais, bassoon',
            '<path d="M12 2v14a4 4 0 0 0 4 4h2"/><circle cx="12" cy="7" r=".9"/><circle cx="12" cy="12" r=".9"/><path d="M10 2h4"/>',
        ),
        _t(
            'in_flute',
            'Flute',
            'concert flute, piccolo, alto and bass flute',
            '<path d="M3 10h18v4H3z"/><circle cx="7" cy="12" r="1"/><circle cx="11" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><path d="M21 10v4"/>',
        ),
        _t(
            'in_recorder',
            'Recorder / whistle',
            'recorder, tin whistle, ocarina, panpipe',
            '<path d="M9 2h6v14l-3 6-3-6z"/><circle cx="12" cy="7" r=".8"/><circle cx="12" cy="11" r=".8"/>',
        ),
        _t(
            'in_drumkit',
            'Drum kit',
            'the whole kit as one instrument',
            '<circle cx="12" cy="15" r="6"/><path d="M6 15v3a6 6 0 0 0 12 0v-3"/><path d="M4 8l5 4M20 8l-5 4"/><path d="M2 8h6M16 8h6"/>',
        ),
        _t(
            'in_kick',
            'Kick',
            'bass drum — acoustic, electronic and layered',
            '<circle cx="12" cy="13" r="8"/><circle cx="12" cy="13" r="2.4"/><path d="M12 2v3"/>',
        ),
        _t(
            'in_snare',
            'Snare',
            'snare, rimshot, ghost note, brush',
            '<ellipse cx="12" cy="8" rx="8" ry="3"/><path d="M4 8v6c0 1.7 3.6 3 8 3s8-1.3 8-3V8"/><path d="M4 12h16" stroke-dasharray="2 2"/>',
        ),
        _t(
            'in_toms',
            'Toms',
            'rack and floor toms, roto and concert toms',
            '<ellipse cx="7" cy="8" rx="4.5" ry="2"/><path d="M2.5 8v5c0 1.1 2 2 4.5 2s4.5-.9 4.5-2V8"/><ellipse cx="17" cy="11" rx="4.5" ry="2"/><path d="M12.5 11v5c0 1.1 2 2 4.5 2s4.5-.9 4.5-2v-5"/>',
        ),
        _t(
            'in_cymbal',
            'Cymbals',
            'crash, ride, splash, china, bell',
            '<path d="M3 9h18"/><path d="M12 9v11"/><path d="M6 9l6-4 6 4"/><path d="M9 20h6"/>',
        ),
        _t(
            'in_hihat',
            'Hi-hat',
            'closed, open, pedal and half-open hats',
            '<path d="M4 8h16M4 12h16"/><path d="M12 12v8"/><path d="M9 20h6"/>',
        ),
        _t(
            'in_perc',
            'Hand percussion',
            'congas, bongos, cajon, djembe, tabla, frame drums',
            '<path d="M6 21V9a4 4 0 0 1 8 0v12"/><ellipse cx="10" cy="9" rx="4" ry="1.8"/><path d="M16 21V12a3 3 0 0 1 6 0v9"/><ellipse cx="19" cy="12" rx="3" ry="1.4"/>',
        ),
        _t(
            'in_shaker',
            'Shakers & small',
            'shaker, tambourine, triangle, claves, cabasa, guiro',
            '<path d="M9 4h6l1 14a4 4 0 0 1-8 0z"/><circle cx="11" cy="10" r=".7"/><circle cx="13.5" cy="13" r=".7"/><circle cx="11" cy="15" r=".7"/>',
        ),
        _t(
            'in_timpani',
            'Timpani',
            'tuned kettle drums, rolls and glissandi',
            '<path d="M4 10a8 4 0 0 1 16 0v4a8 5 0 0 1-16 0z"/><path d="M7 18v3M17 18v3"/>',
        ),
        _t(
            'in_mallet',
            'Marimba / xylophone',
            'wooden bar percussion',
            '<path d="M4 6h3v13H4zM8.5 5h3v15h-3zM13 6.5h3v12h-3zM17.5 8h3v9h-3z"/>',
        ),
        _t(
            'in_vibes',
            'Vibraphone',
            'metal bars with motor tremolo',
            '<path d="M4 6h3v10H4zM9 5h3v12H9zM14 6h3v10h-3z"/><path d="M3 20h18"/><circle cx="20" cy="11" r="2"/>',
        ),
        _t(
            'in_glock',
            'Glockenspiel',
            'glockenspiel, celesta, toy piano',
            '<path d="M3 8h18v8H3z"/><path d="M7 8v8M11 8v8M15 8v8"/><path d="M5 5l2 3M19 5l-2 3"/>',
        ),
        _t(
            'in_bells',
            'Bells & chimes',
            'tubular bells, wind chimes, hand bells, gong-adjacent',
            '<path d="M6 3v12M10 3v16M14 3v13M18 3v10"/><path d="M4 3h16"/>',
        ),
        _t(
            'in_gong',
            'Gong & tam-tam',
            'gong, tam-tam, cymbal swell, bowed metal',
            '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>',
        ),
        _t(
            'in_choir',
            'Choir',
            'SATB pads, ahs, ohs and syllabic choirs',
            '<circle cx="7" cy="7" r="2.6"/><path d="M2.5 17c0-3 2-4.6 4.5-4.6S11.5 14 11.5 17"/><circle cx="16.5" cy="8.5" r="2.4"/><path d="M12.5 17c0-2.7 1.8-4.2 4-4.2s4 1.5 4 4.2"/>',
        ),
        _t(
            'in_voice',
            'Solo voice',
            'solo sung notes, vowels and vocal one-shots',
            '<rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
        ),
        _t(
            'in_synth',
            'Synth',
            'the synthesised half of the library',
            '<path d="M3 15c2-8 4-8 6 0s4 8 6 0 4-8 6 0"/><path d="M3 20h18"/>',
        ),
        _t(
            'in_pad',
            'Pad',
            'slow, sustained, wide synthetic beds',
            '<path d="M3 14c4-6 8 6 12 0s4-4 6-2"/><path d="M3 19h18" stroke-dasharray="3 3"/>',
        ),
        _t('in_lead', 'Lead', 'monophonic synth leads, portamento and all', '<path d="M4 18l4-12 4 9 3-6 5 9"/>'),
        _t(
            'in_pluck',
            'Synth pluck',
            'short, decaying synthetic attacks',
            '<path d="M4 6v13"/><path d="M4 7c8 0 12 3 16 11"/><path d="M4 19h16"/>',
        ),
        _t(
            'in_world',
            'World & folk',
            'ethnic instruments outside the orchestral families',
            '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c4 4 4 14 0 18M12 3C8 7 8 17 12 21"/>',
        ),
        _t(
            'in_fxinstr',
            'FX instrument',
            'risers, impacts, drones and designed musical FX',
            '<path d="M3 20L21 4"/><path d="M11 20l10-8"/><path d="M3 12l8-8"/>',
        ),
    ],
)

# What the player DOES to the note.  The library tags these per file
# (instrument / pitch / dynamic / articulation / round-robin were the axes the
# instruments category was created for) — these are the articulation half.
_sec(
    'artic',
    'Articulation',
    'left',
    [
        _t('ar_sustain', 'Sustain', 'the held note, full length', '<path d="M4 12h16"/><path d="M4 9v6M20 9v6"/>'),
        _t(
            'ar_staccato',
            'Staccato',
            'short, detached notes',
            '<circle cx="6" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18" cy="12" r="1.6"/>',
        ),
        _t(
            'ar_legato',
            'Legato',
            'notes joined without a re-attack',
            '<circle cx="6" cy="15" r="2"/><circle cx="18" cy="15" r="2"/><path d="M6 11c3-5 9-5 12 0"/>',
        ),
        _t('ar_marcato', 'Marcato', 'hard accented attack', '<path d="M5 16l7-9 7 9"/><path d="M4 20h16"/>'),
        _t('ar_accent', 'Accent', 'one note louder than its neighbours', '<path d="M4 8l14 4-14 4"/>'),
        _t(
            'ar_tenuto',
            'Tenuto',
            'held for its full written value',
            '<path d="M5 15h14"/><circle cx="12" cy="9" r="3"/>',
        ),
        _t(
            'ar_pizz',
            'Pizzicato',
            'plucked, not bowed',
            '<path d="M6 4v16"/><path d="M6 12c6 0 9-3 12-6"/><circle cx="18" cy="6" r="1.6"/>',
        ),
        _t(
            'ar_arco',
            'Arco',
            'bowed',
            '<path d="M3 18L21 6"/><path d="M3 18l2 2M21 6l-2-2"/><path d="M8 6v12" stroke-dasharray="2 2"/>',
        ),
        _t('ar_spicc', 'Spiccato', 'bounced bow — short and springy', '<path d="M3 16c2-6 4 6 6 0s4 6 6 0 4 6 6 0"/>'),
        _t('ar_tremolo', 'Tremolo', 'rapid repetition on one pitch', '<path d="M4 8l16-3M4 12l16-3M4 16l16-3"/>'),
        _t(
            'ar_trill',
            'Trill',
            'alternation with the note above',
            '<path d="M4 16V8l3 8V8"/><path d="M10 12c2-4 4 4 6 0s3-3 4-1"/>',
        ),
        _t(
            'ar_mordent',
            'Mordent / turn',
            'ornament around the written note',
            '<path d="M3 14c2-5 4 5 6 0s4 5 6 0 3-3 6-1"/>',
        ),
        _t(
            'ar_gliss',
            'Glissando',
            'a slide through every pitch between',
            '<path d="M4 19L20 5"/><circle cx="4" cy="19" r="1.8"/><circle cx="20" cy="5" r="1.8"/>',
        ),
        _t(
            'ar_portam',
            'Portamento',
            'a smooth pitch carry between two notes',
            '<path d="M4 18c6 0 10-12 16-12"/><circle cx="4" cy="18" r="1.6"/><circle cx="20" cy="6" r="1.6"/>',
        ),
        _t(
            'ar_bend',
            'Bend',
            'pitch bent up or down within the note',
            '<path d="M4 18h6c4 0 4-12 10-12"/><path d="M17 3l3 3-3 3"/>',
        ),
        _t(
            'ar_vibrato',
            'Vibrato',
            'periodic pitch wobble on the held note',
            '<path d="M3 12c1.5-5 3-5 4.5 0s3 5 4.5 0 3-5 4.5 0 3 5 4.5 0"/>',
        ),
        _t(
            'ar_harmonic',
            'Harmonic',
            'natural and artificial harmonics',
            '<circle cx="12" cy="8" r="3"/><path d="M12 11v10"/><path d="M8 21h8"/>',
        ),
        _t(
            'ar_mute',
            'Mute',
            'con sordino, cup, harmon, straight',
            '<path d="M5 9h4l5-4v14l-5-4H5z"/><path d="M17 8l4 8M21 8l-4 8"/>',
        ),
        _t(
            'ar_palmmute',
            'Palm mute',
            "the guitar family's damped attack",
            '<path d="M4 12h16"/><path d="M7 8v8M11 9v6M15 9v6M19 8v8"/><path d="M3 5l18 14" stroke-dasharray="3 2"/>',
        ),
        _t(
            'ar_slide',
            'Slide',
            'fretted slide between two positions',
            '<path d="M4 8h16M4 16h16"/><path d="M6 8l12 8"/>',
        ),
        _t(
            'ar_hammer',
            'Hammer / pull',
            'hammer-on and pull-off',
            '<path d="M5 16V8M19 16V8"/><path d="M5 10c4-5 10-5 14 0"/><path d="M5 14c4 5 10 5 14 0" stroke-dasharray="2 2"/>',
        ),
        _t(
            'ar_slap',
            'Slap & pop',
            'the bass thumb and the finger pop',
            '<path d="M4 18l5-11 3 6 3-9 5 14"/><circle cx="9" cy="7" r="1.4"/>',
        ),
        _t(
            'ar_flutter',
            'Flutter',
            'flutter tongue on winds and brass',
            '<path d="M3 9c3-4 6 4 9 0s6-4 9 0"/><path d="M3 15c3-4 6 4 9 0s6-4 9 0"/>',
        ),
        _t('ar_growl', 'Growl', 'the reed and brass growl', '<path d="M3 12c2-6 3 6 5 0s3 6 5 0 3 6 5 0 3 4 3 2"/>'),
        _t(
            'ar_fall',
            'Fall / doit',
            'the brass fall-off and the lift into a note',
            '<path d="M4 7h9c4 0 5 5 6 10"/><path d="M17 20l2-3 2 3" stroke-dasharray="2 2"/>',
        ),
        _t(
            'ar_roll',
            'Roll',
            'the percussion roll, buzz and press',
            '<path d="M4 16h16"/><path d="M5 8v8M7 6v10M9 8v8M11 6v10M13 8v8M15 6v10M17 8v8M19 6v10"/>',
        ),
        _t(
            'ar_flam',
            'Flam & drag',
            'grace notes ahead of the main stroke',
            '<circle cx="6" cy="15" r="1.4"/><circle cx="10" cy="12" r="2.4"/><path d="M6 13.6V6M12.4 12V5"/>',
        ),
        _t(
            'ar_rimshot',
            'Rimshot & rim',
            'the rim click and the full rimshot',
            '<ellipse cx="12" cy="13" rx="8" ry="4"/><path d="M4 13v3M20 13v3"/><path d="M18 5l-5 5"/>',
        ),
        _t(
            'ar_ghost',
            'Ghost note',
            'the barely-there stroke between the hits',
            '<circle cx="7" cy="12" r="2.4"/><circle cx="14" cy="12" r="1.4" stroke-dasharray="1 2"/><circle cx="19" cy="12" r="2.4"/>',
        ),
        _t(
            'ar_deadnote',
            'Dead note',
            'the pitchless fretted click',
            '<path d="M6 6l12 12M18 6L6 18"/><path d="M3 12h3M18 12h3"/>',
        ),
        _t(
            'ar_rr',
            'Round robin',
            'which alternate take of the same note is used',
            '<path d="M5 8h11a3 3 0 0 1 0 6H8"/><path d="M8 11l-3 3 3 3"/><circle cx="19" cy="6" r="1.6"/>',
        ),
        _t(
            'ar_release',
            'Release sample',
            'the sound the note makes when it STOPS',
            '<path d="M4 6v12"/><path d="M4 8c8 0 12 4 16 10"/><circle cx="20" cy="18" r="1.6"/>',
        ),
    ],
)
