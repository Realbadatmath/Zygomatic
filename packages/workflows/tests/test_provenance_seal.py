#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Invariants of the C2PA seal.

Built 2026-10-06, when every deliverable started carrying a content credential. Two
properties matter and neither is visible by looking at a file: that the credential is
really there and really verifies, and that a broken seal never costs a render. The
second one is why most of these tests are about what seal() does when it CANNOT sign.

The suite signs with a throwaway CA built in a temp directory — never with the operator's
key, which these tests must not be able to read.

    .venv/bin/python -m pytest tests/test_provenance_seal.py -q
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip('c2pa', reason='c2pa-python is not installed in this environment')

from zyg_workflows import bin as zbin  # noqa: E402
from zyg_workflows import provenance_seal as seal_mod  # noqa: E402

EXTENSIONS = ('.png', '.jpg', '.mp4', '.wav', '.mp3')


def _run(*argv):
    proc = subprocess.run(argv, capture_output=True, text=True)
    assert proc.returncode == 0, f'{argv[0]} failed: {proc.stderr[-2000:]}'


def _ffmpeg(ffmpeg, out, *args):
    _run(ffmpeg, '-loglevel', 'error', '-y', *args, str(out))


@pytest.fixture(scope='session')
def ca(tmp_path_factory):
    """A throwaway end-entity + root chain. Skips when openssl is not on this machine.

    A self-signed certificate is refused by the library, so the chain really has to be two
    certificates: the signer, issued by a CA that is itself the root.
    """
    openssl = shutil.which('openssl')
    if openssl is None:
        pytest.skip('openssl is not installed; cannot build a throwaway signing chain')
    d = tmp_path_factory.mktemp('c2pa_ca')
    _run(openssl, 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', str(d / 'ca.key'))
    _run(
        openssl, 'req', '-new', '-x509',
        '-key', str(d / 'ca.key'), '-out', str(d / 'ca.pem'),
        '-days', '30', '-subj', '/CN=test root/O=t/C=NL',
        '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
    )  # fmt: skip
    gen = subprocess.run(
        [openssl, 'ecparam', '-name', 'prime256v1', '-genkey', '-noout'], capture_output=True, check=True
    )
    pkcs8 = subprocess.run(
        [openssl, 'pkcs8', '-topk8', '-nocrypt', '-out', str(d / 'ee.key')],
        input=gen.stdout,
        capture_output=True,
    )
    assert pkcs8.returncode == 0, pkcs8.stderr.decode()[-2000:]
    _run(
        openssl, 'req', '-new',
        '-key', str(d / 'ee.key'), '-out', str(d / 'ee.csr'), '-subj', '/CN=test signer/O=t/C=NL',
    )  # fmt: skip
    (d / 'ee.ext').write_text(
        'basicConstraints=CA:FALSE\n'
        'keyUsage=critical,digitalSignature\n'
        'extendedKeyUsage=emailProtection\n'
        'subjectKeyIdentifier=hash\n'
        'authorityKeyIdentifier=keyid\n'
    )
    _run(
        openssl, 'x509', '-req', '-in', str(d / 'ee.csr'),
        '-CA', str(d / 'ca.pem'), '-CAkey', str(d / 'ca.key'), '-CAcreateserial',
        '-out', str(d / 'ee.pem'), '-days', '30', '-extfile', str(d / 'ee.ext'),
    )  # fmt: skip
    (d / 'chain.pem').write_bytes((d / 'ee.pem').read_bytes() + (d / 'ca.pem').read_bytes())
    return d


@pytest.fixture(scope='session')
def media(tmp_path_factory):
    """One tiny file per signable type, built once. Skips when ffmpeg is not installed."""
    try:
        ffmpeg = zbin.exe('ffmpeg')
    except zbin.MissingExecutable:
        pytest.skip('ffmpeg is not installed; cannot build test media')
    d = tmp_path_factory.mktemp('c2pa_media')
    video = ('-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=5')
    audio = ('-f', 'lavfi', '-i', 'sine=frequency=440')
    _ffmpeg(ffmpeg, d / 't.png', *video, '-frames:v', '1')
    _ffmpeg(ffmpeg, d / 't.jpg', *video, '-frames:v', '1')
    _ffmpeg(ffmpeg, d / 't.wav', *audio, '-t', '1')
    _ffmpeg(ffmpeg, d / 't.mp3', *audio, '-t', '1', '-c:a', 'libmp3lame')
    _ffmpeg(ffmpeg, d / 't.mp4', *video, *audio, '-t', '1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-c:a', 'aac')
    return d


@pytest.fixture
def signing(ca, monkeypatch):
    """Point the module at the throwaway chain, in warn mode, with no timestamp and no root."""
    monkeypatch.setenv('ZYG_C2PA', 'warn')
    monkeypatch.setenv('ZYG_C2PA_KEY', str(ca / 'ee.key'))
    monkeypatch.setenv('ZYG_C2PA_CERT_CHAIN', str(ca / 'chain.pem'))
    monkeypatch.setenv('ZYG_C2PA_TSA_URL', '')
    # Empty, not deleted: the default would be the operator's own root, which a test must
    # neither read nor depend on.
    monkeypatch.setenv('ZYG_C2PA_ROOT_CERT', '')
    return ca


@pytest.fixture
def copy(media, tmp_path):
    """A writable copy of one of the session media files — seal() signs in place."""

    def _copy(ext, name=None):
        dest = tmp_path / (name or f'deliverable{ext}')
        shutil.copy(media / f't{ext}', dest)
        return dest

    return _copy


# ── (a) the credential is really there ──────────────────────────────────────
@pytest.mark.parametrize('ext', EXTENSIONS)
def test_seal_signs_every_supported_type(signing, copy, ext):
    """Sign, then read it back with a fresh reader: Valid, and our own facts inside."""
    path = copy(ext)
    res = seal_mod.seal(path, pipeline='kidsvideo', run_id='run-7', models=[{'name': 'wan', 'sha256': 'ab'}])
    assert res['ok'] is True, res
    got = seal_mod.verify(path)
    assert got['sealed'] is True
    assert got['state'] == 'Valid', got
    assert got['provenance']['pipeline'] == 'kidsvideo'
    assert got['provenance']['run_id'] == 'run-7'
    assert got['manifest']['title'] == os.path.basename(str(path))
    assert seal_mod.is_sealed(path) is True


# ── (b) tamper-evidence is the whole point ──────────────────────────────────
def test_one_flipped_byte_invalidates_the_seal(signing, copy):
    path = copy('.png')
    assert seal_mod.seal(path, pipeline='stills')['ok'] is True
    raw = bytearray(path.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    path.write_bytes(bytes(raw))
    got = seal_mod.verify(path)
    assert got['state'] == 'Invalid', got


# ── (c)-(f) fail-safe: the file is never touched when we cannot sign ────────
def test_mode_off_skips_and_leaves_the_bytes_alone(signing, copy, monkeypatch):
    monkeypatch.setenv('ZYG_C2PA', 'off')
    path = copy('.png')
    before = path.read_bytes()
    res = seal_mod.seal(path, pipeline='stills')
    assert res['ok'] is None
    assert res['skipped'] == 'ZYG_C2PA=off'
    assert path.read_bytes() == before


def test_warn_mode_without_keys_skips_without_raising(signing, copy, monkeypatch, tmp_path):
    """The default mode. A missing key is a log line, never a broken render."""
    monkeypatch.setenv('ZYG_C2PA_KEY', str(tmp_path / 'nope.key'))
    monkeypatch.setenv('ZYG_C2PA_CERT_CHAIN', str(tmp_path / 'nope.pem'))
    path = copy('.mp4')
    before = path.read_bytes()
    logged = []
    res = seal_mod.seal(path, pipeline='kidsvideo', log_fn=logged.append)
    assert res['ok'] is None
    assert res['skipped'] == 'not configured'
    assert path.read_bytes() == before
    assert any('not configured' in line for line in logged), logged
    assert seal_mod.configured() is False


def test_strict_mode_without_keys_raises_sealerror(signing, copy, monkeypatch, tmp_path):
    monkeypatch.setenv('ZYG_C2PA', 'strict')
    monkeypatch.setenv('ZYG_C2PA_KEY', str(tmp_path / 'nope.key'))
    path = copy('.png')
    with pytest.raises(seal_mod.SealError):
        seal_mod.seal(path, pipeline='stills')


def test_unsupported_extension_is_skipped_not_failed(signing, tmp_path):
    """A subtitle track has nowhere to carry a manifest; that is not an error."""
    path = tmp_path / 'dialogue.srt'
    path.write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n')
    before = path.read_bytes()
    res = seal_mod.seal(path, pipeline='kidsvideo')
    assert res['ok'] is None
    assert res['skipped'] == 'unsupported extension .srt'
    assert path.read_bytes() == before


# ── (g) a re-encode names its master ────────────────────────────────────────
def test_seal_derived_records_the_master_as_an_ingredient(signing, copy):
    master = copy('.mp4', name='master.mp4')
    assert seal_mod.seal(master, pipeline='kidsvideo', run_id='run-9')['ok'] is True
    web = copy('.mp4', name='web.mp4')
    res = seal_mod.seal_derived(web, master, pipeline='kidsvideo', run_id='run-9')
    assert res['ok'] is True, res
    got = seal_mod.verify(web)
    assert got['state'] == 'Valid', got
    ingredients = got['manifest'].get('ingredients') or []
    assert [i.get('title') for i in ingredients] == ['master.mp4'], ingredients
    actions = [
        a['action']
        for assertion in got['manifest']['assertions']
        if assertion['label'].startswith('c2pa.actions')
        for a in assertion['data']['actions']
    ]
    assert 'c2pa.transcoded' in actions, actions


# ── (h) the CLI ─────────────────────────────────────────────────────────────
def test_cli_verify_prints_json_and_exits_zero(signing, copy):
    path = copy('.png')
    assert seal_mod.seal(path, pipeline='stills')['ok'] is True
    proc = subprocess.run(
        [sys.executable, '-m', 'zyg_workflows.provenance_seal', 'verify', str(path)],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert json.loads(proc.stdout)['sealed'] is True


# ── (i) trust is a property of the verifier ─────────────────────────────────
def test_trusted_only_when_the_root_is_configured(signing, copy, ca, monkeypatch):
    path = copy('.png')
    assert seal_mod.seal(path, pipeline='stills')['ok'] is True
    assert seal_mod.verify(path)['trusted'] is False
    monkeypatch.setenv('ZYG_C2PA_ROOT_CERT', str(ca / 'ca.pem'))
    assert seal_mod.verify(path)['trusted'] is True
