# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Suite-wide setup: the test database, and a way to swap a submodule out from under a caller."""

import os
import sys

import pytest

import zyg_workflows
from zyg_workflows import pgdb

# Every pytest process writes the TEST database, never production. The DSN is derived from
# the package's own default so a machine whose cluster lives elsewhere only has to say so in
# one place — and $ZYG_PG_DSN still wins, for a CI service container.
TEST_DSN = pgdb.DEFAULT_DSN.replace('/zygomatic?', '/zygomatic_test?')
os.environ.setdefault('ZYG_PG_DSN', TEST_DSN)


@pytest.fixture
def stub_module(monkeypatch):
    """Replace ``zyg_workflows.<name>`` with *obj* for the duration of one test.

    ``sys.modules`` alone is not enough, and the difference is silent. The call sites under
    test import lazily with ``from zyg_workflows import x as X``, and once that submodule has
    been imported anywhere in the process, ``zyg_workflows.x`` is a real **attribute** of the
    package — so the import machinery never consults ``sys.modules`` again and a stub left
    there is simply ignored. Whether a test saw its own stub then depended on which other
    file ran first, which is how a suite that passes one file at a time fails as a whole. So
    both are set, and monkeypatch undoes both.

        stub_module('_comfy_client', types.SimpleNamespace(submit=...))
        stub_module('voice_stt', None)   # None -> the import raises ImportError
    """

    def stub(name, obj):
        monkeypatch.setitem(sys.modules, 'zyg_workflows.' + name, obj)
        if obj is None:
            monkeypatch.delattr(zyg_workflows, name, raising=False)
        else:
            monkeypatch.setattr(zyg_workflows, name, obj, raising=False)

    return stub
