# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_judge.py
=================
Batched Qwen3-VL judge for creature sheet cells (2026-08-25).

Reuses the render-inspection stack in ``vlm_inspector`` (isolated venv worker,
tiers, persistent server, majority-vote aggregation) but drives it per CELL
with a per-cell question list, because two things in ``inspect_frames`` do not
fit a contact sheet:

  * it loads one named checklist and cannot substitute the cell's viewpoint
    into a question ("is the creature shown from behind?" is a different
    question for every cell);
  * every call is its own ``gpu_exclusive`` offload — 16 cells would offload
    ComfyUI 16 times. Here the caller offloads ONCE and judges the batch.

THE STRIP RULE. The worker prefixes multi-image prompts with "You are shown N
frames from one video render" — wrong for a reference/candidate pair. So a
cell is judged as ONE image: a side-by-side strip, LEFT = REFERENCE, RIGHT =
CANDIDATE, both labelled in the pixels. Every question says which panel it is
about. (The VLM Inspector memory's CROP RULE holds here too: a 1024-px cell
next to its anchor is large enough for eyes/fur/limb questions.)

Fail-open like the rest of the ladder: a missing venv, a refused GPU or a
timed-out worker returns ``judged=False`` verdicts that never exclude a cell,
and the sheet report says JUDGE OFFLINE so the operator can see it.
"""

from __future__ import annotations

import json
import os
from typing import Callable
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS = os.path.dirname(os.path.abspath(__file__))
CHECKLIST_PATH = os.environ.get('ZYG_VLM_CHECKLISTS', os.path.join(_CREWS, 'config', 'vlm_checklists.json'))

CELL_CHECKLIST = 'creature_cell'
ANCHOR_CHECKLIST = 'creature_anchor'
PREVIEW_CHECKLIST = 'creature_cell'
# Front lock vs side lock, asked before any cell renders (2026-08-26).
PAIR_CHECKLIST = 'creature_anchor_pair'


def enabled() -> bool:
    return os.environ.get('ZYG_CREATURE_VLM', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def tier() -> str:
    t = (os.environ.get('ZYG_CREATURE_JUDGE_TIER') or 'resident').strip().lower()
    return t if t in ('boundary', 'resident', 'cpu') else 'resident'


def load_items(name: str) -> dict:
    """{'preamble', 'items'[, 'parts']} from the shared checklist book, {} when missing.

    `parts` holds question templates keyed by a body-part word (creature_anchor_pair
    selects from it by body plan, so its flat `items` list is empty by design) — a
    checklist is only "missing" when it has neither.
    """
    try:
        with open(CHECKLIST_PATH, encoding='utf-8') as fh:
            book = json.load(fh).get('checklists') or {}
        cl = book.get(name) or {}
        items = [i for i in (cl.get('items') or []) if isinstance(i, dict) and i.get('id')]
        parts = cl.get('parts') if isinstance(cl.get('parts'), dict) else None
        if not items and not parts:
            return {}
        out = {'preamble': cl.get('preamble', ''), 'items': items}
        if parts:
            out['parts'] = parts
        return out
    except Exception:
        return {}


def cell_items(
    angle_desc: str, *, kind: str = 'body', band: str | None = None, base: dict | None = None, body_plan: str = ''
) -> list[dict]:
    """The creature_cell checklist with the viewpoint question filled in.

    Items carrying ``"kinds"`` only apply to cells of those kinds (a "whole body
    visible" question is wrong for a face close-up); items carrying ``"bands"``
    only to those view bands (a back view cannot show the eyes). Items whose
    question carries ``{body_plan}`` are asked only when a body plan is given
    (body-plan lock, 2026-08-25)."""
    base = base if base is not None else load_items(CELL_CHECKLIST)
    out: list[dict] = []
    for it in base.get('items', []):
        kinds = it.get('kinds')
        if kinds and kind not in kinds:
            continue
        bands = it.get('bands')
        if bands and band is not None and band not in bands:
            continue
        rec = dict(it)
        if '{angle_desc}' in str(rec.get('question', '')):
            rec['question'] = rec['question'].replace('{angle_desc}', angle_desc or 'the requested viewpoint')
        if '{body_plan}' in str(rec.get('question', '')):
            bp = (body_plan or '').strip().rstrip('.')
            if not bp:
                continue
            rec['question'] = rec['question'].replace('{body_plan}', bp)
        out.append(rec)
    return out


def pair_items(body_plan: str, *, base: dict | None = None) -> list[dict]:
    """Per-panel questions for the anchor-agreement check, chosen by body plan.

    Each question is asked of ONE lock at a time and the two answers compared in
    code (check_anchor_agreement). Asking the judge to compare two panels
    directly was MEASURED useless on 2026-08-26: across a front and a side view
    the projected angle of every limb really does differ, so "same angle in both
    panels?" came back 'no' for all four pairs tested — the known-bad one and the
    good candidates alike. These questions are viewpoint-invariant instead.

    Returns [] when the plan names no part we have templates for, which is also
    the no-body-plan case. `expected` is deliberately absent: there is no correct
    answer for one panel, only agreement between the two.
    """
    bp = (body_plan or '').strip().lower()
    if not bp:
        return []
    base = base if base is not None else load_items(PAIR_CHECKLIST)
    parts = base.get('parts') or {}
    out: list[dict] = []
    for word, items in parts.items():
        if word not in bp:
            continue
        for it in items:
            rec = dict(it)
            rec.setdefault('severity', 'critical')
            rec.setdefault('grounding', False)
            out.append(rec)
    return out


def pair_preamble(*, base: dict | None = None) -> str:
    base = base if base is not None else load_items(PAIR_CHECKLIST)
    return base.get('preamble', '')


def anchor_items(brief_desc: str, *, want_full_body: bool = True, base: dict | None = None) -> list[dict]:
    base = base if base is not None else load_items(ANCHOR_CHECKLIST)
    out: list[dict] = []
    for it in base.get('items', []):
        if it.get('id') == 'whole_body' and not want_full_body:
            continue
        if it.get('id') == 'matches_brief' and not (brief_desc or '').strip():
            continue
        rec = dict(it)
        if '{brief}' in str(rec.get('question', '')):
            rec['question'] = rec['question'].replace('{brief}', (brief_desc or '')[:400])
        out.append(rec)
    return out


def _questions(items: list[dict], preamble: str) -> list[dict]:
    qs = []
    for it in items:
        q = ' '.join(x for x in (preamble, str(it.get('question', ''))) if x)
        qs.append(
            {
                'id': it['id'],
                'question': q,
                'expected': str(it.get('expected', 'yes')).lower(),
                'severity': str(it.get('severity', 'major')).lower(),
                'grounding': False,
            }
        )
    return qs


def available() -> bool:
    try:
        from zyg_workflows import vlm_inspector as VI

        return bool(VI.available())
    except Exception:
        return False


def _offline(reason: str, items: list[dict]) -> dict:
    return {
        'judged': False,
        'ok': True,
        'reason': reason,
        'flags': [],
        'criticals': [],
        'majors': [],
        'verdicts': [
            {'id': i['id'], 'answer': 'unknown', 'ok': None, 'severity': i.get('severity', 'major')} for i in items
        ],
    }


def judge_batch(
    jobs: list[dict],
    *,
    offload: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, dict]:
    """Judge a batch of strips in one GPU window.

    jobs: [{'key': str, 'image': path, 'items': [...], 'preamble': str}]
    Returns {key: {'judged', 'ok', 'flags', 'criticals', 'majors', 'verdicts', 'tier', 'model'}}.
    """
    log = log_fn or (lambda _m: None)
    out: dict[str, dict] = {}
    jobs = [j for j in jobs if j.get('image') and os.path.isfile(j['image']) and j.get('items')]
    if not jobs:
        return out
    if not enabled():
        for j in jobs:
            out[j['key']] = _offline('disabled (ZYG_CREATURE_VLM=0)', j['items'])
        return out
    try:
        from zyg_workflows import vlm_inspector as VI
    except Exception as exc:
        for j in jobs:
            out[j['key']] = _offline(f'vlm_inspector import failed: {exc}', j['items'])
        return out
    if not VI.available():
        log(f'creature judge: worker venv missing under {VI.VLM_HOME} — JUDGE OFFLINE')
        for j in jobs:
            out[j['key']] = _offline('worker_unavailable', j['items'])
        return out

    want = tier()
    cfg = VI.TIERS[want]

    def _run_all(chosen: str) -> None:
        model_id = VI.model_for(chosen)
        for n, j in enumerate(jobs, 1):
            qs = _questions(j['items'], j.get('preamble', ''))
            res = VI._run_worker(model_id, [j['image']], qs, chosen, log)
            if res is None:
                out[j['key']] = _offline('worker_failed', j['items'])
                continue
            agg = VI._aggregate(j['items'], [res], log)
            agg.update({'judged': True, 'tier': chosen, 'model': model_id})
            # Keep the worker's own record per question (error / raw reply /
            # infer time): _aggregate drops them, and a parse failure looks
            # exactly like a wrong answer without them (2026-08-25).
            raw = {v.get('id'): v for v in (res.get('verdicts') or []) if isinstance(v, dict)}
            for rec in agg.get('verdicts', []):
                w = raw.get(rec['id']) or {}
                if w.get('error'):
                    rec['error'] = str(w['error'])[:200]
                if w.get('raw'):
                    rec['raw'] = str(w['raw'])[:300]
                if w.get('infer_s') is not None:
                    rec['infer_s'] = w['infer_s']
            n_err = sum(1 for v in raw.values() if v.get('error'))
            if n_err:
                log(
                    f'creature judge {j["key"]}: {n_err}/{len(raw)} questions errored — '
                    + (next(iter(v.get('error') for v in raw.values() if v.get('error'))) or '')[:160]
                )
            out[j['key']] = agg
            log(
                f'creature judge {n}/{len(jobs)} {j["key"]}: '
                + ('PASS' if agg['ok'] else 'FLAG ' + ','.join(agg['flags']))
            )

    if not cfg['needs_gpu']:
        _run_all(want)
        return out
    try:
        from zyg_workflows import comfy_offload as CO
    except Exception as exc:
        log(f'comfy_offload unavailable ({exc}) — judging on CPU tier')
        _run_all('cpu')
        return out
    try:
        if CO.comfy_is_sampling():
            log('ComfyUI is SAMPLING — judge refuses the GPU; cells stay unjudged')
            for j in jobs:
                out[j['key']] = _offline('comfy_sampling', j['items'])
            return out
    except Exception as exc:
        log(f'comfy_is_sampling failed ({exc}) — assuming sampling, judge offline')
        for j in jobs:
            out[j['key']] = _offline('comfy_probe_failed', j['items'])
        return out
    if not offload:
        free = 0.0
        try:
            free = CO.gpu_free_gb() or 0.0
        except Exception as _exc:
            _zyg_log.debug('gpu free vram probe failed, assuming 0 GB: %s', _exc)
        _run_all(VI._downshift(want, float(free), log))
        return out
    try:
        with CO.gpu_exclusive(min_free_gb=float(cfg['min_free_gb']), log_fn=log_fn) as free_gb:
            _run_all(VI._downshift(want, float(free_gb or 0.0), log))
    except Exception as exc:
        log(f'gpu_exclusive failed ({exc}) — judging on CPU tier')
        _run_all('cpu')
    finally:
        # The GPU goes straight back to ComfyUI after an offloaded batch, and the
        # bf16 Qwen-edit checkpoint (41 GB) + a resident 8B judge (10 GB) do not
        # fit on the 48 GB card together. Release the judge now rather than
        # waiting for its 180 s idle watchdog; reloading it costs ~5-10 s.
        try:
            VI.shutdown_workers(log_fn=log_fn)
        except Exception as _exc:
            _zyg_log.warning('judge worker shutdown failed, judge vram may stay held: %s', _exc)
    return out


def shutdown(log_fn=None) -> None:
    """Release any persistent judge server (end of run)."""
    try:
        from zyg_workflows import vlm_inspector as VI

        VI.shutdown_workers(log_fn=log_fn)
    except Exception as _exc:
        _zyg_log.warning('judge worker shutdown failed, judge vram may stay held: %s', _exc)
