# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""MP3 encoding, mix balance, percussion, levelling, soundfont provenance and job state.

Moved verbatim out of the old single-file kids_music_service.py (lines 2640-2958).
"""

from __future__ import annotations

import json
import os

from zyg_workflows.kids_music_service.base import (
    ALLOWED_SOUNDFONTS,
    HERE,
    MIX_MARGIN_MIN_DB,
    SOUNDFONT,
    _ff,
    _log_noop,
    _zyg_log,
)
from zyg_workflows.kids_music_service.soundfont import render_soundfont

# ── The run ──────────────────────────────────────────────────────────────────


def _mp3(src, dst, log_fn=None, br='192k', highpass_hz=0):
    """Encode to mp3, optionally through a high-pass.

    `highpass_hz=60` is used on the score render. The lowest bass fundamental the
    composer can write is C2 at 65 Hz, so a 60 Hz high-pass removes only rumble —
    but 73% of the score render's energy sat below 250 Hz and the sub region is
    where a GM bass patch spends its headroom without contributing a pitch
    anybody hears.
    """
    args = ['-i', src]
    if highpass_hz:
        args += ['-af', f'highpass=f={int(highpass_hz)}:poles=2']
    args += ['-c:a', 'libmp3lame', '-b:a', br, '-ar', '44100', dst]
    return dst if _ff(args, log_fn=log_fn) else None


def mix_balance(midi_path, plan, *, engine='soundfont', log_fn=None):
    """Melody-minus-bass RMS, in dB, by rendering the two roles separately.

    The acceptance test for the per-program gain table. A children's song whose
    tune is under its bass is not a children's song, and nothing in the pipeline
    was measuring it: the arrangement used five fixed velocities corpus-wide.

    `engine` must name the render that ACTUALLY SHIPPED. The two engines balance
    differently — the SoundFont path is velocity-shaped by GM_LEAD_GAIN, the
    sampled path by melody_sampler's fixed role gains — so measuring the
    SoundFont stems and then shipping the sampler render would be a margin
    reported for a mix nobody hears. The >= MIX_MARGIN_MIN_DB rule is the same
    for both.
    """
    import tempfile
    import numpy as np
    import soundfile as sf

    log_fn = log_fn or _log_noop
    out = {'ok': None, 'engine': engine, 'melody_db': None, 'bass_db': None, 'margin_db': None}
    if engine == 'sampler':
        try:
            from zyg_workflows import melody_sampler as MS

            voices = plan.get('voices') or {}
            levels = {}
            for want, role in (('Melody', 'lead'), ('Bass', 'bass')):
                a, _stats = MS.render_role(plan, role, voices[role])
                r = float(np.sqrt(np.mean(np.square(np.asarray(a, dtype='float64'))))) if a.size else 0.0
                levels[want] = 20.0 * np.log10(max(r, 1e-12))
            out.update(
                {
                    'melody_db': round(float(levels['Melody']), 2),
                    'bass_db': round(float(levels['Bass']), 2),
                    'margin_db': round(float(levels['Melody'] - levels['Bass']), 2),
                }
            )
            out['ok'] = bool(out['margin_db'] >= MIX_MARGIN_MIN_DB)
        except Exception as e:  # noqa: BLE001 — a measurement
            out['error'] = f'{type(e).__name__}: {e}'[:180]
            log_fn(f'mix: unmeasured ({type(e).__name__})')
        return out
    try:
        import mido

        src = mido.MidiFile(midi_path)
        with tempfile.TemporaryDirectory() as td:
            levels = {}
            for want in ('Melody', 'Bass'):
                one = mido.MidiFile(ticks_per_beat=src.ticks_per_beat)
                for tr in src.tracks:
                    name = next((m.name for m in tr if getattr(m, 'type', '') == 'track_name'), '')
                    if name in ('', want) or tr is src.tracks[0]:
                        one.tracks.append(tr)
                mp = os.path.join(td, f'{want}.mid')
                wp = os.path.join(td, f'{want}.wav')
                one.save(mp)
                if not render_soundfont(mp, wp, log_fn=None):
                    return out
                a, _sr = sf.read(wp, dtype='float64', always_2d=True)
                r = float(np.sqrt(np.mean(np.square(a)))) if a.size else 0.0
                levels[want] = 20.0 * np.log10(max(r, 1e-12))
            # PLAIN PYTHON TYPES ONLY. numpy scalars leak two ways: json.dump
            # refuses them outright, and `np.True_ is True` is False — which is
            # how an `is True` test on this dict silently rejected a render that
            # had in fact passed.
            out.update(
                {
                    'melody_db': round(float(levels['Melody']), 2),
                    'bass_db': round(float(levels['Bass']), 2),
                    'margin_db': round(float(levels['Melody'] - levels['Bass']), 2),
                }
            )
            out['ok'] = bool(out['margin_db'] >= MIX_MARGIN_MIN_DB)
    except Exception as e:  # noqa: BLE001 — a measurement
        out['error'] = f'{type(e).__name__}: {e}'[:180]
        log_fn(f'mix: unmeasured ({type(e).__name__})')
    return out


def percussion_wav(midi_path, out_wav, log_fn=None):
    """Render ONLY the Percussion track of a plan's MIDI, through the SoundFont.

    The sampled library has no drum kit — the nursery kit (side stick, hand clap,
    shaker) lives in the SoundFont's GM bank 128 — so the sampled render borrows
    it, using the same strip-to-one-track trick mix_balance uses. Returns the wav
    path, or None when there is nothing to render.
    """
    log_fn = log_fn or _log_noop
    try:
        import mido

        src = mido.MidiFile(midi_path)
        one = mido.MidiFile(ticks_per_beat=src.ticks_per_beat)
        found = False
        for tr in src.tracks:
            name = next((m.name for m in tr if getattr(m, 'type', '') == 'track_name'), '')
            if tr is src.tracks[0]:
                one.tracks.append(tr)
            elif name == 'Percussion':
                one.tracks.append(tr)
                found = True
        if not found:
            return None
        mp = os.path.splitext(out_wav)[0] + '.mid'
        one.save(mp)
        got = render_soundfont(mp, out_wav, log_fn=None)
        try:
            os.remove(mp)
        except OSError as _exc:
            _zyg_log.debug('percussion midi %s removal skipped: %s', mp, _exc)
        return got
    except Exception as e:  # noqa: BLE001 — the kit is optional
        log_fn(f'sampler: percussion bed unavailable ({type(e).__name__})')
        return None


def prelevel(src, dst, target_lufs=-14.8, log_fn=None, tp_db=-1.5):
    """Bring the audio to `target_lufs` BEFORE the master, so loudnorm stays linear.

    A soundfont render of a sparse nursery arrangement lands around -24 LUFS with
    plenty of headroom-free transients. Handing that straight to loudnorm asks it
    for +10 dB, which would put true peak above the ceiling, so ffmpeg silently
    drops to DYNAMIC normalisation and re-shapes the programme's dynamics --
    measured on the first run of this workflow, and the same failure already on
    record for the scene-audio chain.

    The correction runs in BOTH directions. A source hotter than the target is
    just as capable of forcing the dynamic fallback as a quiet one, and the
    original positive-only clamp let every such source through untouched.

    ITERATED, not single-shot. The first version applied the measured deficit
    once through a limiter and stopped — but limiting REMOVES energy, so it
    always landed short (measured: asked -14.8, landed -16.11), and the leftover
    is exactly what tips the master into dynamic AGC. audio_mix.level_to already
    solves this properly (gain-then-limit, up to 8 passes, verifying it landed),
    so it is used rather than reimplemented; the single-shot path below is the
    fallback for when audio_mix is unavailable.
    """
    log_fn = log_fn or _log_noop
    try:
        from zyg_workflows import audio_mix

        # level_to works in place, so stage a wav copy first.
        if not _ff(['-i', src, '-ar', '48000', '-c:a', 'pcm_s16le', dst], log_fn=log_fn):
            raise RuntimeError('stage copy failed')
        res = {}
        ok = audio_mix.level_to(dst, target_lufs=target_lufs, tp_db=tp_db, log_fn=None, result=res)
        got = res.get('final_lufs')
        if res.get('silent'):
            log_fn('prelevel: source is silent — nothing to level')
            return src
        if ok or got is not None:
            log_fn(
                f'prelevel: {res.get("input_lufs")} -> {got} LUFS '
                f'(target {target_lufs:g}, '
                f'{"converged" if ok else "did not converge"})'
            )
            return dst if os.path.isfile(dst) else src
    except Exception as e:  # noqa: BLE001 — fall through
        log_fn(f'prelevel: level_to unavailable ({type(e).__name__}) — single shot')

    gain = 0.0
    try:
        from zyg_workflows import audio_mix

        i_lufs = audio_mix.measure_lufs(src, log_fn=None)  # a float, not a dict
        if i_lufs is not None:
            gain = max(-24.0, min(24.0, float(target_lufs) - float(i_lufs)))
    except Exception as e:  # noqa: BLE001
        log_fn(f'prelevel: could not measure ({type(e).__name__}) — no pre-gain')
    if abs(gain) <= 0.25:
        return src
    af = f'volume={gain:.2f}dB,alimiter=limit=0.75:attack=5:release=60:level=disabled'
    if _ff(['-i', src, '-af', af, '-ar', '48000', '-c:a', 'pcm_s16le', dst], log_fn=log_fn):
        log_fn(f'prelevel: {gain:+.1f} dB through a -2.5 dBFS limiter')
        return dst
    return src


def soundfont_info():
    """What the score render will ACTUALLY use, verified against the allow-list.

    licence.ok_commercial used to be a hardcoded `True`. Proof it was never
    derived from anything: a run with ZYG_KIDSMUSIC_SF2=/nonexistent.sf3 still
    shipped a manifest reading "soundfont": "MuseScore_General.sf3 (MIT)",
    "ok_commercial": true — with no audio rendered at all.
    """
    import hashlib

    info = {
        'ok': False,
        'path': SOUNDFONT,
        'basename': os.path.basename(SOUNDFONT),
        'sha256': '',
        'licence': '',
        'attribution': '',
        'reason': '',
    }
    entry = ALLOWED_SOUNDFONTS.get(info['basename'])
    if not os.path.isfile(SOUNDFONT):
        info['reason'] = 'soundfont file does not exist'
        return info
    if not entry:
        info['reason'] = f'{info["basename"]} is not on the allow-list'
        return info
    try:
        h = hashlib.sha256()
        with open(SOUNDFONT, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''):
                h.update(chunk)
        info['sha256'] = h.hexdigest()
    except OSError as e:
        info['reason'] = f'unreadable: {e}'
        return info
    info.update({'ok': True, 'licence': entry['licence'], 'attribution': entry['attribution']})
    return info


def _merge_voice_licences(voices):
    """{licence_id: sample count} across every voice that played, merged.

    voice_info() reports its licences per voice; the manifest wants the folder's
    total, because that is the question a publish check asks — "what licences
    are in this song", not "what licences is the cello under".
    """
    out = {}
    for info in (voices or {}).values():
        for lic, n in ((info or {}).get('licences') or {}).items():
            out[lic] = out.get(lic, 0) + int(n)
    return dict(sorted(out.items()))


def _write_state(out_dir, manifest, job_id=''):
    """The per-run state file every other department writes.

    Without it a kidsmusic run is invisible to the metrics roll-up, to the jobs
    audit and to restart recovery — it never appears in by_pipeline_type and a
    GUI bounce loses it entirely.

    The filename convention is `data/runtime/pipeline_<id>_state.json`, which is
    what pipeline_common.recent_state_files globs for — a state file written
    anywhere else is a state file nothing reads.
    """
    try:
        jid = job_id or os.path.basename(out_dir.rstrip('/'))
        d = manifest.get('delivery') or {}
        v = manifest.get('video') or {}
        # The roll-up buckets by pipeline_type, so a cinematic cue counted as
        # 'kidsmusic' would put orchestral runs in the children's totals. The
        # DEPARTMENT stays 'kidsmusic': the busy-check, the Live Tail and the
        # `kidsmusic-{pid}` worker-alive needle all key on it.
        cinematic = (manifest.get('family') or 'children') == 'cinematic'
        state = {
            'pipeline_id': jid,
            'job_id': jid,
            'pipeline_type': 'cinematic' if cinematic else 'kidsmusic',
            'department': 'kidsmusic',
            # 'video' when an mp4 actually exists. The roll-up buckets by this,
            # so asserting 'video' on a run whose picture leg failed would count
            # a song that has no pictures as an illustrated one.
            'mode': 'video' if v.get('ok') else 'audio',
            'status': 'completed' if manifest.get('ok') else 'failed',
            'current_stage': 'Deliver' if manifest.get('ok') else 'Error',
            'started': manifest.get('created'),
            'directive': (manifest.get('brief') or {}).get('theme', ''),
            'output_dir': out_dir,
            'progress_pct': 100,
            'error': None if manifest.get('ok') else (d.get('reason') or 'run produced no audio'),
            'params': {
                'title': manifest.get('title'),
                'style': manifest.get('style'),
                'singer': (manifest.get('brief') or {}).get('singer'),
                'score': (manifest.get('score') or {}).get('total'),
                'elapsed_s': manifest.get('elapsed_s'),
            },
            'result': {
                'picked': d.get('picked'),
                'picked_leg': d.get('picked_leg'),
                'produced_status': d.get('produced_status'),
                'melody_followed': d.get('melody_followed'),
                'video': v.get('file'),
                'video_pictures': (v.get('pacing') or {}).get('pictures'),
                'video_per_5s': (v.get('pacing') or {}).get('per_5s_mean'),
                'ok_commercial': (manifest.get('licence') or {}).get('ok_commercial'),
            },
            'stages': {},
            'stage_timeline': [],
            'debug_events': [],
        }
        with open(os.path.join(out_dir, 'state.json'), 'w') as fh:
            json.dump(state, fh, indent=1)
        root = os.path.join(HERE, 'data', 'runtime')
        if os.path.isdir(root):
            with open(os.path.join(root, f'pipeline_{jid}_state.json'), 'w') as fh:
                json.dump(state, fh, indent=1)
    except Exception as _exc:  # noqa: BLE001 — bookkeeping, never fatal
        _zyg_log.warning('dashboard state write for %s failed, the roll-up will miss this run: %s', out_dir, _exc)
