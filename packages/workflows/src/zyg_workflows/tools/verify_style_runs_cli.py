# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.verify_style_runs`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.verify_style_runs` still reaches it.
"""

import argparse
import os
import sys

from zyg_workflows.tools.verify_style_runs import __doc__ as _LIB_DOC
from zyg_workflows.tools.verify_style_runs import (
    FAMILY_ROOTS,
    LIBRARY_URL,
    check,
    fetch_library,
    newest_per_style,
)


def main():
    ap = argparse.ArgumentParser(description=_LIB_DOC)
    ap.add_argument(
        '--family',
        default='children',
        choices=sorted(FAMILY_ROOTS),
        help='which style family (and output root) to verify',
    )
    ap.add_argument('styles', nargs='+', help='style keys to verify')
    a = ap.parse_args()

    root = FAMILY_ROOTS[a.family]
    found = newest_per_style(root, set(a.styles))
    try:
        songs = fetch_library().get('songs') or []
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print(f'FAIL library {LIBRARY_URL}: {exc}')
        return 2

    bad = 0
    for style in a.styles:
        if style not in found:
            print(f'FAIL {style:12s} no manifest under output/{root}/*/')
            bad += 1
            continue
        out_dir, man = found[style]
        fails = check(style, a.family, out_dir, man, songs)
        jid = os.path.basename(out_dir)
        if fails:
            bad += 1
            print(f'FAIL {style:12s} {jid}  ' + '; '.join(fails))
        else:
            clap = man['gates']['render']['checks']['clap']['positive_prob']
            lufs = man['gates']['master']['checks']['lufs']
            extra = ''
            if a.family != 'cinematic':
                vc = man['video']['gates']['checks']
                extra = (
                    f'video={vc["frames"]} pictures '
                    f'cartoon={vc["cartoon"]["mean"]} lettered='
                    f'{vc["lettering"]["frames_with_text"]} '
                )
            print(
                f'PASS {style:12s} {jid}  engine=sampler '
                f'layers={len(man["render"]["layers"])} '
                f'picked={man["delivery"]["picked"]}'
                f'({man["delivery"]["picked_leg"]}) '
                f'master={lufs} LUFS clap={clap} {extra}'
                f'shelf={a.family}/{style} elapsed={man.get("elapsed_s")}s'
            )
    print(f'{len(a.styles) - bad}/{len(a.styles)} styles pass in family {a.family!r}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
