# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The attribute compliance gate (2026-07-16) and the dedup re-check.

Moved verbatim out of contact_sheet_pipeline_steps.py (lines 661-1174).
"""

from __future__ import annotations

import os
from .anchor_ctx import AnchorCtx, _dedup_most_similar
from .anchor_attribute_gate_rungs import (
    attribute_spec,
    clear_scratch,
    iris_recolour_rung,
    load_attr_judge,
    open_attr_gate,
    run_boosted_retries,
    style_recheck,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.contact_sheet_pipeline_steps')


def step_attribute_gate(ctx: AnchorCtx) -> None:
    """VLM attribute compliance on the anchor (eye/hair/skin colour)."""
    from zyg_workflows import comfy_generation_service as _cgs

    # ── ATTRIBUTE COMPLIANCE GATE (2026-07-16) ──────────────────────
    # FLUX ignores weak attribute tokens: two consecutive runs shipped
    # brown-eyed anchors against a green-eyed spec, and the qwen cells
    # clone the anchor's face verbatim — one wrong anchor = 48 wrong
    # cells + a wrong LoRA. VLM-read the delivered anchor vs the spec;
    # on mismatch retry with failing attributes front-loaded + wrong-
    # colour negatives; last rung recolours the irises with a targeted
    # qwen edit; whatever finally ships is synced back to the bible so
    # scene prompts never fight the LoRA.
    _attr_gate_on = os.environ.get(
        'ZYG_ANCHOR_ATTR_GATE',
        '1',
    ).strip().lower() not in ('0', 'false', 'no', 'off')
    _attr_spec = attribute_spec(ctx.params)
    if not (_attr_gate_on and ctx.photoreal and _attr_spec):
        return
    _avj = load_attr_judge()
    if _avj is None:
        return

    # Verify-only on resume: judge + bible-sync still run, but
    # no boosted regens (the anchor cannot change anymore).
    _attr_retries = (
        0
        if ctx.cell0_reused
        else max(
            0,
            int(os.environ.get('ZYG_ANCHOR_ATTR_RETRIES', '2')),
        )
    )
    gate = open_attr_gate(ctx, _cgs, _avj, _attr_spec, _attr_retries)
    run_boosted_retries(gate)
    iris_recolour_rung(gate)
    style_recheck(gate)
    clear_scratch(gate)

    _attr_sync_verdict(ctx, gate.verdict, _attr_spec)


def _attr_sync_verdict(ctx: AnchorCtx, _attr_verdict: dict, _attr_spec: dict) -> None:
    """Record the attribute verdict; make delivered reality authoritative."""
    char_id = ctx.char_id
    params = ctx.params
    log_fn = ctx.log_fn
    progress_job = ctx.progress_job
    _cell0_reused = ctx.cell0_reused

    if _attr_verdict.get('checked'):
        if progress_job is not None:
            progress_job['anchor_attributes'] = {
                'observed': _attr_verdict.get('observed') or {},
                'mismatches': _attr_verdict.get('mismatches') or {},
            }
        if _attr_verdict.get('mismatches'):
            _mm_txt = ', '.join(
                f"{a}='{v or '?'}' vs spec '{_attr_spec[a]}'" for a, v in _attr_verdict['mismatches'].items()
            )
            _synced_now = {a: v for a, v in _attr_verdict['mismatches'].items() if v and v not in ('unclear', 'other')}
            # Record the delta for the review-card disclosure on
            # BOTH paths (strict-park and ship-and-sync) — this is
            # display-only and never overwrites the selected value.
            _deltas = params.setdefault('_attr_deltas', {})
            for _a, _v in _synced_now.items():
                _deltas[_a] = {
                    'selected': _attr_spec.get(_a),
                    'delivered': _v,
                }
            # STRICT ATTRIBUTES (2026-07-20, opt-in): default is
            # ship-and-sync (FLUX often can't hit a colour under a
            # strong heritage prior, and a synced bible keeps the
            # LoRA coherent). ZYG_STRICT_ATTRIBUTES=1 instead PARKS
            # the run when boosted retries could not deliver the
            # SELECTED colours. The park MUST happen BEFORE the
            # bible sync + params overwrite below — otherwise the
            # authoritative bible is already rewritten to the
            # delivered colour (attributes_synced_from_anchor makes
            # it sticky), and a re-roll could never recover the
            # operator's selection the strict gate exists to protect.
            _strict_attrs = os.environ.get(
                'ZYG_STRICT_ATTRIBUTES',
                '0',
            ).strip().lower() in ('1', 'true', 'yes', 'on')
            if _strict_attrs and _synced_now and not _cell0_reused:
                _strict_txt = ', '.join(
                    f"{a}: got '{v}' vs selected '{_attr_spec.get(a)}'" for a, v in _synced_now.items()
                )
                if log_fn:
                    log_fn(
                        'Attribute gate: STRICT mode — boosted retries '
                        f'could not deliver selected attributes ({_strict_txt}) '
                        '— parking for operator WITHOUT clobbering the selected '
                        'spec (ZYG_STRICT_ATTRIBUTES=0 to ship-and-sync)',
                    )
                from zyg_workflows import pipeline_control as _pc_attr

                raise _pc_attr.PipelinePaused(
                    char_id,
                    f'strict attributes unmet: {_strict_txt}',
                )
            # SHIP-AND-SYNC (default): FLUX shipped the closest
            # anchor; make delivered reality authoritative so the
            # LoRA and downstream prompts are coherent.
            # EXCEPTION (2026-07-21): never sync an EXPLICITLY
            # chosen skin_tone away to the delivered tone — a
            # light-skinned member of a dark heritage is a valid
            # request, and syncing would surrender skin authority
            # to the heritage prior (the very coupling we removed).
            # The delta is still recorded above for disclosure;
            # the bible/params keep the requested tone so scenes
            # and future regens keep aiming for it.
            # Same rule for EXPLICIT hair colour (2026-07-22):
            # brown under a dark-hair heritage is a valid request,
            # not drift — never sync it away to the delivered black.
            _skin_explicit = not bool((params or {}).get('_skin_tone_was_auto', True))
            _hair_explicit = not bool((params or {}).get('_hair_color_was_auto', True))
            _syncable = {
                a: v
                for a, v in _synced_now.items()
                if not (a == 'skin_tone' and _skin_explicit) and not (a == 'hair_color' and _hair_explicit)
            }
            for _ax, _flag, _spec_key in (
                ('skin_tone', _skin_explicit, 'skin_tone'),
                ('hair_color', _hair_explicit, 'hair_color'),
            ):
                if _flag and _ax in _synced_now and log_fn:
                    log_fn(
                        f"Attribute gate: keeping the operator's explicit {_ax} "
                        f"'{_attr_spec.get(_spec_key)}' as truth (delivered "
                        f"'{_synced_now[_ax]}' NOT synced) — disclosed on the review card",
                    )
            if log_fn and _syncable:
                log_fn(
                    f'Attribute gate: shipping anchor with non-spec attributes ({_mm_txt}) '
                    '— syncing bible to delivered reality so scene prompts match the LoRA',
                )
            try:
                from zyg_workflows import character_bible_service as _cbs_attr

                _cbs_attr.sync_delivered_attributes(
                    char_id,
                    _syncable,
                    log_fn=log_fn,
                )
            except Exception as _bs_exc:
                if log_fn:
                    log_fn(f'Bible attribute sync failed ({_bs_exc})')
            # SPLIT-BRAIN FIX (2026-07-20): the bible sync above
            # wrote delivered colours into the bible, but the
            # in-flight `params` dict still held the SELECTED
            # colours — so QC-repair tile regens and captions kept
            # prompting 'hazel eyes' while every anchor-cloned
            # tile showed the delivered brown (Ivy Rossi audit:
            # regen tiles drifted off-spec vs their siblings).
            # Delivered reality wins downstream — EXCEPT an
            # explicit skin tone (see _syncable above), which
            # stays as requested so regens/captions keep aiming
            # for it rather than the heritage-driven delivered tone.
            for _a, _v in _syncable.items():
                params[_a] = _v
            if log_fn and _syncable:
                log_fn(
                    'Attribute gate: run params updated to delivered '
                    'reality for downstream regens/captions ('
                    + ', '.join(f'{k}={v}' for k, v in _syncable.items())
                    + ')',
                )
        elif log_fn:
            _obs = _attr_verdict.get('observed') or {}
            log_fn(
                'Attribute gate OK — anchor matches spec (' + ', '.join(f'{k}={v}' for k, v in _obs.items() if v) + ')',
            )


def step_dedup_recheck(ctx: AnchorCtx) -> None:
    """Dedup re-check after the attribute gate (2026-07-18).

    Boosted attribute regens replace the anchor AFTER the dedup decision and
    were never re-measured — run 59f1f012 shipped at 0.508 although the gate
    approved 0.465. The value lands in _anchor_dedup for the metrics file.
    """
    params = ctx.params
    char_id = ctx.char_id
    log_fn = ctx.log_fn
    _cell0_reused = ctx.cell0_reused
    _dedup_on = ctx.dedup_on
    anchor_face = ctx.anchor_face

    if ctx.anchor_replaced is None or ctx.dedup_others is None:
        # The dedup gate never collected candidates, or the attribute gate
        # never ran: inline, this block hit an unbound name and skipped.
        _zyg_log.debug('dedup re-check skipped, its helpers are not bound on this path')
        return
    try:
        if _dedup_on and ctx.anchor_replaced and anchor_face and os.path.isfile(anchor_face):
            _dd2 = _dedup_most_similar(anchor_face, ctx.dedup_others, ctx.dedup_max_sim, ctx.dedup_max_sim_arch)
            if _dd2['sim'] >= 0:
                params['_anchor_dedup'] = {
                    'max_sim': round(_dd2['sim'], 3),
                    'vs': _dd2['cid'] or None,
                    'vs_archived': bool(_dd2['archived']),
                    'ceiling': _dd2['ceiling'],
                    'post_attr_regen': True,
                }
                # ENFORCE the ceiling after attribute regens (2026-07-22):
                # the hair/skin regens produce a NEW anchor that was never
                # re-deduped, so a duplicate could ship (Maren 0.597 vs
                # Noor, over the 0.52 ceiling, only 'flagged'). Park BEFORE
                # 47 tiles + a LoRA burn on a duplicate character. Only a
                # SIGNIFICANT breach parks (margin > tol) so a hairline
                # 0.001 overshoot still ships; env-off ZYG_DEDUP_ENFORCE_POST_REGEN=0.
                _dd_enforce = os.environ.get(
                    'ZYG_DEDUP_ENFORCE_POST_REGEN',
                    '1',
                ).strip().lower() not in ('0', 'false', 'no', 'off')
                _dd_tol = float(os.environ.get('ZYG_DEDUP_ENFORCE_TOL', '0.02'))
                if _dd2['margin'] > _dd_tol and _dd_enforce and not _cell0_reused:
                    if log_fn:
                        log_fn(
                            f'Dedup re-check after attribute regens: sim {_dd2["sim"]:.3f} '
                            f'vs {_dd2["cid"]} EXCEEDS ceiling {_dd2["ceiling"]:g} by '
                            f'{_dd2["margin"]:.3f} — PARKING before tile generation '
                            '(duplicate character; reroll or decline). '
                            'ZYG_DEDUP_ENFORCE_POST_REGEN=0 to ship-and-flag instead.',
                        )
                    from zyg_workflows import pipeline_control as _pc_dd2

                    raise _pc_dd2.PipelinePaused(
                        char_id,
                        f'duplicate anchor after attribute regens: {_dd2["sim"]:.3f} vs '
                        f'{_dd2["cid"]} (ceiling {_dd2["ceiling"]:g})',
                    )
                if log_fn:
                    if _dd2['margin'] > 0:
                        log_fn(
                            f'Dedup re-check after attribute regens: sim '
                            f'{_dd2["sim"]:.3f} vs {_dd2["cid"]} EXCEEDS ceiling '
                            f'{_dd2["ceiling"]:g} by {_dd2["margin"]:.3f} — flagged for review',
                        )
                    else:
                        log_fn(f'Dedup re-check after attribute regens OK (sim {_dd2["sim"]:.3f})')
    except NameError as _exc:
        _zyg_log.debug('dedup re-check skipped, its helpers are not bound on this path: %s', _exc)
    except Exception as _dd2_exc:
        if log_fn:
            log_fn(f'Dedup re-check skipped ({_dd2_exc})')
