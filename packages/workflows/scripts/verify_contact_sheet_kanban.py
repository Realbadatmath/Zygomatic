#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Verify multi-angle contact sheet Kanban + API wiring (no GPU)."""

from __future__ import annotations

import os
import sys
import tempfile

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

os.chdir(_CREWS)


def _test_module_imports():
    from zyg_workflows import contact_sheet_pipeline as csp

    assert csp.DEFAULT_ROWS >= 2
    assert csp.DEFAULT_COLS >= 2
    from zyg_workflows import comfy_generation_service as _cgs

    auto_mode = csp._resolve_sheet_mode('auto')
    assert auto_mode in ('pose_locked_cells', 'dual_canvas'), auto_mode
    if _cgs.pose_locked_stack_ready():
        assert auto_mode == 'pose_locked_cells'
    assert csp._resolve_sheet_mode('single_canvas') == 'single_canvas'
    assert csp.DUAL_SHEET_TOTAL_ANGLES == 24
    assert csp.DUAL_SHEET_COLS == 3 and csp.DUAL_SHEET_COUNT == 4
    assert len(csp.CONTACT_SHEET_ANGLE_LABELS) == 24
    assert csp.CANVAS_GEN_W == 1920 and csp.CANVAS_GEN_H == 1080
    assert csp.EXPORT_CELL_W == 640 and csp.EXPORT_CELL_H == 720
    print('  [ok] contact_sheet_pipeline imports + 4×2×3 constants')


def _test_dual_sheet_tile_export():
    """Multi 2×3×4 manifests → 24 tiles with correct angle labels."""
    from zyg_workflows import contact_sheet_pipeline as csp
    from PIL import Image

    char_id = 'verify_cs_dual24'
    with tempfile.TemporaryDirectory() as td:
        csp._DATASET_ROOT = td
        rows, cols, gutter = 2, 3, 8
        uw, uh = 3840, 2160
        cw, ch = csp._grid_cell_size(uw, uh, rows, cols, gutter)
        offsets = (0, 6, 12, 18)
        for part, _angles, offset in (
            ('a', csp.SHEET_A_ANGLES, offsets[0]),
            ('b', csp.SHEET_B_ANGLES, offsets[1]),
            ('c', csp.SHEET_C_ANGLES, offsets[2]),
            ('d', csp.SHEET_D_ANGLES, offsets[3]),
        ):
            sheet = Image.new('RGB', (uw, uh), (30, 30, 36))
            for r in range(rows):
                for c in range(cols):
                    x0 = gutter + c * (cw + gutter)
                    y0 = gutter + r * (ch + gutter)
                    color = ((offset + r * cols + c) * 9 % 200 + 40, 80, 120)
                    for y in range(y0, min(y0 + ch, uh)):
                        for x in range(x0, min(x0 + cw, uw)):
                            sheet.putpixel((x, y), color)
            os.makedirs(csp.contact_sheet_dir(char_id), exist_ok=True)
            sheet.save(csp.master_sheet_path_part(char_id, part), format='PNG')
        comp = os.path.join(csp.contact_sheet_dir(char_id), 'contact_sheet_master.png')
        csp._composite_sheet_stack(
            [csp.master_sheet_path_part(char_id, p) for p in ('a', 'b', 'c', 'd')],
            comp,
        )
        csp.write_manifest(
            char_id,
            rows=rows,
            cols=cols,
            gutter=gutter,
            cell_w=cw,
            cell_h=ch,
            sheet_path=comp,
            extra={
                'generation_mode': 'multi_canvas_esrgan',
                'dual_sheet': True,
                'total_tiles': 24,
                'sheets': [
                    {
                        'part': p,
                        'angles': csp._angles_for_sheet_part(p),
                        'angle_offset': off,
                        'master_path': csp.master_sheet_path_part(char_id, p),
                        'rows': rows,
                        'cols': cols,
                    }
                    for p, off in zip(('a', 'b', 'c', 'd'), offsets)
                ],
                'export_cell_width': csp.EXPORT_CELL_W,
                'export_cell_height': csp.EXPORT_CELL_H,
            },
        )
        tiles = csp.split_sheet_into_tiles(char_id)
        assert len(tiles) == 24, len(tiles)
        assert tiles[0]['angle'] == csp.SHEET_A_ANGLES[0]
        assert tiles[6]['angle'] == csp.SHEET_B_ANGLES[0]
        assert tiles[18]['angle'] == csp.SHEET_D_ANGLES[0]
        for t in tiles:
            from PIL import Image as _Im

            assert _Im.open(t['path']).size == (csp.EXPORT_CELL_W, csp.EXPORT_CELL_H)
    print('  [ok] four 2×3 sheets → 24×640×720 tiles')


def _test_perfect_pixel_tile_export():
    """Synthetic 4K sheet → tiles export at 640×720."""
    from zyg_workflows import contact_sheet_pipeline as csp
    from PIL import Image

    char_id = 'verify_cs_4k_slice01'
    with tempfile.TemporaryDirectory() as td:
        csp._DATASET_ROOT = td
        rows, cols, gutter = 2, 3, 8
        uw, uh = 1920 * 2, 1080 * 2  # 3840×2160
        cw, ch = csp._grid_cell_size(uw, uh, rows, cols, gutter)
        sheet = Image.new('RGB', (uw, uh), (40, 40, 40))
        for r in range(rows):
            for c in range(cols):
                x0 = gutter + c * (cw + gutter)
                y0 = gutter + r * (ch + gutter)
                color = ((r + 1) * 40, (c + 1) * 50, 120)
                for y in range(y0, min(y0 + ch, uh)):
                    for x in range(x0, min(x0 + cw, uw)):
                        sheet.putpixel((x, y), color)
        os.makedirs(csp.contact_sheet_dir(char_id), exist_ok=True)
        master = csp.master_sheet_path(char_id)
        sheet.save(master, format='PNG')
        csp.write_manifest(
            char_id,
            rows=rows,
            cols=cols,
            gutter=gutter,
            cell_w=cw,
            cell_h=ch,
            sheet_path=master,
            extra={
                'generation_mode': 'single_canvas_esrgan',
                'export_cell_width': csp.EXPORT_CELL_W,
                'export_cell_height': csp.EXPORT_CELL_H,
            },
        )
        tiles = csp.split_sheet_into_tiles(char_id)
        assert len(tiles) == rows * cols
        for t in tiles:
            from PIL import Image as _Im

            im = _Im.open(t['path'])
            assert im.size == (csp.EXPORT_CELL_W, csp.EXPORT_CELL_H), im.size
    print('  [ok] 4K sheet slices → 640×720 export tiles')


def _test_mock_sheet_and_tiles():
    from zyg_workflows import contact_sheet_pipeline as csp

    char_id = 'verify_cs_tiles01'
    with tempfile.TemporaryDirectory() as td:
        # Patch roots for isolation
        csp._DATASET_ROOT = td
        params = {'name': 'Verify', 'gender': 'female', 'style': 'photorealistic'}
        path = csp.generate_contact_sheet(
            char_id,
            params,
            rows=2,
            cols=3,
            mode='mock',
            log_fn=lambda m: None,
        )
        assert os.path.isfile(path), path
        csp.write_manifest(
            char_id,
            rows=2,
            cols=3,
            gutter=4,
            cell_w=128,
            cell_h=160,
            sheet_path=path,
            approved=True,
        )
        tiles = csp.split_sheet_into_tiles(char_id)
        assert len(tiles) == 6, len(tiles)
        n = csp.write_tile_captions(char_id, params, tiles)
        assert n == 6, n
        ds = os.path.join(td, char_id)
        pngs = [f for f in os.listdir(ds) if f.startswith('contactsheet_') and f.endswith('.png')]
        assert len(pngs) == 6, pngs
    print('  [ok] mock sheet → tiles → captions')


def _test_kanban_priority():
    from zyg_dashboard import crewai_web_gui as gui

    gui._contact_sheet_jobs.clear()
    gui._char_gen_jobs.clear()
    gui._workflow_jobs.clear()
    gui._CONTACT_SHEET_RELOAD_DONE = True
    cid = 'verify_cs_kanban01'
    gui._contact_sheet_jobs[cid] = {
        'char_id': cid,
        'status': 'running',
        'stage': 'tile_crop',
        'started': '2026-06-01T22:00:00+02:00',
        'model_family': 'flux',
        'params': {'style': 'photorealistic'},
        'debug_events': [],
        'stage_timeline': [],
    }
    gui._char_gen_jobs['other'] = {
        'char_id': 'other',
        'status': 'running',
        'stage': 'lora_training',
        'started': '2026-06-01T21:00:00+02:00',
        'model_family': 'sdxl',
        'params': {},
        'debug_events': [],
        'stage_timeline': [],
    }
    with gui.app.test_client() as client:
        r = client.get('/api/kanban/status')
        assert r.status_code == 200
        data = r.get_json()
        assert data.get('template') == 'contact_sheet_creation', data.get('template')
        assert 'Tile Crop' in (data.get('cards') or {})
        assert data.get('cards', {}).get('Tile Crop') == 'running'
    gui._contact_sheet_jobs.clear()
    gui._char_gen_jobs.clear()
    print('  [ok] Kanban prefers contact_sheet_creation')


def _test_list_contact_sheets_api():
    from zyg_dashboard import crewai_web_gui as gui

    with gui.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_role'] = 'admin'
            sess['_validity'] = gui.SESSION_VALIDITY_TOKEN
        r = client.get('/api/internal/storyteller/list-contact-sheets')
        assert r.status_code == 200, r.get_data(as_text=True)[:300]
        data = r.get_json()
        assert 'sheets' in data
        print(f'  [ok] list-contact-sheets ({data.get("count", 0)} entries)')


def _test_start_and_status_api():
    from zyg_dashboard import crewai_web_gui as gui

    gui._contact_sheet_jobs.clear()
    payload = {
        'name': 'SheetTest',
        'gender': 'female',
        'hair_color': 'auburn',
        'eye_color': 'green',
        'skin_tone': 'medium',
        'style': 'photorealistic',
        'model_family': 'flux',
        'kick_lora': False,
        'auto_approve': True,
        'rows': 2,
        'cols': 2,
        'sheet_mode': 'mock',
    }
    token = os.environ.get('ZERO_PUBLIC_TOKEN', '')
    headers = {'X-Zero-Public-Token': token} if token else {}
    with gui.app.test_client() as client:
        if not token:
            with client.session_transaction() as sess:
                sess['user_role'] = 'admin'
                sess['_validity'] = gui.SESSION_VALIDITY_TOKEN
        r = client.post(
            '/api/internal/storyteller/contact-sheet/start',
            json=payload,
            headers=headers,
        )
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        body = r.get_json()
        cid = body['char_id']
        assert body.get('pipeline') == 'multi_angle_contact_sheet'
        # Let background thread finish quickly (mock, no lora)
        import time

        for _ in range(60):
            time.sleep(0.25)
            st = client.get(
                f'/api/internal/storyteller/contact-sheet/status/{cid}',
                headers=headers,
            )
            assert st.status_code == 200
            sj = st.get_json()
            if sj.get('status') in ('done', 'error'):
                break
        assert sj.get('status') == 'done', sj
        assert sj.get('tile_count', 0) >= 4, sj
        job = gui._contact_sheet_jobs.get(cid) or {}
        job['status'] = 'done'
    gui._contact_sheet_jobs.clear()
    print('  [ok] contact-sheet start API + background pipeline (mock, no LoRA)')


def main() -> int:
    print('verify_contact_sheet_kanban')
    _test_module_imports()
    _test_dual_sheet_tile_export()
    _test_perfect_pixel_tile_export()
    _test_mock_sheet_and_tiles()
    _test_kanban_priority()
    _test_list_contact_sheets_api()
    _test_start_and_status_api()
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
