# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Config & Registry tools (lines 102-329 of the original pipeline_tools.py)."""

from .base import BaseTool, _LOCKS, _RUNTIME_DIR, _now_iso, _runtime_path, hashlib, json, os

# ---------------------------------------------------------------------------
# Config & Registry tools
# ---------------------------------------------------------------------------


class ConfigStoreTool(BaseTool):
    name: str = 'Config Store (JSON / DB read-write)'
    description: str = (
        'Read or write configuration values to a persistent JSON store. '
        "Actions: 'get', 'set', 'delete', 'list'. Key-value based."
    )

    def _run(
        self, action: str, key: str = '', value: str = '', store_file: str = _runtime_path('clipfarm_config.json')
    ) -> str:
        with _LOCKS['config']:
            data = {}
            if os.path.exists(store_file):
                with open(store_file) as f:
                    data = json.load(f)
            if action == 'get':
                return json.dumps({'key': key, 'value': data.get(key)})
            elif action == 'set':
                parsed = json.loads(value) if value.startswith(('{', '[', '"')) else value
                data[key] = parsed
                with open(store_file, 'w') as f:
                    json.dump(data, f, indent=2)
                return json.dumps({'status': 'ok', 'key': key, 'value': parsed})
            elif action == 'delete':
                removed = data.pop(key, None)
                with open(store_file, 'w') as f:
                    json.dump(data, f, indent=2)
                return json.dumps({'status': 'ok', 'removed': removed is not None})
            elif action == 'list':
                return json.dumps({'keys': list(data.keys()), 'count': len(data)})
            return json.dumps({'error': f'Unknown action: {action}'})


class SystemParameterStoreTool(BaseTool):
    name: str = 'System Parameter Store'
    description: str = (
        "Read or write system-level parameters (thresholds, limits, toggles). Actions: 'get', 'set', 'list'."
    )

    def _run(
        self,
        action: str,
        key: str = '',
        value: str = '',
        store_file: str = _runtime_path('clipfarm_system_params.json'),
    ) -> str:
        # Reuse config store logic
        tool = ConfigStoreTool()
        return tool._run(action, key, value, store_file)


class SafetyThresholdCheckerTool(BaseTool):
    name: str = 'Safety Threshold Checker (reads safety_thresholds.json)'
    description: str = (
        'Check whether a given metric value exceeds defined safety thresholds. '
        'Returns whether threshold is breached and by how much.'
    )

    def _run(self, metric_name: str, value: float, thresholds_file: str = 'safety_thresholds.json') -> str:
        # Try to find thresholds file relative to crews dir
        for base in [os.getcwd(), os.path.dirname(__file__), _RUNTIME_DIR]:
            path = os.path.join(base, thresholds_file)
            if os.path.exists(path):
                with open(path) as f:
                    thresholds = json.load(f)
                break
        else:
            # Default thresholds
            thresholds = {
                'cpu_percent': 90.0,
                'ram_percent': 85.0,
                'gpu_temp_c': 85.0,
                'disk_percent': 90.0,
                'error_rate': 0.1,
                'queue_depth': 1000,
            }

        threshold = thresholds.get(metric_name)
        if threshold is None:
            return json.dumps({'metric': metric_name, 'value': value, 'status': 'no_threshold', 'breached': False})
        breached = float(value) > float(threshold)
        return json.dumps(
            {
                'metric': metric_name,
                'value': value,
                'threshold': threshold,
                'breached': breached,
                'overage': round(float(value) - float(threshold), 4) if breached else 0,
            }
        )


class PlatformCredentialsRegistryTool(BaseTool):
    name: str = 'Platform Credentials Registry (read)'
    description: str = (
        'Read platform API credential references (not secrets) from the registry. '
        'Returns which credential keys are configured per platform.'
    )

    def _run(self, platform: str = '') -> str:
        PLATFORMS = {
            'youtube': ['YOUTUBE_API_KEY', 'YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET'],
            'tiktok': ['TIKTOK_ACCESS_TOKEN', 'TIKTOK_APP_ID'],
            'instagram': ['INSTAGRAM_ACCESS_TOKEN', 'INSTAGRAM_ACCOUNT_ID'],
            'reddit': ['REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET'],
        }
        result = {}
        platforms = [platform.lower()] if platform else list(PLATFORMS.keys())
        for p in platforms:
            keys = PLATFORMS.get(p, [])
            result[p] = {k: bool(os.getenv(k)) for k in keys}
        return json.dumps({'platforms': result, 'note': 'Shows which env vars are set (True/False), not their values'})


class ChannelRegistryTool(BaseTool):
    name: str = 'Channel Registry (read)'
    description: str = 'Read the list of registered channels from the channel registry store.'

    def _run(self, filter_platform: str = '', registry_file: str = _runtime_path('clipfarm_channels.json')) -> str:
        if os.path.exists(registry_file):
            with open(registry_file) as f:
                channels = json.load(f)
        else:
            channels = []
        if filter_platform:
            channels = [c for c in channels if c.get('platform', '').lower() == filter_platform.lower()]
        return json.dumps({'count': len(channels), 'channels': channels})


class FileRegistryTool(BaseTool):
    name: str = 'File Registry (track all pipeline-written files)'
    description: str = (
        'Register or query files written by the pipeline. '
        "Actions: 'register', 'list', 'check'. Tracks path, agent, timestamp, type."
    )

    def _run(
        self,
        action: str,
        file_path: str = '',
        agent: str = '',
        file_type: str = 'output',
        registry_file: str = _runtime_path('clipfarm_file_registry.json'),
    ) -> str:
        with _LOCKS['file_registry']:
            registry = []
            if os.path.exists(registry_file):
                with open(registry_file) as f:
                    registry = json.load(f)
            if action == 'register':
                entry = {
                    'path': file_path,
                    'agent': agent,
                    'type': file_type,
                    'timestamp': _now_iso(),
                    'exists': os.path.exists(file_path),
                    'size_bytes': os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                }
                registry.append(entry)
                with open(registry_file, 'w') as f:
                    json.dump(registry, f, indent=2)
                return json.dumps({'status': 'registered', **entry})
            elif action == 'list':
                return json.dumps({'count': len(registry), 'files': registry[-50:]})
            elif action == 'check':
                matches = [r for r in registry if r.get('path') == file_path]
                return json.dumps({'path': file_path, 'registered': len(matches) > 0, 'entries': matches})
        return json.dumps({'error': f'Unknown action: {action}'})


class DuplicateFlagRegistryTool(BaseTool):
    name: str = 'Duplicate Flag Registry'
    description: str = (
        "Store and query content-hash based duplicate flags. Actions: 'flag', 'check', 'list'. Uses SHA256 of content."
    )

    def _run(
        self,
        action: str,
        content_hash: str = '',
        content: str = '',
        label: str = '',
        registry_file: str = _runtime_path('clipfarm_duplicates.json'),
    ) -> str:
        if content and not content_hash:
            content_hash = hashlib.sha256(content.encode()).hexdigest()
        with _LOCKS['duplicates']:
            registry = {}
            if os.path.exists(registry_file):
                with open(registry_file) as f:
                    registry = json.load(f)
            if action == 'flag':
                registry[content_hash] = {'label': label, 'flagged_at': _now_iso(), 'hash': content_hash}
                with open(registry_file, 'w') as f:
                    json.dump(registry, f, indent=2)
                return json.dumps({'status': 'flagged', 'hash': content_hash})
            elif action == 'check':
                entry = registry.get(content_hash)
                return json.dumps({'hash': content_hash, 'is_duplicate': entry is not None, 'entry': entry})
            elif action == 'list':
                return json.dumps({'count': len(registry), 'flags': list(registry.values())[-50:]})
        return json.dumps({'error': f'Unknown action: {action}'})


class DuplicateFlagCheckerTool(BaseTool):
    name: str = 'Duplicate Flag Checker'
    description: str = (
        'Check if content or a file has already been flagged as a duplicate '
        'by comparing its SHA256 hash against the registry.'
    )

    def _run(self, content: str = '', file_path: str = '') -> str:
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                content_hash = hashlib.sha256(f.read()).hexdigest()
        elif content:
            content_hash = hashlib.sha256(content.encode()).hexdigest()
        else:
            return json.dumps({'error': 'Provide content or file_path'})
        tool = DuplicateFlagRegistryTool()
        return tool._run('check', content_hash=content_hash)
