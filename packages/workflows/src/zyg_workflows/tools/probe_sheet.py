# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Contact sheet of a probe clip next to the draft: python3 tools/probe_sheet.py CLIP DRAFT OUT [--n 6]"""

import subprocess
import tempfile
import os
from PIL import Image
from zyg_workflows.bin import exe


def frames(path, n, w, h):
    tmp = tempfile.mkdtemp()
    subprocess.run([exe('ffmpeg'), '-v', 'error', '-y', '-i', path, os.path.join(tmp, 'f_%04d.png')], check=True)
    fs = sorted(os.listdir(tmp))
    idx = [round(i * (len(fs) - 1) / (n - 1)) for i in range(n)]
    return [Image.open(os.path.join(tmp, fs[i])).convert('RGB').resize((w, h)) for i in idx], idx


if __name__ == '__main__':  # the CLI lives in probe_sheet_cli
    from zyg_workflows.tools.probe_sheet_cli import main as _cli_main

    raise SystemExit(_cli_main())
