# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.build_agony_bed`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.build_agony_bed` still reaches it.
"""

from __future__ import annotations

import os
import sys

from zyg_workflows.build_agony_bed import (
    DUR_S,
    LICENCE,
    _HERE,
    _entries,
    _out_name,
    build,
    check,
)


def main():
    dur_s = DUR_S
    if '--seconds' in sys.argv:
        i = sys.argv.index('--seconds') + 1
        try:
            dur_s = float(sys.argv[i])
        except (IndexError, ValueError) as _exc:
            raise SystemExit(
                'usage: build_agony_bed.py [--seconds N] [--check] — --seconds needs a number (e.g. 16)'
            ) from _exc
        if not 1.0 <= dur_s <= 120.0:
            raise SystemExit(f'--seconds {dur_s:g}: give a bed length between 1 and 120 s')
    name = _out_name(dur_s)
    out = os.path.join(_HERE, 'data', 'runtime', '_agony_work', name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if '--check' not in sys.argv:
        if not build(out, dur_s=dur_s):
            raise SystemExit('build failed')
    r = check(out)
    if '--check' in sys.argv:
        return
    # A bed that does not read as a crowd in agony is not the asset that was
    # asked for, and shipping it quietly would hide that behind "it's soft".
    if (r.get('positive_prob') or 0) < 0.60:
        raise SystemExit(
            f'REFUSING to register: CLAP positive_prob '
            f'{r.get("positive_prob")} — this does not read as '
            f'people screaming in agony.'
        )
    from zyg_workflows import ambience_ingest

    # Rebuilding must REPLACE, not accumulate: register_audio_asset uniquifies
    # to crowd_agony_2.wav and the scene would keep playing the old one.
    from zyg_workflows import asset_library_service as AL

    prior = os.path.join(AL._audio_dir('soundtracks'), name)
    if os.path.isfile(prior):
        os.remove(prior)
    built = getattr(build, 'last', None) or {
        'layers': len(_entries(dur_s)[0]),
        'waves': _entries(dur_s)[1],
        'seconds': dur_s,
    }
    licence = dict(LICENCE)
    licence['notes'] = LICENCE['notes'].format(**built)
    rec = ambience_ingest.register_audio_asset(
        'soundtracks', out, licence, name=name[: -len('.wav')], convert=True, log_fn=print
    )
    print('registered:', (rec or {}).get('id'))


if __name__ == '__main__':
    main()
