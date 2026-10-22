# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""capabilities_tests.py — load, merge and VALIDATE the default test behind a capability sheet.

    python3 capabilities_tests.py list                 every step, has-test / columns / hash
    python3 capabilities_tests.py check <step|all>     the honesty audit: every column, one disposition
    python3 capabilities_tests.py columns <step>       per column: how the test answers it
    python3 capabilities_tests.py show <step>          the merged test as JSON (what a runner receives)
    python3 capabilities_tests.py questions <step>     every column the sheet asks, grouped — no test module needed
    python3 capabilities_tests.py shared <kind> [--strict]
                                                       validate capability_tests/<kind>_shared.py and print, per step of
                                                       that kind, which asked columns the bank does NOT cover; --strict
                                                       fails when an uncovered column is in a band this kind owns

What "check" enforces (the contract is written out in capability_tests/__init__.py):
  * every column the step's sheet asks (capabilities_questions DOMAIN + BANKS + UNIVERSAL) has
    exactly ONE disposition — probe, derive, lookup, wiring or na — for every row;
  * every id a test mentions is a real column (typo guard: a probe that "feeds" a misspelled
    column would silently answer nothing);
  * every check kind is in CHECK_KINDS, every probe has fixed inputs, repeats and a grade a probe
    may write; every `na` carries a reason of at least 20 characters;
  * every fixture the test points at exists, and an answer key that is not `verified` is
    reported as BLOCKING the columns it feeds.
A test that fails check is not a default test; the hub shows it as broken rather than present.

The merged test is hashed (sha256 of its canonical JSON, 12 hex). A sheet written from a run
records `test_hash`; the board refuses to read two sheets with different hashes as one
comparison. Change a prompt, and the hash says the old cells were measured by another test.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys

CREWS = os.path.dirname(os.path.abspath(__file__))
if CREWS not in sys.path:
    sys.path.insert(0, CREWS)

from zyg_workflows import capabilities_questions as Q  # noqa: E402
from zyg_workflows.devreload import maybe_reload  # noqa: E402
import capability_tests as CT  # noqa: E402

# Under ZYG_DEV_RELOAD=1 the GUI process reloads THIS module per request
# (capabilities_hub.default_test) but a plain import would hand back the package and
# questionnaire it cached at first load — an edited contract (a new transport, a new budget
# field) would then be invisible until a GUI restart.
Q = maybe_reload(Q)
CT = maybe_reload(CT)

STORE = os.environ.get('ZYG_CAPABILITIES_DIR') or os.path.join(CREWS, 'data', 'runtime', 'capabilities')
FIXTURES = os.path.join(CREWS, 'capability_tests', 'fixtures')


# ── the questionnaire, as the sheet asks it ─────────────────────────────────────────
def columns_of(step):
    """DOMAIN → BANKS → UNIVERSAL, first id wins — the same order migrate_capability_questions
    writes into the sheet, so the test is validated against exactly what the sheet asks."""
    out, seen = [], set()
    for c in Q.DOMAIN.get(step, []) + Q.BANKS.get(step, []) + Q.EXTRA.get(step, []) + Q.UNIVERSAL:
        if c['id'] not in seen:
            seen.add(c['id'])
            out.append(c)
    return out


# ── loading & merging ───────────────────────────────────────────────────────────────
def _module(step):
    # Under ZYG_DEV_RELOAD=1, reloaded on every load so an edited test is what the hub serves —
    # the hub polls every 60 s and would otherwise keep the first import for the life of the
    # GUI process.
    mod = importlib.import_module(f'capability_tests.{step}')
    return maybe_reload(mod)


_SHARED_DISPOSITION_KEYS = ('probes', 'derive', 'lookup', 'wiring', 'na', 'transport_na', 'CHECK_KINDS', 'TRANSPORTS')


def shared_module(kind):
    if kind not in CT.SHARED_KINDS:
        raise ValueError(f'unknown shared kind {kind!r} — one of {CT.SHARED_KINDS}')
    mod = importlib.import_module(f'capability_tests.{kind}_shared')
    return maybe_reload(mod)


def shared_bank(kind):
    """The shared bank of one kind as plain data, with the module's own CHECK_KINDS and
    TRANSPORTS additions carried along so the validator can union them."""
    mod = shared_module(kind)
    sh = json.loads(json.dumps(mod.SHARED, default=str))
    sh['CHECK_KINDS'] = dict(getattr(mod, 'CHECK_KINDS', {}) or {})
    sh['TRANSPORTS'] = dict(getattr(mod, 'TRANSPORTS', {}) or {})
    return sh


def _merge_shared(t, sh, asked):
    """Merge one shared bank INTO a step test. The bank is generic: an entry for a column this
    step does not ask is dropped silently — only the STEP module's own ids are typo-checked.
    Anything the step (or an earlier bank) already owns wins over the bank."""
    step_na = set((t.get('na') or {}).keys())
    owned = step_na | {c for p in t.get('probes', []) for c in p.get('feeds', [])}
    for k in ('derive', 'lookup', 'wiring'):
        owned |= set((t.get(k) or {}).keys())
    merged = []
    for p in sh.get('probes') or []:
        p = dict(p)
        p['shared'] = True
        p['feeds'] = [c for c in p['feeds'] if c in asked and c not in owned]
        if p['feeds']:  # a shared probe with nothing left to answer is not run here
            merged.append(p)
            owned |= set(p['feeds'])
    t['probes'] = merged + list(t.get('probes', []))
    for k in ('derive', 'lookup', 'wiring'):
        base = {
            c: v
            for c, v in (sh.get(k) or {}).items()
            if (c in asked or (isinstance(v, dict) and v.get('feeds_derive'))) and c not in owned
        }
        base.update(t.get(k) or {})
        t[k] = base
        owned |= set(base.keys())
    na = {c: v for c, v in (sh.get('na') or {}).items() if c in asked and c not in owned}
    na.update(t.get('na') or {})
    t['na'] = na
    tna = dict(t.get('transport_na') or {})
    for tr, cols in (sh.get('transport_na') or {}).items():
        cur = dict(tna.get(tr) or {})
        for c, why in (cols or {}).items():
            if c in asked and c not in cur:
                cur[c] = why
        tna[tr] = cur
    t['transport_na'] = tna
    t.setdefault('check_kinds_added', {}).update(sh.get('CHECK_KINDS') or {})
    t.setdefault('transports_added', {}).update(sh.get('TRANSPORTS') or {})


def _budget_totals(t):
    """`budget.per_row` and `budget.total` from the test-level budget plus per-row overrides.
    Never raises — the validator reports a bad budget as an error."""
    b = t.get('budget')
    if not isinstance(b, dict):
        return
    rows = t.get('rows') or {}
    per, tot = {}, {k: 0.0 for k in CT.BUDGET_NUMERIC}
    for rid, r in rows.items():
        rb = dict(b)
        rb.update((r.get('budget') or {}) if isinstance(r, dict) else {})
        per[rid] = {}
        for k in CT.BUDGET_NUMERIC:
            try:
                v = float(rb.get(k) or 0)
            except (TypeError, ValueError):
                v = 0.0
            per[rid][k] = v
            tot[k] += v
    b['rows'] = len(rows)
    b['per_row'] = per
    b['total'] = tot


def load_test(step):
    """The merged test: the step module's TEST plus the shared bank it includes. Returns None
    when the step has no test module. Step-level `na` beats a shared probe (the column is
    dropped from that probe's feeds for this step) so a step can say "this shared question
    does not apply here" without editing the shared bank."""
    try:
        mod = _module(step)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.endswith(step):
            return None
        raise
    t = json.loads(json.dumps(mod.TEST, default=str))  # a deep copy, plain data
    t.setdefault('step', step)
    inc = t.pop('include_shared', None)
    # Step-level `na_bands`: whole question bands the step cannot answer (a transcriber has no
    # prompt). Expanded into plain `na` entries BEFORE the shared merge, so the sheet view says
    # na on those columns instead of listing a shared probe that no row would run.
    nb = t.pop('na_bands', None)
    if nb:
        na = dict(t.get('na') or {})
        owned = {c for p in t.get('probes', []) for c in p.get('feeds', [])}
        for k in ('derive', 'lookup', 'wiring'):
            owned |= set((t.get(k) or {}).keys())
        for c in columns_of(step):
            if (c.get('group') or '') in nb.get('bands', []) and c['id'] not in na and c['id'] not in owned:
                na[c['id']] = nb.get('reason') or 'band marked not applicable for this step'
        t['na'] = na
    asked = {c['id'] for c in columns_of(step)}
    kinds = [inc] if isinstance(inc, str) else list(inc or [])
    t['shared'] = {}
    for kind in kinds:
        sh = shared_bank(kind)
        _merge_shared(t, sh, asked)
        t['shared'][kind] = {k: v for k, v in sh.items() if k not in _SHARED_DISPOSITION_KEYS}
    t['include_shared'] = kinds
    # A row may declare whole bands not applicable (`na_bands`: a builder with no prompt); the
    # loader expands that into one `na` per column of those bands, reason attached, so the
    # per-row view and the runner see plain columns.
    groups = {c['id']: (c.get('group') or '') for c in columns_of(step)}
    for _rid, r in (t.get('rows') or {}).items():
        # `skip`: the whole row is not run (a retired model kept for its receipt) — every
        # column becomes na with that reason, so the sheet says why instead of showing untested
        if r.get('skip'):
            na = dict(r.get('na') or {})
            for cid in groups:
                na.setdefault(cid, str(r['skip']))
            r['na'] = na
        nb = r.pop('na_bands', None)
        if nb:
            na = dict(r.get('na') or {})
            for cid, g in groups.items():
                if g in nb.get('bands', []) and cid not in na:
                    na[cid] = nb.get('reason') or 'band marked not applicable for this row'
            r['na'] = na
    t.setdefault('check_kinds_added', {}).update(dict(getattr(mod, 'CHECK_KINDS', {}) or {}))
    t.setdefault('transports_added', {}).update(dict(getattr(mod, 'TRANSPORTS', {}) or {}))
    _budget_totals(t)
    t['hash'] = test_hash(t)
    return t


def test_hash(t):
    body = {k: v for k, v in t.items() if k not in ('hash', 'budget')}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]


# ── validation ──────────────────────────────────────────────────────────────────────
def _sheet_rows(step):
    from zyg_dashboard.capabilities_hub import sheet_path

    p = sheet_path(step)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            rec = json.load(f)
    except Exception:
        return None
    return [r.get('id') for r in (rec.get('rows') or [])]


def dispositions(t, step):
    """{column_id: [(kind, ref), …]} over the whole sheet (before row overrides)."""
    d = {c['id']: [] for c in columns_of(step)}
    unknown = []

    def put(col, kind, ref):
        if col in d:
            d[col].append((kind, ref))
        else:
            unknown.append((kind, ref, col))

    for p in t.get('probes', []):
        for c in p.get('feeds', []):
            put(c, 'probe', p['id'])
    for kind in ('derive', 'lookup', 'wiring', 'na'):
        for c, v in (t.get(kind) or {}).items():
            if kind == 'lookup' and isinstance(v, dict) and v.get('feeds_derive'):
                continue  # a helper table, not a column
            put(c, kind, c)
    return d, unknown


def validate(step):
    t = load_test(step)
    if t is None:
        return {'step': step, 'present': False, 'ok': False, 'errors': ['no test module'], 'warnings': []}
    errors, warnings = [], []
    cols = columns_of(step)
    col_ids = {c['id'] for c in cols}
    d, unknown = dispositions(t, step)
    for kind, ref, col in unknown:
        errors.append(f'{kind} {ref!r} names {col!r}, which is not a column of {step}')
    missing = [c for c, v in d.items() if not v]
    multi = {
        c: v for c, v in d.items() if len({k for k, _ in v}) > 1 or (len(v) > 1 and all(k != 'probe' for k, _ in v))
    }
    for c in missing:
        errors.append(f'column {c!r} has NO disposition — it would ship as untested with no reason')
    for c, v in multi.items():
        errors.append(f'column {c!r} has more than one disposition: ' + ', '.join(f'{k}:{r}' for k, r in v))

    check_kinds = dict(CT.CHECK_KINDS)
    check_kinds.update(t.get('check_kinds_added') or {})
    transports = dict(CT.TRANSPORTS)
    transports.update(t.get('transports_added') or {})

    # budget: what the test is expected to cost, per row, before anyone runs it
    b = t.get('budget')
    if not isinstance(b, dict):
        errors.append(
            'no `budget` — the test must say what it costs (calls, tokens_in, tokens_out, minutes, gpu_minutes, operator_minutes, note)'
        )
    else:
        for k in CT.BUDGET_REQUIRED:
            if k not in b:
                errors.append(f'budget: missing {k!r}')
        for k in CT.BUDGET_NUMERIC:
            v = b.get(k)
            if k in b and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
                errors.append(f'budget: {k!r} must be a number >= 0 (got {v!r})')
        if isinstance(b.get('calls'), (int, float)) and b.get('calls', 0) <= 0:
            errors.append('budget: `calls` must be > 0')
        if isinstance(b.get('minutes'), (int, float)) and b.get('minutes', 0) <= 0:
            errors.append('budget: `minutes` must be > 0')
        if not isinstance(b.get('note'), str) or len(b.get('note') or '') < 40:
            errors.append('budget: `note` must hold the arithmetic (>= 40 chars)')
        if not (b.get('tokens_in') or b.get('tokens_out')):
            if not isinstance(b.get('tokens_note'), str) or len(b['tokens_note']) < 20:
                errors.append('budget: tokens_in and tokens_out are both 0 — `tokens_note` (>= 20 chars) must say why')
        for rid, r in (t.get('rows') or {}).items():
            rb = (r.get('budget') or {}) if isinstance(r, dict) else {}
            for k, v in rb.items():
                if k in CT.BUDGET_NUMERIC and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
                    errors.append(f'row {rid!r} budget: {k!r} must be a number >= 0')
                elif k not in CT.BUDGET_NUMERIC and k not in ('note', 'tokens_note'):
                    errors.append(f'row {rid!r} budget: unknown field {k!r}')

    # probes
    seen = set()
    for p in t.get('probes', []):
        pid = p.get('id') or '?'
        if pid in seen:
            errors.append(f'duplicate probe id {pid!r}')
        seen.add(pid)
        if not p.get('feeds'):
            warnings.append(f'probe {pid!r} feeds no column on this step (all its columns were overridden)')
        if p.get('grade') not in CT.DISPOSITION_GRADES['probe']:
            errors.append(f'probe {pid!r}: grade {p.get("grade")!r} is not one a probe may write')
        ins = p.get('inputs') or {}
        # the same input keys validate_shared accepts — a bank probe merged into a step must not
        # fail here for carrying its input under `command` or `image` (2026-09-30 tree finding)
        if not any(ins.get(k) for k in ('prompt', 'task', 'fixture', 'audio', 'image', 'video', 'mesh', 'command')):
            errors.append(f'probe {pid!r}: no fixed input (prompt/task/fixture/audio/image/video/mesh/command)')
        cond = p.get('conditions') or {}
        if not cond.get('repeats'):
            errors.append(f'probe {pid!r}: no repeat count')
        if not p.get('checks'):
            errors.append(f'probe {pid!r}: no checks')
        for ch in p.get('checks') or []:
            if ch.get('check') not in check_kinds:
                errors.append(f'probe {pid!r}: unknown check kind {ch.get("check")!r}')
            if ch.get('check') == 'operator' and not ch.get('question'):
                errors.append(f'probe {pid!r}: operator check without a written question')
        sr = p.get('state_rule') or CT.STATE_RULE
        if not (0 < sr.get('partial', 0) < sr.get('yes', 0) <= 1):
            errors.append(f'probe {pid!r}: state_rule must satisfy 0 < partial < yes <= 1')

    for kind in ('derive', 'lookup', 'wiring'):
        for c, v in (t.get(kind) or {}).items():
            if not isinstance(v, dict):
                errors.append(f'{kind} {c!r}: not an object')
                continue
            g = v.get('grade')
            allowed = CT.DISPOSITION_GRADES[kind]
            if kind == 'derive' and g == 'lowest of inputs':
                pass
            elif g not in allowed:
                errors.append(f'{kind} {c!r}: grade {g!r} not allowed for {kind} (allowed {allowed})')
            if kind == 'lookup' and not v.get('requires'):
                errors.append(f'lookup {c!r}: no `requires` — a lookup without a pinned source is an opinion')
    for c, reason in (t.get('na') or {}).items():
        if not isinstance(reason, str) or len(reason) < 20:
            errors.append(f'na {c!r}: reason too short ("{reason}")')

    # rows
    rows = t.get('rows') or {}
    if not rows:
        errors.append('no rows: the test must name the models it is for')
    sheet_rows = _sheet_rows(step)
    for rid, r in rows.items():
        tr = r.get('transport')
        if tr not in transports:
            errors.append(f'row {rid!r}: unknown transport {tr!r}')
        if r.get('skip') is not None and (not isinstance(r['skip'], str) or len(r['skip']) < 20):
            errors.append(f'row {rid!r}: `skip` needs a written reason (>= 20 chars)')
        for c, reason in (r.get('na') or {}).items():
            if c not in col_ids:
                errors.append(f'row {rid!r} na names {c!r}, not a column')
            if not isinstance(reason, str) or len(reason) < 20:
                errors.append(f'row {rid!r} na {c!r}: reason too short')
        for c in (t.get('transport_na') or {}).get(tr or '', {}):
            if c not in col_ids:
                warnings.append(f'transport_na[{tr}] names {c!r}, not a column of {step} (ignored here)')
    if sheet_rows is not None:
        for rid in sheet_rows:
            if rid not in rows:
                errors.append(f'sheet row {rid!r} is not covered by the test — a model in the sheet with no test')
        for rid in rows:
            if rid not in sheet_rows:
                warnings.append(f'test row {rid!r} is not (yet) a row of the sheet')
    else:
        warnings.append('no sheet recorded for this step yet; rows checked against the test only')

    # fixtures & keys
    blocked = {}
    for fx in t.get('fixtures') or []:
        path = fx.get('path') if isinstance(fx, dict) else fx
        ap = path if os.path.isabs(path) else os.path.join(CREWS, path)
        if not os.path.exists(ap):
            if isinstance(fx, dict) and fx.get('generated'):
                warnings.append(f'fixture {path} is generated by the runner ({fx["generated"]}) — not on disk yet')
            else:
                errors.append(f'fixture missing: {path}')
        if isinstance(fx, dict) and fx.get('verified') is False:
            for c in fx.get('blocks') or []:
                blocked.setdefault(c, []).append(path)
    for k in t.get('keys_unverified') or []:
        for c in k.get('blocks') or []:
            blocked.setdefault(c, []).append(k.get('id') or 'key')
    for c, why in blocked.items():
        warnings.append(
            f'column {c!r} is BLOCKED until verified: {", ".join(why)} — the runner writes untested "key unverified"'
        )

    kinds = {}
    for v in d.values():
        for k, _ in v[:1]:
            kinds[k] = kinds.get(k, 0) + 1
    return {
        'step': step,
        'present': True,
        'ok': not errors,
        'version': t.get('version'),
        'hash': t['hash'],
        'title': t.get('title'),
        'columns': len(cols),
        'probes': len(t.get('probes', [])),
        'operator_checks': sum(
            1 for p in t.get('probes', []) for ch in p.get('checks', []) if ch.get('check') == 'operator'
        ),
        'dispositions': kinds,
        'rows': list(rows.keys()),
        'blocked': sorted(blocked),
        'errors': errors,
        'warnings': warnings,
        'module': f'capability_tests/{step}.py',
        'include_shared': t.get('include_shared') or [],
        'budget': t.get('budget') if isinstance(t.get('budget'), dict) else None,
        'check_kinds_added': sorted((t.get('check_kinds_added') or {}).keys()),
        'transports_added': sorted((t.get('transports_added') or {}).keys()),
    }


# Which shared banks a step includes, in order. Default: [PROMPT_KIND[step]]. The mixed steps
# ask bands of two kinds (body_fit is judged but asks the Moves bank; diarization is a judge
# with audio capacity; audio_judges hears; rigging is geometry over a moving body). The four
# prompt-less steps have no PROMPT_KIND and are named here so their capacity + universal
# columns still have a bank.
STEP_KINDS = {
    'body_fit': ['video', 'judge'],
    'diarization': ['audio', 'judge'],
    'audio_judges': ['audio', 'judge'],
    'rigging': ['video', 'geometry'],
    'stem_split': ['audio'],
    'interp': ['video'],
    'video_assembly': ['video'],
    'pixel_gates': ['judge'],
    'lipsync': ['video', 'audio'],  # lipsync asks the AUDIO capacity band (acap_*)
}
_ALL_KINDS = ('text', 'image', 'video', 'audio', 'judge', 'geometry')
# Which kinds' banks must cover a band (matched on the group name's prefix). Capacity is split
# on the column id: acap_* is audio's, cap_* is everyone else's.
BAND_OWNER = {
    'Render: ': ('image', 'video'),
    'Moves: ': ('video',),
    'Builds: ': ('geometry',),
    'Sees: ': ('judge',),
    'Names: ': ('judge',),
    'Makes: ': ('audio',),
    'Hears: ': ('audio',),
    'Counting & quantity': ('text', 'image', 'video', 'judge', 'audio'),
    'Space & relation': ('text', 'image', 'video', 'judge', 'geometry'),
    'Attributes': ('image', 'video', 'judge', 'geometry'),
    'Capacity': _ALL_KINDS,
    'Prompt: ': _ALL_KINDS,
    'Licence & rights': _ALL_KINDS,
    'Cost & speed': _ALL_KINDS,
    'Reliability': _ALL_KINDS,
    'Operability': _ALL_KINDS,
}


def kinds_of(step):
    if step in STEP_KINDS:
        return list(STEP_KINDS[step])
    pk = (getattr(Q, 'PROMPT_KIND', {}) or {}).get(step)
    return [pk] if pk else []


def band_owners(col):
    """The kinds whose bank must cover this column (by its group), () for a domain column."""
    g = col.get('group') or ''
    for prefix, owners in BAND_OWNER.items():
        if g == prefix or (prefix.endswith(' ') and g.startswith(prefix)):
            if g == 'Capacity':
                return ('audio',) if col['id'].startswith('acap_') else tuple(k for k in owners if k != 'audio')
            return owners
    return ()


def steps_of_kind(kind):
    """Every step whose include list names `kind` (text: the five Story & text steps)."""
    from zyg_dashboard.capabilities_hub import STEP_IDS

    if kind == 'text':
        return ['llm_script', 'llm_prompt', 'llm_agents', 'llm_research', 'subtitles']
    return [s for s in STEP_IDS if kind in kinds_of(s)]


def validate_shared(kind, strict=False):
    """The honesty audit of one shared bank: every feed is a real column of at least one step
    of that kind, every check kind is known (base + the bank's own additions), every probe has
    fixed inputs, repeats, checks and a grade, every na reason is written. Prints per step what
    the bank leaves for the step module."""
    errors, warnings = [], []
    try:
        sh = shared_bank(kind)
    except Exception as exc:
        return {'kind': kind, 'ok': False, 'errors': [f'{type(exc).__name__}: {exc}'], 'warnings': []}
    steps = steps_of_kind(kind)
    all_cols = {}
    for st in steps:
        for c in columns_of(st):
            all_cols.setdefault(c['id'], set()).add(st)
    check_kinds = dict(CT.CHECK_KINDS)
    check_kinds.update(sh.get('CHECK_KINDS') or {})
    owned = {}
    seen = set()
    for p in sh.get('probes') or []:
        pid = p.get('id') or '?'
        if pid in seen:
            errors.append(f'duplicate probe id {pid!r}')
        seen.add(pid)
        if not p.get('feeds'):
            errors.append(f'probe {pid!r} feeds nothing')
        for c in p.get('feeds') or []:
            if c not in all_cols:
                errors.append(f'probe {pid!r} feeds {c!r}, which no {kind} step asks')
            owned.setdefault(c, []).append(('probe', pid))
        if p.get('grade') not in CT.DISPOSITION_GRADES['probe']:
            errors.append(f'probe {pid!r}: grade {p.get("grade")!r} is not one a probe may write')
        ins = p.get('inputs') or {}
        if not any(ins.get(k) for k in ('prompt', 'task', 'fixture', 'audio', 'image', 'video', 'mesh', 'command')):
            errors.append(f'probe {pid!r}: no fixed input (prompt/task/fixture/audio/image/video/mesh/command)')
        if not (p.get('conditions') or {}).get('repeats'):
            errors.append(f'probe {pid!r}: no repeat count')
        if not p.get('checks'):
            errors.append(f'probe {pid!r}: no checks')
        for ch in p.get('checks') or []:
            if ch.get('check') not in check_kinds:
                errors.append(
                    f"probe {pid!r}: unknown check kind {ch.get('check')!r} (add it to the bank's CHECK_KINDS with a one-line rule)"
                )
            if ch.get('check') == 'operator' and not ch.get('question'):
                errors.append(f'probe {pid!r}: operator check without a written question')
        sr = p.get('state_rule') or CT.STATE_RULE
        if not (0 < sr.get('partial', 0) < sr.get('yes', 0) <= 1):
            errors.append(f'probe {pid!r}: state_rule must satisfy 0 < partial < yes <= 1')
    for k in ('derive', 'lookup', 'wiring'):
        for c, v in (sh.get(k) or {}).items():
            if not isinstance(v, dict):
                errors.append(f'{k} {c!r}: not an object')
                continue
            if k == 'lookup' and v.get('feeds_derive'):
                continue
            if c not in all_cols:
                errors.append(f'{k} {c!r}: no {kind} step asks this column')
            owned.setdefault(c, []).append((k, c))
            g = v.get('grade')
            if not (k == 'derive' and g == 'lowest of inputs') and g not in CT.DISPOSITION_GRADES[k]:
                errors.append(f'{k} {c!r}: grade {g!r} not allowed for {k}')
            if k == 'lookup' and not v.get('requires'):
                errors.append(f'lookup {c!r}: no `requires`')
    for c, reason in (sh.get('na') or {}).items():
        if c not in all_cols:
            errors.append(f'na {c!r}: no {kind} step asks this column')
        owned.setdefault(c, []).append(('na', c))
        if not isinstance(reason, str) or len(reason) < 20:
            errors.append(f'na {c!r}: reason too short')
    for c, v in owned.items():
        if len({k for k, _ in v}) > 1 or (len(v) > 1 and all(k != 'probe' for k, _ in v)):
            errors.append(
                f'column {c!r} has more than one disposition in the bank: ' + ', '.join(f'{k}:{r}' for k, r in v)
            )
    for tr, cols in (sh.get('transport_na') or {}).items():
        if tr not in CT.TRANSPORTS and tr not in (sh.get('TRANSPORTS') or {}):
            errors.append(f'transport_na names unknown transport {tr!r}')
        for c in cols or {}:
            if c not in all_cols:
                warnings.append(f'transport_na[{tr}] names {c!r}, which no {kind} step asks')
    uncovered, covered, asked, must = {}, {}, {}, {}
    for st in steps:
        cols = columns_of(st)
        miss = [c['id'] for c in cols if c['id'] not in owned]
        uncovered[st] = miss
        covered[st] = len(cols) - len(miss)
        asked[st] = len(cols)
        # strict: a band column this kind OWNS that the bank leaves uncovered is the bank's
        # failure, not the step module's (domain columns are the step's)
        must[st] = [c['id'] for c in cols if c['id'] not in owned and kind in band_owners(c)]
    if strict:
        for st, cols in must.items():
            if cols:
                errors.append(
                    f'{st}: {len(cols)} band column(s) this bank must cover are uncovered: '
                    + ', '.join(cols[:40])
                    + (' …' if len(cols) > 40 else '')
                )
    return {
        'kind': kind,
        'ok': not errors,
        'version': sh.get('version'),
        'probes': len(sh.get('probes') or []),
        'errors': errors,
        'warnings': warnings,
        'steps': steps,
        'uncovered': uncovered,
        'covered': covered,
        'asked': asked,
        'must': must,
        'check_kinds_added': sorted((sh.get('CHECK_KINDS') or {}).keys()),
    }


def row_view(step, rid):
    """Per row: {column: (kind, ref, reason)} after transport and row overrides."""
    t = load_test(step)
    d, _ = dispositions(t, step)
    r = (t.get('rows') or {}).get(rid) or {}
    tna = (t.get('transport_na') or {}).get(r.get('transport') or '', {})
    out = {}
    for c, v in d.items():
        if c in (r.get('na') or {}):
            out[c] = ('na', 'row', r['na'][c])
        elif c in tna:
            out[c] = ('na', 'transport', tna[c])
        elif v:
            k, ref = v[0]
            out[c] = (k, ref, (t.get('na') or {}).get(c, ''))
        else:
            out[c] = ('MISSING', '', '')
    return out


def summary(step):
    """What the hub attaches to a sheet: small, and never raises."""
    try:
        v = validate(step)
    except Exception as exc:  # a broken module is reported, not hidden
        return {
            'present': True,
            'ok': False,
            'errors': [f'{type(exc).__name__}: {exc}'],
            'module': f'capability_tests/{step}.py',
        }
    return v


if __name__ == '__main__':  # the CLI lives in capabilities_tests_cli
    from zyg_dashboard.capabilities_tests_cli import _main as _cli_main

    raise SystemExit(_cli_main(sys.argv[1:]))
