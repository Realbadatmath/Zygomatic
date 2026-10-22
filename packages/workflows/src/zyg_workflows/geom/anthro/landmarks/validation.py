# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ANSUR II validation harness and the CLI."""

from zyg_workflows.geom.anthro.landmarks.constants import (
    MS,
    REFERENCE_FRACTIONS,
    REF_MALE,
    _paths,
    np,
    os,
)

# ---------------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------------
# $ZYG_ANSUR_IMPORT_DIR overrides it; the default lives under the package scratch root
# (paths.ZYG_TMP_DIR, 0o700) rather than a world-readable fixed /tmp path.
SCRATCH = _paths.ZYG_ANSUR_IMPORT_DIR


def _ansur_check():
    """Recompute REFERENCE_FRACTIONS from the microdata so the table cannot silently
    drift from its source. Returns [] if the files are absent."""
    import csv

    rows = []
    for sex, fn in (('male', 'ansur_m.csv'), ('female', 'ansur_f.csv')):
        p = os.path.join(SCRATCH, fn)
        if not os.path.exists(p):
            return []
        with open(p, newline='', encoding='latin-1') as fh:
            d = list(csv.DictReader(fh))
        st = np.array([float(r['stature']) for r in d])
        for key, (m, f, col) in REFERENCE_FRACTIONS.items():
            want = m if sex == 'male' else f
            got = np.array([float(r[col]) for r in d]) / st
            rows.append((sex, key, want[0], want[1], got.mean(), got.std(ddof=1), len(d)))
    return rows


def _cases():
    reg = MS._registry()
    out = [('anny-neutral', REF_MALE, None, None, 'male')]
    for sec in ('originals', 'derived'):
        for k in reg.get(sec, {}):
            p = reg[sec][k]['params']
            sex = p.get('sex') or ('female' if p['phenotype'].get('gender', 0) > 0.5 else 'male')
            out.append((k, p['phenotype'], p['local_changes'], p.get('anatomy_layer'), sex))
    return out


def main(*a, **k):
    """The CLI lives in validation_cli; `landmarks/__init__` still re-exports this name."""
    from zyg_workflows.geom.anthro.landmarks.validation_cli import main as _m

    return _m(*a, **k)


if __name__ == '__main__':  # the CLI lives in validation_cli
    from zyg_workflows.geom.anthro.landmarks.validation_cli import main as _cli_main

    raise SystemExit(_cli_main())
