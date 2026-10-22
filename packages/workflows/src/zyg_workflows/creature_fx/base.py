# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

#   HERE below is the ONE line of the old file that could not travel verbatim:
#   creature_fx.py sat directly in zyg_workflows/, so dirname(__file__) WAS the
#   directory that owns data/. This module sits one level deeper and climbs back
#   out, the same way every module under geom/ does. HERE, and with it DATA,
#   RUNTIME, PRESETS, JOBDIR, PROP_ROOT and PACKS_ROOT, resolve unchanged.
"""Module constants, the path fences, the five parameter-schema helpers and the op registry itself.

Moved verbatim out of the old single-file creature_fx.py (lines 58-258).
"""

from __future__ import annotations

import os
import re
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, 'data')
RUNTIME = os.path.join(DATA, 'runtime')
PRESETS = os.path.join(RUNTIME, 'creature_fx_presets.json')
JOBDIR = os.path.join(RUNTIME, 'creature_fx_jobs')

DS_ROOT = os.path.realpath(paths.ZYG_CREATURE_DATASETS)
OUT_ROOT = os.path.realpath(paths.ZYG_CREATURE_OUTPUTS)

# The three roots a creature's mesh may legitimately come from, and the pack the
# 3D view falls back to when a creature has none. Anything under mesh_packs is
# served straight by /inspect/arch-asset/<rel>; prop_meshes and the dataset dirs
# sit outside that root, so they go through the studio route
# /inspect/api/studio/creature/glb?id=<cid> (studio_ext_server/creature.py).
PROP_ROOT = os.path.realpath(os.path.join(DATA, 'assets', 'prop_meshes'))
PACKS_ROOT = os.path.realpath(os.path.join(DATA, 'assets', 'mesh_packs'))
BASE_PACK = 'zyg_creatures'
BASE_PACK_DIR = os.path.join(PACKS_ROOT, BASE_PACK)
# The ordered list of THIRD-PARTY CC0 stand-ins the 3D view shows when nothing is
# injected. Our own pufferball (zyg_creatures) is deliberately NOT in it: it is
# one creature's own mesh, not a neutral base to work against.
BASES_JSON = os.path.join(PACKS_ROOT, 'quaternius_animals', 'BASES.json')
GEN_PREVIEWS = '_generated_previews'

ID_RE = re.compile(r'^[a-f0-9]{12}$')
NAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,120}$')
IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')

# Where each image category lives relative to the dataset dir. Identical to the
# map kanban_server serves images from -- one more category, `studio`, which is
# where this module's own bakes land. The caller never supplies a path fragment:
# a category is a key in this dict or the request is refused.
CATS = {
    'preview': ('', 'Preview render'),
    'sheet': ('contact_sheet', 'Contact sheet'),
    'cell': (os.path.join('contact_sheet', 'cells'), 'Sheet cell'),
    'anchor': (os.path.join('contact_sheet', 'anchors'), 'Anchor'),
    'lock': ('locks', 'Operator lock'),
    'ref': ('', 'Reference'),
    'val': ('__out__', 'Validation'),
    'mesh': ('mesh_trellis', 'Mesh reconstruction'),
    'studio': ('studio', 'Studio edit'),
}
STUDIO_CAT = 'studio'

# FLUX.1-dev creatures: the base licence is non-commercial, the channel is
# monetised, and the tab already withholds their imagery. Rendering a NEW image
# off one would mint a fresh non-commercial asset, so the studio refuses --
# deterministic pixel ops on what is already on disk are still allowed, because
# they create no new model output.
FLUX1_FAMILIES = {'flux', 'flux1', 'flux-dev', 'flux_dev', 'flux.1-dev', 'flux1-dev'}
LICENCES = {
    'klein': ('Apache-2.0', True, 'FLUX.2 klein-4B base — commercial use OK'),
    'qwen': ('Apache-2.0', True, 'Qwen-Image base — commercial use OK'),
    'sdxl': ('CreativeML OpenRAIL++-M', True, 'SDXL base — commercial use OK'),
    'flux': (
        'FLUX.1-dev non-commercial',
        False,
        'FLUX.1-dev base — NON-COMMERCIAL; renders paused by the licence gate',
    ),
}

PREVIEW_MAX = 1024
CELL_PX = int(os.environ.get('ZYG_CREATURE_CELL_PX', '1024'))


# ── parameter schema helpers (same five types the VFX toolbox uses) ─────────
def f(k, lb, df, mn, mx, st=0.01, tip=''):
    return {'k': k, 'lb': lb, 't': 'f', 'df': df, 'mn': mn, 'mx': mx, 'st': st, 'tip': tip}


def i(k, lb, df, mn, mx, st=1, tip=''):
    return {'k': k, 'lb': lb, 't': 'i', 'df': df, 'mn': mn, 'mx': mx, 'st': st, 'tip': tip}


def b(k, lb, df=False, tip=''):
    return {'k': k, 'lb': lb, 't': 'b', 'df': bool(df), 'tip': tip}


def e(k, lb, df, opts, tip=''):
    return {'k': k, 'lb': lb, 't': 'e', 'df': df, 'opts': list(opts), 'tip': tip}


def c(k, lb, df='#7fd8c8', tip=''):
    return {'k': k, 'lb': lb, 't': 'c', 'df': df, 'tip': tip}


def s(k, lb, df='', tip='', pat=r"[-+0-9a-zA-Z_.,;:'()/ ]{0,300}"):
    """Free text. `pat` is the FULL-match charset it is held to.

    A clause written here ends up inside a diffusion prompt, not inside a
    shell -- but it also ends up inside a JSON sidecar, a caption file and a
    manifest, so it is bounded to printable prompt punctuation rather than
    escaped downstream and hoped for."""
    return {'k': k, 'lb': lb, 't': 's', 'df': df, 'tip': tip, 'pat': pat}


# ── the registry ────────────────────────────────────────────────────────────
# An op is one icon in a bar, one card in the stack, and one of three things
# when it compiles:
#
#   cls 'edit'  fn(p, x) -> a clause of the Qwen-Image-Edit instruction.
#               Generative. Cannot be previewed without rendering, and the page
#               says so rather than showing you a picture that omits it.
#   cls 'pix'   pfn(im, p) -> a Pillow image. Deterministic, previewed live,
#               and what you see IS what bakes.
#   cls 'act'   a dock button (or a Measure button): no stack row, an action.
#
# `bar` says which of the two bars the icon lives on and NOTHING APPEARS ON
# BOTH. Side = the creature: what it is made of, how it is lit, how it is
# framed. Dock = the session: the stack, the source, the render settings, the
# view, what you do with the result.
#
# `needs` is honesty about reach: 'comfy' greys the op out when ComfyUI is not
# up, 'lora' when the creature has no trained weights, 'plan' when it has no
# body-plan lock. Greyed and told why beats offered and silently dropped.
OPS = []
_SEEN = set()


def _op(id_, lb, sec, bar, tip, svg, params=(), cls='edit', fn=None, pfn=None, needs='', tog=False, neg=''):
    if id_ in _SEEN:
        raise RuntimeError(f'duplicate op id {id_}')
    _SEEN.add(id_)
    OPS.append(
        {
            'id': id_,
            'lb': lb,
            'sec': sec,
            'bar': bar,
            'tip': tip,
            'svg': svg,
            'params': list(params),
            'cls': cls,
            'fn': fn,
            'pfn': pfn,
            'needs': needs,
            'tog': bool(tog),
            'neg': neg,
            'act': cls == 'act',
        }
    )
    return OPS[-1]


def _edit(id_, lb, sec, tip, svg, params=(), fn=None, needs='comfy', neg=''):
    """A generative op: it contributes a clause to the edit instruction."""
    return _op(id_, lb, sec, 'side', tip, svg, params, cls='edit', fn=fn, needs=needs, neg=neg)


def _pix(id_, lb, sec, tip, svg, params=(), pfn=None):
    """A deterministic op: Pillow, instant, previewed live."""
    return _op(id_, lb, sec, 'side', tip, svg, params, cls='pix', pfn=pfn)


def _act(id_, lb, sec, tip, svg, bar='dock', tog=False, needs=''):
    return _op(id_, lb, sec, bar, tip, svg, cls='act', tog=tog, needs=needs)


# ── clause helpers ──────────────────────────────────────────────────────────
def _amt(v, words=('slightly', 'noticeably', 'much', 'dramatically')):
    """Turn a -100..100 or 0..100 strength into a word.

    Diffusion text encoders do not read "0.63". They read "slightly" and
    "dramatically", and the difference between those two IS the knob -- so the
    slider is quantised to language here rather than pasted in as a number
    that the model averages away."""
    a = abs(float(v))
    if a < 12:
        return ''
    if a < 34:
        return words[0]
    if a < 62:
        return words[1]
    if a < 85:
        return words[2]
    return words[3]


def _pick(p, k='v'):
    return str(p.get(k) or '').strip()
