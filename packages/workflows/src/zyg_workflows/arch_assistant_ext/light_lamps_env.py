# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""light_lamps_env — the assistant's half of the Lighting family.

Three placeholders became real icons (arch_ext/light_lamps_env.js):
  l_hdri  the sky as the light source      l_lamp  point / spot / area lamps
  l_ies   a measured luminaire's photometry

The model cannot click the canvas, so every one of them has a server-side twin
here that does the same job on the Drawing and answers in text:

  place_light(kind, cell, storey, watts, colour)  -> a lamp record in a cell
  set_ies(which, name)                            -> a spot's measured beam
  list_hdri()                                     -> the sky library + licence
  set_hdri(name)                                  -> doc.ext, replayed by the tab

THE PHOTOMETRY IS PARSED ONCE. `set_ies` does not re-implement IESNA LM-63: it
imports parse_ies from arch_server_ext/light_lamps_env.py — the same function
the /ext/light_lamps_env/ies_info route answers with — so the number the model
quotes and the number the icon writes into the record cannot drift apart. (The
tab's JS holds a third copy of the same arithmetic, pinned against this one by
tests_arch_ext/test_light_lamps_env.py.)

Assets: data/assets/mesh_packs/hdri (CC0 1.0, Poly Haven) and
data/assets/mesh_packs/ies (MIT, three.js examples/ies). Stdlib only.
"""

from __future__ import annotations

import importlib.util
import os

from zyg_workflows.arch_assistant import Drawing, _num, cell_centre, cell_name, parse_cell

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KINDS = {
    'light_point': {'w': 12, 'r': 8, 'col': '#ffe9c4'},
    'light_spot': {'w': 20, 'r': 12, 'angle': 35, 'pen': 0.3, 'col': '#ffe9c4'},
    'light_area': {'w': 30, 'x': 1.0, 'z': 0.6, 'col': '#ffe9c4'},
}
OPENINGS: list = []
LABEL = {'light_point': 'Point light', 'light_spot': 'Spot light', 'light_area': 'Area light'}
CAP = 32  # the tab's light budget: the same number in both engines
STOREY_M = 2.7

BUTTONS = ['l_hdri', 'l_lamp', 'l_ies']

PROMPT = (
    'Lighting (environment, lamps, photometry). place_light(kind=point|spot|area, cell="C4", storey, '
    'watts, colour="#ffe9c4") drops a lamp record 0.3 m under that storey\'s ceiling; at most 32 lamps '
    'in a drawing. set_ies(which="new"|ids|kind, name) reads a bundled IESNA LM-63 profile and gives '
    'every selected SPOT its measured half-intensity beam angle, flux and peak candela (p.ies, p.angle, '
    'p.ies_lm, p.ies_cd). list_hdri() names the bundled CC0 skies; set_hdri(name|"off") lights the whole '
    'scene with one of them (it is a document setting: it survives a save). The same three icons can be '
    'pressed instead: press_button("l_hdri", {"name": "moonless_golf"}), '
    'press_button("l_lamp", {"kind": "light_spot", "cell": "D5", "storey": 0}), '
    'press_button("l_ies", {"name": "<profile>"}) — l_lamp without a cell ARMS the click-to-place tool.'
)


# ── the two libraries on disk (one arithmetic: the server ext owns it) ──────
_SRV = [None]


def _srv():
    """arch_server_ext/light_lamps_env.py, loaded by path and then KEPT. It is
    not an importable package, and re-executing it per tool call re-compiled the
    LM-63 parser once for every one of list_hdri / set_hdri / set_ies in a single
    conversation turn. The module holds no state, so loading it once is enough."""
    if _SRV[0] is None:
        path = os.path.join(HERE, 'arch_server_ext', 'light_lamps_env.py')
        spec = importlib.util.spec_from_file_location('arch_server_ext.light_lamps_env', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SRV[0] = mod
    return _SRV[0]


def _lights(d: Drawing) -> list:
    return [o for o in d.objs if o['kind'] in KINDS]


# ── tools ───────────────────────────────────────────────────────────────────
def t_place_light(d: Drawing, a, kind='point', cell='', storey=0, watts=None, colour='', height=None):
    k = str(kind or 'point').strip().lower()
    if not k.startswith('light_'):
        k = 'light_' + k
    if k not in KINDS:
        return 'refused: kind must be point, spot or area (got "%s")' % str(kind)[:30]
    have = len(_lights(d))
    if have >= CAP:
        return f'refused: the drawing already holds {have} lamps — {CAP} is the budget the tab renders'
    try:
        c, r = parse_cell(cell)
    except ValueError:
        return 'refused: cell must be a grid cell like C4 or AB12 (got "%s")' % str(cell)[:20]
    x, z = cell_centre(c, r)
    p = dict(KINDS[k])
    if watts is not None:
        p['w'] = round(min(5000.0, max(0.1, _num(watts, p['w']))), 3)
    if colour:
        p['col'] = str(colour)[:24]
    st = int(_num(storey, 0))
    y = st * STOREY_M + (_num(height, 0.0) if height is not None else STOREY_M - 0.3)
    rec = d.new(k, p, x, z, y, name=LABEL[k], mat='mat_plaster')
    d.selected = [rec['id']]
    return (
        f'{LABEL[k].lower()} {rec["id"]} in {cell_name(c, r)} on storey {st} at y {y:.2f} m — '
        f'{p["w"]:g} W, {p["col"]}; {have + 1} of {CAP} lamps used'
    )


def t_set_ies(d: Drawing, a, which='new', name=''):
    srv = _srv()
    idx = srv._index(srv.IES_DIR, '.ies')
    nm = str(name or '').strip()
    if nm not in idx:
        return 'refused: unknown IES profile "%s" — have: %s' % (nm[:40], ', '.join(sorted(idx)) or 'none')
    with open(idx[nm], 'r', encoding='utf-8', errors='replace') as fh:
        ph = srv.parse_ies(fh.read())
    recs = [o for o in d.select(which if which not in (None, '') else 'new') if o['kind'] == 'light_spot']
    if not recs:
        return (
            f'{nm}: {ph["beam_angle"]:.1f}\u00b0 half-intensity beam, {ph["lumens"]:.0f} lm, '
            f'{ph["peak_cd"]:.0f} cd peak, {ph["n_v"]}\u00d7{ph["n_h"]} angles \u2014 '
            f'but nothing matching "{which}" is a spot light, so no record was changed'
        )
    ang = round(min(80.0, max(3.0, ph['beam_angle'])), 1)
    for o in recs:
        o['p']['ies'] = nm
        o['p']['angle'] = ang
        o['p']['ies_lm'] = round(ph['lumens'])
        o['p']['ies_cd'] = round(ph['peak_cd'])
        if ph['watts'] > 0:
            o['p']['w'] = ph['watts']
    return (
        f'{nm} applied to {len(recs)} spot light(s) ({", ".join(o["id"] for o in recs[:8])}'
        f'{"…" if len(recs) > 8 else ""}): {ang:.1f}\u00b0 half-intensity beam, '
        f'{ph["lumens"]:.0f} lm, {ph["peak_cd"]:.0f} cd peak at {ph["peak_angle"]:g}\u00b0, '
        f'{ph["watts"]:g} W'
    )


def t_list_hdri(d: Drawing, a):
    srv = _srv()
    items = srv._items(srv.HDRI_DIR, '.hdr')
    if not items:
        return 'the sky library is empty'
    cur = (d.ext.get('light_lamps_env') or {}).get('hdri')
    rows = [
        '%s — %s (%d kB)%s' % (it['name'], it['label'], it['kb'], '  <- in use' if it['name'] == cur else '')
        for it in items
    ]
    return '%d HDRI skies (%s):\n' % (len(items), srv.HDRI_LICENCE) + '\n'.join(rows)


def t_set_hdri(d: Drawing, a, name=''):
    srv = _srv()
    nm = str(name or '').strip()
    if nm in ('', 'off', 'none'):
        d.ext.setdefault('light_lamps_env', {})['hdri'] = None
        d.ui.append({'cmd': 'tool', 'args': {'id': 'l_hdri', 'args': {'name': 'off'}}})
        return 'environment light off — the scene is back on the flat background'
    idx = srv._index(srv.HDRI_DIR, '.hdr')
    if nm not in idx:
        return 'refused: unknown sky "%s" — have: %s' % (nm[:40], ', '.join(sorted(idx)) or 'none')
    d.ext.setdefault('light_lamps_env', {})['hdri'] = nm
    d.ui.append({'cmd': 'tool', 'args': {'id': 'l_hdri', 'args': {'name': nm}}})
    return f'environment light set to {nm} ({srv.HDRI_LICENCE}) — it lights and reflects the whole scene'


TOOLS = [
    (
        {
            'name': 'place_light',
            'description': 'Place an artificial lamp (point, spot or area) in a grid cell so an interior reads after dark. '
            'It lands 0.3 m under the ceiling of the storey you name. At most 32 lamps in a drawing.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'kind': {'type': 'string', 'enum': ['point', 'spot', 'area']},
                    'cell': {'type': 'string', 'description': 'grid cell, e.g. C4 or AB12'},
                    'storey': {'type': 'integer'},
                    'watts': {
                        'type': 'number',
                        'description': 'watts-ish: 12 for a point, 20 for a spot, 30 for an area light',
                    },
                    'colour': {'type': 'string', 'description': 'hex, e.g. #ffe9c4 for a warm lamp'},
                    'height': {
                        'type': 'number',
                        'description': 'metres above the storey floor, instead of just under the ceiling',
                    },
                },
                'required': ['kind', 'cell'],
            },
        },
        t_place_light,
    ),
    (
        {
            'name': 'set_ies',
            'description': 'Give spot lights a real luminaire\u2019s measured photometry from a bundled IESNA LM-63 profile: '
            'its half-intensity beam angle, luminous flux and peak intensity replace the guessed cone. '
            'Call list_hdri first only for skies; profile names come from the studio\u2019s IES library.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': {'type': 'string', 'description': '"new", "all", a kind, a group name or ids'},
                    'name': {'type': 'string', 'description': 'the IES profile name'},
                },
                'required': ['name'],
            },
        },
        t_set_ies,
    ),
    (
        {
            'name': 'list_hdri',
            'description': 'List the bundled CC0 HDRI skies that can light the scene, with their licence and which one is in use.',
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        t_list_hdri,
    ),
    (
        {
            'name': 'set_hdri',
            'description': 'Light the whole scene with one of the bundled HDRI skies (or "off"). It is what glass and metal '
            'reflect, and it is saved with the drawing.',
            'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        },
        t_set_hdri,
    ),
]

EXAMPLES = [
    {
        'ask': 'light the living room after dark — a spot over the table in D5 and a couple of point lights',
        'calls': [
            {'tool': 'place_light', 'args': {'kind': 'spot', 'cell': 'D5', 'storey': 0, 'watts': 24}},
            {'tool': 'place_light', 'args': {'kind': 'point', 'cell': 'B4', 'storey': 0}},
            {'tool': 'place_light', 'args': {'kind': 'point', 'cell': 'F6', 'storey': 0}},
            {'tool': 'select', 'args': {'which': 'new'}},
        ],
    },
    {
        'ask': 'make that downlight a real BEGA luminaire',
        'calls': [{'tool': 'set_ies', 'args': {'which': 'light_spot', 'name': '007cfb11e343e2f42e3b476be4ab684e'}}],
    },
    {
        'ask': 'which skies can you light this with? give me the dusk one',
        'calls': [{'tool': 'list_hdri', 'args': {}}, {'tool': 'set_hdri', 'args': {'name': 'qwantani_dusk_2_puresky'}}],
    },
]
