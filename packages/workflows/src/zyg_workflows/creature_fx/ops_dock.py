# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""DOCK — stack, source, render, preset, view, output and pipeline actions, then the registry index.

Moved verbatim out of the old single-file creature_fx.py (lines 3899-4419).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import OPS, _act


# ══ DOCK · STACK ════════════════════════════════════════════════════════════
_act(
    'st_undo',
    'Undo',
    'Stack',
    'Undo the last change to the stack — an added op, a moved one, a knob. Eighty deep.',
    '<path d="M4 9.4h11.6a5 5 0 010 10H8.6"/><path d="M8 5l-4 4.4 4 4.4"/>',
)
_act(
    'st_redo',
    'Redo',
    'Stack',
    'Redo what Undo took back.',
    '<path d="M20 9.4H8.4a5 5 0 000 10H15.4"/><path d="M16 5l4 4.4-4 4.4"/>',
)
_act(
    'st_up',
    'Move up',
    'Stack',
    'Move the selected op one place earlier. Order decides everything here: a pixel op '
    'above the generative edit crops the SOURCE, the same op below it crops the RESULT.',
    '<path d="M12 20V5"/><path d="M6.6 10.4L12 5l5.4 5.4"/>',
)
_act(
    'st_down',
    'Move down',
    'Stack',
    'Move the selected op one place later.',
    '<path d="M12 4v15"/><path d="M6.6 13.6L12 19l5.4-5.4"/>',
)
_act(
    'st_dupe',
    'Duplicate',
    'Stack',
    'Copy the selected op, with its settings, directly after itself.',
    '<rect x="3.4" y="3.4" width="12" height="12" rx="1.4"/><rect x="8.6" y="8.6" width="12" height="12" rx="1.4"/>',
)
_act(
    'st_del',
    'Remove',
    'Stack',
    'Take the selected op out of the stack.',
    '<path d="M4.4 6.6h15.2"/><path d="M9 6.6V4.4h6v2.2"/>'
    '<path d="M6.6 6.6l1 13a1.4 1.4 0 001.4 1.4h6a1.4 1.4 0 001.4-1.4l1-13"/>',
)
_act(
    'st_clear',
    'Clear',
    'Stack',
    'Empty the whole stack. Undo brings it back.',
    '<path d="M5.4 5.4l13.2 13.2M18.6 5.4L5.4 18.6"/>',
)
_act(
    'st_bypass',
    'Bypass',
    'Stack',
    'Switch the selected op off in place, keeping its settings. The only honest way to '
    'answer "what is this one actually doing?".',
    '<path d="M12 3.6v7.8"/><path d="M6.6 6.6a7.4 7.4 0 1010.8 0"/>',
    tog=True,
)
_act(
    'st_solo',
    'Solo',
    'Stack',
    'Show only the selected op. Leaving solo restores exactly what was there — solo '
    'rewrites what is sent, never the stack itself.',
    '<circle cx="12" cy="12" r="3.4"/><path d="M12 3.6v3M12 17.4v3M3.6 12h3M17.4 12h3"/>',
    tog=True,
)
_act(
    'st_copy',
    'Copy stack',
    'Stack',
    'Copy the whole stack, to paste onto another creature. Stacks are creature-agnostic: '
    'the same eight ops describe the same edit whatever they are pointed at.',
    '<rect x="8.6" y="3.4" width="12" height="12" rx="1.4"/>'
    '<path d="M15.4 15.4v3.2a2 2 0 01-2 2H5.4a2 2 0 01-2-2V10.6a2 2 0 012-2h3.2"/>',
)
_act(
    'st_paste',
    'Paste stack',
    'Stack',
    'Replace the stack with the copied one.',
    '<rect x="5.4" y="5.4" width="13.2" height="15.2" rx="1.8"/>'
    '<path d="M9 5.4V4a1.6 1.6 0 011.6-1.6h2.8A1.6 1.6 0 0115 4v1.4z"/>'
    '<path d="M8.6 11h6.8M8.6 14.6h4.8"/>',
)


# ══ DOCK · SOURCE ═══════════════════════════════════════════════════════════
# Which of the creature's own images the stack is pointed at. This is the one
# decision that changes what everything else means, which is why it is the
# first section of the dock and not a dropdown hidden in a dialog.
_act(
    'sr_pick',
    'Pick source',
    'Source',
    "Pick which of the creature's images to work on — previews, sheet cells, anchors, "
    'operator locks, references, validation frames, and earlier studio bakes.',
    '<rect x="3.4" y="5.4" width="17.2" height="13.2" rx="1.8"/>'
    '<path d="M3.4 15l4.6-4.4 3.4 3.2 3-2.6 6.2 5.2"/><circle cx="8.6" cy="9.4" r="1.4"/>',
)
_act(
    'sr_prev',
    'Previous',
    'Source',
    'Step to the previous image in the same category.',
    '<path d="M14.6 5.4L8 12l6.6 6.6"/>',
)
_act('sr_next', 'Next', 'Source', 'Step to the next image in the same category.', '<path d="M9.4 5.4L16 12l-6.6 6.6"/>')
_act(
    'sr_hero',
    'Hero',
    'Source',
    "Jump to the creature's hero image — the one its card is judged by.",
    '<path d="M12 3.6l2.6 5.4 5.8.8-4.2 4.2 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.2-4.2 5.8-.8z"/>',
)
_act(
    'sr_anchor',
    'Anchor',
    'Source',
    'Jump to the identity anchor — the image every sheet cell was edited FROM, and the one identity is scored against.',
    '<path d="M12 7.4v13"/><circle cx="12" cy="5" r="2.4"/>'
    '<path d="M4.6 13.4a7.4 7.4 0 0014.8 0"/><path d="M4.6 13.4h3M16.4 13.4h3"/>',
)
_act(
    'sr_reload',
    'Reload',
    'Source',
    'Re-read the creature from disk. A training run that finished while this tab was open '
    'is exactly when what you are looking at is stale.',
    '<path d="M20.4 12a8.4 8.4 0 11-2.6-6.1"/><path d="M20.6 3.6v4.4h-4.4"/>',
)
_act(
    'sr_info',
    'Source info',
    'Source',
    'What this image IS: which category, what stage of the pipeline made it, when, and '
    'what it proves. A preview is the trained LoRA talking; a sheet cell is what it was '
    'taught; a lock is what the operator fixed by hand.',
    '<rect x="4.4" y="3.6" width="15.2" height="16.8" rx="1.8"/><path d="M8 8.4h8M8 12h8M8 15.6h5"/>',
)


# ══ DOCK · RENDER ═══════════════════════════════════════════════════════════
# The generative half's settings. Every one of these is recorded in the sidecar,
# because a bake you cannot reproduce is a bake you cannot fix.
_act(
    'rn_seed',
    'Seed',
    'Render',
    'Seed — the same seed with the same stack gives the same picture. Changing it is how '
    'you get a second opinion on the same instruction.',
    '<circle cx="12" cy="12" r="8.4"/><circle cx="9" cy="9" r="1.3"/>'
    '<circle cx="15" cy="9" r="1.3"/><circle cx="9" cy="15" r="1.3"/>'
    '<circle cx="15" cy="15" r="1.3"/><circle cx="12" cy="12" r="1.3"/>',
)
_act(
    'rn_dice',
    'Reroll',
    'Render',
    'Pick a new random seed.',
    '<rect x="4.4" y="4.4" width="15.2" height="15.2" rx="3"/>'
    '<circle cx="9" cy="9" r="1.3"/><circle cx="15" cy="15" r="1.3"/>'
    '<circle cx="12" cy="12" r="1.3"/>',
)
_act(
    'rn_best',
    'Best of N',
    'Render',
    'Render N seeds and keep the best by identity score, not by which came back first. The '
    "sheet pipeline's regen ladder works exactly this way, and it is the difference "
    'between a lucky cell and a repeatable one.',
    '<path d="M6.4 20.4V9.4M12 20.4V4.4M17.6 20.4v-7"/><path d="M3.6 20.4h16.8"/>',
)
_act(
    'rn_steps',
    'Steps',
    'Render',
    'Sampler steps. The default is what the creature sheet uses; fewer is faster and measurably softer on fur.',
    '<path d="M3.6 19.4h4.4V15h4.4v-4.6h4.4V6h4"/>',
)
_act(
    'rn_cfg',
    'Guidance',
    'Render',
    'Guidance scale — how hard the model is pushed toward the instruction. Too high and '
    'the identity goes; the sheet pipeline sits at 4.0 for that reason.',
    '<path d="M12 20.4V12"/><circle cx="12" cy="8.4" r="4.4"/><path d="M7.6 20.4h8.8"/>',
)
_act(
    'rn_size',
    'Size',
    'Render',
    'Render size. 1024 is the cell size the whole creature pipeline works at; going '
    'smaller is not a faster preview of the same picture, it is a different picture.',
    '<path d="M3.6 8.4V4.4h4M20.4 8.4V4.4h-4M3.6 15.6v4h4M20.4 15.6v4h-4"/>',
)
_act(
    'rn_str',
    'Edit strength',
    'Render',
    'Edit strength — how far the edit may move from the source image. The multiple-angles '
    'LoRA scale rides with it, because creatures measurably UNDER-rotate at the graph '
    'default.',
    '<path d="M4.4 15.6c4-6 11.2-6 15.2 0"/><path d="M12 15.6V6.4"/><path d="M9.4 9l2.6-2.6L14.6 9"/>',
)
_act(
    'rn_go',
    'Render',
    'Render',
    'Run the stack for real: the pixel ops above the edit, then the Qwen-Image-Edit pass '
    'with the compiled instruction, then the pixel ops below it. This IS the bake — there '
    'is no proxy pass, so what comes back is what lands.',
    '<path d="M8 5.4l11 6.6-11 6.6z"/>',
    needs='comfy',
)
_act(
    'rn_stop',
    'Cancel',
    'Render',
    'Stop the running render.',
    '<rect x="6.4" y="6.4" width="11.2" height="11.2" rx="1.6"/>',
)
_act(
    'rn_chain',
    'Receipt',
    'Render',
    'The receipt: the exact instruction, the exact negative prompt, the graph, the seeds '
    'and every pixel op with its parameters. A receipt, not a claim — you can read it '
    'before you spend four minutes on it.',
    '<path d="M6.4 3.6h11.2v16.8l-2.8-1.8-2.8 1.8-2.8-1.8-2.8 1.8z"/><path d="M9.4 8h5.2M9.4 11.6h5.2M9.4 15.2h3"/>',
)


# ══ DOCK · PRESET ═══════════════════════════════════════════════════════════
_act(
    'pr_save',
    'Save preset',
    'Preset',
    'Save this stack as a named preset, usable on any creature.',
    '<path d="M5.4 4.4h10.2l3 3v12.2H5.4z"/><path d="M8.4 4.4v5h6v-5"/>'
    '<rect x="8" y="12.6" width="8" height="4.8" rx="1"/>',
)
_act(
    'pr_load',
    'Presets',
    'Preset',
    'Load a saved preset over the current stack.',
    '<path d="M3.6 7.4h6l1.8 2.4h9v9.2a1.6 1.6 0 01-1.6 1.6H5.2a1.6 1.6 0 01-1.6-1.6z"/>',
)
_act(
    'pr_del',
    'Delete preset',
    'Preset',
    'Remove a saved preset.',
    '<path d="M4.4 7.4h15.2"/><path d="M9.4 7.4V5.2h5.2v2.2"/>'
    '<path d="M6.6 7.4l1 12.2a1.4 1.4 0 001.4 1.3h6a1.4 1.4 0 001.4-1.3l1-12.2"/>'
    '<path d="M10.4 11v6M13.6 11v6"/>',
)


# ══ DOCK · VIEW ═════════════════════════════════════════════════════════════
# What the pane shows. None of these change a pixel of the result -- they change
# what you are being shown of it, which is a different thing and is why they are
# on the dock rather than in the stack.
_act(
    'v_fit',
    'Fit',
    'View',
    'Fit the whole image in the pane.',
    '<path d="M4.4 9V4.4H9M15 4.4h4.6V9M19.6 15v4.6H15M9 19.6H4.4V15"/>',
    tog=True,
)
_act(
    'v_1to1',
    '1:1',
    'View',
    'Show it at one image pixel per screen pixel. The only zoom at which a sharpen or a denoise can be judged at all.',
    '<rect x="4.4" y="4.4" width="15.2" height="15.2" rx="1.6"/><path d="M9 9h1.4v6M13.4 9h1.4v6"/>',
    tog=True,
)
_act(
    'v_zoomin',
    'Zoom in',
    'View',
    'Closer.',
    '<circle cx="10.6" cy="10.6" r="6.4"/><path d="M15.4 15.4l5.2 5.2"/><path d="M7.8 10.6h5.6M10.6 7.8v5.6"/>',
)
_act(
    'v_zoomout',
    'Zoom out',
    'View',
    'Further back.',
    '<circle cx="10.6" cy="10.6" r="6.4"/><path d="M15.4 15.4l5.2 5.2"/><path d="M7.8 10.6h5.6"/>',
)
_act(
    'v_ab',
    'A / B',
    'View',
    'Split the pane down the middle: source on the left, stack on the right. The only '
    'comparison that survives an argument about whether an edit did anything.',
    '<rect x="3.6" y="4.4" width="16.8" height="15.2" rx="1.6"/>'
    '<path d="M12 4.4v15.2"/><path d="M3.6 4.4h8.4v15.2H3.6z" fill="currentColor" stroke="none" opacity=".25"/>',
    tog=True,
)
_act(
    'v_alpha',
    'Matte',
    'View',
    'Show the alpha channel as a picture. It is the one view that says whether a key '
    'actually cut the background or just made it faint.',
    '<rect x="3.6" y="3.6" width="16.8" height="16.8" rx="1.8"/>'
    '<path d="M3.6 12h8.4V3.6M12 12v8.4h8.4" fill="currentColor" stroke="none" opacity=".3"/>'
    '<path d="M3.6 12h16.8M12 3.6v16.8"/>',
    tog=True,
)
_act(
    'v_checker',
    'Checker',
    'View',
    'Put a checkerboard behind the image, so transparency reads as transparency rather than as a black creature.',
    '<rect x="3.6" y="3.6" width="16.8" height="16.8" rx="1.4"/>'
    '<path d="M3.6 3.6h8.4v8.4H3.6zM12 12h8.4v8.4H12z" fill="currentColor" stroke="none" opacity=".35"/>',
    tog=True,
)
_act(
    'v_bg',
    'Ground',
    'View',
    'Cycle the ground behind the image — checker, black, white, mid grey, green. A white '
    'creature on a white ground is invisible, and that is a real thing to find out.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8"/>'
    '<path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none" opacity=".4"/>',
)
_act(
    'v_grid',
    'Grid',
    'View',
    'Thirds grid over the pane, for framing and margin decisions.',
    '<rect x="3.6" y="3.6" width="16.8" height="16.8" rx="1.4"/>'
    '<path d="M9.2 3.6v16.8M14.8 3.6v16.8M3.6 9.2h16.8M3.6 14.8h16.8"/>',
    tog=True,
)
_act(
    'v_pin',
    'Pin source',
    'View',
    'Keep the untouched source visible in a corner while you work. Cheaper than toggling '
    'A/B when the change is subtle.',
    '<path d="M12 3.6v9.4"/><path d="M8.4 13h7.2l-1.4-3.4V5.4H9.8v4.2z"/><path d="M12 13v7.4"/>',
    tog=True,
)
# Its own op rather than a second meaning for v_pin: a picture and a mesh are
# two different things to be looking at, and the operator should be able to have
# the source pinned WHILE the pane shows the mesh.
_act(
    'v_3d',
    '3D view',
    'View',
    'Show the creature as a 3D mesh (its own GLB when it has one, else the base creature) instead of the picture.',
    '<path d="M12 3.2l7.6 4.4v8.8L12 20.8 4.4 16.4V7.6z"/><path d="M4.4 7.6L12 12l7.6-4.4M12 12v8.8"/>',
    tog=True,
)
# The base is a THIRD-PARTY CC0 stand-in, never one of ours, and which one it is
# is the operator's choice rather than a constant: a coat scheme reads one way on
# a wolf and another on a cube-pet, and that difference is the point of looking.
_act(
    'v_base',
    'Base creature',
    'View',
    'Pick which third-party base creature stands in the preview when no creature is '
    'injected (pinned in this browser; unpin returns to the first of the list).',
    '<path d="M4.2 14.6c0-3.1 2.6-5.6 5.8-5.6h4c3.2 0 5.8 2.5 5.8 5.6"/>'
    '<circle cx="8.2" cy="6.2" r="2.3"/><circle cx="15.8" cy="6.2" r="2.3"/>'
    '<path d="M6.6 20.4v-3.2M17.4 20.4v-3.2"/>',
)


# ══ DOCK · OUTPUT ═══════════════════════════════════════════════════════════
# What happens to the result. Everything here writes; nothing here writes to the
# source. The three promotions -- hero, anchor lock, training tile -- change what
# the NEXT sheet and the NEXT training run are made of, so each is its own
# deliberate act with its own icon rather than a checkbox on a save dialog.
_act(
    'ou_save',
    'Save edit',
    'Output',
    "Write the result into the creature's own studio folder, with a JSON sidecar holding "
    'the whole recipe, the seeds, the measurements and the inherited licence. The source '
    'is never touched.',
    '<path d="M5.4 4.4h10.2l3 3v12.2H5.4z"/><path d="M8.4 4.4v5h6v-5"/><path d="M8.4 19.6v-6h7.2v6"/>',
)
_act(
    'ou_hero',
    'Set as hero',
    'Output',
    "Make this the creature's hero image — the one its card is judged by everywhere in "
    'the app. Writes hero_image into the manifest and nothing else.',
    '<path d="M12 3.6l2.6 5.4 5.8.8-4.2 4.2 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.2-4.2 5.8-.8z"/><path d="M19.4 19.4l2 2"/>',
)
_act(
    'ou_lock',
    'Set anchor lock',
    'Output',
    'Promote this to an operator anchor lock — full-body or side. THE consequential write: '
    'the side lock is the rotation source for every side, back and top cell of the next '
    'sheet, and locking a wrong one propagates into all of them.',
    '<rect x="5.4" y="10.4" width="13.2" height="9.2" rx="1.8"/>'
    '<path d="M8.4 10.4V7.6a3.6 3.6 0 017.2 0v2.8"/><circle cx="12" cy="15" r="1.6"/>',
)
_act(
    'ou_tile',
    'Add training tile',
    'Output',
    "Add this image, with a caption, to the creature's training set. What the NEXT LoRA "
    'run learns from — so a wrong tile here is a wrong creature later.',
    '<rect x="3.6" y="3.6" width="7.4" height="7.4" rx="1.2"/>'
    '<rect x="13" y="3.6" width="7.4" height="7.4" rx="1.2"/>'
    '<rect x="3.6" y="13" width="7.4" height="7.4" rx="1.2"/>'
    '<path d="M16.7 13v7.4M13 16.7h7.4"/>',
)
_act(
    'ou_ref',
    'Add as reference',
    'Output',
    'File it as a reference image for the creature — material for the next sheet build, '
    'without entering the training set.',
    '<path d="M4.4 5.4h15.2v13.2H4.4z"/><path d="M4.4 14.4l4.6-4.2 3.4 3 3-2.4 4.2 3.6"/>'
    '<circle cx="9" cy="8.6" r="1.3"/>',
)
_act(
    'ou_png',
    'Download',
    'Output',
    'Download the rendered image as a PNG, alpha intact.',
    '<path d="M12 3.6v11.2"/><path d="M7.6 10.4L12 14.8l4.4-4.4"/><path d="M4.4 18.6h15.2"/>',
)
_act(
    'ou_recipe',
    'Recipe',
    'Output',
    'The recipe as JSON — the stack, the seeds, the source and the measurements — to copy '
    'out, or to paste back in and reproduce a bake exactly.',
    '<path d="M6.4 3.6h11.2v16.8H6.4z"/><path d="M9.4 8h5.2M9.4 11.4h5.2M9.4 14.8h3.4"/><path d="M17.6 16.6l2.8 2.8"/>',
)
_act(
    'ou_del',
    'Delete edit',
    'Output',
    'Delete a studio bake and its sidecar. Only ever a studio bake: nothing in this dock '
    'can reach a preview, a cell, a lock or a reference.',
    '<path d="M4.4 7h15.2"/><path d="M9.4 7V4.8h5.2V7"/>'
    '<path d="M6.6 7l1 12.2a1.4 1.4 0 001.4 1.3h6a1.4 1.4 0 001.4-1.3l1-12.2"/>',
)


# ══ DOCK · PIPELINE ═════════════════════════════════════════════════════════
# The long-running jobs that own this creature elsewhere. Two of them are
# hand-offs on purpose: rebuilding a sheet is a 25-minute GPU run and retraining
# is hours, and a studio that could start either by mis-click is a studio that
# eats a night's queue. They print the exact command instead.
_act(
    'pl_brief',
    'Brief',
    'Pipeline',
    "The creature's brief and body-plan lock, editable. This is the text every future "
    'edit instruction, caption and judge question is built from, so it is the highest-'
    'leverage thing in the tab.',
    '<path d="M5.4 3.6h9.2l4 4v12.8H5.4z"/><path d="M14.6 3.6v4h4"/><path d="M8.4 12h7.2M8.4 15.4h4.8"/>',
)
_act(
    'pl_judge',
    'Run judge',
    'Pipeline',
    'Run the VLM checklist over the current picture now, and print every question with its '
    'answer. Same judge, same questions as the sheet QC.',
    '<circle cx="10.6" cy="10.6" r="6.4"/><path d="M15.4 15.4l5.2 5.2"/><path d="M8.4 10.6l1.6 1.6 3-3.2"/>',
)
_act(
    'pl_sheet',
    'Rebuild sheet',
    'Pipeline',
    'Rebuild the 16-cell contact sheet from the current anchors and body plan. A ~25 minute '
    'GPU run that owns the whole card, so this hands you the exact command rather than '
    'starting it behind a single click.',
    '<rect x="3.6" y="3.6" width="16.8" height="16.8" rx="1.8"/>'
    '<path d="M3.6 9.2h16.8M3.6 14.8h16.8M9.2 3.6v16.8M14.8 3.6v16.8"/>',
)
_act(
    'pl_train',
    'Retrain LoRA',
    'Pipeline',
    "Retrain the creature's LoRA on its current training tiles. Hours of GPU, and it "
    'replaces the weights every render of this creature uses — so this hands you the exact '
    'command rather than starting it behind a single click.',
    '<path d="M12 4.4a7.6 7.6 0 107.6 7.6"/><path d="M12 8.4a3.6 3.6 0 103.6 3.6"/>'
    '<path d="M16.4 3.6l3.2 1.2-1.2 3.2"/>',
)
_act(
    'pl_jobs',
    'Jobs',
    'Pipeline',
    'Every render this studio has run: what it was, what it measured, and where the file went.',
    '<path d="M4.4 6.4h15.2M4.4 12h15.2M4.4 17.6h15.2"/>'
    '<circle cx="7.4" cy="6.4" r="1.6"/><circle cx="12" cy="12" r="1.6"/>'
    '<circle cx="16.6" cy="17.6" r="1.6"/>',
)
_act(
    'pl_open',
    'Folder',
    'Pipeline',
    "The creature's paths on disk — dataset, weights, studio bakes — as text to copy.",
    '<path d="M3.6 7.4h6l1.8 2.4h9v9.2a1.6 1.6 0 01-1.6 1.6H5.2a1.6 1.6 0 01-1.6-1.6z"/>'
    '<path d="M3.6 7.4V5.8a1.6 1.6 0 011.6-1.6h3.4l1.6 2.2"/>',
)

OP_BY_ID = {o['id']: o for o in OPS}
