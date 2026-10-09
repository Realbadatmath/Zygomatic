# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE ENGINE / validation and the compiler: one stack becomes pixel-pre, one instruction, pixel-post.

Moved verbatim out of the old single-file creature_fx.py (lines 4819-4996).
"""

from __future__ import annotations

import re

from zyg_workflows.creature_fx.ops_dock import OP_BY_ID


# ── validation ──────────────────────────────────────────────────────────────
def validate(op_id, raw):
    """Coerce and clamp one op's parameters against its own schema.

    An out-of-schema KEY is dropped rather than passed through. Numbers are
    forced into their declared range, enums must be members, colours must match
    #rrggbb, and free text must match its declared charset. Text from here ends
    up in a prompt, a caption file and a JSON sidecar; none of those is a place
    to discover that a value was never checked."""
    o = OP_BY_ID.get(op_id)
    if not o:
        raise ValueError(f'unknown op: {op_id}')
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for spec in o['params']:
        k, t, df = spec['k'], spec['t'], spec['df']
        v = raw.get(k, df)
        if t in ('f', 'i'):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = float(df)
            if v != v or v in (float('inf'), float('-inf')):
                v = float(df)
            v = max(float(spec['mn']), min(float(spec['mx']), v))
            out[k] = int(round(v)) if t == 'i' else v
        elif t == 'b':
            out[k] = bool(v) if isinstance(v, bool) else str(v).lower() in ('1', 'true', 'yes', 'on')
        elif t == 'e':
            out[k] = v if v in spec['opts'] else df
        elif t == 'c':
            v = str(v or df)
            out[k] = v if re.fullmatch(r'#[0-9a-fA-F]{6}', v) else df
        else:
            v = '' if v is None else str(v).strip()
            out[k] = v if re.fullmatch(spec.get('pat', r'.{0,300}'), v) else df
    return out


def normalise_stack(stack):
    """Clean a whole stack: drop unknown or action ops, validate every parameter.

    Returns ([{op,on,p}], dropped). A silent drop reads as "your stack ran" when
    part of it did not, so what went and why comes back with it."""
    out, dropped = [], []
    for row in stack or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get('op') or '')
        o = OP_BY_ID.get(oid)
        if not o or o['cls'] == 'act':
            dropped.append({'op': oid, 'why': 'no such tool'})
            continue
        out.append({'op': oid, 'on': row.get('on', True) is not False, 'p': validate(oid, row.get('p'))})
    return out, dropped


# ── the compiler ────────────────────────────────────────────────────────────
# The stack compiles into THREE things, and the split is the whole design:
#
#   pre   -- pixel ops ABOVE the first generative op: they change the source
#            the model is handed.
#   instr -- every generative op's clause, in order, joined into one Qwen edit
#            instruction, with the creature's own keep-sentence and body plan
#            spliced in exactly the way creature_sheet_service splices them.
#   post  -- pixel ops BELOW the last generative op: they change the result.
#
# With no generative ops the whole stack is `pre` and the bake is instant and
# exact. That is not a degraded mode -- it is the deterministic half of the
# toolbox working on its own, and it needs no GPU at all.

_KEEP_BASE = 'Same creature, same colours and proportions. One creature only, no people, no text.'
_NEG_BASE = (
    'text, watermark, signature, multiple creatures, human, person, '
    'extra limbs, deformed anatomy, blurry, letterbox bars'
)


# Which sections a keep-clause CANNOT survive. The sheet pipeline's keep
# sentence is unconditional and correct there, because every edit it makes is a
# camera move: nothing about the creature is supposed to change. Here the whole
# point is changing it, and an instruction that says "make the creature
# turquoise. Same creature, same colours" is a prompt arguing with itself --
# which does not fail loudly, it just returns the average of the two.
_KEEP_DROPS = {
    'colour': {'Colour'},
    'proportion': {'Form'},
    'anatomy': {'Form', 'Appendages', 'Face'},
    'style': {'Style'},
}


def keep_sentence(body_plan='', changing=()):
    """The 'do not change the rest' clause, minus whatever the stack is changing.

    Mirrors creature_sheet_service.keep_sentence -- prompts steer and pixels
    guarantee, and the sentence is what keeps the KIND of appendage stable
    across an edit that was about something else. The difference is that a
    STUDIO stack may be about exactly that, so each half of the clause is
    dropped when an op in the stack contradicts it, and the receipt says which
    halves were dropped and why."""
    ch = set(changing or ())
    keeps = ['Same creature']
    if 'colour' not in ch:
        keeps.append('same colours')
    if 'proportion' not in ch:
        keeps.append('same proportions')
    out = ', '.join(keeps) + '. One creature only, no people, no text.'
    bp = (body_plan or '').strip()
    if bp and 'anatomy' not in ch:
        out = f'{out} The creature has {bp}'.rstrip('.') + '.'
    return out


def _changing(clauses):
    """Which keep-halves this stack's ops contradict."""
    secs = {OP_BY_ID[c['op']]['sec'] for c in clauses}
    return {k for k, v in _KEEP_DROPS.items() if secs & v}


def compile_stack(stack, x=None):
    x = x or {}
    rows, dropped = normalise_stack(stack)
    live = [r for r in rows if r['on']]
    first_gen = next((k for k, r in enumerate(live) if OP_BY_ID[r['op']]['cls'] == 'edit'), None)
    pre, post, clauses, negs = [], [], [], []
    for k, r in enumerate(live):
        o = OP_BY_ID[r['op']]
        if o['cls'] == 'pix':
            (pre if (first_gen is None or k < first_gen) else post).append(r)
            continue
        cl = ''
        if o['fn']:
            try:
                cl = (o['fn'](r['p'], x) or '').strip().rstrip('.')
            except Exception as ex:  # noqa: BLE001
                dropped.append({'op': r['op'], 'why': f'{type(ex).__name__}: {ex}'})
                cl = ''
        if cl:
            clauses.append({'op': r['op'], 'lb': o['lb'], 'text': cl})
        if o['neg']:
            nv = o['neg']
            if '{v}' in nv:
                nv = nv.replace('{v}', str(r['p'].get('v') or '')).strip()
            if nv:
                negs.append(nv)
    body = '. '.join(c['text'][0].upper() + c['text'][1:] if c['text'] else '' for c in clauses)
    ch = _changing(clauses)
    instr = (body + '. ' if body else '') + keep_sentence(x.get('body_plan'), ch)
    sty = (x.get('style_hint') or '').strip()
    # the creature's own style hint is a keep-clause too, and a Style op is
    # exactly the instruction to stop keeping it
    if sty and body and 'style' not in ch:
        instr += f' Same rendering style: {sty}.'
    return {
        'rows': rows,
        'dropped': dropped,
        'pre': pre,
        'post': post,
        'clauses': clauses,
        'instruction': instr if body else '',
        'negative': ', '.join([_NEG_BASE] + negs),
        'gen_count': len(clauses),
        'pix_count': len(pre) + len(post),
        'keep_dropped': sorted(ch),
    }


def apply_pixels(im, rows):
    """Run a list of validated pixel rows over a Pillow image, in order."""
    for r in rows:
        o = OP_BY_ID.get(r['op'])
        if not o or not o['pfn']:
            continue
        im = o['pfn'](im.convert('RGBA'), r['p'])
    return im
