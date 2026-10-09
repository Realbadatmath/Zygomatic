# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stages 5-7 of a betting episode: the charts, the render spec, the render
itself and the delivery — all lifted verbatim out of ``pipeline._run``.

Every stage is a plain function over the :class:`~zyg_workflows.pipeline_sports.
pipeline_card.EpisodeRun` the card stages built, so it can be exercised on its
own. The import direction is one-way: ``pipeline`` imports this module, never the
reverse, and ``_description_intro`` reaches :func:`build_render_spec` as an
injected callable rather than through a back-import.
"""

from __future__ import annotations

import dataclasses
import functools
import os

from zyg_workflows import paths
from zyg_workflows.pipeline_sports.constants import (
    ATTRIBUTION,
    BJ,
    BV,
    DISCLAIMER,
    OUTRO_LINE,
    SI,
    _display_selection,
    _entity_label,
    _log,
    _stage,
    shutil,
)
from zyg_workflows.pipeline_sports.scripts import (
    _board_rows,
    _chapter_title,
    _overview_script,
    _parlay_rows,
    _parlay_script,
    _speech_final,
)


@dataclasses.dataclass
class EpisodeCharts:
    """Every chart the episode renders: the opening board, the three panels per
    chapter, the optional parlay chapters and the outro card."""

    board_png: str
    panels: list
    parlays: list
    parlay_items: list
    outro_png: str


def _render_log(pid, level, msg):
    """Attribute an engine log line to whatever stage is actually current — the
    engine logs narration, encoding and QC through one callback, and stamping
    them all 'Render Episode' made the job log misleading."""
    _log(pid, level, (BJ.jobs().get(pid) or {}).get('current_stage') or 'Render Episode', msg)


def _render_progress(pid, stage, pct):
    """Map an engine progress stage onto this job's stage name and record `pct`."""
    _stage(pid, {'Narrate': 'Narrate', 'Render': 'Render Episode', 'QC Gates': 'QC Gates'}.get(stage, stage), pct)


def build_charts(run, on_air, art, players_art, day_h) -> EpisodeCharts:
    """Stage 5: render the opening board, the three panels of every chapter, the
    optional parlay sheet and the outro card. Returns their paths."""
    _stage(run.pid, 'Build Charts', 38)
    board_png = os.path.join(run.charts_dir, 'board.png')
    BV.render_board(
        run.th_brand,
        'Our matches for today',
        f'{day_h} · {len(on_air)} selections · {run.cat["label"]}',
        _board_rows(on_air),
        board_png,
        '18+ · gamble responsibly · odds move, always check your book',
    )
    panels = _chapter_panels(run, on_air, art, players_art)
    parlays, parlay_items = _parlay_sheet(run, on_air, day_h)
    outro_png = os.path.join(run.charts_dir, 'outro.png')
    BV.render_card(
        run.th_brand,
        'Thanks for watching',
        ['Free betting tips in our telegram', 'Like · Subscribe · See you next time', '18+ · gamble responsibly'],
        outro_png,
        'begambleaware.org',
    )
    return EpisodeCharts(board_png, panels, parlays, parlay_items, outro_png)


def _chapter_panels(run, on_air, art, players_art):
    """Render [matchup, the side we back, the risk] for each on-air bet; a Draw
    selection has no badge of its own and stays on the matchup card."""
    pid = run.pid
    th_brand = run.th_brand
    panels = []
    for i, b in enumerate(on_air):
        BJ.check_stop(pid)
        ha = art.get((b['event_id'], 'home')) or ''
        aa = art.get((b['event_id'], 'away')) or ''
        base = os.path.join(run.charts_dir, f'{i + 1:02d}')
        m_png = BV.render_matchup(
            th_brand,
            b,
            base + '_matchup.png',
            ha,
            aa,
            home_players=players_art.get((b['event_id'], 'home')),
            away_players=players_art.get((b['event_id'], 'away')),
        )
        pick_side = 'home' if b['selection'] == b['home'] else ('away' if b['selection'] == b['away'] else '')
        other = 'away' if pick_side == 'home' else 'home'
        if pick_side:
            f1 = BV.render_entity_focus(
                th_brand,
                b[f'{pick_side}_entity'],
                art.get((b['event_id'], pick_side)),
                f'Why {_display_selection(b)}',
                f'Backed at {b["price"]} · fair {b["fair_price"]}',
                base + '_pick.png',
                players=players_art.get((b['event_id'], pick_side)),
            )
            f2 = BV.render_entity_focus(
                th_brand,
                b[f'{other}_entity'],
                art.get((b['event_id'], other)),
                f'The risk: {_entity_label(b, other)}',
                f'Edge {b["edge_pct"]:+.1f}% · fair {b["fair_price"]}',
                base + '_risk.png',
                players=players_art.get((b['event_id'], other)),
            )
        else:
            # a Draw selection has no badge of its own — stay on the matchup
            f1 = f2 = m_png
        panels.append([m_png, f1, f2])
    return panels


def _parlay_sheet(run, on_air, day_h):
    """Build the parlay combinations and, when there are any, the two extra
    chapters (bet overview + parlay sheet) that close the episode."""
    pid = run.pid
    th_brand = run.th_brand
    # ── parlay sheet (after all chapters + a bet-overview recap) ────────
    parlays, parlay_items = [], []
    if run.flags.parlays:
        parlays = SI.build_parlays(on_air, banker_ids=[b.get('event_id') for b in on_air if b.get('starred')])
    if parlays:
        bets_by_id = {b.get('event_id'): b for b in on_air}
        overview_png = os.path.join(run.charts_dir, 'overview.png')
        BV.render_board(
            th_brand,
            'The card at a glance',
            f'{day_h} · {len(on_air)} selections · {run.cat["label"]}',
            _board_rows(on_air),
            overview_png,
            '18+ · gamble responsibly · odds move, always check your book',
        )
        parlay_png = os.path.join(run.charts_dir, 'parlays.png')
        BV.render_parlay_sheet(
            th_brand,
            'The parlay sheet',
            f'{len(parlays)} combinations · 2-4 legs, never more',
            _parlay_rows(parlays, bets_by_id),
            parlay_png,
            "multiplied best prices — your book's parlay price will differ · 18+ gamble responsibly",
        )
        parlay_items = [
            {
                'chapter': 'Bet overview',
                'panels': [
                    {
                        'image': overview_png,
                        'text': _speech_final(_overview_script(on_air, day_h)),
                        'ken_burns': False,
                        'min_seconds': 11,
                    }
                ],
            },
            {
                'chapter': 'The parlay sheet',
                'panels': [
                    {
                        'image': parlay_png,
                        'text': _speech_final(_parlay_script(parlays, bets_by_id)),
                        'ken_burns': False,
                        'min_seconds': 11,
                    }
                ],
            },
        ]
        _log(
            pid,
            'INFO',
            'Build Charts',
            f'parlay sheet: {len(parlays)} combination(s) — '
            + '; '.join(
                f'{p["label"]} pays {p["price"]} ({p["prob_pct"]:.1f}%, edge {p["edge_pct"]:+.1f}%)' for p in parlays
            ),
        )
    return parlays, parlay_items


def attribution_note(players_art) -> str:
    """The licence note for the description: the fixed attribution plus a credit
    per photo source actually used by a cutout on screen."""
    return ATTRIBUTION + ''.join(
        f' Additional player photos: {src}.'
        for src in ('API-SPORTS', 'ESPN')
        if any(p.get('source') == src for lst in players_art.values() for p in lst)
    )


def build_render_spec(run, *, charts, welcome, scripts, on_air, day, day_h, players_art, description_intro) -> dict:
    """Stage 6a: assemble the render spec the video engine takes — the voice, the
    slug, the welcome board, one chapter per on-air bet (plus the parlay
    chapters), the jingles, the outro and the description. `description_intro` is
    the orchestrator's own `_description_intro`, injected to keep this module's
    import direction one-way (and the operator's monkeypatch target single)."""
    ch = run.ch
    s = run.s
    jingle_dir = paths.DATA_DIR / 'assets' / 'audio'
    return {
        'channel': ch['label'],
        'theme': ch['theme'],
        'voice_seed': s.get(ch['voice_key']) or '',
        'voice_id': f'briefing-{run.department}',
        'slug': f'{run.department}_{run.category}_{day.replace("-", "")}_{run.pid[:6]}',
        'welcome_text': _speech_final(welcome),
        'welcome_chapter': "Welcome & today's matches",
        'board_png': charts.board_png,
        'board_seconds': float(s.get('opening_chart_seconds') or 8),
        'items': [
            {
                'chapter': _chapter_title(b, i + 1),
                'panels': [
                    {'image': charts.panels[i][0], 'text': _speech_final(scripts[i][0]), 'ken_burns': False},
                    {'image': charts.panels[i][1], 'text': _speech_final(scripts[i][1]), 'ken_burns': True},
                    {'image': charts.panels[i][2], 'text': _speech_final(scripts[i][2]), 'ken_burns': True},
                ],
            }
            for i, b in enumerate(on_air)
        ]
        + charts.parlay_items,
        'outro_png': charts.outro_png,
        'jingle_intro': (str(jingle_dir / 'brief_intro.wav') if run.flags.jingles else ''),
        'jingle_outro': (str(jingle_dir / 'brief_outro.wav') if run.flags.jingles else ''),
        'outro_text': _speech_final(OUTRO_LINE),
        'outro_chapter': 'Telegram, and see you next time',
        'description_intro': description_intro(ch, run.cat, on_air, day_h, parlays=charts.parlays),
        'disclaimer': DISCLAIMER,
        'attribution_note': attribution_note(players_art),
    }


def render_episode(run, spec):
    """Stage 6b: narrate, render and QC the episode. Returns the engine's result
    dict; raises RuntimeError (naming the quarantine, if any) when it failed."""
    pid = run.pid
    result = BV.render_episode(
        spec,
        run.work_dir,
        run.out_dir,
        log=functools.partial(_render_log, pid),
        check_stop=lambda: BJ.check_stop(pid),
        progress=functools.partial(_render_progress, pid),
    )
    if result.get('error'):
        raise RuntimeError(
            f'render failed: {result["error"]}'
            + (f' (quarantined at {result["quarantined"]})' if result.get('quarantined') else '')
        )
    return result


def episode_record(run, result, res, on_air, on_ice, parlays, day) -> dict:
    """The episode.json payload: the job, the channel, the match day, the video
    and its QC, every on-air bet minus its raw outcomes, the parlays, the ice
    box, the artwork/odds credits and the one-unit bets."""
    episode = {
        'job_id': run.pid,
        'department': run.department,
        'channel': run.ch['label'],
        'category': run.category,
        'sub_channel': f'{run.ch["label"]}{run.cat["label"]}',
        'match_day': day,
        'built_at': BJ.now_iso(),
        'duration_s': result['duration'],
        'video': result['video'],
        'description': result['description'],
        'chapters': result['chapters'],
        'qc': result['qc'],
        'bets': [{k: v for k, v in b.items() if k != 'all_outcomes'} for b in on_air],
        'parlays': parlays,
        'icebox': [f'{b["home"]} vs {b["away"]}' for b in on_ice],
        'skipped': res.get('skipped'),
        'artwork_source': 'TheSportsDB',
        'artwork_licence_note': ('used unmodified; credited in the description per thesportsdb.com terms of use'),
        'odds_credit_note': res.get('credit_note'),
        'ttl_hours': float(run.s.get('delivery_ttl_hours') or 72),
    }
    episode['unit_bets'] = [
        {
            'match': f'{b["home"]} vs {b["away"]}',
            'selection': b.get('selection'),
            'odds': b.get('price'),
            'book': b.get('book'),
            'fair_prob': b.get('fair_prob'),
            'units': 1,
            'stars': 3,
        }
        for b in on_air
        if b.get('starred')
    ]
    return episode


def deliver_episode(run, result, res, on_air, on_ice, parlays, day):
    """Stage 7: write episode.json, register the history, the one-unit bets and
    the star experiment, park the ice box, drop the work dir and finish the job."""
    pid = run.pid
    _stage(pid, 'Deliver', 93)
    episode = episode_record(run, result, res, on_air, on_ice, parlays, day)
    BJ._save_json(os.path.join(run.out_dir, 'episode.json'), episode)
    SI.history_add(on_air, run.ch['label'], run.category, pid)
    SI.unit_bets_add([b for b in on_air if b.get('starred')], run.ch['label'], run.category, pid, day)
    _log(pid, 'INFO', 'Deliver', 'one-unit bets registered to data/runtime/sports_unit_bets.json')
    _log_star_experiment(run, on_air, day)
    _park_icebox(run, on_ice)
    _cleanup_and_finish(run, result, on_air, day)


def _log_star_experiment(run, on_air, day):
    """Record the market-vs-form counterfactual for this episode's stars."""
    pid = run.pid
    form_ranked = sorted([b for b in on_air if b.get('form_score') is not None], key=lambda x: -x['form_score'])
    SI.star_experiment_add(
        pid,
        run.ch['label'],
        run.category,
        day,
        market_stars=[b['event_id'] for b in on_air if b.get('starred')],
        form_stars=[b['event_id'] for b in form_ranked[:2]],
        bets=on_air,
    )
    _log(
        pid,
        'INFO',
        'Deliver',
        'star experiment logged (market vs form selection) — '
        + (
            ', '.join(_display_selection(b) for b in form_ranked[:2])
            if form_ranked
            else 'no form data for a counterfactual'
        ),
    )


def _park_icebox(run, on_ice):
    """Park the held-back bets for telegram/X and say which they are."""
    pid = run.pid
    _stage(pid, 'Ice Box', 96)
    SI.icebox_add(on_ice, run.ch['label'], run.category)
    _log(
        pid,
        'INFO',
        'Ice Box',
        f'{len(on_ice)} bet(s) parked for telegram/X: '
        + (', '.join(f'{b["home"]} vs {b["away"]}' for b in on_ice) or '(none)'),
    )


def _cleanup_and_finish(run, result, on_air, day):
    """Remove the work dir, announce the TTL and close the job and its marker."""
    pid = run.pid
    _stage(pid, 'Cleanup', 98)
    shutil.rmtree(run.work_dir, ignore_errors=True)
    ttl = float(run.s.get('delivery_ttl_hours') or 72)
    _log(pid, 'INFO', 'Cleanup', f'work dir removed; the episode auto-deletes in {ttl:.0f} h')

    BJ.finish(
        pid,
        True,
        result=f'{run.ch["label"]} {run.cat["label"]} — {len(on_air)} bets for '
        f'{day}, {result["duration"] / 60:.1f} min → {result["video"]}',
    )
    BJ.marker_update(run.mid, status='done')
