# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The universal 27 by disposition: derive, lookup, wiring, na and transport_na."""

from __future__ import annotations

from .probes import PROBES

# ── derive: computed from the run's own telemetry, ledger or receipt ───────────────────
DERIVE = {
    'speed': {
        'grade': 'measured',
        'unit': 's',
        'from': "wall seconds for ONE 81-frame clip at the row's own resolution, model load INCLUDED, "
        'median of the 3 base-scene seeds. The trial records load and sample separately.',
    },
    'throughput': {
        'grade': 'measured',
        'unit': 'clips/h',
        'from': '3600 / speed, taken from the SAME three renders with the model already resident (the '
        'second and third seed), because that is the state a batch runs in.',
    },
    'vram': {
        'grade': 'measured',
        'unit': 'GiB',
        'from': 'peak of nvidia-smi --query-gpu=memory.used sampled at 1 Hz for the duration of the base '
        'render, minus the idle reading taken immediately before. Highest of the three seeds.',
    },
    'ram': {
        'grade': 'measured',
        'unit': 'GiB',
        'from': 'peak RSS of the worker process tree (psutil, 1 Hz) over the base render. Highest of three.',
    },
    'disk': {
        'grade': 'measured',
        'unit': 'MiB',
        'from': 'bytes of every file the row wrote for one clip — the clip, its frames if kept, the manifest, '
        'the preview. Measured, not the clip size alone.',
    },
    'cost': {
        'grade': 'lowest of inputs',
        'unit': 'EUR',
        'from': 'speed x the tariff in LOOKUP["tariff"]. Grade is the LOWEST of speed (measured) and the '
        'tariff (vendor), so a local row reads receipt and an API row reads vendor.',
    },
    'first_take': {
        'grade': 'measured',
        'from': 'the FIRST repeat of the base-scene probe at seed 11, and nothing else. Never the best '
        'of three [[feedback_first_take_not_retries]].',
    },
    'retries': {
        'grade': 'measured',
        'unit': 'count',
        'from': 'renders needed to reach one clip that passes the base key, counted from the run ledger for '
        'this sheet. 1 means the first take was usable.',
    },
    'silent_fail': {
        'grade': 'measured',
        'from': 'every trial in this sheet that produced a file but failed its checks, against how many '
        'of those the row itself flagged (a non-zero exit, a warning line, a QC verdict). All '
        'flagged = yes; some = partial; a wrong clip returned as success = no.',
    },
    'batch': {
        'grade': 'measured',
        'unit': 'count',
        'from': 'clips queued in ONE call without touching the row again, read from the comfy queue depth or '
        'the service signature. 1 means one at a time.',
    },
    'receipts': {
        'grade': 'receipt',
        'from': 'the trial file itself: workflow (or module and function), model hash, seed, shift, steps, '
        "cfg, sampler, resolution, fps, the input still's sha256, the prompt and the negative, "
        'verbatim. A row that cannot produce all of those from its own output is partial, and the '
        'missing field is named.',
    },
    'pd_portable': {
        'grade': 'measured',
        'from': 'the SAME base prompt and key on the sibling rows of this step (Wan 2.1 next to Wan 2.2, '
        'i2v next to t2v): the share of siblings that pass the key the first row passed. This is '
        'read across the sheet, not from a new render.',
    },
    'pd_recorded': {
        'grade': 'receipt',
        'from': "whether the prompt, the negative and the motion phrase come back out of the row's own "
        'output manifest byte-identical to what went in. Derived from the same receipt as '
        '`receipts`, reported separately because a row can record its seed and lose its prompt.',
    },
    'pd_retries': {
        'grade': 'measured',
        'unit': 'count',
        'from': 'prompt REWRITES (not re-rolls) needed to reach a clip that passes the base key, counted '
        'from the ledger. Distinct from `retries`, which counts re-rolls of one prompt.',
    },
}

# ── lookup: a documented fact with a pinned source ─────────────────────────────────────
LOOKUP = {
    'licence': {
        'grade': 'vendor',
        'requires': 'the model card or repository LICENSE at a pinned revision, quoted',
        'note': "Wan 2.1/2.2 ship Apache-2.0 weights; a row that wraps someone else's checkpoint inherits "
        "that checkpoint's terms and the trial cites the file it read.",
    },
    'weights_pinned': {
        'grade': 'receipt',
        'requires': 'the sha256 of every weight file the row loaded, from '
        'data/runtime/model_hash_cache.json, plus the revision string',
        'note': 'not "is there a licence" but "do we know exactly which bytes we ran"',
    },
    'outputs_clause': {
        'grade': 'vendor',
        'requires': 'the clause about ownership of generated output, quoted verbatim from the pinned licence text',
    },
    'attribution': {'grade': 'vendor', 'requires': 'the attribution clause, quoted, plus where we satisfy it'},
    'train_data': {
        'grade': 'vendor',
        'requires': "the model card's own statement about training data, quoted, and "
        '"not stated" written where it says nothing',
    },
    'ai_training': {
        'grade': 'vendor',
        'requires': "the clause governing training on this model's OUTPUT, quoted. "
        'A silent licence is recorded as "not stated", never as yes.',
    },
    'wired': {
        'grade': 'receipt',
        'requires': 'the production call site (file and line) plus a run in '
        'data/runtime/run_ledger.sqlite3 from the last 90 days',
        'note': 'a row with a call site but no run in 90 days is partial; a row with neither is no. This is a '
        'receipt, not a reading of intent.',
    },
    'tariff': {
        'grade': 'vendor',
        'feeds_derive': 'cost',
        'requires': 'EUR per GPU-hour for this box (electricity plus amortisation, from the house figure) for '
        'a local row, or the vendor price list at a pinned date for an API row',
        'note': 'not a sheet column; it is the second input to DERIVE["cost"]',
    },
}

# ── wiring: read off the code path, never run, and visibly `assumed` ──────────────────
WIRING = {
    'isolation': {
        'grade': 'assumed',
        'read': 'whether the row runs in a CHILD process or a subprocess of the GUI. Every comfy row does '
        '(the workflow is queued over HTTP and never imported into the Flask process); a service '
        'row imported at module level does not. Read from the call site, marked assumed, because '
        'proving it would mean crashing the GUI on purpose.',
    },
    'gated': {
        'grade': 'assumed',
        'read': "whether the row's output passes a qc_contract gate before it can ship — the contract name and "
        'its mode, read from qc_contract.py. A row whose gate is advisory is assumed-partial, not yes.',
    },
    'previewable': {
        'grade': 'assumed',
        'read': 'whether clip LENGTH is a single node input (or function argument) that can be set to 21 '
        'frames without changing anything else in the workflow. Read from the workflow JSON or '
        'the signature. It is wiring rather than a probe because a 21-frame draft at the same '
        'seed is not evidence about the 81-frame clip — it only shows the call is possible.',
    },
}

# ── na: not applicable, with the reason on the sheet ──────────────────────────────────
NA = {
    'concurrency': 'One 24 GB card and one comfy queue: a second render waits, it does not run. Parallel jobs that '
    'pay off is a question about a farm we do not have, and answering it with a number measured on '
    'one card would be a fiction.',
    'pd_asks_back': 'The transport returns pixels, not words. There is no reply channel for a renderer to say it is '
    'unsure in, so there is nothing to measure. A judging row asked a question CAN abstain, and that '
    'is pd_abstain, which this bank does probe.',
}


# ── transport_na: the columns a row cannot answer because of HOW it is driven ──────────
PROMPT_COLS = sorted(
    {c for p in PROBES for c in p['feeds'] if c.startswith('pd_')}
    | {k for k in DERIVE if k.startswith('pd_')}
    | {k for k in NA if k.startswith('pd_')}
)
assert len(PROMPT_COLS) == 64, len(PROMPT_COLS)

_NO_PROMPT = (
    'This row takes no text prompt at all — it is driven by a script and a file — so every prompt question '
    'is about an input it does not have. Written na, not no: nothing was measured and nothing is claimed.'
)
_JUDGE_ONLY = (
    'This row produces pixels, not a verdict; there is no answer to reword, lead or batch. The column is '
    'for a judging row on the same sheet.'
)
_RENDER_ONLY = (
    'This row is asked a question and answers in words; it renders nothing, so there is no clip to read '
    'this column off.'
)

TRANSPORT_NA = {
    'blender': dict(
        {c: _NO_PROMPT for c in PROMPT_COLS},
        **{
            'cap_prompt_terms': _NO_PROMPT,
            'vram': 'The rig scripts run on the CPU in headless Blender; the card is never touched, so a '
            'peak VRAM figure would be the idle reading of whatever else is resident.',
        },
    ),
    'ffmpeg': dict(
        {c: _NO_PROMPT for c in PROMPT_COLS},
        **{
            'cap_prompt_terms': _NO_PROMPT,
            'vram': "A filter graph on the CPU holds no VRAM; the reading would be somebody else's.",
            'degrades': 'A CPU filter graph does not compete for the card, so there is nothing to degrade '
            'when the GPU is busy. Its own CPU contention is a different question and is not '
            'this column.',
        },
    ),
    'library': {c: _NO_PROMPT for c in PROMPT_COLS},
    'vlm_ollama': {
        c: _RENDER_ONLY
        for c in [
            c
            for c in PROMPT_COLS
            if c.startswith(
                (
                    'pd_clarity',
                    'pd_terse',
                    'pd_detail',
                    'pd_sweet',
                    'pd_motion',
                    'pd_camera',
                    'pd_prompt_vs',
                    'pd_small',
                    'pd_fix',
                    'pd_seed',
                    'pd_weight',
                    'pd_negative_len',
                    'pd_bleed',
                    'pd_leak',
                    'pd_meta',
                    'pd_unstated',
                    'pd_dimension',
                    'pd_spatial',
                    'pd_count_words',
                    'pd_action',
                    'pd_attrs',
                    'pd_unique',
                )
            )
        ]
    },
    'vlm_inspector': {
        c: _RENDER_ONLY
        for c in [
            c
            for c in PROMPT_COLS
            if c.startswith(
                (
                    'pd_clarity',
                    'pd_terse',
                    'pd_detail',
                    'pd_sweet',
                    'pd_motion',
                    'pd_camera',
                    'pd_prompt_vs',
                    'pd_small',
                    'pd_fix',
                    'pd_seed',
                    'pd_weight',
                    'pd_negative_len',
                    'pd_bleed',
                    'pd_leak',
                    'pd_meta',
                    'pd_unstated',
                    'pd_dimension',
                    'pd_spatial',
                    'pd_count_words',
                    'pd_action',
                    'pd_attrs',
                    'pd_unique',
                )
            )
        ]
    },
    'comfy': {
        'pd_question_wording': _JUDGE_ONLY,
        'pd_leading': _JUDGE_ONLY,
        'pd_yes_bias': _JUDGE_ONLY,
        'pd_rubric_needed': _JUDGE_ONLY,
        'pd_abstain': _JUDGE_ONLY,
        'pd_batched_questions': _JUDGE_ONLY,
    },
    'service': {
        'pd_question_wording': _JUDGE_ONLY,
        'pd_leading': _JUDGE_ONLY,
        'pd_yes_bias': _JUDGE_ONLY,
        'pd_rubric_needed': _JUDGE_ONLY,
        'pd_abstain': _JUDGE_ONLY,
        'pd_batched_questions': _JUDGE_ONLY,
    },
}

TRANSPORT_NA_NOTE = (
    'A service or comfy row that DOES return a verdict (a QC gate, a judge, a workflow ending in a '
    'classifier) drops the six verdict exemptions in its own step module. The bank cannot tell a '
    'rendering service from a judging one, so it exempts both, and the step module puts back what '
    'its row can really answer.'
)
