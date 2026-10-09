# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Misc pipeline tools (lines 1365-1688 of the original pipeline_tools.py)."""

from .base import (
    BaseTool,
    _LOCKS,
    _RUNTIME_DIR,
    _ams_now,
    _now_iso,
    _runtime_path,
    hashlib,
    json,
    os,
    time,
)

# ---------------------------------------------------------------------------
# Misc pipeline tools
# ---------------------------------------------------------------------------


class TempFileCleanerTool(BaseTool):
    name: str = 'Temp File Cleaner'
    description: str = 'Clean temporary pipeline files older than a given age from a directory.'

    def _run(self, directory: str = _RUNTIME_DIR, max_age_hours: float = 24.0, pattern: str = 'clipfarm_') -> str:
        import glob

        now = time.time()
        max_age_sec = max_age_hours * 3600
        removed = []
        errors = []
        for f in glob.glob(os.path.join(directory, f'*{pattern}*')):
            try:
                age = now - os.path.getmtime(f)
                if age > max_age_sec:
                    os.remove(f)
                    removed.append(f)
            except Exception as e:
                errors.append(str(e))
        return json.dumps(
            {'removed_count': len(removed), 'removed_files': removed, 'errors': errors, 'directory': directory}
        )


class QuotaTrackerTool(BaseTool):
    name: str = 'Quota Tracker (per-API rolling window counters)'
    description: str = (
        "Track API quota usage with rolling window counters. Actions: 'increment', 'check', 'reset', 'list'."
    )

    def _run(
        self,
        action: str,
        api_name: str = '',
        window: str = 'daily',
        store_file: str = _runtime_path('clipfarm_quota_tracker.json'),
    ) -> str:
        QUOTAS = {
            'youtube_data': {'daily': 10000},
            'tiktok': {'daily': 1000},
            'instagram': {'daily': 500},
            'default': {'daily': 1000},
        }
        with _LOCKS['quota']:
            data = {}
            if os.path.exists(store_file):
                with open(store_file) as f:
                    data = json.load(f)
            date_key = (
                _ams_now().strftime('%Y-%m-%d')
                if window == 'daily'
                else _ams_now().strftime('%Y-%m-%dT%H')
                if window == 'hourly'
                else 'all'
            )
            key = f'{api_name}:{date_key}'
            current = data.get(key, 0)
            limit = QUOTAS.get(api_name, QUOTAS['default']).get(window, 1000)
            if action == 'increment':
                data[key] = current + 1
                with open(store_file, 'w') as f:
                    json.dump(data, f, indent=2)
                return json.dumps(
                    {
                        'api': api_name,
                        'used': current + 1,
                        'limit': limit,
                        'remaining': max(0, limit - current - 1),
                        'exhausted': current + 1 >= limit,
                    }
                )
            elif action == 'check':
                return json.dumps(
                    {
                        'api': api_name,
                        'used': current,
                        'limit': limit,
                        'remaining': max(0, limit - current),
                        'exhausted': current >= limit,
                    }
                )
            elif action == 'reset':
                data.pop(key, None)
                with open(store_file, 'w') as f:
                    json.dump(data, f, indent=2)
                return json.dumps({'status': 'reset', 'api': api_name, 'key': key})
            elif action == 'list':
                return json.dumps({'quotas': data})
        return json.dumps({'error': f'Unknown action: {action}'})


class PublishTimeSchedulerTool(BaseTool):
    name: str = 'Publish Time Scheduler'
    description: str = (
        'Schedule optimal publish times for content based on audience activity patterns. '
        'Returns recommended publish windows.'
    )

    def _run(self, platform: str = 'youtube', timezone_offset: int = 0, content_type: str = 'shorts') -> str:
        # Evidence-based optimal posting windows (UTC)
        OPTIMAL_WINDOWS = {
            'youtube': {
                'shorts': [
                    {'day': 'weekday', 'hour_utc': 14, 'hour_utc_end': 16},
                    {'day': 'weekend', 'hour_utc': 12, 'hour_utc_end': 15},
                ],
                'long': [{'day': 'weekday', 'hour_utc': 17, 'hour_utc_end': 20}],
            },
            'tiktok': [
                {'day': 'any', 'hour_utc': 13, 'hour_utc_end': 15},
                {'day': 'any', 'hour_utc': 19, 'hour_utc_end': 22},
            ],
            'instagram': [{'day': 'weekday', 'hour_utc': 11, 'hour_utc_end': 13}],
        }
        windows = OPTIMAL_WINDOWS.get(platform, OPTIMAL_WINDOWS['youtube'])
        if isinstance(windows, dict):
            windows = windows.get(content_type, windows.get('shorts', []))
        local_windows = []
        for w in windows:
            local_windows.append(
                {
                    **w,
                    'hour_local': (w['hour_utc'] + timezone_offset) % 24,
                    'hour_local_end': (w['hour_utc_end'] + timezone_offset) % 24,
                }
            )
        return json.dumps(
            {
                'platform': platform,
                'content_type': content_type,
                'timezone_offset': timezone_offset,
                'optimal_windows': local_windows,
            }
        )


class MarkdownHTMLReportBuilderTool(BaseTool):
    name: str = 'Markdown / HTML Report Builder'
    description: str = (
        'Build a formatted Markdown or HTML report from structured data. '
        'Input: title, sections (list of {heading, content}).'
    )

    def _run(self, title: str, sections_json: str, output_format: str = 'markdown', output_path: str = '') -> str:
        sections = json.loads(sections_json) if isinstance(sections_json, str) else sections_json
        if output_format == 'html':
            lines = [
                f'<html><head><title>{title}</title></head><body>',
                f'<h1>{title}</h1>',
                f'<p>Generated: {_now_iso()}</p>',
            ]
            for sec in sections:
                lines.append(f'<h2>{sec.get("heading", "")}</h2>')
                lines.append(f'<p>{sec.get("content", "")}</p>')
            lines.append('</body></html>')
            content = '\n'.join(lines)
        else:
            lines = [f'# {title}', f'\n_Generated: {_now_iso()}_\n']
            for sec in sections:
                lines.append(f'\n## {sec.get("heading", "")}\n')
                lines.append(str(sec.get('content', '')))
            content = '\n'.join(lines)
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
        return json.dumps(
            {'status': 'ok', 'format': output_format, 'output_path': output_path, 'preview': content[:500]}
        )


class TaskDecomposerTool(BaseTool):
    name: str = 'Task Decomposer'
    description: str = (
        'Decompose a high-level task description into a structured list of subtasks '
        'using keyword matching and rule-based splitting.'
    )

    def _run(self, task_description: str, max_subtasks: int = 8) -> str:
        import re

        # Split on action verbs / connectors
        connectors = r'\b(then|next|after that|followed by|and then|finally|first|second|third|lastly)\b'
        parts = re.split(connectors, task_description, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if len(p.strip()) > 10 and not re.match(connectors, p.strip(), re.IGNORECASE)]
        subtasks = []
        for i, part in enumerate(parts[:max_subtasks], 1):
            subtasks.append({'step': i, 'description': part, 'status': 'pending', 'priority': max_subtasks - i + 1})
        return json.dumps({'original_task': task_description, 'subtask_count': len(subtasks), 'subtasks': subtasks})


class TaskTypeClassifierTool(BaseTool):
    name: str = 'Task Type Classifier'
    description: str = (
        'Classify a task description into a pipeline category '
        '(download, process, analyze, publish, monitor, report, etc.).'
    )

    def _run(self, task_description: str) -> str:
        CATEGORIES = {
            'download': ['download', 'fetch', 'scrape', 'pull', 'extract url'],
            'process': ['encode', 'transcode', 'render', 'convert', 'trim', 'cut', 'normalize'],
            'analyze': ['analyze', 'detect', 'score', 'measure', 'evaluate', 'classify'],
            'publish': ['upload', 'post', 'publish', 'schedule', 'distribute'],
            'monitor': ['monitor', 'watch', 'track', 'alert', 'notify'],
            'report': ['report', 'log', 'summarize', 'generate report'],
            'manage': ['register', 'store', 'save', 'delete', 'clean'],
        }
        text = task_description.lower()
        scores = {}
        for cat, keywords in CATEGORIES.items():
            scores[cat] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=lambda x: scores[x]) if any(scores.values()) else 'general'
        return json.dumps(
            {'task': task_description, 'category': best, 'all_scores': scores, 'confidence': scores.get(best, 0)}
        )


class CPUResourceAllocatorTool(BaseTool):
    name: str = 'CPU Resource Allocator'
    description: str = 'Check CPU availability and allocate CPU resources for a pipeline task.'

    def _run(self, requested_cores: int = 1, priority: str = 'normal') -> str:
        import psutil

        cpu_count = psutil.cpu_count(logical=True)
        cpu_pct = psutil.cpu_percent(interval=0.5)
        available_pct = 100.0 - cpu_pct
        can_allocate = requested_cores <= cpu_count and available_pct > 20
        return json.dumps(
            {
                'cpu_count': cpu_count,
                'cpu_usage_percent': cpu_pct,
                'available_percent': round(available_pct, 1),
                'requested_cores': requested_cores,
                'can_allocate': can_allocate,
                'recommendation': 'proceed' if can_allocate else 'wait',
            }
        )


class GPUResourceAllocatorTool(BaseTool):
    name: str = 'GPU Resource Allocator'
    description: str = 'Check GPU VRAM availability and allocate GPU resources for a task.'

    def _run(self, required_vram_gb: float = 4.0) -> str:
        try:
            import pynvml

            pynvml.nvmlInit()
            gpus = []
            for i in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                free_gb = mem.free / 1e9
                gpus.append(
                    {
                        'index': i,
                        'free_vram_gb': round(free_gb, 2),
                        'total_vram_gb': round(mem.total / 1e9, 2),
                        'can_allocate': free_gb >= required_vram_gb,
                    }
                )
            pynvml.nvmlShutdown()
            best = next((g for g in gpus if g['can_allocate']), None)
            return json.dumps(
                {
                    'required_vram_gb': required_vram_gb,
                    'gpus': gpus,
                    'allocated_gpu': best['index'] if best else None,
                    'status': 'allocated' if best else 'insufficient_vram',
                }
            )
        except Exception as e:
            return json.dumps({'error': str(e), 'required_vram_gb': required_vram_gb})


class TimeslotAllocatorTool(BaseTool):
    name: str = 'Timeslot Allocator'
    description: str = (
        'Allocate or query execution timeslots for pipeline agents. '
        "Actions: 'allocate' (reserve a slot), 'list' (show all slots), 'release' (free a slot)."
    )

    def _run(
        self,
        action: str,
        agent_name: str = '',
        start_iso: str = '',
        duration_minutes: int = 30,
        store_file: str = _runtime_path('clipfarm_timeslots.json'),
    ) -> str:
        with _LOCKS['timeslots']:
            slots = []
            if os.path.exists(store_file):
                with open(store_file) as f:
                    slots = json.load(f)
            if action == 'allocate':
                slot = {
                    'id': hashlib.md5(f'{agent_name}{time.time()}'.encode(), usedforsecurity=False).hexdigest()[:10],
                    'agent': agent_name,
                    'start': start_iso or _now_iso(),
                    'duration_minutes': duration_minutes,
                    'status': 'allocated',
                    'allocated_at': _now_iso(),
                }
                slots.append(slot)
                with open(store_file, 'w') as f:
                    json.dump(slots, f)
                return json.dumps({'status': 'allocated', 'slot': slot})
            elif action == 'release':
                slots = [s for s in slots if s.get('agent') != agent_name]
                with open(store_file, 'w') as f:
                    json.dump(slots, f)
                return json.dumps({'status': 'released', 'agent': agent_name})
            elif action == 'list':
                return json.dumps({'count': len(slots), 'slots': slots})
            return json.dumps({'error': f'Unknown action: {action}'})
