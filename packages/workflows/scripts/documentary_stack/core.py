# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared harness state: the venv re-exec, the result tape, and the asset finders.

Sections 1-15 and the 2026-08-25 anachronism block live in the sibling modules;
`runner.main` drives them in the original order."""

# E402: the __file__ re-anchor below has to run before the moved import block.
# F401: this module inherits the original file's whole top import block verbatim;
# json/subprocess/tempfile/_ast/paths are used by the sections that moved to the
# sibling modules, which re-import them from here.
# ruff: noqa: E402,F401

import os as _zyg_os

# This block moved out of scripts/test_documentary_stack.py verbatim, one
# directory deeper. Re-anchor the two dunders it reads instead of editing the
# moved lines: CREWS, the os.execv re-exec target and getLogger(__name__) all
# have to keep the values they had in the single-file harness.
__file__ = _zyg_os.path.join(
    _zyg_os.path.dirname(_zyg_os.path.dirname(_zyg_os.path.abspath(__file__))),
    'test_documentary_stack.py',
)
__name__ = '__main__'
del _zyg_os


import glob
import json
import os
import subprocess
import sys
import tempfile
import ast as _ast
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)
os.chdir(CREWS)

# ── Run under the same interpreter production runs under ──────────────────
# crewai_web_gui.py runs from agents/.venv/bin/python; that venv is where the
# ML stack actually lives. Re-exec rather than warn: a warning at the top of a
# 140-line report is read by nobody, and the failure mode it guards against is
# a quieter score, not a crash.
#
# Compare sys.prefix, NOT realpath(sys.executable): the venv's bin/python is a
# SYMLINK to /usr/bin/python3.12, so realpath collapses them and the guard
# never fires. The first version of this check was inert for exactly that
# reason. sys.prefix is the venv root when running inside it and the system
# prefix when not, which is the distinction that matters here.
_VENV_DIR = os.path.join(os.path.dirname(CREWS), '.venv')
_VENV_PY = os.path.join(_VENV_DIR, 'bin', 'python')
if (
    os.path.exists(_VENV_PY)
    and os.path.abspath(sys.prefix) != os.path.abspath(_VENV_DIR)
    and not os.environ.get('ZYG_TEST_NO_REEXEC')
):
    print(f'[re-exec] {sys.executable} -> {_VENV_PY} (production interpreter)')
    sys.stdout.flush()
    # -u so a long run streams instead of surfacing everything at exit.
    os.execv(_VENV_PY, [_VENV_PY, '-u', os.path.abspath(__file__)] + sys.argv[1:])  # noqa: S606  re-exec under the venv interpreter: no shell, argv is this file's own
FULL = '--full' in sys.argv
RESULTS = []


def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond), detail))
    print(f'{"PASS" if cond else "FAIL"}  {name}' + (f'  — {detail}' if detail else ''))
    return bool(cond)


def skip(name, why):
    RESULTS.append((name, None, why))
    print(f'SKIP  {name}  — {why}')


_NARRATION_CACHE = []


def _narration():
    """Newest narration mp3 that actually contains audio.

    "Newest" alone is not enough: a pipeline run with narration_enabled=False
    still writes a full-length narration track, and it is SILENT. Seven such
    placeholders from gate-validation runs sat at the top of this list and made
    test_level_to fail at -70.0 -> -70.0 LUFS — a real failure, but of the test
    corpus, not of audio_mix.level_to. A test that samples "the newest file"
    from a shared output tree has to say what it needs from that file.
    """
    if _NARRATION_CACHE:
        return _NARRATION_CACHE[0] or None
    cands = sorted(glob.glob('data/output/clips/*/*_narration.mp3'), key=os.path.getmtime, reverse=True)
    try:
        from zyg_workflows import audio_mix as _am
    except Exception:
        _NARRATION_CACHE.append(cands[0] if cands else None)
        return _NARRATION_CACHE[0]
    for c in cands[:12]:
        try:
            if _am.measure_lufs(c) > -40.0:
                _NARRATION_CACHE.append(c)
                return c
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    _NARRATION_CACHE.append(None)
    return None


def _frames(n=3):
    f = sorted(glob.glob('data/output/clips/*/flux_images/*.jpg'))
    return f[:n]
