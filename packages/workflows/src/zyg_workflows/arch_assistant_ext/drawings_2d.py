# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""drawings_2d — the assistant half of the 2D drawing generator (2026-09-08).

No new kinds: the family turns records that already exist into plan,
elevation and section SVGs. The model cannot LOOK at an SVG, so `drawing`
is a press of the tab's own icon (the picture appears in the studio, in the
person's sheet) while `drawing_settings` writes the document-level settings
the generator reads — AR.doc.ext.drawings_2d — which round-trip through the
Drawing and back into the tab.

Stdlib only.
"""

import json

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['dc_plan', 'dc_elev', 'dc_sect', 'dc_scale', 'dc_dim', 'dc_hatch', 'dc_lw']

PROMPT = (
    '2D drawings: drawing(kind="plan"|"elevation"|"section", storey=0, elev="front", x=, z=, axis="x") '
    'makes the drawing IN THE TAB and shows it to the person on a sheet with a download button — you cannot '
    'see the SVG yourself, so say what you asked for. drawing_settings(scale=100, hatch="ansi31"|"concrete"|"none", '
    'cut_h=1.2, text_mm=2.5, arrow="tick"|"arrow"|"dot", unit="m"|"mm", decimals=2, cut=0.5, proj=0.25, hidden=0.13, '
    'thin=0.13, section_axis="x"|"z", section_x=, section_z=) edits AR.doc.ext.drawings_2d (scale, hatch, dimension '
    'style, pen widths in mm, the default section plane). A plan also draws the dimension, angle and label annotation '
    'records that are already on the drawing. The same seven icons '
    'can be pressed directly: press_button("dc_plan", {"storey": 0}), press_button("dc_elev", {"elev": "front"}), '
    'press_button("dc_sect", {"dir": "x", "x": 0}), press_button("dc_scale", {"scale": 50}), '
    'press_button("dc_dim", {"text_mm": 2.5, "arrow": "arrow", "unit": "mm", "decimals": 0}), '
    'press_button("dc_hatch", {"hatch": "concrete"}) (no args cycles it), '
    'press_button("dc_lw", {"cut": 0.7, "proj": 0.25}).'
)

DEF = {
    'scale': 100,
    'lw': {'cut': 0.5, 'proj': 0.25, 'hidden': 0.13, 'thin': 0.13},
    'hatch': 'ansi31',
    'hatch_cut': True,
    'dim': {'text_mm': 2.5, 'arrow': 'tick', 'unit': 'm', 'decimals': 2},
    'storey': 0,
    'cut_h': 1.2,
    'elev': 'front',
    'section': {'x': None, 'z': None, 'dir': 'x'},
}

_ICON = {'plan': 'dc_plan', 'elevation': 'dc_elev', 'elev': 'dc_elev', 'section': 'dc_sect', 'sect': 'dc_sect'}


def _settings(d) -> dict:
    s = d.ext.get('drawings_2d')
    if not isinstance(s, dict):
        s = json.loads(json.dumps(DEF))
        d.ext['drawings_2d'] = s
    for k, v in DEF.items():
        if isinstance(v, dict):
            if not isinstance(s.get(k), dict):
                s[k] = dict(v)
            for kk, vv in v.items():
                s[k].setdefault(kk, vv)
        else:
            s.setdefault(k, v)
    return s


def t_drawing(d, a, kind='plan', storey=None, elev=None, x=None, z=None, axis=None):
    k = str(kind or 'plan').strip().lower()
    icon = _ICON.get(k)
    if not icon:
        return 'refused: kind must be "plan", "elevation" or "section"'
    args: dict = {}
    if icon == 'dc_plan':
        args['storey'] = int(storey or 0)
    elif icon == 'dc_elev':
        e = str(elev or 'front').strip().lower()
        if e not in ('front', 'back', 'left', 'right'):
            return 'refused: elev must be front, back, left or right'
        args['elev'] = e
    else:
        ax = str(axis or ('z' if z is not None else 'x')).strip().lower()
        if ax not in ('x', 'z'):
            return 'refused: axis must be "x" or "z"'
        args['dir'] = ax
        v = z if ax == 'z' else x
        if v is not None:
            args[ax] = float(v)
    d.ui.append({'cmd': 'tool', 'args': {'id': icon, 'args': args}})
    return 'requested: the studio is drawing the %s (%s) at 1:%s and showing it on a sheet with a download button' % (
        k,
        json.dumps(args),
        _settings(d)['scale'],
    )


def t_drawing_settings(
    d,
    a,
    scale=None,
    hatch=None,
    hatch_cut=None,
    cut_h=None,
    storey=None,
    elev=None,
    text_mm=None,
    arrow=None,
    unit=None,
    decimals=None,
    cut=None,
    proj=None,
    hidden=None,
    thin=None,
    section_axis=None,
    section_x=None,
    section_z=None,
):
    s = _settings(d)
    changed = []
    if scale is not None:
        n = int(round(float(scale)))
        if n <= 0:
            return 'refused: a scale is a positive number, e.g. 100 for 1:100'
        s['scale'] = n
        changed.append('scale 1:%d' % n)
    if hatch is not None:
        h = str(hatch).strip().lower()
        if h not in ('ansi31', 'concrete', 'none'):
            return 'refused: hatch must be ansi31, concrete or none'
        s['hatch'] = h
        changed.append('hatch %s' % h)
    if hatch_cut is not None:
        s['hatch_cut'] = bool(hatch_cut)
        changed.append('hatch_cut %s' % s['hatch_cut'])
    if cut_h is not None:
        s['cut_h'] = float(cut_h)
        changed.append('cut height %.2f m' % s['cut_h'])
    if storey is not None:
        s['storey'] = int(storey)
        changed.append('storey %d' % s['storey'])
    if elev is not None:
        e = str(elev).strip().lower()
        if e not in ('front', 'back', 'left', 'right'):
            return 'refused: elev must be front, back, left or right'
        s['elev'] = e
        changed.append('elevation %s' % e)
    if text_mm is not None:
        s['dim']['text_mm'] = float(text_mm)
        changed.append('text %.2f mm' % s['dim']['text_mm'])
    if arrow is not None:
        v = str(arrow).strip().lower()
        if v not in ('tick', 'arrow', 'dot'):
            return 'refused: arrow must be tick, arrow or dot'
        s['dim']['arrow'] = v
        changed.append('arrowhead %s' % v)
    if unit is not None:
        v = str(unit).strip().lower()
        if v not in ('m', 'mm'):
            return 'refused: unit must be m or mm'
        s['dim']['unit'] = v
        changed.append('unit %s' % v)
    if decimals is not None:
        s['dim']['decimals'] = max(0, min(4, int(decimals)))
        changed.append('%d decimals' % s['dim']['decimals'])
    if section_axis is not None:
        v = str(section_axis).strip().lower()
        if v not in ('x', 'z'):
            return 'refused: section_axis must be "x" or "z"'
        s['section']['dir'] = v
        changed.append('section along %s' % v)
    for key, val in (('x', section_x), ('z', section_z)):
        if val is not None:
            s['section'][key] = float(val)
            changed.append('section plane %s = %.2f m' % (key, s['section'][key]))
    for key, val in (('cut', cut), ('proj', proj), ('hidden', hidden), ('thin', thin)):
        if val is not None:
            f = float(val)
            if f <= 0:
                return 'refused: a pen width is a positive number of millimetres'
            s['lw'][key] = f
            changed.append('%s pen %.2f mm' % (key, f))
    if not changed:
        sec = s['section']
        at = sec.get(sec.get('dir') or 'x')
        return (
            'drawing settings: 1:%s, hatch %s, cut at %.2f m, text %.2f mm %s in %s, pens cut/proj/hidden/thin '
            '%.2f/%.2f/%.2f/%.2f mm, section along %s at %s'
            % (
                s['scale'],
                s['hatch'],
                s['cut_h'],
                s['dim']['text_mm'],
                s['dim']['arrow'],
                s['dim']['unit'],
                s['lw']['cut'],
                s['lw']['proj'],
                s['lw']['hidden'],
                s['lw']['thin'],
                sec.get('dir') or 'x',
                'the middle' if at is None else '%.2f m' % float(at),
            )
        )
    return 'drawing settings updated: ' + ', '.join(changed)


TOOLS = [
    (
        {
            'name': 'drawing',
            'description': (
                'Draw a plan, an elevation or a section of the current model as a to-scale SVG and show it '
                'to the person on a sheet (with a download button). You cannot see the picture yourself.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'kind': {
                        'type': 'string',
                        'enum': ['plan', 'elevation', 'section'],
                        'description': 'which drawing',
                    },
                    'storey': {'type': 'integer', 'description': 'plan only: which storey (0 = ground)'},
                    'elev': {
                        'type': 'string',
                        'enum': ['front', 'back', 'left', 'right'],
                        'description': 'elevation only: the side you look from',
                    },
                    'axis': {
                        'type': 'string',
                        'enum': ['x', 'z'],
                        'description': 'section only: the axis the plane is normal to',
                    },
                    'x': {'type': 'number', 'description': 'section only: cut at x = this (metres)'},
                    'z': {'type': 'number', 'description': 'section only: cut at z = this (metres)'},
                },
                'required': [],
            },
        },
        t_drawing,
    ),
    (
        {
            'name': 'drawing_settings',
            'description': (
                'Read or edit the drawing settings kept with the document (scale, cut height, hatch, '
                'dimension style, pen widths in mm). Call with no arguments to read them back.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'scale': {'type': 'integer', 'description': '1:scale — 20, 50, 100, 200, 500'},
                    'hatch': {
                        'type': 'string',
                        'enum': ['ansi31', 'concrete', 'none'],
                        'description': 'fill of the cut solids',
                    },
                    'hatch_cut': {'type': 'boolean', 'description': 'hatch the cut solids at all'},
                    'cut_h': {'type': 'number', 'description': 'height above the storey floor the plan cuts at (m)'},
                    'storey': {'type': 'integer', 'description': 'default storey for a plan'},
                    'elev': {
                        'type': 'string',
                        'enum': ['front', 'back', 'left', 'right'],
                        'description': 'default elevation',
                    },
                    'text_mm': {'type': 'number', 'description': 'dimension text height in paper mm'},
                    'arrow': {
                        'type': 'string',
                        'enum': ['tick', 'arrow', 'dot'],
                        'description': 'dimension terminator',
                    },
                    'unit': {'type': 'string', 'enum': ['m', 'mm'], 'description': 'dimension unit'},
                    'decimals': {'type': 'integer', 'description': 'decimals on a metre dimension'},
                    'cut': {'type': 'number', 'description': 'cut pen width, mm'},
                    'proj': {'type': 'number', 'description': 'projected pen width, mm'},
                    'hidden': {'type': 'number', 'description': 'hidden pen width, mm'},
                    'thin': {'type': 'number', 'description': 'thin pen width, mm'},
                    'section_axis': {
                        'type': 'string',
                        'enum': ['x', 'z'],
                        'description': 'default section: the axis the plane is normal to',
                    },
                    'section_x': {'type': 'number', 'description': 'default section plane at x = this (metres)'},
                    'section_z': {'type': 'number', 'description': 'default section plane at z = this (metres)'},
                },
                'required': [],
            },
        },
        t_drawing_settings,
    ),
]

EXAMPLES = [
    {
        'ask': 'give me the ground floor plan at 1:50',
        'calls': [
            {'tool': 'drawing_settings', 'args': {'scale': 50}},
            {'tool': 'drawing', 'args': {'kind': 'plan', 'storey': 0}},
        ],
    },
    {'ask': 'a front elevation please', 'calls': [{'tool': 'drawing', 'args': {'kind': 'elevation', 'elev': 'front'}}]},
    {
        'ask': 'cut a section through the middle on x, with concrete hatch and a heavier cut pen',
        'calls': [
            {'tool': 'drawing_settings', 'args': {'hatch': 'concrete', 'cut': 0.7}},
            {'tool': 'drawing', 'args': {'kind': 'section', 'axis': 'x'}},
        ],
    },
    {
        'ask': 'dimensions in millimetres with arrowheads',
        'calls': [{'tool': 'drawing_settings', 'args': {'unit': 'mm', 'decimals': 0, 'arrow': 'arrow'}}],
    },
]
