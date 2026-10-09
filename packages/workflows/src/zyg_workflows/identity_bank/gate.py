# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""identity_bank — enrolment into the bank and the single-still identity gate."""

import logging as _zyg_logging
import os
import time

from zyg_workflows import pgdb

from .embedding import (
    DEFAULT_BACKEND,
    Z_FLOOR,
    Z_MIN_BANK,
    Z_MIN_STD,
    _FLOORS,
    _blob,
    _l2,
    _ledger_fallback,
    _ledger_gate,
    _log,
    _np,
    _run_id,
    _unblob,
    embed_face,
    embed_region,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.identity_bank')


# ── enrolment ────────────────────────────────────────────────────────────────
def enroll(
    char_id,
    style_profile,
    image_paths,
    backend=None,
    episode=None,
    render_id=None,
    box_fracs=None,
    device=None,
    log_fn=None,
    run_id=None,
):
    """Write normalised embeddings for `image_paths` into the bank.

    box_fracs: optional list parallel to image_paths (None entries = whole image).
    Returns {'ok', 'enrolled', 'backend', 'failed': [(path, error), ...], 'n_bank'}.
    """
    try:
        backend = backend or DEFAULT_BACKEND
        if isinstance(image_paths, str):
            image_paths = [image_paths]
        image_paths = [p for p in (image_paths or []) if p]
        if not image_paths:
            return {'ok': False, 'error': 'no_images', 'enrolled': 0}
        rows, failed = [], []
        for i, p in enumerate(image_paths):
            bf = None
            if box_fracs:
                try:
                    bf = box_fracs[i]
                except (IndexError, TypeError):
                    bf = None
            if not os.path.isfile(p):
                failed.append((p, 'missing'))
                continue
            r = (
                embed_face(p, backend='facenet', box_frac=bf, device=device, log_fn=log_fn)
                if backend == 'facenet'
                else embed_region(p, box_frac=bf, backend=backend, device=device, log_fn=log_fn)
            )
            if not r.get('ok'):
                failed.append((p, r.get('error')))
                continue
            rows.append(
                (
                    char_id,
                    style_profile,
                    episode,
                    render_id,
                    backend,
                    int(r['dim']),
                    _blob(r['embedding']),
                    p,
                    time.time(),
                )
            )
        if not rows:
            _log(log_fn, f'[identity_bank] enroll {char_id}/{style_profile}: 0 usable of {len(image_paths)}')
            return {'ok': False, 'error': 'no_usable_embeddings', 'enrolled': 0, 'backend': backend, 'failed': failed}
        with pgdb.connect() as con:
            with con.cursor() as cur:
                cur.executemany(
                    'INSERT INTO chars (char_id, style, episode, render_id, backend, dim, '
                    'embedding, src, ts) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    rows,
                )
            n = con.execute(
                'SELECT COUNT(*) FROM chars WHERE char_id=%s AND style=%s AND backend=%s',
                (char_id, style_profile, backend),
            ).fetchone()[0]
        _log(log_fn, f'[identity_bank] enrolled {len(rows)} -> {char_id}/{style_profile}/{backend} (bank={n})')
        return {'ok': True, 'enrolled': len(rows), 'backend': backend, 'failed': failed, 'n_bank': int(n)}
    except Exception as e:
        return {'ok': None, 'error': f'{type(e).__name__}: {e}', 'enrolled': 0}


def _bank(char_id, style_profile, backend):
    """(matrix, dim, srcs) of L2-normalised bank embeddings; empty matrix if none."""
    np = _np()
    with pgdb.connect() as con:
        rows = con.execute(
            'SELECT embedding, dim, src FROM chars WHERE char_id=%s AND style=%s AND backend=%s ORDER BY ts',
            (char_id, style_profile, backend),
        ).fetchall()
    if not rows:
        return np.zeros((0, 1), dtype=np.float32), 0, []
    dim = int(rows[0][1])
    mat = np.stack([_unblob(r[0], dim) for r in rows]).astype(np.float32)
    return mat, dim, [r[2] for r in rows]


def bank_backends(char_id, style_profile=None):
    """Which backends actually have embeddings for this character."""
    try:
        with pgdb.connect() as con:
            if style_profile:
                rows = con.execute(
                    'SELECT backend, COUNT(*) FROM chars WHERE char_id=%s AND style=%s GROUP BY backend',
                    (char_id, style_profile),
                ).fetchall()
            else:
                rows = con.execute(
                    'SELECT backend, COUNT(*) FROM chars WHERE char_id=%s GROUP BY backend', (char_id,)
                ).fetchall()
        return {r[0]: int(r[1]) for r in rows}
    except Exception:
        return {}


def bank_stats(char_id, style_profile, backend=None):
    """Centroid self-consistency stats — the distribution `check` z-scores against.

    Uses LEAVE-ONE-OUT cosines so the spread is not artificially tight.
    """
    try:
        np = _np()
        backend = backend or _pick_backend(char_id, style_profile)
        mat, dim, srcs = _bank(char_id, style_profile, backend)
        n = int(mat.shape[0])
        if n == 0:
            return {'ok': False, 'error': 'empty_bank', 'n_bank': 0, 'backend': backend}
        cen = _l2(mat.mean(axis=0))
        if n == 1:
            loo = np.array([1.0], dtype=np.float32)
        else:
            loo = []
            for i in range(n):
                other = _l2(np.delete(mat, i, axis=0).mean(axis=0))
                loo.append(float(np.dot(mat[i], other)))
            loo = np.asarray(loo, dtype=np.float32)
        return {
            'ok': True,
            'backend': backend,
            'n_bank': n,
            'dim': dim,
            'centroid': cen.tolist(),
            'loo_mean': float(loo.mean()),
            'loo_std': float(loo.std(ddof=0)),
            'loo_min': float(loo.min()),
            'srcs': srcs,
        }
    except Exception as e:
        return {'ok': None, 'error': f'{type(e).__name__}: {e}'}


def _pick_backend(char_id, style_profile):
    have = bank_backends(char_id, style_profile)
    if DEFAULT_BACKEND in have:
        return DEFAULT_BACKEND
    for b in ('facenet', 'dinov2'):
        if b in have:
            return b
    return DEFAULT_BACKEND


# ── the gate ─────────────────────────────────────────────────────────────────
def check(
    char_id,
    style_profile,
    image_path,
    backend=None,
    box_frac=None,
    episode=None,
    render_id=None,
    floor=None,
    device=None,
    log_fn=None,
    run_id=None,
    tag='',
    record=True,
):
    """Score one image against the character's bank.

    ok = cosine >= floor AND (z > Z_FLOOR, enforced only once n_bank >= Z_MIN_BANK and
    the bank spread is real — see Z_MIN_BANK; z is always reported).
    Returns {'ok', 'cosine', 'z', 'n_bank', 'backend', 'floor', 'reason', ...}.
    ok is None (UNKNOWN) whenever we could not measure — an empty bank, an undetectable
    face with no fallback, a broken model. UNKNOWN must never be read as a pass.
    """
    try:
        np = _np()
        backend = backend or _pick_backend(char_id, style_profile)
        st = bank_stats(char_id, style_profile, backend)
        if not st.get('ok'):
            return {
                'ok': None,
                'cosine': None,
                'z': None,
                'n_bank': st.get('n_bank', 0),
                'backend': backend,
                'error': st.get('error', 'no_bank'),
                'reason': 'empty_bank',
            }
        emb = (
            embed_face(image_path, backend='facenet', box_frac=box_frac, device=device, log_fn=log_fn)
            if backend == 'facenet'
            else embed_region(image_path, box_frac=box_frac, backend=backend, device=device, log_fn=log_fn)
        )
        if not emb.get('ok'):
            # No face. A facenet bank cannot be scored with a dinov2 vector, so we only
            # fall back when a dinov2 bank ALSO exists for this character+style;
            # otherwise report UNKNOWN rather than fabricate a comparable number.
            if backend == 'facenet' and 'dinov2' in bank_backends(char_id, style_profile):
                _log(log_fn, f'[identity_bank] {char_id}: no face -> dinov2 region bank')
                _ledger_fallback(
                    'identity_bank.check',
                    'facenet',
                    'dinov2',
                    detail=f'{os.path.basename(str(image_path))}: {emb.get("error")}',
                    run_id=run_id,
                )
                alt = check(
                    char_id,
                    style_profile,
                    image_path,
                    backend='dinov2',
                    box_frac=box_frac,
                    episode=episode,
                    render_id=render_id,
                    device=device,
                    log_fn=log_fn,
                    run_id=run_id,
                    tag=tag or 'facenet_miss',
                    record=record,
                )
                alt['fallback_from'] = 'facenet'
                alt['fallback_reason'] = emb.get('error')
                return alt
            _ledger_fallback(
                'identity_bank.check',
                backend,
                'unmeasured',
                detail=f'{os.path.basename(str(image_path))}: {emb.get("error")}',
                run_id=run_id,
            )
            res = {
                'ok': None,
                'cosine': None,
                'z': None,
                'n_bank': st['n_bank'],
                'backend': backend,
                'error': emb.get('error'),
                'reason': 'no_embedding',
            }
            if record:
                _record_check(
                    char_id,
                    style_profile,
                    episode,
                    render_id,
                    run_id,
                    backend,
                    None,
                    None,
                    None,
                    st['n_bank'],
                    image_path,
                    tag,
                )
            _ledger_gate(
                run_id, 'identity_bank', 'unknown', score=None, tag=f'{char_id}/{style_profile}:{emb.get("error")}'
            )
            return res
        cen = np.asarray(st['centroid'], dtype=np.float32)
        vec = np.asarray(emb['embedding'], dtype=np.float32)
        if vec.shape != cen.shape:
            return {
                'ok': None,
                'cosine': None,
                'z': None,
                'n_bank': st['n_bank'],
                'backend': backend,
                'error': 'dim_mismatch',
                'reason': 'dim_mismatch',
            }
        cos = float(np.dot(vec, cen))
        sd = st['loo_std']
        z = float((cos - st['loo_mean']) / sd) if sd > 1e-6 else 0.0
        flo = float(floor) if floor is not None else _FLOORS.get(backend, 0.5)
        z_enforced = bool(st['n_bank'] >= Z_MIN_BANK and sd >= Z_MIN_STD)
        z_bad = bool(z_enforced and z <= Z_FLOOR)
        ok = bool(cos >= flo and not z_bad)
        reason = 'pass' if ok else ('below_floor' if cos < flo else 'z_outlier')
        res = {
            'ok': ok,
            'cosine': round(cos, 4),
            'z': round(z, 3),
            'n_bank': st['n_bank'],
            'backend': backend,
            'floor': flo,
            'z_floor': Z_FLOOR,
            'z_enforced': z_enforced,
            'reason': reason,
            'bank_mean': round(st['loo_mean'], 4),
            'bank_std': round(sd, 4),
            'det_prob': emb.get('det_prob'),
            'fallback_from': emb.get('fallback_from'),
        }
        if record:
            _record_check(
                char_id, style_profile, episode, render_id, run_id, backend, cos, z, ok, st['n_bank'], image_path, tag
            )
        _ledger_gate(
            run_id, 'identity_bank', 'pass' if ok else 'fail', score=cos, tag=f'{char_id}/{style_profile}/{backend}'
        )
        _log(
            log_fn,
            f'[identity_bank] {char_id}/{style_profile}/{backend} '
            f'cos={cos:.3f} z={z:+.2f}{"" if z_enforced else "(advisory)"} '
            f'floor={flo} n={st["n_bank"]} -> {reason}',
        )
        return res
    except Exception as e:
        _log(log_fn, f'[identity_bank] check failed: {type(e).__name__}: {e}')
        return {
            'ok': None,
            'cosine': None,
            'z': None,
            'n_bank': 0,
            'error': f'{type(e).__name__}: {e}',
            'reason': 'exception',
        }


def _record_check(char_id, style, episode, render_id, run_id, backend, cos, z, ok, n_bank, src, tag):
    try:
        with pgdb.connect() as con:
            con.execute(
                'INSERT INTO checks (char_id, style, episode, render_id, run_id, backend,'
                ' cosine, z, ok, n_bank, src, tag, ts)'
                ' VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (
                    char_id,
                    style,
                    episode,
                    render_id,
                    run_id or _run_id(),
                    backend,
                    cos,
                    z,
                    None if ok is None else int(bool(ok)),
                    int(n_bank or 0),
                    str(src),
                    tag,
                    time.time(),
                ),
            )
    except Exception as _exc:
        _zyg_log.warning('identity measurement insert failed, the measurement is unrecorded: %s', _exc)
