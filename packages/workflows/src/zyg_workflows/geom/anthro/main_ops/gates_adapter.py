# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro CLI — the adapter that calls whatever entry point gates.py offers.

Moved verbatim from geom/anthro/__main__.py (lines 220-360) when that 1,757-line
file became the __main__ shim over this package. No logic was changed.
"""

from zyg_workflows.geom.anthro.main_ops.constants import GatesAbsent, GatesUnusable, _GATE_ENTRYPOINTS
from zyg_workflows.geom.anthro.main_ops.characters import _age_years, _build, _measure


# ---------------------------------------------------------------------------------
# the gates.py adapter
# ---------------------------------------------------------------------------------
def _adapt_call(fn, pool):
    """Call `fn` with whichever of `pool`'s values its signature actually names.

    A parameter with no default that the pool cannot fill means this entry point is not
    the one we want; raising TypeError lets the caller move on to the next candidate
    rather than passing something arbitrary into a gate.
    """
    import inspect

    sig = inspect.signature(fn)
    args, kwargs, missing = [], {}, []
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.name in pool:
            if p.kind is p.POSITIONAL_ONLY:
                args.append(pool[p.name])
            else:
                kwargs[p.name] = pool[p.name]
        elif p.default is p.empty:
            missing.append(p.name)
    if missing:
        raise TypeError('cannot fill required parameter(s) %s' % ', '.join(missing))
    return fn(*args, **kwargs)


def _subject(G, rec):
    """gates.py's own Subject, when it has one.

    Built through the gate module rather than assembled here so that whatever the engine
    checks about a subject on construction — for this registry, that the rebuilt cage
    still hashes to what shipped — actually runs. Returns (subject, how) or (None, why).
    """
    Subject = getattr(G, 'Subject', None)
    if Subject is None:
        return None, 'gates.py exposes no Subject class'
    if rec['section'] in ('originals', 'derived') and hasattr(Subject, 'from_registry'):
        try:
            return Subject.from_registry(rec['name']), 'Subject.from_registry(%r)' % (rec['name'],)
        except Exception as e:  # noqa: BLE001
            # A hash mismatch here means the recipe no longer rebuilds the issued mesh.
            # That is a real finding, not a reason to quietly gate a different body.
            raise GatesUnusable('Subject.from_registry(%r) refused: %s' % (rec['name'], e)) from e
    if hasattr(Subject, 'from_mesh'):
        v, faces = _build(rec)
        spec = {
            'sex': rec['sex'],
            'ancestry': rec.get('ancestry'),
            'phenotype': rec['phenotype'],
            'local_changes': rec['local_changes'],
            'age_years': _age_years(rec),
        }
        return Subject.from_mesh(v, faces, spec, name=rec['name']), 'Subject.from_mesh (unregistered control)'
    return None, 'Subject has neither from_registry nor from_mesh'


def call_gates(rec, measurement=None, v=None, faces=None, ancestry=None):
    """Whatever gates.py exposes, called with whatever it asks for.

    Returns (gate_report, entrypoint_name, subject_or_None). Raises GatesAbsent if the
    module does not exist and GatesUnusable if it does but nothing in it could be called.
    """
    # find_spec, not a try/except around the import: "cannot import name 'gates' from
    # 'geom.anthro'" and "gates.py raised ImportError on line 3" are the same exception
    # type, and treating the second as absence would silently swap a fixture in for a
    # gate module that exists and is merely broken.
    import importlib
    import importlib.util

    if importlib.util.find_spec('geom.anthro.gates') is None:
        raise GatesAbsent('geom.anthro.gates does not exist')
    G = importlib.import_module('zyg_workflows.geom.anthro.gates')
    ref = None
    try:
        from zyg_workflows.geom.anthro.reference import reference as _reference

        ref = _reference()
    except Exception:  # noqa: BLE001
        ref = None
    subject, how = _subject(G, rec)
    if subject is not None and measurement is None:
        # The Subject caches its own measurement; measuring again would cost a second
        # full pass and could silently diverge from what the gates actually judged.
        measurement = getattr(subject, 'measurements', None)
    if measurement is None:
        measurement, v, faces = _measure(rec)
    if v is None:
        v, faces = getattr(subject, 'v', None), getattr(subject, 'faces', None)
    meta = (measurement or {}).get('meta') or {}
    pool = {
        'subject': subject,
        'subj': subject,
        's': subject,
        'name': rec['name'],
        'character': rec['name'],
        'character_name': rec['name'],
        'measurement': measurement,
        'measurements': measurement,
        'measured': measurement,
        'meas': measurement,
        'm': measurement,
        'ratios': measurement.get('ratios'),
        'meta': meta,
        'sex': rec['sex'],
        'ancestry': ancestry if ancestry is not None else rec.get('ancestry'),
        'v': v,
        'verts': v,
        'vertices': v,
        'faces': faces,
        'f': faces,
        'phenotype': rec['phenotype'],
        'local_changes': rec['local_changes'],
        'params': rec.get('params'),
        'age_frac': rec.get('age_frac'),
        'stature_m': meta.get('stature_m'),
        'reference': ref,
        'ref': ref,
    }
    if subject is None:
        pool.pop('subject'), pool.pop('subj'), pool.pop('s')
    tried = []
    for nm in _GATE_ENTRYPOINTS:
        fn = getattr(G, nm, None)
        if not callable(fn):
            continue
        try:
            return _adapt_call(fn, pool), nm, subject
        except TypeError as e:
            tried.append('%s (%s)' % (nm, e))
    raise GatesUnusable(
        'geom.anthro.gates imported but no entry point could be called. Subject: %s. '
        'Tried: %s. Callables present: %s'
        % (
            how if subject is None else 'built via %s' % how,
            '; '.join(tried) or 'none of %s' % ', '.join(_GATE_ENTRYPOINTS),
            ', '.join(sorted(n for n in dir(G) if callable(getattr(G, n, None)) and not n.startswith('_'))) or 'none',
        )
    )
