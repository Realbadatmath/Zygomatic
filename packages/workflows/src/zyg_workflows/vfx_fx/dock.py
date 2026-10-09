# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The BOTTOM DOCK — the session acts (vfx_fx.py lines 2557-2947)."""

from __future__ import annotations


from zyg_workflows.vfx_fx.registry import (
    OPS,
    _op,
)

# ── THE BOTTOM DOCK ─────────────────────────────────────────────────────────
# Nothing here changes a pixel, so nothing here has an `fn`.  These are the
# SESSION: what the stack does with itself, what you are looking at, what comes
# out at the end.  They live on the second bar for the same reason the
# Architecture Studio's do -- your hand is on the look kit while you work, and
# reaching past 110 icons to press Undo is the wrong shape for a toolbar.
#
# `act` marks them for the page: an act fires once and lights for a moment
# rather than latching, because a permanently lit Undo is a lie about what the
# button is.  `tog` marks the ones that DO hold a state (a view mode, a scope).


def _act(id_, lb, sec, tip, svg, tog=False, kinds='iv'):
    _op(id_, lb, sec, 'dock', tip, svg, kinds=kinds)
    OPS[-1]['act'] = True
    OPS[-1]['tog'] = bool(tog)


# ── stack ──
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
    'Move the selected op one place earlier. Order is the whole argument in a '
    'stack: saturation before a curve and saturation after one are different '
    'pictures, and blurring before a key is not the same as blurring the key.',
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
    'Copy the selected op, with its settings, directly after itself. Two mild '
    'passes of a filter is often a different result from one strong pass.',
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
    'st_bypass',
    'Bypass',
    'Stack',
    'Switch the selected op off without removing it — the stack keeps its place '
    'and its settings. The only honest way to answer "what is this one actually '
    'doing?"',
    '<path d="M12 3.4v8.2"/><path d="M17.6 6.2a7.6 7.6 0 11-11.2 0"/>',
    tog=True,
)
_act(
    'st_solo',
    'Solo',
    'Stack',
    'Show ONLY the selected op — everything else bypassed. The other half of the same question.',
    '<circle cx="12" cy="12" r="3.4"/><circle cx="12" cy="12" r="8.6" stroke-dasharray="2.6 2.6"/>',
    tog=True,
)
_act(
    'st_clear',
    'Clear stack',
    'Stack',
    'Remove every op and go back to the untouched source. Undoable.',
    '<path d="M4.4 4.4l15.2 15.2M19.6 4.4L4.4 19.6"/>',
)
_act(
    'st_copy',
    'Copy stack',
    'Stack',
    'Copy the whole stack, so it can be pasted onto another element. Matching '
    'twelve elements to one plate is one grade built once and pasted eleven '
    'times.',
    '<rect x="8.6" y="3.4" width="12" height="14" rx="1.4"/><path d="M15.4 20.6H4.8a1.4 1.4 0 01-1.4-1.4V7.4"/>',
)
_act(
    'st_paste',
    'Paste stack',
    'Stack',
    'Paste the copied stack onto this element, replacing what is here.',
    '<rect x="6.4" y="5.4" width="11.2" height="15.2" rx="1.4"/>'
    '<path d="M9.4 5.4V4a1.4 1.4 0 011.4-1.4h2.4A1.4 1.4 0 0114.6 4v1.4z"/>'
    '<path d="M9.4 11h5.2M9.4 15h5.2" opacity=".6"/>',
)

# ── presets ──
_act(
    'pr_save',
    'Save preset',
    'Preset',
    'Save this stack as a named preset. A preset is the recipe, not the picture: '
    'it applies to any element, which is what makes it worth keeping.',
    '<path d="M4.4 4.4h11.4l4.2 4.2v11a1.4 1.4 0 01-1.4 1.4H4.4z"/>'
    '<path d="M7.6 4.4v5h7.2v-5"/><rect x="7.6" y="13" width="8.8" height="7.6"/>',
)
_act(
    'pr_load',
    'Presets',
    'Preset',
    'Open the preset library and apply one. The built-ins are the looks this '
    'toolbox was built to reach; yours sit beside them.',
    '<path d="M3.4 7.4a2 2 0 012-2h4l2 2.4h7.2a2 2 0 012 2v8.8a2 2 0 01-2 2H5.4a2 2 0 01-2-2z"/>'
    '<path d="M8 13h8" opacity=".6"/>',
)
_act(
    'pr_del',
    'Delete preset',
    'Preset',
    'Remove one of your own presets. The built-ins cannot be deleted.',
    '<path d="M4.4 4.4h11.4l4.2 4.2v11a1.4 1.4 0 01-1.4 1.4H4.4z"/><path d="M8.6 12.4l6.8 6.8M15.4 12.4l-6.8 6.8"/>',
)

# ── view ──
_act(
    'v_rgb',
    'RGB',
    'View',
    'The normal view — colour, composited over whatever ground is set.',
    '<circle cx="9.4" cy="10" r="4.6"/><circle cx="14.6" cy="10" r="4.6"/><circle cx="12" cy="14.6" r="4.6"/>',
    tog=True,
)
_act(
    'v_alpha',
    'Alpha',
    'View',
    'The matte alone, as a greyscale picture. Half of compositing is invisible '
    'in RGB: a key that looks clean over black is routinely full of holes, and '
    'this is the only view that shows them.',
    '<path d="M12 3.4l7.4 17.2H4.6z" fill="currentColor" stroke="none" opacity=".35"/>'
    '<path d="M12 3.4l7.4 17.2H4.6z"/>',
    tog=True,
)
_act(
    'v_r',
    'Red',
    'View',
    'The red channel alone.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6a8.4 8.4 0 010 16.8" fill="currentColor" stroke="none" opacity=".4"/>'
    '<path d="M9 8.4h3.4a2 2 0 010 4H9zm0 4l3.6 3.6M9 8.4v7.2"/>',
    tog=True,
)
_act(
    'v_g',
    'Green',
    'View',
    'The green channel alone — where most of the luminance '
    'actually is, so it is the channel to judge detail and grain on.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M14.6 9.6a3.2 3.2 0 10.6 3.4h-2.6"/>',
    tog=True,
)
_act(
    'v_b',
    'Blue',
    'View',
    'The blue channel alone — always the noisiest, and the one a key will fall apart in first.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M9.4 8h3.2a1.9 1.9 0 010 3.8H9.4zm0 3.8h3.6a2.1 2.1 0 010 4.2H9.4z"/>',
    tog=True,
)
_act(
    'v_ab',
    'A/B compare',
    'View',
    'Split the preview down the middle: the source on one side, the stack on the '
    'other. The only comparison that does not rely on your memory of what it '
    'looked like a minute ago.',
    '<rect x="3.4" y="4.4" width="17.2" height="15.2" rx="1.4"/><path d="M12 4.4v15.2"/>'
    '<path d="M3.4 4.4h8.6v15.2H3.4z" fill="currentColor" stroke="none" opacity=".22"/>',
    tog=True,
)
_act(
    'v_bg',
    'Ground',
    'View',
    'What the transparent parts are drawn against: checker, black, white, or a '
    'colour. A black ground hides exactly the alpha you opened the element to '
    'look at, which is why checker is the default.',
    '<rect x="3.4" y="3.4" width="8.6" height="8.6" fill="currentColor" stroke="none" opacity=".3"/>'
    '<rect x="12" y="12" width="8.6" height="8.6" fill="currentColor" stroke="none" opacity=".3"/>'
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1"/><path d="M12 3.4v17.2M3.4 12h17.2"/>',
)
_act(
    'v_fit',
    'Fit',
    'View',
    'Fit the whole frame in the preview.',
    '<path d="M4 9.5V4h5.5M20 9.5V4h-5.5M4 14.5V20h5.5M20 14.5V20h-5.5"/>',
)
_act(
    'v_1to1',
    '1:1',
    'View',
    'One image pixel to one screen pixel. Grain, edge fringing and compression '
    'blocks are all invisible at fit — every judgement about detail has to be '
    'made here.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.4"/>'
    '<path d="M8.6 8.6h1.4v6.8M14 8.6h1.4v6.8" stroke-linejoin="round"/>',
)
_act(
    'v_grid',
    'Grid',
    'View',
    'Thirds and centre lines over the preview.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.2"/>'
    '<path d="M9.1 3.4v17.2M14.9 3.4v17.2M3.4 9.1h17.2M3.4 14.9h17.2"/>',
    tog=True,
)
_act(
    'v_safe',
    'Safe areas',
    'View',
    'Action and title safe. Worth a look before an element is placed near an '
    'edge that a delivery spec is going to crop.',
    '<rect x="3.4" y="4.4" width="17.2" height="15.2" rx="1.2"/>'
    '<rect x="6.4" y="7" width="11.2" height="10" stroke-dasharray="2.4 2.2"/>',
    tog=True,
)
_act(
    'v_hist',
    'Histogram',
    'View',
    'How many pixels sit at each level, per channel. The one readout that tells '
    'you whether you have clipped anything — and clipping is invisible on a '
    'monitor until it is a flat white slab in the render.',
    '<path d="M3.6 20.4V12M7.2 20.4V7M10.8 20.4v-9.4M14.4 20.4V4.6M18 20.4v-7M21 20.4v-4"/>',
    tog=True,
)
_act(
    'v_wave',
    'Waveform',
    'View',
    "Luminance against horizontal position — the broadcast engineer's view. "
    'This is where you set a black point, because it shows you WHERE in frame '
    'the darkest thing is, which a histogram cannot.',
    '<rect x="3.4" y="4.4" width="17.2" height="15.2" rx="1.2"/><path d="M5 17c3-1 3-7 6-7s3 5 6 4 1.4-1 2-1.4"/>',
    tog=True,
)
_act(
    'v_vector',
    'Vectorscope',
    'View',
    'Hue as angle, saturation as distance from the centre. The tool for matching '
    "one element's colour to another's: two things that sit on the same spoke "
    'are the same hue no matter how differently they are lit.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 12l6-3.4M12 12l-2 7"/>'
    '<circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/>',
    tog=True,
)
_act(
    'v_scope_rgb',
    'RGB parade',
    'View',
    'The three channels side by side as waveforms. A colour cast is a step '
    'between the parades that no amount of looking at the picture will make '
    'obvious.',
    '<rect x="3" y="6" width="5.2" height="12" rx="1"/><rect x="9.4" y="6" width="5.2" height="12" rx="1"/>'
    '<rect x="15.8" y="6" width="5.2" height="12" rx="1"/>',
    tog=True,
)
_act(
    'v_picker',
    'Pixel probe',
    'View',
    'Click the preview and read the exact RGBA of that pixel, before and after '
    'the stack. The difference between "the black looks fine" and "the black is 6".',
    '<path d="M4 20l1-4.2L16.6 4.2a2.1 2.1 0 013 3L8 18.9 4 20z"/><path d="M14.6 6.2l3 3"/>',
    tog=True,
)

# ── output ──
_act(
    'o_format',
    'Output format',
    'Output',
    'What the bake writes: WebM VP9 with alpha, ProRes 4444 with alpha, h264 '
    'without, or a PNG sequence. h264 has NO alpha channel — picking it for an '
    'element hands back a black box that looks like a successful render.',
    '<rect x="3.4" y="4.4" width="17.2" height="15.2" rx="1.4"/>'
    '<path d="M3.4 9h17.2"/><path d="M7.6 13.4h8.8M7.6 16.6h5.6" opacity=".6"/>',
)
_act(
    'o_res',
    'Output size',
    'Output',
    'Resolution and frame rate of the bake, independent of the Resize op — this '
    'is the container, that is a step in the look.',
    '<rect x="3.4" y="5.4" width="17.2" height="13.2" rx="1.4"/>'
    '<path d="M8.4 5.4v13.2M3.4 12h17.2" opacity=".5"/><path d="M15.6 8.6h2.4v2.4"/>',
)
_act(
    'o_quality',
    'Quality',
    'Output',
    'Bitrate or CRF for the bake. An element that is going to be graded again '
    'downstream wants headroom; one that is going straight into a cut does not.',
    '<path d="M12 3.6l2.6 5.6 6 .8-4.4 4.2 1.1 6.2L12 17.4l-5.3 3-1.1-6.2L1.2 10l6-.8z" '
    'transform="translate(2.4,0) scale(0.86)"/>',
)

# ── file ──
_act(
    'f_render',
    'Render',
    'File',
    'Bake the stack into a NEW library row. The source is never touched: an edit '
    'that overwrote its own master would be one bad stack away from losing an '
    'element nobody can re-download.',
    '<path d="M12 3.4v11.2"/><path d="M7.6 10.2L12 14.6l4.4-4.4"/>'
    '<path d="M4.4 16.6v2.6a1.4 1.4 0 001.4 1.4h12.4a1.4 1.4 0 001.4-1.4v-2.6"/>',
)
_act(
    'f_chain',
    'Show chain',
    'File',
    'Print the exact ffmpeg command this stack compiles to. A receipt, not a '
    'claim — you can read it, copy it, and run it yourself, and if it does not '
    'say what you expected then the stack does not do what you expected.',
    '<path d="M9.4 14.6a4 4 0 010-5.6l2.4-2.4a4 4 0 015.6 5.6l-1 1"/>'
    '<path d="M14.6 9.4a4 4 0 010 5.6l-2.4 2.4a4 4 0 01-5.6-5.6l1-1"/>',
)
_act(
    'f_recipe_save',
    'Save recipe',
    'File',
    'Write the stack out as JSON next to the element. The bake records its '
    'recipe too, so a derived row can always say what was done to it.',
    '<path d="M6.4 3.4h8l4 4v13.2H6.4z"/><path d="M14.4 3.4v4h4" opacity=".6"/>'
    '<path d="M9 12h6M9 15.4h6" opacity=".6"/>',
)
_act(
    'f_recipe_load',
    'Load recipe',
    'File',
    'Read a stack back out of a JSON recipe.',
    '<path d="M6.4 20.6h11.2V7.4l-4-4H6.4z"/><path d="M12 10.6v6M9.2 13.8L12 16.6l2.8-2.8"/>',
)
_act(
    'f_analyze',
    'Send to Analyzer',
    'File',
    'Hand the BAKED result to the frame-by-frame Analyzer. Measuring the source '
    'and shipping the edit is how a QC pass ends up green on a file nobody '
    'looked at.',
    '<circle cx="10.6" cy="10.6" r="6.2"/><path d="M15.2 15.2l5.4 5.4"/>'
    '<path d="M8 10.6h5.2M10.6 8v5.2" opacity=".6"/>',
)
_act(
    'f_revert',
    'Revert',
    'File',
    'Throw the stack away and go back to the untouched source.',
    '<path d="M4.6 5.4v5.2h5.2"/><path d="M4.9 10.6a8 8 0 112 7.4"/>',
)
_act(
    'f_place3d',
    'Place in 3D scene',
    'File',
    'Add this volume element to the current Architecture Studio shot '
    '(data/architecture/shots/current.json) 2 m in front of the camera at a '
    '3 m size; then open the shot in the studio and press Draft. Browsing a '
    'volume pack and seeing it in the city is one click, not a record typed '
    'out by hand.',
    '<path d="M12 3.4l7.6 4.4v8.4L12 20.6 4.4 16.2V7.8z"/>'
    '<path d="M4.4 7.8L12 12.2l7.6-4.4M12 12.2v8.4" opacity=".6"/>',
    kinds='v',
)
