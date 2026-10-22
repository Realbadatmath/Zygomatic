# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.build_teen_voices`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.build_teen_voices` still reaches it.
"""

from __future__ import annotations

import json
import os
import sys

from zyg_workflows.build_teen_voices import (
    DESIGN,
    DEST,
    MANIFEST,
    _KYUTAI_NOTE,
    _MAYA_NOTE,
    freeze,
    vs,
)


def main(design_json: str = ''):
    design = DESIGN
    if design_json:
        with open(design_json, encoding='utf-8') as f:
            design = json.load(f)
    if not design:
        raise SystemExit('no design rows — pass the tuning JSON')
    os.makedirs(DEST, exist_ok=True)
    rows = []
    for d in design:
        vid = d['id']
        out_wav = os.path.join(DEST, vid + '.wav')
        freeze(d['source'], d['k'], d['m'], out_wav)
        seed_m = vs.measure(out_wav)
        src = vs.voice(d['source'])
        note = _MAYA_NOTE if d['family'] == 'maya1' else _KYUTAI_NOTE
        row = {
            'name': vid,
            'display': d['display'],
            'role': d['role'],
            'wav': out_wav,
            'gender': 'm',
            'band': 'teen_male',
            'family': d['family'],
            'anchor': d['anchor'],
            'source_voice': d['source'],
            'source_display': src.get('name', ''),
            'source_wav': src.get('seed', ''),
            'seed_k': round(float(d['k']), 3),
            'seed_m': round(float(d['m']), 3),
            'seed_f0_hz': seed_m.get('f0_hz'),
            'seed_vtl_cm': seed_m.get('vtl_cm'),
            'render_f0_hz': d.get('render_f0'),
            'render_vtl_cm': d.get('render_vtl'),
            'render_verdict': d.get('verdict', ''),
            'measured_on': 'DEFAULT_LINES[0] (Second Ledger cold open)',
            'note': note,
        }
        # Wear candidates carry WHY they were chosen. The age figures say where a
        # voice sits; they say nothing about whether it is clean, and for the
        # worn bench that is the whole selection criterion — so it is recorded
        # next to the numbers it was picked on rather than left in a scratch file.
        if d.get('wear') is not None:
            row['wear_score'] = round(float(d['wear']), 2)
            row['source_texture'] = d.get('src_texture') or {}
            row['render_texture'] = d.get('render_texture') or {}
        rows.append(row)
        with open(os.path.splitext(out_wav)[0] + '.json', 'w', encoding='utf-8') as f:
            json.dump(
                {
                    'candidate': d['display'],
                    'age_class': 'teen_male',
                    'anchor': d['anchor'],
                    'built': '2026-08-12 by build_teen_voices.py',
                    'source_voice': d['source'],
                    'source_wav': src.get('seed', ''),
                    'source_family': d['family'],
                    'transform': {
                        'k': row['seed_k'],
                        'm': row['seed_m'],
                        'ffmpeg': (
                            f'asetrate/atempo k={row["seed_k"]:.3f} + rubberband '
                            f'pitch={row["seed_m"]:.3f} formant=preserved'
                        ),
                        'note': (
                            'm<1 lowers pitch and GROWS the tract on this build; '
                            'm>1 drags formants up and collapses it. k sets the '
                            'body. Tuned by closed loop against measured renders, '
                            'not by prediction.'
                        ),
                    },
                    'seed_measured': {'f0_median_hz': seed_m.get('f0_hz'), 'vtl_cm': seed_m.get('vtl_cm')},
                    'rendered_measured': {
                        'f0_median_hz': d.get('render_f0'),
                        'vtl_cm': d.get('render_vtl'),
                        'verdict': d.get('verdict', ''),
                        'line': 'Second Ledger cold open',
                        'engine': 'chatterbox, defaults, seed 1672',
                    },
                    'tuning_history': d.get('history', []),
                    'wear': (
                        {
                            'score': d['wear'],
                            'source_texture': d.get('src_texture') or {},
                            'render_texture': d.get('render_texture') or {},
                            'note': (
                                'Wear is inherited from the DONOR, not added '
                                'afterwards: EQ cannot produce jitter or an '
                                'irregular glottis. Measured over 93 cached '
                                'renders, source-vs-render composite wear '
                                'correlates r=0.750, so a weathered donor '
                                'stays weathered through the cloner.'
                            ),
                        }
                        if d.get('wear') is not None
                        else None
                    ),
                    'wholly_synthetic': d['family'] == 'maya1',
                    'note': note,
                },
                f,
                indent=1,
                ensure_ascii=False,
            )
        print(
            f'{vid:8s} {d["source"]:20s} k={row["seed_k"]:.3f} m={row["seed_m"]:.3f} '
            f'seed {seed_m.get("f0_hz")} Hz / {seed_m.get("vtl_cm")} cm  '
            f'render {d.get("render_f0")} / {d.get("render_vtl")}',
            flush=True,
        )

    # MERGE, never replace. Building a second batch used to rewrite the manifest
    # from the design alone, which silently unregistered every voice from the
    # first — the wavs stay on disk, so nothing looks broken until an operator
    # goes to play a voice that has been picked already and finds it gone. Rows
    # are keyed by name: rebuilding a candidate updates it in place, and one that
    # is not in this design is carried through untouched.
    prior = []
    try:
        with open(MANIFEST, encoding='utf-8') as f:
            prior = (json.load(f) or {}).get('voices') or []
    except (OSError, ValueError):
        prior = []
    fresh = {r['name'] for r in rows}
    kept = [r for r in prior if r.get('name') not in fresh and os.path.isfile(r.get('wav', ''))]
    rows = sorted(kept + rows, key=lambda r: r['name'])
    if kept:
        print(f'carried forward {len(kept)} voice(s) already in the manifest')

    with open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(
            {
                'purpose': 'candidate teenage-male voices for audition in the Voices tab',
                'built': '2026-08-12',
                'measured_on': 'DEFAULT_LINES[0], chatterbox at defaults, eng_seed 1672',
                'caveat': (
                    'voice_qc cannot separate a teenage male from an adult '
                    'female on F0+VTL alone — the bands genuinely overlap. '
                    'These numbers prove the voice is not a child and not an '
                    'adult man; only the ear settles the rest.'
                ),
                'voices': rows,
            },
            f,
            indent=1,
            ensure_ascii=False,
        )
    print(f'\nmanifest: {MANIFEST}  ({len(rows)} voices)')


def cli_main() -> int:
    """The former `if __name__` body of build_teen_voices."""
    main(sys.argv[1] if len(sys.argv) > 1 else '')
    return 0


if __name__ == '__main__':
    sys.exit(cli_main())
