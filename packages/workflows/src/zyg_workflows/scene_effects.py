#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Extract a JangaFX VDB pack into a padded frame sequence Blender can import.

This is the CPU-side half of the scene bridge.  ``blender_scripts/scene_build.py``
cannot do the extraction itself: the extractors live in ``vfx_volume_preview``,
which imports ``vfx_ingest`` -> Pillow, and Blender's bundled Python has numpy
but no PIL.  So the Blender script shells out to this module with the crews venv
(or is handed a ready sequence directory with ``--extract-dir``).

What it guarantees:

* the masters in ``_originals/`` are never modified — only read;
* frames land as ``f_0000.vdb … f_<n-1>.vdb``, the exact padded run
  ``vfx_volume_render.import_sequence`` expects (it builds its file list as
  ``f_%04d.vdb`` for ``i in range(n)``);
* the extraction happens ONCE — a ``cache.json`` next to the frames records the
  pack, the archive size and the frame count, and a second call returns
  immediately;
* it refuses to fill the disk.  These packs run 62 MB … 7 GB compressed and
  several GB unpacked, and this box sits at 98 % full, so an archive over
  ``MAX_ARCHIVE_BYTES`` needs an explicit ``--allow-big`` and every extraction
  is checked against the free space it needs plus a reserve.

    python3 scene_effects.py --pack SmallCampfireVDB.zip
    python3 scene_effects.py --pack Fire_01.rar --allow-big --max-frames 60
    python3 scene_effects.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
from zyg_workflows import paths as _zyg_paths  # noqa: E402

VDB_DIR = str(_zyg_paths.ZYG_DATA_ROOT / 'asset_libraries' / '_originals' / 'jangafx_embergen_vdb')
CACHE_DIR = os.path.join(HERE, 'data', 'runtime', 'vdb_cache')

# An archive bigger than this is not extracted without --allow-big: the two
# largest packs unpack to tens of GB and there are ~37 GB free on this machine.
MAX_ARCHIVE_BYTES = 2 * 1024**3
# Never leave the filesystem with less than this after an extraction.
FREE_RESERVE_BYTES = 5 * 1024**3
# Rough unpacked:archive ratio used when the container cannot report member
# sizes cheaply (RAR).  Deliberately pessimistic.
RAR_EXPANSION = 3.0

CACHE_NAME = 'cache.json'


class PackError(RuntimeError):
    """Anything that makes an extraction impossible or unsafe."""


# --------------------------------------------------------------------------
# naming
# --------------------------------------------------------------------------


def slug(pack: str) -> str:
    """``SmallCampfireVDB.zip`` -> ``smallcampfirevdb``.  Same rule as
    ``vfx_volume_preview._slug`` but without importing it (that module pulls in
    Pillow, which this path must not need)."""
    base = re.sub(r'\.(zip|rar|7z)$', '', os.path.basename(pack), flags=re.I)
    return re.sub(r'[^a-z0-9]+', '_', base.lower()).strip('_') or 'volume'


def available_packs() -> list:
    try:
        names = os.listdir(VDB_DIR)
    except OSError:
        return []
    return sorted(n for n in names if n.lower().endswith(('.zip', '.rar', '.7z')))


def archive_path(pack: str) -> str:
    """Absolute path of a pack, or raise ``PackError`` naming what there is."""
    if not isinstance(pack, str) or not pack.strip():
        raise PackError('pack must be a non-empty file name')
    pack = pack.strip()
    if os.path.basename(pack) != pack:
        raise PackError('pack %r must be a bare file name, not a path' % pack)
    path = os.path.join(VDB_DIR, pack)
    if not os.path.isfile(path):
        raise PackError(
            'unknown pack %r: not found in %s (have: %s)' % (pack, VDB_DIR, ', '.join(available_packs()) or 'nothing')
        )
    return path


def seq_dir_for(pack: str) -> str:
    return os.path.join(CACHE_DIR, slug(pack))


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------


def _read_cache(seq: str) -> dict:
    try:
        with open(os.path.join(seq, CACHE_NAME), 'r', encoding='utf-8') as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) else {}


def _cache_valid(seq: str, rec: dict) -> bool:
    n = rec.get('n')
    if not isinstance(n, int) or n < 1:
        return False
    # Spot-check rather than stat 200 files: first, last, middle.
    for i in (0, n // 2, n - 1):
        fp = os.path.join(seq, 'f_%04d.vdb' % i)
        if not os.path.isfile(fp) or os.path.getsize(fp) == 0:
            return False
    return True


def cached(pack: str):
    """``(seq_dir, n)`` if this pack is already extracted, else ``None``."""
    seq = seq_dir_for(pack)
    rec = _read_cache(seq)
    return (seq, int(rec['n'])) if _cache_valid(seq, rec) else None


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------


def _free_bytes(path: str) -> int:
    d = path
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    return shutil.disk_usage(d or '/').free


def _needed_bytes(archive: str, members: list) -> int:
    if archive.lower().endswith('.zip'):
        import zipfile

        want = set(members)
        with zipfile.ZipFile(archive) as zf:
            return sum(i.file_size for i in zf.infolist() if i.filename in want)
    total = os.path.getsize(archive) * RAR_EXPANSION
    return int(total)


def ensure_extracted(pack: str, allow_big: bool = False, max_frames: int = 0, log=None):
    """Extract ``pack``'s VDB frames once; return ``(seq_dir, n)``.

    ``max_frames`` strides the sequence (never truncates it) so a long sim can
    be brought in cheaply; a strided extraction is cached under its own count,
    so asking for the full run afterwards re-extracts.
    """
    say = log or (lambda *_a: None)
    archive = archive_path(pack)  # raises on an unknown pack
    size = os.path.getsize(archive)
    if size > MAX_ARCHIVE_BYTES and not allow_big:
        raise PackError(
            'pack %r is %.1f GB, over the %.1f GB limit; pass allow_big=True '
            '(--allow-big) if there is really room for it' % (pack, size / 1e9, MAX_ARCHIVE_BYTES / 1e9)
        )

    hit = cached(pack)
    if hit and (not max_frames or hit[1] <= max_frames):
        say('[fx] cached: %s (%d frames)' % (hit[0], hit[1]))
        return hit

    # Pillow-importing modules are only touched once we know we must extract.
    sys.path.insert(0, HERE)
    from zyg_workflows import vfx_volume_preview as VP  # noqa: N814

    members = VP.list_archive(archive)
    if not members:
        raise PackError('cannot list %s (a .rar needs unrar: %s)' % (pack, VP.unrar_bin() or 'not installed'))
    vdbs = sorted((m for m in members if m.lower().endswith('.vdb')), key=VP._frame_no)
    if not vdbs:
        raise PackError('%s holds no .vdb frames' % pack)
    picked = vdbs
    if max_frames and len(vdbs) > max_frames:
        stride = (len(vdbs) + max_frames - 1) // max_frames
        picked = vdbs[::stride]
        say('[fx] %d frames -> every %dth (%d)' % (len(vdbs), stride, len(picked)))

    need = _needed_bytes(archive, picked)
    free = _free_bytes(CACHE_DIR)
    if need + FREE_RESERVE_BYTES > free:
        raise PackError(
            '%s needs about %.1f GB unpacked and only %.1f GB is free '
            '(keeping %.0f GB in reserve)' % (pack, need / 1e9, free / 1e9, FREE_RESERVE_BYTES / 1e9)
        )

    seq = seq_dir_for(pack)
    raw = seq + '.raw'
    shutil.rmtree(raw, ignore_errors=True)
    shutil.rmtree(seq, ignore_errors=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    t0 = time.time()
    say('[fx] extracting %d frame(s) of %s (%.0f MB packed)…' % (len(picked), pack, size / 1e6))
    try:
        got = VP.extract_members(archive, picked, raw)
        os.makedirs(seq, exist_ok=True)
        for i, fp in enumerate(got):
            os.replace(fp, os.path.join(seq, 'f_%04d.vdb' % i))
    except BaseException:
        shutil.rmtree(raw, ignore_errors=True)
        shutil.rmtree(seq, ignore_errors=True)
        raise
    shutil.rmtree(raw, ignore_errors=True)

    n = len(got)
    rec = {
        'pack': pack,
        'slug': slug(pack),
        'n': n,
        'archive_bytes': size,
        'frames_in_archive': len(vdbs),
        'bytes': sum(os.path.getsize(os.path.join(seq, 'f_%04d.vdb' % i)) for i in range(n)),
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    with open(os.path.join(seq, CACHE_NAME), 'w', encoding='utf-8') as fh:
        json.dump(rec, fh, indent=2)
        fh.write('\n')
    say('[fx] %d frame(s), %.0f MB, %.0f s -> %s' % (n, rec['bytes'] / 1e6, time.time() - t0, seq))
    return seq, n


# --------------------------------------------------------------------------
# CLI — one JSON line is the contract, so scene_build.py can parse it
# --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(prog='scene_effects.py')
    ap.add_argument('--pack', default='', help='archive file name in %s' % VDB_DIR)
    ap.add_argument(
        '--allow-big', action='store_true', help='permit an archive over %.0f GB' % (MAX_ARCHIVE_BYTES / 1e9)
    )
    ap.add_argument('--max-frames', type=int, default=0, help='stride the sequence down to at most this many frames')
    ap.add_argument('--list', action='store_true', help='list the packs and exit')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)

    if args.list:
        print(json.dumps({'ok': True, 'packs': available_packs(), 'dir': VDB_DIR}))
        return 0
    if not args.pack:
        print(json.dumps({'ok': False, 'error': '--pack is required'}), flush=True)
        return 2
    try:
        seq, n = ensure_extracted(
            args.pack,
            allow_big=args.allow_big,
            max_frames=args.max_frames,
            log=None if args.quiet else (lambda m: print(m, file=sys.stderr, flush=True)),
        )
    except Exception as e:  # noqa: BLE001
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}), flush=True)
        return 1
    print(json.dumps({'ok': True, 'pack': args.pack, 'seq': seq, 'n': n}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
