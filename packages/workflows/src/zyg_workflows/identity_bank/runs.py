# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""identity_bank — the per-run entry point, the longitudinal views and canon enrolment."""

import logging as _zyg_logging
import os
import time

# The original module's symtable held a module-level `import json as _json`, in its
# `if __name__ == '__main__'` block (now identity_bank/__main__.py). It stays here, and it
# is the only binding of the name: run_char_ids and score_run below used to repeat the
# same import function-locally — the shadowing ruff reported as F811 — and they read this
# one instead. The alias is `_json`, because that is the name the moved bodies call.
import json as _json

from zyg_workflows import pgdb

from .clip import check_clip, enabled
from .embedding import RATCHET_DELTA, RATCHET_MIN_RENDERS, _log
from .gate import bank_backends, enroll

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.identity_bank')


# ── the plain entry point other studios call ─────────────────────────────────
_RUN_CHAR_KEYS = ('char_ids', 'character_ids', 'characters', 'chars', 'char_id', 'character_id')


def _bankable(char_id, style_profile):
    try:
        return bool(bank_backends(char_id, style_profile))
    except Exception:
        return False


def run_char_ids(run_dir, style_profile='arcane'):
    """Character ids named by a run directory's own json, filtered to ids that
    actually have a bank. Order is preserved — it is what the column ROIs key off."""
    import glob as _glob

    found = []
    files = sorted(_glob.glob(os.path.join(run_dir, '*.json')))
    files += sorted(_glob.glob(os.path.join(run_dir, '*', '*.json')))[:40]
    for f in files[:60]:
        try:
            with open(f, 'r') as fh:
                doc = _json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('run json unreadable, skipping it: %s', _exc)
            continue
        stack = [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in _RUN_CHAR_KEYS:
                        vals = v if isinstance(v, (list, tuple)) else [v]
                        for x in vals:
                            if isinstance(x, dict):
                                x = x.get('char_id') or x.get('id')
                            if isinstance(x, str) and x and x not in found:
                                found.append(x)
                    elif isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(node, list):
                stack.extend([x for x in node if isinstance(x, (dict, list))])
    return [c for c in found if _bankable(c, style_profile)]


def score_run(
    run_dir,
    chars=None,
    style_profile='arcane',
    clips=None,
    stride=None,
    max_frames=None,
    backend=None,
    device=None,
    log_fn=None,
    run_id=None,
    write_sidecar=True,
    max_clips=4,
):
    """Score the finished clips of ONE run directory. Advisory; never raises.

    This is the plain function other studios call (Movement Studio calls it on a
    finished job). `chars` may be omitted: the run's own json is read for character
    ids and each is given a vertical column ROI in the order it appears — the same
    equal-column convention arcane_multichar uses to build its QC regions. A single
    character gets no ROI (the whole frame).

    Writes `identity_clip.json` next to each clip. Returns
    {'ok', 'run_dir', 'chars', 'clips': [{'clip', 'results': {char_id: {...}}}], ...}.
    """
    import glob as _glob

    out = {'ok': None, 'run_dir': str(run_dir), 'clips': [], 'chars': [], 'enabled': enabled()}
    try:
        if not enabled():
            out['reason'] = 'disabled (ZYG_IDENTITY_CLIP=0)'
            return out
        if not os.path.isdir(run_dir):
            out['reason'] = 'run_dir_missing'
            return out
        if clips is None:
            cand = sorted(_glob.glob(os.path.join(run_dir, '*.mp4')))
            if not cand:
                cand = sorted(_glob.glob(os.path.join(run_dir, '*', '*.mp4')))
            cand = [c for c in cand if os.path.getsize(c) > 100_000]
            cand.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            clips = cand[:max_clips]
        if not clips:
            out['reason'] = 'no_clips'
            return out
        chars_source = 'caller'
        if chars is None:
            chars_source = 'run_json'
            chars = run_char_ids(run_dir, style_profile)
        out['chars_source'] = chars_source
        norm = []
        for _i, c in enumerate(chars or []):
            if isinstance(c, dict):
                norm.append(
                    {
                        'char_id': c.get('char_id') or c.get('id'),
                        'style': c.get('style') or style_profile,
                        'roi': c.get('roi'),
                    }
                )
            else:
                norm.append({'char_id': c, 'style': style_profile, 'roi': None})
        norm = [c for c in norm if c['char_id']]
        n = len(norm)
        for i, c in enumerate(norm):
            if c['roi'] is None and n > 1:
                c['roi'] = [i / n, 0.0, (i + 1) / n, 1.0]
        out['chars'] = [c['char_id'] for c in norm]
        if not norm:
            out['reason'] = 'no_banked_characters_in_run'
            return out
        if chars_source == 'run_json' and n == 1:
            # MEASURED 2026-09-02 on output/multichar_seated: the run json named one
            # character, so no ROI was applied, the whole-frame detector locked onto
            # whichever face it liked per frame, and one frame of five scored -0.047
            # — Abel's face against Cornelis' bank. A discovered cast of one is a
            # GUESS that the clip is a solo shot, and the caller must be told so.
            out['caution'] = (
                'cast auto-discovered as a single character; no ROI '
                'applied. If the clip is a two-hander the score mixes '
                'faces — pass chars=[...] explicitly.'
            )
            _log(log_fn, '[identity_bank] score_run: ' + out['caution'])
        for clip in clips:
            entry = {'clip': str(clip), 'results': {}}
            for c in norm:
                r = check_clip(
                    c['char_id'],
                    c['style'],
                    clip,
                    roi=c['roi'],
                    stride=stride,
                    max_frames=max_frames,
                    backend=backend,
                    device=device,
                    log_fn=log_fn,
                    run_id=run_id,
                    render_id=os.path.basename(str(run_dir).rstrip('/')),
                    tag='score_run',
                )
                entry['results'][c['char_id']] = r
            if write_sidecar:
                side = os.path.join(os.path.dirname(str(clip)), 'identity_clip.json')
                try:
                    with open(side, 'w') as fh:
                        _json.dump(entry, fh, indent=2, default=str)
                    entry['sidecar'] = side
                except Exception as e:
                    entry['sidecar_error'] = f'{type(e).__name__}: {e}'
            out['clips'].append(entry)
        verdicts = [r.get('ok') for e in out['clips'] for r in e['results'].values()]
        out['ok'] = None if not any(v is not None for v in verdicts) else all(v for v in verdicts if v is not None)
        out['reason'] = 'advisory'
        return out
    except Exception as e:
        out['error'] = f'{type(e).__name__}: {e}'
        return out


# ── longitudinal ─────────────────────────────────────────────────────────────
def drift_report(char_id, style_profile=None, backend=None, limit=500):
    """Time-series of recorded checks for the nightly drift dashboard.

    Returns {'ok', 'series': [...], 'by_episode': {...}, 'trend': {...}} where trend
    compares the newest quartile of measurements to the oldest — the cross-episode
    ratchet the memoryless per-render gate cannot see.
    """
    try:
        with pgdb.connect() as con:
            q = (
                'SELECT ts, char_id, style, episode, render_id, run_id, backend, cosine,'
                ' z, ok, n_bank, src, tag FROM checks WHERE char_id=%s'
            )
            args = [char_id]
            if style_profile:
                q += ' AND style=%s'
                args.append(style_profile)
            if backend:
                q += ' AND backend=%s'
                args.append(backend)
            q += ' ORDER BY ts DESC LIMIT %s'
            args.append(int(limit))
            rows = con.execute(q, args).fetchall()
        cols = [
            'ts',
            'char_id',
            'style',
            'episode',
            'render_id',
            'run_id',
            'backend',
            'cosine',
            'z',
            'ok',
            'n_bank',
            'src',
            'tag',
        ]
        series = [dict(zip(cols, r)) for r in rows][::-1]  # oldest first
        for s in series:
            s['when'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s['ts'] or 0))
        by_ep, by_rd = {}, {}
        for s in series:
            if s['cosine'] is None:
                continue
            by_ep.setdefault(s['episode'] or '_none', []).append(s['cosine'])
            key = (s['episode'] or '_none', s['render_id'] or s['run_id'] or '_none')
            by_rd.setdefault(key, []).append(s['cosine'])
        by_episode = {
            k: {'n': len(v), 'mean': round(sum(v) / len(v), 4), 'min': round(min(v), 4)} for k, v in by_ep.items()
        }
        # One point PER RENDER — several windows of one clip are not a time-series, and
        # treating them as one is how a within-clip wobble gets mislabelled as a
        # cross-episode ratchet.
        by_render = [
            {
                'episode': k[0],
                'render_id': k[1],
                'n': len(v),
                'mean': round(sum(v) / len(v), 4),
                'min': round(min(v), 4),
                'spread': round(max(v) - min(v), 4),
            }
            for k, v in by_rd.items()
        ]
        trend = {'n_renders': len(by_render)}
        if len(by_render) >= RATCHET_MIN_RENDERS:
            vals = [r['mean'] for r in by_render]
            k = max(1, len(vals) // 4)
            old = sum(vals[:k]) / k
            new = sum(vals[-k:]) / k
            trend.update(
                {
                    'oldest_q_mean': round(old, 4),
                    'newest_q_mean': round(new, 4),
                    'delta': round(new - old, 4),
                    'ratcheting_down': bool(new - old < RATCHET_DELTA),
                }
            )
        else:
            trend['note'] = f'need >= {RATCHET_MIN_RENDERS} renders for a ratchet verdict (have {len(by_render)})'
            trend['ratcheting_down'] = None
        return {
            'ok': True,
            'char_id': char_id,
            'n': len(series),
            'series': series,
            'by_episode': by_episode,
            'by_render': by_render,
            'trend': trend,
            'banks': bank_backends(char_id, style_profile),
        }
    except Exception as e:
        return {'ok': None, 'error': f'{type(e).__name__}: {e}', 'series': []}


def purge(char_id, style_profile=None, backend=None, checks_too=False):
    """Drop bank entries (used when a character is legitimately re-canonised)."""
    try:
        with pgdb.connect() as con:
            q, args = 'DELETE FROM chars WHERE char_id=%s', [char_id]
            if style_profile:
                q += ' AND style=%s'
                args.append(style_profile)
            if backend:
                q += ' AND backend=%s'
                args.append(backend)
            n = con.execute(q, args).rowcount
            m = 0
            if checks_too:
                m = con.execute('DELETE FROM checks WHERE char_id=%s', (char_id,)).rowcount
        return {'ok': True, 'deleted': int(n), 'checks_deleted': int(m)}
    except Exception as e:
        return {'ok': None, 'error': f'{type(e).__name__}: {e}'}


# ── convenience: enrol a Second-Ledger-style character from canon ────────────
def enroll_from_canon(
    char_id, style_profile='arcane', extra_paths=None, backend=None, episode='canon', device=None, log_fn=None
):
    """Seed a bank from canon_service's single source of visual truth."""
    try:
        from zyg_workflows import canon_service

        paths = [canon_service.canon_portrait(char_id), canon_service.canon_face_crop(char_id)]
        paths += list(extra_paths or [])
        return enroll(
            char_id,
            style_profile,
            [p for p in paths if p],
            backend=backend,
            episode=episode,
            render_id='canon',
            device=device,
            log_fn=log_fn,
        )
    except Exception as e:
        return {'ok': None, 'error': f'{type(e).__name__}: {e}', 'enrolled': 0}
