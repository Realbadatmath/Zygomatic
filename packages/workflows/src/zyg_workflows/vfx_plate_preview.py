#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plate previews — the short cut a plate card hover-plays, and a poster of it.

The volumes library already had this (``vfx_volume_preview``): a VDB pack has
nothing to show, so it is given one small mp4.  A PLATE has the opposite
problem — it has 4 to 43 minutes of footage and no short form of it, and the
Library board wants a card face and a two-second answer to "what is this".

**Two measurements, not two guesses.**

1. *The poster was black on 14 of 20 plates.*  ``vfx_ingest`` grabs it at a
   fixed ``-ss 3``, and every DOE film opens on leader — measured: 14 of the 20
   posters are under 2.6 KB of 480-wide JPEG, i.e. a flat black frame.  A
   library of black rectangles is a library you cannot read, so the poster is
   re-taken from the window this picks instead of from a constant.

2. *Where the effect is cannot be guessed from a fraction of the runtime, and
   the obvious metric picks the wrong thing.*  The whole film is decoded ONCE at
   2 fps into 64x36 greyscale (measured 3.2 s for a 12-minute plate — the
   analysis is not the expensive part, so there is no reason to sample instead
   of scan), giving three curves: frame-to-frame change, brightness, and how
   much picture a frame has.  `find_flash` and `pick_window` document what each
   curve is for and which wrong answer it rules out; the short version is that
   most-motion alone lands on torn tape at the end of a reel, brightest-frame
   alone lands on a white title card, and both together still land on a card
   that FADES up unless the shot is also required to keep moving afterwards.

The cut and the poster come from the SAME window, so the card's still picture is
a frame of what the hover plays rather than an unrelated part of the film.

**This is a heuristic on documentary films, not an element library, and it does
not always win.**  These are 4-to-43-minute DOE films with narration, titles and
long stretches of nothing to composite; on the twenty here it finds a blast on
most and something merely representative on the rest.  That is what ``--at`` is
for: it pins one plate's window by hand, records the pick as `manual`, and no
later run — ``--force`` included — will re-derive it.

Writes ``<stem>_pv.mp4`` and ``<stem>_pv.jpg`` beside the working copy, and sets
``preview``/``preview_dur``/``preview_src``/``preview_at``/``preview_pick``/
``poster`` on the sidecar record.  The ingest's own black poster file is LEFT on
disk, merely no longer pointed at: the sidecar is the only thing that changes,
so this is undone by putting one field back.

Idempotent by output path, like every other ingest here — re-running fills gaps
and re-does nothing.  ``--force`` rebuilds anyway.

    python3 vfx_plate_preview.py                              # fill the gaps
    python3 vfx_plate_preview.py --force                      # rebuild all
    python3 vfx_plate_preview.py --only doe_0800001.mp4 --at 660   # pin one
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from zyg_workflows import vfx_ingest as vi
from zyg_workflows.bin import exe

CAT = 'vfx_plates'
WIN_S = 6.0  # how long the hover cut runs
FPS = 2.0  # analysis sample rate
SW, SH = 64, 36  # analysis frame size
HEAD_S = 8.0  # skip the leader — every one of these films has one
DARK = 16.0  # mean grey below this is a black frame, not a picture
DETAIL_FRAC = 0.6  # a window must hold at least this much of the film's typical picture
CAP_MED = 3.0  # activity is scored capped at this many times the film's median
FLASH_JUMP = 40.0  # grey levels a detonation adds in half a second
FLASH_LEAD = 1.0  # the cut opens this long before the flash, not inside it
# How far past the flash the poster may be taken from. 20 s was too far and it
# showed: on Trinity Shot the search walked straight out of the event and landed
# on the `This Video Has Been Sanitized` card 16 s later. Seven seconds is
# inside the cut this same window produces, so the still is always a frame of
# what the card hover-plays — which is the whole point of taking both from one
# window. A plate whose picture never recovers inside that gets the fireball
# itself (the +8 default below), overexposed but honest.
POSTER_MAX_S = 7.0
PV_W = 480  # cut/poster width; a card thumb is ~220 CSS px
# **`-ss` before `-i` is a KEYFRAME seek and these files are not densely keyed.**
# Measured on doe_0800008: keyframes at 1232.83 then 1241.14 — an 8.3 s gap, so
# `-ss 1240.5` silently started the cut at 1232.83 and grabbed the poster from
# there too. Every window this script measures was landing up to eight seconds
# early, which is how a poster picked for being the brightest sample in its
# window came out at mean grey 5.5. Two-stage seek fixes it: fast keyframe seek
# to PAD seconds early, then an accurate output-side seek forward over the
# decoded frames. PAD must exceed the longest keyframe gap in the material.
SEEK_PAD = 12.0
# These plates are film-to-tape transfers and comb on every motion — idet over
# 218 frames read TFF 215 / progressive 0 — while the working copies still flag
# every frame `interlaced_frame=0`, so bwdif's normal `deint=interlaced` mode
# skips all of them and does nothing at all. `deint=all` is the only setting
# that touches this material (see project_vfx_effect_toolbox). A card face full
# of comb lines reads as a broken decode, which is why this is on by default
# here rather than left to the operator.
DEINT = 'bwdif=deint=all'


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _seek(t: float):
    """(input -ss, output -ss) landing accurately on `t`. See SEEK_PAD."""
    pre = max(0.0, t - SEEK_PAD)
    return pre, t - pre


def scan(path: str):
    """Per-sample (diff, bright, detail) — one full decode at FPS/SWxSH grey.

    `detail` is the mean absolute difference between horizontally adjacent
    pixels: how much PICTURE the frame has.  It is here because activity alone
    picks the wrong window on this material — see pick_window()."""
    p = subprocess.run(
        [
            exe('ffmpeg'),
            '-v',
            'error',
            '-i',
            path,
            '-an',
            '-vf',
            f'fps={FPS},scale={SW}:{SH},format=gray',
            '-f',
            'rawvideo',
            '-',
        ],
        capture_output=True,
    )
    buf, n = p.stdout, SW * SH
    if len(buf) < n * 4:
        return [], [], []
    frames = [buf[i * n : (i + 1) * n] for i in range(len(buf) // n)]
    bright = [sum(f) / n for f in frames]
    detail = []
    for f in frames:
        t = 0
        for r in range(SH):
            b = r * SW
            for c in range(SW - 1):
                t += abs(f[b + c] - f[b + c + 1])
        detail.append(t / (SH * (SW - 1)))
    diff = [0.0]
    for i in range(1, len(frames)):
        a, b = frames[i - 1], frames[i]
        diff.append(sum(abs(a[j] - b[j]) for j in range(n)) / n)
    return diff, bright, detail


def _median(xs):
    ys = sorted(xs)
    return ys[len(ys) // 2] if ys else 0.0


def find_flash(diff, bright, detail):
    """The detonation, or None — (flash sample, poster sample).

    A blast is the one event in these films with a signature no documentary
    footage shares: brightness leaps by tens of levels in half a second, comes
    back DOWN over the following seconds, and the picture keeps moving the
    whole time.  All three parts are load-bearing, measured against the twenty
    plates on disk:

      * the leap alone also fires on a cut to a white title card;
      * the leap plus the decay still fires on `This Video Has Been Sanitized`,
        which fades rather than cuts — so the third gate asks the shot to MOVE
        for the ten seconds after (a card is bright and still);
      * and the frame at the peak is a white-out with nothing in it, so the
        poster is taken later: the first sample where the picture has come back
        (detail near the film's own median) and the exposure has settled.

    This is a heuristic on documentary films, not an element library, and it is
    honest about being one — it wins on maybe half of these twenty and hands
    back None on the rest, where the caller falls back to the busiest window.
    `--only <file> --at <seconds>` overrides any of it by hand, permanently."""
    n = len(bright)
    if n < 40:
        return None
    med_h, med_d = _median(detail), _median(diff)
    best = None
    for i in range(12, n - 24):
        pre = min(bright[i - 6 : i])
        jump = bright[i] - pre
        if jump < FLASH_JUMP:
            continue
        if bright[i] - _median(bright[i + 8 : i + 16]) < 0.15 * jump:
            continue
        if _median(diff[i + 2 : i + 20]) < med_d:
            continue
        s = jump + (bright[i] - _median(bright[i + 8 : i + 16]))
        if best is None or s > best[0]:
            best = (s, i, pre, jump)
    if not best:
        return None
    _, i, pre, jump = best
    hi = min(n, i + int(POSTER_MAX_S * FPS))
    for j in range(i, hi):
        if detail[j] >= 0.7 * med_h and bright[j] <= pre + 0.6 * jump and diff[j] >= 0.5 * med_d:
            return (i, j)
    # Nothing in the window has its picture back yet — half of these blasts are
    # at night, or the camera is stopped down to nothing around them, so a fixed
    # offset lands on black: measured, +4 s gave posters of mean grey 1.2 and 4.8
    # out of 255, exactly the black card this script exists to stop shipping.
    #
    # Take the brightest SUSTAINED moment instead of the brightest sample. The
    # difference is not pedantry — on doe_0800008 the single brightest sample is
    # 202 with 1.6 on both sides of it, one frame of flash in a black night
    # shot, and a poster grab is not frame-accurate enough to hit it: asking for
    # that exact second returned mean grey 5.5, twice, from either side of it.
    # Scoring min(this, next) makes a one-frame spike worth its dark neighbour
    # and picks the settled fireball a few seconds later, which is both brighter
    # on average and actually reproducible.
    return (i, max(range(i, hi - 1), key=lambda j: min(bright[j], bright[j + 1])))


def pick_window(diff, bright, detail, dur: float):
    """Start second of the window the cut is taken from, the second the poster
    is taken from, and WHICH rule produced them.

    A blast if one can be found (find_flash), and the cut opens a beat before it
    so the hover shows flash into cloud rather than starting inside the
    white-out.  Otherwise the busiest window that is neither black nor empty:

    **Most-motion alone picks the damaged tail, measured.**  On Trinity Shot the
    last 30 s of 720 score diff 29 then 69 against a body of 10-20 — that is
    torn tape, not an event, and it won the first version of this outright.  The
    tell is that it has almost no picture in it: horizontal detail 3.8-6.8
    against ~15-20 anywhere the film is showing something.  So a window has to
    clear two gates before its activity is even compared: not black (mean grey
    >= DARK — the leader) and as much picture in it as the film typically has
    (mean detail >= DETAIL_FRAC of the median).  Activity is then scored CAPPED
    at CAP_MED times the film's median, so one torn frame inside an otherwise
    good window cannot buy the window a win either.

    Fallbacks, in order: brightness gate only, then no gate at all, then 10% in.
    A plate always gets a preview, and `why` records which of those actually
    happened rather than letting a fallback look like a pick."""
    w = int(WIN_S * FPS)
    if len(diff) <= w:
        return (max(0.0, min(dur - WIN_S, dur * 0.1)), None, 'fallback')
    fl = find_flash(diff, bright, detail)
    if fl:
        i, pj = fl
        start = max(0.0, i / FPS - FLASH_LEAD)
        return (start, pj / FPS, 'flash')
    med_d, med_h = _median(diff), _median(detail)
    cap = max(1.0, CAP_MED * med_d)
    lo = int(HEAD_S * FPS)
    hi = max(lo + 1, len(diff) - w)
    cands = {'both': None, 'lit': None, 'any': None}
    for i in range(lo, hi):
        sl_d, sl_b, sl_h = diff[i : i + w], bright[i : i + w], detail[i : i + w]
        s = sum(min(x, cap) for x in sl_d)
        lit = sum(sl_b) / w >= DARK
        has = sum(sl_h) / w >= DETAIL_FRAC * med_h
        for k, ok in (('any', True), ('lit', lit), ('both', lit and has)):
            if ok and (cands[k] is None or s > cands[k][0]):
                cands[k] = (s, i)
    for k, why in (('both', 'measured'), ('lit', 'measured-flat'), ('any', 'measured-dark')):
        if cands[k]:
            i = cands[k][1]
            # the poster is the brightest sample in the window: on this material
            # that is the flash itself, and on any other it is at least the most
            # readable frame of the cut.
            pi = max(range(i, i + w), key=lambda j: bright[j])
            return (i / FPS, pi / FPS, why)
    return (max(0.0, min(dur - WIN_S, dur * 0.1)), None, 'fallback')


def build(only=None, force=False, at=None, log=print) -> int:
    meta = vi.load_sidecar()
    lib = os.path.join(vi.LIBS, CAT)
    keys = sorted(k for k, r in meta.items() if isinstance(r, dict) and r.get('cat') == CAT and r.get('file'))
    done = 0
    for k in keys:
        rec = meta[k]
        fn = rec['file']
        if only and fn != only:
            continue
        src = os.path.join(lib, fn)
        if not os.path.isfile(src):
            log(f'[plate-pv] missing working copy, skipping: {fn}')
            continue
        stem = fn.rsplit('.', 1)[0]
        out_mp4, out_jpg = os.path.join(lib, stem + '_pv.mp4'), os.path.join(lib, stem + '_pv.jpg')
        if not force and rec.get('preview') and os.path.isfile(out_mp4):
            continue
        # A hand-set window is permanent: the pick below is a heuristic on
        # documentary footage and will be wrong on some plate, and re-running
        # the builder must not quietly undo the operator's correction of it.
        want = at
        if want is None and rec.get('preview_pick') == 'manual' and rec.get('preview_at') is not None:
            want = float(rec['preview_at'])
            log(f'[plate-pv] {fn}: keeping the hand-set window at {want:.1f}s')
        if want is not None:
            start, ptime, why = float(want), float(want) + WIN_S / 3, 'manual'
        else:
            log(f'[plate-pv] scanning {fn} ({rec.get("dur", 0):.0f}s)…')
            diff, bright, detail = scan(src)
            start, ptime, why = pick_window(diff, bright, detail, float(rec.get('dur') or 0))
        if ptime is None:
            ptime = start + WIN_S / 2
        log(f'[plate-pv]   window {start:.1f}s ({why}), poster at {ptime:.1f}s')
        pre, off = _seek(start)
        r = _run(
            [
                exe('ffmpeg'),
                '-y',
                '-v',
                'error',
                '-ss',
                f'{pre:.2f}',
                '-i',
                src,
                '-ss',
                f'{off:.2f}',
                '-t',
                f'{WIN_S:.2f}',
                '-an',
                '-vf',
                f'{DEINT},scale={PV_W}:-2',
                '-c:v',
                'libx264',
                '-crf',
                '23',
                '-preset',
                'veryfast',
                '-pix_fmt',
                'yuv420p',
                '-movflags',
                '+faststart',
                out_mp4,
            ]
        )
        if r.returncode != 0 or not os.path.isfile(out_mp4):
            log(f'[plate-pv]   CUT FAILED {fn}: {r.stderr[-300:]}')
            rec['preview_error'] = 'cut failed'
            vi.save_sidecar(meta)
            continue
        ppre, poff = _seek(ptime)
        _run(
            [
                exe('ffmpeg'),
                '-y',
                '-v',
                'error',
                '-ss',
                f'{ppre:.2f}',
                '-i',
                src,
                '-ss',
                f'{poff:.2f}',
                '-frames:v',
                '1',
                '-vf',
                f'{DEINT},scale={PV_W}:-2',
                out_jpg,
            ]
        )
        p = vi.probe(out_mp4)
        rec['preview'] = os.path.basename(out_mp4)
        rec['preview_dur'] = float(p.get('dur') or WIN_S)
        rec['preview_src'] = 'cut'
        rec['preview_at'] = round(start, 2)
        rec['preview_pick'] = why
        rec['preview_error'] = ''
        if os.path.isfile(out_jpg) and os.path.getsize(out_jpg) > 0:
            rec['poster'] = os.path.basename(out_jpg)
        vi.save_sidecar(meta)
        done += 1
        log(f'[plate-pv]   wrote {os.path.basename(out_mp4)} ({os.path.getsize(out_mp4) / 1e6:.1f} MB) + poster')
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--only', help='one working-copy filename')
    ap.add_argument('--force', action='store_true', help='rebuild even if one exists')
    ap.add_argument(
        '--at',
        type=float,
        help='take the cut from this second instead of picking one; '
        'recorded as a manual pick and never re-derived after',
    )
    a = ap.parse_args(argv)
    if a.at is not None and not a.only:
        ap.error("--at sets one plate's window, so it needs --only")
    # --at is an instruction to change the window, so it implies a rebuild.
    n = build(only=a.only, force=a.force or a.at is not None, at=a.at)
    print(f'[plate-pv] {n} preview(s) built')
    return 0


if __name__ == '__main__':
    sys.exit(main())
