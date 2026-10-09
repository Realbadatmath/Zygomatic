# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.synthesis — ffmpeg plumbing, synthesis and measurement.

Moved verbatim from voice_studio.py lines 1259-1569 (2026-10-06 split).
"""

from __future__ import annotations

from zyg_workflows.bin import exe
import json
import logging as _zyg_logging
import os
import shutil
import subprocess
import time

from zyg_workflows.voice_studio.constants import (
    _CHATTERBOX_PY,
    _CHATTERBOX_WORKER,
    _INDEXTTS_PY,
    _INDEXTTS_WORKER,
    _SEED_SR,
    _SR,
    _TTS_CORES,
    _TTS_THREADS,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.voice_studio')


# ───────────────────────────────────────────────────────────── ffmpeg plumbing
def _run(cmd: list, timeout: float = 900) -> 'tuple[int, str]':
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stderr or '')[-600:]
    except subprocess.TimeoutExpired:
        return 124, 'timeout'
    except OSError as e:
        return 125, str(e)[:200]


def _resample_chain(sr: int, factor: float) -> list:
    """Speed-linked shift by `factor`: pitch AND formants move together, duration
    is put back with atempo. Returns filter fragments."""
    return [f'asetrate={int(round(sr * factor))}', f'aresample={sr}', f'atempo={1.0 / factor:.6f}']


def seed_chain(p: dict) -> list:
    """The documented seed transform: asetrate/atempo k, then rubberband m with
    formants preserved. Reproduces abel_narrator_seed.json's numbers exactly."""
    f = [f'aresample={_SEED_SR}']
    k, m = float(p['seed_k']), float(p['seed_m'])
    if abs(k - 1.0) > 1e-6:
        f += _resample_chain(_SEED_SR, k)
    if abs(m - 1.0) > 1e-6:
        f.append(f'rubberband=pitch={m:.6f}:formant=preserved')
    return f


def render_chain(p: dict) -> list:
    """Post-synthesis chain. Every knob at its default collapses this to a bare
    resample, so 'defaults' means 'the engine's own output, level-matched'."""
    f = [f'aresample={_SR}']
    if float(p['hpf']) > 25:
        f.append(f'highpass=f={int(p["hpf"])}')

    # Size first (resample: pitch + tract together), then the formant-preserving
    # pitch move. These are deliberately NOT combined into a "formant scale that
    # leaves pitch alone" — that trick needs rubberband to preserve formants in
    # both directions, and measurement on this build (2026-08-11, Abel identity
    # reference) says it does not: pitch=1.1:formant=preserved lands on VTL
    # 14.46 cm, byte-for-byte the same as formant=shifted and as a plain
    # resample. Cancelling the resample with a preserved shift therefore cancels
    # the tract change too, and a "formant" knob built that way delivered 2 % of
    # its nominal 10 %. Two honest levers beat one that lies.
    sz = float(p['size'])
    if abs(sz - 1.0) > 1e-6:
        f += _resample_chain(_SR, sz)
    rb = 2.0 ** (float(p['pitch_st']) / 12.0)
    if abs(rb - 1.0) > 1e-6:
        f.append(f'rubberband=pitch={rb:.6f}:formant=preserved')

    if abs(float(p['tempo']) - 1.0) > 1e-6:
        f.append(f'atempo={float(p["tempo"]):.6f}')

    for key, ff, width in (('warmth', 200, 1.2), ('body', 450, 1.0), ('mid', 1200, 1.0), ('presence', 3500, 1.0)):
        g = float(p[key])
        if abs(g) > 0.05:
            f.append(f'equalizer=f={ff}:t=o:w={width}:g={g:.2f}')
    if abs(float(p['air'])) > 0.05:
        f.append(f'highshelf=f=9000:g={float(p["air"]):.2f}')

    d = float(p['deess'])
    if d > 0.5:
        f.append(f'deesser=i={d / 100.0:.3f}:m=0.5:f=0.5:s=o')

    c = float(p['comp'])
    if c > 0.5:
        ratio = 1.0 + 3.0 * (c / 100.0)  # 1:1 → 4:1
        thr_db = -12.0 - 18.0 * (c / 100.0)  # −12 → −30 dBFS
        thr_lin = max(0.000976563, min(1.0, 10.0 ** (thr_db / 20.0)))
        f.append(f'acompressor=threshold={thr_lin:.6f}:ratio={ratio:.2f}:attack=15:release=250:makeup=1:detection=rms')

    r = float(p['room'])
    if r > 0.5:
        d1 = int(p['room_ms'])
        d2 = int(d1 * 1.7)
        g1 = 0.45 * (r / 100.0)
        f.append(f'aecho=0.95:0.9:{d1}|{d2}:{g1:.3f}|{g1 * 0.55:.3f}')
    return f


def _apply(in_wav: str, out_wav: str, filters: list, sr: int) -> 'str|None':
    args = [exe('ffmpeg'), '-y', '-loglevel', 'error', '-i', in_wav]
    if filters:
        args += ['-af', ','.join(filters)]
    args += ['-ar', str(sr), '-ac', '1', '-c:a', 'pcm_s16le', out_wav]
    rc, err = _run(args)
    if rc != 0 or not os.path.isfile(out_wav) or os.path.getsize(out_wav) <= 44:
        return None
    return out_wav


# ───────────────────────────────────────────────────────────────── synthesis
def _last_json_line(text: str) -> dict:
    for line in reversed((text or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('worker output line is not the json result, looking further back: %s', _exc)
                continue
    return {}


def _gpu_usable() -> bool:
    try:
        return subprocess.run([exe('nvidia-smi'), '-L'], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def _synth_timeout(text: str) -> float:
    words = max(1, len(text.split()))
    return min(3600.0, 420.0 + (2.0 if _gpu_usable() else 10.0) * words)


def synth(text: str, ref_wav: str, out_wav: str, p: dict, log) -> 'str|None':
    """One-shot synthesis through the requested engine's isolated venv. Returns
    out_wav or None. No fallback: on the Voices tab a silent engine swap would
    make the operator judge a knob move on the WRONG engine."""
    eng = p['engine']
    if eng == 'indextts2':
        if not (os.path.isfile(_INDEXTTS_PY) and os.path.isfile(_INDEXTTS_WORKER)):
            log('IndexTTS-2 venv/worker missing')
            return None
        cmd = [
            _INDEXTTS_PY,
            _INDEXTTS_WORKER,
            '--text',
            text,
            '--out',
            out_wav,
            '--ref',
            ref_wav,
            '--seed',
            str(int(p['eng_seed'])),
            '--emo-alpha',
            f'{float(p["ix_emo_alpha"]):g}',
            '--threads',
            _TTS_THREADS,
        ]
        if not p['ix_emo_text']:
            cmd.append('--no-emo-text')
    else:
        if not (os.path.isfile(_CHATTERBOX_PY) and os.path.isfile(_CHATTERBOX_WORKER)):
            log('Chatterbox venv/worker missing')
            return None
        dev = p['device']
        if dev == 'auto':
            dev = 'cuda' if _gpu_usable() else 'cpu'
        cmd = [
            _CHATTERBOX_PY,
            _CHATTERBOX_WORKER,
            '--text',
            text,
            '--out',
            out_wav,
            '--ref',
            ref_wav,
            '--seed',
            str(int(p['eng_seed'])),
            '--exaggeration',
            f'{float(p["cb_exaggeration"]):g}',
            '--cfg-weight',
            f'{float(p["cb_cfg_weight"]):g}',
            '--temperature',
            f'{float(p["cb_temperature"]):g}',
            '--device',
            dev,
        ]
        log(f'device: {dev}')
    if _TTS_CORES and shutil.which('taskset'):
        cmd = ['taskset', '-c', _TTS_CORES] + cmd
    env = dict(os.environ)
    for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[k] = _TTS_THREADS
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=_synth_timeout(text))
    except subprocess.TimeoutExpired:
        log(f'{eng}: TIMED OUT after {_synth_timeout(text):.0f}s')
        return None
    res = _last_json_line(r.stdout)
    ok = bool(res.get('ok')) or (
        # Native fd-1 writes (CUDA banners) can mangle the JSON line; artifact
        # evidence wins when the worker exited clean. Same rule as abel_voice.
        not res and r.returncode == 0 and os.path.isfile(out_wav) and os.path.getsize(out_wav) > 44
    )
    if not ok:
        log(f'{eng} failed: {res.get("error") or (r.stderr or "")[-240:]}')
        return None
    log(f'{eng}: rendered in {time.time() - t0:.1f}s')
    return out_wav if os.path.isfile(out_wav) else None


def synth_batch(items: list, ref_wav: str, p: dict, log) -> int:
    """Synthesise many lines through ONE worker invocation. Returns how many
    landed. items: [{'text', 'out'}] — each 'out' is written in place.

    WHY: the model is loaded per invocation, and on this box that load is the
    bulk of a take. Measured, 2026-08-12, three of the default lines on Abel:

        3 separate invocations   15.2 + 12.1 + 11.3 = 38.6 s
        1 batched invocation                          19.1 s   (2.0x)

    and the three wavs came back BYTE-IDENTICAL to the singles, because the
    worker re-seeds torch/random/numpy with the same seed before every item — an
    item's audio does not depend on its position in the batch. That is the whole
    licence for this function: a pre-rendered take has to be exactly what
    pressing Render would have produced, or the cache is lying about what the
    voice sounds like. Re-verify it if the worker's seeding ever changes.

    Chatterbox only. IndexTTS-2's worker takes one line per call, so callers get
    False and fall back to synth() per item rather than a silent engine swap."""
    if p['engine'] != 'chatterbox' or not items:
        return 0
    if not (os.path.isfile(_CHATTERBOX_PY) and os.path.isfile(_CHATTERBOX_WORKER)):
        log('Chatterbox venv/worker missing')
        return 0
    dev = p['device']
    if dev == 'auto':
        dev = 'cuda' if _gpu_usable() else 'cpu'
    spec = os.path.join(os.path.dirname(items[0]['out']), '_batch.json')
    try:
        with open(spec, 'w', encoding='utf-8') as f:
            json.dump([{'text': it['text'], 'out': it['out']} for it in items], f)
    except OSError as e:
        log(f'could not write the batch spec: {e}')
        return 0
    cmd = [
        _CHATTERBOX_PY,
        _CHATTERBOX_WORKER,
        '--batch',
        spec,
        '--ref',
        ref_wav,
        '--seed',
        str(int(p['eng_seed'])),
        '--exaggeration',
        f'{float(p["cb_exaggeration"]):g}',
        '--cfg-weight',
        f'{float(p["cb_cfg_weight"]):g}',
        '--temperature',
        f'{float(p["cb_temperature"]):g}',
        '--device',
        dev,
    ]
    if _TTS_CORES and shutil.which('taskset'):
        cmd = ['taskset', '-c', _TTS_CORES] + cmd
    env = dict(os.environ)
    for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[k] = _TTS_THREADS
    # The per-line timeouts summed, plus one model load's worth of headroom.
    budget = sum(_synth_timeout(it['text']) for it in items) + 180
    t0 = time.time()
    try:
        subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=budget)
    except subprocess.TimeoutExpired:
        log(f'chatterbox batch TIMED OUT after {budget:.0f}s')
    # Judged on ARTIFACTS, not on the worker's exit: a CUDA banner written
    # straight to fd 1 can mangle the JSON line, and a batch that produced eight
    # of ten wavs should bank the eight. The two misses stay uncached and are
    # simply picked up on the next pass.
    made = sum(1 for it in items if os.path.isfile(it['out']) and os.path.getsize(it['out']) > 44)
    try:
        os.remove(spec)
    except OSError as _exc:
        _zyg_log.debug('batch spec %s left behind: %s', spec, _exc)
    log(f'chatterbox batch: {made}/{len(items)} in {time.time() - t0:.1f}s on {dev}')
    return made


# ─────────────────────────────────────────────────────────────── measurement
def measure(wav_path: str, age_class: str = '', identity_ref: str = '') -> dict:
    """F0 / VTL plus the age and identity verdicts. Never raises: an unavailable
    analysis venv degrades to {'available': False}, it does not fail a render."""
    out = {'available': False, 'f0_hz': None, 'vtl_cm': None, 'age': None, 'identity': None, 'band': None}
    try:
        from zyg_workflows import voice_qc
    except Exception as e:
        out['detail'] = f'voice_qc unavailable: {e!r}'
        return out
    if not voice_qc.enabled():
        out['detail'] = 'voice QC disabled or analysis venv missing'
        return out
    m = voice_qc.measure(wav_path)
    first = m[0] if m and 'error' not in m[0] else {}
    if not first:
        out['detail'] = 'nothing measurable in this render'
        return out
    out.update(
        {
            'available': True,
            'f0_hz': first.get('f0_median_hz'),
            'vtl_cm': first.get('vtl_cm'),
            'verdict': first.get('verdict', ''),
            'duration_s': first.get('duration_s'),
            'f1_hz': first.get('f1_hz'),
            'f2_hz': first.get('f2_hz'),
        }
    )
    if age_class:
        out['band'] = voice_qc.AGE_BANDS.get(age_class)
        out['age'] = voice_qc.gate_voice_age(wav_path, age_class)
    if identity_ref and os.path.isfile(identity_ref):
        out['identity'] = voice_qc.gate_voice_identity(wav_path, identity_ref)
    return out
