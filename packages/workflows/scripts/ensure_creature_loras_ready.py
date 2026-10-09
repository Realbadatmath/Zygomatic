#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Download and install Creature Creation LoRA weights."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from zyg_workflows import paths

CREWS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CREWS))

from zyg_workflows.creature_lora_service import CREATURE_LORA_DIR, CREATURE_LORA_PROFILES, status_report  # noqa: E402

COMFY_LORA = paths.ZYG_COMFY_LORA_DIR

DOWNLOADS = {
    'flux_cinematic_wildlife.safetensors': {
        'repo': 'akba08/flux_cinematic_photography_finetuned',
        'filename': 'pytorch_lora_weights.safetensors',
    },
    'flux_dark_fantasy.safetensors': {
        'repo': 'Shakker-Labs/FLUX.1-dev-LoRA-Dark-Fantasy',
        'filename': 'FLUX.1-dev-lora-Dark-Fantasy.safetensors',
    },
    'flux_dark_fantasy_alt.safetensors': {
        'repo': 'Omarito2412/Dark-Fantasy-Flux',
        'filename': 'dark_fantasy_flux.safetensors',
    },
}


def _hf_token() -> str:
    tok = os.environ.get('HF_TOKEN', '').strip()
    if tok:
        return tok
    env_file = paths.ZYG_CREWS_ROOT.parent.parent / '.env'
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if line.startswith('HF_TOKEN='):
                return line.split('=', 1)[1].strip()
    return ''


def _run(cmd: list[str], **kwargs) -> int:
    return subprocess.run(cmd, check=False, **kwargs).returncode


def _download_one(dest_name: str, spec: dict) -> bool:
    dest = CREATURE_LORA_DIR / dest_name
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        print(f'OK already present: {dest}', flush=True)
        return True

    CREATURE_LORA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CREATURE_LORA_DIR / f'.dl_{dest_name}'
    if tmp.is_dir():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    tok = _hf_token()
    if tok:
        env['HF_TOKEN'] = tok

    hf_cli = paths.ZYG_COMFY_ROOT / '.venv' / 'bin' / 'hf'
    hf_bin = str(hf_cli) if hf_cli.is_file() else 'hf'
    print(f'Downloading {spec["repo"]} → {dest_name} …', flush=True)
    rc = _run(
        [
            hf_bin,
            'download',
            spec['repo'],
            spec['filename'],
            '--local-dir',
            str(tmp),
        ],
        timeout=7200,
        env=env,
    )
    src = tmp / spec['filename']
    if rc != 0 or not src.is_file():
        print(f'FAILED download {spec["repo"]}', flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
        return False

    shutil.copy2(src, dest)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'Installed {dest} ({dest.stat().st_size // 1_000_000} MB)', flush=True)
    return True


def _mirror_to_comfy() -> None:
    COMFY_LORA.mkdir(parents=True, exist_ok=True)
    for prof in CREATURE_LORA_PROFILES.values():
        src = CREATURE_LORA_DIR / prof['lora_file']
        if not src.is_file():
            continue
        dst = COMFY_LORA / prof['lora_file']
        if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
            print(f'Mirrored to Comfy loras: {dst.name}', flush=True)


def main() -> int:
    ok = True
    for dest_name, spec in DOWNLOADS.items():
        if not _download_one(dest_name, spec):
            ok = False
    _mirror_to_comfy()
    if not status_report(print):
        ok = False
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
