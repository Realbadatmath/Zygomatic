# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""melody_sampler.sample_index — the sample index — one pass over the 66k-record sidecar, cached on disk.

Moved verbatim out of the 1,177-line melody_sampler.py; original lines 187-338.
"""

from zyg_workflows.melody_sampler.constants import (
    INDEX_CACHE,
    LOG,
    SIDECAR,
    VOICES,
    VOICE_TRANSPOSE,
    _MIN_SAMPLES,
    _PH_DROP_DYNAMIC,
    _PH_DROP_LENGTH,
    _PH_SOFT_DROP_LENGTH,
    _log_noop,
    _zyg_log,
    json,
    os,
    pitch_to_midi,
)

# ── Index ────────────────────────────────────────────────────────────────────

_INDEX = None
_INDEX_STAMP = None


def _sidecar_stamp():
    try:
        st = os.stat(SIDECAR)
    except OSError:
        return None
    return {'mtime': st.st_mtime, 'size': st.st_size}


def _row(file_id, meta, midi):
    return {
        'file_id': file_id,
        'midi': int(midi),
        'dynamic': str(meta.get('dynamic') or ''),
        'length': str(meta.get('length') or ''),
        'license_id': str(meta.get('license_id') or ''),
        'attribution_required': bool(meta.get('attribution_required')),
        'attribution': str(meta.get('attribution') or ''),
        'pack': str(meta.get('pack') or ''),
    }


def _build_index(log_fn=None):
    """One pass over the ~90 MB sidecar, resolving every VOICES selector."""
    log = log_fn or _log_noop
    with open(SIDECAR, 'r', encoding='utf-8') as f:
        files = (json.load(f) or {}).get('files') or {}

    exact = {}  # (pack, instrument, group) -> voice_key
    masters = []  # (substring, voice_key)
    for key, sel in VOICES.items():
        if not sel:
            continue
        if sel[0] == 'master':
            masters.append((sel[1], key))
        else:
            exact[(sel[0], sel[1], sel[2])] = key

    out = {k: [] for k, sel in VOICES.items() if sel}
    for file_id, meta in files.items():
        if not isinstance(meta, dict):
            continue
        midi = pitch_to_midi(meta.get('pitch'))
        if midi is None:  # unpitched one-shot — not a voice
            continue
        key = exact.get((meta.get('pack'), meta.get('instrument'), meta.get('group')))
        if key is None:
            master = str(meta.get('master') or '')
            for sub, cand in masters:
                if sub in master:
                    key = cand
                    break
        if key is None:
            continue
        if meta.get('pack') == 'philharmonia':
            if str(meta.get('length') or '') in _PH_DROP_LENGTH:
                continue
            if str(meta.get('dynamic') or '') in _PH_DROP_DYNAMIC:
                continue
        out[key].append(_row(file_id, meta, midi))

    for key, rows in out.items():
        # 'very-long' is a poor one-shot (six seconds of a single note, so a
        # short note is mostly attack-and-cut). Drop it *when there is anything
        # else* — the philharmonia guitar, mandolin, banjo and tremolo violin
        # were recorded ONLY as very-long, and dropping it there would delete
        # four voices outright.
        trimmed = [r for r in rows if not (r['pack'] == 'philharmonia' and r['length'] in _PH_SOFT_DROP_LENGTH)]
        if len(trimmed) >= _MIN_SAMPLES:
            rows = trimmed
        rows.sort(key=lambda r: (r['midi'], r['file_id']))
        out[key] = rows
        if len(rows) < _MIN_SAMPLES:
            LOG.warning(
                'voice %r resolved to only %d pitched samples — selector %r may be stale', key, len(rows), VOICES[key]
            )
            log(f'melody_sampler: WARNING voice {key!r} has {len(rows)} samples')
    return out


def index(*, refresh=False, log_fn=None):
    """{voice_key: [SampleRow, ...]}, built once and cached on disk.

    The sidecar is 66k records / ~65 MB and takes about a second to parse, which
    is too slow to pay on every render. The cache is keyed on the sidecar's
    (mtime, size) so re-ingesting the library invalidates it automatically and
    nobody has to remember to delete a file.
    """
    global _INDEX, _INDEX_STAMP
    stamp = _sidecar_stamp()
    if stamp is None:
        raise FileNotFoundError(f'instruments sidecar missing: {SIDECAR}')
    if not refresh and _INDEX is not None and _INDEX_STAMP == stamp:
        return _INDEX

    if not refresh and os.path.isfile(INDEX_CACHE):
        try:
            with open(INDEX_CACHE, 'r', encoding='utf-8') as f:
                doc = json.load(f)
            if doc.get('sidecar') == stamp and isinstance(doc.get('voices'), dict):
                _INDEX, _INDEX_STAMP = doc['voices'], stamp
                return _INDEX
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('melody index cache unreadable, rebuilding it: %s', _exc)

    built = _build_index(log_fn=log_fn)
    try:
        os.makedirs(os.path.dirname(INDEX_CACHE) or '.', exist_ok=True)
        tmp = INDEX_CACHE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'version': 1, 'sidecar': stamp, 'voices': built}, f)
        os.replace(tmp, INDEX_CACHE)
    except OSError as e:
        LOG.warning('could not write index cache %s: %s', INDEX_CACHE, e)
    _INDEX, _INDEX_STAMP = built, stamp
    return _INDEX


def voice_keys():
    """Every voice that resolves to at least one sample, in table order."""
    idx = index()
    return [k for k in VOICES if idx.get(k)]


def voice_info(key):
    """count / midi_lo / midi_hi / licences / packs for one voice.

    Goes straight into the render manifest: it is the record of what the song
    was actually played on and under which licence.
    """
    if key not in VOICES:
        raise KeyError(f'unknown voice {key!r}')
    rows = index().get(key) or []
    licences = {}
    packs = set()
    for r in rows:
        licences[r['license_id']] = licences.get(r['license_id'], 0) + 1
        packs.add(r['pack'])
    return {
        'key': key,
        'count': len(rows),
        'midi_lo': min((r['midi'] for r in rows), default=None),
        'midi_hi': max((r['midi'] for r in rows), default=None),
        'licences': dict(sorted(licences.items())),
        'packs': sorted(packs),
        'transpose': VOICE_TRANSPOSE.get(key, 0),
    }
