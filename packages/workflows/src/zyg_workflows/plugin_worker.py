#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""plugin_worker.py — runs exactly one VST3 plugin call, in its own process.

Third-party native plugin code is not trustworthy the way ffmpeg is: while
building this (see plugin_host.py's docstring) Cardinal's VST3 segfaulted on
teardown once and hung on load once, both in a supposedly headless load. A
crash or hang HERE must never take the long-lived kanban-server down with it
— sfx_merger._run() gets the same isolation for ffmpeg via subprocess, this
gives the same guarantee to plugin DSP. Talks one JSON request on stdin, one
JSON response on stdout; the parent always runs this under a hard timeout.
"""

import json
import sys
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


SKIP_SUB = ('sidechain', 'visibility', 'overlay', 'graph_analysis', 'pause', 'clear', 'listen', 'show_')
MAX_KNOBS = 24


def _unit_for(key):
    if key.endswith('_db'):
        return 'dB'
    if key.endswith('_hz'):
        return 'Hz'
    if key.endswith('_ms'):
        return 'ms'
    return ''


def _load(vst3, plugin_name):
    from pedalboard import load_plugin

    return load_plugin(vst3, plugin_name=plugin_name)


def introspect(vst3, plugin_name):
    """The plugin's real parameters, filtered to ones meaningful for an
    offline single-file render (no sidechain input exists in this pipeline;
    GUI meter/overlay toggles do nothing to the audio) and expressible as a
    knob (a real numeric range, or a plain on/off)."""
    p = _load(vst3, plugin_name)
    knobs = []
    for k, v in p.parameters.items():
        if any(s in k for s in SKIP_SUB):
            continue
        rng = getattr(v, 'range', None)
        if not rng:
            continue
        lo, hi, step = rng
        if (lo, hi) == (False, True):
            knobs.append(
                {
                    'key': k,
                    'type': 'toggle',
                    'label': getattr(v, 'name', k) or k,
                    'def': bool(getattr(p, k)),
                    'hint': '',
                }
            )
        elif lo is not None and hi is not None:
            lof = -60.0 if lo == float('-inf') else float(lo)
            hif = 60.0 if hi == float('inf') else float(hi)
            try:
                defv = float(getattr(p, k))
            except (TypeError, ValueError):
                defv = lof
            if defv != defv or defv in (float('-inf'), float('inf')):
                defv = lof
            defv = max(lof, min(hif, defv))
            knobs.append(
                {
                    'key': k,
                    'type': 'knob',
                    'label': getattr(v, 'name', k) or k,
                    'def': round(defv, 4),
                    'min': round(lof, 4),
                    'max': round(hif, 4),
                    'step': round(float(step), 6) if step else round(max((hif - lof) / 200.0, 0.001), 4),
                    'unit': _unit_for(k),
                    'hint': '',
                }
            )
        if len(knobs) >= MAX_KNOBS:
            break
    return knobs


def render(vst3, plugin_name, params, in_wav, out_wav):
    import soundfile as sf

    p = _load(vst3, plugin_name)
    for k, v in (params or {}).items():
        try:
            setattr(p, k, v)
        except Exception as _exc:
            _zyg_log.warning('plugin parameter %s not applied, keeping plugin default: %s', k, _exc)
    with sf.SoundFile(in_wav) as f:
        audio = f.read(dtype='float32', always_2d=True).T  # pedalboard wants (channels, samples)
        sr = f.samplerate
    out = p.process(audio, sr)
    sf.write(out_wav, out.T, sr, subtype='FLOAT')


def _handle(req):
    mode = req.get('mode')
    if mode == 'introspect':
        result = {}
        for item in req['plugins']:
            try:
                result[item['id']] = introspect(req['vst3'], item['plugin_name'])
            except Exception as e:  # noqa: BLE001
                result[item['id']] = {'error': str(e)}
        return {'ok': True, 'racks': result}
    if mode == 'render':
        render(req['vst3'], req['plugin_name'], req.get('params') or {}, req['in_wav'], req['out_wav'])
        return {'ok': True}
    if mode == 'ping':
        return {'ok': True}
    return {'ok': False, 'error': 'bad mode'}


def main():
    """One request per stdin line, one JSON response per stdout line — kept
    running so the VST3 module scan (~8 s for the LSP bundle: JUCE parses all
    198 sub-plugins' descriptors, once, in-process) is paid ONCE per worker
    lifetime, not once per render. plugin_host.py owns restarting this if it
    ever dies or hangs."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = _handle(req)
        except Exception as e:  # noqa: BLE001
            resp = {'ok': False, 'error': str(e)}
        sys.stdout.write(json.dumps(resp) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
