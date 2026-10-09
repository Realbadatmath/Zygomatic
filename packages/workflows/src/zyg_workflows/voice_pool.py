# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_pool.py — the reference-voice pick, shared by the TTS path and the GUI.

WHY THIS FILE EXISTS
--------------------
`_voice_seed_for()` decides which frozen reference wav a voice id clones. It
lived inside tts_service.py, which imports Flask and crewai_web_gui at module
scope — so the only way for anything outside the web app to ask "which seed does
en-GB-RyanNeural actually speak with?" was to reimplement the pick.

That question is exactly what the Voices tab's "Assign a voice" panel has to
answer before it can put a checkmark next to a character: a character bible
stores an Azure-style voice id, and the seed that id resolves to is a
gender-filtered md5 over a manifest — not something a second implementation can
be trusted to reproduce. A duplicate would drift the first time the pool gains a
seed, and it would drift SILENTLY, since both answers look plausible.

So the pick moved here, verbatim, and tts_service imports it back under its old
private names. Nothing about the resolution changed; this module just has no
Flask in its import graph. Keep it that way — it is imported by the :8899 kanban
server, which must never pull in the GUI's Flask app.
"""

from __future__ import annotations

import glob
import json
import os
import re
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# Voice-id first names → gender. Voice ids are opaque identifiers (they keep
# their historical Azure-style spelling because 65 catalog rows, the GUI
# dropdowns, character bibles and every archived job state key off them).
# Gender drives the seed-pool pick: 2026-07-24 r3 showed a MIXED-gender pool
# sent a selected female narrator (en-US-MichelleNeural) back male in run
# dd36662e. Seed names encode gender in char [0]: f* = female, m* = male.
_AZURE_VOICE_GENDER = {
    # en-US female / male
    'jenny': 'f',
    'aria': 'f',
    'michelle': 'f',
    'ava': 'f',
    'emma': 'f',
    'jane': 'f',
    'sara': 'f',
    'nancy': 'f',
    'amber': 'f',
    'ashley': 'f',
    'cora': 'f',
    'elizabeth': 'f',
    'monica': 'f',
    'leah': 'f',
    'luna': 'f',
    'ana': 'f',
    'nina': 'f',
    'guy': 'm',
    'davis': 'm',
    'andrew': 'm',
    'brian': 'm',
    'jason': 'm',
    'tony': 'm',
    'eric': 'm',
    'jacob': 'm',
    'roger': 'm',
    'steffan': 'm',
    'christopher': 'm',
    'brandon': 'm',
    'adam': 'm',
    # en-GB female / male
    'sonia': 'f',
    'libby': 'f',
    'abbi': 'f',
    'bella': 'f',
    'hollie': 'f',
    'maisie': 'f',
    'olivia': 'f',
    'ryan': 'm',
    'alfie': 'm',
    'elliot': 'm',
    'ethan': 'm',
    'noah': 'm',
    'oliver': 'm',
    'thomas': 'm',
}


# 2026-07-31: the first-name table above only ever covered en-US and en-GB, so
# EVERY en-AU / en-CA / en-IN / en-IE / en-NZ / en-SG / en-ZA voice in
# storyteller_voice_catalog resolved to '' — the gender filter in
# the voice pick was then skipped and the deterministic md5(voice_id) pick ran
# over a MIXED-gender pool. 13 of the 65 catalog voices therefore rendered in the
# WRONG gender, and because the hash is taken over a constant string that is fixed
# forever, not a probability (en-CA-LiamNeural -> af_bella on every single run).
# The catalog already carries an authoritative per-voice `gender`, so make that the
# primary source and keep the first-name table as a fallback for ids outside it.
_CATALOG_VOICE_GENDER: dict = {}
_CATALOG_VOICE_GENDER_LOADED = False


def _catalog_voice_gender_map() -> dict:
    """{azure_voice_id: 'f'|'m'|''} from storyteller_voice_catalog (lazy, guarded).

    Returns an empty dict when the catalog module is unavailable — callers then
    degrade to the _AZURE_VOICE_GENDER first-name table (pre-fix behaviour).
    """
    global _CATALOG_VOICE_GENDER_LOADED
    if _CATALOG_VOICE_GENDER_LOADED:
        return _CATALOG_VOICE_GENDER
    _CATALOG_VOICE_GENDER_LOADED = True
    try:
        from zyg_workflows import storyteller_voice_catalog as _svc_gen

        try:
            _rows = list(_svc_gen.voice_gender_map().items())
        except AttributeError:
            # older catalog without the accessor — read the raw rows
            _rows = [(v.get('id'), v.get('gender')) for v in getattr(_svc_gen, '_STORYTELLER_VOICES', [])]
        for _vid, _g in _rows:
            if not _vid:
                continue
            _CATALOG_VOICE_GENDER[str(_vid)] = {'female': 'f', 'male': 'm'}.get(str(_g or '').strip().lower(), '')
    except Exception as _cat_e:
        _zyg_log.info(
            f'[KOKORO] storyteller_voice_catalog unavailable ({_cat_e!r}) — gender falls back to the first-name table'
        )
    return _CATALOG_VOICE_GENDER


def _voice_gender(azure_voice: str = '') -> str:
    """'f'/'m' from an Azure voice id like en-US-MichelleNeural; '' unknown.

    2026-07-31: catalog-first (see _catalog_voice_gender_map). Set
    ZYG_TTS_CATALOG_GENDER=0 to restore the pre-fix first-name-only lookup.
    """
    _v = (azure_voice or '').strip()
    if not _v:
        return ''
    if os.environ.get('ZYG_TTS_CATALOG_GENDER', '1').strip().lower() not in ('0', 'false', 'no', 'off'):
        _cg = _catalog_voice_gender_map().get(_v, '')
        if _cg:
            return _cg
        # Catalog gender 'neutral' (or id not in the catalog) → fall through to the
        # first-name table rather than returning '' here: hard-returning '' would
        # push the narrator voice en-US-BrianNeural back onto the mixed pool.
    _m = re.search(r'-([A-Za-z]+?)(?:Multilingual)?Neural$', _v)
    if not _m:
        return ''
    return _AZURE_VOICE_GENDER.get(_m.group(1).lower(), '')


# ── voice seed pool ─────────────────────────────────────────────────────────
# Both engines are CLONERS: a voice is a reference WAV, not a preset name. Voice
# ids stay Azure-style strings ('en-GB-RyanNeural') because 65 catalog rows, the
# GUI dropdowns, character bibles and every historical job state key off them —
# they are opaque identifiers now, not a claim that Azure is involved.
_SEED_POOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'assets', 'voice_seeds', 'pool')
_SEED_POOL_CACHE: dict = {'loaded': False, 'voices': []}
_SEED_PICK_LOGGED: set = set()


def _seed_pool() -> list:
    """[{name, gender, wav}] from the seed-pool manifest (cached, guarded)."""
    if _SEED_POOL_CACHE['loaded']:
        return _SEED_POOL_CACHE['voices']
    _SEED_POOL_CACHE['loaded'] = True
    _voices: list = []
    try:
        with open(os.path.join(_SEED_POOL_DIR, 'manifest.json'), encoding='utf-8') as _f:
            for _v in json.load(_f).get('voices', []):
                _w = _v.get('wav') or ''
                if _w and os.path.isfile(_w):
                    _voices.append(
                        {'name': _v.get('name', ''), 'gender': (_v.get('gender') or '').lower()[:1], 'wav': _w}
                    )
    except Exception as _sp_e:
        _zyg_log.info(f'[TTS] seed-pool manifest unavailable ({_sp_e!r}) — scanning {_SEED_POOL_DIR} for wavs')
    if not _voices:  # manifest missing/corrupt → fall back to a bare directory scan
        try:
            for _w in sorted(glob.glob(os.path.join(_SEED_POOL_DIR, '*.wav'))):
                _n = os.path.splitext(os.path.basename(_w))[0]
                _voices.append({'name': _n, 'gender': _n[:1] if _n[:1] in 'mf' else '', 'wav': _w})
        except OSError as _exc:
            _zyg_log.warning('seed-pool scan of %s failed, continuing with no seed voices: %s', _SEED_POOL_DIR, _exc)
    _SEED_POOL_CACHE['voices'] = _voices
    return _voices


def _voice_seed_for(voice_id: str = '', seed_wav: str = '') -> 'tuple[str, str]':
    """(seed_name, reference_wav) for a voice id — gender-matched, deterministic.

    Same contract the Kokoro pick had: one voice id always resolves to the same
    reference voice, across chunks and across runs, so a character does not
    change voice mid-episode or between episodes.

    `seed_wav` (2026-08-06) names the reference voice OUTRIGHT and wins over both
    the env override and the hash pick. The briefing departments (Stockmarket /
    Cryptodaily / TokiToki / Arena) each own one fixed channel voice, and
    routing that through a voice-id hash would have meant inventing fake voice ids
    whose md5 happened to land on the wanted seed — and re-inventing them the day
    a seed is added to the pool. Passing it per call is also the only version that
    is safe for concurrent callers; ZYG_TTS_SEED_WAV is process-global.
    """
    _explicit = (seed_wav or '').strip()
    if _explicit and os.path.isfile(_explicit):
        return os.path.splitext(os.path.basename(_explicit))[0], _explicit
    _override = os.environ.get('ZYG_TTS_SEED_WAV', '').strip()
    if _override and os.path.isfile(_override):
        return os.path.splitext(os.path.basename(_override))[0], _override
    _pool = _seed_pool()
    if not _pool:
        return '', ''
    _gender = _voice_gender(voice_id)
    if _gender:
        _gp = [v for v in _pool if v['gender'] == _gender]
        if _gp:
            _pool = _gp
    if voice_id:
        import hashlib as _hl_seed

        _idx = int(_hl_seed.md5(voice_id.encode(), usedforsecurity=False).hexdigest(), 16) % len(_pool)
        _picked = _pool[_idx]
    else:
        import random as _rnd_seed

        _picked = _rnd_seed.choice(_pool)
    try:  # audit trail: a wrong-gender pick is otherwise invisible (synthesis succeeds)
        _key = (voice_id, _picked['name'])
        if _key not in _SEED_PICK_LOGGED:
            if len(_SEED_PICK_LOGGED) > 200:
                _SEED_PICK_LOGGED.clear()
            _SEED_PICK_LOGGED.add(_key)
            _lvl = 'WARNING gender mismatch:' if _gender and _picked['gender'] != _gender else 'voice'
            _zyg_log.info(
                f'[TTS] {_lvl} {voice_id} ({_gender or "?"}) -> seed {_picked["name"]} ({_picked["gender"] or "?"})'
            )
    except Exception as _exc:
        _zyg_log.debug('seed-pick audit line skipped: %s', _exc)
    return _picked['name'], _picked['wav']


def seed_name_for(voice_id: str = '') -> str:
    """Just the seed NAME a voice id resolves to — the read-only question the GUI
    asks. Deliberately ignores ZYG_TTS_SEED_WAV: that env override is a global
    stomp on the running process, not a property of the voice id, and reporting it
    as "this character uses that voice" would be a lie about the stored data.
    Never logs, so a browse over 148 bibles cannot flood the journal."""
    vid = (voice_id or '').strip()
    if not vid:
        return ''
    pool = _seed_pool()
    if not pool:
        return ''
    gender = _voice_gender(vid)
    if gender:
        gp = [v for v in pool if v['gender'] == gender]
        if gp:
            pool = gp
    import hashlib

    return pool[int(hashlib.md5(vid.encode(), usedforsecurity=False).hexdigest(), 16) % len(pool)]['name']


# Public aliases. tts_service re-exports the underscored names it has always had.
seed_pool = _seed_pool
voice_gender = _voice_gender
seed_for = _voice_seed_for
