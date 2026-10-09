#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  this module inherits test_creature_sheet.py's original top import
# block; the test modules import those names from here, so every one must stay bound.
"""Shared harness for the creature-sheet test package: the imports, the legacy-tree path
helper, the review-card isolation fixture, the pure-exec loader and the skip markers.

Moved verbatim out of tests/test_creature_sheet.py when it became this package.
"""

import importlib.util
import json
import os
import re

import pytest

from PIL import Image

import zyg_workflows
from zyg_workflows import creature_identity as cid
from zyg_workflows import creature_judge as cj
from zyg_workflows import creature_sheet_service as css
from zyg_workflows import creature_training_service as cts
from zyg_workflows import paths

_PKG = os.path.dirname(os.path.abspath(zyg_workflows.__file__))


def _crews(*parts):
    """A path in the legacy flat tree, whose GUI sources some tests below read as text.

    Those contracts belong with the dashboard and the public site; until they move there
    with their own copies, the text is read from the production tree and the test skips
    when that tree is not installed.
    """
    p = os.path.join(str(paths.ZYG_CREWS_ROOT), *parts)
    if not os.path.exists(p):
        pytest.skip('not in this checkout, it is a GUI source: %s' % p, allow_module_level=True)
    return p


@pytest.fixture(autouse=True)
def _isolate_review_cards(tmp_path, monkeypatch):
    """The review gate now queues an Agent Zero card when it parks. No test may
    write into the operator's live pending queue, so every test in this module
    gets its own."""
    rt = tmp_path / 'zero_queue'
    monkeypatch.setattr(cts, '_RUNTIME_DIR', str(rt))
    monkeypatch.setattr(cts, '_PENDING_PATH', str(rt / 'zpub_pending.json'))


def _pure(module_file, names):
    """Exec only the named top-level defs/assignments of a module whose import
    pulls Flask + the whole GUI (char_state_service, zpub_main_api). The
    functions under test are pure; the golden-suite venv has no Flask."""
    import ast
    import types

    own = os.path.join(_PKG, module_file)
    src = open(own if os.path.isfile(own) else _crews(module_file), encoding='utf-8').read()
    tree = ast.parse(src)
    keep = [
        n
        for n in tree.body
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names)
        or (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in names for t in n.targets))
    ]
    mod = types.ModuleType('pure_' + module_file.replace('.py', ''))
    import threading as _threading

    mod.__dict__.update({'os': os, 'json': json, 're': re, 'threading': _threading})
    # The code compiled here is the subset of top-level defs this test asked for, taken
    # from a source file shipped in this package — never from input. Importing the module
    # instead would pull in the whole service, which is what this harness exists to avoid.
    exec(  # noqa: S102  AST subset of a source file shipped in this package, see above
        compile(ast.Module(body=keep, type_ignores=[]), module_file, 'exec'), mod.__dict__
    )
    missing = [n for n in names if not hasattr(mod, n)]
    assert not missing, f'{module_file}: {missing} not found at top level'
    return mod


csvc = _pure(
    'char_state_service.py',
    ('_creature_stage_key', 'CREATURE_STAGE_ORDER', '_creature_derive_pipeline_stage', '_creature_refresh_external'),
)


# The judge reads its questions from one shared checklist book, config/vlm_checklists.json.
# The 2026-10-05 repository split filed that book with the GUI rather than with the judge
# that loads it, so on a plain checkout of this repository every judge question resolves to
# the empty list and the tests below assert against nothing. $ZYG_VLM_CHECKLISTS points
# creature_judge at a copy; without one there is no question to substitute, compare or arm,
# so these skip and say where the book should be.
needs_checklists = pytest.mark.skipif(
    not (cj.load_items(cj.CELL_CHECKLIST) and cj.load_items(cj.PAIR_CHECKLIST)),
    reason='no VLM checklist book — set $ZYG_VLM_CHECKLISTS (looked at %s)' % cj.CHECKLIST_PATH,
)

# imagehash is a declared dependency of this package (pyproject [project] dependencies) and
# is simply absent from the sandbox this was verified in. structural_check swallows the
# ImportError by design — a perceptual-hash miss must not fail a render — which turns the
# absence into an empty reasons list rather than an error, so the test has to check for it.
needs_imagehash = pytest.mark.skipif(
    importlib.util.find_spec('imagehash') is None,
    reason='imagehash is not installed here, so the phash arms of structural_check are dead',
)
