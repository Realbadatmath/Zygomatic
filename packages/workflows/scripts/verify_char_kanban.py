#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Verify character-generation Kanban + model_family wiring (no GPU work)."""

from __future__ import annotations

import json
import os
import sys
import tempfile

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

os.chdir(_CREWS)


def _test_normalize_default():
    from zyg_dashboard import crewai_web_gui as gui

    assert gui._normalize_char_model_family(None, {}, {}) == 'sdxl'
    assert gui._normalize_char_model_family('', {}, {}) == 'sdxl'
    assert gui._normalize_char_model_family('flux', {}, {}) == 'flux'
    print('  [ok] _normalize_char_model_family defaults')


def _test_kanban_char_priority():
    from zyg_dashboard import crewai_web_gui as gui

    gui._char_gen_jobs.clear()
    gui._workflow_jobs.clear()
    char_id = 'verify_kanban_test01'
    gui._char_gen_jobs[char_id] = {
        'char_id': char_id,
        'status': 'running',
        'stage': 'lora_training',
        'started': '2026-05-28T22:00:00+02:00',
        'model_family': 'sdxl',
        'params': {'model_family': 'sdxl', 'style': 'photorealistic'},
        'debug_events': [],
        'stage_timeline': [],
    }
    gui._workflow_jobs['story-pipe-1'] = {
        'status': 'running',
        'department': 'storyteller',
        'model_family': 'flux',
        'started': '2026-05-28T21:00:00+02:00',
        'current_stage': 'Stage 2',
        'stage_timeline': [],
        'debug_events': [],
    }

    with gui.app.test_client() as client:
        r = client.get('/api/kanban/status')
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data.get('template') == 'character_creation', data.get('template')
        assert data.get('model_family') == 'sdxl', data.get('model_family')
        assert data.get('pipeline', {}).get('status') == 'running'
        cards = data.get('cards') or {}
        assert 'SimpleTuner SDXL LoRA Training' in cards or 'SimpleTuner FLUX LoRA Training' in cards
        assert 'SDXL Preview Render' in cards
        print('  [ok] Kanban prefers character_creation over running storyteller')

    gui._char_gen_jobs.clear()
    gui._workflow_jobs.clear()


def _test_generate_character_registers_mf():
    from zyg_dashboard import crewai_web_gui as gui

    gui._char_gen_jobs.clear()
    payload = {
        'name': 'Verify',
        'gender': 'female',
        'hair_color': 'brown',
        'eye_color': 'brown',
        'skin_tone': 'medium',
        'style': 'photorealistic',
        'model_family': 'sdxl',
        'kick_lora': False,
    }
    token = os.environ.get('ZERO_PUBLIC_TOKEN', '')
    headers = {'X-Zero-Public-Token': token} if token else {}
    with gui.app.test_client() as client:
        r = client.post(
            '/api/internal/storyteller/generate-character',
            json=payload,
            headers=headers,
        )
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:300])
        body = r.get_json()
        assert body.get('model_family') == 'sdxl', body
        cid = body['char_id']
        job = gui._char_gen_jobs.get(cid) or {}
        assert job.get('model_family') == 'sdxl'
        assert (job.get('params') or {}).get('model_family') == 'sdxl'
        # Stop background thread from doing real work
        job['status'] = 'error'
        job['error'] = 'verify abort'
        print('  [ok] generate-character persists model_family on job')


def _test_caption_style():
    from zyg_workflows.blender_character_service import caption_style_description

    assert 'photorealistic' in caption_style_description('photorealistic')
    print('  [ok] photorealistic captions')


def _test_sdxl_lora_config_writer():
    import os
    from zyg_workflows import lora_trainer_service as lts

    with tempfile.TemporaryDirectory() as td:
        # The config writer only records the dataset dir, never reads it, so td doubles as one.
        job = lts.TrainingJob('t', td, 'TOK', 8, model_family='sdxl')
        lts._write_st_config_sdxl(job, td)
        with open(os.path.join(td, 'config.json')) as f:
            cfg = json.load(f)
    assert cfg.get('--model_family') == 'sdxl'
    train_path = cfg.get('--pretrained_model_name_or_path', '')
    assert not str(train_path).endswith('.safetensors'), train_path
    if os.path.isdir(train_path):
        assert lts._sdxl_diffusers_complete(train_path), f'incomplete SDXL tree at {train_path}'
    print('  [ok] SDXL SimpleTuner config writer')


def _test_orphan_stale_running():
    from zyg_dashboard import crewai_web_gui as gui

    zombie = {
        'char_id': 'orphan_test01',
        'status': 'running',
        'stage': 'blender_render',
        'current_stage': 'init',
        'params': {'model_family': 'sdxl', 'name': 'Zombie'},
        'model_family': 'sdxl',
        'debug_events': [],
        'stage_timeline': [],
    }
    fixed, changed = gui._char_orphan_stale_running_job(zombie)
    assert changed
    assert fixed.get('status') == 'error'
    assert 'Orphaned on server restart' in (fixed.get('error') or '')

    done_job = {
        'char_id': 'orphan_test02',
        'status': 'running',
        'stage': 'blender_render',
        'debug_events': [{'msg': 'Character orphan_test02 generation complete', 'ts': '2026-05-28T22:40:43+02:00'}],
        'stage_timeline': [
            {'name': 'Stage 1d — Preview Render', 'status': 'failed', 'ended_at': '2026-05-28T22:40:43+02:00'},
        ],
        'lora_failed': True,
    }
    fixed2, changed2 = gui._char_orphan_stale_running_job(done_job)
    assert changed2
    assert fixed2.get('status') == 'error'
    print('  [ok] orphan stale running jobs on restart')


def _test_preview_slots_and_reconcile():
    from zyg_dashboard import crewai_web_gui as gui

    assert gui._char_preview_slot_names('sdxl') == ('preview_sdxl_front', 'preview_sdxl_face')
    assert gui._char_preview_slot_names('flux') == ('preview_flux_front', 'preview_flux_face')
    stale = {
        'char_id': 'stale01',
        'status': 'running',
        'stage': 'blender_render',
        'debug_events': [{'msg': 'Character stale01 generation complete', 'ts': '2026-05-28T22:40:43+02:00'}],
        'stage_timeline': [
            {'name': 'Stage 1d — Preview Render', 'status': 'completed', 'ended_at': '2026-05-28T22:40:43+02:00'},
        ],
    }
    fixed = gui._char_reconcile_job_state(stale)
    assert fixed.get('status') == 'done'
    assert gui._char_derive_pipeline_stage(fixed) == 'done'
    print('  [ok] preview slot names + stale job reconcile')


def main() -> int:
    print('verify_char_kanban')
    _test_normalize_default()
    _test_caption_style()
    _test_sdxl_lora_config_writer()
    _test_orphan_stale_running()
    _test_kanban_char_priority()
    _test_generate_character_registers_mf()
    _test_preview_slots_and_reconcile()
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
