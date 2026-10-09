# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro CLI — the argument parser and main().

Moved verbatim from geom/anthro/__main__.py (lines 1636-1753) when that 1,757-line
file became the __main__ shim over this package. No logic was changed.
"""

import argparse
import os
import sys
import traceback

from zyg_workflows.geom.anthro.main_ops.constants import EXIT_ERROR, GatesUnusable
from zyg_workflows.geom.anthro.main_ops.commands import cmd_build_pack, cmd_check, cmd_measure, cmd_reference
from zyg_workflows.geom.anthro.main_ops.selftest import cmd_list, cmd_selftest

# ---------------------------------------------------------------------------------
# Defaults for the shared options. They are applied after parsing rather than by argparse,
# because the same options are attached to the main parser AND to every subparser (so that
# both `--ancestry X check c` and `check c --ancestry X` work), and an argparse default on
# the subparser would overwrite a value the main parser had already read.
_COMMON_DEFAULTS = {'columns': 100, 'width': 'p5p95', 'ancestry': None, 'out': None}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        """A usage error is exit 3 (internal error), never 2. In this CLI 2 means the
        BODY failed its gates, and a mistyped flag must not be reported as that."""
        self.print_usage(sys.stderr)
        sys.stderr.write('%s: error: %s\n' % (self.prog, message))
        raise SystemExit(EXIT_ERROR)


def _common():
    c = argparse.ArgumentParser(add_help=False)
    c.add_argument('--columns', type=int, default=argparse.SUPPRESS, help='terminal width')
    c.add_argument('--width', default=argparse.SUPPRESS, help='band width: p1p99 p5p95 p25p75 sd1 sd2 sd3')
    c.add_argument(
        '--ancestry',
        default=argparse.SUPPRESS,
        help='DODRace group for the bands. Omitting it uses the POOLED US '
        'Army mixture, which is a bias, not a tolerance.',
    )
    c.add_argument(
        '--out',
        default=argparse.SUPPRESS,
        help='where the JSON goes. An existing directory (or a path ending in '
        '%s) takes one file per character, <dir>/<name>.json, for one '
        'character or for "all". Anything else is a file, and a file with '
        '"all" is refused before the run starts rather than N reports '
        'racing for one path. `measure`, `reference` and `selftest` take '
        'a directory here.' % os.sep,
    )
    return c


def _parser():
    common = _common()
    p = _Parser(
        prog='python -m zyg_workflows.geom.anthro',
        parents=[common],
        description='Measure generated parametric bodies against real anthropometric '
        'distributions. Exit 0 pass, 1 pass-with-warnings, 2 fail, '
        '3 internal error.',
    )
    sub = p.add_subparsers(dest='cmd', parser_class=_Parser)

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    c = add('check', help='run the gates, print the report, write the JSON')
    c.add_argument('character', help='a character name, or "all"')
    c.add_argument('--quiet', action='store_true', help='summary line only')
    c.add_argument('--only-problems', action='store_true', help='hide passing gates (the strip is still complete)')
    c.add_argument(
        '--keep-stale-summary',
        action='store_true',
        help='do NOT supersede the stored summary of a character that could '
        'not be gated. For a read-only checkout. The stale record then '
        'keeps presenting its old verdict as current, and this run says '
        'so on stderr; the exit code is unchanged.',
    )
    c.set_defaults(fn=cmd_check)

    m = add('measure', help='the measurement table with its conventions')
    m.add_argument('character')
    m.add_argument('--json', action='store_true')
    m.set_defaults(fn=cmd_measure)

    r = add('reference', help='the band and provenance for one ratio')
    r.add_argument('ratio', help='a ratio name, or "list"')
    r.add_argument('--sex', default='male')
    r.set_defaults(fn=cmd_reference)

    b = add('build-pack', help='re-run the reference builder')
    b.set_defaults(fn=cmd_build_pack)

    s = add('selftest', help='exercise the whole stack on one character')
    s.add_argument('--character', default='abel')
    s.set_defaults(fn=cmd_selftest)

    ls = add('list', help='characters this CLI can see')
    ls.set_defaults(fn=cmd_list)
    return p


def main(argv=None):
    p = _parser()
    try:
        a = p.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_ERROR
    for k, v in _COMMON_DEFAULTS.items():
        if not hasattr(a, k):
            setattr(a, k, v)
    if not getattr(a, 'fn', None):
        p.print_help()
        return EXIT_ERROR
    try:
        return int(a.fn(a))
    except SystemExit as e:
        code = e.code
        if isinstance(code, int):
            return code
        sys.stderr.write('%s\n' % code)
        return EXIT_ERROR
    except GatesUnusable as e:
        # Deliberately NOT a fixture fallback: gates.py exists, so a report that did not
        # run it is not a report about this body.
        sys.stderr.write('INTERNAL ERROR: %s\n' % e)
        return EXIT_ERROR
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return EXIT_ERROR
