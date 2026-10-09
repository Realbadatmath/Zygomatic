# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages analyze_render() walks, and the small records it carries between them.

Extracted from entry.py (2026-10-09) to bring analyze_render under the 300-line
function cap: it was 313 lines of straight-line orchestration. Each stage here is
the same code, with its implicit locals turned into explicit parameters and its
results into the three dataclasses below. The import direction is one-way —
entry.py imports this module, never the other way round.
"""

import json
import os
import time
import logging as _zyg_logging
from dataclasses import dataclass

from zyg_workflows.vlm_report.constants import GROUND_PROMPTS, PERSON_FALLBACK
from zyg_workflows.vlm_report.inspection import _run_inspection
from zyg_workflows.vlm_report.markdown_report import _write_markdown
from zyg_workflows.vlm_report.synthesis import _run_synthesis, _synthesis_prompt
from zyg_workflows.vlm_report.targets import (
    _ground_targets,
    _hand_side_targets,
    _merge_targets,
    _pin_targets,
)
from zyg_workflows.vlm_report.util import _default_times, _probe

# the channel the extracted code logged on while it lived in entry.py
_zyg_log = _zyg_logging.getLogger('zyg_workflows.vlm_report')


@dataclass
class _RunPaths:
    """Where one analyze_render run reads from and writes to.

    Built by _prepare_run once the clip is known to exist: every directory in it
    already exists on disk by then.
    """

    clip_path: str
    stem: str
    out_dir: str
    crops_dir: str
    work_dir: str
    run_id: str
    scene_key: str


@dataclass
class _ClipInfo:
    """The clip's geometry plus the timestamps that will be sampled from it."""

    w: int
    h: int
    fps: float
    dur: float
    times: list


@dataclass
class _Judging:
    """What the per-crop VLM judging round produced.

    results/localized are the screen and localization verdicts, n_calls the
    number of worker runs, and model/tier what actually answered (the requested
    tier can fall back).
    """

    results: list
    localized: list
    n_calls: int
    model: str
    tier: str


def _prepare_run(clip_path, out_dir, run_id):
    """Resolve and create the output tree for one clip. Returns a _RunPaths.

    clip_path must already exist. out_dir defaults to a `vlm_report_<stem>`
    sibling of the clip, run_id to `vlmrep_<stem>_<timestamp>`, and the scene key
    to the clip's parent directory name (the stem when it has none).
    """
    clip_path = os.path.abspath(clip_path)
    stem = os.path.splitext(os.path.basename(clip_path))[0]
    out_dir = os.path.abspath(out_dir or os.path.join(os.path.dirname(clip_path), f'vlm_report_{stem}'))
    crops_dir = os.path.join(out_dir, 'crops')
    work_dir = os.path.join(out_dir, '_work')
    for d in (out_dir, crops_dir, work_dir):
        os.makedirs(d, exist_ok=True)
    run_id = run_id or f'vlmrep_{stem}_{time.strftime("%Y%m%d_%H%M%S")}'
    scene_key = os.path.basename(os.path.dirname(clip_path)) or stem
    return _RunPaths(clip_path, stem, out_dir, crops_dir, work_dir, run_id, scene_key)


def _load_metadata(shot_metadata_path, clip_path, log):
    """Read shot_metadata.json (authored pins/boxes/beats) for a clip.

    shot_metadata_path None -> a `shot_metadata.json` sibling of the clip when
    there is one. Returns the parsed dict, or {} when there is no readable file:
    the run continues without pins rather than failing.
    """
    if shot_metadata_path is None:
        cand = os.path.join(os.path.dirname(clip_path), 'shot_metadata.json')
        shot_metadata_path = cand if os.path.isfile(cand) else None
    meta = {}
    if shot_metadata_path and os.path.isfile(shot_metadata_path):
        try:
            with open(shot_metadata_path, encoding='utf-8') as f:
                meta = json.load(f) or {}
        except Exception as e:
            log(f'shot_metadata unreadable ({e}) — continuing without pins')
    log(f'metadata keys: {sorted(meta)}')
    return meta


def _clip_info(clip_path, meta, beat_times, log):
    """Probe the clip and decide which timestamps to sample. Returns a _ClipInfo.

    Explicit beat_times win (rounded to 2 dp); otherwise the authored beats plus
    whole-clip coverage, per _default_times.
    """
    w, h, fps, dur = _probe(clip_path)
    log(f'clip: {w}x{h} @ {fps:.2f} fps, {dur:.2f}s')
    times = [round(float(t), 2) for t in beat_times] if beat_times else _default_times(meta, dur)
    log(f'sample times: {times}')
    return _ClipInfo(w, h, fps, dur, times)


def _resolve_targets(clip_path, meta, char_regions, ground, times, w, h, log):
    """Decide the inspection regions for a clip. Returns {name: target}.

    Pins FIRST: they are the authored intent and they are what anchors the
    detector's candidate choice (see ROLE_PIN_ANCHOR). People come from the
    caller when given, otherwise from the detector, and from a documented
    half-frame default when neither found them (a missing person box would
    otherwise silently disable every person-scoped CRITICAL check). Hand-side
    targets are derived last, from the per-frame hand boxes.
    """
    pins = _pin_targets(meta, char_regions, log)
    do_ground = os.environ.get('ZYG_VLM_REPORT_GROUND', '1') != '0' if ground is None else bool(ground)
    grounded = _ground_targets(clip_path, times, log, pins=pins) if do_ground else {}
    hands_per_t = grounded.pop('_hands_per_t', {})
    for role in ('man', 'boy'):
        if role in pins:
            grounded.pop(role, None)
            continue
        if role in grounded:
            pins[role] = grounded.pop(role)
        else:
            pins[role] = {
                'name': role,
                'box_frac': list(PERSON_FALLBACK[role]),
                'source': 'fallback',
                'per_frame': {},
                'note': 'GroundingDINO did not return a plausible '
                f'"{GROUND_PROMPTS[role]}" box — using the '
                'authored left/right half-frame default '
                '(crops are LOOSER than normal here)',
            }
            log(f'{role}: no usable detection — half-frame fallback {PERSON_FALLBACK[role]}')
    targets = _merge_targets(pins, grounded, w, h, log)
    targets.update(
        _hand_side_targets(
            hands_per_t, targets.get('man', {}).get('box_frac'), targets.get('boy', {}).get('box_frac'), log
        )
    )
    log('targets: ' + ', '.join(f'{k}[{v["source"]}]{v["box_frac"]}' for k, v in sorted(targets.items())))
    return targets


def _judge_crops(VLM, targets, checklist, cl_doc, inspect_tier, k_critical, refs, work_dir, log, log_fn):
    """Run the per-crop binary judging round. Returns a _Judging.

    The requested inspect_tier can fall back, so the model and tier reported are
    the first ones the workers actually answered on.
    """
    vlm_results, localized, n_calls = _run_inspection(
        VLM, targets, checklist, cl_doc, inspect_tier, k_critical, refs, work_dir, log, log_fn
    )
    inspect_model = next((r.get('model') for r in vlm_results if r.get('model')), VLM.model_for(inspect_tier))
    inspect_tier_real = next((r.get('tier') for r in vlm_results if r.get('tier')), inspect_tier)
    log(
        f'inspection: {len(vlm_results)} screen verdicts, {len(localized)} '
        f'localization verdicts, {n_calls} worker runs on {inspect_model}'
    )
    return _Judging(vlm_results, localized, n_calls, inspect_model, inspect_tier_real)


def _tier_note(judging, k_critical):
    """The sentence that tells the synthesis LLM how the crops were judged."""
    return (
        f'The judging tier was `{judging.tier}` '
        f'({judging.model}); critical items were asked '
        f'{k_critical} times and majority-voted.'
    )


def _synthesise(
    out_dir,
    clip_path,
    meta,
    preamble,
    findings,
    pixel,
    prior,
    targets,
    n_crops,
    dur,
    tier_note,
    tier,
    log,
    log_fn,
    offload,
):
    """Write the synthesis prompt beside the report and have the LLM answer it.

    Returns _run_synthesis's dict ({'text','model','tier','seconds',...}). A
    prompt that cannot be saved is only a warning — the run still synthesises.
    """
    prompt = _synthesis_prompt(clip_path, meta, preamble, findings, pixel, prior, targets, n_crops, dur, tier_note)
    try:
        with open(os.path.join(out_dir, 'synthesis_prompt.txt'), 'w', encoding='utf-8') as f:
            f.write(prompt)
    except OSError as _exc:
        _zyg_log.warning('synthesis_prompt.txt not written: %s', _exc)
    return _run_synthesis(prompt, tier, out_dir, log, log_fn, offload=offload)


def _report_context(
    clip_path,
    run_id,
    info,
    judging,
    targets,
    n_crops,
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
):
    """The context dict _write_markdown renders DEFECT_REPORT.md from."""
    return {
        'clip': clip_path,
        'findings': findings,
        'verdict': verdict,
        'synth_text': synth.get('text'),
        'synth_error': synth.get('error'),
        'synth_model': synth.get('model'),
        'synth_tier': synth.get('tier'),
        'synth_seconds': synth.get('seconds'),
        'fell_back': synth.get('fell_back'),
        'synth_peak_gb': synth.get('peak_vram_gb'),
        'requested_tier': tier,
        'inspect_tier': judging.tier,
        'inspect_model': judging.model,
        'n_vlm_calls': judging.n_calls,
        'k_critical': k_critical,
        'targets': targets,
        'n_crops': n_crops,
        'times': info.times,
        'w': info.w,
        'h': info.h,
        'fps': info.fps,
        'dur': info.dur,
        'pixel': pixel,
        'prior': prior,
        'run_id': run_id,
        'ledger_rows': ledger_rows,
        'lesson_rows': lesson_rows,
        'peak_vram_mb': peak_mb,
        'elapsed_s': elapsed,
    }


def _raw_record(
    clip_path,
    run_id,
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
    k_critical,
    ledger_rows,
    lesson_rows,
    peak_mb,
    elapsed,
):
    """The machine-readable twin of the report, written as defect_report.json."""
    return {
        'run_id': run_id,
        'clip': clip_path,
        'verdict': verdict,
        'ok': True,
        'elapsed_s': elapsed,
        'peak_vram_mb': peak_mb,
        'clip_info': {'w': info.w, 'h': info.h, 'fps': info.fps, 'duration_s': info.dur},
        'sample_times': info.times,
        'checklist': checklist,
        'targets': targets,
        'crops': crops,
        'vlm': {
            'tier': judging.tier,
            'model': judging.model,
            'worker_runs': judging.n_calls,
            'k_critical': k_critical,
            'k_method': 'inspect_frames(k=N) repeats the worker and '
            'majority-votes; the worker CLI --k flag is not '
            'forwarded by vlm_inspector',
            'screen': judging.results,
            'localize': judging.localized,
        },
        'pixel': pixel,
        'findings': findings,
        'prior': prior,
        'synthesis': {k: v for k, v in synth.items() if k != 'text'},
        'synthesis_text': synth.get('text'),
        'ledger_rows': ledger_rows,
        'lesson_rows': lesson_rows,
    }


def _write_reports(
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
):
    """Emit the two report artefacts. Returns (markdown path, json path).

    The markdown report is the deliverable; the json path is None when the raw
    record could not be written, which is logged and otherwise survivable.
    """
    md = _write_markdown(
        os.path.join(paths.out_dir, 'DEFECT_REPORT.md'),
        _report_context(
            paths.clip_path,
            paths.run_id,
            info,
            judging,
            targets,
            len(crops),
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
        ),
    )
    raw = _raw_record(
        paths.clip_path,
        paths.run_id,
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
        k_critical,
        ledger_rows,
        lesson_rows,
        peak_mb,
        elapsed,
    )
    rj = os.path.join(paths.out_dir, 'defect_report.json')
    try:
        with open(rj, 'w', encoding='utf-8') as f:
            json.dump(raw, f, indent=1, default=str)
    except Exception as e:
        log(f'could not write raw json ({e})')
        rj = None
    return md, rj


def _record_ledger(VLM, judging, synth, run_id, elapsed, peak_mb):
    """Record this run as a run_ledger stage. A ledger that refuses is a warning."""
    try:
        from zyg_workflows import run_ledger

        run_ledger.record_stage(
            'vlm_report',
            run_id=run_id,
            device=VLM.TIERS.get(judging.tier, {}).get('device'),
            model_id=f'{judging.model} + {synth.get("model")}',
            wall_s=elapsed,
            vram_peak_mb=peak_mb,
            fallback_taken=synth.get('fell_back'),
        )
    except Exception as _exc:
        _zyg_log.warning('run ledger stage not recorded: %s', _exc)
