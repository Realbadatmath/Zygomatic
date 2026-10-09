#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Like-for-like downshift/warming comparison for the liked Farmyard take.

Three engines, same two sources, same shifts, so the difference you hear is the
engine and nothing else:

* **R2** - ffmpeg's `rubberband` filter.  libavfilter/af_rubberband.c hard-codes
  RubberBandOptionProcessRealTime and never sets OptionEngineFiner, so every
  shift the pipeline made before this ran the *older* R2 engine.  This is the
  baseline that was judged, not a straw man.
* **R3** - the very same librubberband 3.3.0 that is already on the box, driven
  offline with OptionEngineFiner via tools/rubberband_r3.py (ctypes; no build,
  no sudo, because rubberband-cli would need root).
* **SS** - Signalsmith Stretch (MIT) through the `python-stretch` wheel.

Plus the *formant-only* controls: the note does not move at all, only the
vocal-tract envelope is scaled down, which reads as a warmer/larger singer.
They are the answer to "is it really the pitch that is wrong, or the timbre?".

Outputs (mp3 256k, decoded at 48 kHz stereo):
    output/kidsmusic/0fc29420eb5a/pitch_fix_ss/
        <src>_<key>.mp3  x 20   index.json   listen.html

Every take is measured back against its own source with
sung_pitch.shift_semitones: the transposed ones must land on the semitones they
asked for, the formant-only ones must land on 0.00.

    python tools/farmyard_stretch.py            # build everything
    python tools/farmyard_stretch.py --measure-only   # re-measure what is there
"""

from __future__ import annotations

import argparse
import json
import logging as _zyg_logging
import os
import subprocess
import sys
import tempfile
from zyg_workflows.bin import exe

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CREWS not in sys.path:
    sys.path.insert(0, CREWS)

from zyg_workflows import sung_pitch  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

JOB = '0fc29420eb5a'
SONG = 'The Farmyard Sounds Song'
ROOT = os.path.join(CREWS, 'output', 'kidsmusic', JOB)
SRC_DIR = os.path.join(ROOT, 'voice_sweep')
OUT_DIR = os.path.join(ROOT, 'pitch_fix_ss')
R3 = os.path.join(CREWS, 'tools', 'rubberband_r3.py')

SOURCES = [
    ('v02', 'v02_bright_soprano_master.mp3', 'v02 bright soprano (the liked take)'),
    ('v01', 'v01_warm_control_master.mp3', 'v01 warm control'),
]

# key, method, asked semitones, formant treatment
VARIANTS = [
    ('r2_down2', 'r2', -2.0, 'preserved'),
    ('r2_down3', 'r2', -3.0, 'preserved'),
    ('r3_down2', 'r3', -2.0, 'preserved'),
    ('r3_down3', 'r3', -3.0, 'preserved'),
    ('r3f_down3', 'r3', -3.0, 'follow'),
    ('ss_down2', 'ss', -2.0, 'compensated'),
    ('ss_down3', 'ss', -3.0, 'compensated'),
    ('r3_form_m1', 'r3', 0.0, 'explicit -1.00 st'),
    ('r3_form_m2', 'r3', 0.0, 'explicit -2.00 st'),
    ('ss_form_m15', 'ss', 0.0, 'explicit -1.50 st'),
]

TOL = 0.15
CORR_MIN = 0.85


# ---------------------------------------------------------------------------
# engines
# ---------------------------------------------------------------------------


def build_r2(src, dst, semitones):
    """ffmpeg af_rubberband: the R2 engine, formants preserved. What we had."""
    pitch = 2.0 ** (semitones / 12.0)
    subprocess.run(
        [
            exe('ffmpeg'),
            '-y',
            '-v',
            'error',
            '-i',
            src,
            '-af',
            'rubberband=pitch=%.9f:formant=preserved' % pitch,
            '-ar',
            '48000',
            '-ac',
            '2',
            '-c:a',
            'libmp3lame',
            '-b:a',
            '256k',
            dst,
        ],
        check=True,
    )
    return {'engine': 'ffmpeg af_rubberband (R2)', 'engine_version': 2}


def build_r3(src, dst, semitones, formant):
    """tools/rubberband_r3.py: same library, OptionEngineFiner, offline."""
    cmd = [sys.executable, R3, src, dst, '--semitones', '%g' % semitones]
    if formant == 'follow':
        cmd.append('--formant-follow')
    elif formant.startswith('explicit'):
        cmd += ['--formant-semitones', formant.split()[1]]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    rec = json.loads(out.strip().splitlines()[-1])
    return {'engine': 'librubberband 3.3.0 (R3 finer)', 'engine_version': rec.get('engine_version')}


_SS_ERR = None


def _ss_stretch():
    """Resolve the Signalsmith Stretch class from the python-stretch wheel."""
    import python_stretch as _m  # wheel python-stretch 0.3.1: module is python_stretch

    for path in (('Signalsmith', 'Stretch'), ('Stretch',), ('signalsmith', 'Stretch')):
        obj = _m
        for part in path:
            obj = getattr(obj, part, None)
            if obj is None:
                break
        if obj is not None:
            return obj
    raise ImportError('python-stretch imported but no Stretch class found in %r' % (dir(_m),))


def build_ss(src, dst, semitones, formant):
    """Signalsmith Stretch: transpose with formant compensation, or formant only."""
    import numpy as np
    import soundfile as sf

    Stretch = _ss_stretch()
    x, sr = _decode(src)  # (channels, samples) float32
    s = Stretch()
    if hasattr(s, 'preset'):
        s.preset(x.shape[0], sr)
    elif hasattr(s, 'configure'):
        s.configure(x.shape[0], sr // 100, sr // 400)
    # python-stretch 0.3.1 exposes setTransposeSemitones(semitones, tonalityLimit)
    # and NO formant API (checked: dir(Stretch) has no setFormantSemitones /
    # setFormantBase). Signalsmith's own recommendation for vocals is a
    # tonality limit of 8000 Hz / sampleRate: content above it is not
    # transposed, which is the library's envelope-preserving mode.
    if formant == 'compensated':
        s.setTransposeSemitones(float(semitones), 8000.0 / float(sr))
    elif formant.startswith('explicit'):
        raise NotImplementedError(
            'python-stretch 0.3.1 has no formant-only API '
            '(no setFormantSemitones); formant-only rows '
            'come from rubberband_r3.py instead'
        )
    else:
        s.setTransposeSemitones(float(semitones))
    y = np.ascontiguousarray(s.process(x).astype(np.float32))
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
        w = t.name
    sf.write(w, y.T, sr, subtype='FLOAT')
    subprocess.run([exe('ffmpeg'), '-y', '-v', 'error', '-i', w, '-c:a', 'libmp3lame', '-b:a', '256k', dst], check=True)
    os.unlink(w)
    return {'engine': 'Signalsmith Stretch (python-stretch)', 'engine_version': None}


def _decode(path, sr=48000):
    import numpy as np
    import soundfile as sf

    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
        w = t.name
    subprocess.run(
        [exe('ffmpeg'), '-y', '-v', 'error', '-i', path, '-ar', str(sr), '-ac', '2', '-c:a', 'pcm_f32le', w], check=True
    )
    x, got = sf.read(w, dtype='float32', always_2d=True)
    os.unlink(w)
    return np.ascontiguousarray(x.T), got


# ---------------------------------------------------------------------------

BLURB = 'R2 = what ffmpeg gave before; R3 = the finer engine in the same library; formant-only = pitch untouched'


def build(measure_only=False):
    global _SS_ERR
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        _ss_stretch()
    except Exception as exc:  # noqa: BLE001
        _SS_ERR = '%s: %s' % (type(exc).__name__, exc)
        _zyg_log.warning('[ss] unavailable -> %s' % _SS_ERR)

    takes, skipped = [], []
    for skey, sname, slabel in SOURCES:
        src = os.path.join(SRC_DIR, sname)
        sspec = sung_pitch.spec(src)  # measure against this, once
        for key, method, asked, formant in VARIANTS:
            dst = os.path.join(OUT_DIR, '%s_%s.mp3' % (skey, key))
            if method == 'ss' and _SS_ERR:
                skipped.append('%s_%s' % (skey, key))
                continue
            if not (measure_only and os.path.exists(dst)):
                if method == 'r2':
                    info = build_r2(src, dst, asked)
                elif method == 'r3':
                    info = build_r3(src, dst, asked, formant)
                else:
                    try:
                        info = build_ss(src, dst, asked, formant)
                    except NotImplementedError as exc:
                        skipped.append('%s_%s: %s' % (skey, key, exc))
                        continue
            else:
                info = {'engine': None, 'engine_version': None}
            st, corr = sung_pitch.shift_semitones(sspec, dst)
            row = {
                'key': key,
                'source': sname,
                'source_key': skey,
                'source_label': slabel,
                'method': method,
                'engine': info.get('engine'),
                'engine_version': info.get('engine_version'),
                'asked_semitones': asked,
                'formant': formant,
                'measured_semitones': round(st, 3),
                'correlation': round(corr, 4),
                'file': os.path.basename(dst),
            }
            row['ok'] = abs(st - asked) <= TOL and (corr > CORR_MIN or asked == 0.0)
            takes.append(row)
            _zyg_log.info(
                '%-4s %-12s asked %+5.2f  measured %+6.2f  corr %.4f  %s'
                % (skey, key, asked, st, corr, 'ok' if row['ok'] else 'FAIL')
            )

    index = {
        'song': SONG,
        'job': JOB,
        'blurb': BLURB,
        'sources': [{'key': k, 'file': n, 'label': l} for k, n, l in SOURCES],
        'signalsmith_error': _SS_ERR,
        'skipped': skipped,
        'takes': takes,
    }
    with open(os.path.join(OUT_DIR, 'index.json'), 'w') as fh:
        json.dump(index, fh, indent=1)
    write_html(index)
    return index


# ---------------------------------------------------------------------------


def _cell(rows, skey, key, title):
    r = next((x for x in rows if x['source_key'] == skey and x['key'] == key), None)
    if r is None:
        return '<td class="na"><b>%s</b><br><span class=miss>not built</span></td>' % title
    cls = '' if r['ok'] else ' class=bad'
    return (
        '<td><b>%s</b><br><audio controls preload=none src="%s"></audio>'
        '<div%s>%+.2f st &middot; corr %.3f</div></td>'
        % (title, r['file'], cls, r['measured_semitones'], r['correlation'])
    )


def write_html(index):
    rows = index['takes']
    h = [
        '<!doctype html><meta charset=utf-8>',
        '<title>Farmyard - R2 vs R3 vs Signalsmith</title>',
        '<style>',
        'body{font:15px/1.5 system-ui,sans-serif;margin:24px;background:#111;color:#eee}',
        'h1{font-size:20px;margin:0 0 4px}',
        'p.blurb{background:#1d2a1d;border-left:4px solid #6c6;padding:10px 14px;margin:0 0 20px;font-size:16px}',
        'table{border-collapse:collapse;margin:0 0 28px;width:100%}',
        'th,td{border:1px solid #333;padding:8px 10px;vertical-align:top;font-size:13px}',
        'th{background:#1c1c1c;text-align:left}',
        'td.rowhead{background:#181818;white-space:nowrap;font-weight:600}',
        'td.na{color:#777}.miss{color:#a55}.bad{color:#e66}',
        'audio{width:220px;height:32px;display:block;margin:4px 0}',
        'div{color:#8a8;font-size:12px}h2{font-size:16px;margin:22px 0 8px}',
        '</style>',
        '<h1>%s &mdash; downshift and warming, like for like</h1>' % index['song'],
        '<p class=blurb>%s</p>' % index['blurb'],
    ]
    if index.get('signalsmith_error'):
        h.append(
            '<p class=blurb style="background:#2a1d1d;border-color:#c66">'
            'Signalsmith Stretch column unavailable: %s</p>' % index['signalsmith_error']
        )

    h.append('<h2>Transposed &mdash; the note moves down, the timbre is kept</h2>')
    h.append(
        '<table><tr><th>take</th><th>original</th><th>R2 (ffmpeg, before)</th>'
        '<th>R3 (finer)</th><th>R3 formant-follow</th><th>Signalsmith</th></tr>'
    )
    for skey, sname, slabel in SOURCES:
        for n in (2, 3):
            h.append('<tr><td class=rowhead>%s<br>&minus;%d st</td>' % (slabel, n))
            h.append('<td><b>source</b><br><audio controls preload=none src="../voice_sweep/%s"></audio></td>' % sname)
            h.append(_cell(rows, skey, 'r2_down%d' % n, 'R2 &minus;%d' % n))
            h.append(_cell(rows, skey, 'r3_down%d' % n, 'R3 &minus;%d' % n))
            h.append(
                _cell(rows, skey, 'r3f_down%d' % n, 'R3 follow &minus;%d' % n)
                if n == 3
                else '<td class="na">&mdash;</td>'
            )
            h.append(_cell(rows, skey, 'ss_down%d' % n, 'SS &minus;%d' % n))
            h.append('</tr>')
    h.append('</table>')

    h.append('<h2>Formant-only &mdash; the pitch does not move at all</h2>')
    h.append(
        '<table><tr><th>take</th><th>original</th><th>R3 formant &minus;1</th>'
        '<th>R3 formant &minus;2</th><th>Signalsmith formant &minus;1.5</th></tr>'
    )
    for skey, sname, slabel in SOURCES:
        h.append('<tr><td class=rowhead>%s<br>formant only</td>' % slabel)
        h.append('<td><b>source</b><br><audio controls preload=none src="../voice_sweep/%s"></audio></td>' % sname)
        h.append(_cell(rows, skey, 'r3_form_m1', 'R3 form &minus;1'))
        h.append(_cell(rows, skey, 'r3_form_m2', 'R3 form &minus;2'))
        h.append(_cell(rows, skey, 'ss_form_m15', 'SS form &minus;1.5'))
        h.append('</tr>')
    h.append('</table>')
    with open(os.path.join(OUT_DIR, 'listen.html'), 'w') as fh:
        fh.write('\n'.join(h))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument(
        '--measure-only', action='store_true', help='do not re-render, just re-measure and rewrite the index'
    )
    a = ap.parse_args(argv)
    index = build(measure_only=a.measure_only)
    bad = [r for r in index['takes'] if not r['ok']]
    print(
        '\n%d takes, %d bad%s'
        % (len(index['takes']), len(bad), (': ' + ', '.join(r['key'] for r in bad)) if bad else '')
    )
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
