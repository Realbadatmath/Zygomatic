#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_spec_research.py — fill the object-spec store OFFLINE (2026-09-08).

The drawing assistant never researches.  Its CLI is spawned with
`--tools '' --allowedTools mcp__arch`: it has no web access, and a job that
already cannot finish in 28 turns is the worst place to add unbounded latency.
What a build DOES do is record what it could not answer — every kind it drew
with no spec, and every spec() call that missed — into
data/runtime/arch_assistant/spec_gaps.jsonl.

This is the other end: a CLI for an agent that DOES have web access (a session
tree task, or `claude -p` with WebSearch), run between builds.

    arch_spec_research.py --gaps                 what the store still owes
    arch_spec_research.py --coverage             kinds and tools with no sheet
    arch_spec_research.py --brief elevator       the research brief for one key
    arch_spec_research.py --brief-all 8          briefs for the 8 loudest gaps
    arch_spec_research.py --write draft.json     validate and install one sheet
    arch_spec_research.py --validate             check the whole store
    arch_spec_research.py --list                 what is installed, and how

A sheet installed here with source="researched" is never overwritten by the
seeder, so research always beats convention.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))


def _mod():
    spec = importlib.util.spec_from_file_location(
        'object_specs', os.path.join(HERE, 'arch_assistant_ext', 'object_specs.py')
    )
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, HERE)
    spec.loader.exec_module(m)
    return m


BRIEF = """RESEARCH BRIEF — object spec "{key}"

You are filling ONE sheet in the Architecture Studio object knowledge base. It
is read by a drawing assistant that has no web access, at most 28 tool calls per
building, and a design check that enforces the machine half of what you write.

Answer these six questions, and nothing else:

  what    — what is it, in one or two sentences
  looks   — what does it look like: proportions and the visible giveaways
  how     — how it is built with THESE tools, naming the tool and its arguments
  avoid   — what to avoid while building it (a list of short, concrete faults)
  quality — what makes a high-quality one (a list)
  space   — how much room it needs IN RELATION TO ITS SURROUNDINGS

`space` is the half that gets enforced, so it is numbers, not prose:

  {{"w": [min, max], "d": [min, max], "h": [min, max],   metres, any may be omitted
    "clear_r": 1.0,          a clear ring round the object nothing solid may enter
    "clear_front": 1.8,      extra clear depth in front (needs "facing")
    "facing": "+z",          the record's LOCAL front: +z, -z, +x or -x
    "headroom": 2.1,         clear height over it
    "host": "floor",         floor | deck | ground | wall | ceiling | roof | water | any
    "per": {{"unit": "occupants", "n": 200}},   a count rule, if there is one
    "severity": "error",     error = done refuses; warn = reported; info = quiet
    "note": "the one sentence a builder needs"}}

Rules:
 · Give REAL numbers with a REAL source. Cite where each dimension comes from
   (a standard, a code, a manufacturer, a design guide) in "sources": [...].
   If you cannot find a source for a number, say the number is conventional in
   the note and keep source "seeded" — never invent a citation.
 · severity "error" only where a wrong value makes the building unbuildable
   (escape widths, lift landings, parking aisles). Everything else is "warn".
 · Write for a model that will act on it, not for a reader: short, imperative,
   no hedging, no marketing.
 · The studio's own vocabulary for "how": tools are named in
   arch_ext/CAPABILITIES.md and by help(); heights are STOREYS of 2.7 m;
   positions are grid cells like FG150.

Existing tools that may build it: {tools}
Existing record kinds that may be it: {kinds}
Times a build has asked for it: {n}{was}

Write the JSON to a file and install it with:
    arch_spec_research.py --write <file>.json

The file must be exactly this shape:
{{"key": "{key}", "title": "...", "aliases": [...], "kinds": [...], "tools": [...],
 "what": "...", "looks": "...", "how": "...",
 "avoid": ["..."], "quality": ["..."],
 "space": {{...}},
 "source": "researched", "sources": ["https://..."], "written": "YYYY-MM-DD"}}
"""


def cmd_gaps(M, args):
    gs = M.gaps()
    if not gs:
        _zyg_log.info('no open gaps — every kind a build has met has a sheet')
        return 0
    _zyg_log.info(f'{len(gs)} open gap(s), loudest first:\n')
    for g in gs[: args.limit]:
        _zyg_log.info(f'  {g["n"]:4d}x  {g["key"]:28s} last {g["last"]}  ({g["why"]})')
    _zyg_log.info(f'\nBriefs:  {os.path.basename(__file__)} --brief-all {min(len(gs), 8)}')
    return 0


def _candidates(M, key):
    """Tools and kinds whose names look like the missing key — the researcher
    should not have to guess which tool builds the thing."""
    from zyg_workflows import arch_assistant as A

    k = key.replace('_', ' ')
    tools = [t['name'] for t in A.TOOL_DEFS if key in t['name'] or any(w in t['name'] for w in k.split() if len(w) > 3)]
    kinds = [
        x
        for x in sorted(set(list(A.KINDS) + list(A.EXT_KINDS)))
        if key in x or any(w in x for w in k.split() if len(w) > 3)
    ]
    return tools[:10], kinds[:10]


def cmd_brief(M, args, key=None, n=0, why=''):
    key = M._norm(key or args.brief)
    have = M.spec_for(key)
    tools, kinds = _candidates(M, key)
    was = ''
    if have:
        was = (
            f'\n\nA sheet already exists for this ({have["key"]}, source={have.get("source")}). '
            f'Only replace it if you can improve it WITH sources.'
        )
    _zyg_log.info(
        BRIEF.format(
            key=key,
            tools=', '.join(tools) or '(none found — search help())',
            kinds=', '.join(kinds) or '(none)',
            n=n or 0,
            was=was,
        )
    )
    return 0


def cmd_brief_all(M, args):
    gs = M.gaps()[: max(1, args.brief_all)]
    if not gs:
        _zyg_log.info('no open gaps')
        return 0
    for i, g in enumerate(gs):
        if i:
            _zyg_log.info('\n' + '=' * 78 + '\n')
        cmd_brief(M, args, key=g['key'], n=g['n'], why=g['why'])
    return 0


def cmd_write(M, args):
    with open(args.write, encoding='utf-8') as fh:
        s = json.load(fh)
    errs = M.validate_spec(s)
    if errs:
        _zyg_log.info('REFUSED — the sheet is not installable:')
        for e in errs:
            _zyg_log.info(' '.join(str(a) for a in ('  ·', e)))
        return 1
    key = M._norm(s['key'])
    s['key'] = key
    path = os.path.join(M.SPEC_DIR, key + '.json')
    old = None
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as fh:
                old = json.load(fh)
        except Exception:  # noqa: BLE001
            old = None
    if old and old.get('source') == 'researched' and s.get('source') != 'researched':
        _zyg_log.info(f'REFUSED — {key} is already researched; a seeded sheet may not replace it')
        return 1
    os.makedirs(M.SPEC_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(s, fh, ensure_ascii=False, indent=1, sort_keys=True)
    M.load_specs(force=True)
    txt = M.prose(s)
    _zyg_log.info(f'installed {key} ({s.get("source")}, {len(s.get("sources") or [])} source(s)) -> {path}')
    _zyg_log.info(f'the assistant will read {len(txt)} chars:\n')
    _zyg_log.info(txt)
    return 0


def cmd_validate(M, args):
    bad = 0
    for fn in sorted(os.listdir(M.SPEC_DIR)) if os.path.isdir(M.SPEC_DIR) else []:
        if not fn.endswith('.json'):
            continue
        p = os.path.join(M.SPEC_DIR, fn)
        try:
            with open(p, encoding='utf-8') as fh:
                s = json.load(fh)
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'  BAD  {fn}: unreadable ({e!r})')
            bad += 1
            continue
        errs = M.validate_spec(s)
        if errs:
            bad += 1
            _zyg_log.info(f'  BAD  {fn}: {"; ".join(errs)}')
        else:
            n = len(M.prose(s))
            flag = '  (over budget!)' if n > M.PROSE_MAX else ''
            _zyg_log.info(f'  ok   {fn:26s} {s.get("source"):11s} {n:5d} chars{flag}')
    _zyg_log.info(f'\n{bad} unusable' if bad else '\nall sheets valid')
    return 1 if bad else 0


def cmd_coverage(M, args):
    from zyg_workflows import arch_assistant as A

    M.load_specs(force=True)
    kinds = sorted(set(list(A.KINDS) + list(A.EXT_KINDS)))
    # measured with the EXACT lookup the checks use, not the fuzzy one the model
    # gets — a fuzzy hit would report coverage the design check cannot rely on
    miss = [k for k in kinds if not M.spec_for_kind(k) and k not in M.SOLID_SKIP and k not in M.GENERIC_KINDS]
    have = len(kinds) - len(miss)
    _zyg_log.info(f'{have} of {len(kinds)} record kinds resolve to a sheet ({100 * have / max(1, len(kinds)):.0f}%).')
    _zyg_log.info(f'{len(M.load_specs())} sheets installed.\n')
    _zyg_log.info('kinds with no sheet:')
    for i in range(0, len(miss), 6):
        _zyg_log.info('  ' + '  '.join(f'{k:22s}' for k in miss[i : i + 6]))
    return 0


def cmd_list(M, args):
    specs = M.load_specs(force=True)
    for k in sorted(specs):
        s = specs[k]
        sp = s.get('space') or {}
        _zyg_log.info(
            f'  {k:22s} {s.get("source"):11s} sev={str(sp.get("severity") or "-"):6s} '
            f'clear_r={str(sp.get("clear_r") or "-"):5s} host={str(sp.get("host") or "-"):7s} '
            f'{s.get("title")}'
        )
    _zyg_log.info(f'\n{len(specs)} sheets in {M.SPEC_DIR}')
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--gaps', action='store_true')
    ap.add_argument('--coverage', action='store_true')
    ap.add_argument('--brief', metavar='KEY')
    ap.add_argument('--brief-all', type=int, metavar='N')
    ap.add_argument('--write', metavar='FILE.json')
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--limit', type=int, default=40)
    args = ap.parse_args(argv)
    M = _mod()
    if args.gaps:
        return cmd_gaps(M, args)
    if args.coverage:
        return cmd_coverage(M, args)
    if args.brief:
        return cmd_brief(M, args)
    if args.brief_all:
        return cmd_brief_all(M, args)
    if args.write:
        return cmd_write(M, args)
    if args.validate:
        return cmd_validate(M, args)
    if args.list:
        return cmd_list(M, args)
    ap.print_help()
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
