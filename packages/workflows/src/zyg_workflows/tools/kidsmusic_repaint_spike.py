# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kidsmusic_repaint_spike.py — can the live ComfyUI repaint ONE time window of an
ACE-Step 1.5 take and leave the rest of the audio alone?

Feasibility spike, not production. Creates files only under
output/kidsmusic/_repaint_spike/. Submits sequentially through _comfy_client
(which holds the cross-process submit lock), with ZYG_COMFY_KEEP_LOADED=1 so the
client never POSTs /free or restarts the shared server.

Why not SetLatentNoiseMask: it reshapes every MASK to 4-D (N,1,H,W)
(nodes.py:1523) and comfy.utils.reshape_mask treats a 3-D ACE latent
[B,64,T] as dims=1 and calls F.interpolate(4-D, size=(T,), mode='linear')
(comfy/utils.py:1276-1288) -> ValueError. KJNodes' LTXVAudioVideoMask builds
zeros_like(samples) (3-D) and fills [start:end] on the time axis at a hard-coded
25 latents/s (ltxv_nodes.py:215,343) — which happens to equal ACE-Step 1.5's
48000/1920 = 25 Hz.

Usage:
  python tools/kidsmusic_repaint_spike.py render   [--only NAME ...]
  python tools/kidsmusic_repaint_spike.py measure  [--only NAME ...]
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


os.environ['ZYG_COMFY_KEEP_LOADED'] = '1'  # never /free, never restart

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)

SONG_DIR = os.path.join(HERE, 'output', 'kidsmusic', '82b8bc806676')
OUT = os.path.join(HERE, 'output', 'kidsmusic', '_repaint_spike')
COMFY_OUT = str(paths.ZYG_COMFY_ROOT / 'output')
SR = 48000
WIN = (20.0, 25.0)
LAT_HZ_ASSUMED = 25.0  # verified from the saved latent in measure

LM_SEED = 1669026733
SEEDS = [1669026733, 7]
# 0.9 is kept as a finding: at steps=8, KSampler.set_steps uses int(8/0.9) = 8,
# i.e. the SAME sigma schedule as 1.0 (bit-identical output). 0.6/0.8 added.
DENOISES = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def _log(*a):
    _zyg_log.info(' '.join(str(x) for x in (time.strftime('%H:%M:%S'), *a)))


def _plan():
    return json.load(open(os.path.join(SONG_DIR, 'song.json')))


def _tags():
    m = json.load(open(os.path.join(SONG_DIR, 'manifest.json')))
    return m['produced']['ace_tags']


# ----------------------------------------------------------------- workflows
def wf_roundtrip(staged, ckpt, name):
    return {
        '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': ckpt}},
        '8': {'class_type': 'LoadAudio', 'inputs': {'audio': staged}},
        '9': {'class_type': 'VAEEncodeAudio', 'inputs': {'audio': ['8', 0], 'vae': ['1', 2]}},
        '6': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['9', 0], 'vae': ['1', 2]}},
        '7': {'class_type': 'SaveAudio', 'inputs': {'audio': ['6', 0], 'filename_prefix': f'repaintspike/{name}'}},
        '11': {'class_type': 'SaveLatent', 'inputs': {'samples': ['9', 0], 'filename_prefix': f'repaintspike/{name}'}},
    }


def wf_repaint(
    staged, ckpt, name, plan, *, denoise, seed, mask=True, win=WIN, lm_seed=LM_SEED, tags=None, gen_codes=True
):
    """VAEEncodeAudio -> LTXVAudioVideoMask (3-D noise_mask) -> KSampler -> decode."""
    seconds = max(10.0, min(180.0, float(plan['seconds'])))
    # LTXVAudioVideoMask end index = round(end*25)+1 (exclusive); subtract one
    # frame so the mask is exactly [win0, win1).
    end_t = round(win[1] - 1.0 / LAT_HZ_ASSUMED, 4)
    wf = {
        '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': ckpt}},
        '2': {
            'class_type': 'TextEncodeAceStepAudio1.5',
            'inputs': {
                'clip': ['1', 1],
                'tags': tags or _tags(),
                'lyrics': plan.get('lyrics_block') or '[inst]',
                'seed': int(lm_seed),
                'bpm': int(plan['bpm']),
                'duration': seconds,
                'timesignature': str(plan['ts']),
                'language': 'en',
                'keyscale': plan['key']['ace_keyscale'],
                'generate_audio_codes': bool(gen_codes),
                'cfg_scale': 2.0,
                'temperature': 0.85,
                'top_p': 0.9,
                'top_k': 0,
                'min_p': 0.0,
            },
        },
        '3': {'class_type': 'ConditioningZeroOut', 'inputs': {'conditioning': ['2', 0]}},
        '8': {'class_type': 'LoadAudio', 'inputs': {'audio': staged}},
        '9': {'class_type': 'VAEEncodeAudio', 'inputs': {'audio': ['8', 0], 'vae': ['1', 2]}},
        '5': {
            'class_type': 'KSampler',
            'inputs': {
                'model': ['1', 0],
                'seed': int(seed),
                'steps': 8,
                'cfg': 1.0,
                'sampler_name': 'euler',
                'scheduler': 'simple',
                'positive': ['2', 0],
                'negative': ['3', 0],
                'latent_image': ['10', 1] if mask else ['9', 0],
                'denoise': float(denoise),
            },
        },
        '6': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['5', 0], 'vae': ['1', 2]}},
        '7': {'class_type': 'SaveAudio', 'inputs': {'audio': ['6', 0], 'filename_prefix': f'repaintspike/{name}'}},
    }
    if mask:
        wf['10'] = {
            'class_type': 'LTXVAudioVideoMask',
            'inputs': {
                'audio_latent': ['9', 0],
                'video_fps': 25.0,
                'video_start_time': 0.0,
                'video_end_time': 0.0,
                'audio_start_time': float(win[0]),
                'audio_end_time': float(end_t),
                'max_length': 'partial',
                'existing_mask_mode': 'overwrite',
            },
        }
    return wf


def render_specs():
    specs = [{'name': 'rt', 'kind': 'roundtrip'}]
    for d in DENOISES:
        for s in SEEDS:
            specs.append(
                {'name': f'rp_d{int(d * 100):03d}_s{s}', 'kind': 'repaint', 'denoise': d, 'seed': s, 'mask': True}
            )
    # Control: the same sampler with NO mask, so "untouched" has a scale.
    specs.append(
        {'name': 'nomask_d070_s1669026733', 'kind': 'repaint', 'denoise': 0.7, 'seed': 1669026733, 'mask': False}
    )
    return specs


EXTRA_SPECS = {}  # filled by phase-2 CLI flags


def cmd_render(only=None):
    from zyg_workflows import kids_music_service as kms
    from zyg_workflows import _comfy_client as cc

    os.makedirs(OUT, exist_ok=True)
    plan = _plan()
    ckpt = kms.ACE_CHECKPOINT
    specs = render_specs() + list(EXTRA_SPECS.values())
    if only:
        specs = [s for s in specs if s['name'] in only]
    todo = [s for s in specs if not os.path.isfile(os.path.join(OUT, s['name'] + '.flac'))]
    if not todo:
        _log('nothing to render')
        return
    staged = kms._stage_comfy_audio(os.path.join(SONG_DIR, 'song.mp3'), log_fn=_log, stem='repaintspike')
    if not staged:
        raise SystemExit('staging failed')
    _log('staged', staged)
    log_path = os.path.join(OUT, 'renders.jsonl')
    try:
        for s in todo:
            if s['kind'] == 'roundtrip':
                wf = wf_roundtrip(staged, ckpt, s['name'])
            else:
                kw = {k: s[k] for k in ('denoise', 'seed', 'mask', 'win', 'lm_seed', 'tags', 'gen_codes') if k in s}
                wf = wf_repaint(staged, ckpt, s['name'], plan, **kw)
            wf_path = os.path.join(OUT, f'wf_{s["name"]}.json')
            json.dump(wf, open(wf_path, 'w'), indent=1)
            t0 = time.time()
            _log('submit', s['name'])
            try:
                outs = cc.submit(wf, timeout_s=1800)
            except Exception as e:  # noqa: BLE001
                _log('FAILED', s['name'], str(e)[:600])
                with open(log_path, 'a') as f:
                    f.write(
                        json.dumps({**s, 'ok': False, 'error': str(e)[:1500], 'wall_s': round(time.time() - t0, 1)})
                        + '\n'
                    )
                continue
            wall = time.time() - t0
            aud = [p for p in outs if p.endswith('.flac') and os.path.isfile(p)]
            if not aud:
                _log('no audio output', s['name'], outs)
                continue
            dst = os.path.join(OUT, s['name'] + '.flac')
            shutil.move(aud[0], dst)
            if s['kind'] == 'roundtrip':
                lats = sorted(glob.glob(os.path.join(COMFY_OUT, 'repaintspike', f'{s["name"]}_*.latent')))
                if lats:
                    shutil.move(lats[-1], os.path.join(OUT, s['name'] + '.latent'))
            with open(log_path, 'a') as f:
                f.write(
                    json.dumps(
                        {
                            **s,
                            'ok': True,
                            'wall_s': round(wall, 1),
                            'workflow': wf_path,
                            'timing': dict(cc.last_submit_timing),
                        }
                    )
                    + '\n'
                )
            _log('done', s['name'], f'{wall:.0f}s', dict(cc.last_submit_timing))
    finally:
        try:
            os.remove(os.path.join(str(paths.ZYG_COMFY_ROOT / 'input'), staged))
        except OSError as _exc:
            _zyg_log.debug('staged comfy input cleanup skipped: %s', _exc)


# ----------------------------------------------------------------- measuring
def _load(path):
    import soundfile as sf
    import numpy as np

    if path.endswith('.mp3'):
        raw = subprocess.run(
            [exe('ffmpeg'), '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '2', '-ar', str(SR), '-'],
            capture_output=True,
            check=True,
        ).stdout
        return np.frombuffer(raw, dtype='<f4').reshape(-1, 2).astype('float64')
    y, sr = sf.read(path, always_2d=True)
    if sr != SR:
        raise ValueError((path, sr))
    return y.astype('float64')


def _db(x):
    import numpy as np

    return 20.0 * np.log10(max(float(x), 1e-12))


def _rms(a):
    import numpy as np

    return float(np.sqrt(np.mean(np.square(a)))) if a.size else 0.0


def _seg(y, t0, t1):
    return y[int(round(t0 * SR)) : int(round(t1 * SR))]


def _melspec(y):
    import librosa
    import numpy as np

    mono = y.mean(1).astype('float32')
    S = librosa.feature.melspectrogram(y=mono, sr=SR, n_fft=2048, hop_length=480, n_mels=128)
    return 10.0 * np.log10(np.maximum(S, 1e-10))


def _flux(Sdb):
    import numpy as np

    d = np.diff(Sdb, axis=1)
    f = np.maximum(d, 0).mean(0)
    return np.concatenate([[0.0], f])


def compare(y, ref, Sy=None, Sref=None):
    """Region metrics of y against ref (both 48k stereo, same length)."""
    import numpy as np

    n = min(len(y), len(ref))
    y, ref = y[:n], ref[:n]
    dur = n / SR
    Sy = _melspec(y) if Sy is None else Sy
    Sr = _melspec(ref) if Sref is None else Sref
    m = min(Sy.shape[1], Sr.shape[1])
    Sy, Sr = Sy[:, :m], Sr[:, :m]
    floor = Sr.max() - 80.0
    fps = SR / 480.0
    regions = {'pre_0_19.5': (0.0, 19.5), 'win_20_25': WIN, 'post_25.5_end': (25.5, dur)}
    out = {'regions': {}}
    for k, (a, b) in regions.items():
        ys, rs = _seg(y, a, b), _seg(ref, a, b)
        g = float((ys * rs).sum() / max((rs * rs).sum(), 1e-12))
        i0, i1 = int(a * fps), int(b * fps)
        lmd = float(np.abs(np.maximum(Sy[:, i0:i1], floor) - np.maximum(Sr[:, i0:i1], floor)).mean())
        out['regions'][k] = {
            'rel_diff_db': round(_db(_rms(ys - rs) / max(_rms(rs), 1e-12)), 2),
            'gain_matched_rel_diff_db': round(_db(_rms(ys - g * rs) / max(_rms(rs), 1e-12)), 2),
            'gain': round(g, 5),
            'logmel_dist_db': round(lmd, 3),
        }
    # Diff profile in 0.25 s bins around the window: how far does change leak?
    prof = []
    t = 17.0
    while t < 28.0 - 1e-9:
        ys, rs = _seg(y, t, t + 0.25), _seg(ref, t, t + 0.25)
        prof.append((round(t, 2), round(_db(_rms(ys - rs) / max(_rms(rs), 1e-12)), 1)))
        t += 0.25
    out['profile_17_28'] = prof
    # Boundary flux: render peak vs roundtrip peak at the same timestamps.
    fy, fr = _flux(Sy), _flux(Sr)
    bnd = {}
    for b in WIN:
        i0, i1 = int((b - 0.12) * fps), int((b + 0.12) * fps) + 1
        py, pr = float(fy[i0:i1].max()), float(fr[i0:i1].max())
        bnd[f'{b:g}s'] = {
            'flux_peak': round(py, 3),
            'flux_peak_ref': round(pr, 3),
            'ratio': round(py / max(pr, 1e-9), 2),
            'pctile_in_track': round(float((fy < py).mean() * 100), 2),
            'ref_pctile_in_track': round(float((fr < pr).mean() * 100), 2),
        }
    out['boundaries'] = bnd
    return out


def align_lag(a, b, max_lag=4800):
    """Lag (samples) such that a[i+lag] ~ b[i]."""
    import numpy as np

    x = a[int(5 * SR) : int(15 * SR)].mean(1)
    y = b[int(5 * SR) : int(15 * SR)].mean(1)
    best, bl = -1e18, 0
    for lag in range(-max_lag, max_lag + 1, 1):
        if lag >= 0:
            v = float(np.dot(x[lag:], y[: len(y) - lag]))
        else:
            v = float(np.dot(x[:lag], y[-lag:]))
        if v > best:
            best, bl = v, lag
    return bl


def window_vocal(path, work):
    """demucs (CPU, cores 0-19) on 14-31 s, then RMVPE on the 20-25 s stem."""
    import soundfile as sf
    from zyg_workflows import kids_music_service as kms
    from zyg_workflows import sung_pitch

    os.makedirs(work, exist_ok=True)
    y = _load(path)
    crop = os.path.join(work, 'crop_14_31.wav')
    sf.write(crop, _seg(y, 14.0, 31.0), SR, subtype='FLOAT')
    stems = os.path.join(work, 'stems')
    if not os.path.isfile(os.path.join(stems, 'vocals.wav')):
        cmd = ['taskset', '-c', '0-19', kms._AGENTS_PY, kms._DEMUCS_TOOL, crop, stems, '--device', 'cpu']
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        js = [l for l in (r.stdout or '').splitlines() if l.startswith('{')]
        sep = json.loads(js[-1]) if js else {'ok': False, 'error': r.stderr[-300:]}
        if not sep.get('ok'):
            return {'ok': False, 'error': sep.get('error')}
    v, vsr = sf.read(os.path.join(stems, 'vocals.wav'), always_2d=True)
    rest, _ = sf.read(os.path.join(stems, 'no_vocals.wav'), always_2d=True)
    a, b = int(6.0 * vsr), int(11.0 * vsr)  # 20-25 s of the song
    vw = os.path.join(work, 'vocals_20_25.wav')
    sf.write(vw, v[a:b], vsr, subtype='PCM_16')
    ratio = _db(_rms(v[a:b]) / max(_rms(rest[a:b]), 1e-12))
    m = sung_pitch.measure_stem(vw)
    return {
        'ok': bool(m.get('ok')),
        'f0_median_hz': m.get('f0_median_hz'),
        'f0_p10_hz': m.get('f0_p10_hz'),
        'f0_p90_hz': m.get('f0_p90_hz'),
        'voiced_frac': m.get('voiced_frac'),
        'agreement_cents': m.get('agreement_cents'),
        'stem_ratio_db': round(ratio, 2),
        'error': m.get('error', ''),
    }


def cmd_measure(only=None):
    import numpy as np
    from zyg_workflows import kids_music_service as kms

    plan = _plan()
    res_path = os.path.join(OUT, 'measure.json')
    res = json.load(open(res_path)) if os.path.isfile(res_path) else {}
    rt_path = os.path.join(OUT, 'rt.flac')
    rt = _load(rt_path)
    S_rt = _melspec(rt)

    if 'rt' not in res or (only and 'rt' in only):
        r = {'name': 'rt'}
        lat = os.path.join(OUT, 'rt.latent')
        if os.path.isfile(lat):
            from safetensors.torch import load_file

            t = load_file(lat)['latent_tensor']
            r['latent_shape'] = list(t.shape)
            r['audio_s'] = round(len(rt) / SR, 4)
            r['latent_hz'] = round(t.shape[-1] / (len(rt) / SR), 4)
        orig = _load(os.path.join(SONG_DIR, 'song.mp3'))
        lag = align_lag(orig, rt)
        r['orig_vs_rt_lag_samples'] = lag
        o = orig[lag:] if lag >= 0 else np.concatenate([np.zeros((-lag, 2)), orig])
        r['vae_loss_vs_original'] = compare(rt, o, Sy=S_rt)['regions']
        r['gate'] = {
            k: v
            for k, v in kms.gate_audio(rt_path, plan, leg='produced', want_clap=False)['checks'].items()
            if k in ('detected_bpm', 'bpm_relation', 'detected_key', 'key_match', 'key_correlation')
        }
        orig_path = os.path.join(SONG_DIR, 'song.mp3')
        r['gate_original'] = {
            k: v
            for k, v in kms.gate_audio(orig_path, plan, leg='produced', want_clap=False)['checks'].items()
            if k in ('detected_bpm', 'bpm_relation', 'detected_key', 'key_match', 'key_correlation')
        }
        r['vocal_rt'] = window_vocal(rt_path, os.path.join(OUT, 'work', 'rt'))
        r['vocal_original'] = window_vocal(orig_path, os.path.join(OUT, 'work', 'original'))
        res['rt'] = r
        json.dump(res, open(res_path, 'w'), indent=1)
        _log('rt', json.dumps(r)[:1500])

    names = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(OUT, '*.flac')))
    for name in names:
        if name == 'rt' or (only and name not in only) or (name in res and not only):
            continue
        p = os.path.join(OUT, name + '.flac')
        y = _load(p)
        r = {'name': name}
        r.update(compare(y, rt, Sref=S_rt))
        g = kms.gate_audio(p, plan, leg='produced', want_clap=False)['checks']
        r['gate'] = {
            k: v
            for k, v in g.items()
            if k in ('detected_bpm', 'bpm_relation', 'detected_key', 'key_match', 'key_correlation')
        }
        r['vocal'] = window_vocal(p, os.path.join(OUT, 'work', name))
        res[name] = r
        json.dump(res, open(res_path, 'w'), indent=1)
        _log(name, json.dumps({k: r[k] for k in ('regions', 'boundaries', 'gate', 'vocal')}))


if __name__ == '__main__':
    args = sys.argv[1:]
    only = None
    if '--only' in args:
        only = set(args[args.index('--only') + 1 :])
        args = args[: args.index('--only')]
    if not args or args[0] not in ('render', 'measure'):
        raise SystemExit(__doc__)
    {'render': cmd_render, 'measure': cmd_measure}[args[0]](only)
