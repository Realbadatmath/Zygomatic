# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.abel_voice`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.abel_voice` still reaches it.
"""

import argparse
import json

from zyg_workflows.abel_voice import narrate_video


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in abel_voice."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--narrate', help='video to narrate')
    ap.add_argument('--out', help='output video path')
    ap.add_argument('--engine', default='chatterbox')
    ap.add_argument('--device', default='cpu')
    a = ap.parse_args()
    if a.narrate and a.out:
        res = narrate_video(a.narrate, a.out, engine=a.engine, device=a.device, log_fn=print)
        # Compact, COMPLETE JSON on the last stdout line (the stack's _last_json_line
        # contract) — bulky qc sub-dicts summarized to per-gate ok maps, no slicing.
        out = {'ok': False}
        if res:
            nqc = res.get('narration_qc') or {}
            aqc = res.get('audio_qc') or {}
            clap_ok = (aqc.get('clap_bed') or {}).get('ok')
            out = {
                'ok': (
                    nqc.get('ok') is not False
                    and aqc.get('ok') is not False
                    and clap_ok is not False
                    and not res.get('over_runtime')
                ),
                'video': res.get('video'),
                'pause_map': res.get('pause_map'),
                'engine': res.get('engine'),
                'over_runtime': bool(res.get('over_runtime')),
                'attributions': res.get('attributions') or [],
                'narration_gates': {k: g.get('ok') for k, g in (nqc.get('gates') or {}).items() if isinstance(g, dict)},
                'master_gates': {k: g.get('ok') for k, g in (aqc.get('gates') or {}).items() if isinstance(g, dict)},
                'clap_bed_ok': clap_ok,
            }
        print(json.dumps(out, default=str))
        return 0 if out['ok'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
