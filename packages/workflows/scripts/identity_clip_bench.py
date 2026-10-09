#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""identity_clip_bench.py — bench the per-frame clip identity instrument BEFORE
trusting it (2026-09-02, S03).

A number with no null model is a rumour. `identity_bank.check_clip` used to carry
floors calibrated on ONE render (scene20_v7) and had zero callers, so nothing had
ever told us what "doing nothing" scores. This bench runs four arms per character:

  ceiling  — the character's canon still repeated 341 times as an mp4. The top of
             the achievable scale AND the cost of an h264 round trip. (The canon
             portrait is itself in the bank, so this is an IN-BANK ceiling; it is
             what "perfect" looks like, not an independent sample.)
  true     — the newest real finished clip in which that character appears.
  impostor — a different character in the same arcane style. Two flavours:
             CROSS-CLIP (the other character's own scene) and, harder,
             SAME-CLIP (a two-hander: the other character's column of the very
             same frames — same style, same grade, same framing, same render).
  shuffle  — the exact frame SET of `true` in a random order. A per-frame metric
             is order-blind by construction, so this arm must land on top of
             `true`; if it does not, the instrument is reading the decoder, not
             the face. It is the null that says the summary statistics carry no
             temporal information.

Usage:
    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" \
        scripts/identity_clip_bench.py [--stride 24] [--quick]

Writes output/identity_bench/{bench.json,bench.md,series_<arm>.png}.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)

from zyg_workflows import identity_bank as ib  # noqa: E402

OUT = os.path.join(_HERE, 'output', 'identity_bench')

ABEL = 'c3345deb5bde'
CORNELIS = '0015c8a3f2e3'
STYLE = 'arcane'
NAMES = {ABEL: 'Abel', CORNELIS: 'Cornelis'}

# Real finished clips, found 2026-09-02 by mtime under output/ and confirmed by each
# scene's own scene_state.json stills (cabin_abel / cabin_cornelis).
CLIP_ABEL = os.path.join(
    _HERE,
    'output/storyteller/scene_second_ledger_intro_teen08_settled_shores_v27_leanfix'
    '/second_ledger_intro_teen08_settled_shores_v27_leanfix.mp4',
)
CLIP_CORNELIS = os.path.join(_HERE, 'output/storyteller/scene_cornelis_day1/cornelis_day1.mp4')
# One finished two-hander with BOTH of them in frame: the hardest impostor there is.
CLIP_BOTH = os.path.join(_HERE, 'output/multichar_seated/FINAL_20s_pipe_smoke_scene.mp4')
ROI_LEFT = (0.0, 0.0, 0.5, 1.0)  # Cornelis' column
ROI_RIGHT = (0.5, 0.0, 1.0, 1.0)  # Abel's column


def _sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def make_ceiling(char_id, dst, n_frames=341, fps=24):
    """The canon still, repeated n_frames times, through the same h264 encoder the
    real clips came out of."""
    from zyg_workflows import canon_service as CS

    still = CS.canon_portrait(char_id)
    if not still or not os.path.isfile(still):
        return None, None
    _sh(
        [
            'ffmpeg',
            '-v',
            'error',
            '-y',
            '-loop',
            '1',
            '-i',
            still,
            '-frames:v',
            str(n_frames),
            '-r',
            str(fps),
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            '-crf',
            '17',
            dst,
        ]
    )
    return dst, still


def make_shuffle(clip, dst, stride, max_frames, seed=1729, fps=24):
    """The SAMPLED frames of `clip`, same set, random order, re-encoded.

    Shuffling the whole 1400-frame clip would cost 2 GB of PNG for no extra
    information: the arm only has to contain exactly the frames the true arm
    scores, in a different order.
    """
    import tempfile

    td = tempfile.mkdtemp(prefix='idshuf_')
    try:
        frames = ib._explode(clip, os.path.join(td, 'in'), stride, max_frames)
        if len(frames) < 4:
            return None, 0
        order = list(frames)
        random.Random(seed).shuffle(order)
        sd = os.path.join(td, 'sh')
        os.makedirs(sd, exist_ok=True)
        for i, f in enumerate(order):
            os.link(f, os.path.join(sd, 'f_%06d.png' % i))
        _sh(
            [
                'ffmpeg',
                '-v',
                'error',
                '-y',
                '-framerate',
                str(fps),
                '-i',
                os.path.join(sd, 'f_%06d.png'),
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-crf',
                '17',
                dst,
            ]
        )
        return dst, len(order)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def summarise(name, char_id, r):
    led = r.get('ledger') or {}
    return {
        'arm': name,
        'char': NAMES.get(char_id, char_id),
        'char_id': char_id,
        'clip': os.path.basename(str(r.get('clip', ''))),
        'sampled': r.get('sampled') or r.get('measured'),
        'found': r.get('found') if r.get('found') is not None else r.get('measured'),
        'not_found': led.get('not_found'),
        'not_detectable': led.get('not_detectable'),
        'unmeasurable': led.get('unmeasurable'),
        'cos_min': r.get('cosine_min'),
        'cos_mean': r.get('cosine'),
        'cos_p10': r.get('cosine_p10'),
        'cos_med': r.get('cosine_median'),
        'cos_max': r.get('cosine_max'),
        'spread': r.get('spread'),
        'z_min': r.get('z'),
        'z_med': r.get('z_median'),
        'pass_frac': r.get('pass_frac'),
        'ok': r.get('ok'),
        'reason': r.get('reason'),
        'backend': r.get('backend'),
        'mode': r.get('mode'),
    }


def plot_series(r, dst, title):
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    s = r.get('series') or []
    ts = [x['t'] for x in s]
    cos = [x.get('cosine') for x in s]
    fig, ax = plt.subplots(figsize=(13, 4.2), dpi=110)
    ax.plot(
        [t for t, c in zip(ts, cos) if c is not None],
        [c for c in cos if c is not None],
        '.-',
        lw=1.0,
        ms=4,
        color='#1f77b4',
        label='cosine (found)',
    )
    ax.axhline(r.get('floor', 0.35), color='#d62728', ls='--', lw=1.2, label='floor %.2f' % r.get('floor', 0.35))
    colours = {'not_found': '#bbbbbb', 'not_detectable': '#ff9f40', 'unmeasurable': '#9467bd'}
    seen = set()
    for x in s:
        st = x.get('state')
        if st in colours:
            ax.axvspan(
                x['t'],
                x['t'] + (ts[1] - ts[0] if len(ts) > 1 else 0.5),
                color=colours[st],
                alpha=0.35,
                lw=0,
                label=None if st in seen else st,
            )
            seen.add(st)
    ax.set_xlabel('clip time (s)')
    ax.set_ylabel('cosine vs bank centroid')
    ax.set_ylim(-0.1, 1.0)
    ax.set_title(title, fontsize=10)
    ax.legend(loc='lower right', fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(dst)
    plt.close(fig)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stride', type=int, default=24, help='sample every Nth frame (24 = one per second at 24fps)')
    ap.add_argument('--max-frames', type=int, default=120)
    ap.add_argument('--quick', action='store_true', help='ceiling + one true arm only')
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    rows, raw, notes = [], {}, []

    def run(name, char_id, clip, roi=None, stride=None, mode=None):
        if not clip or not os.path.isfile(clip):
            notes.append(f'{name}: clip missing ({clip})')
            return None
        st = stride or a.stride
        print(f'  [{name}] {NAMES.get(char_id, char_id)} vs {os.path.basename(clip)} stride={st} roi={roi}', flush=True)
        r = ib.check_clip(
            char_id,
            STYLE,
            clip,
            roi=roi,
            stride=st,
            max_frames=a.max_frames,
            mode=mode,
            record=False,
            tag=f'bench:{name}',
        )
        raw[name] = r
        rows.append(summarise(name, char_id, r))
        return r

    print('bench: building ceiling clips')
    for cid in (ABEL, CORNELIS):
        dst = os.path.join(OUT, f'ceiling_{cid}.mp4')
        p, still = make_ceiling(cid, dst)
        if p:
            notes.append(f'ceiling_{NAMES[cid]}: {os.path.basename(still)} x341 @24fps')
            run(f'ceiling/{NAMES[cid]}', cid, p)

    print('bench: true arms')
    r_abel = run('true/Abel', ABEL, CLIP_ABEL)
    r_corn = run('true/Cornelis', CORNELIS, CLIP_CORNELIS)

    if not a.quick:
        print('bench: cross-clip impostor arms (different scene, same style)')
        run('impostor-xclip/Abel-bank-on-Cornelis-clip', ABEL, CLIP_CORNELIS)
        run('impostor-xclip/Cornelis-bank-on-Abel-clip', CORNELIS, CLIP_ABEL)

        print('bench: same-clip impostor arms (one two-hander, two columns)')
        run('true-sameclip/Cornelis-left', CORNELIS, CLIP_BOTH, roi=ROI_LEFT, stride=8)
        run('true-sameclip/Abel-right', ABEL, CLIP_BOTH, roi=ROI_RIGHT, stride=8)
        run('impostor-sameclip/Cornelis-bank-on-Abel-column', CORNELIS, CLIP_BOTH, roi=ROI_RIGHT, stride=8)
        run('impostor-sameclip/Abel-bank-on-Cornelis-column', ABEL, CLIP_BOTH, roi=ROI_LEFT, stride=8)

        print('bench: shuffle arms (same frame set, random order)')
        for cid, clip in ((ABEL, CLIP_ABEL), (CORNELIS, CLIP_CORNELIS)):
            dst = os.path.join(OUT, f'shuffle_{cid}.mp4')
            p, n = make_shuffle(clip, dst, a.stride, a.max_frames)
            if p:
                notes.append(f'shuffle_{NAMES[cid]}: {n} frames of {os.path.basename(clip)}, seed 1729')
                run(f'shuffle/{NAMES[cid]}', cid, p, stride=1)

        print('bench: legacy arm (5 fixed times, static box) for comparison')
        run('legacy/Abel-static-box', ABEL, CLIP_ABEL, roi=(0.45, 0.0, 1.0, 0.6), mode='legacy')

    plots = []
    if r_abel and (r_abel.get('series')):
        plots.append(
            plot_series(
                r_abel,
                os.path.join(OUT, 'series_true_abel.png'),
                'Abel identity per frame — %s (stride %d, facenet vs bank centroid)'
                % (os.path.basename(CLIP_ABEL), a.stride),
            )
        )
    if r_corn and (r_corn.get('series')):
        plots.append(
            plot_series(
                r_corn,
                os.path.join(OUT, 'series_true_cornelis.png'),
                'Cornelis identity per frame — %s (stride %d, facenet vs bank centroid)'
                % (os.path.basename(CLIP_CORNELIS), a.stride),
            )
        )

    doc = {
        'when': time.strftime('%Y-%m-%d %H:%M:%S'),
        'elapsed_s': round(time.time() - t0, 1),
        'stride': a.stride,
        'max_frames': a.max_frames,
        'floors_at_bench_time': dict(ib._FLOORS),
        'pass_frac_at_bench_time': ib.CLIP_PASS_FRAC,
        'clips': {'abel': CLIP_ABEL, 'cornelis': CLIP_CORNELIS, 'both': CLIP_BOTH},
        'notes': notes,
        'plots': plots,
        'rows': rows,
        'raw': {k: {kk: vv for kk, vv in v.items() if kk != 'series'} for k, v in raw.items()},
    }
    with open(os.path.join(OUT, 'bench.json'), 'w') as fh:
        json.dump(doc, fh, indent=2, default=str)
    with open(os.path.join(OUT, 'bench_series.json'), 'w') as fh:
        json.dump({k: v.get('series') for k, v in raw.items()}, fh, indent=1, default=str)

    hdr = [
        'arm',
        'char',
        'found',
        'nf',
        'nd',
        'um',
        'cos_min',
        'cos_p10',
        'cos_med',
        'cos_mean',
        'cos_max',
        'spread',
        'pass_frac',
        'ok',
    ]
    lines = ['| ' + ' | '.join(hdr) + ' |', '|' + '---|' * len(hdr)]
    for r in rows:
        lines.append(
            '| '
            + ' | '.join(
                str(r.get(k, ''))
                for k in [
                    'arm',
                    'char',
                    'found',
                    'not_found',
                    'not_detectable',
                    'unmeasurable',
                    'cos_min',
                    'cos_p10',
                    'cos_med',
                    'cos_mean',
                    'cos_max',
                    'spread',
                    'pass_frac',
                    'ok',
                ]
            )
            + ' |'
        )
    md = (
        '# identity clip bench %s\n\nstride %d, max_frames %d, elapsed %.0fs\n\n'
        % (doc['when'], a.stride, a.max_frames, doc['elapsed_s'])
    ) + '\n'.join(lines)
    md += '\n\n## notes\n' + '\n'.join('- ' + n for n in notes) + '\n'
    with open(os.path.join(OUT, 'bench.md'), 'w') as fh:
        fh.write(md)
    print('\n' + md)
    print('\n->', os.path.join(OUT, 'bench.json'))


if __name__ == '__main__':
    main()
