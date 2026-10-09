# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""light_lamps_env — the server half of the Lighting family (2026-09-07).

It serves two small libraries of files the browser cannot read off disk:

  data/assets/mesh_packs/hdri/*.hdr   1k equirectangular skies, CC0 1.0,
                                      Poly Haven (https://polyhaven.com/license)
  data/assets/mesh_packs/ies/*.ies    IESNA LM-63 photometric profiles, MIT,
                                      the three.js repository's examples/ies
                                      (source: https://ieslibrary.com)

Each folder carries its own License.txt and PROVENANCE.json (source URL, byte
size, sha256 per file); `list` / `ies_list` report the licence line with the
items so the tab can toast it. Stdlib only — no third-party imports.

ROUTES maps an op to fn(payload, method) and returns a dict (JSON) or a tuple
(bytes, mime, filename) that the server sends as a download. Reached at
/inspect/api/architecture/ext/light_lamps_env/<op>; reloaded on file change.

The `name` of a request is never joined onto a path: it is looked up in the
directory listing this module builds itself, so nothing outside these two
folders can ever be read through here.
"""

from __future__ import annotations

import json
import math
import os
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRI_DIR = os.path.join(HERE, 'data', 'assets', 'mesh_packs', 'hdri')
IES_DIR = os.path.join(HERE, 'data', 'assets', 'mesh_packs', 'ies')

HDRI_LICENCE = 'CC0 1.0, Poly Haven, https://polyhaven.com/license'
IES_LICENCE = 'MIT, three.js examples/ies (profiles from ieslibrary.com)'

# a human label per file, when PROVENANCE.json has one
_MAX_BYTES = 40 * 1024 * 1024


def _provenance(folder: str) -> dict:
    path = os.path.join(folder, 'PROVENANCE.json')
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            doc = json.load(fh)
    except Exception:  # noqa: BLE001
        return {}
    return {str(f.get('name')): f for f in (doc.get('files') or []) if f.get('name')}


def _index(folder: str, ext: str) -> dict:
    """{name: absolute path} for every file of that extension actually on disk.
    The only place a name is turned into a path — the fence for every read."""
    out = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for fn in names:
        if not fn.lower().endswith(ext):
            continue
        p = os.path.join(folder, fn)
        if os.path.isfile(p):
            out[fn[: -len(ext)]] = p
    return out


def _items(folder: str, ext: str) -> list:
    prov = _provenance(folder)
    items = []
    for name, path in _index(folder, ext).items():
        meta = prov.get(name) or {}
        items.append(
            {
                'name': name,
                'file': os.path.basename(path),
                'kb': int(round(os.path.getsize(path) / 1024.0)),
                'label': meta.get('label') or name.replace('_', ' '),
                'url': meta.get('url') or '',
            }
        )
    return items


def _send(folder: str, ext: str, mime: str, payload, method):
    name = str((payload or {}).get('name') or '').strip()
    idx = _index(folder, ext)
    if name not in idx:  # the fence: a name is only ever a key
        return {'error': 'unknown file: %s' % name[:60], 'code': 404, 'have': sorted(idx.keys())}
    path = idx[name]
    if os.path.getsize(path) > _MAX_BYTES:
        return {'error': 'file too large', 'code': 413}
    with open(path, 'rb') as fh:
        return (fh.read(), mime, name + ext)


def hdri_list(payload, method):
    return {'ok': True, 'licence': HDRI_LICENCE, 'items': _items(HDRI_DIR, '.hdr')}


def hdri(payload, method):
    return _send(HDRI_DIR, '.hdr', 'image/vnd.radiance', payload, method)


def ies_list(payload, method):
    return {'ok': True, 'licence': IES_LICENCE, 'items': _items(IES_DIR, '.ies')}


def ies(payload, method):
    return _send(IES_DIR, '.ies', 'text/plain; charset=utf-8', payload, method)


def ies_info(payload, method):
    """The parsed photometry of one profile — the SAME arithmetic the tab's JS
    parser does, so the assistant's set_ies and the icon agree on the numbers."""
    name = str((payload or {}).get('name') or '').strip()
    idx = _index(IES_DIR, '.ies')
    if name not in idx:
        return {'error': 'unknown profile: %s' % name[:60], 'code': 404, 'have': sorted(idx.keys())}
    with open(idx[name], 'r', encoding='utf-8', errors='replace') as fh:
        ph = parse_ies(fh.read())
    ph['name'] = name
    ph.pop('cd', None)  # the candela table is big; the tab reads the file itself
    return {'ok': True, 'photometry': ph}


# ── IESNA LM-63 ─────────────────────────────────────────────────────────────
def parse_ies(text: str) -> dict:
    """Parse an IESNA LM-63 file (1986/1991/1995/2002 all share this body).

    After the keyword header comes a TILT= line, then a free-running stream of
    numbers wrapped over as many lines as the writer felt like:

        lamps  lumens_per_lamp  multiplier  n_vert  n_horiz  photo_type  units  w l h
        ballast  future  watts
        <n_vert vertical angles>  <n_horiz horizontal angles>
        <n_horiz blocks of n_vert candela values>

    `lumens_per_lamp` is -1 for absolute photometry (our two samples), so the
    flux is integrated from the candela table instead: the zonal-cavity sum
    2*pi * I_avg * (cos t0 - cos t1) over each vertical band, averaged over the
    horizontal planes the file carries.

    Returns {tilt, lamps, lumens_per_lamp, mult, n_v, n_h, photo_type, units,
             watts, v_angles, h_angles, cd (flat, n_v*n_h, h-major), peak_cd,
             peak_angle, beam_angle, lumens, lumens_measured}.
    """
    lines = str(text).replace('\r', '').split('\n')
    i, tilt = 0, 'NONE'
    while i < len(lines):
        s = lines[i].strip().upper()
        if s.startswith('TILT='):
            tilt = s[5:].strip() or 'NONE'
            i += 1
            break
        i += 1
    else:
        raise ValueError('no TILT= line — this is not an LM-63 photometric file')
    if i >= len(lines):
        raise ValueError('no TILT= line — this is not an LM-63 photometric file')

    tok = []
    for chunk in ' '.join(lines[i:]).replace(',', ' ').split():
        try:
            tok.append(float(chunk))
        except ValueError as _exc:
            _zyg_log.warning('IES photometry token not numeric, the parsed body may be misaligned: %s', _exc)
    k = 0
    if tilt == 'INCLUDE':  # lamp-to-luminaire geometry + n angle/factor pairs
        k += 1
        n_pairs = int(tok[k])
        k += 1
        k += 2 * n_pairs

    def nxt(default=0.0):
        nonlocal k
        v = tok[k] if k < len(tok) else default
        k += 1
        return v

    lamps, lpl, mult = nxt(1), nxt(-1), nxt(1)
    n_v, n_h = int(nxt(0)), int(nxt(0))
    photo_type, units = int(nxt(1)), int(nxt(2))
    nxt()
    nxt()
    nxt()  # luminous opening w, l, h
    ballast, _future, watts = nxt(1), nxt(1), nxt(0)
    if n_v < 2 or n_h < 1 or len(tok) - k < n_v + n_h + n_v * n_h:
        raise ValueError('truncated LM-63 body: %d vertical x %d horizontal angles do not fit' % (n_v, n_h))
    v_ang = [tok[k + j] for j in range(n_v)]
    k += n_v
    h_ang = [tok[k + j] for j in range(n_h)]
    k += n_h
    scale = (mult or 1.0) * (ballast or 1.0)
    cd = [tok[k + j] * scale for j in range(n_v * n_h)]

    col0 = cd[:n_v]  # the vertical distribution at the first horizontal plane
    peak = max(col0) if col0 else 0.0
    pi = col0.index(peak) if col0 else 0
    beam = v_ang[-1] if v_ang else 0.0  # half-intensity HALF angle, degrees from nadir
    half = peak / 2.0
    for j in range(pi + 1, n_v):
        if col0[j] <= half:
            a0, a1, c0, c1 = v_ang[j - 1], v_ang[j], col0[j - 1], col0[j]
            beam = a1 if c0 == c1 else a0 + (c0 - half) * (a1 - a0) / (c0 - c1)
            break

    flux = 0.0
    for v in range(n_v - 1):
        t0, t1 = math.radians(v_ang[v]), math.radians(v_ang[v + 1])
        avg = sum((cd[h * n_v + v] + cd[h * n_v + v + 1]) / 2.0 for h in range(n_h)) / n_h
        flux += 2 * math.pi * avg * (math.cos(t0) - math.cos(t1))
    flux = abs(flux)
    declared = lamps * lpl if lpl and lpl > 0 else 0.0

    return {
        'tilt': tilt,
        'lamps': lamps,
        'lumens_per_lamp': lpl,
        'mult': mult,
        'ballast': ballast,
        'n_v': n_v,
        'n_h': n_h,
        'photo_type': photo_type,
        'units': units,
        'watts': watts,
        'v_angles': v_ang,
        'h_angles': h_ang,
        'cd': cd,
        'peak_cd': round(peak, 2),
        'peak_angle': v_ang[pi] if v_ang else 0.0,
        'beam_angle': round(beam, 2),
        'lumens': round(declared or flux, 1),
        'lumens_measured': round(flux, 1),
    }


ROUTES = {'list': hdri_list, 'hdri': hdri, 'ies_list': ies_list, 'ies': ies, 'ies_info': ies_info}
