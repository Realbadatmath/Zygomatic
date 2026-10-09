# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.helpers — Shared constants and the knob/param declaration helpers."""

import subprocess


_SR = 48000
_FF_TIMEOUT = 180


# ── param helpers ─────────────────────────────────────────────────────────────
def _k(key, label, dflt, lo, hi, step, unit='', hint=''):
    return {
        'key': key,
        'type': 'knob',
        'label': label,
        'def': dflt,
        'min': lo,
        'max': hi,
        'step': step,
        'unit': unit,
        'hint': hint,
    }


def _t(key, label, dflt=False, hint=''):
    return {'key': key, 'type': 'toggle', 'label': label, 'def': bool(dflt), 'hint': hint}


def _s(key, label, values, dflt=0, hint='', labels=None):
    """A select: stored as the INDEX into `values`, so a slot's tweak dict stays
    numeric and hashes to the same stem on every client."""
    labs = labels or [str(v) for v in values]
    return {
        'key': key,
        'type': 'select',
        'label': label,
        'def': int(dflt),
        'min': 0,
        'max': len(values) - 1,
        'step': 1,
        'unit': '',
        'opts': [{'v': v, 'label': labs[i]} for i, v in enumerate(values)],
        'hint': hint,
    }


def _pick(p, key, values):
    i = int(round(float(p.get(key, 0))))
    return values[max(0, min(len(values) - 1, i))]


def _db(x):
    """dB -> linear."""
    return 10.0 ** (float(x) / 20.0)


def _q(s):
    """Escape a value for use inside one ffmpeg filter argument."""
    return str(s).replace('\\', '\\\\').replace(':', r'\:').replace(',', r'\,')


def _run(args, timeout=_FF_TIMEOUT):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stderr or '')
    except subprocess.TimeoutExpired:
        return 124, 'ffmpeg timeout'
    except OSError as e:
        return 125, str(e)[:200]


def _ff(args, what):
    code, err = _run(args)
    if code != 0:
        raise ValueError(f'{what} failed: {err.strip()[-300:] or code}')
    return err
