# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / MEASURE — the measure buttons: a number AND what the number is compared against.

Moved verbatim out of the old single-file creature_fx.py (lines 3802-3898).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _act


# ══ SIDE · MEASURE ══════════════════════════════════════════════════════════
# Not effects: questions. They sit in the side column because they act on the
# creature like everything else there, and every one of them answers with a
# NUMBER and what that number is compared against. A measurement without its
# null is a claim ([[feedback_measure_before_claim]]).

_act(
    'ms_identity',
    'Identity',
    'Measure',
    "Identity — DINOv2 CLS cosine between the picture in the pane and the creature's own "
    'anchor, with the band floor the sheet QC uses printed beside it. This is the number '
    'that says whether an edit is still your creature.',
    '<circle cx="12" cy="9.4" r="4"/><path d="M4.6 20.4c0-4 3.4-7 7.4-7s7.4 3 7.4 7"/>'
    '<path d="M17.6 6.4l1.6 1.6 3-3"/>',
    bar='side',
)

_act(
    'ms_change',
    'Change',
    'Measure',
    'Change — how far the picture has actually moved from its source, structurally. A '
    'generative edit that changed NOTHING is the failure this catches: it looks exactly '
    'like a success and it costs the same four minutes.',
    '<path d="M4.4 12h6.2M13.4 12h6.2"/><path d="M8 8.4L4.4 12 8 15.6"/><path d="M16 8.4L19.6 12 16 15.6"/>',
    bar='side',
)

_act(
    'ms_judge',
    'Judge',
    'Measure',
    'Judge — run the creature VLM checklist on the picture: same creature, one subject, no '
    'human, anatomy intact, viewpoint matches. The same judge, the same questions and the '
    'same tier the sheet pipeline uses.',
    '<path d="M12 3.6v16.8"/><path d="M6.4 7.4h11.2"/><path d="M6.4 7.4L4 13.4h4.8z"/>'
    '<path d="M17.6 7.4L15.2 13.4H20z"/><path d="M8.6 20.4h6.8"/>',
    bar='side',
)

_act(
    'ms_plan',
    'Body plan',
    'Measure',
    "Body plan — the creature's locked anatomy sentence, and whether the picture agrees "
    'with it. The lock exists because a front anchor hides the tail and every rotation '
    'then invents one ([[project_creature_body_plan_lock]]).',
    '<rect x="3.6" y="4.4" width="16.8" height="15.2" rx="1.8"/><path d="M7 9h10M7 12.4h10M7 15.8h6"/>',
    bar='side',
)

_act(
    'ms_facts',
    'Facts',
    'Measure',
    'Facts — resolution, bit depth, how much of the frame is actually opaque, and whether '
    'the alpha carries a real matte or is solid. The questions a card cannot answer by '
    'looking.',
    '<circle cx="12" cy="12" r="8.6"/><path d="M12 11v5.4"/>'
    '<circle cx="12" cy="7.8" r="1.1" fill="currentColor" stroke="none"/>',
    bar='side',
)

_act(
    'ms_palette',
    'Palette',
    'Measure',
    'Palette — the colours actually in the picture, by area. Useful against a brief: a '
    'creature described as turquoise whose dominant colour is grey is a finding, not a '
    'preference.',
    '<circle cx="8" cy="9" r="3.4"/><circle cx="15.4" cy="9" r="3.4"/><circle cx="11.6" cy="15.4" r="3.4"/>',
    bar='side',
)

_act(
    'ms_licence',
    'Licence',
    'Measure',
    "Licence — what the creature's base model was, whether its output may be sold, and "
    'what any edit made here would inherit. The channel is monetised, so this is a gate, '
    'not a footnote.',
    '<path d="M12 3.4l7 3v5.2c0 4.4-3 7.8-7 9-4-1.2-7-4.6-7-9V6.4z"/><path d="M9 12l2.2 2.2 4-4.4"/>',
    bar='side',
)

_act(
    'ms_history',
    'History',
    'Measure',
    'History — every studio bake this creature already has, with the stack that made each '
    'one and what it measured. A recipe you cannot find again is a recipe you do not have.',
    '<path d="M12 7.4v5l3.4 2"/><path d="M20.4 12a8.4 8.4 0 11-3.4-6.7"/><path d="M20.6 3.6v4.4h-4.4"/>',
    bar='side',
)
