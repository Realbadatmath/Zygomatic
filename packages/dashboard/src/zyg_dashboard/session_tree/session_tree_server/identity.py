# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Identity from the caller's own transcript — the role gate.

Moved verbatim from session_tree_server.py lines 433-485.
"""

from ._base import CLAUDE_PROJECTS, glob, os, re
from .storage import CFG


# ───────────────────────────── identity (transcript) ─────────────────────────


def _find_transcript(session_id):
    if not re.fullmatch(r'[0-9a-fA-F-]{8,64}', session_id or ''):
        return None
    hits = glob.glob(os.path.join(CLAUDE_PROJECTS, '*', session_id + '.jsonl'))
    if not hits:
        return None
    hits.sort(key=os.path.getmtime, reverse=True)
    return hits[0]


def _model_from_transcript(path):
    """Last model the harness recorded for this session (assistant turns carry
    message.model). Reads the tail of the file only."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 400_000))
            blob = f.read().decode('utf-8', 'replace')
    except Exception:
        return None
    models = re.findall(r'"model"\s*:\s*"([^"]+)"', blob)
    models = [m for m in models if m.startswith('claude')]
    return models[-1] if models else None


def identify(body):
    sid = (body or {}).get('session_id') or ''
    path = _find_transcript(sid)
    if not path:
        return {
            'session_id': sid,
            'model': None,
            'role': 'unknown',
            'why': 'no Claude Code transcript found for this session id '
            '(CLAUDE_CODE_SESSION_ID missing, or the session has not '
            'produced an assistant turn yet)',
        }
    model = _model_from_transcript(path)
    role = 'unknown'
    if model:
        if any(model.startswith(p) for p in CFG['creator_models']):
            role = 'creator'
        elif any(model.startswith(p) for p in CFG['executor_models']):
            role = 'executor'
        else:
            role = 'other'
    return {'session_id': sid, 'model': model, 'role': role, 'transcript': path, 'pid': (body or {}).get('pid')}
