# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""NEW TOOLS - internal logic, no external API required (lines 1689-2380 of the original pipeline_tools.py)."""

# ruff: noqa: F401
# `datetime` / `timezone` are re-imported at module level even though every use in
# this section is behind a function-local `import`: the single file bound them at
# module level, and CPython's is_import_originated() consults the MODULE symbol table
# when it chooses the LOAD_METHOD vs PUSH_NULL+LOAD_ATTR call form. Keeping them here
# keeps the compiled bytecode of the moved bodies identical to the original's.
from .base import BaseTool, _ams_iso, _ams_now, _runtime_path, json, os

# ---------------------------------------------------------------------------
# NEW TOOLS — internal logic, no external API required
# ---------------------------------------------------------------------------


class ViewVelocityTrackerTool(BaseTool):
    name: str = 'View Velocity Tracker'
    description: str = "Track view velocity (views/hour acceleration) for a video. Actions: 'calculate' (provide video_id, views, upload_iso), 'compare' (compare against stored baseline)."

    def _run(self, action: str = 'calculate', video_id: str = '', views: int = 0, upload_iso: str = '') -> str:
        import datetime

        try:
            if action == 'calculate' and upload_iso:
                uploaded = datetime.datetime.fromisoformat(upload_iso.replace('Z', '+00:00'))
                now = datetime.datetime.now(datetime.timezone.utc)
                hours = max((now - uploaded).total_seconds() / 3600, 0.1)
                vph = round(int(views) / hours, 2)
                acceleration = 'high' if vph > 5000 else 'medium' if vph > 500 else 'low'
                return json.dumps(
                    {'video_id': video_id, 'vph': vph, 'hours_since_upload': round(hours, 1), 'velocity': acceleration}
                )
            return json.dumps({'error': "Provide action='calculate' with views and upload_iso"})
        except Exception as e:
            return json.dumps({'error': str(e)})


class KeywordTriggerMatcherTool(BaseTool):
    name: str = 'Keyword Trigger Matcher'
    description: str = 'Match trigger keywords against a transcript to find high-engagement moments. Provide transcript text and keywords_csv.'

    def _run(self, transcript: str = '', keywords_csv: str = '', context_chars: int = 120) -> str:
        try:
            keywords = [k.strip().lower() for k in keywords_csv.split(',') if k.strip()]
            if not keywords:
                keywords = [
                    'amazing',
                    'incredible',
                    'shocking',
                    'breaking',
                    'exclusive',
                    'secret',
                    'never',
                    'first time',
                    'world record',
                    'unbelievable',
                ]
            matches = []
            text_lower = transcript.lower()
            for kw in keywords:
                idx = 0
                while True:
                    pos = text_lower.find(kw, idx)
                    if pos == -1:
                        break
                    start = max(0, pos - context_chars // 2)
                    end = min(len(transcript), pos + len(kw) + context_chars // 2)
                    matches.append({'keyword': kw, 'position': pos, 'context': transcript[start:end].strip()})
                    idx = pos + 1
            return json.dumps({'matches': matches, 'count': len(matches), 'keywords_searched': len(keywords)})
        except Exception as e:
            return json.dumps({'error': str(e)})


class ReportGeneratorTool(BaseTool):
    name: str = 'Report Generator'
    description: str = 'Generate a formatted markdown report from structured data. Provide title, data_json (dict or list), and optional report_type (summary/detail/table).'

    def _run(self, title: str = 'Report', data_json: str = '{}', report_type: str = 'summary') -> str:
        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
            lines = [f'# {title}', f'*Generated: {_ams_now().strftime("%Y-%m-%d %H:%M %Z")}*', '']
            if isinstance(data, list):
                for i, item in enumerate(data, 1):
                    if isinstance(item, dict):
                        lines.append(f'## Item {i}')
                        for k, v in item.items():
                            lines.append(f'- **{k}**: {v}')
                    else:
                        lines.append(f'{i}. {item}')
            elif isinstance(data, dict):
                for k, v in data.items():
                    lines.append(f'- **{k}**: {v}')
            report = '\n'.join(lines)
            out_path = _runtime_path(f'clipfarm_report_{title.lower().replace(" ", "_")}.md')
            with open(out_path, 'w') as f:
                f.write(report)
            return json.dumps({'report': report, 'saved_to': out_path})
        except Exception as e:
            return json.dumps({'error': str(e)})


class TopChannelAggregatorTool(BaseTool):
    name: str = 'Top Channel Aggregator'
    description: str = "Aggregate and rank top YouTube channels from the channel registry by subscriber count or recent activity. Actions: 'top_n' (provide limit), 'by_niche' (provide niche)."

    def _run(self, action: str = 'top_n', limit: int = 10, niche: str = '') -> str:
        try:
            reg_path = _runtime_path('clipfarm_channels.json')
            channels = []
            if os.path.exists(reg_path):
                with open(reg_path) as f:
                    channels = json.load(f)
            if niche:
                channels = [c for c in channels if niche.lower() in str(c.get('niche', '')).lower()]
            channels = sorted(channels, key=lambda c: int(c.get('subscribers', 0)), reverse=True)[: int(limit)]
            return json.dumps({'channels': channels, 'count': len(channels)})
        except Exception as e:
            return json.dumps({'error': str(e)})


class ProcessingLogParserTool(BaseTool):
    name: str = 'Processing Log Parser'
    description: str = "Parse the Clipfarm processing log to extract recent events, errors, and warnings. Actions: 'read_recent' (limit), 'errors_only', 'by_agent' (agent_name)."

    def _run(self, action: str = 'read_recent', limit: int = 50, agent_name: str = '') -> str:
        try:
            log_path = _runtime_path('clipfarm_processing_log.json')
            entries = []
            if os.path.exists(log_path):
                with open(log_path) as f:
                    entries = json.load(f)
            if action == 'errors_only':
                entries = [e for e in entries if e.get('level') in ('ERROR', 'WARNING')]
            elif action == 'by_agent' and agent_name:
                entries = [e for e in entries if agent_name.lower() in str(e.get('agent', '')).lower()]
            return json.dumps({'entries': entries[-int(limit) :], 'total': len(entries)})
        except Exception as e:
            return json.dumps({'error': str(e)})


class ErrorClassifierTool(BaseTool):
    name: str = 'Error Classifier'
    description: str = 'Classify an error message into a category with a recommended action. Provide error_message and optional context.'

    def _run(self, error_message: str = '', context: str = '') -> str:
        msg = (error_message + ' ' + context).lower()
        if any(w in msg for w in ['timeout', 'timed out', 'time out']):
            cat, action = 'TIMEOUT', 'Retry with longer timeout or reduce batch size'
        elif any(w in msg for w in ['out of memory', 'oom', 'cuda out', 'vram']):
            cat, action = 'OOM', 'Reduce model context, unload other models, retry'
        elif any(w in msg for w in ['connection', 'network', 'unreachable', 'refused', 'dns']):
            cat, action = 'NETWORK', 'Check connectivity, retry after 30s'
        elif any(w in msg for w in ['quota', 'rate limit', '429', 'too many requests']):
            cat, action = 'API_QUOTA', 'Wait for quota reset or switch to RSS fallback'
        elif any(w in msg for w in ['not found', 'no such file', 'filenotfound', 'missing']):
            cat, action = 'MISSING_FILE', 'Check file registry, re-run upstream stage'
        elif any(w in msg for w in ['permission', 'access denied', 'forbidden', '401', '403']):
            cat, action = 'AUTH', 'Check credentials registry, re-authenticate'
        else:
            cat, action = 'UNKNOWN', 'Log full traceback, escalate to Zero'
        return json.dumps({'category': cat, 'recommended_action': action, 'error_message': error_message})


class CompositeScoreEngineTool(BaseTool):
    name: str = 'Composite Score Engine'
    description: str = 'Calculate a weighted composite score (0-100) for a video from multiple metrics. Provide metrics_json with keys: views, engagement_rate, trend_score, recency_score, vph.'

    def _run(self, metrics_json: str = '{}') -> str:
        try:
            weights_path = _runtime_path('clipfarm_trend_weights.json')
            weights = {'views': 0.20, 'engagement_rate': 0.25, 'trend_score': 0.25, 'recency_score': 0.15, 'vph': 0.15}
            if os.path.exists(weights_path):
                with open(weights_path) as f:
                    weights.update(json.load(f))
            m = json.loads(metrics_json) if isinstance(metrics_json, str) else metrics_json
            score = 0.0
            max_vals = {
                'views': 10_000_000,
                'engagement_rate': 15.0,
                'trend_score': 100.0,
                'recency_score': 100.0,
                'vph': 50_000,
            }
            for key, w in weights.items():
                val = float(m.get(key, 0))
                norm = min(val / max_vals.get(key, 100), 1.0)
                score += norm * w * 100
            return json.dumps({'composite_score': round(score, 2), 'weights_used': weights, 'metrics': m})
        except Exception as e:
            return json.dumps({'error': str(e)})


class TrendRelevanceFilterTool(BaseTool):
    name: str = 'Trend Relevance Filter'
    description: str = 'Filter a list of videos by trend relevance score. Provide videos_json (list of dicts with trend_score), min_score (0-100).'

    def _run(self, videos_json: str = '[]', min_score: float = 30.0) -> str:
        try:
            videos = json.loads(videos_json) if isinstance(videos_json, str) else videos_json
            filtered = [v for v in videos if float(v.get('trend_score', 0)) >= float(min_score)]
            filtered.sort(key=lambda v: float(v.get('trend_score', 0)), reverse=True)
            return json.dumps({'filtered': filtered, 'kept': len(filtered), 'removed': len(videos) - len(filtered)})
        except Exception as e:
            return json.dumps({'error': str(e)})


class RiskLevelFilterTool(BaseTool):
    name: str = 'Risk Level Filter'
    description: str = 'Filter videos by copyright/compliance risk level. Provide videos_json (list with risk_level field: low/medium/high), max_risk (low/medium/high).'

    def _run(self, videos_json: str = '[]', max_risk: str = 'medium') -> str:
        try:
            rank = {'low': 0, 'medium': 1, 'high': 2}
            max_r = rank.get(max_risk.lower(), 1)
            videos = json.loads(videos_json) if isinstance(videos_json, str) else videos_json
            filtered = [v for v in videos if rank.get(str(v.get('risk_level', 'medium')).lower(), 1) <= max_r]
            return json.dumps(
                {
                    'filtered': filtered,
                    'kept': len(filtered),
                    'removed': len(videos) - len(filtered),
                    'max_risk': max_risk,
                }
            )
        except Exception as e:
            return json.dumps({'error': str(e)})


class VideoSetSelectorTool(BaseTool):
    name: str = 'Video Set Selector'
    description: str = "Select a final set of videos from a scored candidate list. Provide videos_json, max_count, strategy: 'top_n' | 'diverse' (spread across channels) | 'balanced' (mix scores)."

    def _run(self, videos_json: str = '[]', max_count: int = 10, strategy: str = 'top_n') -> str:
        try:
            videos = json.loads(videos_json) if isinstance(videos_json, str) else videos_json
            videos = sorted(videos, key=lambda v: float(v.get('composite_score', v.get('score', 0))), reverse=True)
            if strategy == 'diverse':
                seen_channels = set()
                selected = []
                for v in videos:
                    ch = v.get('channel_id', v.get('channel', ''))
                    if ch not in seen_channels:
                        selected.append(v)
                        seen_channels.add(ch)
                    if len(selected) >= int(max_count):
                        break
            elif strategy == 'balanced':
                top_half = videos[: len(videos) // 2]
                bottom_half = videos[len(videos) // 2 :]
                selected = []
                for i in range(int(max_count)):
                    if i % 2 == 0 and top_half:
                        selected.append(top_half.pop(0))
                    elif bottom_half:
                        selected.append(bottom_half.pop(0))
            else:
                selected = videos[: int(max_count)]
            return json.dumps({'selected': selected, 'count': len(selected), 'strategy': strategy})
        except Exception as e:
            return json.dumps({'error': str(e)})


class TopBottomClipComparatorTool(BaseTool):
    name: str = 'Top/Bottom Clip Comparator'
    description: str = "Compare top vs bottom performing clips to extract differentiating patterns. Actions: 'compare' (provide clips_json + metric), 'get_top' (limit), 'get_bottom' (limit)."

    def _run(self, action: str = 'compare', clips_json: str = '[]', metric: str = 'score', limit: int = 5) -> str:
        try:
            clips = json.loads(clips_json) if isinstance(clips_json, str) else clips_json
            if not clips:
                store_path = _runtime_path('clipfarm_clip_scores.json')
                if os.path.exists(store_path):
                    with open(store_path) as f:
                        clips = json.load(f)
            clips = sorted(clips, key=lambda c: float(c.get(metric, 0)), reverse=True)
            top = clips[: int(limit)]
            bottom = clips[-int(limit) :]
            if action == 'get_top':
                return json.dumps({'clips': top, 'count': len(top)})
            if action == 'get_bottom':
                return json.dumps({'clips': bottom, 'count': len(bottom)})
            diff = {
                'top_avg_score': round(sum(float(c.get(metric, 0)) for c in top) / max(len(top), 1), 2),
                'bottom_avg_score': round(sum(float(c.get(metric, 0)) for c in bottom) / max(len(bottom), 1), 2),
                'top_common_niches': list({c.get('niche', '') for c in top}),
                'bottom_common_niches': list({c.get('niche', '') for c in bottom}),
                'top_clips': top,
                'bottom_clips': bottom,
            }
            return json.dumps(diff)
        except Exception as e:
            return json.dumps({'error': str(e)})


class WinningPatternRegistryTool(BaseTool):
    name: str = 'Winning Pattern Registry'
    description: str = "Store and retrieve winning clip production patterns. Actions: 'store' (pattern_json), 'get' (pattern_id), 'list' (limit)."

    def _run(self, action: str = 'list', pattern_json: str = '{}', pattern_id: str = '', limit: int = 20) -> str:
        try:
            store_path = _runtime_path('clipfarm_winning_patterns.json')
            store = {}
            if os.path.exists(store_path):
                with open(store_path) as f:
                    store = json.load(f)
            if action == 'store':
                pattern = json.loads(pattern_json) if isinstance(pattern_json, str) else pattern_json
                pid = pattern.get('id') or f'pattern_{len(store) + 1}'
                pattern['id'] = pid
                pattern['stored_at'] = _ams_iso()
                store[pid] = pattern
                with open(store_path, 'w') as f:
                    json.dump(store, f, indent=2)
                return json.dumps({'stored': pid, 'total_patterns': len(store)})
            if action == 'get':
                return json.dumps(store.get(pattern_id, {'error': 'Pattern not found'}))
            patterns = list(store.values())[-int(limit) :]
            return json.dumps({'patterns': patterns, 'total': len(store)})
        except Exception as e:
            return json.dumps({'error': str(e)})


class EditingPatternEngineTool(BaseTool):
    name: str = 'Editing Pattern Engine'
    description: str = "Provide editing pattern templates (cut timing, transitions, pacing) for a given style and niche. Actions: 'get_pattern' (style, niche), 'list_patterns'."

    _PATTERNS = {
        'fast_cuts': {'avg_cut_duration_s': 2.5, 'transition': 'jump_cut', 'music_bpm': 140, 'hook_duration_s': 3},
        'cinematic': {'avg_cut_duration_s': 6.0, 'transition': 'fade', 'music_bpm': 80, 'hook_duration_s': 5},
        'tutorial': {'avg_cut_duration_s': 8.0, 'transition': 'cut', 'music_bpm': 100, 'hook_duration_s': 4},
        'viral_short': {'avg_cut_duration_s': 1.5, 'transition': 'jump_cut', 'music_bpm': 160, 'hook_duration_s': 2},
        'default': {'avg_cut_duration_s': 3.5, 'transition': 'cut', 'music_bpm': 120, 'hook_duration_s': 3},
    }

    def _run(self, action: str = 'get_pattern', style: str = 'default', niche: str = '') -> str:
        if action == 'list_patterns':
            return json.dumps({'patterns': list(self._PATTERNS.keys())})
        niche_map = {
            'luxury': 'cinematic',
            'technology': 'tutorial',
            'hypes': 'viral_short',
            'entertainment': 'fast_cuts',
        }
        resolved_style = niche_map.get(niche.lower(), style) if niche else style
        pattern = self._PATTERNS.get(resolved_style, self._PATTERNS['default'])
        return json.dumps({'style': resolved_style, 'niche': niche, 'pattern': pattern})


class VariantSetBuilderTool(BaseTool):
    name: str = 'Variant Set Builder'
    description: str = 'Build a variant specification set for a clip across multiple platform targets. Provide clip_path and platforms_csv (youtube,tiktok,instagram).'

    def _run(self, clip_path: str = '', platforms_csv: str = 'youtube,tiktok', niche: str = '') -> str:
        specs = {
            'youtube': {'aspect_ratio': '16:9', 'max_duration_s': 60, 'resolution': '1920x1080', 'format': 'mp4'},
            'tiktok': {'aspect_ratio': '9:16', 'max_duration_s': 60, 'resolution': '1080x1920', 'format': 'mp4'},
            'instagram': {'aspect_ratio': '9:16', 'max_duration_s': 90, 'resolution': '1080x1920', 'format': 'mp4'},
            'youtube_short': {'aspect_ratio': '9:16', 'max_duration_s': 60, 'resolution': '1080x1920', 'format': 'mp4'},
        }
        platforms = [p.strip().lower() for p in platforms_csv.split(',')]
        variants = []
        for p in platforms:
            spec = specs.get(p, specs['youtube'])
            variants.append(
                {
                    'platform': p,
                    'clip_path': clip_path,
                    'spec': spec,
                    'output_path': clip_path.replace('.mp4', f'_{p}.mp4') if clip_path else f'output_{p}.mp4',
                }
            )
        return json.dumps({'variants': variants, 'count': len(variants)})


class AudienceActivityAnalyzerTool(BaseTool):
    name: str = 'Audience Activity Analyzer'
    description: str = 'Analyze audience activity patterns to determine peak engagement hours. Provide platform and timezone. Returns peak hours by day of week.'

    _PEAKS = {
        'youtube': {'weekday': [7, 12, 17, 20], 'weekend': [10, 14, 19, 21]},
        'tiktok': {'weekday': [6, 10, 19, 22], 'weekend': [9, 12, 20, 23]},
        'instagram': {'weekday': [8, 12, 17, 21], 'weekend': [11, 13, 20, 22]},
    }

    def _run(self, platform: str = 'youtube', timezone: str = 'UTC') -> str:
        peaks = self._PEAKS.get(platform.lower(), self._PEAKS['youtube'])
        return json.dumps(
            {
                'platform': platform,
                'timezone': timezone,
                'peak_hours_weekday': peaks['weekday'],
                'peak_hours_weekend': peaks['weekend'],
                'note': 'Hours in local timezone. Adjust for target audience location.',
            }
        )


class OptimalTimeCalculatorTool(BaseTool):
    name: str = 'Optimal Time Calculator'
    description: str = (
        'Calculate optimal posting times for a platform and niche. Provide platform, niche, timezone, and num_slots.'
    )

    def _run(self, platform: str = 'youtube', niche: str = '', timezone: str = 'UTC', num_slots: int = 3) -> str:
        import datetime

        base_hours = {'youtube': [17, 20, 12], 'tiktok': [19, 22, 10], 'instagram': [17, 21, 12]}
        hours = base_hours.get(platform.lower(), base_hours['youtube'])[: int(num_slots)]
        now = _ams_now()
        slots = []
        for h in hours:
            t = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if t < now:
                t += datetime.timedelta(days=1)
            slots.append({'time_utc': t.isoformat(), 'hour': h, 'platform': platform})
        return json.dumps({'optimal_slots': slots, 'platform': platform, 'niche': niche, 'timezone': timezone})


class TimeslotConflictCheckerTool(BaseTool):
    name: str = 'Timeslot Conflict Checker'
    description: str = 'Check if a proposed timeslot conflicts with already-allocated slots. Provide proposed_start_iso, duration_minutes, agent_name.'

    def _run(self, proposed_start_iso: str = '', duration_minutes: int = 30, agent_name: str = '') -> str:
        import datetime

        try:
            store_path = _runtime_path('clipfarm_timeslots.json')
            slots = {}
            if os.path.exists(store_path):
                with open(store_path) as f:
                    slots = json.load(f)
            if not proposed_start_iso:
                return json.dumps({'error': 'proposed_start_iso required'})
            start = datetime.datetime.fromisoformat(proposed_start_iso.replace('Z', '+00:00'))
            end = start + datetime.timedelta(minutes=int(duration_minutes))
            conflicts = []
            for slot_id, slot in slots.items():
                if slot.get('status') != 'allocated':
                    continue
                s_start = datetime.datetime.fromisoformat(slot['start'].replace('Z', '+00:00'))
                s_end = s_start + datetime.timedelta(minutes=slot.get('duration_minutes', 30))
                if start < s_end and end > s_start:
                    conflicts.append({'slot_id': slot_id, 'agent': slot.get('agent_name'), 'start': slot['start']})
            if conflicts:
                next_free = max(
                    datetime.datetime.fromisoformat(c['start'].replace('Z', '+00:00')) for c in conflicts
                ) + datetime.timedelta(minutes=duration_minutes)
                return json.dumps({'conflict': True, 'conflicts': conflicts, 'next_available': next_free.isoformat()})
            return json.dumps({'conflict': False, 'proposed_start': proposed_start_iso, 'agent': agent_name})
        except Exception as e:
            return json.dumps({'error': str(e)})


class ExecutionCalendarTool(BaseTool):
    name: str = 'Execution Calendar'
    description: str = "View, add, or remove scheduled agent executions. Actions: 'view' (date_range_days), 'add' (agent_name, scheduled_iso, task), 'remove' (entry_id)."

    def _run(
        self,
        action: str = 'view',
        agent_name: str = '',
        scheduled_iso: str = '',
        task: str = '',
        entry_id: str = '',
        date_range_days: int = 7,
    ) -> str:
        try:
            import datetime

            cal_path = _runtime_path('clipfarm_execution_calendar.json')
            cal = {}
            if os.path.exists(cal_path):
                with open(cal_path) as f:
                    cal = json.load(f)
            if action == 'add':
                eid = f'{agent_name}_{len(cal) + 1}'
                cal[eid] = {
                    'agent': agent_name,
                    'scheduled': scheduled_iso,
                    'task': task,
                    'added_at': _ams_iso(),
                    'status': 'scheduled',
                }
                with open(cal_path, 'w') as f:
                    json.dump(cal, f, indent=2)
                return json.dumps({'added': eid, 'total': len(cal)})
            if action == 'remove':
                removed = cal.pop(entry_id, None)
                with open(cal_path, 'w') as f:
                    json.dump(cal, f, indent=2)
                return json.dumps({'removed': entry_id, 'found': removed is not None})
            cutoff = _ams_now() + datetime.timedelta(days=int(date_range_days))
            entries = [{'id': k, **v} for k, v in cal.items() if v.get('scheduled', '') <= cutoff.isoformat()]
            return json.dumps({'entries': entries, 'count': len(entries)})
        except Exception as e:
            return json.dumps({'error': str(e)})


class WindowResetTimerTool(BaseTool):
    name: str = 'Window Reset Timer'
    description: str = "Manage rate-limit reset windows. Actions: 'check' (window_name), 'reset' (window_name), 'set' (window_name, interval_seconds)."

    def _run(self, action: str = 'check', window_name: str = '', interval_seconds: int = 3600) -> str:
        try:
            import datetime

            store_path = _runtime_path('clipfarm_rate_windows.json')
            store = {}
            if os.path.exists(store_path):
                with open(store_path) as f:
                    store = json.load(f)
            now = _ams_now()
            if action == 'set' or action == 'reset':
                store[window_name] = {
                    'reset_at': (now + datetime.timedelta(seconds=int(interval_seconds))).isoformat(
                        timespec='milliseconds'
                    ),
                    'interval_seconds': int(interval_seconds),
                    'set_at': now.isoformat(timespec='milliseconds'),
                }
                with open(store_path, 'w') as f:
                    json.dump(store, f, indent=2)
                return json.dumps({'window': window_name, 'resets_at': store[window_name]['reset_at']})
            entry = store.get(window_name)
            if not entry:
                return json.dumps({'window': window_name, 'status': 'not_set'})
            reset_at = datetime.datetime.fromisoformat(entry['reset_at'])
            seconds_left = max((reset_at - now).total_seconds(), 0)
            return json.dumps(
                {
                    'window': window_name,
                    'seconds_until_reset': round(seconds_left),
                    'reset_at': entry['reset_at'],
                    'expired': seconds_left == 0,
                }
            )
        except Exception as e:
            return json.dumps({'error': str(e)})


class NicheKeywordMergerTool(BaseTool):
    name: str = 'Niche Keyword Merger'
    description: str = "Merge keyword sets for one or more niches into a unified search keyword list. Provide niches_csv and action: 'merge' | 'get' (single niche) | 'expand'."

    _NICHE_KEYWORDS = {
        'luxury': ['luxury', 'expensive', 'rich', 'billionaire', 'mansion', 'supercar', 'yacht', 'designer'],
        'technology': ['tech', 'AI', 'gadget', 'review', 'coding', 'software', 'hardware', 'innovation'],
        'entertainment': ['funny', 'viral', 'trending', 'meme', 'reaction', 'celebrity', 'drama', 'shocking'],
        'cosmetics': ['makeup', 'skincare', 'beauty', 'tutorial', 'glow', 'routine', 'foundation', 'lipstick'],
        'clothes': ['fashion', 'outfit', 'style', 'haul', 'streetwear', 'brand', 'thrift', 'lookbook'],
        'hypes': ['hype', 'drop', 'sneaker', 'limited edition', 'sold out', 'exclusive', 'collab'],
        'war': ['military', 'combat', 'strategy', 'defense', 'battlefield', 'weapon', 'army', 'navy'],
    }

    def _run(self, niches_csv: str = '', action: str = 'merge') -> str:
        niches = [n.strip().lower() for n in niches_csv.split(',') if n.strip()]
        if action == 'get' and len(niches) == 1:
            return json.dumps({'niche': niches[0], 'keywords': self._NICHE_KEYWORDS.get(niches[0], [])})
        merged = []
        for n in niches:
            merged.extend(self._NICHE_KEYWORDS.get(n, []))
        merged = list(dict.fromkeys(merged))  # deduplicate preserving order
        return json.dumps({'niches': niches, 'keywords': merged, 'count': len(merged)})


class SelectionRuleUpdaterTool(BaseTool):
    name: str = 'Selection Rule Updater'
    description: str = "Read or update video selection rules (min_views, min_vph, max_risk, etc.). Actions: 'get', 'set' (rule_name, rule_value), 'list', 'reset'."

    _DEFAULTS = {
        'min_views': 10000,
        'min_vph': 100,
        'max_risk': 'medium',
        'min_engagement_rate': 2.0,
        'max_duration_s': 600,
        'min_trend_score': 20,
    }

    def _run(self, action: str = 'list', rule_name: str = '', rule_value: str = '') -> str:
        try:
            store_path = _runtime_path('clipfarm_selection_rules.json')
            rules = dict(self._DEFAULTS)
            if os.path.exists(store_path):
                with open(store_path) as f:
                    rules.update(json.load(f))
            if action == 'reset':
                with open(store_path, 'w') as f:
                    json.dump(self._DEFAULTS, f, indent=2)
                return json.dumps({'reset': True, 'rules': self._DEFAULTS})
            if action == 'set' and rule_name:
                try:
                    rules[rule_name] = json.loads(rule_value)
                except Exception:
                    rules[rule_name] = rule_value
                with open(store_path, 'w') as f:
                    json.dump(rules, f, indent=2)
                return json.dumps({'updated': rule_name, 'value': rules[rule_name], 'all_rules': rules})
            if action == 'get' and rule_name:
                return json.dumps({'rule': rule_name, 'value': rules.get(rule_name, 'not_set')})
            return json.dumps({'rules': rules})
        except Exception as e:
            return json.dumps({'error': str(e)})


class TrendWeightUpdaterTool(BaseTool):
    name: str = 'Trend Weight Updater'
    description: str = "Read or update trend metric weights used by the Composite Score Engine. Actions: 'get', 'set' (metric_name, weight 0.0-1.0), 'list', 'reset'."

    _DEFAULTS = {'views': 0.20, 'engagement_rate': 0.25, 'trend_score': 0.25, 'recency_score': 0.15, 'vph': 0.15}

    def _run(self, action: str = 'list', metric_name: str = '', weight: float = 0.0) -> str:
        try:
            store_path = _runtime_path('clipfarm_trend_weights.json')
            weights = dict(self._DEFAULTS)
            if os.path.exists(store_path):
                with open(store_path) as f:
                    weights.update(json.load(f))
            if action == 'reset':
                with open(store_path, 'w') as f:
                    json.dump(self._DEFAULTS, f, indent=2)
                return json.dumps({'reset': True, 'weights': self._DEFAULTS})
            if action == 'set' and metric_name:
                weights[metric_name] = float(weight)
                total = sum(weights.values())
                if total > 0:
                    weights = {k: round(v / total, 4) for k, v in weights.items()}
                with open(store_path, 'w') as f:
                    json.dump(weights, f, indent=2)
                return json.dumps({'updated': metric_name, 'weight': weights[metric_name], 'all_weights': weights})
            if action == 'get' and metric_name:
                return json.dumps({'metric': metric_name, 'weight': weights.get(metric_name, 'not_set')})
            return json.dumps({'weights': weights, 'total': round(sum(weights.values()), 4)})
        except Exception as e:
            return json.dumps({'error': str(e)})


class RightsAssessmentReaderTool(BaseTool):
    name: str = 'Rights Assessment Reader'
    description: str = (
        'Read the rights assessment for a video from the local rights cache. Provide video_id or channel_id.'
    )

    def _run(self, video_id: str = '', channel_id: str = '') -> str:
        try:
            cache_path = _runtime_path('clipfarm_rights_cache.json')
            cache = {}
            if os.path.exists(cache_path):
                with open(cache_path) as f:
                    cache = json.load(f)
            key = video_id or channel_id
            if key in cache:
                return json.dumps(cache[key])
            restricted_path = _runtime_path('clipfarm_restricted_channels.json')
            restricted = []
            if os.path.exists(restricted_path):
                with open(restricted_path) as f:
                    restricted = json.load(f)
            is_restricted = channel_id in restricted or video_id in restricted
            return json.dumps(
                {
                    'video_id': video_id,
                    'channel_id': channel_id,
                    'risk_level': 'high' if is_restricted else 'unknown',
                    'license': 'unknown',
                    'note': 'No cached assessment — run Rights Check Agent first',
                }
            )
        except Exception as e:
            return json.dumps({'error': str(e)})


class QuotaWarningEmitterTool(BaseTool):
    name: str = 'Quota Warning Emitter → Overseer'
    description: str = 'Emit a quota warning to the Clipfarm Overseer when an API quota is approaching its limit. Provide api_name, used_units, total_units.'

    def _run(self, api_name: str = '', used_units: int = 0, total_units: int = 10000) -> str:
        try:
            pct = round(int(used_units) / max(int(total_units), 1) * 100, 1)
            severity = 'critical' if pct >= 90 else 'warning' if pct >= 70 else 'info'
            payload = {
                'type': 'quota_warning',
                'api': api_name,
                'used': used_units,
                'total': total_units,
                'pct_used': pct,
                'severity': severity,
                'timestamp': _ams_iso(),
            }
            log_path = _runtime_path('clipfarm_overseer_alerts.json')
            alerts = []
            if os.path.exists(log_path):
                with open(log_path) as f:
                    alerts = json.load(f)
            alerts.append(payload)
            with open(log_path, 'w') as f:
                json.dump(alerts[-200:], f, indent=2)
            return json.dumps({'emitted': True, 'severity': severity, 'pct_used': pct, 'api': api_name})
        except Exception as e:
            return json.dumps({'error': str(e)})
