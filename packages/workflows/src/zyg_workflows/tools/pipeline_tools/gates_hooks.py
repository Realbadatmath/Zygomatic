# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Approval gates and Hook tools (lines 1124-1364 of the original pipeline_tools.py)."""

from .base import BaseTool, _LOCKS, _ams_now, _now_iso, _runtime_path, json, os
from .clip_logging import _log_event

# ---------------------------------------------------------------------------
# Approval gates
# ---------------------------------------------------------------------------


class JobApprovalGateTool(BaseTool):
    name: str = 'Job Approval Gate'
    description: str = (
        "Request, check, or grant approval for a pipeline job. Actions: 'request', 'approve', 'deny', 'check'."
    )

    def _run(
        self,
        action: str,
        job_id: str,
        reason: str = '',
        approver: str = 'system',
        store_file: str = _runtime_path('clipfarm_approvals.json'),
    ) -> str:
        with _LOCKS['approvals']:
            approvals = {}
            if os.path.exists(store_file):
                with open(store_file) as f:
                    approvals = json.load(f)
            if action == 'request':
                approvals[job_id] = {'status': 'pending', 'reason': reason, 'requested_at': _now_iso()}
                with open(store_file, 'w') as f:
                    json.dump(approvals, f, indent=2)
                return json.dumps({'status': 'pending', 'job_id': job_id})
            elif action == 'approve':
                if job_id not in approvals:
                    approvals[job_id] = {}
                approvals[job_id].update({'status': 'approved', 'approver': approver, 'approved_at': _now_iso()})
                with open(store_file, 'w') as f:
                    json.dump(approvals, f, indent=2)
                return json.dumps({'status': 'approved', 'job_id': job_id})
            elif action == 'deny':
                if job_id not in approvals:
                    approvals[job_id] = {}
                approvals[job_id].update({'status': 'denied', 'reason': reason, 'denied_at': _now_iso()})
                with open(store_file, 'w') as f:
                    json.dump(approvals, f, indent=2)
                return json.dumps({'status': 'denied', 'job_id': job_id})
            elif action == 'check':
                entry = approvals.get(job_id, {'status': 'unknown'})
                return json.dumps({'job_id': job_id, **entry})
        return json.dumps({'error': f'Unknown action: {action}'})


class ZeroApprovalGateTool(BaseTool):
    name: str = 'Zero Approval Gate'
    description: str = 'Gate that requires explicit approval from Zero before proceeding.'

    def _run(self, job_id: str, required_action: str = '') -> str:
        tool = JobApprovalGateTool()
        return tool._run('check', job_id)


class ZeroApprovalRequestSenderTool(BaseTool):
    name: str = 'Zero Approval Request Sender'
    description: str = 'Send an approval request to Zero for a high-stakes pipeline action.'

    def _run(self, job_id: str, action_description: str, risk_level: str = 'medium') -> str:
        tool = JobApprovalGateTool()
        # The gate's own status was discarded, so this reported 'request_sent'
        # whatever the gate did with the request.
        gate = json.loads(tool._run('request', job_id, reason=action_description))
        event = {'job_id': job_id, 'action': action_description, 'risk_level': risk_level, 'target': 'Zero'}
        _log_event(_runtime_path('clipfarm_zero_approval_requests.json'), event)
        return json.dumps({'status': 'request_sent', 'gate_status': gate.get('status'), **event})


class TokenGrantDelayDenyTool(BaseTool):
    name: str = 'Token Grant / Delay / Deny Engine'
    description: str = (
        "Manage token-based rate limiting for pipeline actions. Actions: 'grant', 'delay', 'deny', 'check_quota'."
    )

    def _run(
        self,
        action: str,
        token_type: str,
        agent: str = '',
        store_file: str = _runtime_path('clipfarm_tokens.json'),
    ) -> str:
        LIMITS = {'api_call': 100, 'upload': 10, 'download': 50, 'llm_inference': 200}
        with _LOCKS['tokens']:
            tokens = {}
            if os.path.exists(store_file):
                with open(store_file) as f:
                    tokens = json.load(f)
            today = _ams_now().strftime('%Y-%m-%d')
            key = f'{token_type}:{today}'
            used = tokens.get(key, 0)
            limit = LIMITS.get(token_type, 100)
            if action == 'grant':
                if used >= limit:
                    return json.dumps({'decision': 'deny', 'token_type': token_type, 'used': used, 'limit': limit})
                tokens[key] = used + 1
                with open(store_file, 'w') as f:
                    json.dump(tokens, f, indent=2)
                return json.dumps(
                    {
                        'decision': 'granted',
                        'token_type': token_type,
                        'used': used + 1,
                        'limit': limit,
                        'remaining': limit - used - 1,
                    }
                )
            elif action == 'check_quota':
                return json.dumps(
                    {
                        'token_type': token_type,
                        'used': used,
                        'limit': limit,
                        'remaining': max(0, limit - used),
                        'exhausted': used >= limit,
                    }
                )
        return json.dumps({'error': f'Unknown action: {action}'})


# ---------------------------------------------------------------------------
# Hook tools
# ---------------------------------------------------------------------------


class HookInjectorTool(BaseTool):
    name: str = 'Hook Injector'
    description: str = (
        'Inject a hook phrase at the start of a script or video description to maximize viewer retention.'
    )

    def _run(self, content: str, hook_phrase: str = '', hook_style: str = 'question') -> str:
        STYLES = {
            'question': ['Did you know', 'Have you ever wondered', 'What if I told you'],
            'statement': ['This will change everything', 'Nobody talks about this', "Most people don't know"],
            'challenge': ['Try not to', 'Watch until the end', 'Can you guess'],
        }
        if not hook_phrase:
            import random

            hook_phrase = random.choice(STYLES.get(hook_style, STYLES['question']))
        hooked = f'{hook_phrase}... {content}'
        return json.dumps(
            {
                'hooked_content': hooked,
                'hook_phrase': hook_phrase,
                'style': hook_style,
                'original_length': len(content),
                'new_length': len(hooked),
            }
        )


class HookScriptReaderTool(BaseTool):
    name: str = 'Hook Script Reader'
    description: str = 'Read hook phrase scripts from the hook template library.'

    def _run(self, category: str = '', library_file: str = _runtime_path('clipfarm_hook_scripts.json')) -> str:
        if os.path.exists(library_file):
            with open(library_file) as f:
                library = json.load(f)
        else:
            library = {
                'question': ['Did you know {topic}?', 'What happens when {topic}?'],
                'curiosity': ['The secret to {topic}...', 'Why {topic} matters more than you think'],
                'challenge': ['Try this {topic} trick', 'Most people fail at {topic}'],
            }
        if category:
            return json.dumps(
                {'category': category, 'hooks': library.get(category, []), 'count': len(library.get(category, []))}
            )
        return json.dumps(
            {'categories': list(library.keys()), 'total': sum(len(v) for v in library.values()), 'library': library}
        )


class HookTemplateTool(BaseTool):
    name: str = 'Hook Template Library'
    description: str = 'Browse or search the hook template library for video openings.'

    def _run(self, search_term: str = '', limit: int = 10) -> str:
        tool = HookScriptReaderTool()
        result = json.loads(tool._run())
        library = result.get('library', {})
        all_hooks = []
        for cat, hooks in library.items():
            for hook in hooks:
                all_hooks.append({'hook': hook, 'category': cat})
        if search_term:
            all_hooks = [h for h in all_hooks if search_term.lower() in h['hook'].lower()]
        return json.dumps({'count': len(all_hooks), 'hooks': all_hooks[:limit]})


class HookTemplateStoreTool(BaseTool):
    name: str = 'Hook Template Store'
    description: str = 'Save a new hook template to the library.'

    def _run(
        self,
        hook_text: str,
        category: str = 'custom',
        library_file: str = _runtime_path('clipfarm_hook_scripts.json'),
    ) -> str:
        library = {}
        if os.path.exists(library_file):
            with open(library_file) as f:
                library = json.load(f)
        if category not in library:
            library[category] = []
        if hook_text not in library[category]:
            library[category].append(hook_text)
        with open(library_file, 'w') as f:
            json.dump(library, f, indent=2)
        return json.dumps({'status': 'saved', 'hook': hook_text, 'category': category})


class HookTemplateUpdaterTool(BaseTool):
    name: str = 'Hook Template Updater'
    description: str = 'Update or replace an existing hook template.'

    def _run(
        self, old_hook: str, new_hook: str, library_file: str = _runtime_path('clipfarm_hook_scripts.json')
    ) -> str:
        if not os.path.exists(library_file):
            return json.dumps({'error': 'Library file not found'})
        with open(library_file) as f:
            library = json.load(f)
        updated = False
        for cat in library:
            if old_hook in library[cat]:
                idx = library[cat].index(old_hook)
                library[cat][idx] = new_hook
                updated = True
        with open(library_file, 'w') as f:
            json.dump(library, f, indent=2)
        return json.dumps({'status': 'updated' if updated else 'not_found', 'old': old_hook, 'new': new_hook})
