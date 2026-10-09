# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The public entry point: analyze_render() and the module CLI."""

import json
import os
import sys
import time
import logging as _zyg_logging

from zyg_workflows.vlm_report.constants import _DIR
from zyg_workflows.vlm_report.entry_stages import (
    _clip_info,
    _judge_crops,
    _load_metadata,
    _prepare_run,
    _record_ledger,
    _resolve_targets,
    _write_reports,
    _synthesise,
    _tier_note,
)
from zyg_workflows.vlm_report.fusion import (
    _append_lessons,
    _fuse,
    _ledger_write,
    _prior_context,
    _release_detectors,
    _release_judges,
    _verdict_of,
)
from zyg_workflows.vlm_report.inspection import _checklist_doc, _pixel_metrics
from zyg_workflows.vlm_report.targets import (
    _make_crops,
)
from zyg_workflows.vlm_report.util import _VramWatch, _decode_times, _mklog

_zyg_log = _zyg_logging.getLogger('zyg_workflows.vlm_report')

# ── the public entry point ───────────────────────────────────────────────────


def analyze_render(
    clip_path,
    shot_metadata_path=None,
    out_dir=None,
    char_regions=None,
    checklist='scene20_binary',
    tier='boundary',
    beat_times=None,
    k_critical=3,
    log_fn=None,
    inspect_tier='resident',
    ref_images=None,
    ground=None,
    continuity=None,
    n_people=2,
    run_id=None,
    offload=True,
):
    """Analyse a finished render and report what is wrong — no human in the loop.

    clip_path          the delivered video to diagnose.
    shot_metadata_path shot_metadata.json (authored pins/boxes/beats). Defaults to
                       a sibling of the clip.
    out_dir            where crops/, DEFECT_REPORT.md and the raw JSON land.
                       Defaults to <clip dir>/vlm_report_<clip stem>.
    char_regions       {name: (fx0,fy0,fx1,fy1)}; left-most becomes 'man',
                       right-most 'boy'. Omitted -> GroundingDINO locates them.
    checklist          name in config/vlm_checklists.json.
    tier               tier for the FINAL SYNTHESIS ('boundary' = 32B FP8, taken
                       behind comfy_offload.gpu_exclusive). Falls back down the
                       tier ladder when it will not fit, and says so.
    inspect_tier       tier for the per-crop binary judging ('resident' = 8B FP8,
                       the tier the crop rule was validated on).
    beat_times         explicit sample timestamps; None -> authored beats plus
                       whole-clip coverage.
    k_critical         majority-vote repeats for CRITICAL checklist items.
    ground             None -> auto (GroundingDINO when installed).
    continuity         None -> env ZYG_VLM_REPORT_CONTINUITY; True adds
                       continuity_qc.analyze_clip (SAM2+DINOv2, minutes).

    Returns {'ok','verdict','findings','report_md','report_json','crops_dir',
    'model','elapsed_s', ...}. Never raises: on failure it returns ok=False with
    an 'error' and whatever partial evidence survived.
    """
    log = _mklog(log_fn)
    t_start = time.time()
    vram = _VramWatch().start()
    out = {
        'ok': False,
        'verdict': 'UNKNOWN',
        'findings': [],
        'report_md': None,
        'report_json': None,
        'crops_dir': None,
        'model': None,
        'elapsed_s': 0.0,
    }
    try:
        if not (clip_path and os.path.isfile(clip_path)):
            out['error'] = f'clip not found: {clip_path}'
            return out
        paths = _prepare_run(clip_path, out_dir, run_id)
        clip_path, out_dir, run_id = paths.clip_path, paths.out_dir, paths.run_id
        out['crops_dir'] = paths.crops_dir
        log(f'run_id={run_id} scene={paths.scene_key} out={out_dir}')

        meta = _load_metadata(shot_metadata_path, clip_path, log)
        info = _clip_info(clip_path, meta, beat_times, log)

        # ---- 1. targets ----------------------------------------------------
        frames_by_t = _decode_times(clip_path, info.times, log)
        if not frames_by_t:
            out['error'] = 'no frames could be decoded from the clip'
            return out
        info.times = sorted(frames_by_t.keys())

        targets = _resolve_targets(clip_path, meta, char_regions, ground, info.times, info.w, info.h, log)
        crops = _make_crops(targets, frames_by_t, paths.crops_dir, log)
        if not crops:
            out['error'] = 'no crops could be derived'
            return out

        # ---- 2. inspection --------------------------------------------------
        cl_doc = _checklist_doc(os.path.join(_DIR, 'config', 'vlm_checklists.json'))
        preamble = ((cl_doc.get('checklists') or {}).get(checklist) or {}).get('preamble', '')
        try:
            from zyg_workflows import vlm_inspector as VLM
        except Exception as e:
            out['error'] = f'vlm_inspector unavailable: {e}'
            return out
        refs = [p for p in (ref_images or []) if p and os.path.isfile(p)]

        judging = _judge_crops(
            VLM, targets, checklist, cl_doc, inspect_tier, k_critical, refs, paths.work_dir, log, log_fn
        )

        # ---- 3. pixel metrics ------------------------------------------------
        run_cont = os.environ.get('ZYG_VLM_REPORT_CONTINUITY', '0') == '1' if continuity is None else bool(continuity)
        pixel = _pixel_metrics(clip_path, targets, meta, info.dur, n_people, log, log_fn, run_continuity=run_cont)

        # ---- 4. fusion --------------------------------------------------------
        findings = _fuse(judging.results, judging.localized, pixel, targets, log)
        verdict, crit, maj = _verdict_of(findings)
        out['findings'] = findings
        out['verdict'] = verdict

        prior = _prior_context([f'vlm_report:{f["id"]}' for f in findings], paths.scene_key)
        ledger_rows = _ledger_write(run_id, findings, log)

        # ---- 5. the LLM writes the report ------------------------------------
        _release_detectors(log)
        synth = _synthesise(
            out_dir,
            clip_path,
            meta,
            preamble,
            findings,
            pixel,
            prior,
            targets,
            len(crops),
            info.dur,
            _tier_note(judging, k_critical),
            tier,
            log,
            log_fn,
            offload,
        )

        lesson_rows = _append_lessons(paths.scene_key, run_id, clip_path, findings, synth.get('text'))
        peak_mb = vram.stop()

        elapsed = round(time.time() - t_start, 1)
        md, rj = _write_reports(
            paths,
            checklist,
            info,
            judging,
            targets,
            crops,
            findings,
            verdict,
            pixel,
            prior,
            synth,
            tier,
            k_critical,
            ledger_rows,
            lesson_rows,
            peak_mb,
            elapsed,
            log,
        )

        _record_ledger(VLM, judging, synth, run_id, elapsed, peak_mb)

        out.update(
            {
                'ok': True,
                'report_md': md,
                'report_json': rj,
                'model': synth.get('model') or judging.model,
                'elapsed_s': elapsed,
                'peak_vram_mb': peak_mb,
                'run_id': run_id,
                'n_crops': len(crops),
                'synthesis': synth.get('text'),
                'synthesis_meta': {k: v for k, v in synth.items() if k != 'text'},
            }
        )
        log(f'DONE verdict={verdict} findings={len(findings)} ({len(crit)} critical, {len(maj)} major) in {elapsed}s')
        return out
    except Exception as e:
        import traceback

        out['error'] = f'{type(e).__name__}: {e}'
        out['traceback'] = traceback.format_exc()[-2000:]
        out['elapsed_s'] = round(time.time() - t_start, 1)
        try:
            out['peak_vram_mb'] = vram.stop()
        except Exception as _exc:
            _zyg_log.debug('vram sampler stop skipped: %s', _exc)
        _mklog(log_fn)(f'FAILED: {out["error"]}')
        return out
    finally:
        try:
            vram.stop()
        except Exception as _exc:
            _zyg_log.debug('vram sampler stop skipped: %s', _exc)
        _release_judges(_mklog(log_fn))


def _cli(argv):
    import argparse

    ap = argparse.ArgumentParser(description='Autonomous local-LLM defect report for a finished render')
    ap.add_argument('clip')
    ap.add_argument('--meta', default=None, help='shot_metadata.json')
    ap.add_argument('--out', default=None)
    ap.add_argument('--tier', default='boundary', help='synthesis tier')
    ap.add_argument('--inspect-tier', default='resident', help='per-crop judge tier')
    ap.add_argument('--checklist', default='scene20_binary')
    ap.add_argument('--k', type=int, default=3, help='k-ensemble for critical items')
    ap.add_argument('--times', default=None, help='comma-separated sample seconds')
    ap.add_argument('--no-ground', action='store_true')
    ap.add_argument('--continuity', action='store_true')
    ap.add_argument('--refs', nargs='*', default=None)
    a = ap.parse_args(argv)
    times = [float(x) for x in a.times.split(',')] if a.times else None
    res = analyze_render(
        a.clip,
        shot_metadata_path=a.meta,
        out_dir=a.out,
        checklist=a.checklist,
        tier=a.tier,
        inspect_tier=a.inspect_tier,
        beat_times=times,
        k_critical=a.k,
        ground=(not a.no_ground),
        continuity=a.continuity,
        ref_images=a.refs,
        log_fn=lambda m: _zyg_log.info(m),
    )
    _zyg_log.info(
        json.dumps({k: v for k, v in res.items() if k not in ('findings', 'synthesis')}, indent=1, default=str)
    )
    if res.get('report_md'):
        _zyg_log.info(f'\nreport: {res["report_md"]}')
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
