# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Local TTS samples for the Storyteller voice picker (V1 / V2).

Synthesized by IndexTTS-2 (Chatterbox fallback) so a preview sounds exactly
like what the pipelines will deliver for that voice id."""

from __future__ import annotations

import os
import re
import shutil

from zyg_workflows.storyteller_voice_catalog import (
    VOICE_PREVIEW_SENTENCE,
    VOICE_SAMPLE_V1,
    all_voice_ids,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


VOICE_SAMPLE_V2 = VOICE_PREVIEW_SENTENCE

_VALID_VARIANTS = frozenset({'v1', 'v2'})

_HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES_ROOT = os.path.join(_HERE, 'data', 'runtime', 'storyteller_voice_samples')

_LEGACY_MIGRATED = False


def _safe_voice_dirname(voice_id: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', voice_id.strip())


def sample_path(voice_id: str, variant: str) -> str:
    """Samples are stored as .mp3 (a legacy .wav migration path exists below)."""
    v = variant.strip().lower()
    if v not in _VALID_VARIANTS:
        raise ValueError(f'invalid variant: {variant}')
    return os.path.join(SAMPLES_ROOT, _safe_voice_dirname(voice_id), f'{v}.mp3')


def _legacy_wav_path(voice_id: str, variant: str) -> str:
    v = variant.strip().lower()
    return os.path.join(SAMPLES_ROOT, _safe_voice_dirname(voice_id), f'{v}.wav')


def _looks_like_mp3(path: str) -> bool:
    try:
        with open(path, 'rb') as fh:
            head = fh.read(4)
        if head[:3] == b'ID3':
            return True
        return len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0
    except OSError:
        return False


def migrate_legacy_wav_samples() -> int:
    """Rename .wav files that contain MP3 data (old bug) to .mp3."""
    global _LEGACY_MIGRATED
    if _LEGACY_MIGRATED or not os.path.isdir(SAMPLES_ROOT):
        _LEGACY_MIGRATED = True
        return 0
    moved = 0
    for _root, _dirs, files in os.walk(SAMPLES_ROOT):
        for fn in files:
            if not fn.endswith('.wav'):
                continue
            wav = os.path.join(_root, fn)
            mp3 = wav[:-4] + '.mp3'
            if os.path.isfile(mp3):
                try:
                    os.remove(wav)
                except OSError as _exc:
                    _zyg_log.debug('legacy wav sample removal skipped: %s', _exc)
                continue
            if _looks_like_mp3(wav):
                try:
                    shutil.move(wav, mp3)
                    moved += 1
                except OSError as _exc:
                    _zyg_log.warning('legacy wav to mp3 migration failed, leaving %s in place: %s', wav, _exc)
    _LEGACY_MIGRATED = True
    return moved


def resolve_sample_path(voice_id: str, variant: str) -> str | None:
    """Return path to an on-disk sample, migrating legacy .wav if needed."""
    migrate_legacy_wav_samples()
    try:
        mp3 = sample_path(voice_id, variant)
    except ValueError:
        return None
    if os.path.isfile(mp3) and os.path.getsize(mp3) >= 1000:
        return mp3
    legacy = _legacy_wav_path(voice_id, variant)
    if os.path.isfile(legacy) and os.path.getsize(legacy) >= 1000:
        if _looks_like_mp3(legacy):
            try:
                shutil.move(legacy, mp3)
                return mp3 if os.path.isfile(mp3) else legacy
            except OSError:
                return legacy
        return legacy
    return None


def sample_mimetype(path: str) -> str:
    if path.lower().endswith('.mp3'):
        return 'audio/mpeg'
    if path.lower().endswith('.wav'):
        return 'audio/wav'
    return 'application/octet-stream'


def sample_ready(voice_id: str, variant: str, min_bytes: int = 1000) -> bool:
    p = resolve_sample_path(voice_id, variant)
    return bool(p and os.path.getsize(p) >= min_bytes)


def samples_ready(voice_id: str) -> dict:
    return {
        'v1_ready': sample_ready(voice_id, 'v1'),
        'v2_ready': sample_ready(voice_id, 'v2'),
    }


def default_voice_id() -> str:
    """The operator-selected narrator voice id (tts_service is the source of truth)."""
    try:
        from zyg_workflows.tts_service import _selected_voice_id

        return _selected_voice_id()
    except Exception:
        return 'en-GB-RyanNeural'


def voices_to_warm(*, include_default: bool = True) -> list[str]:
    ids = set(all_voice_ids())
    if include_default:
        ids.add(default_voice_id())
    return sorted(ids)


def _phrase_for_variant(variant: str) -> str:
    return VOICE_SAMPLE_V1 if variant == 'v1' else VOICE_SAMPLE_V2


def synthesize_sample(voice_id: str, variant: str) -> tuple[bool, str]:
    """Synthesize one sample via IndexTTS-2 (Chatterbox fallback). Returns (ok, message)."""
    variant = variant.strip().lower()
    if variant not in _VALID_VARIANTS:
        return False, 'invalid variant'

    out_path = sample_path(voice_id, variant)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp_mp3 = out_path + '.tmp.mp3'
    text = _phrase_for_variant(variant)

    try:
        # Samples must sound like what production delivers: IndexTTS-2 primary,
        # Chatterbox fallback, cloning this voice id's seed-pool reference.
        ok = False
        try:
            from zyg_workflows.tts_service import _tts_shared

            ok, _ = _tts_shared(
                text,
                tmp_mp3,
                f'Voice sample {variant}',
                log_fn=None,
                voice_id=voice_id,
            )
        except Exception:
            ok = False
        if not ok or not os.path.isfile(tmp_mp3) or os.path.getsize(tmp_mp3) < 1000:
            if os.path.isfile(tmp_mp3):
                os.remove(tmp_mp3)
            return False, (
                'No TTS engine produced audio (IndexTTS-2 and Chatterbox both failed; check the voice seed pool)'
            )

        shutil.move(tmp_mp3, out_path)
        return True, out_path
    except Exception as exc:
        if os.path.isfile(tmp_mp3):
            try:
                os.remove(tmp_mp3)
            except OSError as _exc:
                _zyg_log.debug('temporary mp3 cleanup skipped: %s', _exc)
        return False, str(exc)[:200]


def warm_voice(voice_id: str, *, force: bool = False) -> dict:
    """Generate v1 + v2 for one voice. Returns status dict."""
    result = {'voice_id': voice_id, 'v1': False, 'v2': False, 'errors': []}
    for variant in ('v1', 'v2'):
        if not force and sample_ready(voice_id, variant):
            result[variant] = True
            continue
        ok, msg = synthesize_sample(voice_id, variant)
        result[variant] = ok
        if not ok:
            result['errors'].append(f'{variant}: {msg}')
    return result


def warm_all(*, force: bool = False, include_default: bool = True) -> dict:
    """Warm every catalog voice (+ configured default)."""
    migrate_legacy_wav_samples()
    summary = {
        'root': SAMPLES_ROOT,
        'phrases': {'v1': VOICE_SAMPLE_V1, 'v2': VOICE_SAMPLE_V2},
        'default_voice': default_voice_id() if include_default else None,
        'voices': [],
        'ok': 0,
        'partial': 0,
        'failed': 0,
    }
    for vid in voices_to_warm(include_default=include_default):
        row = warm_voice(vid, force=force)
        summary['voices'].append(row)
        if row['v1'] and row['v2']:
            summary['ok'] += 1
        elif row['v1'] or row['v2']:
            summary['partial'] += 1
        else:
            summary['failed'] += 1
    return summary


def enrich_voice_entry(v: dict) -> dict:
    """Attach local sample URLs + readiness flags for API/UI."""
    vid = v.get('id', '')
    st = samples_ready(vid)
    out = dict(v)
    out.update(st)
    if st['v1_ready']:
        out['v1_url'] = f'/api/storyteller/voice-sample/{vid}/v1'
    if st['v2_ready']:
        out['v2_url'] = f'/api/storyteller/voice-sample/{vid}/v2'
    return out


def grouped_voices_for_api(*, kind: str = 'character') -> list[dict]:
    from zyg_workflows.storyteller_voice_catalog import grouped_storyteller_voices

    migrate_legacy_wav_samples()
    groups = grouped_storyteller_voices(kind=kind)
    out = []
    for g in groups:
        voices = [enrich_voice_entry(v) for v in g.get('voices', [])]
        voices = [v for v in voices if v.get('v1_ready') and v.get('v2_ready')]
        if voices:
            out.append({'group': g['group'], 'voices': voices})
    return out
