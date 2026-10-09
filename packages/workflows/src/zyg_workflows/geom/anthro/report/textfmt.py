# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — small formatting helpers.

Moved out of the old single-file report.py (lines 693-784).
"""

import textwrap
from zyg_workflows.geom.anthro.report.constants import UNKNOWN, _zyg_log


# ---------------------------------------------------------------------------------
# small formatting helpers
# ---------------------------------------------------------------------------------
def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _num(x):
    """Coerce numpy scalars and numeric strings without importing numpy for a print."""
    if _is_num(x):
        return float(x)
    if hasattr(x, 'item'):
        try:
            y = x.item()
            return float(y) if _is_num(y) else None
        except Exception:  # noqa: BLE001
            return None
    if isinstance(x, str):
        try:
            return float(x.strip())
        except ValueError:
            return None
    return None


def _fmt_num(x, units=None):
    v = _num(x)
    if v is None:
        return UNKNOWN if x is None else str(x)
    a = abs(v)
    if a and (a < 1e-3 or a >= 1e7):
        s = '%.4g' % v
    elif a < 10:
        s = '%.4f' % v
    elif a < 1000:
        s = '%.2f' % v
    else:
        s = '%.1f' % v
    return s + (' ' + units if units else '')


def _fmt_rate(r):
    """A rejection rate as a percentage. None is 'not measured', which is a different
    statement from 0% and must not be rendered as one."""
    if r is None:
        return 'not measured'
    return '%.3f%% of the reference' % (100.0 * float(r))


def _fmt_pct(p):
    """'!' marks a value outside the observed range of the reference sample entirely.
    That is the true empirical answer — no member of the sample was more extreme — and it
    is deliberately not written as p1 or p99, which would understate it."""
    if p is None:
        return '     -'
    if p <= 0.0:
        return '   p0!'
    if p >= 100.0:
        return ' p100!'
    return ' p%4.1f' % p


def _wrap(text, width, indent):
    if text is None:
        return []
    text = ' '.join(str(text).split())
    if not text:
        return []
    pad = ' ' * indent
    return textwrap.wrap(text, max(24, width - indent), initial_indent=pad, subsequent_indent=pad)


def _jsonable(o):
    """json default hook. Numpy and set types are converted; anything else is stringified
    with its type visible, so an unexpected object shows up in the artifact as a readable
    marker instead of aborting the write."""
    if hasattr(o, 'tolist'):
        try:
            return o.tolist()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('tolist conversion failed, trying item(): %s', _exc)
    if hasattr(o, 'item'):
        try:
            return o.item()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('item conversion failed, stringifying instead: %s', _exc)
    if isinstance(o, (set, frozenset)):
        return sorted(str(x) for x in o)
    if isinstance(o, bytes):
        return o.decode('utf-8', 'replace')
    return '<%s %s>' % (type(o).__name__, o)
