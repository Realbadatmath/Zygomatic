# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""fit_proportions.py — print_delta and the --bake leg that writes the recipes (lines 1146-1426 of the pre-split file, verbatim)."""

from .core import (
    argparse,
    ast,
    json,
    os,
    subprocess,
    sys,
    tempfile,
    MS,
    SCHEMA,
    ISSUE_ANATOMY,
    ANATOMY_SYMBOLIC,
    ANATOMY_DROPPED,
    OUTER_ROUNDS,
    INNER_ITERS,
)
from .fit import fit_sex, REPORT_RATIOS
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def print_delta(sex, rec):
    b, a = rec['before']['ratios'], rec['after']['ratios']
    _zyg_log.info('\n=== %s: before -> after ===' % sex.upper())
    _zyg_log.info('%-46s %9s %9s %7s %7s %6s' % ('ratio', 'before', 'after', 'z0', 'z1', 'flags'))
    for name in REPORT_RATIOS:
        if name not in b or name not in a:
            continue
        f = []
        if b[name]['outside_band']:
            f.append('OUT0')
        if a[name]['outside_band']:
            f.append('OUT1')
        if a[name].get('survey_comparable') is not True:
            f.append('nc')
        if a[name].get('at_window_endpoint'):
            f.append('win')
        _zyg_log.info(
            '%-46s %9.4f %9.4f %+7.3f %+7.3f %6s'
            % (name, b[name]['value'], a[name]['value'], b[name]['z'], a[name]['z'], ','.join(f))
        )
    if 'head_count_CONSEQUENCE' in rec['after']:
        _zyg_log.info(
            'head count (CANON, CONSEQUENCE, never a target): %.3f -> %.3f'
            % (rec['before'].get('head_count_CONSEQUENCE', float('nan')), rec['after']['head_count_CONSEQUENCE'])
        )
    _zyg_log.info(
        'chamfer upper-body fwd %.2f -> %.2f mm, rev %.2f -> %.2f mm'
        % (
            rec['before']['chamfer_upper_fwd_mm'],
            rec['after']['chamfer_upper_fwd_mm'],
            rec['before']['chamfer_upper_rev_mm'],
            rec['after']['chamfer_upper_rev_mm'],
        )
    )
    _zyg_log.info(
        'chamfer full-body  fwd %.2f -> %.2f mm, rev %.2f -> %.2f mm'
        % (
            rec['before']['chamfer_full_fwd_mm'],
            rec['after']['chamfer_full_fwd_mm'],
            rec['before']['chamfer_full_rev_mm'],
            rec['after']['chamfer_full_rev_mm'],
        )
    )
    _zyg_log.info('cage sha %s -> %s' % (rec['before']['cage_vert_sha256'][:16], rec['after']['cage_vert_sha256'][:16]))
    _zyg_log.info(
        'inner leg/torso re-fit: %s | do-no-harm guard: %s'
        % ('RAN' if rec['inner_refit_ran'] else 'FROZEN (declined, see declined_unrestricted_solve)', rec['guard'])
    )


# ===========================================================================
# the bake — literals generated from the JSON, written, re-parsed off disk
# ===========================================================================


def _fmt_dict(d, indent, symbolic=None):
    """A deterministic, sorted, PEP8-ish literal. Values that name a module symbol are
    written as that symbol, not as its string value, so ORIGINAL_ANATOMY keeps referring
    to ABS_PATTERN_V2 instead of hard-coding 'v2-afs-p30' in two places."""
    symbolic = symbolic or {}
    pad = ' ' * indent
    parts = []
    for k in sorted(d):
        v = d[k]
        if k in symbolic and v in symbolic[k]:
            parts.append("%s'%s': %s," % (pad, k, v))
        elif isinstance(v, str):
            parts.append("%s'%s': '%s'," % (pad, k, v))
        elif isinstance(v, float):
            parts.append("%s'%s': %s," % (pad, k, repr(round(v, 6))))
        else:
            parts.append("%s'%s': %r," % (pad, k, v))
    return '\n'.join(parts)


def _literal_by_sex(by_sex, symbolic=None):
    out = ['{']
    for sex in ('male', 'female'):
        out.append("    '%s': {" % sex)
        out.append(_fmt_dict(by_sex[sex], 8, symbolic))
        out.append('    },')
    out.append('}')
    return '\n'.join(out)


def _replace_assign(src, name, literal):
    """Splice a new value onto a module-level assignment, located by ast rather than by
    regex, so a comment that happens to contain the name cannot be hit."""
    tree = ast.parse(src)
    node = None
    for n in tree.body:
        if (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == name
        ):
            node = n
    if node is None:
        raise RuntimeError('no module-level assignment to %s' % name)
    lines = src.splitlines(keepends=True)
    start = sum(len(x) for x in lines[: node.value.lineno - 1]) + node.value.col_offset
    end = sum(len(x) for x in lines[: node.value.end_lineno - 1]) + node.value.end_col_offset
    return src[:start] + literal + src[end:]


def _module_dicts(path):
    """Re-read the WRITTEN file in a fresh interpreter and hand back the three tables it
    actually defines. A subprocess, not an importlib reload, because this process already
    has geom.mesh_skeletons imported and a reload would let a stale module win — which is
    exactly the failure mode this round-trip exists to catch."""
    code = (
        'import json,sys;'
        'sys.path.insert(0, %r);'
        'from geom import mesh_skeletons as MS;'
        'print(json.dumps({"phen": MS.ORIGINAL_PHEN, "locals": MS.ORIGINAL_LOCALS,'
        ' "anat": MS.ORIGINAL_ANATOMY}, sort_keys=True))' % os.path.dirname(os.path.dirname(os.path.abspath(path)))
    )
    out = subprocess.check_output([sys.executable, '-c', code])
    return json.loads(out.decode().strip().splitlines()[-1])


def bake(fit_path, target=None, dry_run=False):
    """Write the fitted recipes into geom/mesh_skeletons.py and prove it landed.

    NEVER hand-type a fitted number. Every literal in the file below is generated from
    the fit JSON, written, and then read BACK OFF DISK twice — once with ast.literal_eval
    on the parsed assignment, once by importing the written module in a fresh
    interpreter — and compared to the JSON. A stale hand-typed run once put 29 of 32
    locals wrong; this is the check that makes that impossible to repeat.
    """
    with open(fit_path) as f:
        recs = json.load(f)
    for sex in ('male', 'female'):
        if sex not in recs:
            raise RuntimeError(
                'fit JSON has no %r — bake both sexes together, the file holds one table for the pair' % sex
            )
        if recs[sex].get('schema') != SCHEMA:
            raise RuntimeError('%s: schema %r, this module writes %r' % (sex, recs[sex].get('schema'), SCHEMA))
    # ORIGINAL_PHEN / ORIGINAL_LOCALS / ORIGINAL_ANATOMY live in mesh_skeletons/spec.py since the
    # 2026-10 split of mesh_skeletons.py into a package.
    target = target or str(paths.PKG_DIR / 'geom' / 'mesh_skeletons' / 'spec.py')
    phen = {s: dict(recs[s]['phenotype']) for s in ('male', 'female')}
    locs = {s: dict(recs[s]['local_changes']) for s in ('male', 'female')}
    anat = {s: dict(ISSUE_ANATOMY[s]) for s in ('male', 'female')}
    for s in ('male', 'female'):
        for k in ANATOMY_DROPPED:
            if k in recs[s].get('anatomy', {}):
                raise RuntimeError(
                    '%s: the fit was run WITH %r in the anatomy layer but the issue drops it — re-run the fit' % (s, k)
                )

    src0 = open(target).read()
    src = _replace_assign(src0, 'ORIGINAL_PHEN', _literal_by_sex(phen))
    src = _replace_assign(src, 'ORIGINAL_LOCALS', _literal_by_sex(locs))
    src = _replace_assign(src, 'ORIGINAL_ANATOMY', _literal_by_sex(anat, ANATOMY_SYMBOLIC))
    if dry_run:
        return src

    # atomic write, then verify off disk
    d = os.path.dirname(os.path.abspath(target))
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.py.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(src)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    # ---- round trip 1: ast, on the literal assignments -------------------
    back = open(target).read()
    tree = ast.parse(back)
    got = {}
    for n in tree.body:
        if (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id in ('ORIGINAL_PHEN', 'ORIGINAL_LOCALS')
        ):
            got[n.targets[0].id] = ast.literal_eval(n.value)
    if got.get('ORIGINAL_PHEN') != phen:
        raise RuntimeError('AST ROUND TRIP FAILED on ORIGINAL_PHEN: %r != %r' % (got.get('ORIGINAL_PHEN'), phen))
    if got.get('ORIGINAL_LOCALS') != locs:
        raise RuntimeError('AST ROUND TRIP FAILED on ORIGINAL_LOCALS: %r != %r' % (got.get('ORIGINAL_LOCALS'), locs))

    # ---- round trip 2: a fresh interpreter, on the SEMANTICS --------------
    want_anat = {
        s: {
            k: (ANATOMY_SYMBOLIC[k][v] if k in ANATOMY_SYMBOLIC and v in ANATOMY_SYMBOLIC[k] else v)
            for k, v in anat[s].items()
        }
        for s in ('male', 'female')
    }
    live = _module_dicts(target)
    for name, want, gotv in (
        ('ORIGINAL_PHEN', phen, live['phen']),
        ('ORIGINAL_LOCALS', locs, live['locals']),
        ('ORIGINAL_ANATOMY', want_anat, live['anat']),
    ):
        if want != gotv:
            raise RuntimeError('IMPORT ROUND TRIP FAILED on %s: %r != %r' % (name, gotv, want))
        for s in ('male', 'female'):
            for k in ANATOMY_DROPPED:
                if k in (live['anat'].get(s) or {}):
                    raise RuntimeError('%s still carries %r after the bake' % (s, k))
    _zyg_log.info(
        'BAKED %s — ast round trip OK, fresh-import round trip OK, %r dropped from '
        'both originals' % (target, list(ANATOMY_DROPPED))
    )
    return src


# ===========================================================================


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--sex', action='append', default=None, choices=('male', 'female'))
    ap.add_argument('--out', default='')
    ap.add_argument('--inner', type=int, default=INNER_ITERS)
    ap.add_argument('--rounds', type=int, default=OUTER_ROUNDS)
    ap.add_argument('--bake', default='', help='fit JSON to write into mesh_skeletons.py')
    a = ap.parse_args(argv)
    if a.bake:
        bake(a.bake)
        return {}
    sexes = a.sex or ['male', 'female']
    recs = {}
    for sex in sexes:
        # the recipe build_originals() actually builds: the neutral template merged with
        # the fitted overrides. ORIGINAL_PHEN alone carries no `gender`, and a fit run
        # without it silently optimises an androgynous body.
        phen0 = {**MS.ORIGINAL_SPEC[sex], **MS.ORIGINAL_PHEN[sex]}
        # the fit runs on the anatomy layer this issue SHIPS — i.e. without bony_relief —
        # so the measured constraints are solved on the cage that will be hashed
        anat0 = {
            k: (ANATOMY_SYMBOLIC[k][v] if k in ANATOMY_SYMBOLIC and v in ANATOMY_SYMBOLIC[k] else v)
            for k, v in ISSUE_ANATOMY[sex].items()
        }
        rec = fit_sex(sex, phen0, MS.ORIGINAL_LOCALS[sex], anat0, iters=a.inner, rounds=a.rounds)
        if rec['band_regressions']:
            # The unrestricted solve improves the surface fit but pushes a MEASURED ratio
            # out of its band. Feet and hands are in NO objective — fit_reference masks
            # them out of the chamfer by skinning weight and no ratio steers them, so they
            # ride on whatever the height axis does — and this pass is forbidden from
            # making them free parameters. So the improvement is declined, not the guard:
            # re-solve with the whole leg/torso free set frozen at its issued value and
            # only the released outer levers moving.
            print(
                '  %s: the unrestricted re-fit trips the do-no-harm guard on %s. '
                'Declining it and re-solving with the leg/torso free set FROZEN.'
                % (sex, ', '.join(g['ratio'] for g in rec['band_regressions']))
            )
            declined = rec
            rec = fit_sex(sex, phen0, MS.ORIGINAL_LOCALS[sex], anat0, iters=a.inner, rounds=a.rounds, freeze_inner=True)
            rec['declined_unrestricted_solve'] = {
                'band_regressions': declined['band_regressions'],
                'local_changes': declined['local_changes'],
                'phenotype': declined['phenotype'],
                'after_chamfer_full_fwd_mm': declined['after']['chamfer_full_fwd_mm'],
                'after_chamfer_full_rev_mm': declined['after']['chamfer_full_rev_mm'],
            }
            if rec['band_regressions']:
                raise RuntimeError(
                    '%s: the FROZEN solve still trips the guard on %s. Nothing is '
                    'written. A repair pass may not push a MEASURED ratio out of band.'
                    % (sex, ', '.join(g['ratio'] for g in rec['band_regressions']))
                )
        recs[sex] = rec
        print_delta(sex, rec)
    if a.out:
        with open(a.out, 'w') as f:
            json.dump(recs, f, indent=1, sort_keys=True)
        print('WROTE %s' % a.out)
    return recs
