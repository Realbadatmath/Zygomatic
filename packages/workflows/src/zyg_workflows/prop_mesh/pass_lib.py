# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pass_lib.py — Blender-side render-pass emitter for the geometry gate (2026-08-04).

Imported by other `blender -b -P` scripts; never by the pipeline (it needs bpy).

WHY PASSES AND NOT JUST THE BEAUTY RENDER.
The gate has to answer questions the finished pixel cannot: *how far is this surface from
the camera*, *which way does it face*, and *which object is this pixel*. Blender already
knows all three exactly. Every one of them has been ESTIMATED elsewhere in this pipeline
by a model — depth by Depth-Anything, object identity by a VLM — and estimation is where
the errors come from. A rendered scene hands them over as ground truth for free.

INDEX-OB, NOT CRYPTOMATTE.
Cryptomatte exists so you can pull a matte for an object you did NOT author. We author
every object in this scene, so we can stamp `object.pass_index` ourselves and read an
integer straight out of the pass. That is exact, needs no ranking/coverage unpacking, and
cannot silently return a partial matte. Cryptomatte is the right tool when you inherit a
scene; IndexOB is the right tool when you built it.

DEPTH UNITS.
Blender's Z pass is camera-space depth in metres, and background pixels come back at ~1e10
rather than 0 — they must be masked before any statistic is taken, or a single unmasked
sky pixel drags every mean to infinity. `passes_io.load_set` does that masking; nothing
downstream should read the raw EXR.

Every metric the gate computes from these is a PAIRED difference between two renders that
differ in exactly one thing, so any monotonic depth convention gives the same verdict.
"""

import os
import glob

import bpy


# pass_index values are the gate's object vocabulary. Stamped here so the Blender script
# and the pure-python gate cannot drift apart on what "3" means.
IDX = {
    'trunk': 1,
    'axe_head': 2,
    'axe_haft': 3,
    'scars': 4,
    'ground': 5,
    'foliage': 6,
}


def enable_passes(scene=None):
    """Turn on Z / Normal / IndexOB on every view layer."""
    scene = scene or bpy.context.scene
    for vl in scene.view_layers:
        vl.use_pass_z = True
        vl.use_pass_normal = True
        vl.use_pass_object_index = True
    return scene


def tag(ob, name):
    """Stamp an object with its gate index. Unknown names are a hard error, not a 0."""
    if name not in IDX:
        raise KeyError('pass_lib.IDX has no entry for %r' % name)
    ob.pass_index = IDX[name]
    return ob


def _clear_nodes(tree):
    for n in list(tree.nodes):
        tree.nodes.remove(n)


def rgb_named_socket(tree, socket):
    """Return a socket whose EXR channels will be named R/G/B rather than X/Y/Z.

    NORMAL IS A VECTOR SOCKET, AND THAT MATTERS ON DISK. Wired straight to a File
    Output, Blender names the EXR channels X/Y/Z; cv2 looks for R/G/B and hands back a
    single 2-D plane holding one component, which `passes_io` correctly refuses to treat
    as a normal. Depth and IndexOB are Value sockets and come out as three identical
    R/G/B channels, which is why only vector passes need this. Splitting and recombining
    as colour forces the R/G/B naming, and costs one node.

    Exported because the sheet scripts build their own compositor graphs (they need
    per-VIEW filenames, which render_set's one-dir-per-view layout cannot give them) and
    the first one to do so re-implemented the wiring WITHOUT this step — shipping 16
    unreadable normal EXRs. The knowledge belongs in one function, not in a comment
    every caller is trusted to have read."""
    is_vector = getattr(socket, 'type', '') == 'VECTOR'
    if not is_vector:
        return socket
    sep = tree.nodes.new('CompositorNodeSeparateXYZ')
    comb = tree.nodes.new('CompositorNodeCombineColor')
    comb.mode = 'RGB'
    tree.links.new(socket, sep.inputs[0])
    for i, axis in enumerate('XYZ'):
        tree.links.new(sep.outputs[axis], comb.inputs[i])
    return comb.outputs['Image']


def _wire_outputs(scene, outdir):
    """Compositor: Render Layers -> one 32-bit EXR File Output per pass.

    File Output always appends the frame number, so slots are named `depth_` and land as
    `depth_0001.exr`; `passes_io` globs rather than assuming the suffix.
    """
    scene.use_nodes = True
    tree = scene.node_tree
    _clear_nodes(tree)
    rl = tree.nodes.new('CompositorNodeRLayers')

    out = tree.nodes.new('CompositorNodeOutputFile')
    out.base_path = outdir
    out.format.file_format = 'OPEN_EXR'
    out.format.color_depth = '32'
    out.format.color_mode = 'RGB'
    out.file_slots.clear()

    for slot, socket in (('depth_', 'Depth'), ('normal_', 'Normal'), ('index_', 'IndexOB')):
        if socket not in rl.outputs:
            raise RuntimeError('render layer has no %r output — enable_passes() first' % socket)
        out.file_slots.new(slot)
        tree.links.new(rgb_named_socket(tree, rl.outputs[socket]), out.inputs[slot])
    return out


def render_set(name, outdir, scene=None, samples=32):
    """Render one pass set into `outdir/name/` — rgb.png plus depth/normal/index EXRs.

    Returns the directory. The beauty pass is written by the normal render path (it is the
    only one that needs colour management); the data passes come off the compositor with
    none applied, which is what makes them measurable.
    """
    scene = scene or bpy.context.scene
    d = os.path.join(outdir, name)
    os.makedirs(d, exist_ok=True)

    enable_passes(scene)
    _wire_outputs(scene, d)

    prev_samples = scene.cycles.samples
    scene.cycles.samples = samples
    scene.render.filepath = os.path.join(d, 'rgb')
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    bpy.ops.render.render(write_still=True)
    scene.cycles.samples = prev_samples

    # normalise the frame-numbered names so the gate can address them directly
    for slot in ('depth', 'normal', 'index'):
        hits = sorted(glob.glob(os.path.join(d, slot + '_*.exr')))
        if hits:
            os.replace(hits[-1], os.path.join(d, slot + '.exr'))
    rgb = os.path.join(d, 'rgb.png')
    if not os.path.exists(rgb):
        for cand in sorted(glob.glob(os.path.join(d, 'rgb*.png'))):
            os.replace(cand, rgb)
            break
    return d


def hide(objs, hidden):
    for ob in objs:
        ob.hide_render = bool(hidden)
