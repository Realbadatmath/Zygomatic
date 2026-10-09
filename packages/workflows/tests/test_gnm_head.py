#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Invariants of the GNM Head adoption (2026-08-09).

.venv-test carries pytest only — no numpy, no gnm — so these tests check what
stdlib CAN check: the licence record, the module's declared posture (no
tensorflow at module level; that dependency was deliberately refused), and the
build manifest's provenance. The numeric invariants (17821 verts, landmark
containment, expression deltas) live in `geom.gnm_head smoke`, which runs on
the production interpreter:

    /usr/bin/python3.12 -m zyg_workflows.geom.gnm_head smoke
"""

import ast
import json
import os

from zyg_workflows import paths

from tests import _tree

_MODULE = _tree.pkg('geom', 'gnm_head.py')
_REGISTRY = _tree.pkg('data', 'runtime', 'model_licences.json')
# The weights manifest is written by the provisioning run and lives with the weights, not
# with the source; without it there is nothing to check the registry against.
_MANIFEST = os.path.join(str(_tree.DATA), 'assets', 'gnm_head', 'manifest.json')


def _registry():
    with open(_REGISTRY, encoding='utf-8') as f:
        return json.load(f)


def _gnm_rule():
    for rule in _registry()['weights']:
        if any('gnm_head' in m for m in rule.get('match', [])):
            return rule
    return None


# ── licence record ──────────────────────────────────────────────────────────
def test_gnm_is_registered_commercial_with_a_source():
    rule = _gnm_rule()
    assert rule is not None, 'GNM has no licence registry entry'
    assert rule['commercial'] is True
    assert rule['licence'] == 'Apache-2.0'
    assert 'LICENSE' in rule['source'], 'entry must cite the read LICENSE, not a blog'


def test_gnm_licence_file_is_actually_apache_on_disk():
    """The registry claims in-clone verification — hold it to that."""
    path = str(paths.ZYG_MODELS_ROOT / 'gnm' / 'LICENSE')
    if not os.path.isfile(path):
        import pytest

        pytest.skip('GNM clone not present on this machine')
    with open(path, encoding='utf-8') as f:
        head = f.read(200)
    assert 'Apache License' in head and 'Version 2.0' in head


# ── module posture ──────────────────────────────────────────────────────────
def _module_tree():
    with open(_MODULE, encoding='utf-8') as f:
        return ast.parse(f.read())


def test_module_parses():
    assert _module_tree() is not None


def test_no_module_level_tensorflow_or_heavy_imports():
    """The install rule that kept tensorflow out of the shared 3.12 site must
    hold in code too: gnm_head may never import tensorflow, and numpy/gnm/torch
    must be lazy (function-level) so .venv-test and light callers can import
    the module without the scientific stack."""
    tree = _module_tree()
    top_imports = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_imports.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_imports.add(node.module.split('.')[0])
    for banned in ('tensorflow', 'numpy', 'torch', 'gnm', 'trimesh', 'cv2'):
        assert banned not in top_imports, f'{banned} imported at module level'
    # tensorflow must not be imported ANYWHERE in the module, even lazily —
    # the semantic samplers reach it only through gnm.shape.semantic_sampler,
    # inside the guarded import. AST sees every import; docstrings don't count.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith('tensorflow') for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or '').startswith('tensorflow')


def test_semantic_sampler_is_guarded_not_required():
    src = open(_MODULE, encoding='utf-8').read()
    assert 'def semantic_samplers' in src
    assert 'return None' in src.split('def semantic_samplers')[1][:800], (
        'semantic sampler import must degrade to None, never raise'
    )


# ── build provenance ────────────────────────────────────────────────────────
def test_manifest_records_provenance():
    if not os.path.isfile(_MANIFEST):
        import pytest

        pytest.skip('no build manifest yet (run: python3.12 -m zyg_workflows.geom.gnm_head build)')
    with open(_MANIFEST, encoding='utf-8') as f:
        m = json.load(f)
    assert m['licence'] == 'Apache-2.0'
    assert m['npz_sha256'], 'npz hash missing — provenance incomplete'
    assert m['num_vertices'] == 17821 and m['identity_dim'] == 253
    assert m['expression_dim'] == 383
    assert len(m['heads']) >= 2
    for h in m['heads']:
        assert h['glb_sha256'], f'{h["name"]}: GLB not hashed'


def test_manifest_vlm_check_never_fabricates():
    """House failure semantics: the VLM check is ok or skipped-with-reason —
    a missing judge must not appear as a pass."""
    if not os.path.isfile(_MANIFEST):
        import pytest

        pytest.skip('no build manifest yet')
    with open(_MANIFEST, encoding='utf-8') as f:
        m = json.load(f)
    chk = m.get('vlm_check')
    if chk is None:
        return  # build ran --no-render; nothing claimed
    assert chk['status'] in ('ok', 'skipped')
    if chk['status'] == 'skipped':
        assert chk.get('reason'), 'a skip must say why'
