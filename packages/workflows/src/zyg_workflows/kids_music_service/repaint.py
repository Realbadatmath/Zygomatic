# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Repaint: re-generate one window of a finished take, and splice it back in.

Moved verbatim out of the old single-file kids_music_service.py (lines 1027-1373).
"""

from __future__ import annotations

import json
import os
import subprocess
from zyg_workflows import paths
from zyg_workflows.bin import exe

from zyg_workflows.kids_music_service.base import (
    ACE_CHECKPOINT,
    _log_noop,
    _zyg_log,
)
from zyg_workflows.kids_music_service.ace import (
    _attest,
    _stage_comfy_audio,
    _submit_abort_kw,
    ace_available,
    ace_prompt,
)
from zyg_workflows.kids_music_service.measure import gate_audio

# ── Repaint: re-generate one window of a finished take ───────────────────────
#
# Spike 2026-09-15 (tools/kidsmusic_repaint_spike.py, output/kidsmusic/_repaint_spike/):
# VAEEncodeAudio(take) -> KJNodes LTXVAudioVideoMask (audio latent, 'partial',
# 'overwrite') -> KSampler with the take's own TextEncodeAceStepAudio1.5 inputs.
#   * audio outside the window came back bit-identical to a VAE roundtrip at
#     every denoise (-240 dB); only +-0.5 s around the window moves
#   * denoise 0.7 sang the bumblebee's skipped line, in the male band (221/227 Hz
#     on two seeds), key and tempo held; 0.5-0.6 jumped an octave in 3 of 4 arms
#   * the key read flipped in 3 of 12 masked arms, so every repaint is re-gated
# Pitfalls it found and this code honours: SetLatentNoiseMask crashes on the 3-D
# ACE latent; the KJ node assumes 25 latents/s (true for ACE-Step 1.5) with an
# INCLUSIVE end index (pass end - 0.04 s); 8 steps make d0.9 == d1.0; the window
# follows the LM audio codes, so tags, lyrics, duration and the LM seed must be
# the take's own.
# The VAE roundtrip is lossy (-18 dB residual, 1.1-1.3 dB log-mel), so the
# repaint is never shipped whole: splice_window() puts ONLY the window (plus its
# spill) back into the original take with short equal-power crossfades.

ACE_WORKFLOW_REPAINT = 'ace_step_kidsong_repaint'
REPAINT_MASK_NODE = 'LTXVAudioVideoMask'
REPAINT_DENOISE = float(os.environ.get('ZYG_KIDSMUSIC_REPAINT_DENOISE', '0.7'))
_ACE_LATENT_HZ = 25.0


def _comfy_has_node(name):
    try:
        from zyg_workflows.net import safe_urlopen as _safe_urlopen

        base = os.environ.get('ZYG_COMFYUI_URL', paths.ZYG_COMFY_URL).rstrip('/')
        with _safe_urlopen(f'{base}/object_info/{name}', timeout=5) as r:
            return name in json.loads(r.read().decode('utf-8') or '{}')
    except Exception:  # noqa: BLE001 — absent means absent
        return False


def ace_repaint(
    plan,
    take_path,
    out_path,
    *,
    start_s,
    end_s,
    lm_seed,
    seed,
    tags=None,
    seconds=None,
    denoise=None,
    info=None,
    log_fn=None,
    should_abort=None,
    timeout_s=None,
):
    """Re-generate ONLY [start_s, end_s] of an existing ACE-Step take.

    `lm_seed`, `tags` and `seconds` must be the take's own (its ace_render info:
    'seed' / 'lm_seed', 'ace_tags', 'seconds') — the masked window is filled
    from the LM's audio codes, and a different LM plan fills it with a different
    song. `seed` is the sampler seed: vary it to get a different repair.
    Returns out_path (the whole decoded song; only the window is new) or None.
    """
    log_fn = log_fn or _log_noop
    rec = info if isinstance(info, dict) else {}
    rec.update(
        {
            'ran': False,
            'reason': '',
            'start_s': round(float(start_s), 2),
            'end_s': round(float(end_s), 2),
            'seed': int(seed),
            'lm_seed': int(lm_seed),
        }
    )
    if should_abort and should_abort():
        rec['reason'] = 'halt requested'
        return None
    if not ace_available():
        rec['reason'] = 'ComfyUI down or checkpoint missing'
        return None
    if not _comfy_has_node(REPAINT_MASK_NODE):
        rec['reason'] = f'{REPAINT_MASK_NODE} node not installed'
        log_fn(f'repaint: unavailable ({rec["reason"]})')
        return None
    import shutil
    from zyg_workflows import _comfy_client as _cc

    seconds = float(
        seconds or max(10.0, min(float(os.environ.get('ZYG_ACE_MAX_SECONDS', '210')), float(plan['seconds'])))
    )
    staged = _stage_comfy_audio(take_path, log_fn=log_fn, stem='repaint')
    if not staged:
        rec['reason'] = 'could not stage the take'
        return None
    d = float(REPAINT_DENOISE if denoise is None else denoise)
    node2 = {
        'tags': tags or ace_prompt(plan),
        'lyrics': plan.get('lyrics_block') or '[inst]',
        'seed': int(lm_seed),
        'bpm': int(plan['bpm']),
        'duration': seconds,
        'timesignature': str(plan['ts']),
        'keyscale': plan['key']['ace_keyscale'],
    }
    overrides = {
        '1': {'ckpt_name': ACE_CHECKPOINT},
        '2': node2,
        '8': {'audio': staged},
        '10': {
            'audio_start_time': round(float(start_s), 3),
            'audio_end_time': round(float(end_s) - 1.0 / _ACE_LATENT_HZ, 3),
        },
        '5': {'seed': int(seed), 'denoise': d},
    }
    rec['denoise'] = d
    try:
        wf = _cc.load_workflow(ACE_WORKFLOW_REPAINT)
        graph = json.loads(json.dumps(wf))
        for nid, vals in overrides.items():
            graph[nid].setdefault('inputs', {}).update(vals)
        att = _attest(graph, log_fn=log_fn, tag='kidsmusic-repaint')
        if att.get('ok') is False:
            rec['reason'] = 'licence attestation FAILED'
            return None
        outputs = _cc.submit(
            wf,
            overrides=overrides,
            timeout_s=float(timeout_s or os.environ.get('ZYG_ACE_TIMEOUT_S', '900')),
            **_submit_abort_kw(should_abort),
        )
        rec['lock_wait_s'] = float((getattr(_cc, 'last_submit_timing', {}) or {}).get('lock_wait_s') or 0.0)
    except Exception as e:  # noqa: BLE001
        rec['reason'] = f'{type(e).__name__}: {e}'[:200]
        log_fn(f'repaint: failed — {rec["reason"]}')
        return None
    finally:
        try:
            os.remove(os.path.join(str(paths.ZYG_COMFY_INPUT), staged))
        except OSError as _exc:
            _zyg_log.debug('staged comfy input %s removal skipped: %s', staged, _exc)
    aud = [p for p in outputs if p.lower().endswith(('.flac', '.wav', '.mp3')) and os.path.isfile(p)]
    if not aud:
        rec['reason'] = 'job completed but produced no audio'
        return None
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    shutil.copy2(aud[0], out_path)
    try:
        os.remove(aud[0])
    except OSError as _exc:
        _zyg_log.debug('comfy output %s removal skipped: %s', aud[0], _exc)
    rec['ran'] = True
    return out_path


def _decode_stereo(path, sr=44100):
    import numpy as np

    r = subprocess.run(
        [exe('ffmpeg'), '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '2', '-ar', str(sr), '-'],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).copy()


def splice_window(original, repainted, out_wav, start_s, end_s, *, guard_s=0.5, xfade_s=0.15, sr=44100):
    """The original take with [start_s, end_s] (+ the decoder's +-guard_s spill)
    taken from the repaint, equal-power crossfaded in and out. Returns a record
    with the alignment lag and how far the two differ inside each crossfade (the
    seam: ~ the VAE roundtrip's own residual when the join is clean)."""
    import numpy as np
    import soundfile as sf

    o = _decode_stereo(original, sr)
    p = _decode_stereo(repainted, sr)
    # Alignment on up to 3 s of UNTOUCHED audio — before the window, or after it
    # when the window starts too early to leave 1.5 s in front.
    pre_end = int((start_s - guard_s - 0.3) * sr)
    post_start = int((end_s + guard_s + 0.3) * sr)
    if pre_end >= int(1.5 * sr) or len(o) - post_start < int(1.5 * sr):
        a1, a0 = max(sr // 2, pre_end), max(0, pre_end - 3 * sr)
    else:
        a0, a1 = post_start, min(len(o) - 2400, post_start + 3 * sr)
    ref = o[a0:a1, 0].astype(np.float64)
    MAXLAG = 2400
    lo = max(0, a0 - MAXLAG)
    hay = p[lo : a1 + MAXLAG, 0].astype(np.float64)
    # exact cross-correlation by FFT; lag L means p[x + L] ~ o[x]
    n = 1 << int(np.ceil(np.log2(len(hay) + len(ref))))
    xc = np.fft.irfft(np.fft.rfft(hay, n) * np.conj(np.fft.rfft(ref, n)), n)
    lags = np.arange(len(xc))
    lags = np.where(lags > n // 2, lags - n, lags) + lo - a0
    ok = np.abs(lags) <= MAXLAG
    i = int(np.argmax(np.where(ok, xc, -np.inf)))
    best_lag = int(lags[i])
    seg = p[a0 + best_lag : a1 + best_lag, 0] if a0 + best_lag >= 0 else np.zeros(0)
    best = (
        float(np.dot(ref, seg) / ((np.linalg.norm(ref) * np.linalg.norm(seg)) or 1.0)) if len(seg) == len(ref) else 0.0
    )
    if best_lag > 0:
        p = p[best_lag:]
    elif best_lag < 0:
        p = np.concatenate([np.zeros((-best_lag, 2), dtype=np.float32), p])
    if len(p) < len(o):
        p = np.concatenate([p, o[len(p) :]])
    xf = max(1, int(xfade_s * sr))
    a = max(0, int((start_s - guard_s) * sr) - xf)
    b = min(len(o), int((end_s + guard_s) * sr) + xf)
    out = o.copy()
    ramp = np.sin(np.linspace(0.0, np.pi / 2.0, xf, dtype=np.float32)) ** 2
    fin, fout = np.sqrt(ramp)[:, None], np.sqrt(1.0 - ramp)[:, None]
    out[a : a + xf] = o[a : a + xf] * fout + p[a : a + xf] * fin
    out[a + xf : b - xf] = p[a + xf : b - xf]
    out[b - xf : b] = p[b - xf : b] * fout + o[b - xf : b] * fin

    def seam(i, j):
        num = float(np.sqrt(np.mean((o[i:j] - p[i:j]) ** 2)))
        den = float(np.sqrt(np.mean(o[i:j] ** 2))) or 1e-9
        return round(20.0 * np.log10(max(num / den, 1e-9)), 1)

    peak = float(np.abs(out).max()) or 1.0
    if peak > 0.999:
        out = out * (0.999 / peak)
    os.makedirs(os.path.dirname(out_wav) or '.', exist_ok=True)
    sf.write(out_wav, out, sr, subtype='PCM_16')
    return {
        'path': out_wav,
        'lag_samples': int(best_lag),
        'align_corr': round(best, 4),
        'seam_in_db': seam(a, a + xf),
        'seam_out_db': seam(b - xf, b),
        'window_s': [round(a / sr, 2), round(b / sr, 2)],
    }


def repair_take(
    take_path,
    plan,
    singer,
    rep,
    take_info,
    work_dir,
    *,
    log_fn=None,
    should_abort=None,
    max_windows=None,
    seeds_per_window=2,
    budget_s=None,
):
    """Repaint every line vocal_analysis flagged as missing or sung too high, one
    window at a time, keeping a repair ONLY when the re-reviewed take is strictly
    less wrong (vocal_analysis.severity) and its key read did not get worse.

    Returns (take_path, review, records) — the original path and review when
    nothing was kept.

    The budget is WORK time: time queued behind another ComfyUI client is
    subtracted (each repaint records its lock wait). The first trial on the
    bumblebee spent its whole 360 s waiting behind a 17-minute Wan render and
    got one attempt — a budget that counts the queue turns contention into
    "no repairs" without saying so.
    """
    import time as _time
    from zyg_workflows import vocal_analysis as VA

    log_fn = log_fn or _log_noop
    max_windows = int(max_windows or os.environ.get('ZYG_KIDSMUSIC_REPAIR_WINDOWS', '3'))
    budget_s = float(budget_s or os.environ.get('ZYG_KIDSMUSIC_REPAIR_BUDGET_S', '360'))
    t0 = _time.time()
    waited = [0.0]

    def work_s():
        return _time.time() - t0 - waited[0]

    records = []
    wins = VA.repair_windows(rep, rep.get('problems') or [], seconds=take_info.get('seconds'))
    if not wins:
        return take_path, rep, records
    base_key = (gate_audio(take_path, plan, leg='produced', want_clap=False, log_fn=None).get('checks') or {}).get(
        'key_match'
    )
    lm_seed = take_info.get('lm_seed') or take_info.get('seed')
    if lm_seed is None:
        return take_path, rep, [{'result': 'skipped', 'reason': 'the take recorded no seed'}]
    current, cur = take_path, rep
    for i, w in enumerate(wins[:max_windows]):
        for n in range(seeds_per_window):
            if should_abort and should_abort():
                return current, cur, records
            if work_s() > budget_s:
                log_fn(f'repair: time budget {budget_s:.0f}s of work spent (plus {waited[0]:.0f}s queued) — stopping')
                return current, cur, records
            seed = int(lm_seed) + 7919 * (n + 1) + int(w['start_s'] * 100)
            rec = {'window': w, 'attempt': n + 1, 'seed': seed}
            log_fn(
                f'repair: lines {[x + 1 for x in w["lines"]]} — repainting '
                f'{w["start_s"]:.1f}-{w["end_s"]:.1f}s (seed {seed})'
            )
            raw = ace_repaint(
                plan,
                current,
                os.path.join(work_dir, f'repaint_{i}_{n}.flac'),
                start_s=w['start_s'],
                end_s=w['end_s'],
                lm_seed=lm_seed,
                seed=seed,
                tags=take_info.get('ace_tags'),
                seconds=take_info.get('seconds'),
                info=rec,
                log_fn=log_fn,
                should_abort=should_abort,
            )
            waited[0] += float(rec.get('lock_wait_s') or 0.0)
            if not raw:
                rec['result'] = 'no render'
                records.append(rec)
                if 'not installed' in (rec.get('reason') or '') or 'down' in (rec.get('reason') or ''):
                    return current, cur, records
                continue
            sp = splice_window(current, raw, os.path.join(work_dir, f'spliced_{i}_{n}.wav'), w['start_s'], w['end_s'])
            rec['splice'] = {k: sp[k] for k in ('lag_samples', 'align_corr', 'seam_in_db', 'seam_out_db')}
            new = VA.review(sp['path'], plan, singer, os.path.join(work_dir, f'review_{i}_{n}'), log_fn=log_fn)
            key = (gate_audio(sp['path'], plan, leg='produced', want_clap=False, log_fn=None).get('checks') or {}).get(
                'key_match'
            )
            rec.update(
                {
                    'severity_before': cur.get('severity'),
                    'severity_after': new.get('severity'),
                    'key_before': base_key,
                    'key_after': key,
                    'problems_after': [p['detail'] for p in new.get('problems') or []][:6],
                }
            )
            key_ok = key in ('exact', 'relative') or key == base_key
            if new.get('ok') and key_ok and new['severity'] < (cur.get('severity') or 0):
                rec['result'] = 'kept'
                log_fn(
                    f'repair: kept — severity {cur.get("severity")} -> {new["severity"]} '
                    f'(key {key}); {VA.summary_line(new)}'
                )
                current, cur = sp['path'], new
                records.append(rec)
                break
            rec['result'] = 'rejected'
            log_fn(f'repair: rejected — severity {cur.get("severity")} -> {new.get("severity")}, key {key}')
            records.append(rec)
    return current, cur, records
