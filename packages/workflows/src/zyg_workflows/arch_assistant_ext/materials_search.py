# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""materials_search — the assistant's door to the PBR material library.

2026-09-07. The studio's material rail holds ~1,500 measured CC0 surfaces
(ambientCG `acg_*`, Poly Haven `pht_*`, decals, atlases) that tile at their
real size; the assistant could only name the 21 flat presets, so every wall it
drew was a flat grey hex. This module adds search_materials(query) over the
library, and arch_assistant.MATERIALS accepts any library kind, so every
`material` argument of every tool now takes a library id too.

No new kinds: a material is stored on the record as its kind string, exactly
as the Paint tool stores it.
"""

from __future__ import annotations

import re

from zyg_workflows.arch_assistant import Drawing, MATERIALS

KINDS: dict = {}
OPENINGS: list = []

PROMPT = (
    'MATERIALS: besides the flat presets (mat_concrete, mat_brick, mat_glass ...) there is a library of about '
    '1,500 photographic PBR surfaces that tile at their measured size. search_materials(query) finds them by '
    'words ("rough concrete", "board-formed concrete", "travertine", "weathered oak planks", "corten", "terrazzo") '
    'and returns ids like acg_Concrete034 or pht_rock_wall_08; pass such an id as the `material` argument of any '
    'drawing tool or of set_material. Tone words count and are measured off the texture ("white marble", "dark '
    'oak"): every hit says its tone, black/dark/mid/light/white. Prefer a library material whenever the user '
    'names a real finish; keep the flat presets for massing studies and when the user says "plain".'
)

_IDX: list | None = None

# How light a surface is, in words. The measured bucket lives on the catalogue
# entry (architecture_materials stamps 'tone' from the albedo map); these are
# the words a person uses for it. White and light name each other, as do black
# and dark, because "a white marble floor" and "a light marble floor" are the
# same request and the bucket edge between them is arbitrary.
TONE_WORDS = {
    'white': ('white', 'light'),
    'light': ('light', 'white'),
    'mid': ('mid',),
    'dark': ('dark', 'black'),
    'black': ('black', 'dark'),
}
ALL_TONE_WORDS = {w for ws in TONE_WORDS.values() for w in ws}


def _index() -> list:
    global _IDX
    if _IDX is None:
        rows = []
        try:
            from zyg_workflows import architecture_materials as AM

            cat = AM.catalogue()
            for g in cat.get('groups') or []:
                grp = str(g.get('g') or '')
                for it in g.get('items') or []:
                    p = it.get('p') or {}
                    sz = p.get('size_m') or [1, 1]
                    tone = str(p.get('tone') or '')
                    tw = TONE_WORDS.get(tone, ())
                    rows.append(
                        {
                            'id': str(it.get('kind') or ''),
                            'n': str(it.get('n') or ''),
                            'group': grp,
                            'size': f'{float(sz[0]):g}x{float(sz[1]):g} m',
                            'note': str(it.get('note') or ''),
                            'tone': tone,
                            'lum': p.get('lum'),
                            'tone_words': set(tw),
                            'hay': (
                                f'{it.get("n") or ""} {grp} {it.get("kind") or ""} {it.get("note") or ""}'
                                + (f' tone:{tone} {" ".join(tw)}' if tone else '')
                            )
                            .lower()
                            .replace('_', ' '),
                        }
                    )
        except Exception as e:  # noqa: BLE001
            rows = [
                {
                    'id': '',
                    'n': f'(library unavailable: {e})',
                    'group': '',
                    'size': '',
                    'note': '',
                    'tone': '',
                    'lum': None,
                    'tone_words': set(),
                    'hay': '',
                }
            ]
        _IDX = rows
    return _IDX


_SYN = {
    'concrete': ['concrete', 'cement'],
    'wood': ['wood', 'planks', 'oak', 'timber', 'parquet'],
    'timber': ['wood', 'planks', 'oak', 'timber'],
    'stone': ['stone', 'rock', 'granite', 'travertine', 'marble', 'slate'],
    'brick': ['brick', 'bricks'],
    'metal': ['metal', 'steel', 'corten', 'rust', 'aluminium'],
    'glass': ['glass'],
    'plaster': ['plaster', 'stucco', 'render'],
    'tile': ['tile', 'tiles', 'terrazzo'],
    'roof': ['roof', 'roofing', 'shingles', 'tiles'],
    'grass': ['grass', 'lawn'],
    'gravel': ['gravel', 'pebbles'],
    'paving': ['paving', 'pavement', 'cobble', 'flagstone', 'setts'],
}


def _word_score(w: str, r: dict) -> int:
    """What one query word is worth on one row. 0 means the word missed.

    Every word of the query counts, and where it lands decides how much: the
    NAME is what the surface is, the GROUP is what family it belongs to, the
    tone is how light it is, and the rest of the haystack (id, tile note) is
    the weakest evidence there is."""
    alts = _SYN.get(w, [w])
    name = ' ' + re.sub(r'[^a-z0-9]+', ' ', r['n'].lower()) + ' '
    grp = ' ' + re.sub(r'[^a-z0-9]+', ' ', r['group'].lower()) + ' '
    s = 0
    if any(f' {a} ' in name for a in alts):
        s += 3
    if any(f' {a} ' in grp for a in alts):
        s += 2
    if w in ALL_TONE_WORDS and w in r['tone_words']:
        # The tone asked for, exactly, is worth more than its neighbour, so
        # "white marble" answers with the white ones before the light ones.
        s += 2 if w == r['tone'] else 1
    elif not s and any(a in r['hay'] for a in alts):
        s += 1
    return s


def search(query: str, limit: int = 10) -> list:
    words = [w for w in re.split(r'[^a-z0-9]+', str(query or '').lower()) if w]
    if not words:
        return []
    scored = []
    for r in _index():
        if not r['id']:
            continue
        hits = [_word_score(w, r) for w in words]
        s = sum(hits)
        if s:
            # A row that answers more of the question comes first, whatever the
            # points say: "white marble floor" must not be won by a very white
            # floor that is not marble.
            scored.append((-sum(1 for h in hits if h), -s, len(r['n']), r['n'], r))
    scored.sort(key=lambda t: t[:4])
    return [t[-1] for t in scored[: max(1, min(int(limit or 10), 40))]]


def t_search_materials(d: Drawing, a, query, limit=10):
    hits = search(query, limit)
    if not hits:
        presets = ', '.join(MATERIALS[:12])
        return f'no library material matches "{query}" — try another word, or use a preset: {presets} ...'
    lines = [f'{len(hits)} material(s) for "{query}", as "id — name (group), tile size, tone":']
    for r in hits:
        tone = f', {r["tone"]}' if r.get('tone') else ''
        lines.append(f'{r["id"]} — {r["n"]} ({r["group"]}), {r["size"]}{tone}')
    return '\n'.join(lines)


TOOLS = [
    (
        {
            'name': 'search_materials',
            'description': 'Find a photographic PBR material in the library (~1,500 CC0 surfaces that tile at their real '
            'size) by words: "rough concrete", "red brick", "travertine", "oak planks", "corten steel", '
            '"terrazzo". Tone words are understood and measured off the texture itself — "white marble", '
            '"dark oak", "light plaster", "black tiles" — so ask for the shade you mean; each hit reports '
            'its tone (black/dark/mid/light/white). Returns ids (acg_..., pht_...) to pass as `material` to '
            'any drawing tool or to set_material. Search before naming a library material; the ids are not '
            'guessable.',
            'input_schema': {
                'type': 'object',
                'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer'}},
                'required': ['query'],
            },
        },
        t_search_materials,
    ),
]

EXAMPLES = [
    {
        'ask': 'make the tower walls rough board-formed concrete',
        'calls': [
            {'tool': 'search_materials', 'args': {'query': 'board formed concrete rough'}},
            {
                'tool': 'set_material',
                'args': {'which': 'tower', 'material': 'acg_Concrete0XX (the id search_materials returned)'},
            },
        ],
    },
    {'ask': 'find me a red brick', 'calls': [{'tool': 'search_materials', 'args': {'query': 'red brick', 'limit': 5}}]},
    {
        'ask': 'what oak plank floors are in the library?',
        'calls': [{'tool': 'search_materials', 'args': {'query': 'oak planks floor'}}],
    },
]
