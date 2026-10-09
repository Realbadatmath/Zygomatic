# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the measurement meta block, the stable digest and the verdict.

Moved out of the old single-file report.py (lines 2698-2894).
"""

import hashlib
import json
from zyg_workflows.geom.anthro.report.constants import (
    ERROR,
    EXIT_CODES,
    _CLOCK_RESIDUE_CONTENT_KEYS,
    _CLOCK_RESIDUE_EPOCH_STR_RE,
    _CLOCK_RESIDUE_IDENTIFIER_RE,
    _CLOCK_RESIDUE_KEY_MAX_LEN,
    _CLOCK_RESIDUE_SEGMENTS,
    _CLOCK_RESIDUE_SPLIT_RE,
    _CLOCK_RESIDUE_SUFFIXES,
    _CLOCK_RESIDUE_UUID_RE,
    _CLOCK_RESIDUE_VALUE_RE,
    _DIGEST_EXCLUDED_TOP_LEVEL,
    _EPOCH_BANDS,
    _INSTRUMENTATION_KEYS,
    _INSTRUMENTATION_SUFFIXES,
)
from zyg_workflows.geom.anthro.report.textfmt import _jsonable


def _measurement_meta(meta):
    """The measurement facts a reader must see to interpret any number above them: the
    convention each girth was taken on, whether the joint regressor ran on this recipe,
    and the ISO caveat. Copied by key rather than wholesale so the artifact does not
    silently grow when measure.py adds a field."""
    keep = (
        'schema',
        'pose',
        'axis_convention',
        'handedness',
        'ground_plane',
        'stature_m',
        'girth_convention',
        'limb_girth_convention',
        'arm_exclusion',
        'coco_source',
        'vertex_scope',
        'density_assumption_kg_m3',
        'iso_caveat',
        'iso_20685_1_table4_mm',
        'units',
        'landmark_module',
        'girth_conventions_also_reported',
        'band_floors',
    )
    return {k: meta[k] for k in keep if k in meta}


def _is_instrumentation_key(key):
    """True if `key` names a wall-clock or elapsed-time field. Exact names and exact
    suffixes only — see the boundary note above _INSTRUMENTATION_KEYS for why this half is
    deliberately conservative and the residue detector is deliberately wide."""
    k = str(key).strip().lower()
    return k in _INSTRUMENTATION_KEYS or any(k.endswith(s) for s in _INSTRUMENTATION_SUFFIXES)


def _digest_strip(obj, path, excluded):
    """A copy of `obj` with every instrumentation key removed AT EVERY DEPTH. Every removal
    is recorded in `excluded` by key path, so nothing leaves the digest silently."""
    if isinstance(obj, dict):
        out = {}
        for k in obj:
            p = ('%s.%s' % (path, k)) if path else str(k)
            if _is_instrumentation_key(k):
                excluded.append(p)
                continue
            out[str(k)] = _digest_strip(obj[k], p, excluded)
        return out
    if isinstance(obj, (list, tuple)):
        return [_digest_strip(v, '%s[%d]' % (path, i), excluded) for i, v in enumerate(obj)]
    return obj


def _looks_like_a_clock_key(key):
    """True if `key` is a FIELD NAME whose segments say wall clock or per-run identity.
    See the note above _CLOCK_RESIDUE_SEGMENTS for why this is segment-wise, why the
    length bail is about prose rather than about length, and what each was measured
    against."""
    k = str(key).strip()
    if len(k) > _CLOCK_RESIDUE_KEY_MAX_LEN and not _CLOCK_RESIDUE_IDENTIFIER_RE.match(k):
        return False  # a paragraph is a citation, not a field name
    low = k.lower()
    if any(low.endswith(s) for s in _CLOCK_RESIDUE_SUFFIXES):
        return True
    segs = {s for s in _CLOCK_RESIDUE_SPLIT_RE.split(low) if s}
    return bool(segs & _CLOCK_RESIDUE_SEGMENTS)


def _looks_like_a_clock_value(v):
    """The half of the test that does not depend on the name (W4-2). Returns a reason or
    None. A bare epoch number is a per-run clock whatever its field is called, and a UUID
    is a per-run identity, which moves the digest for the same reason and is the same
    defect. Booleans are excluded explicitly: in Python they are ints."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            a = abs(float(v))
        except (TypeError, ValueError, OverflowError):
            return None
        for lo, hi, label in _EPOCH_BANDS:
            if lo <= a < hi:
                return 'value is a bare number in the %s range: %r' % (label, v)
        return None
    if isinstance(v, str):
        s = v.strip()
        if _CLOCK_RESIDUE_VALUE_RE.match(s):
            return 'value is a timestamp with a time of day: %r' % s[:32]
        if _CLOCK_RESIDUE_UUID_RE.match(s):
            return 'value is a UUID, which is a per-run identity: %r' % s[:40]
        if _CLOCK_RESIDUE_EPOCH_STR_RE.match(s):
            return 'value is a unix epoch written as a string: %r' % s[:32]
    return None


def _digest_residue(obj, path='', found=None):
    """Anything in the STRIPPED tree that still looks like a per-run clock.

    This is the half that makes the fix hold. The strip only removes names it already
    knows, so the next timer to be added under a name nobody thought of would silently
    return `stable_sha256` to being a nonce — which is exactly how NEW-4 survived two
    re-reviews. Here the test is on SHAPE, not on the vocabulary: a key that reads like a
    clock or a per-run identity, or a VALUE that is one — an ISO date with a time of day on
    it, a bare number in a unix-epoch range, a UUID. A bare date is content (a survey's
    publication date); no anthropometric fact needs an hour and a minute.

    The value half is what makes this a test of the CLASS rather than of a vocabulary
    (W4-2): `created_at`, `gen_sec`, `secs_taken`, `lap`, `tick`, `unix`, `when`, `at` and
    `gate_evaluation_wall_clock_in_milliseconds` were all silent before it existed, and the
    fix for a narrow vocabulary can never be a slightly wider vocabulary.
    """
    if found is None:
        found = []
    if isinstance(obj, dict):
        for k in obj:
            p = ('%s.%s' % (path, k)) if path else str(k)
            if str(k).strip().lower() in _CLOCK_RESIDUE_CONTENT_KEYS:
                continue  # declared content; hashed, so it cannot hide
            if _looks_like_a_clock_key(k):
                found.append(
                    {
                        'path': p,
                        'why': 'key reads as a clock or a per-run '
                        'identity and is not in the '
                        'instrumentation vocabulary',
                    }
                )
                continue  # one finding per subtree, not one per leaf
            _digest_residue(obj[k], p, found)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _digest_residue(v, '%s[%d]' % (path, i), found)
    else:
        why = _looks_like_a_clock_value(obj)
        if why:
            found.append({'path': path, 'why': why})
    return found


def _volatile_content(volatile, path='volatile'):
    """Keys inside the `volatile` block that are NOT instrumentation (W4-4).

    `volatile` is dropped from the digest BY NAME and _digest_residue runs on a tree it has
    already been removed from, so the residue detector cannot see into it: it is the one
    place in the document where content would be invisible to the hash — the mirror image
    of the defect the residue detector exists for, and nothing asserted the boundary. All
    four keys the block carries today are instrumentation; this is what makes that a
    checked fact rather than a habit. A leaf under a nested key is judged on the nested key
    as well, so `volatile.x.stature_m` cannot enter under an instrumentation-shaped parent.
    """
    out = []
    if not isinstance(volatile, dict):
        return out
    for k in sorted(volatile, key=str):
        p = '%s.%s' % (path, k)
        if not _is_instrumentation_key(k):
            out.append(p)
            continue
        v = volatile[k]
        if isinstance(v, dict):
            out.extend(_volatile_content(v, p))
    return out


def _digest_scan(doc):
    """(stripped document, excluded key paths, clock residue). The one place the digest's
    content/instrumentation boundary is applied, so the digest, the block that describes it
    and the self-test cannot use three different definitions of it."""
    d = {k: doc[k] for k in doc if k not in _DIGEST_EXCLUDED_TOP_LEVEL}
    excluded = []
    stripped = _digest_strip(d, '', excluded)
    return stripped, sorted(excluded), _digest_residue(stripped)


def stable_sha(doc):
    """sha256 over the document's CONTENT, so two runs of the same mesh against the same
    pack produce the same digest and a report can be diffed for real change rather than for
    the clock.

    Removed: the volatile block, the digest block, the digest itself, and every
    instrumentation key at every depth — not only the top level. The top-level-only version
    of this function shipped a `stable_sha256` that moved every run, because the per-gate
    wall-clock `ms` that gates.py stamps into `detail` is copied into gates[].evidence
    (re-review NEW-4). See _INSTRUMENTATION_KEYS for the boundary and _selftest_digest for
    the test that would have caught it.
    """
    stripped, _excluded, _residue = _digest_scan(doc)
    return hashlib.sha256(json.dumps(stripped, sort_keys=True, default=_jsonable).encode('utf-8')).hexdigest()


def verdict(doc):
    return doc.get('verdict', ERROR)


def exit_code(doc):
    return EXIT_CODES.get(doc.get('verdict'), EXIT_CODES[ERROR])
