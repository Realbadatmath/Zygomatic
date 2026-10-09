# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The REPAIR section of the rail (vfx_fx.py lines 2948-3056)."""

from __future__ import annotations


from zyg_workflows.vfx_fx.registry import (
    i,
    b,
    e,
    s,
    _op,
    _q,
)

# ── REPAIR ──────────────────────────────────────────────────────────────────
# Added after MEASURING the library rather than by analogy with other tools.
# `ffmpeg -vf idet` over 218 frames of the DOE plates reports TFF on 215 of
# them: the nuclear-test films are top-field-first interlaced film transfers,
# so a deinterlace is not a hypothetical option here, it is a step the library
# actually needs and did not have.  Every op below is video-only for the
# obvious reason.

_op(
    'deint',
    'Deinterlace',
    'Time',
    'side',
    'Deinterlace. The DOE plates measure top-field-first on 215 of 218 frames, so '
    'they comb on any motion until this runs. "Every frame" is ON by default and '
    'has to be: the working copies carry interlaced_frame=0 on every frame even '
    'though they visibly comb, so the usual only-flagged-frames mode skips all of '
    'them and the filter does nothing at all. Measured — with it on, idet goes '
    'from 0/218 progressive to 184/200. bwdif is the good default; estdif is '
    'slower and kinder to diagonals; field rate gives 59.94 from 29.97.',
    '<path d="M3.4 5.6h17.2M3.4 9.4h17.2M3.4 13.2h17.2M3.4 17h17.2M3.4 20.4h17.2" opacity=".45"/>'
    '<path d="M3.4 5.6h17.2M3.4 13.2h17.2"/>',
    [
        e('alg', 'Algorithm', 'bwdif', ['bwdif', 'yadif', 'estdif']),
        e('mode', 'Rate', 'frame', ['frame', 'field']),
        e('parity', 'Field order', 'auto', ['auto', 'tff', 'bff']),
        b(
            'deint_all',
            'Every frame',
            True,
            'off = only frames the CONTAINER flags — which, in this library, is none of them',
        ),
    ],
    kinds='v',
    fn=lambda p, x: (
        f'estdif=mode={"field" if p["mode"] == "field" else "frame"}:'
        f'parity={p["parity"]}:deint={"all" if p["deint_all"] else "interlaced"}'
        if p['alg'] == 'estdif'
        else f'{p["alg"]}=mode='
        + ('send_field' if p['mode'] == 'field' else 'send_frame')
        + f':parity={p["parity"]}:deint={"all" if p["deint_all"] else "interlaced"}'
    ),
)

_op(
    'detelecine',
    'Detelecine',
    'Time',
    'side',
    'Undo a 3:2 pulldown — the cadence that put 24 fps film onto 29.97 fps tape, '
    'which is exactly what these archive transfers are. Without it, one frame in '
    'five is a blend of two different film frames, and every retime and every '
    'optical-flow pass downstream inherits it.',
    '<rect x="2.6" y="7" width="4" height="10"/><rect x="7.6" y="7" width="4" height="10"/>'
    '<rect x="12.6" y="7" width="4" height="10" opacity=".4" stroke-dasharray="2 1.8"/>'
    '<rect x="17.6" y="7" width="4" height="10"/>',
    [
        e('alg', 'Method', 'pullup', ['pullup', 'detelecine', 'fieldmatch']),
        s('pattern', 'Pattern', '23', 'for detelecine — 23 is standard 3:2', pat=r'[0-9puc]{0,12}'),
    ],
    kinds='v',
    fn=lambda p, x: (
        'pullup,dejudder'
        if p['alg'] == 'pullup'
        else 'fieldmatch,decimate'
        if p['alg'] == 'fieldmatch'
        else f'detelecine=pattern={_q(p["pattern"] or "23")}'
    ),
)

_op(
    'stabilize',
    'Stabilize',
    'Transform',
    'side',
    'Take the shake out — a single-pass estimate that shifts and rotates each '
    'frame towards the last. It crops in to hide the edges it uncovers, so it '
    'costs you a little of the frame; on a hand-held archive plate that is a '
    'trade worth making.',
    '<rect x="6.4" y="6.4" width="11.2" height="11.2" rx="1.2"/>'
    '<rect x="3.4" y="3.4" width="11.2" height="11.2" rx="1.2" opacity=".35" stroke-dasharray="2.4 2"/>'
    '<path d="M18.4 19.6l2.2 1M19.6 18.4l1 2.2" opacity=".6"/>',
    [
        i('rx', 'Search X', 16, 0, 64, 16, 'must be a multiple of 16'),
        i('ry', 'Search Y', 16, 0, 64, 16, 'must be a multiple of 16'),
        e('edge', 'Fill edges', 'clamp', ['clamp', 'mirror', 'blank', 'original']),
        i('blocksize', 'Block size', 8, 4, 128, 4),
        i(
            'contrast',
            'Contrast floor',
            125,
            1,
            255,
            1,
            'blocks flatter than this are ignored — raise it on a noisy plate',
        ),
    ],
    kinds='v',
    # deshake REFUSES an rx or ry that is not a multiple of 16, and its own
    # option help does not say so (it advertises "from 0 to 64").  The slider
    # steps by 16 and the value is rounded here as well, because a schema is
    # not a guarantee about what some other caller will send.
    fn=lambda p, x: (
        f'deshake=rx={16 * round(int(p["rx"]) / 16)}:'
        f'ry={16 * round(int(p["ry"]) / 16)}:edge={p["edge"]}:'
        f'blocksize={int(p["blocksize"])}:contrast={int(p["contrast"])}'
    ),
)
