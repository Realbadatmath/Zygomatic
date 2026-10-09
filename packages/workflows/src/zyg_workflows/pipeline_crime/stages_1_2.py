# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stages 1-2: case selection and the Selenium/Wikipedia document research."""

from .constants import (
    _runtime_path,
    _update_marker,
    json,
    requests,
)


def _crime_stages_1_2(_done, _log, _pipeline_marker, _save, _up_crime, job, pipeline_id, pipeline_state):
    # ── Stage 1: Case Selection ─────────────────────────────────────────
    job['current_stage'] = 'Stage 1: Case Selection'
    _update_marker(_pipeline_marker, label=f'🔄 Crime {pipeline_id[:8]} — Case Selection')
    _log('INFO', 'Stage 1', 'Selecting case from court_cases.json')

    cases_path = _runtime_path('court_cases.json')
    used_cases_path = _runtime_path('crime_used_cases.json')

    try:
        with open(cases_path) as _f:
            all_cases = json.load(_f).get('cases', [])
    except Exception as _e:
        raise RuntimeError(f'Could not load court_cases.json: {_e}') from _e

    try:
        with open(used_cases_path) as _f:
            used_ids = set(json.load(_f))
    except Exception:
        used_ids = set()

    # Pick lowest severity_rank (1 = worst / most interesting) that hasn't been used
    available = [
        c for c in sorted(all_cases, key=lambda x: x.get('severity_rank', 99)) if c.get('episode_status') == 'available'
    ]
    selected = next((c for c in available if c.get('case_id') not in used_ids), None)
    if not selected:
        _log('INFO', 'Stage 1', 'All cases used — resetting cycle')
        used_ids = set()
        selected = available[0] if available else all_cases[0]

    pipeline_state['case'] = selected
    _save()
    _log('INFO', 'Stage 1', f'Selected: {selected.get("name")} (rank {selected.get("severity_rank")})')
    _done('Stage 1: Case Selection', {'case': selected.get('name')})

    # ── Stage 2: Document Research (Selenium web agent) ────────────────
    job['current_stage'] = 'Stage 2: Document Research'
    _update_marker(_pipeline_marker, label=f'🔄 Crime {pipeline_id[:8]} — Document Research')
    court_text = ''

    try:
        # web_research_agent.py became a package in the 2026-10 modularization, so the
        # by-path exec of the single file gives way to an ordinary import of the package.
        import importlib as _importlib

        _wra_mod = _importlib.import_module('zyg_workflows.web_research_agent')
        _wra = _wra_mod.WebResearchAgent(
            case=selected,
            pipeline_id=pipeline_id,
            log_fn=_log,
            stop_event=job.get('stop_event'),
        )
        _research_result = _wra.run()
        court_text = _research_result.get('raw_text', '')
        pipeline_state['research_meta'] = {
            'sources_used': _research_result.get('sources_used', []),
            'total_chars': _research_result.get('total_chars', 0),
            'elapsed_s': _research_result.get('elapsed_s', 0),
            'timeline': _research_result.get('timeline', []),
            'key_people': _research_result.get('key_people', {}),
        }
        _log(
            'INFO',
            'Stage 2',
            (
                f'Web research complete: {_research_result.get("total_chars", 0)} chars '
                f'from {len(_research_result.get("sources_used", []))} sources '
                f'in {_research_result.get("elapsed_s", 0)}s'
            ),
        )
    except Exception as _wra_err:
        _log('WARNING', 'Stage 2', f'Web research agent failed: {_wra_err} — falling back to Wikipedia API')

    # Fallback: plain Wikipedia API if agent crashed or returned nothing
    if not court_text or len(court_text) < 300:
        try:
            _wiki_name = _up_crime.quote(selected.get('name', '').replace(' ', '_'))
            _wiki_url = (
                f'https://en.wikipedia.org/w/api.php?action=query'
                f'&prop=extracts&exintro=false&explaintext=true'
                f'&titles={_wiki_name}&format=json&redirects=1'
            )
            _wiki_resp = requests.get(_wiki_url, headers={'User-Agent': 'Zygomatic/1.0'}, timeout=15).json()
            for _wp in _wiki_resp.get('query', {}).get('pages', {}).values():
                _wiki_text = _wp.get('extract', '')
                if _wiki_text and len(_wiki_text) > 300:
                    court_text = _wiki_text[:8000]
                    _log('INFO', 'Stage 2', f'Fallback Wikipedia: {len(court_text)} chars')
                    break
        except Exception as _we:
            _log('WARNING', 'Stage 2', f'Fallback Wikipedia failed: {_we}')

    # Always prepend structured case metadata so LLM has clean context
    _local_summary = (
        f'Case: {selected.get("case_title", selected.get("name", ""))}\n'
        f'State: {selected.get("state", "Unknown")}, Year: {selected.get("year", "Unknown")}\n'
        f'Court: {selected.get("court", "Unknown")}\n'
        f'Crime Category: {selected.get("crime_category", "Unknown")}\n'
        f'Summary: {selected.get("summary", "")}\n'
        f'Why this case: {selected.get("why_narrate", "")}'
    )

    if not court_text or len(court_text) < 100:
        court_text = _local_summary
        _log('INFO', 'Stage 2', f'Using local summary only ({len(court_text)} chars)')
    elif not court_text.startswith('CASE:'):
        # Web agent already prepends metadata — only add if fallback path ran
        court_text = _local_summary + '\n\n--- ADDITIONAL RESEARCH ---\n' + court_text

    if len(court_text.split()) < 150:
        _log('WARNING', 'Stage 2', f'Low source material ({len(court_text.split())} words)')

    pipeline_state['court_text'] = court_text
    _save()
    _log('INFO', 'Stage 2', f'Combined research: {len(court_text)} chars')
    _done('Stage 2: Document Research', {'chars': len(court_text)})

    return (court_text, selected, used_cases_path, used_ids)
