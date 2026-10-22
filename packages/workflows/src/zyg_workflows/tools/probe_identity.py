# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Identity score of a clip against the character's canon face (ArcFace via identity_qc_service).

    python3 tools/probe_identity.py CLIP [CLIP ...] --anchor PNG [--n 8]

Prints per clip: frames with a face, mean/min cosine vs the anchor over detected frames.
"""

import os
import subprocess
import sys
import tempfile
from zyg_workflows.bin import exe

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def frames(clip, n):
    tmp = tempfile.mkdtemp(prefix='idprobe_')
    subprocess.run([exe('ffmpeg'), '-v', 'error', '-y', '-i', clip, os.path.join(tmp, 'f_%04d.png')], check=True)
    fs = sorted(os.listdir(tmp))
    idx = [round(i * (len(fs) - 1) / (n - 1)) for i in range(n)]
    return [os.path.join(tmp, fs[i]) for i in idx]


if __name__ == '__main__':  # the CLI lives in probe_identity_cli
    from zyg_workflows.tools.probe_identity_cli import main as _cli_main

    raise SystemExit(_cli_main())
