# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""texture_score.py — did TRELLIS.2's texturing move the Pufferball toward its anchors?

    /usr/bin/python3.12 prop_mesh/texture_score.py \
        --textured $ZYG_HOME/TRELLIS.2/ztest/texturing/pufferball_textured.glb \
        --solid    $ZYG_HOME/TRELLIS.2/ztest/texturing/pufferball_solid.glb \
        --out output/texturing

THE CLAIM THIS REFUSES TO LET ANYONE MAKE. "We textured the mesh and it looks like the
creature" is worth nothing on its own: the mesh ALREADY looks like the creature — it was
built to. A DINOv2 score against the anchor measures the pair (shape, texture) and the
shape is doing most of the work, so a number without its nulls cannot separate "the
texture helped" from "the silhouette was always right".

FOUR ARMS, ONE RIG.
  textured   the TRELLIS.2 output, rendered by prop_mesh/sheet_render.py
  solid      the SAME mesh, same renderer, same framing, no texture — the matched null.
             This is the arm that answers the actual question, and it is the one a
             rig-mismatched comparison would have got wrong.
  sphere     pbopt.NULL_DIR — the v1 pre-look-dev render. Right shape and framing, no
             coat. Known-bad.
  bald       pbopt.BALD_NULL_DIR — bald but correctly framed. Known-bad for the coat
             specifically; the sphere cannot serve there (it is uniformly smooth, so
             relative to its own texture it has no bare PATCH).

FRAMING IS A CONFOUND AND IS NAMED, NOT HIDDEN. `textured` and `solid` come off this
session's generic rig (whole-bbox fill 0.74). The sphere and bald nulls were rendered
months earlier by the Pufferball's own sheet at the canon framing (fill 0.66, body
bbox). DINOv2 is sensitive to scale-in-frame, so those two columns are NOT directly
comparable with the first two — they are here as the standing known-bad reference the
rest of this project scores against, and the textured-vs-solid contrast is the one that
holds everything but the texture constant.
"""

import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)

BLENDER = os.environ.get('ZYG_BLENDER', '/usr/local/bin/blender')
VIEWS = ('front_full', 'side_left')


def render(glb, out, label, drop_nodes='', samples=48, res=1024, log=print):
    cmd = [
        BLENDER,
        '-b',
        '--factory-startup',
        '-P',
        os.path.join(_HERE, 'sheet_render.py'),
        '--',
        '--glb',
        glb,
        '--out',
        out,
        '--name',
        label,
        '--samples',
        str(samples),
        '--res',
        str(res),
        '--no-passes',
        '--views',
        ','.join(VIEWS),
    ]
    if drop_nodes:
        cmd += ['--drop-nodes', drop_nodes]
    p = subprocess.run(cmd, capture_output=True, text=True)
    txt = (p.stdout or '') + (p.stderr or '')
    for l in txt.splitlines():
        if l.startswith('SR_'):
            log('  ' + l)
    if p.returncode != 0:
        log(txt[-1500:])
        raise SystemExit('render failed for %s (rc=%d)' % (label, p.returncode))
    return {v: os.path.join(out, 'beauty', v + '.png') for v in VIEWS}


def montage(rows, path, cell=420):
    """One PNG: anchors on the top row, every arm below, columns are the two views.

    'Look at it' is a required step of this measurement, not a nicety — the numbers
    below cannot tell a plausible texture from a smeared one, and the operator has to
    be able to do in two seconds what no metric here does at all."""
    from PIL import Image, ImageDraw

    labels = [r[0] for r in rows]
    w = cell * len(VIEWS) + 130
    h = cell * len(rows) + 30
    im = Image.new('RGB', (w, h), (16, 18, 22))
    dr = ImageDraw.Draw(im)
    for c, v in enumerate(VIEWS):
        dr.text((130 + c * cell + 6, 8), v, fill=(190, 220, 230))
    for r, (lb, paths) in enumerate(rows):
        y = 30 + r * cell
        dr.text((8, y + cell // 2), lb, fill=(230, 230, 210))
        for c, v in enumerate(VIEWS):
            p = paths.get(v)
            if not p or not os.path.isfile(p):
                continue
            t = Image.open(p).convert('RGB')
            t.thumbnail((cell - 8, cell - 8))
            im.paste(t, (130 + c * cell + 4, y + 4))
    im.save(path)
    del labels
    return path


if __name__ == '__main__':  # the CLI lives in texture_score_cli
    from zyg_workflows.prop_mesh.texture_score_cli import main as _cli_main

    raise SystemExit(_cli_main())
