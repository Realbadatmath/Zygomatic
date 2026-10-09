# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_shared: DERIVE, LOOKUP, WIRING, NA, TRANSPORT_NA and the assembled SHARED bank."""

from __future__ import annotations

from .settings import (
    AMBIENCE,
    CHECKS_NOTE,
    CHECK_KINDS,
    CLAP_ABSENT_MAX,
    CLAP_MIN,
    CLAP_NULL_MARGIN,
    SETTINGS,
    SOUNDS,
    SOUND_LABELS,
)
from .fixtures import BASE_CHECKS, BASE_LABEL, BASE_PROMPT, DAMAGE_VARIANTS, FIXTURES, LYRIC_80, LYRIC_RULE, PROBES
from .prompt_clarity import CLARITY_RUNGS
from .prompt_limits import LEN_CLAUSES, LEN_RULE, LEN_RUNGS

# ── DERIVE — computed from the run's own telemetry, never asked of the model ────────────
DERIVE = {
    'speed': {
        'from': ['run.wall_s', 'run.output_seconds'],
        'rule': 'median wall seconds per second of finished audio, over every render in this '
        'bank; model load counted once and reported beside it',
        'unit': 's/s',
        'grade': 'measured',
    },
    'throughput': {
        'from': ['run.wall_s', 'run.items'],
        'rule': '3600 / median wall seconds per item, items being the 4 s sounds; the '
        'ambience rows report their own number',
        'unit': 'items/h',
        'grade': 'measured',
    },
    'vram': {
        'from': ['run.nvml_peak_mib'],
        'rule': 'max NVML used-memory delta over the run, sampled at 200 ms; 0 for a row that never touches the GPU',
        'unit': 'MiB',
        'grade': 'measured',
    },
    'ram': {
        'from': ['run.rss_peak_mib'],
        'rule': 'max resident set size of the worker process tree, sampled at 200 ms',
        'unit': 'MiB',
        'grade': 'measured',
    },
    'disk': {
        'from': ['run.bytes_written'],
        'rule': 'bytes written under output/ per finished item, weights excluded (they are '
        "counted once in the row's install size)",
        'unit': 'MiB',
        'grade': 'measured',
    },
    'cost': {
        'from': ['run.wall_s', 'run.gpu_s', 'tariff'],
        'rule': 'gpu_s x the box tariff in `lookup.tariff`, plus metered vendor tokens for an '
        'off-box row; a local row costs electricity only and says so',
        'unit': 'EUR/item',
        'grade': 'lowest of inputs',
    },
    'concurrency': {
        'from': ['probe.acap_concurrent'],
        'rule': "the acap_concurrent ladder's answer: the largest number of parallel "
        'jobs whose total throughput still rises',
        'unit': 'count',
        'grade': 'measured',
    },
    'first_take': {
        'from': ['probe.*.repeat_1'],
        'rule': 'pass rate of the FIRST repeat only, across every probe in this bank '
        '([[feedback_first_take_not_retries]]); retries are pd_retries, not this',
        'grade': 'measured',
    },
    'deterministic': {
        'from': ['probe.make_door_creak.repeat_1', 'run.rerender_seed_11'],
        'rule': 'make_door_creak is rendered a second time at seed 11 in the same '
        'process and compared sample-for-sample: bit-identical -> yes; '
        'log-mel cosine >= 0.999 -> partial; anything else -> no',
        'grade': 'measured',
    },
    'retries': {
        'from': ['run.attempts'],
        'rule': 'median attempts to a passing take over every probe that failed at least '
        'once; a row that never needed a retry reports 1',
        'unit': 'count',
        'grade': 'measured',
    },
    'silent_fail': {
        'from': ['run.exit_code', 'run.stderr', 'run.output_bytes'],
        'rule': 'INVERTED: yes when every failing call in the run left a non-zero exit, '
        'an stderr line or a recorded error. A zero-length WAV with exit 0 and '
        'an empty stderr is a silent failure and makes this no',
        'grade': 'measured',
    },
    'receipts': {
        'from': ['run.ledger_rows', 'run.manifest'],
        'rule': 'yes when every item this bank produced has a run_ledger row carrying the '
        'row id, the seed, the prompt hash and the output sha256; partial when the '
        'row is there but the seed or prompt hash is not',
        'grade': 'receipt',
    },
    'batch': {
        'from': ['run.batch_call'],
        'rule': 'the 53 Makes prompts are submitted as ONE call. yes when the row accepts the '
        'list and returns 53 files; partial when it loops internally but keeps the '
        'model loaded once; no when the caller must load the model per item',
        'grade': 'measured',
    },
    'pd_portable': {
        'from': ['probe.pd_base', 'run.sibling_row'],
        'rule': "BASE_PROMPT is run unchanged on the row's declared sibling (the next "
        'size of the same family, named in the step module). yes when the '
        'sibling passes BASE_CHECKS too; no sibling on this box -> untested',
        'grade': 'measured',
    },
    'pd_recorded': {
        'from': ['run.manifest.prompt', 'run.ledger_rows'],
        'rule': 'yes when the exact prompt string and its sha256 sit beside every output '
        'in the manifest AND the ledger; partial when only one of the two has it',
        'grade': 'receipt',
    },
    'pd_retries': {
        'from': ['run.attempts', 'probe.*.pass'],
        'rule': 'median number of PROMPT rewrites to a usable item, counted over the '
        'clarity ladder: the rung index of pd_clarity_floor minus one. A row that '
        'passes at r1 reports 0',
        'unit': 'count',
        'grade': 'measured',
    },
}


# ── LOOKUP — a documented fact with a pinned source and revision ───────────────────────
def _lk(question, requires, grade='vendor', note=''):
    d = {'question': question, 'requires': list(requires), 'grade': grade}
    if note:
        d['note'] = note
    return d


_SRC = [
    'the licence file shipped with the weights or the package, by path',
    'the vendor page URL and the date it was read',
    'the revision or commit the claim was read at',
]
LOOKUP = {
    'licence': _lk(
        "May the row's output be used commercially, by name of licence?",
        _SRC,
        note='house facts this bank pins: the soundfont behind the score leg is GPL-2, '
        'which is a copyleft obligation on anything distributed with it; the Vocal '
        'FX library is the first house library whose licence FORBIDS AI training, so '
        'its rows must say so here and in ai_training.',
    ),
    'weights_pinned': _lk(
        'Is the weights licence pinned to a revision, or only to a page that can change under us?',
        _SRC + ['the sha256 of the weights file as installed'],
        grade='receipt',
    ),
    'outputs_clause': _lk('Does the licence claim any right over what the row produces?', _SRC),
    'attribution': _lk('Is attribution required, and in what exact words?', _SRC),
    'train_data': _lk(
        'Is the training data of these weights documented well enough to name it?',
        _SRC,
        note='"a large internet audio corpus" is not documentation; the answer is no unless a dataset is named.',
    ),
    'ai_training': _lk(
        "May we train on this row's output?",
        _SRC,
        note='the Vocal FX library is `no` by its own licence; a row that reads from it inherits the no.',
    ),
    'wired': _lk(
        'Is this row actually called by a production pipeline today, from which file and line?',
        ['the calling module and line number', 'the run_ledger query showing a real run in the last 90 days'],
        grade='receipt',
    ),
    'previewable': _lk(
        'Can an operator hear the result before it is committed, through which endpoint or panel?',
        ['the route or panel id that plays it', 'the date it was last seen working'],
        grade='receipt',
    ),
    'tariff': _lk(
        'What does one GPU second on this box cost, at the current electricity price?',
        ['the kWh price and its date', 'the measured board draw under load'],
        grade='receipt',
        note='not a column: feeds derive.cost.',
    ),
}
LOOKUP['tariff']['feeds_derive'] = 'cost'

# ── WIRING — read off the code path, never run, and visibly `assumed` ──────────────────
WIRING = {
    'isolation': {
        'reads': 'the call site: does the row run in a child process or a separate '
        'service, or inside the Flask/kanban process?',
        'rule': 'a child process or an HTTP hop to ComfyUI / a service = yes; an in-process '
        'import of torch inside the GUI = no. Recorded as read, not measured: the '
        'honest measurement would be to destabilise the GUI on purpose',
        'grade': 'assumed',
    },
    'gated': {
        'reads': 'the delivery path: is audio_qc.py (or voice_qc.py for a speech row) called '
        'on the artefact before it ships?',
        'rule': "yes when the path runs audio_qc's LUFS / true-peak / silence / words-per-minute "
        'gate and refuses on a fail; partial when it measures but only warns; no when '
        'nothing stands between the render and the delivery folder',
        'grade': 'assumed',
    },
}

# ── NA — not applicable to any audio row, with the reason written out ──────────────────
NA = {
    'resumable': 'a 4 s render and a 12 s ambience are shorter than the model load that precedes '
    'them, so there is no partial state worth resuming: an interrupted call is redone '
    'from the start. The long-form rows that COULD resume (a full music cue) are '
    'scheduled as several short calls, which is the house answer to this question.',
    'count_fingers': 'fingers are not audible. No audio row is asked to count them, and a probe '
    'that pretended to would be scoring something other than the model.',
    'count_legs': 'the number of legs on an animal is not recoverable from its sound; a four-legged '
    "gait and a two-legged one differ by rhythm, which is count_exact's job, not "
    "this column's.",
    'count_windows': 'repeated architecture is a visual count. The nearest audible thing is room '
    'size, which this bank measures as RT60 in make_room_tone_church, not here.',
    'pd_weight_range': 'no audio row in the house takes weighted prompt terms: ACE-Step, MusicGen, '
    'IndexTTS-2 and the DSP rack have no (term:1.4) syntax at all. There is '
    'nothing to range over, and inventing a syntax to test would measure the '
    'test, not the row.',
    'pd_clip77': 'the 77-token CLIP window is a Stable-Diffusion text encoder. Audio rows use T5, '
    'a bare tokeniser, or a text field with no encoder limit; the real length limit is '
    'measured by pd_length_ladder in words, which is the honest question here.',
    'pd_action_count': 'sequential actions in one prompt are a video question about motion over '
    'frames. The audible version — several sounds in a written order — is '
    "measured by pd_example_needed's clap_sequence check and by acap_layers, so "
    'answering it again here would be a second disposition on the same evidence.',
    'pd_camera_words': 'a camera has no sound. This column reaches the audio bank only because '
    'lipsync is both a video and an audio step; lipsync merges the VIDEO bank '
    "first, so the video bank's real answer wins there and this na is dropped. "
    'For every audio-only row the column is genuinely not applicable.',
    'pd_motion_words': 'motion verbs drive pixels, not samples. Same seam as pd_camera_words: only '
    'lipsync asks it, the video bank owns it there, and no audio-only row has a '
    'motion field to obey.',
    'pd_prompt_vs_plate': 'there is no plate in an audio row. The analogous audio question — does '
    'the prompt still matter beside a reference recording — is measured by '
    'pd_seed_vs_prompt and by the voice_clone reference rows in the step '
    'module, not by pretending a plate exists.',
}

# ── TRANSPORT_NA — a column a whole transport cannot answer ────────────────────────────
TRANSPORT_NA = {
    'library': {
        'pd_negative_len': 'a library search has no negative-prompt field; the query is a label and '
        'a filter, and exclusion is a filter clause, not a prompt.',
        'pd_weight_range': 'a ranked search has no term weights.',
        'pd_seed_vs_prompt': 'a library lookup has no seed: the same query returns the same ranking.',
        'deterministic': 'trivially yes by construction, so measuring it says nothing about the row; '
        'the honest statement is that the index is fixed, which `wired` records.',
        'vram': 'CLAP embedding of the query is CPU work in the house index; there is no GPU render.',
        'acap_variations': 'a library returns what it holds; there is no generator to re-roll, so '
        '"variations before they repeat" is a property of the library contents, '
        'reported as the item count on the sheet instead.',
    },
    'service': {
        'pd_tag_vocab': 'only for the DSP rack rows (sfx_fx.py, audio_mix.py), whose input is a '
        'parameter set and not a prompt at all; the generative service rows DO '
        'answer this column and must not take this exemption.',
    },
    'comfy': {
        'pd_asks_back': 'a workflow JSON cannot ask a question back: an unusable prompt reaches the '
        'sampler as an embedding. The loud-failure half of this is pd_damage_visible, '
        'which comfy rows do answer.',
    },
    'pipeline': {
        'pd_portable': 'a house pipeline stage has no sibling model to transfer to — it IS the '
        "house path. Portability of the model inside it is the model row's column.",
    },
    'retired': {
        'licence': 'a retired row is kept for its historical receipt only. The runner writes '
        'untested "retired" on every column, including this one; AudioGen was retired '
        '2026-08-09 and nothing in production calls it.',
    },
}

# ── the bank ───────────────────────────────────────────────────────────────────────────
OPERATOR_PROTOCOL = (
    'Every check marked `operator` is BLIND unless its own entry says otherwise (u_failsafe and '
    'u_offline are sighted, because they are about the process and not the sound).\n'
    "1. The runner writes each trial's audio to a temporary folder under a random name, strips the "
    'file metadata, loudness-matches nothing and shuffles the order.\n'
    '2. The operator is shown the written question and nothing else — not the prompt, not the row, '
    'not the model name, not the other trials\' answers. Where the question is an A/B ("A then B"), '
    "the pair is presented in a random order per trial and the operator's answer is un-flipped "
    'afterwards by the runner.\n'
    '3. The operator answers yes/no, or a number where the question asks for one. There is no '
    '"maybe": a question the operator cannot answer is recorded as `untested` with the reason, '
    'which is a statement about the question, not about the model.\n'
    '4. Where a question is INVERTED (it asks whether something bad is present), the state_note says '
    'so and the runner flips the answer before scoring. The operator is never asked to remember '
    'which way round a column runs.\n'
    '5. Budget ~30 s per decision. 53 Makes rows x 3 repeats is 159 decisions for the Makes band '
    'alone, which is why every one of them has a CLAP screen: a trial the screen fails is still '
    'heard, but it is heard knowing that.\n'
    "6. The operator's answer decides the column wherever the state_note says so. Where a detector "
    "and the operator disagree, BOTH numbers go in the trial and the column takes the operator's. "
    'We do not average a human against a classifier.'
)

CONDITIONS_NOTE = (
    f'Identical for every row, and not negotiable by a runner: output {SETTINGS["sample_rate_out"]} Hz '
    f'mono, {SETTINGS["seconds"]} s per sound and {SETTINGS["seconds_ambience"]} s per ambience, '
    f'seeds {SETTINGS["seeds"]} with 3 repeats. A row whose native rate differs renders at its own '
    'rate and the runner resamples to 48 kHz with soxr VHQ for the detectors, recording the native '
    'rate in the trial — the model is never asked to do something it cannot. A row with no seed '
    "(a library lookup, a hosted judge) records `seed: null` and its repeats measure the row's own "
    'variance. Judge rows run at temperature 0.0, seed 11, 3 repeats. Nothing in this bank is '
    'scored against a take rendered under different conditions; a sheet that mixes them is two '
    'sheets.'
)

SHARED = {
    'version': '2026-09-30.1',
    'kind': 'audio',
    'title': 'the bank every voice, music and sound step runs: 53 sounds made and heard, under one set of conditions',
    'settings': SETTINGS,
    'sounds': {_k: {'label': _v[0], 'prompt': _v[1]} for _k, _v in SOUNDS.items()},
    'sound_labels': SOUND_LABELS,
    'ambience': list(AMBIENCE),
    'base': {'prompt': BASE_PROMPT, 'label': BASE_LABEL, 'checks': BASE_CHECKS},
    'damage_variants': DAMAGE_VARIANTS,
    'clarity_rungs': [dict(rung=_r, prompt=_p) for _r, _p in CLARITY_RUNGS],
    'length_ladder': {'rungs': LEN_RUNGS, 'clauses': LEN_CLAUSES, 'rule': LEN_RULE},
    'lyric': {'text': LYRIC_80, 'rule': LYRIC_RULE, 'words': 80},
    'clap': {
        'model': 'laion/clap-htsat-fused, revision pinned in the runner',
        'min': CLAP_MIN,
        'null_margin': CLAP_NULL_MARGIN,
        'absent_max': CLAP_ABSENT_MAX,
        'receipt': 'measured 2026-09-27 on a 0.827-scoring render: chroma 0.279 against the '
        'asked label vs 0.252 for the null baseline (the mean score of 64 unrelated '
        'labels). The absolute numbers are small and close, which is exactly why '
        'CLAP is a SCREEN and the operator decides.',
    },
    'detectors': {
        'onsets': 'librosa.onset.onset_detect, backtrack=True, units=time, pinned hop 512',
        'transcript': 'faster-whisper large-v3, word timestamps on, beam 5, language given',
        'speakers': 'pyannote speaker-diarization-3.1',
        'loudness': 'BS.1770-4 integrated LUFS and true peak at 4x oversampling',
        'rt60': 'Schroeder integration of the decay after the last onset',
        'distance': 'log-mel cosine on 64 mels, hop 512, per-file mean removed',
    },
    'fixtures': FIXTURES,
    'conditions_note': CONDITIONS_NOTE,
    'checks_note': CHECKS_NOTE,
    'operator_protocol': OPERATOR_PROTOCOL,
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': WIRING,
    'na': NA,
    'transport_na': TRANSPORT_NA,
    'CHECK_KINDS': CHECK_KINDS,
}
