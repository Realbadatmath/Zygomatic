# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`main()` — mode selection, the A/B sweep and the JSON report."""

from __future__ import annotations

from .bench_assets import (
    Any,
    BENCH_SLOTS,
    _CFG,
    _CREWS,
    _H,
    _OUT_ROOT,
    _PARITY,
    _PERSISTENT,
    _REALISTIC,
    _REALISTIC_IMAGES,
    _REALISTIC_N_PIPELINES,
    _REALISTIC_PRE_FLUX_S,
    _REALISTIC_STAGGER_S,
    _STEPS,
    _W,
    _find_bench_reference,
    _gpu_exclusivity_sweep,
    _load_bench_bible,
    _log,
    _resolve_bench_char_id,
    _stage_pose_image,
    datetime,
    json,
    os,
    time,
    timezone,
    traceback,
)
from .concurrency import _run_persistent_worker, _run_realistic_concurrent
from .slots import _load_diffusers_stack, _run_comfy_slot, _run_diffusers_slot, _summarize_rows, _teardown_diffusers


def main() -> int:
    # ── Mode 3: Realistic Concurrent ──────────────────────────────────────────
    if _REALISTIC or _PERSISTENT:
        ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        run_dir = _OUT_ROOT / ts
        run_dir.mkdir(parents=True, exist_ok=True)

        # Modes 3 and 4 always use production-parity character bible + pose.
        char_id = _resolve_bench_char_id(None)
        pose_ref = _find_bench_reference(char_id)
        pkg, char_id = _load_bench_bible(char_id)
        pose_skeleton = _stage_pose_image(pose_ref, run_dir)
        if not pkg:
            _log('FATAL: realistic/persistent mode requires a loadable character bible')
            return 2
        if not pose_skeleton:
            _log('FATAL: realistic/persistent mode requires a staged pose skeleton')
            return 2

        _log(
            f'Realistic benchmark: n_pipelines={_REALISTIC_N_PIPELINES} '
            f'stagger={_REALISTIC_STAGGER_S}s '
            f'images/pipeline={_REALISTIC_IMAGES} '
            f'pre_flux_s={_REALISTIC_PRE_FLUX_S}s '
            f'char={char_id}'
        )

        report: dict[str, Any] = {
            'timestamp': ts,
            'mode': 'persistent_worker' if _PERSISTENT else 'realistic_concurrent',
            'hardware_note': 'single-GPU concurrent threads',
            'settings': {
                'steps': _STEPS,
                'cfg': _CFG,
                'size': f'{_W}x{_H}',
                'n_pipelines': _REALISTIC_N_PIPELINES,
                'stagger_s': _REALISTIC_STAGGER_S,
                'images_per_pipeline': _REALISTIC_IMAGES,
                'pre_flux_s': _REALISTIC_PRE_FLUX_S,
            },
            'telemetry_source': {
                'file': 'benchmark_telemetry.json',
                'sample_pipelines': 12,
                'pre_flux_s_derivation': ('research(4s) + script(88s) + visual_tagging(21s) + emotion(5s)'),
                'images_derivation': '328 total FLUX images / ~12 pipelines = 27.3 → 28',
            },
            'char_id': char_id or None,
            'pose_reference': pose_ref,
            'pose_skeleton': pose_skeleton,
        }

        _gpu_exclusivity_sweep()

        kwargs = dict(
            n_pipelines=_REALISTIC_N_PIPELINES,
            stagger_s=_REALISTIC_STAGGER_S,
            images_per_pipeline=_REALISTIC_IMAGES,
            pre_flux_s=_REALISTIC_PRE_FLUX_S,
            char_id=char_id,
            pose_ref=pose_ref,
            pose_skeleton=pose_skeleton,
            run_dir=run_dir,
            pkg=pkg,
        )

        if _PERSISTENT:
            result = _run_persistent_worker(**kwargs)
        else:
            result = _run_realistic_concurrent(**kwargs)

        report['result'] = result

        # Comparative summary printed to stdout
        summary: dict[str, Any] = {
            'report': str(_CREWS / 'data' / 'runtime' / f'scholarly_flux_ab_{ts}.json'),
            'mode': report['mode'],
            'n_pipelines': _REALISTIC_N_PIPELINES,
            'stagger_s': _REALISTIC_STAGGER_S,
            'pipelines_ok': result.get('pipelines_ok'),
            'pipelines_fail': result.get('pipelines_fail'),
            'batch_total_s': result.get('batch_total_s'),
        }
        if _REALISTIC:
            summary['fragmentation_gb'] = result.get('vram_fragmentation_gb')
            summary['vram_after_teardown_progression'] = result.get('vram_after_teardown_progression_gb')
            summary['lock_wait_s'] = result.get('lock_wait_s')
            summary['pipelines_failed_flux_load'] = result.get('interpretation', {}).get('pipelines_failed_flux_load')
        if _PERSISTENT:
            summary['load_s'] = result.get('load_s')
            summary['teardown_s'] = result.get('teardown_s')
            summary['vram_used_by_model_gb'] = result.get('vram_used_by_model_gb')
            summary['per_image_s_mean'] = (result.get('per_image_s') or {}).get('mean')

        out_json = _CREWS / 'data' / 'runtime' / f'scholarly_flux_ab_{ts}.json'
        out_json.write_text(json.dumps(report, indent=2), encoding='utf-8')
        _log(f'Report: {out_json}')
        print(json.dumps(summary, indent=2))
        return 0

    # ── Modes 1 & 2: existing diffusers / ComfyUI A/B ─────────────────────────
    backends = os.environ.get('ZYG_BENCH_BACKENDS', 'diffusers,comfy').lower().split(',')
    backends = [b.strip() for b in backends if b.strip() in ('diffusers', 'comfy')]

    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    run_dir = _OUT_ROOT / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    char_id = _resolve_bench_char_id(None) if _PARITY else ''
    pose_ref = _find_bench_reference(char_id if _PARITY else None)
    pkg, char_id = _load_bench_bible(char_id) if _PARITY else (None, '')
    pose_skeleton = _stage_pose_image(pose_ref, run_dir) if _PARITY else None
    if _PARITY and not pkg:
        _log('FATAL: parity mode requires a loadable character bible')
        return 2
    if _PARITY and not pose_skeleton:
        _log('FATAL: parity mode requires a staged pose skeleton')
        return 2

    report = {
        'timestamp': ts,
        'mode': 'production_parity' if _PARITY else 'fast_smoke',
        'hardware_note': 'single-GPU sequential',
        'settings': {
            'steps': _STEPS,
            'cfg': _CFG,
            'size': f'{_W}x{_H}',
            'n_slots': len(BENCH_SLOTS),
            'comfy_vram_clear_between_slots': True,
        },
        'pose_reference': pose_ref,
        'pose_skeleton': pose_skeleton,
        'character_bible': bool(pkg),
        'char_id': char_id or None,
        'backends': backends,
        'production_default': f'{__import__("zyg_workflows.scholarly_stills_backend").SCHOLARLY_PRODUCTION_BACKEND} '
        f'(Comfy only via {__import__("zyg_workflows.scholarly_stills_backend").SCHOLARLY_COMFY_CURATION_ENV}=1)',
        'results': {},
    }

    _gpu_exclusivity_sweep()

    if 'diffusers' in backends:
        diff_dir = run_dir / 'diffusers'
        diff_dir.mkdir(exist_ok=True)
        diff_rows: list[dict[str, Any]] = []
        try:
            stack = _load_diffusers_stack(pose_ref, char_id)
            pipe, cn_pipe, cns, neg, cn_scale, anat_suffix, _, pkg_d = stack
            for i, (sid, scene) in enumerate(BENCH_SLOTS):
                out_p = str(diff_dir / f'{sid}.jpg')
                seed = 10_000 + i
                _log(f'diffusers {i + 1}/{len(BENCH_SLOTS)} {sid}')
                row = _run_diffusers_slot(
                    pipe,
                    cn_pipe,
                    cns,
                    neg,
                    cn_scale,
                    anat_suffix,
                    pose_ref,
                    pkg_d,
                    sid,
                    scene,
                    seed,
                    out_p,
                    pose_skeleton=pose_skeleton,
                )
                row['slot'] = sid
                row['seed'] = seed
                diff_rows.append(row)
            _teardown_diffusers(pipe, cn_pipe, cns)
        except Exception as exc:
            report['diffusers_error'] = traceback.format_exc()[-800:]
            _log(f'diffusers bench failed: {exc}')
            diff_rows = []
        if diff_rows:
            report['results']['diffusers'] = _summarize_rows(diff_rows)
        time.sleep(3)
        _gpu_exclusivity_sweep()

    if 'comfy' in backends:
        os.environ.setdefault('ZYG_COMFY_CLEAR_VRAM_BETWEEN_SLOTS', '1')
        comfy_dir = run_dir / 'comfy'
        comfy_dir.mkdir(exist_ok=True)
        comfy_rows: list[dict[str, Any]] = []
        try:
            from zyg_workflows import comfy_generation_service as cgs

            cgs.clear_vram_between_slots(log_fn=_log, label='pre-comfy-leg')
            for i, (sid, scene) in enumerate(BENCH_SLOTS):
                out_p = str(comfy_dir / f'{sid}.jpg')
                seed = 20_000 + i
                _log(f'comfy {i + 1}/{len(BENCH_SLOTS)} {sid}')
                row = _run_comfy_slot(
                    scene,
                    seed,
                    out_p,
                    pose_ref,
                    pose_skeleton,
                    pkg,
                    char_id,
                    run_dir,
                )
                row['slot'] = sid
                row['seed'] = seed
                comfy_rows.append(row)
        except Exception as exc:
            report['comfy_error'] = traceback.format_exc()[-800:]
            _log(f'comfy bench failed: {exc}')
            comfy_rows = []
        if comfy_rows:
            report['results']['comfy'] = _summarize_rows(comfy_rows)

    d_mean = (report['results'].get('diffusers') or {}).get('mean_s')
    c_mean = (report['results'].get('comfy') or {}).get('mean_s')
    if d_mean and c_mean:
        report['winner_mean_s_per_image'] = 'comfy' if c_mean < d_mean else 'diffusers'
        report['speedup_ratio'] = round(max(d_mean, c_mean) / min(d_mean, c_mean), 3)

    out_json = _CREWS / 'data' / 'runtime' / f'scholarly_flux_ab_{ts}.json'
    out_json.write_text(json.dumps(report, indent=2), encoding='utf-8')
    _log(f'Report: {out_json}')
    print(
        json.dumps(
            {
                'report': str(out_json),
                'mode': report['mode'],
                'diffusers_mean_s': d_mean,
                'comfy_mean_s': c_mean,
                'winner': report.get('winner_mean_s_per_image'),
            },
            indent=2,
        )
    )
    return 0
