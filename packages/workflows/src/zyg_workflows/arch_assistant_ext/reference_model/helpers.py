# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# This module inherits the original file's top import block verbatim; some of those
# imports are used only by its sibling modules, which import them from here, so F401
# must not strip them out of a range that is promised byte-for-byte.

"""reference_model — the assistant's door to the REFERENCE MODELS (2026-09-23).

The operator drops photographs and plans of a real thing into the icon rail
beside the chat panel; these four tools let the assistant look at them and
build the thing in Blender.

    list_reference_models()     what references exist, what is measured on them
    view_reference(...)         LOOK at the pictures — up to 3 come back as
                                pictures, not as descriptions
    build_reference_asset(...)  run a bpy script in an EMPTY scene with the
                                reference material laid out, save .blend + .glb,
                                and render the result OVER its own plans
    place_reference_asset(...)  drop the built asset into the drawing on a cell

WHY A SEPARATE TOOL FROM ``blender_run``

``blender_run`` opens the DRAWING's .blend. An asset is not part of the
drawing: it has its own origin, its own real size, and it must survive being
placed a hundred times. So this starts from a factory-empty scene, hands the
script the references as geometry (``ref_plane``), and ends with a file.

WHY THE CHECK RENDER IS NOT OPTIONAL-BY-DEFAULT

A model built from pictures is a guess until it is put back against the
pictures. The build renders the asset over each plan it used, in the plan's own
view, as a translucent overlay — so the difference between what was drawn and
what was asked for is a thing you can see rather than a thing you assert. That
is the same measurement the studio's own design checks are built on.

WHAT IT REFUSES TO PRETEND

One photograph cannot fix a size: depth and scale trade off exactly along every
ray. If a reference carries no measured length, every reply here says so, and
the asset is reported as "right shape, unverified size". It is not rounded up
into a claim.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

from zyg_workflows import arch_reference as R
from zyg_workflows.arch_assistant import (
    MAX_OBJECTS,
    Drawing,
    _num,
    cell_centre,
    cell_name,
    parse_cell,
    place_height,
)
import logging as _zyg_logging

from zyg_workflows import paths
from zyg_workflows.paths import ZYG_TMP_DIR, tmp_dir

# ── re-export surface ────────────────────────────────────────────────────────
# Every name below is imported above and not used in this module: the sibling
# modules of the 2026-10 split re-import them from here, which is why the
# verbatim import block was kept. Declaring them makes the re-export deliberate
# rather than an unused import; nothing does ``import *`` from here, so __all__
# changes no behaviour.
__all__ = [
    'glob',
    'json',
    're',
    'shutil',
    'subprocess',
    'sys',
    'time',
    'MAX_OBJECTS',
    'Drawing',
    '_num',
    'cell_centre',
    'cell_name',
    'parse_cell',
    'place_height',
]

#: The ``zyg_workflows`` package directory: the builder script and the work tree hang off it.
HERE = str(paths.PKG_DIR)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.reference_model')


KINDS: dict = {}  # no new kinds — a built asset is the studio's 'asset'
OPENINGS: list = []

BLENDER = os.environ.get('BLENDER_BIN', '/usr/local/bin/blender')
BUILDER = os.path.join(HERE, 'arch_reference_build', 'entry.py')
BUILD_TIMEOUT = int(os.environ.get('ZYG_REF_BUILD_TIMEOUT', '900'))
MAX_SCRIPT = 40000
WORK_DIR = os.path.join(HERE, 'data', 'architecture', 'reference', '_work')
# Every holder of this lock derives the path the same way, so they still meet in one file;
# tmp_dir() creates the directory owner-only instead of the old world-writable /tmp path.
LOCK_PATH = str(ZYG_TMP_DIR / 'arch_ext_blender.lock')
THUMB_W, THUMB_MAX = 1100, 780_000

PROMPT = (
    'Reference models (the icon rail beside the chat panel): the operator can park photographs and measured '
    'PLANS of a real thing — a ship, a bridge, a lamp post — and you build it. list_reference_models() names '
    'them; view_reference() hands you the actual pictures and you must LOOK before modelling; '
    'build_reference_asset(script=...) runs your bpy in an EMPTY scene where ref_plane("view_side") lays each '
    'plan out at its measured size, then saves a .blend + .glb and renders your geometry OVER those plans so '
    'you can see the error; place_reference_asset(cell=...) drops the finished asset into the drawing. '
    + R.LAYOUT
    + ' A reference with no measured length gives the right SHAPE at an unverified size — say so, never invent one. '
    'STANDING RULE (the operator, 2026-09-23): every finished build is handed over with THE PORTFOLIO — '
    'build_reference_asset writes ~50 renders into data/architecture/portfolio/<name>-<id>/ (orbit, '
    'orthographic set, cuts at six stations, a plan cut and two interior views per deck, two raking shots for '
    'curve fairness, close lenses on bow, stern, entry, cabin lights and decks) plus a surface audit of the '
    'materials and the shading. LOOK at the contact sheets it hands back and answer its checklist before you '
    'call anything finished: a door that was never cut, a cabin with no window, an empty hold, an unfair '
    'curve or a default material is a defect to FIX, not a note to write. portfolio_reference_asset() '
    're-photographs an asset you did not just build.'
)

EXAMPLES = [
    {
        'ask': 'build the ship from my reference images',
        'calls': [
            {'tool': 'list_reference_models', 'args': {}},
            {'tool': 'view_reference', 'args': {'role': 'view_side'}},
            {
                'tool': 'build_reference_asset',
                'args': {'name': 'hull', 'script': '<bpy: ref_plane(...), loft the stations, mirror(ob)>'},
            },
            {'tool': 'place_reference_asset', 'args': {'cell': 'F12'}},
        ],
    },
]


class Reply(dict):
    """A tool reply that carries pictures as well as text (shim_tool unwraps
    {'text', 'images'}); it str()s to the text alone so every other caller
    keeps the string it has always had."""

    def __str__(self):
        return str(self.get('text') or '')


class _BlenderLock:
    """Blender runs are SERIALISED across processes — the same advisory lock
    arch_ext_harness, render_offline and scene_shot take. Two headless Blenders
    at once SIGBUS the Bonsai add-on."""

    PATH = LOCK_PATH

    def __enter__(self):
        import fcntl

        tmp_dir()
        self.fh = open(self.PATH, 'w')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        import fcntl

        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


# ── helpers ──────────────────────────────────────────────────────────────────
INSPECT_N = 10
# THE PORTFOLIO (2026-09-23). The operator, the same day the ten-shot set was
# built: "i said 10 before but after every drawing, make sure ai assistant
# delivers portfolio folder with 40+ images from projects" — and with it "make
# sure drawing curves and material quality is done perfectly". Ten pictures
# catch a floating deck; they do not catch a door that was never cut, a cabin
# with no window, a hold with nothing in it, a curve that is not fair or a
# material still on Blender's default grey. Forty-odd, one per deck and one per
# station, do — and the folder is the deliverable, on disk, where the operator
# opens it.
PORTFOLIO_N = 44  # the floor; the generated plan is ~52 (arch_reference_build.PORTFOLIO_N)
PORTFOLIO_CHECKLIST = (
    'THE PORTFOLIO IS THE HAND-OVER. Open the pictures and answer these, one line each, naming the picture '
    'each answer comes from, BEFORE you call the build finished:\n'
    ' 1 OPENINGS: has every way in and out been CUT — doors, hatches, companions, gunports, the entry port? '
    'A painted rectangle is not a door: the deck plans and the sections show whether it goes through.\n'
    ' 2 WINDOWS: do the cabins and the stern have real lights — frame, glass, reveal — and can you see INTO '
    'them in the detail views?\n'
    ' 3 INSIDE: does every deck plan and interior view show a space that is USED — bulkheads, cabins, stores, '
    'ladders, fittings — or an empty volume with a lid?\n'
    ' 4 CURVES: in ortho_side, ortho_plan and rake_side, does every line run FAIR? A kink in the highlight, a '
    'flat spot between two stations or a rail that stops short is a defect, not a look.\n'
    ' 5 MATERIALS: read the audit numbers below. Any mesh with no material, any untouched default, any big '
    'flat-shaded curve is a defect.\n'
    ' 6 SCALE: against the 1.75 m red figure in the interiors, is the headroom, the rail height and the deck '
    'spacing right?\n'
    ' 7 MEETING: in the sections and the close lenses, do the parts MEET — nothing floating, nothing poking '
    'through, no gap at a joint?\n'
    'A no is a fix and another build, not a note.'
)
INSPECT_CHECKLIST = (
    'LOOK at the inspection pictures and answer, one line each, BEFORE you call this finished:\n'
    ' 1 does every surface REST on something, or is a deck/floor hanging in the air?\n'
    ' 2 do the parts MEET — no gap between the body and what carries it, nothing poking through?\n'
    ' 3 do the cut views show an INSIDE (floors, levels, structure), or one empty volume with a lid?\n'
    ' 4 is the thing the right SIZE against the 1.75 m red figure in the interior views?\n'
    ' 5 does anything appear TWICE, or appear as a flat plate where it should be solid?\n'
    ' 6 does the check overlay sit on the plan at BOTH ends and top and bottom?\n'
    'A no is a fix and another build, not a note. Say which picture each answer comes from.'
)


def _resolve(which: str):
    rec = R.resolve(which or '')
    if rec is not None:
        return rec, ''
    names = [f'"{m["name"]}" ({m["id"]})' for m in R.models()]
    if not names:
        return None, (
            'refused: there are no reference models yet — the operator adds one from the picture '
            'icon beside the chat panel, then you can build from it'
        )
    return None, (f'refused: "{which}" does not name one reference model. There are: ' + ', '.join(names[:12]))


def _thumb(png: str) -> list | None:
    """One render as a JPEG [mime, b64] small enough to hand a model."""
    if not png or not os.path.exists(png):
        return None
    try:
        import io

        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(png) as im:
            im = im.convert('RGB')
            if im.width > THUMB_W:
                im = im.resize((THUMB_W, max(1, round(im.height * THUMB_W / im.width))), Image.LANCZOS)
            for q in (86, 70, 55, 40, 30):
                buf = io.BytesIO()
                im.save(buf, 'JPEG', quality=q, optimize=True)
                if buf.tell() <= THUMB_MAX or q == 30:
                    return ['image/jpeg', base64.b64encode(buf.getvalue()).decode('ascii')]
    except Exception:  # noqa: BLE001
        return None
    return None


def _contact_sheet(shots: list, dest: str) -> str:
    """The set as ONE captioned picture — ten separate files are ten clicks,
    and the faults show when the views are seen TOGETHER. Lives in the store so
    a script with no assistant in it can make one."""
    return R.contact_sheet(shots, dest)


def _portfolio_folder(rec: dict, shots: list, audit: dict, meta: dict) -> dict:
    return R.write_portfolio(rec, shots, audit, meta)


def _audit_text(audit: dict, top: int = 8) -> str:
    """The audit as the model has to read it: the findings, then the worst rows.
    Numbers, not adjectives — a facet is a facet at 1200 px and a fair curve at
    600, so "it looks smooth" is not a check."""
    if not audit:
        return ''
    out = ['THE SURFACE AUDIT — curves and materials, measured off the mesh:']
    for f in audit.get('findings') or []:
        out.append('  ! ' + str(f))
    rows = (audit.get('meshes') or [])[:top]
    if rows:
        out.append(
            '  the biggest meshes (faces · smooth% · sharpest bend · share of edges bending 20-60 deg, '
            'which is where UNFAIRNESS shows · share over 60 deg, which are corners · open edges · '
            'material):'
        )
        for r in rows:
            out.append(
                f'    {r["name"]}: {r["faces"]} f · {r["smooth_pct"]}% smooth · '
                f'{r["max_bend_deg"]} deg · {r.get("unfair_pct", 0)}% unfair · '
                f'{r.get("corner_pct", 0)}% corners · {r["open_edges"]} open · '
                + (', '.join(r.get('mats') or []) or 'NO MATERIAL')
            )
    mats = audit.get('materials') or []
    if mats:
        out.append(
            '  materials: '
            + '; '.join(
                f'{m["name"]} (base {m.get("base")}, rough {m.get("rough")}'
                + (', metal ' + str(m.get('metal')) if m.get('metal') else '')
                + (', TEXTURED' if m.get('image') else ', flat colour')
                + ')'
                for m in mats[:12]
            )
        )
    return '\n'.join(out)


def _scale_note(rec: dict) -> str:
    return (
        ''
        if R.measurable(rec)
        else ' NOTE: nothing is measured on this reference, so the asset is the right SHAPE at an UNVERIFIED '
        'size — say so, and ask the operator for one real dimension if the size matters.'
    )
