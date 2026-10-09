#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Invariants of the registered prop/creature mesh library and its control maps.

Every test here encodes a defect that was REAL on 2026-08-26, most of them silent:
a mesh that measures 30% too small, a viewer that lays the creature on its side, a
card that leads with the back of the subject's head, a depth map that spends 89% of
its range on the floor, and 16 normal passes that no reader in this repo can open.
None of them raises; all of them look like a working pipeline.

    .venv-test/bin/python -m pytest tests/test_prop_mesh_library.py -q
"""

import os
import struct
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import prop_mesh_library as PML  # noqa: E402

ASSET = 'pufferball'
_registered = PML.get(ASSET) is not None
needs_asset = pytest.mark.skipif(not _registered, reason='pufferball not registered')


# ── the registry itself ─────────────────────────────────────────────────────
@needs_asset
def test_registry_verifies():
    """Every recorded file still hashes to what was recorded. This is the whole
    point of a registry — an asset nobody can prove is intact is just a folder."""
    v = PML.verify(ASSET)[ASSET]
    assert v['ok'], 'bad=%s missing=%s' % (v['bad'], v['missing'])
    assert v['files'] > 60, 'suspiciously few files recorded: %d' % v['files']


@needs_asset
def test_licence_is_declared_and_commercial():
    """The channel is monetised. An asset whose licence is UNDECLARED is not a
    neutral state — it is an un-shippable one, and it must not read as fine."""
    lic = PML.get(ASSET).get('licence') or {}
    assert lic.get('id'), 'no licence id recorded'
    assert lic.get('commercial_ok') is True


# ── geometry: the scene-graph transform defect ──────────────────────────────
@needs_asset
def test_geometry_is_measured_in_world_space():
    """trimesh.util.concatenate(scene.geometry.values()) silently drops the
    scene-graph transforms: every part collapses onto the origin and the bounding
    box comes back ~30% small (0.32x0.30x0.27 m instead of 0.42x0.46x0.33 m).
    It raises nothing and the vertex COUNT is identical, so only the dimensions
    give it away. Scene.to_mesh() is the correct flatten."""
    g = PML.get(ASSET)['geometry']
    s = g['size_m']
    # Re-measured 2026-08-27 after the CANON LOOK port (prop_mesh/pufferball_look.py,
    # `pufferball_sheet.py --look canon`). size_m is now the SOLID creature (fur
    # geometry excluded — see prop_mesh_library.geometry_stats) and the look's tail is
    # a tube that sweeps up-LEFT as in anchor_full, so the width includes the tail:
    #   width  0.3665 -> 0.6337   depth 0.4029 -> 0.6608   height 0.3345 -> 0.5408
    # (phase-3 round 2 of the look, 2026-08-28; the phase-2 look measured 0.6334 /
    # 0.6629 / 0.5408 — the 2 mm depth change is the re-shaped snout.) fur_extent_m
    # (locks included) is wider still, 0.700.
    assert s['width'] == pytest.approx(0.6337, abs=0.002), s
    assert s['depth'] == pytest.approx(0.6608, abs=0.002), s
    assert s['height'] == pytest.approx(0.5408, abs=0.002), s
    # the creature's whole design premise, and a cheap invariant on the above
    assert s['width'] > s['height'], 'the Pufferball is wider than he is tall'


@needs_asset
def test_geometry_sits_on_the_ground_plane():
    """Origin on the floor is the build script's stated convention; a body that
    floats or sinks makes every camera distance in the sheet wrong."""
    z = PML.get(ASSET)['geometry']['bbox_m']['z']
    assert abs(z[0]) < 0.02, 'lowest point is %.4f m, not on the ground' % z[0]


# ── the 3D viewer's geometry ────────────────────────────────────────────────
@needs_asset
def test_mesh3d_is_z_up_and_well_formed():
    """glTF is Y-up and the GUI's orbit camera is Z-up (camera.up = 0,0,1). Skip
    the rotation and the creature lies on its side in the viewer — which looks
    like a broken model, not a broken exporter."""
    rec = PML.get(ASSET)
    p = os.path.join(PML.ROOT, rec['mesh3d'])
    assert os.path.isfile(p)
    raw = open(p, 'rb').read()
    assert raw[:4] == b'ZM3D'
    _ver, nv, nt, ne = struct.unpack('<4I', raw[4:20])
    o = 20
    v = np.frombuffer(raw, np.float32, nv * 3, o).reshape(-1, 3)
    o += nv * 12
    tri = np.frombuffer(raw, np.uint32, nt * 3, o).reshape(-1, 3)
    o += nt * 12
    edge = np.frombuffer(raw, np.uint32, ne * 2, o).reshape(-1, 2)
    assert o + ne * 8 == len(raw), 'trailing bytes — header counts disagree with the body'
    assert tri.max() < nv and edge.max() < nv, 'index out of range'
    height, width = np.ptp(v[:, 2]), np.ptp(v[:, 0])
    assert height == pytest.approx(0.5408, abs=0.002), 'axis 2 is not height — not Z-up'
    assert width > height
    assert v[:, 2].min() > -0.02, 'feet are not on the ground in the viewer frame'


# ── the card's first impression ─────────────────────────────────────────────
@needs_asset
def test_previews_follow_the_sheet_angle_order():
    """A card shows previews[0]. Sorting the folder alphabetically makes that
    'back.png', so the library card led with the back of the creature's head."""
    pv = PML.get(ASSET)['previews']
    assert pv, 'no previews recorded'
    assert os.path.basename(pv[0]) == 'front_full.png', pv[:3]
    ids = PML.view_ids(ASSET)
    got = [os.path.splitext(os.path.basename(p))[0] for p in pv]
    assert got[: len(ids)] == ids, 'preview order diverged from the sheet angle plan'


# ── path resolution ─────────────────────────────────────────────────────────
@needs_asset
def test_every_view_resolves_a_depth_and_index_pass():
    """A control pass that silently resolves to None turns into 'the model ignored
    the depth map' three layers downstream."""
    for vid in PML.view_ids(ASSET):
        assert PML.beauty_path(ASSET, vid), 'no beauty for %s' % vid
        assert PML.pass_path(ASSET, vid, 'depth'), 'no depth for %s' % vid
        assert PML.pass_path(ASSET, vid, 'index'), 'no index for %s' % vid


def test_pass_kind_is_validated():
    """A typo'd pass kind must raise, not return None — None is indistinguishable
    from 'that view was never rendered'."""
    with pytest.raises(ValueError):
        PML.pass_path(ASSET, 'front_full', 'dpeth')


# ── the normal-pass channel-naming defect ───────────────────────────────────
def _exr_channels(path):
    """Channel names straight out of the OpenEXR header.

    Deliberately a hand-rolled 40-line header walk rather than cv2: the defect below
    IS the channel naming, and the test venv carries only pytest — a test that skips
    when cv2 is absent would silently stop guarding the thing it exists for."""
    with open(path, 'rb') as f:
        assert f.read(4) == b'\x76\x2f\x31\x01', 'not an EXR: %s' % path
        f.read(4)
        while True:
            name = b''
            while True:
                c = f.read(1)
                if c in (b'\x00', b''):
                    break
                name += c
            if not name:
                return []
            typ = b''
            while True:
                c = f.read(1)
                if c in (b'\x00', b''):
                    break
                typ += c
            size = struct.unpack('<i', f.read(4))[0]
            data = f.read(size)
            if name == b'channels':
                out, i = [], 0
                while i < len(data):
                    j = data.index(b'\x00', i)
                    cn = data[i:j].decode()
                    if not cn:
                        break
                    i = j + 1 + 16
                    out.append(cn)
                return out


@needs_asset
def test_normal_passes_carry_rgb_named_channels():
    """THE DEFECT: Blender's Normal socket is a VECTOR, so wired straight into a
    File Output it writes EXR channels named X/Y/Z. cv2 looks for R/G/B and hands
    back a 2-plane array, which passes_io correctly refuses to treat as a normal —
    so all 16 normal passes were unusable while sitting on disk looking perfectly
    fine. prop_mesh/pass_lib.rgb_named_socket() splits and recombines as colour;
    the sheet script had re-implemented the wiring without it."""
    bad = {}
    for vid in PML.view_ids(ASSET):
        np_path = PML.pass_path(ASSET, vid, 'normal')
        if not np_path:
            continue
        chans = set(_exr_channels(np_path))
        if not {'R', 'G', 'B'} <= chans:
            bad[vid] = sorted(chans)
    assert not bad, 'normal EXRs not RGB-named (unreadable by passes_io/cv2): %s' % bad


@needs_asset
def test_depth_and_index_passes_are_value_channels():
    """Depth and IndexOB are Value sockets and must come out as R/G/B triples. If
    one of them ever appears as X/Y/Z it means someone wired a vector into that
    slot, and every depth number downstream is a component of something else."""
    for vid in PML.view_ids(ASSET)[:4]:
        for kind in ('depth', 'index'):
            chans = set(_exr_channels(PML.pass_path(ASSET, vid, kind)))
            assert {'R', 'G', 'B'} <= chans, '%s/%s channels: %s' % (vid, kind, sorted(chans))


@needs_asset
def test_sheet_paths_point_into_the_asset_not_the_build_tree():
    """Registration REWRITES the sheet's absolute paths. Left alone they point at
    the LoRA working tree the trainer is entitled to delete, so the asset would
    quietly depend on a directory outside itself."""
    sh = PML.sheet(ASSET) or {}
    root = os.path.join(PML.ROOT, PML.get(ASSET)['dir'])
    for v in sh.get('views') or []:
        b = v.get('beauty')
        if b:
            assert b.startswith(root), 'sheet still points outside the asset: %s' % b
