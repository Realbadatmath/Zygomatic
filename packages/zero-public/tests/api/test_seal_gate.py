# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The content-credential gate on the public download.

``GET /download/<job_id>/<filename>`` is the moment a stranger takes the file home. Under
``ZYG_C2PA=strict`` nothing leaves it without a C2PA manifest: an unsealed deliverable of a
signable type answers 409 instead of the bytes. In the default ``warn`` mode the download is
untouched — the pipeline already logged whatever it could not sign, and a second manifest
read per download would only slow it down.

WHY THE BLUEPRINT IS REGISTERED ON A BARE APP
---------------------------------------------
``zero_public_server`` creates the real ``zpub-worker`` job runner on import (see the long
note in test_zero_public.py). The gate lives in one route of ``zpub_routes_public``, which
imports no worker, so the blueprint goes onto a throwaway Flask app instead — no thread, no
risk of claiming a live job. Thread.start is neutered around the import anyway, because the
handlers reached from here import lazily.
"""

from __future__ import annotations

import os
import tempfile
import threading

import pytest
from flask import Flask

os.environ.setdefault('ZPUB_LOG_PATH', os.path.join(tempfile.gettempdir(), 'apitest_zpub_seal_gate.jsonl'))

_real_start = threading.Thread.start


def _blocked_start(self):
    if self.name.startswith('Otel'):
        return _real_start(self)
    return None


threading.Thread.start = _blocked_start
try:
    from zyg_zero import zpub_routes_public as routes
finally:
    threading.Thread.start = _real_start


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A client for the download route, with one finished job holding an unsealed mp4."""
    mp4 = tmp_path / 'ep01_final.mp4'
    mp4.write_bytes(b'not really an mp4')
    monkeypatch.setattr(routes, '_load_job', lambda _job_id: {'status': 'done', 'output_dir': str(tmp_path)})
    monkeypatch.setattr(routes._seal, 'is_sealed', lambda _path: False)

    app = Flask(__name__)
    app.secret_key = 'seal-gate-test'
    app.register_blueprint(routes.bp)
    with app.test_client() as test_client:
        yield test_client


def test_strict_refuses_an_unsealed_deliverable(client, monkeypatch):
    monkeypatch.setenv('ZYG_C2PA', 'strict')
    response = client.get('/download/job-1/ep01_final.mp4')
    assert response.status_code == 409, response.data[:200]
    assert response.get_json() == {'error': 'deliverable is not sealed'}


def test_warn_serves_the_same_unsealed_deliverable(client, monkeypatch):
    monkeypatch.setenv('ZYG_C2PA', 'warn')
    response = client.get('/download/job-1/ep01_final.mp4')
    assert response.status_code == 200
    assert response.data == b'not really an mp4'


def test_strict_still_serves_a_sealed_deliverable(client, monkeypatch):
    monkeypatch.setenv('ZYG_C2PA', 'strict')
    monkeypatch.setattr(routes._seal, 'is_sealed', lambda _path: True)
    response = client.get('/download/job-1/ep01_final.mp4')
    assert response.status_code == 200


def test_strict_leaves_an_unsignable_type_alone(client, monkeypatch, tmp_path):
    """A .srt has nowhere to carry a manifest, so the gate must not withhold it."""
    monkeypatch.setenv('ZYG_C2PA', 'strict')
    (tmp_path / 'ep01.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n', encoding='utf-8')
    response = client.get('/download/job-1/ep01.srt')
    assert response.status_code == 200
