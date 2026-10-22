# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Composite a character cut-out into a plate set's frame-1 background at the actor matte.

    python3 tools/keyframe_still.py PLATES_DIR CHARACTER_PNG OUT_PNG [--ref-out WHITE_PNG]

Used by scene_shot_run (video.keyframe) so VACE extends from a frame that already shows the
character in the scene (2026-09-20: the still it had was the grey proxy, and it animated that).
"""

import numpy as np
from PIL import Image


def cutout(path):
    from rembg import remove, new_session

    im = Image.open(path).convert('RGB')
    cut = remove(im, session=new_session('u2net'))
    a = np.array(cut)[:, :, 3]
    ys, xs = np.where(a > 64)
    return cut.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


if __name__ == '__main__':  # the CLI lives in keyframe_still_cli
    from zyg_workflows.tools.keyframe_still_cli import main as _cli_main

    raise SystemExit(_cli_main())
