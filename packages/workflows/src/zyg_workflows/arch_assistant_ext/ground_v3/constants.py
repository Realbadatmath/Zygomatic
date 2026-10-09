# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ground_v3: the kinds, the void/sand kind lists, the prompt paragraph and the
numeric limits every other module reads."""

from __future__ import annotations


# ── kinds ────────────────────────────────────────────────────────────────────
KINDS = {
    'ground': {
        'w': 200,
        'd': 200,
        'res': 100,
        'seed': 1,
        'base': 0,
        'amp': 1.5,
        'snow_h': 60,
        'water_h': -0.15,
        'grass_max_slope': 32,
    },
    'sculpt_peak': {'r': 40, 'h': 30, 'rug': 0.45, 'seed': 1, 'feather': 0},
    'sculpt_ridge': {'len': 120, 'w': 40, 'h': 25, 'rug': 0.35, 'seed': 1, 'feather': 0},
    'sculpt_mesa': {'r': 40, 'h': 25, 'top_r': 28, 'rug': 0.25, 'seed': 1, 'feather': 0},
    'sculpt_cut': {'len': 200, 'w': 60, 'depth': 15, 'floor_w': 15, 'profile': 0, 'feather': 0},
    'sculpt_channel': {'len': 120, 'w': 12, 'depth': 2, 'meander': 6, 'seed': 1, 'bank': 2, 'feather': 0},
    'sculpt_basin': {'rx': 40, 'rz': 28, 'depth': 6, 'wobble': 0.25, 'seed': 1, 'shore': 6, 'feather': 0},
    'sculpt_flat': {'w': 40, 'd': 40, 'level': 0, 'feather': 6},
    'sculpt_step': {'len': 120, 'h': 20, 'd': 40, 'rug': 0.3, 'seed': 1, 'feather': 0},
    'sculpt_dunes': {'w': 160, 'd': 80, 'h': 10, 'seed': 1, 'dir': 0, 'feather': 0},
    'sculpt_shelf': {'w': 200, 'd': 120, 'depth': 8, 'feather': 0},
}
OPENINGS: list = []

# The sculpts draw no geometry: an outline in the tab, an empty mesh in Blender.
# tests_arch_ext/test_all.py's sweep must union this into its own VOID_KINDS.
VOID_KINDS = [
    'sculpt_peak',
    'sculpt_ridge',
    'sculpt_mesa',
    'sculpt_cut',
    'sculpt_channel',
    'sculpt_basin',
    'sculpt_flat',
    'sculpt_step',
    'sculpt_dunes',
    'sculpt_shelf',
]

# the two sculpts whose footprint is SAND (a dune belt, a sea bed)
SAND_KINDS = ('sculpt_dunes', 'sculpt_shelf')

PROMPT = (
    'The ground (v3): a drawing has ONE ground and every landform is a sculpt of it — a valley is really a '
    'hollow. make_ground(cell_from, cell_to, style, seed, snow_height, water_level) lays it once, before anything '
    "else ('flat', 'gentle', 'rolling'); a second make_ground is refused. raise_ground and lower_ground shape a "
    "block ('peak', 'ridge', 'mesa', 'valley', 'basin'); level_ground flattens cut AND fill, the flatten for a "
    'building footprint; describe_ground() reports it. explain("ground") has the detail.'
)

# ── constants ────────────────────────────────────────────────────────────────
RES_MAX = 200  # lattice cells a side: 201^2 = 40 401 vertices
RES_MIN = 4
BASE_CELL = 50.0  # metres per cell of the ground's own base noise
FEATHER_FRAC = 0.20  # a sculpt's default feather: 20 % of its size
COLOUR_BAND = 2.0  # metres over which a colour band blends
SLOPE_BAND = 8.0  # degrees over which grass blends into rock
WATER_SOIL = 0.30  # metres above water_h that is still a wet soil bed
COLOUR_MATS = ('mat_grass', 'mat_sand', 'mat_rock', 'mat_snow', 'mat_soil')

STYLE_AMP = {'flat': 0.2, 'gentle': 1.5, 'rolling': 5.0}
PEAK_H_FRAC = (0.25, 1.0)  # a peak is 0.25-1.0 x its radius tall
MESA_H_FRAC = 0.8  # a mesa's top is at most 0.8 x its radius
TROUGH_FRAC = 0.4  # a trough is at most 0.4 x its width deep
LEVEL_BATTER = 0.20  # a sculpt_flat's feather, as a fraction of its short side
