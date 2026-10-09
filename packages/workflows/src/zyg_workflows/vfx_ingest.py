#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""VFX asset ingest — the visual sibling of pack_ingest.py.

Masters stay untouched in ``data/asset_libraries/_originals/<pack>/``; this
writes browser-playable WORKING COPIES into three new libraries and one sidecar
of metadata.  Re-runnable and idempotent by working-copy path, exactly like
``pack_ingest.py`` — re-running only fills gaps.

Three libraries, because they are three different KINDS of thing and mixing
them makes the rail unusable (the same argument that made `foley` a third audio
category rather than a thousand one-shots inside `sfx`):

  vfx_plates   real footage you composite — one row per clip, previewable
  vfx_sprites  sprite sheets / particle PNGs — one row per image
  vfx_volumes  VDB simulation PACKS — one row per pack, NOT per frame.  A pack
               is 100–250 volume files and up to 6.6 GB; it is an input to a
               render, not a clip, so it is listed and never extracted.

**Why a working copy is not cosmetic here.** The DOE masters are MPEG-2, which
no browser can decode — the preview pane would be permanently blank against the
master.  Audio ingest transcodes for uniformity; this one transcodes because the
alternative does not play at all.

Every record carries the three-gate state the licence ledger is built on:
``transform`` (none|dsp|model) + ``no_ai_training``.  Everything ingested here
is CC0 or public domain, so all of it is `model` — but the field exists because
the vendor tiers (ActionVFX, FX Elements, Coverr…) are `dsp` and will land in
the same libraries the day anyone clicks through their download pages by hand.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
LIBS = os.path.join(DATA, 'asset_libraries')
ORIG = os.path.join(LIBS, '_originals')

# The sidecar is a GENERATED index — every record is rebuilt by an ingest run and the
# `source` field names the build script that produced the clip, i.e. a path on the
# machine that ran it. It therefore lives with the rest of the runtime state under
# ZYG_DATA_ROOT, not inside the package. Restore an older one with
#   git show 918c8b7:src/zyg_workflows/data/runtime/asset_library_vfx_meta.json \
#     > "$ZYG_DATA_ROOT/runtime/asset_library_vfx_meta.json"
SIDECAR = str(paths.ZYG_DATA_ROOT / 'runtime' / 'asset_library_vfx_meta.json')

CATEGORIES = {
    'vfx_plates': {
        'label': 'Plates',
        'kind': 'video',
        'desc': 'Real footage to composite — fire, explosions, lava, smoke.',
    },
    'vfx_sprites': {'label': 'Sprites', 'kind': 'image', 'desc': 'Sprite sheets and particle textures for 2D effects.'},
    'vfx_volumes': {
        'label': 'Volumes',
        'kind': 'volume',
        'desc': 'VDB simulation packs — render your own element at any camera, resolution and depth.',
    },
    # In-house renders and R&D clips (Blender/Geometry Nodes tests, look-dev
    # takes) — ours, so no licence gate; they are here to be found and reused,
    # not because a pack shipped them. Added 2026-09-19 for the sand-letters
    # intro test.
    'vfx_experimental': {
        'label': 'Experimental',
        'kind': 'video',
        'desc': 'In-house renders and R&D clips — Blender tests, look-dev takes, motion experiments.',
    },
}

# ── pack definitions ────────────────────────────────────────────────────────
# `group` is the effect family the rail groups a pack's rows under. For volumes
# it is derived per archive; for plates it is derived from the film title.

JANGAFX_GROUPS = [
    (r'aerial|ground|gasoline|midair|mid_air|implosion', 'Explosions'),
    (r'fire|campfire', 'Fire'),
    (r'smoke|chimney|plume', 'Smoke'),
    (r'dust|grenade|shockwave|devil|tornado', 'Dust & wind'),
    (r'cloud', 'Clouds'),
]

PLATE_GROUPS = [
    (
        r'trinity|crossroads|sandstone|greenhouse|buster|tumbler|upshot|'
        r'teapot|redwing|plumbbob|hardtack|dominic|ranger|ivy',
        'Nuclear tests',
    ),
    (r'lava|kilauea|eruption|volcan', 'Volcanic'),
    (r'fire|burn|flashover|calorimetr', 'Fire research'),
]


def _group_for(name: str, table) -> str:
    low = name.lower()
    for pat, label in table:
        if re.search(pat, low):
            return label
    return 'Other'


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe(path: str) -> dict:
    """ffprobe → width/height/fps/duration. {} when it is not a media file."""
    r = _run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=width,height,r_frame_rate:format=duration',
            '-of',
            'json',
            path,
        ]
    )
    if r.returncode != 0:
        return {}
    try:
        d = json.loads(r.stdout or '{}')
    except ValueError:
        return {}
    st = (d.get('streams') or [{}])[0]
    fps = 0.0
    rate = st.get('r_frame_rate') or '0/1'
    try:
        num, _, den = rate.partition('/')
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    try:
        dur = float((d.get('format') or {}).get('duration') or 0)
    except (TypeError, ValueError):
        dur = 0.0
    return {'w': int(st.get('width') or 0), 'h': int(st.get('height') or 0), 'fps': round(fps, 3), 'dur': round(dur, 3)}


def load_sidecar() -> dict:
    if os.path.exists(SIDECAR):
        try:
            with open(SIDECAR, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('sidecar unreadable, continuing with empty metadata: %s', _exc)
    return {}


def save_sidecar(meta: dict, merge: bool = True) -> None:
    """Write the sidecar back, MERGING onto whatever is on disk right now.

    A plain full-dict write is what this file used to do, and it lost work
    twice in one afternoon:

      * `vfx_ingest.py --fix-dims` measured all 174 sprites while a volume
        preview build was running; the next pack to finish wrote back the copy
        it had read minutes earlier and every measurement went to zero.
      * later, some other writer holding a copy from before the build saved at
        16:39 and eight freshly built `preview` fields vanished — the mp4s were
        still on disk, the records simply stopped naming them.

    Neither writer touched the other's fields; they only disagreed about how
    old the rest of the file was. So the write is a per-record FIELD merge
    under an exclusive lock: the incoming record wins field by field, anything
    on disk that the incoming record does not mention is kept, and records the
    caller never loaded are left alone.

    That makes a field impossible to DELETE by omission — which is the right
    trade here, because no writer of this sidecar ever means to. A caller that
    wants a field gone sets it to '' (see `vfx_volume_preview.commit`), and
    `merge=False` is there for a deliberate whole-file rewrite."""
    os.makedirs(os.path.dirname(SIDECAR), exist_ok=True)
    lock = SIDECAR + '.lock'
    with open(lock, 'a+') as lf:
        try:
            import fcntl

            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError) as _exc:
            _zyg_log.warning('sidecar lock not acquired, writing unlocked: %s', _exc)
        out = meta
        if merge:
            cur = load_sidecar()
            out = dict(cur)
            for k, rec in meta.items():
                base = out.get(k)
                if isinstance(base, dict) and isinstance(rec, dict):
                    merged = dict(base)
                    merged.update(rec)
                    out[k] = merged
                else:
                    out[k] = rec
        tmp = SIDECAR + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=1, sort_keys=True)
        os.replace(tmp, SIDECAR)


def _libdir(cat: str) -> str:
    d = os.path.join(LIBS, cat)
    os.makedirs(d, exist_ok=True)
    return d


# ── plates: DOE nuclear test films ─────────────────────────────────────────
def ingest_doe(meta: dict, limit: int = 0, dry: bool = False) -> int:
    src = os.path.join(ORIG, 'doe_nuclear_test_films')
    man_p = os.path.join(src, 'MANIFEST.json')
    if not os.path.exists(man_p):
        _zyg_log.info('[vfx] no DOE manifest yet — skipping plates')
        return 0
    with open(man_p, encoding='utf-8') as f:
        man = json.load(f)
    out = _libdir('vfx_plates')
    done = 0
    for ident, rec in sorted(man.items()):
        if not rec.get('done'):
            continue
        master = os.path.join(src, rec['file'])
        if not os.path.exists(master):
            continue
        dest_name = f'doe_{ident.split(".")[-1]}.mp4'
        dest = os.path.join(out, dest_name)
        key = f'vfx_plates/{dest_name}'
        if os.path.exists(dest) and key in meta:
            continue
        if limit and done >= limit:
            break
        title = rec.get('title') or ident
        if dry:
            _zyg_log.info(f'[dry] plate {dest_name}  ←  {rec["file"]}  ({title})')
            done += 1
            continue
        _zyg_log.info(f'[vfx] transcoding {dest_name} ← {rec["file"]}')
        # veryfast/crf 20: these are 1940s-60s SD tape transfers; the grain is
        # the signal, so do not smooth it away with a slow preset and a high crf.
        r = _run(
            [
                exe('ffmpeg'),
                '-y',
                '-v',
                'error',
                '-i',
                master,
                '-c:v',
                'libx264',
                '-crf',
                '20',
                '-preset',
                'veryfast',
                '-pix_fmt',
                'yuv420p',
                '-c:a',
                'aac',
                '-b:a',
                '128k',
                '-movflags',
                '+faststart',
                dest,
            ]
        )
        if r.returncode != 0 or not os.path.exists(dest):
            _zyg_log.info(f'[vfx] TRANSCODE FAILED {dest_name}: {r.stderr[-300:]}')
            continue
        poster = os.path.join(out, dest_name.rsplit('.', 1)[0] + '.jpg')
        _run(
            [
                exe('ffmpeg'),
                '-y',
                '-v',
                'error',
                '-ss',
                '3',
                '-i',
                dest,
                '-frames:v',
                '1',
                '-vf',
                'scale=480:-2',
                poster,
            ]
        )
        p = probe(dest)
        meta[key] = {
            'cat': 'vfx_plates',
            'file': dest_name,
            'name': title,
            'pack_label': 'DOE nuclear test films',
            'group': _group_for(title, PLATE_GROUPS),
            'kind': 'video',
            'poster': os.path.basename(poster) if os.path.exists(poster) else '',
            'bytes': os.path.getsize(dest),
            'master': os.path.relpath(master, LIBS),
            'master_bytes': rec.get('bytes', 0),
            'master_md5': rec.get('md5', ''),
            'source': rec.get('source', ''),
            'license_id': 'cc0',
            'licence': rec.get('licence', ''),
            'transform': 'model',
            'no_ai_training': False,
            'eula_note': 'US Government work; archive.org item tagged CC0 1.0.',
            **p,
        }
        done += 1
        save_sidecar(meta)
    return done


# ── sprites: Kenney CC0 packs ──────────────────────────────────────────────
def ingest_kenney(meta: dict, dry: bool = False) -> int:
    src = os.path.join(ORIG, 'kenney_cc0')
    if not os.path.isdir(src):
        return 0
    out = _libdir('vfx_sprites')
    done = 0
    for zname in sorted(os.listdir(src)):
        if not zname.lower().endswith('.zip'):
            continue
        pack = zname[:-4].replace('kenney_', '').replace('-', ' ').title()
        try:
            zf = zipfile.ZipFile(os.path.join(src, zname))
        except (OSError, zipfile.BadZipFile) as e:
            _zyg_log.info(f'[vfx] bad zip {zname}: {e}')
            continue
        with zf:
            for info in zf.infolist():
                n = info.filename
                if info.is_dir() or not n.lower().endswith('.png'):
                    continue
                # Kenney ships the same art as loose PNGs and as a packed
                # spritesheet + preview; the loose PNGs are the usable layer.
                low = n.lower()
                if 'spritesheet' in low or low.endswith('preview.png'):
                    continue
                # Kenney's particle pack ships each sprite TWICE — once under
                # "PNG (Transparent)" and once under "PNG (Black background)",
                # same 96 filenames in both. The black-background copy is the
                # same art with the alpha baked against black, which is the one
                # thing a compositor does not want. Dropped deliberately, not
                # silently: without this the two folders overwrite each other
                # and the library reports 174 files from 270 with no complaint.
                if 'black background' in low:
                    continue
                # The pack slug MUST be in the filename. Both Kenney packs ship
                # a `smoke_01.png`-style naming, so a bare basename collides
                # across packs and one pack silently overwrites the other —
                # 270 source PNGs collapsed to 174 files the first time this
                # ran. Same failure as the 344-pack take-number collision.
                stem = re.sub(r'[^A-Za-z0-9_.-]+', '_', os.path.basename(n))
                slug = re.sub(r'[^a-z0-9]+', '', zname[:-4].replace('kenney_', '').lower())
                folder = re.sub(r'[^a-z0-9]+', '', os.path.dirname(n).lower()) or 'root'
                dest_name = f'kenney_{slug}_{folder}_{stem}'
                dest = os.path.join(out, dest_name)
                key = f'vfx_sprites/{dest_name}'
                if os.path.exists(dest) and key in meta:
                    continue
                if dry:
                    done += 1
                    continue
                with zf.open(info) as fsrc, open(dest, 'wb') as fdst:
                    fdst.write(fsrc.read())
                grp = os.path.dirname(n).split('/')[-1] or 'PNG'
                iw, ih = image_dims(dest)
                meta[key] = {
                    'cat': 'vfx_sprites',
                    'file': dest_name,
                    'name': os.path.splitext(os.path.basename(n))[0],
                    'pack_label': f'Kenney — {pack}',
                    'group': grp.title(),
                    'kind': 'image',
                    'bytes': os.path.getsize(dest),
                    'w': iw,
                    'h': ih,
                    'master': os.path.relpath(os.path.join(src, zname), LIBS),
                    'source': 'https://kenney.nl/assets/',
                    'license_id': 'cc0',
                    'licence': 'CC0 1.0 (kenney.nl/support: "public domain '
                    'licensed (CC0) … even in commercial projects")',
                    'transform': 'model',
                    'no_ai_training': False,
                    'eula_note': 'Attribution not required. Kenney logo is NOT CC0.',
                }
                done += 1
        save_sidecar(meta)
    return done


# ── volumes: JangaFX EmberGen VDB packs ────────────────────────────────────
def _archive_members(path: str) -> list:
    """Every member name in the archive. Listing only — never extracts.

    `7z l -ba -slt` rather than the column layout: a member name with a space in
    it breaks `ln.split()[-1]`, and -slt prints one `Path = <name>` per entry."""
    low = path.lower()
    try:
        if low.endswith('.zip'):
            with zipfile.ZipFile(path) as zf:
                return [i.filename for i in zf.infolist() if not i.is_dir()]
        if low.endswith('.rar') or low.endswith('.7z'):
            r = _run(['7z', 'l', '-ba', '-slt', path])
            if r.returncode != 0:
                return []
            names = [ln[7:].strip() for ln in r.stdout.splitlines() if ln.startswith('Path = ')]
            # -slt names the archive itself first for a rar; drop it.
            return [n for n in names if os.path.abspath(n) != os.path.abspath(path)]
    except Exception as e:  # noqa: BLE001 — one bad archive
        _zyg_log.info(f'[vfx] listing failed for {os.path.basename(path)}: {e!r}')
    return []


def _volume_shape(names: list) -> dict:
    """How many VOLUMES a pack really holds, and whether they are one
    simulation's frames or a set of separate elements.

    The old count was `len(names)` — every member of the archive — so the pane
    told you Cloud Pack held "16 volume files" when it holds ten clouds and six
    read-me/licence/project/preview files. Every pack was inflated by three to
    six, and the pack whose count mattered most was the worst.

    The frames-vs-set split is the same distinction the sprite rail makes, read
    the same way: strip the trailing number off each .vdb name and count the
    stems that are left. `embergen_fire_a_0…_100` is ONE stem, so it is 101
    frames of one fire. `cloud_01_variant_0000 … cloud_10_variant_0000` is TEN
    stems of one frame each, so it is ten separate clouds and calling them
    frames of an animation would be a lie the pane tells on every visit."""
    vdb = [os.path.basename(n) for n in names if n.lower().endswith('.vdb')]
    stems = {re.sub(r'[ _.-]*\d+\.vdb$', '', n, flags=re.I) for n in vdb}
    return {'frames': len(vdb), 'members': len(names), 'sims': len(stems) or 1}


def ingest_jangafx(meta: dict, dry: bool = False) -> int:
    src = os.path.join(ORIG, 'jangafx_embergen_vdb')
    man_p = os.path.join(src, 'MANIFEST.json')
    if not os.path.exists(man_p):
        return 0
    with open(man_p, encoding='utf-8') as f:
        man = json.load(f)
    done = 0
    for aname, rec in sorted(man.items()):
        if not rec.get('done'):
            continue
        path = os.path.join(src, aname)
        if not os.path.exists(path):
            continue
        key = f'vfx_volumes/{aname}'
        if key in meta:
            continue
        if dry:
            done += 1
            continue
        names = _archive_members(path)
        shape = _volume_shape(names)
        sample = names[:3]
        pretty = re.sub(r'(VDB)?\.(zip|rar)$', '', aname, flags=re.I)
        pretty = re.sub(r'_0?1$', '', pretty)
        pretty = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', pretty).replace('_', ' ').strip()
        meta[key] = {
            'cat': 'vfx_volumes',
            'file': aname,
            'name': pretty,
            'pack_label': 'JangaFX — EmberGen free VDBs',
            'group': _group_for(aname, JANGAFX_GROUPS),
            'kind': 'volume',
            'sample': sample,
            **shape,
            'bytes': rec.get('bytes', 0),
            'md5': rec.get('md5', ''),
            'master': os.path.relpath(path, LIBS),
            'source': rec.get('source_page', ''),
            'license_id': 'cc0',
            'licence': 'CC0 (jangafx.com: "These free VDB simulations are '
            'licensed as CC0 (Public Domain) so you are free to use '
            'them however you want!")',
            'transform': 'model',
            'no_ai_training': False,
            'eula_note': 'Archive is listed, never extracted — a pack is a render input, not a clip.',
        }
        done += 1
        save_sidecar(meta)
    return done


# ── sprite pixel dimensions ────────────────────────────────────────────────
def image_dims(path: str) -> tuple:
    """(w, h) of one PNG, or (0, 0). Pillow only — no decode of the pixels."""
    try:
        from PIL import Image
    except ImportError:
        return 0, 0
    try:
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:  # noqa: BLE001 — one bad sprite
        return 0, 0


def backfill_image_dims(meta: dict, force: bool = False) -> int:
    """Fill w/h on every sprite record that is missing them.

    The first sprite ingest never measured these — every image row went in with
    w=0 h=0 — so the preview caption printed a size for plates and nothing for
    sprites, and the rail could not tell a 512px particle from a 336px puff.
    Cheap to fix and cheap to re-run: Pillow reads the PNG header only."""
    n = 0
    for _key, rec in meta.items():
        if rec.get('kind') != 'image':
            continue
        if not force and int(rec.get('w') or 0) > 0:
            continue
        fp = os.path.join(LIBS, rec.get('cat') or '', rec.get('file') or '')
        w, h = image_dims(fp)
        if w and h:
            rec['w'], rec['h'] = w, h
            n += 1
    if n:
        save_sidecar(meta)
    return n


def backfill_volume_counts(meta: dict, log=print) -> int:
    """Recount every volume pack from its archive listing. Cheap (headers only)
    and idempotent; run it after this module's count rule changes."""
    n = 0
    for rec in meta.values():
        if rec.get('kind') != 'volume':
            continue
        path = os.path.join(LIBS, rec.get('master') or '')
        if not os.path.isfile(path):
            continue
        shape = _volume_shape(_archive_members(path))
        if not shape['frames']:
            continue
        if (rec.get('frames'), rec.get('sims')) == (shape['frames'], shape['sims']):
            continue
        log(f'  {rec.get("name")}: {rec.get("frames")} -> {shape["frames"]} volume(s), {shape["sims"]} sim(s)')
        rec.update(shape)
        n += 1
    if n:
        save_sidecar(meta)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--fix-counts', action='store_true', help='recount volume packs from their archives, then exit')
    ap.add_argument(
        '--fix-dims', action='store_true', help='measure w/h for sprite rows that are missing them, then exit'
    )
    ap.add_argument('--limit-plates', type=int, default=0, help='transcode at most N plates this run (0 = all)')
    ap.add_argument('--only', choices=['plates', 'sprites', 'volumes'], default=None)
    a = ap.parse_args(argv)

    meta = load_sidecar()
    if a.fix_dims:
        n = backfill_image_dims(meta)
        print(f'[vfx] measured {n} sprite(s)')
        return 0
    if a.fix_counts:
        n = backfill_volume_counts(meta)
        print(f'[vfx] recounted {n} volume pack(s)')
        return 0
    counts = {}
    if a.only in (None, 'volumes'):
        counts['volumes'] = ingest_jangafx(meta, a.dry_run)
    if a.only in (None, 'sprites'):
        counts['sprites'] = ingest_kenney(meta, a.dry_run)
    if a.only in (None, 'plates'):
        counts['plates'] = ingest_doe(meta, a.limit_plates, a.dry_run)
    if not a.dry_run:
        save_sidecar(meta)
    total = {c: sum(1 for r in meta.values() if r.get('cat') == c) for c in CATEGORIES}
    print(f'[vfx] added this run: {counts}')
    print(f'[vfx] library totals: {total}')
    print(f'[vfx] sidecar: {SIDECAR}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
