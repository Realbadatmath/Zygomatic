# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Library access, the ffmpeg stem/mix renderers and the work-dir sweep."""

from zyg_workflows.bin import exe
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from zyg_workflows.sfx_merger.constants import (
    MAX_ITEMS,
    _BUDGET_BYTES,
    _FF_TIMEOUT,
    _LOCKS,
    _LOCKS_GUARD,
    _MAX_LAYER_S,
    _MAX_MIX_S,
    _MAX_START_S,
    _MIX_TTL,
    _REL_RE,
    _RENDER_SEM,
    _SR,
    _STEM_TTL,
    _SWEEP,
    _SWEEP_EVERY,
    _WORK,
    _zyg_log,
)
from zyg_workflows.sfx_merger.racks import clean_slots, plugin_host, sfx_fx


# ── library access ────────────────────────────────────────────────────────────
def _als():
    from zyg_workflows import asset_library_service

    return asset_library_service


def source_path(cat, fn):
    """Absolute path of one registered library file, or '' — same containment
    as kanban_server._serve_sfx: an AUDIO category, a bare basename, realpath
    inside that library dir."""
    als = _als()
    info = als._CATEGORIES.get(cat)
    if not info or info.get('kind') != 'audio':
        return ''
    fn = str(fn or '')
    if not fn or os.path.basename(fn) != fn or fn.startswith('.'):
        return ''
    # realpath/stat raise ValueError on a NUL byte rather than returning False
    if any(ord(ch) < 32 for ch in fn) or len(fn) > 255:
        return ''
    if os.path.splitext(fn)[1].lower() not in als._AUDIO_EXTS:
        return ''
    try:
        root = os.path.realpath(als._audio_dir(cat))
        fp = os.path.realpath(os.path.join(root, fn))
        if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
            return ''
    except (OSError, ValueError):
        return ''
    return fp


def probe(fp):
    """(duration_s, channels) — soundfile for wav/flac/ogg, mutagen for mp3/m4a."""
    try:
        import soundfile as sf

        i = sf.info(fp)
        return float(i.duration), int(i.channels or 0)
    except Exception as _exc:  # noqa: BLE001 — mp3 etc. via mutagen
        _zyg_log.debug('soundfile could not probe %s, trying mutagen: %s', fp, _exc)
    try:
        import mutagen

        m = mutagen.File(fp)
        info = getattr(m, 'info', None)
        return (float(getattr(info, 'length', 0) or 0), int(getattr(info, 'channels', 0) or 0))
    except Exception:  # noqa: BLE001
        return 0.0, 0


def probe_duration(fp):
    return probe(fp)[0]


# ── ffmpeg ────────────────────────────────────────────────────────────────────
def _run(args):
    with _RENDER_SEM:
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=_FF_TIMEOUT)
            return r.returncode, (r.stderr or '')[-800:]
        except subprocess.TimeoutExpired:
            return 124, 'ffmpeg timeout'
        except OSError as e:
            return 125, str(e)[:200]


def _tweak_filters(p, src_dur):
    """The filter list for one 'tweak' slot instance. Order matters: trims act
    on the timeline as this slot sees it (the first slot sees the source
    timeline the operator browses in the library; a slot stacked after another
    sees whatever duration survived upstream, so its own trim numbers are
    approximate), then the time/pitch moves, then tone, then space, then
    level, then fades on the FINAL length (fade-out via areverse so it needs
    no duration arithmetic)."""
    f = []
    ti, to = float(p['trim_in']), float(p['trim_out'])
    if ti > 0.0005 or to > 0.0005:
        if src_dur > 0:
            ti = min(ti, max(0.0, src_dur - 0.05))
            end = max(ti + 0.02, src_dur - to)
            f.append(f'atrim=start={ti:.4f}:end={end:.4f}')
        else:
            f.append(f'atrim=start={ti:.4f}')
        f.append('asetpts=PTS-STARTPTS')
    if p['reverse']:
        f.append('areverse')
    tape = float(p['tape'])
    if abs(tape - 1.0) > 1e-6:
        f += [f'asetrate={int(round(_SR * tape))}', f'aresample={_SR}']
    speed = float(p['speed'])
    if abs(speed - 1.0) > 1e-6:
        f.append(f'atempo={speed:.6f}')
    st = float(p['pitch_st'])
    if abs(st) > 1e-6:
        f.append(f'rubberband=pitch={2.0 ** (st / 12.0):.6f}')
    if float(p['hpf']) > 20.5:
        f.append(f'highpass=f={int(round(p["hpf"]))}')
    if float(p['lpf']) < 19995:
        f.append(f'lowpass=f={int(round(p["lpf"]))}')
    if abs(float(p['bass'])) > 0.05:
        f.append(f'lowshelf=f=120:g={float(p["bass"]):.2f}')
    if abs(float(p['treble'])) > 0.05:
        f.append(f'highshelf=f=6000:g={float(p["treble"]):.2f}')
    if abs(float(p['freq_shift'])) > 0.5:
        f.append(f'afreqshift=shift={float(p["freq_shift"]):.1f}')
    r = float(p['room'])
    if r > 0.5:
        d1 = int(p['room_ms'])
        d2 = int(d1 * 1.7)
        g1 = 0.45 * (r / 100.0)
        f.append(f'aecho=1:1:{d1}|{d2}:{g1:.3f}|{g1 * 0.55:.3f}')  # dry stays at unity
    pan = float(p['pan']) / 100.0
    if abs(pan) > 0.005:
        import math

        a = (pan + 1.0) * math.pi / 4.0
        lg, rg = math.sqrt(2) * math.cos(a), math.sqrt(2) * math.sin(a)
        f.append(f'pan=stereo|c0={lg:.4f}*c0|c1={rg:.4f}*c1')
    g = float(p['gain'])
    if abs(g) > 0.01:
        f.append(f'volume={g:.2f}dB')
    fi, fo = float(p['fade_in']) / 1000.0, float(p['fade_out']) / 1000.0
    if fi > 0.0005:
        f.append(f'afade=t=in:d={fi:.3f}')
    if fo > 0.0005:
        f += ['areverse', f'afade=t=in:d={fo:.3f}', 'areverse']
    return f


def _format_filters(channels):
    """One-time format setup shared by every stage-1 pass, whichever kind of
    slot runs first. Mono sources are duplicated to both channels explicitly:
    swresample's own mono→stereo upmix lands 3 dB down, and the library
    preview (the browser playing the mono file) does not."""
    f = [f'aresample={_SR}']
    if channels == 1:
        f.append('pan=stereo|c0=c0|c1=c0')
    f.append('aformat=sample_fmts=fltp:channel_layouts=stereo')
    return f


def _lock(key):
    with _LOCKS_GUARD:
        if len(_LOCKS) > 512:
            # bounded: a lock still held by a thread stays alive through that
            # thread's reference; the atomic tmp+replace writes make a rare
            # duplicate render of one key harmless
            _LOCKS.clear()
        lk = _LOCKS.get(key)
        if lk is None:
            lk = _LOCKS[key] = threading.Lock()
        return lk


def _dirs():
    for d in ('stems', 'mixes', 'analysis', 'exports'):
        os.makedirs(os.path.join(_WORK, d), exist_ok=True)


def _file_ident(fp):
    st = os.stat(fp)
    return f'{fp}|{int(st.st_mtime)}|{st.st_size}'


def stem(cat, fn, slots):
    """Render (or fetch) one layer's stem. Returns
    {'stem': 'stems/<h>.wav', 'dur': s, 'src_dur': s, 'slots': clean, 'cached': bool}
    or raises ValueError with a message safe to show."""
    fp = source_path(cat, fn)
    if not fp:
        raise ValueError(f'unknown library file {cat}/{fn}')
    sl = clean_slots(slots)
    _dirs()
    _sweep()
    key = hashlib.sha1(
        (_file_ident(fp) + '|' + json.dumps(sl, sort_keys=True) + f'|sr{_SR}v3').encode('utf-8'),
        usedforsecurity=False,
    ).hexdigest()[:24]
    rel = f'stems/{key}.wav'
    out = os.path.join(_WORK, rel)
    src_dur, channels = probe(fp)
    expect = src_dur
    for s in sl:
        if s['type'] == 'tweak':
            p = s['tweak']
            expect = (
                max(0.0, expect - float(p['trim_in']) - float(p['trim_out']))
                / max(0.25, float(p['tape']))
                / max(0.5, float(p['speed']))
            )
        elif sfx_fx is not None and sfx_fx.is_fx(s['type']):
            expect = sfx_fx.dur_after(s['type'], s['tweak'], expect)
        # a plugin slot is audio-in/audio-out: same length
    if expect > _MAX_LAYER_S:
        raise ValueError(
            f'{fn}: this layer would be {expect / 60:.1f} min long after '
            f'tape/speed — the merger caps a layer at {_MAX_LAYER_S / 60:.0f} min'
        )
    with _lock(rel):
        if os.path.isfile(out) and os.path.getsize(out) > 44:
            try:
                os.utime(out, None)  # a hit is a use: keep it out of the sweep
            except OSError as _exc:
                _zyg_log.debug('cache touch of %s skipped: %s', out, _exc)
            return {'stem': rel, 'dur': probe_duration(out), 'src_dur': src_dur, 'slots': sl, 'cached': True}
        tmp = _render_stem_chain(fp, sl, src_dur, channels, os.path.dirname(out))
        try:
            os.replace(tmp, out)
        except OSError:
            try:
                os.remove(tmp)
            except OSError as _exc:
                _zyg_log.debug('temp file %s cleanup skipped: %s', tmp, _exc)
            raise
    return {'stem': rel, 'dur': probe_duration(out), 'src_dur': src_dur, 'slots': sl, 'cached': False}


def _render_stem_chain(fp, sl, src_dur, channels, work_dir):
    """Run one layer's slot list stage by stage: consecutive 'tweak' slots
    batch into a single ffmpeg pass (as before — one filter graph, one
    process), and any plugin slot (see plugin_host.py) runs as its own pass
    between them, each stage's output feeding the next. An all-tweak (or
    empty) slot list is exactly one ffmpeg pass, same as before this existed.
    Returns a temp file path the caller owns (os.replace or os.remove it)."""
    made = []  # every intermediate temp, for cleanup

    def _mktemp(suffix='.wav'):
        fd, p = tempfile.mkstemp(dir=work_dir, suffix=suffix)
        os.close(fd)
        made.append(p)
        return p

    def _ffmpeg_stage(src, filters):
        t = _mktemp()
        code, err = _run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-i',
                src,
                '-af',
                ','.join(filters),
                '-ar',
                str(_SR),
                '-ac',
                '2',
                '-c:a',
                'pcm_f32le',
                t,
            ]
        )
        if code != 0:
            raise ValueError(f'ffmpeg failed: {err.strip()[-300:] or code}')
        return t

    def _batchable(typ):
        """A slot that contributes filters to an -af chain rather than needing a
        pass of its own: the Tweaker, and every sfx_fx block with a builder."""
        return typ == 'tweak' or (sfx_fx is not None and typ in sfx_fx.FILTER_IDS)

    ctx = {'src_dur': src_dur, 'sr': _SR}
    try:
        cur, formatted = fp, False
        i = 0
        while i < len(sl):
            typ = sl[i]['type']
            if _batchable(typ):
                j = i
                filters = [] if formatted else _format_filters(channels)
                while j < len(sl) and _batchable(sl[j]['type']):
                    if sl[j]['type'] == 'tweak':
                        filters += _tweak_filters(sl[j]['tweak'], src_dur)
                    else:
                        filters += sfx_fx.filters(sl[j]['type'], sl[j]['tweak'], ctx)
                    j += 1
                cur = _ffmpeg_stage(cur, filters or _format_filters(channels))
                formatted = True
                i = j
            else:
                if not formatted:  # a plugin needs a normalized wav to read
                    cur = _ffmpeg_stage(cur, _format_filters(channels))
                    formatted = True
                nxt = _mktemp()
                if sfx_fx is not None and typ in sfx_fx.RENDER_IDS:
                    # measure-then-apply, chunked ramps, two-input graphs: its own pass
                    sfx_fx.render(typ, sl[i]['tweak'], cur, nxt, _WORK)
                elif plugin_host is not None:
                    plugin_host.render(typ, sl[i]['tweak'], cur, nxt)
                else:
                    raise ValueError(f'plugin effects are unavailable on this server ({typ})')
                cur = nxt
                i += 1
        if not formatted:  # empty slot list: bare format pass, as before
            cur = _ffmpeg_stage(cur, _format_filters(channels))
        made.remove(cur)  # the caller now owns this one
        return cur
    finally:
        for p in made:
            try:
                os.remove(p)
            except OSError as _exc:
                _zyg_log.debug('temp file %s cleanup skipped: %s', p, _exc)


def _clean_items(items):
    if not isinstance(items, list):
        raise ValueError('items must be a list')
    if len(items) > MAX_ITEMS:
        raise ValueError(f'at most {MAX_ITEMS} layers per merge')
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        try:
            start = float(it.get('start') or 0.0)
        except (TypeError, ValueError):
            start = 0.0
        if start != start:
            start = 0.0
        start = max(0.0, min(_MAX_START_S, start))
        out.append(
            {
                'uid': str(it.get('uid') or f'i{i}')[:40],
                'cat': str(it.get('cat') or ''),
                'f': str(it.get('f') or ''),
                'name': str(it.get('name') or '')[:200],
                'start': round(start, 4),
                'slots': clean_slots(it['slots'] if 'slots' in it else it.get('tweak')),
            }
        )
    return out


def _peak_scale(f32_path, out_path):
    """Write the final s16 mix, scaled down ONCE if the float sum clips. Returns
    (peak_before, scale). A quiet merge is never pushed up — layers keep the
    levels the operator set relative to the library files. Two streamed passes
    (1 s blocks), so a ten-minute merge costs ~400 KB of RAM, not 230 MB."""
    import numpy as np
    import soundfile as sf

    peak = 0.0
    with sf.SoundFile(f32_path) as fin:
        sr, ch = fin.samplerate, fin.channels
        for blk in fin.blocks(blocksize=sr, dtype='float32', always_2d=True):
            if blk.size:
                peak = max(peak, float(np.max(np.abs(blk))))
    scale = 1.0 if peak <= 0.985 else 0.985 / peak
    with (
        sf.SoundFile(f32_path) as fin,
        sf.SoundFile(out_path, 'w', samplerate=sr, channels=ch, subtype='PCM_16') as fout,
    ):
        for blk in fin.blocks(blocksize=sr, dtype='float32', always_2d=True):
            fout.write(blk * scale if scale != 1.0 else blk)
    return peak, scale


def render_mix(items):
    """Render the whole merge. Returns the dict the tab consumes:
    {ok, mix:'mixes/<h>.wav', duration, peak, scale, cached,
     items:[{uid, stem, dur, start, end, src_dur, slots}]}."""
    _sweep()
    its = _clean_items(items)
    stems = []
    for it in its:
        s = stem(it['cat'], it['f'], it['slots'])
        stems.append(
            {
                'uid': it['uid'],
                'cat': it['cat'],
                'f': it['f'],
                'name': it['name'],
                'stem': s['stem'],
                'dur': round(s['dur'], 4),
                'src_dur': round(s['src_dur'], 4),
                'start': it['start'],
                'end': round(it['start'] + s['dur'], 4),
                'slots': s['slots'],
            }
        )
    if not stems:
        return {'ok': True, 'mix': '', 'duration': 0.0, 'peak': 0.0, 'scale': 1.0, 'cached': True, 'items': []}
    key = hashlib.sha1(
        json.dumps([(s['stem'], s['start']) for s in stems], sort_keys=True).encode('utf-8'),
        usedforsecurity=False,
    ).hexdigest()[:24]
    rel = f'mixes/{key}.wav'
    out = os.path.join(_WORK, rel)
    meta_p = out + '.json'
    duration = max(s['end'] for s in stems)
    if duration > _MAX_MIX_S:
        raise ValueError(
            f'the merge would run {duration / 60:.1f} min — the merger caps a merge at {_MAX_MIX_S / 60:.0f} min'
        )
    with _lock(rel):
        if os.path.isfile(out) and os.path.getsize(out) > 44:
            try:
                os.utime(out, None)
            except OSError as _exc:
                _zyg_log.debug('cache touch of %s skipped: %s', out, _exc)
            peak, scale = 0.0, 1.0
            try:
                with open(meta_p, 'r', encoding='utf-8') as fh:
                    m = json.load(fh)
                peak, scale = float(m.get('peak', 0)), float(m.get('scale', 1))
            except (OSError, ValueError) as _exc:
                _zyg_log.debug('mix sidecar %s unreadable, reporting peak 0.0 scale 1.0: %s', meta_p, _exc)
            return {
                'ok': True,
                'mix': rel,
                'duration': round(probe_duration(out), 4),
                'peak': peak,
                'scale': scale,
                'cached': True,
                'items': stems,
            }
        args = [exe('ffmpeg'), '-y', '-loglevel', 'error']
        for s in stems:
            args += ['-i', os.path.join(_WORK, s['stem'])]
        fc = []
        for i, s in enumerate(stems):
            n = int(round(s['start'] * _SR))
            fc.append(f'[{i}]adelay=delays={n}S:all=1[d{i}]')
        fc.append(
            ''.join(f'[d{i}]' for i in range(len(stems))) + f'amix=inputs={len(stems)}:normalize=0:duration=longest'
            f':dropout_transition=0[m]'
        )
        fd, tmp32 = tempfile.mkstemp(dir=os.path.dirname(out), suffix='.f32.wav')
        os.close(fd)
        args += [
            '-filter_complex',
            ';'.join(fc),
            '-map',
            '[m]',
            '-ar',
            str(_SR),
            '-ac',
            '2',
            '-c:a',
            'pcm_f32le',
            tmp32,
        ]
        code, err = _run(args)
        if code != 0:
            try:
                os.remove(tmp32)
            except OSError as _exc:
                _zyg_log.debug('temp file %s cleanup skipped: %s', tmp32, _exc)
            raise ValueError(f'ffmpeg mix failed: {err.strip()[-300:] or code}')
        fd, tmp16 = tempfile.mkstemp(dir=os.path.dirname(out), suffix='.wav')
        os.close(fd)
        try:
            peak, scale = _peak_scale(tmp32, tmp16)
        except Exception:
            try:
                os.remove(tmp16)
            except OSError as _exc:
                _zyg_log.debug('temp file %s cleanup skipped: %s', tmp16, _exc)
            raise
        finally:
            try:
                os.remove(tmp32)
            except OSError as _exc:
                _zyg_log.debug('temp file %s cleanup skipped: %s', tmp32, _exc)
        os.replace(tmp16, out)
        try:
            with open(meta_p, 'w', encoding='utf-8') as fh:
                json.dump({'peak': round(peak, 4), 'scale': round(scale, 4), 'items': stems, 'duration': duration}, fh)
        except OSError as _exc:
            _zyg_log.warning('mix sidecar %s write failed, the next run will re-measure: %s', meta_p, _exc)
    return {
        'ok': True,
        'mix': rel,
        'duration': round(probe_duration(out), 4),
        'peak': round(peak, 4),
        'scale': round(scale, 4),
        'cached': False,
        'items': stems,
    }


def resolve_audio(rel):
    """Work-dir path for '/inspect/merge/audio?p=…', or '' — only the two render
    subdirs, only hex names, only .wav."""
    rel = str(rel or '')
    if not _REL_RE.match(rel):
        return ''
    try:
        fp = os.path.realpath(os.path.join(_WORK, rel))
        root = os.path.realpath(_WORK)
        if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
            return ''
    except (OSError, ValueError):
        return ''
    return fp


def _sweep():
    now = time.time()
    if now - _SWEEP['ts'] < _SWEEP_EVERY:
        return
    _SWEEP['ts'] = now
    kept = []  # (mtime, size, path) survivors
    for sub, ttl in (('mixes', _MIX_TTL), ('stems', _STEM_TTL)):
        d = os.path.join(_WORK, sub)
        try:
            names = os.listdir(d)
        except OSError as _exc:
            _zyg_log.debug('cache dir %s unreadable, skipped in the sweep: %s', d, _exc)
            continue
        for n in names:
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
                if now - st.st_mtime > ttl:
                    os.remove(p)
                else:
                    kept.append((st.st_mtime, st.st_size, p))
            except OSError as _exc:
                _zyg_log.debug('ttl sweep skipped %s: %s', p, _exc)
    total = sum(k[1] for k in kept)
    if total > _BUDGET_BYTES:
        kept.sort()  # oldest first
        for _mt, sz, p in kept:
            if total <= _BUDGET_BYTES:
                break
            try:
                os.remove(p)
                total -= sz
            except OSError as _exc:
                _zyg_log.debug('budget sweep could not remove %s: %s', p, _exc)
            # a mix's sidecar .json goes with it
            if p.endswith('.wav'):
                try:
                    os.remove(p + '.json')
                except OSError as _exc:
                    _zyg_log.debug('sidecar of %s cleanup skipped: %s', p, _exc)
