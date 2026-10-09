# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The entry point, the episode orchestrator and the retention sweep.

The seven stages `_run` used to inline now live in `pipeline_card.py` (the
fixtures, the selection, the research, the artwork) and `pipeline_render.py` (the
charts, the spec, the render, the delivery); this file keeps the thread entry
point, the orchestrator, the four `ZYG_BRIEF_*` switches (the settings registry
names this file for them) and the description text that goes out with the video.
"""

from __future__ import annotations

import os

from zyg_workflows.pipeline_sports import pipeline_card as CARD
from zyg_workflows.pipeline_sports import pipeline_render as VIDEO
from zyg_workflows.pipeline_sports.constants import (
    BJ,
    BV,
    CHANNELS,
    SI,
    _log,
    _stage,
    threading,
    traceback,
)
from zyg_workflows.pipeline_sports.scripts import (
    _welcome_script,
    _write_scripts,
)

# ── entry point ─────────────────────────────────────────────────────────────


def start_episode(department: str, category: str, force=False, pipeline_options=None, **_kw):
    if department not in CHANNELS:
        return {'error': f'unknown department {department!r}'}
    if category not in SI.CATEGORIES:
        return {'error': f'unknown category {category!r} — one of {", ".join(SI.CATEGORIES)}'}
    if not force and BJ.pipeline_busy():
        return {'error': 'pipeline_busy'}
    ok, why = BJ.disk_ok(department)
    if not ok:
        return {'error': f'disk gate: {why}'}
    ok, why = SI.credits_ok()
    if not ok:
        return {'error': f'odds api: {why}'}
    ch = CHANNELS[department]
    pid = BJ.mk_job(
        department,
        'betting',
        f'{ch["label"]} {SI.CATEGORIES[category]["label"]} episode',
        params={'category': category, 'options': pipeline_options or {}},
        sub=category,
    )
    threading.Thread(
        target=_run, args=(pid, department, category, pipeline_options or {}), name=f'{department}-{pid}', daemon=True
    ).start()
    return {'job_id': pid, 'status': 'running', 'department': department, 'category': category}


# ── the pipeline ────────────────────────────────────────────────────────────


def _flag_on(name: str) -> bool:
    """True unless the environment variable `name` is set to an off word."""
    return os.environ.get(name, '1').strip().lower() not in ('0', 'false', 'no', 'off')


def _episode_flags() -> CARD.EpisodeFlags:
    """Read the four ZYG_BRIEF_* switches (all default-on) into one record."""
    return CARD.EpisodeFlags(
        injuries=_flag_on('ZYG_BRIEF_INJURIES'),
        player_art=_flag_on('ZYG_BRIEF_PLAYER_ART'),
        parlays=_flag_on('ZYG_BRIEF_PARLAYS'),
        jingles=_flag_on('ZYG_BRIEF_JINGLES'),
    )


def _run(pid, department, category, opts=None):
    opts = opts or {}
    run = CARD.build_run(pid, department, category, _episode_flags())

    try:
        # ── 1. fixtures + odds ──────────────────────────────────────────────
        res, day, day_h = CARD.collect_fixtures(run, opts)

        # ── 2. price, select, star and research the card ────────────────────
        on_air, on_ice = CARD.select_bets(run, res, day)
        CARD.attach_research_data(run, on_air)

        # ── 3. artwork ──────────────────────────────────────────────────────
        art, players_art = CARD.pull_artwork(run, on_air)

        # ── 4. script ───────────────────────────────────────────────────────
        _stage(pid, 'Write Script', 30)
        welcome = _welcome_script(on_air, run.th_brand['name'], day_h)
        scripts = []
        for i, b in enumerate(on_air, 1):
            BJ.check_stop(pid)
            scripts.append(_write_scripts(pid, b, i, len(on_air)))
        BJ.ollama_release()

        # ── 5. charts ───────────────────────────────────────────────────────
        charts = VIDEO.build_charts(run, on_air, art, players_art, day_h)

        # ── 6. render ───────────────────────────────────────────────────────
        spec = VIDEO.build_render_spec(
            run,
            charts=charts,
            welcome=welcome,
            scripts=scripts,
            on_air=on_air,
            day=day,
            day_h=day_h,
            players_art=players_art,
            description_intro=_description_intro,
        )
        result = VIDEO.render_episode(run, spec)

        # ── 7. deliver, park the ice box and clean up ───────────────────────
        VIDEO.deliver_episode(run, result, res, on_air, on_ice, charts.parlays, day)

    except BJ.Stopped:
        BJ.finish(pid, False, error='stopped by user')
        BJ.marker_update(run.mid, status='done', label=f'{run.cat["emoji"]} {run.ch["label"]} {pid[:8]} — stopped')
    except Exception as e:
        _log(pid, 'ERROR', 'Deliver', f'{e}')
        BJ.finish(pid, False, error=f'{e}\n{traceback.format_exc()[:800]}')
        BJ.marker_update(run.mid, status='done', label=f'{run.cat["emoji"]} {run.ch["label"]} {pid[:8]} — failed')


def _description_intro(ch, cat, bets, day_h, parlays=None) -> str:
    lines = [
        f'{ch["label"]} {cat["label"]} — matches on {day_h}',
        '',
        f"{len(bets)} selections, each with the price, our model's fair price and the reasoning.",
        '',
    ]
    for i, b in enumerate(bets, 1):
        tag = 'VALUE' if b.get('bet_type') == 'value' else 'CONFIDENCE'
        lines.append(
            f'{i}. {b["home"]} vs {b["away"]} — {b["selection"]} @ '
            f'{b["price"]} ({b.get("book")}) · {tag} · '
            f'edge {b["edge_pct"]:+.1f}%'
        )
    if parlays:
        lines += ['', "PARLAY SHEET (2-4 legs, multiplied best prices — your book's parlay price will differ)"]
        for p in parlays:
            legs = ' + '.join(f'{l["selection"]} @ {l["price"]}' for l in p['legs'])
            lines.append(
                f'{p["label"]}: {legs} → pays {p["price"]} · '
                f'{p["prob_pct"]:.1f}% chance · edge {p["edge_pct"]:+.1f}%'
                f' · stake ≤{p["stake_pct"]}%'
            )
    lines += ['', 'Free tips in our telegram.', '', '18+ · gamble responsibly.']
    return '\n'.join(lines)


# ── retention ───────────────────────────────────────────────────────────────


def retention_sweep(log=print) -> dict:
    ttl = float(SI.settings().get('delivery_ttl_hours') or 72)
    return {dept: BV.retention_sweep(BJ.out_root(dept), ttl, log=log) for dept in CHANNELS}
