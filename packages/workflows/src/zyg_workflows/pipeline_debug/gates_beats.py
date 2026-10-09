# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The prompt-side twin: qc_beat_prominence asks who is the sentence SUBJECT of
each beat — milliseconds on text, before the 90-minute render."""

from .gates_charbal_detect import _BEAT_EVEN_SHARE_FRAC
from .gates_v7 import _gate_thr, _record_qc


# ── the prompt-side twin ─────────────────────────────────────────────────────────────────
# v11's four beats were ALL Cornelis actions; Abel appeared only after a colon. The measured
# consequence was a 2.24x face-aliveness gap. That is a text property, knowable in
# milliseconds, and it cost a 90-minute render to discover. Hence this gate.
#
# HONEST DESCRIPTION OF THE HEURISTIC — it is not a parser and there is no POS tagging:
#   1. the beat is cut at the FIRST subordinating separator (':' ';' em/en dash, ' while ',
#      ' as ', ' whose ', ' watching ', ' behind ', ' beside ', ' next to ',
#      ' in the background'). Everything after it is the subordinate tail.
#   2. a leading adverbial phrase is stripped from the main clause when it starts with a
#      known preposition and ends at the first comma ("On the right, zygabel ..." -> the
#      subject is zygabel, not whoever the phrase mentions).
#   3. the character whose alias appears EARLIEST in what remains leads the beat.
# KNOWN FAILURE MODES, all of which the override exists for: pronoun subjects ("he draws on
# the pipe" attributes to nobody), passive voice ("the ledger is signed by Abel" attributes
# to Abel wrongly-but-harmlessly), a name inside the main clause's object ("Cornelis watches
# Abel write" leads Cornelis, correctly, but "Cornelis hands Abel the quill" also leads
# Cornelis when the shot may really be Abel's), and any beat whose separators are unusual.
# OVERRIDE: pass a beat as {'text': ..., 'lead': 'abel'} and the heuristic is skipped for it
# entirely; pass aliases={'abel': ['the boy', 'the clerk']} to teach it role words. Both are
# recorded in the output as source='declared' so a reader can see what was asserted.
_BEAT_SUBORDINATORS = (
    ':',
    ';',
    ' — ',
    ' – ',
    ' -- ',
    ' while ',
    ' as ',
    ' whose ',
    ' watching ',
    ' behind ',
    ' beside ',
    ' next to ',
    ' in the background',
)
_BEAT_LEADING_PREPS = (
    'in ',
    'on ',
    'at ',
    'beside ',
    'behind ',
    'across ',
    'near ',
    'under ',
    'over ',
    'by ',
    'between ',
    'from ',
    'through ',
    'during ',
    'after ',
    'before ',
    'while ',
    'as ',
    'with ',
    'to the left',
    'to the right',
    'on the left',
    'on the right',
)


def _beat_text(b):
    """A beat may be a bare string or a dict; return (text, declared_lead)."""
    if isinstance(b, dict):
        for k in ('text', 'prompt', 'beat', 'positive', 'description'):
            if isinstance(b.get(k), str) and b[k].strip():
                return b[k], (b.get('lead') or b.get('subject') or None)
        return '', (b.get('lead') or b.get('subject') or None)
    return (b if isinstance(b, str) else ''), None


def _beat_aliases(characters, aliases=None):
    """{name: [alias, ...]} — the name itself plus the zyg-prefixed trigger token both
    ways, because prompts here are written with tokens like 'zygabel' and \\babel\\b does
    NOT match inside it."""
    names = list(characters.keys()) if isinstance(characters, dict) else list(characters or [])
    amap = {}
    for n in names:
        got = {str(n).lower()}
        if isinstance(characters, dict):
            spec = characters.get(n)
            if isinstance(spec, dict) and spec.get('aliases'):
                got |= {str(a).lower() for a in spec['aliases']}
            elif isinstance(spec, (list, tuple)) and spec and isinstance(spec[0], str):
                got |= {str(a).lower() for a in spec}
        low = str(n).lower()
        got.add(low[3:] if low.startswith('zyg') and len(low) > 4 else 'zyg' + low)
        for a in (aliases or {}).get(n) or []:
            got.add(str(a).lower())
        amap[str(n)] = sorted(got, key=len, reverse=True)
    return amap


def _beat_split(text):
    """(main clause, subordinate tail) at the first subordinating separator."""
    low = ' ' + (text or '').lower()
    cut = None
    for sep in _BEAT_SUBORDINATORS:
        i = low.find(sep)
        if i >= 0 and (cut is None or i < cut[0]):
            cut = (i, len(sep))
    if cut is None:
        return (text or '').strip(), ''
    return (text or '')[: max(0, cut[0] - 1)].strip(), (text or '')[cut[0] - 1 + cut[1] :].strip()


def _beat_strip_lead_phrase(main):
    """Drop a leading prepositional phrase ('On the right, ...') so the subject is next."""
    low = (main or '').lstrip().lower()
    for p in _BEAT_LEADING_PREPS:
        if low.startswith(p):
            i = (main or '').find(',')
            if 0 <= i < len(main) - 1:
                return main[i + 1 :].strip(), main[: i + 1].strip()
            break
    return (main or '').strip(), ''


def qc_beat_prominence(
    beats, characters, min_share=None, aliases=None, tag=None, clip_path=None, log_fn=None, fail_open=True
):
    """Who is the SENTENCE SUBJECT of each beat? (2026-08-01, static, no video.)

    This is the gate that would have caught scene 20 v11 before the render: four beats, all
    four led by Cornelis, Abel present only as a post-colon clause — and the finished clip
    measured Cornelis's face 2.24x as alive as Abel's.

    beats: list of strings, or of {'text': ..., 'lead': 'abel'} where 'lead' OVERRIDES the
      heuristic for that beat (source='declared' in the output).
    characters: the same dict qc_character_balance takes, or a list of names, or
      {name: [aliases]}. Aliases can also be given per character as {'aliases': [...]}.
    min_share: None -> 0.8 / n_characters, i.e. "you may be the supporting character, but
      not by more than 20% below an even split". With 2 characters that is 0.40, so of four
      beats you must lead at least two — exactly the fix v11 needed. Scalar or {name: share}.

    Read the heuristic's documented failure modes in the block above before trusting a
    verdict on prose the pipeline did not generate.

    Returns {'ok', 'n_beats', 'beats': [...], 'characters': {name: {'leads','share',
    'subordinate_only','mentions','ok'}}, 'checks': [...]}. Advisory: fail-open on error."""
    log = log_fn or (lambda _m: None)
    out = {
        'tag': tag or 'beat_prominence',
        'kind': 'beat_prominence',
        'ok': True,
        'beats': [],
        'characters': {},
        'checks': [],
        'reasons': [],
    }
    if clip_path:
        out['path'] = clip_path
    try:
        import re

        amap = _beat_aliases(characters, aliases)
        if not amap:
            out['error'] = 'no characters supplied — THIS GATE DID NOT RUN'
            out['reasons'].append(out['error'])
            log(f'[qc_beat_prominence] {out["error"]}')
            _record_qc(out)
            return out
        pats = {n: [re.compile(r'\b' + re.escape(a) + r'\b', re.I) for a in al] for n, al in amap.items()}
        blist = list(beats or [])
        out['n_beats'] = len(blist)
        if not blist:
            out['error'] = 'no beats supplied — THIS GATE DID NOT RUN'
            out['reasons'].append(out['error'])
            log(f'[qc_beat_prominence] {out["error"]}')
            _record_qc(out)
            return out
        tally = {n: {'leads': [], 'mentions': [], 'subordinate_only': []} for n in amap}
        for i, b in enumerate(blist):
            text, declared = _beat_text(b)
            main_raw, sub = _beat_split(text)
            main, dropped = _beat_strip_lead_phrase(main_raw)
            rec = {
                'i': i,
                'text': text[:400],
                'main': main[:240],
                'subordinate': sub[:240],
                'dropped_lead_phrase': dropped[:120] or None,
                'lead': None,
                'source': None,
                'mentions': [],
                'subordinate_only': [],
            }
            if declared and str(declared) in amap:
                rec['lead'], rec['source'] = str(declared), 'declared'
            elif declared:
                rec['source'] = 'declared-unknown'
                out['reasons'].append(f'beat {i}: declared lead {declared!r} is not one of {sorted(amap)}')
            first = None
            for n, ps in pats.items():
                hit_main = min((m.start() for p in ps for m in [p.search(main)] if m), default=None)
                hit_any = any(p.search(text) for p in ps)
                if hit_any:
                    rec['mentions'].append(n)
                    tally[n]['mentions'].append(i)
                if hit_main is not None and (first is None or hit_main < first[1]):
                    first = (n, hit_main)
                if hit_any and hit_main is None:
                    rec['subordinate_only'].append(n)
                    tally[n]['subordinate_only'].append(i)
            if rec['lead'] is None and first is not None:
                rec['lead'], rec['source'] = first[0], 'heuristic'
            if rec['lead'] is None:
                rec['source'] = rec['source'] or 'unattributed'
            else:
                tally[rec['lead']]['leads'].append(i)
            out['beats'].append(rec)
            log(
                f'[qc_beat_prominence] beat {i}: lead={rec["lead"] or "UNATTRIBUTED"} '
                f'({rec["source"]}) main={main[:70]!r}'
                + (f' subordinate-only={rec["subordinate_only"]}' if rec['subordinate_only'] else '')
            )

        n = len(blist)
        default_share = _BEAT_EVEN_SHARE_FRAC / max(1, len(amap))
        out['min_share_default'] = round(default_share, 4)
        for name, t in tally.items():
            share = len(t['leads']) / max(1, n)
            thr = _gate_thr(min_share, name, default_share)
            ok = not (thr is not None and share < float(thr))
            reasons = []
            if not ok:
                sub_note = (
                    f' and appears ONLY in a subordinate clause in beat(s) {t["subordinate_only"]}'
                    if t['subordinate_only']
                    else ''
                )
                reasons.append(
                    f'{name} is the sentence subject of {len(t["leads"])}/{n} beats '
                    f'(share {share:.2f} < {thr:.2f}){sub_note} — measured on v11, a '
                    f'character with 0/4 rendered at 2.24x LESS face motion than the one '
                    f'who led every beat. Rewrite so {name} owns the MAIN CLAUSE of at '
                    f'least {int(-(-float(thr) * n // 1))} beat(s)'
                )
            out['characters'][name] = {
                'leads': t['leads'],
                'lead_count': len(t['leads']),
                'share': round(share, 3),
                'mentions': t['mentions'],
                'subordinate_only': t['subordinate_only'],
                'min_share': round(float(thr), 3) if thr is not None else None,
                'ok': ok,
                'reasons': reasons,
            }
            out['checks'].append(
                {
                    'check': f'beat_prominence:{name}',
                    'ok': ok,
                    'share': round(share, 3),
                    'lead_count': len(t['leads']),
                    'n_beats': n,
                    'min_share': round(float(thr), 3) if thr is not None else None,
                    'subordinate_only': len(t['subordinate_only']),
                    'note': '; '.join(reasons),
                }
            )
            log(
                f'[qc_beat_prominence] {name}: leads {len(t["leads"])}/{n} '
                f'(share {share:.2f}, min {thr}) -> {"PASS" if ok else "FAIL"}'
            )
            for r in reasons:
                log(f'[qc_beat_prominence]   {r}')
        una = [b['i'] for b in out['beats'] if b['lead'] is None]
        if una:
            msg = (
                f'beat(s) {una} name no character in the main clause — pronoun subjects '
                f'and passive voice are invisible to this heuristic. They still count in '
                f'the denominator, which is deliberate: an unattributed beat belongs to '
                f'nobody and dilutes everyone. Declare them with {{"lead": "<name>"}}'
            )
            out['checks'].append(
                {'check': 'beat_prominence:unattributed', 'ok': False, 'unattributed': len(una), 'note': msg}
            )
            out['reasons'].append(msg)
            log(f'[qc_beat_prominence] {msg}')
        if n > 4:
            out['checks'].append(
                {
                    'check': 'beat_prominence:beat_count',
                    'ok': True,
                    'n_beats': n,
                    'note': f'{n} beats — informational: the 341-frame/81-context recipe maps '
                    f'six windows onto FOUR beats without a dead one; five or more has '
                    f'always killed beat 0. wan_vace_service.assert_no_dead_beats() is '
                    f'the gate for that, not this one',
                }
            )
        out['ok'] = all(c.get('ok', True) for c in out['checks'])
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = bool(fail_open)
        log(f'[qc_beat_prominence] ERROR (fail-{"open" if fail_open else "CLOSED"}): {e}')
    _record_qc(out)
    return out


_REGRESSION_WORSE_WHEN = {
    'flow_median': 'down',
    'flow_mean': 'down',
    'net_path': 'down',
    'reversals_per_s': 'up',
    'burst_frac': 'down',
}
