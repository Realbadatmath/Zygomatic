# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""manifest.py — the asset register. One record per object, and no object without one.

THE RULES THIS FILE ENFORCES
    Every object must have a photoreal reference image.
    Every object must have readable geometry.
Both are properties of an ASSET, not of a render, so they are checked where assets are
admitted rather than discovered later in a frame. `Manifest.add` refuses a record that has
no reference or no geometry, and refuses any file whose licence is not on the allow list.

WHY THE LICENCE CHECK IS A HARD FAIL AND NOT A WARNING.
This production publishes commercially, so the allow list is Apache-2.0 / MIT / BSD / CC0
and public domain, full stop. A warning gets scrolled past; by the time a non-commercial
texture is three renders deep in a delivered episode it is far more expensive to remove
than to have been refused. Every admitted file therefore carries its licence, its source
URL and its sha256 — the same provenance discipline the wound library already uses, made
mandatory rather than conventional.

THE MANIFEST IS ALSO THE GATE'S INPUT. G2 cannot compute texel density without knowing an
object's world size and its texture resolution, and no render pass carries those. They
live here, next to the licence, because both are facts about the asset rather than the
shot.
"""

import hashlib
import json
import os
import time

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'assets', 'manifest.json'
)

# Canonical spellings, and every variant seen in the wild that maps to them. Anything that
# does not normalise to a key of this dict is refused — including the near-misses that are
# easiest to wave through: CC-BY needs attribution we cannot carry through a restyle, and
# CC-BY-NC is simply out.
_LICENCE_ALIASES = {
    'cc0': 'CC0-1.0',
    'cc0 1.0': 'CC0-1.0',
    'cc0-1.0': 'CC0-1.0',
    'cc zero': 'CC0-1.0',
    'creative commons zero': 'CC0-1.0',
    'cc0 1.0 universal': 'CC0-1.0',
    'publicdomain': 'CC0-1.0',
    'pdm': 'public-domain',
    'public domain': 'public-domain',
    'public domain mark': 'public-domain',
    'pd': 'public-domain',
    'no restrictions': 'public-domain',
    'mit': 'MIT',
    'mit license': 'MIT',
    'apache-2.0': 'Apache-2.0',
    'apache 2.0': 'Apache-2.0',
    'apache2': 'Apache-2.0',
    'bsd': 'BSD-3-Clause',
    'bsd-3-clause': 'BSD-3-Clause',
    'bsd 3-clause': 'BSD-3-Clause',
    'bsd-2-clause': 'BSD-2-Clause',
    'new bsd': 'BSD-3-Clause',
}

ALLOWED = {
    'CC0-1.0',
    'public-domain',
    'MIT',
    'Apache-2.0',
    'BSD-3-Clause',
    'BSD-2-Clause',
    # our own render/generation output — provenance is the pipeline itself
    'internal-owned',
}
_LICENCE_ALIASES.update(
    {'internal': 'internal-owned', 'own-work': 'internal-owned', 'internal-owned': 'internal-owned'}
)

KINDS = ('tree', 'prop', 'leaf', 'material', 'ref', 'terrain', 'character')


class LicenceRefused(Exception):
    pass


def normalise_licence(text):
    """Canonical licence id, or None if it is not one we may publish.

    Returns None rather than raising so a bulk ingest can count what it skipped; callers
    that are admitting a single file should raise LicenceRefused on None.
    """
    if not text:
        return None
    t = str(text).strip().lower().rstrip('.')
    for junk in ('licence', 'license'):
        if t.endswith(' ' + junk):
            t = t[: -len(junk) - 1].strip()
    return _LICENCE_ALIASES.get(t)


def is_allowed(text):
    return normalise_licence(text) in ALLOWED


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(chunk), b''):
            h.update(b)
    return h.hexdigest()


def provenance(path, licence, source, url, extra=None):
    """One admitted file. Raises rather than returning a record we may not publish."""
    canon = normalise_licence(licence)
    if canon not in ALLOWED:
        raise LicenceRefused(
            '%s: licence %r normalises to %r, not in %s' % (os.path.basename(path), licence, canon, sorted(ALLOWED))
        )
    rec = {
        'file': path,
        'licence': canon,
        'licence_raw': str(licence),
        'source': source,
        'url': url,
        'sha256': sha256(path) if os.path.exists(path) else None,
        'bytes': os.path.getsize(path) if os.path.exists(path) else None,
        'ingested': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    rec.update(extra or {})
    return rec


def asset(
    aid,
    kind,
    refs=None,
    geometry=None,
    material=None,
    pass_index=None,
    world_span_m=None,
    embedded_in=None,
    tier_hint=None,
    notes='',
):
    """Build one asset record. `refs` and `geometry` are what the rules demand."""
    if kind not in KINDS:
        raise ValueError('unknown kind %r (have %s)' % (kind, ', '.join(KINDS)))
    return {
        'id': aid,
        'kind': kind,
        'refs': list(refs or []),
        'geometry': geometry,  # {'file','format','polycount','source','licence'}
        'material': material,  # {'maps':{...},'texture_px':N,'licence',...}
        'pass_index': pass_index,  # the integer the IndexOB pass will carry
        'world_span_m': world_span_m,  # largest world dimension — G2 needs it
        'embedded_in': embedded_in,  # host asset id, or None. G3b only runs when set.
        'tier_hint': tier_hint,  # advisory only; the gate measures the real tier
        'notes': notes,
        'gate': None,  # last gate verdict, filled by the gate
    }


class Manifest:
    """The register. Refuses records that break the rules; nothing else may write it."""

    # 'ref' and 'material' records are inputs to other assets and are exempt from needing
    # geometry of their own — a bark photograph is not supposed to have a mesh.
    NEEDS_GEOMETRY = ('tree', 'prop', 'leaf', 'terrain')

    def __init__(self, path=MANIFEST_PATH):
        self.path = path
        self.doc = {'version': 1, 'assets': {}}
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                self.doc = json.load(f)
        self.doc.setdefault('assets', {})

    # ── policy ──────────────────────────────────────────────────────────────
    def _check(self, rec, strict=True):
        aid, kind = rec['id'], rec['kind']
        problems = []
        if not rec.get('refs'):
            problems.append('no photoreal reference image')
        if kind in self.NEEDS_GEOMETRY and not rec.get('geometry'):
            problems.append('no geometry')
        for r in rec.get('refs') or []:
            if r.get('licence') not in ALLOWED:
                problems.append('ref %s has licence %r' % (r.get('file'), r.get('licence')))
        # THE INSPECTION RULE (2026-08-04). A downloaded reference nobody looked at is not
        # a reference — it is a filename. The Met "axe heads" cited as the hurlbat profile
        # source turned out, on inspection, to be neolithic stone celts; the first backfill
        # run then FAILED those very images automatically, which is the rule earning its
        # keep on day one. Every ref carries a `verified` block (geom.verify_refs writes
        # it) saying a judge LOOKED at the image and answered whether it shows the subject.
        #
        # THE ASSET passes when it has at least one CONFIRMED reference. Individual refs
        # that fail inspection stay in the record with shows_subject=false — excluded and
        # countable, not deleted — because "we fetched 15 and only 3 show the subject" is
        # exactly the curation fact worth keeping (measured: the wound sweep was 3/15).
        # Enforced on kind='ref'/'character'; disable only via ZYG_REQUIRE_VERIFIED_REFS=0.
        if kind in ('ref', 'character') and os.environ.get('ZYG_REQUIRE_VERIFIED_REFS', '1') == '1':
            refs = rec.get('refs') or []
            confirmed = sum(
                1 for r in refs if isinstance(r.get('verified'), dict) and r['verified'].get('shows_subject')
            )
            uninspected = sum(1 for r in refs if not isinstance(r.get('verified'), dict))
            if confirmed == 0:
                problems.append(
                    'NO CONFIRMED reference (%d refs: %d failed inspection, '
                    '%d never inspected)' % (len(refs), len(refs) - uninspected, uninspected)
                )
        for block in ('geometry', 'material'):
            b = rec.get(block)
            if isinstance(b, dict) and b.get('licence') and b['licence'] not in ALLOWED:
                problems.append('%s has licence %r' % (block, b['licence']))
        if problems and strict:
            raise LicenceRefused('asset %r refused: %s' % (aid, '; '.join(problems)))
        return problems

    def add(self, rec, strict=True):
        self._check(rec, strict=strict)
        used = {a.get('pass_index') for k, a in self.doc['assets'].items() if k != rec['id'] and a.get('pass_index')}
        if rec.get('pass_index') in used:
            raise ValueError('pass_index %s already taken — the IndexOB pass would be ambiguous' % rec['pass_index'])
        self.doc['assets'][rec['id']] = rec
        return rec

    def next_pass_index(self):
        used = {a.get('pass_index') or 0 for a in self.doc['assets'].values()}
        i = 1
        while i in used:
            i += 1
        return i

    # ── access ──────────────────────────────────────────────────────────────
    def get(self, aid):
        return self.doc['assets'].get(aid)

    def list(self, kind=None):
        return [a for a in self.doc['assets'].values() if kind is None or a['kind'] == kind]

    def index_map(self):
        """{pass_index: asset_id} — what the gate needs to name what it measured."""
        return {a['pass_index']: a['id'] for a in self.doc['assets'].values() if a.get('pass_index')}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.doc['saved'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.doc, f, indent=1)
        os.replace(tmp, self.path)
        return self.path

    def audit(self):
        """Every rule violation across the register, without raising. For the report."""
        out = {}
        for aid, rec in self.doc['assets'].items():
            p = self._check(rec, strict=False)
            if p:
                out[aid] = p
        return out
