#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Assemble the Zygomatic Ai intro.

Stages (run one at a time so the single GPU job rule is never broken)::

    intro_assemble.py finish     # rife 24fps -> esrgan x2 -> scale 1920x1080
    intro_assemble.py plate      # assemble w/o title -> ramped last frame -> end_plate.png
    intro_assemble.py title      # write_words_in_sand -> words.png
    intro_assemble.py swirl      # swirl_in -> title.mp4
    intro_assemble.py dust       # placement record -> composite -> title_fx.mp4
    intro_assemble.py final      # full shot list + audio -> final_1080p.mp4
    intro_assemble.py receipt    # contact sheet + receipt.json

Licence: RIFE v4.6 / RealESRGAN / Qwen-Image-Edit-2511 Apache-2.0 or BSD,
the dust element is CC0 (JangaFX), every audio file is CC0/CC-BY with a
licence sidecar that video_audio checks.  No FLUX on this path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
sys.path.insert(0, CREWS)

OUT = os.path.join(CREWS, 'output', 'video_studio', 'intro_zygomatic_ai')
DUST = os.path.join(CREWS, 'data', 'asset_libraries', 'vfx_volumes', 'grenadedustimpactvdb_4k.mov')

WORDS = 'Zygomatic Ai'
FPS = 24
SIZE = [1920, 1080]
XFADE = 0.18
FADE_IN = 4.0
FADE_OUT = 3.0
RAMP = {'tail_s': 0.8, 'end_speed': 0.12}
SWIRL_DUR = 1.5
SWIRL_HOLD = 5.0

P = lambda *a: os.path.join(OUT, *a)


def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('cmd failed: %s\n%s' % (' '.join(cmd[:6]), r.stderr[-2000:]))
    return r.stdout


def probe_dur(path):
    return float(sh(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]).strip())


# ---------------------------------------------------------------- stage: finish
def stage_finish():
    from zyg_workflows import video_finish as F

    rec = {}
    for k in (1, 2, 3):
        src = P('shot%d.mp4' % k)
        rif = P('_shot%d_rife.mp4' % k)
        esr = P('_shot%d_esr.mp4' % k)
        fin = P('shot%d_fin.mp4' % k)
        log('shot%d: rife' % k)
        r1 = F.rife_2x(src, rif, out_fps=FPS, log=log)
        log('shot%d: rife %s' % (k, r1))
        log('shot%d: esrgan' % k)
        r2 = F.esrgan_clip(rif, esr, scale=2, log=log)
        log('shot%d: esrgan %s' % (k, r2))
        sh(
            [
                'ffmpeg',
                '-y',
                '-v',
                'error',
                '-i',
                esr,
                '-vf',
                'scale=1920:1080:flags=lanczos',
                '-r',
                str(FPS),
                '-c:v',
                'libx264',
                '-crf',
                '16',
                '-preset',
                'slow',
                '-pix_fmt',
                'yuv420p',
                fin,
            ]
        )
        rec['shot%d' % k] = {'rife': r1, 'esrgan': r2, 'fin': F.probe(fin)}
        log('shot%d: fin %s' % (k, rec['shot%d' % k]['fin']))
        for tmp in (rif, esr):
            os.remove(tmp)
    json.dump(rec, open(P('_finish.json'), 'w'), indent=1)
    print(json.dumps(rec, indent=1))


# ----------------------------------------------------------------- shot lists
def _footage_shots():
    """The three finished shots, shot 3 carrying the halt ramp."""
    return [
        {'path': P('shot1_fin.mp4'), 'xfade_s': XFADE},
        {'path': P('shot2_fin.mp4'), 'xfade_s': XFADE},
        {'path': P('shot3_fin.mp4'), 'speed_ramp': dict(RAMP), 'xfade_s': XFADE},
    ]


# ----------------------------------------------------------------- stage: plate
def stage_plate():
    from zyg_workflows import video_assembly as A

    shotlist = {
        'fps': FPS,
        'size': SIZE,
        'shots': _footage_shots(),
        'fade_in_s': 0.0,
        'fade_out_s': 0.0,
        'fade_color': 'black',
        'audio': None,
    }
    rec = A.assemble(shotlist, P('_footage_only.mp4'), log=log)
    json.dump(rec, open(P('_footage_only.json'), 'w'), indent=1)
    # the ramped shot's last frame, full resolution, no fade on it
    sh(
        [
            'ffmpeg',
            '-y',
            '-v',
            'error',
            '-sseof',
            '-0.08',
            '-i',
            P('_footage_only.mp4'),
            '-vframes',
            '1',
            '-vf',
            'scale=1920:1080',
            P('end_plate.png'),
        ]
    )
    log('end_plate.png written')
    print(json.dumps(rec, indent=1))


# ----------------------------------------------------------------- stage: title
def stage_title():
    from zyg_workflows import sand_title_fx as S

    r = S.write_words_in_sand(P('end_plate.png'), WORDS, P('words.png'), seeds=6, log=log)
    log('pass 1: %s' % r)
    if not r.get('exact'):
        log('not exact after 6 seeds - 6 more with the legibility suffix')
        r2 = S.write_words_in_sand(
            P('end_plate.png'),
            WORDS,
            P('words.png'),
            seeds=6,
            log=log,
            extra_instruction=', the letters clearly legible and evenly spaced',
            first_seed=90001,
        )
        log('pass 2: %s' % r2)
        if r2.get('exact') or not r.get('exact'):
            r = r2 if (r2.get('exact') or r2.get('conf', 0) >= r.get('conf', 0)) else r
    json.dump(r, open(P('_title.json'), 'w'), indent=1, default=str)
    print(json.dumps(r, indent=1, default=str))


# ----------------------------------------------------------------- stage: swirl
def stage_swirl():
    from zyg_workflows import sand_title_fx as S

    n = S.swirl_in(
        P('end_plate.png'), P('words.png'), P('title.mp4'), fps=FPS, dur_s=SWIRL_DUR, hold_s=SWIRL_HOLD, log=log
    )
    log('swirl frames=%s dur=%.3f' % (n, probe_dur(P('title.mp4'))))


# ------------------------------------------------------------------ stage: dust
def letters_bbox():
    """Pixel bbox of the lettering in words.png, and the frame size.

    `letters_mask` is not usable for this plate: Qwen-Image-Edit re-rendered
    65 % of the picture, so the mask's largest component is the whole frame.
    The OCR detector's own region boxes are what actually bound the letters,
    and they are the same boxes `lettering_crop` trusts.  The mask is the
    fallback for the case where the detector finds nothing at all.
    """
    import numpy as np
    from zyg_workflows import sand_title_fx as S
    from PIL import Image

    W, H = Image.open(P('words.png')).size
    regs = S._regions(P('words.png'))
    if regs:
        xs = [r['bbox'][0] for r in regs] + [r['bbox'][2] for r in regs]
        ys = [r['bbox'][1] for r in regs] + [r['bbox'][3] for r in regs]
        box = (min(xs) / 1000.0 * W, min(ys) / 1000.0 * H, max(xs) / 1000.0 * W, max(ys) / 1000.0 * H)
        src = 'ocr_regions'
    else:
        m = S.letters_mask(P('end_plate.png'), P('words.png'))
        my, mx = np.nonzero(m)
        if mx.size == 0:
            raise RuntimeError('no letters found to place dust around')
        box = (float(mx.min()), float(my.min()), float(mx.max()), float(my.max()))
        src = 'letters_mask'
    return [int(round(v)) for v in box], (W, H), src


def dust_record():
    """5 dust impacts placed off the letters' own bounding box."""
    (x0, y0, x1, y1), (W, H), src = letters_bbox()
    w = float(x1 - x0)
    pad = 0.15 * w
    # spread across bbox +/- 15 % of its width, kept inside the frame: this
    # title fills the frame edge to edge, so the padded range is clipped.
    lo = max(x0 - pad, 0.06 * W)
    hi = min(x1 + pad, 0.94 * W)
    span = hi - lo
    # 2 above the bbox (dust rising off the top of the letters), 3 below it
    pts = [
        (lo + 0.20 * span, y0, 0.085, 0.20),  # above, left
        (lo + 0.72 * span, y0, 0.095, 0.55),  # above, right
        (lo + 0.05 * span, y1, 0.140, 0.90),  # below, left
        (lo + 0.50 * span, y1, 0.110, 1.30),  # below, centre
        (lo + 0.95 * span, y1, 0.125, 1.80),  # below, right
    ]
    layers = []
    for px, py, h, t in pts:
        layers.append(
            {
                'element': DUST,
                'x': round(px / W, 4),
                'y': round(py / H, 4),
                'anchor': 'bottom-center',
                'height': h,
                'start_s': t,
                'loop': False,
                'speed': 0.6,
                'opacity': 0.9,
                'warm': [1.0, 0.93, 0.80],
            }
        )
    rec = {
        'layers': layers,
        'draft': {'width': 480, 'fps': 12},
        '_bbox': [x0, y0, x1, y1],
        '_frame': [W, H],
        '_bbox_from': src,
    }
    return rec


def stage_dust(draft=False):
    from zyg_workflows import video_overlay as V

    rec = dust_record()
    json.dump(rec, open(P('dust_record.json'), 'w'), indent=1)
    log('bbox=%s frame=%s' % (rec['_bbox'], rec['_frame']))
    if draft:
        r = V.composite(P('title.mp4'), rec, P('_dust_draft.mp4'), draft=True, log=log)
        log('draft %s' % r)
        sh(
            [
                'ffmpeg',
                '-y',
                '-v',
                'error',
                '-i',
                P('_dust_draft.mp4'),
                '-vf',
                "select='eq(n\\,8)+eq(n\\,15)+eq(n\\,24)',tile=3x1",
                '-vsync',
                '0',
                '-frames:v',
                '1',
                P('_dust_draft.jpg'),
            ]
        )
        log('draft strip -> _dust_draft.jpg')
        return
    r = V.composite(P('title.mp4'), rec, P('title_fx.mp4'), draft=False, log=log)
    json.dump(r, open(P('_dust.json'), 'w'), indent=1, default=str)
    log('final %s' % r)


# ----------------------------------------------------------------- stage: final
def peak_dbfs(ref, trim_start_s=0.0, dur_s=None):
    """Peak of the segment of `ref` that the cue will actually use, in dBFS."""
    import numpy as np
    from zyg_workflows import video_audio as VA

    path, _meta = VA.resolve_library_file(ref)  # licence sidecar still decides
    cmd = ['ffmpeg', '-v', 'error']
    if trim_start_s:
        cmd += ['-ss', '%.3f' % trim_start_s]
    if dur_s:
        cmd += ['-t', '%.3f' % dur_s]
    cmd += ['-i', path, '-ac', '1', '-ar', '48000', '-f', 'f32le', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    a = np.frombuffer(raw, dtype='<f4')
    if a.size == 0:
        raise RuntimeError('no samples read from %s' % ref)
    return 20.0 * float(np.log10(max(abs(a).max(), 1e-9)))


def audio_spec(shot3_at):
    """The brief's authored balance, applied to PEAK-NORMALISED sources.

    The library is not level-matched: the sandstorm bed peaks at +2.9 dBFS
    (a brick-walled ambience) while eagle_01 peaks at -17.6.  Applying the
    brief's gains to the raw files puts the first eagle call ~24 dB under the
    bed — inaudible, undetectable by `measure_onsets`, and the summed mix
    clips, which is what forced loudnorm into its dynamic AGC.  So every
    source is first trimmed to 0 dBFS peak over the segment the cue uses, and
    the brief's gain is then applied on top, unchanged.  Every authored
    RELATIVE level survives exactly; only the sources' arbitrary recording
    levels are taken out.  (Same trap `melody_sampler` documents for the
    instrument packs.)
    """
    eagles = json.load(open(os.path.join(CREWS, 'data', 'asset_libraries', 'sfx', 'eagle_shortlist.json')))
    e1 = 'sfx/' + eagles[0]['file']
    e2 = 'sfx/' + (eagles[1]['file'] if len(eagles) > 1 else eagles[0]['file'])
    bed_f = 'foley/xyl_ambience_sand_storm.wav'
    wind_f = 'sfx/uh_ambdsgn_heavy_gusts_of_wind.wav'
    norm = {
        bed_f: peak_dbfs(bed_f),
        e1: peak_dbfs(e1),
        e2: peak_dbfs(e2),
        wind_f: peak_dbfs(wind_f, 20.0, 3.0),
    }
    log('source peaks dBFS: %s' % {k.split('/')[-1]: round(v, 2) for k, v in norm.items()})
    g = lambda ref, authored: round(authored - norm[ref], 2)
    return {
        'bed': {'file': bed_f, 'gain_db': g(bed_f, -10), 'fade_in_s': 0.5, 'fade_out_s': 3.0, 'loop': True},
        'cues': [
            {'file': e1, 'at_s': 1.0, 'gain_db': g(e1, -3), 'trim_start_s': 0, 'dur_s': None, 'fade_s': 0.05},
            {'file': e2, 'at_s': 3.0, 'gain_db': g(e2, -4), 'trim_start_s': 0, 'dur_s': None, 'fade_s': 0.05},
            {
                'file': wind_f,
                'at_s': round(shot3_at, 3),
                'gain_db': g(wind_f, -14),
                'trim_start_s': 20,
                'dur_s': 3.0,
                'fade_s': 0.5,
            },
        ],
        'duck': None,
        'target_lufs': -14.0,
        'true_peak_db': -1.0,
        '_authored_gains_db': {'bed': -10, 'eagle_1': -3, 'eagle_2': -4, 'wind': -14},
        '_source_peaks_dbfs': {k: round(v, 2) for k, v in norm.items()},
    }


def _band_envelope(wav, band):
    """20 ms RMS envelope of `wav` in dB, restricted to `band` = (lo, hi) Hz."""
    import numpy as np

    af = []
    if band[0]:
        af.append('highpass=f=%g' % band[0])
    if band[1]:
        af.append('lowpass=f=%g' % band[1])
    raw = subprocess.run(
        [
            'ffmpeg',
            '-v',
            'error',
            '-i',
            wav,
            '-af',
            ','.join(af) or 'anull',
            '-ac',
            '1',
            '-ar',
            '48000',
            '-f',
            'f32le',
            '-',
        ],
        capture_output=True,
    ).stdout
    a = np.frombuffer(raw, dtype='<f4')
    win = 960  # 20 ms at 48 kHz
    n = a.size // win
    return 20.0 * np.log10(np.sqrt(np.maximum((a[: n * win].reshape(n, win) ** 2).mean(1), 1e-12)))


def bed_relative_onsets(wav, cues, over_db=6.0):
    """Where each cue actually lands, measured against the bed under it.

    `video_audio.measure_onsets` asks for a window 12 dB over the WHOLE file's
    median — a threshold written for cues over near-silence.  Under a dense
    continuous sandstorm bed nothing clears it and every cue reads None,
    however plainly audible.  This measures what the ear does instead: in the
    cue's OWN band (an eagle screech lives above 1.8 kHz, a wind gust below
    800 Hz — judging the gust through a high-pass measures the bed, not the
    gust), take the bed level from the second before the cue, and report the
    first 20 ms window standing `over_db` above it.

    The floor is clamped to the programme's own MEDIAN window level in that
    band: the first eagle sits at 1.0 s, where the bed is still inside its
    0.5 s fade-in, and a ratio taken against that near-silence reads +76 dB
    and means nothing.  Clamped, `over_bed_db` is what it claims to be — how
    far the cue stands above the typical bed in the cue's own band.
    """
    import numpy as np

    out = []
    for at, band in cues:
        db = _band_envelope(wav, band)
        n = db.size
        i = int(round(float(at) / 0.02))
        # baseline stops 0.1 s short of the cue so the window under test never
        # contributes to the floor it is judged against
        base = db[max(0, i - 55) : max(1, i - 5)]
        floor = float(np.median(base)) if base.size else float(np.median(db))
        floor = max(floor, float(np.median(db)))
        # a cue cannot sound before it is placed: search starts at the cue
        lo, hi = max(0, i - 3), min(n, i + 100)  # -0.06 s .. +2.0 s
        seg = db[lo:hi]
        hit = np.nonzero(seg > floor + over_db)[0]
        out.append(
            {
                'onset_s': round((lo + int(hit[0])) * 0.02, 3) if hit.size else None,
                'over_bed_db': round(float(seg.max() - floor), 2),
                'method': 'bed-relative %g-%g Hz, +%g dB over local bed' % (band[0] or 0, band[1] or 24000, over_db),
            }
        )
    return out


def stage_final():
    """Picture first, then the track, levelled with level_to, then the mux.

    `video_assembly` would build and mux the audio itself, but its master is a
    bare two-pass loudnorm and on this programme ffmpeg reverts to its DYNAMIC
    AGC (short piece, a 0.5 s bed fade-in and a 3 s fade-out, a -1 dBTP
    ceiling) and lands 2.5 LU under target — measured -16.5 against -14.
    `audio_mix.level_to` is the remedy this tree already documents for that
    exact failure: gain-then-limit, iterated until the file MEASURABLY sits
    within 0.5 LU of the target.  Every gain the brief authored is untouched;
    only the master trim changes.
    """
    from zyg_workflows import audio_mix as M
    from zyg_workflows import video_assembly as A
    from zyg_workflows import video_audio as VA

    foot = json.load(open(P('_footage_only.json')))
    shot3_at = float(foot['shots'][2]['joined_at'])
    log('shot3 joined_at=%.3f' % shot3_at)
    shots = _footage_shots()
    shots.append({'path': P('title_fx.mp4')})
    spec = audio_spec(shot3_at)
    shotlist = {
        'fps': FPS,
        'size': SIZE,
        'shots': shots,
        'fade_in_s': FADE_IN,
        'fade_out_s': FADE_OUT,
        'fade_color': 'black',
        'audio': spec,
    }
    json.dump(shotlist, open(P('shotlist.json'), 'w'), indent=1)

    # picture only — the same shot list with the audio leg withheld
    mute = dict(shotlist, audio=None)
    rec = A.assemble(mute, P('_picture_only.mp4'), log=log)
    total = float(rec['total_s'])
    log('picture %.3f s' % total)

    wav = P('track.wav')
    arec = VA.build_track(spec, total, wav, log=log)
    log('track built: %s LUFS (%s)' % (arec['lufs'], arec.get('warnings')))
    # only trim when the master actually missed: level_to is 8 gain+limit
    # passes and squashes the programme's dynamics when it is not needed.
    if abs(float(arec['lufs']) + 14.0) > 0.8:
        res = {}
        ok = M.level_to(wav, target_lufs=-14.0, tp_db=-1.0, log_fn=log, result=res)
        arec['lufs'] = M.measure_lufs(wav)
        arec['level_to'] = dict(res, converged=bool(ok))
        log('level_to applied: %s -> %s LUFS' % (res.get('input_lufs'), arec['lufs']))
    else:
        arec['level_to'] = None
    # each cue judged in its own band: eagle screech high, wind gust low
    bands = [(1800.0, None), (1800.0, None), (None, 800.0)]
    for c, o in zip(arec['cues'], bed_relative_onsets(wav, list(zip([c['at_s'] for c in spec['cues']], bands)))):
        c['measured_onset_s'] = o['onset_s']
        c['onset_over_bed_db'] = o['over_bed_db']
        c['onset_method'] = o['method']
    log('final track %s LUFS, onsets %s' % (arec['lufs'], [c['measured_onset_s'] for c in arec['cues']]))

    if not VA.mux(P('_picture_only.mp4'), wav, P('_muxed.mp4'), log=log):
        raise RuntimeError('mux failed')
    # video_audio.mux does not ask for +faststart, and the delivery spec does:
    # a stream copy moves moov in front of mdat without touching a sample.
    sh(
        [
            'ffmpeg',
            '-y',
            '-v',
            'error',
            '-i',
            P('_muxed.mp4'),
            '-c',
            'copy',
            '-movflags',
            '+faststart',
            P('final_1080p.mp4'),
        ]
    )
    os.remove(P('_muxed.mp4'))
    log('faststart remux done')
    rec['audio'] = arec
    rec['out'] = P('final_1080p.mp4')
    rec['total_s'] = probe_dur(P('final_1080p.mp4'))
    json.dump(rec, open(P('_assemble.json'), 'w'), indent=1, default=str)
    print(json.dumps(rec, indent=1, default=str))


# --------------------------------------------------------------- stage: receipt
def frame_luma(path, at_s=None, from_end=False):
    """Mean luma of one frame: the first, or (from_end) the genuine last."""
    import numpy as np
    from PIL import Image

    tmp = P('_luma.png')
    if from_end:
        # -ss past the last frame decodes nothing; -sseof walks back from the
        # end and 'select=eq(n,0)' after it takes the final frame that exists.
        sh(['ffmpeg', '-y', '-v', 'error', '-sseof', '-0.5', '-i', path, '-update', '1', '-q:v', '2', tmp])
    else:
        sh(['ffmpeg', '-y', '-v', 'error', '-ss', '%.3f' % at_s, '-i', path, '-vframes', '1', tmp])
    a = np.asarray(Image.open(tmp).convert('L'), dtype=float)
    os.remove(tmp)
    return float(a.mean())


def stage_receipt():
    import numpy as np
    from PIL import Image
    from zyg_workflows import sand_title_fx as S

    rec = json.load(open(P('_assemble.json')))
    title = json.load(open(P('_title.json')))
    # read the DELIVERED words.png back, rather than trusting the stage return
    read, conf = S.read_words(P('words.png'))
    crop = S.lettering_crop(P('words.png'), P('_ocr_crop.png'))
    read_c, conf_c = S.read_words(crop) if crop else ('', 0.0)
    want = S.normalise(WORDS)
    exact = S.normalise(read) == want or S.normalise(read_c) == want
    delivered = read_c if S.normalise(read_c) == want else read
    log('OCR of delivered words.png: full=%r (%.3f) crop=%r (%.3f) exact=%s' % (read, conf, read_c, conf_c, exact))
    total = float(rec['total_s'])
    final = P('final_1080p.mp4')

    # contact sheet: 12 frames evenly across the programme, 4 x 3
    tiles = []
    for i in range(12):
        t = total * (i + 0.5) / 12.0
        f = P('_cs_%02d.png' % i)
        sh(['ffmpeg', '-y', '-v', 'error', '-ss', '%.3f' % t, '-i', final, '-vframes', '1', '-vf', 'scale=480:270', f])
        tiles.append(np.asarray(Image.open(f).convert('RGB')))
        os.remove(f)
    rows = [np.hstack(tiles[r * 4 : (r + 1) * 4]) for r in range(3)]
    Image.fromarray(np.vstack(rows)).save(P('final_sheet.jpg'), quality=92)
    log('final_sheet.jpg written')

    s = rec['shots']
    beats = {}
    for i, name in enumerate(('shot1', 'shot2', 'shot3', 'title')):
        a = float(s[i]['joined_at'])
        beats[name] = [round(a, 3), round(a + float(s[i]['dur_out']), 3)]
    title_in = beats.pop('title')[0]
    hold_start = title_in + SWIRL_DUR
    out = {
        'total_s': round(total, 3),
        'beats': {
            'shot1': beats['shot1'],
            'shot2': beats['shot2'],
            'shot3': beats['shot3'],
            'title_in': round(title_in, 3),
            'hold': [round(hold_start, 3), round(hold_start + 2.0, 3)],
            'fade_out_start': round(total - FADE_OUT, 3),
        },
        'ocr': {
            'text': delivered,
            'exact': bool(exact),
            'seed': title.get('seed'),
            'stage_text': title.get('ocr_text', ''),
            'stage_exact': bool(title.get('exact')),
        },
        'lufs': float(rec['audio']['lufs']),
        'cue_onsets': [
            {
                'file': c['file'],
                'at_s': c['at_s'],
                'measured_onset_s': c.get('measured_onset_s'),
                'over_bed_db': c.get('onset_over_bed_db'),
                'method': c.get('onset_method'),
            }
            for c in rec['audio']['cues']
        ],
        'first_frame_luma': round(frame_luma(final, 0.0), 3),
        'last_frame_luma': round(frame_luma(final, from_end=True), 3),
        'files': {
            'final': final,
            'sheet': P('final_sheet.jpg'),
            'end_plate': P('end_plate.png'),
            'words': P('words.png'),
            'title': P('title.mp4'),
            'title_fx': P('title_fx.mp4'),
            'shots_fin': [P('shot%d_fin.mp4' % k) for k in (1, 2, 3)],
            'shotlist': P('shotlist.json'),
            'dust_record': P('dust_record.json'),
        },
    }
    json.dump(out, open(P('receipt.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))


STAGES = {
    'finish': stage_finish,
    'plate': stage_plate,
    'title': stage_title,
    'swirl': stage_swirl,
    'dust_draft': lambda: stage_dust(draft=True),
    'dust': lambda: stage_dust(draft=False),
    'final': stage_final,
    'receipt': stage_receipt,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        sys.exit('usage: intro_assemble.py {%s}' % '|'.join(STAGES))
    STAGES[sys.argv[1]]()
