# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Clip metadata & boundary tools and Logger & Emitter tools (lines 813-1123 of the original pipeline_tools.py)."""

from .base import BaseTool, _now_iso, _runtime_path, datetime, exe, json, os
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.tools.pipeline_tools')

# ---------------------------------------------------------------------------
# Clip metadata & boundary tools
# ---------------------------------------------------------------------------


class ClipBoundaryExtractorTool(BaseTool):
    name: str = 'Clip Boundary Extractor'
    description: str = (
        'Extract clip start/end boundary candidates from a video based on silence, '
        'scene changes, and audio energy. Returns list of candidate clip boundaries.'
    )

    def _run(self, video_path: str, min_clip_sec: float = 15.0, max_clip_sec: float = 90.0) -> str:
        import subprocess
        import json

        # Use ffmpeg silencedetect to find natural cut points
        cmd = [exe('ffmpeg'), '-i', video_path, '-af', 'silencedetect=noise=-30dB:d=0.5', '-f', 'null', '/dev/null']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        import re

        silences = re.findall(r'silence_end: ([\d.]+)', result.stderr)
        boundaries = [0.0] + [float(s) for s in silences]
        # Build clip candidates between boundaries
        clips = []
        for i in range(len(boundaries) - 1):
            duration = boundaries[i + 1] - boundaries[i]
            if min_clip_sec <= duration <= max_clip_sec:
                clips.append(
                    {
                        'start': round(boundaries[i], 3),
                        'end': round(boundaries[i + 1], 3),
                        'duration': round(duration, 3),
                    }
                )
        return json.dumps({'candidate_clips': clips, 'count': len(clips), 'silence_points': len(silences)})


class ClipDurationValidatorTool(BaseTool):
    name: str = 'Clip Duration Validator'
    description: str = (
        'Validate that a clip meets platform duration requirements. '
        'Returns pass/fail and which platforms the duration is valid for.'
    )

    def _run(self, duration_sec: float) -> str:
        PLATFORM_LIMITS = {
            'youtube_shorts': (15, 60),
            'tiktok': (5, 600),
            'instagram_reels': (3, 90),
            'youtube_long': (60, 43200),
        }
        results = {}
        for platform, (min_s, max_s) in PLATFORM_LIMITS.items():
            results[platform] = {
                'valid': min_s <= duration_sec <= max_s,
                'min_sec': min_s,
                'max_sec': max_s,
            }
        valid_platforms = [p for p, r in results.items() if r['valid']]
        return json.dumps(
            {
                'duration_sec': duration_sec,
                'valid_platforms': valid_platforms,
                'platform_check': results,
            }
        )


class ClipMetadataReaderTool(BaseTool):
    name: str = 'Clip Metadata Reader'
    description: str = 'Read and return structured metadata for a clip file.'

    def _run(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            return json.dumps({'error': f'File not found: {file_path}'})
        stat = os.stat(file_path)
        meta = {
            'path': file_path,
            'size_bytes': stat.st_size,
            'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'modified_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'extension': os.path.splitext(file_path)[1].lower(),
        }
        # Try mediainfo for richer data
        try:
            from pymediainfo import MediaInfo

            mi = MediaInfo.parse(file_path)
            for track in mi.tracks:
                if track.track_type == 'General':
                    meta['duration_ms'] = track.duration
                    meta['format'] = track.format
                    meta['overall_bitrate'] = track.overall_bit_rate
                elif track.track_type == 'Video' and 'width' not in meta:
                    meta['width'] = track.width
                    meta['height'] = track.height
                    meta['frame_rate'] = track.frame_rate
        except Exception as _exc:
            _zyg_log.warning('mediainfo enrichment unavailable, returning the stat-only metadata: %s', _exc)
        return json.dumps(meta)


# ---------------------------------------------------------------------------
# Logger & Emitter tools
# ---------------------------------------------------------------------------


def _log_event(log_file: str, event: dict):
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    logs = []
    if os.path.exists(log_file):
        with open(log_file) as f:
            logs = json.load(f)
    logs.append({**event, 'timestamp': _now_iso()})
    with open(log_file, 'w') as f:
        json.dump(logs[-2000:], f, indent=2)  # keep last 2000 entries


class AuditLoggerTool(BaseTool):
    name: str = 'Audit Logger'
    description: str = 'Log an audit event with agent, action, and metadata to the audit log.'

    def _run(
        self,
        agent: str,
        action: str,
        metadata_json: str = '{}',
        log_file: str = _runtime_path('clipfarm_audit.json'),
    ) -> str:
        event = {'agent': agent, 'action': action, 'metadata': json.loads(metadata_json) if metadata_json else {}}
        _log_event(log_file, event)
        return json.dumps({'status': 'logged', **event, 'file': log_file})


class ConfigChangeLoggerTool(BaseTool):
    name: str = 'Config Change Logger'
    description: str = 'Log a configuration change with before/after values.'

    def _run(
        self,
        key: str,
        old_value: str = '',
        new_value: str = '',
        changed_by: str = 'system',
        log_file: str = _runtime_path('clipfarm_config_changes.json'),
    ) -> str:
        event = {'key': key, 'old_value': old_value, 'new_value': new_value, 'changed_by': changed_by}
        _log_event(log_file, event)
        return json.dumps({'status': 'logged', **event})


class CleanupLoggerTool(BaseTool):
    name: str = 'Cleanup Logger'
    description: str = 'Log a cleanup operation (files deleted, temp cleared, etc.).'

    def _run(
        self,
        operation: str,
        files_removed: int = 0,
        bytes_freed: int = 0,
        log_file: str = _runtime_path('clipfarm_cleanup.json'),
    ) -> str:
        event = {'operation': operation, 'files_removed': files_removed, 'bytes_freed': bytes_freed}
        _log_event(log_file, event)
        return json.dumps({'status': 'logged', **event})


class PostIDLoggerTool(BaseTool):
    name: str = 'Post ID Logger'
    description: str = 'Log a successfully published post with its platform post ID.'

    def _run(
        self,
        platform: str,
        post_id: str,
        video_title: str = '',
        channel_id: str = '',
        log_file: str = _runtime_path('clipfarm_published_posts.json'),
    ) -> str:
        event = {'platform': platform, 'post_id': post_id, 'title': video_title, 'channel_id': channel_id}
        _log_event(log_file, event)
        return json.dumps({'status': 'logged', **event})


class PublishedStatusLoggerTool(BaseTool):
    name: str = 'Published Status Logger'
    description: str = 'Log the publish status (success/failed) for a content item.'

    def _run(
        self,
        content_id: str,
        status: str,
        platform: str = '',
        error: str = '',
        log_file: str = _runtime_path('clipfarm_publish_status.json'),
    ) -> str:
        event = {'content_id': content_id, 'status': status, 'platform': platform, 'error': error}
        _log_event(log_file, event)
        return json.dumps({'status': 'logged', **event})


class AlertNotifierTool(BaseTool):
    name: str = 'Alert Notifier'
    description: str = (
        'Send an alert notification to the configured alert channel '
        '(logs to file; extend with Slack/email webhook via ALERT_WEBHOOK_URL env var).'
    )

    def _run(
        self,
        alert_type: str,
        message: str,
        severity: str = 'warning',
        source_agent: str = '',
        log_file: str = _runtime_path('clipfarm_alerts.json'),
    ) -> str:
        event = {'type': alert_type, 'message': message, 'severity': severity, 'source': source_agent}
        _log_event(log_file, event)
        # Optional webhook delivery
        webhook = os.getenv('ALERT_WEBHOOK_URL', '')
        delivered = False
        if webhook:
            try:
                import requests

                requests.post(webhook, json=event, timeout=5)
                delivered = True
            except Exception as _exc:
                _zyg_log.warning('webhook delivery failed, reporting delivered_webhook=false: %s', _exc)
        return json.dumps({'status': 'notified', 'delivered_webhook': delivered, **event})


class BlockerReportEmitterTool(BaseTool):
    name: str = 'Blocker Report Emitter → Zero'
    description: str = 'Emit a blocker report to Zero (the orchestrator) when a pipeline step is stuck.'

    def _run(self, blocked_agent: str, reason: str, context_json: str = '{}') -> str:
        event = {
            'blocked_agent': blocked_agent,
            'reason': reason,
            'context': json.loads(context_json) if context_json else {},
            'target': 'Zero',
        }
        _log_event(_runtime_path('clipfarm_blocker_reports.json'), event)
        return json.dumps({'status': 'emitted', **event})


class StorageWarningEmitterTool(BaseTool):
    name: str = 'Storage Warning Emitter → Overseer'
    description: str = 'Emit a storage warning to the Overseer agent when disk usage is high.'

    def _run(self, path: str = '/', threshold_percent: float = 85.0) -> str:
        import psutil

        usage = psutil.disk_usage(path)
        if usage.percent >= threshold_percent:
            event = {
                'path': path,
                'used_percent': usage.percent,
                'free_gb': round(usage.free / 1e9, 2),
                'threshold': threshold_percent,
                'target': 'Overseer',
            }
            _log_event(_runtime_path('clipfarm_storage_warnings.json'), event)
            return json.dumps({'status': 'warning_emitted', **event})
        return json.dumps({'status': 'ok', 'used_percent': usage.percent, 'threshold': threshold_percent})


class QuotaExhaustedEmitterTool(BaseTool):
    name: str = 'Quota Exhausted Report Emitter → Zero'
    description: str = 'Emit a quota exhaustion report to Zero when an API quota is used up.'

    def _run(self, api_name: str, quota_type: str = 'daily', reset_at_iso: str = '') -> str:
        event = {'api': api_name, 'quota_type': quota_type, 'reset_at': reset_at_iso, 'target': 'Zero'}
        _log_event(_runtime_path('clipfarm_quota_exhausted.json'), event)
        return json.dumps({'status': 'emitted', **event})


class HardwareBlockReportEmitterTool(BaseTool):
    name: str = 'Hardware Block Report Emitter → Zero'
    description: str = 'Emit a hardware resource block report to Zero (e.g. GPU OOM, CPU overload).'

    def _run(self, resource: str, reason: str, current_value: float = 0.0) -> str:
        event = {'resource': resource, 'reason': reason, 'current_value': current_value, 'target': 'Zero'}
        _log_event(_runtime_path('clipfarm_hardware_blocks.json'), event)
        return json.dumps({'status': 'emitted', **event})


class DiskBlockReportEmitterTool(BaseTool):
    name: str = 'Disk Block Report Emitter → Zero'
    description: str = 'Emit a disk block report to Zero when disk I/O or space causes a pipeline block.'

    def _run(self, reason: str, path: str = '/', free_gb: float = 0.0) -> str:
        event = {'reason': reason, 'path': path, 'free_gb': free_gb, 'target': 'Zero'}
        _log_event(_runtime_path('clipfarm_disk_blocks.json'), event)
        return json.dumps({'status': 'emitted', **event})


class ConfigErrorReportEmitterTool(BaseTool):
    name: str = 'Config Error Report Emitter → Zero'
    description: str = 'Emit a configuration error report to Zero.'

    def _run(self, config_key: str, error: str, agent: str = '') -> str:
        event = {'config_key': config_key, 'error': error, 'agent': agent, 'target': 'Zero'}
        _log_event(_runtime_path('clipfarm_config_errors.json'), event)
        return json.dumps({'status': 'emitted', **event})
