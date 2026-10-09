# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The grid, the call budget, the backend settings, the catalogues and the cell arithmetic.

Moved verbatim out of the old single-file arch_assistant.py (lines 71-529).
"""

from __future__ import annotations

import math
import os
import re
import shutil
import time

from zyg_workflows import paths

from zyg_workflows.arch_assistant._base import HERE

# ── the grid ────────────────────────────────────────────────────────────────
GRID_N = 300  # cells per side (THREE.GridHelper(300,300) in the studio)
CELL_M = 1.0  # metres per cell — the DEFAULT; a drawing may carry its own
ORIGIN = -150.0  # world x / z of the grid's A1 corner at CELL_M
# 2026-09-07: the cell size is a per-DRAWING setting (doc.cell_m), so a landscape
# can span kilometres while a building keeps 1 m cells. The grid is always
# GRID_N x GRID_N cells (A1..KN300) centred on the origin; only the metres in a
# cell change, so origin = -GRID_N * cell_m / 2.
CELL_SIZES = (1.0, 2.0, 5.0, 10.0)
_CELL = {'m': CELL_M, 'origin': ORIGIN}
STOREY_M = 2.7  # overwritten from the catalogue defaults per job
WALL_T = 0.24
MAX_OBJECTS = 8000  # a drawing past this stops being interactive


# Model round-trips per job. 28 was the measured ceiling for ONE request; a
# staged build (massing -> core -> floors -> facade -> site) is cheaper as
# several resumed jobs than as one long one (a resumed turn wrote 1,950 cache
# tokens against 76,203 for a fresh spawn), so raise this only when a single
# request genuinely cannot be split. ZYG_ARCH_MAX_CALLS overrides it without a
# code change; it is clamped so a typo cannot spend the operator's whole week.
# 2026-09-16: 28 -> 36. Measured on job 94f5813b (09-12): 14 of the 28 calls were
# finishes — 6 search_materials + 8 set_material/set_finish — so the drawing
# itself had 14 left and the design-check fix loop had none. The finishes now
# arrive by construction (finish_schedule) and the fix tools are free (FIX_TOOLS
# below); the extra 8 calls are the fix loop the gate asks for after design_check.
def _max_calls() -> int:
    v = str(os.environ.get('ZYG_ARCH_MAX_CALLS') or '').strip()
    try:
        return max(6, min(80, int(v))) if v else 36
    except ValueError:
        return 36


MAX_CALLS = _max_calls()


# 2026-09-10: MAX_CALLS is the DRAWING budget — the calls that change the
# drawing. Reads, checks, spec/explain and renders are free, so the CLI's own
# --max-turns must sit ABOVE it or the run is cut off before it can call
# present() and done(). Job 71ac02b0 ended subtype 'error_max_turns' at turn 29
# with no done call at all: --max-turns was MAX_CALLS exactly, and the reads
# and renders ate the budget the drawing needed. ZYG_ARCH_TURN_HEADROOM overrides.
def _turn_headroom() -> int:
    v = str(os.environ.get('ZYG_ARCH_TURN_HEADROOM') or '').strip()
    try:
        return max(0, min(60, int(v))) if v else 12
    except ValueError:
        return 12


CLI_TURN_HEADROOM = _turn_headroom()

# Tools that can never change the drawing. The budget counts a call as a
# drawing call only when the records actually moved (the signature below), but
# once the budget is spent a call has to be refused BEFORE it runs — and the
# only calls that may still run are these.
READONLY_TOOLS = frozenset(
    {
        'get_state',
        'design_check',
        'program_status',
        'help',
        'spec',
        'explain',
        'translate',
        'search_materials',
        'search_assets',
        'list_floor_openings',
        'present',
        'blender_render',
        'look',
        'guarding_check',
        'stair_check',
        'egress_check',
        'ask_user',
        'done',
    }
)
READONLY_PREFIXES = ('get_', 'list_', 'find_', 'search_', 'check_', 'measure_', 'analyse_', 'analyze_')

# 2026-09-16: the FIX tools. design_check hands back findings and the gate then
# asks the model to repair them — a repair that costs drawing budget punishes the
# model for doing what the gate demanded, and job 94f5813b ran out mid-fix. These
# change the drawing but add nothing to it, so they are free. Every name here is
# in TOOL_DEFS (checked by tests_arch_ext/test_wiring_gates.py); 'resize' is NOT a
# tool in this build, so it is not listed.
FIX_TOOLS = frozenset(
    {
        'set_material',
        'set_finish',
        'apply_finishes',
        'delete',
        'cut_floor_opening',
        'move',
        'rotate',
    }
)


def draws(name: str) -> bool:
    """True when this tool could change the drawing (so it costs budget)."""
    n = str(name or '')
    return not (n in READONLY_TOOLS or n in FIX_TOOLS or n.startswith(READONLY_PREFIXES))


# 2026-09-06: NEVER Opus. One 5-call request on claude-opus-5 cost ~$0.11
# (7k input, 1k output, 19k cache reads, a 7k cache write) for a 20-storey
# box with windows — the operator called it "extremely expensive and not
# worth it". Haiku 4.5 does the same tool mapping at ~1/5 of the price. The
# env override still works, but an Opus/Fable/Mythos name is refused and
# replaced with Haiku, with a NOTE in the job log.
CHEAP_MODEL = 'claude-haiku-4-5'
EXPENSIVE = ('opus', 'fable', 'mythos')


def _cheap_model(name: str) -> str:
    name = (name or '').strip() or CHEAP_MODEL
    return CHEAP_MODEL if any(x in name.lower() for x in EXPENSIVE) else name


ANTHROPIC_MODEL = _cheap_model(os.environ.get('ZYG_ARCH_ASSIST_MODEL', CHEAP_MODEL))
OLLAMA_MODEL = os.environ.get('ZYG_ARCH_ASSIST_LOCAL', 'qwen3.6:35b-a3b')
OLLAMA_URL = os.environ.get('OLLAMA_URL', paths.ZYG_OLLAMA_URL)
OLLAMA_NEED_GB = float(os.environ.get('ZYG_ARCH_ASSIST_LOCAL_GB', '26'))
# 2026-09-06: the local model's thinking is capped. Ollama has no thinking
# budget, only num_predict (thinking + answer together), so a step gets this
# many tokens WITH thinking; if it is cut off before it answers, the same step
# is re-run once with thinking OFF. Before this, a 29k-token think filled
# num_ctx (32768), came back with no tool call, and was taken as "Done."
OLLAMA_NUM_PREDICT = int(os.environ.get('ZYG_ARCH_ASSIST_LOCAL_PREDICT', '6144'))
OLLAMA_NUM_CTX = 32768

# ── Claude Code CLI (2026-09-07) ─────────────────────────────────────────────
# The DEFAULT backend. `claude -p` runs on the operator's Claude LOGIN (the
# subscription), not on the API key: the spawn env strips every ANTHROPIC_*
# variable, because the CLI prefers a key over the login whenever one is set
# (the Session Tree board does the same). The drawing tools reach the CLI as an
# MCP server (arch_mcp_shim.py) that forwards every call back to THIS process,
# so the Drawing copy, `look` and `ask_user` stay where they were; only the
# thing that produces tool calls changed. Sonnet by default: the budget here is
# quota shared with the operator's own sessions, and the task is tool mapping.
# 'anthropic' (API key) and 'local' (Ollama) remain as dormant, explicit choices.
CLI_BIN = os.environ.get('ZYG_ARCH_ASSIST_CLI', '') or shutil.which('claude') or '/usr/local/bin/claude'
CLI_MODEL = os.environ.get('ZYG_ARCH_ASSIST_CLI_MODEL', 'sonnet')
# 2026-09-10: output cap + watchdog. The CLI caps a reply at 32,000 output
# tokens by default; a 20-storey "luxurious" request spent ALL of it on one
# up-front planning thought (561 s, no tool call), the CLI's own retry started
# a second thought, and the 900 s watchdog killed the run. The operator asked
# for the limit to be removed: the CLI's hard ceiling for Sonnet/Opus 4.x is
# 64,000 (cli.js `lo()`; anything higher is clamped), so that is the setting,
# and the watchdog doubles with it — the same request succeeded in 739-855 s
# under the old cap, so 900 s was already marginal.
CLI_TIMEOUT = int(os.environ.get('ZYG_ARCH_ASSIST_CLI_TIMEOUT', '1800'))
CLI_MAX_OUTPUT = int(os.environ.get('ZYG_ARCH_ASSIST_CLI_OUT', '64000'))
CLI_DIR = os.path.join(
    HERE, 'data', 'runtime', 'arch_assistant', 'cli'
)  # the CLI's cwd: no CLAUDE.md, no project settings
SHIM = os.path.join(HERE, 'arch_mcp_shim.py')
SERVER_URL = os.environ.get('ZYG_ARCH_ASSIST_URL', 'http://127.0.0.1:%s' % os.environ.get('KANBAN_PORT', '8899'))
MCP_SERVER = 'arch'  # tool names arrive as mcp__arch__<name>


class _MaterialList(list):
    """The 21 flat presets, listed; PLUS membership for any kind in the PBR
    material library (acg_*, pht_*, acgd_*, acga_*) — 2026-09-07. Every tool
    validates `material in MATERIALS`, so this one class opens all of them to
    the ~1,500 measured surfaces without touching each call site. The list
    itself stays the presets so prompts and enums stay short."""

    _lib: set | None = None
    _lib_t: float = 0.0

    def _library(self) -> set:
        if self._lib is None or time.time() - self._lib_t > 300:
            try:
                from zyg_workflows import architecture_materials as AM

                self._lib = set((AM.catalogue() or {}).get('defs') or {})
            except Exception:  # noqa: BLE001
                self._lib = set()
            self._lib_t = time.time()
        return self._lib

    def __contains__(self, item) -> bool:
        if list.__contains__(self, item):
            return True
        s = str(item or '')
        return bool(s) and s.startswith(('acg_', 'pht_', 'acgd_', 'acga_')) and s in self._library()


MATERIALS = _MaterialList(
    [
        'mat_concrete',
        'mat_brick',
        'mat_blockwork',
        'mat_plaster',
        'mat_paint_white',
        'mat_paint_dark',
        'mat_timber',
        'mat_glass',
        'mat_steel',
        'mat_zinc',
        'mat_stone',
        'mat_roof_tile',
        'mat_grass',
        'mat_asphalt',
        'mat_gravel',
        'mat_water',
        'mat_rock',
        'mat_snow',
        'mat_sand',
        'mat_soil',
        'mat_foliage',
    ]
)

# kind -> (parameter names with defaults). Mirrors arGeom() in inspection.html.
KINDS = {
    'wall': {'len': 4, 'h': 2.7, 't': 0.24},
    'partition': {'len': 4, 'h': 2.7, 't': 0.10},
    'door': {'w': 0.9, 'h': 2.1},
    'double_door': {'w': 1.6, 'h': 2.1},
    'window': {'w': 1.2, 'h': 1.4, 'sill': 0.9},
    'opening': {'w': 1.0, 'h': 2.1, 'sill': 0.0},
    'column_rect': {'w': 0.3, 'd': 0.3, 'h': 3},
    'column_round': {'r': 0.18, 'h': 3},
    'beam': {'len': 5, 'w': 0.2, 'h': 0.4},
    'slab': {'w': 6, 'd': 4, 't': 0.22},
    'footing': {'w': 1, 'd': 1, 't': 0.35},
    'truss': {'span': 8, 'h': 1.2, 'bays': 6, 'w': 0.12},
    'stair_straight': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0},
    'stair_l': {'steps_a': 8, 'steps_b': 8, 'rise': 0.175, 'run': 0.28, 'w': 1.0},
    'stair_spiral': {'steps': 18, 'rise': 0.19, 'r_in': 0.15, 'r_out': 1.1, 'sweep': 360},
    'ramp': {'len': 6, 'w': 1.5, 'rise': 0.5, 't': 0.15},
    'railing': {'len': 3, 'h': 1.0, 'posts': 5, 't': 0.04},
    'ladder': {'h': 3, 'w': 0.5, 'rungs': 10, 't': 0.04},
    'roof_flat': {'w': 8, 'd': 6, 't': 0.3},
    'roof_gable': {'w': 8, 'd': 6, 'h': 2.4, 'over': 0.4},
    'roof_hip': {'w': 8, 'd': 6, 'h': 2.4, 'over': 0.4},
    'roof_shed': {'w': 6, 'd': 4, 'h': 1.6, 'over': 0.3},
    'roof_dome': {'r': 3, 'h': 2.4},
    'roof_vault': {'w': 4, 'd': 8, 'h': 2},
    'pad': {'w': 20, 'd': 20, 't': 0.2},
    'road': {'len': 20, 'w': 6, 't': 0.08},
    'path': {'len': 10, 'w': 1.2, 't': 0.05},
    'tree': {'h': 6, 'r_can': 2, 'r_trunk': 0.18},
    'bollard': {'h': 0.9, 'r': 0.09},
    'person': {'h': 1.75},
    'box': {'w': 1, 'd': 1, 'h': 1},
    'cylinder': {'r': 0.5, 'h': 1},
    'sphere': {'r': 0.5},
    'cone': {'r': 0.5, 'h': 1},
    'pyramid': {'r': 0.7, 'h': 1, 'sides': 4},
    'torus': {'r': 0.5, 'rt': 0.15},
    'wedge': {'w': 1, 'd': 1, 'h': 1},
    'capsule': {'r': 0.3, 'h': 1},
    'plane': {'w': 2, 'd': 2},
    'disc': {'r': 1},
}
OPENINGS = ('door', 'double_door', 'window', 'opening')
DEFAULT_MAT = {
    'door': 'mat_timber',
    'double_door': 'mat_timber',
    'opening': 'mat_timber',
    'window': 'mat_plaster',
    'tree': 'mat_grass',
    'pad': 'mat_grass',
    'road': 'mat_asphalt',
    'path': 'mat_asphalt',
    # 2026-09-10: a slab is a FLOOR and a flat roof is a DECK — both
    # used to fall through to the wall's material, which is why the
    # 20-storey "luxury" tower came out concrete inside and out.
    'slab': 'mat_concrete',
    'roof_flat': 'pht_bitumen',
}

# 2026-09-10: what a storey is FINISHED in, per finish level. Walls are the
# massing material the user named (level 'luxury' leaves 'wall' None so the
# caller's word still wins); floors and the roof deck are the two surfaces a
# person actually stands on and looks at, and they are library materials, not
# mat_* presets — the run this table comes from rendered marble apartments and a
# timber pool deck in board-formed grey because both fell back to the wall mat.
# The level is read from d.ext['building_program']['finish_level'].
FINISHES = {
    'standard': {'floor': 'mat_concrete', 'roof': 'pht_bitumen', 'wall': None},
    'luxury': {
        'floor': 'acg_Marble021',
        'roof': 'pht_wood_floor_deck',
        'wall': None,
    },  # 2026-09-11: Marble006 is BLACK (map luminance 25/255)
}


def finish_level(d) -> str:
    """The programme's finish level ('standard' | 'luxury'), or 'standard'."""
    lvl = str(((getattr(d, 'ext', None) or {}).get('building_program') or {}).get('finish_level') or 'standard')
    return lvl if lvl in FINISHES else 'standard'


def finish_mat(d, surface: str, given='') -> str:
    """The material for 'floor' or 'roof': an explicit id wins, then the level."""
    if given and given in MATERIALS:
        return given
    return FINISHES[finish_level(d)].get(surface) or DEFAULT_MAT.get(
        'slab' if surface == 'floor' else 'roof_flat', 'mat_concrete'
    )


# ── cells ───────────────────────────────────────────────────────────────────
def col_letters(c: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ''
    c = int(c)
    while True:
        s = chr(65 + c % 26) + s
        c = c // 26 - 1
        if c < 0:
            return s


def parse_cell(txt) -> tuple:
    """'C4' / 'c 4' / 'AB12' / '3,4' -> (col, row) 0-based, or raise ValueError."""
    s = str(txt or '').strip().upper().replace(' ', '')
    m = re.fullmatch(r'([A-Z]{1,2})(\d{1,3})', s)
    if m:
        letters, num = m.group(1), int(m.group(2))
        c = 0
        for ch in letters:
            c = c * 26 + (ord(ch) - 64)
        c -= 1
        r = num - 1
    else:
        m = re.fullmatch(r'(\d{1,3})[,;/](\d{1,3})', s)
        if not m:
            raise ValueError(f'"{txt}" is not a cell — use a column letter and a row number, like C4 or AB12')
        c, r = int(m.group(1)) - 1, int(m.group(2)) - 1
    if not (0 <= c < GRID_N and 0 <= r < GRID_N):
        raise ValueError(f'cell {txt} is off the grid (A1..{col_letters(GRID_N - 1)}{GRID_N})')
    return c, r


def cell_name(c: int, r: int) -> str:
    return f'{col_letters(c)}{r + 1}'


def cell_size() -> float:
    """Metres per cell for the drawing being worked on right now."""
    return _CELL['m']


def cell_origin() -> float:
    """World x / z of the A1 corner at the current cell size."""
    return _CELL['origin']


def _set_cell_m(m: float) -> float:
    prev = _CELL['m']
    _CELL['m'] = float(m)
    _CELL['origin'] = -GRID_N * float(m) / 2.0
    return prev


def _cell_size_of(v, default: float = CELL_M) -> float:
    """A document's cell_m, or the default when it is missing or not allowed."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f in CELL_SIZES else default


class _Scale:
    """parse_cell / cell_centre / cell_of / block_bounds are module functions with
    no `d`, so the drawing's cell size is installed here for the length of a tool
    call (or a summary) and put back afterwards."""

    def __init__(self, m):
        self.m = float(m or CELL_M)

    def __enter__(self):
        self.prev = _set_cell_m(self.m)
        return self

    def __exit__(self, *a):
        _set_cell_m(self.prev)


def cell_centre(c: int, r: int) -> tuple:
    o, m = _CELL['origin'], _CELL['m']
    return o + (c + 0.5) * m, o + (r + 0.5) * m


def cell_of(x: float, z: float) -> str:
    o, m = _CELL['origin'], _CELL['m']
    c = int(math.floor((x - o) / m))
    r = int(math.floor((z - o) / m))
    c = max(0, min(GRID_N - 1, c))
    r = max(0, min(GRID_N - 1, r))
    return cell_name(c, r)


def block_bounds(cell_from, cell_to) -> tuple:
    """Inclusive cell block -> (xmin, zmin, xmax, zmax) in metres."""
    c0, r0 = parse_cell(cell_from)
    c1, r1 = parse_cell(cell_to)
    ca, cb = sorted((c0, c1))
    ra, rb = sorted((r0, r1))
    o, m = _CELL['origin'], _CELL['m']
    return (o + ca * m, o + ra * m, o + (cb + 1) * m, o + (rb + 1) * m)


def storey_of(y: float, h: float) -> int:
    return int(round((y or 0) / (h or STOREY_M)))


# ── centre + size addressing (2026-09-10) ────────────────────────────────────
# The model converted column letters to numbers BY HAND — base-26 arithmetic,
# three different answers for "20 x 20 centred on FH100" inside ONE 561 s
# thought, then the same again for every tree, lamp and road. So every tool
# that takes a footprint now also takes centre + width + depth in cells, and
# block_around / cell_offset are tools of their own. ONE rule for even sizes:
# a 20-wide block cannot centre on a cell, so it starts size // 2 cells before
# the centre (FH100, 20 x 20 -> EX90..FQ109; the centre cell is the 11th).
def block_around(centre, width, depth=None) -> tuple:
    """(cell_from, cell_to) of a width x depth cell block centred on `centre`."""
    c, r = parse_cell(centre)
    w = max(1, min(GRID_N, int(_num(width, 1))))
    dd = max(1, min(GRID_N, int(_num(depth, w) if depth not in (None, '') else w)))
    c0 = max(0, min(GRID_N - w, c - w // 2))
    r0 = max(0, min(GRID_N - dd, r - dd // 2))
    return cell_name(c0, r0), cell_name(c0 + w - 1, r0 + dd - 1)


def cell_offset(cell, east=0, south=0) -> str:
    """The cell `east` columns to the right (+X) and `south` rows down (+Z)."""
    c, r = parse_cell(cell)
    return cell_name(max(0, min(GRID_N - 1, c + int(_num(east, 0)))), max(0, min(GRID_N - 1, r + int(_num(south, 0)))))


def resolve_block(cell_from, cell_to, centre=None, width=None, depth=None) -> tuple:
    """(cell_from, cell_to): the corners as given, else from centre + width (+ depth)."""
    if centre not in (None, '') and (cell_from in (None, '') or cell_to in (None, '')):
        if width in (None, ''):
            raise ValueError('centre needs width (and depth) in cells')
        return block_around(centre, width, depth)
    if cell_from in (None, '') or cell_to in (None, ''):
        raise ValueError('give cell_from and cell_to, or centre + width + depth')
    return cell_from, cell_to


def _num(v, d):
    try:
        f = float(v)
        return f if math.isfinite(f) else d
    except (TypeError, ValueError):
        return d
