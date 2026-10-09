# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stages 1-3 of a betting episode: the run context, the fixtures and odds, the
selection and starring of the card, the measured research attached to it, and the
badge/cutout artwork — all lifted verbatim out of ``pipeline._run``.

``pipeline.py`` owns the orchestrator (and the four ``ZYG_BRIEF_*`` switches,
which the settings registry attributes to that file by name); every stage here is
a plain function over an :class:`EpisodeRun`, so it can be exercised on its own.
The import direction is one-way: ``pipeline`` imports this module, never the
reverse.
"""

from __future__ import annotations

import dataclasses
import functools
import os

from zyg_workflows.pipeline_sports.constants import (
    BJ,
    BV,
    CHANNELS,
    SI,
    _display_selection,
    _kickoff_local,
    _log,
    _stage,
    datetime,
)
from zyg_workflows.pipeline_sports.scripts import _form_score


@dataclasses.dataclass(frozen=True)
class EpisodeFlags:
    """The four ``ZYG_BRIEF_*`` switches, read once by the orchestrator."""

    injuries: bool = True
    player_art: bool = True
    parlays: bool = True
    jingles: bool = True


@dataclasses.dataclass
class EpisodeRun:
    """What every stage of one episode shares: the job id and its channel and
    category rows, the branded theme, the settings snapshot, the three output
    directories, the kanban marker id and the feature flags."""

    pid: str
    department: str
    category: str
    ch: dict
    cat: dict
    th_brand: dict
    s: dict
    out_dir: str
    work_dir: str
    charts_dir: str
    mid: object
    flags: EpisodeFlags


def card_sizes(s) -> tuple[int, int]:
    """Return (bets on air, bets to the ice box) from the settings snapshot `s`,
    falling back to the 7/4 default when a row is missing or empty."""
    return int(s.get('bets_per_episode') or 7), int(s.get('icebox_hold') or 4)


def _collect_log(pid, level, msg):
    """Log `msg` at `level` against job `pid`'s Collect Fixtures stage."""
    _log(pid, level, 'Collect Fixtures', msg)


def build_run(pid, department, category, flags) -> EpisodeRun:
    """Resolve the channel and category rows, the branded theme and the settings
    for job `pid`, create its output/work/chart directories and open its kanban
    marker. Returns the EpisodeRun every stage below takes as its first argument."""
    ch = CHANNELS[department]
    cat = SI.CATEGORIES[category]
    # branded corner tag: "TokiToki Tennis", "TokiToki Soccer", … (operator
    # 2026-08-08); every chart call below takes this dict instead of the theme
    # name so the sub-channel is on screen throughout
    th_brand = dict(BV.theme(ch['theme']))
    th_brand['name'] = f'{ch["label"]} {cat["label"]}'
    s = SI.settings()
    out_dir = os.path.join(BJ.out_root(department, category), pid)
    work_dir = os.path.join(out_dir, 'work')
    charts_dir = os.path.join(out_dir, 'charts')
    for d in (out_dir, work_dir, charts_dir):
        os.makedirs(d, exist_ok=True)
    mid = BJ.marker(f'{cat["emoji"]} {ch["label"]} {cat["label"]} {pid[:8]}', pid)
    return EpisodeRun(
        pid=pid,
        department=department,
        category=category,
        ch=ch,
        cat=cat,
        th_brand=th_brand,
        s=s,
        out_dir=out_dir,
        work_dir=work_dir,
        charts_dir=charts_dir,
        mid=mid,
        flags=flags,
    )


def collect_fixtures(run, opts):
    """Stage 1: research the fixtures and odds for `run`, honouring an operator
    `match_day` override in `opts`. Returns (research result, match day
    'YYYY-MM-DD', the same day spelled for the narration)."""
    pid = run.pid
    _stage(pid, 'Collect Fixtures', 5)
    depth = int(run.s.get('research_depth') or 14)
    bets_n, hold_n = card_sizes(run.s)
    day_override = str(opts.get('match_day') or '').strip()
    if day_override:
        _log(
            pid,
            'WARNING',
            'Collect Fixtures',
            f'operator day override: building for {day_override} instead of the D+2 default',
        )
    res = SI.research(
        run.category,
        want=max(depth, bets_n + hold_n),
        log=functools.partial(_collect_log, pid),
        stop=lambda: BJ.stopped(pid),
        day_override=day_override,
    )
    BJ.check_stop(pid)
    day = res['day']
    day_h = datetime.strptime(day, '%Y-%m-%d').strftime('%A %-d %B')
    _log(pid, 'INFO', 'Collect Fixtures', f'Odds API: {res.get("credit_note")}')
    return res, day, day_h


def select_bets(run, res, day):
    """Stage 2: split the researched card into the on-air selections and the ice
    box, star the one-unit bets and log the selection. Raises RuntimeError when
    fewer than three bets survived the filters."""
    pid = run.pid
    bets_n, hold_n = card_sizes(run.s)
    _stage(pid, 'Price & Select Bets', 16)
    allb = res['bets']
    if len(allb) < 3:
        raise RuntimeError(
            f'only {len(allb)} {run.category} bet(s) survived the filters for {day} '
            f'— not enough for an episode. ' + ('; '.join(res.get('skipped') or [])[:300] or 'no fixtures')
        )
    on_air = allb[:bets_n]
    on_ice = allb[bets_n : bets_n + hold_n]
    for b in allb:
        b['kickoff_local'] = _kickoff_local(b)
    _star_one_unit_bets(run, on_air)
    _log_selection(run, allb, on_air, on_ice)
    return on_air, on_ice


def _star_one_unit_bets(run, on_air):
    """Mark the (up to) two on-air selections most likely to win as one-unit bets
    and say out loud which ones, or that none cleared the likelihood floor."""
    pid = run.pid
    # THE ONE-UNIT BETS (operator rule 2026-08-08): of the on-air card, the
    # (up to) two selections MOST LIKELY TO WIN are actually bet — one unit
    # each, single bets, three golden stars everywhere. A star also has to
    # CLEAR A LIKELIHOOD FLOOR: a thin 3-bet card once starred two 18-25%
    # Draws as "most likely to win", which is not a bet, it is a shrug.
    # Fewer qualifiers → fewer (or zero) unit bets, said out loud.
    star_floor = float(run.s.get('unit_bet_min_prob') or 0.35)
    for b in [
        x
        for x in sorted(on_air, key=lambda x: -float(x.get('fair_prob') or 0))
        if float(x.get('fair_prob') or 0) >= star_floor
    ][:2]:
        b['starred'] = True
    starred = [b for b in on_air if b.get('starred')]
    if starred:
        _log(
            pid,
            'INFO',
            'Price & Select Bets',
            'one-unit bet(s) of the day (★★★): '
            + '; '.join(
                f'{_display_selection(b)} @ {b["price"]} ({float(b["fair_prob"]) * 100:.0f}% to win)' for b in starred
            ),
        )
    else:
        _log(
            pid,
            'INFO',
            'Price & Select Bets',
            f'no selection clears the {star_floor:.0%} likelihood floor — '
            f'no one-unit bets this episode, card is analysis only',
        )


def _log_selection(run, allb, on_air, on_ice):
    """Log the candidate/on-air/ice-box counts and one line per on-air bet."""
    pid = run.pid
    _log(
        pid,
        'INFO',
        'Price & Select Bets',
        f'{len(allb)} candidate(s) → {len(on_air)} on air, {len(on_ice)} to the ice box',
    )
    for b in on_air:
        _log(
            pid,
            'INFO',
            'Price & Select Bets',
            f'{b["home"]} vs {b["away"]}: {b["selection"]} @ {b["price"]} '
            f'({b["bet_type"]}, edge {b["edge_pct"]:+.1f}%, '
            f'{b["n_books"]} books)',
        )


def attach_research_data(run, on_air):
    """Stage 2b: attach the measured absences, the recent results and the
    head-to-head record to every on-air bet, score their form, then let a rotten
    recorded run take a star away from a selection that no longer deserves it."""
    _attach_injuries(run, on_air)
    _attach_results(run, on_air)
    _form_veto(run, on_air)


def _attach_injuries(run, on_air):
    """Fill `<side>_injuries` from the keyless ESPN feed when the flag is on."""
    pid = run.pid
    # measured absences (ESPN keyless feed — populated for NFL/NBA/WNBA,
    # verified empty for soccer 2026-08-07; [] simply means no mention)
    if run.flags.injuries:
        n_inj = 0
        for b in on_air:
            for side in ('home', 'away'):
                try:
                    b[f'{side}_injuries'] = SI.team_injuries(b.get(side) or '', b.get('sport_key'))
                except Exception:
                    b[f'{side}_injuries'] = []
                n_inj += len(b[f'{side}_injuries'])
        _log(
            pid,
            'INFO',
            'Price & Select Bets',
            f'injury feed: {n_inj} listed absence(s) across the card'
            + ('' if n_inj else ' (no data for these competitions — the script will not speculate)'),
        )


def _attach_results(run, on_air):
    """Fill `home_recent`/`away_recent`/`h2h`/`form_score` per on-air bet."""
    pid = run.pid
    cat = run.cat
    # measured recent results + head-to-head (football-data / tennis-data)
    n_rec = n_h2h = 0
    for b in on_air:
        try:
            if cat['entity'] == 'team':
                b['home_recent'] = SI.recent_results(b.get('home') or '', b.get('sport_key'))
                b['away_recent'] = SI.recent_results(b.get('away') or '', b.get('sport_key'))
                b['h2h'] = SI.h2h_results(b.get('home') or '', b.get('away') or '', b.get('sport_key'))
            else:
                b['home_recent'] = SI.player_recent_results(b.get('home') or '', b.get('sport_key'))
                b['away_recent'] = SI.player_recent_results(b.get('away') or '', b.get('sport_key'))
                b['h2h'] = SI.player_h2h(b.get('home') or '', b.get('away') or '', b.get('sport_key'))
        except Exception:
            b.setdefault('home_recent', [])
            b.setdefault('away_recent', [])
            b.setdefault('h2h', {})
        n_rec += len(b.get('home_recent') or []) + len(b.get('away_recent') or [])
        n_h2h += len((b.get('h2h') or {}).get('meetings') or [])
        b['form_score'] = _form_score(b)
    _log(
        pid,
        'INFO',
        'Price & Select Bets',
        f'results data: {n_rec} recent result(s) and {n_h2h} past '
        f'meeting(s) resolved across the card' + ('' if n_rec else ' — no coverage for these competitions'),
    )


def _form_veto(run, on_air):
    """Move a star off a starred side whose recorded run is rotten (≤0.4 pts/game
    over ≥5) onto the next most-likely pick in decent form (≥1.5 pts/game)."""
    pid = run.pid
    # FORM SANITY VETO on the one-unit bets: a starred side with a rotten
    # recorded run (≤0.4 pts/game over ≥5) yields its star to the next
    # most-likely pick in decent form (≥1.5 pts/game). Logged, never silent.
    pool = sorted([b for b in on_air if not b.get('starred')], key=lambda x: -float(x.get('fair_prob') or 0))
    for b in [x for x in on_air if x.get('starred')]:
        sc = b.get('form_score')
        if sc is None or sc > 0.4:
            continue
        alt = next((a for a in pool if (a.get('form_score') or 0) >= 1.5), None)
        if alt is not None:
            b['starred'] = False
            alt['starred'] = True
            pool.remove(alt)
            _log(
                pid,
                'WARNING',
                'Price & Select Bets',
                f'form veto: {_display_selection(b)} loses its star '
                f'(form {sc} pts/game) — {_display_selection(alt)} '
                f'(form {alt["form_score"]}) takes it',
            )


def pull_artwork(run, on_air):
    """Stage 3: download the badge or fighter art for both sides of every on-air
    bet, plus the key-player cutouts when the flag is on. Returns (art,
    players_art), both keyed by (event_id, side)."""
    _stage(run.pid, 'Pull Team Art', 24)
    return _entity_art(run, on_air), _player_cutouts(run, on_air)


def _entity_art(run, on_air):
    """Download one badge/photo per side; missing ones fall back to initials."""
    pid = run.pid
    cat = run.cat
    art, missing = {}, 0
    for b in on_air:
        BJ.check_stop(pid)
        for side in ('home', 'away'):
            ent = b.get(f'{side}_entity') or {}
            p = SI.download_art(ent)
            art[(b['event_id'], side)] = p
            if not p:
                missing += 1
    _log(
        pid,
        'INFO',
        'Pull Team Art',
        f'{len(on_air) * 2 - missing}/{len(on_air) * 2} '
        f'{"badges" if cat["entity"] == "team" else "fighter photos"} resolved'
        + (f' — {missing} fall back to an initials card' if missing else ''),
    )
    return art


def _player_cutouts(run, on_air):
    """Download up to three key-player cutouts per side of a team fixture."""
    pid = run.pid
    cat = run.cat
    # key players around the badge (operator enhancement 2026-08-07)
    players_art: dict = {}
    if cat['entity'] == 'team' and run.flags.player_art:
        n_cut = 0
        for b in on_air:
            BJ.check_stop(pid)
            for side in ('home', 'away'):
                lst = []
                try:
                    for p in SI.team_players(b.get(side) or '', run.category, league_hint=b.get('sport_key') or ''):
                        lp = SI.download_art({'image': p.get('image'), 'display': p.get('name')})
                        if lp:
                            lst.append({'name': p['name'], 'img': lp, 'source': p.get('source') or ''})
                except Exception as _pe:
                    _log(pid, 'WARNING', 'Pull Team Art', f'players for {b.get(side)}: {_pe!r}')
                players_art[(b['event_id'], side)] = lst[:3]
                n_cut += len(lst[:3])
        n_espn = sum(1 for lst in players_art.values() for p in lst if p.get('source') == 'ESPN')
        _log(
            pid,
            'INFO',
            'Pull Team Art',
            f'{n_cut} key-player cutout(s) resolved for the badge cards'
            + (f' — {n_espn} swapped to ESPN headshots (stale shirt on TheSportsDB)' if n_espn else '')
            + ' (TheSportsDB free key caps rosters at ~10 — best-effort)',
        )
    return players_art
