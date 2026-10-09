# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The first half of ``build_sheet``: the run itself, the references, the anchors.

Lifted out of ``build.py`` on 2026-10-09, when ``build_sheet`` was 618 lines with eight
closures. :class:`SheetRun` carries what used to be that function's locals, so every
stage is an ordinary function with explicit inputs — callable, and for the first time
testable, on its own. The stage order, the log lines and the side effects are unchanged;
``build_sheet`` is now the ladder that calls them, and the cell/judge/regen half lives in
``build_cells.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from zyg_workflows import creature_identity as _cid
from zyg_workflows import creature_judge as _cj

from .base import (
    ANGLES,
    CONFORM_SEEDS,
    SCRATCH_ANCHOR_SEEDS,
    SIDE_TOWARD_BACK,
    _file_sig,
    _mirror,
    _score_key,
    _text_sig,
    anchor_locks,
    sheet_dir,
)
from .comfy import _edit, _txt2img, check_anchor_agreement, conform_anchor
from .images import _prepare_reference, make_strip

BRIEF_KEYS = (
    'name',
    'species',
    'description',
    'visual_traits',
    'style_hint',
    'body_plan',
    'anchor_locks',
    'negative',
)
SCRATCH_DIRS = ('refs', 'anchors', 'cells', 'strips', 'candidates')
MAX_REFERENCES = 12
REFS_DISAGREE_BELOW = 0.35


@dataclass
class SheetRun:
    """One ``build_sheet`` run: the brief's fields, the paths, the anchors, the plan.

    Everything here used to be a local of ``build_sheet`` read by one of its closures.
    The first block is settled by :func:`new_run` and never reassigned; the anchor and
    cell fields are filled in by the stages, in stage order.
    """

    dataset_dir: str
    brief: dict
    source: str
    preset: str
    log: Callable[[str], None]
    prog: Callable[[str], None]
    halt: Callable[[], None]
    sdir: str
    desc: str
    style_hint: str
    body_plan: str
    brief_neg: str
    locks: dict[str, str]
    lock_sig: str
    report: dict[str, Any]
    t0: float
    refs: list[str] = field(default_factory=list)
    anchor_ref: str | None = None  # identity anchor (may be a close-up)
    anchor_full: str | None = None  # whole-body anchor (rotation source)
    anchor_side: str | None = None  # operator-locked right-side profile (tail source)
    anchor_side_mirror: str | None = None
    anchor_notes: list[str] = field(default_factory=list)
    base_items: dict[str, Any] = field(default_factory=dict)
    cell_items_base: dict[str, Any] = field(default_factory=dict)
    plan: list[dict[str, Any]] = field(default_factory=list)
    ref_is_closeup: bool = False
    emb_cache: dict[str, Any] = field(default_factory=dict)


# ── 0. the run itself ────────────────────────────────────────────────────


def new_report(dataset_dir: str, brief: dict, source: str, preset: str) -> dict[str, Any]:
    """The empty report: what was asked for, plus which judges are available today."""
    return {
        'source': source,
        'preset': preset,
        'dataset_dir': dataset_dir,
        'brief': {k: brief.get(k) for k in BRIEF_KEYS},
        'refs': [],
        'anchors': {},
        'cells': [],
        'judge': {'enabled': _cj.enabled(), 'available': _cj.available(), 'tier': _cj.tier()},
        'identity': {'model': None, 'enabled': _cid.enabled()},
        'started': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }


def new_run(
    dataset_dir: str,
    brief: dict,
    *,
    source: str,
    reference_paths: list[str] | None,
    preset: str,
    log: Callable[[str], None],
    prog: Callable[[str], None],
    halt: Callable[[], None],
) -> tuple[SheetRun, list[str]]:
    """Open the run: scratch dirs, the brief's fields, the lock signature, the report.

    Returns the run and the operator reference paths that actually exist. Raises
    ``RuntimeError`` when reference mode was asked for with no usable reference.
    """
    t0 = time.time()
    sdir = sheet_dir(dataset_dir)
    for sub in SCRATCH_DIRS:
        os.makedirs(os.path.join(sdir, sub), exist_ok=True)
    source = 'scratch' if (source or '').lower() in ('scratch', 'text', 'from_scratch') else 'reference'
    refs_in = [p for p in (reference_paths or []) if p and os.path.isfile(p)]
    if source == 'reference' and not refs_in:
        raise RuntimeError('reference mode selected but no reference image was provided')
    locks = anchor_locks(brief)
    body_plan = (brief.get('body_plan') or '').strip()
    run = SheetRun(
        dataset_dir=dataset_dir,
        brief=brief,
        source=source,
        preset=preset,
        log=log,
        prog=prog,
        halt=halt,
        sdir=sdir,
        desc=(brief.get('description') or brief.get('visual_traits') or brief.get('name') or 'creature').strip(),
        style_hint=(brief.get('style_hint') or '').strip(),
        body_plan=body_plan,
        brief_neg=(brief.get('negative') or '').strip(),
        locks=locks,
        # what the anchor checkpoint must agree on before it is reused
        lock_sig=lock_signature(locks, body_plan),
        report=new_report(dataset_dir, brief, source, preset),
        t0=t0,
    )
    return run, refs_in


def lock_signature(locks: dict[str, str], body_plan: str) -> str:
    """Signature of the operator locks + body plan an anchor checkpoint must still match."""
    return '|'.join([_file_sig(locks.get('full_body')), _file_sig(locks.get('side')), _text_sig(body_plan)]).strip('|')


# ── 1. references ────────────────────────────────────────────────────────


def refs_agreement(sims: list[float]) -> dict[str, float]:
    """The reported agreement of a set of pairwise reference similarities."""
    return {'min': min(sims), 'mean': round(sum(sims) / len(sims), 3)}


def pairwise_similarities(embs: list[Any]) -> list[float]:
    """Every pairwise DINO similarity of the given embeddings that could be measured."""
    sims = []
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            s = _cid.similarity_emb(embs[i], embs[j])
            if s is not None:
                sims.append(s)
    return sims


def collect_references(run: SheetRun, refs_in: list[str]) -> None:
    """Copy the operator's references into the sheet dir and record their agreement.

    Fills ``run.refs`` and ``report['refs']``; warns when the references look like
    different creatures.
    """
    for i, src in enumerate(refs_in[:MAX_REFERENCES]):
        dst = os.path.join(run.sdir, 'refs', f'ref_{i:02d}.png')
        _prepare_reference(src, dst)
        run.refs.append(dst)
        run.report['refs'].append({'src': src, 'path': dst})
    if run.refs and _cid.enabled():
        embs = [_cid.embed(p) for p in run.refs]
        run.report['identity']['model'] = _cid.model_id()
        if len(run.refs) > 1:
            sims = pairwise_similarities(embs)
            if sims:
                run.report['refs_agreement'] = refs_agreement(sims)
                if min(sims) < REFS_DISAGREE_BELOW:
                    run.log(
                        f'WARNING: reference images disagree (min DINO {min(sims):.2f}) '
                        '— they may show different creatures'
                    )


# ── 2. anchors ───────────────────────────────────────────────────────────


def load_checklists(run: SheetRun) -> None:
    """Load the anchor and cell judge checklists once for the whole run."""
    run.base_items = _cj.load_items(_cj.ANCHOR_CHECKLIST)
    run.cell_items_base = _cj.load_items(_cj.CELL_CHECKLIST)


def anchor_ckpt(run: SheetRun) -> str:
    """Path of the anchor checkpoint a resumed run reads."""
    return os.path.join(run.sdir, 'anchors', 'anchors.json')


def checkpoint_usable(ck: dict, lock_sig: str) -> bool:
    """Whether an anchor checkpoint still has its images and matches the lock signature."""
    return (
        all(os.path.isfile(ck.get(k) or '') for k in ('identity', 'full_body'))
        and (ck.get('lock_sig') or '') == lock_sig
    )


def resume_anchors(run: SheetRun) -> bool:
    """Adopt the anchors of a previous run when the checkpoint still applies.

    A GUI restart mid-run kills the worker thread (2026-08-25: another session
    restarted the GUI 84 s into the pufferball run), so anchors and finished cells are
    recorded on disk and a resumed run renders only what is missing. Returns whether
    the checkpoint was adopted.
    """
    ck_anchor = anchor_ckpt(run)
    try:
        if os.path.isfile(ck_anchor):
            _ck = json.load(open(ck_anchor, encoding='utf-8'))
            if checkpoint_usable(_ck, run.lock_sig):
                run.anchor_ref, run.anchor_full = _ck['identity'], _ck['full_body']
                run.anchor_side = _ck.get('side') if os.path.isfile(_ck.get('side') or '') else None
                run.anchor_side_mirror = (
                    _ck.get('side_mirror') if os.path.isfile(_ck.get('side_mirror') or '') else None
                )
                run.report['anchors'] = _ck.get('report') or {}
                if _ck.get('refs'):
                    run.report['refs'] = _ck['refs']
                run.log('resume: anchors reused from checkpoint')
                return True
            if os.path.isfile(_ck.get('full_body') or ''):
                run.log('anchor checkpoint ignored: locks / body plan changed — rebuilding anchors')
    except Exception as exc:
        run.log(f'anchor checkpoint unreadable ({exc}) — rebuilding anchors')
    return False


def reference_is_whole_body(verdict: dict) -> bool:
    """Whether the judge answered yes to ``whole_body`` for this reference."""
    vv = {x['id']: x for x in verdict.get('verdicts', [])}
    return (vv.get('whole_body') or {}).get('answer') == 'yes'


def reference_rank_key(verdict: dict, index: int) -> tuple[int, int, int]:
    """Rank one judged reference: no criticals first, then whole body, then earliest."""
    whole = reference_is_whole_body(verdict)
    crit = list(verdict.get('criticals') or [])
    return (0 if crit else 1, 1 if whole else 0, -index)


def judge_references(run: SheetRun) -> int:
    """Judge every reference once — single subject / no human / whole body.

    Records each verdict in ``report['refs']`` and returns the index of the best one.
    """
    jobs = [
        {
            'key': f'ref{i}',
            'image': p,
            'items': _cj.anchor_items('', want_full_body=True, base=run.base_items),
            'preamble': run.base_items.get('preamble', ''),
        }
        for i, p in enumerate(run.refs)
    ]
    verdicts = _cj.judge_batch(jobs, offload=True, log_fn=run.log)
    best_i, best_key = 0, None
    for i, _p in enumerate(run.refs):
        v = verdicts.get(f'ref{i}') or {}
        key = reference_rank_key(v, i)
        run.report['refs'][i].update(
            {
                'judged': v.get('judged', False),
                'ok': v.get('ok', True),
                'flags': v.get('flags', []),
                'whole_body': reference_is_whole_body(v),
                'verdicts': v.get('verdicts', []),
            }
        )
        if best_key is None or key > best_key:
            best_key, best_i = key, i
    return best_i


def derive_full_body_anchor(run: SheetRun) -> None:
    """Edit the identity anchor into a whole-body anchor: best of 2, judged vs the source."""
    run.anchor_notes.append('full-body anchor derived from the reference by edit')
    cands = []
    for k in range(2):
        run.halt()
        dst = os.path.join(run.sdir, 'anchors', f'full_cand_{k}.png')
        instr = (
            'Pull the camera back to show the ENTIRE creature from the front, whole body '
            'from top to bottom visible and centred, nothing cut off by the frame.'
        )
        if _edit(run.anchor_ref, instr, dst, 4200 + k, run.log, style_hint=run.style_hint):
            cands.append(dst)
    if not cands:
        raise RuntimeError('could not derive a full-body anchor from the reference')
    strips = []
    for k, c in enumerate(cands):
        sp = os.path.join(run.sdir, 'strips', f'anchor_full_{k}.png')
        make_strip(run.anchor_ref, c, sp)
        strips.append(
            {
                'key': f'full{k}',
                'image': sp,
                'items': _cj.cell_items(
                    'a straight-on front view showing the whole body', kind='body', base=run.cell_items_base
                ),
                'preamble': run.cell_items_base.get('preamble', ''),
            }
        )
    vs = _cj.judge_batch(strips, offload=True, log_fn=run.log)
    ranked = []
    for k, c in enumerate(cands):
        v = vs.get(f'full{k}') or {}
        d = _cid.similarity(run.anchor_ref, c) if _cid.enabled() else None
        ranked.append(candidate_record(c, v, dino=d))
    ranked.sort(key=_score_key, reverse=True)
    run.anchor_full = os.path.join(run.sdir, 'anchors', 'anchor_full.png')
    shutil.copy2(ranked[0]['path'], run.anchor_full)
    run.report['anchors']['full_body'] = {
        'path': run.anchor_full,
        'from': 'edit_of_reference',
        'candidates': ranked,
    }
    if not ranked[0]['ok']:
        run.log(f'WARNING: best full-body anchor still flagged {ranked[0]["flags"]} — sheet continues, review it')


def candidate_record(path: str, verdict: dict, *, dino: float | None) -> dict[str, Any]:
    """One ranked anchor candidate: its path, the judge's answer and its DINO score."""
    return {
        'path': path,
        'ok': verdict.get('ok', True),
        'judged': verdict.get('judged', False),
        'flags': verdict.get('flags', []),
        'dino': dino,
        'reasons': [],
        'verdicts': verdict.get('verdicts', []),
    }


def anchors_from_reference(run: SheetRun) -> None:
    """Pick the identity anchor out of the references and settle the full-body anchor."""
    best_i = judge_references(run)
    run.anchor_ref = run.refs[best_i]
    run.report['anchors']['identity'] = {'path': run.anchor_ref, 'from': 'reference', 'index': best_i}
    ref_whole = bool(run.report['refs'][best_i].get('whole_body')) and run.report['refs'][best_i].get('judged')
    if run.locks.get('full_body'):
        pass  # the operator's lock replaces the derived full-body anchor (applied below)
    elif ref_whole:
        run.anchor_full = run.anchor_ref
        run.report['anchors']['full_body'] = {'path': run.anchor_full, 'from': 'reference'}
    else:
        derive_full_body_anchor(run)


def scratch_prompt(desc: str, brief: dict, style_hint: str) -> str:
    """The txt2img prompt a from-scratch anchor is generated from."""
    prompt = (
        f'{desc}. {brief.get("visual_traits") or ""} single creature, full body, front view, '
        f'centred, plain neutral studio background, high detail reference render, no people, no text'
    )
    if style_hint:
        prompt += f', {style_hint}'
    return prompt


def anchors_from_scratch(run: SheetRun) -> None:
    """Generate the anchor from the brief alone: klein txt2img, best of N, judged."""
    prompt = scratch_prompt(run.desc, run.brief, run.style_hint)
    cands = []
    for k in range(max(1, SCRATCH_ANCHOR_SEEDS)):
        run.halt()
        dst = os.path.join(run.sdir, 'anchors', f'scratch_cand_{k}.png')
        if _txt2img(prompt, dst, 5100 + k, run.log):
            cands.append(dst)
    if not cands:
        raise RuntimeError('from-scratch anchor generation produced no image')
    jobs = [
        {
            'key': f'sc{k}',
            'image': c,
            'items': _cj.anchor_items(run.desc, want_full_body=True, base=run.base_items),
            'preamble': run.base_items.get('preamble', ''),
        }
        for k, c in enumerate(cands)
    ]
    vs = _cj.judge_batch(jobs, offload=True, log_fn=run.log)
    ranked = [candidate_record(c, vs.get(f'sc{k}') or {}, dino=None) for k, c in enumerate(cands)]
    ranked.sort(key=_score_key, reverse=True)
    run.anchor_full = os.path.join(run.sdir, 'anchors', 'anchor_full.png')
    shutil.copy2(ranked[0]['path'], run.anchor_full)
    run.anchor_ref = run.anchor_full
    run.report['anchors']['full_body'] = {'path': run.anchor_full, 'from': 'klein_txt2img', 'candidates': ranked}
    run.report['anchors']['identity'] = {'path': run.anchor_ref, 'from': 'klein_txt2img'}
    if not ranked[0]['ok']:
        run.log(f'WARNING: best scratch anchor still flagged {ranked[0]["flags"]} — review it')


def apply_full_body_lock(run: SheetRun) -> None:
    """Make the operator's locked image the full-body (and in scratch mode identity) anchor."""
    dst = os.path.join(run.sdir, 'anchors', 'anchor_full.png')
    _prepare_reference(run.locks['full_body'], dst)
    run.anchor_full = dst
    run.report['anchors']['full_body'] = {'path': dst, 'from': 'operator_lock', 'src': run.locks['full_body']}
    if run.source == 'scratch':
        run.anchor_ref = dst
        run.report['anchors']['identity'] = {'path': dst, 'from': 'operator_lock'}
    run.anchor_notes.append('full-body anchor locked by the operator')
    run.log(f'anchor lock: full_body <- {os.path.basename(run.locks["full_body"])}')


def conform_to_body_plan(run: SheetRun) -> None:
    """Re-render the derived anchor until it matches the brief's body plan (angles LoRA off)."""
    run.halt()
    run.log(f'conform pass: making the anchor match the body plan ({CONFORM_SEEDS} seed(s), angles LoRA off)')
    res = conform_anchor(
        run.anchor_full,
        run.body_plan,
        os.path.join(run.sdir, 'anchors'),
        run.anchor_ref,
        run.log,
        style_hint=run.style_hint,
        extra_negative=run.brief_neg,
    )
    if not res.get('path'):
        run.log('WARNING: conform pass produced no image — derived anchor kept')
        return
    dst = os.path.join(run.sdir, 'anchors', 'anchor_full.png')
    if os.path.abspath(res['path']) != os.path.abspath(dst):
        shutil.copy2(res['path'], dst)
    prev = run.report['anchors'].get('full_body') or {}
    run.report['anchors']['full_body'] = {
        **prev,
        'path': dst,
        'from': f'{prev.get("from") or "derived"}+conform',
        'conform': res,
    }
    run.anchor_full = dst
    run.anchor_notes.append('anchor conformed to the body plan')
    best = res['candidates'][0]
    if not best.get('ok') or best.get('soft'):
        run.log(f'WARNING: conformed anchor still flagged {best.get("flags")} — sheet continues, review it')


def apply_side_lock(run: SheetRun) -> None:
    """Adopt the operator's side profile (and its mirror) as the side/back/top source."""
    run.anchor_side = os.path.join(run.sdir, 'anchors', 'anchor_side.png')
    _prepare_reference(run.locks['side'], run.anchor_side)
    run.anchor_side_mirror = _mirror(run.anchor_side, os.path.join(run.sdir, 'anchors', 'anchor_side_mirror.png'))
    run.report['anchors']['side'] = {
        'path': run.anchor_side,
        'mirror': run.anchor_side_mirror,
        'from': 'operator_lock',
        'src': run.locks['side'],
        'dino_vs_full': _cid.similarity(run.anchor_full, run.anchor_side) if _cid.enabled() else None,
        'toward_back': SIDE_TOWARD_BACK,
        'cells': [a['id'] for a in ANGLES if a.get('side_source')],
    }
    run.anchor_notes.append('side anchor locked by the operator — side/back/top cells rotate from it')
    run.log(f'anchor lock: side <- {os.path.basename(run.locks["side"])} (mirrored for the left profile)')
    agree = check_anchor_agreement(run.anchor_full, run.anchor_side, run.body_plan, run.sdir, run.log)
    if agree:
        run.report['anchors']['agreement'] = agree
        if agree.get('ok') is False:
            run.anchor_notes.append('ANCHOR LOCKS DISAGREE: ' + ', '.join(agree.get('disagree') or []))


def write_anchor_checkpoint(run: SheetRun) -> None:
    """Record the settled anchors so a restarted run does not pay for them again."""
    with open(anchor_ckpt(run), 'w', encoding='utf-8') as fh:
        json.dump(
            {
                'identity': run.anchor_ref,
                'full_body': run.anchor_full,
                'side': run.anchor_side,
                'side_mirror': run.anchor_side_mirror,
                'lock_sig': run.lock_sig,
                'body_plan': run.body_plan,
                'report': run.report['anchors'],
                'refs': run.report['refs'],
            },
            fh,
            default=str,
        )


def settle_anchors(run: SheetRun) -> None:
    """Operator locks + conform pass (body-plan lock, 2026-08-25), then the checkpoint."""
    if run.locks.get('full_body'):
        apply_full_body_lock(run)
    elif run.body_plan:
        conform_to_body_plan(run)
    if run.locks.get('side'):
        apply_side_lock(run)
    run.report['anchors']['notes'] = run.anchor_notes
    write_anchor_checkpoint(run)


def anchors_ready_line(run: SheetRun) -> str:
    """The one log line that says which anchors the cells will be rotated from."""
    return (
        f'anchors ready: identity={os.path.basename(run.anchor_ref)} '
        f'full_body={os.path.basename(run.anchor_full)}'
        + (f' side={os.path.basename(run.anchor_side)}' if run.anchor_side else '')
        + (f' body_plan="{run.body_plan[:80]}"' if run.body_plan else '')
    )
