#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_cycles_render.py — the photoreal render path for Character Studio.

WHY THIS EXISTS (2026-09-23)
============================
char_hair_assets.js draws an installed groom as ~7,000 ribbons 1.3 mm wide so
the viewport stays interactive. That is a preview and it cannot be photoreal: a
1.3 mm flat plank standing in for seventeen hairs reads as plastic however it
is shaded, and WebGL has no order-independent transparency or self-shadowing to
give it. The split this module completes is the one the skin already uses —
VIEWPORT IS A PREVIEW, THE BAKE IS THE PICTURE:

    viewport   char_hair_assets.js   ribbons, milliseconds
    picture    this module           real curves, seconds

Here the hair is every strand the production groom has, interpolated up to head
density and rendered as curve primitives 0.05 mm across by the Principled Hair
BSDF (Chiang, melanin-parameterised). Transmission through the fibre, multiple
scattering between neighbours, self-shadowing and thin-geometry anti-aliasing
are done by Cycles rather than approximated by a shader.

The body is the same CC0 base sculpt the studio stands, wearing the same albedo
atlas char_photoreal.py baked, with its UDIM tiles remapped into the packed
grid exactly as char_photoreal.js remaps them for three.js. One skin, two
renderers.

STAGES, resumable from disk under output/hair_curves/ and output/hair_renders/:
  strands   blender -b <character>.blend -> <char>_<part>.npz, every strand the
            groom has, in the DONOR'S SKULL FRAME. Cached: a character is only
            opened once however many pictures are made of it.
  render    blender -b -> PNG. The skull of the body standing here is measured
            the same way and one frame is mapped onto the other, so no offset
            for any particular body is stored anywhere.

MEASURED ON THIS MACHINE (RTX 4090, OptiX, 2026-09-23), Einar's groom at
density 8 = 269,612 strands / 6.47 M curve points:
    900 x 1125, 128 samples    ~7 s render, ~22 s wall including the build
See bench() for the rest; render_report.json carries the numbers per run.

    python3 char_cycles_render.py --character einar --out /tmp/a.png
    python3 char_cycles_render.py --character einar --frame body --size 1440 1800
    python3 char_cycles_render.py --bench
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, 'tools', 'hair_assets')
PACKS = os.path.join(HERE, 'data', 'assets', 'mesh_packs')
CHARS = os.path.join(PACKS, 'human_bases', 'blender_studio_characters')
PHOTOREAL = os.path.join(PACKS, 'photoreal')
OUT_CURVES = os.path.join(HERE, 'output', 'hair_curves')
OUT_RENDER = os.path.join(HERE, 'output', 'hair_renders')
BLENDER = shutil.which('blender') or '/usr/local/bin/blender'

# The .blend each character's grooms are extracted from. Paths are as the
# 2026-09-02 install left them; a character missing here is not renderable.
CHAR_BLEND = {
    'einar': 'einar/einar_release_v1.blend',
    'victoria': 'victoria/victoria.blend',
    'rex': 'rex/rex.blend',
    'phil': 'phil/phil.blend',
    'jay': 'jay/jay.blend',
    'ellie': 'ellie/ellie.blend',
}
BODIES = {
    'male_realistic': 'blender_human_base/glb/coll_body_male_realistic.glb',
    'female_realistic': 'blender_human_base/glb/coll_body_female_realistic.glb',
}
DEFAULT_HDRI = os.path.join(PACKS, 'polyhaven_hdri', 'brown_photostudio_02', 'brown_photostudio_02_2k.hdr')


def _log(msg):
    _zyg_log.info(msg)


def _blender(args, sentinel, timeout=7200, log=_log):
    cmd = [BLENDER, '-b', '--factory-startup'] + args
    log('[cycles] ' + ' '.join(cmd[:6]) + ' …')
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = r.stdout or ''
    if sentinel not in out:
        tail = (out + (r.stderr or ''))[-3000:]
        raise RuntimeError(f'blender failed (exit {r.returncode}):\n{tail}')
    for ln in out.splitlines():
        if ln.startswith(sentinel):
            return json.loads(ln[len(sentinel) :])
    return {}


# ── stage: strands ──────────────────────────────────────────────────────────


def strand_cache(character, parts=('hair', 'beard', 'brows'), force=False, log=_log):
    """{part: npz path} for one character, extracting only if it is missing.

    A character's .blend is 20 to 600 MB of production rig; opening it costs
    far more than the render does, so it is opened once and the strands are
    kept."""
    if character not in CHAR_BLEND:
        raise KeyError(f'no .blend registered for {character!r}; known: {sorted(CHAR_BLEND)}')
    os.makedirs(OUT_CURVES, exist_ok=True)
    want = {p: os.path.join(OUT_CURVES, f'{character}_{p}.npz') for p in parts}
    if not force and all(os.path.isfile(p) for p in want.values()):
        return want
    blend = os.path.join(CHARS, CHAR_BLEND[character])
    if not os.path.isfile(blend):
        raise FileNotFoundError(blend)
    t0 = time.time()
    rep = _blender(
        [
            blend,
            '--python',
            os.path.join(TOOLS, 'hair_extract.py'),
            '--',
            os.path.join(OUT_CURVES, f'{character}.npz'),
            character,
            ','.join(parts),
        ],
        'ZYGEXTRACT',
        log=log,
    )
    log(
        f'[strands] {character}: '
        + ', '.join(f'{w["part"]} {w["strands"]}' for w in rep['written'])
        + f' in {time.time() - t0:.0f}s'
    )
    for w in rep.get('problems', []):
        log(f'[strands] ! {w}')
    return {p: fp for p, fp in want.items() if os.path.isfile(fp)}


# ── stage: render ───────────────────────────────────────────────────────────


def render(
    out,
    *,
    character='einar',
    parts=('hair', 'beard', 'brows'),
    body='male_realistic',
    colour='dark brown',
    photoreal=True,
    frame='head',
    az=0.0,
    el=0.0,
    lens=None,
    size=(900, 1125),
    samples=128,
    density=8.0,
    hair_radius_m=5e-5,
    strand_samples=24,
    hdri=DEFAULT_HDRI,
    hdri_strength=1.0,
    device='OPTIX',
    transparent=False,
    seed=7,
    force_strands=False,
    log=_log,
):
    """One photoreal picture. Returns the render report."""
    npz = strand_cache(character, parts, force=force_strands, log=log)
    if not npz:
        raise RuntimeError(f'{character}: no strands extracted')
    glb = os.path.join(PACKS, BODIES.get(body, BODIES['male_realistic']))
    # PREFER THE DE-HAIRED SKIN. char_skin_dehair.py takes the painted brows,
    # stubble and scalp out of the bake so real strands can stand where they
    # were; using the original here would put a grown brow on top of a painted
    # one, which is the doubling char_hair.js has always guarded against.
    alb = os.path.join(PHOTOREAL, body, 'albedo_nohair.jpg')
    if not os.path.isfile(alb):
        alb = os.path.join(PHOTOREAL, body, 'albedo.jpg')
    man = os.path.join(PHOTOREAL, body, 'manifest.json')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cfg = {
        'glb': glb,
        'out': out,
        'albedo': alb if (photoreal and os.path.isfile(alb)) else None,
        'manifest': man if (photoreal and os.path.isfile(man)) else None,
        'grooms': [{'npz': npz[p], 'colour': colour} for p in parts if p in npz],
        'hdri': hdri,
        'hdri_strength': hdri_strength,
        'camera': {'frame': frame, 'az': az, 'el': el, 'lens': lens},
        'size': list(size),
        'samples': int(samples),
        'density': float(density),
        'hair_radius_m': float(hair_radius_m),
        'strand_samples': int(strand_samples),
        'device': device,
        'transparent': bool(transparent),
        'seed': int(seed),
        'report': os.path.splitext(out)[0] + '_report.json',
    }
    cfg_p = os.path.splitext(out)[0] + '_cfg.json'
    with open(cfg_p, 'w', encoding='utf-8') as fh:
        json.dump(cfg, fh, indent=1)
    t0 = time.time()
    rep = _blender(['--python', os.path.join(TOOLS, 'cycles_render.py'), '--', cfg_p], 'ZYGRENDER', log=log)
    n = sum(g.get('rendered_strands', 0) for g in rep.get('grooms', []))
    log(
        f'[render] {os.path.basename(out)}: {n:,} strands, {rep["device"]}, '
        f'{rep["size"][0]}x{rep["size"][1]} @{rep["samples"]} — '
        f'render {rep["t_render"]:.1f}s, wall {time.time() - t0:.0f}s'
    )
    return rep


# ── the benchmark the operator asked for ────────────────────────────────────

BENCH = [
    # label,             size,          samples, density, frame
    ('preview_900', (900, 1125), 128, 8, 'head'),
    ('portrait_1080', (1080, 1350), 256, 8, 'head'),
    ('portrait_dense', (1080, 1350), 256, 16, 'head'),
    ('hero_2160', (2160, 2700), 256, 8, 'head'),
    ('bust_1080', (1080, 1350), 256, 8, 'bust'),
    ('figure_1080', (1080, 1620), 256, 8, 'body'),
]


def bench(character='einar', out_dir=None, log=_log):
    out_dir = out_dir or os.path.join(OUT_RENDER, 'bench')
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for label, size, samples, density, frame in BENCH:
        rep = render(
            os.path.join(out_dir, f'{label}.png'),
            character=character,
            size=size,
            samples=samples,
            density=density,
            frame=frame,
            log=log,
        )
        rows.append(
            {
                'label': label,
                'size': rep['size'],
                'samples': rep['samples'],
                'density': density,
                'frame': frame,
                'strands': sum(g.get('rendered_strands', 0) for g in rep['grooms']),
                'points': sum(g.get('points', 0) for g in rep['grooms']),
                't_hair': rep['t_hair'],
                't_render': rep['t_render'],
                't_total': rep['t_total'],
                'device': rep['device'],
            }
        )
    fp = os.path.join(out_dir, 'bench.json')
    with open(fp, 'w', encoding='utf-8') as fh:
        json.dump({'character': character, 'rows': rows}, fh, indent=1)
    log('')
    log(f'{"label":<18}{"size":>12}{"smp":>5}{"dens":>6}{"strands":>10}{"build":>8}{"render":>8}{"total":>8}')
    for r in rows:
        log(
            f'{r["label"]:<18}{r["size"][0]}x{r["size"][1]:>6}{r["samples"]:>5}'
            f'{r["density"]:>6}{r["strands"]:>10,}{r["t_hair"]:>7.1f}s'
            f'{r["t_render"]:>7.1f}s{r["t_total"]:>7.1f}s'
        )
    log(f'\nwritten {fp}')
    return rows


if __name__ == '__main__':  # the CLI lives in char_cycles_render_cli
    from zyg_workflows.char_cycles_render_cli import main as _cli_main

    raise SystemExit(_cli_main())
