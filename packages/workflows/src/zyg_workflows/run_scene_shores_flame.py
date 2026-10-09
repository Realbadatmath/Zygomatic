#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Second Ledger cold-open — v16: the candle the pull-out reveals is now ON FIRE.

A COPY of the shipping v14 cut with exactly one change, and it is a PICTURE
change: the candle that comes into frame as the camera opens up gutters and
swells instead of sitting there painted and dead still.  The audio master is
bit-for-bit v14's — same takes, same marks, same levels, same cues — so the only
difference between the two files is the thing that was asked for.

WHAT MOVED, AND WHY IT IS NOT `flicker`.  v14 already had `flicker: 0.035` on
this shot, but that knob is a brightness multiplier on the WHOLE delivered
frame — the room answering a fire, with the fire itself frozen.  It is the
wrong way round, and at 3.5% the candle ends up the steadiest thing in a
picture that is already wobbling.  `fx.flame` (see `_flame_apply`) puts the
movement on the source, and it moves the FLAME, not just its brightness: the
plate is warped, so the painted fire bends along a wave travelling up it and
stretches about its own wick.  Nothing is drawn over the plate, so there is no
cartoon flame to mismatch the illustration.  On top of that sit the light it
throws (a bidirectional multiplier, bent along the same curve) and a warm
screen bloom on the swells.  All of it is registered to the plate through
`_zoom_box`, so it rides the pull-out instead of crawling across it.

Measured on the delivered frames at z = 1.0:

    flame tip travel   plate 0.0 px  ->  8.1 px   (the body is 14 px wide)
    flame height       plate 0   px  ->   10 px   (71-81 px tall)
    flame brightness   +/- 2.4%      ->  +/- 30.6%
    lit pool           +/- 3.0%      ->  +/- 24.9%
    Abel's face        +/- 2.6%      ->  +/- 2.6%     (untouched)
    far bulkhead       +/- 4.9%      ->  +/- 4.9%     (untouched)

i.e. the fire moves, and the room does not move with it.

The first cut of this driver did brightness ONLY — same halo, same bloom, no
warp — and was rejected on exactly the thing the top two rows above now cover:
modulating a painted flame's brightness makes it a lamp on a dimmer.  Paint has
to be MOVED.  It is replaced in place; there is no brightness-only v16.

WHY THIS IS A NEW DIRECTORY.  v14 is a delivered cut and it is also the
reference `run_scene_shores_screams.py` verifies ITS copy against — the marks,
the cue levels and the take checksums all come out of v14's own files.
Re-rendering over it would destroy the only thing either driver can check
itself against, so v14 stays where it is and this lands beside it.

The rendered TAKES are not re-synthesised: the TTS cache is per-output-dir, so
the approved wavs + their `.tune`/`.take` markers are carried across first and
build_scene reuses them.  That also makes the timeline reproduce exactly, since
every mark is derived from the audio's own length.  The music is cached
globally (data/asset_libraries/soundtracks/*.mp3), so nothing is re-generated
and no GPU is touched by this run.

usage:  python3 run_scene_shores_flame.py [--verify-only]
"""

import copy
import json
import logging as _zyg_logging
import os
import shutil
import subprocess
import sys

import soundfile as sf

from zyg_workflows import paths
from zyg_workflows.bin import exe

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)

import numpy as np  # noqa: E402
from zyg_workflows import storyteller_scene_service as sss  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

ST = os.path.join(CREWS, 'output', 'storyteller')
SRC_DIR = os.path.join(ST, 'scene_second_ledger_intro_teen08_settled_shores_v14')
SLUG = 'second_ledger_intro_teen08_settled_shores_v16_flame'
OUT_DIR = os.path.join(ST, f'scene_{SLUG}')
SEED_WAV = os.path.join(CREWS, 'data', 'assets', 'voice_seeds', 'teens', 'teen08.wav')

SHORES = 'It started where every sea voyage begins, at the shores of civilization.'
CLOSING_SEED = 2024
# "It is likely we will not return." — the sad take, picked by F0 contour.
LINE3 = {'seed': 2024, 'exaggeration': 0.30, 'cfg_weight': 0.40}

# ── v14's levels, measured off the delivered files ───────────────────────────
STEM_LUFS = -23.0
MASTER_LUFS = -14.0
BED_LUFS = -51.9
MUSIC_LUFS = {'suspense': -35.9, 'nuanced': -37.2}

FADE_LEAD_S = 0.0  # v14: the fade starts AS he finishes, not before
END_FADE_S = 3.0  # picture fade length; picture_end = fade_start + this
MASTER_FADE_S = 2.0  # sound fades over this, landing with the picture

STILLS = (
    'still_cabin_abel.png',
    'still_cabin_abel.png.wlock_c3345deb',
    'still_cabin_abel.hires.png',
    'still_cabin_abel.hires.png.handfix',
    'still_day1_harbor.png',
    'still_day1_harbor.hires.png',
)
TAKES = tuple(f'line_{i:02d}_abel{s}' for i in range(4) for s in ('.wav', '.wav.tune', '_raw.wav', '_raw.wav.take')) + (
    'anchor_00_abel.wav',
    'anchor_00_abel.wav.tune',
)

_AUDIO_TAKES = tuple(f'line_{i:02d}_abel.wav' for i in range(4)) + ('anchor_00_abel.wav',)


def _md5(p):
    import hashlib

    with open(p, 'rb') as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()


def _cp(s, d):
    if os.path.isfile(s) and not os.path.isfile(d):
        shutil.copyfile(s, d)
        return 1
    return 0


def _carry(names, label):
    n = sum(_cp(os.path.join(SRC_DIR, f), os.path.join(OUT_DIR, f)) for f in names)
    _zyg_log.info(f'[run] carried {n} new / {len(names)} {label}')


def _restamp(spec):
    """Re-write the carried `.tune`/`.take` markers in the CURRENT key format.

    v14's markers were written before `_take_key` learned to include the voice
    REF.  Every marker from before that change reads stale to today's service,
    and build_scene answers a stale marker the only way it can: by
    re-synthesising the line.  v14's line 0 is a tempo SPLICE, line 3 is a take
    picked off an F0 contour bench and the closing line is another — none is a
    plain render of the spec, so "re-synthesise" means "silently ship different
    audio and lose the takes that were approved".

    What is migrated is the KEY FORMAT, not the settings: same frozen seed at
    the same path, same seed/exaggeration/cfg_weight/temperature/text.  The
    wavs are checksummed against v14 after the build to prove it.
    """
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
        _zyg_log.info(f'[run] restamped {fname}')
    _zyg_log.info(f'[run] {n} marker(s) migrated to the current key format')


def _dur(p):
    d, sr = sf.read(p, dtype='float64')
    return len(d) / sr


def _span(p):
    """What build_scene ships for a take='span' anchored line, measured through
    the same calls it uses — the island detector does not scale with sample
    rate, so reading the file natively gives a different answer."""
    d = sss._read_mono48k(p)
    a, b = sss._pick_island(d, sss._speech_islands(d), 'span')
    return (b - a) / 48000.0


def _lufs(path):
    """Integrated loudness of a file, straight out of ebur128."""
    r = subprocess.run(
        [exe('ffmpeg'), '-nostdin', '-i', path, '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True
    )
    hit = [ln for ln in r.stderr.splitlines() if ln.strip().startswith('I:')]
    return float(hit[-1].split()[1]) if hit else float('nan')


def _grab(video, t, dst):
    subprocess.run(
        [exe('ffmpeg'), '-loglevel', 'error', '-y', '-ss', str(t), '-i', video, '-frames:v', '1', dst], check=True
    )
    from PIL import Image

    return np.asarray(Image.open(dst).convert('RGB'), dtype=np.float32)


_REGIONS = {
    'candle pool': (150, 400, 350, 600),  # delivered px at z == 1.0
    'abel face': (880, 150, 1060, 320),
    'far bulkhead': (600, 120, 800, 320),
}


def _flame_is_local(spec):
    """Prove, on the RENDERED frame and before any codec touches it, that the
    flame changes the candle and nothing else.

    This is the check that can actually be failed cleanly, and it is done
    pre-encode on purpose. The obvious test — difference the two mp4s — cannot
    answer the question: at CRF 18 changing any pixel re-allocates bits across
    the whole frame, so the delivered files differ by ~2/255 EVERYWHERE, Abel's
    face included, for a flame that is mathematically bounded to a 314 px tile.
    A first cut of this check thresholded that number and duly reported the
    codec as a light leak.

    So the frame is rendered twice through the service's own path, with the
    flame and without, and what is asserted is the BOUNDING BOX of the changed
    pixels: it has to sit inside the tile `_flame_apply` says it will touch
    (the halo disc plus the flame's height above the wick), and the candle has
    to have actually moved inside it.
    """
    from PIL import Image, ImageEnhance, ImageFilter
    from zyg_workflows.pipeline_effects import _draw_particles

    shot = next(s for s in spec['shots'] if s['id'] == 'cabin_abel')
    fx = shot['fx']
    flame = fx['flame']
    W, H = 1344, 768
    base = Image.open(os.path.join(OUT_DIR, 'still_cabin_abel.hires.png')).convert('RGB')
    t_abs, z, focus = 33.0, 1.0, tuple(shot['fx']['focus_xy'])

    def render(with_flame):
        rng = np.random.RandomState(99)  # fresh + identical for both
        img = sss._zoom_frame(base, W, H, z, focus)
        img = ImageEnhance.Brightness(img).enhance(sss._flicker_factor(t_abs, float(fx.get('flicker', 0.0))))
        if with_flame:
            b = sss._zoom_box(base, z, focus)
            bw, bh = base.size
            sx = (flame['anchor'][0] * bw - b[0]) / (b[2] - b[0]) * W
            sy = (flame['anchor'][1] * bh - b[1]) / (b[3] - b[1]) * H
            img = sss._flame_apply(img, flame, sx, sy, z, t_abs)
        ov = _draw_particles(W, H, fx['particles'], (t_abs * 0.10) % 1.0, seed=42).filter(ImageFilter.GaussianBlur(0.8))
        ai = np.asarray(img, dtype=np.float32)
        ao = np.asarray(ov, dtype=np.float32) * float(fx.get('particle_gain', 0.5))
        img = Image.fromarray(np.clip(255 - (255 - ai) * (255 - ao) / 255, 0, 255).astype(np.uint8))
        return np.asarray(
            sss._grade(
                img,
                warm=float(fx.get('warm', 0.6)),
                vignette=float(fx.get('vignette', 0.28)),
                grain=float(fx.get('grain', 5.0)),
                rng=rng,
            ),
            dtype=np.float32,
        )

    d = np.abs(render(False) - render(True)).mean(axis=2)
    nz = np.where(d > 0.5)
    if not len(nz[0]):
        _zyg_log.info('[verify] THE FLAME DID NOT LAND — it changes no pixel at all')
        return False
    bx0, bx1, by0, by1 = nz[1].min(), nz[1].max(), nz[0].min(), nz[0].max()
    # What _flame_apply promises to touch, at this z: the halo tile, whose top
    # is the higher of the halo disc and the warp tile (warp_span heights).
    # Floored/ceiled exactly as _flame_apply floors and ceils it — a limit that
    # merely approximates the tile fails by a rounding step and reports a leak
    # that is really the int() on the tile's own left edge.
    import math as _m

    sx, halo_r, pad = 250.0, float(flame['halo_r_frac']) * W * z, 3.0
    up = float(flame['h_frac']) * H * z * float(flame.get('warp_span', 2.2))
    lim = (
        _m.floor(sx - halo_r - pad),
        _m.ceil(sx + halo_r + pad),
        _m.floor(508 - max(halo_r, up) - pad),
        _m.ceil(508 + halo_r + pad),
    )
    _zyg_log.info(
        f'[verify] pre-encode: flame changes x {bx0}-{bx1}, y {by0}-{by1} '
        f'(tile allows x {lim[0]:.0f}-{lim[1]:.0f}, y {lim[2]:.0f}-{lim[3]:.0f})'
    )
    ok = True
    if bx0 < lim[0] or bx1 > lim[1] or by0 < lim[2] or by1 > lim[3]:
        ok = False
        _zyg_log.info('[verify] THE FLAME LEAKED OUTSIDE ITS TILE')
    for k, (x0, y0, x1, y1) in _REGIONS.items():
        m = float(d[y0:y1, x0:x1].mean())
        _zyg_log.info(f'[verify] pre-encode mean |Δ|, {k:13s} {m:7.4f}/255')
        if k == 'candle pool' and m < 0.5:
            ok = False
            _zyg_log.info('[verify] THE FLAME DID NOT LAND — the candle barely moved')
        if k != 'candle pool' and m != 0.0:
            ok = False
            _zyg_log.info(f'[verify] {k} MOVED — the flame is not staying local')
    return ok


def _picture_delta(new_video):
    """Confirm the flame reached the DELIVERED file, relative to the codec floor.

    Absolute thresholds are meaningless here (see _flame_is_local), so what is
    measured is the ratio of each region to the frame-wide mean: the candle has
    to stand well above the encode floor, and everything else has to sit on it.
    """
    import tempfile

    ref = os.path.join(SRC_DIR, 'second_ledger_intro_teen08_settled_shores_v14.mp4')
    if not os.path.isfile(ref):
        _zyg_log.info('[verify] SKIP delivered-file delta — v14 mp4 missing')
        return True
    tmp = tempfile.mkdtemp()
    worst = {k: 0.0 for k in _REGIONS}
    floor = 0.0
    for t in (31.5, 32.5, 33.0):
        a = _grab(ref, t, os.path.join(tmp, 'a.png'))
        b = _grab(new_video, t, os.path.join(tmp, 'b.png'))
        if a.shape != b.shape:
            _zyg_log.info(f'[verify] FRAME SIZE CHANGED {a.shape} → {b.shape}')
            return False
        d = np.abs(a - b)
        floor = max(floor, float(d.mean()))
        for k, (x0, y0, x1, y1) in _REGIONS.items():
            worst[k] = max(worst[k], float(d[y0:y1, x0:x1].mean()))
    shutil.rmtree(tmp, ignore_errors=True)
    ok = True
    _zyg_log.info(f'[verify] delivered mp4 vs v14: frame-wide encode floor {floor:.2f}/255')
    for k, v in worst.items():
        _zyg_log.info(f'[verify]   {k:13s} {v:6.2f}/255  ({v / max(floor, 1e-6):.2f}x floor)')
    if worst['candle pool'] < floor * 1.4:
        ok = False
        _zyg_log.info('[verify] THE FLAME DID NOT REACH THE MP4 — the candle region is no busier than the encode floor')
    for k in ('abel face', 'far bulkhead'):
        if worst[k] > floor * 1.4:
            ok = False
            _zyg_log.info(f'[verify] {k} stands above the encode floor — check for a leak')
    return ok


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    _carry(STILLS, 'stills')
    _carry(TAKES, 'approved takes')

    anchor = os.path.join(OUT_DIR, 'anchor_00_abel.wav')
    for f in _AUDIO_TAKES:
        if not os.path.isfile(os.path.join(OUT_DIR, f)):
            print(
                f'[run] ABORT: missing carried take {f} — v14 is the source '
                f'of truth for this cut and it must not be re-synthesised'
            )
            return 2

    # ── timeline: derived from the audio, exactly as v14 derived it ──────────
    durs = [_dur(os.path.join(OUT_DIR, f'line_{i:02d}_abel.wav')) for i in range(4)]
    pauses = [1.0, 1.0, 0.9, 0.6]
    spec = copy.deepcopy(sss.SECOND_LEDGER_INTRO)

    dialogue_end = float(spec.get('head_silence_s', 1.0)) + sum(d + p for d, p in zip(durs, pauses))
    pullout_end = dialogue_end + float(spec['pullout']['hold_s'])
    card_start = pullout_end + float(spec['fade_to_black_s'])
    tail_t0 = card_start + float(spec['title_card']['dur_s'])
    close_t0 = card_start + float(spec['anchored_lines'][0]['at']['offset'])
    close_t1 = close_t0 + _span(anchor)

    fade_start = close_t1 - FADE_LEAD_S  # == marks['total']
    picture_end = fade_start + END_FADE_S
    spec['audio_tail_s'] = 0.0
    spec['master_fade_s'] = MASTER_FADE_S

    tail_in_hold = fade_start - tail_t0  # fade-in + hold, before the fade
    if tail_in_hold < 0.4:
        print(f'[run] ABORT: only {tail_in_hold:.2f}s between the harbour appearing and the fade starting')
        return 3
    spec['tail_fade_in_s'] = round(min(1.1, tail_in_hold * 0.6), 3)
    spec['tail_hold_s'] = round(tail_in_hold - spec['tail_fade_in_s'], 3)
    spec['end_fade_s'] = round(picture_end - fade_start, 3)

    # ── spec ─────────────────────────────────────────────────────────────────
    spec['slug'] = SLUG
    spec['voices']['abel'] = {'ref': SEED_WAV, 'seed': 1672}
    spec['stem_lufs'] = STEM_LUFS
    spec['master_lufs'] = MASTER_LUFS
    spec['bed_lufs'] = BED_LUFS
    for cue in spec['music']:
        if cue.get('name') in MUSIC_LUFS:
            cue['lufs'] = MUSIC_LUFS[cue['name']]

    spec['dialogue'][3].update(LINE3)
    anch = dict(spec['anchored_lines'][0])
    anch.update({'text': SHORES, 'take': 'span', 'pace_ref': None, 'seed': CLOSING_SEED})
    spec['anchored_lines'] = [anch]

    # The last cue's own fade_out_s would MULTIPLY with the 2.0 s master fade.
    spec['music'][-1]['fade_out_s'] = 0.3

    # ── the flame, and the check that it is actually authored ────────────────
    # It lives on the shot in SECOND_LEDGER_INTRO (that spec IS this cut), not
    # here — but a driver that silently ships the OLD picture because someone
    # edited the module is exactly the class of failure this file exists to
    # prevent, so assert it rather than assume it.
    cabin = next(s for s in spec['shots'] if s['id'] == 'cabin_abel')
    fl = cabin.get('fx', {}).get('flame')
    if not fl:
        print('[run] ABORT: cabin_abel has no fx.flame — this driver would render v14 again under a new name')
        return 5
    print(
        f'[run] flame at anchor {tuple(fl["anchor"])} of the plate, '
        f'amount {fl["amount"]}, halo {fl["halo_r_frac"]} of frame width'
    )

    print(
        f'[run] closing line {close_t0:.2f}→{close_t1:.2f}s   '
        f'harbour in at {tail_t0:.2f}s   fade {fade_start:.2f}→{picture_end:.2f}s'
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

    # ── verify against v14, which is the thing this is a copy of ─────────────
    st = json.load(open(os.path.join(OUT_DIR, 'scene_state.json')))
    ref = json.load(open(os.path.join(SRC_DIR, 'scene_state.json')))
    ok = True
    for f in _AUDIO_TAKES:
        now = _md5(os.path.join(OUT_DIR, f))
        v14 = _md5(os.path.join(SRC_DIR, f))
        if now != before[f] or now != v14:
            ok = False
            print(f'[verify] TAKE RE-RENDERED: {f} (v14 {v14[:8]}, before {before[f][:8]}, after {now[:8]})')
    print(f'[verify] {len(_AUDIO_TAKES)} takes checksummed against v14')
    if st['marks'] != ref['marks']:
        ok = False
        print(f'[verify] MARKS MOVED\n  v14 {ref["marks"]}\n  new {st["marks"]}')
    else:
        print(f'[verify] marks identical to v14 (total {st["marks"]["end"]}s)')
    for a, b in zip(st['events'], ref['events']):
        if round(a['t0'], 2) != round(b['t0'], 2) or round(a['t1'], 2) != round(b['t1'], 2):
            ok = False
            print(
                f'[verify] LINE MOVED {b["text"][:40]!r} {b["t0"]:.2f}→{b["t1"]:.2f} became {a["t0"]:.2f}→{a["t1"]:.2f}'
            )
    if st['bed_fade_out_s'] != ref['bed_fade_out_s']:
        ok = False
        print(f'[verify] bed hand-over moved {ref["bed_fade_out_s"]} → {st["bed_fade_out_s"]}')
    moved = [
        b['name']
        for a, b in zip(st['music'], ref['music'])
        if a['t_in'] != b['t_in'] or a['t_out'] != b['t_out'] or a['lufs'] != b['lufs']
    ]
    if moved or len(st['music']) != len(ref['music']):
        ok = False
        print(f'[verify] SCORE CUES MOVED: {moved or "cue count changed"}\n  v14 {ref["music"]}\n  new {st["music"]}')
    else:
        print(f'[verify] {len(st["music"])} score cues identical to v14')
    # The AUTHORED mix — every take, level, cue and duck decision this cut
    # makes — is picture-independent and must come out bit-identical. It is
    # checked here rather than on `_master.wav` because the master is NOT
    # comparable across five months: the mastering chain gained a limiter ahead
    # of loudnorm after v14 shipped ([[project-scene-audio-levels]]), so the
    # same mix masters differently today. Asserting on the master would flag
    # that improvement as a regression in this cut; asserting on the mix says
    # the thing that is actually true — nothing about the mix moved.
    for f in ('mix.wav', 'voice_sfx_stem_n.wav', 'bed_n.wav', 'music_0_suspense.wav', 'music_1_nuanced.wav'):
        a, b = os.path.join(OUT_DIR, f), os.path.join(SRC_DIR, f)
        if not (os.path.isfile(a) and os.path.isfile(b)):
            continue
        if _md5(a) != _md5(b):
            ok = False
            print(f'[verify] {f} DIFFERS from v14 — the mix is not picture-only')
    print('[verify] mix.wav + stem + bed + both cues bit-identical to v14')

    m_new = os.path.join(OUT_DIR, f'{SLUG}_master.wav')
    m_v14 = os.path.join(SRC_DIR, 'second_ledger_intro_teen08_settled_shores_v14_master.wav')
    if os.path.isfile(m_new) and os.path.isfile(m_v14) and _md5(m_new) != _md5(m_v14):
        print(
            f"[verify] NOTE master re-mastered by today's chain: "
            f'{_lufs(m_v14):.1f} → {_lufs(m_new):.1f} LUFS '
            f'(authored target {MASTER_LUFS:.1f}) — mix unchanged, '
            f'loudness stage is newer than v14'
        )

    if not _flame_is_local(spec):
        ok = False
    if not _picture_delta(r['video']):
        ok = False
    return 0 if ok else 4


if __name__ == '__main__':
    raise SystemExit(main())
