# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The second half of ``build_sheet``: the cells, the semantic judge, regen, the sheet.

Companion of ``build_anchors.py``, which defines :class:`SheetRun` and settles the
anchors these stages rotate every cell from. Extracted 2026-10-09; the stage order, the
log lines and the side effects are those of the 618-line ``build_sheet`` they came from.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Callable

from zyg_workflows import creature_identity as _cid
from zyg_workflows import creature_judge as _cj

from .base import (
    LOCKED_VIEW_EXEMPT,
    MAX_REGEN,
    MAX_REGEN_SOFT,
    SHEET_FILENAME,
    SOFT_FLAGS,
    _file_sig,
    _score_key,
    _text_sig,
    angle_plan,
    caption_mode,
    report_path,
    sheet_path,
    side_instruction,
)
from .build_anchors import SheetRun
from .comfy import _edit
from .images import make_strip, stitch_sheet, structural_check

import logging as _zyg_logging

# Channel kept from the pre-split module. Re-bound by ASSIGNMENT (not ``from .base
# import``) so the moved call sites keep their original method-call bytecode; it is
# the same logger object either way.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.creature_sheet_service')


# ── 3. cells ─────────────────────────────────────────────────────────────


def plan_cells(run: SheetRun) -> None:
    """Settle the angle plan for the preset and whether the identity anchor is a close-up."""
    run.plan = angle_plan(run.preset)
    run.ref_is_closeup = run.source == 'reference' and run.anchor_full != run.anchor_ref


def cell_ckpt(run: SheetRun, idx: int) -> str:
    """Path of the per-cell checkpoint a resumed run reads."""
    return os.path.join(run.sdir, 'cells', f'cell_{idx:02d}.json')


def save_cell(run: SheetRun, rec: dict) -> None:
    """Write one cell's record to its checkpoint; a failed write only costs a re-render."""
    try:
        with open(cell_ckpt(run, int(rec['idx'])), 'w', encoding='utf-8') as fh:
            json.dump(rec, fh, default=str)
    except Exception as _exc:
        _zyg_log.warning('cell checkpoint write failed, a resume will redo this cell: %s', _exc)


def embed_cached(run: SheetRun, p: str) -> Any:
    """The DINO embedding of an image, computed once per run."""
    if not _cid.enabled():
        return None
    if p not in run.emb_cache:
        run.emb_cache[p] = _cid.embed(p)
    return run.emb_cache[p]


def cell_source(run: SheetRun, a: dict) -> tuple[str, str | None, bool]:
    """(source image, instruction or None, is_copy) for an angle."""
    if a.get('anchor'):
        return run.anchor_full, None, True
    side_src = a.get('side_source')
    if side_src and run.anchor_side:
        src = run.anchor_side_mirror if side_src == 'mirror' else run.anchor_side
        instr = side_instruction(a)
        return src, instr, instr is None
    # 2026-08-26. This used to read `a['kind'] == 'head'`, which routed ALL
    # three close-ups through the operator's raw reference whenever that
    # reference was itself a crop. A dolly-in from a crop is safe; an ORBIT
    # from a crop is not — the model must invent whatever the crop cut off.
    # On the Pufferball sheet the crop ended just past a smooth teal stub,
    # so cells 12/13 grew a smooth unbanded tail while every anchor-derived
    # cell carried the banded furry one, and both put it on the SAME side
    # despite opposite rotations. Only ref_source cells may take that risk.
    src = run.anchor_ref if (a.get('ref_source') and run.ref_is_closeup) else run.anchor_full
    return src, a['instruction'], False


def cell_sig(run: SheetRun, a: dict) -> str:
    """What a checkpointed cell was rendered FROM: source pixels + prompt."""
    src, instr, _copy = cell_source(run, a)
    return f'{_file_sig(src)}:{_text_sig((instr or "") + "|" + run.body_plan)}'


def score_identity(run: SheetRun, rec: dict, src: str, dst: str, band: str) -> None:
    """Measure the cell against the anchor it was edited from and record the verdict."""
    d = _cid.similarity_emb(embed_cached(run, src), embed_cached(run, dst)) if _cid.enabled() else None
    dv = _cid.verdict(d, band)
    rec['dino'] = d
    rec['dino_verdict'] = dv
    if dv['measured'] and not dv['hard_ok']:
        rec['reasons'].append(f'identity_lost:{d:.2f}<{_cid.HARD_FLOOR}')
    elif dv['measured'] and not dv['soft_ok']:
        rec['warnings'] = [f'identity_soft:{d:.2f}<{dv["floor"]:.2f}']


def render_cell(run: SheetRun, a: dict, attempt: int) -> dict | None:
    """Render one cell (or copy its locked source) and judge it structurally + on identity.

    Returns the cell record, or None when the renderer produced nothing.
    """
    idx = run.plan.index(a)
    src, instr, is_copy = cell_source(run, a)
    seed = 7000 + idx + attempt * 100_000
    dst = (
        os.path.join(run.sdir, 'cells', f'cell_{idx:02d}.png')
        if attempt == 0
        else os.path.join(run.sdir, 'candidates', f'cell_{idx:02d}_r{attempt}.png')
    )
    if is_copy:
        shutil.copy2(src, dst)
        ok = True
    else:
        ok = _edit(
            src,
            instr,
            dst,
            seed,
            run.log,
            style_hint=run.style_hint,
            body_plan=run.body_plan,
            extra_negative=run.brief_neg,
        )
    if not ok:
        return None
    rec = {
        'idx': idx,
        'id': a['id'],
        'label': a['label'],
        'kind': a['kind'],
        'band': a['band'],
        'path': dst,
        'source_anchor': src,
        'source_sig': cell_sig(run, a),
        'instruction': instr,
        'seed': seed,
        'attempt': attempt,
        'reasons': [],
        'soft': [],
        'ok': True,
        'judged': False,
        'dino': None,
        'caption_mode': 'angle',
    }
    if is_copy and not a.get('anchor'):
        rec['locked_view'] = True  # copy of the operator's side lock (or its mirror)
    st = structural_check(dst, src, expect_change=not is_copy)
    rec['structural'] = st
    rec['reasons'].extend(st['reasons'])
    score_identity(run, rec, src, dst, a['band'])
    rec['ok'] = not rec['reasons']
    return rec


def resume_cell(run: SheetRun, a: dict, idx: int) -> dict | None:
    """A checkpointed cell when its image is there and its source and prompt still match."""
    try:
        if os.path.isfile(cell_ckpt(run, idx)):
            _prev = json.load(open(cell_ckpt(run, idx), encoding='utf-8'))
            if _prev.get('path') and os.path.isfile(_prev['path']) and _prev.get('id') == a['id']:
                if _prev.get('source_sig') == cell_sig(run, a):
                    run.log(f'resume: cell {idx:02d} {a["label"]} reused from checkpoint')
                    return _prev
                run.log(f'resume: cell {idx:02d} {a["label"]} stale (source or prompt changed) — re-rendering')
    except Exception:
        return None
    return None


def failed_cell_record(a: dict, idx: int, anchor_full: str | None) -> dict[str, Any]:
    """The record of a cell whose render produced nothing: on the sheet, marked failed."""
    return {
        'idx': idx,
        'id': a['id'],
        'label': a['label'],
        'kind': a['kind'],
        'band': a['band'],
        'path': None,
        'reasons': ['render_failed'],
        'ok': False,
        'judged': False,
        'dino': None,
        'attempt': 0,
        'seed': 7000 + idx,
        'source_anchor': anchor_full,
    }


def cell_log_line(idx: int, total: int, a: dict, rec: dict) -> str:
    """The progress line one finished cell logs."""
    return (
        f'cell {idx + 1}/{total} {a["label"]}: '
        + ('ok' if rec['ok'] else 'FAIL ' + ','.join(rec['reasons']))
        + (f' dino={rec["dino"]:.2f}' if isinstance(rec.get('dino'), (int, float)) else '')
    )


def render_all_cells(run: SheetRun) -> list[dict[str, Any]]:
    """Render — or resume — every cell of the plan, in plan order."""
    cells: list[dict[str, Any]] = []
    for a in run.plan:
        run.halt()
        idx = run.plan.index(a)
        rec = resume_cell(run, a, idx)
        if rec is None:
            rec = render_cell(run, a, 0)
            if rec is not None:
                save_cell(run, rec)
        if rec is None:
            rec = failed_cell_record(a, idx, run.anchor_full)
        cells.append(rec)
        run.log(cell_log_line(idx, len(run.plan), a, rec))
    return cells


# ── 4. semantic judge (one GPU window for the batch) ─────────────────────


def judge_jobs(run: SheetRun, recs: list[dict]) -> list[dict[str, Any]]:
    """Build the REFERENCE|CANDIDATE strip of every not-yet-judged cell and its job."""
    jobs = []
    for r in recs:
        if not r.get('path') or not os.path.isfile(r['path']):
            continue
        if 'verdicts' in r:  # checkpointed cell already judged
            continue
        a = run.plan[r['idx']]
        sp = os.path.join(run.sdir, 'strips', f'{os.path.splitext(os.path.basename(r["path"]))[0]}_strip.png')
        make_strip(run.anchor_ref, r['path'], sp)
        r['strip'] = sp
        jobs.append(
            {
                'key': str(id(r)),
                'image': sp,
                'items': _cj.cell_items(
                    a['desc'], kind=a['kind'], band=a['band'], base=run.cell_items_base, body_plan=run.body_plan
                ),
                'preamble': run.cell_items_base.get('preamble', ''),
            }
        )
    return jobs


def apply_cell_verdict(rec: dict, verdict: dict, log: Callable[[str], None]) -> None:
    """Fold one judge verdict into a cell: its flags, the lock exemptions, ok, caption mode."""
    rec['judged'] = bool(verdict.get('judged'))
    rec['verdicts'] = verdict.get('verdicts', [])
    rec['judge_tier'] = verdict.get('tier')
    rec['soft'] = [x for x in (rec.get('soft') or []) if not x.startswith('vlm:')]
    rec['reasons'] = [x for x in rec['reasons'] if not x.startswith('vlm:')]
    if verdict.get('judged'):
        for f in verdict.get('criticals', []) + verdict.get('majors', []):
            if rec.get('locked_view') and f in LOCKED_VIEW_EXEMPT:
                rec.setdefault('exempt', []).append(f'vlm:{f}')
                continue
            (rec['soft'] if f in SOFT_FLAGS else rec['reasons']).append(f'vlm:{f}')
        if rec.get('exempt'):
            log(f'cell {rec["idx"]:02d} locked view: judge flags {rec["exempt"]} not applied (operator lock)')
    elif verdict.get('reason'):
        rec['judge_offline'] = verdict['reason']
    rec['ok'] = not rec['reasons']
    rec['caption_mode'] = caption_mode(rec)


def judge_cells(run: SheetRun, recs: list[dict]) -> None:
    """Judge the given cells in one GPU window and record every verdict on its cell."""
    run.prog('Sheet QC')
    jobs = judge_jobs(run, recs)
    vs = _cj.judge_batch(jobs, offload=True, log_fn=run.log)
    for r in recs:
        v = vs.get(str(id(r)))
        if not v:
            continue
        apply_cell_verdict(r, v, run.log)
        if r.get('attempt', 0) == 0:
            save_cell(run, r)


# ── 5. regen ladder ──────────────────────────────────────────────────────


def cells_to_regen(cells: list[dict], plan: list[dict], attempt: int) -> list[dict]:
    """The cells this regen round should re-render: failed, or soft while soft rounds last."""
    return [
        c
        for c in cells
        if not plan[c['idx']].get('anchor')
        and not c.get('locked_view')
        and (not c['ok'] or (c.get('soft') and attempt <= MAX_REGEN_SOFT))
    ]


def adopt_regen(run: SheetRun, cells: list[dict], r: dict, attempt: int) -> None:
    """Keep a regenerated cell when it scores better than the one on the sheet."""
    cur = cells[r['idx']]
    cur.setdefault('history', []).append(
        {k: cur.get(k) for k in ('path', 'seed', 'attempt', 'reasons', 'soft', 'dino', 'ok', 'judged')}
    )
    if _score_key(r) > _score_key(cur):
        final = os.path.join(run.sdir, 'cells', f'cell_{r["idx"]:02d}.png')
        shutil.copy2(r['path'], final)
        r['path'] = final
        r['history'] = cur.get('history', [])
        cells[r['idx']] = r
        run.log(
            f'cell {r["idx"]:02d} replaced by regen r{attempt} ('
            + ('ok' if r['ok'] and not r.get('soft') else 'still ' + ','.join(r['reasons'] + (r.get('soft') or [])))
            + ')'
        )
    save_cell(run, cells[r['idx']])


def regen_ladder(run: SheetRun, cells: list[dict]) -> None:
    """Re-render failing cells with fresh seeds until they pass or the ladder runs out."""
    for attempt in range(1, MAX_REGEN + 1):
        failed = cells_to_regen(cells, run.plan, attempt)
        if not failed:
            break
        run.prog('Multi-Angle Sheet')
        run.log(f'regen round {attempt}: {len(failed)} cell(s) — {", ".join(c["id"] for c in failed)}')
        regen: list[dict] = []
        for c in failed:
            run.halt()
            r = render_cell(run, run.plan[c['idx']], attempt)
            if r is not None:
                regen.append(r)
        judge_cells(run, regen)
        for r in regen:
            adopt_regen(run, cells, r, attempt)


# ── 6. sheet + report ────────────────────────────────────────────────────


def sheet_title(run: SheetRun, cells: list[dict], n_ok: int, n_soft: int) -> str:
    """The caption stitched across the top of the sheet."""
    return (
        f'{run.brief.get("name") or "creature"} — {n_ok}/{len(cells)} cells train'
        + (f' ({n_soft} with neutral/partial captions)' if n_soft else '')
        + f' — {run.source}'
        + (' · side anchor' if run.anchor_side else '')
        + (' · body plan' if run.body_plan else '')
    )


def finalise(run: SheetRun, cells: list[dict]) -> dict:
    """Stitch the sheet, finish the report, write both and shut the judge down."""
    n_ok = sum(1 for c in cells if c['ok'])
    n_soft = sum(1 for c in cells if c['ok'] and c.get('soft'))
    judged_any = any(c.get('judged') for c in cells)
    judge_note = '' if judged_any else 'JUDGE OFFLINE — structural + DINO only'
    out = sheet_path(run.dataset_dir)
    stitch_sheet(cells, out, title=sheet_title(run, cells, n_ok, n_soft), judge_note=judge_note)
    root_copy = os.path.join(run.dataset_dir, SHEET_FILENAME)
    shutil.copy2(out, root_copy)
    report = run.report
    report.update(
        {
            'cells': cells,
            'sheet_path': out,
            'sheet_root_copy': root_copy,
            'pass_count': n_ok,
            'soft_count': n_soft,
            'cell_count': len(cells),
            'pass_rate': round(n_ok / max(1, len(cells)), 3),
            'judged_any': judged_any,
            'seconds': round(time.time() - run.t0, 1),
            'ended': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
    )
    report['identity']['model'] = _cid.model_id() if _cid.enabled() else None
    with open(report_path(run.dataset_dir), 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=2, default=str)
    _cj.shutdown(log_fn=run.log)
    run.log(f'sheet: {n_ok}/{len(cells)} pass, {report["seconds"]}s → {out}')
    return report
