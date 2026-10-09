#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fetch the three model binaries this library needs but does not ship.

Three small weights files used to sit in the repository as tracked binaries. They are not
ours to redistribute — one of them is AGPL-3.0, which would reach into every consumer of a
checkout — so the repository now records only where they come from and what they must hash
to, and this script puts them on the machine:

* ``yolov8n.pt`` — Ultralytics YOLOv8 nano detector, from the Ultralytics GitHub release.
  **AGPL-3.0-only.** Using it in a service you distribute puts that service under AGPL
  unless you hold an Ultralytics commercial licence.
* ``face_landmarker.task`` / ``hand_landmarker.task`` — MediaPipe float16 landmark bundles
  from the Google model garden. **Apache-2.0**, attribution in NOTICE is enough.

Everything lands in ``paths.ZYG_MODELS_DIR`` (``$ZYG_MODELS_DIR``, default ``~/models``)
and is verified against a recorded sha256 before it is accepted: a weights file that has
quietly changed under the same URL is a silent behaviour change in every QC gate that reads
it, so a mismatch is a refusal, not a warning.

    scripts/fetch_models.py --list        what is wanted, where, and whether it is here
    scripts/fetch_models.py               fetch what is missing
    scripts/fetch_models.py --force       re-fetch everything
    scripts/fetch_models.py --check       verify what is on disk, download nothing

``--list`` and ``--check`` never touch the network. A fetch that cannot reach the network
says so and exits non-zero rather than leaving a half-written file behind.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import sys
import tempfile
import urllib.error
import urllib.request

from zyg_workflows import paths

#: name -> (url, sha256, licence, note). The hashes were taken from the copies that were
#: in production service on 2026-10-05; see the module docstring for why they are enforced.
MODELS = {
    'yolov8n.pt': (
        'https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt',
        'f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36',
        'AGPL-3.0-only',
        'Ultralytics YOLOv8n. AGPL-3.0: a service you distribute that uses these weights '
        'is AGPL too, unless you hold an Ultralytics commercial licence.',
    ),
    'face_landmarker.task': (
        'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
        '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff',
        'Apache-2.0',
        'MediaPipe Face Landmarker, float16 bundle. Apache-2.0: keep the notice.',
    ),
    'hand_landmarker.task': (
        'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
        'fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1',
        'Apache-2.0',
        'MediaPipe Hand Landmarker, float16 bundle. Apache-2.0: keep the notice.',
    ),
}

DEST = paths.ZYG_MODELS_DIR


def sha256(path: str, chunk: int = 1 << 20) -> str:
    """The sha256 of *path*, read in chunks because one of these is 6 MB and one is not."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def state(name: str) -> tuple[str, str]:
    """``(status, path)`` for *name* — one of ``missing``, ``ok``, ``WRONG HASH``."""
    path = os.path.join(str(DEST), name)
    if not os.path.isfile(path):
        return 'missing', path
    want = MODELS[name][1]
    return ('ok' if sha256(path) == want else 'WRONG HASH'), path


def online(host: str = 'github.com', port: int = 443, timeout: float = 4.0) -> bool:
    """Whether a TCP connection to *host* can be opened at all.

    Checked before the first download so that an offline machine gets one clear sentence
    instead of three stack traces.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def listing() -> int:
    """Print what is wanted, where it goes, its licence, and whether it is there."""
    print('destination: %s' % DEST)
    for name in sorted(MODELS):
        url, want, licence, note = MODELS[name]
        status, path = state(name)
        print('')
        print('%-24s %s' % (name, status))
        print('  licence  %s — %s' % (licence, note))
        print('  sha256   %s' % want)
        print('  url      %s' % url)
        print('  path     %s' % path)
    return 0


def check() -> int:
    """Verify what is on disk. Exit non-zero if anything is missing or has moved."""
    bad = 0
    for name in sorted(MODELS):
        status, path = state(name)
        print('%-24s %-10s %s' % (name, status, path))
        if status != 'ok':
            bad += 1
    if bad:
        print('\n%d of %d not usable — run scripts/fetch_models.py' % (bad, len(MODELS)))
    return 1 if bad else 0


def fetch(name: str, force: bool = False) -> bool:
    """Download *name* into :data:`DEST` unless it is already there and correct."""
    url, want, licence, note = MODELS[name]
    status, path = state(name)
    if status == 'ok' and not force:
        print('%-24s already here, hash matches' % name)
        return True

    os.makedirs(str(DEST), exist_ok=True)
    print('%-24s fetching %s' % (name, url))
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=str(DEST), prefix='.%s.' % name, suffix='.part')
        os.close(fd)
        # Only the two hosts in MODELS are ever contacted; the URLs are literals above.
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310  fixed https literals
            with open(tmp, 'wb') as out:
                shutil.copyfileobj(resp, out)
        got = sha256(tmp)
        if got != want:
            print('  REFUSED: sha256 %s, expected %s' % (got, want))
            print('  the file at that URL is not the one this repository was tested against')
            return False
        os.replace(tmp, path)
        tmp = None
        print('  ok %s' % path)
        print('  licence: %s — %s' % (licence, note))
        return True
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print('  FAILED: %s' % exc)
        return False
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--list', action='store_true', help='print the manifest and exit; no network')
    ap.add_argument('--check', action='store_true', help='verify what is on disk; no network')
    ap.add_argument('--force', action='store_true', help='re-download even when the hash matches')
    ap.add_argument('names', nargs='*', choices=sorted(MODELS) + [], help='only these (default: all)')
    args = ap.parse_args(argv)

    if args.list:
        return listing()
    if args.check:
        return check()

    names = args.names or sorted(MODELS)
    todo = [n for n in names if args.force or state(n)[0] != 'ok']
    if not todo:
        print('nothing to do — all %d present with the expected hash' % len(names))
        return 0
    if not online():
        print('no network: cannot fetch %s' % ', '.join(todo))
        print('run with --list to see the URLs, or copy the files into %s by hand' % DEST)
        return 2

    ok = all(fetch(n, force=args.force) for n in todo)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
