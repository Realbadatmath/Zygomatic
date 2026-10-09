# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The op registry: one record per tool, and the four constructors that add one."""

from __future__ import annotations

from zyg_workflows import creature_fx as cfx

# ══════════════════════════════════════════════════════════════════════════════
#  THE REGISTRY
# ══════════════════════════════════════════════════════════════════════════════
# One record per tool: id, label, section, which bar family, tooltip, icon,
# parameter schema, class, and the function it compiles to. The page holds no
# tool list — all three bars are drawn from ops_payload().
#
# `bar` says which FAMILY a tool belongs to and NOTHING APPEARS IN BOTH:
#   'side'  the PICTURE — what is done to the pixels or asked of the model.
#   'dock'  the SESSION — the stack, the source, the render, the view, the
#           output.
# Where a family is DRAWN is the page's business, not this file's.
#
# `needs` is honesty about reach: 'comfy' greys a tool out when ComfyUI is not
# up, 'alpha' marks one that does nothing without a matte, 'svc:<mod>' one that
# depends on a service module being importable. Greyed and told why beats
# offered and silently dropped.

OPS = []
_SEEN = set()

_amt = cfx._amt
_pick = cfx._pick
colour_word = cfx.colour_word


def _op(id_, lb, sec, bar, tip, svg, params=(), cls='edit', fn=None, pfn=None, needs='', tog=False, neg='', svc=''):
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
            'cls': cls,
            'fn': fn,
            'pfn': pfn,
            'needs': needs,
            'tog': bool(tog),
            'neg': neg,
            'svc': svc,
            'act': cls == 'act',
        }
    )
    return OPS[-1]


def _pix(id_, lb, sec, tip, svg, params=(), pfn=None, needs=''):
    """Deterministic: Pillow, instant, and the preview IS the result."""
    return _op(id_, lb, sec, 'side', tip, svg, params, cls='pix', pfn=pfn, needs=needs)


def _svc(id_, lb, sec, tip, svg, params=(), svc='', needs=''):
    """A model that is not a diffusion edit. Runs in the render job only."""
    return _op(id_, lb, sec, 'side', tip, svg, params, cls='svc', svc=svc, needs=needs)


def _edit(id_, lb, sec, tip, svg, params=(), fn=None, needs='comfy', neg=''):
    """Generative: it contributes a clause to the Qwen-Image-Edit instruction."""
    return _op(id_, lb, sec, 'side', tip, svg, params, cls='edit', fn=fn, needs=needs, neg=neg)


def _act(id_, lb, sec, tip, svg, bar='dock', tog=False, needs=''):
    return _op(id_, lb, sec, bar, tip, svg, cls='act', tog=tog, needs=needs)


_ASPECTS = ['source', '1:1', '4:5', '2:3', '3:4', '5:4', '4:3', '3:2', '16:9', '9:16', '21:9']
