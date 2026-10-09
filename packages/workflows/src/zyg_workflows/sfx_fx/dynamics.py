# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.dynamics — LEVEL & DYNAMICS blocks, plus the two-pass Normalize/Loudness renders."""

from zyg_workflows.bin import exe
import logging as _zyg_logging
from zyg_workflows.sfx_fx.helpers import _SR, _db, _ff, _pick, _q

_zyg_log = _zyg_logging.getLogger('zyg_workflows.sfx_fx')


# ═══════════════════════════════════════════════════════════════════════════════
#  LEVEL & DYNAMICS
# ═══════════════════════════════════════════════════════════════════════════════
_NORM_MODES = ['peak', 'rms', 'truepeak']


def _b_compressor(p, ctx):
    f = [
        f'acompressor=level_in={_db(p["level_in"]):.4f}'
        f':threshold={max(0.000977, _db(p["threshold"])):.6f}'
        f':ratio={float(p["ratio"]):.2f}'
        f':attack={float(p["attack"]):.3f}:release={float(p["release"]):.2f}'
        f':makeup={max(1.0, _db(p["makeup"])):.4f}:knee={float(p["knee"]):.3f}'
        f':link={_pick(p, "link", ["average", "maximum"])}'
        f':detection={_pick(p, "detection", ["rms", "peak"])}'
        f':mode={_pick(p, "mode", ["downward", "upward"])}'
        f':mix={float(p["mix"]) / 100.0:.4f}'
    ]
    return f


def _b_limiter(p, ctx):
    return [
        f'alimiter=level_in={_db(p["level_in"]):.4f}:level_out=1'
        f':limit={max(0.0625, _db(p["ceiling"])):.6f}'
        f':attack={float(p["attack"]):.3f}:release={float(p["release"]):.2f}'
        f':level={"true" if p["autolevel"] else "false"}'
        f':asc={"true" if p["asc"] else "false"}'
    ]


def _b_gate(p, ctx):
    return [
        f'agate=level_in={_db(p["level_in"]):.4f}'
        f':threshold={max(0.0, min(1.0, _db(p["threshold"]))):.6f}'
        f':ratio={float(p["ratio"]):.2f}'
        f':range={max(0.0, min(1.0, _db(p["range"]))):.6f}'
        f':attack={float(p["attack"]):.3f}:release={float(p["release"]):.2f}'
        f':knee={float(p["knee"]):.3f}'
        f':detection={_pick(p, "detection", ["rms", "peak"])}'
        f':mode={_pick(p, "mode", ["downward", "upward"])}'
    ]


def _b_expander(p, ctx):
    """Downward expansion through compand's transfer curve: below the knee the
    curve is steeper than 1:1, so quiet material falls away instead of being
    lifted the way a compressor lifts it."""
    th = float(p['threshold'])
    ratio = max(1.0, float(p['ratio']))
    low = -90.0
    out_low = th + (low - th) * ratio
    pts = f'{low:.1f}/{max(-900.0, out_low):.1f}|{th:.1f}/{th:.1f}|0/0'
    return [
        f'compand=attacks={float(p["attack"]) / 1000.0:.4f}'
        f':decays={float(p["release"]) / 1000.0:.4f}'
        f':points={_q(pts)}:gain={float(p["makeup"]):.2f}:soft-knee=6'
    ]


def _b_punch(p, ctx):
    """Transient shaper. Attack is a fast-attack expander over the top of the
    range (peaks get through before the envelope reacts); sustain is a slow
    compander tilt over the body."""
    a = float(p['attack_db'])
    s = float(p['sustain_db'])
    out = []
    if abs(a) > 0.05:
        pts = f'-90/-90|-40/{-40 + a * 0.35:.2f}|-12/{-12 + a:.2f}|0/{min(0.0, a * 0.2):.2f}'
        out.append(f'compand=attacks=0:decays={float(p["recover"]) / 1000.0:.4f}:points={_q(pts)}:soft-knee=3')
    if abs(s) > 0.05:
        pts = f'-90/{-90 + s * 0.2:.2f}|-45/{-45 + s:.2f}|-20/{-20 + s * 0.6:.2f}|0/0'
        out.append(
            f'compand=attacks={float(p["hold"]) / 1000.0:.4f}'
            f':decays={max(0.05, float(p["recover"]) / 1000.0 * 3):.4f}'
            f':points={_q(pts)}:soft-knee=6'
        )
    if abs(float(p['trim'])) > 0.01:
        out.append(f'volume={float(p["trim"]):.2f}dB')
    return out


def _b_deesser(p, ctx):
    return [
        f'deesser=i={float(p["intensity"]) / 100.0:.4f}'
        f':m={float(p["maxdeess"]) / 100.0:.4f}'
        f':f={float(p["freq"]) / 100.0:.4f}'
        f':s={_pick(p, "out", ["i", "o", "e"])}'
    ]


def _b_autolevel(p, ctx):
    return [
        f'dynaudnorm=f={int(p["frame"])}:g={int(p["gauss"]) | 1}'
        f':p={float(p["peak"]) / 100.0:.4f}:m={float(p["maxgain"]):.2f}'
        f':r={float(p["targetrms"]) / 100.0:.4f}'
        f':s={float(p["compress"]):.2f}'
        f':n={"true" if p["couple"] else "false"}'
        f':c={"true" if p["dc"] else "false"}'
    ]


def _b_speechnorm(p, ctx):
    return [
        f'speechnorm=p={float(p["peak"]) / 100.0:.4f}'
        f':e={float(p["expansion"]):.2f}:c={float(p["compression"]):.2f}'
        f':t={float(p["threshold"]) / 100.0:.4f}'
        f':r={float(p["raise"]):.4f}:f={float(p["fall"]):.4f}'
        f':l={"true" if p["link"] else "false"}'
    ]


_SOFTCLIP = ['hard', 'tanh', 'atan', 'cubic', 'exp', 'alg', 'quintic', 'sin', 'erf']


def _b_softclip(p, ctx):
    return [
        f'volume={float(p["drive"]):.2f}dB',
        f'asoftclip=type={_pick(p, "type", _SOFTCLIP)}'
        f':threshold={max(1e-6, _db(p["threshold"])):.6f}'
        f':output={max(1e-6, _db(p["output"])):.6f}'
        f':param={float(p["param"]):.3f}:oversample={int(p["oversample"])}',
    ]


def _b_psyclip(p, ctx):
    return [
        f'apsyclip=level_in={_db(p["level_in"]):.4f}:level_out=1'
        f':clip={max(0.0157, _db(p["clip"])):.6f}'
        f':adaptive={float(p["adaptive"]) / 100.0:.4f}'
        f':iterations={int(p["iterations"])}'
        f':level={"true" if p["autolevel"] else "false"}'
        f':diff={"true" if p["listen"] else "false"}'
    ]


def _b_bitcrush(p, ctx):
    return [
        f'acrusher=level_in={_db(p["level_in"]):.4f}:level_out=1'
        f':bits={float(p["bits"]):.3f}:samples={float(p["samples"]):.2f}'
        f':mix={float(p["mix"]) / 100.0:.4f}'
        f':mode={_pick(p, "mode", ["lin", "log"])}'
        f':dc={float(p["dc"]):.3f}:aa={float(p["aa"]) / 100.0:.4f}'
        f':lfo={"true" if p["lfo"] else "false"}'
        f':lforange={float(p["lforange"]):.2f}:lforate={float(p["lforate"]):.3f}'
    ]


def _b_exciter(p, ctx):
    return [
        f'aexciter=level_in={_db(p["level_in"]):.4f}:level_out=1'
        f':amount={float(p["amount"]):.3f}:drive={float(p["drive"]):.3f}'
        f':blend={float(p["blend"]):.2f}:freq={float(p["freq"]):.0f}'
        f':ceil={float(p["ceil"]):.0f}'
        f':listen={"true" if p["listen"] else "false"}'
    ]


def _b_contrast(p, ctx):
    return [f'acontrast=contrast={float(p["contrast"]):.2f}']


def _b_dcshift(p, ctx):
    return [f'dcshift=shift={float(p["shift"]):.4f}:limitergain={float(p["limitergain"]):.4f}']


# ── two-pass: Normalize ───────────────────────────────────────────────────────
def _measure(src, mode):
    """(peak dBFS, rms dBFS, true-peak dBFS) for one file."""
    err = _ff(
        [
            exe('ffmpeg'),
            '-hide_banner',
            '-nostats',
            '-i',
            src,
            '-af',
            'volumedetect,ebur128=peak=true:framelog=quiet',
            '-f',
            'null',
            '-',
        ],
        'measure',
    )
    peak = rms = tp = None
    for line in err.splitlines():
        s = line.strip()
        if 'max_volume:' in s:
            try:
                peak = float(s.split('max_volume:')[1].split('dB')[0])
            except ValueError as _exc:
                _zyg_log.debug('max_volume unparsable from %r: %s', s, _exc)
        elif 'mean_volume:' in s:
            try:
                rms = float(s.split('mean_volume:')[1].split('dB')[0])
            except ValueError as _exc:
                _zyg_log.debug('mean_volume unparsable from %r: %s', s, _exc)
        elif 'Peak:' in s and tp is None:
            try:
                tp = float(s.split('Peak:')[1].split('dBFS')[0])
            except (ValueError, IndexError) as _exc:
                _zyg_log.debug('true peak unparsable from %r: %s', s, _exc)
    return peak, rms, tp


def _r_normalize(p, src, dst):
    mode = _pick(p, 'mode', _NORM_MODES)
    peak, rms, tp = _measure(src, mode)
    cur = {'peak': peak, 'rms': rms, 'truepeak': tp}.get(mode)
    if cur is None:
        cur = peak if peak is not None else 0.0
    gain = float(p['target']) - float(cur)
    gain = max(-60.0, min(float(p['maxgain']), gain))
    af = [f'volume={gain:.3f}dB']
    if p['ceiling_on']:
        af.append(f'alimiter=limit={_db(p["ceiling"]):.6f}:level=false')
    _ff(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-i',
            src,
            '-af',
            ','.join(af),
            '-ar',
            str(_SR),
            '-ac',
            '2',
            '-c:a',
            'pcm_f32le',
            dst,
        ],
        'normalize',
    )


def _r_loudness(p, src, dst):
    """A real two-pass loudnorm. One-pass loudnorm is a dynamic AGC that moves
    while it plays; measuring first and feeding the numbers back is what makes
    it the linear gain change the knob claims to be."""
    import json as _json

    target_i = float(p['lufs'])
    target_tp = float(p['truepeak'])
    target_lra = float(p['lra'])
    base = f'loudnorm=I={target_i:.2f}:TP={target_tp:.2f}:LRA={target_lra:.2f}'
    err = _ff(
        [exe('ffmpeg'), '-hide_banner', '-nostats', '-i', src, '-af', base + ':print_format=json', '-f', 'null', '-'],
        'loudness measure',
    )
    m = {}
    try:
        blob = err[err.rindex('{') : err.rindex('}') + 1]
        m = _json.loads(blob)
    except (ValueError, IndexError):
        m = {}
    if m.get('input_i'):
        af = (
            base + f':measured_I={m["input_i"]}:measured_TP={m["input_tp"]}'
            f':measured_LRA={m["input_lra"]}:measured_thresh={m["input_thresh"]}'
            f':offset={m.get("target_offset", "0.0")}:linear={"true" if p["linear"] else "false"}'
        )
    else:
        af = base  # degrade to one pass, never fail the render
    _ff(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-i',
            src,
            '-af',
            af,
            '-ar',
            str(_SR),
            '-ac',
            '2',
            '-c:a',
            'pcm_f32le',
            dst,
        ],
        'loudness',
    )
