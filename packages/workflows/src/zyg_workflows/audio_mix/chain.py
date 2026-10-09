# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  - this module inherits the original top import block; its
# siblings re-import from here, so an unused name is still part of the package API.
"""The processing chain: low-level ffmpeg helpers, loudness normalization,
ambience bed construction, sidechain ducking and the scratch-dir helper.

Moved verbatim out of the old single-file audio_mix.py (lines 52-509 and
783-797; the scratch-dir helper joins its four callers here because they
call it and it has no module-level effect of its own).
"""

from __future__ import annotations

import os
import logging as _zyg_logging

from zyg_workflows.bin import exe
from zyg_workflows.paths import ZYG_TMP_DIR

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.audio_mix')


def _log_noop(msg):
    pass


# ── low-level helpers ─────────────────────────────────────────────────────


def _run(cmd, log_fn=None):
    """Run a command list; return (returncode, stderr_text). Never raises."""
    import subprocess

    log_fn = log_fn or _log_noop
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1800,
        )
        return proc.returncode, proc.stderr.decode('utf-8', errors='replace')
    except Exception as e:  # noqa: BLE001 — fail-safe across module boundary
        log_fn(f'audio_mix: subprocess failed: {e} :: {" ".join(cmd[:6])}...')
        return -1, str(e)


def _ffmpeg(args, log_fn=None, loglevel='error'):
    """ffmpeg wrapper with -y and stderr capture. Returns (rc, stderr)."""
    return _run([exe('ffmpeg'), '-y', '-hide_banner', '-nostats', '-loglevel', loglevel] + args, log_fn=log_fn)


def _ok_output(out_path, rc, err, log_fn, what):
    """Common success check: rc==0 and non-empty file. Returns bool."""
    log_fn = log_fn or _log_noop
    if rc != 0:
        log_fn(f'audio_mix: {what} failed rc={rc}: {err.strip()[-800:]}')
        return False
    try:
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            log_fn(f'audio_mix: {what} produced no output: {out_path}')
            return False
    except OSError as e:
        log_fn(f'audio_mix: {what} stat failed: {e}')
        return False
    return True


def probe_duration(path, log_fn=None):
    """Return media duration in seconds (float) or None."""
    log_fn = log_fn or _log_noop
    rc, _err = 0, ''
    import subprocess

    try:
        proc = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        rc = proc.returncode
        if rc == 0:
            return float(proc.stdout.decode().strip())
        _err = proc.stderr.decode(errors='replace')
    except Exception as e:  # noqa: BLE001
        _err = str(e)
    log_fn(f'audio_mix: ffprobe duration failed for {path}: {_err.strip()[-300:]}')
    return None


def _probe_audio_props(path, log_fn=None):
    """Return {'sample_rate': int, 'channels': int} of first audio stream, or None."""
    log_fn = log_fn or _log_noop
    import subprocess

    try:
        proc = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-select_streams',
                'a:0',
                '-show_entries',
                'stream=sample_rate,channels',
                '-of',
                'default=noprint_wrappers=1',
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if proc.returncode != 0:
            log_fn(f'audio_mix: ffprobe props failed: {proc.stderr.decode(errors="replace")[-300:]}')
            return None
        props = {}
        for line in proc.stdout.decode().splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                props[k.strip()] = v.strip()
        return {'sample_rate': int(props.get('sample_rate', 0)), 'channels': int(props.get('channels', 0))}
    except Exception as e:  # noqa: BLE001
        log_fn(f'audio_mix: ffprobe props error for {path}: {e}')
        return None


def _ensure_48k_mono(in_path, tmp_dir, tag, log_fn=None):
    """Return path to a 48 kHz mono version of in_path (original if already ok)."""
    log_fn = log_fn or _log_noop
    props = _probe_audio_props(in_path, log_fn=log_fn)
    if props and props['sample_rate'] == 48000 and props['channels'] == 1:
        return in_path
    out = os.path.join(tmp_dir, f'_48kmono_{tag}.wav')
    rc, err = _ffmpeg(['-i', in_path, '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', out], log_fn=log_fn)
    if not _ok_output(out, rc, err, log_fn, f'resample({tag})'):
        return None
    return out


def measure_lufs(path, log_fn=None):
    """Integrated LUFS via a quick ebur128 scan; float or None.

    ebur128 prints its summary at info loglevel, hence the deviation from
    the -loglevel error house rule (measurement only — no output file).
    """
    import re

    log_fn = log_fn or _log_noop
    rc, err = _ffmpeg(
        ['-i', path, '-map', '0:a', '-filter:a', 'ebur128', '-f', 'null', '-'], log_fn=log_fn, loglevel='info'
    )
    if rc != 0:
        log_fn(f'audio_mix: ebur128 scan failed: {err.strip()[-400:]}')
        return None
    m = re.findall(r'I:\s*(-?[0-9.]+)\s*LUFS', err)
    if not m:
        log_fn('audio_mix: ebur128 summary not found in stderr')
        return None
    try:
        return float(m[-1])
    except ValueError:
        return None


# ── loudness normalization ────────────────────────────────────────────────


def loudnorm_two_pass(in_path, out_path, i=-16.0, tp=-1.5, lra=11.0, ar=48000, dual_mono=False, log_fn=None):
    """Two-pass EBU R128 loudnorm.  Returns {'out': out_path,
    'measured': {...}, 'normalization_type': 'linear'|'dynamic'|None,
    'lra_eff': float} or None.

    NEVER single-pass: without measured values loudnorm runs a dynamic AGC
    that mangles deliberate narration pauses.  Pass 1 measures, pass 2
    requests linear=true gain — but ffmpeg SILENTLY reverts to dynamic AGC
    when measured LRA > target LRA or the linear gain would push true peak
    past TP.  So pass 2 (a) raises the LRA target to clear the measured
    input_lra (lra_eff; for pass 2 the LRA target is only a linear-
    eligibility bound — validated 2026-07-30: LRA=22 on an input_lra 20.2
    mix prints 'linear' with integrated still on target), (b) runs
    print_format=json at info loglevel and parses what ffmpeg ACTUALLY did
    into 'normalization_type' for the caller to gate on, and (c) logs
    loudly up front when linear is arithmetically impossible
    ((i - input_i) + input_tp > tp).  dual_mono=True makes BS.1770 treat a
    mono input as dual-mono (use when the file will later be upmixed
    L=R=c0, which raises integrated loudness by ~3 LU).
    """
    import json
    import math
    import re

    log_fn = log_fn or _log_noop
    dm = ':dual_mono=true' if dual_mono else ''
    base = f'loudnorm=I={i:g}:TP={tp:g}:LRA={lra:g}{dm}'

    # Pass 1 — measure.  loudnorm prints its JSON at info loglevel, so this
    # is the one place we cannot use -loglevel error.
    rc, err = _ffmpeg(
        ['-i', in_path, '-af', f'{base}:print_format=json', '-f', 'null', '-'], log_fn=log_fn, loglevel='info'
    )
    if rc != 0:
        log_fn(f'audio_mix: loudnorm pass1 failed: {err.strip()[-800:]}')
        return None
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', err, re.S)
    if not m:
        log_fn('audio_mix: loudnorm pass1 JSON block not found in stderr')
        return None
    try:
        measured = json.loads(m.group(0))
    except ValueError as e:
        log_fn(f'audio_mix: loudnorm pass1 JSON parse failed: {e}')
        return None
    for key in ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset'):
        val = str(measured.get(key, ''))
        if not val or 'inf' in val.lower() or 'nan' in val.lower():
            log_fn(f'audio_mix: loudnorm measured {key}={val!r} unusable (silent/degenerate input?) — refusing pass 2')
            return None

    # Pass 2 — apply with measured values, linear gain.  Raise the LRA
    # target above the measured value so LRA never disqualifies linear mode
    # (it is only an eligibility bound in pass 2), and predict the one case
    # LRA can't fix: linear gain that would breach the TP ceiling.
    lra_eff = max(float(lra), math.ceil(float(measured['input_lra'])) + 1.0)
    if lra_eff > float(lra):
        log_fn(
            f'audio_mix: loudnorm pass2 raising LRA target {lra:g} -> '
            f'{lra_eff:g} (measured input_lra={measured["input_lra"]}) '
            f'to stay linear-eligible'
        )
    gain_db = float(i) - float(measured['input_i'])
    pred_tp = float(measured['input_tp']) + gain_db
    if pred_tp > float(tp):
        log_fn(
            f'audio_mix: LOUDNORM LINEAR IMPOSSIBLE for {in_path}: '
            f'{gain_db:+.2f} dB linear gain would put true peak at '
            f'{pred_tp:.2f} dBTP > target {tp:g} — ffmpeg WILL fall back '
            f'to dynamic AGC (pause-pumping risk); caller must check '
            f"'normalization_type' in the returned dict"
        )
    filt = (
        f'loudnorm=I={i:g}:TP={tp:g}:LRA={lra_eff:g}{dm}'
        f':measured_I={measured["input_i"]}'
        f':measured_TP={measured["input_tp"]}'
        f':measured_LRA={measured["input_lra"]}'
        f':measured_thresh={measured["input_thresh"]}'
        f':offset={measured["target_offset"]}'
        f':linear=true:print_format=json'
    )
    # print_format=json emits at info loglevel — the second sanctioned
    # deviation from the -loglevel error house rule (see module docstring).
    rc, err = _ffmpeg(['-i', in_path, '-af', filt, '-ar', str(int(ar)), out_path], log_fn=log_fn, loglevel='info')
    if not _ok_output(out_path, rc, err, log_fn, 'loudnorm pass2'):
        return None
    m2 = re.search(r'"normalization_type"\s*:\s*"([A-Za-z]+)"', err) or re.search(
        r'Normalization Type:\s*([A-Za-z]+)', err
    )
    norm_type = m2.group(1).lower() if m2 else None
    if norm_type is None:
        log_fn('audio_mix: loudnorm pass2 normalization_type not found in stderr — reporting None (unverified)')
    elif norm_type != 'linear':
        log_fn(
            f'audio_mix: WARNING loudnorm pass2 applied {norm_type} '
            f'normalization, NOT the linear gain this chain promises — '
            f'dynamic AGC altered the program dynamics'
        )
    if norm_type != 'linear':
        # 2026-07-30: log the silent degrade to the cross-run ledger. Callers that
        # forget to gate on 'normalization_type' used to ship pause-pumped audio
        # for an unknown number of episodes with nothing to diff. Fail-safe and
        # lazy-imported: the ledger must never break a mix.
        try:
            from zyg_workflows import run_ledger

            run_ledger.record_fallback(
                'loudnorm',
                'linear',
                norm_type or 'unverified',
                detail=(
                    f'in={os.path.basename(in_path)} I={i:g} TP={tp:g} '
                    f'LRA_eff={lra_eff:g} input_i={measured.get("input_i")} '
                    f'input_tp={measured.get("input_tp")} '
                    f'input_lra={measured.get("input_lra")} '
                    f'gain={gain_db:+.2f}dB pred_tp={pred_tp:.2f}dBTP'
                ),
                log_fn=log_fn,
            )
        except Exception as _exc:
            _zyg_log.warning('run-ledger fallback record failed, the loudnorm fallback stays unlogged: %s', _exc)
    log_fn(
        f'audio_mix: loudnorm ok I={measured["input_i"]}->target {i:g} '
        f'LUFS ({norm_type or "unverified"}), out={out_path}'
    )
    return {'out': out_path, 'measured': measured, 'normalization_type': norm_type, 'lra_eff': lra_eff}


# ── ambience bed construction ─────────────────────────────────────────────


def _loop_layer_filter(n_copies, crossfade_s, duration_s, gain_db):
    """Build filter_complex looping n_copies inputs of the same file with
    tail-to-head acrossfades, then trim/fade/gain to a bed layer."""
    parts = []
    cur = '[0:a]'
    for k in range(1, n_copies):
        out = f'[x{k}]'
        parts.append(f'{cur}[{k}:a]acrossfade=d={crossfade_s:g}:c1=tri:c2=tri{out}')
        cur = out
    tail_fade_start = max(0.0, duration_s - 0.5)
    parts.append(
        f'{cur}atrim=0:{duration_s:g},asetpts=PTS-STARTPTS,'
        f'afade=t=in:st=0:d=0.5,'
        f'afade=t=out:st={tail_fade_start:g}:d=0.5,'
        f'volume={gain_db:g}dB,'
        f'aformat=channel_layouts=mono:sample_rates=48000[bed]'
    )
    return ';'.join(parts)


def prep_bed(layers, duration_s, out_path, crossfade_s=1.5, log_fn=None):
    """Build a duration_s ambience bed (48 kHz MONO wav) from layers.

    layers = [{'path': str, 'gain_db': float}, ...]

    Short layers loop with a tail-to-head acrossfade of crossfade_s so the
    seam is inaudible (naive concat clicks; naive -stream_loop pops).  Each
    layer is trimmed to duration_s with 0.5 s edge fades, gain applied,
    then all layers amix'd with normalize=0 (keep authored balance).
    Returns out_path or None.
    """
    import math
    import tempfile

    log_fn = log_fn or _log_noop
    if not layers:
        log_fn('audio_mix: prep_bed called with no layers')
        return None
    duration_s = float(duration_s)
    if duration_s <= 0:
        log_fn(f'audio_mix: prep_bed bad duration {duration_s}')
        return None

    with tempfile.TemporaryDirectory(dir=_scratch_dir()) as td:
        layer_files = []
        for idx, layer in enumerate(layers):
            path = layer.get('path')
            gain_db = float(layer.get('gain_db', 0.0))
            if not path or not os.path.exists(path):
                log_fn(f'audio_mix: prep_bed layer {idx} missing: {path} — skipped')
                continue
            src_dur = probe_duration(path, log_fn=log_fn)
            if not src_dur or src_dur <= 0.05:
                log_fn(f'audio_mix: prep_bed layer {idx} unusable duration {src_dur} — skipped')
                continue

            cf = min(float(crossfade_s), max(0.05, src_dur / 2 - 0.05))
            if src_dur >= duration_s:
                n = 1
            else:
                # n copies joined by acrossfade last n*d - (n-1)*cf seconds
                n = int(math.ceil((duration_s - cf) / (src_dur - cf)))
                n = max(2, n)
            if n > 64:
                log_fn(
                    f'audio_mix: prep_bed layer {idx} would need {n} loop '
                    f'copies (src {src_dur:.2f}s) — too short, skipped'
                )
                continue

            layer_out = os.path.join(td, f'layer_{idx}.wav')
            args = []
            for _ in range(n):
                args += ['-i', path]
            filt = _loop_layer_filter(n, cf, duration_s, gain_db)
            args += ['-filter_complex', filt, '-map', '[bed]', '-c:a', 'pcm_s16le', layer_out]
            rc, err = _ffmpeg(args, log_fn=log_fn)
            if not _ok_output(layer_out, rc, err, log_fn, f'prep_bed layer {idx}'):
                continue
            got = probe_duration(layer_out, log_fn=log_fn)
            if got is None or abs(got - duration_s) > 0.1:
                log_fn(f'audio_mix: prep_bed layer {idx} duration {got} != {duration_s} — loop math wrong, skipped')
                continue
            log_fn(
                f'audio_mix: prep_bed layer {idx} ok ({n} cop{"y" if n == 1 else "ies"}, {got:.2f}s, {gain_db:+.1f} dB)'
            )
            layer_files.append(layer_out)

        if not layer_files:
            log_fn('audio_mix: prep_bed produced no usable layers')
            return None

        if len(layer_files) == 1:
            rc, err = _ffmpeg(
                ['-i', layer_files[0], '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', out_path], log_fn=log_fn
            )
        else:
            args = []
            for f in layer_files:
                args += ['-i', f]
            inputs = ''.join(f'[{k}:a]' for k in range(len(layer_files)))
            filt = f'{inputs}amix=inputs={len(layer_files)}:duration=longest:normalize=0[m]'
            args += ['-filter_complex', filt, '-map', '[m]', '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', out_path]
            rc, err = _ffmpeg(args, log_fn=log_fn)
        if not _ok_output(out_path, rc, err, log_fn, 'prep_bed amix'):
            return None

    got = probe_duration(out_path, log_fn=log_fn)
    log_fn(f'audio_mix: prep_bed ok {got}s -> {out_path}')
    return out_path


# ── sidechain ducking ─────────────────────────────────────────────────────


def duck_mix(
    vo_path, bed_path, out_path, bed_gain_db=0.0, threshold=0.06, ratio=3, attack=20, release=600, log_fn=None
):
    """Duck the ambience bed under the voice-over via sidechain compression.

    Depth calibrated 2026-07-30 on the scene20 mix: threshold 0.06 / ratio 3
    gives ~7 dB of duck (bed -41 dB RMS under speech vs -34 in pauses) — the
    bed stays SOFTLY AUDIBLE while the voice speaks and swells back in the
    scripted beats.  The earlier 0.02/8 crushed it 14.5 dB to inaudibility.

    Graph (researched, do not 'simplify'):
      [0:a]asplit=2[vo][key];
      [1:a]volume=<bed_gain_db>dB[b];
      [b][key]sidechaincompress=threshold=..:ratio=..:attack=..:release=..[duck];
      [vo][duck]amix=inputs=2:duration=first:normalize=0

    normalize=0 is MANDATORY (amix would otherwise halve both inputs and
    undo the VO loudnorm); duration=first is MANDATORY (the VO track defines
    program length — a longer bed must not extend it).  Inputs are
    resampled to 48 kHz mono first if needed (sidechaincompress requires
    matching formats).  Returns out_path or None.
    """
    import tempfile

    log_fn = log_fn or _log_noop
    with tempfile.TemporaryDirectory(dir=_scratch_dir()) as td:
        vo = _ensure_48k_mono(vo_path, td, 'vo', log_fn=log_fn)
        bed = _ensure_48k_mono(bed_path, td, 'bed', log_fn=log_fn)
        if not vo or not bed:
            log_fn('audio_mix: duck_mix input prep failed')
            return None
        fc = (
            '[0:a]asplit=2[vo][key];'
            f'[1:a]volume={float(bed_gain_db):g}dB[b];'
            f'[b][key]sidechaincompress=threshold={float(threshold):g}'
            f':ratio={float(ratio):g}:attack={float(attack):g}'
            f':release={float(release):g}[duck];'
            '[vo][duck]amix=inputs=2:duration=first:normalize=0'
        )
        rc, err = _ffmpeg(
            ['-i', vo, '-i', bed, '-filter_complex', fc, '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s16le', out_path],
            log_fn=log_fn,
        )
        if not _ok_output(out_path, rc, err, log_fn, 'duck_mix'):
            return None
    log_fn(f'audio_mix: duck_mix ok -> {out_path}')
    return out_path


# ── scratch dir helper ────────────────────────────────────────────────────


def _scratch_dir():
    """Session scratch for temp files (falls back to system tmp)."""
    import tempfile

    base = os.environ.get('ZYG_SCRATCH', '').strip() or str(ZYG_TMP_DIR)
    try:
        os.makedirs(base, exist_ok=True)
        probe = tempfile.TemporaryFile(dir=base)
        probe.close()
        return base
    except OSError:
        return tempfile.gettempdir()
