# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JUDGE
from .subjects import FIX, SEE_Q, SUBJ_DIR
from .probes_subjects import PROBES, _subject_fixture

# ── Universal: derived from the run's own telemetry ─────────────────────────
# Nothing here asks the model anything new. Every entry says which measurement it reads and
# what makes it a yes, so two rows are never compared on two different arithmetics.
DERIVE = {
    'speed': {
        'from': 'median wall-clock seconds per TRIAL over every probe in this bank, model load excluded '
        '(the load is timed separately and reported in the trial, so a resident model is not '
        'flattered against one that loads per call)',
        'grade': 'measured',
        'unit': 's',
    },
    'throughput': {
        'from': '3600 / `speed`, times the concurrency that actually paid off; a row whose GPU is held '
        'for the whole call is capped at 1 stream',
        'grade': 'measured',
        'unit': 'count',
    },
    'vram': {
        'from': 'peak nvidia-smi used-MiB during the bank, minus the idle reading taken immediately before, '
        'sampled at 1 Hz; 0 for an off-box transport',
        'grade': 'measured',
        'unit': 'gb',
    },
    'ram': {
        'from': 'peak RSS of the runner process and its children during the bank, minus the reading before the '
        'first call',
        'grade': 'measured',
        'unit': 'gb',
    },
    'disk': {
        'from': 'bytes written under data/runtime by the bank, divided by the number of trials; a judge writes '
        'its transcript and nothing else, so this is usually a fraction of a megabyte',
        'grade': 'measured',
        'unit': 'mb',
    },
    'cost': {
        'from': "tokens in and out per trial times the row's entry in the LOOKUP price table; a local row is "
        'the GPU minutes it held times the house electricity+depreciation rate in the same table',
        'grade': 'lowest of inputs',
        'unit': 'eur',
    },
    'concurrency': {
        'from': 'the bank re-run at 1, 2 and 4 parallel calls; the column is the highest setting whose '
        'throughput is at least 1.5x the setting below it AND whose accuracy on the Sees band '
        'is unchanged. A setting that goes faster by answering worse does not count.',
        'grade': 'measured',
        'unit': 'count',
    },
    'first_take': {
        'from': 'the FIRST repeat of every probe, scored on its own; the column is the share of columns '
        'that would have been yes on repeat 1 alone. Retries are not what a gate gets.',
        'grade': 'measured',
    },
    'deterministic': {
        'from': 'byte-identical answers across the three repeats of every probe at the fixed seed; the '
        'column is the share of probes where all repeats agreed. A transport with no seed '
        '(claude_cli) is measured the same way and is simply what it is.',
        'grade': 'measured',
    },
    'retries': {
        'from': 'over the whole bank: calls that returned nothing usable and had to be reissued, per usable '
        'answer. Transport failures count here; wrong answers do not — a wrong answer is a no, not '
        'a retry.',
        'grade': 'measured',
        'unit': 'count',
    },
    'silent_fail': {
        'from': 'trials where the transport returned 200 with an empty or unparseable body and no error; '
        'yes when that count is 0 over the bank',
        'grade': 'measured',
    },
    'batch': {
        'from': 'the cap_images ladder: yes when more than one image per call was accepted AND the per-image '
        'cost fell, or the transport has a documented batch endpoint (LOOKUP)',
        'grade': 'measured',
    },
    'receipts': {
        'from': 'the run ledger: every trial in this bank has its prompt, its image path, its raw answer '
        'and its seed recoverable by trial id. Yes only when all four are there for all trials.',
        'grade': 'receipt',
    },
    'pd_recorded': {
        'from': 'the same ledger read as `receipts`, narrowed to the question text: the exact wording '
        'that produced a verdict is recoverable for every trial. A judge whose verdict cannot '
        'be traced to its wording cannot be audited after the fact.',
        'grade': 'receipt',
    },
    'pd_retries': {
        'from': 'the clarity ladder: the rung index of the first rung that passed, minus one — the number '
        'of question rewrites an operator needed. 0 when rung 1 passed.',
        'grade': 'measured',
        'unit': 'count',
    },
    'pd_portable': {
        'from': 'the clarity-ladder rung that first passed for THIS row, run unchanged on every other '
        'row of the sheet; yes when at least 80 % of the sibling rows also pass it',
        'grade': 'measured',
    },
}


# ── Universal: looked up, with the source pinned ────────────────────────────
LOOKUP = {
    'licence': {
        'ask': 'Does the model licence allow commercial use of the model and of what it outputs, without a '
        'field-of-use restriction?',
        'requires': ['source_url', 'retrieved_on', 'licence_name'],
        'known': {
            'moondream2': 'Apache-2.0',
            'qwen3.5-vl': 'Apache-2.0',
            'qwen3.6-vl': 'Apache-2.0',
            'Qwen3-VL-8B': 'Apache-2.0',
            'Qwen3-VL-32B': 'Apache-2.0',
            'note': 'a name in this table still needs its source_url and retrieved_on recorded on the '
            'row — the table is a starting point, not the receipt',
        },
        'grade': 'vendor',
    },
    'weights_pinned': {
        'ask': 'Is the exact weight file we run identified by digest, and is that digest recorded on the row?',
        'requires': ['sha256', 'source_url', 'retrieved_on'],
        'grade': 'receipt',
        'note': 'receipt, not vendor: the digest is ours, taken from the file on this box. '
        'data/runtime/model_hash_cache.json is where it lives.',
    },
    'outputs_clause': {
        'ask': "Does the licence claim any right over the model's outputs, or restrict what we may "
        'do with a verdict it produced?',
        'requires': ['source_url', 'retrieved_on', 'clause_quote'],
        'grade': 'vendor',
        'note': 'the clause is QUOTED on the row, not summarised, because this is the answer a '
        'lawyer will want to read for themselves',
    },
    'attribution': {
        'ask': 'Does the licence require us to name the model where its verdicts are used?',
        'requires': ['source_url', 'retrieved_on', 'clause_quote'],
        'grade': 'vendor',
    },
    'train_data': {
        'ask': 'Is the training corpus documented well enough to say what the model has and has not '
        'seen — and in particular whether it has seen the kind of picture we judge?',
        'requires': ['source_url', 'retrieved_on'],
        'grade': 'vendor',
        'note': 'an undocumented corpus is written no, not unknown. "We were not told" is an answer.',
    },
    'ai_training': {
        'ask': "May we train a model of our own on this model's outputs?",
        'requires': ['source_url', 'retrieved_on', 'clause_quote'],
        'grade': 'vendor',
    },
    'wired': {
        'ask': 'Is this row actually called by a production code path today, and which file calls it?',
        'requires': ['caller_file', 'caller_line', 'retrieved_on'],
        'grade': 'receipt',
        'note': 'a row nobody calls is written no however well it scores; that is the point of the column',
    },
    'previewable': {
        'ask': 'Can a verdict be seen before it is acted on — a streamed answer, or a queue an operator '
        'reads before the gate fires?',
        'requires': ['transport', 'caller_file'],
        'grade': 'vendor',
    },
    'price_table': {
        'feeds_derive': ['cost'],
        'ask': 'Price per million input and output tokens for an API row; the house euro-per-GPU-minute '
        'rate for a local one.',
        'requires': ['source_url', 'retrieved_on'],
        'grade': 'vendor',
    },
}


# ── Universal: read off the code path, never run ────────────────────────────
WIRING = {
    'isolation': {
        'from': (
            'read of the caller: a judge that runs in the GUI process can take the dashboard down '
            'with it. Yes only when the row is called in a child process or over HTTP to a separate '
            'service (vlm_ollama and vlm_inspector both are); no when a module is imported into the '
            'Flask process and called in-band.'
        ),
        'grade': 'assumed',
        'note': 'assumed, and it says so on the sheet: nobody crashed a GUI to find out.',
    },
    'gated': {
        'from': (
            'read of the caller: is the verdict checked by something before it ships — a threshold, a '
            'second judge, an approval queue — or does it act on its own? A judge that IS the gate is '
            'written no here, which is the honest answer and not a criticism.'
        ),
        'grade': 'assumed',
    },
}


# ── Universal: the three that are probed ────────────────────────────────────
PROBES.append(
    {
        'id': 'u_failsafe',
        'title': 'Fails without breaking the caller',
        'feeds': ['failsafe'],
        'inputs': {
            'task': SEE_Q.format(label='a barrel'),
            'image': [
                FIX + '/broken/truncated.png',
                FIX + '/broken/zero_bytes.png',
                FIX + '/broken/not_an_image.txt',
                FIX + '/broken/absent.png',
            ],
            'fixture': {
                'path': FIX + '/broken/',
                'generated': (
                    'four broken inputs made from the base quay picture with shell tools, no binary authored '
                    'by hand: truncated.png = the first 4096 bytes of base_quay.png; zero_bytes.png = an '
                    'empty file; not_an_image.txt = the ASCII string "this is not an image"; absent.png = a '
                    'path that is deliberately never created'
                ),
                'key': {'expected': 'a raised, catchable error or a structured error answer — never a verdict'},
                'verified': True,
                'blocks': [],
                'how_to_verify': 'the four inputs are made by the recipe above and are self-evidently what they claim; '
                'no operator judgement is needed, so this fixture is verified on creation.',
            },
        },
        'conditions': dict(COND_JUDGE, repeats=2, timeout_s=120),
        'checks': [
            {
                'check': 'regex_absent',
                'pattern': r'^\s*(yes|no)\b',
                'note': 'answering yes or no about a file that is not a picture is the failure: the caller cannot tell '
                'that verdict from a real one',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Shown the runner log for one broken input: did the caller get an error it could act on, and '
                'did the runner stay up? Yes or no. A "maybe" is a no.',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'all four inputs must fail cleanly; three of four is partial. A hang that hits the timeout is a no.',
    }
)

PROBES.append(
    {
        'id': 'u_degrades',
        'title': 'Degrades when the GPU is busy',
        'feeds': ['degrades'],
        'inputs': {
            'task': SEE_Q.format(label='a barrel'),
            'image': [SUBJ_DIR + '/container_barrel_pos.png', SUBJ_DIR + '/container_barrel_neg.png'],
            'fixture': dict(_subject_fixture('container_barrel'), blocks=['degrades']),
            'load': (
                'the same pair judged twice: once on an idle GPU, once while the house load generator holds 80 % '
                'of VRAM and a steady compute load. The load generator is the one the bench already uses; no '
                'production job is displaced to run this.'
            ),
        },
        'conditions': dict(COND_JUDGE, repeats=3, note='two conditions, idle and loaded, same seed and picture'),
        'checks': [
            {
                'check': 'answer_agrees',
                'to': 'the idle condition',
                'note': 'the VERDICT must not change under load; slower is acceptable, different is not',
            },
            {'check': 'accuracy_delta', 'with': 'idle', 'without': 'loaded', 'min': -0.05},
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'yes when the answers are identical and only the clock moved. A row that returns a different '
            'verdict under load is written no however small the drop, because a gate cannot be allowed to '
            'depend on what else is running.'
        ),
    }
)

PROBES.append(
    {
        'id': 'u_offline',
        'title': 'Runs on this box',
        'feeds': ['offline'],
        'inputs': {
            'task': SEE_Q.format(label='a barrel'),
            'image': [SUBJ_DIR + '/container_barrel_pos.png', SUBJ_DIR + '/container_barrel_neg.png'],
            'fixture': dict(_subject_fixture('container_barrel'), blocks=['offline']),
            'command': 'the same trial run with outbound network denied at the namespace level (the house offline '
            'harness), weights already on disk',
        },
        'conditions': dict(COND_JUDGE, repeats=2, network='denied'),
        'checks': [
            {
                'check': 'answer_equals_fixture_key',
                'note': 'the row must give the SAME right answers with the network cut; a row that merely does not crash '
                'has not passed',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'an API row is written no here and that is not a failure — it is the fact an operator needs when '
            'the line goes down. A local row that needs the network to fetch weights on first call is also '
            'no, with the note saying so.'
        ),
    }
)


# ── Not applicable, with the reason ─────────────────────────────────────────
NA = {
    'resumable': (
        'a judge call is atomic: one picture in, one verdict out, in a couple of seconds. There is no '
        'partial state to stop and continue, and a ladder that is interrupted is simply rerun from the '
        'rung that failed. A step whose judge really does stream over a long video overrides this with a '
        'resume probe of its own.'
    ),
    'pd_weight_range': (
        'a judge takes no numeric prompt weighting — there is no (term:1.4) syntax in a question and '
        'no CFG on a verdict. Emphasis here is wording, which the damage band already measures term '
        'by term. Writing a number in this column would be inventing one.'
    ),
}
