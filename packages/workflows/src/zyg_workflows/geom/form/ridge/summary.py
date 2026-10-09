# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""probe_pools() and the summaries read off it, incl. the AFS p.63 fat-invariant census.

Moved verbatim out of the old single-file ridge.py (lines 2645-3092).
"""

import numpy as np

from zyg_workflows.geom.form import curvature as CV
from zyg_workflows.geom.form.ridge.constants import (
    AFS_P63_REGIONS,
    AFS_P63_SOURCE,
    AFS_P63_UNPROBED_ON_BODY,
    CANON_TARGETS,
    FAT_INVARIANT_PROBES,
    RIDGE_NULL_P99,
)
from zyg_workflows.geom.form.ridge.primitive import build_graph
from zyg_workflows.geom.form.ridge.facet_search import facet_flatness, ridge_search
from zyg_workflows.geom.form.ridge.null import facet_percentile, station_cut
from zyg_workflows.geom.form.ridge.probes import HEAD_PROBES, _resolution_contract, _shared_peak_vertices, pool_overlaps


def probe_pools(
    v,
    faces,
    pools,
    stature_m=None,
    areas=None,
    normals=None,
    curv=None,
    modes=('ridge', 'point'),
    null=None,
    scope=None,
):
    """Run both primitives over a list of pools and return one record per pool.

    EACH MODE IS SCORED AT ITS OWN MEASURED CUT. Passing `null` (a ridge_null() result) gives
    each mode the per-station p99 and the run threshold measured for that mode; without it
    both modes fall back to the published isotropic cut and the shipped run constant, which
    is correct for 'point' and optimistic for 'ridge'. The cut in force is recorded in every
    record, because a before/after table where the two columns were scored differently is
    only honest if it says so.

    'facet' pools additionally get facet_flatness on the pool itself, because for a
    dotted-line landmark that is the assertion that matters and the ridge profile is only
    context.

    EVERY RECORD CARRIES ITS OWN RESOLUTION VERDICT — `resolves_relief` (bool) and
    `resolution_class` in {'resolved', 'below_null', 'unmeasurable', 'empty_window'} — and
    the set carries `_summary`, `_independence` and, for the body set, `_fat_invariant`.
    The classification is done HERE, once, against RESOLVED_VERDICTS. A consumer that
    re-derives it from verdict strings is re-making a calibration decision it cannot see;
    that is how `point_only`, which the null says occurs on a third of landmark-free skin
    pools, came to be counted as a resolution and turned 0 resolved body landmarks into
    "8 of 20".

    `scope` is 'body' or 'head' and is inferred from the probe names when not given. The
    two are summarised SEPARATELY and never pooled: the head runs at a cut calibrated on
    torso and limb skin, and merging the counts would let a real zygomatic arch flatter an
    empty clavicle.
    """
    v = np.asarray(v, np.float64)
    # Materialised: the pool list is walked twice — once to probe, once to measure window
    # disjointness — and a generator would silently make the second pass see nothing, which
    # would render as "no overlaps" rather than as an error.
    pools = list(pools)
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    ar = CV.mixed_voronoi_area(v, faces) if areas is None else np.asarray(areas)
    nv = CV.vertex_normals(v, faces) if normals is None else np.asarray(normals)
    G = build_graph(v, faces)
    cuts = {}
    for mode in modes:
        c = station_cut(null, mode)
        d = RIDGE_NULL_P99.get(mode, RIDGE_NULL_P99)
        nm = (null or {}).get('by_mode', {}).get(mode, {})
        # A LIVE NULL MAY RAISE min_run AND MAY NEVER LOWER IT — the same one-way contract
        # station_cut() has always held for the per-station cut, which this line did not
        # hold for the run length. It read the live draw's implied_min_run and used it
        # OUTRIGHT, so a census run with a lucky seed scored every probe at a SHORTER
        # required run than the shipped constant; one draw of a 120-pool p99 could hand
        # back min_run 2 where the panel says 4, and the resolved counts moved with it.
        # Measured on this cage, the single-draw estimator returns 3, 4 or 5 depending only
        # on the seed, so without a floor the census threshold is a coin toss. Prefer the
        # live discrete estimator over the interpolated one where both are present.
        _live = nm.get('discrete_min_run')
        if _live is None:
            _live = nm.get('implied_min_run')
        c['min_run'] = max(int(d['min_run']), int(_live or 0))
        _livea = nm.get('discrete_min_run_any_sign')
        if _livea is None:
            _livea = nm.get('implied_min_run_any_sign')
        c['min_run_any_sign'] = max(int(d.get('min_run_any_sign') or d['min_run']), int(_livea or 0), c['min_run'])
        # The two chance rates that govern how the verdicts may be read. Carried in every
        # record so the number a reader needs to judge a verdict travels with the verdict.
        c['null_rate_resolved'] = (
            nm.get('frac_pools_resolved') if nm.get('frac_pools_resolved') is not None else d.get('null_rate_resolved')
        )
        c['null_rate_point_only_or_better'] = (
            nm.get('frac_pools_point_only_or_better')
            if nm.get('frac_pools_point_only_or_better') is not None
            else d.get('null_rate_point_only_or_better')
        )
        sp = (nm.get('best_run_span_frac_stature') or {}).get('p99')
        c['null_run_span_p99'] = float(sp) if sp else None
        cuts[mode] = c
    cuts['_resolution_contract'] = _resolution_contract(cuts, modes)
    out = {'_cuts': cuts}
    pcache = {}
    for name, kind, pol, pool, prov, ev in pools:
        rec = {
            'name': name,
            'kind': kind,
            'polarity': pol,
            'n_pool': int(len(pool)),
            'provenance': prov,
            'canon': CANON_TARGETS.get(name),
            'cuts': cuts,
            # ALWAYS present, on every record, whatever the status. A consumer that
            # reads this field cannot accidentally count a below-null verdict, an empty
            # window or an unmeasurable one as a resolution.
            'resolves_relief': False,
            'resolution_class': 'empty_window',
        }
        if not len(pool):
            rec.update(
                status='EMPTY_WINDOW',
                why='the window holds no vertex on this cage',
                empty_evidence=ev,
                resolution_why='NEVER PROBED: the window holds no vertex on this '
                'cage, so no primitive ran on it. This is not a flat '
                'reading and must not be counted as one.',
            )
            out[name] = rec
            continue
        for mode in modes:
            c = cuts[mode]
            rec[mode] = ridge_search(
                v,
                faces,
                pool,
                polarity=pol,
                stature_m=S,
                areas=ar,
                normals=nv,
                graph=G,
                mode=mode,
                min_run=c['min_run'],
                min_run_any=c['min_run_any_sign'],
                point_cache=pcache,
                min_frac_stature=c['min_frac_stature'],
                min_contrast=c['min_contrast'],
            )
        if kind == 'facet':
            c = cuts.get('point', cuts[modes[0]])
            try:
                rec['facet'] = facet_flatness(
                    v,
                    faces,
                    pool,
                    stature_m=S,
                    areas=ar,
                    normals=nv,
                    curv=curv,
                    min_frac_stature=c['min_frac_stature'],
                    min_contrast=c['min_contrast'],
                )
            except ValueError as e:
                rec['facet'] = {'verdict': 'unmeasurable', 'why': str(e)}
            if null and rec['facet'].get('curvedness_ratio') is not None:
                rec['facet']['null_percentile'] = facet_percentile(null, rec['facet']['curvedness_ratio'])
        rec['status'] = 'ok'
        rec.update(_classify_probe(rec, modes))
        out[name] = rec

    out['_scope'] = scope or _infer_scope(out)
    out['_independence'] = pool_overlaps(pools)
    out['_independence']['shared_peak_vertices'] = _shared_peak_vertices(out, modes)
    out['_summary'] = relief_summary(out, scope=out['_scope'])
    if out['_scope'] == 'body':
        out['_fat_invariant'] = fat_invariant_report(out, pools=pools)
    return out


def _infer_scope(recs):
    """'body' or 'head', decided by the probe names actually present, never by the caller.

    Kept out of the caller's hands because the head and body counts must not be pooled and
    a mislabelled set is exactly how they would be.
    """
    head = {p[0] for p in HEAD_PROBES}
    names = {k for k in recs if not k.startswith('_')}
    if not names:
        return 'unknown'
    if names <= head:
        return 'head'
    if not (names & head):
        return 'body'
    return 'mixed'


def _classify_probe(rec, modes=('ridge', 'point')):
    """The resolution verdict for one probe, from the per-mode searches already in `rec`.

    Resolved if EITHER primitive resolves — the criterion the report has always described —
    but 'resolves' now means RESOLVED_VERDICTS, i.e. a run outside the mode's own measured
    null, and never `point_only`. The union multiplicity of trying two modes is priced into
    `_cuts['_resolution_contract']`.
    """
    per, resolved_by, ran = {}, [], []
    for m in modes:
        s = rec.get(m) or {}
        if s.get('status') != 'ok':
            per[m] = {'status': s.get('status'), 'why': s.get('why'), 'resolves_relief': False}
            continue
        r = s['result']
        ran.append(m)
        per[m] = {
            'status': 'ok',
            'verdict': r['verdict'],
            'verdict_class': r['verdict_class'],
            'resolves_relief': bool(r['resolves_relief']),
            'longest_run': r['longest_run'],
            'longest_run_any_sign': r['longest_run_any_sign'],
            'min_run': r['thresholds']['min_run'],
            'min_run_any_sign': r['thresholds']['min_run_any_sign'],
            'peak_relief_mm': r['peak_relief_mm'],
            'peak_contrast': r['peak_contrast'],
            'peak_vertex': r['peak_vertex'],
            'null_rate': r['null_rate'],
            'meaning': r['verdict_meaning'],
        }
        if r['resolves_relief']:
            resolved_by.append(m)
    if resolved_by:
        m = resolved_by[0]
        return {
            'resolves_relief': True,
            'resolution_class': 'resolved',
            'resolved_by': resolved_by,
            'resolution_mode': m,
            'resolution_verdict': per[m]['verdict'],
            'peak_relief_mm': per[m]['peak_relief_mm'],
            'by_mode': per,
            'resolution_why': 'resolved by %s: %s' % (m, per[m]['meaning']),
        }
    if not ran:
        return {
            'resolves_relief': False,
            'resolution_class': 'unmeasurable',
            'resolved_by': [],
            'resolution_mode': None,
            'resolution_verdict': 'unmeasurable',
            'peak_relief_mm': None,
            'by_mode': per,
            'resolution_why': 'NOT PROBED: no primitive could run on this pool (%s). '
            'Not a statement about relief in either direction.'
            % '; '.join('%s=%s' % (m, per[m].get('status')) for m in modes),
        }
    # below the null under every mode that ran. point_only outranks flat only as a
    # DESCRIPTION — neither resolves anything.
    order = [m for m in ran if per[m]['verdict'] == 'point_only'] or ran
    m = order[0]
    return {
        'resolves_relief': False,
        'resolution_class': 'below_null',
        'resolved_by': [],
        'resolution_mode': m,
        'resolution_verdict': per[m]['verdict'],
        'peak_relief_mm': per[m]['peak_relief_mm'],
        'by_mode': per,
        'resolution_why': 'INSIDE THE MEASURED NULL under every primitive that ran — %s: %s' % (m, per[m]['meaning']),
    }


def relief_summary(recs, scope=None):
    """The counts, split by resolution class, with a sentence that cannot hide any of them.

    FOUR BUCKETS, and the last two are the ones a prose summary keeps losing:
      resolved      outside the measured null under at least one primitive
      below_null    probed, and the reading is inside the null ('point_only' or 'flat')
      unmeasurable  probed, but no primitive could run (the window is a cluster, not a
                    curve, or too few stations were measurable)
      never_probed  EMPTY_WINDOW — the window holds no vertex on this cage, so nothing ran

    `never_probed` is NOT a flat reading and the sentence says so explicitly, by name, every
    time — including when the list is empty, so that a reader can tell "no empty windows"
    from "empty windows not mentioned". The shipped head prose reported "4 of 12 resolve;
    unresolved: <5 names>" and left the 3 windows that hold no geometry unnamed anywhere.
    """
    scope = scope or _infer_scope(recs)
    buckets = {'resolved': [], 'below_null': [], 'unmeasurable': [], 'empty_window': []}
    detail = {}
    for name in sorted(recs):
        if name.startswith('_'):
            continue
        r = recs[name]
        cls = r.get('resolution_class', 'empty_window')
        buckets.setdefault(cls, []).append(name)
        detail[name] = {
            'class': cls,
            'resolves_relief': bool(r.get('resolves_relief')),
            'verdict': r.get('resolution_verdict'),
            'mode': r.get('resolution_mode'),
            'peak_relief_mm': r.get('peak_relief_mm'),
            'why': r.get('resolution_why'),
        }
    n = sum(len(x) for x in buckets.values())
    contract = (recs.get('_cuts') or {}).get('_resolution_contract') or {}
    rate_res = contract.get('null_rate_resolved_either_mode')
    rate_pt = contract.get('null_rate_point_only_or_better_either_mode')
    point_only = sorted(k for k in buckets['below_null'] if detail[k]['verdict'] == 'point_only')
    flat = sorted(k for k in buckets['below_null'] if detail[k]['verdict'] == 'flat')
    sentence = (
        '%s: %d of %d probes resolve relief outside the measured null%s. '
        'Below the null: %d (%d point_only, %d flat)%s — point_only is INSIDE the null and '
        'resolves nothing. Probed but unmeasurable: %d%s. NEVER PROBED (window holds no '
        'vertex on this cage, which is not a flat reading): %d%s.'
        % (
            scope.upper(),
            len(buckets['resolved']),
            n,
            '' if rate_res is None else ' (chance rate %.2f%%)' % (100.0 * rate_res),
            len(buckets['below_null']),
            len(point_only),
            len(flat),
            ''
            if rate_pt is None
            else '; a point_only-or-better reading occurs by chance on %.1f%% of '
            'landmark-free skin pools under this same search' % (100.0 * rate_pt),
            len(buckets['unmeasurable']),
            (' [%s]' % ', '.join(buckets['unmeasurable'])) if buckets['unmeasurable'] else ' [none]',
            len(buckets['empty_window']),
            (' [%s]' % ', '.join(buckets['empty_window'])) if buckets['empty_window'] else ' [none]',
        )
    )
    if scope == 'head':
        # Stated on the sentence itself, not in a footnote, because the sentence is what
        # gets quoted. The head is a different regime and its counts may not be added to
        # the body's in either direction.
        sentence += (
            ' HEAD SCOPE: the cut and the chance rates in force were measured on '
            'TORSO AND LIMB skin — there is no featureless head skin on this cage '
            'to build a head null from — so these are REPORT ONLY and may not be '
            'summed with the body counts.'
        )
    return {
        'scope': scope,
        'n_probes': n,
        'n_resolved': len(buckets['resolved']),
        'resolved': sorted(buckets['resolved']),
        'n_below_null': len(buckets['below_null']),
        'below_null': sorted(buckets['below_null']),
        'point_only': point_only,
        'flat': flat,
        'n_unmeasurable': len(buckets['unmeasurable']),
        'unmeasurable': sorted(buckets['unmeasurable']),
        'n_never_probed': len(buckets['empty_window']),
        'never_probed': sorted(buckets['empty_window']),
        'per_probe': detail,
        'resolution_contract': contract,
        'sentence': sentence,
    }


def fat_invariant_report(body_recs, pools=None):
    """AFS p.63's roster against this cage, with the page's own denominator kept whole.

    Refuses a head probe set: p.63's body regions are scored at the body cut, and the head
    windows that touch the page's facial-mask and nape rows are report-only (their contrast
    floor was measured on torso and limb skin). Counting them towards a body result in
    either direction would be the head flattering the body.
    """
    scope = _infer_scope(body_recs)
    if scope not in ('body', 'unknown'):
        raise ValueError(
            'fat_invariant_report is a BODY census; it was handed the %r probe '
            'set. The head windows are report-only and may not be counted '
            'towards it.' % scope
        )
    rows, missing, resolved, absent = [], [], [], []
    for region, body, head, note in AFS_P63_REGIONS:
        pr = []
        for p in body:
            r = body_recs.get(p) or {}
            # A roster probe that is not in the probe set at all is NOT a probe that found
            # nothing. It is a broken census, and it is named as one rather than being
            # allowed to swell the "resolves nothing" list and read as a cage defect.
            cls = r.get('resolution_class', 'absent') if r else 'absent'
            if not r:
                absent.append(p)
            pr.append(
                {
                    'probe': p,
                    'class': cls,
                    'resolves_relief': bool(r.get('resolves_relief')),
                    'verdict': r.get('resolution_verdict'),
                    'peak_relief_mm': r.get('peak_relief_mm'),
                }
            )
            (resolved if r.get('resolves_relief') else missing).append(p)
        rows.append(
            {
                'page_region': region,
                'body_probes': list(body),
                'head_probes_report_only': list(head),
                'note': note,
                'probed_on_body': bool(body),
                'probes': pr,
                'n_resolved': sum(1 for x in pr if x['resolves_relief']),
            }
        )
    ind = None
    if pools is not None:
        ind = pool_overlaps(pools, subset=set(FAT_INVARIANT_PROBES))
    n_unprobed = len(AFS_P63_UNPROBED_ON_BODY)
    sentence = (
        '%d of the %d body probes covering AFS p.63 resolve relief outside the measured '
        "null; %d resolve nothing: %s. Those %d probes cover %d of the page's %d named "
        'fat-invariant regions%s — %d region(s) have NO body probe at all and are reported '
        'unprobed, not passed: %s.'
        % (
            len(resolved),
            len(FAT_INVARIANT_PROBES),
            len(missing),
            ', '.join(sorted(missing)) or 'none',
            len(FAT_INVARIANT_PROBES),
            len(AFS_P63_REGIONS) - n_unprobed,
            len(AFS_P63_REGIONS),
            ''
            if ind is None
            else (
                ', over %d separated regions of skin, at most %d of them pairwise '
                'disjoint, so the denominator is %d windows and not %d independent '
                'observations'
                % (
                    ind['n_disjoint_clusters'],
                    ind['max_disjoint_windows'],
                    len(FAT_INVARIANT_PROBES),
                    len(FAT_INVARIANT_PROBES),
                )
            ),
            n_unprobed,
            ', '.join(AFS_P63_UNPROBED_ON_BODY),
        )
    )
    if absent:
        sentence += (
            ' CENSUS INCOMPLETE: %d roster probe(s) are not present in this probe '
            'set at all and were counted as resolving nothing — that is a broken '
            'census, not a cage finding: %s.' % (len(absent), ', '.join(sorted(absent)))
        )
    return {
        'source': AFS_P63_SOURCE,
        'n_page_regions': len(AFS_P63_REGIONS),
        'n_page_regions_with_a_body_probe': len(AFS_P63_REGIONS) - n_unprobed,
        'unprobed_page_regions': list(AFS_P63_UNPROBED_ON_BODY),
        'regions': rows,
        'probes': list(FAT_INVARIANT_PROBES),
        'n_probes': len(FAT_INVARIANT_PROBES),
        'n_probes_resolved': len(resolved),
        'resolved': sorted(resolved),
        'n_probes_missing': len(missing),
        'missing': sorted(missing),
        'n_probes_absent_from_set': len(absent),
        'absent_from_set': sorted(absent),
        'independence': ind,
        'sentence': sentence,
    }
