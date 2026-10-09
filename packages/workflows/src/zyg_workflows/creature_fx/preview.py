# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE ENGINE / preview — the deterministic half at full source resolution, honest about the rest.

Moved verbatim out of the old single-file creature_fx.py (lines 4997-5161).
"""

from __future__ import annotations

import io
import json

from zyg_workflows.creature_fx.ops_pixel import _rgba
from zyg_workflows.creature_fx.ops_dock import OP_BY_ID
from zyg_workflows.creature_fx.resolve import _manifest, licence_of, resolve_image
from zyg_workflows.creature_fx.compiler import apply_pixels, compile_stack


# ── preview ─────────────────────────────────────────────────────────────────
# The preview shows the DETERMINISTIC half of the stack, at full source
# resolution, resized only on the way out. What it cannot show is the
# generative half -- and it says so in a header rather than handing back a
# picture that quietly omits three of your eight ops.


def _open(fp):
    from PIL import Image

    im = Image.open(fp)
    im.load()
    return im.convert('RGBA')


def _png(im, maxw=0):
    if maxw and im.width > maxw:
        from PIL import Image

        h = max(1, int(round(im.height * maxw / float(im.width))))
        im = im.resize((maxw, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def _checkerboard(size, sq=16):
    from PIL import Image, ImageDraw

    im = Image.new('RGBA', size, (46, 50, 58, 255))
    d = ImageDraw.Draw(im)
    for yy in range(0, size[1], sq):
        for xx in range(0, size[0], sq):
            if ((xx // sq) + (yy // sq)) % 2:
                d.rectangle([xx, yy, xx + sq - 1, yy + sq - 1], fill=(62, 68, 78, 255))
    return im


def preview_frame(cid, cat, name, stack, view='rgb', ab=False, maxw=0, ground=''):
    """One PNG of the stack's deterministic half, plus what it could not show."""
    fp = resolve_image(cid, cat, name)
    x = _ctx(cid)
    comp = compile_stack(stack, x)
    src = _open(fp)
    out = apply_pixels(src, comp['pre'] + comp['post'])
    if view == 'alpha':
        a = out.getchannel('A')
        out = a.convert('RGBA')
    if ab:
        from PIL import Image

        base = src if src.size == out.size else src.resize(out.size, Image.LANCZOS)
        half = out.width // 2
        merged = base.copy()
        merged.paste(out.crop((half, 0, out.width, out.height)), (half, 0))
        out = merged
    if ground and view != 'alpha':
        from PIL import Image

        if ground == 'checker':
            bg = _checkerboard(out.size)
        else:
            bg = Image.new(
                'RGBA',
                out.size,
                _rgba(
                    {'black': '#000000', 'white': '#ffffff', 'grey': '#7f7f7f', 'green': '#00b140'}.get(
                        ground, '#000000'
                    ),
                    100,
                ),
            )
        bg.alpha_composite(out)
        out = bg
    info = {
        'w': out.width,
        'h': out.height,
        'gen': comp['gen_count'],
        'pix': comp['pix_count'],
        'dropped': comp['dropped'],
        'not_shown': ([c['lb'] for c in comp['clauses']] if comp['gen_count'] else []),
    }
    return _png(out, maxw), info


def chain_text(cid, cat, name, stack):
    """The receipt: exactly what a render would send, before it is sent."""
    fp = resolve_image(cid, cat, name)
    x = _ctx(cid)
    comp = compile_stack(stack, x)
    lic = licence_of(cid)
    lines = [
        f'creature   {x.get("name")}  [{cid}]',
        f'source     {fp}',
        f'licence    {lic["licence"]}  (commercial_ok={lic["commercial_ok"]})',
    ]
    if lic['render_blocked']:
        lines.append(f'RENDER     BLOCKED — {lic["block_note"]}')
    lines.append('')
    lines.append(f'-- pixel ops before the edit ({len(comp["pre"])}) — these change the image the model is handed')
    for r in comp['pre'] or []:
        lines.append(f'   {OP_BY_ID[r["op"]]["lb"]:<16} {json.dumps(r["p"], sort_keys=True)}')
    if not comp['pre']:
        lines.append('   (none)')
    lines.append('')
    if comp['gen_count']:
        lines.append(
            f'-- edit instruction ({comp["gen_count"]} generative op'
            f'{"" if comp["gen_count"] == 1 else "s"}) '
            '— Qwen-Image-Edit-2509, graph qwen_edit_angle'
        )
        for c_ in comp['clauses']:
            lines.append(f'   [{c_["lb"]}] {c_["text"]}')
        lines.append('')
        lines.append('   INSTRUCTION SENT:')
        lines.append('   ' + comp['instruction'])
        lines.append('')
        lines.append('   NEGATIVE:')
        lines.append('   ' + comp['negative'])
        if comp['keep_dropped']:
            lines.append('')
            lines.append('   KEEP-CLAUSE DROPPED: ' + ', '.join(comp['keep_dropped']))
            lines.append(
                '   (an op in this stack changes it, and "make it turquoise. Same '
                'colours" is a prompt arguing with itself)'
            )
    else:
        lines.append(
            '-- edit instruction: none. This stack is fully deterministic, '
            'so the preview IS the result and no GPU is needed.'
        )
    lines.append('')
    lines.append(f'-- pixel ops after the edit ({len(comp["post"])}) — these change the rendered result')
    for r in comp['post'] or []:
        lines.append(f'   {OP_BY_ID[r["op"]]["lb"]:<16} {json.dumps(r["p"], sort_keys=True)}')
    if not comp['post']:
        lines.append('   (none)')
    if comp['dropped']:
        lines.append('')
        lines.append('-- dropped')
        for d in comp['dropped']:
            lines.append(f'   {d["op"]}: {d["why"]}')
    return {
        'ok': True,
        'text': '\n'.join(lines),
        'instruction': comp['instruction'],
        'negative': comp['negative'],
        'gen': comp['gen_count'],
        'pix': comp['pix_count'],
        'blocked': lic['render_blocked'],
    }


def _ctx(cid):
    man = _manifest(cid)
    return {
        'id': cid,
        'name': man.get('name') or cid,
        'species': man.get('species') or '',
        'body_plan': man.get('body_plan') or '',
        'style_hint': man.get('style_hint') or '',
        'trigger': man.get('trigger_token') or '',
    }
