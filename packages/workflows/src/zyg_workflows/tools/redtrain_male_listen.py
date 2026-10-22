# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build the audition page for the ten male takes of "The Red Train to the Sea".

Reads male_voices/index.json and writes male_voices/listen.html. Separate from
the render script so the page can be rebuilt without touching the GPU.

The shipped ADULT FEMALE master is the first row: the sweep's whole question is
"which of these should replace it", and a bench you cannot A/B against the thing
it is replacing does not answer that.

F0 is printed but the gate column is marked ADVISORY, because the band it is
held against (110-285 Hz) was set on Praat and the number beside it comes from
RMVPE. Rank by ear.
"""

import os
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
JOB = os.path.join(CREWS, 'output/kidsmusic/1ba342d5cd75')
OUT = os.path.join(JOB, 'male_voices')

CSS = """
 body{font:14px/1.5 system-ui,sans-serif;margin:0;padding:28px;background:#14161a;color:#e6e8ec}
 h1{font-size:20px;margin:0 0 4px}
 .sub{color:#9aa3b0;margin:0 0 22px;max-width:74ch}
 table{border-collapse:collapse;width:100%;max-width:1240px}
 th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
     color:#8b94a3;border-bottom:1px solid #2b3038;padding:6px 10px;font-weight:600}
 td{border-bottom:1px solid #22262d;padding:10px;vertical-align:middle}
 tr.ref{background:#1b2028}
 tr.dead{background:#2a1a1c}
 .k{color:#6f7a8a;font-variant-numeric:tabular-nums}
 .n{min-width:200px;font-weight:600}
 .cap{font-weight:400;font-size:11px;color:#818b99;margin-top:3px;max-width:36ch}
 .why{font-weight:400;font-size:11px;color:#a7b0bd;margin-top:3px;max-width:36ch}
 .num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
 .u{color:#6f7a8a;font-size:11px;margin-left:2px}
 .na{color:#5c6470;font-size:11px}
 .st{font-size:11px;font-weight:700;text-transform:uppercase}
 .st.pass{color:#5fd08a} .st.warn{color:#e8c46a} .st.fail{color:#ff7b7b}
 audio{height:32px;width:260px}
 .note{margin-top:22px;color:#8b94a3;font-size:12px;max-width:82ch}
 .note b{color:#c3cad4}
 code{color:#9aa3b0;font-size:11px}
"""


def num(v, unit='', dp=0):
    if v is None:
        return '<td class="num na">&mdash;</td>'
    return f'<td class=num>{float(v):.{dp}f}' + (f'<span class=u> {unit}</span>' if unit else '') + '</td>'


if __name__ == '__main__':  # the CLI lives in redtrain_male_listen_cli
    from zyg_workflows.tools.redtrain_male_listen_cli import main as _cli_main

    raise SystemExit(_cli_main())
