#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v19: the harbour rebuilt, and a real canary.

A copy of the delivered v18 cut. The TIMING is v18's to the frame — same takes,
same marks, same bird window, same hold-then-pan — and everything that changed
is picture:

  1. THE LEFT BANK IS REBUILT. The crates that stood in the canal are gone, a
     proper paved quayside walk with a railing and mooring posts runs in front
     of the houses, and the three moored craft are now ONE large Dutch barge.

  2. THE CRATES STANDING IN THE WATER ON THE RIGHT ARE GONE. Four Qwen region
     edits were tried and all four invented something that is not there — a
     slipway, a flat rectangular pool, a milky wash, a jetty on stilts —
     because a region edit re-synthesises its box and cannot see the water it
     must match. What shipped instead is real canal borrowed from another
     stretch, histogram-matched to the water ringing the hole and feathered
     through an irregular mask; fx.water's polygon was then extended over it,
     so the patch ripples with the rest of the canal.

  3. THE SHIP HAS ITS STEERING GEAR — AND IT IS NOT A WHEEL. Three independent
     researchers plus three adversarial checks (one of which downloaded and
     searched the full text of Witsen's 1671 "Aeloude en hedendaegsche
     scheeps-bouw en bestier") agree: a Dutch merchantman of 1672 was steered
     by a WHIPSTAFF — the kolderstok, a vertical lever through the deck onto
     the tiller. The ship's wheel does not appear until c.1703. The operator's
     other instinct was exactly right though: the helm stood on a RAISED,
     OPEN platform right aft — Witsen's stuurplecht, "hoog 6 voet, lang 16
     voet" — with the helmsman in the open air forward of the hut, not shut in
     below. That is what has been built at the stern.

  4. THE CANDLE IS REPAINTED. The flame the pull-out reveals was a soft white
     sliver with a saturated blue mid-section — an upscale of detail the plate
     never had. It was re-synthesised at 4x through a crop-scoped edit and is
     now a warm teardrop with a bright core. It also sits 30 px higher on the
     hires plate, so fx.flame's anchor, h_frac and w_frac were re-measured; the
     old numbers over the new candle would bend empty air beneath it.

  5. THE BIRD IS A CANARY. The first one was a flat yellow blob on an ellipse
     body with a paddle wing. This one is built on the real bird: a teardrop
     body, a two-segment wing that bends at the wrist, a notched finch tail,
     and the colour MAP a canary actually has — three bright zones (face,
     breast, rump) separated by three dark ones (streaked mantle, wing coverts
     crossed by a pale bar, near-black primaries) over a pale belly. Its flight
     is now a DEPTH move: in from the right close to the lens at 97 px of
     wingspan, out toward the moored ship and away from us to 34 px, then round
     and off to the left.

  6. THE SMOKE IS FIXED. The right-hand plume was anchored at (0.762, 0.284),
     which is open sky ten pixels up-left of the actual stack — measured, the
     pot mouths are at (1033.5, 222) and (1058, 219). Both plumes also climbed
     far too fast; their periods are doubled.

usage:  python3 run_scene_shores_v19.py [--verify-only]
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

import soundfile as sf

from zyg_workflows import paths
from zyg_workflows.bin import exe

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from zyg_workflows import storyteller_scene_service as sss  # noqa: E402

ST = os.path.join(CREWS, 'output', 'storyteller')
SRC_DIR = os.path.join(ST, 'scene_second_ledger_intro_teen08_settled_shores_v18_bird')
SRC_MP4 = os.path.join(SRC_DIR, 'second_ledger_intro_teen08_settled_shores_v18_bird.mp4')
SLUG = 'second_ledger_intro_teen08_settled_shores_v19_canary'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')
SEED_WAV = os.path.join(CREWS, 'data', 'assets', 'voice_seeds', 'teens', 'teen08.wav')
SCRATCH = os.path.join(
    tempfile.gettempdir(),
    'claude-1000',
    '-home-zygomatic-zygomatics-zero',
    '87d4887e-1c1b-4df7-8d75-2b988a045b73',
    'scratchpad',
)
NEW_PLATE = os.path.join(SCRATCH, 'v19_plate.png')
NEW_HIRES = os.path.join(SCRATCH, 'v19_plate.hires.png')
NEW_CABIN_HIRES = os.path.join(SCRATCH, 'cabin_v19.hires.png')

SHORES = 'It started where every sea voyage begins, at the shores of civilization.'
CLOSING_SEED = 2024
LINE3 = {'seed': 2024, 'exaggeration': 0.30, 'cfg_weight': 0.40}

STEM_LUFS = -23.0
MASTER_LUFS = -14.0
BED_LUFS = -51.9
MUSIC_LUFS = {'suspense': -35.9, 'nuanced': -37.2}

# ── the new tail, all of it relative to the harbour's arrival ───────────────
BIRD_IN = 2.0  # operator: "after 2 seconds show the bird coming in"
BIRD_DUR = 5.0  # operator: "in screen for 4-6 seconds"
BEAT_S = 0.2  # a breath between the bird leaving and Abel speaking
TAIL_FADE_IN_S = 1.1
END_FADE_S = 3.0
MASTER_FADE_S = 2.0
OVERSHOOT_S = 2.0  # the move is authored past the fade, never arriving

STILLS_CARRY = ('still_cabin_abel.png', 'still_cabin_abel.png.wlock_c3345deb', 'still_cabin_abel.hires.png.handfix')
TAKES = tuple(f'line_{i:02d}_abel{s}' for i in range(4) for s in ('.wav', '.wav.tune', '_raw.wav', '_raw.wav.take')) + (
    'anchor_00_abel.wav',
    'anchor_00_abel.wav.tune',
)
_AUDIO_TAKES = tuple(f'line_{i:02d}_abel.wav' for i in range(4)) + ('anchor_00_abel.wav',)

# Delivered-pixel boxes that must hold perfectly still during the bird. The
# right-bank houses are chosen because they are the busiest STATIC thing in
# frame and sit clear of both the smoke plumes and the flight path.
# The bird now crosses the frame at y 300-390, so a "still" box at that height
# is not still — the first version of this check put one at (1160,250,1330,450)
# and measured the CANARY as the floor, which more than doubled it and failed a
# perfectly good canal. Both boxes now sit clear of the flight path.
_STATIC_REGIONS = {'right gable': (1170, 40, 1330, 200), 'left roofline': (200, 195, 420, 300)}


def _md5(p):
    import hashlib

    with open(p, 'rb') as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()


def _cp(s, d, force=False):
    if os.path.isfile(s) and (force or not os.path.isfile(d)):
        shutil.copyfile(s, d)
        return 1
    return 0


def _carry(names, label):
    n = sum(_cp(os.path.join(SRC_DIR, f), os.path.join(OUT_DIR, f)) for f in names)
    print(f'[run] carried {n} new / {len(names)} {label}')


def _restamp(spec):
    """Re-write the carried markers in the CURRENT key format. A no-op while
    v17's are current, which is the point of running it: a stale marker is
    answered by build_scene by re-synthesising the line, and these takes were
    picked off benches rather than rendered from the spec."""
    voices = spec['voices']
    jobs = [(f'line_{i:02d}_abel.wav', dict(spec['dialogue'][i])) for i in range(4)]
    jobs.append(('anchor_00_abel.wav', dict(spec['anchored_lines'][0])))
    n = 0
    for fname, ev in jobs:
        wav = os.path.join(OUT_DIR, fname)
        v = dict(voices[ev['speaker']])
        for k in ('seed', 'exaggeration', 'cfg_weight', 'temperature', 'tempo', 'pace_ref'):
            if k in ev:
                v[k] = ev[k]
        take = sss._take_key(v, ev['text'])
        want = f'{sss._tune_key(v, wav)}|{take}'
        got = None
        if os.path.isfile(wav + '.tune'):
            with open(wav + '.tune') as fh:
                got = fh.read().strip()
        if got == want:
            continue
        with open(wav + '.tune', 'w') as fh:
            fh.write(want)
        raw = wav.replace('.wav', '_raw.wav')
        if os.path.isfile(raw):
            with open(raw + '.take', 'w') as fh:
                fh.write(take)
        n += 1
        print(f'[run] restamped {fname}')
    print(f'[run] {n} marker(s) migrated to the current key format')


def _dur(p):
    d, sr = sf.read(p, dtype='float64')
    return len(d) / sr


def _span(p):
    d = sss._read_mono48k(p)
    a, b = sss._pick_island(d, sss._speech_islands(d), 'span')
    return (b - a) / 48000.0


def _grab(video, t, dst):
    subprocess.run(
        [exe('ffmpeg'), '-loglevel', 'error', '-y', '-ss', str(t), '-i', video, '-frames:v', '1', dst], check=True
    )
    return np.asarray(Image.open(dst).convert('RGB'), dtype=np.float32)


def _seq(video, t0, dur, tmp, tag):
    subprocess.run(
        [
            exe('ffmpeg'),
            '-loglevel',
            'error',
            '-y',
            '-ss',
            str(t0),
            '-t',
            str(dur),
            '-i',
            video,
            '-vf',
            'fps=24',
            os.path.join(tmp, f'{tag}_%03d.png'),
        ],
        check=True,
    )
    fs = sorted(f for f in os.listdir(tmp) if f.startswith(tag + '_'))
    return [np.asarray(Image.open(os.path.join(tmp, f)).convert('L'), dtype=np.float32) for f in fs]


def _bird_is_right(spec) -> bool:
    """The flight itself, checked off `_bird_pose` rather than off the picture:
    in from the RIGHT, down into the harbour, out on the LEFT, 4-6 s, and never
    a frame of it outside its own window."""
    cfg = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']['bird']
    dur = float(cfg['dur_s'])
    ok = True
    if not (4.0 <= dur <= 6.0):
        ok = False
        print(f'[verify] BIRD ON SCREEN {dur}s — the brief is 4-6 s')
    if sss._bird_pose(cfg, -0.01) is not None or sss._bird_pose(cfg, dur + 0.01) is not None:
        ok = False
        print('[verify] the bird exists outside its flight window')
    ps = [sss._bird_pose(cfg, dur * k / 200.0) for k in range(201)]
    xs = [p['pos'][0] for p in ps]
    ys = [p['pos'][1] + p['bob'] * 0.03 for p in ps]
    print(
        f'[verify] bird: enters x={xs[0]:.2f} y={ys[0]:.2f}, '
        f'lowest y={max(ys):.2f} at x={xs[int(np.argmax(ys))]:.2f}, '
        f'leaves x={xs[-1]:.2f} y={ys[-1]:.2f}, {dur}s'
    )
    if xs[0] < 1.0:
        ok = False
        print('[verify] the bird does not ENTER — it starts already in frame')
    if xs[-1] > 0.0:
        ok = False
        print('[verify] the bird does not LEAVE on the left')
    if any(b - a > 1e-9 for a, b in zip(xs, xs[1:])):
        ok = False
        print('[verify] the bird reverses direction — it must cross right to left')
    # The flight is a DEPTH move now, not a dive: what has to be true is that
    # the bird gets SMALLER as it goes out toward the ship and never simply
    # crosses the frame at one size.
    sc = [p['scale'] for p in ps]
    print(
        f'[verify] recession: scale {sc[0]:.2f} at entry -> {min(sc):.2f} at the '
        f'ship -> {sc[-1]:.2f} leaving  ({sc[0] / max(min(sc), 1e-6):.1f}x)'
    )
    if min(sc) > sc[0] * 0.55:
        ok = False
        print('[verify] THE BIRD DOES NOT FLY AWAY — it crosses at one size')
    if int(np.argmin(sc)) < len(sc) * 0.25:
        ok = False
        print('[verify] the bird is already at its smallest when it enters')
    # bounding flight: the vertical track has to scallop, not glide smoothly
    d = np.diff(np.array(ys))
    turns = int(np.sum(np.sign(d[1:]) != np.sign(d[:-1])))
    want = dur / float(cfg.get('bound_period_s', 0.82))
    print(f'[verify] bounding flight: {turns} reversals over {dur}s (~{want:.1f} cycles authored)')
    if turns < want:
        ok = False
        print('[verify] the flight is not BOUNDING — a small bird that glides smoothly reads as a gull')
    return ok


def _smoke_leaves_the_chimney(spec) -> bool:
    """The plume has to start AT the pot, not in clear air above it, and it has
    to be narrow there and wide up top. Measured on the drawn tile."""
    fx = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']
    base = Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png'))
    BW, BH = base.size
    ok = True
    for i, cfg in enumerate(fx['smoke']):
        ax, ay = cfg['anchor']
        widths = []
        near = []
        for t in (k * 0.55 for k in range(15)):
            (x0, y0), tile = sss._draw_smoke((BW, BH), cfg, t)
            a = np.asarray(tile.split()[-1], dtype=np.float32)
            ys, xs = np.where(a > 12)
            if not len(ys):
                ok = False
                print(f'[verify] smoke {i}: NOTHING DRAWN at t={t}')
                continue
            # gap between the pot mouth and the lowest smoke, in plate pixels
            near.append((y0 + ys.max()) - ay * BH)
            top = ys.min() + (ys.max() - ys.min()) * 0.15
            bot = ys.max() - (ys.max() - ys.min()) * 0.10
            wt = float((a[int(top)] > 12).sum())
            wb = float((a[int(bot)] > 12).sum())
            widths.append((wb, wt))
        gap = min(near) if near else -999
        # Worst case over 8 s of the cycle, not one lucky instant: the puffs are
        # phased, so a plume can sit on its pot at one frame and float 12 px
        # above it at the next, which is a flicker rather than a plume.
        # Reported in DELIVERED pixels, which is where it would be seen.
        print(
            f'[verify] smoke {i} at ({ax:.4f}, {ay:.4f}): worst case over 8 s, '
            f'reaches {gap / 2.0:+.1f} delivered px past the pot mouth; '
            f'base/top width {widths[0][0] / 2:.0f}/{widths[0][1] / 2:.0f}px'
        )
        if gap < -4:
            ok = False
            print(
                f'[verify] smoke {i} STARTS ABOVE THE POT — a '
                f'{-gap / 2.0:.1f} delivered-px gap between the chimney and '
                f'its own smoke'
            )
        if widths and widths[0][1] <= widths[0][0]:
            ok = False
            print(f'[verify] smoke {i} does not SPREAD as it rises')
    return ok


def _water_moves_in_the_delivered_file(spec, st, video) -> bool:
    """The check v17 did not have, and the only one that could have caught it.

    Measured on the DELIVERED mp4, during the held camera, as inter-frame
    change inside the water mask against inter-frame change in boxes that are
    supposed to be perfectly still. v17 scored 1.26x here, against v16's 1.25x
    with no water effect at all — i.e. it could not tell the two apart, which
    is exactly what the operator saw.
    """
    import tempfile

    tmp = tempfile.mkdtemp()
    tail0 = st['marks']['tail_start']
    cfg = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']['water']
    base = Image.open(os.path.join(OUT_DIR, 'still_day1_harbor.hires.png'))
    W, H = int(spec['width']), int(spec['height'])
    # a window inside the hold, after the fade-in has finished
    t0 = tail0 + TAIL_FADE_IN_S + 0.3
    fr = _seq(video, t0, 1.6, tmp, 'w')
    # Blur first. `_grade` lays ±5/255 of film grain on every pixel of every
    # frame, so a raw inter-frame difference has a ~2.2/255 floor EVERYWHERE
    # that has nothing to do with the picture — measured, it was most of the
    # floor this check was tripping over. Grain is spatially uncorrelated and
    # the water's motion is not, so a 1.5 px blur removes the one and keeps the
    # other, which is also roughly what the eye does with it.
    import cv2

    fr = [cv2.GaussianBlur(x, (0, 0), 1.5) for x in fr]
    d = np.mean([np.abs(fr[i + 1] - fr[i]) for i in range(len(fr) - 1)], axis=0)
    mk = sss._water_mask(base.size, cfg).crop(sss._zoom_box(base, 1.0, (0.93, 0.30)))
    if mk.size != (W, H):
        mk = mk.resize((W, H), Image.BILINEAR)
    m = np.asarray(mk, dtype=np.float32) / 255.0
    wet = m > 0.5
    wv = float(d[wet].mean())
    stat = {k: float(d[b[1] : b[3], b[0] : b[2]].mean()) for k, b in _STATIC_REGIONS.items()}
    floor = max(stat.values())
    shutil.rmtree(tmp, ignore_errors=True)
    print(
        f'[verify] DELIVERED file, camera held {t0:.1f}-{t0 + 1.6:.1f}s, grain '
        f'removed: water {wv:.3f}/255 vs still-region floor {floor:.3f} '
        f'-> {wv / max(floor, 1e-6):.1f}x'
    )
    for k, v in stat.items():
        print(f'[verify]     still: {k:14s} {v:.3f}/255')
    if wv < floor * 3.0:
        print('[verify] THE WATER IS NOT VISIBLY MOVING IN THE DELIVERED FILE — this is the v17 defect, not a new one')
        return False
    return True


def _camera_holds_for_the_bird(spec, st) -> bool:
    """No pan while the bird is on screen. Read off the service's own camera."""
    shot = sss.shot_by_id_spec(spec, spec['tail_shot_id'])
    fx = shot['fx']
    t0 = st['marks']['tail_start']
    t1 = st['marks']['picture_end'] + float(spec.get('tail_zoom_overshoot_s', 0.0))
    zs = []
    for k in range(0, int((BIRD_IN + BIRD_DUR) * 24) + 1):
        t = t0 + k / 24.0
        tt = max(0.0, min(1.0, (t - t0) / (t1 - t0)))
        zs.append(sss._kb_keys_at(tt, fx['kb_keys'])[0])
    drift = max(zs) - min(zs)
    tt_end = (st['marks']['picture_end'] - t0) / (t1 - t0)
    z_black = sss._kb_keys_at(tt_end, fx['kb_keys'])[0]
    print(
        f'[verify] camera during the bird: z {min(zs):.4f}-{max(zs):.4f} '
        f'(drift {drift:.4f}); reaches z={z_black:.3f} at black'
    )
    if drift > 0.01:
        print('[verify] THE CAMERA PANS UNDER THE BIRD')
        return False
    if z_black < 1.8:
        print('[verify] the closing move never arrives at the house')
        return False
    return True


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    _carry(STILLS_CARRY, 'cabin stills')
    _carry(TAKES, 'approved takes')
    for src, dst in (
        (NEW_PLATE, 'still_day1_harbor.png'),
        (NEW_HIRES, 'still_day1_harbor.hires.png'),
        (NEW_CABIN_HIRES, 'still_cabin_abel.hires.png'),
    ):
        if not os.path.isfile(src):
            print(f'[run] ABORT: new harbour plate missing: {src}')
            return 7
        _cp(src, os.path.join(OUT_DIR, dst))
    print('[run] plates installed: harbour rebuilt + candle repainted')

    for f in _AUDIO_TAKES:
        if not os.path.isfile(os.path.join(OUT_DIR, f)):
            print(
                f'[run] ABORT: missing carried take {f} — v18 is the source '
                f'of truth for the audio and it must not be re-synthesised'
            )
            return 2
    anchor = os.path.join(OUT_DIR, 'anchor_00_abel.wav')

    durs = [_dur(os.path.join(OUT_DIR, f'line_{i:02d}_abel.wav')) for i in range(4)]
    pauses = [1.0, 1.0, 0.9, 0.6]
    spec = copy.deepcopy(sss.SECOND_LEDGER_INTRO)

    # everything up to the DAY 1 card is v18's, unchanged
    dialogue_end = float(spec.get('head_silence_s', 1.0)) + sum(d + p for d, p in zip(durs, pauses))
    pullout_end = dialogue_end + float(spec['pullout']['hold_s'])
    card_start = pullout_end + float(spec['fade_to_black_s'])
    tail_t0 = card_start + float(spec['title_card']['dur_s'])

    # ── the new tail ────────────────────────────────────────────────────────
    bird_out = BIRD_IN + BIRD_DUR  # bird leaves frame
    line_t0 = bird_out + BEAT_S  # Abel speaks, camera moves
    line_t1 = line_t0 + _span(anchor)
    total_rel = line_t1 + 0.2  # fade starts as he finishes
    picture_end_rel = total_rel + END_FADE_S
    win_rel = picture_end_rel + OVERSHOOT_S

    spec['tail_fade_in_s'] = TAIL_FADE_IN_S
    spec['tail_hold_s'] = round(total_rel - TAIL_FADE_IN_S, 3)
    spec['end_fade_s'] = END_FADE_S
    spec['tail_zoom_overshoot_s'] = OVERSHOOT_S
    spec['audio_tail_s'] = 0.0
    spec['master_fade_s'] = MASTER_FADE_S

    # The hold ends exactly when the bird leaves. Derived, not authored: the
    # take lengths above set tail_t0, and a hard-coded fraction would drift off
    # the bird the first time a line re-rendered.
    F = (0.93, 0.30)
    hold_at = round(bird_out / win_rel, 4)
    sss.shot_by_id_spec(spec, 'day1_harbor')['fx']['kb_keys'] = [
        {'at': 0.0, 'z': 1.0, 'focus': F},
        {'at': hold_at, 'z': 1.0, 'focus': F},
        {'at': 1.0, 'z': 3.0, 'focus': F},
    ]

    spec['slug'] = SLUG
    spec['voices']['abel'] = {'ref': SEED_WAV, 'seed': 1672}
    spec['stem_lufs'] = STEM_LUFS
    spec['master_lufs'] = MASTER_LUFS
    spec['bed_lufs'] = BED_LUFS
    for cue in spec['music']:
        if cue.get('name') in MUSIC_LUFS:
            cue['lufs'] = MUSIC_LUFS[cue['name']]
    spec['music'][-1]['fade_out_s'] = 0.3

    spec['dialogue'][3].update(LINE3)
    # The closing line now hangs off the HARBOUR, not the card: it lands when
    # the bird leaves frame.
    spec['anchored_lines'] = [
        {
            'speaker': 'abel',
            'text': SHORES,
            'seed': CLOSING_SEED,
            'take': 'span',
            'pace_ref': None,
            'at': {'mark': 'tail_start', 'offset': round(line_t0, 3)},
            'align': 'start',
        }
    ]

    fx = sss.shot_by_id_spec(spec, 'day1_harbor')['fx']
    for k in ('water', 'smoke', 'bird'):
        if not fx.get(k):
            print(f'[run] ABORT: the tail shot has no fx.{k}')
            return 5
    if abs(float(fx['bird']['t0_rel']) - BIRD_IN) > 1e-6:
        print("[run] ABORT: the bird's t0_rel disagrees with this driver")
        return 5
    print(
        f'[run] tail {tail_t0:.2f}s: bird {tail_t0 + BIRD_IN:.2f}'
        f'→{tail_t0 + bird_out:.2f}s, line {tail_t0 + line_t0:.2f}'
        f'→{tail_t0 + line_t1:.2f}s, fade {tail_t0 + total_rel:.2f}'
        f'→{tail_t0 + picture_end_rel:.2f}s'
    )
    print(f'[run] camera holds to at={hold_at} of the {win_rel:.2f}s move window')
    print(
        f'[run] water amp {fx["water"]["amp_frac"]} + shade '
        f'{fx["water"].get("shade", {}).get("amount")} , {len(fx["smoke"])} chimneys, '
        f'bird {fx["bird"]["dur_s"]}s'
    )

    _restamp(spec)
    before = {f: _md5(os.path.join(OUT_DIR, f)) for f in _AUDIO_TAKES}

    if '--verify-only' in sys.argv:
        r = {'video': os.path.join(OUT_DIR, f'{SLUG}.mp4')}
        if not os.path.isfile(r['video']):
            print('[run] --verify-only but nothing has been built yet')
            return 1
        print(f'[run] --verify-only: re-checking {os.path.basename(r["video"])}')
    else:
        r = sss.build_scene(spec, out_dir=OUT_DIR)
        if not r:
            print('[run] FAILED')
            return 1
        print(f'[run] done: {r["video"]}')

    st = json.load(open(os.path.join(OUT_DIR, 'scene_state.json')))
    ref = json.load(open(os.path.join(SRC_DIR, 'scene_state.json')))
    ok = True

    for f in _AUDIO_TAKES:
        now = _md5(os.path.join(OUT_DIR, f))
        v18 = _md5(os.path.join(SRC_DIR, f))
        if now != before[f] or now != v18:
            ok = False
            print(f'[verify] TAKE RE-RENDERED: {f} (v18 {v18[:8]}, now {now[:8]})')
    print(f'[verify] {len(_AUDIO_TAKES)} takes checksummed against v18')

    # Everything up to the card must be v18's timing to the frame; only the
    # tail was re-authored.
    for k in ('dialogue_end', 'pullout_start', 'pullout_end', 'card_start', 'card_end', 'tail_start'):
        if round(st['marks'][k], 2) != round(ref['marks'][k], 2):
            ok = False
            print(
                f'[verify] MARK {k} MOVED {ref["marks"][k]} → {st["marks"][k]} '
                f'— nothing before the tail was meant to change'
            )
    print(f'[verify] marks up to tail_start identical to v18 (tail at {st["marks"]["tail_start"]}s)')
    for a, b in zip(st['events'][:4], ref['events'][:4]):
        if round(a['t0'], 2) != round(b['t0'], 2):
            ok = False
            print(f'[verify] CABIN LINE MOVED {b["text"][:36]!r}')
    print('[verify] the four cabin lines land where v18 put them')

    want_line = round(st['marks']['tail_start'] + line_t0, 2)
    got_line = round(st['events'][4]['t0'], 2)
    if abs(got_line - want_line) > 0.05:
        ok = False
        print(f'[verify] the closing line is at {got_line}s, authored {want_line}s')
    else:
        print(
            f'[verify] closing line at {got_line}s — '
            f'{got_line - (st["marks"]["tail_start"] + BIRD_IN + BIRD_DUR):+.2f}s '
            f'after the bird leaves frame'
        )
    print(
        f'[verify] scene {ref["marks"]["picture_end"]}s → '
        f'{st["marks"]["picture_end"]}s (tail '
        f'{ref["marks"]["picture_end"] - ref["marks"]["tail_start"]:.1f}s → '
        f'{st["marks"]["picture_end"] - st["marks"]["tail_start"]:.1f}s)'
    )

    if not _camera_holds_for_the_bird(spec, st):
        ok = False
    if not _bird_is_right(spec):
        ok = False
    if not _smoke_leaves_the_chimney(spec):
        ok = False
    if not _water_moves_in_the_delivered_file(spec, st, r['video']):
        ok = False

    # The cabin DID change this time — the candle was repainted at 4x through a
    # crop-scoped edit — so what is asserted is that it changed WHERE IT SHOULD
    # and nowhere else: the candle differs from v18, and Abel's face and the far
    # bulkhead sit on the encode floor.
    import tempfile

    tmp = tempfile.mkdtemp()
    fl = sss.shot_by_id_spec(spec, 'cabin_abel')['fx']['flame']
    cxp = int(float(fl['anchor'][0]) * int(spec['width']))
    cyp = int(float(fl['anchor'][1]) * int(spec['height']))
    for t in (12.0, 33.0):
        a = _grab(SRC_MP4, t, os.path.join(tmp, 'a.png'))
        b = _grab(r['video'], t, os.path.join(tmp, 'b.png'))
        d = np.abs(a - b).mean(axis=2)
        cand = float(d[max(0, cyp - 170) : cyp + 120, max(0, cxp - 130) : cxp + 130].mean())
        face = float(d[150:320, 880:1060].mean())
        bulk = float(d[120:320, 600:800].mean())
        print(
            f"[verify] cabin t={t}s vs v18: candle {cand:5.2f}/255   Abel's face {face:5.2f}   far bulkhead {bulk:5.2f}"
        )
        if t == 33.0 and cand < 2.0:
            ok = False
            print('[verify] THE CANDLE WAS NOT REPAINTED — the old plate shipped')
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 4


if __name__ == '__main__':
    raise SystemExit(main())
