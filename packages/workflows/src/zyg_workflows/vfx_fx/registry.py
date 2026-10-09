# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Parameter schema helpers and the op registry (vfx_fx.py lines 77-172)."""

from __future__ import annotations

import re


# ── parameter schema helpers ────────────────────────────────────────────────
def f(k, lb, df, mn, mx, st=0.01, tip=''):
    return {'k': k, 'lb': lb, 't': 'f', 'df': df, 'mn': mn, 'mx': mx, 'st': st, 'tip': tip}


def i(k, lb, df, mn, mx, st=1, tip=''):
    return {'k': k, 'lb': lb, 't': 'i', 'df': df, 'mn': mn, 'mx': mx, 'st': st, 'tip': tip}


def b(k, lb, df=False, tip=''):
    return {'k': k, 'lb': lb, 't': 'b', 'df': bool(df), 'tip': tip}


def e(k, lb, df, opts, tip=''):
    return {'k': k, 'lb': lb, 't': 'e', 'df': df, 'opts': list(opts), 'tip': tip}


def c(k, lb, df='#00ff00', tip=''):
    return {'k': k, 'lb': lb, 't': 'c', 'df': df, 'tip': tip}


def s(k, lb, df='', tip='', pat=r'[-+0-9a-zA-Z_./ ]{0,200}'):
    """A free-text parameter. `pat` is the FULL-match charset it is held to --
    a curves point list and a convolution matrix are both strings that go
    straight into a filtergraph, so each declares exactly what it may contain
    and anything else is refused rather than escaped and hoped for."""
    return {'k': k, 'lb': lb, 't': 's', 'df': df, 'tip': tip, 'pat': pat}


# ── the registry ────────────────────────────────────────────────────────────
# An op is one icon in the rail, one card in the stack, and one fragment in the
# filtergraph.  `fn(p, ctx) -> str` gets VALIDATED parameters and the source's
# facts; it returns either a plain filter chain (wrapped into the linear graph
# for it) or, if it needs to branch, a whole fragment written between the
# literal labels [IN] and [OUT].
#
# `bar` says which of the two bars the icon lives on and nothing appears on
# both -- the same picture in two places is two things to keep in step and, on
# screen, just reads as a duplicate (the ruling the Architecture Studio's rail
# already settled).  `side` is the LOOK kit, the things that change pixels;
# `dock` is the SESSION -- stack order, view, output, file.
#
# `kinds` is honesty about what an op can touch: `v` is video-only, and every
# time op is video-only because a still has no neighbouring frame to blend,
# retime or reverse.  The rail greys those out on a sprite rather than
# offering a button that would compile to nothing.
OPS = []
_SEEN = set()


def _op(id_, lb, sec, bar, tip, svg, params=(), kinds='iv', fn=None, stub=False):
    if id_ in _SEEN:
        raise ValueError(f'duplicate op id {id_}')
    _SEEN.add(id_)
    OPS.append(
        {
            'id': id_,
            'lb': lb,
            'sec': sec,
            'bar': bar,
            'tip': tip,
            'svg': svg,
            'params': list(params),
            'kinds': kinds,
            'fn': fn,
            'stub': bool(stub),
        }
    )


def hexc(v, default='#000000'):
    v = str(v or default)
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', v):
        v = default
    return '0x' + v[1:]


def _n(v):
    """Format a number for a filtergraph without an exponent or a trailing .0."""
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, int):
        return str(v)
    t = f'{float(v):.6f}'.rstrip('0').rstrip('.')
    return t or '0'


def _q(expr):
    r"""Quote a filter VALUE that contains commas or spaces.

    A filtergraph is comma-separated at the top level, so a geq expression with
    a comma in it silently becomes two filters -- and the second one is a parse
    error naming a filter that does not exist, which reads as a broken build
    rather than a quoting bug.  Single quotes are the parser's own escape."""
    return "'" + str(expr).replace('\\', r'\\').replace("'", r'\'') + "'"
