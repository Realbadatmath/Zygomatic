# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.calibrate_sung_pitch`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.tools.calibrate_sung_pitch` still reaches
it.
"""

import argparse
import datetime as _dt
import json
import os
import shutil
import sys
import tempfile

import numpy as np
from zyg_workflows import sung_pitch as SP
from zyg_workflows.tools.calibrate_sung_pitch import (
    AUDIO_DIR,
    BAND,
    CENT_TOL,
    F0_DIR,
    FMAX,
    FMIN,
    OUT_DEFAULT,
    PRAAT_SCRIPT,
    VOCADITO,
    _agg,
    _agg_median,
    _versions,
    demucs_vocals,
    estimate_frames,
    load_reference,
    make_mix,
    median_err_cents,
    praat_medians,
    score,
)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--praat-n', type=int, default=10)
    ap.add_argument('--device', default='cuda', help='demucs device')
    ap.add_argument('--skip-mixed', action='store_true')
    ap.add_argument('--out', default=OUT_DEFAULT)
    a = ap.parse_args(argv)

    stems = sorted(
        (f[:-4] for f in os.listdir(AUDIO_DIR) if f.endswith('.wav')), key=lambda s: int(s.rsplit('_', 1)[1])
    )
    if a.limit:
        stems = stems[: a.limit]
    if not os.path.exists(BAND):
        raise SystemExit(f'band missing: {BAND}')

    tmp = tempfile.mkdtemp(prefix='sungcal_')
    rows = []
    try:
        for i, stem in enumerate(stems, 1):
            wav = os.path.join(AUDIO_DIR, f'{stem}.wav')
            t_ref, f_ref = load_reference(os.path.join(F0_DIR, f'{stem}_f0.csv'))
            row = {'file': stem, 'seconds': None}

            m = SP.measure_stem(wav, fmin=FMIN, fmax=FMAX)
            t_e, f_e, v_e = estimate_frames(wav)
            row['seconds'] = m.get('seconds')
            row['clean'] = score(t_e, f_e, v_e, t_ref, f_ref)
            err, ref_med = median_err_cents(m.get('f0_median_hz'), f_ref)
            row['clean'].update(
                {
                    'measure_stem_ok': bool(m.get('ok')),
                    'f0_median_hz': m.get('f0_median_hz'),
                    'ref_median_hz': ref_med,
                    'median_err_cents': err,
                    'swiftf0_median_hz': m.get('swiftf0_median_hz'),
                    'agreement_cents': m.get('agreement_cents'),
                }
            )

            if not a.skip_mixed:
                mix = os.path.join(tmp, f'{stem}_mix.wav')
                sep = os.path.join(tmp, f'{stem}_sep')
                minfo = make_mix(wav, BAND, mix)
                d = demucs_vocals(mix, sep, a.device)
                voc = d['vocals']
                mm = SP.measure_stem(voc, fmin=FMIN, fmax=FMAX)
                t_m, f_m, v_m = estimate_frames(voc)
                row['mixed'] = score(t_m, f_m, v_m, t_ref, f_ref)
                merr, _ = median_err_cents(mm.get('f0_median_hz'), f_ref)
                row['mixed'].update(
                    {
                        'measure_stem_ok': bool(mm.get('ok')),
                        'f0_median_hz': mm.get('f0_median_hz'),
                        'median_err_cents': merr,
                        'demucs_device': d.get('device'),
                        'demucs_ratio_db': d.get('ratio_db'),
                        'mix': minfo,
                    }
                )
                shutil.rmtree(sep, ignore_errors=True)
                os.remove(mix)

            rows.append(row)
            c = row['clean']
            msg = f'[{i}/{len(stems)}] {stem} clean rpa={c["rpa"]} rca={c["rca"]} err={c["median_err_cents"]}c'
            if 'mixed' in row:
                mx = row['mixed']
                msg += f' | mixed rpa={mx["rpa"]} rca={mx["rca"]} err={mx["median_err_cents"]}c'
            print(msg, flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # old Praat meter on the first N clean excerpts
    praat = []
    pn = min(a.praat_n, len(stems))
    if pn:
        paths = [os.path.join(AUDIO_DIR, f'{s}.wav') for s in stems[:pn]]
        pr = praat_medians(paths)
        for s in stems[:pn]:
            r = pr.get(f'{s}.wav', {})
            hz = r.get('f0_median_hz')
            ref = next((x['clean']['ref_median_hz'] for x in rows if x['file'] == s), None)
            e = round(1200.0 * float(np.log2(hz / ref)), 2) if hz and ref else None
            praat.append(
                {
                    'file': s,
                    'praat_f0_median_hz': hz,
                    'ref_median_hz': ref,
                    'median_err_cents': e,
                    'error': r.get('error'),
                }
            )
            for x in rows:
                if x['file'] == s:
                    x['praat'] = praat[-1]

    doc = {
        'date': _dt.datetime.now().isoformat(timespec='seconds'),
        'dataset': 'vocadito (Zenodo 5578807, CC BY 4.0)',
        'dataset_dir': VOCADITO,
        'band': BAND,
        'meter': 'sung_pitch.measure_stem (RMVPE) — unmodified',
        'old_meter': PRAAT_SCRIPT,
        'cent_tolerance': CENT_TOL,
        'fmin_hz': FMIN,
        'fmax_hz': FMAX,
        'conf_min': SP.CONF_MIN,
        'mix_ratio_db': 0.0,
        'n_files': len(rows),
        'rpa_clean': _agg([r['clean']['rpa'] for r in rows]),
        'rca_clean': _agg([r['clean']['rca'] for r in rows]),
        'rpa_mixed': _agg([r['mixed']['rpa'] for r in rows if 'mixed' in r]),
        'rca_mixed': _agg([r['mixed']['rca'] for r in rows if 'mixed' in r]),
        'median_err_cents_clean': _agg_median([r['clean']['median_err_cents'] for r in rows]),
        'median_err_cents_mixed': _agg_median([r['mixed']['median_err_cents'] for r in rows if 'mixed' in r]),
        'abs_median_err_cents_clean': _agg_median(
            [abs(r['clean']['median_err_cents']) for r in rows if r['clean']['median_err_cents'] is not None]
        ),
        'abs_median_err_cents_mixed': _agg_median(
            [
                abs(r['mixed']['median_err_cents'])
                for r in rows
                if 'mixed' in r and r['mixed']['median_err_cents'] is not None
            ]
        ),
        'praat_median_err_cents': _agg_median([p['median_err_cents'] for p in praat]),
        'praat_abs_median_err_cents': _agg_median(
            [abs(p['median_err_cents']) for p in praat if p['median_err_cents'] is not None]
        ),
        'praat_n': len(praat),
        'versions': _versions(),
        'files': rows,
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w') as fh:
        json.dump(doc, fh, indent=2)

    print(
        '\nAGGREGATE '
        + json.dumps(
            {
                k: doc[k]
                for k in (
                    'n_files',
                    'rpa_clean',
                    'rca_clean',
                    'median_err_cents_clean',
                    'abs_median_err_cents_clean',
                    'rpa_mixed',
                    'rca_mixed',
                    'median_err_cents_mixed',
                    'abs_median_err_cents_mixed',
                    'praat_median_err_cents',
                    'praat_abs_median_err_cents',
                    'praat_n',
                )
            }
        )
    )
    print('wrote', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
