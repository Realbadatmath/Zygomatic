# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""music_studio.py — the Music Studio tab's option surface.

Music Studio (:8899, between Voice Studio and Sfx Studio) is the Sfx Studio
cloned onto the INSTRUMENTS library: the same three-level library tree, the
same lane board, the same server-rendered stems — fed the 66,028 sampled
musical one-shots (`instruments`) and the music cues (`soundtracks`) instead
of the ambience beds and one-shot foley.

WHAT THIS FILE IS.  The Sfx Studio's toolbox is built FROM the server's effect
list (`sfx_fx.py` via `/inspect/api/merge/spec`), so a block added there
appears in the bars with no second list to keep in step.  That covers what can
be DONE to a sound.  It says nothing about what a MUSIC studio needs — key,
tempo, articulation, voicing, groove, notation — so this module is the second
half of that roster: the music-shaped option surface, one entry per option,
each with its own inline SVG.

── THE HONESTY MARKING (the load-bearing part) ───────────────────────────────
Most of what is listed here is NOT BUILT.  Shipping a complete *list* of a
domain's options is worth far more than shipping five working ones — but only
if the unbuilt ones cannot be mistaken for broken ones.  So every tool carries
``live``:

    live=True   the tool acts.  It is wired to a real function in the page.
    live=False  a PLACEHOLDER.  The page draws it dashed, with an amber pip,
                writes "[placeholder]" into its tooltip, and clicking it opens
                a sheet that says the knob is not built.  Three independent
                tells, because a tool that looks live and does nothing gets
                read as a broken feature rather than as unbuilt work.

Nothing here silently no-ops.  See project_studio_option_bars.

── THE THREE BARS ────────────────────────────────────────────────────────────
The cut is by QUESTION, never by count (the ruling Creature Studio and Video
Studio settled):

    place='left'   what the SOUND IS       — instrument, articulation,
                                             dynamic, register, the sampler
                                             and the synthesiser behind it
    place='dock'   what is DONE to it      — arrange, time, compose, mix,
                                             master, notate
    place='side'   the SESSION             — transport, layer, chain,
                                             measurement, files, view

The live EFFECT families (Level / Tone / Time / Space / Modulation / Repair /
Utility / Plugins) are NOT listed here.  They come from the merger spec at
render time and land in the dock beside these sections — one roster, one
owner, and no chance of listing `reverb` twice with two different pictures.

Icons live HERE, next to the name, rather than in a table in the page: two
lists in two files is exactly the drift this module exists to avoid.  Every
one is stroke-only on a 24x24 grid so a single CSS rule colours all of them,
and no icon is a character — a glyph can fall back to another font, cannot
take the accent colour on hover, and (measured on the Architecture rail) a
fifth of an emoji toolbar rendered as the same missing-glyph box.
"""

# ruff: noqa: F401  (this package is a facade: every import below is a re-export)

# The section modules, imported in the EXACT original section order so the
# module-level _sec() calls append to SECTIONS in the same order as before.
from . import _defs
from . import left_instrument
from . import left_sound
from . import dock_arrange
from . import dock_mix
from . import side_session
from . import registry

# Every name the single-file module defined, public and underscore.
from ._defs import SECTIONS, _sec, _t
from .registry import (
    CATEGORIES,
    DEFAULT_CATEGORY,
    _selfcheck,
    spec,
)
