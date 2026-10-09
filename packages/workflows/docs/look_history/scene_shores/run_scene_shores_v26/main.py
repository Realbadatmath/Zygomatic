# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`main` — the render/verify driver (verbatim from run_scene_shores_v26.py)."""

from zyg_workflows.run_scene_shores_v26.bird_flight import _bird_flies_away
from zyg_workflows.run_scene_shores_v26.constants import (
    BEAT_S,
    BED_LUFS,
    BIRD_CFG,
    BIRD_DUR,
    BIRD_IN,
    CLOSING_SEED,
    END_FADE_S,
    LINE3,
    MASTER_FADE_S,
    MASTER_LUFS,
    MUSIC_LUFS,
    NEW_HIRES,
    NEW_PLATE,
    OUT_DIR,
    OVERSHOOT_S,
    SEED_WAV,
    SHORES,
    SLUG,
    SPRITE_DIR,
    SRC_DIR,
    SRC_MP4,
    STEM_LUFS,
    STILLS_CARRY,
    TAIL_FADE_IN_S,
    TAKES,
    WATER_POLY,
    _AUDIO_TAKES,
    _carry,
    _cp,
    _dur,
    _grab,
    _md5,
    _restamp,
    _span,
    copy,
    json,
    np,
    os,
    shutil,
    sss,
    sys,
)
from zyg_workflows.run_scene_shores_v26.delivered_checks import (
    _bird_bank_visible_in_delivered_file,
    _bird_is_in_the_delivered_file,
    _bird_trajectory_matches_model_in_delivered_file,
    _camera_holds_for_the_bird,
    _no_crates_in_the_water,
    _no_one_on_the_stern,
    _smoke_leaves_the_chimney,
    _the_bow_is_opaque,
    _water_moves_in_the_delivered_file,
)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    _carry(STILLS_CARRY, 'cabin stills')
    _carry(TAKES, 'approved takes')
    for src, dst in ((NEW_PLATE, 'still_day1_harbor.png'), (NEW_HIRES, 'still_day1_harbor.hires.png')):
        if not os.path.isfile(src):
            print(f'[run] ABORT: new harbour plate missing: {src}')
            return 7
        _cp(src, os.path.join(OUT_DIR, dst))
    print('[run] plates carried from v20 unchanged — this cut is motion only')

    for f in _AUDIO_TAKES:
        if not os.path.isfile(os.path.join(OUT_DIR, f)):
            print(
                f'[run] ABORT: missing carried take {f} — v20 is the source '
                f'of truth for the audio and it must not be re-synthesised'
            )
            return 2
    anchor = os.path.join(OUT_DIR, 'anchor_00_abel.wav')

    durs = [_dur(os.path.join(OUT_DIR, f'line_{i:02d}_abel.wav')) for i in range(4)]
    pauses = [1.0, 1.0, 0.9, 0.6]
    spec = copy.deepcopy(sss.SECOND_LEDGER_INTRO)

    dialogue_end = float(spec.get('head_silence_s', 1.0)) + sum(d + p for d, p in zip(durs, pauses))
    pullout_end = dialogue_end + float(spec['pullout']['hold_s'])
    card_start = pullout_end + float(spec['fade_to_black_s'])
    tail_t0 = card_start + float(spec['title_card']['dur_s'])

    bird_out = BIRD_IN + BIRD_DUR
    line_t0 = bird_out + BEAT_S
    line_t1 = line_t0 + _span(anchor)
    total_rel = line_t1 + 0.2
    picture_end_rel = total_rel + END_FADE_S
    win_rel = picture_end_rel + OVERSHOOT_S

    spec['tail_fade_in_s'] = TAIL_FADE_IN_S
    spec['tail_hold_s'] = round(total_rel - TAIL_FADE_IN_S, 3)
    spec['end_fade_s'] = END_FADE_S
    spec['tail_zoom_overshoot_s'] = OVERSHOOT_S
    spec['audio_tail_s'] = 0.0
    spec['master_fade_s'] = MASTER_FADE_S

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

    # ── the bird, now flying past the ship instead of stopping there ───────
    with open(BIRD_CFG) as fh:
        bird = json.load(fh)
    bird['sprites'] = SPRITE_DIR  # never a scratch path
    fx['bird'] = bird
    with open(WATER_POLY) as fh:
        poly = json.load(fh)
    fx['water'] = dict(fx['water'])
    fx['water']['poly'] = poly + [[0.0, 1.0]]

    for k in ('water', 'smoke', 'bird'):
        if not fx.get(k):
            print(f'[run] ABORT: the tail shot has no fx.{k}')
            return 5
    if abs(float(fx['bird']['t0_rel']) - BIRD_IN) > 1e-6:
        print("[run] ABORT: the bird's t0_rel disagrees with this driver")
        return 5
    if abs(float(fx['bird']['dur_s']) - BIRD_DUR) > 1e-6:
        print("[run] ABORT: the bird's dur_s disagrees with this driver")
        return 5
    print(
        f'[run] tail {tail_t0:.2f}s: bird {tail_t0 + BIRD_IN:.2f}'
        f'→{tail_t0 + bird_out:.2f}s, line {tail_t0 + line_t0:.2f}'
        f'→{tail_t0 + line_t1:.2f}s, fade {tail_t0 + total_rel:.2f}'
        f'→{tail_t0 + picture_end_rel:.2f}s'
    )
    print(f'[run] camera holds to at={hold_at} of the {win_rel:.2f}s move window')
    print(
        f'[run] water poly {len(fx["water"]["poly"])} pts out to the new '
        f'bulkhead, {len(fx["smoke"])} chimneys, bird {fx["bird"]["dur_s"]}s '
        f'from sprites'
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
        v20 = _md5(os.path.join(SRC_DIR, f))
        if now != before[f] or now != v20:
            ok = False
            print(f'[verify] TAKE RE-RENDERED: {f} (v20 {v20[:8]}, now {now[:8]})')
    print(f'[verify] {len(_AUDIO_TAKES)} takes checksummed against v20')

    for k in ('dialogue_end', 'pullout_start', 'pullout_end', 'card_start', 'card_end', 'tail_start'):
        if round(st['marks'][k], 2) != round(ref['marks'][k], 2):
            ok = False
            print(
                f'[verify] MARK {k} MOVED {ref["marks"][k]} → {st["marks"][k]} '
                f'— everything up to the tail must still land where v20 put it'
            )
    print(f'[verify] every mark up to the tail identical to v20 (tail at {st["marks"]["tail_start"]}s)')
    print(
        f'[verify] picture now ends at {st["marks"]["picture_end"]}s '
        f'(v20: {ref["marks"]["picture_end"]}s) — the tail is '
        f'{BIRD_DUR - 5.0:+.1f}s longer than v22, by design'
    )
    # events[0:4] are the four SPOKEN dialogue lines, all before the tail
    # begins — those must be byte-identical to v20. events[4] is the anchored
    # closing line INSIDE the tail, which is supposed to move: it starts
    # BIRD_IN + BIRD_DUR + BEAT_S after tail_start, so a longer BIRD_DUR
    # pushes it later BY DESIGN. Checked against that expected delta instead
    # of against v20's fixed timestamp.
    for a, b in zip(st['events'][:4], ref['events'][:4]):
        if round(a['t0'], 2) != round(b['t0'], 2):
            ok = False
            print(f'[verify] LINE MOVED {b["text"][:36]!r}')
    print('[verify] all four spoken lines land where v20 put them')
    closing_a, closing_b = st['events'][4], ref['events'][4]
    shift = closing_a['t0'] - closing_b['t0']
    expect = BIRD_DUR - 5.0
    print(
        f'[verify] closing line {closing_b["text"][:36]!r} moved {shift:+.2f}s '
        f'(expected {expect:+.2f}s, from the BIRD_DUR change)'
    )
    if abs(shift - expect) > 0.05:
        ok = False
        print('[verify] THE CLOSING LINE MOVED BY THE WRONG AMOUNT')

    if not _the_bow_is_opaque(spec):
        ok = False
    if not _no_one_on_the_stern(spec):
        ok = False
    if not _no_crates_in_the_water(spec):
        ok = False
    if not _camera_holds_for_the_bird(spec, st):
        ok = False
    if not _bird_flies_away(spec):
        ok = False
    if not _bird_is_in_the_delivered_file(st, r['video']):
        ok = False
    bird_cfg = sss.shot_by_id_spec(spec, spec['tail_shot_id'])['fx']['bird']
    if not _bird_trajectory_matches_model_in_delivered_file(bird_cfg, st, r['video']):
        ok = False
    if not _bird_bank_visible_in_delivered_file(bird_cfg, st, r['video']):
        ok = False
    if not _smoke_leaves_the_chimney(spec):
        ok = False
    if not _water_moves_in_the_delivered_file(spec, st, r['video']):
        ok = False

    # The cabin is v20's, byte for byte, so it must be identical on screen.
    import tempfile

    tmp = tempfile.mkdtemp()
    for t in (12.0, 33.0):
        a = _grab(SRC_MP4, t, os.path.join(tmp, 'a.png'))
        b = _grab(r['video'], t, os.path.join(tmp, 'b.png'))
        d = float(np.abs(a - b).mean())
        print(f'[verify] cabin t={t}s vs v20: {d:5.2f}/255 mean difference')
        if d > 2.0:
            ok = False
            print('[verify] THE CABIN CHANGED — only the harbour was meant to')
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 4


if __name__ == '__main__':
    raise SystemExit(main())
