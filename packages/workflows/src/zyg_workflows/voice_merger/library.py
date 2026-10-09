# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_workflows.voice_merger.rack import (
    _LIB_CATS,
    _MAX_LAYER_S,
    _MERGED_CAT,
    _REC_CAT,
    _SR,
    _WORK,
    _zyg_log,
    exe,
    os,
    re,
    shutil,
    tempfile,
    time,
)
from zyg_workflows.voice_merger.render import _als, _run, _vs, probe_duration, render_mix, source_path


# ── licensing: derived from the SOURCE VOICES, not from a file sidecar ────────
def _source_info(vid):
    """(display name, publishable, blocker note) for one voice."""
    vs = _vs()
    v = vs.voice(vid)
    if not v:
        return vid, False, 'unknown voice'
    pol = vs.publication_policy(v) if hasattr(vs, 'publication_policy') else {}
    note = '; '.join(pol.get('blockers') or []) if isinstance(pol, dict) else ''
    return v.get('name', vid), bool((pol or {}).get('publishable')), note


def _source_ok(cat, fn):
    """(ok, note) for one merge source, whichever kind it is."""
    if cat in ('take', 'clip'):
        vid, _, _key = fn.partition('|')
        vname, ok, note = _source_info(vid)
        return ok, (f'{vname}: {note}' if note else vname)
    if cat in _LIB_CATS:
        m = _als().get_audio_meta(cat, fn) or {}
        ok = bool(m.get('commercial_ok'))
        return ok, f'{cat}/{fn}' + ('' if ok else (': ' + (m.get('notes') or 'not cleared')))
    return False, f'{cat}/{fn}: unrecognised source'


def derive_licence(sources):
    """sources: [(cat, fn), …]. One unclear source (a Kyutai-descended or
    excluded-age-band voice, or a previous merge/recording that was itself
    blocked) fails the WHOLE merge closed — the same contract
    sfx_merger.derive_licence uses, just keyed on the voice's publication
    policy instead of a file's licence sidecar."""
    problems, names = [], []
    for cat, fn in sources:
        ok, note = _source_ok(cat, fn)
        names.append(note)
        if not ok:
            problems.append(note)
    if problems:
        return {
            'license_id': 'derived-unverified',
            'commercial_ok': False,
            'attribution': '',
            'attribution_required': False,
            'no_ai_training': True,
            'no_redistribute': True,
            'transform': 'model',
            'notes': 'MERGE BLOCKED — source problems: ' + ' || '.join(problems),
        }
    return {
        'license_id': 'royalty-free-verified',
        'commercial_ok': True,
        'attribution': '',
        'attribution_required': False,
        'no_ai_training': False,
        'no_redistribute': False,
        'transform': 'model',
        'notes': 'derived work of: ' + ', '.join(sorted(set(names))),
    }


def _slug(name):
    s = re.sub(r'[^a-z0-9]+', '_', str(name or '').strip().lower()).strip('_')
    return s[:60] or 'voicemix'


def save_mix(name, items):
    """Render + register the merge as data/asset_libraries/voice_mix/<slug>.wav.
    Returns {ok, cat, file, name, duration, licence, recipe}."""
    als = _als()
    if _MERGED_CAT not in als._CATEGORIES:
        raise ValueError('the voice mix library is not registered in asset_library_service')
    name = str(name or '').strip()[:120] or time.strftime('voice mix %Y-%m-%d %H:%M')
    res = render_mix(items)
    if not res['items']:
        raise ValueError('nothing to save — the merge list is empty')
    d = als._audio_dir(_MERGED_CAT)
    base = _slug(name)
    fn, k = f'{base}.wav', 1
    while True:
        try:
            os.close(os.open(os.path.join(d, fn), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            break
        except FileExistsError as exc:
            k += 1
            fn = f'{base}_{k}.wav'
            if k > 999:
                raise ValueError('too many voice mixes with that name') from exc
    src = os.path.join(_WORK, res['mix'])
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f'.{base}.', suffix='.tmp')
    os.close(fd)
    shutil.copyfile(src, tmp)
    os.replace(tmp, os.path.join(d, fn))
    sources = [(s['cat'], s['f']) for s in res['items']]
    recipe = {
        'version': 1,
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
            'source': 'Voice Merger',
            'pack_label': 'Merged (Voice Merger)',
            'group': time.strftime('%Y-%m-%d'),
            'descriptor': name,
            'merged': True,
            'source_url': '',
            'sources': [{'cat': c, 'file': f} for c, f in sources],
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


def save_recording(src_path, name):
    """Register a live mic take (the mixer's Record button) as a normal file in
    the `voice_recorded` library, so it can be added to a merge like any other
    source. Returns {ok, cat, file, name, duration} or raises ValueError."""
    als = _als()
    if _REC_CAT not in als._CATEGORIES:
        raise ValueError('the voice recordings library is not registered in asset_library_service')
    name = str(name or '').strip()[:120] or time.strftime('recording %Y-%m-%d %H:%M')
    d = als._audio_dir(_REC_CAT)
    os.makedirs(d, exist_ok=True)
    base = _slug(name)
    fn, k = f'{base}.wav', 1
    while True:
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
                _zyg_log.debug('aborted recording %s not removed: %s', p, _exc)
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
        'source': 'Voice Merger — live recording',
        'pack_label': 'Recorded (Voice Merger)',
        'group': time.strftime('%Y-%m-%d'),
        'descriptor': name,
        'license_id': 'royalty-free-verified',
        'commercial_ok': True,
        'attribution': '',
        'attribution_required': False,
        'no_ai_training': False,
        'no_redistribute': False,
        'transform': 'dsp',
        'notes': 'live microphone recording made in the Voice Merger mixer — operator-owned',
        'duration_s': round(dur, 4),
        'added_date': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    if not als.set_audio_meta(_REC_CAT, fn, meta):
        raise ValueError('saved the recording but the licence sidecar refused the write')
    return {'ok': True, 'cat': _REC_CAT, 'file': fn, 'name': name, 'duration': round(dur, 4)}


def recipe(fn):
    """The stored recipe of one saved voice mix, or None."""
    if not source_path(_MERGED_CAT, fn):
        return None
    m = _als().get_audio_meta(_MERGED_CAT, fn)
    r = m.get('merge_recipe') if isinstance(m, dict) else None
    if not isinstance(r, dict):
        return None
    return r


def check_sources(items):
    """{'cat|f': bool} — whether each (cat, f) source still resolves.

    There is no static "all voice takes" inventory the client can hold and
    diff against the way sfx_merger's SFX rail does (takes are the live take
    cache, evicted by its own LRU/TTL, not a fixed library listing), so a
    restored merge or a re-opened recipe checks its sources against the
    SERVER instead — one round trip covering every layer at once."""
    out = {}
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        c, f = str(it.get('cat') or ''), str(it.get('f') or '')
        out[f'{c}|{f}'] = bool(source_path(c, f))
    return out


def take_ref(vid, text, params):
    """{ok, cat:'take', f, name, duration} for the finished take matching this
    voice/line/params exactly, ready to hand straight to the merger's Add — or
    raises ValueError if nothing has been rendered at those params yet.

    Deliberately does not render on demand: the merger adds what has already
    been HEARD (per the take cache's own contract — see voice_studio.py), not
    a fresh synthesis kicked off from a right-click."""
    vs = _vs()
    v = vs.voice(vid)
    if not v:
        raise ValueError('unknown voice')
    text = str(text or '')
    if not text.strip():
        raise ValueError('no line to speak')
    p = vs.sanitize(params or {})
    tc = vs.take_cached(vid, text, p)
    if not tc:
        raise ValueError('no finished take for this voice/line/params — render it first')
    preview = text.strip()
    if len(preview) > 40:
        preview = preview[:39].rstrip() + '…'
    dur = 0.0
    fp = vs.resolve_audio(tc['wav'])
    if fp:
        dur = probe_duration(fp)
    return {
        'ok': True,
        'cat': 'take',
        'f': f'{vid}|{tc["key"]}',
        'name': f'{v.get("name", vid)} — {preview}',
        'duration': round(dur, 4),
    }


def voice_ref(vid, text, params):
    """take_ref() for a whole VOICE (a Voice Studio rail row): the finished take
    if there is one, else the voice's first audition clip on disk — the same
    wav the row plays when nothing is baked, so what the row sounds like is
    what the merge gets. An empty `text` means the voice's default line, by the
    same rule voice_studio.prerender_state() keys the bake on. Still never
    renders; raises ValueError only when the voice has no audio at all."""
    vs = _vs()
    v = vs.voice(vid)
    if not v:
        raise ValueError('unknown voice')
    text = (str(text or '') or v.get('default_text') or '').strip()[: vs.MAX_PREVIEW_CHARS]
    if text:
        try:
            return take_ref(vid, text, params)
        except ValueError as _exc:
            _zyg_log.debug('no baked take for %s, falling back to an audition clip: %s', vid, _exc)
    for c in vs.audition_clips(v):
        f = f'{vid}|{c["rel"]}'
        fp = source_path('clip', f)
        if fp:
            return {
                'ok': True,
                'cat': 'clip',
                'f': f,
                'name': f'{v.get("name", vid)} — {c["label"]}',
                'duration': round(probe_duration(fp), 4),
            }
    raise ValueError('nothing on disk for this voice yet — no rendered take and no clip')
