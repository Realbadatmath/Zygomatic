#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Verify / install HandFixer + FLUX.1-Fill-dev for ComfyUI hand repair."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from zyg_workflows import paths

CREWS = Path(__file__).resolve().parent.parent
COMFY_ROOT = paths.ZYG_COMFY_ROOT
COMFY_VENV = COMFY_ROOT / '.venv' / 'bin' / 'python'
HANDFIXER = COMFY_ROOT / 'custom_nodes' / 'ComfyUI-HandFixer'
FILL_UNET = COMFY_ROOT / 'models' / 'unet' / 'flux1-fill-dev.safetensors'
FILL_MODEL = 'black-forest-labs/FLUX.1-Fill-dev'
HAND_YOLO = COMFY_ROOT / 'models' / 'ultralytics' / 'bbox' / 'hand_yolov8s.pt'


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, **kwargs)


def main() -> int:
    ok = True

    if not HANDFIXER.is_dir():
        print(f'Cloning HandFixer → {HANDFIXER} …', flush=True)
        HANDFIXER.parent.mkdir(parents=True, exist_ok=True)
        rc = _run(
            [
                'git',
                'clone',
                '--depth',
                '1',
                'https://github.com/Xiangyu-CAS/HandFixer.git',
                str(HANDFIXER),
            ]
        ).returncode
        if rc != 0:
            print('HandFixer clone failed', flush=True)
            ok = False
    else:
        print(f'OK HandFixer node at {HANDFIXER}', flush=True)

    req = HANDFIXER / 'requirements.txt'
    if req.is_file() and COMFY_VENV.is_file():
        print('Installing HandFixer requirements in Comfy venv …', flush=True)
        _run([str(COMFY_VENV), '-m', 'pip', 'install', '-r', str(req)])
        # HandFixer needs legacy mediapipe.solutions (removed in ≥0.10.21)
        _run([str(COMFY_VENV), '-m', 'pip', 'install', 'mediapipe==0.10.14'])

    vae_link = COMFY_ROOT / 'models' / 'vae' / 'ae.safetensors'
    flux_ae = COMFY_ROOT / 'models' / 'vae' / 'flux_ae.safetensors'
    if flux_ae.is_file() and not vae_link.is_file():
        vae_link.symlink_to('flux_ae.safetensors')
        print('OK ae.safetensors → flux_ae.safetensors', flush=True)

    if not FILL_UNET.is_file() or FILL_UNET.stat().st_size < 1_000_000_000:
        print(f'Downloading FLUX.1-Fill-dev → {FILL_UNET} …', flush=True)
        FILL_UNET.parent.mkdir(parents=True, exist_ok=True)
        hf_cli = COMFY_ROOT / '.venv' / 'bin' / 'hf'
        env = os.environ.copy()
        _env_file = paths.ZYG_CREWS_ROOT.parent.parent / '.env'
        if _env_file.is_file() and not env.get('HF_TOKEN'):
            for _line in _env_file.read_text().splitlines():
                if _line.startswith('HF_TOKEN='):
                    env['HF_TOKEN'] = _line.split('=', 1)[1].strip()
                    break
        dl_cmd = [
            str(hf_cli) if hf_cli.is_file() else 'hf',
            'download',
            FILL_MODEL,
            'flux1-fill-dev.safetensors',
            '--local-dir',
            str(FILL_UNET.parent),
        ]
        rc = _run(dl_cmd, timeout=7200, env=env).returncode
        if rc != 0 or not FILL_UNET.is_file():
            print('FLUX Fill download failed — set HF_TOKEN if gated', flush=True)
            ok = False
    else:
        print(f'OK FLUX Fill {FILL_UNET.stat().st_size // 1_000_000_000} GB', flush=True)

    if HAND_YOLO.is_file():
        print(f'OK hand_yolov8s {HAND_YOLO.stat().st_size // 1_000_000} MB', flush=True)
    else:
        print(f'Missing {HAND_YOLO} — run ensure_comfy_impact_ready.py', flush=True)
        ok = False

    sys.path.insert(0, str(CREWS))
    os.chdir(CREWS)
    try:
        from zyg_workflows import comfy_generation_service as cgs

        if cgs.hand_fixer_enabled() and cgs.hand_fixer_stack_ready():
            # 2026-07-24 r4: masks are host-built from YOLO boxes; the
            # MediapipeHandNode dependency is gone.
            print('OK HandFixer stack ready (hand_yolov8s + FLUX Fill, host masks)', flush=True)
        elif cgs.hand_fixer_enabled():
            print('WARN HandFixer enabled but stack not ready', flush=True)
            if not FILL_UNET.is_file():
                ok = False
        else:
            print('HandFixer disabled (ZYG_HAND_FIXER=0)', flush=True)
        if cgs.hand_detailer_stack_ready():
            print('OK HandDetailer fallback (hand_yolov8s + SAM)', flush=True)
    except Exception as exc:
        print(f'Comfy check failed: {exc}', flush=True)
        ok = False

    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
