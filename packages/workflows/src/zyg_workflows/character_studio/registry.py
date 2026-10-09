# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The sections, the path helpers, the derived facts and the read/edit API.

Moved verbatim from ``character_studio.py`` lines 937-1294 by the 2026-10-06
modularization split.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional
import logging as _zyg_logging

from .fields import _HEX_RE, LORA_ROOT, MAX_EDITS, MAX_TEXT

# Imported through ``fields_new`` on purpose: that module is what appends the
# second half of the registry, and ``MIRRORS`` below is derived from the
# COMPLETE dict, exactly as it was in the single file.
from .fields_new import FIELDS

_zyg_log = _zyg_logging.getLogger('zyg_workflows.character_studio')


# Sections, in the order the rail reads them.
SECTIONS = [
    'identity',
    'face',
    'eyes',
    'hair',
    'body',
    'wardrobe',
    'accessories',
    'grooming',
    'expression',
    'pose',
    'render',
    'model',
    'voice',
    'motion',
    'checks',
    'dataset',
    'studio',
]

# The lock list lives here. A path in it is refused by edit() — see _locked().
LOCK_FIELD = 'studio.locked_fields'

# A write to either half of a mirrored pair lands on both — see rule 2 up top.
MIRRORS = {spec['mirror']: p for p, spec in FIELDS.items() if spec.get('mirror')}


# ── path helpers ─────────────────────────────────────────────────────────────
def _get(pkg: dict, path: str) -> Any:
    cur: Any = pkg
    for part in path.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set(pkg: dict, path: str, value: Any) -> None:
    parts = path.split('.')
    cur = pkg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _coerce(spec: dict, raw: Any) -> Any:
    """Types are enforced HERE, not in the browser. A number that arrives as the
    string '0.85' is stored as 0.85 — a bible whose lora_scale is a string makes
    the renderer's float() throw at load time, hours after the edit."""
    t = spec['t']
    if t == 'bool':
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
    if t in ('int', 'float'):
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None  # an explicitly cleared number
        try:
            v = int(raw) if t == 'int' else float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'not a number: {str(raw)[:40]!r}') from exc
        lo, hi = spec.get('min'), spec.get('max')
        if lo is not None and v < lo:
            raise ValueError(f'below the minimum ({lo})')
        if hi is not None and v > hi:
            raise ValueError(f'above the maximum ({hi})')
        return v
    s = '' if raw is None else str(raw)
    if len(s) > MAX_TEXT:
        raise ValueError(f'longer than {MAX_TEXT} characters')
    s = s.strip()
    if t == 'plate':
        if not s:
            return ''  # clearing the field is always allowed
        name = spec.get('_char') or ''
        try:
            import zyg_workflows.geom.body_plates as BP
        except Exception as e:  # noqa: BLE001
            raise ValueError(f'plate validation unavailable ({e})') from e
        if not BP.is_plate_path(name, s):
            raise ValueError(
                "not one of this character's rendered plates — run the plate render first, then pick one of its files"
            )
        return os.path.realpath(s)
    if t == 'colour':
        if not s:
            return ''  # cleared: "whatever the outfit says"
        if not _HEX_RE.match(s):
            raise ValueError(f'not a #rrggbb colour: {s[:40]!r}')
        return s.lower()
    if t == 'enum' and not spec.get('open'):
        if s not in spec.get('choices', []):
            raise ValueError(f'not one of the allowed values: {s[:40]!r}')
    return s


def _locked_paths(pkg: dict) -> set[str]:
    """The lock list as a set, parsed defensively.

    The field is an area, so it holds whatever a human or a client last typed.
    Anything that is not a JSON list of strings locks NOTHING: a lock list that
    fails to parse must not become a lock on the whole bible, because the only
    way out of that would be an edit the lock itself refuses."""
    raw = _get(pkg, LOCK_FIELD)
    if isinstance(raw, list):
        return {str(x) for x in raw if isinstance(x, str)}
    if not isinstance(raw, str) or not raw.strip():
        return set()
    try:
        parsed = json.loads(raw)
    except ValueError:
        return set()
    if not isinstance(parsed, list):
        return set()
    return {x for x in parsed if isinstance(x, str)}


# ── derived facts, measured off disk ─────────────────────────────────────────
_FAMILIES = ('flux', 'sdxl', 'klein', 'qwen')


def _stat(p: Optional[str]) -> Optional[dict]:
    if not p or not isinstance(p, str):
        return None
    try:
        st = os.stat(p)
    except OSError:
        return {'path': p, 'exists': False}
    return {'path': p, 'exists': True, 'bytes': st.st_size, 'mtime': round(st.st_mtime, 1)}


def derived(char_id: str, char_dir: str, pkg: dict) -> dict:
    """What is TRUE about this character on disk right now — as opposed to what
    the bible claims. The two disagree often enough (a bible naming a LoRA that
    was never trained, a path left over from a deleted run) that the panels show
    both and the difference is the point."""
    cond = pkg.get('conditioning') or {}
    loras = {}
    for fam in _FAMILIES:
        # the bible's claim...
        claimed = cond.get(f'{fam}_lora_path')
        if fam == 'flux' and not claimed:
            claimed = cond.get('lora_path')
        # ...and the file the standard layout would put it at, claim or not
        std = os.path.join(LORA_ROOT, char_id, f'lora-weights-{fam}', 'pytorch_lora_weights.safetensors')
        loras[fam] = {'claimed': _stat(claimed), 'standard': _stat(std)}

    imgs = {}
    for cat, rel in (
        ('arcane_final', 'arcane_instantid'),
        ('cells', os.path.join('contact_sheet', 'cells')),
        ('tiles', os.path.join('contact_sheet', 'tiles')),
        ('training', 'training'),
        ('training_sdxl_animated', 'training_sdxl_animated'),
        ('training_photoreal_sdxl', 'training_photoreal_sdxl'),
    ):
        d = os.path.join(char_dir, rel)
        n = 0
        newest = 0.0
        try:
            for fn in os.listdir(d):
                if fn.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    n += 1
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(d, fn)))
                    except OSError as _exc:
                        _zyg_log.debug('image mtime unavailable: %s', _exc)
        except OSError as _exc:
            _zyg_log.debug('image dir listing skipped: %s', _exc)
        imgs[cat] = {'count': n, 'newest': round(newest, 1) if newest else 0}

    manifest = {}
    try:
        with open(os.path.join(char_dir, 'contact_sheet', 'manifest.json'), encoding='utf-8') as f:
            m = json.load(f)
        q = m.get('identity_qc') or {}
        manifest = {
            'approved': m.get('approved'),
            'qc_counts': q.get('counts'),
            'qc_mean': q.get('mean_score'),
            'qc_total': q.get('total'),
            'qc_excluded': q.get('excluded_from_dataset'),
            'angles': m.get('angles') if isinstance(m.get('angles'), (int, list)) else None,
            'keys': sorted(m.keys())[:40],
        }
    except Exception:
        manifest = {'missing': True}

    hist = pkg.get('scene_history')
    return {
        'loras': loras,
        'images': imgs,
        'manifest': manifest,
        'scene_history_count': len(hist) if isinstance(hist, list) else 0,
        'scene_history_tail': (hist[-8:] if isinstance(hist, list) else []),
        'generation_stats': pkg.get('generation_stats') or {},
        'dir': char_dir,
        'dir_bytes': _dir_bytes(char_dir),
        'server_time': round(time.time(), 1),
    }


def _dir_bytes(d: str, cap: int = 40000) -> int:
    """Size of the character's tree. Capped at `cap` files so a character with a
    runaway output folder cannot stall the request."""
    total = 0
    seen = 0
    for root, _dirs, files in os.walk(d):
        for fn in files:
            seen += 1
            if seen > cap:
                return total
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError as _exc:
                _zyg_log.debug('file size unavailable: %s', _exc)
    return total


# ── the API the server routes to ─────────────────────────────────────────────
def _cbs():
    from zyg_workflows import character_bible_service

    return character_bible_service


def spec() -> dict:
    """The field registry, as the client needs it: which paths exist, what type
    each is, what may be written. One source of truth — the browser builds its
    editors from this rather than hard-coding a type per knob."""
    return {
        'sections': SECTIONS,
        'fields': {p: dict(s) for p, s in FIELDS.items()},
        'max_text': MAX_TEXT,
        'max_edits': MAX_EDITS,
    }


def _values(pkg: dict) -> dict:
    """Every registered path, with the spec default standing in for a key the
    bible does not hold yet.

    The new 2026-09-18 groups are absent from all 132 bibles on disk until
    someone edits them, and a panel that renders `undefined` into a slider is
    worse than one that renders the default: the operator cannot tell "not set"
    from "broken". `values` is therefore what the field IS, defaulted — the
    bible itself is still served untouched under `bible`, so a caller that needs
    to know whether the key exists can look there."""
    out = {}
    for p, s in FIELDS.items():
        v = _get(pkg, p)
        if v is None and 'default' in s:
            v = s['default']
        out[p] = v
    return out


def read(char_id: str, char_dir: str) -> dict:
    pkg = _cbs().load(char_id)
    if pkg is None:
        return {'ok': False, 'error': 'no character_bible.json for this character'}
    return {
        'ok': True,
        'id': char_id,
        'values': _values(pkg),
        'locked': sorted(_locked_paths(pkg)),
        'bible': pkg,
        'derived': derived(char_id, char_dir, pkg),
    }


def edit(char_id: str, char_dir: str, edits: dict) -> dict:
    """Apply a whitelisted set of dotted-path edits and save through the bible
    service. Returns what was ACTUALLY written — the age invariant may rewrite
    age_range under a change to age, and the caller has to be able to see that
    rather than assume its own value landed."""
    if not isinstance(edits, dict) or not edits:
        return {'ok': False, 'error': 'no edits'}
    if len(edits) > MAX_EDITS:
        return {'ok': False, 'error': f'too many fields at once (max {MAX_EDITS})'}

    cbs = _cbs()
    pkg = cbs.load(char_id)
    if pkg is None:
        return {'ok': False, 'error': 'no character_bible.json for this character'}

    before = _values(pkg)
    # The lock list as it stands BEFORE this batch. Unlocking and editing in one
    # request is allowed on purpose — otherwise the page would need two round
    # trips and the operator would see a refusal for an edit they had just
    # authorised. Writing the lock list is never itself refused, or a bad list
    # would be unremovable.
    locked = _locked_paths(pkg)
    unlocking = LOCK_FIELD in edits

    applied, rejected = {}, {}
    for path, raw in edits.items():
        spec_ = FIELDS.get(path)
        if not spec_:
            rejected[path] = 'not an editable field'
            continue
        if spec_['t'] == 'ro':
            rejected[path] = 'read-only'
            continue
        if path in locked and not unlocking:
            rejected[path] = 'locked'
            continue
        try:
            # the plate validator needs to know WHOSE plates are acceptable; every
            # other type ignores it
            val = _coerce(dict(spec_, _char=char_id) if spec_['t'] == 'plate' else spec_, raw)
        except ValueError as e:
            rejected[path] = str(e)
            continue
        _set(pkg, path, val)
        applied[path] = val
        mirror = spec_.get('mirror')
        if mirror:
            _set(pkg, mirror, val)
            applied[mirror] = val
        # ...and the other direction, if someone writes the legacy flat key
        back = MIRRORS.get(path)
        if back:
            _set(pkg, back, val)
            applied[back] = val

    if not applied:
        return {'ok': False, 'error': 'nothing applied', 'rejected': rejected}

    try:
        path_out = cbs.save(pkg)
    except Exception as e:  # noqa: BLE001 — surfaced to the UI
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'[:200]}

    saved = cbs.load(char_id) or pkg
    values = _values(saved)
    # what the SAVE changed that the caller did not ask for — the age invariant
    # is the one that does this, and it must not happen silently. updated_at is
    # excluded: it changes on EVERY save by design, so reporting it would bury
    # the one line that matters under a line that always fires.
    forced = {p: values[p] for p in FIELDS if p not in applied and p != 'updated_at' and values[p] != before.get(p)}
    return {
        'ok': True,
        'id': char_id,
        'file': path_out,
        'applied': applied,
        'rejected': rejected,
        'forced': forced,
        'locked': sorted(_locked_paths(saved)),
        'values': values,
        'derived': derived(char_id, char_dir, saved),
    }
