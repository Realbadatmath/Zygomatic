# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""glossary_examples.tools — topic aliases, explain(), and the three tool callables."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.glossary_examples.explain_sheets import EXPLAIN
from zyg_workflows.arch_assistant_ext.glossary_examples.terms_de_fr import language_of, translate, units
from zyg_workflows.arch_assistant_ext.glossary_examples.terms_nl import Drawing, _norm

_ALIAS = {
    'wall': 'walls',
    'partition': 'walls',
    'curved': 'curved walls',
    'curve': 'curved walls',
    'arc': 'curved walls',
    'round': 'curved walls',
    'tower': 'curved walls',
    'storey': 'storeys',
    'story': 'storeys',
    'floors': 'storeys',
    'floor': 'storeys',
    'height': 'storeys',
    'verdieping': 'storeys',
    'geschoss': 'storeys',
    'window': 'windows',
    'glass': 'windows',
    'glazing': 'windows',
    'raam': 'windows',
    'door': 'doors',
    'opening': 'doors',
    'deur': 'doors',
    'roof': 'roofs',
    'dak': 'roofs',
    'skylight': 'roofs',
    'dormer': 'roofs',
    'stair': 'stairs',
    'lift': 'stairs',
    'elevator': 'stairs',
    'escalator': 'stairs',
    'trap': 'stairs',
    'column': 'columns',
    'beam': 'columns',
    'structure': 'columns',
    'frame': 'columns',
    'truss': 'columns',
    'pergola': 'columns',
    'balcony': 'balconies',
    'facade': 'balconies',
    'gevel': 'balconies',
    'parapet': 'balconies',
    'canopy': 'balconies',
    'louvre': 'balconies',
    'landscape': 'site',
    'garden': 'site',
    'tree': 'site',
    'trees': 'site',
    'fence': 'site',
    'road': 'site',
    'water': 'site',
    'pool': 'infinity pool',
    'weir': 'infinity pool',
    'rooftop pool': 'infinity pool',
    'tuin': 'site',
    'hill': 'terrain',
    'slope': 'terrain',
    'morph': 'massing',
    'mass': 'massing',
    'shape': 'massing',
    'furnish': 'furniture',
    'chair': 'furniture',
    'kitchen': 'furniture',
    'bathroom': 'furniture',
    'room': 'rooms',
    'interior': 'rooms',
    'corridor': 'rooms',
    'ceiling': 'rooms',
    'mep': 'services',
    'solar': 'services',
    'gutter': 'services',
    'chimney': 'services',
    'pipe': 'services',
    'radiator': 'services',
    'vehicle': 'vehicles',
    'car': 'vehicles',
    'crane': 'vehicles',
    'scaffold': 'vehicles',
    'edit': 'editing',
    'move': 'editing',
    'rotate': 'editing',
    'mirror': 'editing',
    'array': 'editing',
    'copy': 'editing',
    'view': 'views',
    'camera': 'views',
    'sun': 'views',
    'section': 'views',
    'measure': 'measuring',
    'dimension': 'measuring',
    'quantity': 'measuring',
    'bom': 'measuring',
    'area': 'measuring',
    'export': 'blender',
    'mesh': 'blender',
    'bpy': 'blender',
    'modifier': 'blender',
    'bevel': 'blender',
    'boolean': 'blender',
    'subsurf': 'blender',
    'shader': 'blender',
    'asset': 'assets',
    'library': 'assets',
    'typology': 'typologies',
    'house': 'typologies',
    'building': 'typologies',
    'office': 'typologies',
    'church': 'typologies',
    'huis': 'typologies',
    'material': 'materials',
    'colour': 'materials',
    'color': 'materials',
    'texture': 'materials',
    'cell': 'cells',
    'grid': 'cells',
    'coordinate': 'cells',
    'address': 'cells',
    'redo': 'undo',
    'delete': 'undo',
    'mistake': 'undo',
    'base_height': 'ground',
    'ground_height': 'ground',
    'level': 'ground',
    'flatten': 'ground',
    'flatten_pad': 'ground',
    'drape': 'ground',
    'tiling': 'ground',
    'seat': 'ground',
    'metres_per_cell': 'scale',
    'set_grid_scale': 'scale',
    'kilometre': 'scale',
    'kilometer': 'scale',
    'size': 'scale',
    'sizes': 'scale',
    'real size': 'scale',
    'proportion': 'proportions',
    'describe_landscape': 'proportions',
    'buried': 'proportions',
    'floating': 'proportions',
    'sanity': 'proportions',
    'sculpt': 'sculpting',
    'dig out': 'sculpting',
    'raise': 'sculpting',
    'heightfield': 'sculpting',
    'make_ground': 'sculpting',
    'raise_ground': 'sculpting',
    'lower_ground': 'sculpting',
    'level_ground': 'sculpting',
    'describe_ground': 'sculpting',
    'carve_river': 'sculpting',
    'fill_lake': 'sculpting',
    'fill_sea': 'sculpting',
    'scene': 'scenes',
    'compose_landscape': 'scenes',
    'suggest_scene': 'scenes',
    'recipe': 'scenes',
    'alpine': 'scenes',
    'river_valley': 'scenes',
    'forest_lake': 'scenes',
    # the drawing-skills sheets (2026-09-08)
    'presentation': 'quality',
    'luxury': 'quality',
    'photoreal': 'quality',
    'placeholder': 'quality',
    'real model': 'quality',
    'toy': 'quality',
    'finish': 'quality',
    'finishes': 'quality',
    'porte-cochere': 'entrance',
    'porte cochere': 'entrance',
    'porte-cochère': 'entrance',
    'porte cochère': 'entrance',
    'entree': 'entrance',
    'approach': 'entrance',
    'driveway': 'entrance',
    'drive': 'entrance',
    'lobby': 'entrance',
    'front door': 'entrance',
    'arrival': 'entrance',
    'infinity': 'infinity pool',
    'roof deck': 'roof',
    'rooftop': 'roof',
    'deck': 'roof',
    'penthouse': 'roof',
    'roof pool': 'infinity pool',
    'roof terrace': 'roof',
    'overrun': 'roof',
    'spandrel': 'facade',
    'string course': 'facade',
    'string_course': 'facade',
    'curtain wall': 'facade',
    'mullion': 'facade',
    'transom': 'facade',
    'skin': 'facade',
    'core': 'facade',
    'hollow': 'facade',
    'check': 'render',
    'design_check': 'render',
    'from_cell': 'render',
    'to_cell': 'render',
    'focal': 'render',
    'lens': 'render',
    'picture': 'render',
    'photo': 'render',
    'shot': 'render',
}

TOPICS = sorted(EXPLAIN)


def explain(topic) -> str:
    """The paragraph for a topic, or '' when nothing matches."""
    t = _norm(topic)
    if not t:
        return ''
    if t in EXPLAIN:
        return EXPLAIN[t]
    if t in _ALIAS:
        return EXPLAIN[_ALIAS[t]]
    en = translate(t)
    if en and _norm(en) in _ALIAS:
        return EXPLAIN[_ALIAS[_norm(en)]]
    if en and _norm(en) in EXPLAIN:
        return EXPLAIN[_norm(en)]
    for k in TOPICS:  # 'roof lights' -> 'roofs'
        if k in t or t in k:
            return EXPLAIN[k]
    for k, v in _ALIAS.items():
        if k in t.split() or t in k:
            return EXPLAIN[v]
    return ''


# ── the tools ────────────────────────────────────────────────────────────────
def t_explain(d: Drawing, a, topic=''):
    txt = explain(topic)
    if not txt:
        return 'refused: no glossary entry for "%s" — topics are: %s' % (str(topic)[:40], ', '.join(TOPICS))
    return txt


def t_translate(d: Drawing, a, word=''):
    w = str(word or '').strip()
    if not w:
        return 'refused: give a word to translate'
    en = translate(w)
    if not en:
        return (
            f'refused: "{w[:40]}" is not in the Dutch/German/French glossary — '
            f'use the English studio term, or call explain(topic) for the tool that fits'
        )
    lang = language_of(w) or 'Dutch/German/French'
    return f'{w} ({lang}) = {en}'


def t_units(d: Drawing, a, text=''):
    out = units(text)
    if not out:
        return (
            'refused: nothing to convert in "%s" — this tool takes feet, inches, yards, or a count of '
            'floors/verdiepingen/etages' % str(text)[:60]
        )
    return out


TOOLS = [
    (
        {
            'name': 'explain',
            'description': 'How to ask for something in this studio: a paragraph naming the tool that does it and the arguments it takes. Topics: walls, curved walls, storeys, windows, doors, roofs, stairs, columns, balconies, site, terrain, massing, furniture, rooms, services, vehicles, editing, views, measuring, blender, assets, typologies, materials, cells, undo, for landscapes landscape, scenes, mountains, rivers, forests, cliffs, coast, fields, ground, sculpting, scale, proportions, and the drawing-skills sheets quality (real models and PBR finishes), entrance (porte-cochere proportions), roof (decks, roof pools, infinity edges), facade (slabs that read, cores), render (how to check with a camera) and blender (the bpy pro sheet). Call it when you are unsure which tool fits a request; call explain("ground"), explain("sculpting") and explain("scale") before drawing a landscape, and the skills sheets before a presentation model.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic': {'type': 'string', 'description': 'one of the topics, or any word close to one'}
                },
                'required': ['topic'],
            },
        },
        t_explain,
    ),
    (
        {
            'name': 'translate',
            'description': 'The English studio term for a Dutch, German or French building word (gevel = facade, Geschoss = storey, toiture = roof). Call it before guessing what a foreign word means; the answer names the term the tools and kinds use.',
            'input_schema': {'type': 'object', 'properties': {'word': {'type': 'string'}}, 'required': ['word']},
        },
        t_translate,
    ),
    (
        {
            'name': 'units',
            'description': 'Convert imperial lengths to metres (feet, inches, yards) and a count of floors / verdiepingen / etages / Geschosse to storeys of 2.7 m. Call it whenever the request is not already in metres and storeys.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'text': {
                        'type': 'string',
                        'description': 'the phrase to convert, e.g. "30 feet" or "5 verdiepingen"',
                    }
                },
                'required': ['text'],
            },
        },
        t_units,
    ),
]
