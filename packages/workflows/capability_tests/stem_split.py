# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Stem separation (stem_split). 2026-09-30.

Question the sheet asks: can we pull a clean vocal out of a generated song?

Today the sheet has no verdict at all. Its only note says the evidence is indirect — the
voice-conversion bench passed DOWNSTREAM of the split, which bounds the split from below and
measures nothing. This test makes the truth knowable the one way it can be made knowable:
we MIX the fixture ourselves. The house score render (kids_music_theory / melody_sampler,
one WAV per role) gives exact drums, bass and other; a sung take is laid over them at a
known level; the sum is the mix the splitter is given. Every SDR below is then measured
against a stem we wrote, not against a guess.

WHAT THE CODE ACTUALLY DOES (tools/demucs_split.py, read 2026-09-30)
    htdemucs returns FOUR sources — drums, bass, other, vocals (line 82). The house wrapper
    keeps `vocals` and SUMS the other three into `no_vocals.wav` (line 84). So three of this
    sheet's four separation columns are asked of a capability the production path throws
    away. The probes measure all four off the model's own output, and `wired`/the notes say
    which two production actually consumes — that distinction is the point of the sheet.

    Two more facts fall out of the same read and decide two columns before anyone runs
    anything. The wrapper decodes through ffmpeg to the MODEL's rate and channel count
    (`sr_model = model.samplerate` = 44100, `ch_model` = 2, lines 40-47) and writes
    `subtype='PCM_16'` (lines 89-91). A 48 kHz mono float input therefore comes back 44.1 kHz
    stereo 16-bit: `sr_keep` is a measured NO on the house path unless the input was already
    44.1 kHz, and `length_keep` can only be asked in SECONDS, because the sample count changes
    with the rate. The probes are written to measure exactly that rather than to be passed.

WHAT IS HONESTLY BLOCKED
    The truth vocal. There is no genuinely dry sung take on this box: every sung vocal we hold
    has already been through demucs once. Measuring demucs against a demucs output flatters
    it, so `vocal` is BLOCKED until the operator has looked at the truth stem's spectrogram
    and listened for bleed. Drums, bass and backing are not blocked — their truth comes out of
    the sampler and is exact to the sample. `harmony_vox` and `reverb` are built from the same
    imperfect vocal, so on those columns the BLIND operator check decides and the SDR is
    reported beside it as a number with a known bias, written into the note.

    No local model is asked whether a split "sounds clean": `artefacts`, and the deciding half
    of `harmony_vox`, `reverb` and `generated`, are blind operator checks. Everything else has
    a meter — museval BSS-Eval v4 for SDR, a sample-aligned residual for phase, an RMS ratio
    over the truth's silent bars for bleed, librosa onsets for realignment, ffprobe for rate
    and length.

This step asks no prompt questions at all (47 columns: Separation, Downstream, Capacity and
the universal bands). Capacity and the universal columns come from the shared audio bank.
"""

from __future__ import annotations

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'sdr_min': 'BSS-Eval v4 SDR (museval, 1 s frames, median over frames) of the returned `stem` against the TRUTH stem it was mixed from >= `min` dB',
    'sum_residual_db_max': 'peak level of (sum of every returned stem - the decoded input mix), sample-aligned, <= `max` dBFS; the comparison is against the mix AS DECODED by the wrapper (44.1 kHz stereo), not against the original file',
    'bleed_db_max': "RMS of the `stem` stem over the frames where `absent` is silent in the TRUTH, relative to that stem's own full-file RMS, <= `max` dB",
    'onset_align_ms_max': 'median |onset(returned stem) - onset(truth stem)| over librosa onsets matched nearest-neighbour within 200 ms <= `max` ms, on >= `share` of the truth onsets',
    'lufs_delta_max': '|integrated loudness(returned stem) - integrated loudness(truth stem)| (BS.1770-4) <= `max` LU',
    'ffprobe_rate_equal': "ffprobe sample_rate of every returned stem equals the INPUT file's sample_rate exactly",
    'ffprobe_seconds_equal': "ffprobe duration of every returned stem equals the input's within `tolerance` seconds",
    'ffprobe_samples_equal': "ffprobe duration_ts (samples) of every returned stem equals the input's within `tolerance` samples",
    'ffprobe_channels_equal': "ffprobe channel count of every returned stem equals the input file's",
}

FX = 'capability_tests/fixtures/audio/stem_split'

# The mix we made ourselves, and the four stems it was made from. The three instrument stems
# are exact: they are the sampler's own per-role renders, summed at fixed gains.
MIX = FX + '/truth4_mix.wav'
TRUTH = {
    'drums': FX + '/truth4_drums.wav',
    'bass': FX + '/truth4_bass.wav',
    'other': FX + '/truth4_other.wav',
    'vocals': FX + '/truth4_vocals.wav',
}
BACKING_TRUTH = FX + '/truth4_backing.wav'  # drums + bass + other, the wrapper's `rest`
HARMONY = FX + '/harmony_mix.wav'
HARMONY_VOX = FX + '/harmony_vocals.wav'
REVERB = FX + '/reverb_mix.wav'
REVERB_VOX = FX + '/reverb_vocals.wav'
GENERATED = FX + '/generated_song.wav'
MIX_48K = FX + '/truth4_mix_48k_mono.wav'  # the same mix, 48 kHz mono, for sr_keep

MIX_RECIPE = (
    'render one kids-music job with kids_music_theory + melody_sampler keeping the per-role WAVs '
    '(render_role writes lead / bass / perc / extra separately), map lead+extra -> other, perc -> drums, bass -> bass; '
    "take the separated vocal of output/kidsmusic/c7284ed06145 as the vocal layer; sum at the song's own recorded "
    'vocal_db balance (calibration.json level_line_vocal_over_backing_db p50 -2.1 dB) into truth4_mix.wav at 44.1 kHz stereo, '
    'and write each layer out unchanged beside it. The gains are written into the fixture record so the mix is reproducible to the sample.'
)

ROW = ['htdemucs']

# One split is nominally deterministic, but every call is a fresh subprocess that reloads the
# model and may fall back to CPU on OOM (tools/demucs_split.py:70-79) — which is a different
# numerical path. Three repeats is what makes that visible rather than assumed.
COND = {
    'repeats': 3,
    'device': 'cuda',
    'overlap': 0.25,
    'split': True,
    'note': "the wrapper's own settings; the CPU fallback on OutOfMemoryError is a different numerical path and the repeats are what expose it",
}


def _p(pid, title, feeds, checks, audio=MIX, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'audio': audio, 'fixture': FX + '/RECORD.json', 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': ROW,
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'vocal',
        'The vocal stem is usable',
        ['vocal'],
        [
            {'check': 'sdr_min', 'stem': 'vocals', 'min': 6.0},
            {
                'check': 'bleed_db_max',
                'stem': 'vocals',
                'absent': 'vocals',
                'max': -30.0,
                'note': "over the truth's vocal-silent bars the vocal stem should be 30 dB down on itself",
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Listening to this vocal stem once: could you put it into a mix as it is, or does something have to be fixed first? yes = usable as it is',
            },
        ],
        state_rule={'yes': 0.8, 'partial': 0.4},
        state_note=(
            '6 dB SDR is the bar because that is roughly where the MUSDB18 leaderboard put htdemucs on vocals; this fixture is easier '
            '(four clean layers, no room, no bus compression) so anything below it is a real problem. BLOCKED: the truth vocal is itself a demucs '
            'output, so this SDR is an UPPER BOUND until the operator has checked it (see fixtures).'
        ),
    ),
    _p(
        'backing',
        'The backing stem is usable',
        ['backing'],
        [
            {'check': 'sdr_min', 'stem': 'no_vocals', 'min': 8.0, 'truth': BACKING_TRUTH},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Listening to this backing stem once: does the song still stand up without the voice, or is there a hole where the voice was? yes = it stands up',
            },
        ],
        state_note='this is the column production actually depends on: the wrapper ships vocals.wav and no_vocals.wav and nothing else. Its truth is exact (the sum of the three sampler stems), so unlike `vocal` it is not blocked',
    ),
    _p(
        'drums',
        'Drums come out clean',
        ['drums'],
        [
            {'check': 'sdr_min', 'stem': 'drums', 'min': 7.0},
            {'check': 'bleed_db_max', 'stem': 'drums', 'absent': 'drums', 'max': -30.0},
        ],
        state_note="measured off the model's four-source output. The HOUSE WRAPPER discards this stem (tools/demucs_split.py:84 sums drums+bass+other into `rest`), so a yes here is a capability we own and do not use",
    ),
    _p(
        'bass',
        'Bass comes out clean',
        ['bass'],
        [
            {'check': 'sdr_min', 'stem': 'bass', 'min': 6.0},
            {'check': 'bleed_db_max', 'stem': 'bass', 'absent': 'bass', 'max': -30.0},
        ],
        state_note='as drums: measured off the four-source output, discarded by the wrapper. Bass is the stem the sampler renders most cleanly, so a low number here points at the splitter, not at the fixture',
    ),
    _p(
        'artefacts',
        'No audible split artefacts',
        ['artefacts'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Listening to this 20-second stem excerpt once: do you hear a separation artefact — watery swirling, a gated stutter, a phasey smear on a cymbal or an s? yes/no (yes = there IS an artefact, which fails)',
            },
            {
                'check': 'noise_floor_max',
                'max': -60.0,
                'note': 'the mechanical half: a leaked broadband floor is what the ear calls "watery"',
            },
        ],
        state_rule={'yes': 0.9, 'partial': 0.5},
        state_note='three 20 s excerpts (vocal, backing, drums) x 3 repeats, shuffled into one unlabelled pile with three excerpts of the TRUTH stems as the anchor. If the truth stems are flagged at the same rate the flags are noise and the column is untested, not a yes',
    ),
    _p(
        'bleed',
        'No bleed between stems',
        ['bleed'],
        [
            {
                'check': 'bleed_db_max',
                'stem': 'no_vocals',
                'absent': 'vocals',
                'max': -40.0,
                'note': "the brief's number: over the bars where the truth vocal is silent, the vocal energy that reached the BACKING stem must be 40 dB down",
            },
            {'check': 'bleed_db_max', 'stem': 'vocals', 'absent': 'vocals', 'max': -40.0},
        ],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='both directions must pass. Bleed is the failure the downstream conversion bench cannot see: RVC happily converts a backing leak into a warbling ghost and ship_check still measures a melody',
    ),
    _p(
        'phase',
        'The stems sum back to the mix',
        ['phase'],
        [{'check': 'sum_residual_db_max', 'max': -50.0}],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'htdemucs is a waveform model, not a mask, so the four sources are NOT guaranteed to sum to the input. The comparison is against the mix AS THE WRAPPER DECODED IT '
            "(44.1 kHz stereo) — comparing against the original file would measure ffmpeg's resampler. PCM_16 output puts a quantisation floor near -90 dBFS, well under the bar"
        ),
    ),
    _p(
        'realign',
        'The stem goes back into the mix where it came from',
        ['realign'],
        [
            {'check': 'onset_align_ms_max', 'max': 10, 'share': 0.95},
            {'check': 'lufs_delta_max', 'max': 1.0, 'stem': 'vocals'},
        ],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='the splitter must not shift or re-level anything — 10 ms is already generous for a model that works on the waveform. This is what voice_conversion.realign inherits: a converted stem cannot land in the mix if the split it came from had already moved',
    ),
    _p(
        'harmony_vox',
        'Stacked harmony vocals',
        ['harmony_vox'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'This vocal stem came from a three-part stacked harmony. Are all three parts present and intact, or has the splitter kept the lead and thinned or dropped the harmonies? yes = all three are there',
            },
            {
                'check': 'sdr_min',
                'stem': 'vocals',
                'min': 4.0,
                'truth': HARMONY_VOX,
                'note': 'reported beside the operator, not decisive: the truth vocal carries the same separation bias as truth4_vocals',
            },
        ],
        audio=HARMONY,
        state_note='the operator decides this column. A splitter trained on lead-plus-band routinely treats a third above the lead as "other", and the SDR barely moves when it does — which is exactly why the number cannot be the judge here',
    ),
    _p(
        'reverb',
        'A wet vocal',
        ['reverb'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'This vocal stem came from a vocal with a long plate reverb on it. Does the tail come out WITH the voice, or has it been left behind in the backing (the stem sounds dry and clipped short)? yes = the tail came with it',
            },
            {
                'check': 'rt60_range',
                'min': 0.8,
                'max': 1.6,
                'note': 'the plate is built at RT60 ~1.2 s; a stem that measures dry has left the tail in the backing',
            },
            {
                'check': 'sdr_min',
                'stem': 'vocals',
                'min': 3.0,
                'truth': REVERB_VOX,
                'note': 'reported, not decisive — same bias as harmony_vox',
            },
        ],
        audio=REVERB,
        state_note='there is no right answer in the abstract — a dry vocal is what conversion wants and a wet one is what a remix wants. The column records WHICH it does, consistently, so the caller knows. The house need is dry, so "tail left behind" is recorded as a yes with the note',
    ),
    _p(
        'generated',
        'Works on generated audio, not just recordings',
        ['generated'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'This vocal stem came from an ACE-Step song. Is it as clean as the stem from the hand-mixed fixture you heard earlier, or noticeably worse? yes = as clean',
            },
            {
                'check': 'bleed_db_max',
                'stem': 'vocals',
                'absent': 'vocals',
                'max': -30.0,
                'note': 'the generated song has no truth stems, so the silent-bar test is run against the operator-marked instrumental bars in the fixture record',
            },
        ],
        audio=GENERATED,
        state_note="this is the step's real workload — every stem the house splits comes out of ACE-Step, not out of a studio. No SDR is possible (nobody mixed it), so the column is an operator call plus the one mechanical test that needs no truth stem",
    ),
    _p(
        'sr_keep',
        'Keeps the sample rate',
        ['sr_keep'],
        [{'check': 'ffprobe_rate_equal'}, {'check': 'ffprobe_channels_equal'}],
        audio=MIX_48K,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'EXPECTED NO on the house path, and the probe exists to record it rather than to be passed. tools/demucs_split.py:40-47 decodes through ffmpeg to '
            '`model.samplerate` (44100) and `model.audio_channels` (2), and lines 89-91 write PCM_16. A 48 kHz mono float input comes back 44.1 kHz stereo 16-bit. '
            'The 48 kHz mono fixture is used here precisely because the 44.1 kHz stereo one would hide it'
        ),
    ),
    _p(
        'length_keep',
        'Keeps the length exactly',
        ['length_keep'],
        [{'check': 'ffprobe_samples_equal', 'tolerance': 1}, {'check': 'ffprobe_seconds_equal', 'tolerance': 0.001}],
        audio=MIX,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'run on the 44.1 kHz fixture, where samples and seconds are the same question — on the 48 kHz one the sample count cannot be kept because the rate is not '
            '(see sr_keep), and a sheet that scored length on a resampled file would be scoring the resampler. `split=True, overlap=0.25` is supposed to reassemble to '
            'the input length exactly; +/- 1 sample is the whole tolerance'
        ),
    ),
    # `failsafe` is owned here, not by the bank. The bank's u_failsafe declares its input under
    # `inputs.command`, which validate_shared accepts and the step validator does not, so a step
    # that leaves this column to the bank cannot pass `check`. Owning it also lets the broken
    # input be the shape this step breaks on.
    _p(
        'failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': 'Did the call print its one JSON line with ok=false and an error, leaving the process alive and the VRAM released within 30 s? yes/no',
            },
            {
                'check': 'file_absent',
                'path': FX + '/_fail/vocals.wav',
                'note': 'a half-written stem in the output directory is a fail: the caller checks for the file, not for ok',
            },
        ],
        audio=[
            "capability_tests/fixtures/audio/judge/truncated.wav (the bank's broken WAV: a header claiming 40 s over 0.2 s of data)",
            'a path that does not exist — the ffmpeg decode must fail into the JSON line, not into a traceback',
            'the 44.1 kHz mix while ComfyUI holds the card, to force the OutOfMemoryError branch at tools/demucs_split.py:70-79',
        ],
        conditions={'repeats': 3, 'note': 'three broken calls, one each; all three must come back over stdout as JSON'},
        state_rule={'yes': 1.0, 'partial': 0.34},
        state_note='sighted, not blind. The third case is the one that matters in production: the wrapper already falls back to CPU on OOM because ComfyUI holds 45.4 of 47.4 GiB between jobs, and the singer gate fails CLOSED if the split dies — a song would lose its produced leg for a reason that has nothing to do with the song',
    ),
]

TEST = {
    'step': 'stem_split',
    'version': '2026-09-30.1',
    'title': 'A mix we made ourselves, split four ways and measured against its own layers',
    'purpose': (
        "Replace the sheet's indirect evidence (the conversion bench passed downstream) with SDR against stems we wrote, "
        'and record on the sheet the two things the code decides before any run: three of the four sources are thrown away, and the rate is not kept.'
    ),
    'include_shared': 'audio',
    'house_path': {
        'where': 'tools/demucs_split.py — htdemucs via the demucs model API in the agents venv, as a subprocess over stdout JSON',
        'returns': ['vocals.wav', 'no_vocals.wav'],
        'model_sources': ['drums', 'bass', 'other', 'vocals'],
        'note': (
            'the wrapper sums drums+bass+other into no_vocals.wav (line 84); the demucs CLI is deliberately unused because its writer goes through '
            'torchaudio save_with_torchcodec, which raises ImportError on this box. Output is 44.1 kHz stereo PCM_16 regardless of the input.'
        ),
    },
    'rows': {
        'htdemucs': {
            'transport': 'service',
            'where': 'tools/demucs_split.py main() — `get_model("htdemucs")` + `apply_model(split=True, overlap=0.25)`, CUDA first with a CPU fallback on OutOfMemoryError',
            'model': 'htdemucs (Demucs v4 hybrid transformer, the bundled pretrained weights)',
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [
        {'path': MIX, 'verified': True, 'generated': MIX_RECIPE},
        {
            'path': TRUTH['drums'],
            'verified': True,
            'generated': "the sampler's perc role render, written out unchanged — exact to the sample, because we mixed it",
        },
        {'path': TRUTH['bass'], 'verified': True, 'generated': "the sampler's bass role render, written out unchanged"},
        {
            'path': TRUTH['other'],
            'verified': True,
            'generated': "the sampler's lead + extra role renders summed, written out unchanged",
        },
        {
            'path': BACKING_TRUTH,
            'verified': True,
            'generated': "drums + bass + other summed at the same gains — the truth for the wrapper's `rest`",
        },
        {
            'path': TRUTH['vocals'],
            'verified': False,
            'blocks': ['vocal'],
            'generated': "the separated vocal of output/kidsmusic/c7284ed06145, level-matched to the song's recorded vocal_db before it is summed into the mix",
            'how_to_verify': (
                'there is no dry sung take on this box: this truth vocal has already been through demucs once, so measuring demucs against it flatters it. '
                'Open it in a spectrogram, look for the tell-tale high-band notch and for backing energy in the vocal-silent bars, and listen to the silent bars. '
                'If it is clean, set verified = true and the SDR stands. If it is not, it is an UPPER BOUND and the flag stays down. The real fix is a dry take: '
                'record or synthesise one sung line that has never been separated, and rebuild the fixture around it.'
            ),
        },
        {
            'path': MIX_48K,
            'verified': True,
            'generated': 'ffmpeg -i truth4_mix.wav -ar 48000 -ac 1 -c:a pcm_f32le truth4_mix_48k_mono.wav — the same music at the rate the rest of the house works in, so sr_keep is asked where it can fail',
        },
        {
            'path': HARMONY,
            'verified': True,
            'generated': "the same backing with a three-part stacked harmony over it: render the melody line plus a third and a sixth above through melody_sampler's voice roles, sum to harmony_vocals.wav, add to the backing at the same -2.1 dB balance",
        },
        {
            'path': HARMONY_VOX,
            'verified': True,
            'generated': 'the three harmony parts summed, written out unchanged — the truth for harmony_mix',
        },
        {
            'path': REVERB,
            'verified': True,
            'generated': 'truth4_vocals through a plate impulse at RT60 ~1.2 s (sox reverb or the house sfx_process reverb), written to reverb_vocals.wav, then summed onto the same backing',
        },
        {'path': REVERB_VOX, 'verified': True, 'generated': 'the wet vocal on its own — the truth for reverb_mix'},
        {
            'path': GENERATED,
            'verified': False,
            'blocks': [],
            'generated': 'one ACE-Step song rendered through ace_step_service at the house 60 s bed length, kept as the mix with NO truth stems (nobody mixed it — that is the point of the column)',
            'how_to_verify': 'mark the instrumental bars (where no voice sings) in the fixture record; the bleed check needs them and nothing else here does. Not a blocker: the column is decided by the operator.',
        },
        {
            'path': FX + '/RECORD.json',
            'verified': False,
            'blocks': ['generated'],
            'generated': 'written by the same script that builds the fixtures: the per-layer gains, the vocal-silent bar list for the truth mix, the instrumental bar list for the generated song, and the sha256 of every wav above',
            'how_to_verify': "the bar lists are the operator's: play the two mixes and write down where the voice is not singing. Until they exist the bleed checks have no windows to measure over.",
        },
    ],
    'budget': {
        'calls': 144,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a separator takes a wav and returns wavs; no language model is called anywhere on this step, so no tokens and no Claude week are spent',
        'minutes': 96,
        'gpu_minutes': 78,
        'operator_minutes': 16,
        'note': (
            "One row. This test's own probes: 5 fixtures (truth mix, 48 kHz mix, harmony, reverb, generated) x 3 repeats = 15 splits, plus 3 failsafe calls = 18 calls. "
            'Each call is a FRESH SUBPROCESS, so the ~20 s htdemucs load is paid every time and is not amortised: ~20 s load + ~15 s apply on a 2-minute song = ~35 s x 18 = ~11 min GPU. '
            'museval BSS-Eval v4 is CPU and slow, ~40 s per scored item x 15 = ~10 min wall off the card. '
            'SHARED AUDIO BANK for this step: 10 bank probes fire (this step asks NO prompt band — 47 columns, not 105), and they are the 7 Capacity ladders plus the universal ones. '
            'A ladder is ~6 rungs x 3 seeds = 18 splits, so 7 x 18 = 126 splits at ~35 s = ~74 min GPU. That is where four fifths of the cost is, and it buys 7 columns. '
            'Total ~144 calls, ~78 GPU min, ~96 min wall. '
            'Operator: artefacts 3 excerpts x 3 repeats = 9, plus harmony 3, reverb 3, generated 3, backing 3, vocal 3, failsafe 3 = 27 decisions at 30 s = ~14 min, rounded to 16 for the shuffle. '
            'NOT included and one-time: building the fixtures (~30 min of renders and ffmpeg) and the operator marking the two bar lists in RECORD.json (~20 min), '
            'without which `vocal` and `generated` stay BLOCKED.'
        ),
    },
    'run_order': [
        'phase',
        'sr_keep',
        'length_keep',
        'realign',
        'bleed',
        'backing',
        'drums',
        'bass',
        'vocal',
        'generated',
        'harmony_vox',
        'reverb',
        'artefacts',
    ],
    'notes': [
        'The truth is known because we mixed it. Every SDR here is against a stem written out of the same script that built the mix, at gains recorded in RECORD.json — not against a public test set and not against a judgement.',
        'phase, sr_keep and length_keep run first and cost one split between them: they are answered off the very first call, and two of them are already decided by a code read (the wrapper resamples to 44.1 kHz stereo PCM_16). A run stopped after ten minutes still fills four columns.',
        'Three of the four separation columns are asked of a capability production throws away — the wrapper ships two stems. That is not a reason to skip them: the sheet exists to say what the house COULD do, and `wired` is the column that says what it does.',
        'bleed is the column the existing indirect evidence cannot reach. The conversion bench passed downstream of the split, but RVC converts a backing leak into a warbling ghost and ship_check measures its melody quite happily. A downstream pass is not an upstream measurement.',
        'The capacity ladders from the bank cost four fifths of this test for seven columns. If the operator is scheduling a partial run, run_order and the budget note are there so that choice is made with the numbers in front of them.',
    ],
}
