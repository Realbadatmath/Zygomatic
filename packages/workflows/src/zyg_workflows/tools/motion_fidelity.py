# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Wrist fidelity of a rendered clip against the rig's own projected joints.

    python3 tools/motion_fidelity.py CLIP SHOT_DIR [--n 8]

Detects BlazePose on N evenly spaced frames of CLIP (geom.keypoints.detect) and compares
left/right wrists with plates_raw/joints.json (the Blender rig's 2D projections, same 33-name
convention). Pairing is by position (min over direct/swapped) because a back view flips
left/right in the detector. Reports px error and % of the rig's body height. Writes
<clip>.fidelity.json.
"""

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


if __name__ == '__main__':  # the CLI lives in motion_fidelity_cli
    from zyg_workflows.tools.motion_fidelity_cli import main as _cli_main

    raise SystemExit(_cli_main())
