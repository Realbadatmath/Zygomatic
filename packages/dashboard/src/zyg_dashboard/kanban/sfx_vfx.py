# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban/sfx_vfx.py — SFX library, VFX asset libraries, the effect stacks, volume previews and the audio mergers.

Split verbatim out of ``kanban_server.py`` (lines 2195-2804) on 2026-10-06; the handler
re-imports every name from here, so ``zyg_dashboard.kanban_server.<name>`` still resolves.
"""

import os
import re
import json
import time
import threading
from urllib.parse import quote as _urlquote
from zyg_dashboard.kanban.common import _zyg_log

# ── SFX Library tab (2026-08-25): read-only browser over the AUDIO asset ─────
# libraries (data/asset_libraries/<cat>/ — sfx beds, vocal_fx, foley,
# soundtracks). asset_library_service owns the file listing and the licence
# sidecar; this server only folds in a header probe (duration / channels /
# rate / bits) and streams the WORKING copies with Range support so the
# player can seek. Imported lazily and defensively like voice_studio: a broken
# service module costs this tab only, never the board or the Inspections SPA.
_ALIB_MOD = {'m': None, 'err': ''}
_ALIB_EXT_MIME = {
    '.wav': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.ogg': 'audio/ogg',
    '.flac': 'audio/flac',
    '.m4a': 'audio/mp4',
}
# key: the tuple of DEFERRED categories folded into the payload ('' = none).
# One entry per shape the tab asks for, so opening the instruments library does
# not evict the default payload every other request.
_ALIB_CACHE = {}
_ALIB_CACHE_TTL = 20.0
# 2026-09-02: a library this large is DEFERRED from the default payload. The
# tab holds every row in memory and ships them in ONE json (2,818 rows was
# 840 KB); the instruments library is ~60k files on its own, which would put
# that response into the tens of megabytes and rebuild it every 20 s. The rail
# still lists a deferred library with its TRUE count and opening it asks for
# it by name (?extra=instruments) — nothing is hidden, only postponed.
_ALIB_DEFER_MIN = 6000
_ALIB_PROBE = {}  # abs path -> ((mtime, size), (dur, ch, sr, bits))
_ALIB_LOCK = threading.Lock()
_ALIB_TAKE_RE = re.compile(r'[\s_-]*\d+[a-z]?$', re.IGNORECASE)  # trailing take number
# One line per library so the tab can say what each is FOR — the split between
# sfx (beds) and foley (one-shots) is a product decision, not a file-type one.
_ALIB_CAT_DESC = {
    'sfx': 'Ambience BEDS — what a scene loops under dialogue (waves, creak, gulls, crowds)',
    'vocal_fx': 'Human one-shots — mouth noises, screams, pain, laughs, breaths',
    'foley': 'One-shot foley — weapons, impacts, gore, stingers, raw object recordings',
    'soundtracks': 'Music cues and derived beds',
    'merged': 'Merges saved from the SFX Merger — right-click any sample → Add to Merge list',
    'instruments': (
        'Sampled musical instruments — one note or hit per file, tagged instrument / pitch / dynamic / articulation'
    ),
}


def _alib():
    if _ALIB_MOD['m'] is None and not _ALIB_MOD['err']:
        try:
            from zyg_workflows import asset_library_service

            _ALIB_MOD['m'] = asset_library_service
        except Exception as e:  # noqa: BLE001 — failure is fatal to the tab only
            _ALIB_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] asset_library_service unavailable — {_ALIB_MOD["err"]}')
    return _ALIB_MOD['m']


def _alib_probe(fp):
    """(duration_s, channels, sample_rate, bits) for one audio file, memoised on
    (mtime, size). WAV via the stdlib header read (no decode); anything else,
    or a WAV the stdlib cannot parse, via mutagen. Never raises — an unreadable
    file probes as zeros and still lists, so one bad header cannot hide the
    other 2,800 files."""
    try:
        st = os.stat(fp)
    except OSError:
        return (0.0, 0, 0, 0)
    key = (st.st_mtime, st.st_size)
    hit = _ALIB_PROBE.get(fp)
    if hit and hit[0] == key:
        return hit[1]
    dur, ch, sr, bits = 0.0, 0, 0, 0
    if fp.lower().endswith('.wav'):
        try:
            import wave

            with wave.open(fp, 'rb') as w:
                ch, sr, bits = w.getnchannels(), w.getframerate(), w.getsampwidth() * 8
                dur = (w.getnframes() / float(sr)) if sr else 0.0
        except Exception:  # noqa: BLE001 — fall through to mutagen
            dur = 0.0
    if not dur:
        try:
            import mutagen

            m = mutagen.File(fp)
            info = getattr(m, 'info', None)
            if info is not None:
                dur = float(getattr(info, 'length', 0) or 0)
                ch = int(getattr(info, 'channels', 0) or 0) or ch
                sr = int(getattr(info, 'sample_rate', 0) or 0) or sr
                bits = int(getattr(info, 'bits_per_sample', 0) or 0) or bits
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('audio probe of %s failed, reporting the header values only: %s', fp, _exc)
    val = (round(dur, 3), ch, sr, bits)
    _ALIB_PROBE[fp] = (key, val)
    return val


def _alib_ai_state(rec):
    """Collapse the sidecar's licence fields into the one question the operator
    asks at the console: may this file feed a MODEL (voice ref / training), or
    is it mix-only? 'model' | 'dsp' | '' (unknown — no sidecar entry)."""
    t = str(rec.get('transform') or '').lower()
    if t in ('model', 'dsp'):
        return t
    nat = rec.get('no_ai_training')
    if nat is True:
        return 'dsp'
    if nat is False:
        return 'model'
    return ''


def _api_sfx(force=False, extra=()):
    """Every file in every audio library, lean records (the page holds ~2,800
    rows, so keys are one or two letters and the pack label is an index into
    `packs`). 20 s TTL, same as the video scan; ?force=1 (the Refresh button)
    bypasses it. Field key: c=category f=filename n=name p=pack-index g=group
    d=duration ch/sr/bt=format s=bytes m=mtime t=model|dsp|'' v=verbal
    vt=asr text l=licence x=sex u=UCS b=bed q=slate-suspect."""
    now = time.time()
    extra = frozenset(e for e in (extra or ()) if e)
    ckey = ','.join(sorted(extra))
    with _ALIB_LOCK:
        hit = _ALIB_CACHE.get(ckey)
        if not force and hit and (now - hit['ts']) < _ALIB_CACHE_TTL:
            return hit['data']
        als = _alib()
        if not als:
            return {
                'error': f'asset library unavailable: {_ALIB_MOD["err"]}',
                'categories': [],
                'packs': [],
                'files': [],
            }
        cats, files, packs, pidx = [], [], [], {}
        for key, info in als._CATEGORIES.items():
            if info.get('kind') != 'audio':
                continue
            d = als._audio_dir(key)
            try:
                recs = als.load_assets(key)
            except Exception as e:  # noqa: BLE001 — one broken library must not hide the rest
                _zyg_log.info(f'[KANBAN-SERVER] sfx library {key} failed to list: {e!r}')
                recs = []
            deferred = len(recs) >= _ALIB_DEFER_MIN and key not in extra
            cats.append(
                {
                    'key': key,
                    'label': info.get('label') or key,
                    'count': len(recs),
                    'desc': _ALIB_CAT_DESC.get(key, ''),
                    'deferred': deferred,
                }
            )
            if deferred:
                continue
            for r in recs:
                fn = r.get('file') or r.get('id') or ''
                if not fn:
                    continue
                fp = os.path.join(d, fn)
                dur, ch, sr, bits = _alib_probe(fp)
                try:
                    mt = int(os.path.getmtime(fp))
                except OSError:
                    mt = 0
                plabel = (r.get('pack_label') or r.get('source') or '').strip() or 'Individual files (no pack)'
                group = str(r.get('group') or '').strip()
                name = (r.get('descriptor') or r.get('name') or fn).strip()
                # SoundBits files all sit in two folders, 'Male' and 'Female'
                # (742 + 313 rows) — a wall, and the sex already rides as a tag.
                # Their descriptors are '<sex> <kind> NNN' with only three kinds
                # each (Scream / Grunt Shout / Shout of Pain), so the kind is the
                # real group: strip the take number and use the stem.
                if group.lower() in ('male', 'female'):
                    stem = _ALIB_TAKE_RE.sub('', name).strip()
                    if stem and stem.lower() != name.lower():
                        group = stem
                if plabel not in pidx:
                    pidx[plabel] = len(packs)
                    packs.append(plabel)
                sex = str(r.get('sex') or '').strip().lower()[:1]
                verbal = bool(r.get('verbal'))
                files.append(
                    {
                        'c': key,
                        'f': fn,
                        'n': name,
                        'p': pidx[plabel],
                        'g': group,
                        'd': dur,
                        'ch': ch,
                        'sr': sr,
                        'bt': bits,
                        's': int(r.get('size') or 0),
                        'm': mt,
                        't': _alib_ai_state(r),
                        'v': verbal,
                        'vt': (str(r.get('asr_text') or '')[:160] if verbal else ''),
                        'l': str(r.get('license_id') or ''),
                        'x': sex if sex in ('m', 'f') else '',
                        'u': str(r.get('ucs_category') or ''),
                        'b': bool(r.get('bed')),
                        'q': bool(r.get('slate_suspect')),
                    }
                )
        # NOT int(now). The 20 s TTL rebuilds this payload from disk four
        # times a minute, and a wall clock in the body makes every rebuild a
        # different byte string — which would hand _send_json a fresh ETag each
        # time and defeat the conditional response for a library that had not
        # changed at all. The newest file's mtime says the same thing ("as of
        # when") and only moves when the library actually does.
        data = {
            'categories': cats,
            'packs': packs,
            'files': files,
            'loaded': sorted(set(f['c'] for f in files)),
            'generated': max([f['m'] for f in files] or [0]),
        }
        _ALIB_CACHE[ckey] = {'ts': now, 'data': data}
        return data


# ── VFX asset libraries (2026-09-01) ───────────────────────────────────────
# The VFX Studio rail used to list the three uploaded ANALYZER clips (an Arcane
# episode and two test renders). It browses the downloaded effects library now,
# the same shape the SFX rail uses for audio: category → pack → group → file.
# `vfx_ingest` owns the sidecar, the working copies and the licence state; this
# only reads and serves bytes.
#
# Deliberately NOT routed through _vfx_get(): that helper 503s unless the whole
# vfx_analyzer stack (OpenCV, MediaPipe, optionally a local VLM) imports, and a
# broken CV install must not empty a rail that is really just a directory scan.
_VFXA_MOD = {'m': None, 'err': ''}
_VFXA_CACHE = {'ts': 0.0, 'data': None}
_VFXA_CACHE_TTL = 20.0
_VFXA_LOCK = threading.Lock()
_VFXA_EXT_MIME = {
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.mov': 'video/quicktime',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
}


def _vfxa():
    if _VFXA_MOD['m'] is None and not _VFXA_MOD['err']:
        try:
            from zyg_workflows import vfx_ingest

            _VFXA_MOD['m'] = vfx_ingest
        except Exception as e:  # noqa: BLE001 — fatal to this rail only
            _VFXA_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] vfx_ingest unavailable — {_VFXA_MOD["err"]}')
    return _VFXA_MOD['m']


def _api_vfx_assets(force=False):
    """Every file in every VFX library, lean records — same field key as the
    SFX scan so the two rails can share their shape. c=category f=filename
    n=name p=pack-index g=group k=kind(video|image|volume) s=bytes
    w/h/fps/d=probe fr=frames-in-a-volume-pack t=transform l=licence-id
    po=poster. 20 s TTL; ?force=1 bypasses it."""
    now = time.time()
    with _VFXA_LOCK:
        if not force and _VFXA_CACHE['data'] is not None and (now - _VFXA_CACHE['ts']) < _VFXA_CACHE_TTL:
            return _VFXA_CACHE['data']
        vi = _vfxa()
        if not vi:
            return {'error': f'vfx library unavailable: {_VFXA_MOD["err"]}', 'categories': [], 'packs': [], 'files': []}
        try:
            meta = vi.load_sidecar()
        except Exception as e:  # noqa: BLE001
            return {'error': f'vfx sidecar unreadable: {e!r}', 'categories': [], 'packs': [], 'files': []}
        packs, pidx, files = [], {}, []
        counts = {}
        for rec in meta.values():
            cat = rec.get('cat') or ''
            if cat not in vi.CATEGORIES:
                continue
            fn = rec.get('file') or ''
            if not fn:
                continue
            plabel = (rec.get('pack_label') or '').strip() or 'Individual files (no pack)'
            if plabel not in pidx:
                pidx[plabel] = len(packs)
                packs.append(plabel)
            counts[cat] = counts.get(cat, 0) + 1
            files.append(
                {
                    'c': cat,
                    'f': fn,
                    'n': rec.get('name') or fn,
                    'p': pidx[plabel],
                    'g': str(rec.get('group') or ''),
                    'k': rec.get('kind') or '',
                    's': int(rec.get('bytes') or 0),
                    'w': int(rec.get('w') or 0),
                    'h': int(rec.get('h') or 0),
                    'fps': float(rec.get('fps') or 0),
                    'd': float(rec.get('dur') or 0),
                    'fr': int(rec.get('frames') or 0),
                    't': str(rec.get('transform') or ''),
                    'l': str(rec.get('license_id') or ''),
                    'po': str(rec.get('poster') or ''),
                    'src': str(rec.get('source') or ''),
                    # A volume pack has no frames of its own to show, so it carries
                    # a rendered preview clip instead: pv=its filename in the same
                    # library dir, pvs=vendor|render (whose render it is), pve=why
                    # there is not one. vfx_volume_preview owns all three.
                    'pv': str(rec.get('preview') or ''),
                    'pvs': str(rec.get('preview_src') or ''),
                    'pve': str(rec.get('preview_error') or ''),
                    'pvd': float(rec.get('preview_dur') or 0),
                    # el = an optional COMPOSITING element rendered from the pack's
                    # own VDB: 4K-wide, alpha-carrying, framed tight on the sim
                    # instead of on a turntable's safe distance. It is a different
                    # ANSWER to the pack than pv is — pv is for picking an effect
                    # off the rail, el is the thing you would actually put in a
                    # shot — so it sits beside pv rather than replacing it.
                    'el': str(rec.get('element') or ''),
                    'elw': int(rec.get('element_w') or 0),
                    'elh': int(rec.get('element_h') or 0),
                    'els': int(rec.get('element_bytes') or 0),
                    # elv = COLOUR PASSES of that same element (vfx_element_colour):
                    # n=name f=its webm s=bytes. A recolour is a per-channel multiply
                    # on the kept RGBA master, so these are the same render — same
                    # camera, same motion, same matte — and they hang off `el`
                    # rather than becoming packs of their own. Trimmed to files that
                    # are actually on disk, for the same reason _vfx_featured_preview
                    # checks: a sidecar field outlives the file it names.
                    'elv': [
                        {'n': str(v.get('name') or ''), 'f': str(v.get('element') or ''), 's': int(v.get('bytes') or 0)}
                        for v in (rec.get('element_variants') or [])
                        if v.get('element') and os.path.isfile(os.path.join(vi.LIBS, cat, str(v.get('element'))))
                    ],
                    # sm = how many DISTINCT simulations a volume pack holds. 1 is
                    # the normal case (fr = the frames of that one sim); Cloud Pack
                    # is 10 separate clouds of one frame each, and the pane must not
                    # call those the frames of an animation.
                    'sm': int(rec.get('sims') or 1),
                }
            )
        cats = [
            {'key': k, 'label': v['label'], 'kind': v['kind'], 'count': counts.get(k, 0), 'desc': v.get('desc', '')}
            for k, v in vi.CATEGORIES.items()
        ]
        data = {'categories': cats, 'packs': packs, 'files': files, 'generated': int(now)}
        _VFXA_CACHE.update(ts=now, data=data)
        return data


# ── VFX effect stack (vfx_fx) ───────────────────────────────────────────────
# Routed BEFORE _vfx_get() for exactly the reason the assets rail is: that
# helper 503s unless the whole OpenCV/MediaPipe analyzer stack imports, and
# editing an element needs ffmpeg and nothing else.  A broken CV install must
# not take the editor down with it.
_VFXFX_MOD = {'m': None, 'err': ''}


def _vfxfx():
    if _VFXFX_MOD['m'] is None and not _VFXFX_MOD['err']:
        try:
            from zyg_workflows import vfx_fx

            _VFXFX_MOD['m'] = vfx_fx
        except Exception as e:  # noqa: BLE001
            _VFXFX_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.warning(f'[KANBAN-SERVER] vfx_fx unavailable — {_VFXFX_MOD["err"]}')
    return _VFXFX_MOD['m']


_CRFX_MOD = {'m': None, 'err': ''}


def _crfx():
    if _CRFX_MOD['m'] is None and not _CRFX_MOD['err']:
        try:
            from zyg_workflows import creature_fx

            _CRFX_MOD['m'] = creature_fx
        except Exception as e:  # noqa: BLE001
            _CRFX_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.warning(f'[KANBAN-SERVER] creature_fx unavailable — {_CRFX_MOD["err"]}')
    return _CRFX_MOD['m']


_PFX_MOD = {'m': None, 'err': ''}


def _pfx():
    """Picture Studio's toolbox. Loaded the same way creature_fx is -- lazily,
    once, and with the import error kept so the tab can say WHY the bars are
    empty instead of showing none and looking broken."""
    if _PFX_MOD['m'] is None and not _PFX_MOD['err']:
        try:
            from zyg_workflows import picture_fx

            _PFX_MOD['m'] = picture_fx
        except Exception as e:  # noqa: BLE001
            _PFX_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.warning(f'[KANBAN-SERVER] picture_fx unavailable — {_PFX_MOD["err"]}')
    return _PFX_MOD['m']


def _fx_stack_arg(raw):
    """Decode the `s` query parameter: a base64url JSON stack.

    The stack rides in the URL because the preview is an <img src> and an image
    element can only issue a GET.  Base64url rather than raw JSON so a filter
    expression full of quotes, commas and percent signs survives the trip
    intact -- percent-encoding one of those wrong turns a graph into a parse
    error that reads as a broken effect."""
    if not raw:
        return []
    import base64

    pad = '=' * (-len(raw) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(raw + pad).decode('utf-8'))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f'unreadable stack: {type(e).__name__}') from e


def _vfx_featured_preview():
    """The one asset the Library's VFX TILE shows, or {}.

    Same contract as _featured_preview() does for Videos, one library over: the
    tile was the icon glyph and nothing else, and it now carries a real picture
    — the featured asset's own poster — and hover-plays that asset's own
    preview clip.

    WHICH asset is featured is the VFX sidecar's call, not this page's: the
    record flagged '"featured": true' wins (ties broken by sidecar key, so the
    answer is stable). The flag lives in the sidecar rather than in this file
    because `vfx_ingest.save_sidecar` merges FIELD BY FIELD and nothing in the
    ingest or the preview builder ever writes that key — so a re-ingest, a
    re-probe or a rebuilt preview all leave it standing, while hardcoding a
    filename here would rot the first time a pack is renamed.

    A missing flag, a poster that is not on disk, or a broken sidecar all
    return {} and the tile keeps the icon it has always had — the same honest
    default the Videos tile takes."""
    vi = _vfxa()
    if not vi:
        return {}
    try:
        meta = vi.load_sidecar()
    except Exception as e:  # noqa: BLE001 — costs the tile, nothing else
        _zyg_log.info(f'[KANBAN-SERVER] vfx featured tile: sidecar unreadable: {e!r}')
        return {}
    picks = sorted(
        k
        for k, r in meta.items()
        if isinstance(r, dict) and r.get('featured') and (r.get('cat') or '') in vi.CATEGORIES
    )
    if not picks:
        return {}
    rec = meta[picks[0]]
    cat = rec['cat']
    root = os.path.realpath(os.path.join(vi.LIBS, cat))

    def _asset_url(fn):
        """A library URL for `fn`, or '' — same containment as _serve_vfx_asset,
        checked HERE too so the tile never advertises a file that route will
        404 (an element master lives beside its preview, and a stale sidecar
        field outlives the file it named)."""
        if not fn or os.path.basename(fn) != fn or fn.startswith('.'):
            return ''
        fp = os.path.realpath(os.path.join(root, fn))
        if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
            return ''
        return f'/inspect/vfx/asset?cat={_urlquote(cat)}&f={_urlquote(fn)}'

    thumb = _asset_url(rec.get('poster') or '')
    if not thumb:
        return {}
    return {
        'thumb': thumb,
        'preview': _asset_url(rec.get('preview') or ''),
        'label': (rec.get('name') or '').strip() or os.path.splitext(rec.get('poster') or '')[0],
    }


# ── volume previews (2026-09-01) ───────────────────────────────────────────
# A VDB pack is the one library kind with nothing to play, so vfx_volume_preview
# builds it one small mp4 and drops it in the vfx_volumes library dir, where the
# existing _serve_vfx_asset route already serves it under its own containment
# rules. Everything is built ahead of time; this endpoint exists so a pack
# ingested LATER can be given a preview from the UI instead of leaving a dead
# card in the pane until someone remembers to run the script.
#
# One job at a time on purpose: a render is a GPU job in the same box the
# pipeline renders on, and two of them racing for VRAM helps nobody.
_VOLPV_JOBS = {}
_VOLPV_LOCK = threading.Lock()


def _volpv_worker(fn):
    def log(msg):
        with _VOLPV_LOCK:
            j = _VOLPV_JOBS.get(fn)
            if j:
                j['log'].append(str(msg))
                del j['log'][:-40]
        _zyg_log.info(f'[VOLPV] {fn}: {msg}')

    try:
        from zyg_workflows import vfx_volume_preview as vp

        out = vp.build_all(only=fn, force=False, log=log)
        state = 'done' if out.get('failed', 0) == 0 else 'error'
    except Exception as e:  # noqa: BLE001 — one job only
        out, state = {'error': f'{type(e).__name__}: {e}'}, 'error'
        log(out['error'])
    with _VOLPV_LOCK:
        j = _VOLPV_JOBS.get(fn) or {}
        j.update(state=state, result=out, finished=time.time())
    _VFXA_CACHE.update(ts=0.0)  # the rail must see the new preview


def _volpv_start(fn):
    with _VOLPV_LOCK:
        busy = [k for k, j in _VOLPV_JOBS.items() if j.get('state') == 'running']
        if busy:
            return {'error': f'a preview is already building ({busy[0]})'}, 409
        _VOLPV_JOBS[fn] = {'state': 'running', 'log': [], 'started': time.time()}
    threading.Thread(target=_volpv_worker, args=(fn,), daemon=True).start()
    return {'ok': True, 'state': 'running', 'file': fn}, 200


def _volpv_status(fn):
    with _VOLPV_LOCK:
        j = _VOLPV_JOBS.get(fn)
        if not j:
            return {'state': 'idle'}
        return {
            'state': j.get('state'),
            'log': list(j.get('log') or []),
            'result': j.get('result'),
            'elapsed': round(time.time() - j.get('started', time.time()), 1),
        }


# ── SFX Merger (2026-08-25): layers library samples on one timeline ─────────
# sfx_merger owns the stems, the mix and the save-into-library step; this
# server only routes. Lazy + guarded like the others: it needs ffmpeg, numpy and
# soundfile, and a broken install must cost the merger only.
_MERGE_MOD = {'m': None, 'err': ''}


def _sfx_merger():
    if _MERGE_MOD['m'] is None and not _MERGE_MOD['err']:
        try:
            from zyg_workflows import sfx_merger

            _MERGE_MOD['m'] = sfx_merger
        except Exception as e:  # noqa: BLE001 — fatal to the merger only
            _MERGE_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] sfx_merger unavailable — {_MERGE_MOD["err"]}')
    return _MERGE_MOD['m']


# music_studio (2026-09-05): the Music Studio tab's OPTION ROSTER — 299 music
# tools with their own inline SVGs, and the four musical asset categories that
# tab browses. Same lazy/defensive contract: a broken import costs the Music
# Studio its bars, not the page.
_MUSIC_MOD = {'m': None, 'err': ''}


def _music_studio():
    if _MUSIC_MOD['m'] is None and not _MUSIC_MOD['err']:
        try:
            from zyg_workflows import music_studio

            _MUSIC_MOD['m'] = music_studio
        except Exception as e:  # noqa: BLE001 — fatal to the Music Studio bars only
            _MUSIC_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] music_studio unavailable — {_MUSIC_MOD["err"]}')
    return _MUSIC_MOD['m']


# voice_merger (2026-08-31): the Voices tab's own independent merger — same
# lazy/defensive contract as _sfx_merger() above, its own module so a broken
# import there never touches the SFX Merger.
_VOICE_MERGE_MOD = {'m': None, 'err': ''}


def _voice_merger():
    if _VOICE_MERGE_MOD['m'] is None and not _VOICE_MERGE_MOD['err']:
        try:
            from zyg_workflows import voice_merger

            _VOICE_MERGE_MOD['m'] = voice_merger
        except Exception as e:  # noqa: BLE001 — fatal to the merger only
            _VOICE_MERGE_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] voice_merger unavailable — {_VOICE_MERGE_MOD["err"]}')
    return _VOICE_MERGE_MOD['m']


# ── VFX Library / Analyzer (2026-08-29) ─────────────────────────────────────
# vfx_analyzer owns the media library, the frame-by-frame scan and the run
# reports; this server only routes and serves bytes. Imported LAZILY and
# defensively like every other optional tab: the scanner pulls in OpenCV,
# MediaPipe and (optionally) a local VLM, and a broken CV install must degrade
# the VFX tab, never take the Kanban board and the Inspections SPA down with it.
