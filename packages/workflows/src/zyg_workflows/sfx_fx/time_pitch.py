# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.time_pitch — TIME & PITCH blocks, plus the Doppler render."""

import math
import subprocess
from zyg_workflows.bin import exe
from zyg_workflows.sfx_fx.helpers import _SR, _db, _ff, _pick


# ═══════════════════════════════════════════════════════════════════════════════
#  TIME & PITCH
# ═══════════════════════════════════════════════════════════════════════════════
def _b_pitchpro(p, ctx):
    st = float(p['semitones']) + float(p['cents']) / 100.0
    return [
        f'rubberband=pitch={2.0 ** (st / 12.0):.6f}'
        f':tempo={float(p["tempo"]):.5f}'
        f':formant={_pick(p, "formant", ["shifted", "preserved"])}'
        f':transients={_pick(p, "transients", ["crisp", "mixed", "smooth"])}'
        f':detector={_pick(p, "detector", ["compound", "percussive", "soft"])}'
        f':phase={_pick(p, "phase", ["laminar", "independent"])}'
        f':window={_pick(p, "window", ["standard", "short", "long"])}'
        f':smoothing={_pick(p, "smoothing", ["off", "on"])}'
        f':pitchq={_pick(p, "pitchq", ["quality", "speed", "consistency"])}'
        f':channels={_pick(p, "channels", ["apart", "together"])}'
    ]


def _d_pitchpro(p, d):
    t = max(0.01, float(p['tempo']))
    return d / t


def _b_stutter(p, ctx):
    n = int(p['repeats'])
    if n <= 0:
        return []
    size = max(64, int(float(p['slice_ms']) / 1000.0 * _SR))
    start = max(0, int(float(p['from_s']) * _SR))
    return [f'aloop=loop={n}:size={size}:start={start}']


def _d_stutter(p, d):
    return d + int(p['repeats']) * float(p['slice_ms']) / 1000.0


def _b_silence(p, ctx):
    f = []
    head = float(p['head_ms'])
    tail = float(p['tail_ms'])
    if head > 0.5:
        f.append(f'adelay=delays={head:.1f}:all=1')
    if tail > 0.5:
        f.append(f'apad=pad_dur={tail / 1000.0:.4f}')
    return f


def _d_silence(p, d):
    return d + (float(p['head_ms']) + float(p['tail_ms'])) / 1000.0


def _b_trimsil(p, ctx):
    f = []
    det = _pick(p, 'detection', ['rms', 'peak'])
    if p['head']:
        f.append(
            f'silenceremove=start_periods=1'
            f':start_threshold={_db(p["threshold"]):.6f}'
            f':start_duration={float(p["min_ms"]) / 1000.0:.4f}'
            f':start_silence={float(p["keep_ms"]) / 1000.0:.4f}'
            f':detection={det}'
        )
    if p['tail']:
        f.append(
            f'areverse,silenceremove=start_periods=1'
            f':start_threshold={_db(p["threshold"]):.6f}'
            f':start_duration={float(p["min_ms"]) / 1000.0:.4f}'
            f':start_silence={float(p["keep_ms"]) / 1000.0:.4f}'
            f':detection={det},areverse'
        )
    if p['inner']:
        f.append(
            f'silenceremove=stop_periods=-1'
            f':stop_threshold={_db(p["threshold"]):.6f}'
            f':stop_duration={max(0.05, float(p["inner_ms"]) / 1000.0):.4f}'
            f':stop_silence={float(p["keep_ms"]) / 1000.0:.4f}'
            f':detection={det}'
        )
    return f


_FADE_CURVES = [
    'tri',
    'qsin',
    'hsin',
    'esin',
    'log',
    'ipar',
    'qua',
    'cub',
    'squ',
    'cbr',
    'par',
    'exp',
    'iqsin',
    'ihsin',
    'dese',
    'desi',
    'losi',
    'sinc',
    'isinc',
    'nofade',
]


def _b_fadepro(p, ctx):
    f = []
    fi = float(p['fade_in']) / 1000.0
    fo = float(p['fade_out']) / 1000.0
    ci = _pick(p, 'curve_in', _FADE_CURVES)
    co = _pick(p, 'curve_out', _FADE_CURVES)
    if fi > 0.0005:
        f.append(f'afade=t=in:st={float(p["in_at"]) / 1000.0:.4f}:d={fi:.4f}:curve={ci}')
    if fo > 0.0005:
        f += ['areverse', f'afade=t=in:st=0:d={fo:.4f}:curve={co}', 'areverse']
    return f


_DITHERS = [
    'rectangular',
    'triangular',
    'triangular_hp',
    'lipshitz',
    'shibata',
    'low_shibata',
    'high_shibata',
    'f_weighted',
    'modified_e_weighted',
    'improved_e_weighted',
]


def _b_lofi(p, ctx):
    sr = int(p['rate'])
    d = _pick(p, 'dither', _DITHERS)
    f = []
    if sr < _SR - 1:
        f.append(f'aresample={sr}:dither_method={d}:filter_size={int(p["quality"])}')
        f.append(f'aresample={_SR}:dither_method={d}')
    bits = int(p['bits'])
    if bits < 32:
        f.append(f'acrusher=bits={bits}:mix=1:mode=lin:aa=0')
    return f


# ── render: Doppler ───────────────────────────────────────────────────────────
def _probe_dur(fp):
    try:
        r = subprocess.run(
            [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', fp],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float((r.stdout or '').strip().splitlines()[-1]) if r.returncode == 0 else 0.0
    except (ValueError, IndexError, OSError, subprocess.SubprocessError):
        return 0.0


def _r_doppler(p, src, dst):
    """A pass-by: pitch ramps from high to low across the sound, level swells
    to a peak at the closest point and the image sweeps left to right.

    The pitch ramp is CHUNKED — a varispeed per slice, concatenated. ffmpeg has
    no time-varying resampler, so this is the honest way to get one; 90 slices
    over the length keeps each step under a cent or two of jump."""
    d = _probe_dur(src)
    if d <= 0.02:
        raise ValueError('doppler: source too short to measure')
    n = max(8, min(120, int(d / 0.03)))
    st0 = float(p['from_st'])
    st1 = float(p['to_st'])
    curve = float(p['curve'])
    slice_d = d / n
    parts, labels = [], []
    for i in range(n):
        u = (i + 0.5) / n
        # `curve` shapes how abruptly the shift happens at the closest point:
        # 1 = linear sweep, higher = a flat approach then a fast flip past you
        w = 0.5 + 0.5 * math.copysign(abs(2 * u - 1) ** max(0.2, curve), 2 * u - 1)
        st = st0 + (st1 - st0) * w
        rate = int(round(_SR * (2.0 ** (st / 12.0))))
        lab = f'p{i}'
        parts.append(
            f'[0:a]atrim=start={i * slice_d:.6f}:end={(i + 1) * slice_d:.6f},'
            f'asetpts=PTS-STARTPTS,asetrate={rate},aresample={_SR}[{lab}]'
        )
        labels.append(f'[{lab}]')
    graph = ';'.join(parts) + ';' + ''.join(labels) + f'concat=n={n}:v=0:a=1[cc]'
    # the swell and the pan are continuous, so they run as expressions over the
    # concatenated result rather than per slice
    depth = float(p['swell_db'])
    width = max(0.05, float(p['pass_width']))
    amt = float(p['pan_sweep']) / 100.0
    g = f'pow(10\\,({depth:.3f}/20)*exp(-pow((t/{d:.6f}-0.5)/{width:.4f}\\,2)))'
    l = f'{g}*(0.5+0.5*(1-{amt:.4f}*(2*t/{d:.6f}-1)))'
    r = f'{g}*(0.5+0.5*(1+{amt:.4f}*(2*t/{d:.6f}-1)))'
    graph += f';[cc]aeval=exprs=val(0)*{l}|val(1)*{r}:c=same[out]'
    _ff(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-i',
            src,
            '-filter_complex',
            graph,
            '-map',
            '[out]',
            '-ar',
            str(_SR),
            '-ac',
            '2',
            '-c:a',
            'pcm_f32le',
            dst,
        ],
        'doppler',
    )
