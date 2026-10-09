# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Registry entries: the DOCK bars, and the id index over the finished registry."""

from __future__ import annotations

from zyg_workflows.picture_fx.registry import OPS, _act

# ══ DOCK · STACK ════════════════════════════════════════════════════════════
# The session half. These are ACTIONS: no stack row, no parameters, and the
# page owns what each one does.

_act(
    'sk_open',
    'Stack',
    'Stack',
    "Open the stack — what is in it, in what order, and the selected op's knobs. Order "
    'is load-bearing: a deterministic op ABOVE the first generative one changes the '
    'image the model is handed, one below it changes the result.',
    '<path d="M12 3.4l8.6 4.4L12 12.2 3.4 7.8z"/><path d="M3.4 12L12 16.4 20.6 12"/>'
    '<path d="M3.4 16.2L12 20.6l8.6-4.4"/>',
)
_act(
    'sk_up',
    'Move up',
    'Stack',
    'Move the selected op one place earlier in the stack.',
    '<path d="M12 20.6V4.6"/><path d="M6 10.6L12 4.6l6 6"/>',
)
_act(
    'sk_down',
    'Move down',
    'Stack',
    'Move the selected op one place later.',
    '<path d="M12 3.4v16"/><path d="M6 13.4l6 6 6-6"/>',
)
_act(
    'sk_dup',
    'Duplicate',
    'Stack',
    'Copy the selected op, with its knobs, directly after it. Two of the same op at '
    'different strengths is a real technique, not a mistake.',
    '<rect x="3.4" y="3.4" width="12" height="12" rx="1.6"/><path d="M8.6 20.6h10a2 2 0 002-2v-10"/>',
)
_act(
    'sk_bypass',
    'Bypass',
    'Stack',
    'Switch the selected op off without removing it. The A/B for one op rather than for the whole stack.',
    '<path d="M12 4.6v6.8"/><path d="M7 7.4a7 7 0 1010 0"/>',
    tog=True,
)
_act(
    'sk_solo',
    'Solo',
    'Stack',
    'Show ONLY the selected op. The fastest way to find which op in a stack of nine is the one doing the damage.',
    '<circle cx="12" cy="12" r="3.4"/><circle cx="12" cy="12" r="8.4" stroke-dasharray="2 2.6"/>',
    tog=True,
)
_act(
    'sk_del',
    'Remove',
    'Stack',
    'Remove the selected op from the stack.',
    '<path d="M4.6 6.6h14.8"/><path d="M9.4 6.6V4.4h5.2v2.2"/><path d="M6.6 6.6l1 13.2h8.8l1-13.2"/>',
)
_act('sk_clear', 'Clear', 'Stack', 'Empty the stack. Undoable.', '<path d="M3.4 3.4l17.2 17.2M20.6 3.4L3.4 20.6"/>')
_act(
    'sk_undo',
    'Undo',
    'Stack',
    'Undo the last change to the stack — up to 80 steps.',
    '<path d="M3.6 8.6h11a6 6 0 010 12h-6"/><path d="M7.4 4.6L3.4 8.6l4 4"/>',
)
_act(
    'sk_redo',
    'Redo',
    'Stack',
    'Redo what was just undone.',
    '<path d="M20.4 8.6h-11a6 6 0 100 12h6"/><path d="M16.6 4.6l4 4-4 4"/>',
)


# ══ DOCK · SOURCE ═══════════════════════════════════════════════════════════

_act(
    'sr_inject',
    'Inject subject',
    'Source',
    'Pick a subject from the CHARACTER library or the CREATURE library and load one of '
    'its pictures onto the stage. Always reachable, whether or not something is already '
    'loaded.',
    '<circle cx="12" cy="8.4" r="4"/><path d="M5 20.6c0-3.9 3.1-7 7-7"/><path d="M17.4 13.6v7.2M13.8 17.2h7.2"/>',
)
_act(
    'sr_pick',
    'Pick image',
    'Source',
    "Choose which of this subject's pictures the stack runs on, from every category it "
    "owns — including this studio's own earlier bakes, so an edit can be built on an edit.",
    '<rect x="3" y="4.6" width="18" height="14.8" rx="2"/>'
    '<path d="M3 15.4l5-4.6 3.4 3 3-2.4 6.6 5.6"/><circle cx="8.4" cy="9.4" r="1.6"/>',
)
_act(
    'sr_info',
    'Source info',
    'Source',
    'What this picture is: category, pixel size, bytes, when it was written, and the '
    'licence the subject inherits — which decides whether a generative render is allowed '
    'at all.',
    '<circle cx="12" cy="12" r="8.6"/><path d="M12 11v5.4"/><path d="M12 7.8h.01"/>',
)
_act(
    'sr_reload',
    'Reload',
    'Source',
    'Re-read this subject from disk. What the pipeline wrote while the studio was open does not appear on its own.',
    '<path d="M20.4 12a8.4 8.4 0 11-2.4-5.9"/><path d="M20.6 3.6v4.6H16"/>',
)


# ══ DOCK · RENDER ═══════════════════════════════════════════════════════════

_act(
    'rn_go',
    'Render',
    'Render',
    'Bake the stack. Deterministic ops run instantly; a generative op runs the whole '
    'stack through Qwen-Image-Edit at full size and takes minutes. The result lands in '
    "the subject's picture_studio folder and NEVER over the source.",
    '<path d="M7.4 4.6l12 7.4-12 7.4z"/>',
    needs='comfy',
)
_act(
    'rn_opts',
    'Render settings',
    'Render',
    'Seed, best-of-N, steps, guidance and output size. Best-of-N is not "keep the last '
    'one": every candidate is scored for how far it moved from the source, and one that '
    'came back IDENTICAL is ranked last however good it looks.',
    '<circle cx="12" cy="12" r="3.4"/>'
    '<path d="M12 2.6v3M12 18.4v3M2.6 12h3M18.4 12h3M5.4 5.4l2.2 2.2M16.4 16.4l2.2 2.2'
    'M18.6 5.4l-2.2 2.2M7.6 16.4l-2.2 2.2"/>',
)
_act(
    'rn_chain',
    'Receipt',
    'Render',
    'The exact instruction and negative that a render would send, printed BEFORE it is '
    'sent. A prompt you have not read is a prompt you cannot debug '
    '([[project_llm_audit]]).',
    '<path d="M6 3.4h12v17.2l-3-2-3 2-3-2-3 2z"/><path d="M9 8.4h6M9 12h6"/>',
)
_act(
    'rn_jobs',
    'Renders',
    'Render',
    'Every render this session started, with its log and its measurements.',
    '<rect x="3.4" y="4.6" width="17.2" height="14.8" rx="2"/><path d="M3.4 9.4h17.2"/><path d="M7 13.4h4M7 16.4h8"/>',
)


# ══ DOCK · VIEW ═════════════════════════════════════════════════════════════
# Nothing here changes a pixel of the output. They change what you are looking
# at, which is a different question and kept in a different bar.

_act(
    'vw_fit',
    'Fit',
    'View',
    'Fit the whole picture in the stage.',
    '<path d="M3.4 8.6V3.4h5.2M20.6 8.6V3.4h-5.2M3.4 15.4v5.2h5.2M20.6 15.4v5.2h-5.2"/>',
    tog=True,
)
_act(
    'vw_1to1',
    '1:1',
    'View',
    'One image pixel to one screen pixel. The only zoom at which a sharpen or a denoise can honestly be judged.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="2"/><path d="M8.6 8.6h6.8v6.8H8.6z"/>',
    tog=True,
)
_act(
    'vw_zoomin',
    'Zoom in',
    'View',
    'Zoom in a step.',
    '<circle cx="11" cy="11" r="6.4"/><path d="M15.8 15.8l4.8 4.8"/><path d="M11 8.4v5.2M8.4 11h5.2"/>',
)
_act(
    'vw_zoomout',
    'Zoom out',
    'View',
    'Zoom out a step.',
    '<circle cx="11" cy="11" r="6.4"/><path d="M15.8 15.8l4.8 4.8"/><path d="M8.4 11h5.2"/>',
)
_act(
    'vw_ab',
    'A / B',
    'View',
    'Split the stage: the untouched source on the left, the stack on the right. The only '
    'honest way to answer "did that actually do anything".',
    '<rect x="3.4" y="4.6" width="17.2" height="14.8" rx="1.6"/><path d="M12 4.6v14.8"/>'
    '<path d="M3.4 4.6h8.6v14.8H3.4z" fill="currentColor" stroke="none" opacity=".28"/>',
    tog=True,
)
_act(
    'vw_alpha',
    'Matte',
    'View',
    'Show the alpha channel alone. A matte you have not looked at is a matte you are guessing about.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="2"/><path d="M3.4 12h8.6V3.4M12 12h8.6v8.6"/>',
    tog=True,
)
_act(
    'vw_checker',
    'Checker',
    'View',
    'Put a checkerboard behind the picture so transparency is visible as transparency '
    'rather than as whatever colour the page happens to be.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.6"/>'
    '<path d="M3.4 3.4h8.6v8.6H3.4zM12 12h8.6v8.6H12z" fill="currentColor" stroke="none" opacity=".3"/>',
    tog=True,
)
_act(
    'vw_bg',
    'Ground',
    'View',
    'Cycle the ground behind the picture — checker, black, white, mid grey, chroma green. '
    'An edge that looks clean on black and fringes on white has a matte problem.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none"/>',
)
_act(
    'vw_grid',
    'Grid',
    'View',
    'Thirds overlay. The composition check, and the only way to see that a reframe moved '
    'the subject off the line it was on.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.6"/>'
    '<path d="M9.1 3.4v17.2M14.9 3.4v17.2M3.4 9.1h17.2M3.4 14.9h17.2"/>',
    tog=True,
)


# ══ DOCK · OUTPUT ═══════════════════════════════════════════════════════════
# Everything here writes, and nothing here writes over a pipeline image.

_act(
    'ou_save',
    'Save bake',
    'Output',
    "Run the stack and keep the result as a new picture in the subject's picture_studio "
    'folder, with a JSON sidecar carrying the whole recipe. A bake you cannot reproduce '
    'is a bake you do not have.',
    '<path d="M4.6 4.6h11l4 4v10.8a1 1 0 01-1 1H4.6a1 1 0 01-1-1V5.6a1 1 0 011-1z"/>'
    '<path d="M8 4.6v5h6v-5M8 20.4v-6h8v6"/>',
)
_act(
    'ou_bakes',
    'Studio edits',
    'Output',
    'Every edit this studio has baked for this subject, newest first — each one loadable '
    'back onto the stage as a new source.',
    '<rect x="3.4" y="3.4" width="7.2" height="7.2" rx="1"/><rect x="13.4" y="3.4" width="7.2" height="7.2" rx="1"/>'
    '<rect x="3.4" y="13.4" width="7.2" height="7.2" rx="1"/><rect x="13.4" y="13.4" width="7.2" height="7.2" rx="1"/>',
)
_act(
    'ou_png',
    'Download PNG',
    'Output',
    'Save what is on the stage — the deterministic half of the stack, at full source '
    'resolution — straight to your machine, without baking it into the library.',
    '<path d="M12 3.4v11.2"/><path d="M7.6 10.2L12 14.6l4.4-4.4"/><path d="M4.6 19.4h14.8"/>',
)
_act(
    'ou_recipe',
    'Recipe',
    'Output',
    'The sidecar of the selected bake: its source, its stack, its instruction, its seed and its measurements.',
    '<path d="M5.4 3.4h13.2v17.2H5.4z"/><path d="M8.4 8h7.2M8.4 11.4h7.2M8.4 14.8h4.4"/>',
)
_act(
    'ou_preset',
    'Save preset',
    'Output',
    'Keep this stack by name so it can be dropped onto another picture. A preset is the '
    'stack, not the source — it carries no subject with it.',
    '<path d="M6.6 3.4h10.8v17.2L12 16.6l-5.4 4z"/>',
)
_act(
    'ou_presets',
    'Presets',
    'Output',
    'Load or delete a saved stack.',
    '<path d="M4.6 6.6h14.8M4.6 12h14.8M4.6 17.4h14.8"/><circle cx="8.4" cy="6.6" r="1.6"/>'
    '<circle cx="15.6" cy="17.4" r="1.6"/>',
)
_act(
    'ou_del',
    'Delete bake',
    'Output',
    "Delete a studio edit and its sidecar. It can only reach this studio's own bakes — a "
    'cell, a tile, a final or a creature preview is not addressable from here at all.',
    '<path d="M4.6 6.6h14.8"/><path d="M9.4 6.6V4.4h5.2v2.2"/>'
    '<path d="M6.6 6.6l1 13.2h8.8l1-13.2"/><path d="M10 10.4v6M14 10.4v6"/>',
)
_act(
    'ou_paths',
    'Paths',
    'Output',
    'Where this subject and its bakes actually live on disk.',
    '<path d="M3.4 7.4a2 2 0 012-2h4l2 2.4h7.2a2 2 0 012 2v8.8a2 2 0 01-2 2H5.4a2 2 0 01-2-2z"/>',
)

OP_BY_ID = {o['id']: o for o in OPS}
