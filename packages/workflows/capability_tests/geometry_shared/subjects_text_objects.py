# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.subjects_text_objects — SUBJECTS: Text & number (13) and Objects (16).

Verbatim from the former geometry_shared.py, lines 682-900.
"""

from __future__ import annotations

from .constants import _mat, _ocr, _ocr_has
from .subjects_people_body import SUBJECTS


SUBJECTS.update(
    {
        # ── Text & number (13) — lettering must be GEOMETRY or a legible map, and OCR decides ──
        'model_text_letters': (
            'three carved letters',
            'A flat oak board half a metre wide with the three capital letters A B C carved into it as raised geometry, nothing else on the board.',
            (1, 6),
            ('max', 0.40, 0.70),
            _ocr('abc'),
        ),
        'model_text_word': (
            'a carved word',
            'A flat oak board half a metre wide with the single word KATTENBURG carved into it as raised capital letters, nothing else on the board.',
            (1, 14),
            ('max', 0.40, 0.80),
            _ocr('kattenburg'),
        ),
        'model_text_sentence': (
            'a carved sentence',
            'A flat stone slab a metre wide with the sentence HIER RUST EEN ZEEMAN cut into it in capitals on two lines, nothing else.',
            (1, 24),
            ('max', 0.80, 1.30),
            _ocr_has('hier', 'rust', 'zeeman'),
        ),
        'model_number_digits': (
            'four carved digits',
            'A flat oak board forty centimetres wide with the four digits 1 6 7 1 carved into it as raised numerals, nothing else on the board.',
            (1, 8),
            ('max', 0.30, 0.60),
            _ocr('1671'),
        ),
        'model_number_specific': (
            'a specific carved number',
            'A stone tablet thirty centimetres wide with the number 47 cut into it in deep numerals, nothing else on the tablet.',
            (1, 4),
            ('max', 0.22, 0.45),
            _ocr('47'),
        ),
        'model_number_date': (
            'a carved date',
            'A stone lintel a metre wide with the date 1671 cut into it in numerals above a small carved rosette, nothing else.',
            (1, 10),
            ('max', 0.80, 1.30),
            _ocr_has('1671'),
        ),
        'model_number_roman': (
            'carved roman numerals',
            'A stone plaque forty centimetres wide with the roman numerals MDCLXXI cut into it in capitals, nothing else on the plaque.',
            (1, 10),
            ('max', 0.30, 0.60),
            _ocr('mdclxxi'),
        ),
        'model_clock_face': (
            'a clock face reading twenty past three',
            'A church clock face one metre across with roman numerals I to XII around the rim, the hour hand on III and the minute hand on the twenty-minute mark.',
            (3, 20),
            ('max', 0.85, 1.20),
            [{'check': 'clock_reads', 'time': '3:20', 'tolerance': 5, 'when': 'sheet'}],
        ),
        'model_handwriting': (
            'a written line on paper',
            'A flat sheet of paper thirty centimetres wide lying on a table, the words goede reis written across it in flowing ink script as raised geometry.',
            (2, 20),
            ('max', 0.25, 0.60),
            _ocr_has('goede'),
        ),
        'model_signage': (
            'a hanging shop sign',
            'A hanging wooden shop sign half a metre wide on an iron bracket, the word BROOD painted across it in capitals. Sign and bracket separate.',
            (2, 12),
            ('max', 0.40, 0.90),
            _ocr_has('brood'),
        ),
        'model_book_page': (
            'an open book with text on the page',
            'An open book thirty centimetres wide lying flat, both pages covered in five lines of printed text, the covers and pages as separate geometry.',
            (3, 20),
            ('max', 0.25, 0.50),
            None,
        ),
        'model_map_labels': (
            'a map with place labels',
            'A flat paper chart sixty centimetres wide lying on a table, a coastline drawn on it and the three labels AMSTERDAM TEXEL and IJ lettered beside it.',
            (1, 30),
            ('max', 0.50, 0.90),
            _ocr_has('amsterdam', 'texel'),
        ),
        'model_symbol_crest': (
            'a carved crest',
            'A stone shield forty centimetres tall carved with a heraldic lion rampant above three stars, the carving in relief, nothing else.',
            (1, 12),
            ('y', 0.30, 0.60),
            None,
        ),
        # ── Objects (16) ──
        'model_tool_hand': (
            'a hand tool',
            "One carpenter's hammer with an oak handle and an iron head, thirty-five centimetres long, lying flat. Handle and head separate.",
            (2, 5),
            ('max', 0.28, 0.50),
            _mat('wood', 'iron'),
        ),
        'model_furniture': (
            'a wooden chair',
            'One oak chair with four legs, a plank seat and a slatted back, standing on flat ground. Legs, seat and back as separate parts.',
            (4, 20),
            ('y', 0.80, 1.20),
            [{'check': 'mesh_part_names', 'terms': ['leg', 'seat'], 'when': 'glb'}],
        ),
        'model_container_barrel': (
            'a wooden barrel',
            'One oak barrel ninety centimetres tall with five iron hoops and a flat lid, standing upright. Staves, hoops and lid as separate parts.',
            (3, 20),
            ('y', 0.70, 1.10),
            _mat('oak', 'iron'),
        ),
        'model_rope_rigging': (
            'a coil of rope',
            'One coil of hemp rope three centimetres thick, coiled flat in five turns half a metre across, lying on the ground.',
            (1, 8),
            ('max', 0.40, 0.75),
            None,
        ),
        'model_weapon': (
            'a sword',
            'One straight sword a metre long with a steel blade, a crossguard and a wrapped grip, lying flat. Blade, guard and grip separate.',
            (3, 8),
            ('max', 0.85, 1.20),
            _mat('steel'),
        ),
        'model_instrument_music': (
            'a stringed instrument',
            'One lute seventy centimetres long with a rounded body, a fretted neck and six strings as separate geometry, lying flat.',
            (3, 20),
            ('max', 0.55, 0.95),
            None,
        ),
        'model_lantern': (
            'a metal and glass lantern',
            'One iron lantern thirty centimetres tall with four glass panes, a hinged top and a carrying ring, standing upright. Frame, panes and ring separate.',
            (6, 20),
            ('y', 0.22, 0.45),
            _mat('iron', 'glass'),
        ),
        'model_wheel_cart': (
            'a spoked cart wheel',
            'One wooden cart wheel one metre across with twelve spokes, a hub and an iron rim, standing upright. Hub, spokes and rim separate.',
            (5, 25),
            ('max', 0.85, 1.20),
            [{'check': 'mesh_part_names', 'terms': ['spoke', 'hub'], 'when': 'glb'}],
        ),
        'model_boat': (
            'a small rowing boat',
            'One clinker-built rowing boat four metres long with a plank hull, three thwarts and two oars, sitting level. Hull, thwarts and oars separate.',
            (5, 30),
            ('max', 3.50, 5.00),
            None,
        ),
        'model_ship_rigging': (
            'a mast with standing rigging',
            "One ship's mast eight metres tall with a crosstree, four shrouds running down to the sides and a halyard. Mast and each line separate.",
            (5, 30),
            ('y', 7.00, 9.50),
            None,
        ),
        'model_sail': (
            'a set square sail',
            'One square canvas sail four metres wide bent to a yard, bellied by wind, with three reef lines along the foot. Sail and yard separate.',
            (2, 12),
            ('max', 3.50, 5.00),
            _mat('canvas'),
        ),
        'model_quill_ink': (
            'a quill and inkpot',
            'One goose-feather quill lying beside a squat glass inkpot with its stopper out. Quill, pot and stopper as three separate objects.',
            (3, 6),
            ('max', 0.20, 0.40),
            None,
        ),
        'model_coins': (
            'a pile of coins',
            'Seven silver coins three centimetres across, five lying flat in a loose pile and two standing on edge against it. Seven separate objects.',
            (7, 12),
            ('max', 0.07, 0.20),
            None,
        ),
        'model_basket': (
            'a woven basket',
            'One wicker basket forty centimetres across with a woven body, a rolled rim and one handle, standing empty and upright.',
            (2, 30),
            ('max', 0.32, 0.60),
            None,
        ),
        'model_glassware': (
            'a glass drinking vessel',
            'One tall glass goblet twenty centimetres high with a hollow stem and a flared foot, standing upright and empty.',
            (1, 4),
            ('y', 0.15, 0.30),
            _mat('glass'),
        ),
        'model_mirror': (
            'a framed mirror',
            'One oval mirror fifty centimetres tall in a carved wooden frame, standing upright, the glass as its own flat surface. Frame and glass separate.',
            (2, 8),
            ('y', 0.40, 0.70),
            [
                {
                    'check': 'pbr_value_range',
                    'field': 'metallic',
                    'shell': 'smallest',
                    'min': 0.7,
                    'max': 1.0,
                    'when': 'glb',
                }
            ],
        ),
    }
)
