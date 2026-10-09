# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from . import aggregation_sections as _sections
from .constants import (
    CACHE_PATH,
    SCAN_TTL_S,
    _LAST,
    hashlib,
    json,
    os,
    sys,
    time,
)
from .reading import _walk_training

import logging as _zyg_logging

# The logger is re-created here by assignment rather than imported from the sibling
# module: getLogger returns the one singleton the original module held, and an assigned
# global keeps the method-call bytecode of every `_zyg_log.debug(...)` below unchanged.
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.expansion_hub')
# ── aggregation ──────────────────────────────────────────────────────────────

# `_agg` moved to aggregation_sections with the tallies that use it; re-bound here by
# assignment (not `from … import`) because `expansion_hub/__init__` re-exports it from
# this module and an assignment is not an import ruff can call unused.
_agg = _sections._agg


def _folder_rows(files, comps, dirs_seen):
    """Aggregate rows for every directory at depth ≤ 2 under each component root."""
    rows = {}
    comp_root = {c['id']: c['root'] for c in comps}
    for f in files:
        root = comp_root.get(f['comp'], '')
        rel = os.path.relpath(f['abs'], root) if root and f['abs'].startswith(root + os.sep) else f['abs']
        parts = rel.split(os.sep)
        # depth 0 = the component itself
        keys = [(f['comp'], '')]
        if len(parts) > 1:
            keys.append((f['comp'], parts[0]))
        if len(parts) > 2:
            keys.append((f['comp'], os.path.join(parts[0], parts[1])))
        if len(parts) <= 1:
            keys.append((f['comp'], '(loose files)'))
        for k in keys:
            r = rows.setdefault(
                k,
                {
                    'comp': k[0],
                    'folder': k[1],
                    'depth': 0 if not k[1] else k[1].count(os.sep) + 1,
                    'files': 0,
                    'bytes': 0,
                    'lines': 0,
                    'kinds': {},
                    'exts': {},
                    'dirs': 0,
                },
            )
            r['files'] += 1
            r['bytes'] += f['bytes']
            r['lines'] += f['lines']
            r['kinds'][f['kind']] = r['kinds'].get(f['kind'], 0) + 1
            r['exts'][f['ext']] = r['exts'].get(f['ext'], 0) + 1
    # structural directory count per row (walked dirs under that folder)
    for cid, dp in dirs_seen:
        root = comp_root.get(cid, '')
        rel = os.path.relpath(dp, root) if dp.startswith(root) else dp
        parts = [] if rel == '.' else rel.split(os.sep)
        for k in (
            [(cid, '')]
            + ([(cid, parts[0])] if parts else [])
            + ([(cid, os.path.join(parts[0], parts[1]))] if len(parts) > 1 else [])
        ):
            if k in rows:
                rows[k]['dirs'] += 1
    out = []
    for r in rows.values():
        top = sorted(r['exts'].items(), key=lambda x: -x[1])[:4]
        r['top_exts'] = ', '.join(f'{e} {n}' for e, n in top)
        del r['exts']
        out.append(r)
    out.sort(key=lambda r: (-r['lines'], r['comp'], r['folder']))
    return out


def _version(files, excluded, training_totals, services):
    h = hashlib.sha1(usedforsecurity=False)
    for f in files:
        h.update(f'{f["abs"]}|{int(f["mtime"])}|{f["bytes"]}\n'.encode('utf-8', 'surrogateescape'))
    h.update(json.dumps([e['path'] for e in excluded], sort_keys=True).encode())
    h.update(json.dumps(training_totals, sort_keys=True).encode())
    h.update(json.dumps([(s['unit'], s['state']) for s in services]).encode())
    return h.hexdigest()[:16]


def build(fresh=False):
    """Scan the tree once and return the whole Expansion payload.

    The orchestrator: one filesystem sweep, then every independent tally over
    the swept rows (see `aggregation_sections`), then the payload. `fresh` is
    accepted for the caller's signature; the sweep itself is always current.
    """
    t0 = time.time()
    scan = _sections._scan_tree(t0)
    training, training_totals = _walk_training()
    langs = _sections._language_groups(scan.files)
    excluded_rows, skipped_rows = _sections._exclusion_rows(scan.excluded, scan.skipped)
    sec = _sections.Sections(
        by_kind=_sections._kind_rows(scan.files),
        by_ext=_sections._ext_rows(scan.files),
        components=_sections._component_rows(scan.comps, scan.files, scan.dirs_seen),
        folders=_folder_rows(scan.files, scan.comps, scan.dirs_seen),
        files=_sections._file_rows(scan.files),
        structure=_sections._structure_counts(scan.files, langs),
        prompts=_sections._prompt_summary(scan.files, langs.py),
        excluded=excluded_rows,
        skipped=skipped_rows,
    )
    version = _version(scan.files, scan.excluded, training_totals, scan.services)
    return _sections._payload(scan, t0, version, sec, training, training_totals)


def section_expansion(days=30, now=None, fresh=False):
    """Metrics > Expansion: `days` is ignored on purpose — a size census is what is on disk now."""
    t = time.time()
    if not fresh and _LAST['payload'] is not None and t - _LAST['t'] < SCAN_TTL_S:
        return _LAST['payload']
    payload = build(fresh=fresh)
    _LAST.update(t=time.time(), payload=payload)
    return payload


if __name__ == '__main__':
    fresh = '--fresh' in sys.argv
    if fresh:
        try:
            os.remove(CACHE_PATH)
        except OSError as _exc:
            _zyg_log.debug('no cache to remove for --fresh: %s', _exc)
    p = build(fresh=fresh)
    if '--json' in sys.argv:
        print(json.dumps(p, indent=1, default=str))
    else:
        t = p['totals']
        print(
            f'scan {p["scan"]["total_ms"]} ms (walk {p["scan"]["walk_ms"]} ms, read {p["scan"]["files_read"]}, '
            f'cache {p["scan"]["files_from_cache"]})  version {p["data_version"]}'
        )
        print(
            f'files {t["files"]}  lines {t["lines"]}  bytes {t["bytes"] / 1e6:.1f} MB  dirs {t["dirs"]}  '
            f'components {t["components"]}  services {t["services"]} ({t["services_active"]} active)'
        )
        print(
            f'py {t["py"]}  js {t["js"]}  html {t["html"]}  css {t["css"]}  json {t["json"]}  md {t["md"]}  sh {t["sh"]}  yaml {t["yaml"]}'
        )
        print(
            f'prompts: files {t["prompt_files"]} units {t["prompt_units"]}  in-code literals {t["prompt_literals"]} '
            f'({p["prompts"]["in_code_chars"]} chars in {p["prompts"]["in_code_files"]} files)'
        )
        print(
            f'training: {t["training_datasets"]} datasets, {t["training_files"]} files, {t["training_bytes"] / 1e9:.2f} GB'
        )
        print(
            f'excluded dirs {t["excluded_dirs"]}  skipped files {t["skipped_files"]} ({t["skipped_bytes"] / 1e9:.2f} GB)'
        )
        print('-- by kind')
        for k in p['by_kind']:
            print(f'  {k["kind"]:8s} files {k["files"]:6d} lines {k["lines"]:9d} bytes {k["bytes"] / 1e6:8.1f} MB')
        print('-- components')
        for c in p['components']:
            print(
                f'  {c["label"]:40s} files {c["files"]:6d} lines {c["lines"]:9d} dirs {c["dirs"]:5d} services {len(c["services"])}'
                + ('  MISSING' if c['missing'] else '')
            )
        print('-- top extensions')
        for e in p['by_ext'][:14]:
            print(
                f'  {e["ext"]:14s} files {e["files"]:6d} lines {e["lines"]:9d} median {e["median_lines"]:6d} max {e["max_lines"]:7d} {e["largest"]}'
            )
        print('-- excluded by reason')
        for e in p['excluded']:
            print(f'  {e["count"]:4d}  {e["reason"]}')
        print('-- skipped files by reason')
        for s in p['skipped']:
            print(f'  {s["files"]:7d} {s["bytes"] / 1e9:8.2f} GB  {s["reason"]}')
