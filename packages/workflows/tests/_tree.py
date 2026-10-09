# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Where the tests find the things that are not in this repository.

This suite grew inside one flat production tree, where the library, the Flask GUI, the
ComfyUI workflow graphs and tens of gigabytes of asset data were siblings in a single
directory, and every test addressed them as ``<repo root>/<name>``. Three of those four now
live elsewhere: the library is the ``zyg_workflows`` package here, the GUI is the dashboard
repository, and the data and the graphs stay in the production tree because they are neither
source nor redistributable.

So a test asks here instead of guessing from ``__file__``:

* :data:`PKG` for this library's own source, when the test reads it as text;
* :func:`crews` for anything in the production tree (graphs, the GUI's sources);
* :func:`data` / :func:`output` for the asset and render trees.

The three functions skip — at module level when they are called at import time — rather than
fail when the production tree is not installed, so a clean checkout runs the part of the
suite that is about this library and says plainly what it left out.
"""

from __future__ import annotations

import os

import pytest

import zyg_workflows
from zyg_workflows import paths

#: This library's own source directory — the only root that is always present.
PKG = os.path.dirname(os.path.abspath(zyg_workflows.__file__))

CREWS = str(paths.ZYG_CREWS_ROOT)
DATA = str(paths.ZYG_DATA_ROOT)
OUTPUT = str(paths.ZYG_OUTPUT_ROOT)


def require(path: str) -> str:
    """Return *path*, or skip because what it names is not installed on this machine."""
    if not os.path.exists(path):
        pytest.skip(
            'not shipped with this repository — set ZYG_CREWS_ROOT to a tree that has it: %s' % path,
            allow_module_level=True,
        )
    return path


def crews(*parts: str) -> str:
    """A path in the production tree (``$ZYG_CREWS_ROOT``), or a skip."""
    return require(os.path.join(CREWS, *parts))


def data(*parts: str) -> str:
    """A path in the asset data tree (``$ZYG_DATA_ROOT``), or a skip."""
    return require(os.path.join(DATA, *parts))


def output(*parts: str) -> str:
    """A path in the render output tree (``$ZYG_OUTPUT_ROOT``), or a skip."""
    return require(os.path.join(OUTPUT, *parts))


def pkg(*parts: str) -> str:
    """A path inside this library — its source, or the small data files it does ship."""
    return require(os.path.join(PKG, *parts))


def instrument_samples() -> str:
    """The sampled-instrument library, or a skip.

    Its 65 MB index ships with the package because the licence trail is in it; the ~20 GB of
    one-shots the index points at does not, so an index alone renders nothing.
    """
    from zyg_workflows import melody_sampler

    lib = melody_sampler.LIB_DIR
    if not os.path.isdir(lib) or not os.listdir(lib):
        pytest.skip('the instrument samples are not on this machine: %s' % lib, allow_module_level=True)
    return lib
