# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Master, stems, remix, remux and the voice-conversion leg.

Moved verbatim out of the old single-file kids_music_service.py (lines 2959-3310).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from zyg_workflows import provenance_seal as _seal
from zyg_workflows.bin import exe

from zyg_workflows.kids_music_service.base import (
    _log_noop,
    _zyg_log,
)
from zyg_workflows.kids_music_service.measure import (
    gate_audio,
    trim_tail,
)
from zyg_workflows.kids_music_service.mixdown import (
    _mp3,
    prelevel,
)

# ── Master, stems and remix ──────────────────────────────────────────────────


def master_audio(src, out_dir, plan, *, log_fn=None, dst_name='master.mp3'):
    """The delivery master chain, in one place: trim the dead tail, pre-level to
    -14 LUFS / -1.5 dBTP, loudnorm to -14 / -1 dBTP, 256k mp3, gate it. run()
    and remix_job() both ship through this, so a remix is mastered exactly like
    the song it replaces. Returns (master_path|None, gate|{}, trimmed_s)."""
    log_fn = log_fn or _log_noop
    mw = os.path.join(out_dir, '_master.wav')
    norm, master, gate = {}, None, {}
    # Trim the dead tail off what feeds the master; the untrimmed take stays
    # on disk. The duration gate could never see this, because it compares
    # the container against the number ace_render used to SET the container.
    fed, trimmed_s = trim_tail(src, os.path.join(out_dir, '_trim.wav'), log_fn=log_fn)
    # Target the master's own -14.0 with a -1.5 dBTP ceiling, so the
    # loudnorm that follows has ~0 dB of correction left and can make it
    # linearly. Pre-levelling to -14.8 left it +2.1 dB to find against a
    # -1 dBTP target, which is precisely the condition that forces dynamic.
    pre = prelevel(fed, os.path.join(out_dir, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=log_fn)
    try:
        from zyg_workflows import audio_mix

        if audio_mix.master(pre, mw, i=-14.0, tp=-1.0, log_fn=log_fn, result=norm):
            master = _mp3(mw, os.path.join(out_dir, dst_name), log_fn=log_fn, br='256k')
    except Exception as e:  # noqa: BLE001
        log_fn(f'master: levelling failed ({type(e).__name__}: {e})'[:180])
    if master:
        gate = gate_audio(master, plan, leg='master', want_clap=False, log_fn=log_fn)
        gate['checks']['loudnorm'] = {
            'normalization_type': norm.get('normalization_type'),
            'lra_eff': norm.get('lra_eff'),
        }
        if norm.get('normalization_type') not in (None, 'linear'):
            gate['warnings'].append(
                f"loudnorm ran {norm.get('normalization_type')}, not linear — the programme's dynamics were re-shaped"
            )
    for tmp in ('_master.wav', '_pre.wav', '_trim.wav'):
        try:
            os.remove(os.path.join(out_dir, tmp))
        except OSError as _exc:
            _zyg_log.debug('mastering temp %s removal skipped: %s', tmp, _exc)
    if master:
        # The delivery master is what leaves the studio; it carries the credential.
        _seal.seal(master, pipeline='kids_music', log_fn=log_fn)
    return master, gate, trimmed_s


STEM_FILES = {
    'vocals': 'stems/vocals.flac',
    'backing': 'stems/backing.flac',
    'vocals_unconverted': 'stems/vocals_unconverted.flac',
}


def save_stems(vocals_wav, rest_wav, out_dir):
    """The shipped take's two stems, kept beside the song as FLAC."""
    import soundfile as sf

    os.makedirs(os.path.join(out_dir, 'stems'), exist_ok=True)
    out = {}
    for key, src in (('vocals', vocals_wav), ('backing', rest_wav)):
        if src and os.path.isfile(src):
            y, sr = sf.read(src, dtype='float32', always_2d=True)
            dst = os.path.join(out_dir, STEM_FILES[key])
            sf.write(dst, y, sr, format='FLAC', subtype='PCM_16')
            out[key] = STEM_FILES[key]
    return out


def remix_stems(vocals, backing, out_wav, *, vocal_db=0.0, backing_db=0.0):
    """vocals x g_v + backing x g_b, written as float WAV (no clipping here; the
    master chain levels it). demucs' two stems sum back to the take within
    -32 dB (bumblebee 82b8bc806676, lag 0), so small gains are clean."""
    import numpy as np
    import soundfile as sf

    v, sr = sf.read(vocals, dtype='float32', always_2d=True)
    b, sr_b = sf.read(backing, dtype='float32', always_2d=True)
    if sr != sr_b:
        raise ValueError(f'stem sample rates differ ({sr} vs {sr_b})')
    n = min(len(v), len(b))
    y = v[:n] * (10.0 ** (float(vocal_db) / 20.0)) + b[:n] * (10.0 ** (float(backing_db) / 20.0))
    sf.write(out_wav, y, sr, subtype='FLOAT')
    return {'path': out_wav, 'peak': round(float(np.abs(y).max()), 4)}


def remux_video(job_dir, audio_path, log_fn=None):
    """Put a new master under an existing video without re-encoding the picture
    (the same mux kids_video_service uses)."""
    log_fn = log_fn or _log_noop
    vid = os.path.join(job_dir, 'video.mp4')
    if not os.path.isfile(vid):
        return False
    tmp = os.path.join(job_dir, '_remux.mp4')
    r = subprocess.run(
        [
            exe('ffmpeg'),
            '-y',
            '-v',
            'error',
            '-i',
            vid,
            '-i',
            audio_path,
            '-c:v',
            'copy',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '-map',
            '0:v:0',
            '-map',
            '1:a:0',
            '-shortest',
            '-movflags',
            '+faststart',
            tmp,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not os.path.isfile(tmp):
        log_fn(f'remix: video re-mux failed — {(r.stderr or "")[-200:]}')
        return False
    os.replace(tmp, vid)
    # The re-mux rewrites the container, so whatever credential the old video
    # carried is gone with it; the new one names the master it was muxed from.
    _seal.seal_derived(vid, audio_path, pipeline='kids_music', log_fn=log_fn)
    return True


def convert_voice(voice, plan, singer, take, out_dir, *, log_fn=None):
    """Convert the shipped take's vocal to the singer's trained voice.

    Records everything in voice['conversion'] and returns the converted mix to
    master (a WAV at the song's recorded vocal balance), or None when the take
    ships unconverted — conversion off, no reviewed stem, conversion failed, or
    voice_conversion.ship_check refused it. On a shipped conversion both vocals
    are kept: stems/vocals.flac (converted) and stems/vocals_unconverted.flac."""
    from zyg_workflows import voice_conversion as VC

    log_fn = log_fn or _log_noop
    t0 = time.time()
    rec = {
        'shipped': False,
        'reasons': [],
        'model': singer.get('vc_model'),
        'weights': singer.get('vc_weights') or '',
        'provenance': VC.PROVENANCE,
    }
    voice['conversion'] = rec
    if not VC.enabled():
        rec['reasons'] = ['turned off (ZYG_KIDSMUSIC_VC=0)']
        return None
    stems = voice.get('_stems') or {}
    if not (
        voice.get('reviewed') and os.path.isfile(stems.get('vocals') or '') and os.path.isfile(stems.get('rest') or '')
    ):
        rec['reasons'] = ['no reviewed vocal stem to convert']
        log_fn('voice: conversion skipped — no reviewed vocal stem')
        return None
    work = os.path.join(out_dir, '_vc')
    c = VC.convert_stem(
        stems['vocals'],
        work,
        model=rec['model'],
        weights=rec['weights'],
        index_rate=float(singer.get('vc_index_rate', 0.5)),
        protect=float(singer.get('vc_protect', 0.33)),
        log_fn=log_fn,
    )
    rec.update(
        {
            k: c.get(k)
            for k in (
                'engine',
                'weights',
                'index_rate',
                'protect',
                'f0_method',
                'lag_samples',
                'envelope_corr',
                'gain_db',
                'convert_s',
            )
            if c.get(k) is not None
        }
    )
    if not c.get('ok'):
        rec['reasons'] = [c.get('error') or 'conversion failed']
        rec['seconds'] = round(time.time() - t0, 1)
        log_fn(f'voice: conversion failed ({rec["reasons"][0]}) — shipping the unconverted take')
        return None
    from zyg_workflows import vocal_analysis as VA

    drift = VC.melody_drift(stems['vocals'], c['path'])
    # The bare decode has to hear what the conversion would actually ship, so the
    # converted mix is built BEFORE the check rather than after it. `take` is
    # still the unconverted master and would grade the wrong audio.
    vd = float((voice.get('mix') or {}).get('vocal_db') or 0.0)
    try:
        cand = remix_stems(c['path'], stems['rest'], os.path.join(work, '_remix_vc_check.wav'), vocal_db=vd)['path']
    except Exception as e:  # noqa: BLE001 — fall back to the take
        log_fn(f'voice: could not build the converted mix to check ({type(e).__name__})')
        cand = None
    after = VA.review(
        take,
        plan,
        singer,
        os.path.join(work, 'review'),
        sep={'ok': True, 'vocals': c['path'], 'rest': stems['rest']},
        bare_take=cand,
        log_fn=log_fn,
    )
    ship, reasons = VC.ship_check(
        {'lyrics': voice.get('lyrics'), 'lyrics_bare': voice.get('lyrics_bare')}, after, drift
    )
    rec.update(
        {
            'melody': drift,
            'shipped': ship,
            'reasons': reasons,
            'review_after': (
                {k: after.get(k) for k in ('lyrics', 'lyrics_bare', 'register', 'key', 'severity')}
                | {'problems': [p['detail'] for p in after.get('problems') or []]}
                if after.get('ok')
                else {'error': after.get('error')}
            ),
            'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
    )
    if not ship:
        rec['seconds'] = round(time.time() - t0, 1)
        log_fn(f'voice: conversion NOT shipped — {"; ".join(reasons)} (kept the unconverted take)')
        return None
    import soundfile as sf

    os.makedirs(os.path.join(out_dir, 'stems'), exist_ok=True)
    for src, rel in ((stems['vocals'], STEM_FILES['vocals_unconverted']), (c['path'], STEM_FILES['vocals'])):
        y, sr = sf.read(src, dtype='float32', always_2d=True)
        sf.write(os.path.join(out_dir, rel), y, sr, format='FLAC', subtype='PCM_16')
    voice.setdefault('stems', {}).update(
        {'vocals': STEM_FILES['vocals'], 'vocals_unconverted': STEM_FILES['vocals_unconverted']}
    )
    if os.path.isfile(os.path.join(out_dir, STEM_FILES['backing'])):
        voice['stems']['backing'] = STEM_FILES['backing']
    feed = remix_stems(c['path'], stems['rest'], os.path.join(out_dir, '_remix_vc.wav'), vocal_db=vd)['path']
    rec['unconverted'] = {'master': 'master_unconverted.mp3', 'vocals': STEM_FILES['vocals_unconverted']}
    rec['seconds'] = round(time.time() - t0, 1)
    ly = after.get('lyrics') or {}
    lyb = after.get('lyrics_bare') or {}
    clar = (
        f', {lyb.get("clear")}/{lyb.get("lines")} clear (before {(voice.get("lyrics_bare") or {}).get("clear")})'
        if lyb.get('measured')
        else ''
    )
    log_fn(
        f'voice: converted voice ships — melody {drift["median_abs_cents"]} c, '
        f'{ly.get("sung")}/{ly.get("lines")} lines sung (before '
        f'{(voice.get("lyrics") or {}).get("sung")}){clar}, {rec["seconds"]:.0f}s'
    )
    return feed


def _update_voice_report(out_dir, voice):
    """Fold voice['conversion'] (and the stems it changed) into voice_report.json,
    which run() wrote before the master existed."""
    p = os.path.join(out_dir, 'voice_report.json')
    try:
        rep = json.load(open(p))
    except (OSError, ValueError):
        return
    rep['conversion'] = voice.get('conversion')
    rep['stems'] = voice.get('stems') or rep.get('stems')
    with open(p + '.tmp', 'w') as fh:
        json.dump(rep, fh, indent=1)
    os.replace(p + '.tmp', p)


def remix_job(job_dir, *, vocal_db=0.0, backing_db=0.0, log_fn=None):
    """Re-balance a finished song from its stems: new master.mp3, the video's
    audio replaced, manifest['voice']['mix'] updated. (0, 0) re-masters the
    ORIGINAL take rather than the stem sum, so 'reset' is exact."""
    log_fn = log_fn or _log_noop
    man_path = os.path.join(job_dir, 'manifest.json')
    man = json.load(open(man_path))
    plan = json.load(open(os.path.join(job_dir, 'song.json')))
    vd, bd = round(float(vocal_db), 1), round(float(backing_db), 1)
    if not (-12.0 <= vd <= 12.0 and -12.0 <= bd <= 12.0):
        return {'ok': False, 'error': 'gains must be within +-12 dB'}
    stems = {k: os.path.join(job_dir, p) for k, p in STEM_FILES.items()}
    # A song whose voice was converted ships stems/vocals.flac = the CONVERTED
    # vocal, and its take (song.mp3) is still the unconverted one — so a reset
    # must re-sum the converted stems at 0 dB, never re-master the take.
    converted = bool(((man.get('voice') or {}).get('conversion') or {}).get('shipped'))
    need = ('vocals', 'backing') + (('vocals_unconverted',) if converted else ())
    if (vd or bd or converted) and not all(os.path.isfile(stems[k]) for k in need):
        return {'ok': False, 'error': 'this song has no stems (made before 2026-09-15)'}
    if (man.get('delivery') or {}).get('picked_leg') != 'produced':
        return {'ok': False, 'error': 'the shipped song is the score render — no voice to balance'}
    if vd or bd or converted:
        src = remix_stems(
            stems['vocals'], stems['backing'], os.path.join(job_dir, '_remix.wav'), vocal_db=vd, backing_db=bd
        )['path']
    else:
        src = os.path.join(job_dir, (man.get('voice') or {}).get('take_file') or 'song.mp3')
    master, gate, _trim = master_audio(src, job_dir, plan, log_fn=log_fn, dst_name='_remix_master.mp3')
    try:
        os.remove(os.path.join(job_dir, '_remix.wav'))
    except OSError as _exc:
        _zyg_log.debug('remix temp _remix.wav removal skipped: %s', _exc)
    if not master:
        return {'ok': False, 'error': 'mastering failed'}
    os.replace(master, os.path.join(job_dir, 'master.mp3'))
    if converted:
        # Keep the A/B fair: the unconverted master gets the same balance.
        if vd or bd:
            usrc = remix_stems(
                stems['vocals_unconverted'],
                stems['backing'],
                os.path.join(job_dir, '_remix.wav'),
                vocal_db=vd,
                backing_db=bd,
            )['path']
        else:
            usrc = os.path.join(job_dir, (man.get('voice') or {}).get('take_file') or 'song.mp3')
        um, _ug, _t = master_audio(usrc, job_dir, plan, log_fn=log_fn, dst_name='_remix_unconv.mp3')
        try:
            os.remove(os.path.join(job_dir, '_remix.wav'))
        except OSError as _exc:
            _zyg_log.debug('remix temp _remix.wav removal skipped: %s', _exc)
        if um:
            os.replace(um, os.path.join(job_dir, 'master_unconverted.mp3'))
    remuxed = remux_video(job_dir, os.path.join(job_dir, 'master.mp3'), log_fn=log_fn)
    voice = man.setdefault('voice', {})
    voice['mix'] = {
        'vocal_db': vd,
        'backing_db': bd,
        'by': 'operator',
        'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'video_remuxed': remuxed,
    }
    man.setdefault('gates', {})['master'] = gate
    tmp = man_path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(man, fh, indent=1)
    os.replace(tmp, man_path)
    return {'ok': True, 'mix': voice['mix'], 'lufs': (gate.get('checks') or {}).get('lufs')}
