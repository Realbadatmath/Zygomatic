# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Script writing: the per-match facts, the templates, the role-flip and
percentage audits, the parlay copy and the board rows (verbatim from
pipeline_sports.py)."""

from __future__ import annotations

from zyg_workflows.pipeline_sports.constants import (
    BJ,
    _display_selection,
    _entity_label,
    _kickoff_local,
    _log,
    _re_sp,
    _speech_label,
    _speech_selection,
    _speech_sub,
    _speechify,
)


# ── script writing ──────────────────────────────────────────────────────────


def _facts_for(bet: dict) -> list:
    # measured drivers, with raw odds-API names swapped for their spoken forms
    facts = [_speech_sub(bet, d) for d in (bet.get('drivers') or [])]
    ko = _kickoff_local(bet)
    if ko:
        facts.append(f'it starts {ko}')
    if bet.get('league'):
        facts.append(f'the competition is {bet["league"]}')
    if bet.get('starred'):
        facts.append('this is one of our one-unit bets of the day — a pick likely enough to actually back')
    others = [o for o in (bet.get('all_outcomes') or []) if o.get('name') != bet.get('selection')]
    for o in others[:2]:
        facts.append(
            _speech_sub(bet, f'the other side, {o["name"]}, is a ')
            + f'{float(o.get("fair_prob") or 0) * 100:.0f} percent chance at '
            f'a best price of {o.get("best_price")}'
        )
    facts.extend(_form_facts(bet))
    facts.extend(_injury_facts(bet))
    return facts


def _form_facts(bet: dict) -> list:
    """Measured recent-results and head-to-head facts (operator 2026-08-08:
    form, opponents faced and previous meetings belong in the analysis). Only
    what the results files actually contain — absent data means no sentence."""
    out = []
    for side in ('home', 'away'):
        rec = bet.get(f'{side}_recent') or []
        if len(rec) < 3:
            continue
        label = _speech_label(bet, side)
        w = sum(1 for g in rec if g['res'] == 'W')
        d_ = sum(1 for g in rec if g['res'] == 'D')
        l_ = sum(1 for g in rec if g['res'] == 'L')
        # tennis-data spells opponents "Osaka N." — drop the trailing initial
        # or the narrator reads "Osaka En"
        opps = ', '.join(_speechify(_re_sp.sub(r'\s+[A-Z]\.?$', '', g['opp'])) for g in rec[:3])
        drew = f', drew {d_}' if d_ else ''
        out.append(
            f'recorded form: {label} won {w}{drew} and lost {l_} of '
            f'their last {len(rec)} matches, most recently facing '
            f'{opps}'
        )
    h = bet.get('h2h') or {}
    meets = h.get('meetings') or []
    if len(meets) >= 2:
        home, away = _speech_label(bet, 'home'), _speech_label(bet, 'away')
        draws = f', {h["draws"]} draws' if h.get('draws') else ''
        out.append(
            f'head to head, their last {len(meets)} meetings: {home} '
            f'won {h.get("w_home", 0)}, {away} won {h.get("w_away", 0)}'
            f'{draws}'
        )
    return out


def _form_score(bet: dict):
    """Points-per-game of the SELECTION side over its recorded recent matches
    (3/1/0), None when the selection is a Draw or the data is too thin."""
    sel = bet.get('selection') or ''
    side = 'home' if sel == bet.get('home') else 'away' if sel == bet.get('away') else None
    if side is None:
        return None
    rec = bet.get(f'{side}_recent') or []
    if len(rec) < 5:
        return None
    pts = sum(3 if g['res'] == 'W' else (1 if g['res'] == 'D' else 0) for g in rec)
    return round(pts / len(rec), 3)


def _injury_facts(bet: dict) -> list:
    """Measured absences only — [] when the feed has nothing for these teams,
    and then the claims guard bans the LLM from inventing any."""
    out = []
    for side in ('home', 'away'):
        team = _speech_label(bet, side)
        for j in (bet.get(f'{side}_injuries') or [])[:3]:
            if not j.get('player'):
                continue
            line = f'injury news: {team} are missing {j["player"]} ({j.get("status") or "out"}'
            if j.get('detail'):
                line += f', {j["detail"]}'
            out.append(line + ')')
    return out


def _template_scripts(bet: dict, index: int, total: int) -> list:
    """Three panels of narration built straight from the measured facts."""
    home, away = _speech_label(bet, 'home'), _speech_label(bet, 'away')
    sel = _speech_selection(bet)
    ko = _kickoff_local(bet)
    drivers = [_speech_sub(bet, d) for d in (bet.get('drivers') or [])]
    kind = 'a value bet' if bet.get('bet_type') == 'value' else 'a confidence pick rather than a value bet'

    # No "Match 3 of 7" numbering (the count is on the board), no bookmaker
    # name (it is on screen), no Kelly/stake talk, no "odds move, act quickly"
    # — all operator cuts 2026-08-07/08.
    star_line = ' This is one of our one-unit bets of the day.' if bet.get('starred') else ''
    p1 = (
        f'{home} against {away}'
        f'{", in the " + bet["league"] if bet.get("league") else ""}'
        f'{", " + ko if ko else ""}. '
        f'Our selection here is {sel} at {bet.get("price")}. '
        f'This is {kind}.{star_line}'
    )
    p2 = (
        f'So why {sel}? '
        + (drivers[0] + '. ' if drivers else '')
        + (drivers[1] + '. ' if len(drivers) > 1 else '')
        + (f'That is why we are on {sel} at {bet.get("price")}.')
    )
    risk_bits = drivers[2:4]
    inj = _injury_facts(bet)
    inj_line = (' Squad news: ' + '; '.join(i.replace('injury news: ', '') for i in inj[:3]) + '.') if inj else ''
    p3 = (
        'And the other side of it. '
        + ('. '.join(risk_bits) + '. ' if risk_bits else '')
        + inj_line
        + f" Our model's fair price is {bet.get('fair_price')} against the "
        f'{bet.get("price")} on offer.'
    )
    return [p1, p2, p3]


def _role_flip(text: str, name: str, is_fav: bool) -> bool:
    """True when the copy assigns `name` the WRONG favourite/underdog role.

    Chapter 5 of the first episode called the 52% favourite Atlético Tucumán
    "the underdog" in one sentence and "favored" in the next — the numbers were
    all legal, the roles were inverted. Both word orders are checked."""
    n = _re_sp.escape(name)
    wrong = r'underdogs?' if is_fav else r'(?:favou?rites?|favored|favoured)'
    # the gap is deliberately TIGHT (≤12 chars): a wider window matched across
    # a comma into the next clause and blamed the wrong team for its neighbour's
    # perfectly correct role
    return bool(
        _re_sp.search(rf'\b{wrong}\b(?:\s+\w+){{0,2}}\s+{n}\b', text, _re_sp.I)
        or _re_sp.search(
            rf'\b{n}\b[^.!?,]{{0,12}}\b(?:is|are|was|remains?)\s+'
            rf'(?:the\s+)?(?:clear\s+|heavy\s+|heavily\s+)?{wrong}\b',
            text,
            _re_sp.I,
        )
    )


_PCT_RE = _re_sp.compile(r'(?<![\d.])(\d{1,2}) percent')


def _team_variants(bet: dict) -> dict:
    """{'home'|'away'|'draw': {name variants}} for attribution matching."""
    v = {'draw': {'Draw', 'draw', 'a draw', 'the draw'}}
    for side in ('home', 'away'):
        forms = {bet.get(side) or '', _entity_label(bet, side), _speech_label(bet, side)}
        v[side] = {f for f in forms if f}
    return v


def _nearest_team(variants: dict, text: str, before: int = None) -> str:
    """Team key of the LAST variant occurring before `before` in `text`."""
    hay = text if before is None else text[:before]
    best_key, best_pos = None, -1
    for key, forms in variants.items():
        for f in forms:
            i = hay.rfind(f)
            if i > best_pos:
                best_pos, best_key = i, key
    return best_key


def _pct_misattributions(bet: dict, parts: list, facts: list) -> list:
    """Integer percentages pinned to the WRONG side.

    The number guard checks that a percentage EXISTS in the facts; this checks
    it is attached to the right team. Real case: "Moreirense is the underdog,
    with a 55 percent chance against the favourite Braga" — 55 is Braga's
    probability, every digit legal, the sentence still false. A percentage is
    flagged only when every fact containing it names a DIFFERENT side; numbers
    that appear in nameless facts (implied-probability drivers) always pass."""
    variants = _team_variants(bet)
    allowed, nameless = {}, set()
    for f in facts or []:
        pcts = set(_PCT_RE.findall(f))
        if not pcts:
            continue
        f_teams = {k for k, forms in variants.items() if any(x in f for x in forms)}
        for p in pcts:
            if f_teams:
                allowed.setdefault(p, set()).update(f_teams)
            else:
                nameless.add(p)
    bad = []
    for sent in _re_sp.split(r'(?<=[.!?])\s+', ' '.join(parts)):
        for m in _PCT_RE.finditer(sent):
            p = m.group(1)
            team = _nearest_team(variants, sent, m.start())
            if team is None or p in nameless or p not in allowed:
                continue
            if team not in allowed[p]:
                bad.append(f'{p}% pinned to {team} but belongs to {"/".join(sorted(allowed[p]))}')
    return bad


def _role_flips(bet: dict, text: str) -> list:
    outs = bet.get('all_outcomes') or []
    if not outs:
        return []
    fav_raw = outs[0].get('name')  # all_outcomes is sorted by fair_prob desc
    flips = []
    for side in ('home', 'away'):
        raw = bet.get(side) or ''
        if not raw:
            continue
        for nm in {_speech_label(bet, side), _entity_label(bet, side)}:
            if nm and _role_flip(text, nm, raw == fav_raw):
                flips.append(
                    f'{nm} called '
                    f'{"underdog" if raw == fav_raw else "favourite"} '
                    f'but is the '
                    f'{"favourite" if raw == fav_raw else "underdog"}'
                )
                break
    return flips


def _write_scripts(pid, bet: dict, index: int, total: int) -> list:
    facts = _facts_for(bet)
    baseline = _template_scripts(bet, index, total)
    home, away = _speech_label(bet, 'home'), _speech_label(bet, 'away')
    prompt = (
        'You are the presenter of a daily sports-betting channel. Write ONE segment '
        'of the show as THREE short spoken parts. Rules, all mandatory:\n'
        '1. Do NOT introduce any number, price, percentage, date or statistic that is '
        'not already in the FACTS. Not one.\n'
        '2. You know NOTHING about these teams beyond the FACTS. Do NOT mention '
        'form, recent results or performances, streaks, head-to-head history, '
        "injuries, suspensions, line-ups, or the quality of anyone's defence, "
        'attack or tactics unless the FACTS state it.\n'
        '3. Only call a side the favourite or the underdog if the FACTS say which '
        'is which — never guess roles.\n'
        '4. Never claim a result is certain or guaranteed.\n'
        '5. Part 1 introduces the fixture and states the selection and its price. '
        'Part 2 argues FOR the selection using only the FACTS. Part 3 gives the '
        'counter-case.\n'
        '6. Conversational, upbeat and to the point — no exclamation marks, '
        '40 to 60 words per part, no headings, no emoji.\n'
        '7. Team names: use them exactly as written in FIXTURE and FACTS. '
        'Never name a bookmaker.\n'
        '8. You speak directly TO the viewer. Never say "behind me" — anything '
        'on screen is "in front of you". Never number the matches — do not say '
        '"match three of seven" or similar.\n'
        '9. NEVER mention Kelly, stakes, staking, units of bankroll, '
        'percentages of bankroll, or tell the viewer to hurry because odds '
        'move. Do not give staking advice at all.\n\n'
        f'FIXTURE: {home} vs {away}\n'
        f'OUR SELECTION: {_speech_selection(bet)} at {bet.get("price")}\n'
        'FACTS:\n- ' + '\n- '.join(facts) + '\n\n'
        'Answer STRICT JSON: {"parts": ["<part 1>", "<part 2>", "<part 3>"]}'
    )
    resp = BJ.ollama_json(prompt, num_predict=620, temperature=0.45)
    parts = (resp or {}).get('parts') or []
    if not isinstance(parts, list) or len(parts) < 3 or any(len(str(p).split()) < 18 for p in parts[:3]):
        _log(pid, 'WARNING', 'Write Script', f'{home} vs {away}: LLM gave nothing usable — speaking the measured facts')
        return baseline
    parts = [str(p).strip() for p in parts[:3]]
    written = ' '.join(parts)
    bad = BJ.llm_invented_numbers(written, facts + baseline)
    if bad:
        _log(
            pid,
            'WARNING',
            'Write Script',
            f'{home} vs {away}: LLM invented {sorted(bad)} — discarded, speaking the measured facts instead',
        )
        return baseline
    claims = BJ.unsupported_claims(written, facts + baseline)
    if claims:
        _log(
            pid,
            'WARNING',
            'Write Script',
            f'{home} vs {away}: LLM invented unmeasured claims '
            f'({"; ".join(claims)}) — discarded, speaking the measured facts',
        )
        return baseline
    flips = _role_flips(bet, written)
    if flips:
        _log(
            pid,
            'WARNING',
            'Write Script',
            f'{home} vs {away}: LLM inverted favourite/underdog roles '
            f'({"; ".join(flips)}) — discarded, speaking the measured facts',
        )
        return baseline
    mis = _pct_misattributions(bet, parts, facts)
    if mis:
        _log(
            pid,
            'WARNING',
            'Write Script',
            f'{home} vs {away}: LLM pinned a percentage to the wrong side '
            f'({"; ".join(mis)}) — discarded, speaking the measured facts',
        )
        return baseline
    stage_talk = _re_sp.search(
        r'\b(?:match|game|pick|selection)\s+(?:number\s+)?'
        r'(?:\d+|one|two|three|four|five|six|seven|eight|nine)\s+of\s+'
        r'(?:\d+|seven|eight|nine|ten)\b'
        r'|behind me\b'
        r'|\b(?:kelly|bankroll|stake|staking|staked)\b'
        r'|\bodds\s+(?:can\s+|do\s+|will\s+)?move\b'
        r'|\b(?:act|move)\s+(?:quickly|fast)\b'
        r'|\bbe prepared to act\b',
        written,
        _re_sp.I,
    )
    if stage_talk:
        _log(
            pid,
            'WARNING',
            'Write Script',
            f'{home} vs {away}: LLM used stage talk ({stage_talk.group(0)!r}) — discarded, speaking the measured facts',
        )
        return baseline
    return parts


def _welcome_script(bets: list, show_label: str, day_h: str) -> str:
    # Just the greeting and the card — the selection-count / look-at-the-board
    # tail was pure filler (operator cut it 2026-08-08, was 0:33-0:45). The
    # opener names the SUB-CHANNEL ("TokiToki Tennis"), matching the on-screen
    # tag (operator 2026-08-08).
    names = [f'{_speech_label(b, "home")} against {_speech_label(b, "away")}' for b in bets]
    listed = (
        (', '.join(names[:-1]) + ', and ' + names[-1]) if len(names) > 1 else (names[0] if names else 'nothing today')
    )
    return f"Welcome to {show_label}, let's hop right in. Our matches for today are: {listed}."


def _speech_final(text: str) -> str:
    """Last pass before anything reaches the voice: no symbols the engine could
    read out ('@' → 'at'), no doubled spaces. The narrator states what he needs
    to — nothing else rides along from screen formatting."""
    t = str(text or '').replace('@', ' at ').replace('★', ' ')
    t = t.replace(' %', ' percent').replace('&', ' and ')
    return _re_sp.sub(r'\s{2,}', ' ', t).strip()


# ── parlays (operator enhancement 2026-08-07) ───────────────────────────────


def _speech_leg(bets_by_id: dict, leg: dict) -> str:
    b = bets_by_id.get(leg.get('event_id'))
    return _speech_selection(b) if b else (leg.get('selection') or '')


def _display_leg(bets_by_id: dict, leg: dict) -> str:
    b = bets_by_id.get(leg.get('event_id'))
    return _display_selection(b) if b else (leg.get('selection') or '')


def _parlay_rows(parlays: list, bets_by_id: dict) -> list:
    rows = []
    for p in parlays:
        rows.append(
            {
                'label': p['label'],
                'legs': ' + '.join(_display_leg(bets_by_id, l) for l in p['legs']),
                'stats': f'{p["n_legs"]} legs · {p["prob_pct"]:.1f}% chance · edge {p["edge_pct"]:+.1f}%',
                'pays': f'{p["price"]:g}',
            }
        )
    return rows


def _overview_script(bets: list, day_h: str) -> str:
    starred = [b for b in bets if b.get('starred')]
    base = 'That is every match covered — the full card is on the board in front of you. '
    if len(starred) == 2:
        names = ' and '.join(_speech_selection(b) for b in starred)
        return base + (
            f'Now, our actual bets for {day_h}: one unit on '
            f'{names}. Those are the two picks on this card most '
            f'likely to win, marked with three golden stars. Single '
            f'bets, one unit each — everything else on the board is '
            f'analysis, not a wager.'
        )
    if len(starred) == 1:
        return base + (
            f'Our only actual bet for {day_h}: one unit on '
            f'{_speech_selection(starred[0])}, marked with three '
            f'golden stars — the one pick on this card likely '
            f'enough to back. Everything else is analysis, not a '
            f'wager.'
        )
    return base + (
        'No one-unit bets today: nothing on this card is likely '
        'enough to back, so the whole board stays analysis, not '
        'a wager.'
    )


def _parlay_script(parlays: list, bets_by_id: dict) -> str:
    lines = [
        'Before we sign off, the parlay sheet — a few ways to combine '
        "today's picks, strictly for fun money. Never more than four "
        'legs: a parlay multiplies the risk exactly as fast as the payout.'
    ]
    for p in parlays:
        names = [_speech_leg(bets_by_id, l) for l in p['legs']]
        listed = (', '.join(names[:-1]) + ' and ' + names[-1]) if len(names) > 1 else names[0]
        label_speech = p['label'].replace('★', '').strip()
        lines.append(
            f'{label_speech}: {listed}. The multiplied price is about '
            f'{p["price"]}, and our model makes it a {p["prob_pct"]:.1f} '
            f'percent chance.'
        )
    lines.append(
        'One honest note: those prices multiply the best price per '
        "match across different bookmakers, so your own book's parlay "
        'price will come out different.'
    )
    return ' '.join(lines)


# ── board ───────────────────────────────────────────────────────────────────


def _board_rows(bets: list) -> list:
    rows = []
    for b in bets:
        ko = _kickoff_local(b)
        rows.append(
            {
                # No character caps here — render_board measures each column against
                # its real pixel budget, so the full strings are safe to pass and the
                # board keeps as much of each name as actually fits.
                'left': f'{_entity_label(b, "home")} vs {_entity_label(b, "away")}',
                'mid': f'{b.get("league") or ""}{"  ·  " + ko if ko else ""}',
                'right': f'{_display_selection(b)} @ {b.get("price")}',
                'tone': 'up' if b.get('bet_type') == 'value' else 'neutral',
                'stars': bool(b.get('starred')),
            }
        )
    return rows


def _chapter_title(b: dict, i: int) -> str:
    # No 20-char slices: they shipped "New England Revoluti" as a chapter title.
    # YouTube accepts long chapter names; only guard against the absurd.
    t = f'{i}. {_entity_label(b, "home")} vs {_entity_label(b, "away")} — {_display_selection(b)} @ {b.get("price")}'
    return t if len(t) <= 96 else t[:95].rstrip() + '…'
