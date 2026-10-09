# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Validation, the compiler, the source and the views (vfx_fx.py lines 3057-3372)."""

from __future__ import annotations

import json
import os
import re
import subprocess

from zyg_workflows.vfx_fx.constants import (
    FFMPEG,
    FFPROBE,
)
from zyg_workflows.vfx_fx.registry import (
    OPS,
    _n,
    _q,
)

# ── validation ──────────────────────────────────────────────────────────────
OP_BY_ID = {o['id']: o for o in OPS}


def validate(op_id, raw):
    """Coerce and clamp one op's parameters against its own schema.

    An out-of-schema KEY is dropped rather than passed through, and every value
    is forced into its declared type and range.  This is the only place a
    number from the browser becomes a number in a filtergraph, so it is the
    only place that has to be right: `geq` takes an expression, `lut3d` takes a
    file, and a filtergraph is a parser.  Nothing here trusts the client to
    have kept its own slider inside its own min and max."""
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
            if v != v or v in (float('inf'), float('-inf')):  # NaN / inf
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
        else:  # 's'
            v = '' if v is None else str(v)
            out[k] = v if re.fullmatch(spec.get('pat', r'.{0,200}'), v) else df
    return out


def normalise_stack(stack, kind='video'):
    """Clean a whole stack: drop unknown ops, drop ops this KIND cannot take,
    validate every parameter.  Returns [{op, on, p}] and a list of what it
    dropped and why -- a silent drop would read as "your stack ran" when a
    third of it did not ([[project_vfx_studio_library]]'s ingest lesson)."""
    out, dropped = [], []
    k = 'v' if kind == 'video' else 'i'
    for row in stack or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get('op') or '')
        o = OP_BY_ID.get(oid)
        if not o or o.get('act'):
            dropped.append({'op': oid, 'why': 'no such effect'})
            continue
        if k not in o['kinds']:
            dropped.append({'op': oid, 'why': f'{o["lb"]} needs moving frames; this source is a still'})
            continue
        out.append({'op': oid, 'on': row.get('on', True) is not False, 'p': validate(oid, row.get('p'))})
    return out, dropped


# ── the compiler ────────────────────────────────────────────────────────────
_LBL = re.compile(r'\[\$(\w+)\]')


def compile_chain(stack, ctx, tail=''):
    """Turn a stack into one -filter_complex string, and return its out label.

    Each op contributes either a plain filter chain (wrapped into the linear
    graph) or, when it needs to branch, a fragment written between the literal
    labels [IN] and [OUT].  A fragment's own internal labels are written [$x]
    and get the segment index stitched into them here, so two glows in one
    stack cannot collide on a label name -- which they would, silently, and
    ffmpeg would wire the second one's blend to the first one's blur."""
    parts = []
    cur = '0:v'
    parts.append(f'[{cur}]format=rgba[v0]')
    cur = 'v0'
    n = 0
    for idx, row in enumerate(stack):
        if not row.get('on', True):
            continue
        o = OP_BY_ID[row['op']]
        frag = o['fn'](row['p'], ctx)
        if not frag or frag == 'null':
            continue
        n += 1
        nxt = f'v{n}'
        if '[IN]' in frag:
            frag = _LBL.sub(lambda m, _idx=idx: f'[s{_idx}_{m.group(1)}]', frag)
            frag = frag.replace('[IN]', f'[{cur}]').replace('[OUT]', f'[{nxt}]')
            parts.append(frag)
        else:
            parts.append(f'[{cur}]{frag}[{nxt}]')
        cur = nxt
    if tail:
        n += 1
        parts.append(f'[{cur}]{tail}[v{n}]')
        cur = f'v{n}'
    return ';'.join(parts), cur


# ── the source ──────────────────────────────────────────────────────────────
_PROBE_CACHE = {}


def probe(path):
    """w/h/fps/duration/kind for one file, cached by path+mtime."""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (path, st.st_mtime_ns, st.st_size)
    hit = _PROBE_CACHE.get(key)
    if hit:
        return hit
    try:
        out = subprocess.run(
            [
                FFPROBE,
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=width,height,r_frame_rate,nb_frames,pix_fmt:format=duration',
                '-of',
                'json',
                path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        d = json.loads(out or '{}')
        s = (d.get('streams') or [{}])[0]
        num, _, den = (s.get('r_frame_rate') or '0/1').partition('/')
        fps = float(num) / float(den or 1) if float(den or 1) else 0.0
        dur = float((d.get('format') or {}).get('duration') or 0)
        pix = str(s.get('pix_fmt') or '')
        info = {
            'w': int(s.get('width') or 0),
            'h': int(s.get('height') or 0),
            'fps': round(fps, 6) or 25.0,
            'dur': dur,
            'nframes': int(s.get('nb_frames') or 0),
            'pix_fmt': pix,
            'alpha': bool(re.search(r'a|argb|rgba|bgra', pix) and ('a' in pix.replace('yuv', '').replace('gbr', ''))),
            'kind': 'image'
            if dur <= 0.08 or os.path.splitext(path)[1].lower() in ('.png', '.jpg', '.jpeg', '.webp', '.tga')
            else 'video',
        }
    except Exception:  # noqa: BLE001
        info = {}
    if info:
        _PROBE_CACHE[key] = info
    return info


def _libpath(cat, fn):
    """Resolve one library file, with the same containment fence the serving
    route uses: a bare basename inside one declared category dir, realpath
    checked, so `_originals/` stays unreachable through this module too."""
    from zyg_workflows import vfx_ingest as vi

    if cat not in vi.CATEGORIES:
        raise ValueError('unknown category')
    if not fn or os.path.basename(fn) != fn or fn.startswith('.'):
        raise ValueError('bad filename')
    root = os.path.realpath(os.path.join(vi.LIBS, cat))
    fp = os.path.realpath(os.path.join(root, fn))
    if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
        raise ValueError('no such file')
    return fp


def source_ctx(cat, fn):
    fp = _libpath(cat, fn)
    info = probe(fp)
    if not info:
        raise ValueError('could not read that file')
    return fp, {
        'w': info['w'],
        'h': info['h'],
        'fps': info['fps'] or 25.0,
        'dur': info['dur'],
        'kind': info['kind'],
        'alpha': info['alpha'],
        'nframes': info['nframes'],
    }


# ── views and scopes ────────────────────────────────────────────────────────
# These are TAIL filters on the same graph, not a separate code path, so the
# alpha you inspect is the alpha the bake will write.  A view built by a
# different route is a view that can disagree with the render, and the one time
# it does is the time you needed it.
VIEWS = {
    'rgb': '',
    # alphaextract must be FENCED BY format ON BOTH SIDES, and the leading one
    # is the load-bearing half.  Whenever it is the first filter after a graph
    # LABEL its input link is unconstrained, ffmpeg reports "could not choose
    # their formats" and writes no frame -- so the one view that shows a
    # matte's holes is the one view that silently fails.  Inside a continuous
    # chain it negotiates fine, which is why this only breaks once the tail is
    # split off into its own segment.
    'alpha': 'format=rgba,alphaextract,format=gray,format=rgba',
    'r': 'format=rgba,colorchannelmixer=rr=1:rg=0:rb=0:gr=1:gg=0:gb=0:br=1:bg=0:bb=0:aa=1',
    'g': 'format=rgba,colorchannelmixer=rr=0:rg=1:rb=0:gr=0:gg=1:gb=0:br=0:bg=1:bb=0:aa=1',
    'b': 'format=rgba,colorchannelmixer=rr=0:rg=0:rb=1:gr=0:gg=0:gb=1:br=0:bg=0:bb=1:aa=1',
}
SCOPES = {
    'histogram': 'format=yuv444p,histogram=display_mode=stack:levels_mode=logarithmic,format=rgba',
    'waveform': 'format=yuv444p,waveform=mode=column:intensity=0.08:graticule=green:'
    'flags=numbers+dots:scale=digital,format=rgba',
    'parade': 'format=yuv444p,waveform=mode=column:display=parade:intensity=0.08:'
    'graticule=green:scale=digital,format=rgba',
    'vectorscope': 'format=yuv444p,vectorscope=mode=color3:graticule=green:flags=name,format=rgba',
}
PREVIEW_MAX = 1280


def build_graph(stack, ctx, view='rgb', scope='', ab=False, maxw=0):
    """The one graph builder every route goes through.

    `maxw` scales for TRANSPORT ONLY and is appended after the stack, never
    before it.  Scaling first would be faster and would also be wrong: a blur
    of sigma 4 on a 960-wide proxy of a 3840-wide element is four times
    stronger, relative to the frame, than the same op in the bake.  The preview
    would look right and the render would not match it, which is the worst
    class of bug this whole tab exists to avoid.  So the preview is the bake,
    one frame of it, resized on the way out."""
    tail = SCOPES.get(scope) or VIEWS.get(view, '')
    if maxw:
        rs = f'scale=w={_q(f"min(iw,{int(maxw)})")}:h=-1:flags=bicubic'
        tail = (tail + ',' + rs) if tail else rs
    if not ab:
        return compile_chain(stack, ctx, tail=tail)
    # A/B: the source and the stack, cut down the middle of one frame.
    body, out = compile_chain(stack, ctx)
    body = body.replace('[0:v]format=rgba[v0]', '[0:v]format=rgba,split[abraw][v0]', 1)
    parts = [
        body,
        '[abraw]crop=iw/2:ih:0:0[abl]',
        f'[{out}]crop=iw/2:ih:iw/2:0[abr]',
        '[abl][abr]hstack=inputs=2,format=rgba[abo]',
    ]
    cur = 'abo'
    if tail:
        parts.append(f'[{cur}]{tail}[abt]')
        cur = 'abt'
    return ';'.join(parts), cur


def preview_cmd(fp, ctx, graph, out_label, t=0.0):
    """One frame, as PNG on stdout.

    -ss goes BEFORE -i so ffmpeg seeks rather than decodes to t -- on a
    1531-second plate that is the difference between a preview and a coffee."""
    cmd = [FFMPEG, '-hide_banner', '-nostdin', '-v', 'error']
    if ctx['kind'] == 'video' and t > 0:
        cmd += ['-ss', _n(t)]
    cmd += [
        '-i',
        fp,
        '-filter_complex',
        graph,
        '-map',
        f'[{out_label}]',
        '-frames:v',
        '1',
        '-c:v',
        'png',
        '-f',
        'image2',
        '-',
    ]
    return cmd


def preview_frame(cat, fn, stack, t=0.0, view='rgb', scope='', ab=False, maxw=PREVIEW_MAX):
    """PNG bytes for one frame of the stack, plus what it had to drop."""
    fp, ctx = source_ctx(cat, fn)
    st, dropped = normalise_stack(stack, ctx['kind'])
    graph, out = build_graph(st, ctx, view=view, scope=scope, ab=ab, maxw=maxw)
    r = subprocess.run(preview_cmd(fp, ctx, graph, out, t), capture_output=True, timeout=300)
    if r.returncode != 0 or not r.stdout:
        err = (r.stderr or b'').decode('utf-8', 'replace').strip()
        raise RuntimeError(err.splitlines()[-1] if err else 'ffmpeg produced no frame')
    return r.stdout, {
        'dropped': dropped,
        'ctx': ctx,
        'time_ops': [o['op'] for o in st if OP_BY_ID[o['op']]['sec'] == 'Time' and o.get('on', True)],
    }


def chain_text(cat, fn, stack, view='rgb', scope='', ab=False):
    """The receipt: the graph, and the whole command that would run it."""
    fp, ctx = source_ctx(cat, fn)
    st, dropped = normalise_stack(stack, ctx['kind'])
    graph, out = build_graph(st, ctx, view=view, scope=scope, ab=ab)
    pv = preview_cmd(fp, ctx, graph, out, 0)
    return {
        'graph': graph,
        'out': out,
        'ctx': ctx,
        'dropped': dropped,
        'ops': len([o for o in st if o.get('on', True)]),
        'preview_cmd': ' '.join(("'" + a + "'") if (' ' in a or ';' in a) else a for a in pv),
    }
