#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_comfy_workflow.py — Validate a workflow JSON against the live ComfyUI server.

Loads a workflow from _comfy_workflows/<name>.json, submits it to /prompt, and
reports any node_errors. Used to iterate workflow correctness without a browser.

Usage::
    python3 scripts/test_comfy_workflow.py flux_txt2img
    python3 scripts/test_comfy_workflow.py flux_fill_inpaint
    python3 scripts/test_comfy_workflow.py wan_i2v
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zyg_workflows import _comfy_client as cc


def main():
    if len(sys.argv) < 2:
        print(f'usage: {sys.argv[0]} <workflow_name> [timeout_s]')
        sys.exit(2)
    name = sys.argv[1]
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 180

    if not cc.server_reachable():
        print(f'ComfyUI not reachable at {cc.COMFY_HOST}:{cc.COMFY_PORT}')
        sys.exit(1)
    print(f'server OK at {cc.COMFY_HOST}:{cc.COMFY_PORT}')

    wf = cc.load_workflow(name)
    print(f'workflow has {len(wf)} nodes: {sorted(wf.keys())}')

    t0 = time.time()
    try:
        outputs = cc.submit(wf, timeout_s=timeout)
        elapsed = time.time() - t0
        print(f'OK in {elapsed:.1f}s — outputs:')
        for o in outputs:
            print(f'  {o}')
    except cc.ComfyUIError as exc:
        elapsed = time.time() - t0
        print(f'FAILED after {elapsed:.1f}s: {exc}')
        sys.exit(1)


if __name__ == '__main__':
    main()
