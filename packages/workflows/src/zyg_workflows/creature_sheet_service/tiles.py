# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""After the run: the training tiles and a re-judge of a finished sheet."""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Callable

from zyg_workflows import creature_judge as _cj

from .base import (
    ANGLES,
    LOCKED_VIEW_EXEMPT,
    SHEET_FILENAME,
    SOFT_FLAGS,
    _split_flags,
    caption_mode,
    load_report,
    report_path,
    sheet_dir,
    sheet_path,
)
from .images import make_strip, stitch_sheet

import logging as _zyg_logging

# Channel kept from the pre-split module. Re-bound by ASSIGNMENT (not ``from .base
# import``) so the moved call sites keep their original method-call bytecode; it is
# the same logger object either way.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.creature_sheet_service')


def training_tiles(
    report: dict, dataset_dir: str, trigger: str, brief: dict, log_fn: Callable[[str], None] | None = None
) -> list[str]:
    """Copy PASSING cells + every reference into <dataset>/training/ with captions.

    Returns the list of image paths written. Excluded cells never train."""
    log = log_fn or (lambda _m: None)
    tdir = os.path.join(dataset_dir, 'training')
    os.makedirs(tdir, exist_ok=True)
    for f in os.listdir(tdir):
        if f.endswith(('.png', '.jpg', '.jpeg', '.txt')):
            try:
                os.remove(os.path.join(tdir, f))
            except OSError as _exc:
                _zyg_log.warning('stale training file removal failed, it may still be trained on: %s', _exc)
    desc = (brief.get('description') or brief.get('visual_traits') or 'creature').strip().rstrip('.')
    species = (brief.get('species') or 'creature').strip()
    style = (brief.get('style_hint') or '').strip()
    # the body plan is in every caption so the LoRA binds the words to the pixels
    bp = (brief.get('body_plan') or '').strip().rstrip('.')
    written: list[str] = []

    def _write(src: str, stem: str, view: str) -> None:
        dst = os.path.join(tdir, f'{stem}.png')
        shutil.copy2(src, dst)
        parts = [trigger, desc] + ([bp] if bp else []) + [species, view]
        if style:
            parts.append(style)
        parts.append('single creature, clean background, high quality reference')
        with open(os.path.join(tdir, f'{stem}.txt'), 'w', encoding='utf-8') as fh:
            fh.write(', '.join(p for p in parts if p))
        written.append(dst)

    for c in report.get('cells', []):
        if c.get('ok') and c.get('path') and os.path.isfile(c['path']):
            mode = c.get('caption_mode') or caption_mode(c)
            view = c.get('label', '')
            if mode in ('neutral', 'neutral_partial'):
                view = 'alternate view of the creature'
            if mode in ('partial', 'neutral_partial'):
                view += ', partial view, cropped framing'
            _write(c['path'], f'sheet_{int(c["idx"]):02d}', view)
    for i, r in enumerate(report.get('refs', [])):
        p = r.get('path')
        if p and os.path.isfile(p):
            view = 'reference view' if not r.get('whole_body') else 'reference view, whole body'
            _write(p, f'reference_{i:02d}', view)
    log(f'training set: {len(written)} tiles → {tdir}')
    return written


def reclassify(dataset_dir: str, *, rejudge_hard: bool = True, log_fn: Callable[[str], None] | None = None) -> dict:
    """Re-apply the pass/soft/exclude policy to a finished sheet WITHOUT
    re-rendering: cells keep their stored verdicts; cells whose only hard flag
    is a vlm identity check are re-judged with the band-aware question set
    (a back view was being asked about eyes). Rewrites sheet.png + sheet.json."""
    log = log_fn or (lambda _m: None)
    report = load_report(dataset_dir)
    cells = report.get('cells') or []
    if not cells:
        raise RuntimeError('no sheet.json to reclassify')
    sdir = sheet_dir(dataset_dir)
    plan = {a['id']: a for a in ANGLES}
    anchor_ref = ((report.get('anchors') or {}).get('identity') or {}).get('path')
    base = _cj.load_items(_cj.CELL_CHECKLIST)
    rejudge = []
    for c in cells:
        hard, soft = _split_flags(c.get('reasons') or [])
        soft = list(dict.fromkeys(soft + [x for x in (c.get('soft') or [])]))
        if c.get('locked_view'):
            soft = [x for x in soft if x[4:] not in LOCKED_VIEW_EXEMPT]
        c['reasons'], c['soft'] = hard, soft
        c['ok'] = not hard
        c['caption_mode'] = caption_mode(c)
        if rejudge_hard and any(x.startswith('vlm:') for x in hard) and c.get('path') and anchor_ref:
            rejudge.append(c)
    if rejudge:
        jobs = []
        for c in rejudge:
            a = plan.get(c['id']) or {}
            sp = os.path.join(sdir, 'strips', f'{os.path.splitext(os.path.basename(c["path"]))[0]}_rejudge.png')
            make_strip(anchor_ref, c['path'], sp)
            jobs.append(
                {
                    'key': str(id(c)),
                    'image': sp,
                    'items': _cj.cell_items(
                        a.get('desc', ''),
                        kind=a.get('kind', 'body'),
                        band=a.get('band'),
                        base=base,
                        body_plan=(report.get('brief') or {}).get('body_plan') or '',
                    ),
                    'preamble': base.get('preamble', ''),
                }
            )
        vs = _cj.judge_batch(jobs, offload=True, log_fn=log)
        for c in rejudge:
            v = vs.get(str(id(c)))
            if not v or not v.get('judged'):
                continue
            c['reasons'] = [x for x in c['reasons'] if not x.startswith('vlm:')]
            c['soft'] = [x for x in c['soft'] if not x.startswith('vlm:')]
            for f in v.get('criticals', []) + v.get('majors', []):
                (c['soft'] if f in SOFT_FLAGS else c['reasons']).append(f'vlm:{f}')
            c['verdicts'] = v.get('verdicts', [])
            c['rejudged'] = True
            c['ok'] = not c['reasons']
            c['caption_mode'] = caption_mode(c)
            log(f'cell {c["idx"]:02d} re-judged: ' + ('ok' if c['ok'] else 'still ' + ','.join(c['reasons'])))
        _cj.shutdown(log_fn=log)
    n_ok = sum(1 for c in cells if c['ok'])
    n_soft = sum(1 for c in cells if c['ok'] and c.get('soft'))
    brief = report.get('brief') or {}
    title = (
        f'{brief.get("name") or "creature"} — {n_ok}/{len(cells)} cells train'
        + (f' ({n_soft} with neutral/partial captions)' if n_soft else '')
        + f' — {report.get("source", "")}'
    )
    out = sheet_path(dataset_dir)
    stitch_sheet(cells, out, title=title, judge_note='' if report.get('judged_any') else 'JUDGE OFFLINE')
    shutil.copy2(out, os.path.join(dataset_dir, SHEET_FILENAME))
    report.update(
        {
            'cells': cells,
            'pass_count': n_ok,
            'soft_count': n_soft,
            'pass_rate': round(n_ok / max(1, len(cells)), 3),
            'reclassified': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
    )
    with open(report_path(dataset_dir), 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=2, default=str)
    for c in cells:
        try:
            with open(os.path.join(sdir, 'cells', f'cell_{int(c["idx"]):02d}.json'), 'w', encoding='utf-8') as fh:
                json.dump(c, fh, default=str)
        except Exception as _exc:
            _zyg_log.warning('cell record write failed, the report on disk stays authoritative: %s', _exc)
    log(f'reclassified: {n_ok}/{len(cells)} train ({n_soft} soft) → {out}')
    return report
