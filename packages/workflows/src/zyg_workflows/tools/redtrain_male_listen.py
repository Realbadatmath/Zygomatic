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

import html
import json
import os
import sys
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


def main():
    idx = json.load(open(os.path.join(OUT, 'index.json')))
    lo, hi = idx['band_hz']
    rows = []

    # The thing these ten are auditioning to replace.
    rows.append(
        '<tr class=ref>'
        '<td class=k>&mdash;</td>'
        '<td class=n>SHIPPED &mdash; adult female'
        '<div class=why>The delivered master, for comparison.</div></td>'
        '<td><audio controls preload=none src="../master.mp3"></audio></td>'
        '<td class=num>427<span class=u> Hz</span></td>'
        '<td class="num na">&mdash;</td>'
        '<td class=num>-6.6<span class=u> dB</span></td>'
        '<td class="num na">&mdash;</td>'
        '<td><span class="st pass">shipped</span></td>'
        '<td class=k>1669026733</td></tr>'
    )

    for _i, t in enumerate(idx['takes'], 1):
        g = t.get('gate') or {}
        src = t.get('master') or (os.path.basename(t['key'] + '.mp3'))
        dead = '' if t.get('ok') else ' dead'
        audio = (
            f'<audio controls preload=none src="{html.escape(src)}"></audio>'
            if t.get('ok')
            else f'<span class=na>{html.escape(t.get("reason") or "no take")}</span>'
        )
        p10, p90 = g.get('f0_p10_hz'), g.get('f0_p90_hz')
        spread = (
            f'<td class=num>{p10:.0f}&ndash;{p90:.0f}<span class=u> Hz</span></td>'
            if p10 and p90
            else '<td class="num na">&mdash;</td>'
        )
        # The song's own identity, measured on the file that ships — a take in
        # the wrong key is not this song however good the voice is.
        sc = t.get('song_check') or {}
        song = (
            f'<td class=num>{html.escape(str(sc.get("detected_key") or "?"))}'
            f'<span class=u> {html.escape(str(sc.get("key_match") or ""))}</span>'
            f'<div class=cap>{sc.get("detected_bpm")} bpm '
            f'({html.escape(str(sc.get("bpm_relation") or ""))})</div></td>'
        )
        # How hard the arm was to land. One seed is a strong arm; six is a
        # caption that fights the register, and the operator should know which.
        n_try = t.get('attempts_used') or len([a for a in (t.get('attempts') or []) if a.get('f0') is not None]) or 1
        how = t.get('reseed') or ''
        tries = f'<td class=num>{n_try}' + (f'<div class=cap>{html.escape(how)}</div>' if how else '') + '</td>'
        rows.append(
            f'<tr class="{dead}">'
            f'<td class=k>{t["key"].split("_")[0]}</td>'
            f'<td class=n>{html.escape(t["display"])}'
            f'<div class=why>{html.escape(t.get("why", ""))}</div>'
            f'<div class=cap>{html.escape(t["caption"])}</div></td>'
            f'<td>{audio}</td>'
            + num(g.get('f0_median_hz'), 'Hz')
            + spread
            + num(g.get('vocal_over_mix_db'), 'dB', 1)
            + song
            + tries
            + f'<td class=k>{t["seed"]}</td></tr>'
        )

    page = f"""<!doctype html>
<meta charset=utf-8><title>The Red Train to the Sea &mdash; 10 male voices</title>
<style>{CSS}</style>
<h1>The Red Train to the Sea &mdash; ten male voices</h1>
<p class=sub>Same melody, lyrics, key (D&nbsp;major), tempo (117&nbsp;bpm) and ukulele /
glockenspiel arrangement in every take &mdash; the a2a melody-conditioned graph at
denoise&nbsp;0.45, the same one that produced the shipped master. Only the singer
clause at the head of the ACE-Step caption and that take's seed change. All ten
mastered through the delivered song's chain to &minus;14&nbsp;LUFS so they compare at
equal loudness. Cast band {lo:.0f}&ndash;{hi:.0f}&nbsp;Hz.</p>
<table>
<tr><th>#<th>voice<th>listen<th>F0 median<th>p10&ndash;p90<th>vocal vs mix
    <th>key / tempo<th>seeds tried<th>seed</tr>
{chr(10).join(rows)}
</table>
<p class=note><b>The gate column is advisory, not a verdict.</b> The male band
{lo:.0f}&ndash;{hi:.0f}&nbsp;Hz was set on the Praat meter from six takes, and Praat was
retired for sung material on 2026-09-06 (its 550&nbsp;Hz ceiling censors the median).
The F0 beside it is RMVPE. A different instrument against an old band is not a
pass/fail, so the sweep ran with <code>ZYG_KIDSMUSIC_SINGER_ENFORCE=0</code>: every
number recorded, nothing failed on it. These ten renders <b>are</b> the male
re-measurement the SINGERS table asks for. Rank by ear; the numbers say which one
sits where, not which one is right.</p>
<p class=note>Each row is reproducible from the pair (caption, seed) printed on it,
against plan <code>output/kidsmusic/1ba342d5cd75/song.json</code>. Rebuild with
<code>tools/redtrain_male_voices.py</code> &mdash; takes already on disk are reused.</p>
"""
    dst = os.path.join(OUT, 'listen.html')
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(page)
    print(f'wrote {dst} ({len(page)} bytes, {len(idx["takes"])} takes)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
