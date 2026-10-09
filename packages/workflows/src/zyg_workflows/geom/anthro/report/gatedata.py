# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — reading gates.py's output as data.

Moved out of the old single-file report.py (lines 786-1064).
"""

from zyg_workflows.geom.anthro.report.constants import (
    CRASHED,
    CRASH_UNDECLARED,
    GATE_ERROR,
    PASS,
    RAN,
    UNKNOWN,
    _CRASH_KEYS,
    _ENGINE_STATUS_CONSTANTS,
    _HIGH_SEVERITIES,
    _LOW_SEVERITIES,
    _PROV_CLASSES,
    _STATUS_ALIASES,
)
from zyg_workflows.geom.anthro.report.textfmt import _fmt_num, _is_num, _num


# ---------------------------------------------------------------------------------
# reading gates.py's output as data
# ---------------------------------------------------------------------------------
def _get(d, *keys, **kw):
    """First present, non-None value among `keys`. Default is the string 'unknown' so a
    missing field renders rather than raising or vanishing."""
    default = kw.get('default', UNKNOWN)
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def normalize_status(raw):
    """Map whatever gates.py wrote into the buckets. Booleans are accepted because a gate
    whose result is literally True/False is a plausible thing to write.

    AN UNMAPPED STATUS RENDERS AS AN ERROR, NEVER AS A PASS AND NEVER AS SOMETHING SOFTER
    (W4-1). It used to fall through to 'unknown', which counts towards the warning total
    and, on a blocking gate, produces an escalated non-verdict rather than a blocking
    failure. That is the softer of the two available readings of "the engine said something
    this renderer has never heard of", and the whole reason this module exists is that the
    softer reading is how a crashed blocking gate once shipped as PASS-WITH-WARNINGS. An
    engine that grows a status faster than this renderer learns it must lose the argument.
    'unknown' is kept for the case it was written for: the status could not be READ at all —
    absent, empty, or a row that is not a mapping. That is a fact about the artefact rather
    than a statement by the engine, and it keeps its own bucket and its own '????' mark.
    Every unrecognised spelling is named in the `unrecognised_status` alarm, so landing in
    the error bucket is never silent.
    """
    if raw is None:
        return 'unknown'
    if isinstance(raw, bool):
        return PASS if raw else 'fail'
    key = str(raw).strip().lower().replace(' ', '_')
    if not key:
        return 'unknown'
    return _STATUS_ALIASES.get(key, GATE_ERROR)


def status_is_recognised(raw):
    """True if `raw` is a status spelling this renderer actually knows. False means the row
    was rendered as an error by the fallback above, which is a renderer defect to be fixed
    rather than a fact about the body — so it is alarmed on by name."""
    if raw is None or isinstance(raw, bool):
        return True
    key = str(raw).strip().lower().replace(' ', '_')
    return (not key) or key in _STATUS_ALIASES


def _crash_state(g):
    """(state, declared) — did this gate RAISE? Read from the producer, never inferred.

    state is CRASHED, RAN or CRASH_UNDECLARED; `declared` says whether the producer
    actually spoke. See the contract note above _CRASH_KEYS: the one thing this function
    may never do is look at the status, because 'error' is exactly the field that stopped
    meaning one thing.
    """
    if not isinstance(g, dict):
        return CRASH_UNDECLARED, False
    detail = g.get('detail')
    for src in (g, detail if isinstance(detail, dict) else {}):
        for k in _CRASH_KEYS:
            v = src.get(k)
            if isinstance(v, bool):
                return (CRASHED if v else RAN), True
    return CRASH_UNDECLARED, False


def engine_statuses():
    """Every status the gate engine can emit, discovered from gates.py itself.

    Returns (mapping of CONSTANT_NAME -> status string, where it came from). Read live
    rather than frozen, because the defect this guards against is gates.py growing a
    status this renderer has never heard of and rendering it as 'unknown' — which is
    precisely how a crashed blocking gate came to ship as PASS-WITH-WARNINGS. The
    discovery rule is gates.py's own convention that a status constant's value is its name
    in lower case (PASS='pass' ... ERROR='error'); the self-test cross-checks the result
    against _ENGINE_STATUS_CONSTANTS, so a rename breaks the test rather than the report.

    Falls back to the frozen list when gates.py cannot be imported, and says so, so that a
    green self-test can never mean "nothing was checked".
    """
    try:
        from zyg_workflows.geom.anthro import gates as _gates
    except Exception as e:  # noqa: BLE001
        return (
            {n: n.lower() for n in _ENGINE_STATUS_CONSTANTS},
            'frozen list in report.py (geom.anthro.gates not importable: %s)' % e,
        )
    found = {n: v for n, v in vars(_gates).items() if n.isupper() and isinstance(v, str) and v == n.lower()}
    return found, 'geom.anthro.gates'


def _severity_class(sev):
    """('high'|'low'|'unrecognised', normalised_text). Unrecognised is deliberately its
    own class: it must behave like high but must be REPORTED as unrecognised, because the
    likeliest cause is a typo in the gate registry."""
    if sev is None:
        return 'unrecognised', UNKNOWN
    s = str(sev).strip().lower()
    if s in _LOW_SEVERITIES:
        return 'low', s
    if s in _HIGH_SEVERITIES:
        return 'high', s
    return 'unrecognised', s or UNKNOWN


def _band_of(raw):
    """Normalise a band into (lo, hi, width_label, text). Accepts (lo,hi), [lo,hi],
    {'lo','hi'}, {'min','max'}, one-sided dicts, and free text."""
    lo = hi = None
    width = None
    if raw is None:
        return None, None, None, None
    if isinstance(raw, (list, tuple)):
        vals = [_num(x) for x in raw]
        if len(vals) >= 2:
            lo, hi = vals[0], vals[1]
        elif len(vals) == 1:
            hi = vals[0]
    elif isinstance(raw, dict):
        for k in ('lo', 'low', 'min', 'minimum', 'lower'):
            if raw.get(k) is not None:
                lo = _num(raw[k])
                break
        for k in ('hi', 'high', 'max', 'maximum', 'upper'):
            if raw.get(k) is not None:
                hi = _num(raw[k])
                break
        width = raw.get('width') or raw.get('interval')
        if lo is None and hi is None:
            return None, None, width, str(raw)
    elif _is_num(raw):
        hi = _num(raw)
    else:
        return None, None, None, str(raw)
    return lo, hi, width, None


def _fmt_band(lo, hi, width, text, units=None):
    if text:
        return text
    if lo is None and hi is None:
        return UNKNOWN
    if lo is None:
        s = '<= %s' % _fmt_num(hi)
    elif hi is None:
        s = '>= %s' % _fmt_num(lo)
    else:
        s = '%s .. %s' % (_fmt_num(lo), _fmt_num(hi))
    if width:
        s += ' [%s]' % width
    if units:
        s += ' %s' % units
    return s


def _observed_of(raw):
    """(value_or_None, printable, units). An observed field may be a bare number, a dict
    carrying units, or a sentence."""
    if isinstance(raw, dict):
        units = raw.get('units')
        for k in ('value', 'observed', 'value_mm', 'measured', 'x', 'd2'):
            if raw.get(k) is not None:
                v = _num(raw[k])
                if k == 'value_mm' and not units:
                    units = 'mm'
                return v, _fmt_num(raw[k], units), units
        # A diagnostic dict with no headline number: naming the fields is honest, whereas
        # a JSON fragment chopped at 60 characters looks like a value and is not one. The
        # whole dict survives in the JSON artifact either way.
        keys = [k for k in sorted(raw) if k != 'units']
        if len(keys) == 1:
            return _num(raw[keys[0]]), '%s=%s' % (keys[0], _fmt_num(raw[keys[0]])), units
        return None, '{%d fields}' % len(keys), units
    v = _num(raw)
    if v is not None:
        return v, _fmt_num(v), None
    return None, (UNKNOWN if raw is None else str(raw)), None


def _prov_class(gate):
    """Declared provenance class, or UNDECLARED. A class is only accepted when it is
    declared in a field or stands at the head of the source string; guessing it from the
    prose would defeat the purpose of demanding it."""
    for k in ('threshold_provenance', 'provenance_class', 'provenance', 'claim_class', 'class'):
        val = gate.get(k) if isinstance(gate, dict) else None
        if isinstance(val, str):
            up = val.strip().upper()
            for c in _PROV_CLASSES:
                if up == c or up.startswith(c + ':') or up.startswith(c + ' '):
                    return c
    for k in ('threshold_source', 'source'):
        src = gate.get(k) if isinstance(gate, dict) else None
        if isinstance(src, str):
            up = src.strip().upper()
            for c in _PROV_CLASSES:
                if up.startswith(c):
                    return c
    return 'UNDECLARED'


def _iter_gates(gate_report):
    """Yield (tier_name, gate_dict) out of any of the shapes gates.py might use.

    Accepted: {'tiers': {tier: [g,...]}}, {'tiers': [{'tier':..,'gates':[..]}]},
    {'tiers': [g,...]} flat, {'gates': [...]}, or a bare list of gates. Anything that is
    not a dict where a gate belongs is yielded as a malformed marker rather than skipped,
    because a gate that cannot be read is not a gate that passed.
    """
    seq = [0]

    def as_gate(x, tier):
        if isinstance(x, dict):
            return str(_get(x, 'tier', 'stage', 'group', default=tier)), x
        seq[0] += 1
        return str(tier), {
            'id': '<malformed#%d>' % seq[0],
            'status': 'unknown',
            'severity': None,
            'explanation': 'MALFORMED gate entry of type %s: %r' % (type(x).__name__, x),
            '_malformed': True,
        }

    if gate_report is None:
        return
    src = gate_report
    if isinstance(src, dict):
        tiers = src.get('tiers')
        if tiers is None:
            tiers = src.get('gates')
        if tiers is None:
            tiers = src.get('results')
        if tiers is None:
            return
    else:
        tiers = src

    if isinstance(tiers, dict):
        for tier in tiers:
            block = tiers[tier]
            if isinstance(block, dict):
                block = block.get('gates', block.get('results', [block]))
            if not isinstance(block, (list, tuple)):
                block = [block]
            for g in block:
                yield as_gate(g, tier)
        return
    if isinstance(tiers, (list, tuple)):
        for entry in tiers:
            if isinstance(entry, dict) and ('gates' in entry or 'results' in entry):
                tier = str(_get(entry, 'tier', 'name', 'id', default=UNKNOWN))
                block = entry.get('gates', entry.get('results')) or []
                if not isinstance(block, (list, tuple)):
                    block = [block]
                for g in block:
                    yield as_gate(g, tier)
            else:
                yield as_gate(entry, UNKNOWN)
        return
    yield as_gate(tiers, UNKNOWN)


def _rejection_rate(g):
    """The measured fraction of the reference population a gate would reject, if the gate
    engine calibrated it. None when the engine made no such claim — which is not the same
    as zero and must never render as zero."""
    if not isinstance(g, dict):
        return None
    r = g.get('reference_rejection_rate')
    if r is None:
        cal = g.get('severity_calibration')
        if isinstance(cal, dict):
            r = cal.get('rate')
    return _num(r)
