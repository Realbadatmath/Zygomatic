# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The TIME section of the rail (vfx_fx.py lines 2165-2378)."""

from __future__ import annotations


from zyg_workflows.vfx_fx.registry import (
    f,
    i,
    b,
    e,
    _op,
    _n,
    _q,
)

# ── TIME ────────────────────────────────────────────────────────────────────
# Every op here is video-only and says so, because a still has no neighbouring
# frame to blend, retime or reverse.  The rail greys them out on a sprite
# instead of offering a button that compiles to nothing -- a control that does
# nothing when pressed is worse than a control that is visibly unavailable.
#
# They also all break the single-frame preview, and the pane says so: seeking
# to t and applying `reverse` shows you the frame at t of a clip that has not
# been reversed yet, because reverse needs the whole clip in hand.  The BAKE is
# correct; the preview of a time op is a still of the source.

_op(
    'speed',
    'Retime',
    'Time',
    'side',
    'Speed — change the playback rate by rescaling the timestamps. Under 1 is '
    'slow motion by holding frames, which judders; pair it with Optical flow to '
    'make the in-between frames instead of repeating them.',
    '<circle cx="12" cy="12" r="8.6"/><path d="M12 6.8V12l3.6 2.4"/>'
    '<path d="M18.6 5.4l2.4-2.4M21 3v3.2h-3.2" opacity=".6"/>',
    [f('rate', 'Rate', 1, 0.05, 20, 0.01, '2 = twice as fast'), b('keepfps', 'Keep frame rate', True)],
    kinds='v',
    fn=lambda p, x: f'setpts=PTS/{_n(p["rate"])}' + (f',fps={_n(x["fps"])}' if p['keepfps'] else ''),
)

_op(
    'tmix',
    'Frame blend',
    'Time',
    'side',
    'Average N neighbouring frames into each output frame — shutter-angle motion '
    'blur after the fact. Three to five frames on a fast element is the cheapest '
    'convincing motion blur there is.',
    '<rect x="3" y="7" width="8" height="10" opacity=".35"/><rect x="7" y="7" width="8" height="10" opacity=".6"/>'
    '<rect x="11" y="7" width="8" height="10"/>',
    [i('frames', 'Frames', 3, 1, 128)],
    kinds='v',
    fn=lambda p, x: f'tmix=frames={int(p["frames"])}:planes=15',
)

_op(
    'oflow',
    'Optical flow retime',
    'Time',
    'side',
    'Motion-compensated interpolation — invent the in-between frames by tracking '
    'where the pixels went, instead of repeating the last one. The good slow '
    'motion, and slow to compute. It tears on fast, low-contrast smoke, which is '
    'much of this library, so check it before you trust it.',
    '<path d="M3.4 17.4c4-1 5.6-9.4 9-9.4s4 5 8.2 3.4"/><path d="M17.4 10l3.2 1.4-1 3.2" opacity=".7"/>'
    '<circle cx="3.4" cy="17.4" r="1.5"/>',
    [
        f('fps', 'Target fps', 60, 1, 240, 0.1),
        e('mi_mode', 'Mode', 'mci', ['mci', 'blend', 'dup']),
        e('mc_mode', 'Compensation', 'aobmc', ['obmc', 'aobmc']),
        e('me_mode', 'Estimation', 'bidir', ['bidir', 'bilat']),
        b('vsbmc', 'Variable-size blocks', True),
    ],
    kinds='v',
    fn=lambda p, x: (
        f'minterpolate=fps={_n(p["fps"])}:mi_mode={p["mi_mode"]}:'
        f'mc_mode={p["mc_mode"]}:me_mode={p["me_mode"]}:'
        f'vsbmc={1 if p["vsbmc"] else 0}'
    ),
)

_op(
    'trim',
    'Trim',
    'Time',
    'side',
    'Cut in and out points, in seconds, and restamp from zero. Most stock plates '
    'carry a lead-in and a tail you will never use — trimming them here means '
    'everything after this in the stack only has to process what you kept.',
    '<circle cx="6.6" cy="6.6" r="2.6"/><circle cx="6.6" cy="17.4" r="2.6"/>'
    '<path d="M8.8 8.4L20.4 17.4M8.8 15.6L20.4 6.6"/>',
    [
        f('start', 'In', 0, 0, 86400, 0.01, 'seconds'),
        f('end', 'Out', 0, 0, 86400, 0.01, 'seconds — 0 means to the end'),
    ],
    kinds='v',
    fn=lambda p, x: (
        f'trim=start={_n(p["start"])}'
        + (f':end={_n(p["end"])}' if p['end'] > p['start'] else '')
        + ',setpts=PTS-STARTPTS'
    ),
)

_op(
    'loopop',
    'Loop',
    'Time',
    'side',
    'Repeat the clip N more times. A one-shot bed looped is the mistake the audio '
    'side already made once — a fire that restarts visibly is worse than a short '
    'fire, so look at the seam before you ship the loop.',
    '<path d="M4.4 9.4A6 6 0 0110.4 4h4.8a6 6 0 010 12h-8"/><path d="M9.6 12.6L6.6 16l3 3.4"/>',
    [i('loop', 'Extra loops', 1, 0, 200), i('size', 'Frames', 0, 0, 100000, 1, '0 = the whole clip')],
    kinds='v',
    fn=lambda p, x: (
        f'loop=loop={int(p["loop"])}:size={int(p["size"]) or max(1, int(round(x["dur"] * x["fps"])))}:start=0'
    ),
)

_op(
    'reverse',
    'Reverse',
    'Time',
    'side',
    'Play it backwards. Buffers the WHOLE clip in memory to do it, which is fine '
    'on a two-second element and is not fine on a twenty-five-minute plate — trim '
    'first, always.',
    '<path d="M20.6 12H5"/><path d="M9.4 6.6L4 12l5.4 5.4"/>',
    kinds='v',
    fn=lambda p, x: 'reverse',
)

_op(
    'pingpong',
    'Ping-pong',
    'Time',
    'side',
    'Forwards then backwards, concatenated. The one loop that CANNOT show a seam, '
    'because both joins meet the same frame — which is why it is the standard way '
    'to make a short element usable as a long one.',
    '<path d="M4.4 8.4h15.2M19.6 8.4l-3.4-3M4.4 15.6h15.2M4.4 15.6l3.4-3" stroke-linejoin="round"/>',
    kinds='v',
    fn=lambda p, x: '[IN]split[$a][$b];[$b]reverse[$r];[$a][$r]concat=n=2:v=1:a=0,format=rgba[OUT]',
)

_op(
    'freeze',
    'Freeze frame',
    'Time',
    'side',
    'Hold one frame for a length of time. The tail of an explosion held and faded '
    'is a different beat from one that just stops.',
    '<rect x="3.4" y="4.4" width="17.2" height="15.2" rx="1.4"/><path d="M8.6 9.4v5.2M12 9.4v5.2M15.4 9.4v5.2"/>',
    [i('frame', 'Frame', 0, 0, 1000000), f('hold', 'Hold', 1, 0.04, 60, 0.04, 'seconds')],
    kinds='v',
    fn=lambda p, x: (
        f'select={_q("eq(n," + str(int(p["frame"])) + ")")},'
        f'loop=loop={max(0, int(round(p["hold"] * x["fps"])) - 1)}:size=1:start=0,'
        f'setpts=N/{_n(x["fps"])}/TB'
    ),
)

_op(
    'echo',
    'Motion trail',
    'Time',
    'side',
    'Trails — each pixel decays towards the next frame instead of cutting to it, '
    'so a bright element smears a tail behind itself. Only bright values persist, '
    'which is why it reads as a light trail and not as a ghost of the whole frame.',
    '<circle cx="18" cy="12" r="3"/><circle cx="12.6" cy="12" r="2.4" opacity=".55"/>'
    '<circle cx="7.8" cy="12" r="1.8" opacity=".3"/>',
    [f('decay', 'Decay', 0.95, 0, 1, 0.002)],
    kinds='v',
    fn=lambda p, x: f'lagfun=decay={_n(p["decay"])}:planes=15',
)

_op(
    'stutter',
    'Stutter',
    'Time',
    'side',
    'Drop the temporal resolution and hold each surviving frame — the "shot on '
    'twos" look, and stop-motion. It changes nothing about the duration, only how '
    'many distinct pictures are inside it.',
    '<path d="M4 12h3.2M10.4 12h3.2M16.8 12h3.2"/><path d="M4 6.4h3.2M10.4 6.4h3.2M16.8 6.4h3.2" opacity=".45"/>'
    '<path d="M4 17.6h3.2M10.4 17.6h3.2M16.8 17.6h3.2" opacity=".45"/>',
    [f('fps', 'Distinct fps', 12, 0.5, 60, 0.5)],
    kinds='v',
    fn=lambda p, x: f'fps={_n(p["fps"])},fps={_n(x["fps"])}',
)

_op(
    'conform',
    'Frame rate',
    'Time',
    'side',
    'Conform to a frame rate by dropping or duplicating frames. The pack fps are '
    '29.97, 45 and 24 depending on which vendor made them — assuming 30 is how an '
    'effect ends up running at the wrong speed in a finished shot.',
    '<rect x="3.4" y="5.4" width="17.2" height="13.2" rx="1.4"/>'
    '<path d="M3.4 8.6h17.2M3.4 15.4h17.2"/><path d="M12 8.6v6.8"/>',
    [f('fps', 'Frame rate', 24, 1, 240, 0.001)],
    kinds='v',
    fn=lambda p, x: f'fps=fps={_n(p["fps"])}',
)

_op(
    'fade',
    'Fade',
    'Time',
    'side',
    'Fade in or out, on the picture or on the MATTE. Fading alpha is the one you '
    'want for an element: it dissolves out of the shot instead of turning into a '
    'black rectangle that dissolves.',
    '<rect x="3.4" y="5.4" width="17.2" height="13.2" rx="1.4"/>'
    '<path d="M20.6 5.4v13.2H3.4z" fill="currentColor" stroke="none" opacity=".2"/>',
    [
        e('t', 'Direction', 'in', ['in', 'out']),
        f('st', 'Start', 0, 0, 86400, 0.01, 'seconds'),
        f('d', 'Length', 0.5, 0.01, 60, 0.01, 'seconds'),
        b('alpha', 'Fade the matte', True),
    ],
    kinds='v',
    fn=lambda p, x: f'format=rgba,fade=t={p["t"]}:st={_n(p["st"])}:d={_n(p["d"])}:alpha={1 if p["alpha"] else 0}',
)
