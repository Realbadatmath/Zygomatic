# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""landscape_composer/tools.py — the three tools, the scene-word index, TOOLS and EXAMPLES.

Moved verbatim out of landscape_composer.py (lines 1508-1884).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.landscape_composer.constants import (
    BOULDER_M,
    Drawing,
    GROUND_KIND,
    GROUND_TOL,
    LANDSCAPE_KINDS,
    MAX_METRES,
    MIN_CELLS,
    MIN_METRES,
    SCENES,
    TREE_H,
    _A,
    block_bounds,
    unicodedata,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.checks import (
    _block_cells,
    landscape_warnings,
    solid_ground_kinds,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.recipes_core import (
    _run,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.recipes_more import (
    RECIPES,
)


# ── the tools ─────────────────────────────────────────────────────────────────
def t_compose_landscape(d: Drawing, a: dict, cell_from, cell_to, scene='alpine', seed=1, name=''):
    if scene not in RECIPES:
        raise ValueError('unknown scene %r — pick one of %s' % (scene, ', '.join(SCENES)))
    ca, ra, cb, rb = _block_cells(cell_from, cell_to)
    cols, rows = cb - ca + 1, rb - ra + 1
    x0, z0, x1, z1 = block_bounds(cell_from, cell_to)
    W, D = x1 - x0, z1 - z0
    # METRES first: the scene is built out of real things, so the honest floor is a
    # ground size. The cell floor after it only matters if a cell is not 1 m — the
    # recipes lay their bands out by row, and a 6-row block has no bands to lay.
    m = MIN_METRES.get(scene, 60.0)
    if W < m or D < m:
        raise ValueError(
            'the %s scene is built out of real sizes (peaks, %g m trees, %g m boulders), so it '
            'needs at least %g x %g m of ground; %s..%s is only %g x %g m'
            % (scene, TREE_H['conifer'], BOULDER_M, m, m, cell_from, cell_to, W, D)
        )
    need = MIN_CELLS.get(scene)
    if need and (cols < need or rows < need):
        raise ValueError(
            'the %s scene needs a block of at least %d x %d cells; %s..%s is %d x %d'
            % (scene, need, need, cell_from, cell_to, cols, rows)
        )
    if W > MAX_METRES or D > MAX_METRES:
        raise ValueError(
            'a scene is one sculpted ground and the grid tops out at %g m a side; %s..%s is '
            '%g x %g m — coarsen the grid with set_grid_scale or compose two blocks'
            % (MAX_METRES, cell_from, cell_to, W, D)
        )
    if any(o.get('kind') == GROUND_KIND for o in d.objs):
        raise ValueError(
            'this drawing already has a ground — a scene lays its own. Start a new drawing, '
            'or shape the one you have with raise_ground / lower_ground / carve_river.'
        )
    try:
        seed = int(seed)
    except (TypeError, ValueError) as _exc:
        raise ValueError('seed must be a whole number') from _exc
    nm = str(name or '').strip()
    steps = RECIPES[scene](cell_from, cell_to, seed, nm)
    if len(d.objs) + len(steps) * 40 > _A.MAX_OBJECTS * 2:
        raise ValueError('the drawing is already too full for a whole landscape')
    out = _run(d, scene, steps)
    if out.startswith('refused'):
        return out
    solids = solid_ground_kinds(d)
    if solids:
        return (
            '%s\n  ! %d v1 solid ground record(s) got through onto a sculpted ground: %s — every '
            'landform in a v3 scene has to be a sculpt of the one ground'
            % (out, len(solids), ', '.join('%s %s' % s for s in solids))
        )
    return out


def t_describe_landscape(d: Drawing, a: dict):
    rows = {}
    for o in d.objs:
        fam = LANDSCAPE_KINDS.get(o.get('kind'))
        if not fam:
            continue
        rows.setdefault((fam, o['kind']), []).append(o)
    if not rows:
        return 'no landscape records in this drawing yet — compose_landscape lays a whole scene at once.'
    out = ['%d landscape records:' % sum(len(v) for v in rows.values())]
    for fam, kind in sorted(rows):
        objs = rows[(fam, kind)]
        p = objs[0].get('p') or {}
        size = ', '.join(
            '%s %g' % (k, p[k])
            for k in ('w', 'd', 'h', 'r', 'rx', 'len', 'radius', 'depth')
            if isinstance(p.get(k), (int, float))
        )
        out.append('  %-14s %-15s x%-4d %s' % (fam, kind, len(objs), size or '-'))
    warn = landscape_warnings(d)
    if warn:
        out.append(
            'warnings (%d) — %g m is the most a record may float above or sink into its ground:'
            % (len(warn), GROUND_TOL)
        )
        for w in warn[:20]:
            out.append('  ! ' + w)
        if len(warn) > 20:
            out.append('  ! ... and %d more' % (len(warn) - 20))
    else:
        out.append('warnings: none — every record sits on its ground and the proportions hold.')
    return '\n'.join(out)


def _fold(s):
    s = unicodedata.normalize('NFKD', str(s or '').lower())
    return ''.join(ch for ch in s if not unicodedata.combining(ch))


_SCENE_WORDS = {
    'alpine': (
        'berg',
        'bergen',
        'gebergte',
        'gebirge',
        'alpen',
        'alpine',
        'alps',
        'mountain',
        'mountains',
        'montagne',
        'peak',
        'summit',
        'snow',
        'sneeuw',
        'schnee',
        'glacier',
        'gletsjer',
    ),
    'river_valley': (
        'rivier',
        'river',
        'fluss',
        'riviere',
        'vallei',
        'valley',
        'tal',
        'vallee',
        'dal',
        'beek',
        'stream',
        'bach',
        'ruisseau',
        'meander',
        'bank',
        'oever',
        'ufer',
    ),
    'forest_lake': (
        'bos',
        'forest',
        'wald',
        'foret',
        'woods',
        'woodland',
        'meer',
        'lake',
        'see',
        'lac',
        'bomen',
        'trees',
        'baume',
        'arbres',
        'undergrowth',
        'onderhout',
    ),
    'coast': (
        'kust',
        'coast',
        'kuste',
        'cote',
        'zee',
        'sea',
        'mer',
        'strand',
        'beach',
        'plage',
        'duin',
        'duinen',
        'dune',
        'dunes',
        'eiland',
        'island',
        'insel',
        'ile',
        'klif',
        'cliff',
        'falaise',
        'klippe',
        'ocean',
        'oceaan',
    ),
    'polder': (
        'polder',
        'molen',
        'windmill',
        'windmuhle',
        'moulin',
        'dijk',
        'deich',
        'digue',
        'dyke',
        'sloot',
        'ditch',
        'graben',
        'tulpen',
        'tulips',
        'tulpenveld',
        'weiland',
        'meadow',
        'wiese',
        'prairie',
        'akker',
        'field',
        'acker',
        'champ',
        'moeras',
        'marsh',
        'moor',
        'marais',
        'holland',
        'nederland',
    ),
    'heath': (
        'heide',
        'heath',
        'lande',
        'heather',
        'moorland',
        'veen',
        'vijver',
        'pond',
        'teich',
        'etang',
        'zand',
        'sand',
        'kei',
        'keien',
        'boulder',
        'boulders',
        'fels',
        'rocher',
    ),
    'canyon': (
        'canyon',
        'kloof',
        'schlucht',
        'gorge',
        'mesa',
        'plateau',
        'tafelberg',
        'ravine',
        'butte',
        'escarpment',
        'desert',
        'woestijn',
        'wuste',
    ),
}


def t_suggest_scene(d: Drawing, a: dict, words):
    txt = _fold(words)
    if not txt.strip():
        raise ValueError('say something about the landscape you want')
    toks = [t for t in ''.join(ch if ch.isalnum() else ' ' for ch in txt).split() if t]
    if not toks:
        raise ValueError('no words to work from')
    best = None
    for scene in SCENES:
        vocab = _SCENE_WORDS[scene]
        hits = [t for t in toks if t in vocab]
        if not hits:
            # compounds: 'kustlandschap' holds 'kust', 'Waldsee' holds 'wald'
            hits = [t for t in toks if len(t) >= 4 and any(w in t or t in w for w in vocab if len(w) >= 4)]
        if not hits:
            continue
        first = min(toks.index(h) for h in hits)
        key = (-len(hits), first, SCENES.index(scene))
        if best is None or key < best[0]:
            best = (key, scene, hits)
    if best is None:
        raise ValueError('nothing in %r points at one of the seven scenes: %s' % (str(words)[:60], ', '.join(SCENES)))
    _key, scene, hits = best
    return '%s — %r reads as %s; compose_landscape(cell_from, cell_to, scene=%r).' % (
        scene,
        ' '.join(sorted(set(hits))[:4]),
        scene.replace('_', ' '),
        scene,
    )


TOOLS = [
    (
        {
            'name': 'compose_landscape',
            'description': (
                'Lay a whole coherent landscape over a block in one call: one of seven recipes runs the '
                'landscape families in a fixed order. It lays ONE sculpted ground (make_ground) over the '
                'block FIRST and after that only cuts into it (lower_ground, carve_river, fill_lake, '
                'fill_sea, add_beach, add_dunes, add_cliff) or drapes over it — it never adds a solid '
                'terrain, valley, mountain, sea or lake record, so a valley is a real hole and a lake is '
                'real water in it. Sizes are real metres (16 m conifers, 2.5 m boulders, a 12 m windmill '
                'tower); only a mountain scales with the block, radius 0.15 x the width and height 0.8 x '
                'that radius, capped at 150 m. Scenes: alpine, river_valley, forest_lake, coast, polder, '
                'heath, canyon. Use this first when the user asks for a landscape rather than a single '
                'feature, then adjust with the single tools. alpine needs at least 240 x 240 m, coast and '
                'canyon 120 m, and no scene may exceed 1000 m a side; at a kilometre set_grid_scale(5) or '
                '(10) first so the ground has cells to work with.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string', 'description': 'One corner of the block, e.g. A1.'},
                    'cell_to': {'type': 'string', 'description': 'The opposite corner, e.g. GR200.'},
                    'scene': {'type': 'string', 'enum': list(SCENES), 'description': 'Which recipe to run.'},
                    'seed': {'type': 'integer', 'description': 'Changes the random detail.'},
                    'name': {'type': 'string', 'description': 'Prefix for the record names.'},
                },
                'required': ['cell_from', 'cell_to', 'scene'],
            },
        },
        t_compose_landscape,
    ),
    (
        {
            'name': 'describe_landscape',
            'description': (
                'List every landscape record in the drawing, grouped by family and kind, with sizes, THEN '
                'warn about anything buried, floating or out of proportion (trees taller than 0.3 of the '
                'summit, boulders over 4 m, a windmill over 22 m, water standing higher than its own banks, '
                'a v1 solid ground record on a sculpted ground). Call it after drawing a landscape by hand '
                'to check the scene holds together. Draws nothing.'
            ),
            'input_schema': {'type': 'object', 'properties': {}},
        },
        t_describe_landscape,
    ),
    (
        {
            'name': 'suggest_scene',
            'description': (
                "Turn free words in Dutch, German, French or English ('bergen', 'kust', 'polder', "
                "'bos met meer', 'Wald', 'cote') into one of the seven compose_landscape scenes, with a "
                'one-line reason. A lookup: it draws nothing.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {'words': {'type': 'string', 'description': 'What the user said about the landscape.'}},
                'required': ['words'],
            },
        },
        t_suggest_scene,
    ),
]

EXAMPLES = [
    {
        'ask': 'make a mountain landscape over A1 to JJ260',
        'calls': [{'tool': 'compose_landscape', 'args': {'cell_from': 'A1', 'cell_to': 'JJ260', 'scene': 'alpine'}}],
    },
    {
        'ask': 'a mountain range across a whole kilometre',
        'calls': [
            {'tool': 'set_grid_scale', 'args': {'metres_per_cell': 5}},
            {'tool': 'compose_landscape', 'args': {'cell_from': 'A1', 'cell_to': 'GR200', 'scene': 'alpine'}},
        ],
    },
    {
        'ask': 'een kustlandschap van A1 tot GR200',
        'lang': 'nl',
        'calls': [{'tool': 'compose_landscape', 'args': {'cell_from': 'A1', 'cell_to': 'GR200', 'scene': 'coast'}}],
    },
    {
        'ask': 'een polder met een molen, A1 tot FX170',
        'lang': 'nl',
        'calls': [{'tool': 'compose_landscape', 'args': {'cell_from': 'A1', 'cell_to': 'FX170', 'scene': 'polder'}}],
    },
    {
        'ask': 'eine Waldlandschaft mit einem See von A1 bis FX170',
        'lang': 'de',
        'calls': [
            {'tool': 'compose_landscape', 'args': {'cell_from': 'A1', 'cell_to': 'FX170', 'scene': 'forest_lake'}}
        ],
    },
    {
        'ask': 'I want something like bergen met een meer — which scene is that?',
        'calls': [{'tool': 'suggest_scene', 'args': {'words': 'bergen met een meer'}}],
    },
    {'ask': 'is anything buried or floating in this landscape?', 'calls': [{'tool': 'describe_landscape', 'args': {}}]},
]
