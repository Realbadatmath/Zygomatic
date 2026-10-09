#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Short pose-locked contact-sheet test (default 3 cells)."""

from __future__ import annotations

import os
import sys
import uuid

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)
os.chdir(_CREWS)

os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
os.environ.setdefault('ZYG_CONTACT_SHEET_MODE', 'pose_locked_cells')
os.environ.setdefault('ZYG_CONTACT_SHEET_POSE_MAX_CELLS', '3')
os.environ.setdefault('ZYG_CONTACT_SHEET_STEPS', os.environ.get('ZYG_CONTACT_SHEET_STEPS', '20'))
os.environ.setdefault('ZYG_CONTACT_SHEET_MIN_CELLS', '2')
os.environ.setdefault('ZYG_CONTACT_SHEET_POSE_PREVIEW_ROWS', '1')
os.environ.setdefault('ZYG_CONTACT_SHEET_POSE_PREVIEW_COLS', '3')


def main() -> int:
    from zyg_workflows import _comfy_client as cc
    from zyg_workflows import comfy_generation_service as cgs
    from zyg_workflows import contact_sheet_pipeline as csp

    n = int(os.environ.get('ZYG_CONTACT_SHEET_POSE_MAX_CELLS', '3'))
    print(f'pose_locked_stack_ready: {cgs.pose_locked_stack_ready()}')
    if not cc.server_reachable():
        print('ERROR: ComfyUI not reachable on :8188 — run setup_comfyui_stack.sh or start_server.sh')
        return 1
    if not cgs.pose_locked_stack_ready():
        print('ERROR: pose stack not ready (IPA, Union CN, or pose assets missing)')
        return 1

    char_id = os.environ.get('ZYG_POSE_TEST_CHAR_ID', f'pose_test_{uuid.uuid4().hex[:8]}')
    params = {
        'name': 'Pose Test',
        'gender': 'female',
        'hair_color': 'auburn',
        'eye_color': 'green',
        'skin_tone': 'medium',
        'style': 'photorealistic',
    }
    csp.master_sheet_path(char_id)

    def log(msg: str) -> None:
        print(msg, flush=True)

    log(f'=== Pose-locked test: {n} cells, char_id={char_id} ===')
    try:
        path = csp.generate_contact_sheet(
            char_id,
            params,
            mode='pose_locked_cells',
            model_family='flux',
            log_fn=log,
        )
    except Exception as exc:
        print(f'FAILED: {exc}')
        return 1

    if not path or not os.path.isfile(path):
        print('FAILED: no master sheet output')
        return 1

    csp.tiles_dir(char_id)
    cells = (
        sorted(f for f in os.listdir(os.path.join(csp.contact_sheet_dir(char_id), 'cells')) if f.endswith('.png'))
        if os.path.isdir(os.path.join(csp.contact_sheet_dir(char_id), 'cells'))
        else []
    )
    print(f'OK — preview: {path}')
    print(f'    cells: {cells}')
    print(f'    dir:   {csp.contact_sheet_dir(char_id)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
