# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 4, step 1: make room on the GPU and import the two services.

Driver lines 213-379 of `pipeline_video._run_video_pipeline` at d443b3b,
verbatim: the `Video Generation` stage card, the `sys.path` tweak, the
competing-VRAM-user sweep (Step 1), the PyTorch cache flush and the free-VRAM
verdict (Step 2), the `wan_video_service` import with its VRAM gate and its
ComfyUI escape hatch, and the `audio_service` import.

The one line that is not verbatim is the `sys.path` anchor, which derived the
`zyg_workflows/` directory from the module's own path: it reads the `_PKG_DIR`
constant below instead, the same re-anchor `scholarly/stages_01_18.py` makes.
"""

import os

from zyg_workflows.bin import exe
from zyg_workflows.vram_manager import _release_pipeline_vram

import logging as _zyg_logging

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')

# `zyg_workflows/` — what one `dirname` gave while these lines sat in
# `pipeline_video.py`. From this sub-package one `dirname` would give
# `zyg_workflows/video_stages/`, so `_PKG_DIR` takes one more.
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def prepare_vram_and_services(ctx):
    _log = ctx._log
    _set_stage = ctx._set_stage
    job = ctx.job
    n_scenes = ctx.n_scenes
    scene_duration = ctx.scene_duration
    # `_wan_n_chained` / `_wan_test_frames` / `_wan_test_steps` are bound
    # inside the `try:` below, beside the `_wan_svc` import. When that
    # import raises, the monolith left all four names to the handler, which
    # sets `_wan_svc = None` — and every reader of the other three sits
    # behind `if _wan_svc:`, so an unbound local was never reached. This
    # function has to *return* them, so they start as the `None` the caller
    # then never looks at.
    _wan_n_chained = _wan_test_frames = _wan_test_steps = None

    _set_stage('Video Generation')
    _log('INFO', 'Stage 4', f'Generating {n_scenes} WAN video clips…')

    import sys as _sys_v
    import json as _json_v

    _crews_dir_v = _PKG_DIR
    if _crews_dir_v not in _sys_v.path:
        _sys_v.path.insert(0, _crews_dir_v)

    # ── Pre-WAN VRAM check — WAN needs ~35 GB free (28 GB model + 5 GB buffers + headroom) ──
    _release_pipeline_vram('pre-WAN', lambda m: _log('INFO', 'Stage 4', m))
    try:
        import torch as _t_vram_chk
        import gc as _gc_vram_chk
        import subprocess as _sp_vram

        # ── Step 1: Kill competing VRAM users (gabi-gabi / other non-pipeline processes) ──
        _own_pid = os.getpid()
        try:
            _apps_raw = _sp_vram.run(
                [exe('nvidia-smi'), '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
                capture_output=True,
                timeout=10,
                text=True,
            )
            # Same ComfyUI-exempt logic as the Stage 0 sweep.
            _comfy_exempt_pid = None
            if os.environ.get('ZYG_USE_COMFYUI', '').strip().lower() in ('1', 'true', 'yes', 'on'):
                try:
                    _pg = _sp_vram.run(
                        ['pgrep', '-f', 'ai-models/comfyui/.venv/bin/python main.py'],
                        capture_output=True,
                        timeout=5,
                        text=True,
                    )
                    _pids = [int(x) for x in _pg.stdout.split() if x.strip().isdigit()]
                    if _pids:
                        _comfy_exempt_pid = _pids[0]
                except Exception as _exc:
                    _zyg_log.warning('comfy PID probe failed, the VRAM sweep has no exemption: %s', _exc)
            _competing_mb = 0
            _killed_pids = []
            for _line in _apps_raw.stdout.strip().splitlines():
                _parts = [p.strip() for p in _line.split(',')]
                if len(_parts) != 2:
                    continue
                try:
                    _comp_pid = int(_parts[0])
                    _comp_mb = int(_parts[1])
                except ValueError as _exc:
                    _zyg_log.debug('unparseable nvidia-smi app line skipped: %s', _exc)
                    continue
                if _comp_pid == _own_pid:
                    continue  # skip our own process
                if _comp_pid == _comfy_exempt_pid:
                    _log(
                        'INFO',
                        'Stage 4',
                        f'Keeping ComfyUI server PID {_comp_pid} ({_comp_mb} MiB) — needed for ZYG_USE_COMFYUI',
                    )
                    continue
                _competing_mb += _comp_mb
                _log(
                    'WARNING',
                    'Stage 4',
                    f'Competing VRAM user detected: PID {_comp_pid} using {_comp_mb} MiB — terminating',
                )
                try:
                    os.kill(_comp_pid, 15)  # SIGTERM first
                    import time as _t_sig

                    _t_sig.sleep(2)
                    try:
                        os.kill(_comp_pid, 0)  # check still alive
                        os.kill(_comp_pid, 9)  # SIGKILL if SIGTERM didn't work
                        _t_sig.sleep(1)
                    except ProcessLookupError as _exc:
                        _zyg_log.debug('PID %s already gone after SIGTERM: %s', _comp_pid, _exc)
                    _killed_pids.append(_comp_pid)
                except (ProcessLookupError, PermissionError) as _kill_e:
                    _log('WARNING', 'Stage 4', f'Could not kill PID {_comp_pid}: {_kill_e}')
            if _killed_pids:
                _log(
                    'INFO',
                    'Stage 4',
                    f'Freed ~{_competing_mb} MiB from {len(_killed_pids)} competing process(es): {_killed_pids}',
                )
                import time as _t_gc2

                _t_gc2.sleep(3)  # let CUDA driver reclaim
        except Exception as _comp_e:
            _log('WARNING', 'Stage 4', f'Competing VRAM scan failed: {_comp_e}')

        # ── Step 2: PyTorch cache flush ───────────────────────────────────
        _gc_vram_chk.collect()
        _t_vram_chk.cuda.empty_cache()

        _vfree = _t_vram_chk.cuda.mem_get_info()[0] / 1024**3
        _log('INFO', 'Stage 4', f'VRAM free before WAN: {_vfree:.1f} GB (need ~35 GB)')
        if _vfree < 35.0:
            _log('WARNING', 'Stage 4', f'Low VRAM ({_vfree:.1f} GB) — forcing aggressive cleanup…')
            _gc_vram_chk.collect()
            _t_vram_chk.cuda.empty_cache()
            import time as _t_vwait

            _t_vwait.sleep(6)
            _gc_vram_chk.collect()
            _t_vram_chk.cuda.empty_cache()
            _vfree = _t_vram_chk.cuda.mem_get_info()[0] / 1024**3
            _log('INFO', 'Stage 4', f'VRAM after cleanup: {_vfree:.1f} GB')
    except Exception as _vram_chk_e:
        _log('WARNING', 'Stage 4', f'VRAM check failed: {_vram_chk_e}')
        _vfree = 99.0  # assume OK if check fails
    try:
        from zyg_workflows import wan_video_service as _wan_svc

        _po_pv = job.get('pipeline_options') or {}
        _test_scene = bool(_po_pv.get('test_scene'))
        # ~5s TEST render: one native sub-clip (~81f@17fps ≈ 4.8s), fewer steps.
        _wan_n_chained = 1 if _test_scene else _wan_svc.n_chained_for_scene_duration(scene_duration)
        _wan_test_frames = 81 if _test_scene else None
        _wan_test_steps = 12 if _test_scene else None
        _wan_via_comfy = False
        try:
            from zyg_workflows import _comfy_client as _cc_wan_gate

            _wan_via_comfy = _cc_wan_gate.is_enabled() and _cc_wan_gate.server_reachable()
        except ImportError as _exc:
            _zyg_log.debug('comfy client unavailable for the WAN gate: %s', _exc)
        if not _wan_via_comfy:
            try:
                from zyg_workflows import comfy_generation_service as _cgs_wan_gate

                _wan_via_comfy = _cgs_wan_gate.is_available()
            except ImportError as _exc:
                _zyg_log.debug('comfy_generation_service unavailable for the WAN gate: %s', _exc)
        if _vfree < 32.0 and not _wan_via_comfy:
            _log(
                'WARNING',
                'Stage 4',
                f'Skipping WAN — only {_vfree:.1f} GB free after cleanup, need 32 GB; using static images',
            )
            job.setdefault('warnings', []).append(
                f'⚠️ WAN skipped — insufficient VRAM ({_vfree:.1f} GB free, need 32 GB). '
                'Static image fallback used — video will show still frames.'
            )
            job['wan_fallback'] = True
            _wan_svc = None
        elif _vfree < 32.0 and _wan_via_comfy:
            _log(
                'INFO',
                'Stage 4',
                f'Low free VRAM ({_vfree:.1f} GB) but ComfyUI primary — WAN will run on Comfy server',
            )
    except ImportError as _wan_imp_err:
        _log('WARNING', 'Stage 4', f'wan_video_service import failed: {_wan_imp_err}')
        _wan_svc = None

    # ── Load audio_service for foley SFX + BGM ───────────────────────────
    try:
        from zyg_workflows import audio_service as _audio_svc

        _log('INFO', 'Stage 4', 'Audio service loaded (foley SFX + BGM enabled)')
    except ImportError as _asvc_e:
        _log('WARNING', 'Stage 4', f'audio_service unavailable: {_asvc_e} — no foley/BGM')
        _audio_svc = None

    return _wan_svc, _audio_svc, _json_v, _wan_n_chained, _wan_test_frames, _wan_test_steps
