# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Context pack — the neutral facts a subagent would otherwise rediscover.

WHY THIS EXISTS, measured rather than assumed. Across four multi-agent waves on this
package (34 agents, 2,144 tool calls) the token bill decomposed as:

    cache reads (context re-sent on every tool call)   506.5M   96.3%
    cache writes (information actually being fetched)   17.3M    3.3%
    output (agents writing)                              1.96M    0.4%

Every tool call re-sends the agent's whole accumulated context. Agents started at ~9k
tokens and finished at 200-370k — a 28-39x growth — averaging 236k re-read per call. So
cost is roughly (number of calls) x (context size), and context grows with calls: it is
close to quadratic in how long an agent lives. The top 5 of 34 agents burned 39.3% of the
total, and they are exactly the ones that ran 130-174 calls.

The waste that follows is orientation, not thinking. Measured over 21 agents:

    ran the full gate suite independently (30-60 s each)   19 of 21
    read plan.md                                            9
    read integration.md                                     6
    read review_2 / review_0 / review_1                     6 / 5 / 5
    read gates.py, report.py, pose_limits.py                4 each
    ran the same cd + grep orientation commands            21 of 21

Nineteen agents re-ran a suite whose complete output was already on disk in
data/assets/anthro_reports/*.json. This module reads those artefacts instead of
recomputing them, adds a source symbol index so nobody has to grep for a line number, and
prints the whole thing small enough to paste into an agent prompt. Every discovery call it
removes is worth ~236k tokens of re-read context, which is why a 3%-of-input saving is
worth far more than 3%.

THE LINE THIS MODULE MUST NOT CROSS. It carries FACTS: what the code currently is, what
the gates currently measured, where a symbol lives. It carries NO CONCLUSIONS: no review
verdict, no "this is correct", no assessment. Adversarial reviewers exist precisely to
re-derive conclusions independently, and feeding them a cached judgement turns a reviewer
into an echo. Caching facts is efficiency; caching conclusions is collusion.

It imports NOTHING from the package it describes. It parses source text and reads JSON.
That keeps it usable while other agents are mid-edit in gates.py or report.py, and means a
syntax error in the package under study cannot take the pack down with it.

    python -m zyg_workflows.geom.anthro.pack              # the pack
    python -m zyg_workflows.geom.anthro.pack --json       # machine-readable
    python -m zyg_workflows.geom.anthro.pack --section gates
"""

import json
import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../geom
REPO = os.path.dirname(ROOT)  # .../crews
REPORTS = os.path.join(REPO, 'data', 'assets', 'anthro_reports')

# Modules a subagent working on this package repeatedly has to locate things in. Order is
# the order they are printed; keep the most-read first.
INDEXED = (
    'anthro/gates.py',
    'anthro/report.py',
    'anthro/measure.py',
    'anthro/landmarks.py',
    'anthro/reference.py',
    'anthro/build_reference.py',
    'anthro/integrity.py',
    'anthro/__main__.py',
    'form/regions.py',
    'form/curvature.py',
    'form/ridge.py',
    'form/blockout.py',
    'form/hands.py',
    'form/relational.py',
    'form/sections.py',
    'form/angles.py',
    'pose_limits.py',
    'mesh_skeletons.py',
    'fit_reference.py',
)

# Standing measurements that cost real GPU/CPU time to re-derive and do not change unless
# the cage does. Each carries how it was obtained so a reader can re-verify rather than
# trust. These are MEASUREMENTS, not judgements.
STANDING_FACTS = (
    (
        'cage',
        'anny: 13,718-vertex quad cage, 13,710 quads, 6 phenotype macros, '
        '256 local morphs, 163 bones. gender 0.0 = MALE.',
    ),
    (
        'cage',
        'FOUR connected components: body 13,348v, tongue 226v, two eyeballs 72v each. '
        'Naive self-intersection tests read the body-eyeball enclosure as 520 hits.',
    ),
    (
        'relief',
        'cage relief null p99 = 2.45e-3 of stature (4.13 mm at S=1.686 m), '
        'contrast floor 3.66. Anything below this is inside the measurement noise.',
    ),
    (
        'relief',
        'BODY landmarks: 0 of 20 resolve outside the null. patella +8.90 mm '
        '(contrast 3.06), epicondyle_lat +6.84 (11.5), epicondyle_med +4.53 (2.69), '
        'malleolus_lat -0.18 (FLAT). No clavicle, iliac crest, trochanter, PSIS, '
        'cervicale. A point_only verdict is INSIDE the null (chance rate 37.8%).',
    ),
    (
        'relief',
        'HEAD landmarks are a different regime: orbital_margin +20.03 mm, '
        'nasal_bone +16.93, superciliary_arch +15.39, zygomatic_arch +10.79. The '
        'last two clear the magnitude floor and fail only the contrast test, which '
        'was calibrated on a body null.',
    ),
    (
        'rig',
        'ABSENT from the 163 bones (name-searched): scapula, rib, patella, radius, '
        'ulna, hip, sternum, occiput, atlas, axis. The cervical chain has 4 rotational '
        "joints, not C3-C7's 5. `jaw` is a single midline hinge with no corner, so no "
        'gonial angle can be measured on it.',
    ),
    (
        'pose',
        'fitted pose libraries exist for abel (44 poses) and cornelis (43) only. '
        'male, female and anny-neutral have none, so any gate declaring a library '
        'subject must report unresolved on them, never pass.',
    ),
    (
        'proportion',
        'head-unit ladder measured on all four characters: total head count '
        '7.06-7.13 for a 12-year-old AND three adults (spread 0.07). '
        'crotch_height_over_stature fails at p0.4 cornelis / p1.5 female / '
        'p2.7 male; abel sits at p48.',
    ),
    (
        'determinism',
        'mesh hashes are thread-count independent (_vert_sha canonicalizes '
        'signed zeros with + 0.0). Throttling threads costs wall-clock only.',
    ),
)

SYM_RE = re.compile(r'^(?:(?P<kind>def|class)\s+(?P<name>\w+)|(?P<const>[A-Z][A-Z0-9_]{2,})\s*=(?!=))')


def _read(path):
    try:
        with open(path, 'r', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _stamp(ts):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts)) if ts else '-'


# ---------------------------------------------------------------------------- freshness
def freshness():
    """Are the on-disk gate artefacts newer than the source that produced them?

    This is the whole reason the pack is safe to hand to an agent. A stale artefact read
    as current is the same defect class as the stale registry summary this package already
    had to fix once: it looks like a measurement and is a memory. Reported, never hidden,
    and never silently refreshed — refreshing means running the suite, which is the
    expensive thing the pack exists to avoid, so the caller decides.
    """
    arts = {}
    if os.path.isdir(REPORTS):
        for fn in sorted(os.listdir(REPORTS)):
            if fn.endswith('.json'):
                arts[fn[:-5]] = _mtime(os.path.join(REPORTS, fn))
    newest_src, newest_src_file = 0.0, None
    for rel in INDEXED:
        m = _mtime(os.path.join(ROOT, rel))
        if m and m > newest_src:
            newest_src, newest_src_file = m, rel
    oldest_art = min(arts.values()) if arts else None
    stale = bool(arts and newest_src and oldest_art and newest_src > oldest_art)
    behind = [n for n, m in arts.items() if newest_src and m and m < newest_src]
    return {
        'artefacts': arts,
        'newest_source': newest_src_file,
        'newest_source_mtime': newest_src,
        'oldest_artefact_mtime': oldest_art,
        'stale': stale,
        'artefacts_behind_source': sorted(behind),
    }


# ------------------------------------------------------------------------------ gates
def gate_table():
    """Per-gate status across every character, straight out of the shipped artefacts.

    This is the table 19 of 21 agents each spent 30-60 s re-running the suite to obtain
    while it sat on disk.
    """
    chars, rows = [], {}
    meta = {}
    if not os.path.isdir(REPORTS):
        return [], {}, {}
    for fn in sorted(os.listdir(REPORTS)):
        if not fn.endswith('.json'):
            continue
        doc = None
        try:
            with open(os.path.join(REPORTS, fn)) as fh:
                doc = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            meta[fn[:-5]] = {'unreadable': str(exc)}
            continue
        name = doc.get('character') or fn[:-5]
        chars.append(name)
        counts = doc.get('counts') or {}
        meta[name] = {
            'verdict': doc.get('verdict'),
            'exit': doc.get('exit_code'),
            'sex': doc.get('sex'),
            'age': doc.get('age_years'),
            'stature_m': doc.get('stature_m'),
            'n_gates': doc.get('n_gates'),
            'counts': counts,
            'unrun_blocking': len(doc.get('unrun_blocking') or []),
            'blocking': list(doc.get('blocking') or []),
            'stable_sha256': (doc.get('stable_sha256') or '')[:12],
        }
        for g in doc.get('gates') or []:
            gid = g.get('id')
            if not gid:
                continue
            # severity_calibrated is a BOOLEAN flag ("was calibration applied"), not a
            # severity — reading it as one prints "block>True". The pair that carries
            # meaning is declared -> effective: 38 gates declare block and 26 keep it,
            # because a CANON threshold has no population and the policy strips its
            # blocking claim automatically.
            r = rows.setdefault(
                gid,
                {
                    'tier': g.get('tier'),
                    'title': g.get('title'),
                    'sev_declared': g.get('severity_declared') or g.get('severity'),
                    'sev_effective': g.get('severity'),
                    'downgraded': bool(g.get('downgraded_by_severity')),
                    'provenance': g.get('provenance_class') or g.get('provenance'),
                    'status': {},
                },
            )
            r['status'][name] = g.get('effective_status') or g.get('status')
    return chars, rows, meta


# ----------------------------------------------------------------------- symbol index
def symbol_index(max_per_file=28):
    """file -> [(line, 'def foo' | 'class Bar' | 'CONST')]. Kills the grep-for-a-line-number
    calls. Capped per file: the point is orientation, not a second copy of the source."""
    out = {}
    for rel in INDEXED:
        src = _read(os.path.join(ROOT, rel))
        if src is None:
            continue
        syms, n = [], 0
        for i, line in enumerate(src.splitlines(), 1):
            m = SYM_RE.match(line)
            if not m:
                continue
            n += 1
            if m.group('const'):
                syms.append((i, m.group('const')))
            else:
                syms.append((i, '%s %s' % (m.group('kind'), m.group('name'))))
        out[rel] = {
            'lines': len(src.splitlines()),
            'n_symbols': n,
            'symbols': syms[:max_per_file],
            'truncated': max(0, n - max_per_file),
        }
    return out


def constants():
    """Module-level ALL_CAPS assignments with a scalar/tuple literal, with file:line.

    These are the load-bearing numbers — thresholds, floors, nulls. An agent that changes
    one needs to know where every other one lives, and this package's cardinal rule is
    that a threshold may not move to make our own assets pass.
    """
    out = []
    for rel in INDEXED:
        src = _read(os.path.join(ROOT, rel))
        if src is None:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            m = re.match(r'^([A-Z][A-Z0-9_]{2,})\s*=\s*(.+?)\s*(?:#.*)?$', line)
            if not m:
                continue
            val = m.group(2)
            if len(val) > 78 or val.endswith((',', '(', '[', '{')):
                continue
            out.append((rel, i, m.group(1), val))
    return out


# ---------------------------------------------------------------------------- render
def build():
    chars, rows, meta = gate_table()
    return {
        'freshness': freshness(),
        'characters': meta,
        'char_order': chars,
        'gates': rows,
        'symbols': symbol_index(),
        'constants': constants(),
        'standing_facts': [{'topic': t, 'fact': f} for t, f in STANDING_FACTS],
    }


def _render_freshness(fr, w):
    w('== FRESHNESS ==')
    if not fr['artefacts']:
        w('  NO ARTEFACTS on disk. The gate table below is EMPTY, not passing. Run')
        w('  `python -m zyg_workflows.geom.anthro check all` before trusting anything in this section.')
        return
    w('  artefacts   %s' % _stamp(fr['oldest_artefact_mtime']))
    w('  newest src  %s  (%s)' % (_stamp(fr['newest_source_mtime']), fr['newest_source']))
    if fr['stale']:
        w('  *** STALE: source is NEWER than the artefacts. Every gate status below is a')
        w('      MEMORY of the previous code, not a measurement of the current code.')
        w('      Behind: %s' % ', '.join(fr['artefacts_behind_source']))
        w('      Re-run `python -m zyg_workflows.geom.anthro check all` or treat this section as void.')
    else:
        w('  OK — no indexed source file is newer than the oldest artefact.')


def _render_gates(chars, rows, meta, w):
    if not rows:
        return
    w('')
    w('== CHARACTERS ==')
    # The counts dict keys the passing bucket 'PASS' in caps and carries six more buckets
    # besides pass/warn/fail; printing only three of eight hides exactly the non-verdicts
    # this package spent four waves learning to surface.
    order = ('PASS', 'warn', 'fail', 'skip', 'report', 'missing', 'error', 'unknown')
    w(
        '  %-13s %-7s %-5s %-8s %-13s %s   %s'
        % ('name', 'sex', 'age', 'stature', 'verdict/exit', ' '.join('%-6s' % k[:6] for k in order), 'unrun_blk')
    )
    for c in chars:
        m = meta.get(c, {})
        cnt = m.get('counts') or {}
        w(
            '  %-13s %-7s %-5s %-8s %-13s %s   %s'
            % (
                c,
                m.get('sex') or '-',
                ('%.0f' % m['age']) if isinstance(m.get('age'), (int, float)) else '-',
                ('%.3f' % m['stature_m']) if isinstance(m.get('stature_m'), (int, float)) else '-',
                '%s/%s' % (m.get('verdict'), m.get('exit')),
                ' '.join('%-6s' % cnt.get(k, '-') for k in order),
                m.get('unrun_blocking'),
            )
        )
    w('')
    n_down = sum(1 for r in rows.values() if r['downgraded'])
    w('== GATES (%d) ==   status per character, in the column order above' % len(rows))
    w('   severity is DECLARED>EFFECTIVE; * marks the %d auto-downgraded (a printed number' % n_down)
    w('   has no population, so the policy strips its blocking claim rather than trust it)')
    w('  %-34s %-4s %-14s %-9s %s' % ('id', 'tier', 'sev decl>eff', 'prov', ' '.join('%-6s' % c[:6] for c in chars)))
    for gid in sorted(rows):
        r = rows[gid]
        sev = '%s>%s%s' % (str(r['sev_declared'])[:5], str(r['sev_effective'])[:5], '*' if r['downgraded'] else '')
        st = ' '.join('%-6s' % str(r['status'].get(c, '-'))[:6] for c in chars)
        w(
            '  %-34s %-4s %-14s %-9s %s'
            % (gid[:34], str(r['tier'] or '-')[:4], sev, str(r['provenance'] or '-')[:9], st)
        )


def render(pack, section=None):
    lines = []
    w = lines.append
    fr = pack['freshness']
    w('ZYGOMATIC ANTHRO CONTEXT PACK')
    w('Facts only — current code and current measurements. NO review conclusions, by')
    w('design: an adversarial reviewer handed a cached judgement stops being a reviewer.')
    w('Generated from artefacts + source text. Nothing here re-ran the mesh pipeline.')
    w('')
    want = lambda s: section in (None, s)
    if want('freshness'):
        _render_freshness(fr, w)
    if want('gates'):
        _render_gates(pack['char_order'], pack['gates'], pack['characters'], w)
    if want('facts'):
        w('')
        w('== STANDING MEASURED FACTS ==  (re-deriving these costs GPU/CPU minutes)')
        for f in pack['standing_facts']:
            w('  [%s] %s' % (f['topic'], f['fact']))
    if want('constants'):
        w('')
        w('== LOAD-BEARING CONSTANTS ==  (a threshold may NEVER move to make our own assets pass)')
        for rel, ln, name, val in pack['constants']:
            w('  %s:%-5d %-38s = %s' % (rel, ln, name[:38], val[:60]))
    if want('symbols'):
        w('')
        w('== SYMBOL INDEX ==  file:line for every def/class/CONST — do not grep for these')
        for rel, d in pack['symbols'].items():
            w(
                '  %s  (%d lines, %d symbols%s)'
                % (rel, d['lines'], d['n_symbols'], ', %d not shown' % d['truncated'] if d['truncated'] else '')
            )
            for ln, s in d['symbols']:
                w('      %-6d %s' % (ln, s))
    return '\n'.join(lines)


if __name__ == '__main__':  # the CLI lives in pack_cli
    from zyg_workflows.geom.anthro.pack_cli import main as _cli_main

    raise SystemExit(_cli_main())
