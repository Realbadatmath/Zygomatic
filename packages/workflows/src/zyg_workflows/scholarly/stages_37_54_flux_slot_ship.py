# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Part 3 of a Stage 3.5 slot: what happens to the frame the ladder picked.

The last third of the 646-line `generate_one`, in its original order:

* `repair_typography` — repaint flagged lettering instead of re-rolling the
  whole slot, and unflag the winning record when it worked;
* `repair_era_regions` — the same for small, boxed anachronisms (a wristwatch,
  a bulb, a sneaker), re-asking the gate's own question on the repaired crop;
* `summarize_slot_review` — which judge looked at the winner, its score, and
  the `SHIPPED FLAGGED` warning with the kind of defect that survived;
* `canonicalize_winner` — the winner becomes `flux_NNN.jpg` and the losing
  attempt files are deleted, so Stage 6's sorted glob cannot shift;
* `publish_slot` — the IPAdapter and ControlNet registrations, the focal point
  the next slot composes against, the `_flux_image_meta` entry and the receipt.

Both repairs run HERE rather than in the Stage 3.6 sweep because FLUX is still
resident at this point; the sweep runs after the worker has stood down, and
reloading the model to fix a patch would cost more than the patch is worth.
"""

import logging as _zyg_logging
import os

from zyg_workflows.stage_runner import _log_prompt
from zyg_workflows.subscription_llm import (
    api_key_or_login as _llm_key,
)

# The monolith's logger name, not `__name__`, so every debug line of one run
# stays under `zyg_workflows.pipeline_scholarly`.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')


def _winner_record(qa_attempts, best_path):
    """Return `(record, issues)` for the attempt that produced *best_path*.

    In: the slot's attempt records and the winning path. Out: that record (or
    None when the path is not among them) and a fresh list of its issues, which
    is what both repairs edit when they clear a flag.
    """
    _rec = next((_r for _r in qa_attempts if _r.get('path') == best_path), None)
    return _rec, list((_rec or {}).get('issues') or [])


def repair_typography(fs, ctx, plan, best_path, qa_attempts, repair_pipe):
    """Repaint readable lettering out of the winning frame; True when it took.

    In: the winning path, the slot's attempt records and the pipe the ladder
    left resident (None on the ComfyGen path, where only the classical strategy
    is available). Out: whether the frame was repaired — and if it was, the
    winning record loses its typography issue, so the slot no longer counts as
    a flagged shipment.

    The ladder's answer to lettering is to re-roll the whole slot, which throws
    away a composition that was fine except for a few square centimetres. The
    OCR judge already hands back a BOX for every flag, so when the ladder has
    run out of rungs, repaint just that region and keep the rest of the frame.
    It is verified twice before it is allowed to replace anything — the frame
    must read clean AND the repaint must look like the material around it.
    Without the second check FLUX painted flat white bars across a map and a
    hole through a question mark: no readable text, and far worse than what it
    replaced.
    """
    _debug = ctx._debug
    _log = ctx._log
    idx = plan.idx
    _repair_ok = False
    try:
        _win_rec0, _win_iss0 = _winner_record(qa_attempts, best_path)
        _typo_left = any('typography' in _i for _i in _win_iss0)
        if _typo_left and fs._TYPO_REPAIR_ENABLED and os.path.exists(best_path):
            from zyg_workflows import typography_repair as _trep_sch

            _rr = _trep_sch.repair(
                best_path,
                None,
                pipe=repair_pipe,
                seed=(plan.gen_seed + 97) % (2**31),
                log=lambda m: _debug('Stage 3.5', f'Slot {idx}: {m}'),
            )
            fs._ladder_stats['repair_tried'] += 1
            if _rr.get('repaired'):
                _repair_ok = True
                fs._ladder_stats['repair_ok'] += 1
                fs._slot_review[idx]['repaired'].append('typography')
                _log(
                    'INFO',
                    'Stage 3.5',
                    f'Slot {idx}: lettering REPAIRED in place '
                    f'({_rr.get("strategy")}, {_rr.get("rounds")} round(s), '
                    f'{_rr.get("mask_area_frac", 0) * 100:.1f}% repainted) — '
                    f'composition kept instead of re-rolled',
                )
                # the frame is clean now, so it is no longer
                # a flagged shipment
                if _win_rec0 is not None:
                    _win_rec0['issues'] = [_i for _i in _win_iss0 if 'typography' not in _i]
            else:
                _log(
                    'INFO',
                    'Stage 3.5',
                    f'Slot {idx}: region repair declined — {str(_rr.get("reason"))[:90]}',
                )
    except Exception as _rp_e:
        _debug('Stage 3.5', f'Slot {idx}: region repair failed ({_rp_e!r})', level='WARN')
    return _repair_ok


def repair_era_regions(fs, ctx, plan, best_path, qa_attempts):
    """Repaint small, boxed anachronisms out of the winning frame.

    In: the winning path and the slot's attempt records. Out: nothing — on
    success the winning record loses its anachronism issue and the era-repair
    counters move.

    A wristwatch, a bulb, a sneaker: the composition is fine and a few square
    centimetres are wrong. The gate hands back a bbox for every flag; when the
    winner is still flagged and every remaining anachronism is small and boxed,
    repaint those regions through the Qwen inpaint graph and re-ask the SAME
    question on the repaired crop. Accepted only if it now answers 'no', and a
    single declined region abandons the whole repair.
    """
    _debug = ctx._debug
    _log = ctx._log
    idx = plan.idx
    try:
        _win_rec_e, _win_iss_e = _winner_record(qa_attempts, best_path)
        _era_left = any('anachronism' in _i for _i in _win_iss_e)
        _era_flags_w = [
            f for f in (fs._era_last_flags.get(idx) or []) if f.get('id') not in ('gore_wound_bone', 'subject_present')
        ]
        if (
            _era_left
            and _era_flags_w
            and os.path.exists(best_path)
            and os.environ.get('ZYG_SCHOLARLY_ERA_REPAIR', '1').lower() not in ('0', 'false', 'no')
            and all(f.get('small') and f.get('bbox') for f in _era_flags_w)
        ):
            from zyg_workflows import era_gate as _eg_rep

            fs._ladder_stats['era_repair_tried'] += 1
            _fixed_all = True
            for _f_rep in _era_flags_w:
                _rr_e = _eg_rep.region_repair(
                    best_path,
                    _f_rep,
                    ctx._era_lock,
                    seed=(plan.gen_seed + 131) % (2**31),
                    log=lambda m: _debug('Stage 3.5', f'Slot {idx}: {m}'),
                    judge_kwargs={
                        'tier': os.environ.get('ZYG_SCHOLARLY_VLM_TEXT_TIER', 'resident'),
                        'api_key': _llm_key(),
                        'api_model': fs._VLM_TEXT_MODEL,
                    },
                )
                if not _rr_e.get('repaired'):
                    _fixed_all = False
                    _log(
                        'INFO',
                        'Stage 3.5',
                        f'Slot {idx}: era region repair declined for {_f_rep["id"]} — {str(_rr_e.get("reason"))[:80]}',
                    )
                    break
            if _fixed_all:
                fs._ladder_stats['era_repair_ok'] += 1
                fs._slot_review[idx]['repaired'].append('era')
                _log(
                    'INFO',
                    'Stage 3.5',
                    f'Slot {idx}: {len(_era_flags_w)} small anachronism(s) '
                    f'REPAIRED in place ({", ".join(f["id"] for f in _era_flags_w)}) '
                    f'— composition kept',
                )
                if _win_rec_e is not None:
                    _win_rec_e['issues'] = [_i for _i in _win_iss_e if 'anachronism' not in _i]
    except Exception as _er_e:
        _debug('Stage 3.5', f'Slot {idx}: era region repair failed ({_er_e!r})', level='WARN')


def defect_kind(issues):
    """Name the one defect a flagged shipment is reported under.

    In: the winning attempt's issue strings. Out: the single word the warning
    and the state file carry. The order is the order of severity the ladder
    works in — typography first, then anachronism, gore, subject, anatomy — so
    a frame with two flags is reported under the worse of them, and anything
    unrecognised is 'defect' rather than silence.
    """
    for _needle, _name in (
        ('typography', 'typography'),
        ('anachronism', 'anachronism'),
        ('gore:', 'gore'),
        ('subject:', 'subject'),
        ('anatomy', 'anatomy'),
    ):
        if any(_needle in _i for _i in issues):
            return _name
    return 'defect'


def summarize_slot_review(fs, ctx, plan, best_path, best_qa_score, qa_attempts):
    """Record what the winning frame was judged by, and warn when it still fails.

    In: the winning path and score plus the slot's attempt records. Out: nothing
    — `fs._slot_review[idx]` gains the winner's attempt number, score, per-judge
    verdicts and surviving flags, and a still-defective winner is logged as
    SHIPPED FLAGGED and appended to `fs._shipped_flagged`.

    Best-of-N ships — but say so when the winner is still defective. Run
    7033208f shipped five slots with visible gibberish text and the only way to
    discover that was to replay the log by hand, because the retry ladder
    logged each attempt and never logged its verdict.
    """
    idx = plan.idx
    try:
        _win_rec, _win_iss = _winner_record(qa_attempts, best_path)
        # Slot review: what the WINNING attempt was actually
        # checked by, its score, and anything still flagged.
        try:
            _rv = fs._slot_review[idx]
            _wa = int((_win_rec or {}).get('attempt', 0))
            _rv['winner_attempt'] = _wa
            _rv['score'] = round(float(best_qa_score), 3)
            for _k in ('anatomy', 'typography', 'era'):
                _rv[_k] = _rv.get(f'{_k}_a{_wa}', 'unreviewed')
            _rv['flagged'] = [str(_i)[:60] for _i in _win_iss]
            _rv['anatomy_shot'] = bool(plan.is_anatomy_shot)
        except (KeyError, IndexError, TypeError, ValueError) as _exc:
            _zyg_log.debug('slot %s review summary left incomplete: %s', idx, _exc)
        if _win_iss:
            _kind = defect_kind(_win_iss)
            ctx._log(
                'WARNING',
                'Stage 3.5',
                f'Slot {idx} SHIPPED FLAGGED after '
                f'{len(qa_attempts)} attempt(s) — best score '
                f'{best_qa_score:.2f}, unresolved {_kind}: '
                f'{"; ".join(_win_iss)[:120]}',
            )
            fs._shipped_flagged.append(
                {
                    'slot': idx,
                    'attempts': len(qa_attempts),
                    'score': round(float(best_qa_score), 2),
                    'kind': _kind,
                    'issues': _win_iss[:3],
                }
            )
    except (KeyError, IndexError, TypeError, ValueError) as _exc:
        _zyg_log.debug(
            'slot %s QA bookkeeping failed — the winning image still ships: %s',
            idx,
            _exc,
        )


def canonicalize_winner(fs, ctx, plan, best_path, qa_attempts):
    """Rename the winner to `flux_NNN.jpg` and delete the losing attempts.

    In: the winning path and the slot's attempt records. Out: the path that
    ships — the canonical one, or the original when the rename failed.

    The folder must hold exactly one image per slot: stray retry files would
    interleave into Stage 6's sorted-glob rescue path and shift every later
    image off its narration window.
    """
    _canon_p = os.path.join(fs._flux_images_dir, f'flux_{plan.idx:03d}.jpg')
    try:
        if best_path != _canon_p:
            os.replace(best_path, _canon_p)
        for _qa_rec in qa_attempts:
            _qa_fp = _qa_rec.get('path', '')
            if _qa_fp and _qa_fp not in (best_path, _canon_p) and os.path.exists(_qa_fp):
                try:
                    os.remove(_qa_fp)
                except OSError as _exc:
                    _zyg_log.debug('losing attempt %s not deleted: %s', _qa_fp, _exc)
        best_path = _canon_p
    except OSError as _canon_e:
        ctx._debug('Stage 3.5', f'Slot {plan.idx}: canonical rename failed: {_canon_e}', level='WARN')
    return best_path


def publish_slot(fs, ctx, plan, out_p, best_qa_score, qa_attempts, steps_attempt):
    """Register the shipped frame everywhere the rest of the run reads it, and return it.

    In: the canonical path, the winning score, the slot's attempt records and
    the step count the winning attempt actually used. Out: the same path, after
    the first-seen subject has been registered as an IPAdapter reference, its
    pose cached for ControlNet, the focal point extracted for the next slot's
    composition, the `_flux_image_meta` entry appended and the prompt receipt
    written.
    """
    _debug = ctx._debug
    idx = plan.idx
    _n_attempts = len(qa_attempts)
    if _n_attempts > 1:
        ctx._log(
            'INFO',
            'Stage 3.5',
            f'Slot {idx}: {_n_attempts} attempts → best QA={best_qa_score:.2f} (using {os.path.basename(out_p)})',
        )

    # ── Stage 9: Register first-seen image as IPAdapter reference ─
    # On subsequent slots with the same subject, this image will be
    # used as appearance conditioning.
    if plan.tag in fs._IDENTITY_TAGS and fs._ipa_ready and fs._ipa is not None:
        _ipa_subj_key = plan.subj.lower().strip()[:40]
        fs._ipa.register_reference(_ipa_subj_key, out_p)

    # ── Stage 10: Cache pose for ControlNet ────────────────────
    # Extract pose from the best output and store it so the next
    # slot with the same subject gets spatially-guided generation.
    if plan.is_anatomy_shot and fs._cn_pipe is not None and fs._cns is not None:
        _cn_subj_key = plan.subj.lower().strip()[:40]
        if _cn_subj_key not in (fs._cns._pose_cache or {}):
            try:
                _extracted = fs._cns.extract_pose_image(out_p)
                if _extracted is not None:
                    fs._cns._pose_cache[_cn_subj_key] = _extracted
                    _debug('Stage 3.5', f'ControlNet: pose cached for "{_cn_subj_key}"')
            except Exception as _cn_cache_e:
                _debug('Stage 3.5', f'ControlNet pose cache error: {_cn_cache_e}', level='WARN')

        # ── Layer 3a: extract focal point for next image's composition ──
    try:
        from zyg_workflows import murch_engine as _me3a

        _fp = _me3a.extract_focal_point(out_p, ctx._murch_image_debug)
        fs._prev_focal_zone = _fp.get('zone', 'center')
        _debug(
            'Stage 3.5',
            f'Slot {idx}: focal={fs._prev_focal_zone} saliency={_fp.get("saliency_peak", 0):.2f}',
        )
    except Exception as _fpe:
        fs._prev_focal_zone = 'center'
        _debug('Stage 3.5', f'Focal point extraction failed slot {idx}: {_fpe}', level='WARN')

    fs._flux_image_meta.append(
        {
            'path': out_p,
            'index': idx,
            'prompt': plan.prompt,
            'subject': plan.subj,
            'tag': plan.tag,
            'shot_type': plan.shot_type,
            'emotion': plan.emotion,
            'narration_segment': plan.seg_preview,
            'source': 'flux',
            'model': plan.model_label,
            'pipeline_id': ctx.pipeline_id,
            'topic': ctx.topic,
            'essay_title': ctx._essay_title_for_prompt,
            'slot_seconds': round(idx * fs._slot_clock_total / max(ctx._n_flux_images, 1), 1),
            'seed': plan.gen_seed,
            'focal_zone': fs._prev_focal_zone,
            'counterpoint': plan.cp_used,
            'inference_steps': steps_attempt,
            'qa_score': round(best_qa_score, 3),
            'qa_attempts': _n_attempts,
            'qa_issues': qa_attempts[-1]['issues'] if qa_attempts else [],
        }
    )
    _log_prompt(
        'flux_image',
        'Stage 3.5',
        ctx.pipeline_id,
        plan.prompt,
        {
            'slot': idx,
            'subject': plan.subj,
            'tag': plan.tag,
            'shot_type': plan.shot_type,
            'emotion': plan.emotion,
            'seed': plan.gen_seed,
            'model': plan.model_label,
            'topic': ctx.topic,
            'counterpoint': plan.cp_used,
            'inference_steps': plan.n_steps,
            'qa_score': round(best_qa_score, 3),
        },
    )
    _debug(
        'Stage 3.5',
        f'Prompt slot {idx}: [{plan.tag}] "{plan.prompt[:100]}…" emotion={plan.emotion} shot={plan.shot_type}',
    )
    return out_p
