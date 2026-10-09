#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stills — the content credential is applied to the sheets and stills that ship.

    scripts/run_tests.sh tests/test_stills_seal.py

Three delivery sites: char2d's turnaround.png and demo.mp4 (``run_char2d``), the per-cell
contact sheet (``step_finalize_sheet``) and the Picture Studio derived PNGs (``_pe_worker``).
Only the contact sheet can be called in a test — the other two need Blender/Comfy and a live
job — so for those the proof is scripts/check_seal_hooks.py, run here as a test. The seal
itself is proven in tests/test_provenance_seal.py; what is asserted here is the wiring: the
FINAL path, once, under the pipeline name that site claims.
"""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from zyg_workflows import contact_sheet_pipeline as _csp
from zyg_workflows import contact_sheet_pipeline_steps as S
from zyg_workflows import provenance_seal
from zyg_workflows.bin import exe

_WORKFLOWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(os.path.dirname(_WORKFLOWS))
_CHECKER = os.path.join(_WORKFLOWS, 'scripts', 'check_seal_hooks.py')


@pytest.fixture
def seals(monkeypatch):
    """Record every seal call instead of signing; returns the list of (path, kwargs)."""
    calls = []

    def _record(path, **kwargs):
        calls.append((str(path), kwargs))
        return {'ok': None, 'skipped': 'test'}

    monkeypatch.setattr(provenance_seal, 'seal', _record)
    return calls


def _png(tmp_path, name):
    """A 64x64 PNG from ffmpeg's test source — the smallest real image input."""
    ffmpeg = exe('ffmpeg', required=False)
    if not ffmpeg:
        pytest.skip('ffmpeg is not installed on this machine')
    out = str(tmp_path / name)
    subprocess.run(
        [ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=1', '-frames:v', '1', out],
        check=True,
        timeout=120,
    )
    assert os.path.isfile(out), out
    return out


def _check(path, func):
    """scripts/check_seal_hooks.py on one function; returns its stdout."""
    proc = subprocess.run(
        [sys.executable, _CHECKER, path, func],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f'{proc.stdout}{proc.stderr}'
    return proc.stdout.strip()


def test_finalize_sheet_seals_the_sheet(tmp_path, monkeypatch, seals):
    """step_finalize_sheet seals the composited master sheet it writes."""
    cell = _png(tmp_path, 'cell.png')
    sheet = str(tmp_path / 'sheet.png')
    monkeypatch.setenv('ZYG_CONTACT_SHEET_MIN_CELLS', '1')
    monkeypatch.setattr(_csp, 'master_sheet_path_part', lambda char_id, part: str(tmp_path / f'page_{part}.png'))
    monkeypatch.setattr(_csp, '_stitch_cell_images', lambda *a, **k: open(a[1], 'wb').close())
    monkeypatch.setattr(_csp, '_composite_sheet_stack', lambda pages, out, **k: open(out, 'wb').close())
    monkeypatch.setattr(_csp, 'write_manifest', lambda *a, **k: None)

    # step_finalize_sheet reads only these six attributes off the run; a namespace
    # keeps the test to the fields under test instead of CellRun's 21 required ones.
    run = SimpleNamespace(char_id='testchar', log_fn=None, progress_job=None, base_seed=1, anchor_family='x')
    out = S.step_finalize_sheet(
        run,
        out_path=sheet,
        aset='front',
        total=1,
        gutter=8,
        cell_paths=[cell],
        cell_angles=['front'],
        anchor_face=None,
        cell_plan={},
        failures=0,
        pose_ready=False,
        on_cell_progress=None,
    )

    assert out == sheet
    assert [p for p, _ in seals] == [sheet]
    assert seals[0][1]['pipeline'] == 'contact_sheet'
    assert seals[0][1]['run_id'] == 'testchar'


def test_char2d_hook_is_in_place():
    """run_char2d writes turnaround.png and demo.mp4 — Blender and Comfy only, so the checker proves it."""
    src = os.path.join(_WORKFLOWS, 'src', 'zyg_workflows', 'pipeline_char2d.py')
    assert _check(src, 'run_char2d') == 'OK pipeline_char2d.py:run_char2d'


def test_contact_sheet_hook_is_in_place():
    src = os.path.join(_WORKFLOWS, 'src', 'zyg_workflows', 'contact_sheet_pipeline_steps.py')
    assert _check(src, 'step_finalize_sheet') == 'OK contact_sheet_pipeline_steps.py:step_finalize_sheet'


def test_picture_studio_hook_is_in_place():
    """_pe_worker needs a live job and Comfy/rembg, so the checker proves its three branches."""
    src = os.path.join(_REPO, 'packages', 'dashboard', 'src', 'zyg_dashboard', 'bp_picture_studio.py')
    if not os.path.isfile(src):
        pytest.skip('the dashboard package is not checked out here')
    assert _check(src, '_pe_worker') == 'OK bp_picture_studio.py:_pe_worker'


def test_hooked_modules_import():
    """A seal import that breaks a delivery module would take the pipeline with it."""
    from zyg_workflows import pipeline_char2d

    assert pipeline_char2d._seal is provenance_seal
    assert S._seal is provenance_seal


def test_picture_studio_module_imports():
    """The dashboard blueprint pulls in all of crewai_web_gui, so it only runs where that is installed.

    crewai_web_gui is imported first on purpose: it and the bp_* modules form a circular
    contract whose bottom block registers every blueprint, so importing bp_picture_studio
    on its own leaves that module half-initialised and raises AttributeError.
    """
    try:
        import zyg_dashboard.crewai_web_gui  # noqa: F401  the shared namespace the blueprint imports back

        from zyg_dashboard import bp_picture_studio as ps
    except (ModuleNotFoundError, FileNotFoundError, RuntimeError) as exc:
        pytest.skip(f'crewai_web_gui needs something this environment has not got: {exc}')
    assert ps._seal is provenance_seal
