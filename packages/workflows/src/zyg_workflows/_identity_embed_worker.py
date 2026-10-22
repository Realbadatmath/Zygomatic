# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
ArcFace embedding worker — runs inside the ComfyUI venv (insightface + antelopev2).

Invoked as a subprocess by identity_qc_service; not imported by the agents venv.
stdin/argv: --images <json list file> --root <insightface root> --out <json path>
Output JSON per image:
  {face_detected, faces_count, det_score, bbox, embedding[512], yaw, img_w, img_h}
faces_count counts detections at/above --det-thresh (content-truth checks use it
to reject sliced-collage tiles containing more than one person). yaw comes from
the landmark_3d_68 head-pose model (degrees; None when unavailable).

The command line (the whole argv parsing and scoring loop) lives in
`_identity_embed_worker_cli.py` so that library code never prints.
"""

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


if __name__ == '__main__':  # the CLI lives in _identity_embed_worker_cli
    try:
        from zyg_workflows._identity_embed_worker_cli import main as _cli_main
    except ImportError:  # identity_qc_service runs this file by path in the ComfyUI venv
        import os as _os
        import sys as _sys

        _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from zyg_workflows._identity_embed_worker_cli import main as _cli_main

    raise SystemExit(_cli_main())
