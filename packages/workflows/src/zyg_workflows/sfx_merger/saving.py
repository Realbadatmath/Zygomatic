# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Saving into the library: licence derivation, save_mix, save_recording."""

from zyg_workflows.bin import exe
import os
import re
import shutil
import tempfile
import time
from zyg_workflows.sfx_merger.constants import _MAX_LAYER_S, _MERGED_CAT, _SR, _WORK, _zyg_log
from zyg_workflows.sfx_merger.racks import _slots_from_legacy
from zyg_workflows.sfx_merger.render import _als, _run, probe_duration, render_mix, source_path

# ── saving into the library ───────────────────────────────────────────────────
_ALLOWED = frozenset({'cc0', 'cc0-1.0', 'public-domain', 'apache-2.0', 'mit', 'royalty-free-verified'})
_ATTRIB = frozenset({'cc-by-3.0', 'cc-by-4.0'})


def _norm(lic):
    return re.sub(r'[\s_]+', '-', str(lic or '').strip().lower()).strip('-')


def _source_clean(meta):
    """Mirror of ambience_ingest._violation_reasons, kept local so this module
    never imports the pipeline. [] == clean."""
    if not meta:
        return ['no license metadata recorded']
    r = []
    if meta.get('banned'):
        r.append('banned')
    if meta.get('deleted'):
        r.append('deleted')
    lic = str(meta.get('license_id') or '').strip()
    n = _norm(lic)
    if not lic:
        r.append('license_id missing')
    elif n.startswith('cc-by-nc') or 'nc' in n.split('-'):
        r.append(f'non-commercial: {lic}')
    elif n in _ATTRIB:
        if not str(meta.get('attribution') or '').strip():
            r.append(f'{lic} without attribution')
    elif n not in _ALLOWED:
        r.append(f'licence not in allowlist: {lic}')
    if meta.get('commercial_ok') is not True:
        r.append('commercial_ok is not True')
    if meta.get('attribution_required') and not str(meta.get('attribution') or '').strip():
        r.append('attribution_required but attribution is empty')
    return r


def derive_licence(sources):
    """One sidecar dict for a file made of `sources` ([(cat, fn, meta), …]).
    The strictest source wins on every axis; one unclean source makes the
    merge unclean (fail closed: license_id 'derived-unverified' is outside
    the gate's allowlist)."""
    ids, credits, problems = [], [], []
    attrib_req = False
    model_clean = True
    for cat, fn, m in sources:
        bad = _source_clean(m)
        if bad:
            problems.append(f'{cat}/{fn}: ' + '; '.join(bad))
        n = _norm((m or {}).get('license_id'))
        ids.append(n)
        cr = str((m or {}).get('attribution') or '').strip()
        if cr and cr not in credits:
            credits.append(cr)
        if (m or {}).get('attribution_required') or n in _ATTRIB:
            attrib_req = True
        # model-clean only when EVERY source says so; anything less is mix-only,
        # and the AI flag says the same thing so the sidecar cannot contradict itself
        if str((m or {}).get('transform') or '') != 'model':
            model_clean = False
    out = {
        'attribution': ' | '.join(credits),
        'attribution_required': attrib_req or bool(credits),
        'no_ai_training': not model_clean,
        'no_redistribute': not model_clean,
        'transform': 'model' if model_clean else 'dsp',
    }
    if problems:
        out.update(
            {
                'license_id': 'derived-unverified',
                'commercial_ok': False,
                'notes': 'MERGE BLOCKED — source licence problems: ' + ' || '.join(problems),
            }
        )
        return out
    attrib = [i for i in ids if i in _ATTRIB]
    if attrib:
        lic = 'cc-by-4.0' if 'cc-by-4.0' in attrib else attrib[0]
    elif len(set(ids)) == 1:
        lic = sources[0][2].get('license_id')
    else:
        lic = 'royalty-free-verified'
    out.update(
        {
            'license_id': lic,
            'commercial_ok': True,
            'notes': 'derived work of '
            + ', '.join(f'{c}/{f} [{(m or {}).get("license_id") or "?"}]' for c, f, m in sources),
        }
    )
    return out


def _slug(name):
    s = re.sub(r'[^a-z0-9]+', '_', str(name or '').strip().lower()).strip('_')
    return s[:60] or 'merge'


def save_mix(name, items):
    """Render + register the merge as data/asset_libraries/merged/<slug>.wav.
    Returns {ok, cat, file, name, duration, licence, recipe}."""
    als = _als()
    if _MERGED_CAT not in als._CATEGORIES:
        raise ValueError('the merged library is not registered in asset_library_service')
    name = str(name or '').strip()[:120] or time.strftime('merge %Y-%m-%d %H:%M')
    res = render_mix(items)
    if not res['items']:
        raise ValueError('nothing to save — the merge list is empty')
    d = als._audio_dir(_MERGED_CAT)
    base = _slug(name)
    fn, k = f'{base}.wav', 1
    while True:  # O_EXCL claims the name; no exists() race
        try:
            os.close(os.open(os.path.join(d, fn), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            break
        except FileExistsError as exc:
            k += 1
            fn = f'{base}_{k}.wav'
            if k > 999:
                raise ValueError('too many merges with that name') from exc
    src = os.path.join(_WORK, res['mix'])
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f'.{base}.', suffix='.tmp')
    os.close(fd)
    shutil.copyfile(src, tmp)
    os.replace(tmp, os.path.join(d, fn))
    sources = [(s['cat'], s['f'], als.get_audio_meta(s['cat'], s['f'])) for s in res['items']]
    recipe = {
        'version': 2,
        'name': name,
        'sr': _SR,
        'items': [
            {'uid': s['uid'], 'cat': s['cat'], 'f': s['f'], 'name': s['name'], 'start': s['start'], 'slots': s['slots']}
            for s in res['items']
        ],
    }
    meta = derive_licence(sources)
    meta.update(
        {
            'source': 'SFX Merger',
            'pack_label': 'Merged (SFX Merger)',
            'group': time.strftime('%Y-%m-%d'),
            'descriptor': name,
            'merged': True,
            'source_url': '',
            'sources': [{'cat': c, 'file': f} for c, f, _ in sources],
            'duration_s': res['duration'],
            'peak': res['peak'],
            'mix_scale': res['scale'],
            'merge_recipe': recipe,
            'added_date': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    )
    if not als.set_audio_meta(_MERGED_CAT, fn, meta):
        raise ValueError('saved the wav but the licence sidecar refused the write')
    return {
        'ok': True,
        'cat': _MERGED_CAT,
        'file': fn,
        'name': name,
        'duration': res['duration'],
        'licence': meta['license_id'],
        'commercial_ok': meta['commercial_ok'],
        'recipe': recipe,
    }


_REC_CAT = 'recorded'


def save_recording(src_path, name):
    """Register a live mic take (the mixer's Record button) as a normal file in
    the `recorded` library, so it can be added to a merge like any other
    source. Transcodes whatever the browser sent (webm/opus, wav, …) to the
    merger's canonical 48 kHz stereo wav; ffmpeg sniffs the container from
    content, not the extension, so the source file needs no particular name.
    Returns {ok, cat, file, name, duration} or raises ValueError."""
    als = _als()
    if _REC_CAT not in als._CATEGORIES:
        raise ValueError('the recordings library is not registered in asset_library_service')
    name = str(name or '').strip()[:120] or time.strftime('recording %Y-%m-%d %H:%M')
    d = als._audio_dir(_REC_CAT)
    os.makedirs(d, exist_ok=True)
    base = _slug(name)
    fn, k = f'{base}.wav', 1
    while True:  # O_EXCL claims the name; no exists() race
        try:
            os.close(os.open(os.path.join(d, fn), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            break
        except FileExistsError as exc:
            k += 1
            fn = f'{base}_{k}.wav'
            if k > 999:
                raise ValueError('too many recordings with that name') from exc
    out = os.path.join(d, fn)

    def _abort(msg):
        for p in (tmp, out):
            try:
                os.remove(p)
            except OSError as _exc:
                _zyg_log.debug('temp file %s cleanup skipped: %s', p, _exc)
        raise ValueError(msg)

    fd, tmp = tempfile.mkstemp(dir=d, prefix=f'.{base}.', suffix='.wav')
    os.close(fd)
    code, err = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-i',
            src_path,
            '-ar',
            str(_SR),
            '-ac',
            '2',
            '-c:a',
            'pcm_f32le',
            tmp,
        ]
    )
    if code != 0:
        _abort(f'ffmpeg could not read the recording: {err.strip()[-300:] or code}')
    dur = probe_duration(tmp)
    if dur <= 0.05:
        _abort('the recording is empty')
    if dur > _MAX_LAYER_S:
        _abort(f'the recording is {dur / 60:.1f} min — the merger caps a layer at {_MAX_LAYER_S / 60:.0f} min')
    os.replace(tmp, out)
    meta = {
        'source': 'Sfx Studio — live recording',
        'pack_label': 'Recorded (Sfx Studio)',
        'group': time.strftime('%Y-%m-%d'),
        'descriptor': name,
        'license_id': 'royalty-free-verified',
        'commercial_ok': True,
        'attribution': '',
        'attribution_required': False,
        'no_ai_training': False,
        'no_redistribute': False,
        'transform': 'dsp',
        'notes': 'live microphone recording made in the Sfx Studio mixer — operator-owned',
        'duration_s': round(dur, 4),
        'added_date': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    if not als.set_audio_meta(_REC_CAT, fn, meta):
        raise ValueError('saved the recording but the licence sidecar refused the write')
    return {'ok': True, 'cat': _REC_CAT, 'file': fn, 'name': name, 'duration': round(dur, 4)}


def recipe(fn):
    """The stored recipe of one merged file, or None — always in the current
    (slots) shape, migrating a v1 (flat tweak) recipe saved before the mixer
    had a slot list."""
    if not source_path(_MERGED_CAT, fn):
        return None
    m = _als().get_audio_meta(_MERGED_CAT, fn)
    r = m.get('merge_recipe') if isinstance(m, dict) else None
    if not isinstance(r, dict):
        return None
    if int(r.get('version') or 1) < 2:
        r = dict(
            r,
            items=[
                dict(it, slots=_slots_from_legacy(it.get('tweak'))) for it in r.get('items', []) if isinstance(it, dict)
            ],
        )
    return r
