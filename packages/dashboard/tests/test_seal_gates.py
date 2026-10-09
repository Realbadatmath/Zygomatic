# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The content-credential gate on the pipeline status API.

``/api/internal/pipeline/status/<id>`` is the listing zero-public reads to decide which file
a stranger is offered, so it is the last place an unsealed deliverable can be held back:
every record gains ``sealed``, and under ``ZYG_C2PA=strict`` an unsealed file is left out of
``output_files`` and named in ``unsealed_withheld`` instead.

WHY THE GATE IS COMPILED OUT OF THE SOURCE
------------------------------------------
``bp_pipeline_api`` cannot be imported in a checkout whose venv carries only the core set:
it imports ``crewai_web_gui``, which needs crewai, mediapipe, opencv and the production tree
(see tests/api/conftest.py, which skips for exactly that reason). :func:`_gate` therefore
parses the real file and compiles ``_seal_gate_outputs`` — a pure function — on its own, with
a stub seal module bound in its globals. It is the shipped source that runs, not a copy, so a
refactor that drops the gate fails here whether or not crewai is installed.

The route tests below exercise the same gate through the Flask client and skip, naming the
module, where that import is impossible.
"""

import ast
import json
import os
import socket
import threading
from pathlib import Path

import pytest

# bp_pipeline_api is a package since ee630e2; the gate lives in its creature module.
SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'zyg_dashboard' / 'bp_pipeline_api' / 'creature.py'
GATE = '_seal_gate_outputs'


class _StubSeal:
    """``provenance_seal``'s surface as the gate uses it, with a fixed verdict."""

    SUPPORTED = frozenset({'.mp4', '.png'})

    def __init__(self, sealed):
        self._sealed = sealed
        self.asked = []

    def is_sealed(self, path):
        self.asked.append(path)
        return self._sealed


def _gate(sealed):
    """``(callable, stub)`` — ``_seal_gate_outputs`` compiled straight out of the source."""
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'), filename=str(SOURCE))
    func = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == GATE), None)
    assert func is not None, f'{SOURCE.name} no longer defines {GATE} at module level'
    stub = _StubSeal(sealed)
    namespace = {'os': os, '_seal': stub}
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(SOURCE), 'exec'), namespace)  # noqa: S102
    return namespace[GATE], stub


def _entries():
    return [{'name': 'ep01_final.mp4', 'size_mb': 12.3, 'path': '/out/ep01_final.mp4'}]


def test_warn_lists_the_file_with_sealed_false(monkeypatch):
    monkeypatch.setenv('ZYG_C2PA', 'warn')
    gate, stub = _gate(sealed=False)
    kept, withheld = gate(_entries())
    assert kept == [{'name': 'ep01_final.mp4', 'size_mb': 12.3, 'sealed': False}]
    assert withheld is None, 'unsealed_withheld must not appear outside strict mode'
    assert stub.asked == ['/out/ep01_final.mp4']


def test_strict_withholds_the_unsealed_file(monkeypatch):
    monkeypatch.setenv('ZYG_C2PA', 'strict')
    gate, _stub = _gate(sealed=False)
    kept, withheld = gate(_entries())
    assert kept == []
    assert withheld == ['ep01_final.mp4']


def test_strict_lists_a_sealed_file_and_withholds_nothing(monkeypatch):
    monkeypatch.setenv('ZYG_C2PA', 'strict')
    gate, _stub = _gate(sealed=True)
    kept, withheld = gate(_entries())
    assert kept == [{'name': 'ep01_final.mp4', 'size_mb': 12.3, 'sealed': True}]
    assert withheld == []


def test_the_internal_path_key_never_reaches_the_response(monkeypatch):
    monkeypatch.setenv('ZYG_C2PA', 'warn')
    gate, _stub = _gate(sealed=True)
    kept, _withheld = gate(_entries())
    assert 'path' not in kept[0]


# ──────────────────────────────────────────────────────────────── the live route
@pytest.fixture(scope='module')
def dash_app():
    """crewai_web_gui with every watcher thread suppressed — see tests/api/conftest.py."""
    os.environ['CREWAI_PAGE_LOAD_DEBUG'] = '0'
    # Importing needs no secret, but signing the session the route tests carry does.
    os.environ.setdefault('FLASK_SECRET_KEY', 'a' * 64)
    suppressed = []
    real_start = threading.Thread.start

    def _blocked_start(self):
        if self.name.startswith('Otel'):
            return real_start(self)
        suppressed.append(self.name)
        return None

    threading.Thread.start = _blocked_start
    try:
        from zyg_dashboard import crewai_web_gui as g
    except (ModuleNotFoundError, FileNotFoundError, RuntimeError) as exc:
        pytest.skip(f'crewai_web_gui needs something this environment has not got: {exc}')
    finally:
        threading.Thread.start = real_start

    g.limiter.enabled = False
    socket.setdefaulttimeout(5)
    yield g


@pytest.fixture
def done_job(dash_app, tmp_path):
    """A finished pipeline whose single deliverable is an mp4 on disk."""
    mp4 = tmp_path / 'ep01_final.mp4'
    mp4.write_bytes(b'not really an mp4')
    pipeline_id = 'sealgate-test'
    dash_app._workflow_jobs[pipeline_id] = {
        'status': 'done',
        'department': 'kidsvideo',
        'started': '',
        'ended': '',
        'result': '',
        'output_dir': str(tmp_path),
        'final_output_file': str(mp4),
    }
    try:
        yield pipeline_id, mp4
    finally:
        dash_app._workflow_jobs.pop(pipeline_id, None)


def _status(dash_app, pipeline_id):
    with dash_app.app.test_client() as client:
        # /api/internal/pipeline/status/ is not one of the loopback-only bypasses, so an
        # anonymous client answers 401. Carry a session, exactly as tests/api/conftest.py does.
        with client.session_transaction() as s:
            s['user_role'] = 'admin'
            s['user_id'] = '__sealgate__'
            s['user_name'] = 'sealgate'
            s['_validity'] = dash_app.SESSION_VALIDITY_TOKEN
        response = client.get(f'/api/internal/pipeline/status/{pipeline_id}')
        assert response.status_code == 200, response.data[:200]
        return json.loads(response.data)


def test_route_in_warn_mode_reports_sealed_false(dash_app, done_job, monkeypatch):
    pipeline_id, _mp4 = done_job
    monkeypatch.setenv('ZYG_C2PA', 'warn')
    monkeypatch.setattr('zyg_dashboard.bp_pipeline_api._seal.is_sealed', lambda _p: False)
    payload = _status(dash_app, pipeline_id)
    assert [f['name'] for f in payload['output_files']] == ['ep01_final.mp4']
    assert payload['output_files'][0]['sealed'] is False
    assert 'unsealed_withheld' not in payload


def test_route_in_strict_mode_withholds_the_unsealed_deliverable(dash_app, done_job, monkeypatch):
    pipeline_id, _mp4 = done_job
    monkeypatch.setenv('ZYG_C2PA', 'strict')
    monkeypatch.setattr('zyg_dashboard.bp_pipeline_api._seal.is_sealed', lambda _p: False)
    payload = _status(dash_app, pipeline_id)
    assert payload['output_files'] == []
    assert payload['unsealed_withheld'] == ['ep01_final.mp4']
