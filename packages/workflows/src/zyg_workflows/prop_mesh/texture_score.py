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

import argparse
import json
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


def main():
    import zyg_workflows.prop_mesh.pbopt as PBO
    from zyg_workflows import creature_identity as cid

    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--textured', required=True)
    ap.add_argument('--solid', required=True)
    ap.add_argument('--out', default=os.path.join(_ROOT, 'output', 'texturing'))
    ap.add_argument('--samples', type=int, default=48)
    ap.add_argument('--skip-render', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    anchors = dict(PBO.VIEWS)  # {'front_full': path, 'side_left': path}
    arms = {}
    for label, glb in (('textured', a.textured), ('solid', a.solid)):
        d = os.path.join(a.out, label)
        if a.skip_render and os.path.isdir(os.path.join(d, 'beauty')):
            arms[label] = {v: os.path.join(d, 'beauty', v + '.png') for v in VIEWS}
        else:
            print('[render] %s' % label)
            arms[label] = render(glb, d, label, samples=a.samples)
    arms['null_sphere'] = {v: os.path.join(PBO.NULL_DIR, v + '_beauty.png') for v in VIEWS}
    arms['null_bald'] = {v: os.path.join(PBO.BALD_NULL_DIR, v + '_beauty.png') for v in VIEWS}

    aemb = {v: cid.embed(p) for v, p in anchors.items()}
    if any(e is None for e in aemb.values()):
        raise SystemExit(
            'DINOv2 could not embed the anchors: %s' % (cid.unavailable_reason() or 'anchor files unreadable')
        )
    table, ledger = {}, {}
    for label, paths in arms.items():
        table[label] = {}
        for v in VIEWS:
            p = paths.get(v)
            if not p or not os.path.isfile(p):
                table[label][v] = None
                ledger[f'{label}/{v}'] = 'not_found'
                continue
            s = cid.similarity_emb(aemb.get(v), cid.embed(p))
            table[label][v] = s
            ledger[f'{label}/{v}'] = 'found' if s is not None else 'unmeasurable'

    rows = [('anchor', anchors)] + [(k, arms[k]) for k in ('textured', 'solid', 'null_sphere', 'null_bald')]
    mp = montage(rows, os.path.join(a.out, 'texturing_side_by_side.png'))

    delta = {}
    for v in VIEWS:
        t, s = table['textured'][v], table['solid'][v]
        delta[v] = None if (t is None or s is None) else round(t - s, 4)
    rep = {
        'anchors': anchors,
        'views': list(VIEWS),
        'scores': table,
        'textured_minus_solid': delta,
        'ledger': ledger,
        'montage': mp,
        'framing_note': (
            "textured/solid share this session's generic rig; the sphere "
            'and bald nulls were rendered by the Pufferball sheet at the '
            'canon framing, so those two columns are NOT rig-matched'
        ),
        'verdict': None,
    }
    ok = [v for v in VIEWS if delta[v] is not None]
    if ok:
        won = [v for v in ok if delta[v] > 0]
        rep['verdict'] = 'texturing improved anchor similarity on %d of %d views (%s)' % (
            len(won),
            len(ok),
            ', '.join('%s %+0.4f' % (v, delta[v]) for v in ok),
        )
    p = os.path.join(a.out, 'texture_score.json')
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, indent=2)
        fh.write('\n')
    print(json.dumps({k: rep[k] for k in ('scores', 'textured_minus_solid', 'verdict', 'ledger')}, indent=2))
    print('[texture-score] %s' % p)
    print('[texture-score] %s' % mp)
    return 0


if __name__ == '__main__':
    sys.exit(main())
