# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.run_scene_shores_water`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.run_scene_shores_water` still reaches it.
"""

import copy
import json
import os
import sys


def main() -> int:
    """The command line that used to live in run_scene_shores_water.

    The library module imports `soundfile` (the optional `audio` group) at module level, so
    it is reached from inside this function: importing the CLI itself must not need it.
    """

    from zyg_workflows.run_scene_shores_water import (
        BED_LUFS,
        CLOSING_SEED,
        END_FADE_S,
        FADE_LEAD_S,
        LINE3,
        MASTER_FADE_S,
        MASTER_LUFS,
        MUSIC_LUFS,
        OUT_DIR,
        SEED_WAV,
        SHORES,
        SLUG,
        SRC_DIR,
        STEM_LUFS,
        STILLS,
        TAKES,
        _AUDIO_TAKES,
        _carry,
        _dur,
        _flame_is_local,
        _lufs,
        _md5,
        _picture_delta,
        _restamp,
        _span,
        _water_is_local,
        sss,
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    _carry(STILLS, 'stills')
    _carry(TAKES, 'approved takes')

    anchor = os.path.join(OUT_DIR, 'anchor_00_abel.wav')
    for f in _AUDIO_TAKES:
        if not os.path.isfile(os.path.join(OUT_DIR, f)):
            print(
                f'[run] ABORT: missing carried take {f} — v16 is the source '
                f'of truth for this cut and it must not be re-synthesised'
            )
            return 2

    durs = [_dur(os.path.join(OUT_DIR, f'line_{i:02d}_abel.wav')) for i in range(4)]
    pauses = [1.0, 1.0, 0.9, 0.6]
    spec = copy.deepcopy(sss.SECOND_LEDGER_INTRO)

    dialogue_end = float(spec.get('head_silence_s', 1.0)) + sum(d + p for d, p in zip(durs, pauses))
    pullout_end = dialogue_end + float(spec['pullout']['hold_s'])
    card_start = pullout_end + float(spec['fade_to_black_s'])
    tail_t0 = card_start + float(spec['title_card']['dur_s'])
    close_t0 = card_start + float(spec['anchored_lines'][0]['at']['offset'])
    close_t1 = close_t0 + _span(anchor)

    fade_start = close_t1 - FADE_LEAD_S
    picture_end = fade_start + END_FADE_S
    spec['audio_tail_s'] = 0.0
    spec['master_fade_s'] = MASTER_FADE_S

    tail_in_hold = fade_start - tail_t0
    if tail_in_hold < 0.4:
        print(f'[run] ABORT: only {tail_in_hold:.2f}s between the harbour appearing and the fade starting')
        return 3
    spec['tail_fade_in_s'] = round(min(1.1, tail_in_hold * 0.6), 3)
    spec['tail_hold_s'] = round(tail_in_hold - spec['tail_fade_in_s'], 3)
    spec['end_fade_s'] = round(picture_end - fade_start, 3)

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
    spec['music'][-1]['fade_out_s'] = 0.3

    # ── the two picture effects, asserted rather than assumed ───────────────
    # Both live on their shots in SECOND_LEDGER_INTRO (that spec IS this cut),
    # so a module edit that dropped either would otherwise ship the previous
    # picture under a new name in silence.
    cabin = sss.shot_by_id_spec(spec, 'cabin_abel')
    if not cabin.get('fx', {}).get('flame'):
        print('[run] ABORT: cabin_abel has no fx.flame — this driver would render a dead candle')
        return 5
    harbor = sss.shot_by_id_spec(spec, spec['tail_shot_id'])
    wc = harbor.get('fx', {}).get('water')
    if not wc:
        print('[run] ABORT: the tail shot has no fx.water — this driver would render v16 again under a new name')
        return 6
    print(
        f'[run] water: {len(wc["poly"])}-point mask, horizon {wc["horizon"]}, '
        f'amp {wc["amp_frac"]} of frame height, {len(wc["trains"])} wave trains, '
        f'glint gain {wc["glint"]["gain"]}'
    )
    print(f'[run] flame at anchor {tuple(cabin["fx"]["flame"]["anchor"])}, amount {cabin["fx"]["flame"]["amount"]}')
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

    # ── verify against v16, which is the thing this is a copy of ────────────
    st = json.load(open(os.path.join(OUT_DIR, 'scene_state.json')))
    ref = json.load(open(os.path.join(SRC_DIR, 'scene_state.json')))
    ok = True
    for f in _AUDIO_TAKES:
        now = _md5(os.path.join(OUT_DIR, f))
        v16 = _md5(os.path.join(SRC_DIR, f))
        if now != before[f] or now != v16:
            ok = False
            print(f'[verify] TAKE RE-RENDERED: {f} (v16 {v16[:8]}, before {before[f][:8]}, after {now[:8]})')
    print(f'[verify] {len(_AUDIO_TAKES)} takes checksummed against v16')
    if st['marks'] != ref['marks']:
        ok = False
        print(f'[verify] MARKS MOVED\n  v16 {ref["marks"]}\n  new {st["marks"]}')
    else:
        print(f'[verify] marks identical to v16 (total {st["marks"]["end"]}s)')
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
        print(f'[verify] SCORE CUES MOVED: {moved or "cue count changed"}\n  v16 {ref["music"]}\n  new {st["music"]}')
    else:
        print(f'[verify] {len(st["music"])} score cues identical to v16')
    for f in ('mix.wav', 'voice_sfx_stem_n.wav', 'bed_n.wav', 'music_0_suspense.wav', 'music_1_nuanced.wav'):
        a, b = os.path.join(OUT_DIR, f), os.path.join(SRC_DIR, f)
        if not (os.path.isfile(a) and os.path.isfile(b)):
            continue
        if _md5(a) != _md5(b):
            ok = False
            print(f'[verify] {f} DIFFERS from v16 — the mix is not picture-only')
    print('[verify] mix.wav + stem + bed + both cues bit-identical to v16')

    m_new = os.path.join(OUT_DIR, f'{SLUG}_master.wav')
    m_v16 = os.path.join(SRC_DIR, 'second_ledger_intro_teen08_settled_shores_v16_flame_master.wav')
    if os.path.isfile(m_new) and os.path.isfile(m_v16) and _md5(m_new) != _md5(m_v16):
        ok = False
        print(
            f'[verify] MASTER DIFFERS from v16 ({_lufs(m_v16):.1f} → '
            f'{_lufs(m_new):.1f} LUFS) — nothing about the audio changed in '
            f'this cut, so this is a regression, not a re-master'
        )
    else:
        print('[verify] master bit-identical to v16')

    if not _water_is_local(spec):
        ok = False
    if not _flame_is_local(spec):
        ok = False
    if not _picture_delta(spec, st, r['video']):
        ok = False
    return 0 if ok else 4


if __name__ == '__main__':
    raise SystemExit(main())
