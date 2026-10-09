# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The source list behind the payload and its data_version fingerprint."""

from __future__ import annotations

import glob
import hashlib
import json
import os
from zyg_dashboard import metrics_hub as mh

from .arch_studio import ARCH_SOURCES
from .constants import CREWS, RUNTIME


# ── the section ──────────────────────────────────────────────────────────────


def _sources(now):
    pats = [
        ('Pipeline states', 'pipeline_*_state.json'),
        ('Storyteller states', 'storyteller_*_state.json'),
        ('Character / creature / sheet jobs', 'char_gen_*.json'),
        ('LLM audit log', 'llm_audit/*.jsonl'),
        ('Context ledger', 'context_ledger.jsonl'),
        ('Agent sessions ledger', 'agent_sessions_ledger.jsonl'),
        ('System usage (minute samples)', 'system_usage.jsonl'),
        ('Telemetry CSVs (per-run, until 2026-08-25)', 'telemetry_*.csv'),
        ('Claude quota samples', 'quota_samples.jsonl'),
        ('Approval Queue toggles', '*_daily.json'),
        ('Zero auto mode', 'zero_auto_mode.json'),
        ('Assumptions', 'analytics_config.json'),
        ('Pre-emptive bank entries', 'preempt/documentary/*/entry.json'),
        ('Pre-emptive bank ledgers', 'preempt/documentary/*/turns.jsonl'),
        ('Pre-emptive song briefs', 'preempt/songs.json'),
        ('Pre-emptive builder state', 'preempt/state.json'),
    ]
    out = []
    for label, pat in pats:
        paths = glob.glob(os.path.join(RUNTIME, pat))
        mt = max((os.path.getmtime(p) for p in paths), default=None)
        out.append(
            {
                'source': label,
                'path': 'data/runtime/' + pat,
                'files': len(paths),
                'last_write': mh._iso(mt),
                'age_s': round(now - mt) if mt else None,
            }
        )
    for label, pat in ARCH_SOURCES:  # Architecture Studio card (2026-09-18)
        paths = glob.glob(pat)
        mt = max((os.path.getmtime(p) for p in paths), default=None)
        out.append(
            {
                'source': label,
                'path': os.path.relpath(pat, CREWS),
                'files': len(paths),
                'last_write': mh._iso(mt),
                'age_s': round(now - mt) if mt else None,
            }
        )
    return out


def _version(sources, cfg, toggles):
    # Cache-busting fingerprint of the payload's inputs, not a security digest.
    h = hashlib.sha1(usedforsecurity=False)
    for s in sources:
        h.update(f'{s["path"]}={s["last_write"]}={s["files"]};'.encode())
    h.update(json.dumps(cfg, sort_keys=True).encode())
    h.update(json.dumps([(t['id'], t['enabled']) for t in toggles]).encode())
    return h.hexdigest()[:12]
