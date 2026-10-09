# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Workflow overrides and the workflow health check."""

import json
import os
from zyg_workflows.runtime import _runtime_path

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')


def _load_workflow_overrides() -> dict:
    """Return the current user override decisions (skip/fix per issue_id)."""
    f = _runtime_path('clipfarm_workflow_overrides.json')
    if os.path.exists(f):
        try:
            with open(f) as fh:
                return json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('%s unreadable, using an empty dict: %s', f, _exc)
    return {}


def _check_workflow_health() -> list:
    """
    Scan for known workflow blockers. Returns a list of issue dicts.
    Issues have: id, title, description, severity, fix_available, skip_note, auto_resolved.
    """
    issues = []
    creds_file = _runtime_path('clipfarm_credentials.json')
    creds = {}
    if os.path.exists(creds_file):
        try:
            with open(creds_file) as f:
                creds = json.load(f)
        except Exception as _exc:
            _zyg_log.warning(
                'credentials file %s unreadable, treating every credential as absent: %s', creds_file, _exc
            )

    # Reddit credentials
    if not creds.get('REDDIT_CLIENT_ID') and not creds.get('REDDIT_CLIENT_SECRET'):
        issues.append(
            {
                'id': 'reddit_no_credentials',
                'title': 'Reddit API not configured',
                'description': (
                    'Source Scanner cannot pull Reddit trending posts. '
                    'No REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET found in credentials.'
                ),
                'severity': 'warning',
                'fix_available': False,
                'skip_note': 'YouTube RSS scanner will be used instead. Reddit steps are already bypassed.',
                'auto_resolved': True,
            }
        )

    # Upload platforms
    has_upload = any(
        creds.get(k)
        for k in (
            'YOUTUBE_UPLOAD_CLIENT_ID',
            'YOUTUBE_UPLOAD_CLIENT_SECRET',
            'TIKTOK_API_KEY',
            'INSTAGRAM_ACCESS_TOKEN',
            'UPLOAD_PLATFORM',
        )
    )
    if not has_upload:
        issues.append(
            {
                'id': 'no_upload_platforms',
                'title': 'No upload platforms configured',
                'description': (
                    'Upload Agent has no destinations. '
                    'No YouTube upload OAuth, TikTok, or Instagram credentials found. '
                    'The Publish stage (Stage 6) cannot push clips anywhere.'
                ),
                'severity': 'warning',
                'fix_available': False,
                'skip_note': (
                    'Finished clips will be saved to data/output/clipfarm/<job_id>/ '
                    'so you can evaluate them before connecting a real platform.'
                ),
                'auto_resolved': False,
            }
        )

    return issues
