# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The question constructor, the universal spine and the empty DOMAIN registry."""

from __future__ import annotations


def q(cid, label, hint='', unit='ratio', hb=True, group=''):
    return {'id': cid, 'label': label, 'hint': hint, 'unit': unit, 'higher_better': hb, 'group': group}


# ── the shared spine ─────────────────────────────────────────────────────────
# Appended to every step, after its domain questions, and skipped where the step already
# defines the same id (the domain wording wins, because it is more specific).
UNIVERSAL = [
    # Licence & rights — in this house a licence answer IS a capability answer: a model we
    # may not ship commercially cannot do the job however good the output is.
    q('licence', 'Licence allows commercial use', 'may the output be sold', 'text', True, 'Licence & rights'),
    q(
        'weights_pinned',
        'Weights licence pinned',
        'a revision is recorded, not just a name',
        'text',
        True,
        'Licence & rights',
    ),
    q(
        'outputs_clause',
        'No claim over the outputs',
        'the licence does not reach our renders',
        'text',
        True,
        'Licence & rights',
    ),
    q('attribution', 'Attribution required', 'must we credit it in the deliverable', 'text', False, 'Licence & rights'),
    q(
        'train_data',
        'Training data provenance known',
        'what it learned from, and under what terms',
        'text',
        True,
        'Licence & rights',
    ),
    q(
        'ai_training',
        'May we train on its output',
        'some licences forbid exactly this',
        'text',
        True,
        'Licence & rights',
    ),
    # Cost & speed
    q('speed', 'Time per unit of work', 'wall clock for one item', 's', False, 'Cost & speed'),
    q('throughput', 'Items per hour', 'sustained, not a single best run', 'count', True, 'Cost & speed'),
    q('vram', 'Peak VRAM', 'against a 24 GB card', 'gb', False, 'Cost & speed'),
    q('ram', 'Peak system RAM', '', 'gb', False, 'Cost & speed'),
    q('disk', 'Disk per item', 'what it leaves behind', 'mb', False, 'Cost & speed'),
    q('cost', 'Cost per item', 'money, not tokens', 'eur', False, 'Cost & speed'),
    q('concurrency', 'Parallel jobs that pay off', 'where adding another stops helping', 'count', True, 'Cost & speed'),
    # Reliability
    q(
        'first_take',
        'Usable on the first take',
        'the house standard is first take, not retries',
        '',
        True,
        'Reliability',
    ),
    q('deterministic', 'Same input, same output', 'can a result be reproduced at all', '', True, 'Reliability'),
    q('retries', 'Retries to reach a usable item', '', 'count', False, 'Reliability'),
    q('failsafe', 'Fails without breaking the caller', 'returns nothing rather than raising', '', True, 'Reliability'),
    q('isolation', 'Cannot destabilise the GUI', 'own venv, subprocess, no torch in-process', '', True, 'Reliability'),
    q('degrades', 'Degrades when the GPU is busy', 'falls back instead of failing', '', True, 'Reliability'),
    q('silent_fail', 'Cannot fail silently', 'a wrong result is detectable from the output', '', True, 'Reliability'),
    # Operability
    q('offline', 'Runs on this box', 'no network call, no third party', '', True, 'Operability'),
    q('batch', 'Batch interface', 'one startup cost for many items', '', True, 'Operability'),
    q('resumable', 'Resumable or interruptible', 'a long job can be stopped and continued', '', True, 'Operability'),
    q(
        'previewable',
        'Previewable before commit',
        'we can look before paying for the full run',
        '',
        True,
        'Operability',
    ),
    q(
        'gated',
        'Output is gated before it ships',
        'an automatic check stands between it and delivery',
        '',
        True,
        'Operability',
    ),
    q('receipts', 'Writes a receipt', 'what ran, with what settings, is recoverable', '', True, 'Operability'),
    q('wired', 'Actually wired into production', 'installed is not the same as used', '', True, 'Operability'),
]

# Old column ids that are the universal question under a different name. The migration
# renames the stored cell so its evidence survives the rename.
ALIASES = {
    'llm_script': {'latency': 'speed'},
    'llm_prompt': {'latency': 'speed'},
    'llm_agents': {'latency': 'speed'},
    'llm_research': {'latency': 'speed'},
    'stt': {'latency': 'speed'},
    'diarization': {'latency': 'speed'},
    'sfx_process': {'preview': 'previewable'},
}

DOMAIN = {}
