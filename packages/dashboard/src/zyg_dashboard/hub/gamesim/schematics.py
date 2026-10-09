# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Built-in and custom Minecraft schematics, and the schematics board."""

import json
import logging as _zyg_logging
import threading
from pathlib import Path

import schem_store

from .config import GAMESIM_DIR
from . import HUB_DIR

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Schematics (Minecraft builds for the build-FP sim) ─────────────────
BUILD_FP_DIR = Path(GAMESIM_DIR) / 'minecraft_build_fp'
SCHEMATIC_FILE = BUILD_FP_DIR / 'schematic_current.json'
BUILD_STATUS_FILE = BUILD_FP_DIR / 'build_status.json'
SCHEM_STATE_FILE = HUB_DIR / 'schematics_state.json'
QUEUE_STATE_FILE = HUB_DIR / 'production_queue.json'
BUILD_FP_GAME = 'Minecraft Build FP'


def _blk(x, y, z, mat, kind):
    return {'x': x, 'y': y, 'z': z, 'mat': mat, 'kind': kind}


def _stair_ring(xlo, xhi, zlo, zhi, ybase, ytop, mat='cobblestone'):
    """Interior wall-adjacent ring of rising columns, clockwise from the SW
    interior corner — walkable footing so the bot can reach upper walls
    (same idea as the original tower's spiral staircase)."""
    x0, x1 = xlo + 1, xhi - 1
    z0, z1 = zlo + 1, zhi - 1
    cells = []
    for x in range(x0, x1 + 1):
        cells.append((x, z1))  # south wall, W→E
    for z in range(z1 - 1, z0 - 1, -1):
        cells.append((x1, z))  # east wall, S→N
    for x in range(x1 - 1, x0 - 1, -1):
        cells.append((x, z0))  # north wall, E→W
    for z in range(z0 + 1, z1):
        cells.append((x0, z))  # west wall, N→S
    n = max(len(cells) - 1, 1)
    blocks = []
    for i, (x, z) in enumerate(cells):
        top = ybase + round(i * (ytop - ybase) / n)
        for y in range(ybase, top + 1):
            blocks.append(_blk(x, y, z, mat, 'stair'))
    blocks.sort(key=lambda b: b['y'])  # layer-by-layer, self-supporting
    return blocks


def _side_order(b, xlo, xhi, zlo, zhi):
    if b['z'] == zhi:
        return 1
    if b['x'] == xhi:
        return 2
    if b['z'] == zlo:
        return 3
    if b['x'] == xlo:
        return 4
    return 5


def _ring_order(b, zlo, zhi):
    if b['z'] in (zlo, zhi):
        return b['x']
    return -b['z']


def _box_walls(xlo, xhi, zlo, zhi, ybase, ytop, mat_fn, skip_fn=None):
    """Hollow rectangular walls built as one circuit per floor."""
    walls = []
    for y in range(ybase, ytop + 1):
        for x in range(xlo, xhi + 1):
            for z in range(zlo, zhi + 1):
                if x not in (xlo, xhi) and z not in (zlo, zhi):
                    continue
                if skip_fn and skip_fn(x, y, z):
                    continue
                m = mat_fn(x, y, z)
                if m:
                    walls.append(_blk(x, y, z, m, 'wall'))
    walls.sort(key=lambda b: (b['y'], _side_order(b, xlo, xhi, zlo, zhi), _ring_order(b, zlo, zhi)))
    return walls


def _schem_watchtower():
    XLO, XHI, ZLO, ZHI, YB, YT = -3, 3, -9, -3, 65, 70
    blocks = _stair_ring(XLO, XHI, ZLO, ZHI, YB, YT)

    def mat(x, y, z):
        if x in (XLO, XHI) and z in (ZLO, ZHI):
            return 'dark_oak_log'
        return 'mossy_stone_bricks' if y % 4 == 0 else 'stone_bricks'

    def door(x, y, z):
        return z == ZHI and abs(x) <= 1 and y <= 66

    blocks += _box_walls(XLO, XHI, ZLO, ZHI, YB, YT, mat, door)
    for x in range(XLO, XHI + 1):
        if x % 2 == 0:
            blocks.append(_blk(x, YT + 1, ZLO, 'chiseled_stone_bricks', 'battlement'))
            blocks.append(_blk(x, YT + 1, ZHI, 'chiseled_stone_bricks', 'battlement'))
    for z in range(ZLO + 1, ZHI):
        if z % 2 == 0:
            blocks.append(_blk(XLO, YT + 1, z, 'chiseled_stone_bricks', 'battlement'))
            blocks.append(_blk(XHI, YT + 1, z, 'chiseled_stone_bricks', 'battlement'))
    return blocks


def _schem_castle_keep():
    XLO, XHI, ZLO, ZHI, YB, YT = -4, 4, -12, -4, 65, 70
    blocks = _stair_ring(XLO, XHI, ZLO, ZHI, YB, YT)

    def mat(x, y, z):
        if x in (XLO, XHI) and z in (ZLO, ZHI):
            return 'dark_oak_log'
        if y in (65, 68):
            return 'mossy_stone_bricks'
        if (x * 7 + z * 13 + y) % 9 == 0:
            return 'cracked_stone_bricks'
        return 'stone_bricks'

    def gate(x, y, z):
        return z == ZHI and abs(x) <= 1 and y <= 66

    blocks += _box_walls(XLO, XHI, ZLO, ZHI, YB, YT, mat, gate)
    # battlements along the wall tops, corner turret caps above the oak columns
    for x in range(XLO, XHI + 1):
        for z in range(ZLO, ZHI + 1):
            if x not in (XLO, XHI) and z not in (ZLO, ZHI):
                continue
            corner = x in (XLO, XHI) and z in (ZLO, ZHI)
            if corner:
                blocks.append(_blk(x, YT + 1, z, 'chiseled_stone_bricks', 'battlement'))
                blocks.append(_blk(x, YT + 2, z, 'chiseled_stone_bricks', 'battlement'))
            elif (x + z) % 2 == 0:
                blocks.append(_blk(x, YT + 1, z, 'stone_bricks', 'battlement'))
    return blocks


def _schem_fortress_wall():
    Z = -8
    blocks = []
    for y in range(65, 69):
        for x in range(-6, 7):
            m = 'cracked_stone_bricks' if (x * 5 + y) % 7 == 0 else 'stone_bricks'
            blocks.append(_blk(x, y, Z, m, 'wall'))
    for x in range(-6, 7):
        if x % 2 == 0:
            blocks.append(_blk(x, 69, Z, 'chiseled_stone_bricks', 'battlement'))
    for x in (-5, 0, 5):
        for y in (65, 66):
            blocks.append(_blk(x, y, Z + 1, 'cobblestone', 'buttress'))
    return blocks


def _schem_cottage():
    XLO, XHI, ZLO, ZHI = -3, 3, -9, -4
    blocks = []
    # garden steps up the east side so the bot can climb onto the roof
    for i, z in enumerate((-5, -6, -7)):
        for y in range(65, 66 + i):
            blocks.append(_blk(XHI + 1, y, z, 'cobblestone', 'stair'))

    def mat(x, y, z):
        if x in (XLO, XHI) and z in (ZLO, ZHI):
            return 'oak_log'
        if y == 66 and ((z == ZLO and x in (-1, 1)) or (x in (XLO, XHI) and z in (-6, -7))):
            return 'glass'
        return 'oak_planks'

    def door(x, y, z):
        return z == ZHI and x == 0 and y <= 66

    blocks += _box_walls(XLO, XHI, ZLO, ZHI, 65, 67, mat, door)
    # gable triangles on the south/north ends
    for gz in (ZHI, ZLO):
        for y, half in ((68, 2), (69, 1), (70, 0)):
            for x in range(-half, half + 1):
                blocks.append(_blk(x, y, gz, 'oak_planks', 'gable'))
    # stepped roof sloping up to a ridge, 1-block overhang at both ends
    for lvl in range(4):
        y = 68 + lvl
        xs = [0] if lvl == 3 else [-(3 - lvl), 3 - lvl]
        for z in range(ZLO - 1, ZHI + 2):
            for x in xs:
                blocks.append(_blk(x, y, z, 'spruce_planks', 'roof'))
    return blocks


def _schem_pyramid():
    CX, CZ = 0, -7
    blocks = []
    for lvl in range(5):
        half = 4 - lvl
        y = 65 + lvl
        m = 'cut_sandstone' if lvl % 2 == 1 else 'sandstone'
        for x in range(CX - half, CX + half + 1):
            for z in range(CZ - half, CZ + half + 1):
                blocks.append(_blk(x, y, z, m, 'core'))
    blocks.append(_blk(CX, 70, CZ, 'glowstone', 'cap'))
    return blocks


def _schem_lighthouse():
    CX, CZ = 0, -7
    blocks = [_blk(0, 65, -4, 'cobblestone', 'stair')]  # approach step onto the base
    for y in (65, 66):
        for x in range(CX - 2, CX + 3):
            for z in range(CZ - 2, CZ + 3):
                blocks.append(_blk(x, y, z, 'stone_bricks', 'base'))
    for y, m in ((67, 'quartz_block'), (68, 'red_wool'), (69, 'quartz_block')):
        for x in range(CX - 1, CX + 2):
            for z in range(CZ - 1, CZ + 2):
                blocks.append(_blk(x, y, z, m, 'tower'))
    blocks.append(_blk(CX, 70, CZ, 'glowstone', 'lamp'))
    return blocks


def _schem_bridge():
    blocks = []
    for z in (-3, -7, -11):
        for x in (-1, 0, 1):
            blocks.append(_blk(x, 65, z, 'cobblestone', 'pier'))
    for z in range(-2, -13, -1):
        for x in (-1, 0, 1):
            blocks.append(_blk(x, 66, z, 'stone_bricks', 'deck'))
    for z in range(-2, -13, -1):
        if z % 2 == 0:
            blocks.append(_blk(-1, 67, z, 'cobblestone', 'rail'))
            blocks.append(_blk(1, 67, z, 'cobblestone', 'rail'))
    return blocks


def _schem_fountain():
    CX, CZ = 0, -7
    blocks = []
    for x in range(CX - 2, CX + 3):
        for z in range(CZ - 2, CZ + 3):
            if x in (CX - 2, CX + 2) or z in (CZ - 2, CZ + 2):
                blocks.append(_blk(x, 65, z, 'stone_bricks', 'basin'))
    for y in (65, 66, 67):
        blocks.append(_blk(CX, y, CZ, 'polished_andesite', 'column'))
    blocks.append(_blk(CX, 68, CZ, 'glowstone', 'cap'))
    return blocks


def _schem_obelisk():
    CX, CZ = 0, -7
    blocks = [_blk(0, 65, -5, 'cobblestone', 'stair')]  # approach step onto the base
    for y in (65, 66):
        for x in (CX - 1, CX, CX + 1):
            for z in (CZ - 1, CZ, CZ + 1):
                blocks.append(_blk(x, y, z, 'obsidian', 'base'))
    for y in (67, 68, 69):
        blocks.append(_blk(CX, y, CZ, 'obsidian', 'spire'))
    blocks.append(_blk(CX, 70, CZ, 'glowstone', 'beacon'))
    return blocks


def _schem_nether_portal():
    Z = -7
    blocks = []
    for x in range(-1, 3):
        blocks.append(_blk(x, 65, Z, 'obsidian', 'frame'))
    for y in range(66, 69):
        blocks.append(_blk(-1, y, Z, 'obsidian', 'frame'))
        blocks.append(_blk(2, y, Z, 'obsidian', 'frame'))
    for x in range(-1, 3):
        blocks.append(_blk(x, 69, Z, 'obsidian', 'frame'))
    return blocks


def _schem_meta(sid, name, desc, category, difficulty, blocks):
    xs = [b['x'] for b in blocks]
    ys = [b['y'] for b in blocks]
    zs = [b['z'] for b in blocks]
    mats = {}
    for b in blocks:
        mats[b['mat']] = mats.get(b['mat'], 0) + 1
    return {
        'id': sid,
        'name': name,
        'desc': desc,
        'category': category,
        'difficulty': difficulty,
        'blocks': blocks,
        'materials': mats,
        'block_count': len(blocks),
        'size': {'w': max(xs) - min(xs) + 1, 'h': max(ys) - min(ys) + 1, 'd': max(zs) - min(zs) + 1},
        'est_minutes': max(1, round(len(blocks) * 1.8 / 60) + 2),
    }


SCHEMATICS = {}
for _s in [
    _schem_meta(
        'watchtower',
        'Watchtower',
        'Six-storey stone watchtower with an internal spiral staircase and battlements.',
        'Tower',
        'medium',
        _schem_watchtower(),
    ),
    _schem_meta(
        'castle-keep',
        'Castle Keep',
        '9×9 fortified keep — dark oak corner columns, mossy banding, crowned battlements.',
        'Castle',
        'hard',
        _schem_castle_keep(),
    ),
    _schem_meta(
        'fortress-wall',
        'Fortress Wall',
        'Crenellated curtain-wall segment with cobblestone buttresses.',
        'Castle',
        'easy',
        _schem_fortress_wall(),
    ),
    _schem_meta(
        'cozy-cottage',
        'Cozy Cottage',
        'Oak cottage with glass windows and a stepped spruce gable roof.',
        'House',
        'medium',
        _schem_cottage(),
    ),
    _schem_meta(
        'stone-pyramid',
        'Sandstone Pyramid',
        'Nine-wide stepped pyramid with a glowstone capstone.',
        'Monument',
        'medium',
        _schem_pyramid(),
    ),
    _schem_meta(
        'lighthouse',
        'Lighthouse',
        'Quartz-and-red banded lighthouse with a glowing lamp room.',
        'Tower',
        'easy',
        _schem_lighthouse(),
    ),
    _schem_meta(
        'stone-bridge',
        'Stone Bridge',
        'Three-wide stone bridge on cobblestone piers with side rails.',
        'Infrastructure',
        'easy',
        _schem_bridge(),
    ),
    _schem_meta(
        'garden-fountain',
        'Garden Fountain',
        'Stone basin fountain with a glowing andesite column.',
        'Infrastructure',
        'easy',
        _schem_fountain(),
    ),
    _schem_meta(
        'obsidian-obelisk',
        'Obsidian Obelisk',
        'Dark obsidian monument crowned with a glowstone beacon.',
        'Monument',
        'easy',
        _schem_obelisk(),
    ),
    _schem_meta(
        'nether-portal',
        'Nether Portal',
        'Classic 4×5 obsidian portal frame.',
        'Monument',
        'easy',
        _schem_nether_portal(),
    ),
]:
    SCHEMATICS[_s['id']] = _s

BUILTIN_SCHEMATIC_IDS = frozenset(SCHEMATICS)


def load_custom_schematics():
    """Merge user-created schematics into the registry.

    LOAD ORDER IS LOAD-BEARING: _load_schem_columns() and _load_queue() both
    filter with `in SCHEMATICS`, so this must run BEFORE either of them or every
    custom card's column and every queued custom build is silently discarded on
    each restart — and it would look like a UI bug, not a load-order bug.
    """
    n = 0
    for rec in schem_store.load_all():
        if rec['id'] in BUILTIN_SCHEMATIC_IDS:
            continue  # never let a custom file shadow a built-in
        SCHEMATICS[rec['id']] = rec
        n += 1
    return n


_custom_loaded = load_custom_schematics()
if _custom_loaded:
    _zyg_log.info(f'[schematics] loaded {_custom_loaded} custom schematic(s)')

SCHEM_COLUMN_IDS = ('backlog', 'ready', 'inproduction', 'built')
DEFAULT_SCHEM_COLUMNS = {
    'watchtower': 'ready',
    'castle-keep': 'ready',
    'cozy-cottage': 'ready',
    'stone-pyramid': 'ready',
    'lighthouse': 'backlog',
    'stone-bridge': 'backlog',
    'fortress-wall': 'backlog',
    'garden-fountain': 'backlog',
    'obsidian-obelisk': 'backlog',
    'nether-portal': 'backlog',
}

_schem_lock = threading.Lock()


def _load_schem_columns():
    cols = dict(DEFAULT_SCHEM_COLUMNS)
    try:
        saved = json.loads(SCHEM_STATE_FILE.read_text())
        for k, v in saved.items():
            if k in SCHEMATICS and v in SCHEM_COLUMN_IDS:
                cols[k] = v
    except (OSError, ValueError, AttributeError) as _exc:
        _zyg_log.warning('schematic column state unreadable, continuing with the defaults: %s', _exc)
    return cols


def _set_schem_column(sid, column):
    with _schem_lock:
        cols = _load_schem_columns()
        cols[sid] = column
        try:
            SCHEM_STATE_FILE.write_text(json.dumps(cols, indent=1))
        except OSError as _exc:
            _zyg_log.warning('schematic column state not saved, the move is lost on restart: %s', _exc)


def _read_build_status():
    try:
        return json.loads(BUILD_STATUS_FILE.read_text())
    except Exception:
        return None


def _write_schematic_file(schem):
    payload = {'id': schem['id'], 'name': schem['name'], 'materials': schem['materials'], 'blocks': schem['blocks']}
    SCHEMATIC_FILE.write_text(json.dumps(payload))
    try:
        BUILD_STATUS_FILE.unlink()
    except FileNotFoundError as _exc:
        _zyg_log.debug('no build status file to clear: %s', _exc)


DEFAULT_SCHEMATIC_ID = 'watchtower'


def _ensure_schematic_file():
    """bot.js has no built-in fallback structure by design — the hub is the single
    source of truth. The Creation tab can start the build sim directly without
    picking a schematic, so give it the default rather than letting the bot fail.
    """
    if SCHEMATIC_FILE.exists():
        return
    schem = SCHEMATICS.get(DEFAULT_SCHEMATIC_ID) or next(iter(SCHEMATICS.values()))
    _write_schematic_file(schem)
    _zyg_log.info(f"[schematics] no schematic selected — wrote default '{schem['id']}'")
