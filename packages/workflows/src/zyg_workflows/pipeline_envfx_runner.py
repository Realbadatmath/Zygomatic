# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_envfx_runner.py — minimal, additive dispatch runners for the Environments and
Effects boards. New pipeline_types only — cannot affect existing pipelines.

Each runner registers a job in the shared `_workflow_jobs` registry (so the busy-check and the
kanban poll see it), spawns a daemon thread that calls the pipeline_environments / pipeline_effects
functions based on the 2D/3D render_mode, and updates status. Returns {job_id, status}.
"""

import os
import uuid
import threading
import time
import traceback

from zyg_workflows.runtime import ams_iso as _ams_iso, workflow_jobs as _workflow_jobs

_OUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')


def _now_iso():
    return _ams_iso()


def _jobs():
    return _workflow_jobs


def _mk_job(department, directive, render_mode, pipeline_options):
    pid = uuid.uuid4().hex[:12]
    _jobs()[pid] = {
        'job_id': pid,
        'pipeline_id': pid,
        'status': 'running',
        'department': department,
        'stop_event': threading.Event(),
        'stage': f'{department}_brief',
        'current_stage': 'Brief',
        'started': _now_iso(),
        'directive': (directive or '').strip(),
        'render_mode': render_mode,
        'model_family': 'sdxl',
        'pipeline_options': pipeline_options or {},
        'stages': {},
        'stage_timeline': [],
        'result': None,
        'error': None,
    }
    return pid


def _finish(pid, ok, result=None, error=None):
    j = _jobs().get(pid)
    if not j:
        return
    j['status'] = 'completed' if ok else 'failed'
    j['current_stage'] = 'Deliver' if ok else 'Error'
    j['result'] = result
    j['error'] = error


def _log_for(pid):
    """Append one Live-Tail event.

    Entries MUST be dicts {level, ts, stage, msg}. `bp_pipeline_api.kanban_status`
    reads `ev.get('level')` off every event of the active job, so appending a
    bare string raises AttributeError and 500s /api/kanban/status for the WHOLE
    dashboard, not just this board — and a failed poll then flips the board into
    a fallback that fabricates card movement twice a second.

    Not theoretical: flask.log holds 16 real tracebacks ending at
    bp_pipeline_api.py with GET /api/kanban/status 500 between 19:24 and 19:30 on
    2026-08-29, two of them AFTER the job had finished, because the status route
    falls back to the most recent job regardless of state.

    Behaviour is otherwise unchanged: same call sites, same text, same
    truncation. Only the shape of the appended value differs, and it now matches
    the shape the consumer has always required.
    """

    def _l(m):
        j = _jobs().get(pid)
        if j is None:
            return
        txt = str(m)[:120]
        low = txt.lower()
        lvl = (
            'WARN'
            if any(k in low for k in ('fail', 'unavailable', 'error', 'could not', 'missing', 'skipped'))
            else 'INFO'
        )
        j.setdefault('debug_events', []).append(
            {
                'level': lvl,
                'ts': time.strftime('%H:%M:%S'),
                'stage': j.get('current_stage') or 'Brief',
                'msg': txt,
            }
        )

    return _l


def _set_stage(pid, stage):
    j = _jobs().get(pid)
    if j is not None:
        j['current_stage'] = stage
        # Closing the previous row gives the Kanban card dialog an end to time
        # each card against; before 2026-08-26 rows were append-only with a
        # start ``ts`` and no status, so every card read "0s".
        now = time.time()
        tl = j.setdefault('stage_timeline', [])
        for entry in tl:
            if entry.get('status') == 'running' and not entry.get('ended_at'):
                entry['status'] = 'completed'
                entry['ended_at'] = now
        tl.append({'name': stage, 'status': 'running', 'ts': now, 'started_at': now, 'ended_at': None})


def start_environments(directive='', image_paths=None, render_mode='3d', pipeline_options=None, **_kw):
    """Environments board: 2d → scenery still, 3d → scenery camera-move clip."""
    render_mode = '2d' if str(render_mode).lower() == '2d' else '3d'
    pid = _mk_job('environments', directive, render_mode, pipeline_options)
    out_dir = os.path.join(_OUT_ROOT, 'environments', pid)
    os.makedirs(out_dir, exist_ok=True)
    test_mode = bool((pipeline_options or {}).get('test_scene', True))

    def _run():
        try:
            from zyg_workflows import pipeline_environments as ENV

            log = _log_for(pid)
            scene = directive or 'a cinematic landscape'
            _set_stage(pid, 'Environment Brief')
            if render_mode == '2d':
                _set_stage(pid, '2D Scenery Plate')
                r = ENV.generate_scenery_2d(scene, os.path.join(out_dir, 'scenery.png'), arcane=False, log_fn=log)
            else:
                _set_stage(pid, '3D Camera-Move Clip')
                r = ENV.generate_scenery_3d(scene, out_dir, seconds=5, test_mode=test_mode, log_fn=log)
            _set_stage(pid, 'Grade & Deliver')
            _finish(pid, bool(r), result=r)
        except Exception as e:
            _finish(pid, False, error=f'{e}\n{traceback.format_exc()[:500]}')

    threading.Thread(target=_run, name=f'env-{pid}', daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': 'environments', 'render_mode': render_mode}


def start_effects(
    directive='', image_paths=None, render_mode='3d', pipeline_options=None, effect_id='', char_id='', **_kw
):
    """Effects board: needs a base plate (image_paths[0], else generate one from the directive).
    2d → compositing FX still, 3d → motion-FX clip.
    When effect_id is given (Asset Manager card → Apply to character), apply that specific library
    preset to the character's render via effects_service (kind decides 2d still vs 3d clip)."""
    effect_id = (effect_id or '').strip()
    char_id = (char_id or '').strip()
    render_mode = '2d' if str(render_mode).lower() == '2d' else '3d'
    pid = _mk_job(
        'effects', directive or (f'{effect_id} -> {char_id[:8]}' if effect_id else ''), render_mode, pipeline_options
    )
    out_dir = os.path.join(_OUT_ROOT, 'effects', pid)
    os.makedirs(out_dir, exist_ok=True)
    test_mode = bool((pipeline_options or {}).get('test_scene', True))
    base0 = (image_paths or [None])[0]

    def _run():
        try:
            from zyg_workflows import pipeline_effects as FX

            log = _log_for(pid)
            _set_stage(pid, 'Effect Brief')
            # Library-preset path: apply one named effect to a character's render.
            if effect_id:
                from zyg_workflows import effects_service as FXS

                _set_stage(pid, 'Apply Effect')
                r = FXS.apply_effect(effect_id, base0, out_dir, char_id=char_id, log_fn=log)
                _set_stage(pid, 'Grade & Deliver')
                _finish(pid, bool(r), result=r)
                return
            base = base0
            if not (base and os.path.isfile(base)):
                # no plate supplied → make a quick scenery base from the directive
                from zyg_workflows import pipeline_environments as ENV

                base = ENV.generate_scenery_2d(
                    directive or 'a cinematic scene', os.path.join(out_dir, 'base.png'), arcane=False, log_fn=log
                )
            if not base:
                _finish(pid, False, error='no base plate for effects')
                return
            if render_mode == '2d':
                _set_stage(pid, '2D FX Layer')
                r = FX.apply_effect_2d(base, os.path.join(out_dir, 'fx.png'), log_fn=log)
            else:
                _set_stage(pid, '3D Motion FX Clip')
                # DEFAULT: scene-preserving compositing overlay (subtle drifting particles);
                # pick the particle type from the directive; fall back to WAN-baked for
                # transformation effects (fire/magic/explode) that must alter the scene.
                dl = (directive or '').lower()
                fx = next((k for k in ('embers', 'snow', 'rain', 'dust') if k in dl), None)
                if fx or not any(w in dl for w in ('fire', 'magic', 'explode', 'melt', 'transform', 'burn')):
                    r = FX.composite_fx_clip(base, out_dir, fx=(fx or 'embers'), seconds=5, log_fn=log)
                else:
                    r = FX.generate_effect_3d(base, out_dir, seconds=5, test_mode=test_mode, log_fn=log)
            _set_stage(pid, 'Grade & Deliver')
            _finish(pid, bool(r), result=r)
        except Exception as e:
            _finish(pid, False, error=f'{e}\n{traceback.format_exc()[:500]}')

    threading.Thread(target=_run, name=f'fx-{pid}', daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': 'effects', 'render_mode': render_mode}


def start_wardrobe(directive='', char_id='', outfit_id='', image_paths=None, pipeline_options=None, **_kw):
    """Wardrobe board: apply a shared-library outfit to a character (no retrain) via Qwen-edit."""
    char_id = (char_id or '').strip()
    outfit_id = (outfit_id or '').strip()
    pid = _mk_job('wardrobe', directive or f'{char_id[:8]} -> {outfit_id}', '2d', pipeline_options)
    out_dir = os.path.join(_OUT_ROOT, 'wardrobe', pid)
    os.makedirs(out_dir, exist_ok=True)
    base0 = (image_paths or [None])[0]

    def _run():
        try:
            from zyg_workflows import wardrobe_service as WD

            log = _log_for(pid)
            _set_stage(pid, 'Wardrobe Brief')
            if not char_id or not outfit_id:
                _finish(pid, False, error='char_id and outfit_id are required')
                return
            _set_stage(pid, 'Apply Outfit')
            out = os.path.join(out_dir, (outfit_id or 'outfit') + '.png')
            r = WD.apply_outfit(char_id, outfit_id, out, base_image=base0, log_fn=log)
            _set_stage(pid, 'Deliver')
            _finish(pid, bool(r), result=r)
        except Exception as e:
            _finish(pid, False, error=f'{e}\n{traceback.format_exc()[:500]}')

    threading.Thread(target=_run, name=f'wardrobe-{pid}', daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': 'wardrobe'}


def start_asset_apply(
    category='', asset_id='', char_id='', directive='', image_paths=None, pipeline_options=None, **_kw
):
    """Asset-library boards (items/food/weapons/agriculture/water/clouds/geology):
    apply a shared-library asset to a character's render via Qwen-edit (anchor decides
    held-in-hand / on-table / background swap). Presence-QC result is stored on the job."""
    category = (category or '').strip()
    asset_id = (asset_id or '').strip()
    char_id = (char_id or '').strip()
    dept = f'assetlib_{category}'
    pid = _mk_job(dept, directive or f'{category}/{asset_id} -> {char_id[:8]}', '2d', pipeline_options)
    out_dir = os.path.join(_OUT_ROOT, dept, pid)
    os.makedirs(out_dir, exist_ok=True)
    base0 = (image_paths or [None])[0]

    def _run():
        try:
            from zyg_workflows import asset_library_service as AL

            log = _log_for(pid)
            _set_stage(pid, 'Asset Brief')
            if not category or not asset_id or not char_id:
                _finish(pid, False, error='category, asset_id and char_id are required')
                return
            _set_stage(pid, 'Apply Asset')
            out = os.path.join(out_dir, f'{asset_id}.png')
            r, qc = AL.apply_asset(category, asset_id, char_id, out, base_image=base0, log_fn=log)
            j = _jobs().get(pid)
            if j is not None:
                j['presence_qc'] = qc
            _set_stage(pid, 'Deliver')
            err = None
            if not r:
                # surface the real reason (last debug event) instead of error=None
                j2 = _jobs().get(pid) or {}
                tail = (j2.get('debug_events') or ['apply failed'])[-1]
                err = f'asset apply failed: {tail}'
            elif qc and qc.get('present') is False:
                err = f'presence-QC: {qc.get("note") or "asset not visible in result"}'
            _finish(pid, bool(r) and not err, result=r, error=err)
        except Exception as e:
            _finish(pid, False, error=f'{e}\n{traceback.format_exc()[:500]}')

    threading.Thread(target=_run, name=f'assetlib-{pid}', daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': dept}
