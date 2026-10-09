# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Scheduling & Queue tools (lines 330-550 of the original pipeline_tools.py)."""

from .base import BaseTool, _LOCKS, _now_iso, _runtime_path, hashlib, importlib, json, os, time

# ---------------------------------------------------------------------------
# Scheduling & Queue tools
# ---------------------------------------------------------------------------


class CronTaskSchedulerTool(BaseTool):
    name: str = 'Cron / Task Scheduler'
    description: str = (
        'Schedule, list, or cancel recurring tasks using APScheduler. '
        "Actions: 'add_interval', 'add_cron', 'list', 'remove'."
    )

    def _run(
        self, action: str, job_id: str = '', cron_expr: str = '', interval_seconds: int = 60, task_name: str = ''
    ) -> str:
        if importlib.util.find_spec('apscheduler') is None:
            return json.dumps({'error': 'APScheduler not installed'})

        # We operate on scheduler metadata only (no running instance here)
        schedule_file = _runtime_path('clipfarm_schedule.json')
        with _LOCKS['schedule']:
            schedules = []
            if os.path.exists(schedule_file):
                with open(schedule_file) as f:
                    schedules = json.load(f)
            if action == 'add_interval':
                entry = {
                    'id': job_id or f'job_{int(time.time())}',
                    'type': 'interval',
                    'interval_seconds': interval_seconds,
                    'task': task_name,
                    'created_at': _now_iso(),
                    'active': True,
                }
                schedules.append(entry)
                with open(schedule_file, 'w') as f:
                    json.dump(schedules, f, indent=2)
                return json.dumps({'status': 'scheduled', **entry})
            elif action == 'add_cron':
                entry = {
                    'id': job_id or f'cron_{int(time.time())}',
                    'type': 'cron',
                    'cron': cron_expr,
                    'task': task_name,
                    'created_at': _now_iso(),
                    'active': True,
                }
                schedules.append(entry)
                with open(schedule_file, 'w') as f:
                    json.dump(schedules, f, indent=2)
                return json.dumps({'status': 'scheduled', **entry})
            elif action == 'list':
                return json.dumps({'count': len(schedules), 'schedules': schedules})
            elif action == 'remove':
                before = len(schedules)
                schedules = [s for s in schedules if s.get('id') != job_id]
                with open(schedule_file, 'w') as f:
                    json.dump(schedules, f, indent=2)
                return json.dumps({'status': 'removed', 'removed_count': before - len(schedules)})
        return json.dumps({'error': f'Unknown action: {action}'})


class JobQueueBuilderTool(BaseTool):
    name: str = 'Job Queue Builder'
    description: str = (
        "Add, list, or pop jobs from the pipeline job queue. Actions: 'enqueue', 'list', 'dequeue', 'clear'."
    )

    def _run(
        self,
        action: str,
        job_type: str = '',
        payload_json: str = '{}',
        priority: int = 5,
        queue_file: str = _runtime_path('clipfarm_job_queue.json'),
    ) -> str:
        with _LOCKS['job_queue']:
            queue = []
            if os.path.exists(queue_file):
                with open(queue_file) as f:
                    queue = json.load(f)
            if action == 'enqueue':
                job = {
                    'id': hashlib.md5(f'{job_type}{time.time()}'.encode(), usedforsecurity=False).hexdigest()[:12],
                    'type': job_type,
                    'priority': priority,
                    'payload': json.loads(payload_json) if payload_json else {},
                    'enqueued_at': _now_iso(),
                    'status': 'pending',
                }
                queue.append(job)
                queue.sort(key=lambda x: x.get('priority', 5))
                with open(queue_file, 'w') as f:
                    json.dump(queue, f, indent=2)
                return json.dumps({'status': 'enqueued', 'job': job})
            elif action == 'list':
                return json.dumps({'count': len(queue), 'jobs': queue[-20:]})
            elif action == 'dequeue':
                if not queue:
                    return json.dumps({'status': 'empty'})
                job = queue.pop(0)
                with open(queue_file, 'w') as f:
                    json.dump(queue, f, indent=2)
                return json.dumps({'status': 'dequeued', 'job': job})
            elif action == 'clear':
                count = len(queue)
                with open(queue_file, 'w') as f:
                    json.dump([], f)
                return json.dumps({'status': 'cleared', 'removed': count})
        return json.dumps({'error': f'Unknown action: {action}'})


class PrioritySchedulerTool(BaseTool):
    name: str = 'Priority Scheduler'
    description: str = (
        'Schedule tasks with priority scores. Higher priority = earlier execution. '
        "Actions: 'schedule', 'list', 'next', 'complete'."
    )

    def _run(
        self,
        action: str,
        task_id: str = '',
        task_name: str = '',
        priority: float = 5.0,
        metadata_json: str = '{}',
        store_file: str = _runtime_path('clipfarm_priority_queue.json'),
    ) -> str:
        with _LOCKS['priority']:
            tasks = []
            if os.path.exists(store_file):
                with open(store_file) as f:
                    tasks = json.load(f)
            if action == 'schedule':
                task = {
                    'id': task_id
                    or hashlib.md5(f'{task_name}{time.time()}'.encode(), usedforsecurity=False).hexdigest()[:10],
                    'name': task_name,
                    'priority': priority,
                    'metadata': json.loads(metadata_json) if metadata_json else {},
                    'scheduled_at': _now_iso(),
                    'status': 'pending',
                }
                tasks.append(task)
                tasks.sort(key=lambda x: -x.get('priority', 5))
                with open(store_file, 'w') as f:
                    json.dump(tasks, f, indent=2)
                return json.dumps({'status': 'scheduled', **task})
            elif action == 'list':
                return json.dumps({'count': len(tasks), 'tasks': tasks[:20]})
            elif action == 'next':
                pending = [t for t in tasks if t.get('status') == 'pending']
                return json.dumps({'next': pending[0] if pending else None, 'pending_count': len(pending)})
            elif action == 'complete':
                for t in tasks:
                    if t.get('id') == task_id:
                        t['status'] = 'completed'
                        t['completed_at'] = _now_iso()
                with open(store_file, 'w') as f:
                    json.dump(tasks, f, indent=2)
                return json.dumps({'status': 'completed', 'task_id': task_id})
        return json.dumps({'error': f'Unknown action: {action}'})


class RetryQueueManagerTool(BaseTool):
    name: str = 'Retry Queue Manager'
    description: str = (
        "Manage a retry queue for failed pipeline tasks. Actions: 'add', 'list', 'retry_next', 'clear_failed'."
    )

    def _run(
        self,
        action: str,
        task_id: str = '',
        task_json: str = '{}',
        max_retries: int = 3,
        store_file: str = _runtime_path('clipfarm_retry_queue.json'),
    ) -> str:
        with _LOCKS['retry']:
            queue = []
            if os.path.exists(store_file):
                with open(store_file) as f:
                    queue = json.load(f)
            if action == 'add':
                task = json.loads(task_json) if task_json else {}
                task.setdefault(
                    'id', task_id or hashlib.md5(str(time.time()).encode(), usedforsecurity=False).hexdigest()[:10]
                )
                task.setdefault('retries', 0)
                task['max_retries'] = max_retries
                task['last_attempt'] = _now_iso()
                task['status'] = 'pending_retry'
                queue.append(task)
                with open(store_file, 'w') as f:
                    json.dump(queue, f, indent=2)
                return json.dumps({'status': 'added', **task})
            elif action == 'list':
                return json.dumps({'count': len(queue), 'queue': queue[-20:]})
            elif action == 'retry_next':
                pending = [
                    t
                    for t in queue
                    if t.get('status') == 'pending_retry' and t.get('retries', 0) < t.get('max_retries', 3)
                ]
                if not pending:
                    return json.dumps({'status': 'no_pending'})
                task = pending[0]
                task['retries'] = task.get('retries', 0) + 1
                task['last_attempt'] = _now_iso()
                with open(store_file, 'w') as f:
                    json.dump(queue, f, indent=2)
                return json.dumps({'status': 'retrying', 'task': task})
            elif action == 'clear_failed':
                before = len(queue)
                queue = [t for t in queue if t.get('retries', 0) < t.get('max_retries', 3)]
                with open(store_file, 'w') as f:
                    json.dump(queue, f, indent=2)
                return json.dumps({'status': 'cleared', 'removed': before - len(queue)})
        return json.dumps({'error': f'Unknown action: {action}'})
