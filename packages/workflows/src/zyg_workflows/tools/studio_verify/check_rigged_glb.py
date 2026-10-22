#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Structural proof for a rigged base-creature GLB.

    python3 tools/studio_verify/check_rigged_glb.py FILE.glb [--joints 51] [--anims 12]
        [--min-tris 50000] [--max-tris 400000] [--color0] [--basecolor-alpha]

Exit 0 only when every primitive carries JOINTS_0 + WEIGHTS_0, the skin has the
expected joint count, the animation count matches, the triangle count is in
range, and (flags) COLOR_0 is present on every primitive / the coat material's
baseColorTexture PNG has an alpha channel (the fur-length channel). Prints one
JSON line either way.
"""

if __name__ == '__main__':  # the CLI lives in check_rigged_glb_cli
    from zyg_workflows.tools.studio_verify.check_rigged_glb_cli import main as _cli_main

    raise SystemExit(_cli_main())
