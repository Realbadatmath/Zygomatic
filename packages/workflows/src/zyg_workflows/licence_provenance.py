# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""licence_provenance.py — is every weight in this graph cleared for commercial publication?

2026-08-09. Built when the channel moved to monetised YouTube delivery and a
survey of the open-weights landscape found the pipeline standing on weights that
do not permit commercial use:

  * FLUX.1-dev  — BFL **Non-Commercial License v2.0**. lora_trainer_service.py:39-44
    trains on `flux1-dev` and explicitly REJECTS schnell ("schnell is distilled and
    doesn't produce good LoRAs"), so every character LoRA on disk is a derivative of
    a non-commercial base, not merely a render-time dependency.
  * FLUX.1-Fill-dev — same licence, wired at flux_fill_service.py:49 (HandFixer).
  * MiniMax H3 / Tencent Hunyuan family — community licences whose "Territory"
    EXCLUDES the European Union. The operator is in the Netherlands. These exclude
    not just running the weights but *using the Outputs*, so the usual
    "we never distribute, so copyleft cannot trigger" reasoning does not rescue
    them: the restriction never needed distribution to bite.

WHY THIS GATE AND NOT YOUR EYES
-------------------------------
Every other class in DEFECT_TAXONOMY is something an operator can eventually SEE.
This one is not. A FLUX-dev frame and an Apache-licensed frame are visually
identical; the difference is legal and invisible at every resolution. The taxonomy
comment says rows with no gate "are what your eyes are still the only instrument
for" — here the eyes are not an instrument at all, at any effort level. That is the
whole argument for gating it in software.

WHAT IT CHECKS
--------------
Per model file referenced anywhere in a ComfyUI graph (enumeration is delegated to
``lora_attest.collect_model_refs`` — one graph-walking implementation across the
debug stack, and it already handles the kijai WanVideoWrapper node classes):

  cleared             licence permits commercial use AND does not exclude our territory
  non_commercial      licence forbids commercial use            → FAIL
  territory_excluded  licence excludes ZYG_LICENCE_TERRITORY    → FAIL
  unknown             no registry entry for this weight         → UNKNOWN, never PASS

LORA LINEAGE IS THE POINT
-------------------------
A graph references ``zygchar_c3345deb5bde.safetensors``. That file's own licence is
meaningless — what matters is the base model it was FINE-TUNED FROM, because a LoRA
is a derivative work of its base. This module resolves that lineage from
``training_status_<family>.json`` (which records ``model_family``) and charges the
LoRA with its base's licence. A gate that only read the LoRA filename would report
green on the exact exposure it exists to find.

THREE VERDICTS, NOT TWO (qc_contract rule 1)
--------------------------------------------
An unregistered weight returns UNKNOWN, not PASS. A licence nobody has recorded has
not been cleared; it has merely not been looked at. Ordering is deliberate:
FAIL outranks UNKNOWN (a known violation beats an unread one), and any single
non-cleared artifact decides the whole graph — licence exposure does not average.

    from zyg_workflows import licence_provenance as lp
    res = lp.attest_licences(graph, log_fn=log)
    # {'ok': True/False/None, 'verdict': 'pass'|'fail'|'unknown', 'artifacts': [...], ...}

    lp.publish_decision(manifest)        # the zpub_gate boundary
    lp.assert_flux_allowed('contact_sheet')   # the pause switch, see below

THE PAUSE SWITCH
----------------
``ZYG_FLUX_RENDERS`` — ``paused`` (DEFAULT as of 2026-08-09, operator decision) or
``allowed``. While paused, ``assert_flux_allowed()`` raises :class:`FluxRendersPaused`
at FLUX entry points so no NEW non-commercially-licensed asset is produced while the
migration to Qwen-Image 2.0 (Apache 2.0) is in flight. This is deliberately a
separate switch from the QC ladder: the ladder judges finished work, this stops work
starting. To resume FLUX rendering (e.g. after purchasing a BFL commercial licence):

    export ZYG_FLUX_RENDERS=allowed

License posture (commercial publication): stdlib json/os/fnmatch (PSF) only. No new
dependency, no weights, no GPU. Nothing here writes a pixel into a delivered frame.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import time
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.join(_HERE, 'data', 'runtime')

REGISTRY_PATH = os.environ.get('ZYG_MODEL_LICENCES', os.path.join(_RUNTIME_DIR, 'model_licences.json'))

GATE_NAME = 'licence_provenance'

# The territory whose exclusion clauses apply to us. The operator is in the
# Netherlands; MiniMax and Tencent community licences both name the EU explicitly.
TERRITORY = os.environ.get('ZYG_LICENCE_TERRITORY', 'EU').strip().upper()

# statuses, worst first — order matters, see _worst()
NON_COMMERCIAL = 'non_commercial'
TERRITORY_EXCLUDED = 'territory_excluded'
UNKNOWN = 'unknown'
CLEARED = 'cleared'

_SEVERITY = {NON_COMMERCIAL: 3, TERRITORY_EXCLUDED: 3, UNKNOWN: 2, CLEARED: 0}
_FAILING = (NON_COMMERCIAL, TERRITORY_EXCLUDED)

# Where trained LoRAs record their base family. training_status_<family>.json
# carries {'model_family': 'flux'|'sdxl', 'char_id': ..., 'lora_path': ...}.
_LORA_OUTPUT_ROOTS = [
    p
    for p in (
        os.environ.get('ZYG_LORA_OUTPUT_ROOT', '').strip(),
        str(paths.ZYG_LORA_OUTPUTS / 'storyteller_chars'),
        str(paths.ZYG_LORA_OUTPUTS / 'creatures'),
        str(paths.ZYG_LORA_OUTPUTS),
    )
    if p
]

# a 12-hex character id as used in zygchar_<id>.safetensors / lora-outputs/<id>/
_CHAR_ID_RE = re.compile(r'([0-9a-f]{12})')


class FluxRendersPaused(RuntimeError):
    """Raised by assert_flux_allowed() while ZYG_FLUX_RENDERS=paused.

    Deliberately a plain RuntimeError subclass, NOT a BaseException like
    qc_contract.QCBlocked. QCBlocked outranks fail-safe QC handlers because a gate
    that decided to stop a render must beat the handler that tolerates broken gates.
    This is the opposite situation: a caller that catches Exception around a render
    and degrades gracefully SHOULD be able to catch this and skip the FLUX path.
    """


def _log_noop(_m):
    pass


# ── ledger bridge (never a hard dependency — mirrors lora_attest) ────────────


def _record_gate(run_id, outcome, score=None, tag=''):
    try:
        from zyg_workflows import run_ledger

        run_ledger.record_gate(
            run_id or os.environ.get('ZYG_RUN_ID') or 'adhoc', GATE_NAME, outcome, score=score, tag=tag
        )
        return True
    except Exception:
        return False


# ── the registry ─────────────────────────────────────────────────────────────

# The registry records WHERE a licence was read — a LICENSE file in a clone, a pinned
# model card — and those live outside the package, on whatever disk this installation
# put them on. So the file stores them against a named root from `paths`
# ('ZYG_MODELS_ROOT/gnm/LICENSE') and the loader expands them here. Longest name first:
# the regex alternation must not let ZYG_MODELS_DIR shadow ZYG_MODELS_ROOT.
_REGISTRY_ROOTS = {
    'ZYG_CREWS_ROOT': paths.ZYG_CREWS_ROOT,
    'ZYG_DATA_ROOT': paths.ZYG_DATA_ROOT,
    'ZYG_COMFY_MODELS_ROOT': paths.ZYG_COMFY_MODELS_ROOT,
    'ZYG_COMFY_LORA_DIR': paths.ZYG_COMFY_LORA_DIR,
    'ZYG_COMFY_ROOT': paths.ZYG_COMFY_ROOT,
    'ZYG_FLUX_ROOT': paths.ZYG_FLUX_ROOT,
    'ZYG_MODELS_ROOT': paths.ZYG_MODELS_ROOT,
    'ZYG_MODELS_DIR': paths.ZYG_MODELS_DIR,
    'ZYG_LORA_OUTPUTS': paths.ZYG_LORA_OUTPUTS,
    'ZYG_LORA_DATASETS': paths.ZYG_LORA_DATASETS,
    'ZYG_HOME': paths.ZYG_HOME,
}

_ROOT_RE = re.compile(
    r'\b(' + '|'.join(sorted(_REGISTRY_ROOTS, key=len, reverse=True)) + r')(?![A-Za-z0-9_])(/[^\s,;)\'"]*)?'
)

#: Provenance fields whose text may name a root. They are prose, not lookup keys —
#: matching is by filename glob — so expansion is for the reader, never for the gate.
_PATH_FIELDS = ('source', 'note')


def resolve_root_path(text):
    """Expand every ``<ROOT_NAME>/relative/path`` in *text* to an absolute path.

    An absolute path (or any text naming no root) comes back unchanged, so entries
    written before the 2026-10-05 re-keying still resolve.
    """
    s = str(text or '')
    if not s:
        return s
    return _ROOT_RE.sub(lambda m: str(_REGISTRY_ROOTS[m.group(1)]) + (m.group(2) or ''), s)


def _expand_roots(rule):
    """One registry record with its provenance fields resolved against `paths`."""
    if not isinstance(rule, dict):
        return rule
    if not any(isinstance(rule.get(k), str) for k in _PATH_FIELDS):
        return rule
    out = dict(rule)
    for k in _PATH_FIELDS:
        if isinstance(out.get(k), str):
            out[k] = resolve_root_path(out[k])
    return out


def load_registry(path=None):
    """{'weights': [rule...], 'families': {...}} — broken/missing file returns empty.

    Never raises: a missing registry must make every weight UNKNOWN, which is
    already a non-passing verdict. It must not make the gate crash and get
    swallowed into a green.
    """
    try:
        with open(path or REGISTRY_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {'weights': [], 'families': {}}
        rules = d.get('weights')
        fams = d.get('families')
        lineage = d.get('lora_lineage')
        return {
            'weights': [_expand_roots(r) for r in rules] if isinstance(rules, list) else [],
            'families': dict(fams) if isinstance(fams, dict) else {},
            'lora_lineage': list(lineage) if isinstance(lineage, list) else [],
        }
    except Exception:
        return {'weights': [], 'families': {}, 'lora_lineage': []}


def _record_status(rec):
    """A licence record → one of the four statuses."""
    if not isinstance(rec, dict):
        return UNKNOWN
    excluded = [str(t).strip().upper() for t in (rec.get('territory_excluded') or [])]
    if TERRITORY in excluded:
        return TERRITORY_EXCLUDED
    commercial = rec.get('commercial')
    if commercial is False:
        return NON_COMMERCIAL
    if commercial is True:
        return CLEARED
    return UNKNOWN


def _match_rule(name, rules):
    """First rule whose glob matches the ComfyUI-relative name or its basename."""
    rel = str(name or '').replace('\\', '/').strip().lstrip('/')
    base = os.path.basename(rel)
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        for pat in rule.get('match') or []:
            pat = str(pat)
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(base, pat):
                return rule
    return None


# ── LoRA lineage ─────────────────────────────────────────────────────────────


def _read_family_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        fam = str((d or {}).get('model_family') or '').strip().lower()
        return fam or None
    except Exception:
        return None


_WEIGHTS_DIR_RE = re.compile(r'lora-weights-([A-Za-z0-9_]+)')


def _status_records(dirpath):
    """[(family, lora_path)] from training_status*.json in one directory.

    The family-scoped files (training_status_<family>.json) are authoritative.
    The bare legacy training_status.json is written by whichever family trained
    LAST (lora_trainer_service.py:1480 keeps it only for back-compat) so it is
    read only when nothing scoped exists — mirroring the trainer's own lookup
    order, which tries f'training_status_{mf}.json' before the shared name.
    """
    scoped, legacy = [], []
    try:
        entries = sorted(os.listdir(dirpath))
    except OSError:
        return []
    for entry in entries:
        if not (entry.startswith('training_status') and entry.endswith('.json')):
            continue
        full = os.path.join(dirpath, entry)
        fam = _read_family_file(full)
        if not fam:
            continue
        lp = None
        try:
            with open(full, 'r', encoding='utf-8') as f:
                lp = (json.load(f) or {}).get('lora_path')
        except Exception:
            lp = None
        (legacy if entry == 'training_status.json' else scoped).append((fam, lp))
    return scoped or legacy


def _same_file(a, b):
    if not (a and b):
        return False
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except Exception:
        return False


def _match_lineage(name, rules):
    """First lora_lineage rule whose glob matches -> its family, else None.

    Rule ORDER is significant: the wan/qwen conventions must precede the broad
    flux one, or wan_char_* falls through to a FLUX charge.
    """
    rel = str(name or '').replace('\\', '/').strip().lstrip('/')
    base = os.path.basename(rel)
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get('family'):
            continue
        for pat in rule.get('match') or []:
            pat = str(pat)
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(base, pat):
                return rule['family']
    return None


def lora_base_families(name, path=None, registry=None):
    """(families, how) — every base MODEL FAMILY this LoRA could derive from.

    A character in this pipeline is commonly trained TWICE — lora-weights-flux/
    AND lora-weights-sdxl/ — because photoreal (FLUX) and animated (SDXL) twins
    are the same character. So "which family is this LoRA?" is a question about a
    WEIGHTS FILE, not about a character, and answering it per-character picks one
    arbitrarily. Resolution order, most authoritative first:

      1. the weights path sits inside lora-weights-<family>/   -> exact
      2. a status file whose lora_path IS this file            -> exact
      3. a registry lora_lineage name/folder convention        -> by convention
      4. every family recorded for the char id                 -> AMBIGUOUS

    Step 3 is load-bearing and not a nicety: char_id is NOT a lineage key. One
    character owns several LoRAs trained on DIFFERENT bases — an image LoRA on
    flux1-dev and a video LoRA on Wan2.1 (wan_chars/wan_char_<id>.safetensors,
    musubi-tuner --task i2v-14B). Resolving wan_char_<id> by char id finds the
    FLUX leg and charges a licence those weights never touched: measured as a
    false FAIL on 40 of the 41 captured graphs in this repo before step 3 existed.

    In the ambiguous case ALL candidates are returned and the caller charges the
    worst-licensed one. Staged LoRAs are copied to the ComfyUI loras folder as
    zygchar_<id>.safetensors, which strips the directory that carried the answer —
    the same provenance-loss shape as the 2026-07-31 shared-filename staging bug.
    Returning the cleaner twin on a coin-flip is precisely how this gate would
    report green on a FLUX exposure.

    Empty list means lineage could not be established -> UNKNOWN, never cleared.
    """
    if path:
        # 1. the directory the weights live in names the family outright
        m = _WEIGHTS_DIR_RE.search(os.path.abspath(path))
        if m:
            return [m.group(1).strip().lower()], 'weights-dir'
        # 2. a status file that points AT this exact file
        d = os.path.dirname(os.path.abspath(path))
        for _ in range(3):
            if not d or d == os.path.dirname(d):
                break
            recs = _status_records(d)
            for fam, lora_path in recs:
                if _same_file(lora_path, path):
                    return [fam], 'lora_path-match'
            if recs:
                fams = sorted({f for f, _ in recs})
                return fams, ('status-dir' if len(fams) == 1 else 'status-dir-ambiguous')
            d = os.path.dirname(d)

    # 3. a registry naming/folder convention that names the base outright
    lin = _match_lineage(name, (registry or load_registry()).get('lora_lineage') or [])
    if lin:
        return [str(lin).strip().lower()], 'registry-convention'

    # 4. by char id under the known output roots — cannot distinguish the twins
    m = _CHAR_ID_RE.search(os.path.basename(str(name or '')))
    if m:
        char_id = m.group(1)
        fams = set()
        for root in _LORA_OUTPUT_ROOTS:
            cand = os.path.join(root, char_id)
            if os.path.isdir(cand):
                fams.update(f for f, _ in _status_records(cand))
        if fams:
            out = sorted(fams)
            return out, ('charid' if len(out) == 1 else 'charid-ambiguous')
    return [], 'unresolved'


def lora_base_family(name, path=None):
    """Back-compat single-value form. Returns the FIRST candidate or None.

    Prefer lora_base_families(); this loses the ambiguity that decides the verdict.
    """
    fams, _how = lora_base_families(name, path)
    return fams[0] if fams else None


# ── classification ───────────────────────────────────────────────────────────


def classify_weight(name, kind=None, path=None, registry=None):
    """Classify one weight reference.

    Returns {'name','kind','status','licence','reason','base_family','commercial',
             'territory_excluded'}.
    """
    reg = registry if registry is not None else load_registry()
    rules, families = reg.get('weights') or [], reg.get('families') or {}

    out = {'name': name, 'kind': kind, 'status': UNKNOWN, 'licence': None, 'reason': '', 'base_family': None}

    # A LoRA is a derivative of its base. Charge it with the base's licence, and
    # only fall through to a direct rule when lineage cannot be established.
    if (kind or '').lower() == 'lora':
        fams, how = lora_base_families(name, path, registry=reg)
        out['base_family'] = fams[0] if len(fams) == 1 else (fams or None)
        out['lineage'] = how
        if fams:
            # Score every candidate and charge the WORST. When the twins are
            # indistinguishable, "it might be the Apache one" is not clearance.
            scored = []
            for fam in fams:
                rec = families.get(fam)
                scored.append(
                    (
                        fam,
                        _record_status(rec) if isinstance(rec, dict) else UNKNOWN,
                        (rec or {}).get('licence') if isinstance(rec, dict) else None,
                    )
                )
            worst = max(scored, key=lambda t: _SEVERITY.get(t[1], 2))
            fam, st, lic = worst
            if st == UNKNOWN and not isinstance(families.get(fam), dict):
                out.update(
                    status=UNKNOWN, licence=None, reason=f'LoRA base family {fam!r} has no entry in registry families'
                )
                return out
            amb = ' (ambiguous lineage — charged the worst of '
            out.update(
                status=st,
                licence=lic,
                reason=(
                    f'LoRA fine-tuned from {fam} base '
                    f'({lic or "unrecorded licence"})'
                    + (amb + '/'.join(f for f, _, _ in scored) + ')' if len(scored) > 1 else '')
                ),
            )
            return out
        # no lineage: fall through to a direct match, but never silently clear it
        out['reason'] = 'LoRA lineage unresolved (no training_status_*.json found)'

    rule = _match_rule(name, rules)
    if rule is None:
        if not out['reason']:
            out['reason'] = 'no registry entry'
        return out
    st = _record_status(rule)
    out.update(
        status=st,
        licence=rule.get('licence'),
        reason=rule.get('note') or f'matched registry rule {rule.get("licence")}',
    )
    return out


def _worst(statuses):
    if not statuses:
        return UNKNOWN
    return max(statuses, key=lambda s: _SEVERITY.get(s, 2))


def _verdict_from(statuses):
    """FAIL outranks UNKNOWN outranks PASS. Licence exposure does not average."""
    worst = _worst(statuses)
    if worst in _FAILING:
        return False
    if worst == UNKNOWN:
        return None
    return True


# ── the gate ─────────────────────────────────────────────────────────────────


def attest_licences(graph, log_fn=None, registry_path=None, run_id=None, tag='', record=True):
    """Classify every weight a ComfyUI graph references. Never raises.

    Returns::

        {'ok': True|False|None,
         'artifacts':  [{'name','kind','status','licence','reason','base_family'}],
         'violations': [artifact, ...],     # non_commercial / territory_excluded
         'unknowns':   [artifact, ...],
         'territory':  'EU',
         'elapsed_s':  float,
         'error':      str}                 # only when ok is None from breakage

    ``ok`` is False on any violation, None when anything is unknown (or the check
    itself broke), True only when every referenced weight is positively cleared.
    """
    log = log_fn or _log_noop
    t0 = time.time()
    out = {'ok': None, 'artifacts': [], 'violations': [], 'unknowns': [], 'territory': TERRITORY, 'elapsed_s': 0.0}
    try:
        reg = load_registry(registry_path)
        if not reg.get('weights') and not reg.get('families'):
            out['error'] = f'licence registry empty or unreadable ({registry_path or REGISTRY_PATH})'
            log(f'[licence] {out["error"]} — every weight will read UNKNOWN')

        try:
            from zyg_workflows import lora_attest

            refs = lora_attest.collect_model_refs(graph or {})
            resolve = lora_attest.resolve_model_path
        except Exception as exc:
            out['error'] = f'lora_attest unavailable: {type(exc).__name__}: {exc}'
            log(f'[licence] {out["error"]}')
            return out

        if not refs:
            out['error'] = 'no model references found in graph'
            return out

        seen = set()
        for _nid, _cls, _key, name, kind, folders in refs:
            if (name, kind) in seen:
                continue
            seen.add((name, kind))
            try:
                path = resolve(name, folders)
            except Exception:
                path = None
            art = classify_weight(name, kind=kind, path=path, registry=reg)
            out['artifacts'].append(art)
            if art['status'] in _FAILING:
                out['violations'].append(art)
            elif art['status'] == UNKNOWN:
                out['unknowns'].append(art)

        out['ok'] = _verdict_from([a['status'] for a in out['artifacts']])

        if out['ok'] is True:
            log(
                f'[licence] {tag or "graph"}: PASS — {len(out["artifacts"])} weight(s) '
                f'cleared for commercial publication in {TERRITORY}'
            )
        elif out['ok'] is False:
            log(
                f'[licence] {tag or "graph"}: FAIL — {len(out["violations"])} weight(s) '
                f'not cleared for commercial publication in {TERRITORY}'
            )
            for v in out['violations']:
                log(f'[licence]   {v["status"]}: {v["name"]} ({v["licence"] or "?"}) — {v["reason"]}')
        else:
            log(
                f'[licence] {tag or "graph"}: UNKNOWN — {len(out["unknowns"])} weight(s) '
                f'with no recorded licence; UNKNOWN is not a pass'
            )
            for u in out['unknowns'][:8]:
                log(f'[licence]   unknown: {u["name"]} — {u["reason"]}')
    except Exception as exc:
        out['ok'] = None
        out['error'] = f'{type(exc).__name__}: {exc}'
        log(f'[licence] gate broke (treated as UNKNOWN, never green): {out["error"]}')
    out['elapsed_s'] = round(time.time() - t0, 3)
    if record:
        outcome = {True: 'PASS', False: 'FAIL'}.get(out['ok'], 'UNKNOWN')
        _record_gate(run_id, outcome, score=float(len(out['violations'])), tag=tag or 'graph')
    return out


def check_name(res):
    """pipeline_debug check-name for a result, so qc_contract.mode_for() can route it.

    Longest-prefix keys in GATE_CONTRACTS are 'licence_provenance:' — emit the
    status as the suffix so a future split (non_commercial vs territory) can be
    routed by fail_kind the way region_flow was split.
    """
    if res.get('ok') is True:
        return 'licence_provenance:cleared'
    if res.get('ok') is False:
        worst = _worst([v['status'] for v in res.get('violations') or []])
        return f'licence_provenance:{worst}'
    return 'licence_provenance:unknown'


# ── the publish boundary ─────────────────────────────────────────────────────


def publish_decision(weights, log_fn=None, registry_path=None):
    """Decide whether a finished asset may be PUBLISHED, given its weight lineage.

    ``weights`` is an iterable of either plain names or (name, kind) pairs — whatever
    the delivery manifest recorded. This is the zpub_gate-side entry point: it judges
    an artifact that already exists, where attest_licences() judges a graph about to
    render.

    Returns {'allowed': bool, 'verdict': 'pass'|'fail'|'unknown', 'artifacts', 'reason'}.
    UNKNOWN does not allow publication — for a monetised channel, "nobody recorded
    this licence" is not consent.
    """
    log = log_fn or _log_noop
    reg = load_registry(registry_path)
    arts = []
    for w in weights or []:
        if isinstance(w, (tuple, list)) and len(w) >= 2:
            name, kind = w[0], w[1]
        else:
            name, kind = w, None
        arts.append(classify_weight(name, kind=kind, registry=reg))
    ok = _verdict_from([a['status'] for a in arts])
    verdict = {True: 'pass', False: 'fail'}.get(ok, 'unknown')
    bad = [a for a in arts if a['status'] in _FAILING]
    unk = [a for a in arts if a['status'] == UNKNOWN]
    if ok is True:
        reason = f'{len(arts)} weight(s) cleared for {TERRITORY}'
    elif ok is False:
        reason = '; '.join(f'{a["name"]}: {a["status"]}' for a in bad[:4])
    else:
        reason = 'unrecorded licence for ' + ', '.join(a['name'] for a in unk[:4])
    log(f'[licence] publish {verdict.upper()}: {reason}')
    return {'allowed': ok is True, 'verdict': verdict, 'artifacts': arts, 'reason': reason}


def family_decision(family, log_fn=None, registry_path=None):
    """Is a whole model FAMILY cleared for commercial publication?

    The pre-render counterpart to publish_decision(): at approval time no weights
    exist yet (a contact-sheet run TRAINS the LoRA it will use), so the only thing
    knowable is which base family the run will derive from. Refusing here costs an
    approval; refusing at the render gate costs a GPU slot.

    Returns {'allowed', 'verdict', 'family', 'licence', 'reason'}.
    """
    log = log_fn or _log_noop
    fam = str(family or '').strip().lower()
    reg = load_registry(registry_path)
    rec = (reg.get('families') or {}).get(fam)
    st = _record_status(rec) if isinstance(rec, dict) else UNKNOWN
    # The pause is a separate, stronger statement than the registry: an operator
    # may pause a family whose licence is fine (mid-migration, cost, whatever).
    paused = fam == 'flux' and flux_paused()
    allowed = (st == CLEARED) and not paused
    if paused:
        verdict, reason = (
            'fail',
            ('FLUX renders are paused (ZYG_FLUX_RENDERS); flux1-dev is under the BFL Non-Commercial License'),
        )
    elif st == CLEARED:
        verdict, reason = 'pass', f'{fam} base is {(rec or {}).get("licence")}'
    elif st in _FAILING:
        verdict, reason = 'fail', f'{fam} base is {st}: {(rec or {}).get("licence")}'
    else:
        verdict, reason = 'unknown', f'no recorded licence for base family {fam!r}'
    log(f'[licence] family {fam} -> {verdict.upper()}: {reason}')
    return {
        'allowed': bool(allowed),
        'verdict': verdict,
        'family': fam,
        'licence': (rec or {}).get('licence') if isinstance(rec, dict) else None,
        'reason': reason,
    }


# ── the pause switch ─────────────────────────────────────────────────────────


def flux_state():
    """'paused' | 'allowed'. Defaults to PAUSED (2026-08-09 operator decision).

    Anything other than an explicit allow-word is treated as paused: the safe
    reading of a typo'd env var is "do not produce more exposure".
    """
    raw = os.environ.get('ZYG_FLUX_RENDERS', '').strip().lower()
    if raw in ('allowed', 'allow', 'on', '1', 'true', 'yes'):
        return 'allowed'
    return 'paused'


def flux_paused():
    return flux_state() == 'paused'


def assert_flux_allowed(site='', log_fn=None):
    """Raise :class:`FluxRendersPaused` while FLUX rendering is paused.

    Call at every entry point that would produce a NEW FLUX-derived asset —
    render, inpaint/fill, or LoRA training on a FLUX base. ``site`` names the
    caller so the log says which stage stopped.
    """
    if not flux_paused():
        return True
    msg = (
        f'FLUX renders are PAUSED{" at " + site if site else ""} — FLUX.1-dev is '
        f'under the BFL Non-Commercial License and this channel is monetised. '
        f'Set ZYG_FLUX_RENDERS=allowed to resume (e.g. after purchasing a BFL '
        f'commercial licence).'
    )
    (log_fn or _log_noop)(f'[licence] {msg}')
    raise FluxRendersPaused(msg)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli():
    import sys

    argv = sys.argv[1:]
    cmd = argv[0] if argv else 'help'

    def log(m):
        _zyg_log.info(m)

    if cmd == 'check':
        if len(argv) < 2:
            _zyg_log.info('usage: licence_provenance.py check <graph.json>')
            return 2
        with open(argv[1], 'r', encoding='utf-8') as f:
            graph = json.load(f)
        r = attest_licences(graph, log_fn=log, tag=os.path.basename(argv[1]), record=False)
        _zyg_log.info(
            json.dumps(
                {k: r[k] for k in ('ok', 'territory', 'violations', 'unknowns', 'error') if k in r},
                indent=2,
                default=str,
            )
        )
        return 0 if r.get('ok') else 1
    if cmd == 'weight':
        if len(argv) < 2:
            _zyg_log.info('usage: licence_provenance.py weight <name> [kind]')
            return 2
        kind = argv[2] if len(argv) > 2 else None
        _zyg_log.info(json.dumps(classify_weight(argv[1], kind=kind), indent=2))
        return 0
    if cmd == 'state':
        _zyg_log.info(
            json.dumps(
                {
                    'flux_renders': flux_state(),
                    'territory': TERRITORY,
                    'registry': REGISTRY_PATH,
                    'registry_loaded': bool(load_registry().get('weights')),
                },
                indent=2,
            )
        )
        return 0
    _zyg_log.info(__doc__)
    return 0


if __name__ == '__main__':
    raise SystemExit(_cli())
