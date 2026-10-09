#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Measure the score-render CLAP gate on the cinematic renders already on disk.

Why this exists: three cinematic styles (suspense, mystery, triumph) fail or sit
on `gate_audio()`'s CLAP check of the SAMPLER render (melody.mp3) — the negative
'pop song with vocals' outscores their captions on sparse dark cues. This tool
re-measures the existing renders so a caption change can be chosen on numbers
rather than on taste, and so a candidate set can be shown NOT to be so generic
that it would also describe a cheerful or a chase cue.

Phases (all read-only; nothing here writes into the pipeline):
  baseline  every output/cinematic/*/melody.mp3 against the style's CURRENT
            clap_pos + the current cinematic negatives.
  cands     the candidate caption sets below, each scored on the style's OWN
            renders (every seed on disk) and on the two most-different other
            styles' renders (cheerful, chase).
  regress   every render against its own CURRENT captions but with the chosen
            negatives variant — the null for changing a family-wide negative.

Usage:
  ../.venv/bin/python tools/measure_cinematic_clap.py --phase baseline
  ../.venv/bin/python tools/measure_cinematic_clap.py --phase cands --neg current
  ../.venv/bin/python tools/measure_cinematic_clap.py --phase cands --neg variant \
      --sets suspense:S1,mystery:M1,triumph:T1
  ../.venv/bin/python tools/measure_cinematic_clap.py --phase regress --neg variant
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import audio_qc  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'cinematic')

# The candidate positive sets. Every set keeps THREE captions so the softmax
# baseline (n_pos/(n_pos+n_neg) = 3/8) and therefore the effective threshold
# 0.525 stay exactly what the gate uses today — a 4th caption would move the
# bar and make the comparison meaningless.
CANDIDATES = {
    'suspense': {
        'S0': None,  # filled with the current set
        'S1': [
            'dark suspenseful orchestral film score',
            'ominous slow instrumental music with tremolo strings',
            'tense cinematic underscore without vocals',
        ],
        'S2': [
            'dark orchestral suspense cue with tremolo strings and low clarinet',
            'ominous instrumental film music with no singing',
            'tense sparse orchestral underscore',
        ],
        'S3': [
            'solo clarinet and tremolo strings with harp ostinato',
            'sparse dark instrumental chamber music',
            'suspenseful classical instrumental cue',
        ],
        # S4/S5 are built FROM the probe ranking rather than guessed: on this
        # render 'quiet' beats 'dark'/'tense'/'ominous' by two orders of
        # magnitude, because the cue is a -20 dBFS sparse texture.
        'S4': ['a quiet orchestral piece', 'a slow quiet string piece', 'a quiet film score'],
        'S5': ['a quiet orchestral piece', 'suspense music from a thriller film', 'a slow orchestral film score'],
        'S6': ['a quiet orchestral piece', 'a slow quiet string piece', 'suspense music from a thriller film'],
    },
    'mystery': {
        'M0': None,
        'M1': [
            'mysterious orchestral film score',
            'slow eerie instrumental music with oboe and harpsichord',
            'sparse curious cinematic underscore',
        ],
        'M2': [
            'oboe and harpsichord chamber music, instrumental',
            'eerie sparse instrumental cue with pizzicato bass and vibraphone',
            'curious mysterious classical instrumental',
        ],
        'M3': [
            'a baroque harpsichord and oboe instrumental',
            'sparse eerie orchestral underscore with no singing',
            'mysterious instrumental chamber music',
        ],
    },
    'triumph': {
        'T0': None,
        'T1': [
            'triumphant orchestral fanfare with brass and organ',
            'grand victorious film score',
            'majestic instrumental finale',
        ],
        'T2': [
            'brass fanfare with pipe organ and tuba, instrumental',
            'grand majestic orchestral finale',
            'victorious cinematic brass music',
        ],
    },
}

# The negatives. 'variant' replaces the genre word ('pop song with vocals') with
# one that names the SINGING, which is the thing an instrumental cue must not
# have — the hypothesis being that CLAP matches sustained tremolo strings and
# harpsichord to the genre caption, not to an actual voice.
NEG_CURRENT = T.clap_negatives('cinematic')
NEG_VARIANT = [n for n in NEG_CURRENT if n != 'pop song with vocals'] + ['pop song with a singer singing lyrics']

CROSS = ('cheerful', 'chase')  # the two most-different cues on disk

# Single captions to probe one at a time (each scored as the ONLY positive
# against the family negatives), so a candidate set can be BUILT from the
# captions this audio actually answers to instead of guessed as a triple.
PROBE_POOL = [
    'a suspenseful film score',
    'suspenseful orchestral film score',
    'a dark orchestral film score',
    'tense dark orchestral music',
    'mysterious orchestral film score',
    'mysterious instrumental score',
    'a slow orchestral film score',
    'slow eerie instrumental music with oboe and harpsichord',
    'slow ominous instrumental music with tremolo strings',
    'dark suspenseful orchestral film score',
    'tense cinematic underscore without vocals',
    'sparse curious cinematic underscore',
    'a quiet orchestral piece',
    'a gentle orchestral piece',
    'a sad orchestral piece',
    'slow mournful film music',
    'emotional instrumental score',
    'a heroic orchestral theme',
    'triumphant brass film music',
    'grand instrumental score',
    'a classical instrumental piece',
    'chamber music with clarinet and strings',
    'orchestral film music',
    'instrumental film score',
    'a slow atmospheric instrumental',
    'suspense music from a thriller film',
    'creepy background music from a film',
    'an eerie orchestral cue',
    # The suspense render answers to 'quiet' far better than to 'dark' or
    # 'tense' (see the probe), so the pool carries a quiet-first arm.
    'a quiet suspenseful orchestral piece',
    'quiet slow orchestral music',
    'a soft orchestral film cue',
    'sparse quiet instrumental music with strings',
    'a slow quiet string piece',
    'quiet tense orchestral music',
    'quiet dark orchestral music',
    'a quiet instrumental piece',
    'a quiet film score',
]


def renders():
    """{style: [(job_id, melody.mp3 path), ...]} for everything on disk."""
    out = {}
    if not os.path.isdir(OUT_ROOT):
        return out
    for jid in sorted(os.listdir(OUT_ROOT)):
        d = os.path.join(OUT_ROOT, jid)
        mp3 = os.path.join(d, 'melody.mp3')
        man = os.path.join(d, 'manifest.json')
        if not (os.path.isfile(mp3) and os.path.isfile(man)):
            continue
        try:
            with open(man) as fh:
                m = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('manifest unreadable, render skipped: %s', _exc)
            continue
        style = m.get('style')
        if not style:
            continue
        out.setdefault(style, []).append((jid, mp3))
    return out


REPEATS = 1  # set by --repeats; see score() for why more than one is needed


def score(path, positives, negatives):
    """qc_clap REPEATS times; returns the run set plus min/mean/max.

    Repeats are not paranoia: laion/clap-htsat-fused's feature extractor fuses
    RANDOMLY truncated chunks for audio longer than 10 s, so the same file
    against the same captions scores differently every call (triumph's render
    measured 0.4697 / 0.6858 / 0.7954 / 0.8129 on four calls). A single
    measurement therefore cannot tell a caption change from the noise, and a
    style whose mean sits near 0.525 is a coin toss in production.
    """
    runs = []
    for _ in range(REPEATS):
        r = audio_qc.qc_clap(path, positives, negatives, threshold=0.45)
        if r.get('ok') is None:
            return r
        scores = r.get('scores') or {}
        negs = {k: v for k, v in scores.items() if k in negatives}
        r['top_negative'] = max(negs.items(), key=lambda kv: kv[1]) if negs else ('-', 0.0)
        runs.append(r)
    out = dict(runs[-1])
    probs = [r['positive_prob'] for r in runs]
    out['runs'] = probs
    out['p_min'], out['p_max'] = min(probs), max(probs)
    out['p_mean'] = sum(probs) / len(probs)
    out['n_pass'] = sum(1 for r in runs if r['ok'])
    return out


def line(tag, jid, r):
    if r.get('ok') is None:
        return f'  {tag:24s} {jid}  UNSCORED ({r.get("reason")})'
    tn, tv = r['top_negative']
    return (
        f'  {tag:24s} {jid}  min={r["p_min"]:.4f} mean={r["p_mean"]:.4f} '
        f'max={r["p_max"]:.4f} thr={r["effective_threshold"]:.3f} '
        f'pass={r["n_pass"]}/{len(r["runs"])}  '
        f'lastnegtop={tn!r} {tv:.4f}'
    )


def phase_baseline(reg, negatives, neg_label):
    _zyg_log.info(f'=== BASELINE: current captions x negatives[{neg_label}] ===')
    _zyg_log.info(f'    negatives = {negatives}')
    for style in sorted(reg):
        pos = T.clap_captions(style, 'cinematic')
        _zyg_log.info(f'{style}  pos={pos}')
        for jid, path in reg[style]:
            _zyg_log.info(line('current', jid, score(path, pos, negatives)))


def phase_cands(reg, negatives, neg_label, only):
    _zyg_log.info(f'=== CANDIDATES x negatives[{neg_label}] ===')
    _zyg_log.info(f'    negatives = {negatives}')
    for style in ('suspense', 'mystery', 'triumph'):
        sets = dict(CANDIDATES[style])
        cur = T.clap_captions(style, 'cinematic')
        for k in list(sets):
            if sets[k] is None:
                sets[k] = cur
        for key in sorted(sets):
            if only and f'{style}:{key}' not in only:
                continue
            pos = sets[key]
            _zyg_log.info(f'{style} / {key}  pos={pos}')
            own = reg.get(style) or []
            for jid, path in own:
                _zyg_log.info(line(f'own[{style}]', jid, score(path, pos, negatives)))
            for other in CROSS:
                for jid, path in reg.get(other) or []:
                    _zyg_log.info(line(f'cross[{other}]', jid, score(path, pos, negatives)))


def phase_regress(reg, negatives, neg_label):
    _zyg_log.info(f"=== REGRESSION: every style's CURRENT captions x negatives[{neg_label}] ===")
    _zyg_log.info(f'    negatives = {negatives}')
    bad = 0
    for style in sorted(reg):
        pos = T.clap_captions(style, 'cinematic')
        for jid, path in reg[style]:
            r = score(path, pos, negatives)
            if r.get('ok') is not True:
                bad += 1
            _zyg_log.info(line(style, jid, r))
    _zyg_log.info(f'{bad} render(s) not passing under negatives[{neg_label}]')


def phase_probe(reg, negatives, neg_label, styles):
    """Rank PROBE_POOL one caption at a time on each named style's renders."""
    _zyg_log.info(f'=== PROBE: one caption at a time x negatives[{neg_label}] ===')
    for style in styles:
        for jid, path in (reg.get(style) or [])[:1]:  # seeds are duplicates
            rows = []
            for cap in PROBE_POOL:
                r = score(path, [cap], negatives)
                if r.get('ok') is None:
                    continue
                rows.append((r['p_mean'], r['p_min'], cap))
            rows.sort(reverse=True)
            _zyg_log.info(f'{style} {jid}:')
            for mean, mn, cap in rows:
                _zyg_log.info(f'  {mean:.4f} (min {mn:.4f})  {cap!r}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', choices=('baseline', 'cands', 'regress', 'probe'), required=True)
    ap.add_argument('--neg', choices=('current', 'variant'), default='current')
    ap.add_argument('--sets', default='', help="comma list like 'suspense:S1,mystery:M2' (cands only)")
    ap.add_argument('--repeats', type=int, default=3, help='qc_clap calls per (file, caption set) — CLAP is noisy')
    a = ap.parse_args()

    global REPEATS
    REPEATS = max(1, a.repeats)
    negatives = NEG_CURRENT if a.neg == 'current' else NEG_VARIANT
    reg = renders()
    if not reg:
        print(f'no renders under {OUT_ROOT}')
        return 1
    only = {s.strip() for s in a.sets.split(',') if s.strip()}

    if a.phase == 'baseline':
        phase_baseline(reg, negatives, a.neg)
    elif a.phase == 'cands':
        phase_cands(reg, negatives, a.neg, only)
    elif a.phase == 'probe':
        phase_probe(reg, negatives, a.neg, sorted(only) or ['suspense', 'mystery', 'triumph'])
    else:
        phase_regress(reg, negatives, a.neg)
    return 0


if __name__ == '__main__':
    sys.exit(main())
