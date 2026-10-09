# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The MEASURED/CANON/HOUSE evidence contract, its import-time negative controls,
and the record/judge constructors every predicate in the pack emits through.

Moved verbatim out of the old single-file hands.py (lines 559-824).
"""

import re
import sys

from zyg_workflows.geom.form.hands.rig import (
    PREDICATES,
    DIGIT_PREDICATES,
    PASS,
    FAIL,
    REPORT,
    MEASURED,
    CANON,
)

# provenance_rule_controls() below reads BK2010_SOURCE / HD2002_SOURCE out of
# `globals()`, because in the single-file hands.py the two shipped MEASURED source
# strings were defined 1,400 lines further down and were only there by the time the
# import-time control suite ran. They now live in digits_rig.py, so they are imported
# here by name: without this the suite silently drops its two POSITIVE controls and only
# ever proves that hostile strings are refused. (digits_rig imports nothing but rig, so
# this is not a cycle.) F401 is deliberate — the lookup is dynamic.
from zyg_workflows.geom.form.hands.digits_rig import (  # noqa: F401
    BK2010_SOURCE,
    HD2002_SOURCE,
)


# ---------------------------------------------------------------------------------
# Predicate records
# ---------------------------------------------------------------------------------
# What makes a source a SURVEY rather than a citation: it reports how many PEOPLE were
# measured. `n=66`, `n = 197`. A book page has no sample size because a book page is not a
# sample.
#
# TIGHTENED 2026-08-06 (re-review, hands.py minor). The n-test alone was a test of the
# SPELLING of the citation and not of the evidence — exactly the shape geom/anthro/gates.py
# had already had to widen from a page test to a book test (see CANON_BOOKS there).
# Measured against the shipped code before the change:
#
#   MEASURED, source 'the AFS head-unit chart, n=1 drawing'          -> ACCEPTED
#   MEASURED, source 'Anatomy For Sculptors, the crotch chart, n=12' -> ACCEPTED
#   MEASURED, source 'AFS chapter 4, n=200'                          -> ACCEPTED
#
# all three of which the registry's book test refuses for any real gate. Defence in depth
# held; the module-local layer did not, and a layer that cannot fail is not a layer. Three
# tests now, and a MEASURED source must survive all three:
#   1. it prints a sample size at all
#   2. every sample size it prints is at least 2 — one body is a case report, not a survey
#   3. it does not name a canon art/anatomy book AT ALL. Typing `n=` beside a book title
#      does not turn the book into a survey.
_SURVEY_N_RE = re.compile(r'\bn\s*=\s*(\d+)', re.IGNORECASE)
# What makes a source CANON: a page, plate or figure in a printed text.
_CITATION_RE = re.compile(r'\b(?:p{1,2}\.\s*\d|pages?\s+\d|fig\.\s*\d|plate\s+\d)', re.IGNORECASE)
# MIRROR of geom.anthro.gates.CANON_BOOKS, kept local so this module never has to import
# the registry to refuse a record. _assert_provenance compares the two whenever the
# registry is loaded and refuses on the HOLE direction (a book the registry knows about
# and this list does not), because a mirror nobody checks is how the weaker of two layers
# quietly becomes the only one. Substring matching, case-insensitive, exactly as the
# registry does it — a local rule that is looser than the registry's is the defect.
_CANON_BOOK_NAMES = (
    'Anatomy For Sculptors',
    'AFS',
    'Form of the Head and Neck',
    'HeadNeck',
    'FacialExpr',
    'Facial Expressions',
)
_MIN_SURVEY_N = 2
_BOOK_MIRROR_CHECKED = [False]


def _canon_books_named(text):
    """Every canon book title this text names. Non-empty means the number is CANON."""
    s = str(text or '')
    return [b for b in _CANON_BOOK_NAMES if re.search(re.escape(b), s, re.I)]


def _assert_book_mirror():
    """Refuse if the registry knows a canon book this module does not.

    Only looks at an ALREADY-IMPORTED registry: importing geom.anthro.gates from a tier-5
    form module to run a string check would invert the dependency. gates.py loads this
    module through form_module() at gate time, so on the path that matters the registry is
    in sys.modules and this really runs. Returns the state it observed so a caller can see
    which it was; it never reports 'checked' when it did not check.
    """
    g = sys.modules.get('geom.anthro.gates')
    known = getattr(g, 'CANON_BOOKS', None) if g is not None else None
    if not known:
        return {
            'checked': False,
            'why': 'geom.anthro.gates is not loaded in this process, so the mirror '
            'could not be compared. This is not a pass.',
        }
    missing = [b for b in known if b not in _CANON_BOOK_NAMES]
    if missing:
        raise ValueError(
            'geom/form/hands.py _CANON_BOOK_NAMES is missing %r, which '
            'geom.anthro.gates.CANON_BOOKS lists. This module would accept a MEASURED tag '
            'on a source naming that book while the registry refuses it, which makes the '
            'module-local provenance check the weaker of the two layers instead of the '
            'first one.' % (missing,)
        )
    return {
        'checked': True,
        'registry_books': list(known),
        'local_only': [b for b in _CANON_BOOK_NAMES if b not in known],
    }


def _assert_provenance(predicate, provenance, source):
    """Refuse a provenance tag the record's own source cannot support.

    2026-08-06. `digit_chains` shipped `provenance=MEASURED` with
    `source='integer skeletal counts, AFS p.179 and p.188; ...'`. Two book pages are
    CANON. The gate registry had already been re-tagged; this module had not, so the
    stale MEASURED string travelled into every gate row (`module_provenance`,
    `per_side.<side>.provenance`) and was printed in the text report as the strongest
    evidence class the file has. Re-tagging the one record fixes today; this refuses to
    let it happen again, in either direction, and it fails at emission rather than in
    review.

    It never widens: no tag is upgraded here, and a record whose source cannot carry its
    tag raises instead of being quietly demoted to something that passes.
    """
    src = source or ''
    if provenance == MEASURED:
        if not _BOOK_MIRROR_CHECKED[0]:
            _BOOK_MIRROR_CHECKED[0] = bool(_assert_book_mirror().get('checked'))
        ns = [int(m) for m in _SURVEY_N_RE.findall(src)]
        books = _canon_books_named(src)
        if not ns:
            raise ValueError(
                'predicate %r is tagged MEASURED but its source names no sample size, so '
                'it is not a survey of real people: %r. A number printed in a book is '
                'CANON however correct it is, and a count taken off our own rig is HOUSE. '
                "MEASURED is the file's strongest evidence class and is ranked above "
                'both.' % (predicate, src[:200])
            )
        if min(ns) < _MIN_SURVEY_N:
            raise ValueError(
                'predicate %r is tagged MEASURED but its source prints a sample size of '
                '%d: %r. A sample of fewer than %d bodies is a case report, not a survey, '
                "and it cannot carry this file's strongest evidence class."
                % (predicate, min(ns), src[:200], _MIN_SURVEY_N)
            )
        if books:
            raise ValueError(
                'predicate %r is tagged MEASURED but its source names %s, which is an '
                'art/anatomy book: %r. A book has no sample, no n and no sampling frame '
                'whatever is typed beside its title, so a number attributed to one is '
                'CANON. Printing "n=" next to a book title does not make it a survey. If '
                'the record wants to ARGUE with the book, it can do that in `explain` — '
                'the source line names the evidence the number came from and nothing '
                'else.' % (predicate, ' and '.join(books), src[:200])
            )
    if provenance == CANON and not _CITATION_RE.search(src):
        raise ValueError(
            'predicate %r is tagged CANON but its source cites no page, plate or figure: '
            '%r. CANON means a printed convention; without the citation there is nothing '
            'for a reader to check and the tag should be HOUSE.' % (predicate, src[:200])
        )


# NEGATIVE CONTROLS for the rule above, run at import so they cannot be skipped. Each row
# is (source, provenance, must_refuse, why). The first is the exact string the re-review
# found ACCEPTED by this module while the registry refused it; a control suite that cannot
# see the defect it is named for is worse than no suite, so it is in here verbatim.
_PROVENANCE_CONTROLS = (
    (
        'the AFS head-unit chart, n=1 drawing',
        'MEASURED',
        True,
        'names a canon book AND prints a sample size of one; ACCEPTED before 2026-08-06',
    ),
    (
        'Anatomy For Sculptors, the crotch chart, n=12 figures',
        'MEASURED',
        True,
        'a book with a plausible-looking n typed beside it',
    ),
    ('AFS chapter 4, n=200', 'MEASURED', True, 'a book with a large n typed beside it — size is not provenance'),
    ('Form of the Head and Neck p.161, n=30', 'MEASURED', True, 'a second canon book, page cited, still a book'),
    ('a radiographic series, n=1', 'MEASURED', True, 'no book, but one body is a case report and not a survey'),
    ('a radiographic series, n=0', 'MEASURED', True, 'an empty sample is not a sample'),
    ('an anatomy atlas plate', 'MEASURED', True, 'no sample size at all'),
    (
        'two series, n=66 and n=1',
        'MEASURED',
        True,
        'the strictest printed n governs: a pooled claim may not hide a sample of one',
    ),
    (
        'Jones 2011, J. Anat. 218(4):401-410 (n=140 adults, CT)',
        'MEASURED',
        False,
        'a real survey, no book named — this must still be emittable',
    ),
    ('AFS p.178', 'CANON', False, 'a book with a page is exactly what CANON means'),
    ('our own cage, all 13718 vertices', 'CANON', True, 'CANON with nothing to check'),
    ('our own cage, all 13718 vertices', 'HOUSE', False, 'HOUSE claims nothing external'),
)


def provenance_rule_controls():
    """Run _PROVENANCE_CONTROLS plus the two shipped MEASURED sources. Returns rows."""
    rows = []
    cases = list(_PROVENANCE_CONTROLS)
    for nm in ('BK2010_SOURCE', 'HD2002_SOURCE'):
        s = globals().get(nm)
        if s:
            cases.append((s, 'MEASURED', False, 'the shipped %s must survive the tightened rule' % nm))
    for src, prov, must_refuse, why in cases:
        try:
            _assert_provenance('__control__', prov, src)
            refused, err = False, None
        except ValueError as e:
            refused, err = True, str(e)[:160]
        rows.append(
            {
                'source': src[:90],
                'provenance': prov,
                'must_refuse': must_refuse,
                'refused': refused,
                'why': why,
                'error': err,
                'ok': refused is must_refuse,
            }
        )
    return rows


def _run_provenance_controls_at_import():
    """A rule this module cannot demonstrate on a hostile string is a rule on paper.

    Called at the bottom of the module, after the two real MEASURED source strings exist,
    so the suite proves both directions: the hostile strings are refused AND the sources
    this file actually ships still emit. Import-time, so nobody can forget to run it.
    """
    bad = [r for r in provenance_rule_controls() if not r['ok']]
    if bad:
        raise RuntimeError(
            'geom/form/hands.py provenance controls FAILED at import: %s. The MEASURED / '
            'CANON rule in _assert_provenance does not do what its docstring says.'
            % [
                (
                    r['source'],
                    r['provenance'],
                    'accepted but must refuse' if r['must_refuse'] else 'refused but must accept',
                )
                for r in bad
            ]
        )


def _rec(
    predicate, basis, status, observed, unit, explain, band=None, threshold=None, provenance=None, source=None, **detail
):
    if predicate not in PREDICATES + DIGIT_PREDICATES:
        raise ValueError(
            'unknown predicate %r; the vocabulary is %s (shared with the '
            'image path) plus %s (mesh/rig only)' % (predicate, ', '.join(PREDICATES), ', '.join(DIGIT_PREDICATES))
        )
    _assert_provenance(predicate, provenance, source)
    out = {
        'predicate': predicate,
        'basis': basis,
        'status': status,
        'observed': observed,
        'unit': unit,
        'band': band,
        'threshold': threshold,
        'provenance': provenance,
        'source': source,
        'explain': explain,
    }
    if detail:
        out['detail'] = detail
    return out


def _judge(value, band):
    """pass/fail against a (lo, hi) band, either end optionally None."""
    if band is None or value is None:
        return REPORT
    lo, hi = band
    if lo is not None and value < lo:
        return FAIL
    if hi is not None and value > hi:
        return FAIL
    return PASS
