#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Export a GEM-X SOMA demo result as a 78-joint SOMA BVH plus a metadata sidecar.

Runs inside the GEM-X venv ($ZYG_MODELS_DIR/gemx/GEM-X/.venv). It reads the
``preprocess/hpe_results.pt`` written by ``scripts/demo/demo_soma.py``, takes the
world-space body params, builds the SOMA skeleton for the recovered identity and
writes the BVH with the demo's own ``retarget_utils`` helpers.

``build_soma_skeleton_from_model`` resolves ``inputs/soma_assets`` relative to the
process CWD, so this script resolves every user path to an absolute one and then
chdirs into the GEM-X root itself.

Usage:
    python tools/gem_capture.py \
        --gem-dir .../capture/_raw/qa_sword/gem/qa_sword \
        --fps 24 \
        --out .../capture/_raw/qa_sword/qa_sword_soma.bvh
"""

from __future__ import annotations

import os
from pathlib import Path

# This script runs under the GEM-X venv, where zyg_workflows is not importable, so the
# ZYG_HOME / ZYG_MODELS_DIR roots are read here with the defaults paths.py uses.
_ZYG_HOME = Path(os.environ.get('ZYG_HOME', '').strip() or Path.home())
_MODELS_DIR = Path(os.environ.get('ZYG_MODELS_DIR', '').strip() or _ZYG_HOME / 'models')
GEMX_ROOT = _MODELS_DIR / 'gemx' / 'GEM-X'
GEMX_DEMO = GEMX_ROOT / 'scripts' / 'demo'


def _describe(value):
    """One-line shape/type description of a tensor, array or container."""
    shape = getattr(value, 'shape', None)
    if shape is not None:
        return f'{type(value).__name__}{tuple(shape)}'
    if isinstance(value, dict):
        return f'dict({len(value)} keys)'
    if isinstance(value, (list, tuple)):
        return f'{type(value).__name__}({len(value)})'
    return type(value).__name__


if __name__ == '__main__':  # the CLI lives in gem_capture_cli
    try:
        from zyg_workflows.tools.gem_capture_cli import main as _cli_main
    except ImportError:  # the GEM-X venv has no zyg_workflows; the sibling module sits beside this file
        from gem_capture_cli import main as _cli_main

    raise SystemExit(_cli_main())
