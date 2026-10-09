# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ACE-Step COVER mode on The Farmyard Sounds Song — does the register follow?

THE QUESTION. Every previous attempt to move this song's singer down failed for
the same structural reason: the melody-conditioned (a2a) graph only swaps the
KSampler's starting latent. The DiT's melodic context still comes from the 5 Hz
audio codes the 1.7B LM invents from the caption and the four metas, so a -12
transpose of the score moved the sung F0 by 0.00 st. The caption was never the
lever and neither was the starting latent.

ReferenceTimbreAudio is the lever. Feeding a latent into it sets is_covers=True
(comfy/model_base.py ~1845), DROPS the LM codes, and tokenises the reference
itself into the semantic codes that become the source context
(comfy/ldm/ace/ace_step15.py prepare_condition). If cover mode works as the
maintainers describe, a reference pitched down 4 semitones should come back sung
about 4 semitones lower.

FOUR SOURCES, each answering a different half of that.
  src_ctrl   the take the operator liked (v02 bright soprano), unshifted. The
             control: a cover of a good take at its own pitch. Whatever the
             cover process costs in quality is visible here with the register
             held still.
  src_down4  the same file through rubberband at -4 st. The artefacts do not
             matter — the model re-performs the material rather than replaying
             it — so a crude shifter is the right tool.
  src_down2  the same at -2 st, the shallow rung, to see whether the response is
             proportional or a threshold.
  src_sf_a   the soundfont render of the score transposed down 5 (A major, no
             vocal at all). The dossier's second candidate: a sparse nursery
             arrangement is exactly the material the maintainer says holds its
             melody through a cover.

The caption asks for the singer in all four; in src_sf_a there is no voice in
the reference to copy, so it tests whether cover mode takes the TUNE from the
reference and the VOICE from the caption.

TWO SEEDS EACH, because the caption sweep established that seed noise moves this
model's voice more than a caption does. One seed per source could not tell a
register shift from that noise.

The keyscale meta is moved with the source (D / A# / C / A major): handing the
model a caption that disagrees with the audio it is covering would confound the
measurement with a key conflict.

MEASURED, per take: the log-spectrum cross-correlation shift against the control
SOURCE (every partial of every instrument votes, independent of F0 tracking) and
the RMVPE confidence-weighted median F0 of the demucs vocal stem. Both, because
the first is robust but reads the whole mix, and the second reads the singer but
needs a stem to exist first — vocal_present_db says whether it does.
"""

import logging as _zyg_logging
import copy
import json
import os
import shutil
import subprocess
import sys
import time
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)
os.environ.setdefault('ZYG_USE_COMFYUI', '1')

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import sung_pitch  # noqa: E402

JOB = os.path.join(CREWS, 'output/kidsmusic/0fc29420eb5a')
OUT = os.path.join(JOB, 'cover_sweep')
SRC_DIR = os.path.join(OUT, 'sources')

LIKED = os.path.join(JOB, 'voice_sweep/v02_bright_soprano_master.mp3')
SF_MID = os.path.join(JOB, 'register_sweep/r05_down5.mid')

# Held across the sweep. 1303347561 is the seed the register sweep pinned; the
# second is arbitrary and only there to separate signal from seed noise.
SEEDS = [1303347561, 998877221]

# (key, keyscale meta, how it is built, why)
SOURCES = [
    ('src_ctrl', 'D major', 'liked take, unshifted', 'control — a cover of the liked take at its own pitch'),
    (
        'src_down4',
        'A# major',
        'liked take, rubberband pitch=0.7937 formant=preserved',
        'the -4 st question: does the cover follow the reference down?',
    ),
    (
        'src_down2',
        'C major',
        'liked take, rubberband pitch=0.8909 formant=preserved',
        'the shallow rung — proportional response or a threshold?',
    ),
    (
        'src_sf_a',
        'A major',
        'soundfont render of register_sweep/r05_down5.mid',
        'no voice in the reference at all: tune from the score, voice from the caption',
    ),
]


def log(msg):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {msg}')


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f'    ffmpeg failed: {(r.stderr or "")[-300:]}')
        return False
    return True


def build_sources():
    """The four reference wavs, 44.1k stereo (what LoadAudio/VAEEncodeAudio want)."""
    os.makedirs(SRC_DIR, exist_ok=True)
    made = {}

    plain = os.path.join(SRC_DIR, 'src_ctrl.wav')
    if _run([exe('ffmpeg'), '-y', '-v', 'error', '-i', LIKED, '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', plain]):
        made['src_ctrl'] = plain

    for key, ratio in (('src_down4', '0.7937'), ('src_down2', '0.8909')):
        dst = os.path.join(SRC_DIR, f'{key}.wav')
        if _run(
            [
                exe('ffmpeg'),
                '-y',
                '-v',
                'error',
                '-i',
                LIKED,
                '-af',
                f'rubberband=pitch={ratio}:formant=preserved',
                '-ar',
                '44100',
                '-ac',
                '2',
                '-c:a',
                'pcm_s16le',
                dst,
            ]
        ):
            made[key] = dst

    sf = os.path.join(SRC_DIR, 'src_sf_a.wav')
    if K.render_soundfont(SF_MID, sf, log_fn=log):
        made['src_sf_a'] = sf
    else:
        log('    soundfont render of r05_down5.mid FAILED')
    return made


def measure(path, work):
    """(vocal f0 median Hz, vocal-vs-rest dB, stem path or '')."""
    sep = K.separate_vocal(path, work, log_fn=log)
    if not sep.get('ok'):
        return None, None, f'separation failed: {sep.get("error", "")[:120]}'
    ratio = sep.get('ratio_db')
    m = sung_pitch.measure_stem(sep['vocals'])
    if not m.get('ok'):
        return None, ratio, f'measure failed: {m.get("error", "")[:120]}'
    return m.get('f0_median_hz'), ratio, ''


def html(rows, srcs):
    def num(v, unit='', dp=2):
        if v is None:
            return '<span class=na>n/a</span>'
        return f'{float(v):.{dp}f}<span class=u>{unit}</span>'

    ctrl = [r for r in rows if r['source'] == 'src_ctrl' and r.get('vocal_f0_median_hz')]
    base = (sum(r['vocal_f0_median_hz'] for r in ctrl) / len(ctrl)) if ctrl else None

    out = [
        """<!doctype html>
<meta charset=utf-8><title>Farmyard Sounds - ACE-Step cover mode</title>
<style>
 body{font:14px/1.5 system-ui,sans-serif;margin:0;padding:28px;background:#14161a;color:#e6e8ec}
 h1{font-size:20px;margin:0 0 4px} h2{font-size:14px;margin:26px 0 8px;color:#c3cad4}
 .sub{color:#9aa3b0;margin:0 0 22px;max-width:78ch}
 table{border-collapse:collapse;width:100%;max-width:1280px}
 th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
     color:#8b94a3;border-bottom:1px solid #2b3038;padding:6px 10px;font-weight:600}
 td{border-bottom:1px solid #22262d;padding:10px;vertical-align:middle}
 tr.fail{background:#2a1a1c}
 .k{color:#6f7a8a;font-variant-numeric:tabular-nums}
 .n{min-width:150px;font-weight:600}
 .cap{font-weight:400;font-size:11px;color:#818b99;margin-top:3px;max-width:36ch}
 .num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
 .u{color:#6f7a8a;font-size:11px;margin-left:2px}
 .na{color:#5c6470;font-size:11px}
 audio{height:32px;width:220px}
 code{color:#9aa3b0;font-size:11px}
 .note{margin-top:22px;color:#8b94a3;font-size:12px;max-width:80ch}
 .note b{color:#c3cad4}
</style>
<h1>The Farmyard Sounds Song &mdash; ACE-Step cover mode</h1>
<p class=sub>Each take is a COVER: the reference below is tokenised into the
semantic codes that become the model's source context, the LM's own audio codes
are dropped. Same lyrics and caption throughout; the keyscale meta moves with the
reference. Two seeds per reference because seed noise moves this model's voice
more than a caption does. Mastered to &minus;14&nbsp;LUFS so they compare at equal
loudness.</p>
<h2>the four references</h2>
<table>
<tr><th>source<th>listen<th>keyscale<th>built<th>why</tr>"""
    ]
    for s in srcs:
        f = f'sources/{s["key"]}.wav'
        out.append(
            f'<tr><td class=n>{s["key"]}</td>'
            f'<td><audio controls preload=none src="{f}"></audio></td>'
            f'<td class=k>{s["keyscale"]}</td>'
            f'<td class=k>{s["built"]}</td>'
            f'<td class=k>{s["why"]}</td></tr>'
        )
    out.append('</table>\n<h2>the covers</h2>\n<table>')
    out.append(
        '<tr><th>take<th>reference<th>seed<th>raw<th>master'
        '<th>spectral shift<th>corr<th>vocal F0<th>vs ctrl'
        '<th>vocal vs mix</tr>'
    )
    for r in rows:
        cls = '' if r['ok'] else 'fail'
        raw = (
            f'<audio controls preload=none src="{r["file"]}"></audio>'
            if r.get('file')
            else '<span class=na>&mdash;</span>'
        )
        mst = (
            f'<audio controls preload=none src="{r["master"]}"></audio>'
            if r.get('master')
            else '<span class=na>&mdash;</span>'
        )
        st = None
        if base and r.get('vocal_f0_median_hz'):
            import math

            st = 12 * math.log2(r['vocal_f0_median_hz'] / base)
        out.append(
            f'<tr class="{cls}"><td class=n>{r["key"]}'
            f'<div class=cap>{r.get("reason", "") or ""}</div></td>'
            f'<td class=k>{r["source"]}</td>'
            f'<td class=num><code>{r["seed"]}</code></td>'
            f'<td>{raw}</td><td>{mst}</td>'
            f'<td class=num>{num(r.get("spectral_shift_vs_ctrl"), " st")}</td>'
            f'<td class=num>{num(r.get("corr"), "", 3)}</td>'
            f'<td class=num>{num(r.get("vocal_f0_median_hz"), " Hz", 1)}</td>'
            f'<td class=num>{num(st, " st")}</td>'
            f'<td class=num>{num(r.get("vocal_present_db"), " dB", 1)}</td></tr>'
        )
    out.append('</table>')
    out.append(
        '<p class=note><b>How to read it.</b> <b>spectral shift</b> is the '
        'log-spectrum cross-correlation of the whole mix against the unshifted '
        'reference &mdash; every partial votes, no F0 tracking involved; '
        '<b>corr</b> below ~0.8 means the take is different enough material that '
        'the shift number is not about pitch. <b>vocal F0</b> is the '
        'confidence-weighted RMVPE median of the demucs stem, and <b>vs ctrl</b> '
        'converts it to semitones against the mean of the control covers. Cover '
        'mode is working as advertised if the down4 rows sit near &minus;4 on '
        'both.</p>'
    )
    return '\n'.join(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable')
    base_plan = json.load(open(os.path.join(JOB, 'song.json')))

    log('building the four references')
    made = build_sources()
    srcs = [
        {'key': k, 'keyscale': ks, 'built': built, 'why': why, 'file': f'sources/{k}.wav', 'ok': k in made}
        for k, ks, built, why in SOURCES
    ]
    for s in srcs:
        log(f'  {s["key"]:10s} {"ok" if s["ok"] else "MISSING":7s} {s["built"]}')

    ctrl_spec = sung_pitch.spec(made['src_ctrl']) if 'src_ctrl' in made else None
    work = os.path.join(OUT, '_work')
    rows = []
    n = sum(1 for s in srcs if s['ok']) * len(SEEDS)
    i = 0
    for key, ks, _built, _why in SOURCES:
        if key not in made:
            continue
        for seed in SEEDS:
            i += 1
            tk = f'{key}_s{seed}'
            log(f'--- {i}/{n}  {tk}  (keyscale {ks})')
            plan = copy.deepcopy(base_plan)
            plan['key'] = dict(plan['key'])
            plan['key']['ace_keyscale'] = ks

            take = os.path.join(OUT, f'{tk}.mp3')
            master = os.path.join(OUT, f'{tk}_master.mp3')
            rec = {}
            got = K.ace_render(
                plan, take, seed=seed, cover_wav=made[key], log_fn=log, info=rec, should_abort=lambda: False
            )
            row = {
                'key': tk,
                'source': key,
                'seed': seed,
                'keyscale': ks,
                'ok': bool(got),
                'reason': rec.get('reason', ''),
                'mode': rec.get('mode'),
                'workflow': rec.get('workflow'),
                'file': os.path.basename(take) if got else '',
                'master': '',
                'spectral_shift_vs_ctrl': None,
                'corr': None,
                'vocal_f0_median_hz': None,
                'vocal_present_db': None,
            }
            if got:
                pre = K.prelevel(got, os.path.join(OUT, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=log)
                if pre and K._mp3(pre, master, log_fn=log, br='256k') and os.path.isfile(master):
                    row['master'] = os.path.basename(master)
                meas_on = master if row['master'] else got
                if ctrl_spec is not None:
                    sh, corr = sung_pitch.shift_semitones(ctrl_spec, meas_on)
                    row['spectral_shift_vs_ctrl'] = round(sh, 2)
                    row['corr'] = round(corr, 4)
                f0, ratio, err = measure(meas_on, os.path.join(work, tk))
                row['vocal_f0_median_hz'] = f0
                row['vocal_present_db'] = ratio
                if err:
                    row['reason'] = err
                log(
                    f'    shift {row["spectral_shift_vs_ctrl"]} st '
                    f'(corr {row["corr"]})  vocal F0 {f0} Hz  '
                    f'stem {ratio} dB'
                )
            else:
                log(f'    FAILED: {row["reason"]}')
            rows.append(row)
            json.dump(
                {
                    'song': 'The Farmyard Sounds Song',
                    'job': '0fc29420eb5a',
                    'mode': 'cover (ReferenceTimbreAudio)',
                    'workflow': K.ACE_WORKFLOW_COVER,
                    'seeds': SEEDS,
                    'sources': srcs,
                    'takes': rows,
                },
                open(os.path.join(OUT, 'index.json'), 'w'),
                indent=1,
            )
            open(os.path.join(OUT, 'listen.html'), 'w').write(html(rows, srcs))

    for f in os.listdir(OUT):
        if f.startswith('_') and f.endswith('.wav'):
            try:
                os.remove(os.path.join(OUT, f))
            except OSError as _exc:
                _zyg_log.debug('intermediate render cleanup skipped: %s', _exc)
    shutil.rmtree(work, ignore_errors=True)

    log('=== SUMMARY ===')
    for r in rows:
        log(
            f'{r["key"]:26s} shift {str(r["spectral_shift_vs_ctrl"]):>6s} st '
            f'corr {str(r["corr"]):>7s}  F0 {str(r["vocal_f0_median_hz"]):>8s} Hz '
            f'stem {str(r["vocal_present_db"]):>7s} dB '
            f'{"" if r["ok"] else "FAILED " + r["reason"]}'
        )

    try:
        from zyg_workflows import comfy_offload

        comfy_offload.comfy_free(log_fn=log)
    except Exception as e:  # noqa: BLE001
        log(f'vram release failed: {type(e).__name__}: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
