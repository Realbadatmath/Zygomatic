#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tools_arch_landscape_gallery.py — the operator's landscape evidence, v3.

v2 photographed solids standing on a lawn. v3 has ONE sculpted ground per
drawing and every landform is a sculpt of it, so this gallery photographs the
ground itself, twice per scene and from two different renderers:

  * Blender (`blender_render`) at 'aerial' and 'eye' — what the geometry IS;
  * the LIVE Architecture Studio tab in headless Chrome at 'eye'
    (`tools_arch_screenshot.py`) — what the operator SEES.

It composes the seven recipes, draws the French hillside with the tools on a v3
ground, and lays a kilometre of alpine in ONE compose at 5 m cells, saving each
as a studio project so the operator can open it.

    cd "$ZYG_CREWS_ROOT" && "$ZYG_LEGACY_VENV_PY" tools_arch_landscape_gallery.py

Writes ~/Documents/landscape_renders/  (ZYG_HOME/Documents/landscape_renders)
    v3_<key>_aerial.png   Blender, 45 deg from the south-west
    v3_<key>_eye.png      Blender, standing in it at 1.7 m
    v3_<key>_studio.png   the live studio tab, same eye view
    INDEX_v3.md           the verdict table

Phases (all of them by default):
    --scenes        compose + Blender renders + save the studio projects
    --shots         the live-studio screenshots of the saved projects
    --index-only    rewrite INDEX_v3.md from the last run and the verdict file
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zyg_workflows import paths

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from zyg_workflows import arch_assistant as A  # noqa: E402
from zyg_workflows import arch_ext_harness as H  # noqa: E402
from zyg_workflows import tools_arch_screenshot as SHOT  # noqa: E402
from zyg_workflows.arch_assistant_ext import landscape_composer as LC  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

OUT = str(paths.ZYG_HOME / 'Documents' / 'landscape_renders')
API = paths.ZYG_KANBAN_URL + '/inspect/api/architecture'

# 300 x 300 m at 1 m cells. v2 used 200 m; the v3 composer refuses alpine under
# 240 m (real sizes: a 0.15 x W peak radius), so the block had to grow.
BLOCK = ('A1', 'KN300')
SEED = 3

SCENE_NAMES = {
    'alpine': 'Alpine valley',
    'river_valley': 'River valley',
    'forest_lake': 'Forest lake',
    'coast': 'Coast',
    'polder': 'Dutch polder',
    'heath': 'Heath',
    'canyon': 'Canyon',
}

TRI_SCRIPT = (
    't = 0\n'
    'for o in bpy.data.objects:\n'
    '    if o.type == "MESH" and o.data:\n'
    '        o.data.calc_loop_triangles()\n'
    '        t += len(o.data.loop_triangles)\n'
    'print("TRIS", t)\n'
)

ROWS: list[dict] = []  # one per rendered scene, for INDEX_v3.md
PROJECTS: list[dict] = []  # {'name': ..., 'id': ...}

ROWS_PATH = os.path.join(HERE, 'data', 'runtime', 'landscape_gallery_v3_rows.json')
VERDICTS_PATH = os.path.join(HERE, 'data', 'runtime', 'landscape_gallery_v3_verdicts.json')


# ── the studio round trip ─────────────────────────────────────────────────────
def _post(path: str, body: dict) -> dict:
    url = API + path
    # net.safe_urlopen cannot carry the JSON Content-Type header this POST needs, so the scheme
    # audit S310/B310 asks for is done here instead, on the only URL this call can reach.
    if urlsplit(url).scheme not in ('http', 'https'):
        return {'error': f'refusing to POST to {url!r}: only http/https'}
    req = urllib.request.Request(  # noqa: S310  scheme checked on the line above  # nosec B310
        url, data=json.dumps(body).encode('utf-8'), headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as fh:  # noqa: S310  scheme checked above  # nosec B310
            return json.loads(fh.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'error': 'HTTP %d %s' % (e.code, e.read().decode('utf-8', 'replace')[:200])}


def _slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:60]


def save_project(d, name: str) -> str:
    """Delete the same-slug drawing first — save_project does not overwrite, it
    makes a NEW id ('...-2') when the slug is taken."""
    _post('/delete', {'id': _slug(name)})  # 404 when it is not there yet — fine
    out = _post('/save', {'doc': d.to_doc(), 'name': name})
    if not out.get('ok'):
        raise RuntimeError('save %r failed: %s' % (name, out))
    PROJECTS.append({'name': name, 'id': out['id']})
    return out['id']


# ── measuring and rendering ───────────────────────────────────────────────────
def tris_of(d) -> int:
    r = A.call_tool(d, 'blender_run', {'script': TRI_SCRIPT})
    m = re.findall(r'TRIS (\d+)', str(r[0] if isinstance(r, tuple) else r))
    return int(m[-1]) if m else -1


def _scaled(d):
    return A._Scale(getattr(d, 'cell_m', A.CELL_M))


def faults(d) -> list:
    with _scaled(d):
        return LC.landscape_warnings(d)


def ground_note(d) -> str:
    """describe_ground's first two lines: extent, relief, water and snow lines."""
    with _scaled(d):
        txt = str(A.call_tool(d, 'describe_ground', {}))
    return ' | '.join(txt.splitlines()[:2])


def gallery(d, key: str, name: str, note: str = '') -> None:
    """Both Blender views + the studio project + one printed line."""
    n = len(d.objs)
    t = tris_of(d)
    paths = {}
    for view in ('aerial', 'eye'):
        p = os.path.join(OUT, 'v3_%s_%s.png' % (key, view))
        t0 = time.time()
        H.save_render(d, p, view=view)
        paths[view] = p
        _zyg_log.info('    %-6s %6.1f s  %s' % (view, time.time() - t0, p))
    pid = save_project(d, name)
    warn = faults(d)
    ROWS.append(
        {
            'key': key,
            'name': name,
            'records': n,
            'tris': t,
            'aerial': paths['aerial'],
            'eye': paths['eye'],
            'studio': os.path.join(OUT, 'v3_%s_studio.png' % key),
            'project': name,
            'pid': pid,
            'warnings': warn,
            'note': note,
            'ground': ground_note(d),
            'kinds': H.kinds_of(d),
        }
    )
    _zyg_log.info(
        '%-14s records %4d  tris %7d  project %s%s' % (key, n, t, pid, ('  [%d warnings]' % len(warn)) if warn else '')
    )
    for w in warn[:6]:
        _zyg_log.info('    warn: ' + w)
    _save_rows()


# ── 1. the seven composer scenes ──────────────────────────────────────────────
def scenes(only=()) -> None:
    for key in LC.SCENES:
        if only and key not in only:
            continue
        _zyg_log.info('\n== %s ==' % key)
        txt, d = H.assistant(
            'compose_landscape', {'cell_from': BLOCK[0], 'cell_to': BLOCK[1], 'scene': key, 'seed': SEED}
        )
        if str(txt).startswith('refused') or not d.objs:
            raise RuntimeError('compose %s: %s' % (key, str(txt)[:300]))
        _zyg_log.info('    ' + str(txt).splitlines()[0][:200])
        gallery(
            d,
            key,
            '%s (landscape v3)' % SCENE_NAMES[key],
            note='compose_landscape %s seed %d over %s..%s (300 x 300 m at 1 m cells) — '
            'one sculpted ground, every landform a sculpt of it' % (key, SEED, BLOCK[0], BLOCK[1]),
        )


# ── 2. the French hillside, drawn with the tools on a v3 ground ───────────────
def french_hillside() -> None:
    _zyg_log.info('\n== french_hillside ==')
    cn = A.cell_name
    d = A.Drawing({'objects': []})
    said = []

    def tool(name, args):
        r = A.call_tool(d, name, args)
        txt = str(r[0] if isinstance(r, tuple) else r)
        if txt.startswith('refused'):
            raise RuntimeError('%s refused: %s' % (name, txt))
        said.append('%s -> %s' % (name, txt.splitlines()[0][:170]))
        return txt

    # THE ground: 200 x 200 m of gentle country. Everything below cuts into it.
    tool(
        'make_ground',
        {
            'cell_from': 'A1',
            'cell_to': cn(199, 199),
            'style': 'gentle',
            'seed': SEED,
            'water_level': -0.4,
            'snow_height': 400,
            'name': 'hillside ground',
        },
    )
    # the hill itself: a ridge along the southern 70 m, 35 m above the foot.
    # A v3 ridge feathers into the land at both ends, so there is no cliff at the
    # north face the way add_slope's wedge had one.
    tool(
        'raise_ground',
        {
            'cell_from': cn(0, 130),
            'cell_to': cn(199, 199),
            'height': 35,
            'shape': 'ridge',
            'seed': SEED,
            'name': 'the hillside',
        },
    )
    # the stream is CARVED: a channel cut into the ground with water on the bed,
    # running along the northern foot and falling west to east.
    tool(
        'carve_river',
        {
            'cells': [cn(4, 16), cn(70, 12), cn(140, 9), cn(196, 6)],
            'width': 2.5,
            'depth': 0.7,
            'meander': 4,
            'seed': SEED,
            'name': 'foot stream',
        },
    )
    # the pond is a real basin dug in the meadow with water floating on the bed —
    # no LEVEL_TOL to refuse, because the tool digs the level ground it needs.
    tool(
        'fill_lake',
        {
            'centre': cn(150, 40),
            'radius': 11,
            'radius_z': 8,
            'depth': 1.6,
            'irregularity': 0.35,
            'seed': SEED,
            'name': 'foot pond',
        },
    )
    # ── drapes last: they read the FINISHED ground under them ────────────────
    v = tool('add_vineyard', {'cell_from': cn(30, 112), 'cell_to': cn(169, 168), 'height': 1.8, 'name': 'vines'})
    contour = 'contour' in v.lower()
    tool(
        'plant_forest',
        {
            'cell_from': cn(0, 174),
            'cell_to': cn(199, 199),
            'mix': 'deciduous',
            'height': 10,
            'density': 0.025,
            'seed': SEED,
            'name': 'crest wood',
        },
    )
    tool(
        'scatter_rocks',
        {'cell_from': cn(4, 22), 'cell_to': cn(44, 52), 'count': 16, 'size': 1.4, 'seed': SEED, 'name': 'nw boulders'},
    )
    tool(
        'add_meadow',
        {'cell_from': cn(0, 20), 'cell_to': cn(199, 70), 'flowers': 320, 'seed': SEED, 'name': 'foot meadow'},
    )

    for s in said:
        _zyg_log.info('    ' + s)
    _zyg_log.info('    vineyard direction from contour: %s' % contour)
    gallery(
        d,
        'french_hillside',
        'French hillside (landscape v3)',
        note='drawn with the tools on a v3 ground: make_ground 200 x 200 m gentle, a 35 m '
        'ridge raised along the south, a carved stream and a basin pond cut into the '
        'foot, vines on the contour over the mid slope (contour=%s), a deciduous crest '
        'wood, 16 boulders and a flowering meadow draped on the finished ground' % contour,
    )


# ── 3. a kilometre of alpine on 5 m cells, in ONE compose ─────────────────────
def alpine_km() -> str:
    """Returns '' when the single compose worked, else the NOT DONE sentence."""
    _zyg_log.info('\n== alpine_1km ==')
    d = A.Drawing({'objects': []})
    r = A.call_tool(d, 'set_grid_scale', {'metres_per_cell': 5})
    _zyg_log.info('    set_grid_scale(5) -> %s' % str(r).splitlines()[0][:160])
    if str(r).startswith('refused'):
        return 'set_grid_scale(5) refused: %s' % r
    try:
        one = A.call_tool(
            d, 'compose_landscape', {'cell_from': 'A1', 'cell_to': 'GR200', 'scene': 'alpine', 'seed': SEED}
        )
    except ValueError as e:
        one = 'refused: %s' % e
    if str(one).startswith('refused') or not d.objs:
        return 'item 3: ONE compose over 1000 x 1000 m is still refused: %s' % str(one)[:220]
    _zyg_log.info('    ' + str(one).splitlines()[0][:200])
    gallery(
        d,
        'alpine_1km',
        'Alpine valley 1 km (landscape v3)',
        note='ONE compose_landscape alpine seed %d over A1..GR200 at 5 m cells '
        '(1000 x 1000 m) — a single sculpted ground a kilometre across, no tiling' % SEED,
    )
    return ''


# ── 4. the live studio: what the operator actually sees ───────────────────────
def studio_shots(rows) -> list:
    """Screenshot every saved project at 'eye' through the real tab. Returns the
    keys that failed (they go in NOT DONE)."""
    bad = []
    for r in rows:
        out = os.path.join(OUT, 'v3_%s_studio.png' % r['key'])
        t0 = time.time()
        try:
            info = SHOT.shoot(out, project=r['pid'], view='eye', quiet=True)
            r['studio'] = out
            r['studio_info'] = {k: info.get(k) for k in ('objs', 'span', 'ground', 'cam', 'bytes')}
            _zyg_log.info(
                'studio %-14s %6.1f s  %d objs, ground %.2f m, %d KB  %s'
                % (
                    r['key'],
                    time.time() - t0,
                    info.get('objs', -1),
                    float(info.get('ground') or 0.0),
                    info.get('bytes', 0) // 1024,
                    out,
                )
            )
            if info.get('page_errors'):
                _zyg_log.info('    page errors: %s' % info['page_errors'])
        except Exception as e:  # noqa: BLE001
            bad.append('%s: %s: %s' % (r['key'], type(e).__name__, e))
            _zyg_log.info('studio %-14s FAILED %s: %s' % (r['key'], type(e).__name__, e))
            traceback.print_exc()
        _save_rows()
    return bad


# ── 5. the index ──────────────────────────────────────────────────────────────
def write_index(verdicts: dict, not_done: list) -> None:
    lines = [
        '# Landscape gallery — ground v3',
        '',
        'Composed by `tools_arch_landscape_gallery.py` (seed %d). The seven recipes and the '
        'French hillside are 300 x 300 m and 200 x 200 m at 1 m cells; the last row is '
        '1000 x 1000 m at 5 m cells. Every drawing has ONE sculpted ground and every landform '
        'is a sculpt of it — there is no solid standing on a lawn anywhere in this gallery.' % SEED,
        '',
        'Three pictures per scene: `v3_<key>_aerial.png` and `v3_<key>_eye.png` are Blender '
        '(the geometry), `v3_<key>_studio.png` is the live Architecture Studio tab at the same '
        'eye height (what the operator sees).',
        '',
        '## Aerial — the whole scene from 45 degrees',
        '',
        '| picture | scene | records | tris | verdict |',
        '| --- | --- | ---: | ---: | --- |',
    ]
    for r in ROWS:
        lines.append(
            '| v3_%s_aerial.png | %s | %d | %d | %s |'
            % (r['key'], r['name'], r['records'], r['tris'], verdicts.get(r['key'] + '_aerial', '(not judged)'))
        )
    lines += [
        '',
        '## Eye — standing in it at 1.7 m (Blender)',
        '',
        '| picture | scene | verdict |',
        '| --- | --- | --- |',
    ]
    for r in ROWS:
        lines.append(
            '| v3_%s_eye.png | %s | %s |' % (r['key'], r['name'], verdicts.get(r['key'] + '_eye', '(not judged)'))
        )
    lines += ['', '## Studio — the live tab, same eye view', '', '| picture | scene | verdict |', '| --- | --- | --- |']
    for r in ROWS:
        lines.append(
            '| v3_%s_studio.png | %s | %s |' % (r['key'], r['name'], verdicts.get(r['key'] + '_studio', '(not judged)'))
        )
    lines += ['', '## The ground under each scene', '']
    for r in ROWS:
        lines.append('- **%s** — %s' % (r['key'], r.get('ground') or '(no ground record)'))
    lines += ['', '## Notes', '']
    for r in ROWS:
        lines.append(
            '- **%s** — %s%s'
            % (r['key'], r['note'], ('  Ground/size warnings: ' + '; '.join(r['warnings'])) if r['warnings'] else '')
        )
    lines += ['', '## Studio projects', '']
    for p in PROJECTS:
        lines.append('- %s (`%s`)' % (p['name'], p['id']))
    if not_done:
        lines += ['', '## Not done', '']
        for n in not_done:
            lines.append('- %s' % n)
    lines.append('')
    path = os.path.join(OUT, 'INDEX_v3.md')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))
    _zyg_log.info('wrote ' + path)


def _load(path: str, default):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save_rows(not_done=()) -> None:
    os.makedirs(os.path.dirname(ROWS_PATH), exist_ok=True)
    with open(ROWS_PATH, 'w', encoding='utf-8') as fh:
        json.dump({'rows': ROWS, 'projects': PROJECTS, 'not_done': list(not_done)}, fh, indent=1)


def main(argv) -> int:
    os.makedirs(OUT, exist_ok=True)
    want_scenes = '--scenes' in argv or not (set(argv) & {'--scenes', '--shots', '--index-only'})
    want_shots = '--shots' in argv or not (set(argv) & {'--scenes', '--shots', '--index-only'})
    saved = _load(ROWS_PATH, {})
    not_done: list = list(saved.get('not_done') or [])

    if want_scenes:
        t0 = time.time()
        scenes()
        french_hillside()
        skipped = alpine_km()
        if skipped:
            not_done.append(skipped)
        print('\nscenes phase: %.1f s' % (time.time() - t0), flush=True)
    else:
        ROWS.extend(saved.get('rows') or [])
        PROJECTS.extend(saved.get('projects') or [])
        if not ROWS:
            print('no %s — run --scenes first' % ROWS_PATH, file=sys.stderr)
            return 1

    if want_shots:
        t0 = time.time()
        bad = studio_shots(ROWS)
        not_done += ['live studio screenshot ' + b for b in bad]
        print('\nstudio phase: %.1f s' % (time.time() - t0), flush=True)

    _save_rows(not_done)
    write_index(_load(VERDICTS_PATH, {}), not_done)
    print('\nprojects: ' + ', '.join(p['name'] for p in PROJECTS), flush=True)
    for n in not_done:
        print('NOT DONE: ' + n, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
