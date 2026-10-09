# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from capability_tests.text_shared.banks import COND_NOTE, EXTRACT_KEY, EXTRACT_TASK, FILLER_RULE, KEYS, PASSAGE, SYSTEM
from capability_tests.text_shared.probes import PROBES, _probe


# ── dispositions that are not probes ──────────────────────────────────────────────────
DERIVE = {
    'speed': {
        'from': 'mean wall-clock seconds per call over every probe trial of this row',
        'grade': 'measured',
        'unit': 's',
    },
    'throughput': {'from': '3600 / speed, single stream, warm model', 'grade': 'measured', 'unit': 'count'},
    'vram': {
        'from': "peak nvidia-smi memory.used sampled at 1 Hz during the row's trials, minus the idle baseline; ollama rows only",
        'grade': 'measured',
        'unit': 'gb',
    },
    'ram': {
        'from': "peak RSS of the ollama server process during the row's trials; ollama rows only",
        'grade': 'measured',
        'unit': 'gb',
    },
    'disk': {
        'from': '`ollama show --modelfile` size of the weights on this box; ollama rows only',
        'grade': 'measured',
        'unit': 'mb',
    },
    'cost': {
        'from': 'API rows: measured input/output tokens × the vendor price table pinned in LOOKUP["price_table"] (grade vendor). Ollama rows: measured wall-clock × nvidia-smi power draw × the tariff in LOOKUP["tariff"] (grade = the tariff\'s grade). CLI rows: the CLI\'s own cost figure from the audit row (receipt).',
        'grade': 'lowest of inputs',
        'unit': 'eur',
    },
    'concurrency': {
        'from': 'the 18 bank questions run at 1, 2, 4 and 8 parallel streams; the column = the stream count after which items/hour stops growing by ≥ 10 %',
        'grade': 'measured',
        'unit': 'count',
    },
    'first_take': {'from': 'pass rate of the FIRST repeat over every probe trial of this row', 'grade': 'measured'},
    'retries': {
        'from': 'mean number of repeats until the first passing one, over trials that eventually passed',
        'grade': 'measured',
        'unit': 'count',
    },
    'silent_fail': {
        'from': 'over every failed trial: share whose failure a format check (json_valid / empty / starts_clean) would have caught; yes ≥ 0.9, partial ≥ 0.5',
        'grade': 'measured',
    },
    'batch': {
        'from': 'first-call seconds vs mean warm-call seconds for this row; yes when the warm cost is paid once per run (first ≥ 1.5 × warm) or the transport has a batch endpoint (LOOKUP)',
        'grade': 'measured',
    },
    'receipts': {
        'from': "after the run, data/runtime/llm_audit holds one row per trial with prompt AND response for this row's transport",
        'grade': 'receipt',
    },
    'pd_recorded': {
        'from': 'same ledger read as `receipts`: the exact prompt text is recoverable for every trial',
        'grade': 'receipt',
    },
    'pd_retries': {
        'from': 'over the creative probes: prompt REWRITES the operator needed to reach a usable take, counted from the ladder step that first passed (0 when step 1 passed)',
        'grade': 'measured',
        'unit': 'count',
    },
    'pd_portable': {
        'from': 'the clarity-ladder step 5 prompt run unchanged on every OTHER row of this sheet; yes when ≥ 80 % of sibling rows pass it',
        'grade': 'measured',
    },
    'tok_in': {
        'from': "mean prompt tokens per creative trial (from the transport's usage field)",
        'grade': 'measured',
        'unit': 'tokens',
    },
    'tok_out': {'from': 'mean completion tokens per creative trial', 'grade': 'measured', 'unit': 'tokens'},
}

LOOKUP = {
    'licence': {
        'ask': 'May the output be sold? Name the licence and the clause.',
        'requires': ['source_url', 'retrieved_on'],
        'grade': 'vendor',
    },
    'weights_pinned': {
        'ask': 'Is a revision recorded (ollama digest, API model id with date, registry row)?',
        'requires': ['revision'],
        'grade': 'receipt',
    },
    'outputs_clause': {
        'ask': 'Does the licence or ToS claim anything over the outputs?',
        'requires': ['source_url', 'clause_quote'],
        'grade': 'vendor',
    },
    'attribution': {
        'ask': 'Must we credit the model in the deliverable?',
        'requires': ['source_url', 'clause_quote'],
        'grade': 'vendor',
    },
    'train_data': {'ask': 'Is the training data provenance published?', 'requires': ['source_url'], 'grade': 'vendor'},
    'ai_training': {
        'ask': 'May we train on its output? Quote the clause.',
        'requires': ['source_url', 'clause_quote'],
        'grade': 'vendor',
    },
    'wired': {
        'ask': "A production call site (the row's `where`) AND an llm_audit row from production in the last 30 days",
        'requires': ['call_site', 'audit_row_id'],
        'grade': 'receipt',
    },
    'previewable': {
        'ask': 'Can we see partial output before the call completes (streaming) or a cheap draft before the full run?',
        'requires': ['transport'],
        'grade': 'vendor',
    },
    'price_table': {
        'ask': 'EUR per million input and output tokens for every API row, with the vendor page and date',
        'requires': ['source_url', 'retrieved_on'],
        'grade': 'vendor',
        'feeds_derive': 'cost',
    },
    'tariff': {
        'ask': 'EUR per kWh from the electricity contract (receipt) — or leave it assumed at 0.30 and let `cost` show as assumed',
        'requires': ['source'],
        'grade': 'receipt',
        'feeds_derive': 'cost',
    },
}

WIRING = {
    'isolation': {
        'read': 'the transport: ollama is a separate server process; anthropic_api is an HTTP client in-process; claude_cli is a subprocess. None loads torch into the GUI process.',
        'grade': 'assumed',
    },
    'gated': {
        'read': "is there an automatic check between this step's output and delivery? Name the code path per row (schema check, typography gate, era gate) or write no.",
        'grade': 'assumed',
    },
}

# Probes that stand in for universal columns
PROBES += [
    _probe(
        'u_deterministic',
        'Same input, same output',
        ['deterministic'],
        EXTRACT_TASK,
        [{'check': 'identical_runs'}],
        cond={'temperature': 0.0, 'seed': 11, 'max_tokens': 400, 'repeats': 3},
        state_note='at temperature 0 and a fixed seed where the transport has them; CLI rows run at default and the note says so',
    ),
    _probe(
        'u_failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        EXTRACT_TASK,
        [
            {
                'check': 'operator',
                'blind': False,
                'question': 'derived: the harness call returned within the timeout with a typed error and no exception escaped to the runner',
            }
        ],
        cond={'temperature': 0.0, 'max_tokens': 400, 'repeats': 1},
        transport_override="the row's transport pointed at a closed port (127.0.0.1:1) with a 20 s timeout",
        state_note="measures the WRAPPER (llm_audit.ollama_generate / SubscriptionClient / the SDK) on this row's path, not the model",
    ),
    _probe(
        'u_degrades',
        'Degrades when the GPU is busy',
        ['degrades'],
        'BANK',
        [{'check': 'equals_key', 'key': 'KEYS'}],
        load='a fixed torch matmul loop on 8 GB of the same card (capability_tests/fixtures/gpu_load.py) for the duration; ollama rows only',
        state_note='yes when accuracy is unchanged and speed ≤ 3 × idle; partial when accuracy holds but speed > 3 ×; no when calls fail',
    ),
    _probe(
        'u_offline',
        'Runs on this box',
        ['offline'],
        'BANK',
        [{'check': 'equals_key', 'key': 'KEYS'}],
        sandbox='unshare -n (no network namespace) around the harness, for EVERY row — an API or CLI row fails it and that failure is the measured answer',
        state_note='yes when the bank passes with the network off; no when the transport cannot be reached (the honest answer for an API row)',
    ),
]

NA = {
    'resumable': 'a single model call is atomic; there is nothing to stop and continue (llm_agents overrides this with a real resume probe)',
    'pd_weight_range': 'text models have no numeric prompt weighting; emphasis is wording, which the damage band already measures',
}

# Columns a row cannot answer because of how it is DRIVEN — written `na` with the reason.
TRANSPORT_NA = {
    'claude_cli': {
        'temp': 'the claude_cli path drops temperature (subscription_llm); the lever does not exist on this row',
        'pd_seed_vs_prompt': 'the CLI exposes no seed',
        'pd_reasoning_budget': 'the CLI exposes no thinking budget',
        'vram': 'runs off-box',
        'ram': 'runs off-box',
        'disk': 'no weights on this box',
        'degrades': 'not on our GPU',
        'concurrency': "one login, sequential turns; parallelism is the Session Tree's business (llm_agents)",
    },
    'anthropic_api': {
        'pd_seed_vs_prompt': 'the Anthropic API exposes no seed',
        'vram': 'runs off-box',
        'ram': 'runs off-box',
        'disk': 'no weights on this box',
        'degrades': 'not on our GPU',
    },
    'github_models': {
        'pd_seed_vs_prompt': 'no seed on GitHub Models',
        'pd_reasoning_budget': 'no thinking control',
        'vram': 'runs off-box',
        'ram': 'runs off-box',
        'disk': 'no weights on this box',
        'degrades': 'not on our GPU',
    },
    'ollama': {},
    'builtin': {},
    'pipeline': {},
}

SHARED = {
    'version': '2026-09-28.1',
    'system': SYSTEM,
    'passage': PASSAGE,
    'keys': KEYS,
    'extract_key': EXTRACT_KEY,
    'filler_rule': FILLER_RULE,
    'conditions_note': COND_NOTE,
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': WIRING,
    'na': NA,
    'transport_na': TRANSPORT_NA,
    'operator_protocol': [
        'Every operator check is BLIND: the runner writes the outputs to a folder named by trial id with the row id replaced by a random letter, shuffled, and the operator answers the written question per item. The letter→row map is revealed only after all answers are saved.',
        'The operator answers yes/no. A "maybe" is a no — the house standard is first take, not a charitable reading.',
        'The operator never sees the model name, the seed, or which ladder step produced a text until the answers are in.',
    ],
}
