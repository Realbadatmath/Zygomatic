# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE ENGINE / measurement — identity against the anchor, structural change against the source.

Moved verbatim out of the old single-file creature_fx.py (lines 5162-5406).
"""

from __future__ import annotations

import os
import uuid
import logging as _zyg_logging

from zyg_workflows.creature_fx.base import JOBDIR, _pick
from zyg_workflows.creature_fx.ops_colour import colour_word
from zyg_workflows.creature_fx.resolve import _anchor_path, licence_of, list_bakes, resolve_image
from zyg_workflows.creature_fx.compiler import apply_pixels, compile_stack, keep_sentence
from zyg_workflows.creature_fx.preview import _ctx, _open


_zyg_log = _zyg_logging.getLogger(__name__)


# ── measurement ─────────────────────────────────────────────────────────────
# Every one of these answers with a number AND what the number is compared
# against. `ms_change` exists because the failure mode of a generative edit is
# not a bad picture, it is an UNCHANGED picture that cost four minutes.


def _tmp_png(im):
    os.makedirs(JOBDIR, exist_ok=True)
    fp = os.path.join(JOBDIR, f'_m_{uuid.uuid4().hex[:10]}.png')
    im.convert('RGB').save(fp)
    return fp


def _phash(im, n=8):
    """Average hash — enough to answer "did this change at all?", which is the
    only question ms_change asks. Not a similarity metric and not offered as
    one: identity has its own op and its own model.

    Composited over mid grey FIRST, and that is not a detail. Hashing
    `im.convert('L')` throws the alpha away, so a key that cut 13.6% of the
    frame to transparent came back as "IDENTICAL — nothing changed a pixel"
    (measured 2026-09-02 on cell_02 with px_key in the stack). A change metric
    that cannot see the one op class whose whole output IS the alpha is worse
    than none: it reports a working op as a no-op."""
    from PIL import Image

    if im.mode == 'RGBA':
        bg = Image.new('RGBA', im.size, (128, 128, 128, 255))
        bg.alpha_composite(im)
        im = bg
    g = im.convert('L').resize((n, n))
    px = list(g.getdata())
    avg = sum(px) / float(len(px))
    return ''.join('1' if v >= avg else '0' for v in px)


def _hamm(a, b):
    return sum(1 for p, q in zip(a, b) if p != q)


def measure(cid, cat, name, which, stack=None, band='front'):
    fp = resolve_image(cid, cat, name)
    x = _ctx(cid)
    comp = compile_stack(stack or [], x)
    src = _open(fp)
    cur = apply_pixels(src, comp['pre'] + comp['post'])
    if which == 'ms_facts':
        a = cur.getchannel('A')
        hist = a.histogram()
        total = float(cur.width * cur.height) or 1.0
        clear = hist[0] / total
        solid = hist[255] / total
        return {
            'ok': True,
            'kind': 'facts',
            'rows': [
                ['source', f'{cat}/{name}'],
                ['size', f'{src.width} x {src.height}'],
                ['after stack', f'{cur.width} x {cur.height}'],
                ['bytes on disk', f'{os.path.getsize(fp):,}'],
                ['fully transparent', f'{clear * 100:.1f}% of pixels'],
                ['fully opaque', f'{solid * 100:.1f}% of pixels'],
                [
                    'alpha carries a matte',
                    'yes' if clear > 0.005 and solid < 0.995 else 'no — the alpha is solid, this image has no cut-out',
                ],
            ],
        }
    if which == 'ms_palette':
        small = cur.convert('RGB').resize((64, 64))
        q = small.quantize(colors=8, method=2)
        pal = q.getpalette() or []
        counts = sorted(q.getcolors() or [], reverse=True)
        rows = []
        for cnt, idx in counts[:8]:
            r, g, b_ = pal[idx * 3 : idx * 3 + 3]
            hexv = f'#{r:02x}{g:02x}{b_:02x}'
            rows.append([hexv, f'{cnt / 40.96:.1f}%  ({colour_word(hexv)})'])
        return {
            'ok': True,
            'kind': 'palette',
            'rows': rows,
            'note': 'By area, over an 8-colour quantisation of the picture in the pane.',
        }
    if which == 'ms_licence':
        lic = licence_of(cid)
        return {
            'ok': True,
            'kind': 'licence',
            'rows': [
                ['train family', lic['family'] or '(none — no trained weights)'],
                ['licence', lic['licence']],
                ['commercial use', {True: 'YES', False: 'NO', None: 'unknown'}[lic['commercial_ok']]],
                ['note', lic['note']],
                [
                    'new renders',
                    'BLOCKED — ' + lic['block_note']
                    if lic['render_blocked']
                    else 'allowed; a studio bake inherits exactly this licence',
                ],
            ],
        }
    if which == 'ms_plan':
        bp = x.get('body_plan') or ''
        return {
            'ok': True,
            'kind': 'plan',
            'rows': [
                [
                    'body plan lock',
                    bp or '(none set — every rotation of this creature is free to invent whatever the anchor hides)',
                ],
                ['keep sentence', keep_sentence(bp)],
                ['spliced into', 'every edit instruction, every caption and the judge checklist'],
            ],
            'note': 'Edit it under Pipeline → Brief.',
        }
    if which == 'ms_change':
        d = _hamm(_phash(src), _phash(cur))
        same_size = src.size == cur.size
        a0 = src.getchannel('A').histogram()[0] / float(src.width * src.height)
        a1 = cur.getchannel('A').histogram()[0] / float(cur.width * cur.height)
        # bytes differ is the fine-grained answer; the hash is the coarse one. A
        # grade that moves every pixel by one level is a real change the hash
        # cannot see, and reporting only the hash would call it identical.
        same_bytes = src.size == cur.size and src.convert('RGBA').tobytes() == cur.convert('RGBA').tobytes()
        return {
            'ok': True,
            'kind': 'change',
            'rows': [
                ['deterministic ops', f'{comp["pix_count"]} in the stack'],
                ['average-hash distance', f'{d} of 64 bits'],
                ['geometry', 'unchanged' if same_size else f'{src.size} -> {cur.size}'],
                ['transparent area', f'{a0 * 100:.1f}%  ->  {a1 * 100:.1f}%'],
                ['byte-identical', 'yes' if same_bytes else 'no'],
                [
                    'verdict',
                    'IDENTICAL — nothing in the deterministic half changed a pixel' if same_bytes else 'changed',
                ],
            ],
            'note': 'The hash is composited over grey before it is taken, so an alpha-only '
            'change (a key) shows up; hashing the luminance alone reported a working '
            'keyer as a no-op. This measures the pixel half only — generative ops are '
            'measured after a render, against the same source.',
        }
    if which in ('ms_identity',):
        try:
            from zyg_workflows import creature_identity as cid_mod
        except Exception as ex:  # noqa: BLE001
            return {'ok': False, 'error': f'identity metric unavailable: {ex}'}
        anchor, kind = _anchor_path(cid)
        if not anchor:
            return {'ok': False, 'error': 'this creature has no anchor to score against'}
        tmp = _tmp_png(cur)
        try:
            sc = cid_mod.similarity(anchor, tmp)
        finally:
            try:
                os.unlink(tmp)
            except OSError as _exc:
                _zyg_log.debug('temp png cleanup skipped: %s', _exc)
        v = cid_mod.verdict(sc, band)
        return {
            'ok': True,
            'kind': 'identity',
            'rows': [
                ['model', cid_mod.model_id() or 'unavailable'],
                ['anchor', f'{os.path.basename(anchor)}  ({kind})'],
                ['DINOv2 CLS cosine', 'not measured' if sc is None else f'{sc:.4f}'],
                ['floor for this band', f'{v["floor"]:.2f}  (band: {band})'],
                ['hard floor', f'{cid_mod.HARD_FLOOR:.2f} — below this it is a different subject'],
                [
                    'verdict',
                    'not measured'
                    if sc is None
                    else (
                        'PASS'
                        if v['soft_ok']
                        else ('DIFFERENT SUBJECT' if not v['hard_ok'] else 'below the soft floor')
                    ),
                ],
            ],
            'note': 'Calibration on this model: same image vs its mirror 0.981, same creature '
            'different angle 0.784, different creature 0.113.',
        }
    if which in ('ms_judge', 'pl_judge'):
        try:
            from zyg_workflows import creature_judge as cj
        except Exception as ex:  # noqa: BLE001
            return {'ok': False, 'error': f'judge unavailable: {ex}'}
        if not cj.available():
            return {
                'ok': False,
                'error': 'the VLM judge worker is not reachable right now — nothing is judged rather than judged blind',
            }
        items = cj.cell_items(
            _pick(dict(v=band), 'v') or 'the requested viewpoint',
            kind='body',
            band=band,
            body_plan=x.get('body_plan') or '',
        )
        if not items:
            return {'ok': False, 'error': 'the creature_cell checklist is missing'}
        tmp = _tmp_png(cur)
        try:
            res = cj.judge_batch(
                [
                    {
                        'key': 'studio',
                        'image': tmp,
                        'items': items,
                        'preamble': cj.load_items('creature_cell').get('preamble', ''),
                    }
                ]
            )
        except Exception as ex:  # noqa: BLE001
            return {'ok': False, 'error': f'{type(ex).__name__}: {ex}'}
        finally:
            try:
                os.unlink(tmp)
            except OSError as _exc:
                _zyg_log.debug('temp png cleanup skipped: %s', _exc)
        agg = (res or {}).get('studio') or {}
        if not agg.get('judged'):
            return {'ok': False, 'error': f'judge offline: {agg.get("reason", "unknown")}'}
        rows = [
            [v.get('id', ''), f'{v.get("answer", "?")}   {"ok" if v.get("ok") else "FLAG"}   [{v.get("severity", "")}]']
            for v in (agg.get('verdicts') or [])
        ]
        rows.insert(0, ['verdict', 'PASS' if agg.get('ok') else 'FLAGGED: ' + ', '.join(agg.get('flags') or [])])
        rows.insert(1, ['tier / model', f'{agg.get("tier", "")} · {agg.get("model", "")}'])
        return {
            'ok': True,
            'kind': 'judge',
            'rows': rows,
            'note': 'Same judge, same checklist and the same tier the sheet QC runs per cell. '
            'It refuses the GPU while ComfyUI is sampling rather than queueing behind it.',
        }
    if which == 'ms_history':
        bks = list_bakes(cid)
        rows = [[b_['name'], f'{b_.get("when", "")}  ·  {b_.get("summary", "")}'] for b_ in bks]
        return {'ok': True, 'kind': 'history', 'rows': rows or [['—', 'no studio bakes yet']]}
    return {'ok': False, 'error': f'no such measurement: {which}'}
