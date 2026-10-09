# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Analysis — everything the studio can MEASURE about a sound."""

from zyg_workflows.bin import exe
import hashlib
import json
import os
import subprocess
from zyg_workflows.sfx_merger.constants import _FF_TIMEOUT, _RENDER_SEM, _WORK, _zyg_log
from zyg_workflows.sfx_merger.render import _run, source_path, stem

# ── analysis ──────────────────────────────────────────────────────────────────
# Everything the studio can MEASURE about a sound as it currently stands, in
# one pass per instrument. This exists because the toolbox lets you stack sixty
# effects on a layer: without numbers, "is it clipping now?" and "did that make
# it quieter?" are guesses, and a guess about level is how a bed ends up 6 dB
# hot in a finished film. See feedback_measure_before_claim.
_ANALYSIS_TTL = 3 * 86400


def _num(v):
    """A measurement, or None. drmeter answers '-nan' on a file too short to
    have a dynamic range, ffmpeg writes '-inf' for a silent stretch, and
    json.dumps turns both into bare NaN / Infinity — which every browser
    refuses to parse, taking the whole analysis sheet down with it."""
    try:
        f = float(str(v).split()[0])
    except (TypeError, ValueError, IndexError):
        return None
    return f if f == f and abs(f) != float('inf') else None


def _stats_pass(fp):
    """astats + ebur128 + drmeter + silencedetect over one file, parsed."""
    args = [
        exe('ffmpeg'),
        '-hide_banner',
        '-nostats',
        '-i',
        fp,
        '-af',
        'astats=measure_overall=all:measure_perchannel=all,'
        'ebur128=peak=true:framelog=quiet,drmeter,'
        'silencedetect=n=-50dB:d=0.15',
        '-f',
        'null',
        '-',
    ]
    # NOT through _run(): that keeps the last 800 characters, which is the right
    # amount for an error message and drops two thirds of an astats report —
    # every level line lands above the cut, which is exactly why peak and RMS
    # came back empty the first time this ran.
    with _RENDER_SEM:
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=_FF_TIMEOUT)
            err = r.stderr or ''
        except (subprocess.SubprocessError, OSError) as e:
            return {'error': str(e)[:200], 'silence': []}
    out = {}
    sil = []
    section = ''
    for raw in err.splitlines():
        line = raw.strip()
        if line.startswith('[Parsed_'):  # every filter's lines carry one
            line = line.split(']', 1)[-1].strip()
        if line.lower() == 'overall':
            section = 'overall'
            continue
        if ':' in line:
            k, _, v = line.partition(':')
            # "Peak level dB" -> peak_level; the unit is in the name, not the value
            k = k.strip().lower().replace(' ', '_')
            if k.endswith('_db'):
                k = k[:-3]
            v = v.strip()
            if k in (
                'peak_level',
                'rms_level',
                'rms_peak',
                'rms_trough',
                'crest_factor',
                'flat_factor',
                'dc_offset',
                'dynamic_range',
                'zero_crossings_rate',
                'peak_count',
                'noise_floor',
                'entropy',
                'number_of_samples',
                'bit_depth',
                'mean_difference',
                'abs_peak_count',
            ):
                n = _num(v)
                if n is not None and (section == 'overall' or k not in out):
                    out[k] = n
            elif k == 'i' and 'lufs' in v.lower():
                n = _num(v)
                if n is not None:
                    out['lufs_i'] = n
            elif k == 'lra' and 'lu' in v.lower():
                n = _num(v)
                if n is not None:
                    out['lra'] = n
            elif k == 'peak' and 'dbfs' in v.lower():
                n = _num(v)
                if n is not None:
                    out['true_peak'] = n
            elif k == 'threshold' and 'lufs' in v.lower():
                n = _num(v)
                if n is not None:
                    out['lufs_thresh'] = n
            elif k in ('dr_value', 'overall_dr', 'overall'):
                n = _num(v)
                if n is not None:
                    out['dr'] = n
        if 'silence_start' in line:
            n = _num(line.split('silence_start:')[1])
            if n is not None:
                sil.append(['start', n])
        elif 'silence_end' in line:
            n = _num(line.split('silence_end:')[1])
            if n is not None:
                sil.append(['end', n])
    out['silence'] = sil[:40]
    return out


def _picture(fp, rel, kind):
    """One analysis picture. Content-addressed like every other render, so the
    same sound never draws twice."""
    out = os.path.join(_WORK, rel)
    if os.path.isfile(out) and os.path.getsize(out) > 512:
        try:
            os.utime(out, None)
        except OSError as _exc:
            _zyg_log.debug('cache touch of %s skipped: %s', out, _exc)
        return rel
    if kind == 'spectrogram':
        af = 'showspectrumpic=s=1200x420:mode=combined:color=intensity:scale=log:legend=1:gain=2'
    else:
        # scale=sqrt, not linear: a −25 dBFS layer drew as a flat line, and a
        # waveform you cannot see is a dead tool. draw=full keeps single-sample
        # transients visible at 1200 px instead of averaging them away.
        af = 'showwavespic=s=1200x260:colors=#00e5ff|#7c5cff:split_channels=1:scale=sqrt:draw=full'
    tmp = os.path.join(os.path.dirname(out), f'.tmp-{os.getpid()}-{os.path.basename(out)}')
    code, err = _run([exe('ffmpeg'), '-y', '-loglevel', 'error', '-i', fp, '-lavfi', af, '-frames:v', '1', tmp])
    if code != 0:
        try:
            os.remove(tmp)
        except OSError as _exc:
            _zyg_log.debug('temp file %s cleanup skipped: %s', tmp, _exc)
        return ''
    os.replace(tmp, out)
    return rel


def analyze(cat, fn, slots, pictures=True):
    """Measure one layer as its chain currently leaves it. Returns the numbers,
    the source's own facts, and the two pictures."""
    st = stem(cat, fn, slots)
    fp = os.path.join(_WORK, st['stem'])
    src = source_path(cat, fn)
    m = _stats_pass(fp)
    key = os.path.basename(st['stem']).split('.')[0]
    pics = {}
    if pictures:
        for kind, _suffix in (('spectrogram', 's'), ('waveform', 'w')):
            h = hashlib.sha1(f'{key}|{kind}|v1'.encode(), usedforsecurity=False).hexdigest()[:24]
            rel = _picture(fp, f'analysis/{h}.png', kind)
            if rel:
                pics[kind] = rel
    info = {}
    if src:
        try:
            # ffprobe answers on stdout; _run() hands back stderr, so this
            # one call is made directly rather than through it
            r = subprocess.run(
                [exe('ffprobe'), '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', src],
                capture_output=True,
                text=True,
                timeout=30,
            )
            j = json.loads(r.stdout or '{}')
            a = ([x for x in j.get('streams', []) if x.get('codec_type') == 'audio'] or [{}])[0]
            f = j.get('format', {})
            info = {
                'codec': a.get('codec_name', ''),
                'sample_rate': a.get('sample_rate', ''),
                'channels': a.get('channels', 0),
                'bits': a.get('bits_per_raw_sample') or a.get('bits_per_sample') or '',
                'bitrate': f.get('bit_rate', ''),
                'size': f.get('size', ''),
                'format': f.get('format_name', ''),
                'duration': float(f.get('duration') or 0),
            }
        except (OSError, ValueError, subprocess.SubprocessError):
            info = {}
    return {
        'ok': True,
        'stem': st['stem'],
        'dur': st['dur'],
        'src_dur': st['src_dur'],
        'stats': m,
        'source': info,
        'pictures': pics,
        'slots': st['slots'],
    }
