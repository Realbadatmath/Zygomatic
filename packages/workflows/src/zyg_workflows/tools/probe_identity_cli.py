# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.probe_identity`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.probe_identity` still reaches it.
"""

import argparse
import json
import os
import sys

from zyg_workflows.tools.probe_identity import HERE, frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clips', nargs='+')
    ap.add_argument('--anchor', required=True)
    ap.add_argument('--n', type=int, default=8)
    a = ap.parse_args()
    from zyg_workflows import identity_qc_service as I

    out = {}
    for clip in a.clips:
        fr = frames(clip, a.n)
        emb = I.embed_images([a.anchor] + fr)
        anc = (emb.get(a.anchor) or {}).get('embedding')
        if not anc:
            print(clip, 'ANCHOR HAS NO FACE')
            continue
        scores = []
        for f in fr:
            e = emb.get(f) or {}
            if e.get('embedding'):
                scores.append(round(I.cosine(anc, e['embedding']), 3))
        rec = {
            'faces': '%d/%d' % (len(scores), len(fr)),
            'mean': round(sum(scores) / len(scores), 3) if scores else None,
            'min': min(scores) if scores else None,
            'per_frame': scores,
        }
        out[clip] = rec
        print(os.path.relpath(clip, HERE), json.dumps(rec))
    return 0


if __name__ == '__main__':
    sys.exit(main())
