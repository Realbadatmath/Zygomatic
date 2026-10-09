#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The licence registry is root-relative — and still resolves to the same files.

2026-10-05. ``model_licences.json`` is real configuration, not a generated index:
it is the only record of where each weight's licence was *read*, and the gate in
licence_provenance.py is worthless without it. So it ships inside the package —
which means it must not name one machine's disk. Every path in a ``source`` or
``note`` field is now written against a named root from ``zyg_workflows.paths``
(``ZYG_MODELS_ROOT/gnm/LICENSE``) and expanded by the loader.

These tests are the lock on both halves: that no absolute home path creeps back
into the file, and that expansion lands on exactly the path the pre-re-keying
file carried, so the provenance trail still points at a real LICENSE on disk.

    .venv-test/bin/python -m pytest tests/test_model_licences_rekey.py -q
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import licence_provenance as lp  # noqa: E402
from zyg_workflows import paths  # noqa: E402


def _raw_registry():
    with open(lp.REGISTRY_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _gnm_entry(weights):
    """The GNM head rule — the entry whose 'source' is a LICENSE in a local clone."""
    for rule in weights:
        if 'gnm_head.npz' in (rule.get('match') or []):
            return rule
    raise AssertionError('no gnm_head.npz rule in the registry')


def test_registry_file_names_no_absolute_home_path():
    """The regression this file exists for: a hand-added entry pasting its own
    machine's path back in. The whole file is checked, not just source/note."""
    with open(lp.REGISTRY_PATH, 'r', encoding='utf-8') as f:
        text = f.read()
    assert '/home/' not in text, 'model_licences.json carries an absolute home path again'
    assert '/Users/' not in text, 'model_licences.json carries an absolute home path again'


def test_source_resolves_to_the_same_absolute_path_as_before_rekeying():
    """ZYG_MODELS_ROOT/gnm/LICENSE must expand to the file the pre-re-keying
    registry named: ~/ai-models/gnm/LICENSE."""
    raw = _gnm_entry(_raw_registry()['weights'])
    assert raw['source'].startswith('ZYG_MODELS_ROOT/gnm/LICENSE'), raw['source']

    resolved = lp.load_registry()
    loaded = _gnm_entry(resolved['weights'])
    assert loaded['source'].startswith(str(paths.ZYG_MODELS_ROOT / 'gnm' / 'LICENSE'))
    if not os.environ.get('ZYG_MODELS_ROOT', '').strip():
        # The literal the file held before 2026-10-05, rebuilt from the default root.
        assert loaded['source'].startswith(str(Path.home() / 'ai-models' / 'gnm' / 'LICENSE'))

    # Only the path is rewritten; the prose after it is untouched.
    assert raw['source'].split('LICENSE', 1)[1] == loaded['source'].split('LICENSE', 1)[1]


def test_every_root_relative_path_expands_to_an_absolute_one():
    """No field may be left half-expanded: if a value names a root, the loaded
    value must be absolute, or the provenance trail points nowhere."""
    for rule in lp.load_registry()['weights']:
        for field in lp._PATH_FIELDS:
            val = rule.get(field)
            if not isinstance(val, str):
                continue
            assert not any(val.startswith(name) for name in lp._REGISTRY_ROOTS), (
                f'{field} still starts with an unexpanded root: {val[:80]}'
            )


def test_absolute_paths_are_still_accepted():
    """Back-compat: an entry written before the re-keying resolves unchanged, so a
    merge from model_licences_pending/ cannot silently corrupt its own source."""
    absolute = '/opt/weights/foo/LICENSE (read 2026-01-01)'
    assert lp.resolve_root_path(absolute) == absolute
    assert lp.resolve_root_path('') == ''
    assert lp.resolve_root_path(None) == ''


def test_expansion_does_not_touch_an_env_flag_name():
    """A note mentioning an env var that merely LOOKS like a root (no path after
    it, not in the map) must survive verbatim — these notes are read by humans."""
    note = 'env-gated ZYG_WAN_LIGHTNING, pinned by ZYG_SORTFORMER_MODEL'
    assert lp.resolve_root_path(note) == note


def test_matching_is_unaffected_by_the_rekeying():
    """The gate matches by filename glob, never by stored path, so re-keying must
    not move a single verdict."""
    reg = lp.load_registry()
    rule = lp._match_rule('gnm_head.npz', reg['weights'])
    assert rule is not None
    assert lp._record_status(rule) == lp.CLEARED
