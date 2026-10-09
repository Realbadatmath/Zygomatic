# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""OUTER SIDE: set rendering, the negative set, PROVENANCE and the CLI."""

from zyg_workflows.geom.mv_render.constants import (
    AZIMUTH_STEP_DEG,
    BLENDER,
    CHAR_ROOT,
    CYCLES_SAMPLES,
    ELEVATION_DEG,
    FEMALE_GLB,
    FRAME_H_PER_STATURE,
    HEAD_TOP_MARGIN,
    LENS_MM,
    NEG_CHARS,
    N_VIEWS,
    OUT_H,
    OUT_W,
    ROOT,
    SENSOR_MM,
    SETS,
    WORKER_STATUS,
    _now,
    argparse,
    glob,
    json,
    os,
    shutil,
    subprocess,
    sys,
    tempfile,
)

# ===========================================================================
# OUTER SIDE
# ===========================================================================


def _blender_version():
    try:
        out = subprocess.run([BLENDER, '--version'], capture_output=True, text=True, timeout=60).stdout
        return out.strip().splitlines()[0].strip()
    except Exception:
        return 'unknown'


def _render_positive(set_name, textured, outdir):
    """Render one control set, into a STAGING directory, and only publish it if the worker
    finished.

    THE HOLE THIS CLOSES. The first version passed `outdir` straight to Blender, ignored the
    subprocess returncode, and took `manifest.json exists` as its success test. Every one of
    those three is wrong on its own and together they made every abort in this file
    unenforced: Blender exits 0 on an uncaught exception, so a failed run looked like a
    successful one, and the manifest it "found" was the one a PREVIOUS good build had left
    in the directory. A deliberate screen-locked regression — the exact defect the
    texture-lock test exists to catch — was demonstrated to abort inside Blender and still
    be reported as a successful build, with the old 48 PNGs and the old
    `verdict: surface_locked` left in place for the gate downstream to read as fresh.
    A partially rendered set (worker killed at frame 30) had the same shape: 30 new cells,
    18 stale ones, reported as success.

    So: render into a fresh empty staging dir, require returncode 0 AND a status sentinel
    the worker writes last AND exactly N_VIEWS images AND a manifest, and only then replace
    the published directory. A failed build leaves the previous one untouched and raises.
    """
    staging = outdir + '.staging'
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    cfg = {
        'set_name': set_name,
        'role': (
            'CEILING: 48 projections of one rigid textured object; SfM must '
            'succeed here or the framing itself is the problem'
            if textured
            else 'FEATURE FLOOR: same object, same cameras, no albedo features'
        ),
        'outdir': staging,
        'glb': os.path.join(ROOT, FEMALE_GLB),
        'glb_rel': FEMALE_GLB,
        'textured': textured,
        'texture_treatment': (
            'procedural Voronoi F1 (scale 110) x noise (scale 38, detail 8), driven '
            'from Texture Coordinate -> OBJECT, i.e. surface-locked; verified '
            'structurally and empirically, see texture_lock_verification'
            if textured
            else 'none: flat matte grey base colour 0.55, roughness 1.0'
        ),
        'out_w': OUT_W,
        'out_h': OUT_H,
        'n_views': N_VIEWS,
        'azimuth_step_deg': AZIMUTH_STEP_DEG,
        'elevation_deg': ELEVATION_DEG,
        'lens_mm': LENS_MM,
        'sensor_mm': SENSOR_MM,
        'frame_h_per_stature': FRAME_H_PER_STATURE,
        'head_top_margin': HEAD_TOP_MARGIN,
        'samples': CYCLES_SAMPLES,
        # 60 W per area light. Calibrated 2026-08-07 by sweep: 120 W clipped 27 % of the
        # subject to pure white and destroyed the texture, 28 W left only 18.8 bytes of
        # pixel sd, 60 W measures mean 166, p1 90, p99 224, max 236 (nothing clipped)
        # and 34.7 bytes of sd.
        'light_energy': 60.0,
        'blender_version': _blender_version(),
    }
    fd, cfg_path = tempfile.mkstemp(suffix='.json', prefix='mvcfg_')
    with os.fdopen(fd, 'w') as fh:
        json.dump(cfg, fh)
    # `blender --python` needs a runnable file: this package's __main__.py, the
    # post-split equivalent of running mv_render.py as a script. ROOT is the
    # zyg_workflows package directory (paths.PKG_DIR), never this module's own.
    worker = os.path.join(ROOT, 'geom', 'mv_render', '__main__.py')
    cmd = [BLENDER, '-b', '-noaudio', '--python', worker, '--', cfg_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(cfg_path)

    def _bad(why):
        sys.stderr.write(r.stdout[-6000:] + '\n' + r.stderr[-6000:] + '\n')
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(
            'blender worker failed for %s: %s. The previously published '
            'directory (if any) is UNCHANGED and must not be read as the '
            'output of this run.' % (set_name, why)
        )

    if r.returncode != 0:
        _bad('exit code %d' % r.returncode)
    status_path = os.path.join(staging, WORKER_STATUS)
    if not os.path.isfile(status_path):
        _bad(
            'no %s — the worker did not reach the end of its run (Blender exits 0 on an '
            'uncaught exception, so the exit code alone proves nothing)' % WORKER_STATUS
        )
    with open(status_path) as fh:
        st = json.load(fh)
    if not st.get('ok'):
        _bad('worker status %r' % st)
    if not os.path.isfile(os.path.join(staging, 'manifest.json')):
        _bad('no manifest.json')
    n = len(glob.glob(os.path.join(staging, 'cell_*.png')))
    if n != N_VIEWS:
        _bad('%d of %d cells rendered' % (n, N_VIEWS))
    if st.get('n_images') != N_VIEWS:
        _bad('worker reported %r images, expected %d' % (st.get('n_images'), N_VIEWS))

    # publish: replace wholesale so no stale cell can survive into the new set
    if os.path.isdir(outdir):
        old = outdir + '.previous'
        shutil.rmtree(old, ignore_errors=True)
        os.rename(outdir, old)
        shutil.rmtree(old, ignore_errors=True)
    os.rename(staging, outdir)
    return outdir


def _build_negative(outdir):
    """48 cells, 8 from each of 6 characters, at matching angle indices.

    Cell k is taken from NEG_CHARS[k % 6] at angle index k. That gives every character
    exactly 8 cells, uses every angle index 0..47 exactly once, and keeps the angular
    coverage of the set identical to a real sheet — the ONLY thing that changes is that
    the subject is a different person in every consecutive frame. Files are COPIED, not
    symlinked, so the set survives a cleanup of lora-datasets and so the gate sees a
    plain directory of .png with no link resolution.
    """
    os.makedirs(outdir, exist_ok=True)
    angles = None
    for c in NEG_CHARS:
        mpath = os.path.join(CHAR_ROOT, c, 'contact_sheet', 'manifest.json')
        with open(mpath) as fh:
            ca = json.load(fh).get('cell_angles')
        if ca is None or len(ca) != N_VIEWS:
            raise RuntimeError('%s has no usable cell_angles' % c)
        if angles is None:
            angles = ca
        elif ca != angles:
            raise RuntimeError(
                '%s cell_angles differ from %s — "matching angle indices" would be a lie' % (c, NEG_CHARS[0])
            )

    from PIL import Image

    images = []
    per_char = {c: 0 for c in NEG_CHARS}
    for k in range(N_VIEWS):
        char = NEG_CHARS[k % len(NEG_CHARS)]
        src = os.path.join(CHAR_ROOT, char, 'contact_sheet', 'cells', 'cell_%02d.png' % k)
        if not os.path.isfile(src):
            raise RuntimeError('missing source cell %s' % src)
        dst = os.path.join(outdir, 'cell_%02d.png' % k)
        shutil.copyfile(src, dst)
        per_char[char] += 1
        with Image.open(dst) as im:
            w, h = im.size
        images.append(
            {
                'file': 'cell_%02d.png' % k,
                'source_char_id': char,
                'source_cell_index': k,
                'source_path': src,
                'requested_angle': angles[k],
                'width': w,
                'height': h,
            }
        )
    manifest = {
        'set': 'negative_mixed',
        'generated': _now(),
        'generator': 'geom/mv_render.py (no rendering; cells copied)',
        'role': (
            'FLOOR: 48 cells from 6 DIFFERENT characters, so they are definitively '
            'not projections of one object. A real sheet scoring at or below this '
            'is indistinguishable from an incoherent subject.'
        ),
        'source': {
            'kind': 'copied_generated_cells',
            'characters': NEG_CHARS,
            'cells_per_character': per_char,
            'root': CHAR_ROOT,
            'assignment': (
                'cell_NN.png is taken from characters[NN mod 6] at that '
                'same cell index NN: every angle index 0..47 is used '
                'exactly once and every character contributes 8 cells'
            ),
            'angle_lists_identical_across_characters': True,
        },
        'resolution': sorted({(im['width'], im['height']) for im in images})[0]
        if len({(im['width'], im['height']) for im in images}) == 1
        else 'MIXED',
        'n_images': len(images),
        'camera': {
            'projection': 'unknown (diffusion-generated, no declared intrinsics)',
            'focal_length_mm': None,
            'elevation_deg': None,
            'trajectory': 'the 48 hand-written contact-sheet angle prompts, verbatim '
            'per image in images[].requested_angle',
        },
        'texture_treatment': 'n/a — real generated imagery',
        'images': images,
    }
    with open(os.path.join(outdir, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)
    return outdir


_PROVENANCE = {
    'note': (
        'Control image sets for the multi-view-consistency gate. NO EXTERNAL '
        'ASSET IS INTRODUCED BY THIS BUILD. The two positive sets are rendered '
        'from a mesh already in the repo with textures generated procedurally by '
        "Blender's own shader nodes — nothing was downloaded, and no image, HDRI "
        'or material was imported. The negative set is a copy of imagery this '
        'project generated itself.'
    ),
    'items': [
        {
            'what': 'positive_textured / positive_untextured (rendered)',
            'input': FEMALE_GLB,
            'input_licence': (
                'in-house mesh, already in the repo and already '
                "licence-evidenced upstream: it is anny's parametric "
                'body fitted (geom/fit_reference.py) to point clouds '
                'sampled on the Blender Studio Human Base Meshes '
                'bundle v1.4.1, whose CC0 evidence with source URL and '
                'verbatim licence quote is recorded in '
                'data/assets/mesh_packs/blender_human_base/'
                'PROVENANCE.json. THIS BUILD ADDS NO UPSTREAM ASSET, '
                'so it claims no licence evidence of its own — the '
                'entry exists to say exactly that.'
            ),
            'texture': (
                'procedural, generated at render time by Blender node groups '
                '(ShaderNodeTexVoronoi / ShaderNodeTexNoise). Not a file, not '
                'a download, no third-party rights involved.'
            ),
            'renderer': 'Blender (GPL-3.0-or-later) — a tool, output not encumbered',
        },
        {
            'what': 'negative_mixed (copied)',
            'input': CHAR_ROOT + '/<char>/contact_sheet/cells/cell_NN.png',
            'input_licence': 'in-house generated output of this project',
        },
    ],
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m zyg_workflows.geom.mv_render',
        description='Render the multi-view-consistency control image sets.',
    )
    ap.add_argument('--set', default='all', choices=('all',) + SETS, help='which control set to build (default: all)')
    ap.add_argument(
        '--out', default='data/assets/mvconsist_controls', help='output root, relative to the repo root unless absolute'
    )
    ap.add_argument(
        '--force',
        action='store_true',
        help='replace a control set that already exists. Required, because '
        'geom/mvconsist_band.py derives its thresholds from measurements '
        'taken on the EXACT images in that directory, and Cycles is '
        'stochastic: a rebuild produces different pixels and silently '
        'invalidates the band that was measured on the old ones.',
    )
    args = ap.parse_args(argv)

    out_root = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(out_root, exist_ok=True)
    wanted = SETS if args.set == 'all' else (args.set,)

    # A REBUILD INVALIDATES THE BAND. The thresholds in geom/mvconsist_band.py are the
    # midpoint between measurements taken on the images currently in these directories.
    # Overwriting them with a fresh stochastic render leaves the band describing images
    # that no longer exist, and nothing downstream would notice.
    existing = [s for s in wanted if glob.glob(os.path.join(out_root, s, 'cell_*.png'))]
    if existing and not args.force:
        raise SystemExit(
            'refusing to rebuild %s in %s: %d control set(s) already exist there and\n'
            "geom/mvconsist_band.py's thresholds were measured on those exact images.\n"
            'Cycles is stochastic, so a rebuild changes the pixels and the band no longer\n'
            'describes what is on disk. Either build somewhere else with --out, or pass\n'
            '--force AND re-measure every control and re-derive the band afterwards\n'
            '(DERIVATION says in so many words that a new control measurement is the only\n'
            'legitimate reason to move a threshold, and that it must rewrite DERIVATION).'
            % (', '.join(existing), out_root, len(existing))
        )

    done = []
    for s in wanted:
        d = os.path.join(out_root, s)
        if s == 'negative_mixed':
            _build_negative(d)
        else:
            _render_positive(s, s == 'positive_textured', d)
        n = len(glob.glob(os.path.join(d, 'cell_*.png')))
        # Printed AND checked. A count that is only printed is a count nobody reads.
        if n != N_VIEWS:
            raise RuntimeError(
                '%s finished with %d cells, expected %d — refusing to '
                'record it in PROVENANCE.json as a control set' % (s, n, N_VIEWS)
            )
        done.append((s, d, n))
        print('%-20s %s  %d png' % (s, d, n))

    # PROVENANCE IS MERGED, NOT OVERWRITTEN. This file accounts for a DIRECTORY, and the
    # directory keeps whatever sets are on disk. Rebuilding one set used to rewrite the
    # record with only that set's name and a fresh timestamp, deleting the licence and
    # source account of the two sets still sitting beside it.
    prov_path = os.path.join(out_root, 'PROVENANCE.json')
    prov = dict(_PROVENANCE)
    previous = {}
    if os.path.isfile(prov_path):
        try:
            with open(prov_path) as fh:
                previous = json.load(fh) or {}
        except (OSError, ValueError):
            previous = {}
    built_now = {s: _now() for s, _, _ in done}
    stamps = dict(previous.get('set_generated') or {})
    stamps.update(built_now)
    # only claim a set that is actually present on disk right now
    stamps = {s: t for s, t in stamps.items() if os.path.isdir(os.path.join(out_root, s))}
    prov['generated'] = _now()
    prov['sets'] = sorted(stamps)
    prov['set_generated'] = stamps
    prov['sets_built_this_invocation'] = sorted(built_now)
    prov['sets_note'] = (
        '`sets` is every control set present in this directory, with the '
        'time each was last built in `set_generated`. It is merged with '
        'the previous record rather than replaced, so building one set '
        'does not erase the provenance of the others.'
    )
    with open(prov_path, 'w') as fh:
        json.dump(prov, fh, indent=1)
    return 0
