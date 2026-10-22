# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.prop_mesh.texture_score`, moved out of the library module
so that library code never prints; `python -m zyg_workflows.prop_mesh.texture_score` still
reaches it.
"""

import argparse
import json
import os
import sys

from zyg_workflows.prop_mesh import texture_score as _mod
from zyg_workflows.prop_mesh.texture_score import (
    VIEWS,
    _ROOT,
    montage,
    render,
)


def main():
    import zyg_workflows.prop_mesh.pbopt as PBO
    from zyg_workflows import creature_identity as cid

    ap = argparse.ArgumentParser(description=_mod.__doc__.split('\n')[0])
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
