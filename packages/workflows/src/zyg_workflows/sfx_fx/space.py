# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.space — SPACE blocks: reverb, delay, convolution, stereo field."""

import hashlib
import math
import os
import tempfile
from zyg_workflows.bin import exe
from zyg_workflows.sfx_fx.helpers import _SR, _db, _ff, _pick, _q


# ═══════════════════════════════════════════════════════════════════════════════
#  SPACE
# ═══════════════════════════════════════════════════════════════════════════════
def _b_reverb(p, ctx):
    """A tapped echo reverb: six taps spread over the room's size with a decay
    that follows the tail length, damped by a high cut. Cheap, and it does what
    a sound-design room is for. Convolution (fx_convolve) is the real one."""
    size = float(p['size_ms'])
    tail = max(0.05, float(p['decay_s']))
    wet = float(p['mix']) / 100.0
    if wet <= 0.001:
        return []
    pre = float(p['predelay_ms'])
    taps, gains = [], []
    for i in range(1, 7):
        t = pre + size * (i**0.82) * (0.55 + 0.11 * ((i * 7) % 5))
        if t > 90000:
            break
        taps.append(f'{t:.1f}')
        gains.append(f'{max(0.001, 0.7 * math.exp(-3.0 * (t / 1000.0) / tail)):.4f}')
    f = [f'aecho={max(0.0, 1.0 - wet * 0.35):.3f}:{wet:.3f}:{"|".join(taps)}:{"|".join(gains)}']
    if float(p['damp_hz']) < 19990:
        f.append(f'lowpass=f={float(p["damp_hz"]):.0f}')
    if float(p['lowcut_hz']) > 20.5:
        f.append(f'highpass=f={float(p["lowcut_hz"]):.0f}')
    if float(p['width']) > 0.5:
        f.append(
            f'stereowiden=delay=18:feedback=0.25:crossfeed=0.28:drymix={max(0.0, 1.0 - float(p["width"]) / 200.0):.3f}'
        )
    return f


def _b_delay(p, ctx):
    t = float(p['time_ms'])
    fb = float(p['feedback']) / 100.0
    wet = float(p['mix']) / 100.0
    if wet <= 0.001 or t < 1:
        return []
    taps, gains = [], []
    g = 1.0
    for i in range(1, int(p['taps']) + 1):
        g *= max(0.0, fb) if i > 1 else 1.0
        if g < 0.004:
            break
        taps.append(f'{t * i:.1f}')
        gains.append(f'{g:.4f}')
    f = [f'aecho={max(0.0, 1.0 - wet * 0.3):.3f}:{wet:.3f}:{"|".join(taps)}:{"|".join(gains)}']
    if float(p['tone_hz']) < 19990:
        f.append(f'lowpass=f={float(p["tone_hz"]):.0f}')
    return f


def _r_pingpong(p, src, dst):
    """Ping-pong: odd taps left, even taps right. Needs the two channels split
    and rejoined, which -af cannot express, so it is its own pass."""
    t = float(p['time_ms'])
    fb = max(0.0, min(0.95, float(p['feedback']) / 100.0))
    wet = max(0.0, min(1.0, float(p['mix']) / 100.0))
    n = int(p['taps'])
    lt, lg, rt, rg = [], [], [], []
    g = 1.0
    for i in range(1, n + 1):
        if i > 1:
            g *= fb
        if g < 0.004:
            break
        if i % 2:
            lt.append(f'{t * i:.1f}')
            lg.append(f'{g:.4f}')
        else:
            rt.append(f'{t * i:.1f}')
            rg.append(f'{g:.4f}')
    if not lt:
        lt, lg = [f'{t:.1f}'], ['0.5']
    if not rt:
        rt, rg = [f'{t * 2:.1f}'], ['0.25']
    dry = max(0.0, 1.0 - wet * 0.3)
    graph = (
        f'[0:a]channelsplit=channel_layout=stereo[l][r];'
        f'[l]aecho={dry:.3f}:{wet:.3f}:{"|".join(lt)}:{"|".join(lg)}[lo];'
        f'[r]aecho={dry:.3f}:{wet:.3f}:{"|".join(rt)}:{"|".join(rg)}[ro];'
        f'[lo][ro]join=inputs=2:channel_layout=stereo[out]'
    )
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
        'ping-pong',
    )


_IR_CHARS = ['room', 'hall', 'plate', 'chamber', 'spring', 'cave']


def _ir_path(p, work_dir):
    """Synthesise (and cache) the impulse response this slot asks for. Noise
    shaped by a decay curve and a character filter — no IR pack, so no IR
    pack's licence."""
    char = _pick(p, 'character', _IR_CHARS)
    tail = max(0.05, float(p['decay_s']))
    damp = float(p['damp_hz'])
    pre = float(p['predelay_ms'])
    key = hashlib.sha1(f'{char}|{tail:.3f}|{damp:.0f}|{pre:.1f}|v1'.encode(), usedforsecurity=False).hexdigest()[:20]
    d = os.path.join(work_dir, 'irs')
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f'{key}.wav')
    if os.path.isfile(out) and os.path.getsize(out) > 1024:
        return out
    colour = {'room': 'brown', 'hall': 'pink', 'plate': 'white', 'chamber': 'pink', 'spring': 'white', 'cave': 'brown'}[
        char
    ]
    af = [f'afade=t=out:st=0:d={tail:.3f}:curve=exp']
    if char == 'plate':
        af.append('highpass=f=380,lowpass=f=9000,aecho=1:1:7|11|17:0.6|0.45|0.3')
    elif char == 'spring':
        af.append('bandpass=f=1800:t=q:w=0.7,aphaser=speed=1.6:decay=0.6,aecho=1:1:23|41:0.7|0.5')
    elif char == 'cave':
        af.append('lowpass=f=2600,aecho=1:1:57|113|181:0.7|0.5|0.35')
    elif char == 'hall':
        af.append('lowpass=f=7200,highpass=f=90')
    elif char == 'chamber':
        af.append('bandpass=f=900:t=q:w=1.4')
    else:
        af.append('lowpass=f=6000,highpass=f=140')
    if damp < 19990:
        af.append(f'lowpass=f={damp:.0f}')
    af.append('adecorrelate=stages=5')
    if pre > 0.5:
        af.append(f'adelay=delays={pre:.1f}:all=1')
    af.append('aformat=sample_fmts=fltp:channel_layouts=stereo')
    tmp = out + '.tmp.wav'
    _ff(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-f',
            'lavfi',
            '-i',
            f'anoisesrc=d={tail + pre / 1000.0 + 0.05:.3f}:c={colour}:r={_SR}:a=0.9:s=7',
            '-af',
            'pan=stereo|c0=c0|c1=c0,' + ','.join(af),
            '-ar',
            str(_SR),
            '-ac',
            '2',
            '-c:a',
            'pcm_f32le',
            tmp,
        ],
        'ir build',
    )
    os.replace(tmp, out)
    return out


def _r_convolve(p, src, dst, work_dir=None):
    """MEASURED, not assumed: afir has no dry path. Its output is
    wet * conv(dry * x) — dry=1,wet=0 and dry=0,wet=1 both render silence, and
    the "35 % wet" that looked right was 35 % of a convolution nobody had
    levelled. So the dry signal is split off BEFORE the convolver and the two
    are mixed here, which also means the balance knob means what it says.

    gtype=gn (gain normalisation, 1/sum(ir)) is the only setting whose output
    tracks the input level across IR lengths; peak lands ~27 dB down and none
    clips. It still runs about 6 dB hot on a dense tail, hence the wet trim."""
    ir = _ir_path(p, work_dir or tempfile.gettempdir())
    wet = max(0.0, min(1.0, float(p['mix']) / 100.0))
    dry = 1.0 - wet
    trim = _db(p['wet_db'])
    graph = (
        '[0:a]asplit=2[d][w];'
        f'[w][1:a]afir=dry=1:wet=1'
        f':length={max(0.01, min(1.0, float(p["ir_length"]) / 100.0)):.4f}'
        f':gtype={_pick(p, "gain", ["none", "peak", "dc", "gn", "ac", "rms"])}'
        f':irgain=1:minp=1024:maxp=8192[c];'
        f'[c]volume={trim:.6f}[r];'
        f'[d][r]amix=inputs=2:weights={dry:.4f} {wet:.4f}:normalize=0[out]'
    )
    _ff(
        [
            exe('ffmpeg'),
            '-y',
            '-loglevel',
            'error',
            '-i',
            src,
            '-i',
            ir,
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
        'convolution',
    )


def _b_width(p, ctx):
    f = []
    mode = _pick(p, 'mode', ['widen', 'extra', 'both'])
    if mode in ('widen', 'both'):
        f.append(
            f'stereowiden=delay={float(p["delay_ms"]):.2f}'
            f':feedback={float(p["feedback"]) / 100.0:.4f}'
            f':crossfeed={float(p["crossfeed"]) / 100.0:.4f}'
            f':drymix={float(p["drymix"]) / 100.0:.4f}'
        )
    if mode in ('extra', 'both'):
        f.append(f'extrastereo=m={float(p["amount"]):.3f}:c={"true" if p["clip"] else "false"}')
    return f


_ST_MODES = ['lr>lr', 'lr>ms', 'ms>lr', 'lr>ll', 'lr>rr', 'lr>l+r', 'lr>rl', 'ms>ll', 'ms>rr', 'ms>rl', 'lr>l-r']


def _b_stereotools(p, ctx):
    return [
        f'stereotools=level_in={_db(p["level_in"]):.4f}:level_out=1'
        f':balance_in={float(p["balance_in"]) / 100.0:.4f}'
        f':balance_out={float(p["balance_out"]) / 100.0:.4f}'
        f':mode={_q(_pick(p, "mode", _ST_MODES))}'
        f':slev={max(0.0157, _db(p["side"])):.4f}'
        f':mlev={max(0.0157, _db(p["mid"])):.4f}'
        f':sbal={float(p["side_bal"]) / 100.0:.4f}'
        f':mpan={float(p["mid_pan"]) / 100.0:.4f}'
        f':base={float(p["base"]) / 100.0:.4f}'
        f':delay={float(p["delay_ms"]):.3f}'
        f':phase={float(p["phase"]):.1f}'
        f':mutel={"true" if p["mute_l"] else "false"}'
        f':muter={"true" if p["mute_r"] else "false"}'
        f':phasel={"true" if p["invert_l"] else "false"}'
        f':phaser={"true" if p["invert_r"] else "false"}'
        f':softclip={"true" if p["softclip"] else "false"}'
    ]


def _b_haas(p, ctx):
    return [
        f'haas=level_in={_db(p["level_in"]):.4f}:level_out=1'
        f':side_gain={_db(p["side_gain"]):.4f}'
        f':middle_source={_pick(p, "source", ["left", "right", "mid", "side"])}'
        f':left_delay={float(p["left_ms"]):.3f}:right_delay={float(p["right_ms"]):.3f}'
        f':left_balance={float(p["left_bal"]) / 100.0:.4f}'
        f':right_balance={float(p["right_bal"]) / 100.0:.4f}'
        f':middle_phase={"true" if p["mid_phase"] else "false"}'
        f':right_phase={"true" if p["right_phase"] else "false"}'
    ]


def _b_crossfeed(p, ctx):
    return [
        f'crossfeed=strength={float(p["strength"]) / 100.0:.4f}'
        f':range={float(p["range"]) / 100.0:.4f}'
        f':slope={max(0.01, float(p["slope"])):.4f}'
        f':level_in={float(p["level_in"]) / 100.0:.4f}:level_out=1'
    ]


def _b_decorrelate(p, ctx):
    return [f'adecorrelate=stages={int(p["stages"])}:seed={int(p["seed"])}']


def _b_compdelay(p, ctx):
    return [
        f'compensationdelay=cm={int(p["cm"])}:m={int(p["m"])}:mm={int(p["mm"])}'
        f':dry={float(p["dry"]) / 100.0:.4f}:wet={float(p["wet"]) / 100.0:.4f}'
        f':temp={int(p["temp"])}'
    ]


def _b_autopan(p, ctx):
    return [
        f'apulsator=level_in={_db(p["level_in"]):.4f}:level_out=1'
        f':mode={_pick(p, "shape", ["sine", "triangle", "square", "sawup", "sawdown"])}'
        f':amount={float(p["amount"]) / 100.0:.4f}'
        f':offset_l={float(p["offset_l"]) / 100.0:.4f}'
        f':offset_r={float(p["offset_r"]) / 100.0:.4f}'
        f':width={float(p["width"]):.3f}'
        f':timing={_pick(p, "timing", ["bpm", "ms", "hz"])}'
        f':bpm={float(p["bpm"]):.1f}:ms={int(p["ms"])}:hz={float(p["hz"]):.3f}'
    ]
