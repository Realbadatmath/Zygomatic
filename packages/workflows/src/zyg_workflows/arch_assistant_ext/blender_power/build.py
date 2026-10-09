# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power.build — see the package docstring."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.blender_power.constants import (
    BLENDER,
    BLEND_DIR,
    BSTORE,
    BUILDER,
    BUILD_TIMEOUT,
    Drawing,
    HERE,
    MAX_OBJECTS,
    hashlib,
    json,
    os,
    re,
    subprocess,
    time,
)


# ── stage 1: build the drawing ───────────────────────────────────────────────
def _blender_ok():
    if not os.path.exists(BLENDER):
        return f'refused: Blender not found at {BLENDER} (set BLENDER_BIN)'
    if not os.path.exists(BUILDER):
        return 'refused: arch_blender_build.py is missing'
    return ''


def _slug(name):
    return re.sub(r'[^a-z0-9]+', '-', str(name or 'drawing').lower()).strip('-') or 'drawing'


def _doc_sig(doc):
    """What makes this .blend: the document AND the code that builds it.

    Folding the builder's stamp in means an edit to arch_blender_build.py
    invalidates every stored build, so `find_clean` can never hand back geometry
    the current builder would not produce."""
    key = json.dumps(doc, sort_keys=True) + '|' + BSTORE.builder_stamp()
    return hashlib.sha1(key.encode('utf-8'), usedforsecurity=False).hexdigest()[:12]


def _build(d: Drawing):
    """(blend_path, note) or raises ValueError('...') -> 'refused: ...'."""
    if not d.objs:
        raise ValueError('the drawing is empty — draw something before sending it to Blender')
    if len(d.objs) > MAX_OBJECTS:
        raise ValueError(f'the drawing holds more than the {MAX_OBJECTS} object ceiling')
    doc = d.to_doc()
    sig = _doc_sig(doc)
    cached = getattr(d, '_bp_blend', None)
    if cached and cached[0] == sig and os.path.exists(cached[1]):
        return cached[1], 'reused the .blend built earlier in this request'
    # Across requests too: a build is ~2 GB and several minutes, and the document
    # is usually untouched between one tool call and the next.  Only builds that
    # no pass has saved into are offered (see arch_blend_store.mark_dirty).
    ondisk = BSTORE.find_clean(sig)
    if ondisk:
        d._bp_blend = (sig, ondisk)
        return ondisk, 'reused the .blend already built from this drawing'
    os.makedirs(BLEND_DIR, exist_ok=True)
    base = os.path.join(BLEND_DIR, f'{_slug(d.name)}-{time.strftime("%Y%m%d-%H%M%S")}-{sig}')
    src = base + '.json'
    with open(src, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)
    blend = base + '.blend'
    cmd = [BLENDER, '-b', '--python', BUILDER, '--', '--in', src, '--out', blend]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    except subprocess.TimeoutExpired as _exc:
        raise ValueError(f'Blender took longer than {BUILD_TIMEOUT}s to build the drawing') from _exc
    info = {}
    for line in (p.stdout or '').splitlines()[::-1]:
        if line.startswith('{'):
            try:
                info = json.loads(line)
            except ValueError:
                info = {}
            break
    if p.returncode != 0 or not info.get('ok') or not os.path.exists(blend):
        raise ValueError(
            'Blender could not build the drawing: '
            + (info.get('error') or (p.stderr or p.stdout or '')[-200:] or f'exit {p.returncode}')
        )
    d._bp_blend = (sig, blend)
    # retention runs on the back of the write that caused the growth
    BSTORE.sweep(protect=[blend])
    return blend, f'built {info.get("objects")} objects ({info.get("skipped") or 0} skipped)'
