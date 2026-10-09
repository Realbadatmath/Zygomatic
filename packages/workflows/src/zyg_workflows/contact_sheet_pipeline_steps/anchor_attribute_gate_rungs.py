# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The rungs of the anchor attribute compliance gate.

``step_attribute_gate`` was one 304-line function with three closures. Its
rungs — judge, boosted regens, targeted iris recolour, style re-check, scratch
cleanup — are helpers here, and the enclosing locals the closures reached
through ``nonlocal`` are :class:`AttrGate`. The anchor face crop and its
detection flag live on the ``AnchorCtx`` (``_reinstall_anchor`` writes them
there), so the gate reads them live instead of mirroring them.

Behaviour, log lines, scratch files and their order are unchanged; the two
environment variables stay read in ``anchor_attribute_gate.py``, where the
settings registry documents them.
"""

from __future__ import annotations

import logging as _zyg_logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any

from .anchor_ctx import AnchorCtx, _anchor_style_check, _reinstall_anchor

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')

_EYE_VOCAB_FALLBACK = ('brown', 'green', 'blue', 'hazel', 'gray', 'amber')

_IRIS_NEGATIVES = 'glowing eyes, neon eyes, oversaturated irises, colored contact lenses, luminous irises'

__all__ = [
    'AttrGate',
    'attribute_spec',
    'boost_tokens',
    'clear_scratch',
    'eye_negatives',
    'iris_edit_prompt',
    'iris_fix_kwargs',
    'iris_recolour_rung',
    'judge_anchor',
    'load_attr_judge',
    'merge_negative',
    'open_attr_gate',
    'restore_best',
    'run_boosted_retries',
    'style_recheck',
]


@dataclass
class AttrGate:
    """What the attribute gate carries from one rung to the next.

    ``verdict`` is the live judgement of the anchor on disk, ``best_verdict``
    the fewest-mismatch one seen so far (with ``best_anchor`` holding that
    image) and ``orig_verdict`` the pre-gate one (with ``pregate_anchor``).
    """

    ctx: AnchorCtx
    cgs: Any
    avj: Any
    spec: dict
    eye_colors: tuple
    retries: int
    best_anchor: str
    pregate_anchor: str
    verdict: dict = field(default_factory=dict)
    best_verdict: dict = field(default_factory=dict)
    orig_verdict: dict = field(default_factory=dict)


def attribute_spec(params: dict) -> dict:
    """The attribute colours the run actually asked for, lower-cased.

    In: the run params. Out: a dict of the non-empty ``eye_color``,
    ``hair_color`` and ``skin_tone`` values — empty when nothing was specified,
    which is one of the three conditions that switch the whole gate off.
    """
    return {
        k: (params.get(k) or '').strip().lower()
        for k in ('eye_color', 'hair_color', 'skin_tone')
        if (params.get(k) or '').strip()
    }


def load_attr_judge():
    """The cell VLM judge module, or None when it is absent or disabled."""
    try:
        from zyg_workflows import cell_vlm_judge as _avj

        if not _avj.enabled():
            return None
    except Exception:
        return None
    return _avj


def merge_negative(existing, addition) -> str:
    """Append one negative-prompt clause to an existing ``extra_negative``.

    In: the current value (possibly None or comma-padded) and the clause to
    add. Out: the two joined with ', ', with empty parts dropped — replacing
    the existing negatives instead of merging them invited back the exact skin
    lightening the edit prompt forbids.
    """
    return ', '.join(x for x in ((existing or '').strip(', '), addition) if x)


def judge_anchor(gate: AttrGate) -> dict:
    """VLM-read the delivered anchor and compare it with the spec.

    In: the gate. Out: the judge's verdict dict (``checked``, ``observed``,
    ``mismatches``, ``unverifiable``). The face crop is judged when one exists,
    the whole cell otherwise; the crop is read live because a reinstall after a
    regen rebinds it on the ctx.
    """
    ctx = gate.ctx
    face = ctx.anchor_face
    target = face if (face and os.path.isfile(face)) else ctx.cell_path
    return gate.avj.judge_attributes(target, gate.spec, log_fn=ctx.log_fn)


def eye_negatives(gate: AttrGate, spec_color: str) -> str:
    """Every eye colour in the judge's vocabulary that is NOT the spec one.

    In: the gate and the specified eye colour. Out: a negative-prompt fragment
    like ``'brown eyes, blue eyes, …'`` — the wrong colours pushed away, since
    a bare positive loses to the model's prior.
    """
    avj = gate.avj
    _sc = avj.normalize_color(spec_color) if hasattr(avj, 'normalize_color') else spec_color
    return ', '.join(f'{c} eyes' for c in gate.eye_colors if c not in _sc and _sc not in c)


def boost_tokens(gate: AttrGate, mismatches: dict) -> tuple[list[str], list[str]]:
    """Front-loaded positives and symmetric negatives for one boosted regen.

    In: the gate and the mismatching attributes. Out: ``(boost_bits,
    neg_bits)`` — the phrases to prepend to the prompt and the colours to push
    away. Hair and skin go through the bible service's heritage-neutral
    phrasing so an 'olive' spec does not re-inject 'Mediterranean' to fight the
    heritage token.
    """
    spec = gate.spec
    params = gate.ctx.params
    boost_bits: list[str] = []
    neg_bits: list[str] = []
    if 'eye_color' in mismatches:
        _ec = spec['eye_color']
        boost_bits.append(f'striking {_ec} eyes, vivid {_ec} irises')
        neg_bits.append(eye_negatives(gate, _ec))
    if 'hair_color' in mismatches:
        boost_bits.append(f'{spec["hair_color"]} hair')
        # Symmetric hair negative on the reroll (2026-07-22):
        # a bare positive 'brown hair' lost to the dark prior
        # every time; push the contradicting colours away too.
        try:
            from zyg_workflows import character_bible_service as _cbs_hn

            _hn = _cbs_hn.hair_color_negatives(
                spec['hair_color'],
                (params or {}).get('ethnic_heritage'),
            )
            if _hn:
                neg_bits.append(_hn)
        except Exception as _exc:
            _zyg_log.warning('hair colour negatives unavailable, the attribute reroll runs without them: %s', _exc)
    if 'skin_tone' in mismatches:
        # Use describe_skin_tone (heritage-neutral swap) not the
        # raw phrase dict, so an 'olive' spec does not re-inject
        # 'Mediterranean' to fight the heritage token — and add
        # the symmetric skin negative so the reroll actively
        # pushes AWAY from the delivered wrong-direction tone
        # (2026-07-21), mirroring eye_negatives for eyes.
        try:
            from zyg_workflows import character_bible_service as _cbs_sk

            boost_bits.append(
                _cbs_sk.describe_skin_tone(
                    spec['skin_tone'],
                    (params or {}).get('ethnic_heritage'),
                )
                or f'{spec["skin_tone"]} skin tone',
            )
            _skn = _cbs_sk.skin_tone_negatives(
                spec['skin_tone'],
                (params or {}).get('ethnic_heritage'),
            )
            if _skn:
                neg_bits.append(_skn)
        except Exception:
            boost_bits.append(f'{spec["skin_tone"]} skin tone')
    return boost_bits, neg_bits


def open_attr_gate(ctx: AnchorCtx, cgs, avj, spec: dict, retries: int) -> AttrGate:
    """Start the gate: fresh breaker, first verdict, two scratch anchors.

    In: the anchor ctx, the generation service, the judge module, the spec and
    the number of boosted retries allowed. Out: the :class:`AttrGate` the rungs
    work on. ``ctx.anchor_replaced`` and ``ctx.attr_reinstall_bound`` are bound
    here — the dedup re-check and the structure gate read those sentinels to
    tell "the gate ran" from "the gate never ran".
    """
    # Fresh breaker state: the module-level tier breaker is shared
    # with the per-tile judge and survives across runs in the
    # long-lived GUI process — stale dead-tier state must not
    # silently no-op this gate.
    try:
        avj.reset_tier_errors()
    except Exception as _exc:
        _zyg_log.warning('vlm tier breaker not reset, a stale dead tier may no-op the attribute gate: %s', _exc)
    ctx.anchor_replaced = False
    ctx.attr_reinstall_bound = True
    gate = AttrGate(
        ctx=ctx,
        cgs=cgs,
        avj=avj,
        spec=spec,
        eye_colors=tuple(getattr(avj, 'EYE_VOCAB', _EYE_VOCAB_FALLBACK)),
        retries=retries,
        best_anchor=ctx.cell_path + '.attr_best.png',
        pregate_anchor=ctx.cell_path + '.attr_orig.png',
    )
    verdict = judge_anchor(gate)
    if verdict.get('unverifiable') and ctx.log_fn:
        ctx.log_fn(
            'Attribute gate: skipping unverifiable spec value(s): '
            + ', '.join(f"{a}='{spec.get(a)}'" for a in verdict['unverifiable']),
        )
    shutil.copy2(ctx.cell_path, gate.best_anchor)
    shutil.copy2(ctx.cell_path, gate.pregate_anchor)
    gate.verdict = verdict
    gate.orig_verdict = dict(verdict)
    gate.best_verdict = dict(verdict)
    return gate


def restore_best(gate: AttrGate) -> None:
    """Put the best verified anchor back on disk.

    Full restore: file AND face crop AND verdict must stay in lockstep — a
    stale face crop mixes identity sources for every downstream IPA/QC
    consumer.
    """
    shutil.copy2(gate.best_anchor, gate.ctx.cell_path)
    _reinstall_anchor(gate.ctx)
    gate.verdict = dict(gate.best_verdict)


def run_boosted_retries(gate: AttrGate) -> None:
    """Re-generate the anchor with the failing attributes front-loaded.

    In: a freshly opened gate. Out: nothing — ``gate.verdict`` ends on the
    anchor that is actually on disk, which is never worse (more mismatches)
    than any anchor seen during the loop. A failed generation or a VLM that
    goes away mid-loop restores the best verified anchor rather than shipping
    an unverified one.
    """
    ctx = gate.ctx
    log_fn = ctx.log_fn
    rounds = 0
    while gate.verdict.get('mismatches') and rounds < gate.retries:
        rounds += 1
        _mm = gate.verdict['mismatches']
        if log_fn:
            log_fn(
                'Attribute gate: anchor mismatch — '
                + ', '.join(f"{a}: spec '{gate.spec[a]}' got '{v or '?'}'" for a, v in _mm.items())
                + f' — regenerating with boosted tokens ({rounds}/{gate.retries})',
            )
        _boost_bits, _neg_bits = boost_tokens(gate, _mm)
        _at_kw = dict(ctx.gen_kwargs)
        _at_kw['seed'] = int(uuid.uuid4().int % (2**31))
        _negs = ', '.join(b for b in _neg_bits if b)
        if _negs:
            _at_kw['extra_negative'] = merge_negative(_at_kw.get('extra_negative'), _negs)
        _at_prompt = f'{", ".join(_boost_bits)}, {ctx.prompt}' if _boost_bits else ctx.prompt
        _at_ok, _at_b = gate.cgs.generate_still(ctx.cell_path, _at_prompt, **_at_kw)
        if not _at_ok or not os.path.isfile(ctx.cell_path):
            if log_fn:
                log_fn(f'Attribute gate: retry generation failed ({_at_b}) — keeping best anchor so far')
            restore_best(gate)
            break
        ctx.anchor_replaced = True
        _reinstall_anchor(ctx)
        gate.verdict = judge_anchor(gate)
        if not gate.verdict.get('checked'):
            # Transient VLM failure mid-loop: an UNVERIFIED regen
            # must never ship as if it had zero mismatches.
            if log_fn:
                log_fn('Attribute gate: VLM unavailable on re-check — restoring best verified anchor')
            restore_best(gate)
            break
        if len(gate.verdict.get('mismatches') or {}) < len(gate.best_verdict.get('mismatches') or {}):
            shutil.copy2(ctx.cell_path, gate.best_anchor)
            gate.best_verdict = dict(gate.verdict)
    # Never ship a retry that ended WORSE than an earlier anchor.
    if len(gate.verdict.get('mismatches') or {}) > len(gate.best_verdict.get('mismatches') or {}):
        restore_best(gate)
    try:
        os.remove(gate.best_anchor)
    except OSError as _exc:
        _zyg_log.debug('best-anchor scratch copy not removed: %s', _exc)


def iris_edit_prompt(spec_color: str) -> str:
    """The qwen edit prompt that recolours the irises and changes nothing else.

    In: the specified eye colour. Out: the edit instruction. The 'naturally
    muted / desaturated' wording is load-bearing (2026-07-17): the plain
    recolour prompt produced neon contact-lens irises on run 1415cfdf (Iris
    Howard) — colour-label-correct, so the VLM accepted them, and the garish
    eyes seeded all 48 tiles.
    """
    return (
        f"Change the person's eye colour so that both irises are a "
        f'natural, realistic {spec_color} — muted and desaturated like real '
        f'human eyes, with darker limbal rings, natural iris fibre '
        'detail and normal pupil, NOT bright, glowing or saturated. '
        'Keep everything else exactly identical: the same '
        'face, the same skin tone and complexion (do not lighten or change '
        'the skin colour), the same hairstyle, clothing, pose, lighting and '
        'plain studio background, and the exact same framing and camera '
        'distance — do not zoom in or out'
    )


def iris_fix_kwargs(gate: AttrGate, spec_color: str) -> dict:
    """Generation kwargs for the targeted iris recolour edit.

    In: the gate and the specified eye colour. Out: a copy of the run's
    gen_kwargs switched to the qwen edit workflow on the current anchor, with
    the wrong-colour and anti-neon negatives MERGED into whatever negatives the
    run already carried (the skin-tone defence among them).
    """
    kw = dict(gate.ctx.gen_kwargs)
    kw['seed'] = int(uuid.uuid4().int % (2**31))
    kw['reference_image'] = gate.ctx.cell_path
    kw['force_workflow'] = 'qwen_edit_angle'
    kw.pop('flux_guidance', None)
    kw['extra_negative'] = merge_negative(kw.get('extra_negative'), eye_negatives(gate, spec_color))
    kw['extra_negative'] = merge_negative(kw['extra_negative'], _IRIS_NEGATIVES)
    return kw


def iris_recolour_rung(gate: AttrGate) -> None:
    """Last rung: recolour the irises with a targeted qwen edit.

    In: the gate after the boosted retries. Out: nothing — on a verified
    improvement the edited image becomes the anchor and ``gate.verdict`` its
    verdict. Eye colour is a local edit qwen does well and it preserves the
    anchor the operator is about to approve in every other respect. Skipped on
    resume (verify-only): the cells already cloned the delivered irises; the
    bible sync records reality. Only a STRICT improvement is accepted — the eye
    fixed and no NEW mismatch introduced — because an edit that recolours
    irises but lightens the skin trades one defect for another.
    """
    ctx = gate.ctx
    log_fn = ctx.log_fn
    if ctx.cell0_reused or not (gate.verdict.get('mismatches') or {}).get('eye_color'):
        return
    try:
        _qwen_fix_ok = bool(gate.cgs.has_qwen_edit_angles())
    except Exception:
        _qwen_fix_ok = False
    if not _qwen_fix_ok:
        return
    _ec = gate.spec['eye_color']
    if log_fn:
        log_fn(f'Attribute gate: recolouring irises to {_ec} via targeted qwen edit')
    _fx_path = ctx.cell_path + '.attrfix.png'
    _fx_kw = iris_fix_kwargs(gate, _ec)
    _fx_ok, _fx_b = gate.cgs.generate_still(_fx_path, iris_edit_prompt(_ec), **_fx_kw)
    if _fx_ok and os.path.isfile(_fx_path):
        _fx_verdict = gate.avj.judge_attributes(_fx_path, gate.spec, log_fn=log_fn)
        if (
            _fx_verdict.get('checked')
            and 'eye_color' not in (_fx_verdict.get('mismatches') or {})
            and set(_fx_verdict.get('mismatches') or {}) <= (set(gate.verdict.get('mismatches') or {}) - {'eye_color'})
        ):
            shutil.copy2(_fx_path, ctx.cell_path)
            ctx.anchor_replaced = True
            _reinstall_anchor(ctx)
            gate.verdict = _fx_verdict
            if log_fn:
                log_fn(f'Attribute gate: iris recolour accepted ({_fx_b})')
        elif log_fn:
            log_fn('Attribute gate: iris recolour did not verify — keeping previous anchor')
    elif log_fn:
        log_fn(f'Attribute gate: iris recolour generation failed ({_fx_b})')
    try:
        os.remove(_fx_path)
    except OSError as _exc:
        _zyg_log.debug('iris recolour scratch image not removed: %s', _exc)


def style_recheck(gate: AttrGate) -> None:
    """Re-check texture when the gate replaced the anchor.

    In: the gate. Out: nothing — a gate replacement bypassed the
    style/luminance gates, so the texture floor is applied again here and a
    replacement that regressed into semi-render territory is rolled back to the
    pre-gate anchor, verdict included.
    """
    ctx = gate.ctx
    if not (ctx.anchor_replaced and ctx.photoreal and ctx.style_gate_on):
        return
    _sg2_pass, _sg2_why = _anchor_style_check(ctx)
    if _sg2_pass:
        return
    if ctx.log_fn:
        ctx.log_fn(
            f'Attribute gate: replacement anchor failed style recheck ({_sg2_why}) — restoring pre-gate anchor',
        )
    shutil.copy2(gate.pregate_anchor, ctx.cell_path)
    _reinstall_anchor(ctx)
    gate.verdict = dict(gate.orig_verdict)


def clear_scratch(gate: AttrGate) -> None:
    """Delete the gate's two scratch anchors; an already-gone one is fine."""
    for _tmp_anchor in (gate.best_anchor, gate.pregate_anchor):
        try:
            os.remove(_tmp_anchor)
        except OSError as _exc:
            _zyg_log.debug('attribute gate scratch anchor %s not removed: %s', _tmp_anchor, _exc)
