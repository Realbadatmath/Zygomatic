# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Melody sampler — play a composed plan with real recorded instruments.

melody_sampler.cli — the licence fence and the command line.

Moved verbatim out of the 1,177-line melody_sampler.py; original lines 1027-1177.

The first line above is the original module docstring's first line on
purpose: main() builds its argparse description from __doc__.splitlines()[0].
"""

from zyg_workflows.melody_sampler.constants import CATEGORY, VOICES, argparse, logging, sys

from zyg_workflows.melody_sampler.sample_index import index, voice_info, voice_keys

from zyg_workflows.melody_sampler.cinematic import (
    _CIN_EXTRA_ROLES,
    _CIN_ROLES,
    _role_db,
    arrange_cinematic,
    render_plan,
)

# ── Licences ─────────────────────────────────────────────────────────────────


def licence_refs(files):
    """Flatten whatever render_plan returned into license_gate's ref list."""
    out = []
    seen = set()
    if isinstance(files, dict):
        files = [f for v in files.values() for f in (v or [])]
    for fid in files or []:
        fid = str(fid)
        if fid not in seen:
            seen.add(fid)
            out.append((CATEGORY, fid))
    return out


def credits(files, log_fn=None):
    """Run the publish-stage licence fence over the samples actually played.

    Returns ambience_ingest.license_gate's dict verbatim:
    ``{'ok', 'violations', 'attributions'}``. The attribution lines are not
    advisory — a cc-by-* sample in the mix means that credit MUST appear in the
    episode credits.
    """
    from zyg_workflows import ambience_ingest

    return ambience_ingest.license_gate(licence_refs(files), log_fn=log_fn)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _note_name(m):
    if m is None:
        return '--'
    names = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
    return f'{names[m % 12]}{m // 12 - 1}'


def _print_voices():
    idx = index(log_fn=lambda m: print(m, file=sys.stderr))
    print(f'{"voice":18s} {"n":>5s}  {"range":<17s} {"packs":<16s} licences')
    print('-' * 88)
    for key, sel in VOICES.items():
        if sel is None:
            print(f'{key:18s} {"—":>5s}  {"(not in library)":<17s}')
            continue
        v = voice_info(key)
        rng = (
            f'{v["midi_lo"]:3d}-{v["midi_hi"]:<3d} {_note_name(v["midi_lo"])}-{_note_name(v["midi_hi"])}'
            if v['count']
            else '(empty)'
        )
        lic = ', '.join(f'{k}:{n}' for k, n in v['licences'].items())
        print(f'{key:18s} {v["count"]:5d}  {rng:<17s} {",".join(v["packs"]):<16s} {lic}')
    print(f'\n{len(voice_keys())} playable voices; {sum(len(r) for r in idx.values())} pitched samples indexed.')


def parse_extra(spec):
    """'marimba:ostinato' -> {'voice': 'marimba', 'role': 'ostinato'}.

    The same 'voice:role' string the thirteen cinematic styles carry in their
    `extra_layer` field, so the CLI and the style table speak one language.
    """
    txt = str(spec or '').strip()
    if not txt:
        return None
    voice, _, role = txt.partition(':')
    voice, role = voice.strip(), role.strip().lower()
    if voice not in VOICES:
        raise ValueError(f'unknown extra voice {voice!r}')
    if role not in _CIN_EXTRA_ROLES:
        raise ValueError(f'unknown extra role {role!r} (one of {", ".join(_CIN_EXTRA_ROLES)})')
    return {'voice': voice, 'role': role}


def _demo(out_wav, lead, pad, bass, seconds=30.0, family=None, extra=None):
    from zyg_workflows import kids_music_theory as T

    def log(m):
        print(m)

    cinematic = str(family or '') == 'cinematic'
    brief = {
        'theme': 'a melody sampler demo',
        'seconds': seconds,
        'age_band': 'cinematic' if cinematic else 'preschool',
        'mood': 'cinematic' if cinematic else 'happy',
    }
    plan = T.compose_best(brief, candidates=8, log_fn=log)
    voices = {'lead': lead, 'pad': pad, 'bass': bass}
    if cinematic:
        plan['family'] = 'cinematic'
        spec = parse_extra(extra)
        if spec:
            plan['extra'] = spec
            voices['extra'] = spec['voice']
            log(f'arrangement: extra layer {spec["voice"]} as {spec["role"]}')
    log(
        f'plan: {plan["bars"]} bars {plan["meter"]} {plan["bpm"]} bpm '
        f'{plan["key"]["label"]} score={plan["score"]["total"]:.3f}'
    )
    if cinematic:
        ev = arrange_cinematic(plan)
        log('layers: ' + ', '.join(f'{r}={len(ev[r])}' for r in _CIN_ROLES) + ' events')
    res = render_plan(plan, out_wav, voices=voices, log_fn=log)
    if not res['ok']:
        return 1
    if res.get('layers'):
        log('mix: ' + ', '.join(f'{r}={k}@{_role_db(plan, r):+.0f}dB' for r, k in res['layers'].items()))
    gate = credits(res['files'], log_fn=log)
    log(f'licences: ok={gate["ok"]} violations={len(gate["violations"])}')
    for att in gate['attributions']:
        log(f'  credit: {att}')
    log(f'out-of-range notes: {res["out_of_range_notes"]}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--voices', action='store_true', help='print the voice table')
    ap.add_argument('--refresh', action='store_true', help='rebuild the index cache')
    ap.add_argument('--demo', metavar='OUT.WAV', help='compose and render a demo')
    ap.add_argument('--lead', default='flute')
    ap.add_argument('--pad', default='guitar_nylon')
    ap.add_argument('--bass', default='double_bass_pizz')
    ap.add_argument('--seconds', type=float, default=30.0)
    ap.add_argument('--family', default=None, help="'cinematic' arranges four layers with a dynamic arc")
    ap.add_argument(
        '--extra',
        default=None,
        metavar='VOICE:ROLE',
        help='fourth layer, e.g. marimba:ostinato (' + '|'.join(_CIN_EXTRA_ROLES) + ')',
    )
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if args.refresh:
        index(refresh=True, log_fn=lambda m: print(m, file=sys.stderr))
    if args.voices:
        _print_voices()
    if args.demo:
        return _demo(args.demo, args.lead, args.pad, args.bass, args.seconds, family=args.family, extra=args.extra)
    if not args.voices and not args.refresh:
        ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
