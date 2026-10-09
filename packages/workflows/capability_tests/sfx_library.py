# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — SFX library & search (sfx_library). 2026-09-30.

Question the sheet asks: can we find the right recorded sound without listening to everything?

Nothing on this step GENERATES. Every row is a lookup in the house audio libraries
(data/asset_libraries/<cat>/ with a licence sidecar at data/runtime/asset_library_<cat>_meta.json),
so the shared audio bank's `Makes:` band cannot be run as written — a library has no prompt and
no seed. It is overridden here with the honest library reading of the same 53 questions: the
bank's own CLAP LABEL is sent as the query, the top hit is screened by CLAP and then PLAYED
BLIND to the operator, who decides whether the library really holds that sound. Same subjects,
same labels, same blind question as every other audio sheet — a different transport.

The three rows are three different things, so most domain columns belong to exactly one of
them and are `na` with a reason on the other two:
    clap     the CLAP semantic search itself (audio_qc.qc_clap is the house use site today —
             a pass/fail gate at threshold 0.45, never a ranked retrieval bench, which is why
             "is the top hit usable" has no number on the sheet yet). It answers the Finding-it
             columns and the 53 Makes columns.
    slates   the slate/metadata layer (asset_library_service.py sidecars). It answers the
             Rights & metadata columns and `filters`.
    vocal_fx the 344 Audio Human Mouth Noises library, 1684 items. The first house library
             whose licence FORBIDS AI training (`no_ai_training: true` on every record), so
             `ai_clause` is `no` here with the clause quoted, and `ai_training` inherits it.

What is BLOCKED: capability_tests/fixtures/audio/library_keys.json holds the 20 fixed queries
with EMPTY `accept` / `relevant` lists and `verified: false`. Until the operator fills them,
semantic, precision, recall_lib and by_example ship `untested — key unverified`. We do not
score a search against an answer nobody has checked.
"""

from __future__ import annotations

from capability_tests import audio_shared as AS

FX = 'capability_tests/fixtures/audio'
KEYS = FX + '/library_keys.json'

# The libraries this step searches, with the item counts read off the sidecars 2026-09-30.
LIBRARIES = {'sfx': 95, 'foley': 1049, 'vocal_fx': 1684, 'soundtracks': 2, 'merged': 6}
ITEMS = sum(LIBRARIES.values())  # 2836 — the index the search covers

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'library_label_hit': "the library search for the text `label` returns at least one item whose CLAP cosine to `label` >= `min` AND >= that label's null baseline + `margin`; the TOP hit is the item carried to the operator",
    'library_top1_in_key': "the top-ranked slate id for the query is in that query's `accept` list in library_keys.json",
    'recall_at_k_min': "share of the query's `relevant` ids that appear in the top `k` returned ids >= `min`",
    'pairwise_corr_max': 'every pair of the top `k` results has maximum normalised cross-correlation (level-matched, best lag within +/- 0.5 s) < `max`',
    'by_example_self_rank': "querying the index with an item's OWN audio returns that item's slate id at position <= `max`",
    'filter_respected': 'every returned item satisfies the filter clause `field` (within `min`/`max`, or == `equals`); one violating item fails the trial',
    'metadata_share_min': "share of the sidecar records of the row's libraries whose `field` is present and non-empty >= `min`",
    'tag_vocab_share_min': 'share of the sidecar records whose descriptive values sit in a field of the controlled list `vocab` (rather than in free text) >= `min`',
    'duplicate_hash_max': "number of sha256 digests shared by more than one file across the row's libraries <= `max`",
}


def _p(pid, title, feeds, checks, inputs, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': dict(inputs),
        'conditions': {
            'seed': None,
            'repeats': 3,
            'top_k': 10,
            'index': sorted(LIBRARIES),
            'note': "a library lookup has no seed; the three repeats measure the index's own variance and would be identical on a static index — a difference is a finding, not noise",
        },
        'checks': list(checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


PROBES = []

# ── Makes (53 columns): for a LIBRARY this reads "the library HAS a usable <sound>" ────
# The bank's label is the query verbatim. CLAP screens, the OPERATOR decides — exactly the
# bank's rule, because the defect-judge bench says no local model can be asked "is this right".
for _sid, (_lbl, _pr) in AS.SOUNDS.items():
    PROBES.append(
        _p(
            f'make_{_sid}',
            f'Library holds: {_lbl}',
            [f'make_{_sid}'],
            [
                {'check': 'library_label_hit', 'label': _lbl, 'min': AS.CLAP_MIN, 'margin': AS.CLAP_NULL_MARGIN},
                {'check': 'operator', 'blind': True, 'question': f'Is this {_lbl}, and only that? yes/no'},
            ],
            {'prompt': _lbl, 'task': 'Search every library in the index for this text and return the ranked top ten.'},
            state_note=(
                'yes needs a blind yes on the top hit in all three repeats. The bank renders this '
                'subject from a prompt; a library cannot, so the same 53 subjects are asked as a '
                'query and the column means "the library holds a usable one". CLAP is the SCREEN '
                '(2026-09-27: correct 0.827, chroma-only 0.279, null 0.252) and its score, the null '
                'baseline and the winning slate id go on every trial.'
            ),
        )
    )

# ── Finding it (7) ─────────────────────────────────────────────────────────────────────
PROBES += [
    _p(
        'semantic',
        'The twenty fixed queries find their sound',
        ['semantic'],
        [{'check': 'library_top1_in_key', 'key': KEYS}],
        {
            'prompt': KEYS + '#queries',
            'fixture': KEYS,
            'task': 'Run each of the twenty queries verbatim and return the ranked top ten ids.',
        },
        state_rule={'yes': 0.8, 'partial': 0.4},
        state_note='pass rate over the 20 queries: >= 16 of 20 with the top hit in `accept` is yes, >= 8 partial. BLOCKED until the key is verified.',
    ),
    _p(
        'precision',
        'The top hit is usable',
        ['precision'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'You asked for: "{query}". Is this recording a usable first choice for that, with no edit beyond a trim? yes/no',
            }
        ],
        {
            'prompt': KEYS + '#queries',
            'fixture': KEYS,
            'task': 'Play the TOP hit of each of the twenty queries, blind, in shuffled order.',
        },
        state_note='the OPERATOR decides. This is the column the sheet says has no number today ("CLAP is used as a pass/fail semantic check, never as a ranked retrieval bench"), and a blind listen is the only honest way to give it one.',
    ),
    _p(
        'recall_lib',
        'Finds everything relevant',
        ['recall_lib'],
        [{'check': 'recall_at_k_min', 'k': 10, 'min': 0.7, 'key': KEYS}],
        {
            'prompt': KEYS + '#queries',
            'fixture': KEYS,
            'task': "For each query take the top ten ids and score them against that query's `relevant` list.",
        },
        state_note='recall@10 >= 0.7 on a query is a pass; the column is the pass rate over the 20. BLOCKED until the key is verified.',
    ),
    _p(
        'near_dupe',
        'Surfaces variations, not duplicates',
        ['near_dupe'],
        [
            {'check': 'pairwise_corr_max', 'k': 10, 'max': 0.95},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Played one after another, are these ten takes ten different performances rather than the same recording filed several times? yes/no',
            },
        ],
        {
            'prompt': 'footsteps on wooden boards',
            'fixture': KEYS,
            'task': 'Take the top ten for the one near_dupe query and compare them pairwise.',
        },
        state_note='a pair above 0.95 normalised cross-correlation is the same recording, not a variation. Mechanical first, operator second; where they disagree the operator decides and both numbers stay on the trial.',
    ),
    _p(
        'by_example',
        'Search by a sound, not a word',
        ['by_example'],
        [{'check': 'by_example_self_rank', 'max': 1}],
        {
            'audio': KEYS + '#by_example',
            'fixture': KEYS,
            'task': "Query the index with each of the ten named files' own audio and read the rank of that file's own id.",
        },
        state_note='an audio-query index that cannot return the query itself at rank 1 is not an index. The column is the pass rate over the ten. BLOCKED until the ten ids are chosen and verified.',
    ),
    _p(
        'filters',
        'Filter by length, channels, rate',
        ['filters'],
        [{'check': 'filter_respected'}],
        {
            'prompt': KEYS + '#filters',
            'fixture': KEYS,
            'task': 'Apply each of the four filter clauses to the same broad query ("footsteps") and check every returned item against the clause.',
        },
        state_note='four clauses, each a pass/fail: duration <= 3 s, duration >= 30 s, stereo only, 48 kHz only. One item that violates its clause fails that clause. A filter the layer does NOT offer is a `no` on that clause, not an exemption — the operator writes what is missing in the note.',
    ),
    # ── the one universal column this step must own (see notes) ───────────────────────
    _p(
        'd_failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': 'Did the lookup return a value or raise a catchable exception, leaving the process alive and no sidecar rewritten, within 30 s? yes/no',
            },
            {
                'check': 'file_absent',
                'path': 'data/runtime/asset_library_sfx_meta.json.lock',
                'note': 'a lock file left behind after a failed lookup is a fail — the next writer would block on it',
            },
        ],
        {
            'task': (
                'query the row on a DELIBERATELY broken input three ways and record what came back: (1) query = '
                'the empty string; (2) audio query = capability_tests/fixtures/audio/judge/truncated.wav (the '
                "bank's WAV whose header claims 40 s over 0.2 s of data); (3) a filter clause naming a field the "
                'sidecar does not have (`field: "loudness_lufs_typo"`)'
            ),
            'fixture': FX + '/judge/truncated.wav',
        },
        state_note=(
            "the bank's u_failsafe, restated here because its input is declared under a key the validator "
            'does not accept (see notes), and because a library fails differently from a generator: the '
            'hazard is a half-written sidecar, not a leaked allocation. Three broken calls, all three must '
            'come back: yes = every call returned or raised something the caller can catch, the process is '
            'still up, the sidecars are byte-identical to before and no `.lock` is left; no = any hang past '
            '120 s, any crash, or a modified sidecar. This check is SIGHTED — it is about the process, not '
            'the sound.'
        ),
    ),
]

# ── the bands a library row cannot answer at all ───────────────────────────────────────
NA_BANDS_SLATES = {
    'reason': (
        'the slate index answers what the library SAYS it holds. Whether a file really is that '
        'sound is decided by the blind listen on the clap row, and a second disposition here '
        'would count the same evidence twice.'
    ),
    'bands': [
        'Makes: Human & movement',
        'Makes: Objects & work',
        'Makes: Nature & weather',
        'Makes: Animals',
        'Makes: Space & ambience',
    ],
}
NA_BANDS_VOCAL_FX = {
    'reason': (
        'the Vocal FX library is 1684 human mouth noises and nothing else (344 Audio Human Mouth '
        'Noises, purchased 2026-08-21). It holds no object, weather, animal or ambience recording '
        'at all, so these columns are not a failure of the library but a statement of its scope.'
    ),
    'bands': ['Makes: Objects & work', 'Makes: Nature & weather', 'Makes: Animals', 'Makes: Space & ambience'],
}

_FIND = ['semantic', 'precision', 'recall_lib', 'near_dupe', 'by_example']
_META = ['provenance', 'attribution_req', 'ai_clause', 'slate', 'tags', 'loudness_meta', 'dedupe', 'size']

NA_CLAP = {
    c: 'this is a property of the slate/metadata layer (asset_library_service.py sidecars), not of the CLAP search that ranks the audio; it is measured on the slates row'
    for c in _META + ['filters']
}
NA_SLATES = {
    c: 'this is a property of the CLAP retrieval engine, not of the slate index that stores the records; it is measured on the clap row'
    for c in _FIND
}
NA_VOCAL_FX = {
    c: 'the retrieval engine is one index over every library; measuring it again on one library would measure the engine twice, so the Finding-it columns stay on the clap and slates rows'
    for c in _FIND + ['filters']
}

TEST = {
    'step': 'sfx_library',
    'version': '2026-09-30.1',
    'title': "Twenty fixed queries and the bank's 53 labels asked of the house libraries",
    'purpose': (
        'Measure retrieval, not generation: whether a fixed text query returns a usable recording '
        'from the 2836 items the house holds, and whether every one of those items carries the '
        'licence, attribution and AI-training facts a commercial episode needs.'
    ),
    'include_shared': 'audio',
    'libraries': LIBRARIES,
    'rows': {
        'clap': {
            'transport': 'library',
            'where': 'audio_qc.qc_clap (laion/clap-htsat-fused) as called from kids_music_service.gate_audio:1774 and build_agony_bed.py; threshold 0.45 in production, ranked here',
            'na': NA_CLAP,
        },
        'slates': {
            'transport': 'library',
            'where': 'asset_library_service.get_audio_meta / set_audio_meta over data/runtime/asset_library_<cat>_meta.json; the :8899 SFX Library tab is the operator surface',
            'na': NA_SLATES,
            'na_bands': NA_BANDS_SLATES,
            'budget': {
                'calls': 25,
                'minutes': 4,
                'operator_minutes': 6,
                'note': 'a metadata pass over five sidecars (2836 records) plus the four filter clauses at 3 repeats; no CLAP sweep, so neither the index build nor the 159 Makes queries are paid on this row',
            },
        },
        'vocal_fx': {
            'transport': 'library',
            'where': 'data/asset_libraries/vocal_fx/ + data/runtime/asset_library_vocal_fx_meta.json — 1684 items, 344 Audio Limited, Sonniss 1-user licence, purchased 2026-08-21',
            'na': NA_VOCAL_FX,
            'na_bands': NA_BANDS_VOCAL_FX,
            'budget': {
                'calls': 70,
                'minutes': 8,
                'operator_minutes': 25,
                'note': "only the 13 human Makes columns at 3 repeats (39 queries) plus the rights pass over 1684 records; the other 40 subjects are out of this library's scope and are na",
            },
        },
    },
    'probes': PROBES,
    'derive': {
        'coverage': {
            'from': ['probe.make_*'],
            'rule': 'the COUNT of the 53 bank subjects whose make_* column came out yes on this '
            'row — how much of the standard sound list the library actually holds. '
            'Reported as "N of 53" and the missing ids are listed in the note',
            'unit': 'count',
            'grade': 'measured',
        },
        'slate': {
            'from': ['sidecar.records', 'library.files'],
            'rule': "share of files on disk in the row's libraries that have a sidecar record at "
            'all (metadata_share_min 1.0). A file with no record is un-cleared and '
            'ambience_ingest.license_gate blocks it at publish time, so anything below '
            '1.0 is a no, not a partial',
            'metadata_share_min': 1.0,
            'grade': 'receipt',
        },
        'tags': {
            'from': ['sidecar.records'],
            'rule': 'share of records whose descriptive values sit in a field of the controlled list '
            '(library_keys.json#tag_vocab: ucs_category, group, descriptor, sex, pack, '
            'pack_label, instrument, pitch, transform, license_id) rather than in free text '
            'inside `notes`. yes >= 0.9, partial >= 0.6',
            'tag_vocab_share_min': 0.9,
            'grade': 'receipt',
        },
        'loudness_meta': {
            'from': ['sidecar.records'],
            'rule': 'share of records carrying an integrated-loudness field (LUFS). The '
            'sfx sidecar records a free-text "mean_volume -25.1 dB" inside `notes` '
            'on some items; that is NOT a LUFS field and does not count',
            'metadata_share_min': 1.0,
            'grade': 'receipt',
        },
        'dedupe': {
            'from': ['library.files'],
            'rule': "sha256 every file in the row's libraries; the column is yes when no digest "
            'occurs twice (duplicate_hash_max 0). The duplicate ids are listed in the note',
            'duplicate_hash_max': 0,
            'unit': 'count',
            'grade': 'measured',
        },
        'size': {
            'from': ['library.files'],
            'rule': 'number of items the row indexes. Read 2026-09-30: sfx 95, foley 1049, '
            'vocal_fx 1684, soundtracks 2, merged 6 — 2836 across the index',
            'unit': 'count',
            'grade': 'measured',
        },
    },
    'lookup': {
        'provenance': {
            'question': 'Does every item carry its licence at FILE level — source, source_url, license_id, commercial_ok — and not just at pack level?',
            'requires': [
                'the sidecar path and the date it was read',
                'the count of records with a non-empty license_id, over the total',
                'the EULA file or URL each license_id resolves to',
            ],
            'metadata_share_min': 1.0,
            'grade': 'receipt',
            'note': 'the house rule is file-level, because a pack-level claim cannot survive a merge. sfx is mostly CC0 (archive.org licenseurl recorded per item); foley and vocal_fx are 344 Audio "royalty-free-verified" with the shipped EULA PDF path in the record.',
        },
        'attribution_req': {
            'question': 'Is the attribution obligation recorded per item, and does the record hold the exact credit line to print?',
            'requires': [
                'the sidecar path and the date it was read',
                'the count of records with attribution_required present, over the total',
                'for every record where it is true, the non-empty `attribution` string',
            ],
            'metadata_share_min': 1.0,
            'grade': 'receipt',
            'note': 'attribution_required is present and false on the 344 Audio and CC0 records read 2026-09-30; a true with an empty `attribution` string is a no, because an obligation without its wording cannot be met.',
        },
        'ai_clause': {
            'question': 'Is the AI-training clause recorded per item, and what does it say?',
            'requires': [
                'the sidecar path and the date it was read',
                'the count of records with no_ai_training present, over the total',
                'the EULA clause quoted, with the PDF path and the clause location',
            ],
            'grade': 'vendor',
            'answer_vocal_fx': 'no — every one of the 1684 vocal_fx records carries `no_ai_training: true` and `no_redistribute: true` (344 Audio Limited, Human Mouth Noises, purchased from Sonniss 2026-08-21, EULA at _originals/344_human_mouth_noises/Documentation/344-Audio-EULA-2025.pdf). The permission that IS granted is quoted in build_agony_bed.py: "You may modify, edit, and combine the Sounds" — DSP only. This is the first house library whose licence forbids exactly this, and a derived work inherits it (soundtracks/crowd_agony.wav carries the same two flags).',
            'note': 'the column is `yes` when the clause is RECORDED per item, whatever it says; the answer itself (may we / may we not) is the `ai_training` column. vocal_fx and foley record `true`, the CC0 sfx items record `false`, the instruments library records `false` — so the flag is real data, not a default.',
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': KEYS,
            'verified': False,
            'blocks': ['semantic', 'precision', 'recall_lib', 'by_example'],
            'how_to_verify': (
                'the operator opens the SFX Library tab, plays candidates for each of the 20 '
                'queries with the ranking hidden, fills `accept` (usable first hits) and '
                '`relevant` (belongs in a top ten) with slate ids, chooses the ten '
                '`by_example` files, then sets verified to true. Budget ~90 min once.'
            ),
        },
    ],
    'budget': {
        'calls': 530,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a library lookup spends no language-model tokens: the query is embedded by CLAP and the result is a ranked list of files',
        'minutes': 25,
        'gpu_minutes': 0,
        'operator_minutes': 160,
        'note': (
            'THIS MODULE: 53 Makes labels x 3 = 159 queries, the 20 fixed queries x 3 = 60 (semantic, '
            'precision and recall_lib read the SAME result lists), near_dupe 1 x 3, by_example 10 x 3 = 30, '
            'filters 4 x 3 = 12, one metadata pass over the five sidecars = 5 -> 269 calls. '
            'THE SHARED AUDIO BANK on this step: the four prompt bands (damage variants, the clarity '
            'ladder, the length ladder, the steering chain) and the capacity ladders, each run as a '
            'SEARCH rather than a render, ~260 more calls. A query costs ~0.6 s once the index exists; '
            'the index itself is CLAP-embedding 2836 items on CPU at ~0.4 s each = ~19 min, paid ONCE '
            "and counted here. gpu_minutes 0 because the house index is CPU (see the bank's "
            'transport_na for `library`). OPERATOR: 159 Makes + 60 precision + 3 near_dupe + ~100 blind '
            'listens in the bank = ~320 decisions x 30 s = 160 min, PLUS a one-time ~90 min filling '
            'library_keys.json (until then four columns are BLOCKED).'
        ),
    },
    'run_order': [
        'size',
        'dedupe',
        'slate',
        'tags',
        'loudness_meta',
        'provenance',
        'attribution_req',
        'ai_clause',
        'filters',
        'near_dupe',
        'by_example',
        'semantic',
        'recall_lib',
        'precision',
        'make_*',
        'shared bank',
    ],
    'notes': [
        'The sheet\'s recorded limitation is the reason this test exists: "CLAP is used as a pass/fail '
        'semantic check, never as a ranked retrieval bench, so is the top hit usable has no number." '
        'Every Finding-it probe here reads a RANKED list, which is a use of CLAP the house does not yet '
        'have wired — the runner must add it, and until it does these columns are untested, not no.',
        "The Makes band is overridden for this step only. Its probe ids are the bank's (make_<subject>) "
        "so the bank's derive entries that name them still resolve, and the operator question is the "
        "bank's word for word, so a library row and a generator row stay comparable on the same column.",
        'The Capacity ladders are left to the shared bank. acap_words, acap_voices and acap_instruments '
        'read oddly for a lookup, but the bank owns them for all fifteen audio steps and rewriting them '
        'here would make this sheet incomparable with the others; the library exemptions the bank DID '
        'write (acap_variations, pd_seed_vs_prompt, deterministic, vram, pd_negative_len, pd_weight_range) '
        'come in through transport_na for `library`.',
        "`failsafe` is owned here, not by the bank. The bank's u_failsafe declares its input under a key "
        'the validator does not count as a fixed input, so merging it produces "probe u_failsafe: no fixed '
        'input". The local d_failsafe is that probe restated with the input under `task` + `fixture`, and '
        "with the library's own failure mode substituted for the generator's: a half-written sidecar or a "
        'stranded `.lock`, not leaked VRAM.',
    ],
}
