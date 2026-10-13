# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Render The Farmyard Sounds Song from the LOWERED recomposition.

The register sweep proved the shrillness was in the SCORE, not the caption: the
`preschool` age band is C4-D5, so a D-major pentatonic settled on A4 with D5 on
top and ACE-Step sang exactly that. Transposing a finished plan works, but it
moves a tune that was written for a range it no longer occupies.

This does it the right way round: the composer now intersects the age band with
the singer's own sung window (adult female D4-B4), so the tune is WRITTEN inside
the register it will be sung in. `plan['tessitura']['source'] == 'singer'` is the
proof that the narrowing actually applied — a window too narrow to hold a tonic
is refused by the composer and falls back to the age band, and a silent fallback
here would render the old shrill tune under a new name.

TWO LEGS, because they answer different questions:
  t2m   text-to-music. ACE-Step is given the caption, lyrics, bpm, key and metre
        and writes its own tune. Six seeds, the SAME six the voice sweep used, so
        the operator can put an old take and a new one side by side and hear only
        the change of register.
  a2a   melody-conditioned on the soundfont render of the lowered score. This is
        the leg the register actually reaches — the tune ACE follows is the one
        the composer just wrote inside D4-B4.

The soundfont wav is therefore a deliverable, not a temp file: it is both the
conditioning audio and the human-audible statement of what the new score is.
"""

import logging as _zyg_logging
import json
import os
import sys
import time
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

JOB_ID = '0fc29420eb5a'
JOB = os.path.join(CREWS, 'output/kidsmusic', JOB_ID)
OUT = os.path.join(JOB, 'lowered')
SONG = 'The Farmyard Sounds Song'

# The same six the voice sweep drew, in the same order. A new set of seeds would
# have made the comparison "different register AND different roll of the dice".
SEEDS = [1303347561, 214748301, 998877221, 40391177, 776650012, 1200034477]

NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def log(msg):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {msg}')


def note_name(m):
    return f'{NOTE[m % 12]}{m // 12 - 1}'


def build_brief():
    """The shipped brief, with only what this task fixes stated explicitly."""
    base = json.load(open(os.path.join(JOB, 'song.json')))
    b = dict(base['brief'])
    b.update(
        {
            'style': 'animals',
            'family': 'children',
            'tonic': 'D',
            'tonic_pc': 2,
            'bpm': 123,
            'seconds': 30.0,
            'sung': True,
            'singer': 'adult_female',
            'lyrics_lines': list(base['lyrics']),
        }
    )
    return b


def master(raw, name):
    """prelevel -> 256k mp3. Returns the master's basename, '' if it failed."""
    out = os.path.join(OUT, f'{name}_master.mp3')
    pre = os.path.join(OUT, f'_{name}_pre.wav')
    try:
        got = K.prelevel(raw, pre, target_lufs=-14.0, tp_db=-1.5, log_fn=log)
        if not got:
            log(f'    prelevel failed for {name}')
            return ''
        K._mp3(got, out, log_fn=log, br='256k')
    except Exception as e:  # noqa: BLE001
        log(f'    master failed: {type(e).__name__}: {e}')
    finally:
        if os.path.isfile(pre):
            try:
                os.remove(pre)
            except OSError as _exc:
                _zyg_log.debug('pre-master cleanup skipped: %s', _exc)
    return os.path.basename(out) if os.path.isfile(out) else ''


def write_listen(rows, plan, stats):
    """One row per take, raw and master side by side, exactly as the sweep did."""
    trs = []
    for r in rows:
        cls = '' if r['ok'] else 'fail'
        raw = (
            f'<audio controls preload=none src="{r["file"]}"></audio>'
            if r['ok'] and r.get('file')
            else '<span class=na>&mdash;</span>'
        )
        mst = (
            f'<audio controls preload=none src="{r["master"]}"></audio>'
            if r.get('master')
            else '<span class=na>&mdash;</span>'
        )
        why = (
            'melody-conditioned on the lowered soundfont render'
            if r['mode'] == 'a2a'
            else 'text-to-music, ACE writes its own tune'
        )
        trs.append(f'''    <tr class="{cls}">
      <td class=k>{r['key']}</td>
      <td class=n>{r['mode']}<div class=cap>{why}</div></td>
      <td>{raw}</td>
      <td>{mst}</td>
      <td class="st {'pass' if r['ok'] else 'fail'}">{'ok' if r['ok'] else 'fail'}</td>
      <td class=num><code>{r['seed']}</code></td>
      <td class=cap>{r['reason'] or ''}</td>
    </tr>''')
    html = f"""<!doctype html>
<meta charset=utf-8><title>Farmyard Sounds &mdash; lowered recomposition</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:0;padding:28px;background:#14161a;color:#e6e8ec}}
 h1{{font-size:20px;margin:0 0 4px}}
 .sub{{color:#9aa3b0;margin:0 0 22px;max-width:74ch}}
 table{{border-collapse:collapse;width:100%;max-width:1180px}}
 th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
     color:#8b94a3;border-bottom:1px solid #2b3038;padding:6px 10px;font-weight:600}}
 td{{border-bottom:1px solid #22262d;padding:10px;vertical-align:middle}}
 tr.fail{{background:#2a1a1c}}
 .k{{color:#6f7a8a;font-variant-numeric:tabular-nums}}
 .n{{min-width:150px;font-weight:600}}
 .cap{{font-weight:400;font-size:11px;color:#818b99;margin-top:3px;max-width:40ch}}
 .num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
 .na{{color:#5c6470;font-size:11px}}
 .st{{font-size:11px;font-weight:700;text-transform:uppercase}}
 .st.pass{{color:#5fd08a}} .st.fail{{color:#ff7b7b}}
 audio{{height:32px;width:250px}}
 code{{color:#9aa3b0;font-size:11px}}
 .note{{margin-top:22px;color:#8b94a3;font-size:12px;max-width:80ch}}
 .note b{{color:#c3cad4}}
</style>
<h1>{SONG} &mdash; lowered recomposition</h1>
<p class=sub>Re-composed, not transposed: the composer intersected the preschool
age band with the adult-female sung window, so the tune was written inside
{stats['lo']}&ndash;{stats['hi']} (median {stats['median']},
{stats['median_hz']:.0f}&nbsp;Hz) rather than moved there afterwards.
{plan['key']['label']}, {plan['bpm']}&nbsp;bpm, {plan['meter']} time.
Masters at &minus;14&nbsp;LUFS so takes compare at equal loudness.</p>
<p class=sub>The score itself: <a href="lowered_melody.wav" style="color:#7fb3ff">
lowered_melody.wav</a> (soundfont) &middot;
<a href="roll.svg" style="color:#7fb3ff">roll.svg</a> &middot;
<a href="plan.json" style="color:#7fb3ff">plan.json</a></p>
<table>
<tr><th>take<th>leg<th>raw<th>master<th>state<th>seed<th>reason</tr>
{chr(10).join(trs)}
</table>
<p class=note>
<b>t2m</b> takes give ACE-Step only the caption and the words; the six seeds are
the same six the voice sweep used, so an old take and a new one differ by the
register alone. <b>a2a</b> takes are conditioned on the soundfont render of this
score, which is the leg through which the composer's register actually reaches
the sung take. <b>Pitch is not measured here</b> &mdash; that is a separate pass,
deliberately, so the renderer cannot grade its own homework.
</p>
"""
    open(os.path.join(OUT, 'listen.html'), 'w').write(html)


def render_take(plan, key, seed, cond, attempts=3):
    """One take, retried while ComfyUI is coming back.

    :8188 is shared and it went down mid-sweep once already, taking six takes
    with it: `ace_render` returns None rather than raising, so a dead backend
    reads as six honest failures and the sweep finishes with nothing to compare.
    A take is worth several minutes of GPU, so waiting a minute for the server to
    answer again is cheaper than a re-run — and a genuine refusal (a licence
    violation, an empty output) fails the same on every attempt, so retrying
    costs only the takes that would have been lost anyway.
    """
    raw = os.path.join(OUT, f'{key}.mp3')
    rec = {}
    for n in range(1, attempts + 1):
        if not K.ace_available():
            log(f'    ComfyUI not answering — waiting 60s (attempt {n}/{attempts})')
            time.sleep(60)
            if not K.ace_available():
                rec = {'ran': False, 'reason': 'ComfyUI down'}
                continue
        rec = {}
        got = K.ace_render(plan, raw, seed=seed, log_fn=log, info=rec, melody_wav=cond, should_abort=lambda: False)
        if got:
            return got, rec
        log(f'    attempt {n}/{attempts} failed: {rec.get("reason", "")}')
    return None, rec


def main():
    os.makedirs(OUT, exist_ok=True)
    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable — is ZYG_USE_COMFYUI=1 set?')

    brief = build_brief()
    plan = T.compose_best(brief, candidates=16, log_fn=log)
    tess = plan.get('tessitura') or {}
    pit = sorted(n['p'] for n in plan['melody'])
    if tess.get('source') != 'singer':
        raise RuntimeError(
            f'tessitura came from {tess.get("source")!r}, not the singer window — {tess.get("window_note")}'
        )
    if pit[-1] > 71:
        raise RuntimeError(f'melody tops out at {pit[-1]} ({note_name(pit[-1])}) > B4')

    # ace_render reads plan['lyrics_block']; without it the take is instrumental.
    plan['lyrics'] = brief['lyrics_lines']
    plan['lyrics_block'] = K.lyrics_block(brief['lyrics_lines'], plan['order'])

    med = pit[len(pit) // 2]
    stats = {
        'lo_midi': pit[0],
        'hi_midi': pit[-1],
        'median_midi': med,
        'lo': note_name(pit[0]),
        'hi': note_name(pit[-1]),
        'median': note_name(med),
        'median_hz': round(440.0 * 2 ** ((med - 69) / 12), 1),
    }
    log(
        f'tune {stats["lo"]}-{stats["hi"]}, median {stats["median"]} '
        f'({stats["median_hz"]:.0f} Hz)  key {plan["key"]["ace_keyscale"]}  '
        f'tessitura {tess["source"]} ({tess["lo"]}-{tess["hi"]})'
    )

    json.dump(plan, open(os.path.join(OUT, 'plan.json'), 'w'), indent=1)
    mid = K.write_midi(plan, os.path.join(OUT, 'lowered.mid'), log_fn=log)
    cond = os.path.join(OUT, 'lowered_melody.wav')
    if not K.render_soundfont(mid, cond, log_fn=log):
        raise SystemExit('soundfont render failed — the a2a leg has no conditioning')
    K.write_roll_svg(plan, os.path.join(OUT, 'roll.svg'))

    takes = [(f't2m_s{i:02d}', s, 't2m') for i, s in enumerate(SEEDS, 1)] + [
        (f'a2a_s{i:02d}', s, 'a2a') for i, s in enumerate(SEEDS[:2], 1)
    ]
    rows = []
    for i, (key, seed, mode) in enumerate(takes, 1):
        log(f'--- {i}/{len(takes)}  {key}  ({mode}, seed {seed})')
        raw = os.path.join(OUT, f'{key}.mp3')
        # The plan is deterministic for this brief, so a take already on disk is
        # the same take this run would render. Resumable because the backend has
        # proven it can vanish mid-sweep, and a re-render costs minutes of GPU.
        if os.path.isfile(raw) and os.path.isfile(os.path.join(OUT, f'{key}_master.mp3')):
            log('    already rendered — kept')
            rows.append(
                {
                    'key': key,
                    'seed': seed,
                    'mode': mode,
                    'file': f'{key}.mp3',
                    'master': f'{key}_master.mp3',
                    'ok': True,
                    'reason': '',
                    'ace_ran': True,
                    'melody_conditioned': mode == 'a2a',
                    'workflow': '',
                    'ace_tags': '',
                    'resumed': True,
                }
            )
            continue
        got, rec = render_take(plan, key, seed, cond if mode == 'a2a' else None)
        row = {
            'key': key,
            'seed': seed,
            'mode': mode,
            'file': os.path.basename(raw) if got else '',
            'master': master(got, key) if got else '',
            'ok': bool(got),
            'reason': rec.get('reason', ''),
            'ace_ran': bool(rec.get('ran')),
            'melody_conditioned': bool(rec.get('melody_conditioned')),
            'workflow': rec.get('workflow', ''),
            'ace_tags': rec.get('ace_tags', ''),
        }
        row['ok'] = bool(got) and bool(row['master'])
        log(f'    ran={row["ace_ran"]} master={row["master"] or "NONE"} reason={row["reason"] or "-"}')
        rows.append(row)
        json.dump(
            {
                'song': SONG,
                'job': JOB_ID,
                'plan_range': stats,
                'tessitura': tess,
                'key': plan['key']['label'],
                'bpm': plan['bpm'],
                'seeds': SEEDS,
                'takes': rows,
            },
            open(os.path.join(OUT, 'index.json'), 'w'),
            indent=1,
        )

    write_listen(rows, plan, stats)

    # The GPU is shared. comfy_free posts /free and polls ComfyUI's own PID, and
    # unlike release_memory it does not honour ZYG_COMFY_KEEP_LOADED — which is 1
    # on this box, so anything that respects it would silently release nothing.
    try:
        from zyg_workflows import comfy_offload as CO

        log(f'vram: comfy_free -> {CO.comfy_free(log_fn=log)}')
    except Exception as e:  # noqa: BLE001
        log(f'vram: NOT released — {type(e).__name__}: {e}')

    ok = sum(1 for r in rows if r['ok'])
    log(f'=== {ok}/{len(rows)} takes ok ===')
    for r in rows:
        log(f'{r["key"]:10s} {r["mode"]:4s} seed {r["seed"]:<11d} {"OK " if r["ok"] else "FAIL"} {r["reason"]}')
    return 0 if ok >= 6 else 1


if __name__ == '__main__':
    sys.exit(main())
