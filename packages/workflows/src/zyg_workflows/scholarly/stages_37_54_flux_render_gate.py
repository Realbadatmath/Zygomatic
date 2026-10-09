# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3.5 render gate: the era ladder, the per-slot era check and the gate itself.

Every function here is a nested `def` of `stage_11c_flux_image_loop` in
`stages_37_54`, hoisted to module level with its body unchanged. A closure read
its stage's locals for free; a module-level function cannot, so each one takes
two carriers and re-binds the names it reads in a glue block at the top, in the
head/tail glue style the rest of this package uses:

* `fs` — `FluxLoopState` from `stages_37_54_flux_state`: the per-run FLUX loop
  state (the stats dicts the gates count into, the judge models, the enable
  flags). The dicts and lists are the very objects the stage holds, so a gate
  mutating one is seen by the loop exactly as before;
* `ctx` — the pipeline's `RunContext`: the run inputs and the prologue closures
  (`_log`, `_debug`, `_done`, `_stage_start`, `_gate_receipt`).

A call from one hoisted function to another was a bare closure call, so it is
re-bound as `functools.partial(<fn>, fs, ctx)` and every call site inside the
body is the line the monolith ran.
"""

import functools as _ft
import os

from zyg_workflows.pipeline_scholarly import (
    _ANATOMY_Q_ORIGINAL,
    _ANATOMY_Q_SHIPPED,
    _PERSON_NOUN_RE,
)
from zyg_workflows.runtime import (
    _record_token_usage,
)
from zyg_workflows.subscription_llm import (
    api_key_or_login as _llm_key,
)
from zyg_workflows.scholarly import stages_37_54_flux_vlm_gates as _flux_vlm_gates

# No module logger here: none of the three bodies below logs through `logging`.
# They all report through `ctx._debug`, which is the prologue closure the
# monolith gave them.


def era_ladder_qualifier(fs, ctx, slot: int) -> str:
    """The positive period clause for this slot's last era flags."""
    _era_last_flags = fs._era_last_flags
    _era_lock = ctx._era_lock
    try:
        from zyg_workflows import era_gate as _eg_lq

        return _eg_lq.ladder_qualifier(_era_last_flags.get(slot) or [], _era_lock)
    except Exception:
        return ''


def era_gate_check(fs, ctx, image_path: str, prompt: str, slot: int | None) -> tuple:
    """(ok, reason) from the per-slot, prompt-derived, crop-based era gate.

    Items: the slot's pre-extracted checks (one Haiku call per batch,
    offline derivation as fallback) + the universal tells + the
    gore and subject-present questions. Judged on 3x2 enlarged
    tiles by Qwen3-VL when the card can hold it, else by the
    Anthropic vision model with the same tiles. None from both ->
    'unreviewed', never a pass.
    """
    _VLM_TEXT_MODEL = fs._VLM_TEXT_MODEL
    _debug = ctx._debug
    _era_gate_stats = fs._era_gate_stats
    _era_last_flags = fs._era_last_flags
    _era_lock = ctx._era_lock
    _era_slot_checks = fs._era_slot_checks
    _last_gate_outcome = fs._last_gate_outcome
    _sch_intensity = ctx._sch_intensity
    _slot_review = fs._slot_review
    _tx_api_dead = fs._tx_api_dead
    pipeline_id = ctx.pipeline_id
    from zyg_workflows import era_gate as _eg

    _sc = _era_slot_checks[slot] if (slot is not None and slot < len(_era_slot_checks)) else None
    if _sc is None:
        _sc = {
            'subject': _eg.subject_phrase_offline(prompt),
            'checks': _eg.derive_checks_offline(prompt, _era_lock),
            'source': 'offline',
        }
    _items = _eg.build_items(_sc, _era_lock, include_gore=_sch_intensity['rank'] < 2)
    # JUDGE ORDER (measured 2026-08-25, 40 Black Death frames,
    # 14-slot truth): the Anthropic vision judge catches what
    # Qwen3-VL-8B rationalises away ("clearly a traditional
    # sailing vessel" on a motor boat), and the local judge is
    # refused outright whenever ComfyUI is sampling — which is
    # most of the time on this box. API first when a key is
    # live; local Qwen3-VL is the no-key / no-credit fallback.
    _era_prefer = os.environ.get('ZYG_SCHOLARLY_ERA_JUDGE', 'api').strip().lower()
    _r = _eg.judge_frame(
        image_path,
        _items,
        _era_lock,
        tier=os.environ.get('ZYG_SCHOLARLY_VLM_TEXT_TIER', 'resident'),
        api_key=_llm_key() if not _tx_api_dead[0] else '',
        api_model=_VLM_TEXT_MODEL,
        prefer=('local' if _era_prefer == 'local' else 'api'),
        log=lambda m: _debug('Stage 3.5', m),
        record_usage=lambda mdl, i, o: _record_token_usage(
            model=mdl,
            prompt_tokens=i,
            completion_tokens=o,
            pipeline_id=pipeline_id,
            stage='Stage 3.5',
            pipeline_type='scholarly',
        ),
    )
    if _r.get('skipped'):
        _era_gate_stats['unavailable'] += 1
        _last_gate_outcome['era'] = 'unreviewed'
        _debug(
            'Stage 3.5',
            f'Era gate: no judge for {os.path.basename(image_path)} ({_r.get("reason")})',
            level='WARN',
        )
        return True, ''
    _era_gate_stats['checked'] += 1
    _era_gate_stats['judge'] = _r.get('judge', '')
    _era_gate_stats['seconds'] += float(_r.get('seconds') or 0.0)
    _last_gate_outcome['era'] = 'checked'
    _flags = [f for f in (_r.get('flags') or []) if f.get('severity') == 'critical']
    _majors = [f for f in (_r.get('flags') or []) if f.get('severity') != 'critical']
    if slot is not None:
        _era_last_flags[slot] = list(_flags) + list(_majors)
    for _f in _flags + _majors:
        _era_gate_stats['by_id'][_f['id']] = _era_gate_stats['by_id'].get(_f['id'], 0) + 1
    _gore = [f for f in _flags if f['id'] == 'gore_wound_bone']
    _anach = [f for f in _flags if f['id'] != 'gore_wound_bone']
    if _gore:
        _era_gate_stats['gore'] += 1
        return False, ('gore: ' + (_gore[0].get('reason') or 'open wound or exposed bone')[:70])
    if _anach:
        _era_gate_stats['flagged'] += 1
        _ids = ', '.join(f['id'].replace('era_', '').replace('obj_', '') for f in _anach[:3])
        return False, ('anachronism: ' + _ids + ' — ' + (_anach[0].get('reason') or '')[:60])
    if _majors:
        # ADVISORY items — subject-present and the haircut read.
        # Measured: hair calls were 1-in-7 right and the subject
        # question missed both confirmed absences while flagging
        # clean frames. They are recorded (stats, outcomes, the
        # debug log) and never fail the gate on their own.
        for _mf in _majors:
            if _mf['id'] == 'subject_present':
                _era_gate_stats['subject_missing'] += 1
            _era_gate_stats['advisory'] = _era_gate_stats.get('advisory', 0) + 1
            _debug(
                'Stage 3.5',
                f'Era gate advisory on {os.path.basename(image_path)}: {_mf["id"]} — {(_mf.get("reason") or "")[:90]}',
            )
        if slot is not None:
            _slot_review.setdefault(slot, {}).setdefault('advisory', [])
            _slot_review[slot]['advisory'] = sorted(
                set(_slot_review[slot].get('advisory') or []) | {_mf['id'] for _mf in _majors}
            )
    return True, ''


def vlm_render_gate(
    fs, ctx, image_path: str, prompt: str = '', slot: int | None = None, anatomy_shot: bool = False
) -> tuple:
    """Return (ok, reason). Ollama VLM defect check, fail-open.

    anatomy_shot (2026-08-25): the caller's shot-grammar flag; with
    the person-noun test on the prompt it decides whether an empty
    moondream verdict is re-asked and escalated (P-08).
    """
    _VLM_ERA_ENABLED = fs._VLM_ERA_ENABLED
    _VLM_QC_ENABLED = fs._VLM_QC_ENABLED
    _anatomy_esc_budget = fs._anatomy_esc_budget
    _debug = ctx._debug
    _era_gate_check = _ft.partial(era_gate_check, fs, ctx)
    _last_gate_outcome = fs._last_gate_outcome
    _sch_intensity = ctx._sch_intensity
    _vlm_anatomy_escalate = _ft.partial(_flux_vlm_gates.vlm_anatomy_escalate, fs, ctx)
    _vlm_ask = _ft.partial(_flux_vlm_gates.vlm_ask, fs, ctx)
    _vlm_gate_stats = fs._vlm_gate_stats
    _vlm_text_gate = _ft.partial(_flux_vlm_gates.vlm_text_gate, fs, ctx)
    _vlm_verdict = _ft.partial(_flux_vlm_gates.vlm_verdict, fs, ctx)
    _last_gate_outcome.clear()
    _last_gate_outcome.update(
        {
            'anatomy': 'skipped' if not _VLM_QC_ENABLED else 'unreviewed',
            'typography': 'unreviewed',
            'era': ('skipped' if not _VLM_ERA_ENABLED else 'unreviewed'),
        }
    )
    if not _VLM_QC_ENABLED:
        return _vlm_text_gate(image_path, prompt=prompt)
    try:
        # INTENSITY DIAL: the original question bundled
        # "screaming faces" in with melted features and
        # deformed anatomy. To this judge an agonised face
        # and a FLUX melt are the same answer, so every
        # genuinely harrowing frame came back as a DEFECT,
        # burned its three retries, and shipped whichever
        # attempt was calmest. That single word was quietly
        # undoing everything the prompt side asks for.
        #
        # At high/extreme the word comes out — and NOTHING
        # ELSE changes, because this judge is moondream and
        # its answers were MEASURED on the 40 frames of the
        # Black Death episode (2026-08-24) against 9
        # panel-confirmed anatomy failures:
        #   original wording      2/40 unreadable, 4/9 caught, 2 false
        #   this wording          1/40 unreadable, 6/9 caught, 8 false
        #   a long "these are NOT defects" version
        #                         9/40 unreadable, 0/9 caught — moondream
        #                         echoes "Say no to those." or answers "0"
        #   "Answer yes or no. Does ..."   40/40 empty replies
        #   listing "hands"/"fingers"     yes on 26-35 of 40 frames
        # moondream only parses the "Say yes if X, otherwise
        # say no" template, and every extra clause degrades
        # it. Qwen3-VL on the same frames: 0/9 — VLMs do not
        # count fingers. Keep this ONE sentence; bench any
        # change with scripts in the 08-24 session notes
        # before shipping it.
        _anatomy_q = (
            'Say yes if this image contains grotesquely distorted '
            'faces, melted facial features, or deformed anatomy, '
            'otherwise say no.'
            if _sch_intensity['enabled']
            else 'Say yes if this image contains grotesquely distorted '
            'or screaming faces, melted facial features, or '
            'deformed anatomy, otherwise say no.'
        )
        _raw_vlm = _vlm_ask(image_path, _anatomy_q)
        _v_defect = _vlm_verdict(_raw_vlm)
        _anatomy_escalated = False
        _can_carry_human = bool(slot == 0 or anatomy_shot or _PERSON_NOUN_RE.search(prompt or ''))
        if _v_defect is None and _can_carry_human:
            # An empty moondream answer on a frame that can
            # carry a human (P-08): moondream's EOS-first
            # empties are per-frame, and at temperature 0 a
            # same-wording retry is pointless — so re-ask ONCE
            # with the alternate benched wording, and only
            # then spend a second-judge call from the budget.
            _alt_q = _ANATOMY_Q_ORIGINAL if _anatomy_q != _ANATOMY_Q_ORIGINAL else _ANATOMY_Q_SHIPPED
            _vlm_gate_stats['anatomy_reask'] += 1
            _raw_re = _vlm_ask(image_path, _alt_q)
            _v_re = _vlm_verdict(_raw_re)
            if _v_re is not None:
                _vlm_gate_stats['anatomy_reask_verdict'] += 1
                _v_defect = _v_re
                _raw_vlm = _raw_re
                _debug(
                    'Stage 3.5',
                    f'Slot {slot}: anatomy re-ask (alternate wording) answered {_raw_re.strip()[:20]!r}',
                )
            elif _vlm_gate_stats['anatomy_escalation_calls'] < _anatomy_esc_budget:
                _vlm_gate_stats['anatomy_escalation_calls'] += 1
                _v_esc = _vlm_anatomy_escalate(image_path)
                if _v_esc is not None:
                    _v_defect = _v_esc
                    _anatomy_escalated = True
                    _raw_vlm = 'escalated: ' + ('yes' if _v_esc else 'no')
            else:
                _debug(
                    'Stage 3.5',
                    f'Slot {slot}: anatomy escalation budget spent '
                    f'({_anatomy_esc_budget}, ZYG_SCHOLARLY_ANATOMY_ESCALATIONS) '
                    f'— frame stays unreviewed',
                    level='WARN',
                )
        if _v_defect is None:
            # No usable verdict — the frame is unreviewed. Fail
            # open so the run never stalls, but never let this
            # be counted as a clean check.
            _vlm_gate_stats['unreadable'] += 1
            _debug(
                'Stage 3.5',
                f'VLM gate returned no verdict for '
                f'{os.path.basename(image_path)} '
                f'(raw={_raw_vlm.strip()[:60]!r}) — anatomy '
                f'unreviewed, still checking typography',
                level='WARN',
            )
            # Do NOT return here. Anatomy and typography are
            # independent checks with independent judges, and
            # an unreadable ANATOMY answer used to skip the
            # typography gate for that frame entirely — one
            # blind judge blinding the other. Measured: a run
            # with 5 gated attempts recorded only 4 typography
            # checks, and the missing one was exactly the frame
            # whose anatomy verdict came back empty. That frame
            # shipped with no lettering review at all.
            _era_ok0, _era_why0 = (True, '') if not _VLM_ERA_ENABLED else _era_gate_check(image_path, prompt, slot)
            if not _era_ok0:
                return False, _era_why0
            return _vlm_text_gate(image_path, prompt=prompt)
        _vlm_gate_stats['checked'] += 1
        # 'escalated', not 'checked': the second judge caught
        # 0/9 anatomy failures on the 08-24 panel, so the
        # receipt must show which frames only IT reviewed.
        _last_gate_outcome['anatomy'] = 'escalated' if _anatomy_escalated else 'checked'
        if _v_defect:
            _vlm_gate_stats['defect'] += 1
            # Prefix it. The judge answers this question with
            # the single word "Yes", so the raw string alone
            # reached the flagged-shipment report as
            # "unresolved defect: vlm_defect: Yes" — which
            # names neither the defect nor the gate. The
            # 'typography:' and 'anachronism:' branches below
            # already prefix, and the ladder keys off those
            # prefixes, so match them.
            _why_an = _raw_vlm.strip()[:60]
            return False, ('anatomy: distorted face or deformed anatomy' + (f' (judge: {_why_an})' if _why_an else ''))
        # ── Anachronism gate ────────────────────────────
        # The prompt guard can only police words. This is the
        # only check that looks at what was actually painted,
        # which is the difference between steering and a
        # guarantee. Per-slot, prompt-derived, crop-based —
        # see era_gate.py and scripts/bench_era_gate.py for
        # the measurement that replaced the one global
        # moondream question (34/40 yes, 2/8 recall).
        if _VLM_ERA_ENABLED:
            _era_ok, _era_why = _era_gate_check(image_path, prompt, slot)
            if not _era_ok:
                if _era_why.startswith('anachronism'):
                    _vlm_gate_stats['anachronism'] += 1
                return False, _era_why
        return _vlm_text_gate(image_path, prompt=prompt)
    except Exception as _vlm_e:
        _vlm_gate_stats['skipped'] += 1
        _debug('Stage 3.5', f'VLM render gate skipped ({_vlm_e})', level='WARN')
        # A dead anatomy gate must not silently disable the
        # typography gate too — they fail independently.
        return _vlm_text_gate(image_path, prompt=prompt)
