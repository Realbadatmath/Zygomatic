# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Which seed does the sung register actually track — the LM's, or the sampler's?

THE QUESTION. Every register experiment on this song so far has been read
through a haze of run-to-run variance: two identical briefs come back with sung
medians tens of cents apart, and the caption sweep found seed noise moving the
voice further than any caption did. Before another lever is tested, the noise
has to be attributed to a mechanism.

THE MECHANISM, verified in comfy/text_encoders/ace15.py. An ACE-Step 1.5
text-to-music graph has TWO independent random draws:

  node 2  TextEncodeAceStep15 — the 1.7B audio-code LM runs once per
          conditioning and invents the 5 Hz semantic codes (the "plan": the
          tune, the phrasing, where the voice sits) from the caption, the
          lyrics and the four metas. It draws on its OWN seed.
  node 5  KSampler — the DiT denoises a latent into audio against those codes.
          It draws on its own, separate seed.

`ace_render(plan, out, seed=S, lm_seed=L)` sets node 2 to L and node 5 to S,
so the two draws can be moved one at a time. A ComfyUI latent BATCH already
demonstrates the asymmetry — a batch shares one LM plan and only sampler noise
differs across it — but a batch cannot be measured take by take here.

THE DESIGN. Eight text-to-music renders of the shipped song, unchanged score,
shipped caption, in two groups of four:

  A  lm_seed  = 1303347561 held; sampler seeds 11, 22, 33, 44.
     Everything the LM decided is identical four times over; only diffusion
     noise moves. Whatever spread survives is the SAMPLER's contribution.
  B  seed     = 1303347561 held; lm_seeds 11, 22, 33, 44.
     The sampler noise is identical four times over; only the LM's plan moves.
     Whatever spread appears is the LM's contribution.

The score is deliberately the ORIGINAL A4-median tune and the render is
deliberately text-to-music, not a2a: the point is to size the variance of the
plain generation path, not to move the register. The two groups are read
against each other, so an absolute register is not needed.

THE MEASUREMENT, per take: demucs two-stem split, then the RMVPE
confidence-weighted median F0 of the vocal stem (with p10/p90 and the fraction
of voiced time above 500 Hz, since register and shrillness are separate axes).
Per group: the median of the four, and the SPREAD, max against min in cents —
cents because a ratio of pitches is the only scale on which a spread at 340 Hz
and one at 420 Hz are comparable.

THE VERDICT RULE, fixed before the run so it cannot be fitted afterwards: the
register tracks a seed if the group that holds THAT seed still is at least
three times tighter than the other. A spread ratio inside 3x is reported as
"both contribute" — with n=4 per group that is the honest reading.
"""

import logging as _zyg_logging
import copy
import json
import math
import os
import shutil
import sys
import time
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)
os.environ.setdefault('ZYG_USE_COMFYUI', '1')

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import sung_pitch  # noqa: E402

JOB = os.path.join(CREWS, 'output/kidsmusic/0fc29420eb5a')
OUT = os.path.join(JOB, 'seed_attrib')

# The seed the register sweep pinned. It is the HELD value in both groups so
# the two groups share a corner of the space and are not two unrelated samples.
PIN = 1303347561
VARY = [11, 22, 33, 44]

# The factor by which one group must beat the other to earn a verdict.
TIGHTER = 3.0

GROUPS = [
    ('A', 'lm_seed held — only sampler noise moves', 'sampler', 'the KSampler seed (node 5, diffusion noise)'),
    ('B', 'sampler seed held — only the LM plan moves', 'lm', 'the LM seed (node 2, the audio-code plan)'),
]


def log(msg):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {msg}')


def cents(a, b):
    """b against a, in cents. None if either is missing or non-positive."""
    if not a or not b or a <= 0 or b <= 0:
        return None
    return 1200.0 * math.log2(float(b) / float(a))


def median(vals):
    v = sorted(vals)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def measure(path, work):
    """(measure_stem dict or {}, vocal-vs-rest dB or None, error string)."""
    sep = K.separate_vocal(path, work, log_fn=log)
    if not sep.get('ok'):
        return {}, None, f'separation failed: {(sep.get("error") or "")[:120]}'
    ratio = sep.get('ratio_db')
    m = sung_pitch.measure_stem(sep['vocals'])
    if not m.get('ok'):
        return {}, ratio, f'measure failed: {(m.get("error") or "")[:120]}'
    return m, ratio, ''


def summarise(rows):
    """Per-group stats and the conclusion line. Pure — no I/O."""
    groups = {}
    for gid, why, _tracks, _label in GROUPS:
        f0 = [r['f0_median_hz'] for r in rows if r['group'] == gid and r.get('ok') and r.get('f0_median_hz')]
        spread = cents(min(f0), max(f0)) if len(f0) >= 2 else None
        groups[gid] = {
            'group': gid,
            'why': why,
            'n_ok': len(f0),
            'held': ('lm_seed' if gid == 'A' else 'seed'),
            'held_value': PIN,
            'varied': ('seed' if gid == 'A' else 'lm_seed'),
            'varied_values': VARY,
            'f0_median_hz': round(median(f0), 3) if f0 else None,
            'f0_min_hz': round(min(f0), 3) if f0 else None,
            'f0_max_hz': round(max(f0), 3) if f0 else None,
            'spread_cents': round(spread, 1) if spread is not None else None,
        }

    a, b = groups['A']['spread_cents'], groups['B']['spread_cents']
    if a is None or b is None:
        return groups, ('inconclusive: fewer than two measured takes in a group, so no spread could be computed')
    # A holds the LM seed: if A is the tight one, the LM seed is what pins the
    # register. B holds the sampler seed: if B is tight, the sampler pins it.
    if a * TIGHTER < b:
        return groups, (
            f'the register tracks the LM seed (node 2): holding it pins the '
            f'sung median to {a:.0f} cents across four sampler seeds, while '
            f'holding the sampler seed and varying the LM leaves {b:.0f} cents '
            f'— {b / a:.1f}x wider'
        )
    if b * TIGHTER < a:
        return groups, (
            f'the register tracks the sampler seed (node 5): holding it pins '
            f'the sung median to {b:.0f} cents across four LM seeds, while '
            f'holding the LM seed and varying the sampler leaves {a:.0f} cents '
            f'— {a / b:.1f}x wider'
        )
    return groups, (
        f'both seeds contribute: sampler-only variance {a:.0f} cents against '
        f'LM-only {b:.0f} cents is a ratio of {max(a, b) / max(min(a, b), 1e-9):.1f}x, '
        f'inside the {TIGHTER:g}x a verdict needs at n=4 per group'
    )


def html(rows, groups, conclusion):
    def num(v, unit='', dp=1):
        if v is None:
            return '<span class=na>n/a</span>'
        return f'{float(v):.{dp}f}<span class=u>{unit}</span>'

    out = [
        """<!doctype html>
<meta charset=utf-8><title>Farmyard Sounds - LM seed vs sampler seed</title>
<style>
 body{font:14px/1.5 system-ui,sans-serif;margin:0;padding:28px;background:#14161a;color:#e6e8ec}
 h1{font-size:20px;margin:0 0 4px} h2{font-size:14px;margin:26px 0 8px;color:#c3cad4}
 .sub{color:#9aa3b0;margin:0 0 22px;max-width:80ch}
 table{border-collapse:collapse;width:100%;max-width:1280px}
 th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
     color:#8b94a3;border-bottom:1px solid #2b3038;padding:6px 10px;font-weight:600}
 td{border-bottom:1px solid #22262d;padding:10px;vertical-align:middle}
 tr.fail{background:#2a1a1c}
 tr.gb td{background:#181b21}
 .k{color:#6f7a8a;font-variant-numeric:tabular-nums}
 .n{min-width:150px;font-weight:600}
 .cap{font-weight:400;font-size:11px;color:#818b99;margin-top:3px;max-width:40ch}
 .num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
 .u{color:#6f7a8a;font-size:11px;margin-left:2px}
 .na{color:#5c6470;font-size:11px}
 .held{color:#7fd1a0} .varied{color:#e0b070}
 audio{height:32px;width:220px}
 code{color:#9aa3b0;font-size:11px}
 .verdict{margin:18px 0 4px;padding:14px 16px;background:#1b2129;border-left:3px solid #7fd1a0;
     max-width:80ch;color:#d6dbe3}
 .note{margin-top:22px;color:#8b94a3;font-size:12px;max-width:82ch}
 .note b{color:#c3cad4}
</style>
<h1>The Farmyard Sounds Song &mdash; LM seed vs sampler seed</h1>
<p class=sub>Eight text-to-music renders of the unchanged song with the shipped
caption. An ACE-Step 1.5 graph draws twice: the 1.7B audio-code LM (node 2)
invents the semantic plan &mdash; the tune, the phrasing, where the voice sits
&mdash; and the KSampler (node 5) denoises against it. Each group holds one of
those seeds still and moves the other four ways, so the run-to-run register
variance can be attributed to a mechanism instead of to &ldquo;seed noise&rdquo;.
Mastered to &minus;14&nbsp;LUFS so they compare at equal loudness.</p>"""
    ]

    out.append(f'<p class=verdict><b>Conclusion.</b> {conclusion}</p>')

    out.append('<h2>per group</h2><table>')
    out.append('<tr><th>group<th>held<th>varied<th>takes<th>median F0<th>min<th>max<th>spread</tr>')
    for gid, _why, _t, _l in GROUPS:
        g = groups[gid]
        out.append(
            f'<tr><td class=n>{gid}<div class=cap>{g["why"]}</div></td>'
            f'<td class=k><span class=held>{g["held"]}={g["held_value"]}</span></td>'
            f'<td class=k><span class=varied>{g["varied"]}='
            f'{", ".join(str(v) for v in g["varied_values"])}</span></td>'
            f'<td class=num>{g["n_ok"]}/4</td>'
            f'<td class=num>{num(g["f0_median_hz"], " Hz")}</td>'
            f'<td class=num>{num(g["f0_min_hz"], " Hz")}</td>'
            f'<td class=num>{num(g["f0_max_hz"], " Hz")}</td>'
            f'<td class=num>{num(g["spread_cents"], " cents", 0)}</td></tr>'
        )
    out.append('</table>')

    out.append('<h2>the eight takes</h2><table>')
    out.append(
        '<tr><th>take<th>group<th>lm seed<th>sampler seed<th>master'
        '<th>F0 median<th>p10<th>p90<th>&gt;500 Hz<th>vocal vs mix</tr>'
    )
    for r in rows:
        cls = ('' if r['ok'] else 'fail') + (' gb' if r['group'] == 'B' else '')
        mst = (
            f'<audio controls preload=none src="{r["master"]}"></audio>'
            if r.get('master')
            else (
                f'<audio controls preload=none src="{r["file"]}"></audio>'
                if r.get('file')
                else '<span class=na>&mdash;</span>'
            )
        )
        lm = f'<span class={"held" if r["group"] == "A" else "varied"}>{r["lm_seed"]}</span>'
        sm = f'<span class={"varied" if r["group"] == "A" else "held"}>{r["seed"]}</span>'
        out.append(
            f'<tr class="{cls}"><td class=n>{r["key"]}'
            f'<div class=cap>{r.get("reason", "") or ""}</div></td>'
            f'<td class=k>{r["group"]}</td>'
            f'<td class=num><code>{lm}</code></td>'
            f'<td class=num><code>{sm}</code></td>'
            f'<td>{mst}</td>'
            f'<td class=num>{num(r.get("f0_median_hz"), " Hz")}</td>'
            f'<td class=num>{num(r.get("f0_p10_hz"), " Hz")}</td>'
            f'<td class=num>{num(r.get("f0_p90_hz"), " Hz")}</td>'
            f'<td class=num>{num(r.get("pct_time_above_500hz"), " %")}</td>'
            f'<td class=num>{num(r.get("vocal_present_db"), " dB")}</td></tr>'
        )
    out.append('</table>')
    out.append(
        '<p class=note><b>How to read it.</b> <b>F0 median</b> is the '
        'confidence-weighted RMVPE median of the demucs vocal stem &mdash; the '
        'register the singer actually landed in, not the composed tune. '
        '<b>spread</b> is max against min inside a group, in cents, because a '
        'ratio of pitches is the only scale on which spreads at different '
        'absolute registers compare. <b>&gt;500 Hz</b> is the share of voiced '
        'time above G#5: brightness is a separate axis from register and a take '
        'can move on one without the other. <b>vocal vs mix</b> below about '
        '&minus;18&nbsp;dB means there is barely a stem to measure and the row '
        'should be distrusted.</p>'
    )
    return '\n'.join(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable')
    base_plan = json.load(open(os.path.join(JOB, 'song.json')))

    # The takes, interleaved A/B so a partial run still has both groups.
    takes = []
    for v in VARY:
        takes.append(('A', f'a_samp{v}', PIN, v))  # (group, key, lm_seed, seed)
    for v in VARY:
        takes.append(('B', f'b_lm{v}', v, PIN))

    work = os.path.join(OUT, '_work')
    rows = []
    for i, (gid, key, lm_seed, seed) in enumerate(takes, 1):
        log(f'--- {i}/{len(takes)}  {key}  group {gid}  lm_seed={lm_seed} sampler seed={seed}')
        # Deep copy so nothing this loop does can leak into the next take; the
        # plan itself is never modified, which is the point of the design.
        plan = copy.deepcopy(base_plan)

        take = os.path.join(OUT, f'{key}.mp3')
        master = os.path.join(OUT, f'{key}_master.mp3')
        rec = {}
        got = K.ace_render(plan, take, seed=seed, lm_seed=lm_seed, log_fn=log, info=rec, should_abort=lambda: False)
        row = {
            'key': key,
            'group': gid,
            'lm_seed': lm_seed,
            'seed': seed,
            'held': 'lm_seed' if gid == 'A' else 'seed',
            'varied': 'seed' if gid == 'A' else 'lm_seed',
            'ok': False,
            'reason': rec.get('reason', ''),
            'mode': rec.get('mode'),
            'workflow': rec.get('workflow'),
            'file': os.path.basename(take) if got else '',
            'master': '',
            'f0_median_hz': None,
            'f0_p10_hz': None,
            'f0_p90_hz': None,
            'f0_median_midi': None,
            'pct_time_above_500hz': None,
            'voiced_frac': None,
            'agreement_cents': None,
            'sharpness_acum': None,
            'vocal_present_db': None,
        }

        if got:
            pre = K.prelevel(got, os.path.join(OUT, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=log)
            if pre and K._mp3(pre, master, log_fn=log, br='256k') and os.path.isfile(master):
                row['master'] = os.path.basename(master)
            meas_on = master if row['master'] else got
            m, ratio, err = measure(meas_on, os.path.join(work, key))
            row['vocal_present_db'] = ratio
            for f in (
                'f0_median_hz',
                'f0_p10_hz',
                'f0_p90_hz',
                'f0_median_midi',
                'pct_time_above_500hz',
                'voiced_frac',
                'agreement_cents',
                'sharpness_acum',
            ):
                row[f] = m.get(f)
            # `ok` means MEASURED, not merely rendered: an unmeasured take
            # contributes nothing to a spread and must not be counted as one.
            row['ok'] = bool(m.get('ok'))
            if err:
                row['reason'] = err
            log(
                f'    F0 {row["f0_median_hz"]} Hz '
                f'(p10 {row["f0_p10_hz"]} / p90 {row["f0_p90_hz"]})  '
                f'above500 {row["pct_time_above_500hz"]}%  stem {ratio} dB'
            )
        else:
            log(f'    RENDER FAILED: {row["reason"]}')
        rows.append(row)

        groups, conclusion = summarise(rows)
        json.dump(
            {
                'song': 'The Farmyard Sounds Song',
                'job': '0fc29420eb5a',
                'question': ('does the sung register track the LM seed (node 2) or the sampler seed (node 5)?'),
                'mode': 'text-to-music (no melody or cover conditioning)',
                'plan_source': 'song.json (unchanged, A4-median tune)',
                'caption': 'shipped (brief.singer = adult_female)',
                'held_seed': PIN,
                'varied_seeds': VARY,
                'verdict_rule': (f'a group must be {TIGHTER:g}x tighter in cents than the other to earn a verdict'),
                'groups': [groups[g] for g, _w, _t, _l in GROUPS],
                'takes': rows,
                'conclusion': conclusion,
            },
            open(os.path.join(OUT, 'index.json'), 'w'),
            indent=1,
        )
        open(os.path.join(OUT, 'listen.html'), 'w').write(html(rows, groups, conclusion))

    for f in os.listdir(OUT):
        if f.startswith('_') and f.endswith('.wav'):
            try:
                os.remove(os.path.join(OUT, f))
            except OSError as _exc:
                _zyg_log.debug('intermediate render cleanup skipped: %s', _exc)
    shutil.rmtree(work, ignore_errors=True)

    groups, conclusion = summarise(rows)
    log('=== SUMMARY ===')
    for r in rows:
        log(
            f'{r["key"]:10s} {r["group"]}  lm {r["lm_seed"]:>10d}  '
            f'samp {r["seed"]:>10d}  F0 {str(r["f0_median_hz"]):>8s} Hz  '
            f'{"" if r["ok"] else "NOT MEASURED " + (r["reason"] or "")}'
        )
    for gid, _w, _t, _l in GROUPS:
        g = groups[gid]
        log(
            f'group {gid}  held {g["held"]:8s}  n={g["n_ok"]}/4  '
            f'median {g["f0_median_hz"]} Hz  spread {g["spread_cents"]} cents'
        )
    log(f'CONCLUSION: {conclusion}')

    try:
        from zyg_workflows import comfy_offload

        comfy_offload.comfy_free(log_fn=log)
    except Exception as e:  # noqa: BLE001
        log(f'vram release failed: {type(e).__name__}: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
