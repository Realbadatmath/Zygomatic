# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI: "spot a regression in one command" (2026-08-01).

Run it as `python -m zyg_workflows.pipeline_debug ...` (see __main__.py)."""

import json
from .gates_beats import qc_beat_prominence
from .gates_charbal import qc_character_balance
from .gates_charbal_detect import _REGRESSION_TOLERANCE, locate_character_faces
from .gates_regression import qc_regression_vs


# ── CLI: "spot a regression in one command" (2026-08-01) ─────────────────────────────────
# Importing this module is unaffected; everything below runs only under __main__.
#   python pipeline_debug.py faces   CLIP [--expect 2]
#   python pipeline_debug.py balance CLIP --auto --names cornelis,abel [--hands JSON]
#   python pipeline_debug.py balance CLIP --chars '{"abel":{"face":[...],"hands":[...]}}'
#   python pipeline_debug.py beats   --beats-json FILE --names cornelis,abel
#   python pipeline_debug.py regress NEW BASE --auto --names cornelis,abel
#   python pipeline_debug.py regress NEW BASE --regions '{"c_face":[0.1,0.08,0.32,0.44]}'
# --auto locates faces with MTCNN and assigns them LEFT to RIGHT in --names order.
def _cli_auto_chars(clip, names, hands=None, log=print):
    det = locate_character_faces(clip, expect=len(names), log_fn=log)
    got = len(det.get('faces') or [])
    if not det.get('ok') or got < len(names):
        raise SystemExit(
            f'--auto could not locate {len(names)} face(s) in {clip}: '
            f'found {got}; {det.get("error") or "pass --chars explicitly"}'
        )
    chars = {}
    for nm, f in zip(names, det['faces']):
        chars[nm] = {'face': f['box']}
        if hands and nm in hands:
            chars[nm]['hands'] = hands[nm]
    return chars


def _cli_main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog='pipeline_debug', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('faces', help='locate face boxes with MTCNN')
    p.add_argument('clip')
    p.add_argument('--expect', type=int, default=2)

    p = sub.add_parser('balance', help='per-character aliveness + cross-character ratio')
    p.add_argument('clip')
    p.add_argument('--chars', help='JSON {"name": {"face": [...], "hands": [...]}}')
    p.add_argument('--auto', action='store_true', help='locate faces with MTCNN (the default when --chars is omitted)')
    p.add_argument('--names', default='cornelis,abel', help='left-to-right, for --auto')
    p.add_argument('--hands', help='JSON {"name": [fx0,fy0,fx1,fy1]} to add to --auto')
    p.add_argument('--max-ratio', type=float)
    p.add_argument('--min-flow', type=float)
    p.add_argument('--no-verify', action='store_true', help='skip the box detector')

    p = sub.add_parser('beats', help='prompt-side beat prominence (no video)')
    p.add_argument('--beats-json', help='file: a JSON list of beats, or {"beats": [...]}')
    p.add_argument('--beat', action='append', default=[], help='repeatable beat text')
    p.add_argument('--names', default='cornelis,abel')
    p.add_argument('--min-share', type=float)

    p = sub.add_parser('regress', help='same regions, new vs baseline, signed deltas')
    p.add_argument('clip')
    p.add_argument('baseline')
    p.add_argument('--regions', help='JSON {"name": [fx0,fy0,fx1,fy1]}')
    p.add_argument('--auto', action='store_true', help='union of detected faces, both clips')
    p.add_argument('--names', default='cornelis,abel')
    p.add_argument('--tolerance', type=float, default=_REGRESSION_TOLERANCE)
    a = ap.parse_args(argv)
    names = [s.strip() for s in getattr(a, 'names', '').split(',') if s.strip()]
    hands = json.loads(a.hands) if getattr(a, 'hands', None) else None
    if a.cmd == 'faces':
        res = locate_character_faces(a.clip, expect=a.expect, log_fn=print)
    elif a.cmd == 'balance':
        chars = json.loads(a.chars) if a.chars else _cli_auto_chars(a.clip, names, hands)
        res = qc_character_balance(
            a.clip,
            chars,
            log_fn=print,
            max_face_ratio=a.max_ratio,
            min_face_flow=a.min_flow,
            verify_boxes=not a.no_verify,
        )
    elif a.cmd == 'beats':
        beats = json.load(open(a.beats_json)) if a.beats_json else list(a.beat)
        if isinstance(beats, dict):
            beats = beats.get('beats') or []
        res = qc_beat_prominence(beats, {n: {} for n in names}, min_share=a.min_share, log_fn=print)
    else:
        if a.regions:
            regions = {k: tuple(v) for k, v in json.loads(a.regions).items()}
        else:
            # --auto on a regression MUST use one box set for both clips, so the boxes are
            # the UNION of what the detector finds in each: a box that moved between renders
            # would otherwise measure the box, not the change.
            ca = _cli_auto_chars(a.clip, names)
            cb = _cli_auto_chars(a.baseline, names)
            regions = {}
            for n in names:
                x, y = ca[n]['face'], cb[n]['face']
                regions[f'{n}.face'] = (min(x[0], y[0]), min(x[1], y[1]), max(x[2], y[2]), max(x[3], y[3]))
        res = qc_regression_vs(a.clip, a.baseline, regions, tolerance=a.tolerance, log_fn=print)
    print(json.dumps(res, indent=1, default=str))
    return 0 if res.get('ok', True) else 1


if __name__ == '__main__':
    raise SystemExit(_cli_main())
