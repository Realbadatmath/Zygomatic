# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Char-state backfill and the metrics formatting helpers — verbatim sections of the
former bp_metrics.py."""

import json
import os

from zyg_dashboard.bp_metrics import _zyg_log
from zyg_dashboard.crewai_web_gui import _char_state_path
from zyg_dashboard.gui.timeutil import _ams_iso


def _backfill_char_gen_states_from_bibles() -> int:
    """Synthesize a minimal char_gen_<id>.json for every pre-existing character bible.

    Characters generated before the stage_timeline persistence work shipped will
    not have a runtime state file, so the dashboard would under-count them.
    This helper walks the character bible dataset root once and writes a
    'done' snapshot (no stage_timeline) for any character that lacks a state
    file. Returns the number of files created. Idempotent — safe to call
    repeatedly; existing files are never overwritten.
    """
    try:
        from zyg_workflows import character_bible_service as _cbs_bf
    except Exception:
        return 0
    try:
        ds_root = getattr(_cbs_bf, '_DATASET_ROOT', None)
        if not ds_root or not os.path.isdir(ds_root):
            return 0
    except Exception:
        return 0

    created = 0
    try:
        for entry in os.listdir(ds_root):
            char_dir = os.path.join(ds_root, entry)
            if not os.path.isdir(char_dir):
                continue
            bible_p = os.path.join(char_dir, 'character_bible.json')
            if not os.path.isfile(bible_p):
                continue
            state_p = _char_state_path(entry)
            if os.path.exists(state_p):
                continue
            try:
                with open(bible_p, encoding='utf-8') as _bf:
                    bible = json.load(_bf)
            except (OSError, ValueError) as _exc:
                _zyg_log.debug('skipping character bible that could not be read: %s', _exc)
                continue
            created_at = bible.get('created_at') or bible.get('updated_at') or _ams_iso()
            updated_at = bible.get('updated_at') or created_at
            # Count dataset images (best-effort)
            image_count = 0
            try:
                for f in os.listdir(char_dir):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        image_count += 1
            except OSError as _exc:
                _zyg_log.debug('dataset image count unavailable for %s: %s', entry, _exc)
            snapshot = {
                'char_id': entry,
                'status': 'done',
                'stage': 'done',
                'current_stage': 'done',
                'started': created_at,
                'ended': updated_at,
                'params': {},
                'render_mode': 'unknown',
                'image_count': image_count,
                'kick_lora': bool(bible.get('lora')),
                'error': None,
                'debug_events': [],
                'stage_timeline': [],
                'backfilled': True,
            }
            # 2026-07-31: this record is SYNTHESIZED from the character bible, not
            # observed. 'ended' is bible.updated_at — NOT a LoRA training timestamp
            # (for c3345deb5bde it precedes the actual training by ~21h) — yet
            # char_state_service._char_library_trained_at and
            # zpub_routes_storyteller._zpub_char_trained_at both return it as
            # trained_at and the library is SORTED by it. Stamp explicit provenance
            # so those consumers can prefer a real timestamp (stage_timeline /
            # training_status.json) over a synthesized one instead of guessing.
            # ZYG_CHAR_GEN_BACKFILL_PROVENANCE=0 restores the unstamped snapshot.
            try:
                _mark_prov = os.environ.get('ZYG_CHAR_GEN_BACKFILL_PROVENANCE', '1').strip().lower() not in (
                    '0',
                    'false',
                    'no',
                    'off',
                )
            except Exception:
                _mark_prov = True
            if _mark_prov:
                snapshot.update(
                    {
                        'synthesized_from': 'character_bible',
                        'synthesized_at': _ams_iso(),
                        'timestamps_synthesized': True,
                        'started_source': 'character_bible.created_at',
                        'ended_source': 'character_bible.updated_at',
                        'synthesized_fields': [
                            'status',
                            'stage',
                            'current_stage',
                            'started',
                            'ended',
                            'params',
                            'render_mode',
                        ],
                    }
                )
            try:
                os.makedirs(os.path.dirname(state_p), exist_ok=True)
                with open(state_p, 'w', encoding='utf-8') as _fh:
                    json.dump(snapshot, _fh, default=str)
                created += 1
            except (OSError, TypeError, ValueError) as _exc:
                _zyg_log.warning('backfilled char state write failed for %s: %s', entry, _exc)
    except Exception as _exc:
        _zyg_log.warning('character state backfill failed after %d snapshot(s): %s', created, _exc)
    return created


def _metrics_fmt_duration(s) -> str:
    if s is None:
        return '—'
    try:
        s = float(s)
    except (TypeError, ValueError):
        return '—'
    if s < 1:
        return '< 1s'
    if s >= 3600:
        return f'{int(s) // 3600}h {(int(s) % 3600) // 60}m'
    if s >= 60:
        return f'{int(s) // 60}m {int(s) % 60}s'
    return f'{int(s)}s'


def _metrics_normalize_stage(name: str) -> str:
    n = (name or '').split(':')[0].strip()
    if 'LoRA Training' in n or 'LoRA' in n:
        if 'FLUX' in n.upper():
            return 'LoRA Training (FLUX)'
        if 'SDXL' in n.upper():
            return 'LoRA Training (SDXL)'
        return 'LoRA Training'
    if 'Preview Render' in n:
        return 'Preview Render'
    if 'Character Render' in n or 'Blender' in n:
        return 'Character Render'
    if 'Caption' in n:
        return 'Caption Generation'
    if 'Character Bible' in n:
        return 'Character Bible'
    return n
