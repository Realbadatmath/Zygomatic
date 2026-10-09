# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_landscape.constants — vocabulary, real-world sizes and the real-model picks.

Moved verbatim out of the 1,180-line site_landscape.py; original lines
57-218.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import EXT_MODULES, MATERIALS, _num, cell_centre, parse_cell

KINDS = {
    'fence': {'len': 5, 'h': 1.2, 'posts': 3, 'rails': 3, 't': 0.04},
    'hedge': {'len': 5, 'h': 1.2, 'w': 0.6},
    'tree_conifer': {'h': 8, 'r': 2},
    'tree_palm': {'h': 7, 'fronds': 7},
    'tree_deciduous': {'h': 7, 'r_can': 3, 'r_trunk': 0.25},
    'shrub': {'r': 0.6, 'h': 0.8},
    'flowerbed': {'w': 3, 'd': 1.5, 't': 0.15, 'gx': 0, 'gz': 0},
    'lamp_post': {'h': 4, 'r': 0.06},
    'bench': {'len': 1.8, 'h': 0.45},
    'bin': {'r': 0.25, 'h': 0.9},
    'kerb': {'len': 5, 'h': 0.12, 'w': 0.15},
    'sidewalk': {'len': 10, 'w': 2, 't': 0.06, 'gx': 0, 'gz': 0},
    'parking_bay': {'w': 2.5, 'd': 5, 't': 0.02, 'gx': 0, 'gz': 0},
    'road_curved': {'r': 10, 'a0': 0, 'a1': 90, 'w': 6, 't': 0.08, 'seg': 24},
}
OPENINGS: list = []

PROMPT = (
    'Site & landscape: plant_trees(cell_from, cell_to, spacing, count, kind, height, jitter, seed) fills a block '
    'with tree_deciduous (6-20 m) / tree_conifer (8-25 m) / tree_palm (5-15 m) on a grid or scattered by the seed; '
    'add_fence(cells, kind=fence|hedge, height) runs a fence or hedge leg by leg; add_parking(cell_from, cell_to, '
    'bay_w, bay_d, direction) tiles a block with bays; add_road(cells, width) and add_curved_road(centre, radius, '
    'start_deg, end_deg, width) lay carriageway (0 = east, 90 = north); add_street_furniture(cells, kind=lamp_post|'
    'bench|bin, rotation_deg) drops one item per cell; add_garden_bed(cell_from, cell_to, kind=flowerbed|hedge|'
    'shrubs) plants a bed, a hedge or a grid of shrubs. Site things land on the ground under them: every tree, '
    'bench and bay takes the height of the hill or slope beneath it, beds and bays tilt with the ground (gx, gz), '
    'fences and roads run downhill, a car park refuses ground that is not near level (flatten_pad it first), and '
    'real sizes never scale with the block. base_height overrides the ground; site work sits at storey 0.'
)

TREE_KINDS = ('tree_deciduous', 'tree_conifer', 'tree_palm', 'tree')
FENCE_KINDS = ('fence', 'hedge')
FURNITURE_KINDS = ('lamp_post', 'bench', 'bin')
BED_KINDS = ('flowerbed', 'hedge', 'shrubs')

# R7 — real-world sizes, absolute, never scaled with the block.
TREE_RANGE = {'tree_deciduous': (6.0, 20.0), 'tree': (6.0, 20.0), 'tree_conifer': (8.0, 25.0), 'tree_palm': (5.0, 15.0)}
TREE_DEFAULT_H = {'tree_deciduous': 8.0, 'tree': 8.0, 'tree_conifer': 12.0, 'tree_palm': 8.0}
CROWN_R = (1.5, 4.0)  # a crown is 3-8 m across
FURNITURE_RANGE = {'lamp_post': (3.0, 6.0)}
FENCE_LEAN = 0.15  # steeper than this and a fence leg is cut up
FENCE_PIECE = 5.0  # metres per piece when it is
PARK_SPREAD = 0.5  # a car park needs ground flatter than this
PARK_SLOPE = 0.08  # ...and shallower than 8 %
TILE_SPREAD = 1.0  # a surface over rougher ground than this is tiled
MAX_TILES = 64


def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _rnd(seed, i, salt=0):
    """A tiny LCG on (seed, index) -> [0, 1). Deterministic on purpose."""
    x = (int(seed) * 1103515245 + int(i) * 12345 + int(salt) * 6971 + 12345) & 0x7FFFFFFF
    x = (x * 1103515245 + 12345) & 0x7FFFFFFF
    x = (x * 1103515245 + 12345) & 0x7FFFFFFF
    return x / 2147483648.0


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


# ── real models (2026-09-08, design rules) ───────────────────────────────────
# A sphere on a cylinder is a massing placeholder. The packs hold life-size
# photoscanned trees and a real street lamp, so plant_trees and
# add_street_furniture place THOSE unless model="parametric" is asked for.
# Species -> candidate "pack|item" ids, each with its native height; the one
# whose native height is closest to the asked height wins and is scaled to
# it (kept within 0.6..1.6 x so a sapling never becomes a 20 m tree).
REAL_TREES = {
    'tree_deciduous': [
        'polyhaven_arch|island_tree_01_2k',
        'polyhaven_arch|tree_small_02_2k',
        'blender_studio/sprite_fright_env|oak_en_tree_1',
        'polyhaven_arch|jacaranda_tree_2k',
        'polyhaven_arch|island_tree_02_2k',
    ],
    'tree': [
        'polyhaven_arch|island_tree_01_2k',
        'blender_studio/sprite_fright_env|oak_en_tree_1',
        'polyhaven_arch|tree_small_02_2k',
        'polyhaven_arch|jacaranda_tree_2k',
    ],
    'tree_conifer': [
        'polyhaven_arch|fir_sapling_medium_2k',
        'polyhaven_arch|pine_sapling_medium_2k',
        'polyhaven_arch|fir_tree_01_2k',
        'polyhaven_arch|pine_tree_01_2k',
    ],
    'tree_palm': [],  # no life-size palm in the packs
}
REAL_LAMPS = ['polyhaven_arch|street_lamp_01_2k']
SCALE_RANGE = (0.6, 1.6)
CROWN_FIT = 0.8  # trees may stand this fraction of a crown diameter apart before they merge

# ── site defaults (2026-09-11, live job 94f5813b) ────────────────────────────
# Six 5.0 m lamp posts were placed under a 4.2 m porte-cochere soffit, two of
# them beside a canopy column, and four of them inside an 8 m drive. Nothing on
# this site stands under a canopy plate, taller than the soffit near one, or in
# the carriageway — the tools now work that out instead of the model.
CANOPY_KINDS = ('canopy', 'awning')
CANOPY_CLEAR = 1.0  # nothing stands within this of a canopy footprint
CANOPY_NEAR = 6.0  # inside this a lamp is clamped under the soffit
SOFFIT_GAP = 0.5  # ...to this far below it
LAMP_DEFAULT_H = 4.0  # a street lamp with no height asked for
ROAD_CLEAR = 0.3  # nothing stands within w/2 + this of a road centreline
ROAD_OFFSET = 0.5  # ...and a refusal names w/2 + this as the offset to use


def _assets():
    return EXT_MODULES.get('assets_search')


def _real_pick(ids, want_h):
    """(row, scale) for the candidate whose native height is closest to want_h, or (None, 1).

    2026-09-11: every life-size tree in the packs is a photoscan of 0.6-17 M
    triangles, and plant_trees places them by the dozen — the live tower job
    came out at 15.66 M, 15.5 M of it four jacarandas. A candidate over
    assets_search.TRI_BUDGET is swapped for its _lod1 stand-in, and drops out of
    the running when none has been built: the next species down is a real tree
    too, whereas a scene nothing can open is not a site plan."""
    AS = _assets()
    if AS is None:
        return None, 1.0
    best = None
    for aid in ids:
        r, _why = AS.within_budget(AS._index()['by_id'].get(aid))
        if not r or r['size'][1] <= 0:
            continue
        sc = want_h / r['size'][1]
        sc = max(SCALE_RANGE[0], min(SCALE_RANGE[1], sc))
        # closest to the asked height first, then the smallest rescale (a model
        # near its native size keeps its bark and leaf scale honest)
        err = (round(abs(r['size'][1] * sc - want_h), 2), abs(sc - 1.0))
        if best is None or err < best[0]:
            best = (err, r, sc)
    return (best[1], round(best[2], 3)) if best else (None, 1.0)


def _tree_p(kind, h):
    h = max(1.0, _num(h, TREE_DEFAULT_H.get(kind, 8.0)))
    if kind == 'tree_conifer':
        return {'h': round(h, 2), 'r': round(_clamp(h * 0.25, 1.0, 4.0), 2)}
    if kind == 'tree_palm':
        return {'h': round(h, 2), 'fronds': 7}
    if kind == 'tree':
        return {'h': round(h, 2), 'r_can': round(_clamp(h * 0.33, *CROWN_R), 2), 'r_trunk': 0.18}
    return {'h': round(h, 2), 'r_can': round(_clamp(h * 0.42, *CROWN_R), 2), 'r_trunk': 0.25}


def _cells(cells, least=2):
    if not isinstance(cells, (list, tuple)) or len(cells) < least:
        raise ValueError(f'give a list of at least {least} cell names, like ["C4", "H4", "H9"]')
    return [cell_centre(*parse_cell(c)) for c in cells]


def _ry(a, b):
    return math.atan2(-(b[1] - a[1]), b[0] - a[0])
