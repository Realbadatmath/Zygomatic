#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
SDXL character pipeline smoke test (config + API wiring + optional GPU LoRA).

Fast path (default, ~15s):
  - Validates SDXL / FLUX SimpleTuner config writers
  - Comfy workflow pick + LoRA staging for SDXL
  - generate-character API registers model_family=sdxl
  - Kanban exposes SDXL LoRA + preview cards

GPU path (optional):
  ZYG_SMOKE_SDXL_LORA=1 ZYG_LORA_TRAIN_STEPS=4 python3 scripts/test_sdxl_char_pipeline_smoke.py

Usage:
  cd "${ZYG_CREWS_ROOT:-$HOME/Zygomatic Full/agents/crews}"
  python3 scripts/test_sdxl_char_pipeline_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from zyg_workflows import paths

SCRIPT_DIR = Path(__file__).resolve().parent
CREWS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(CREWS_DIR))
os.chdir(CREWS_DIR)

PASS = '✅'  # noqa: S105  console status marker, not a credential
FAIL = '❌'
results: list[tuple[bool, str, str]] = []


def check(cond: bool, title: str, ok: str, bad: str) -> None:
    results.append((cond, title, ok if cond else bad))
    print(f'  {PASS if cond else FAIL}  {title}')
    print(f'         → {ok if cond else bad}')


def main() -> int:
    print('\n── SDXL character pipeline smoke ──\n')

    # ── 1. Config writers ───────────────────────────────────────────────────
    from zyg_workflows import lora_trainer_service as lts

    with tempfile.TemporaryDirectory() as td:
        # The config writers only record the dataset dir, never read it, so td doubles as one.
        job_flux = lts.TrainingJob('smoke_flux', td, 'ZYG_CHAR_SMOKE1', 4, model_family='flux')
        job_sdxl = lts.TrainingJob('smoke_sdxl', td, 'ZYG_CHAR_SMOKE2', 4, model_family='sdxl')
        flux_dir = os.path.join(td, 'flux_cfg')
        sdxl_dir = os.path.join(td, 'sdxl_cfg')
        os.makedirs(flux_dir)
        os.makedirs(sdxl_dir)
        lts._write_st_config_flux(job_flux, flux_dir)
        lts._write_st_config_sdxl(job_sdxl, sdxl_dir)
        with open(os.path.join(flux_dir, 'config.json')) as f:
            flux_cfg = json.load(f)
        with open(os.path.join(sdxl_dir, 'config.json')) as f:
            sdxl_cfg = json.load(f)

    check(
        flux_cfg.get('--model_family') == 'flux',
        'FLUX config model_family',
        'flux',
        str(flux_cfg.get('--model_family')),
    )
    check(
        sdxl_cfg.get('--model_family') == 'sdxl',
        'SDXL config model_family',
        'sdxl',
        str(sdxl_cfg.get('--model_family')),
    )
    train_path = lts._resolve_sdxl_train_path()
    check(
        lts._sdxl_diffusers_complete(train_path) if os.path.isdir(train_path) else False,
        'SDXL diffusers train base complete (weights on disk)',
        train_path,
        'incomplete — run character gen once to auto-download, or set ZYG_SDXL_DIFFUSERS_DIR',
    )
    check(
        not str(sdxl_cfg.get('--pretrained_model_name_or_path', '')).endswith('.safetensors'),
        'SDXL config uses diffusers base (not merged safetensors)',
        str(sdxl_cfg.get('--pretrained_model_name_or_path', ''))[:80],
        'merged checkpoint breaks SimpleTuner',
    )

    # ── 2. Comfy SDXL LoRA workflow ─────────────────────────────────────────
    from zyg_workflows import comfy_generation_service as cgs

    wf = cgs._pick_workflow({}, None, None, 'character_sdxl_lora.safetensors', model_family='sdxl')
    check(
        wf == 'sdxl_character_locked',
        'Comfy picks sdxl_character_locked when SDXL LoRA staged',
        wf,
        wf,
    )

    # ── 3. API + Kanban ─────────────────────────────────────────────────────
    from zyg_dashboard import crewai_web_gui as gui

    gui._char_gen_jobs.clear()
    gui._workflow_jobs.clear()
    cid = uuid.uuid4().hex[:12]
    _zp_headers = {}
    _zpt = getattr(gui, '_ZERO_PUBLIC_TOKEN', None) or os.environ.get('ZERO_PUBLIC_INTERNAL_TOKEN', '')
    if _zpt:
        _zp_headers['X-Zero-Public-Token'] = _zpt

    with gui.app.test_client() as client:
        r = client.post(
            '/api/internal/storyteller/generate-character',
            headers=_zp_headers,
            json={
                'name': 'SmokeSDXL',
                'gender': 'female',
                'hair_color': 'brown',
                'eye_color': 'brown',
                'skin_tone': 'medium',
                'style': 'photorealistic',
                'model_family': 'sdxl',
                'kick_lora': False,
            },
        )
        check(r.status_code == 200, 'generate-character HTTP 200', str(r.status_code), r.data[:200].decode())
        body = r.get_json() or {}
        check(body.get('model_family') == 'sdxl', 'API model_family=sdxl', body.get('model_family'), str(body))

        gui._char_gen_jobs[cid] = {
            'char_id': cid,
            'status': 'running',
            'stage': 'lora_training',
            'model_family': 'sdxl',
            'params': {'model_family': 'sdxl'},
            'debug_events': [],
            'stage_timeline': [{'name': 'Stage 1c — SDXL LoRA Training', 'status': 'running'}],
        }
        ks = client.get('/api/kanban/status').get_json() or {}
        cards = ks.get('cards') or {}
        check(
            ks.get('model_family') == 'sdxl',
            'Kanban model_family sdxl',
            ks.get('model_family'),
            str(ks),
        )
        check(
            'SimpleTuner SDXL LoRA Training' in cards,
            'Kanban SDXL LoRA card present',
            'found',
            str(list(cards.keys())[:6]),
        )

    gui._char_gen_jobs.clear()

    # ── 4. Optional GPU mini-train ──────────────────────────────────────────
    if os.environ.get('ZYG_SMOKE_SDXL_LORA', '').strip().lower() in ('1', 'true', 'yes'):
        print('\n  [GPU] ZYG_SMOKE_SDXL_LORA=1 — running mini SDXL LoRA train…')
        ds_root = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
        # Reuse smallest existing dataset if any
        candidates = sorted(
            [p for p in Path(ds_root).iterdir() if p.is_dir()],
            key=lambda p: len(list(p.glob('*.png'))),
        )
        if not candidates:
            check(False, 'GPU SDXL LoRA', 'no dataset dir', 'none under storyteller_chars')
        else:
            ds = str(candidates[0])
            gpu_id = f'sdxl_smoke_{uuid.uuid4().hex[:8]}'
            steps = int(os.environ.get('ZYG_LORA_TRAIN_STEPS', '4'))
            trainer = lts.get_trainer()
            trainer.start_training(
                gpu_id,
                ds,
                trigger_token='ZYG_CHAR_SDXLSMK',  # noqa: S106  LoRA trigger word, not a credential
                total_steps=steps,
                model_family='sdxl',
            )
            deadline = time.time() + 600
            done = False
            while time.time() < deadline:
                st = trainer.get_status(gpu_id, model_family='sdxl')
                if st.get('done'):
                    done = True
                    lora = st.get('lora_path')
                    check(
                        bool(lora and os.path.isfile(lora)),
                        'GPU SDXL LoRA produced weights',
                        str(lora),
                        str(st),
                    )
                    break
                if st.get('failed'):
                    check(False, 'GPU SDXL LoRA', 'failed', str(st.get('error')))
                    break
                time.sleep(5)
            if not done:
                check(False, 'GPU SDXL LoRA', 'timeout', 'no done within 600s')

    # ── Summary ─────────────────────────────────────────────────────────────
    failed = [t for ok, t, _ in results if not ok]
    print(f'\n{"─" * 50}')
    if failed:
        print(f'{FAIL}  {len(failed)} failed: {", ".join(failed)}')
        return 1
    print(f'{PASS}  All {len(results)} checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
