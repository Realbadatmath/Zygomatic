# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared state and private helpers of the cell-00 anchor gates.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 36-206).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable
from zyg_workflows import contact_sheet_pipeline as _csp


@dataclass
class AnchorCtx:
    """State the cell-00 anchor gates read and hand to each other.

    Everything down to `body_anchor_path` is read-only run context; the fields
    below it are the ones the gates REBIND (plain locals of
    `_generate_per_cell_contact_sheet` before the split, reached by the gate
    closures through `nonlocal`).

    `anchor_replaced` stays None until the attribute gate binds it and
    `dedup_others` stays None until the dedup gate collects candidates: the
    dedup re-check used to see an unbound name in exactly those two cases and
    skip itself, which the None sentinels preserve. `attr_reinstall_bound`
    plays the same role for the structure gate's re-extract fallback.
    """

    char_id: str
    params: dict
    log_fn: Callable[[str], None] | None
    cell_path: str
    anchor_path: str
    gen_kwargs: dict
    prompt: str
    pkg: dict
    progress_job: dict | None
    anchor_family: str
    cell0_reused: bool
    render_style: str
    realism_lora_path: str
    realism_lora_scale: float
    anchor_skin: str
    anchor_cfg: float
    dark_retry_cfg: float
    qwen_ok: bool
    base_seed: int
    unet: str
    skin_clause: str
    style_extra: str
    trigger: str
    body_anchor_path: str
    anchor_cell: str | None = None
    anchor_face: str | None = None
    anchor_cell_body: str | None = None
    anchor_face_detected: bool = False
    anchor_replaced: bool | None = None
    attr_reinstall_bound: bool = False
    photoreal: bool = False
    style_gate_on: bool = False
    sg_floor: float = 0.0
    dedup_on: bool = False
    dedup_others: list | None = None
    dedup_max_sim: float = 0.0
    dedup_max_sim_arch: float = 0.0


def _reinstall_anchor(ctx: AnchorCtx) -> None:
    """Re-extract the anchor face crop after a gate replaced the anchor image."""
    import shutil as _sh_ri

    from zyg_workflows import identity_qc_service as _idqc

    try:
        ctx.anchor_face = _idqc.extract_anchor_face(
            ctx.cell_path,
            ctx.anchor_path,
            log_fn=ctx.log_fn,
        )
    except Exception:
        ctx.anchor_face = None
    ctx.anchor_face_detected = bool(ctx.anchor_face)
    if not ctx.anchor_face:
        _sh_ri.copy2(ctx.cell_path, ctx.anchor_path)
        ctx.anchor_face = ctx.anchor_path


def _anchor_style_check(ctx: AnchorCtx) -> tuple[bool, str]:
    """ArcFace detectability + cheek-band texture floor on the anchor image.

    `ctx.anchor_face_detected` is read live on purpose: the attribute gate
    rebinds it through `_reinstall_anchor` and this check must see that.
    """
    from zyg_workflows import identity_qc_service as _idqc

    if not ctx.anchor_face_detected:
        return False, 'face not detectable (likely illustration/cartoon)'
    try:
        _emb = _idqc.embed_images([ctx.cell_path], log_fn=None)
        _bbox = (_emb.get(ctx.cell_path) or {}).get('bbox')
        _tex = _csp._tile_texture_score(ctx.cell_path, _bbox)
    except Exception:
        _tex = None
    if _tex is not None and _tex < ctx.sg_floor:
        return False, f'cheek texture {_tex:.0f} < {ctx.sg_floor:g} (semi-render/doll)'
    return True, f'texture {"n/a" if _tex is None else round(_tex)}'


def _dedup_candidates(char_id: str) -> list[tuple[str, str, bool]]:
    """Other characters' anchor faces to compare against (live roster + archived)."""
    try:
        _dd_all = []
        for _dd_root0 in (_csp._DATASET_ROOT, os.path.join(_csp._DATASET_ROOT, '_archived')):
            _dd_is_arch = _dd_root0.endswith('_archived')
            if not os.path.isdir(_dd_root0):
                continue
            for _dd_cid0 in os.listdir(_dd_root0):
                if _dd_cid0 == char_id or _dd_cid0.startswith('_'):
                    continue
                _dd_p0 = os.path.join(
                    _dd_root0,
                    _dd_cid0,
                    'contact_sheet',
                    'contact_sheet_anchor_face.png',
                )
                if os.path.isfile(_dd_p0):
                    _dd_all.append(
                        (_dd_cid0, _dd_p0, os.path.getmtime(_dd_p0), _dd_is_arch),
                    )
        # Newest 20 keeps the embed batch bounded as the roster grows.
        return [(t[0], t[1], t[3]) for t in sorted(_dd_all, key=lambda t: t[2], reverse=True)[:20]]
    except OSError:
        return []


def _dedup_most_similar(
    face_path: str,
    _dd_others: list,
    _dd_max_sim: float,
    _dd_max_sim_arch: float,
) -> dict:
    """Worst-violation comparison vs library anchors.

    Returns {'sim','cid','path','archived','ceiling','margin'}
    for the anchor with the highest sim-minus-ceiling margin
    (per-anchor ceilings: live vs archived). margin > 0 =
    violation. sim -1 = probe face not embeddable.
    """
    from zyg_workflows import identity_qc_service as _idqc

    _worst = {
        'sim': -1.0,
        'cid': '',
        'path': '',
        'archived': False,
        'ceiling': _dd_max_sim,
        'margin': -999.0,
    }
    _emb = _idqc.embed_images(
        [face_path] + [p for _, p, _a in _dd_others],
        log_fn=None,
    )
    _me = (_emb.get(face_path) or {}).get('embedding')
    if not _me:
        return _worst
    for _cid2, _p2, _arch2 in _dd_others:
        _e2 = (_emb.get(_p2) or {}).get('embedding')
        if not _e2:
            continue
        _s = _idqc.cosine(_me, _e2)
        _c = _dd_max_sim_arch if _arch2 else _dd_max_sim
        if _s - _c > _worst['margin']:
            _worst = {
                'sim': _s,
                'cid': _cid2,
                'path': _p2,
                'archived': _arch2,
                'ceiling': _c,
                'margin': _s - _c,
            }
    return _worst
