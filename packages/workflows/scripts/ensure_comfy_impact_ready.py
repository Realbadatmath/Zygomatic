#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Verify / install Impact-Pack assets for FaceDetailer + SAM (ComfyUI)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from zyg_workflows import paths

CREWS = Path(__file__).resolve().parent.parent
COMFY_ROOT = paths.ZYG_COMFY_ROOT
SAM_FILE = COMFY_ROOT / 'models' / 'sams' / 'sam_vit_b_01ec64.pth'
YOLO_FILE = COMFY_ROOT / 'models' / 'ultralytics' / 'bbox' / 'face_yolov8m.pt'
HAND_YOLO_FILE = COMFY_ROOT / 'models' / 'ultralytics' / 'bbox' / 'hand_yolov8s.pt'
HAND_YOLO_URL = 'https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8s.pt'
IMPACT_PACK = paths.ZYG_HOME / 'ComfyUI-Impact-Pack'
SAM_URL = 'https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth'


def main() -> int:
    ok = True
    SAM_FILE.parent.mkdir(parents=True, exist_ok=True)
    YOLO_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not SAM_FILE.is_file() or SAM_FILE.stat().st_size < 10_000_000:
        print(f'Downloading SAM → {SAM_FILE} …', flush=True)
        try:
            subprocess.run(
                ['wget', '-c', '-O', str(SAM_FILE), SAM_URL],
                check=True,
                timeout=3600,
            )
        except Exception as exc:
            if IMPACT_PACK.is_dir():
                print('Trying Impact-Pack install.py …', flush=True)
                subprocess.run(
                    [sys.executable, str(IMPACT_PACK / 'install.py')],
                    cwd=str(IMPACT_PACK),
                    check=False,
                )
            else:
                print(f'SAM download failed: {exc}', flush=True)
                ok = False
    else:
        print(f'OK SAM {SAM_FILE.stat().st_size // 1_000_000} MB', flush=True)

    if not YOLO_FILE.is_file():
        print(f'Missing YOLO face detector: {YOLO_FILE}', flush=True)
        print('Install via ComfyUI-Manager or Impact-Pack first run.', flush=True)
        ok = False
    else:
        print(f'OK YOLO {YOLO_FILE.name}', flush=True)

    if not HAND_YOLO_FILE.is_file() or HAND_YOLO_FILE.stat().st_size < 1_000_000:
        print(f'Downloading hand YOLO → {HAND_YOLO_FILE} …', flush=True)
        try:
            subprocess.run(
                ['wget', '-c', '-O', str(HAND_YOLO_FILE), HAND_YOLO_URL],
                check=True,
                timeout=600,
            )
        except Exception as exc:
            print(f'Hand YOLO download failed: {exc}', flush=True)
            ok = False
    if HAND_YOLO_FILE.is_file() and HAND_YOLO_FILE.stat().st_size > 1_000_000:
        print(f'OK YOLO {HAND_YOLO_FILE.name}', flush=True)
    else:
        print(f'Missing hand detector: {HAND_YOLO_FILE}', flush=True)
        ok = False

    sys.path.insert(0, str(CREWS))
    os.chdir(CREWS)
    try:
        from zyg_workflows import comfy_generation_service as cgs

        if cgs.sam_face_stack_ready():
            print('OK Comfy FaceDetailer + SAMLoader nodes and weights', flush=True)
        else:
            print('WARN Comfy face detailer stack not ready (is ComfyUI running?)', flush=True)
        if cgs.hand_detailer_stack_ready():
            print('OK Comfy HandDetailer (hand_yolov8s + FaceDetailer)', flush=True)
        else:
            print('WARN Hand detailer stack not ready', flush=True)
            if cgs.sam_face_stack_ready():
                cgs.ensure_hand_yolo_weights(print)
            if not cgs.is_available():
                print('  Set ZYG_COMFY_PRIMARY=1 and start ComfyUI on :8188', flush=True)
            ok = False
    except Exception as exc:
        print(f'Comfy check failed: {exc}', flush=True)
        ok = False

    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
