# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3.5 VLM gates: the anatomy judge, the typography judges and the slot record.

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
import json
import logging as _zyg_logging
import os
import re

from zyg_workflows.net import safe_urlopen
from zyg_workflows.pipeline_config import (
    _OLLAMA_BASE_URL,
)
from zyg_workflows.pipeline_scholarly import (
    _TEXT_SUBJECT_RE,
)
from zyg_workflows.runtime import (
    _record_token_usage,
)
from zyg_workflows.subscription_llm import (
    anthropic_client as _llm_client,
    api_key_or_login as _llm_key,
)

# The monolith's logger name, not `__name__`, so every debug line of one run
# stays under `zyg_workflows.pipeline_scholarly`.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')


def vlm_ask(fs, ctx, image_path: str, question: str) -> str:
    """One moondream question. Raises on transport failure."""
    _VLM_QC_MODEL = fs._VLM_QC_MODEL
    import base64 as _b64_vlm

    with open(image_path, 'rb') as _fh_vlm:
        _img_b64 = _b64_vlm.b64encode(_fh_vlm.read()).decode()
    _payload_vlm = json.dumps(
        {
            'model': _VLM_QC_MODEL,
            'prompt': question,
            'images': [_img_b64],
            'stream': False,
            'options': {'temperature': 0.0, 'num_predict': 30},
            'keep_alive': '3m',
        }
    ).encode()
    with safe_urlopen(_OLLAMA_BASE_URL + '/api/generate', data=_payload_vlm, timeout=60) as _resp_vlm:
        return json.loads(_resp_vlm.read()).get('response', '')


def vlm_verdict(fs, ctx, raw: str):
    """yes → True, no → False, anything unparseable → None.

    Tri-state on purpose. An empty or waffling answer is NOT a
    pass — it means the gate did not inspect this frame, and
    conflating the two is exactly how the gate went dead
    silently. Word-boundary matched: a plain substring test
    for 'yes' fires on 'eyes', which the descriptive answers
    this model gives are full of.
    """
    _t = (raw or '').strip().lower()
    if not _t:
        return None
    _has_yes = re.search(r'\byes\b', _t) is not None
    _has_no = re.search(r'\bno\b|\bnot\b|\bnone\b', _t) is not None
    if _has_yes and not _has_no:
        return True
    if _has_no and not _has_yes:
        return False
    return None


def vlm_text_gate_qwen(fs, ctx, image_path: str) -> tuple | None:
    """Local Qwen3-VL judge. Returns (ok, reason) or None if unusable.

    PREFERRED over the Anthropic path: free per call, no network,
    45 frames in 69s on the resident tier (0.7-2.7s each after a
    3.2s one-time load), and — the part the API path cannot do —
    every flag carries a BBOX, so a future repair pass can inpaint
    the lettering instead of re-rolling the whole slot.

    Measured head-to-head on the 45 frames of run 77bbbfd4:
    Qwen flagged 10, Haiku 12, agreeing on 9. Qwen's extra catch is
    real (slot 0's wall map, which Haiku saw but could not quote).
    Haiku's three extras are all genuinely blurred marginal cases
    that Qwen calls unreadable — a defensible read, not a miss.

    None (not a pass) whenever the judge cannot run — no install,
    ComfyUI sampling, or below the tier's VRAM floor — so the
    caller falls through to the API path rather than shipping the
    frame unreviewed.
    """
    _debug = ctx._debug
    _last_gate_outcome = fs._last_gate_outcome
    _vlm_gate_stats = fs._vlm_gate_stats
    _vlm_text_boxes = fs._vlm_text_boxes
    try:
        from zyg_workflows import vlm_inspector as _vlm_ins

        if not _vlm_ins.available():
            return None
        # HEADROOM GUARD — the fix for the Catherine stall.
        # vlm_inspector protects the render by DOWNSHIFTING to
        # its cpu tier when the GPU is short, and that is
        # exactly the state Stage 3.5 runs in: FLUX is resident
        # and only ~4 GB is free. On cpu one inspection takes
        # ~126 s instead of ~2 s, inside a per-slot retry loop —
        # 70 inspections burned ~2.5 h and the run stalled at
        # slot 24 of 40 with no video.
        #
        # So: only use the local judge when it can actually run
        # on the GPU. Otherwise return None and let the Anthropic
        # path (no VRAM, ~2 s) take it. Returning None is the
        # existing 'judge unusable' contract, so the frame is
        # still reviewed — just by the other judge.
        _tier_q = os.environ.get('ZYG_SCHOLARLY_VLM_TEXT_TIER', 'resident')
        try:
            _need_q = float(_vlm_ins.TIERS[_tier_q]['min_free_gb'])
        except Exception:
            _need_q = 14.0
        _free_q = None
        try:
            from zyg_workflows.vram_manager import _get_free_vram_gb as _fv_q

            _free_q = float(_fv_q())
        except Exception as _exc:  # noqa: BLE001 — the probe shells out to nvidia-smi
            _zyg_log.debug(
                'free-VRAM probe failed — the text judge tier gate is skipped and the resident judge is attempted: %s',
                _exc,
            )
        if _free_q is not None and _free_q < _need_q:
            _debug(
                'Stage 3.5',
                f'Typography: local judge needs {_need_q:.0f} GB, '
                f'{_free_q:.1f} GB free — using the API judge '
                f'(never the cpu tier mid-render)',
            )
            return None
        _r_q = _vlm_ins.inspect_frames(
            [image_path],
            checklist='documentary_typography',
            tier=os.environ.get('ZYG_SCHOLARLY_VLM_TEXT_TIER', 'resident'),
            offload=False,  # never evict ComfyUI for a QC read
            frame_kind='all',
        )
        if not _r_q or _r_q.get('skipped'):
            return None
        if str(_r_q.get('tier') or '') == 'cpu':
            # Downshifted anyway (headroom changed under us).
            _debug(
                'Stage 3.5',
                'Typography: judge downshifted to cpu — discarding and using the API judge',
            )
            return None
        _v_q = (_r_q.get('verdicts') or [None])[0]
        if not _v_q or not str(_v_q.get('answer') or '').strip():
            return None
        _vlm_gate_stats['text_checked'] += 1
        _vlm_gate_stats['text_judge'] = 'qwen3vl'
        _last_gate_outcome['typography'] = 'checked'
        if str(_v_q.get('answer')).strip().lower().startswith('y'):
            _vlm_gate_stats['typography'] += 1
            _bb_q = _v_q.get('bbox')
            if _bb_q:
                _vlm_text_boxes[os.path.basename(image_path)] = _bb_q
            return False, ('typography: ' + (str(_v_q.get('reason') or 'lettering visible')[:80]))
        return True, ''
    except Exception as _q_e:
        _debug(
            'Stage 3.5',
            f'Qwen typography judge unusable ({_q_e}) — falling back to the API path',
            level='WARN',
        )
        return None


def vlm_text_gate(fs, ctx, image_path: str, prompt: str = '') -> tuple:
    """Return (ok, reason). Typography check, fail-open.

    Local Qwen3-VL judge first; the Anthropic vision path is the
    fallback for when it cannot run.

    Flags only when the judge marks the lettering prominent AND
    can quote what it appears to say. Requiring the quote is
    what makes this precise: calibrated on the 45 frames of run
    77bbbfd4, 'prominent' alone fired on 15 frames, of which the
    two weakest (a blurred desk of papers, a chamber of blank
    sheets) both returned an EMPTY largest_text. Dropping those
    leaves 12 flags, 11-12 of them confirmed by eye — including
    every frame a human reviewer had independently marked.
    If the judge cannot say what it reads, it is not readable
    enough to break the shot.
    """
    _OCR_TEXT_ENABLED = fs._OCR_TEXT_ENABLED
    _VLM_TEXT_ENABLED = fs._VLM_TEXT_ENABLED
    _debug = ctx._debug
    _last_gate_outcome = fs._last_gate_outcome
    _vlm_gate_stats = fs._vlm_gate_stats
    _vlm_text_boxes = fs._vlm_text_boxes
    _vlm_text_gate_api = _ft.partial(vlm_text_gate_api, fs, ctx)
    _vlm_text_gate_qwen = _ft.partial(vlm_text_gate_qwen, fs, ctx)
    if not _VLM_TEXT_ENABLED:
        return True, ''
    # ── OCR judge (primary) ─────────────────────────────
    # Agrees with Qwen3-VL 12/12 and 36/36 on 48 real frames
    # (precision 1.00, recall 1.00) at 0.58 s/frame on CPU.
    # It also satisfies this gate's precision rule by
    # construction: it only fires on text it can quote.
    if _OCR_TEXT_ENABLED:
        try:
            from zyg_workflows import typography_ocr as _tocr

            _o_res = _tocr.judge(image_path)
        except Exception as _o_e:
            _o_res = None
            _debug(
                'Stage 3.5',
                f'OCR typography judge unusable ({_o_e!r}) — falling through to the vision judges',
                level='WARN',
            )
        if _o_res is not None:
            _ok_o, _why_o, _boxes_o = _o_res
            _vlm_gate_stats['text_checked'] += 1
            _vlm_gate_stats['text_judge'] = 'ocr'
            _last_gate_outcome['typography'] = 'checked'
            if not _ok_o:
                _vlm_gate_stats['typography'] += 1
                if _boxes_o:
                    _vlm_text_boxes[os.path.basename(image_path)] = _boxes_o[0]
                return False, _why_o
            # ── Second vote when the PROMPT names a written thing ──
            # OCR needs real letters. Pseudo-typeset gibberish
            # (slots 6, 11, 34, 37 of the Black Death run, all
            # passed at QA 1.00) does not OCR, so it reads as
            # "no text" — exactly the frames a viewer sees a
            # document in. When the prompt puts a document,
            # scroll, map or sign in the scene, the vision
            # judge gets a vote too: local Qwen3-VL first,
            # the Anthropic vision prompt as its fallback.
            if prompt and _TEXT_SUBJECT_RE.search(prompt):
                _vlm_gate_stats['text_second_vote'] += 1
                _sv = _vlm_text_gate_qwen(image_path)
                if _sv is None:
                    _sv = _vlm_text_gate_api(image_path)
                if _sv is not None and not _sv[0]:
                    _vlm_gate_stats['text_second_flag'] += 1
                    _vlm_gate_stats['typography'] += 1
                    return False, _sv[1] + ' (second vote; OCR clean)'
            return True, ''
    _q_res = _vlm_text_gate_qwen(image_path)
    if _q_res is not None:
        return _q_res
    _a_res = _vlm_text_gate_api(image_path)
    if _a_res is None:
        _vlm_gate_stats['text_skipped'] += 1
        return True, ''
    return _a_res


def vlm_text_gate_api(fs, ctx, image_path: str) -> tuple | None:
    """Anthropic vision typography judge. None when it cannot run."""
    _VLM_TEXT_MODEL = fs._VLM_TEXT_MODEL
    _VLM_TEXT_PROMPT = fs._VLM_TEXT_PROMPT
    _debug = ctx._debug
    _last_gate_outcome = fs._last_gate_outcome
    _log = ctx._log
    _tx_api_dead = fs._tx_api_dead
    _vlm_gate_stats = fs._vlm_gate_stats
    pipeline_id = ctx.pipeline_id
    _tk = _llm_key()
    if not _tk or _tx_api_dead[0]:
        return None
    _vlm_gate_stats['text_judge'] = 'haiku'
    try:
        import base64 as _b64_tx

        with open(image_path, 'rb') as _fh_tx:
            _raw_tx = _fh_tx.read()
        _b_tx = _b64_tx.b64encode(_raw_tx).decode()
        # ComfyUI writes PNG bytes into the .jpg still; the
        # API checks the bytes, not the extension (400 on
        # a mismatch), so sniff the magic number.
        _mt_tx = (
            'image/png'
            if _raw_tx[:8] == b'\x89PNG\r\n\x1a\n'
            else 'image/webp'
            if _raw_tx[:4] == b'RIFF'
            else 'image/jpeg'
        )
        _r_tx = _llm_client(_tk).messages.create(
            model=_VLM_TEXT_MODEL,
            max_tokens=250,
            temperature=0.0,
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image',
                            'source': {'type': 'base64', 'media_type': _mt_tx, 'data': _b_tx},
                        },
                        {'type': 'text', 'text': _VLM_TEXT_PROMPT},
                    ],
                }
            ],
        )
        try:
            _record_token_usage(
                model=_VLM_TEXT_MODEL,
                prompt_tokens=_r_tx.usage.input_tokens,
                completion_tokens=_r_tx.usage.output_tokens,
                pipeline_id=pipeline_id,
                stage='Stage 3.5',
                pipeline_type='scholarly',
            )
        except Exception as _exc:  # noqa: BLE001 — the recorder writes to Postgres, a third-party error tree
            _zyg_log.debug(
                'token usage of the VLM typography judge not recorded — accounting only: %s',
                _exc,
            )
        _raw_tx = re.sub(r'```(?:json)?|```', '', _r_tx.content[0].text).strip()
        # "Reply with ONLY a JSON object" is not a guarantee:
        # measured, the judge sometimes appends a sentence of
        # commentary after the closing brace, and a bare
        # json.loads then raises "Extra data" and books the
        # frame as unreviewed. Take the first balanced object.
        _m_tx = re.search(r'\{.*?\}', _raw_tx, re.S)
        _d_tx = json.loads(_m_tx.group(0) if _m_tx else _raw_tx)
    except Exception as _tx_e:
        # A billing or auth failure is a property of the
        # ACCOUNT, not of this frame. Measured: the key is
        # set but out of credit, so every frame cost a
        # round-trip and booked itself 'unreadable' — 3 calls
        # to learn one fact. Latch it and stop asking.
        _tx_msg = str(_tx_e)
        if (
            'credit balance' in _tx_msg
            or 'authentication' in _tx_msg.lower()
            or 'invalid x-api-key' in _tx_msg.lower()
            or 'Error code: 401' in _tx_msg
            or 'Error code: 403' in _tx_msg
        ):
            _tx_api_dead[0] = _tx_msg[:120]
            _log(
                'WARNING',
                'Stage 3.5',
                f'Anthropic typography fallback is permanently '
                f'unavailable ({_tx_msg[:90]}) — not calling it '
                f'again this run. The OCR judge is primary and '
                f'unaffected; this only matters if OCR is off.',
            )
        # Same discipline as the anatomy gate: a frame we could
        # not inspect is never counted as a clean check.
        _vlm_gate_stats['text_unreadable'] += 1
        _debug(
            'Stage 3.5',
            f'Typography gate no verdict for {os.path.basename(image_path)} ({_tx_e})',
            level='WARN',
        )
        return True, ''
    if not isinstance(_d_tx, dict) or 'prominent' not in _d_tx:
        _vlm_gate_stats['text_unreadable'] += 1
        _debug(
            'Stage 3.5',
            f'Typography gate unparseable verdict for {os.path.basename(image_path)}: {_raw_tx[:80]!r}',
            level='WARN',
        )
        return True, ''
    _vlm_gate_stats['text_checked'] += 1
    _last_gate_outcome['typography'] = 'checked'
    _quote_tx = str(_d_tx.get('largest_text') or '').strip()
    if _d_tx.get('prominent') and _quote_tx:
        _vlm_gate_stats['typography'] += 1
        _where_tx = str(_d_tx.get('where') or '').strip()
        return False, (f'typography: reads {_quote_tx[:40]!r}' + (f' ({_where_tx[:30]})' if _where_tx else ''))
    return True, ''


def record_slot_review(fs, ctx, slot: int, attempt: int) -> None:
    _last_gate_outcome = fs._last_gate_outcome
    _slot_review = fs._slot_review
    _rv = _slot_review.get(slot)
    if _rv is None:
        return
    _rv['attempts'] = attempt + 1
    for _k in ('anatomy', 'typography', 'era'):
        _rv[f'{_k}_a{attempt}'] = _last_gate_outcome.get(_k, 'unreviewed')


def vlm_anatomy_escalate(fs, ctx, image_path: str) -> bool | None:
    """Second opinion when moondream returned nothing.

    Originally hook-only (slot 0); since 2026-08-25 every slot
    that can carry a human reaches here, after one re-ask with
    the alternate wording and under the per-run budget
    ZYG_SCHOLARLY_ANATOMY_ESCALATIONS (P-08).
    Slot 0 is the frame that decides whether anyone watches; on
    the Black Death run it shipped anatomy-unreviewed because
    moondream's answer was unreadable and the gate failed open.
    For that slot specifically, an empty verdict escalates: local
    Qwen3-VL when the card can hold it, the Anthropic vision
    model otherwise. None = still no verdict (never a pass).
    """
    _VLM_TEXT_MODEL = fs._VLM_TEXT_MODEL
    _debug = ctx._debug
    _tx_api_dead = fs._tx_api_dead
    _vlm_gate_stats = fs._vlm_gate_stats
    _q_an = (
        'Does this image contain a grotesquely distorted or melted '
        'face, a face with missing or duplicated features, or '
        'obviously deformed human anatomy (not a strong expression, '
        'not dirt, not dramatic lighting)? Answer yes or no.'
    )
    try:
        from zyg_workflows import vlm_inspector as _vlm_an

        if _vlm_an.available():
            _free_an = None
            try:
                from zyg_workflows.vram_manager import _get_free_vram_gb as _fv_an

                _free_an = float(_fv_an())
            except Exception as _exc:  # noqa: BLE001 — the probe shells out to nvidia-smi
                _zyg_log.debug(
                    'free-VRAM probe failed — the anatomy judge tier gate is skipped: %s',
                    _exc,
                )
            if _free_an is None or _free_an >= float(_vlm_an.TIERS['resident']['min_free_gb']):
                _r_an = _vlm_an.inspect_frames(
                    [image_path],
                    tier='resident',
                    offload=False,
                    frame_kind='all',
                    items=[
                        {
                            'id': 'anatomy_defect',
                            'question': _q_an,
                            'expected': 'no',
                            'severity': 'critical',
                            'grounding': False,
                        }
                    ],
                    preamble='This is a still frame from a historical documentary, generated by a diffusion model.',
                )
                if _r_an and not _r_an.get('skipped') and str(_r_an.get('tier')) != 'cpu':
                    _v_an = (_r_an.get('verdicts') or [{}])[0]
                    _a_an = str(_v_an.get('answer') or '').lower()
                    if _a_an in ('yes', 'no'):
                        _vlm_gate_stats['anatomy_escalated'] += 1
                        return _a_an == 'yes'
    except Exception as _an_e:
        _debug('Stage 3.5', f'anatomy escalation (local) failed: {_an_e!r}', level='WARN')
    _tk_an = _llm_key()
    if not _tk_an or _tx_api_dead[0]:
        return None
    try:
        import base64 as _b64_an

        with open(image_path, 'rb') as _fh_an:
            _raw_an = _fh_an.read()
        _b_an = _b64_an.b64encode(_raw_an).decode()
        _mt_an = (
            'image/png'
            if _raw_an[:8] == b'\x89PNG\r\n\x1a\n'
            else 'image/webp'
            if _raw_an[:4] == b'RIFF'
            else 'image/jpeg'
        )
        _r_api = _llm_client(_tk_an).messages.create(
            model=_VLM_TEXT_MODEL,
            max_tokens=20,
            temperature=0.0,
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image',
                            'source': {'type': 'base64', 'media_type': _mt_an, 'data': _b_an},
                        },
                        {'type': 'text', 'text': _q_an + ' Reply with one word.'},
                    ],
                }
            ],
        )
        _t_an = _r_api.content[0].text.strip().lower()
        if _t_an.startswith(('yes', 'no')):
            _vlm_gate_stats['anatomy_escalated'] += 1
            return _t_an.startswith('yes')
    except Exception as _an_api_e:
        _debug('Stage 3.5', f'anatomy escalation (API) failed: {_an_api_e!r}', level='WARN')
    return None
