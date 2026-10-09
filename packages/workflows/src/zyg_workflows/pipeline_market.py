# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_market.py — the Stockmarket and Cryptodaily departments (2026-08-06).

One pipeline, two departments: `stocks` screens the S&P 500 ∪ Nasdaq-100 and
`crypto` screens the CoinGecko top-N. Everything downstream of the screen is
identical, which is exactly what the operator asked for ("Cryptodaily workflow,
build this how you build stockmarket workflow").

EPISODE (operator spec)
  opening board listing every pick, held 10 s under the welcome line
  → one chapter per pick, its price chart on screen for the whole explanation,
    stating whether it is expected to rise or fall, WHY, and whether it is a
    short-term trade or a long-term investment
  → the fixed outro line.

THE NUMBER RULE
`market_ingest.score_symbol` decides the direction, the horizon and produces a
`drivers` list in which every claim already carries its measured figure. The LLM
is handed those strings and asked to turn them into spoken English. Whatever it
writes is then checked by `briefing_jobs.llm_invented_numbers`; if a figure comes
back that was in none of the source facts, the written copy is discarded and the
measured facts are spoken verbatim. A hallucinated price target on a finance
channel is not a style problem.

THE ICE BOX
`research_depth` names are researched, `picks_per_episode` go on air and the
remainder are parked in `market_icebox.json` with a ready-to-paste social post —
the operator's "always keep 2 investments tips on ice".
"""

from __future__ import annotations

import os
import shutil
import threading
import traceback
from datetime import datetime

from zyg_workflows import briefing_jobs as BJ
from zyg_workflows import briefing_video as BV
from zyg_workflows import market_ingest as MI

_CREWS = os.path.dirname(os.path.abspath(__file__))

CHANNELS = {
    'stocks': {
        'label': 'Stockmarket',
        'theme': 'stocks',
        'kind': 'stock',
        'noun': 'stock',
        'nouns': 'stocks',
        'voice_key': 'stocks_voice',
    },
    'crypto': {
        'label': 'Cryptodaily',
        'theme': 'crypto',
        'kind': 'crypto',
        'noun': 'coin',
        'nouns': 'coins',
        'voice_key': 'crypto_voice',
    },
}

OUTRO_LINE = (
    'Feel free to join our telegram, there we share free investing tips. '
    'All information is fully free. Please like and subscribe, '
    'see you next time.'
)

DISCLAIMER = (
    'DISCLAIMER: This channel is educational content, not financial advice. '
    'Nothing here is a recommendation to buy or sell any security or digital '
    'asset. Every figure shown is computed from public end-of-day market data '
    'on the date stated on screen and will be out of date by the time you '
    'watch. Markets can and do go to zero. Do your own research.'
)


def _log(pid, level, stage, msg):
    BJ.log(pid, level, stage, msg, tag='MARKET')


def _stage(pid, stage, pct=None):
    BJ.update_stage(pid, stage, pct, tag='MARKET')


# ── script writing ──────────────────────────────────────────────────────────


def _horizon_phrase(pick) -> str:
    if pick['horizon'] == 'short':
        return 'a short-term trade — days to a few weeks, and it needs watching on that clock'
    return 'a long-term investment — this is a months-to-quarters thesis, not something to trade on Friday'


def _verdict_phrase(pick) -> str:
    return 'expected to rise' if pick['direction'] == 'up' else 'expected to fall'


def _facts_for(pick: dict) -> list:
    """The only claims the narration is allowed to make about this pick."""
    ind = pick.get('indicators') or {}
    facts = []
    if ind.get('last'):
        facts.append(f'it last traded at {ind["last"]:,.2f}')
    facts += list(pick.get('drivers_for') or [])
    facts += list(pick.get('drivers_context') or [])
    facts += [f'the risk to that view: {d}' for d in (pick.get('drivers_against') or [])]
    for key, label in (
        ('sma20', 'its 20-day average sits at'),
        ('sma50', 'its 50-day average sits at'),
        ('sma200', 'its 200-day average sits at'),
    ):
        if ind.get(key):
            facts.append(f'{label} {ind[key]:,.2f}')
    return facts


def _template_item_script(pick: dict, channel: dict, index: int, total: int) -> str:
    """The narration used when the LLM is unavailable or is caught inventing.

    Deliberately plain: it reads the measured facts in order. Less lively than the
    written version, always true.
    """
    name = pick.get('name') or pick.get('symbol')
    parts = [f'Number {index} of {total}. {name}, ticker {pick.get("symbol")}.']
    parts.append(
        f'Our read is that it is {_verdict_phrase(pick)}, and we are treating this one as {_horizon_phrase(pick)}.'
    )
    facts = _facts_for(pick)
    if facts:
        parts.append(
            'Here is what the chart is actually telling us. ' + '. '.join(f[0].upper() + f[1:] for f in facts[:5]) + '.'
        )
    against = pick.get('drivers_against') or []
    if against:
        parts.append(f'The case against: {against[0]}.')
    else:
        parts.append(
            'The honest caveat is that nothing in this read is a guarantee — it is a probability, not a promise.'
        )
    parts.append(f'Conviction on this one is {round(float(pick.get("conviction") or 0) * 100)} percent.')
    return ' '.join(parts)


def _write_item_script(pid, pick: dict, channel: dict, index: int, total: int) -> str:
    facts = _facts_for(pick)
    baseline = _template_item_script(pick, channel, index, total)
    prompt = (
        'You are the presenter of a daily markets channel. Rewrite the FACTS below '
        'as spoken narration for one segment of the show. Rules, all mandatory:\n'
        '1. Do NOT introduce any number, price, percentage, date or statistic that '
        'is not already in the FACTS. Not one.\n'
        '2. Do not predict a price target and do not tell anyone to buy or sell.\n'
        '3. State clearly that it is '
        + _verdict_phrase(pick)
        + ' and that this is '
        + ('a SHORT-TERM TRADE' if pick['horizon'] == 'short' else 'a LONG-TERM INVESTMENT')
        + ', and say why that horizon.\n'
        '4. Include the risk / counter-argument honestly.\n'
        '5. Conversational, 110 to 150 words, no headings, no bullet points, no emoji.\n\n'
        f'ASSET: {pick.get("name")} ({pick.get("symbol")})'
        f'{", " + pick["sector"] if pick.get("sector") else ""}\n'
        f'SEGMENT: number {index} of {total}\n'
        'FACTS:\n- ' + '\n- '.join(facts) + '\n\n'
        'Answer STRICT JSON: {"narration": "<the spoken text>"}'
    )
    resp = BJ.ollama_json(prompt, num_predict=520, temperature=0.4)
    written = ((resp or {}).get('narration') or '').strip()
    if not written or len(written.split()) < 45:
        _log(
            pid,
            'WARNING',
            'Write Script',
            f'{pick.get("symbol")}: LLM gave nothing usable — speaking the measured facts',
        )
        return baseline
    bad = BJ.llm_invented_numbers(written, facts + [baseline])
    if bad:
        _log(
            pid,
            'WARNING',
            'Write Script',
            f'{pick.get("symbol")}: LLM invented {sorted(bad)} — discarded, speaking the measured facts instead',
        )
        return baseline
    return written


def _welcome_script(picks: list, channel: dict, day: str) -> str:
    names = [f'{p.get("name") or p.get("symbol")}' for p in picks]
    if len(names) > 1:
        listed = ', '.join(names[:-1]) + ', and ' + names[-1]
    else:
        listed = names[0] if names else 'nothing today'
    ups = sum(1 for p in picks if p['direction'] == 'up')
    downs = len(picks) - ups
    shorts = sum(1 for p in picks if p['horizon'] == 'short')
    return (
        f'Welcome to {channel["label"]}. Great to have you here. '
        f'On the board behind me are all {len(picks)} {channel["nouns"]} that came '
        f"out of today's research, {day}. They are: {listed}. "
        f'{ups} of them we expect to rise and {downs} we expect to fall. '
        f'{shorts} are short-term trades and {len(picks) - shorts} are long-term '
        f'investments — and I will tell you exactly which is which, and why, '
        f"as we go through them one by one. Let's get into it."
    )


# ── board + chart building ──────────────────────────────────────────────────


def _board_rows(picks: list) -> list:
    rows = []
    for p in picks:
        horizon = 'short-term trade' if p['horizon'] == 'short' else 'long-term investment'
        rows.append(
            {
                'left': p.get('symbol'),
                'mid': f'{p.get("name") or ""} · {horizon}',
                'right': ('▲ RISE' if p['direction'] == 'up' else '▼ FALL'),
                'tone': 'up' if p['direction'] == 'up' else 'down',
            }
        )
    return rows


def _chapter_title(p: dict, i: int) -> str:
    horizon = 'short trade' if p['horizon'] == 'short' else 'long hold'
    arrow = 'rise' if p['direction'] == 'up' else 'fall'
    return f'{i}. {p.get("symbol")} — {(p.get("name") or "")[:26]} ({horizon}, {arrow})'


# ── entry points ────────────────────────────────────────────────────────────


def start_stocks(force=False, pipeline_options=None, **_kw):
    return _start('stocks', force=force, pipeline_options=pipeline_options)


def start_crypto(force=False, pipeline_options=None, **_kw):
    return _start('crypto', force=force, pipeline_options=pipeline_options)


def _start(department, force=False, pipeline_options=None):
    if department not in CHANNELS:
        return {'error': f'unknown department {department!r}'}
    if not force and BJ.pipeline_busy():
        return {'error': 'pipeline_busy'}
    ok, why = BJ.disk_ok(department)
    if not ok:
        return {'error': f'disk gate: {why}'}
    ch = CHANNELS[department]
    pid = BJ.mk_job(department, 'briefing', f'{ch["label"]} daily episode', params={'options': pipeline_options or {}})
    threading.Thread(target=_run, args=(pid, department), name=f'{department}-{pid}', daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': department}


# ── the pipeline ────────────────────────────────────────────────────────────


def _run(pid, department):
    ch = CHANNELS[department]
    s = MI.settings()
    out_dir = os.path.join(BJ.out_root(department), pid)
    work_dir = os.path.join(out_dir, 'work')
    charts_dir = os.path.join(out_dir, 'charts')
    for d in (out_dir, work_dir, charts_dir):
        os.makedirs(d, exist_ok=True)
    mid = BJ.marker(f'📊 {ch["label"]} {pid[:8]}', pid)
    day_h = datetime.now().strftime('%-d %B %Y')

    try:
        # ── 1. screen ───────────────────────────────────────────────────────
        _stage(pid, 'Collect Market Data', 4)
        depth = int(s.get('research_depth') or 11)
        picks_n = int(s.get('picks_per_episode') or 7)
        hold_n = int(s.get('icebox_hold') or 2)

        def _slog(level, msg):
            _log(pid, level, 'Collect Market Data', msg)

        researched = MI.screen(ch['kind'], want=max(depth, picks_n + hold_n), log=_slog, stop=lambda: BJ.stopped(pid))
        BJ.check_stop(pid)
        if len(researched) < 3:
            raise RuntimeError(
                f'only {len(researched)} {ch["nouns"]} could be scored '
                f'— every price provider failed or the universe is empty'
            )

        _stage(pid, 'Score & Rank', 14)
        on_air = researched[:picks_n]
        on_ice = researched[picks_n : picks_n + hold_n]
        _log(
            pid,
            'INFO',
            'Score & Rank',
            f'{len(researched)} researched → {len(on_air)} on air, {len(on_ice)} to the ice box',
        )
        for p in on_air:
            _log(
                pid,
                'INFO',
                'Score & Rank',
                f'{p["symbol"]}: {p["direction"]} / {p["horizon"]} '
                f'(conviction {p["conviction"]:.2f}, via {p.get("provider")})',
            )

        # ── 2. script ───────────────────────────────────────────────────────
        _stage(pid, 'Write Script', 20)
        welcome = _welcome_script(on_air, ch, day_h)
        scripts = []
        for i, p in enumerate(on_air, 1):
            BJ.check_stop(pid)
            scripts.append(_write_item_script(pid, p, ch, i, len(on_air)))
        BJ.ollama_release()

        # ── 3. charts ───────────────────────────────────────────────────────
        _stage(pid, 'Build Charts', 28)
        board_png = os.path.join(charts_dir, 'board.png')
        BV.render_board(
            ch['theme'],
            "Today's research",
            f'{day_h} · {len(on_air)} of {len(researched)} researched '
            f'· screened from the {on_air[0].get("index") or "market"}',
            _board_rows(on_air),
            board_png,
            'Educational content · not financial advice',
        )
        item_charts = []
        for i, p in enumerate(on_air, 1):
            BJ.check_stop(pid)
            cp = os.path.join(charts_dir, f'{i:02d}_{p["symbol"].replace(".", "_")}.png')
            BV.render_price_chart(ch['theme'], p, cp)
            item_charts.append(cp)
        outro_png = os.path.join(charts_dir, 'outro.png')
        BV.render_card(
            ch['theme'],
            'Thanks for watching',
            [
                'Free investing tips in our telegram',
                'All information is fully free',
                'Like · Subscribe · See you next time',
            ],
            outro_png,
            'Educational content · not financial advice',
        )

        # ── 4. render ───────────────────────────────────────────────────────
        spec = {
            'channel': ch['label'],
            'theme': ch['theme'],
            'voice_seed': s.get(ch['voice_key']) or '',
            'voice_id': f'briefing-{department}',
            'slug': f'{department}_{datetime.now().strftime("%Y%m%d")}_{pid[:6]}',
            'welcome_text': welcome,
            'welcome_chapter': "Welcome & today's list",
            'board_png': board_png,
            'board_seconds': float(s.get('opening_chart_seconds') or 10),
            'items': [
                {
                    'chapter': _chapter_title(p, i + 1),
                    'panels': [{'image': item_charts[i], 'text': scripts[i], 'ken_burns': False}],
                }
                for i, p in enumerate(on_air)
            ],
            'outro_png': outro_png,
            'outro_text': OUTRO_LINE,
            'outro_chapter': 'Telegram, and see you next time',
            'description_intro': _description_intro(ch, on_air, day_h),
            'disclaimer': DISCLAIMER,
            'attribution_note': (
                'Price data: '
                + ', '.join(
                    sorted({p.get('provider', '').replace(' (cache)', '') for p in on_air if p.get('provider')})
                )
                + '. Charts rendered locally from end-of-day OHLCV.'
            ),
        }

        def _bv_log(level, msg):
            # Attribute the line to whatever stage is actually current — the
            # engine logs narration, encoding and QC through one callback, and
            # stamping them all 'Render Episode' made the job log misleading.
            _log(pid, level, (BJ.jobs().get(pid) or {}).get('current_stage') or 'Render Episode', msg)

        def _bv_progress(stage, pct):
            _stage(
                pid, {'Narrate': 'Narrate', 'Render': 'Render Episode', 'QC Gates': 'QC Gates'}.get(stage, stage), pct
            )

        result = BV.render_episode(
            spec, work_dir, out_dir, log=_bv_log, check_stop=lambda: BJ.check_stop(pid), progress=_bv_progress
        )
        if result.get('error'):
            raise RuntimeError(
                f'render failed: {result["error"]}'
                + (f' (quarantined at {result["quarantined"]})' if result.get('quarantined') else '')
            )

        # ── 5. deliver ──────────────────────────────────────────────────────
        _stage(pid, 'Deliver', 93)
        episode = {
            'job_id': pid,
            'department': department,
            'channel': ch['label'],
            'built_at': BJ.now_iso(),
            'day': day_h,
            'duration_s': result['duration'],
            'video': result['video'],
            'description': result['description'],
            'chapters': result['chapters'],
            'qc': result['qc'],
            'picks': [{k: v for k, v in p.items() if k not in ('bars_tail', 'overlays')} for p in on_air],
            'icebox': [p['symbol'] for p in on_ice],
            'universe_size': len(researched),
            'ttl_hours': float(s.get('delivery_ttl_hours') or 72),
        }
        BJ._save_json(os.path.join(out_dir, 'episode.json'), episode)
        MI.history_add(on_air, ch['label'], pid)

        _stage(pid, 'Ice Box', 96)
        MI.icebox_add(on_ice, ch['label'])
        _log(
            pid,
            'INFO',
            'Ice Box',
            f'{len(on_ice)} pick(s) parked for telegram/X: {", ".join(p["symbol"] for p in on_ice) or "(none)"}',
        )

        _stage(pid, 'Cleanup', 98)
        shutil.rmtree(work_dir, ignore_errors=True)
        ttl = float(s.get('delivery_ttl_hours') or 72)
        _log(pid, 'INFO', 'Cleanup', f'work dir removed; the episode auto-deletes in {ttl:.0f} h')

        BJ.finish(
            pid,
            True,
            result=f'{ch["label"]} episode — {len(on_air)} picks, '
            f'{result["duration"] / 60:.1f} min → {result["video"]}',
        )
        BJ.marker_update(mid, status='done')

    except BJ.Stopped:
        BJ.finish(pid, False, error='stopped by user')
        BJ.marker_update(mid, status='done', label=f'📊 {ch["label"]} {pid[:8]} — stopped')
    except Exception as e:
        _log(pid, 'ERROR', 'Deliver', f'{e}')
        BJ.finish(pid, False, error=f'{e}\n{traceback.format_exc()[:800]}')
        BJ.marker_update(mid, status='done', label=f'📊 {ch["label"]} {pid[:8]} — failed')


def _description_intro(ch, picks, day_h) -> str:
    lines = [
        f'{ch["label"]} — {day_h}',
        '',
        f"{len(picks)} {ch['nouns']} from today's research, each with the read, "
        f'the reasoning and whether we treat it as a short-term trade or a '
        f'long-term investment.',
        '',
    ]
    for i, p in enumerate(picks, 1):
        horizon = 'SHORT-TERM TRADE' if p['horizon'] == 'short' else 'LONG-TERM INVESTMENT'
        arrow = 'expected to RISE' if p['direction'] == 'up' else 'expected to FALL'
        lines.append(f'{i}. {p["symbol"]} ({p.get("name")}) — {arrow} · {horizon}')
    lines += ['', 'Free tips in our telegram. All information is fully free.']
    return '\n'.join(lines)


# ── retention ───────────────────────────────────────────────────────────────


def retention_sweep(log=print) -> dict:
    out = {}
    for dept in ('stocks', 'crypto'):
        ttl = float(MI.settings().get('delivery_ttl_hours') or 72)
        out[dept] = BV.retention_sweep(BJ.out_root(dept), ttl, log=log)
    return out
