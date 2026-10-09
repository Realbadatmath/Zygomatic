# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.universal — the universal 27, the four that must be PROVOKED, the per-transport exemptions and SHARED.

Verbatim from the former geometry_shared.py, lines 2843-3256.
"""

from __future__ import annotations

from .constants import CONDITIONS_NOTE, FIXED_SETTINGS, OPERATOR_PROTOCOL
from .subjects_people_body import SUBJECTS
from .builds_capacity import CAP_NOTE, PROBES, _probe
from .space import SPACE_NOTE
from .attributes import ATTR_NOTE
from .prompt_variants import BASE_KEY_NOTE, BASE_TASK
from .prompt_clarity import CLARITY_LADDER

# ── the universal 27: the four that must be PROVOKED, not read ─────────────────────────────
PROBES += [
    _probe(
        'geo_deterministic',
        'same seed twice, byte-identical GLB',
        ['deterministic'],
        [
            {'check': 'glb_hash_identical', 'across': ['run_a', 'run_b'], 'when': 'glb'},
            {'check': 'build_succeeds', 'when': 'report'},
        ],
        {'prompt': BASE_TASK},
        conditions_override={
            'seeds': [11],
            'repeats': 2,
            'note': 'two whole runs of seed 11 in separate processes, the second after the first has exited',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='sha256 of the exported GLB. Identical on both runs is yes; identical geometry '
        'with a differing byte stream (a timestamp in the header) is partial and the '
        'note says which bytes differ; different geometry is no. A headless Blender row '
        'is expected to be yes — Blender is deterministic — and a diffusion-based mesh '
        'row often is not, which is the finding.',
    ),
    _probe(
        'geo_failsafe',
        'what happens when an input is missing',
        ['failsafe'],
        [
            {
                'check': 'build_error',
                'terms': ['not found', 'no such file', 'missing', 'cannot open', 'failed'],
                'when': 'report',
            },
            {'check': 'file_absent', 'path': 'out/geo_failsafe.glb'},
        ],
        {'prompt': BASE_TASK, 'fixture': 'capability_tests/fixtures/geometry/absent_on_purpose.png'},
        conditions_override={
            'seeds': [11],
            'repeats': 1,
            'note': 'the fixture path deliberately does not exist; the row is also '
            'run once with its model weights path pointed at /dev/null',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='yes when the row refuses LOUDLY — a named error, no output file, a non-zero '
        'exit. Writing an empty or half GLB and reporting success is a no, and it is the '
        'failure that costs a whole batch downstream.',
    ),
    _probe(
        'geo_degrades',
        'behaviour when the GPU is already busy',
        ['degrades'],
        [
            {'check': 'build_succeeds', 'when': 'report'},
            {'check': 'mesh_shell_count', 'min': 4, 'max': 60, 'when': 'glb'},
            {'check': 'build_error', 'terms': ['out of memory', 'cuda', 'oom', 'queue', 'waiting'], 'when': 'report'},
        ],
        {'prompt': BASE_TASK},
        conditions_override={
            'seeds': [11],
            'repeats': 2,
            'load': 'run once on an idle GPU, then '
            'once with a second process holding 16 GB of VRAM and 80 per cent of '
            'the SM time',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='yes when the loaded run either waits and then produces the SAME build, or '
        'refuses with a named OOM. partial when it produces a different but usable '
        'build. no when it crashes the process or writes a broken GLB. The idle/loaded '
        'wall times both go in the trial and feed the speed note.',
    ),
    _probe(
        'geo_offline',
        'does the row run with no network',
        ['offline'],
        [
            {'check': 'build_succeeds', 'when': 'report'},
            {'check': 'mesh_shell_count', 'min': 4, 'max': 60, 'when': 'glb'},
            {'check': 'transcript_absent', 'pattern': '(?i)(resolv|connect|download|huggingface|http)'},
        ],
        {'prompt': BASE_TASK},
        conditions_override={
            'seeds': [11],
            'repeats': 1,
            'note': 'the whole build runs inside `unshare -n` with the model cache '
            'already warm; a second run with a COLD cache is also recorded',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='yes when the warm-cache run completes inside unshare -n. partial when it needs a '
        'warm cache but never reaches the network afterwards. no when it fails without '
        'the network. A claude_cli row is a no here and honestly so — the subscription '
        'login is off-box.',
    ),
]

DERIVE = {
    'speed': {
        'from': 'wall clock from the call to the written GLB, per build, median over the '
        '132 Builds probes on seed 11; the model-load time of the first build is '
        'recorded separately so a per-build figure is not inflated by it',
        'grade': 'measured',
        'unit': 'seconds per build',
    },
    'throughput': {
        'from': 'builds completed per hour over one unbroken run of the whole Builds '
        'band, load time included — the number a schedule can be built on',
        'grade': 'measured',
        'unit': 'builds per hour',
    },
    'vram': {
        'from': 'peak of nvidia-smi --query-gpu=memory.used sampled at 1 Hz for the duration '
        'of the build, minus the idle baseline taken before the process starts',
        'grade': 'measured',
        'unit': 'MiB peak',
    },
    'ram': {
        'from': 'peak resident set size of the build process tree, /proc/<pid>/status VmHWM sampled at 1 Hz',
        'grade': 'measured',
        'unit': 'MiB peak',
    },
    'disk': {
        'from': 'bytes written under the run directory for one build: the GLB, the turntable '
        'sheet, any intermediate voxel or point-cloud dump, plus the weights the row '
        'needed on disk to start',
        'grade': 'measured',
        'unit': 'MiB per build, plus MiB of weights',
    },
    'cost': {
        'from': 'GPU seconds times the GPU tariff from the LOOKUP price_table. A headless '
        'Blender row that renders on CPU is costed as CPU minutes times the CPU '
        'tariff, capped at 20 of 24 cores (feedback_cpu_core_cap) — a Blender row that '
        'takes the whole box is not free just because no GPU was held',
        'grade': 'receipt',
        'unit': 'currency per build',
    },
    'concurrency': {
        'from': 'how many builds ran at once without a failure or a slowdown worse than '
        '1.5x per build: raise the count until one of those happens. For a '
        'Blender row the ceiling is the core cap (20 of 24, '
        'feedback_cpu_core_cap), and the measured number is reported against it',
        'grade': 'measured',
        'unit': 'count',
    },
    'first_take': {
        'from': 'the FIRST repeat only (seed 11) of every Builds probe: the share of '
        'subjects that passed without a retry. Never a best-of-three — a later '
        'seed passing is what retries measures',
        'grade': 'measured',
        'unit': 'share of subjects',
    },
    'retries': {
        'from': 'seeds 12 and 13 of the Builds probes: the share of subjects that failed on '
        'seed 11 and passed on a later seed. High here with a low first_take means '
        'the row works but must be run three times, which is a schedule fact',
        'grade': 'measured',
        'unit': 'share of failed-first subjects recovered',
    },
    'silent_fail': {
        'from': 'builds that the row reported as successful but which failed a '
        'mechanical check (manifold, self-intersection, shell count, bbox, '
        'up-axis) — a broken GLB delivered with no complaint. Counted over the '
        'whole Builds band',
        'grade': 'measured',
        'unit': 'share of reported successes that are broken',
    },
    'batch': {
        'from': 'builds completed in one process before it must be restarted, and whether the '
        'second build is faster than the first (weights held in VRAM). Read from the '
        'run ledger for the whole-band run',
        'grade': 'measured',
        'unit': 'builds per process',
    },
    'receipts': {
        'from': 'the trial for every build carries, verbatim: the prompt or the fixture '
        "image path and its hash, the seed, the row's resolution/steps/sampler, "
        'the tool revision, the exported GLB and its sha256, and the 4-view '
        'turntable sheet. The column is the share of builds whose trial is complete',
        'grade': 'receipt',
        'unit': 'share of builds with a complete trial',
    },
    'pd_recorded': {
        'from': 'the same trial: whether the exact prompt, seed and settings that '
        'produced a given GLB can be recovered from the ledger alone, checked by '
        'replaying ten builds from their receipts and comparing hashes',
        'grade': 'receipt',
        'unit': 'share replayable from the receipt',
    },
    'pd_retries': {
        'from': 'the prompt-band probes only: how many of the 53 columns needed a second '
        'or third seed to reach their state. A prompt that works one time in '
        'three is not a working prompt',
        'grade': 'measured',
        'unit': 'share of prompt columns needing a retry',
    },
    'pd_portable': {
        'from': 'the pd_reusable template and the base task run on EVERY other row in '
        'the same step: the share of rows on which the same wording reaches the '
        'same state. Computed across the sheet, not within one row',
        'grade': 'measured',
        'unit': 'share of rows the wording carries to',
    },
}

LOOKUP = {
    'licence': {
        'ask': 'the licence of the tool and of its weights, read from the LICENSE file (and '
        "the model card's licence field) in the installed revision — never from a "
        'blog post or a comparison article (feedback_licence_policy). Record the '
        "SPDX id or the full text's own name, the revision it was read at, and any "
        'territory, field-of-use or non-commercial clause verbatim. MPFB and its '
        'base bodies are CC0; Direct3D-S2 must be read at file level before any '
        'output of it is shipped (project_direct3d_s2_install)',
        'requires': ['LICENSE file path', 'model card url or local path', 'revision or commit', 'date read'],
        'grade': 'receipt',
    },
    'weights_pinned': {
        'ask': 'whether the weights are pinned to a revision the house holds on disk '
        '(a commit or a sha256), or fetched by a moving tag at run time',
        'requires': ['weights path', 'sha256 or commit', 'where the pin is written'],
        'grade': 'receipt',
    },
    'outputs_clause': {
        'ask': 'what the licence says about the OUTPUT — who owns a generated mesh, '
        'whether it may be sold, whether attribution follows it downstream',
        'requires': ['licence clause quoted verbatim', 'section number'],
        'grade': 'vendor',
    },
    'attribution': {
        'ask': 'what attribution the licence requires, in what form, and where it must appear for a shipped asset',
        'requires': ['licence clause quoted verbatim'],
        'grade': 'vendor',
    },
    'train_data': {
        'ask': 'what the weights were trained on, as the publisher states it, with the '
        'sentence quoted; "not stated" is the honest answer where it is not stated',
        'requires': ['model card url or local path', 'quoted sentence'],
        'grade': 'vendor',
    },
    'ai_training': {
        'ask': 'whether the licence permits the OUTPUT to be used as training data for '
        'another model. The house asset packs answer this too, and several are '
        'no_ai_training=True',
        'requires': ['licence clause quoted verbatim or the pack metadata field'],
        'grade': 'receipt',
    },
    'wired': {
        'ask': 'whether this row is reachable from a house pipeline today: the module and '
        'function that calls it, or the workflow JSON, with the file and line',
        'requires': ['caller file:line', 'or "not wired" with the date checked'],
        'grade': 'receipt',
    },
    'previewable': {
        'ask': 'whether a build can be looked at before it is accepted — the turntable '
        'sheet route or the studio viewer that shows it, with the file and line',
        'requires': ['viewer route or script path'],
        'grade': 'receipt',
    },
    'price_table': {
        'ask': 'the GPU and CPU tariffs the cost derive multiplies by, with the date '
        'they were set and where they are written down',
        'requires': ['tariff source path', 'date'],
        'grade': 'receipt',
        'feeds_derive': 'cost',
    },
}

WIRING = {
    'isolation': {
        'read': 'every geometry row runs in a SUBPROCESS: a headless `blender -b '
        '--python <script>`, or a service call in its own python process, never '
        'an import into the Flask GUI process — torch and bpy in the GUI process '
        'have both taken the dashboard down before. Read from the call site, not '
        'run. Marked assumed and visibly so',
        'grade': 'assumed',
    },
    'gated': {
        'read': 'which house gate a build must pass before it is accepted downstream: the '
        'mesh_qc gates (anatomy, self-intersection, +Y up per '
        'project_body_plates_gltf_upaxis), and for a character row the drift and '
        'plate-overlay gates. Read from the gate module the pipeline calls, with '
        'file:line. Marked assumed',
        'grade': 'assumed',
    },
    'resumable': {
        'read': 'whether the runner writes one output per subject and skips a subject '
        'whose GLB already exists, so an interrupted band continues rather than '
        "restarting. Read from the runner's skip-existing branch, with file:line. "
        'Marked assumed',
        'grade': 'assumed',
    },
}

NA = {
    'pd_weight_range': 'No geometry transport exposes numeric prompt weighting. A mesh generator '
    'takes plain text or an image; a headless Blender script takes parameters, '
    'not weighted tokens. There is no lever to measure, so this is not asked of '
    'a 3D row rather than answered no.',
    'pd_negative_len': 'No geometry transport takes a negative prompt. What a build must NOT contain '
    'is said in the prompt itself and is measured by pd_constraints, which is the '
    'honest home for the question here.',
    'cap_moving': 'A moving-thing count belongs to the video bank, which rigging merges FIRST '
    '(STEP_KINDS rigging = video then geometry), so the video bank answers it and this '
    'entry is never read. No geometry-only step asks it: a static build has nothing '
    'moving to count.',
    'cap_seconds': 'A duration in seconds belongs to the video bank, which rigging merges before '
    'this one. A static build has no duration, so a geometry-only step cannot answer '
    'it and does not ask it.',
    'cap_shots': 'A shot count belongs to the video bank, which rigging merges before this one. A '
    'static build is not a shot, so a geometry-only step cannot answer it.',
}

# ── per-transport exemptions ───────────────────────────────────────────────────────────────
_PD_ALL = sorted({c for _p in PROBES for c in _p['feeds'] if c.startswith('pd_')})
_PD_SCRIPTED = [c for c in _PD_ALL if c not in ('pd_recorded', 'pd_portable', 'pd_retries')]

_NO_PROMPT = (
    'This row takes no prompt: a headless script is driven by parameters on the subject '
    'id, so there is no wording to damage, lengthen, translate or steer. The prompt bands '
    'measure a lever this transport does not have.'
)
_LIB_NO_PROMPT = (
    'A library row generates nothing: the input is a query and the output is an '
    'existing asset, so there is no prompt to damage or steer.'
)

TRANSPORT_NA = {
    'blender': dict.fromkeys(_PD_SCRIPTED, _NO_PROMPT),
    'library': dict(
        dict.fromkeys(_PD_SCRIPTED, _LIB_NO_PROMPT),
        **{
            'vram': 'A library lookup holds no GPU memory; there is nothing to sample.',
            'degrades': 'A library lookup does not contend for the GPU, so there is no loaded condition '
            'to compare an idle one against.',
            'deterministic': 'A library lookup returns the asset that is on disk. Determinism is a '
            'property of the disk, not of the row, and asserting it as measured would '
            'be a claim about nothing.',
        },
    ),
    'claude_cli': {
        'pd_seed_vs_prompt': 'The subscription login takes no seed, so a seed row cannot be built '
        'to compare a prompt row against (feedback_arch_assistant_no_opus '
        'fixes the model to sonnet; the seed is not exposed either).',
        'vram': 'The model runs off-box on the subscription login; no local GPU memory is used.',
        'ram': 'Only the CLI client runs locally; its resident set says nothing about the model.',
        'disk': 'No weights are held locally.',
        'degrades': 'Local GPU load does not reach an off-box model, so there is no degraded condition to measure.',
        'offline': 'The subscription login requires the network by definition; the column is '
        'answered by the probe as a no and needs no separate exemption beyond that.',
    },
    'retired': {},
    'service': {},
}

FIXTURES = [
    {
        'path': 'capability_tests/fixtures/geometry/subjects/<subject id>.png',
        'generated': "One 1024x1024 render per Builds subject, taken from the image bank's APPROVED "
        "render of the same subject prompt (the image_shared bank's own fixture set), "
        'cropped square, background removed to flat mid-grey, subject upright and '
        'centred with a 5 per cent margin. One file per subject id in SUBJECTS; the '
        'prompt in SUBJECTS is the caption recorded beside it.',
        'verified': False,
        'blocks': sorted(SUBJECTS.keys()),
        'how_to_verify': 'An operator opens the 132 PNGs as a contact sheet and confirms that each one '
        'shows the subject its id names, upright, whole and unambiguous — an '
        'image-conditioned row is only as good as the picture it was given, so a '
        'wrong or cropped fixture would be scored against the model. Flip verified to '
        'True only after the whole sheet has been looked at; until then every Builds '
        'column is written untested with the note "fixture unverified".',
    },
    {
        'path': 'capability_tests/fixtures/geometry/absent_on_purpose.png',
        'generated': 'NOT created, ever. The failsafe probe needs a path that does not exist; creating '
        'it would destroy the probe.',
        'verified': True,
        'blocks': [],
        'how_to_verify': 'Confirm the path does NOT exist before the failsafe probe runs.',
    },
]

SHARED = {
    'version': '2026-09-30.1',
    'kind': 'geometry',
    'subjects': {
        k: {'label': v[0], 'prompt': v[1], 'shells': list(v[2]), 'size_m': list(v[3])} for k, v in SUBJECTS.items()
    },
    'fixed_settings': FIXED_SETTINGS,
    'base_task': BASE_TASK,
    'base_key_note': BASE_KEY_NOTE,
    'clarity_ladder': CLARITY_LADDER,
    'conditions_note': CONDITIONS_NOTE,
    'capacity_note': CAP_NOTE,
    'space_note': SPACE_NOTE,
    'attribute_note': ATTR_NOTE,
    'fixtures': FIXTURES,
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': WIRING,
    'na': NA,
    'transport_na': TRANSPORT_NA,
    'operator_protocol': OPERATOR_PROTOCOL,
    'transport_note': (
        'service — Direct3D-S2 and the prop mesh library builder, called as a function in their own '
        'process (project_direct3d_s2_install); an image-conditioned row gets the subject fixture '
        'PNG, a text-in row gets the subject prompt. blender — headless `blender -b --python`, for '
        'the MPFB CC0 human bases, rigging, the Cycles/EEVEE render rows, arch_blender_build.py and '
        'the shared GLB-to-turntable renderer; these rows take no prompt, hold no GPU when they '
        'render on CPU, and are capped at 20 of 24 cores (feedback_cpu_core_cap). library — '
        'prop_lib, answered with library_has. claude_cli — arch_assistant.py runs '
        '`claude -p --model sonnet` on the operator login, NEVER Opus '
        '(feedback_arch_assistant_no_opus). retired — smpl, kept for its receipt only: SMPL is '
        'non-commercial and is not used, so every column is untested with the reason "retired".'
    ),
}
