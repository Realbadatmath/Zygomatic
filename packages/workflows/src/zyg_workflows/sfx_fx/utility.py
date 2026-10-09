# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.utility — UTILITY blocks."""

from zyg_workflows.sfx_fx.helpers import _pick


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILITY
# ═══════════════════════════════════════════════════════════════════════════════
_CH_OPS = ['stereo', 'mono', 'swap', 'left', 'right', 'mid', 'side', 'invert_r', 'invert_all']
_CH_PAN = {
    'stereo': None,
    'mono': 'stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1',
    'swap': 'stereo|c0=c1|c1=c0',
    'left': 'stereo|c0=c0|c1=c0',
    'right': 'stereo|c0=c1|c1=c1',
    'mid': 'stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1',
    'side': 'stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0',
    'invert_r': 'stereo|c0=c0|c1=-1*c1',
    'invert_all': 'stereo|c0=-1*c0|c1=-1*c1',
}


def _b_channel(p, ctx):
    op = _pick(p, 'op', _CH_OPS)
    f = []
    spec = _CH_PAN.get(op)
    if spec:
        f.append('pan=' + spec)
    if abs(float(p['trim'])) > 0.01:
        f.append(f'volume={float(p["trim"]):.2f}dB')
    return f


def _b_gainstage(p, ctx):
    f = [f'volume={float(p["gain"]):.3f}dB']
    if p['invert']:
        f.append('pan=stereo|c0=-1*c0|c1=-1*c1')
    if p['mute']:
        f.append('volume=0')
    return f
