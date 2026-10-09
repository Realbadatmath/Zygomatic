# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The scene bridge, checked from OUTSIDE Blender.

Nothing here builds a scene: ``blender_scripts/scene_build.py`` only runs under
``blender -b --python`` and the real proof of it is the probe render.  What a
plain pytest run CAN prove, and what these tests are for, is the seam:

  * the Blender script imports cleanly with no ``bpy`` — its ``import bpy`` is
    guarded exactly like ``arch_server_ext/render_offline_blender.py``, so the
    module can be linted, imported and introspected by anything in the crews
    venv.  An unguarded import would make every collector in ``tests/`` fail.
  * ``scene_effects`` refuses an unknown pack loudly, before it touches Pillow,
    the 32 GB of masters or the disk.
"""

import importlib.util
import os
import sys

import pytest

from tests import _tree
from zyg_workflows import scene_effects as SE


def _load_scene_build():
    path = _tree.pkg('blender_scripts', 'scene_build.py')
    spec = importlib.util.spec_from_file_location('scene_build_under_test', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scene_build_imports_without_bpy():
    assert 'bpy' not in sys.modules, 'this test only means something without bpy'
    mod = _load_scene_build()
    assert mod.bpy is None and mod.mathutils is None
    for name in ('main', 'place_effect', 'place_actor', 'probe', 'sequence_for', 'build_camera', 'set_timing'):
        assert callable(getattr(mod, name)), name


def test_scene_build_knows_where_the_crews_tree_is():
    mod = _load_scene_build()
    assert os.path.isfile(os.path.join(mod.HERE, 'scene_shot.py'))
    assert os.path.isfile(os.path.join(mod.EXT_DIR, 'render_offline_blender.py'))


def test_ensure_extracted_refuses_an_unknown_pack():
    with pytest.raises(SE.PackError) as exc:
        SE.ensure_extracted('NoSuchPack.zip')
    msg = str(exc.value)
    assert 'unknown pack' in msg
    assert SE.VDB_DIR in msg, 'the refusal must say where it looked'
    if not SE.available_packs():
        pytest.skip('the VDB pack library is not on this machine: %s' % SE.VDB_DIR)
    assert 'SmallCampfireVDB.zip' in msg, 'the refusal must say what there IS'


def test_ensure_extracted_refuses_a_path_for_a_pack_name():
    with pytest.raises(SE.PackError):
        SE.ensure_extracted('../../../etc/passwd')


def test_ensure_extracted_refuses_a_big_archive_without_allow_big():
    big = 'AerialExplosionVDB.zip'  # 7.1 GB, over MAX_ARCHIVE_BYTES
    if not os.path.isfile(os.path.join(SE.VDB_DIR, big)):
        pytest.skip('%s is not on this machine' % big)
    with pytest.raises(SE.PackError) as exc:
        SE.ensure_extracted(big)
    assert 'over the' in str(exc.value)


def test_slug_matches_the_cache_layout():
    assert SE.slug('SmallCampfireVDB.zip') == 'smallcampfirevdb'
    assert SE.slug('Fire_01.rar') == 'fire_01'
    assert SE.seq_dir_for('Fire_01.rar') == os.path.join(SE.CACHE_DIR, 'fire_01')
