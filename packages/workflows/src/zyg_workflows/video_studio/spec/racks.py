# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RACKS — the declarative parameter surface, reassembled in its original order.

The seven racks_* modules each hold one verbatim stretch of the old spec.py
list literal; this module splices them back together, so `RACKS` is the same
list of rack dicts in the same order it always was.
"""

from .racks_bar_delivery import _RACKS_BAR_DELIVERY
from .racks_bar_ffmpeg import _RACKS_BAR_FFMPEG
from .racks_bar_qc_engine import _RACKS_BAR_QC_ENGINE
from .racks_left_engine import _RACKS_LEFT_ENGINE
from .racks_left_guidance import _RACKS_LEFT_GUIDANCE
from .racks_rail_look import _RACKS_RAIL_LOOK
from .racks_rail_shot import _RACKS_RAIL_SHOT

# ─────────────────────────────────────────────────────────── parameter spec
# place: 'rail' → right-hand icon rail, FIVE columns (what the shot looks like,
#                 plus SAMPLER since 2026-09-06)
#        'left' → left-hand icon rail, FIVE columns (how the model computes it)
#        'bar'  → bottom icon bar, FOUR rows (what happens after frames exist,
#                 plus EXPERIMENTAL and ENGINE at its right-hand end)
#
# 2026-09-03 — a THIRD strip. 207 options in a three-row dock is ~70 columns of
# icons, four screen-widths of sideways scroll, so the group at the far end read
# as absent. The render engine (source → engine → memory → sampler → accelerate
# → guidance → experimental → long clip → decode, in pipeline order top to
# bottom) moved to its own rail on the LEFT, leaving the dock the ffmpeg
# finishing chain it shares an axis with. The three strips are three questions:
# right = what the shot shows, left = how it is computed, bottom = what is done
# to the frames afterwards. `place` is the screen edge here (unlike creature_fx,
# where `bar` names a family and the page maps it) — so a new rack picks its
# strip in this file and needs no GUI edit.
#
# 2026-09-03 — the full surface. The rail keeps the creative half and the bar
# now carries every advanced lever the installed stack actually has:
# WanVideoWrapper's optional sampler inputs (cache_args / slg_args / feta_args /
# experimental_args / context_options / loop_args / freeinit_args / NAG), the
# loader's block-swap, torch.compile and VRAM-management args, the decode
# tiling, and a much longer ffmpeg finishing chain (grade, geometry, output,
# QC probes). Everything below reaches a real node input or a real ffmpeg
# filter EXCEPT the params carrying 'todo': True — those are the options this
# console should have and does not yet, marked so they cannot be mistaken for
# broken ones (dashed cell + amber pip + "[not built]" in the hover card).
RACKS = [
    *_RACKS_RAIL_SHOT,
    *_RACKS_RAIL_LOOK,
    *_RACKS_LEFT_ENGINE,
    *_RACKS_LEFT_GUIDANCE,
    *_RACKS_BAR_FFMPEG,
    *_RACKS_BAR_DELIVERY,
    *_RACKS_BAR_QC_ENGINE,
]
