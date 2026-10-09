# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Character preview regeneration and the preview sweep routes.

Verbatim move of bp_storyteller.py:2251-2655 (2026-10-06 split).
"""

import logging as _zyg_logging
import os
import threading

from flask import jsonify, request, session

from zyg_dashboard.bp_storyteller import (  # noqa: E402  the package __init__ binds these before it imports this module
    _ams_iso,
    _char_params_from_bible,
    _have_usable_char_preview,
    _normalize_char_model_family,
    _render_char_preview_images,
    bp,
    gui_state,
    limiter,
)
from zyg_dashboard.bp_storyteller.guards import (
    _CHARS_DATASET_ROOT,
    _CHAR_ID_RE,
    _PREVIEW_REGEN_JOBS,
    _PREVIEW_REGEN_LOCK,
    _SWEEP_LOCK,
    _char_lora_usable,
    _env_on,
    _is_medusa_cid,
    _preview_provenance_map,
    _production_paused,
)

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_storyteller')


@bp.route('/api/internal/storyteller/character/<char_id>/preview/regenerate', methods=['POST', 'OPTIONS'])
@limiter.exempt
def api_internal_storyteller_regen_preview(char_id: str):
    """Regenerate preview_flux_front.png + preview_flux_face.png for *char_id*
    using the trained LoRA (if available) and the character bible's identity.

    Body (optional JSON): {"force": true, "model_family": "sdxl"|"flux"}.
    """
    if request.method == 'OPTIONS':
        return jsonify({'ok': True})
    # 2026-07-31: char_id feeds _char_params_from_bible → dataset_dir →
    # os.makedirs in the renderer, so validate it here like every other
    # disk-touching route in this file.
    if _env_on('ZYG_STORYTELLER_CHAR_ID_STRICT') and not _CHAR_ID_RE.match(char_id or ''):
        return jsonify(
            {'char_id': char_id, 'success': False, 'error': 'invalid char_id (expected 12 lowercase hex characters)'}
        ), 400
    body = request.get_json(silent=True) or {}
    force = bool(body.get('force', False))
    params, info = _char_params_from_bible(char_id)
    if not os.path.isdir(info['dataset_dir']):
        return jsonify({'char_id': char_id, 'success': False, 'error': 'dataset directory not found'}), 404

    _mf_body = (body.get('model_family') or '').strip().lower()
    if _mf_body in ('flux', 'sdxl'):
        params['model_family'] = _mf_body
        info['model_family'] = _mf_body
    _mf = _normalize_char_model_family(body.get('model_family'), params, info)

    # 2026-07-31: this used to render inline in the Flask worker — ~36 GB of
    # FLUX, a _PREVIEW_LORA_WAIT_S wait for in-flight training, then every slot,
    # while the public proxy's 12-30 s timeout had long since given up. Worse,
    # there was no in-flight guard, so two concurrent POSTs raced on the shared
    # pipeline global and rendered character B through character A's adapter.
    # Now: one job per char_id, claimed under a lock, polled via .../preview/status.
    if _env_on('ZYG_PREVIEW_REGEN_ASYNC'):
        if _production_paused():
            return jsonify(
                {
                    'char_id': char_id,
                    'success': False,
                    'status': 'paused',
                    'error': 'preview rendering is paused (production hold)',
                }
            ), 409
        with _PREVIEW_REGEN_LOCK:
            _live = _PREVIEW_REGEN_JOBS.get(char_id)
            if _live and _live.get('status') == 'running':
                return jsonify(
                    {
                        'char_id': char_id,
                        'success': True,
                        'already_running': True,
                        'status': 'running',
                        'started_at': _live.get('started_at'),
                        'poll_url': f'/api/internal/storyteller/character/{char_id}/preview/status',
                    }
                ), 202
            _PREVIEW_REGEN_JOBS[char_id] = {
                'char_id': char_id,
                'status': 'running',
                'model_family': _mf,
                'started_at': _ams_iso(),
                'finished_at': None,
                'rendered': [],
                'skipped': False,
                'lora_used': False,
                'error': None,
                'log': [],
            }

        def _regen_worker():
            _job_rg = _PREVIEW_REGEN_JOBS.get(char_id) or {}
            _logs: list = _job_rg.setdefault('log', [])

            def _rg_log(msg):
                _logs.append(str(msg)[:300])
                if len(_logs) > 60:
                    del _logs[:-60]

            try:
                _res = _render_char_preview_images(
                    char_id,
                    params,
                    info,
                    log_fn=_rg_log,
                    force=force,
                    model_family=_mf,
                )
                _job_rg['rendered'] = [os.path.basename(p) for p in (_res.get('rendered') or [])]
                _job_rg['skipped'] = bool(_res.get('skipped'))
                _job_rg['lora_used'] = bool(_res.get('lora_used'))
                _job_rg['error'] = str(_res.get('error'))[:200] if _res.get('error') else None
                _job_rg['status'] = 'done' if (_res.get('rendered') or _res.get('skipped')) else 'error'
            except Exception as _rg_e:
                _job_rg['status'] = 'error'
                _job_rg['error'] = str(_rg_e)[:200]
            finally:
                _job_rg['finished_at'] = _ams_iso()

        threading.Thread(target=_regen_worker, daemon=True, name=f'char-preview-regen-{char_id[:8]}').start()
        return jsonify(
            {
                'char_id': char_id,
                'success': True,
                'status': 'running',
                'started': True,
                'poll_url': f'/api/internal/storyteller/character/{char_id}/preview/status',
            }
        ), 202

    log_lines: list[str] = []
    result = _render_char_preview_images(
        char_id,
        params,
        info,
        log_fn=lambda m: log_lines.append(m),
        force=force,
        model_family=_mf,
    )
    status = 200 if (result['rendered'] or result['skipped']) else 500
    return jsonify(
        {
            'char_id': char_id,
            'success': bool(result['rendered'] or result['skipped']),
            'skipped': result['skipped'],
            'lora_used': result['lora_used'],
            'rendered': [os.path.basename(p) for p in result['rendered']],
            'error': result['error'],
            'log': log_lines,
        }
    ), status


@bp.route('/api/internal/storyteller/character/<char_id>/preview/status')
@limiter.exempt
def api_internal_storyteller_regen_preview_status(char_id: str):
    """Poll target for the async preview/regenerate job (2026-07-31)."""
    if _env_on('ZYG_STORYTELLER_CHAR_ID_STRICT') and not _CHAR_ID_RE.match(char_id or ''):
        return jsonify({'char_id': char_id, 'error': 'invalid char_id'}), 400
    _job_rg = _PREVIEW_REGEN_JOBS.get(char_id)
    if not _job_rg:
        return jsonify({'char_id': char_id, 'status': 'idle', 'found': False}), 404
    _out = dict(_job_rg)
    _out['found'] = True
    _out['preview_provenance'] = _preview_provenance_map(os.path.join(_CHARS_DATASET_ROOT, char_id))
    return jsonify(_out)


@bp.route('/api/internal/storyteller/gen-char-previews', methods=['POST'])
@limiter.exempt
def api_internal_storyteller_gen_char_previews():
    """
    Launch a one-at-a-time background sweep that fills in MISSING character
    previews. Identity comes ONLY from the character bible and rendering goes
    ONLY through the LoRA-locked renderer; a character with no bible or no
    usable adapter is SKIPPED, never guessed at.
    Idempotent — safe to call multiple times; a running sweep is not duplicated.
    Returns: {started, total, already_running?}

    2026-07-31 identity audit — this endpoint was the direct cause of the
    "cel-shaded adult woman labelled 'LoRA trained — full character consistency'
    for a 12-year-old Dutch boy" incident. The old sweep:
      * scraped the first root-level *.txt for gender/hair/eye/skin/style and
        fell back to hardcoded 'female'/'brown'/'medium'/'brown'/'animated' —
        contact-sheet characters keep captions in training/, so the scrape found
        nothing and EVERY character got the same fabricated female prompt;
      * read training_status.json from lora-datasets while the trainer writes it
        to lora-outputs, so the trigger-token lookup was 100 % dead;
      * rendered on BASE FLUX with no adapter at all and saved the stranger to
        preview_flux_front.png — the exact file the public wizard captions as
        LoRA-trained;
      * reused (and then nulled) the process-global FLUX pipeline it did not
        own, so it could render through another character's live adapter and
        could kill a concurrent contact-sheet render mid-run;
      * enumerated slug dirs the image routes can never serve, and Medusa chars
        the library deliberately hides.
    All of that is gone. The sweep now delegates to
    char_state_service._render_char_preview_images, which owns the LoRA
    load/unload/provenance lifecycle, and FAILS CLOSED on missing identity.
    """
    if not _env_on('ZYG_PREVIEW_SWEEP_ENABLED'):
        return jsonify({'started': False, 'disabled': True, 'total': 0}), 200

    # A sweep is production GPU work — respect the operator's hold like every
    # other start path does.
    if _production_paused():
        return jsonify(
            {'started': False, 'status': 'paused', 'total': 0, 'message': 'Preview sweep is paused (production hold).'}
        ), 409

    # Atomic claim (2026-07-31): the old check-then-set sat 28 lines and an
    # os.listdir apart, so two public page loads in the same second started two
    # sweeps, both fighting over one GPU and losing each other's `done` counts.
    with _SWEEP_LOCK:
        if (gui_state._CHAR_PREVIEW_SWEEP or {}).get('running'):
            return jsonify(
                {
                    'already_running': True,
                    'done': gui_state._CHAR_PREVIEW_SWEEP['done'],
                    'total': gui_state._CHAR_PREVIEW_SWEEP['total'],
                    'current': gui_state._CHAR_PREVIEW_SWEEP['current'],
                }
            ), 200
        gui_state._CHAR_PREVIEW_SWEEP.update({'running': True, 'done': 0, 'total': 0, 'current': '', 'errors': []})

    def _sweep_needs_preview(cid: str) -> bool:
        """False when this character already has something presentable.

        A finished 48-angle master sheet IS the canonical preview for the whole
        modern pipeline (list-chars and library_preview_urls both treat it that
        way), yet the old gate could not see it — so operator-approved,
        fully-QC'd characters were permanently classified 'needs preview' and
        had a base-model portrait written over their dataset root.
        """
        try:
            from zyg_workflows import contact_sheet_pipeline as _csp_sw

            if _csp_sw.master_sheet_exists(cid):  # contract A: monolithic OR multi-part
                return False
        except Exception as _exc:
            _zyg_log.warning('master sheet check failed for %s, the preview sweep may re-run it: %s', cid, _exc)
        _ds = os.path.join(_CHARS_DATASET_ROOT, cid)
        # Cheap stat sweep first (this runs for every dataset dir on every public
        # page load). Face slots and contactsheet_00.png were missing from the
        # old list, so a character whose front slot failed but whose face slot
        # succeeded stayed a sweep target forever — and its only root *.txt was
        # the previous render's PROMPT, which the old scraper then mined as if it
        # were a caption.
        for _pn in (
            'preview_sdxl_front.png',
            'preview_flux_front.png',
            'preview_sdxl_face.png',
            'preview_flux_face.png',
            'contactsheet_00.png',
            'face_00_000deg.png',
            'full_00_000deg.png',
        ):
            _pp = os.path.join(_ds, _pn)
            if os.path.isfile(_pp) and os.path.getsize(_pp) >= 10_000:
                return False
        # Canonical pair check last — it is bible-aware (hybrid/legacy slot
        # naming) and is the shared helper rather than a fourth hand-rolled copy.
        try:
            _p_sw, _i_sw = _char_params_from_bible(cid)
            if _have_usable_char_preview(
                _ds,
                _normalize_char_model_family(None, _p_sw, _i_sw),
                _p_sw,
                _i_sw,
            ):
                return False
        except Exception as _exc:
            _zyg_log.warning('usable preview check failed for %s, treating it as needing a preview: %s', cid, _exc)
        return True

    try:
        _SMOKE_PREFIX = 'smoke'
        _all_cids = sorted(
            c
            for c in os.listdir(_CHARS_DATASET_ROOT)
            # Only canonical 12-hex ids: /api/storyteller/char-image/ and the
            # contact-sheet image route both reject anything else, so rendering
            # a slug dir (abel_van_haren) is pure GPU spend on an image that can
            # never be served.
            if _CHAR_ID_RE.match(c)
            and os.path.isdir(os.path.join(_CHARS_DATASET_ROOT, c))
            and not c.startswith(_SMOKE_PREFIX)
            # Medusa chars share this root but are isolated to the Medusa app —
            # list-contact-sheets already strips them.
            and not _is_medusa_cid(c)
        )
        _need = [c for c in _all_cids if _sweep_needs_preview(c)]
    except Exception as _scan_e:
        with _SWEEP_LOCK:
            gui_state._CHAR_PREVIEW_SWEEP['running'] = False
        _zyg_log.info(f'[PREVIEW-SWEEP] Scan failed: {_scan_e}')
        return jsonify({'started': False, 'total': 0, 'error': 'scan failed'}), 500

    gui_state._CHAR_PREVIEW_SWEEP['total'] = len(_need)

    def _sweep_note(msg: str) -> None:
        """Bounded, truncated error/skip note. The old list appended raw
        str(exception) forever and the status route handed it to anonymous
        callers — CUDA/diffusers messages carry absolute model paths."""
        try:
            _errs = gui_state._CHAR_PREVIEW_SWEEP.setdefault('errors', [])
            _errs.append(str(msg)[:160])
            if len(_errs) > 20:
                del _errs[:-20]
        except Exception as _exc:
            _zyg_log.debug('sweep note could not be recorded: %s', _exc)

    def _sweep():
        # NOTE: this loop deliberately does NOT touch
        # gui_state._FLUX_DEV_PIPELINE_CACHE. _render_char_preview_images owns
        # the load / adapter-attach / unload_lora_weights / teardown lifecycle
        # for that global; the old bespoke loop borrowed it without unloading
        # the previous character's adapter and nulled it in a finally{} that ran
        # even on paths where it had never loaded it (and could NameError on
        # _torch_sw, whose import lived inside the try).
        try:
            for _cid in _need:
                if _production_paused():
                    _sweep_note('sweep stopped — production paused')
                    _zyg_log.info('[PREVIEW-SWEEP] Production paused — stopping sweep')
                    break
                gui_state._CHAR_PREVIEW_SWEEP['current'] = _cid
                try:
                    # ── Identity: bible only, no guessing ─────────────────────
                    _params_sw, _info_sw = _char_params_from_bible(_cid)
                    if not (_info_sw.get('package') or {}):
                        _sweep_note(f'{_cid}: skipped — no character bible')
                        _zyg_log.info(
                            f'[PREVIEW-SWEEP] SKIP {_cid}: no character bible (refusing to invent an identity)'
                        )
                        continue
                    _mf_sw = _normalize_char_model_family(None, _params_sw, _info_sw)

                    # ── LoRA-locked or not at all ─────────────────────────────
                    _ok_lora, _why = _char_lora_usable(_cid, _mf_sw)
                    if not _ok_lora:
                        _sweep_note(f'{_cid}: skipped — {_why}')
                        _zyg_log.info(f'[PREVIEW-SWEEP] SKIP {_cid}: {_why}')
                        continue

                    _zyg_log.info(
                        f'[PREVIEW-SWEEP] Rendering LoRA-locked preview for {_cid} '
                        f'({_mf_sw}, gender={_params_sw.get("gender")}, '
                        f'age={_params_sw.get("age")})'
                    )
                    _res_sw = _render_char_preview_images(
                        _cid,
                        _params_sw,
                        _info_sw,
                        log_fn=lambda m, _cid=_cid: _zyg_log.info(f'[PREVIEW-SWEEP] {_cid[:8]}: {m}'),
                        force=False,
                        # Do not block the sweep on in-flight training — a
                        # character whose LoRA is still baking is simply skipped
                        # on this pass and picked up by the next one.
                        wait_for_lora_s=0,
                        model_family=_mf_sw,
                    )
                    if _res_sw.get('error') and not _res_sw.get('rendered'):
                        _sweep_note(f'{_cid}: {str(_res_sw.get("error"))[:120]}')
                        _zyg_log.info(f'[PREVIEW-SWEEP] ERROR {_cid}: {_res_sw.get("error")}')
                    elif _res_sw.get('rendered') and not _res_sw.get('lora_used'):
                        # Belt and braces: the renderer only aborts when an
                        # adapter load FAILS, not when there was none to load.
                        _sweep_note(f'{_cid}: rendered without a LoRA adapter')
                        _zyg_log.info(f'[PREVIEW-SWEEP] WARN {_cid}: renderer reported lora_used=false')
                except Exception as _pe:
                    _sweep_note(f'{_cid}: {str(_pe)[:120]}')
                    _zyg_log.info(f'[PREVIEW-SWEEP] ERROR {_cid}: {_pe}')
                finally:
                    gui_state._CHAR_PREVIEW_SWEEP['done'] += 1
        except Exception as _sweep_e:
            _zyg_log.info(f'[PREVIEW-SWEEP] Fatal: {_sweep_e}')
            _sweep_note(f'fatal: {str(_sweep_e)[:120]}')
        finally:
            with _SWEEP_LOCK:
                gui_state._CHAR_PREVIEW_SWEEP['running'] = False
                gui_state._CHAR_PREVIEW_SWEEP['current'] = ''
            _zyg_log.info(
                f'[PREVIEW-SWEEP] Complete — '
                f'{gui_state._CHAR_PREVIEW_SWEEP["done"]}/'
                f'{gui_state._CHAR_PREVIEW_SWEEP["total"]}'
            )

    threading.Thread(target=_sweep, daemon=True, name='char-preview-sweep').start()
    return jsonify({'started': True, 'total': len(_need)}), 202


@bp.route('/api/internal/storyteller/char-preview-status')
@limiter.exempt
def api_internal_storyteller_char_preview_status():
    """Return current sweep progress.

    2026-07-31: this used to jsonify the whole sweep dict — including an
    uncapped `errors` list of raw str(exception) values — to unauthenticated
    public callers at 120/min. A CUDA/diffusers failure string carries absolute
    model paths and library internals. Anonymous callers now get counts only;
    the text is returned to logged-in main-app sessions.
    """
    _st = dict(gui_state._CHAR_PREVIEW_SWEEP or {})
    _errs = list(_st.get('errors') or [])
    if not _env_on('ZYG_PREVIEW_STATUS_REDACT'):
        return jsonify(_st)
    _out = {
        'running': bool(_st.get('running')),
        'done': _st.get('done', 0),
        'total': _st.get('total', 0),
        'current': _st.get('current', ''),
        'error_count': len(_errs),
    }
    try:
        if session.get('user_role'):
            _out['errors'] = _errs
    except Exception as _exc:
        _zyg_log.debug('session role unavailable, withholding the error list: %s', _exc)
    return jsonify(_out)
