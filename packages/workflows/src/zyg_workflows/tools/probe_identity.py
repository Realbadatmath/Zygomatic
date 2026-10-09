# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Identity score of a clip against the character's canon face (ArcFace via identity_qc_service).

    python3 tools/probe_identity.py CLIP [CLIP ...] --anchor PNG [--n 8]

Prints per clip: frames with a face, mean/min cosine vs the anchor over detected frames.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import json
from zyg_workflows.bin import exe

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def frames(clip, n):
    tmp = tempfile.mkdtemp(prefix='idprobe_')
    subprocess.run([exe('ffmpeg'), '-v', 'error', '-y', '-i', clip, os.path.join(tmp, 'f_%04d.png')], check=True)
    fs = sorted(os.listdir(tmp))
    idx = [round(i * (len(fs) - 1) / (n - 1)) for i in range(n)]
    return [os.path.join(tmp, fs[i]) for i in idx]


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
