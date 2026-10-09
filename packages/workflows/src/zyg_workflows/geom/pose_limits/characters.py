# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Characters, the fitted pose library, and the whole-run report.

Moved verbatim out of the old single-file pose_limits.py (lines 3240-3868).
"""

from zyg_workflows.geom.pose_limits.base import (
    ERROR,
    FAIL,
    MS,
    PASS,
    ROOT,
    SCHEMA,
    UNRESOLVED,
    WARN,
    glob,
    json,
    np,
    os,
    rollup,
    strict_wrist,
    sys,
)
from zyg_workflows.geom.pose_limits.rig import anatomical_frame, bone_roster
from zyg_workflows.geom.pose_limits.skeleton import skeleton_from_pose_aa, skeleton_from_rig
from zyg_workflows.geom.pose_limits.rom import _res, elbow_angle, knee_angle, t5_joint_rom, wrist_angles
from zyg_workflows.geom.pose_limits.pronation import pronation_coupling_in_pose, t5_pronation_isolation
from zyg_workflows.geom.pose_limits.joint_gates import t5_elbow_owner, t5_patellar_ligament, t5_scapula_static


# ---------------------------------------------------------------------------------
# characters, the fitted pose library, and the whole-run report
# ---------------------------------------------------------------------------------
NEUTRAL = {'gender': 0.0, 'age': 0.5, 'muscle': 0.5, 'weight': 0.5, 'height': 0.5, 'proportions': 0.5}


def characters():
    """The anny-neutral CONTROL plus every issued original and derived character."""
    reg = MS._registry()
    out = [{'name': 'anny-neutral', 'phenotype': dict(NEUTRAL), 'local_changes': None, 'control': True}]
    for sec in ('originals', 'derived'):
        for k in sorted(reg.get(sec, {})):
            p = reg[sec][k]['params']
            out.append(
                {'name': k, 'phenotype': p['phenotype'], 'local_changes': p.get('local_changes'), 'control': False}
            )
    return out


# The fitted pose library on disk. char_mesh asset id -> the character it was fitted for.
POSE_LIBRARY_ROOT = os.path.join(ROOT, 'output', 'char_mesh')
POSE_LIBRARY_CHARACTERS = {'c3345deb5bde': 'abel', '0015c8a3f2e3': 'cornelis'}

# Why a file was not readable as a pose. Each one is NAMED in the integrity record, never
# swallowed: a rate whose denominator shrank without saying so is a fabricated rate.
DROP_REASONS = {
    'unreadable': 'the file could not be opened, or is not valid JSON',
    'no_pose_aa': 'the file carries no pose_aa array (or it is empty)',
    'bone_count_mismatch': 'pose_aa has a different number of rows than the rig has bones, '
    'so it cannot be applied to this rig',
    'source_image_missing': 'the cell this pose was fitted to no longer has a source image '
    '— it was quarantined (identity drift) or deleted. The fit '
    'therefore describes a render the pipeline already rejected, '
    'and because a quarantined cell cannot be re-fitted the file '
    'also goes stale the moment the fitter changes.',
}


def _cell_source_image(fit_path):
    """The image a fit was made from, read from the cell's own mesh.json.

    anny_fit.json does not record its source, so the path is recovered from the sibling
    mesh.json rather than reconstructed from a naming convention — a convention would
    silently stop matching the day the dataset layout moves, and this check failing OPEN
    would put quarantined poses back into the statistics without saying so.
    """
    mj = os.path.join(os.path.dirname(fit_path), 'mesh.json')
    try:
        with open(mj) as fh:
            return (json.load(fh) or {}).get('image')
    except Exception:  # noqa: BLE001
        return None


LIBRARY_COMPLETENESS_RULE = (
    'A fitted pose library that lost files MUST NOT present itself as complete. Every '
    'violation rate published from this module carries `rate_denominator` (the number of '
    'poses actually measured), `n_files_found` (the number the glob matched) and '
    '`library_complete`; when those disagree the library subject cannot return a clean '
    'verdict, because the poses that failed to load are exactly the ones nobody looked at.'
)


def scan_pose_library(char_asset=None, root=None):
    """Read the fitted pose library AND account for every file the glob matched.

    Returns {'records': [...], 'integrity': {...}}. `records` is what load_pose_library()
    returns. `integrity` is the accounting, and any caller that publishes a RATE over the
    library MUST carry it.

    integrity keys, ALL ALWAYS PRESENT (None never means "fine"):
      root                    POSE_LIBRARY_ROOT
      pattern                 the glob that was run
      char_asset              the asset id asked for, or '*'
      n_files_found           files the glob matched
      n_loaded                files that produced a usable pose record
      n_dropped               n_files_found - n_loaded
      complete                bool: n_files_found > 0 and n_dropped == 0
      dropped                 [{path, reason, detail}] — EVERY dropped file is NAMED
      dropped_paths           the same paths, flat, for a caller that only wants the list
      drop_reason_counts      {reason: n}
      expected_pose_aa_rows   the rig's bone count; the length a pose_aa must have
      n_fit_ok_false          poses whose OWN fit recorded fit_ok=False. These are LOADED
                              and MEASURED — a bad fit is still a pose we ship — and the
                              count is published so 'our fit failed' stays separable from
                              'our pose is out of band'.
      fit_ok_false_paths      those paths, named
      rule                    LIBRARY_COMPLETENESS_RULE, in words

    These are the poses that actually drive the VACE control channel through
    geom/anny_animate.py, so their ROM violation rate is a statement about what we ship,
    not a synthetic exercise.
    """
    root = root or POSE_LIBRARY_ROOT
    pat = os.path.join(root, char_asset or '*', 'cell_*', 'anny_fit.json')
    names, _ = bone_roster()
    files = sorted(glob.glob(pat))
    out, dropped = [], []
    for p in files:
        try:
            with open(p) as fh:
                d = json.load(fh)
        except Exception as e:  # noqa: BLE001
            dropped.append({'path': p, 'reason': 'unreadable', 'detail': '%s: %s' % (type(e).__name__, str(e)[:160])})
            continue
        aa = d.get('pose_aa')
        if not aa:
            dropped.append(
                {
                    'path': p,
                    'reason': 'no_pose_aa',
                    'detail': 'pose_aa is %r' % (type(aa).__name__ if aa is not None else None),
                }
            )
            continue
        if len(aa) != len(names):
            dropped.append(
                {
                    'path': p,
                    'reason': 'bone_count_mismatch',
                    'detail': 'pose_aa has %d rows, the rig has %d bones' % (len(aa), len(names)),
                }
            )
            continue
        # A FIT WHOSE SOURCE IMAGE IS GONE DESCRIBES A BODY THAT WAS REJECTED.
        # MEASURED 2026-08-08 on abel: 9 of his 44 library poses — cell_04, 12, 28, 31,
        # 32, 34, 40, 41, 42 — were fitted to cells whose images were moved into
        # `_drift_quarantine_20260805` on 2026-08-05 for IDENTITY DRIFT. The loader
        # carried all 44 anyway (n_files_found 44, n_loaded 44, n_dropped 0), so every
        # pose statistic in this module — the ROM violation rate, the pronation coupling,
        # the transverse-tilt diversity — was computed partly over renders the pipeline
        # had already thrown away for not being the character. A quarantined cell also
        # cannot be re-fitted, so its anny_fit.json silently goes stale the moment the
        # fitter changes, which is exactly what happened when the cervical prior landed:
        # 35 cells re-fitted, those 9 kept fits from the previous fitter.
        # Dropping is the only honest option: this module cannot un-quarantine an image
        # and must not average over one.
        src = d.get('source_image') or (d.get('mesh') or {}).get('image') or _cell_source_image(p)
        if src and not os.path.exists(src):
            dropped.append(
                {
                    'path': p,
                    'reason': 'source_image_missing',
                    'detail': 'the cell this pose was fitted to no longer has a '
                    'source image (%s) — it was quarantined or deleted, '
                    'so this fit describes a render the pipeline '
                    'rejected and cannot be re-fitted' % src,
                }
            )
            continue
        out.append(
            {
                'path': p,
                'asset': os.path.basename(os.path.dirname(os.path.dirname(p))),
                'cell': d.get('cell'),
                'pose_aa': np.asarray(aa, np.float64),
                'phenotype': d.get('phenotype') or {},
                'fit_ok': bool(d.get('fit_ok')),
                'err_over_torso': d.get('err_over_torso'),
            }
        )
    counts = {}
    for d in dropped:
        counts[d['reason']] = counts.get(d['reason'], 0) + 1
    bad_fit = [r['path'] for r in out if not r['fit_ok']]
    return {
        'records': out,
        'integrity': {
            'root': root,
            'pattern': pat,
            'char_asset': char_asset or '*',
            'n_files_found': len(files),
            'n_loaded': len(out),
            'n_dropped': len(dropped),
            'complete': bool(files and not dropped),
            'dropped': dropped,
            'dropped_paths': [d['path'] for d in dropped],
            'drop_reason_counts': counts,
            'drop_reason_meanings': {k: DROP_REASONS[k] for k in sorted(counts)},
            'expected_pose_aa_rows': len(names),
            'n_fit_ok_false': len(bad_fit),
            'fit_ok_false_paths': bad_fit,
            'rule': LIBRARY_COMPLETENESS_RULE,
        },
    }


def load_pose_library(char_asset=None, root=None):
    """Every READABLE anny_fit.json on disk, as (asset, cell, pose_aa, phenotype, fit_ok).

    THIS FUNCTION RETURNS ONLY THE RECORDS AND THEREFORE CANNOT TELL A CALLER WHETHER THE
    LIBRARY IS COMPLETE. Any caller that computes a rate, a fraction or a count over the
    library MUST call scan_pose_library() instead and carry its `integrity` record —
    adversarial-review finding F8 is precisely this function dropping unreadable files with
    a bare `continue`, so a violation rate would be published over a denominator that had
    shrunk without saying so. That drop is now also written to stderr, so even a caller that
    ignores the integrity record cannot lose the fact that files went missing.
    """
    scan = scan_pose_library(char_asset, root)
    integ = scan['integrity']
    if integ['n_dropped']:
        sys.stderr.write(
            'geom.pose_limits.load_pose_library: DROPPED %d of %d fitted pose file(s) for '
            'asset %r. The library is INCOMPLETE and any rate computed over it has a '
            'shrunken denominator. Dropped: %s\n'
            % (
                integ['n_dropped'],
                integ['n_files_found'],
                integ['char_asset'],
                '; '.join('%s (%s)' % (d['path'], d['reason']) for d in integ['dropped'][:10]),
            )
        )
    return scan['records']


def fit_mask_defect():
    """MEASURED evidence for the anny_fit bone-mask defect named in the module docstring.

    This does not fix anything — anny_fit.py belongs to another workstream — it measures
    the consequence, which is what a ROM gate is for. Returns None when the library is
    absent.
    """
    try:
        from zyg_workflows.geom import anny_fit as AF

        allow_stems = tuple(AF.POSE_BONES_FULL)
    except Exception:  # noqa: BLE001
        return None
    names, _ = bone_roster()
    m = MS._model()
    has_bones_attr = hasattr(m, 'bones')
    allowed = {n for n in names if any(s in n.lower() for s in allow_stems)}
    lib = load_pose_library()
    if not lib:
        return None
    moved = set()
    for rec in lib:
        nz = np.nonzero(np.linalg.norm(rec['pose_aa'], axis=1) > 1e-9)[0]
        moved |= {names[i] for i in nz}
    leaked = sorted(moved - allowed)
    return {
        'model_exposes_bones_attr': bool(has_bones_attr),
        'guard_source': (
            'geom/anny_fit.py: bone_names = [str(n) for n in m.bones] if '
            "hasattr(m, 'bones') else []  ->  allow = torch.ones(n_bones) "
            'when that list is empty'
        ),
        'n_allowed_by_intent': len(allowed),
        'n_bones_actually_moved': len(moved),
        'n_leaked': len(leaked),
        'leaked_bones': leaked,
        'poses_examined': len(lib),
        'finding': (
            'the anny model publishes bone_labels, not bones, so hasattr(m, '
            '"bones") is %s and the allow-list falls through to all-ones. %d bones '
            'outside the intended %d carry non-zero fitted rotations across %d '
            'poses.' % (has_bones_attr, len(leaked), len(allowed), len(lib))
        ),
    }


def _check_limit_and_exceedance(c):
    """(limit, exceedance, units) read STRAIGHT OFF a t5_joint_rom sub-check record.

    No number is invented here and none is chosen: every limit returned is one the
    sub-check itself already recorded from the printed constants, and the exceedance is
    just observed-minus-limit in the sub-check's own units. It exists so 'worst offender'
    means the largest measured breach of a printed band, rather than an arbitrary ordering.
    """
    st = c.get('status')
    if c.get('observed_share') is not None and c.get('min_share') is not None:
        return (c['min_share'], round(float(c['min_share']) - float(c['observed_share']), 6), 'share')
    obs = c.get('observed_deg')
    if obs is None:
        return None, None, None
    obs = abs(float(obs))
    if c.get('max_deg') is not None:
        return c['max_deg'], round(obs - float(c['max_deg']), 4), 'deg'
    if c.get('band_deg'):
        lim = float(c['band_deg'][1] if st == FAIL else c['band_deg'][0])
        return lim, round(obs - lim, 4), 'deg'
    if c.get('forced_deg') is not None:
        hard = float(c['natural_deg'] if strict_wrist() else c['forced_deg'])
        lim = hard if st == FAIL else float(c['natural_deg'])
        return lim, round(obs - lim, 4), 'deg'
    return None, None, None


def pose_library_report(char_asset=None, phenotype=None, local_changes=None, limit=None, root=None):
    """Run t5_joint_rom over the fitted pose library and report the violation RATE.

    A high rate is a finding about our poses. It is explicitly NOT a licence to widen a
    printed band, and this function cannot widen one.

    KEYS THIS FUNCTION RETURNS — this list is the contract, and every key below is
    genuinely computed here rather than aliased from another name:

      n_poses                 int   poses actually measured (== rate_denominator)
      rate_denominator        int   the denominator behind every rate in this record
      n_violating             int   poses whose t5_joint_rom status is FAIL
      n_warning               int   poses whose t5_joint_rom status is WARN
      n_passing               int   poses whose t5_joint_rom status is PASS
      violation_rate          float n_violating / rate_denominator
      warn_rate               float n_warning  / rate_denominator
      status                  str   the LIBRARY-SUBJECT verdict: the worst per-pose status,
                                    raised to at least WARN when the library is incomplete
      status_counts           dict  {status: n}
      per_check_counts        dict  {sub-check: {'fail': n, 'warn': n}}
      worst_offenders         dict  {'by_check': [...], 'by_pose': [...]} — see below
      library_complete        bool  from scan_pose_library()
      integrity               dict  the full file accounting, F8
      occiput_share_failures_by_total_rotation   dict
      pronation_coupling      dict
      rows                    list  one row per pose, with its violations
      policy                  str
      explain                 str   one sentence, safe to render on its own

    worst_offenders['by_check'] rows: {check, fail, warn, fail_share_of_poses,
      worst_exceedance, worst_units, worst_pose}. worst_offenders['by_pose'] rows:
      {asset, cell, path, fit_ok, status, n_fail, n_warn, worst_check, worst_exceedance,
      worst_units}. Both are sorted worst-first and capped at 10.

    HISTORICAL NOTE, kept because it is the defect this contract exists to close: an
    earlier consumer read `n_violating` and `violating` off this record, this function
    returned neither, and a library measured at violation_rate 1.0 rendered as
    "ROM-violating None". `n_violating` below is the real numerator, not an alias.
    """
    scan = scan_pose_library(char_asset, root)
    lib, integ = scan['records'], scan['integrity']
    if limit:
        lib = lib[: int(limit)]
        integ = dict(integ)
        integ['complete'] = False
        integ['limit_applied'] = int(limit)
        integ['note_limit'] = (
            'a caller-supplied limit truncated the library to %d poses; '
            'this record is a sample, not the library' % int(limit)
        )
    if not lib:
        return {
            'n_poses': 0,
            'rate_denominator': 0,
            'n_violating': None,
            'n_warning': None,
            'n_passing': None,
            'violation_rate': None,
            'warn_rate': None,
            'status': UNRESOLVED,
            'status_counts': {},
            'per_check_counts': {},
            'worst_offenders': {'by_check': [], 'by_pose': []},
            'library_complete': False,
            'integrity': integ,
            'occiput_share_failures_by_total_rotation': {},
            'pronation_coupling': None,
            'rows': [],
            'policy': 'a high rate is a finding about our pose library. It is not a reason to widen a printed band.',
            'reason': (
                'no readable anny_fit.json under %s for asset %r (glob matched %d '
                'file(s), %d were dropped as unreadable)'
                % (POSE_LIBRARY_ROOT, integ['char_asset'], integ['n_files_found'], integ['n_dropped'])
            ),
            'explain': (
                'no fitted pose library could be read for asset %r: %d file(s) '
                'matched, %d loaded. NOT a pass — these poses were never checked.'
                % (integ['char_asset'], integ['n_files_found'], integ['n_loaded'])
            ),
        }
    rows, counts = [], {}
    coupling = []
    for rec in lib:
        ph = dict(phenotype or NEUTRAL)
        ph.update(
            {
                k: v
                for k, v in (rec['phenotype'] or {}).items()
                if k in ('gender', 'age', 'muscle', 'weight', 'height', 'proportions')
            }
        )
        sk = skeleton_from_pose_aa(ph, rec['pose_aa'], local_changes, source='%s/%s' % (rec['asset'], rec['cell']))
        r = t5_joint_rom(sk)
        counts[r['status']] = counts.get(r['status'], 0) + 1
        bad = [c for c in r['detail']['checks'] if c['status'] in (FAIL, WARN)]
        viols = []
        for c in bad:
            lim, exc, units = _check_limit_and_exceedance(c)
            viols.append(
                {
                    'check': c['check'],
                    'status': c['status'],
                    'observed_deg': c.get('observed_deg'),
                    'observed_share': c.get('observed_share'),
                    'total_cervical_deg': c.get('total_cervical_deg'),
                    'limit': lim,
                    'exceedance': exc,
                    'units': units,
                }
            )
        rows.append(
            {
                'asset': rec['asset'],
                'cell': rec['cell'],
                'path': rec['path'],
                'fit_ok': rec['fit_ok'],
                'status': r['status'],
                'n_fail': sum(1 for v in viols if v['status'] == FAIL),
                'n_warn': sum(1 for v in viols if v['status'] == WARN),
                'violations': viols,
            }
        )
        for side in ('l', 'r'):
            c = pronation_coupling_in_pose(sk, side)
            if c['resolved']:
                coupling.append((c['forearm_twist_deg'], c['humerus_twist_deg']))
    per_check = {}
    for r in rows:
        for v in r['violations']:
            k = v['check']
            per_check.setdefault(k, {FAIL: 0, WARN: 0})
            per_check[k][v['status']] += 1
    # A share violation on a 0.4 deg twitch and one on a 40 deg turn are the same ratio
    # and not the same finding, so the share failures are binned by how much rotation was
    # actually being apportioned. No bin is a threshold; the bins are decades.
    share_mag = {}
    for r in rows:
        for v in r['violations']:
            if not v['check'].startswith('occiput_c2_share'):
                continue
            t = abs(v.get('total_cervical_deg') or 0.0)
            b = (
                '<1deg'
                if t < 1
                else '1-5deg'
                if t < 5
                else '5-15deg'
                if t < 15
                else '15-45deg'
                if t < 45
                else '>=45deg'
            )
            share_mag.setdefault(v['check'], {}).setdefault(b, 0)
            share_mag[v['check']][b] += 1
    fa = np.array([c[0] for c in coupling]) if coupling else np.zeros(0)
    hu = np.array([c[1] for c in coupling]) if coupling else np.zeros(0)
    corr = None
    if len(fa) > 2 and fa.std() > 1e-9 and hu.std() > 1e-9:
        corr = float(np.corrcoef(fa, hu)[0, 1])

    n = len(rows)
    n_fail = sum(1 for r in rows if r['status'] == FAIL)
    n_warn = sum(1 for r in rows if r['status'] == WARN)
    n_pass = sum(1 for r in rows if r['status'] == PASS)

    # WORST OFFENDERS. Ordering only — every quantity below was already measured against a
    # printed band by t5_joint_rom, and nothing here can change a verdict.
    by_check = []
    for k, v in per_check.items():
        hits = [(r, x) for r in rows for x in r['violations'] if x['check'] == k]
        scored = [(x['exceedance'], r) for r, x in hits if x['exceedance'] is not None]
        wx, wr = max(scored, key=lambda t: t[0]) if scored else (None, None)
        by_check.append(
            {
                'check': k,
                'fail': v[FAIL],
                'warn': v[WARN],
                'fail_share_of_poses': round(v[FAIL] / float(n), 4),
                'worst_exceedance': wx,
                'worst_units': next((x['units'] for _, x in hits if x['units']), None),
                'worst_pose': (None if wr is None else '%s/%s' % (wr['asset'], wr['cell'])),
            }
        )
    by_check.sort(key=lambda d: (-(d['fail'] + d['warn']), d['check']))
    by_pose = []
    for r in rows:
        if r['status'] not in (FAIL, WARN):
            continue
        scored = [(x['exceedance'], x) for x in r['violations'] if x['exceedance'] is not None]
        wx, wv = max(scored, key=lambda t: t[0]) if scored else (None, None)
        by_pose.append(
            {
                'asset': r['asset'],
                'cell': r['cell'],
                'path': r['path'],
                'fit_ok': r['fit_ok'],
                'status': r['status'],
                'n_fail': r['n_fail'],
                'n_warn': r['n_warn'],
                'worst_check': (wv or {}).get('check'),
                'worst_exceedance': wx,
                'worst_units': (wv or {}).get('units'),
            }
        )
    by_pose.sort(key=lambda d: (-d['n_fail'], -(d['worst_exceedance'] or 0.0)))

    # THE LIBRARY-SUBJECT VERDICT. The worst per-pose status, because the claim is that
    # every joint angle we ship is inside a printed band — one pose out of band falsifies
    # it. Raised to at least WARN when files were dropped: a rate over a shrunken
    # denominator cannot certify the library it was supposed to measure (F8).
    # ROLLUP_RANK is the module's single ordering; a second copy here could drift from it.
    status = rollup(counts.keys())
    incomplete_note = None
    if not integ['complete']:
        why = []
        if integ['n_dropped']:
            why.append(
                '%d of %d matched file(s) did not load: %s'
                % (integ['n_dropped'], integ['n_files_found'], ', '.join(integ['dropped_paths'][:6]))
            )
        if integ.get('limit_applied'):
            why.append(
                'a caller-supplied limit truncated the library to %d of the %d '
                'poses on disk' % (integ['limit_applied'], integ['n_loaded'])
            )
        if not why:
            why.append('the glob matched no file at all under %s' % integ['pattern'])
        incomplete_note = (
            '%s. This rate therefore has a shrunken denominator (%d) and CANNOT certify '
            'the library it was meant to measure.' % ('; '.join(why), n)
        )
        status = rollup((status, WARN))
    explain = (
        '%d of %d fitted pose(s) FAIL t5_joint_rom against the printed AFS '
        'p.181-182 / HeadNeck p.161 / p.171 bands (violation rate %.4f, warn rate '
        '%.4f). Worst sub-check: %s.'
        % (
            n_fail,
            n,
            n_fail / float(n),
            n_warn / float(n),
            (
                '%s, failing %d and warning %d of %d poses'
                % (by_check[0]['check'], by_check[0]['fail'], by_check[0]['warn'], n)
            )
            if by_check
            else 'none — every sub-check passed on every pose',
        )
    )
    if integ['n_fit_ok_false']:
        # Kept separate from the ROM verdict on purpose: 'our fit failed on this cell' and
        # 'this pose is out of a printed band' are different findings and must not be
        # allowed to explain each other away.
        explain += (
            ' %d of these pose(s) carry fit_ok=False from their own fit, which is a '
            'separate finding and is NOT an excuse for the band violations.' % integ['n_fit_ok_false']
        )
    if incomplete_note:
        explain += ' LIBRARY INCOMPLETE: ' + incomplete_note

    return {
        'n_poses': n,
        'rate_denominator': n,
        'status_counts': counts,
        'n_violating': n_fail,
        'n_warning': n_warn,
        'n_passing': n_pass,
        'violation_rate': round(n_fail / float(n), 4),
        'warn_rate': round(n_warn / float(n), 4),
        'status': status,
        'per_check_counts': per_check,
        'worst_offenders': {'by_check': by_check[:10], 'by_pose': by_pose[:10]},
        'library_complete': bool(integ['complete']),
        'library_incomplete_note': incomplete_note,
        'integrity': integ,
        'occiput_share_failures_by_total_rotation': share_mag,
        'pronation_coupling': {
            'n_arms': len(coupling),
            'forearm_twist_deg_abs_mean': (round(float(np.abs(fa).mean()), 3) if len(fa) else None),
            'humerus_twist_deg_abs_mean': (round(float(np.abs(hu).mean()), 3) if len(hu) else None),
            'pearson_r_forearm_vs_humerus': (round(corr, 4) if corr is not None else None),
            'n_arms_humerus_twist_above_floor': int(sum(1 for v in hu if abs(v) > 1e-3)),
            'note': 'AFS p.149 requires the humerus twist to owe nothing to the '
            'forearm twist. A correlation here is a retarget defect, not an '
            'anatomy one; it is reported, never gated, because no printed '
            'source gives a correlation threshold.',
        },
        'rows': rows,
        'explain': explain,
        'policy': 'a high rate is a finding about our pose library. It is not a reason to widen a printed band.',
    }


def run_character(name, phenotype, local_changes=None, side='l'):
    """Every gate this file can run on one body, IN ITS SHIPPED REST CONFIGURATION ONLY.

    READ THIS BEFORE CALLING IT FROM A GATE. The subject here is the A-pose and nothing
    else: `skeleton_from_rig(..., pose_aa=None)`. On the shipped A-pose the wrists sit
    within ~6 deg of anatomical neutral and the whole cervical chain is at zero, so
    t5_joint_rom's PASS is a property of the rest pose, not of anything a pose channel
    ships. A gate whose registry text claims the fitted pose library as part of its subject
    MUST NOT be scored from this function — call pose_layer() instead, which evaluates both
    subjects and rolls them up. This is adversarial-review finding F3/D3/calibration-6, and
    the reason the warning is here rather than only in the caller.
    """
    out = {'character': name, 'schema': SCHEMA, 'gates': []}
    sk = skeleton_from_rig(phenotype, local_changes, None, source=name)
    st = sk.state
    out['stature_m'] = round(float(st['v'][:, 2].max() - st['v'][:, 2].min()), 4)
    af = anatomical_frame(st)
    out['anatomical_frame'] = {k: (np.round(v, 4).tolist() if isinstance(v, np.ndarray) else v) for k, v in af.items()}
    out['rest_geometry'] = {
        'elbow_included_deg': {s: round(elbow_angle(sk, s), 2) for s in ('l', 'r')},
        'knee_included_deg': {s: round(knee_angle(sk, s), 2) for s in ('l', 'r')},
        'wrist': {
            s: {
                k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in wrist_angles(sk, s).items()
                if k in ('extension_deg', 'ulnar_deviation_deg', 'total_deviation_from_neutral_deg', 'frame_kind')
            }
            for s in ('l', 'r')
        },
    }
    for fn, args in (
        (t5_joint_rom, (sk,)),
        (t5_pronation_isolation, (phenotype, local_changes, side)),
        (t5_scapula_static, (phenotype, local_changes, side)),
        (t5_elbow_owner, (phenotype, local_changes, side)),
        (t5_patellar_ligament, (phenotype, local_changes, side)),
    ):
        try:
            out['gates'].append(fn(*args))
        except Exception as e:  # noqa: BLE001
            import traceback

            out['gates'].append(
                _res(fn.__name__, ERROR, '%s: %s' % (type(e).__name__, e), traceback=traceback.format_exc()[-1500:])
            )
    return out
