# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared.facts — derive, lookup, wiring, na, transport_na and the SHARED export."""

from __future__ import annotations

from capability_tests.image_shared.conditions import (
    COLOUR_BANDS,
    COND_NOTE,
    COND_RENDER,
    NEGATIVE,
    NEGATIVE_NOTE,
    PROMPT_NOTE,
    SUBJECT_FIXTURES,
)
from capability_tests.image_shared.subjects import SUBJECTS
from capability_tests.image_shared.probes import (
    PD_BASE,
    PD_CHECKS,
    PD_KEY_NOTE,
    PROBES,
    SUBJECT_CHECKS,
    SUBJECT_QUESTION,
    SUBJECT_STATE_RULE,
)
from capability_tests.image_shared.prompt_ladders import FILLER_CLAUSES, LANTERN_TAIL, LENGTH_RULE

# ── derive: read off the run own telemetry and ledger ───────────────────────────────────────
_NVIDIA = 'nvidia-smi sampled at 1 Hz for the whole probe by the runner, written into the trial'

DERIVE = {
    'speed': {
        'from': ['the wall clock around each queued render, model load included', 'the number of renders in the probe'],
        'rule': 'the MEDIAN seconds per render at 1024x1024 over every render in the subject '
        'band (132 subjects x 3 seeds = 396 renders), so one slow first load cannot set '
        'the number. The trial also keeps the first render separately, because the first '
        'is where the checkpoint load sits.',
        'grade': 'measured',
    },
    'throughput': {
        'from': ['speed', 'the wall clock across the whole subject band'],
        'rule': 'renders per hour = 3600 / speed, and beside it the MEASURED renders per hour '
        'across the whole band including every queue gap — the two differ and the '
        'second is what the house can schedule.',
        'grade': 'measured',
    },
    'vram': {
        'from': [_NVIDIA],
        'rule': 'the PEAK GPU memory in MiB over the probe, and the peak during the '
        'checkpoint load recorded separately, because the load peak is what decides '
        'whether two rows can share the card.',
        'grade': 'measured',
    },
    'ram': {
        'from': ['the resident set size of the comfy process sampled at 1 Hz by the runner'],
        'rule': 'the PEAK RSS in MiB over the probe.',
        'grade': 'measured',
    },
    'disk': {
        'from': [
            'the on-disk size of every file the row loads (checkpoint, VAE, CLIP, any '
            'ControlNet or IP-Adapter the workflow names)',
            'the bytes written by the probe',
        ],
        'rule': 'weights on disk in GiB, plus the output bytes per render. Both are read from '
        'the filesystem, not from a model card.',
        'grade': 'measured',
    },
    'cost': {
        'from': ['speed', 'vram', 'price_table', 'tariff'],
        'rule': 'GPU seconds per render x the card board power from price_table x the '
        'electricity tariff, in euro per 100 renders. A house GPU row has no API price, '
        'so the cost IS the electricity and the sheet says so.',
        'grade': 'receipt',
        'grade_note': 'takes the LOWEST grade of its inputs: speed is measured, the tariff is a '
        'receipt, so the cell is a receipt.',
    },
    'first_take': {
        'from': ['the FIRST repeat of every subject probe (seed 11), before any retry'],
        'rule': 'the share of the 132 subjects whose whole key passes on seed 11 alone. The '
        'house standard is the first take, not the best of three, so this number is '
        'read off repeat one and nothing else.',
        'grade': 'measured',
    },
    'retries': {
        'from': ['the run ledger entry for every queued render in the probe'],
        'rule': 'the share of renders that had to be queued more than once to get a frame, and '
        'the reason of each retry. A retry the runner did silently still counts.',
        'grade': 'measured',
    },
    'silent_fail': {
        'from': ['every render that returned a frame', 'the checks on that frame', 'the ComfyUI log for that render'],
        'rule': 'the share of renders that came back with no error at all and yet failed their '
        'mechanical key — the frames the house would have shipped. This is the number '
        'that matters most on the sheet and it is arithmetic, not a judgement.',
        'grade': 'measured',
    },
    'batch': {
        'from': [
            'the batch_size lever in the row own workflow JSON',
            'a two-setting comparison: batch_size 1 against batch_size 4 on U_PROMPT at '
            'seeds 11-14, same everything else',
        ],
        'rule': 'yes only if batch_size 4 returns four frames AND the seconds per frame fall. '
        'The lever is COMPARED, never read: the FLUX inert-lever work means a setting '
        'that exists in the JSON and changes nothing must read as no.',
        'grade': 'measured',
    },
    'receipts': {
        'from': ['the trial of every render'],
        'rule': 'yes only if the trial holds, for every render: the workflow JSON as queued, the '
        'seed, the resolved checkpoint filename and its hash, THE NAMES OF EVERY LOADED '
        'LORA, and the PNG own embedded metadata. The LoRA names are required because '
        'ComfyUI LoRAs were never actually applied stack-wide until convert_lora.py on '
        '2026-09-23, so a receipt that does not name the loaded LoRA cannot prove the '
        'render used one.',
        'grade': 'measured',
    },
    'pd_recorded': {
        'from': ['receipts', 'the trial of every probe in the four Prompt bands'],
        'rule': 'yes only if the exact prompt string, the exact negative, the seed, the size and '
        'the loaded LoRA names are in the trial for every prompt-band render, so a '
        'prompt finding can be reproduced by someone who was not there.',
        'grade': 'measured',
    },
    'pd_retries': {
        'from': ['retries', 'the prompt-band probes only'],
        'rule': 'how many re-queues the prompt bands needed to get a scoreable frame, separately '
        'from the subject band, because a long or damaged prompt is where a queue '
        'errors.',
        'grade': 'measured',
    },
    'pd_portable': {
        'from': ['the SAME prompt-band probes already run on the other rows of this step'],
        'rule': 'the share of the prompt-band cells that hold their state when the identical '
        'prompt is run on a different row of the same step. Computed across sheets, so '
        'it is empty until a second row has been run and the cell then says so rather '
        'than guessing.',
        'grade': 'measured',
    },
}

# ── lookup: a documented fact with a pinned source ─────────────────────────────────────────
LOOKUP = {
    'licence': {
        'requires': [
            'the licence file shipped WITH the weights the row actually loads (not the '
            'model card), quoted by filename and sha256',
            'the revision or download date of that file',
        ],
        'rule': 'the licence name, and whether it permits commercial use of the outputs, taken '
        'from the file beside the weights on this machine.',
        'grade': 'receipt',
    },
    'weights_pinned': {
        'requires': [
            'the resolved absolute path of every weight the workflow loads',
            'the sha256 of each, from data/runtime/sha256_cache.json or computed',
        ],
        'rule': 'yes only if every weight is a local file with a recorded hash — a workflow that '
        'names a hub repo without a revision is a no.',
        'grade': 'receipt',
    },
    'outputs_clause': {
        'requires': [
            'the clause in that same licence file that speaks about the generated '
            'images, quoted verbatim with its section number'
        ],
        'rule': 'what the licence says the house may do with the pictures. Quoted, not summarised.',
        'grade': 'vendor',
    },
    'attribution': {
        'requires': ['the attribution clause of the licence file, quoted verbatim'],
        'rule': 'whether a credit must be carried, and the exact wording if so.',
        'grade': 'vendor',
    },
    'train_data': {
        'requires': ['the publisher own statement about the training set, with its URL and the date it was read'],
        'rule': 'what the publisher says the model was trained on. A silence is recorded as '
        '"not stated", which is an answer.',
        'grade': 'vendor',
    },
    'ai_training': {
        'requires': [
            'the clause of the licence that speaks about using the outputs to train another model, quoted verbatim'
        ],
        'rule': 'whether the house may train on these pictures. This is the clause the sampled '
        'audio packs got wrong, so it is quoted and not inferred.',
        'grade': 'vendor',
    },
    'wired': {
        'requires': [
            'the house module and function that calls this row in production, by file and line',
            'the workflow JSON filename under _comfy_workflows/',
        ],
        'rule': 'yes only if a production code path reaches this row. A workflow nobody calls is '
        'a no, and the note names the file that would have to change.',
        'grade': 'receipt',
    },
    'previewable': {
        'requires': [
            'the preview or progress node in the row own workflow JSON, by node id',
            'the house endpoint that serves that preview',
        ],
        'rule': 'yes if a partial frame can be seen while the render runs.',
        'grade': 'receipt',
    },
    'price_table': {
        'feeds_derive': 'cost',
        'requires': [
            'the board power of the card in watts from nvidia-smi -q',
            'the measured wall power draw if a meter is available',
        ],
        'rule': 'the watts the cost arithmetic multiplies by.',
        'grade': 'receipt',
    },
    'tariff': {
        'feeds_derive': 'cost',
        'requires': ['the electricity price per kWh from the current house bill, with its date'],
        'rule': 'the euro per kWh the cost arithmetic multiplies by. Dated, because it changes.',
        'grade': 'receipt',
    },
}

# ── wiring: read off the code path, never run, and visibly assumed ──────────────────────────
WIRING = {
    'isolation': {
        'read_from': [
            'the comfy client in _comfy_client.py and the process it talks to',
            'whether the render happens in the GUI process or in the separate ComfyUI server on :8188',
        ],
        'rule': 'assumed yes for every comfy row: the render runs in the ComfyUI server '
        'process, never imported into the Flask GUI, so a crash in a model cannot take '
        'the dashboard with it. Written from the code path and marked assumed, so it is '
        'never mistaken for something a render proved.',
        'grade': 'assumed',
    },
    'gated': {
        'read_from': [
            'the QC contract the step runs under (qc_contract.py) and whether its '
            'gates are enforcing or advisory for this step',
            'the approval queue route the step output passes through, if any',
        ],
        'rule': 'assumed from the contract: whether a bad frame from this row is STOPPED before '
        'it reaches an output folder. Read off the code, marked assumed.',
        'grade': 'assumed',
    },
}

# ── na: with the reason written out ─────────────────────────────────────────────────────────
NA = {
    'concurrency': 'There is one GPU and one ComfyUI queue on this machine, so two renders never run at '
    'once by design — the queue serialises them. A concurrency number here would be a claim '
    'about hardware the house does not have. The related real question, what happens when '
    'the card is already busy, is measured by u_degrades instead.',
    'resumable': 'A single render is atomic: the sampler either finishes its steps and returns a PNG or '
    'it returns nothing, and there is no half-render on disk to resume from. Nothing in this '
    'bank produces a resumable unit of work. The lora_train step DOES have checkpoints and '
    'its own module overrides this column with a real probe.',
    'pd_asks_back': 'An image transport has no channel to answer in: it returns pixels, never a question, so '
    'a picture cannot ask what was meant. There is nothing here to measure rather than '
    'something we failed to measure. The nearest real question, whether a damaged '
    'instruction is visible in the output at all, is measured by pd_damage_visible.',
}

# ── transport_na: levers a transport does not have ─────────────────────────────────────────
_PROMPT_COLS = sorted(
    {c for p in PROBES for c in p['feeds'] if c.startswith('pd_')}
    | {k for k in DERIVE if k.startswith('pd_')}
    | set(NA) & {'pd_asks_back'}
)
_NO_PROMPT_REASON = (
    'This transport takes no prompt at all — it is called as a function on a fixture, so there '
    'is no instruction to damage, lengthen, reorder or weight. The column is not unmeasured, '
    'there is nothing in this row for it to be about.'
)
_NO_PROMPT_TRANSPORTS = ('service', 'pipeline', 'blender', 'ffmpeg', 'library')

TRANSPORT_NA = {t: {c: _NO_PROMPT_REASON for c in _PROMPT_COLS} for t in _NO_PROMPT_TRANSPORTS}
TRANSPORT_NA['library'].update(
    {
        'vram': 'A library lookup is a query against an index on disk; it never touches the GPU, so '
        'there is no GPU memory figure to report for this row.',
        'deterministic': 'A library lookup has no seed and no sampler — it returns the same ranked '
        'items for the same query by construction, so the column would be yes by '
        'definition and tells the reader nothing.',
    }
)
TRANSPORT_NA['comfy'] = {}
TRANSPORT_NA['retired'] = {}
TRANSPORT_NA_NOTE = (
    'comfy is the transport this bank was written for and it is short of nothing here: it has a '
    'prompt, a negative prompt, a seed, a size, term weights and a batch lever. It has no '
    'temperature, but no image step asks for one. The CLI and API text transports do not appear '
    'in this kind at all. A `retired` row needs no exemptions: the runner skips it and writes '
    'untested "retired" on every column from the row own `skip` reason.'
)

SHARED = {
    'version': '2026-09-30.1',
    'settings': COND_RENDER,
    'negative': NEGATIVE,
    'negative_note': NEGATIVE_NOTE,
    'prompt_note': PROMPT_NOTE,
    'conditions_note': COND_NOTE,
    'subjects': SUBJECTS,
    'subject_checks': SUBJECT_CHECKS,
    'subject_question': SUBJECT_QUESTION,
    'subject_state_rule': SUBJECT_STATE_RULE,
    'subject_fixtures': SUBJECT_FIXTURES,
    'colour_bands': COLOUR_BANDS,
    'pd_base': PD_BASE,
    'pd_key': PD_CHECKS,
    'pd_key_note': PD_KEY_NOTE,
    'length_rule': LENGTH_RULE,
    'filler_clauses': FILLER_CLAUSES,
    'lantern_tail': LANTERN_TAIL,
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': WIRING,
    'na': NA,
    'transport_na': TRANSPORT_NA,
    'transport_na_note': TRANSPORT_NA_NOTE,
    'operator_protocol': [
        'Every operator check is BLIND. The runner writes each frame out under a random name, '
        'strips the PNG metadata, and shuffles the whole set before the operator sees any of it. '
        'The operator never learns the model, the row, the seed, the repeat number, or whether a '
        'frame came from a clean or a damaged prompt.',
        'The operator answers the written question in this file, word for word, and nothing '
        'else. No note, no score out of ten, no "it depends". The questions are here so that the '
        'same question is asked of the next model in a year.',
        'The answer is yes or no. A maybe is a NO: a frame the operator has to think about is not '
        'a frame the house would ship without looking.',
        'Where a detector also runs, the operator answers first and never sees the detector '
        'output. The detector is authority for the thing it measures (the count, the lettering, '
        'the fingertips, the colour share) and the operator is authority for everything else; '
        'both must pass for the seed to count.',
        'Frames from the same subject on different seeds are separated in the shuffle, so the '
        'operator cannot mark three at once from a first impression.',
        'For cap_cells_clean the nine cells are cut apart and shuffled among other sheets cells, '
        'and each is judged alone — a sheet that reads well as a whole cannot carry a bad cell.',
        'For pd_damage_visible the damaged and clean frames are shuffled together and the '
        'operator is not told the proportion, so guessing yes cannot score.',
        'About thirty seconds a decision. The operator minute count in each step budget is '
        'built from that and from nothing else.',
    ],
}
