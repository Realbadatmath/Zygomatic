# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""abel_voice.py — Abel's narrator voice + scene-audio driver (2026-07-30).

The narrator voice is a TWO-STAGE asset (research 2026-07-30, all license-verified):
  1. Maya1 (Apache-2.0, isolated venv) DESIGNS the voice once from a text description
     ("teenage boy ~15, calm, measured, weathered") -> candidate takes -> the best one is
     frozen as the canonical seed sample (abel_narrator_seed.wav). Voice identity lives
     in that FILE, not in a model preset.
  2. Chatterbox (MIT, isolated venv) CLONES the frozen seed for all production narration.
     Per-segment synthesis (the pause map needs it) only keeps one consistent voice
     because the seed is frozen.
Fallback tier: IndexTTS-2 (the house primary since 2026-08-06) clones the same frozen
seed via tts_service, so a fallback render keeps Abel's voice identity.

Scene audio chain (audio_mix.py): stem loudnorm -16 LUFS -> license-gated ambience bed
~20 LU under voice -> sidechain duck (slow 600 ms release so the waves swell into the
scripted beats) -> frame-locked fade -> master -14 LUFS. QC via audio_qc.run_stem_gates
/ run_master_gates / qc_clap.

Workers are SUBPROCESSES in their own venvs (NeMo-diarization pattern) — the production
venv never imports chatterbox/maya1 torch stacks.
"""

import json
import os
import subprocess
import time
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))

_CHATTERBOX_DIR = str(paths.ZYG_LEGACY_MODELS / 'tts_chatterbox')
_CHATTERBOX_PY = os.path.join(_CHATTERBOX_DIR, '.venv', 'bin', 'python')
_CHATTERBOX_WORKER = os.path.join(_CHATTERBOX_DIR, 'chatterbox_worker.py')
_MAYA1_DIR = str(paths.ZYG_MODELS_DIR / 'tts_maya1')
_MAYA1_PY = os.path.join(_MAYA1_DIR, '.venv', 'bin', 'python')
_MAYA1_WORKER = os.path.join(_MAYA1_DIR, 'maya1_worker.py')

_SEED_DIR = os.path.join(_HERE, 'data', 'assets', 'voice_seeds')
ABEL_SEED_WAV = os.path.join(_SEED_DIR, 'abel_narrator_seed.wav')
# Identity is checked against a known-good RENDER, not the seed: the seed is
# DSP-pitch-shifted audio, and its formants measure differently from what the
# model re-synthesises (seed 13.87 cm vs render 11.99 cm), so gating the render
# against the seed fails every time on a voice that is actually correct.
ABEL_IDENTITY_REF = os.path.join(_SEED_DIR, 'abel_identity_reference.wav')

# Abel is TWELVE in the story, but the operator chose a 14-15 year-old VOICE
# (2026-08-06): the twelve-year-old render read too young for narration this
# grave. Story age and voice age are deliberately different.
ABEL_VOICE_DESCRIPTION = (
    'teenage boy, about fifteen, calm, low-key, measured, thoughtful, slightly weathered, quiet authority'
)

# The 1672 opening narration — segments split at the scripted beats (pause map).
ABEL_SEGMENTS_1672 = [
    {'text': 'What we speak is not to be written.', 'pause_after': 'paragraph'},
    {
        'text': 'What we write is not to be spoken; therefore, I will tread carefully in the telling of our journey.',
        'pause_after': 'scene_break',
    },
    {'text': 'In the year of 1672...', 'pause_after': None},
]
ABEL_SCRIPT_1672 = ' '.join(s['text'] for s in ABEL_SEGMENTS_1672)


def _log_noop(_m):
    pass


def _last_json_line(stdout_text):
    for line in reversed((stdout_text or '').strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('non-JSON stdout line skipped: %s', _exc)
                continue
    return None


# ---------------------------------------------------------------- chatterbox
def chatterbox_synth_segment(
    text,
    out_wav,
    ref=None,
    exaggeration=0.3,
    cfg_weight=0.4,
    temperature=0.7,
    seed=1672,
    device='cpu',
    timeout=900,
    log_fn=None,
    **_ignored,
):
    """Hook consumed by narration_service (engine='chatterbox'). Subprocess into the
    isolated MIT Chatterbox venv; returns out_wav or None. Default ref is the frozen
    Abel seed when present."""
    log = log_fn or _log_noop
    if not (os.path.isfile(_CHATTERBOX_PY) and os.path.isfile(_CHATTERBOX_WORKER)):
        log('[abel] chatterbox venv/worker missing')
        return None
    if ref is None and os.path.isfile(ABEL_SEED_WAV):
        ref = ABEL_SEED_WAV
    cmd = [
        _CHATTERBOX_PY,
        _CHATTERBOX_WORKER,
        '--text',
        text,
        '--out',
        out_wav,
        '--exaggeration',
        str(exaggeration),
        '--cfg-weight',
        str(cfg_weight),
        '--temperature',
        str(temperature),
        '--seed',
        str(seed),
        '--device',
        device,
    ]
    if ref:
        cmd += ['--ref', ref]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log('[abel] chatterbox worker timeout')
        return None
    res = _last_json_line(r.stdout)
    if not (res and res.get('ok')):
        # Native fd-1 writes (CUDA banners etc.) can mangle the JSON line; fall back
        # to artifact evidence when the worker exited cleanly and the wav exists.
        if res is None and r.returncode == 0 and os.path.isfile(out_wav) and os.path.getsize(out_wav) > 44:
            log('[abel] chatterbox worker stdout unparseable but rc=0 and wav present — accepting (JSON-parse anomaly)')
            return out_wav
        log(f'[abel] chatterbox worker failed: {(res or {}).get("error") or (r.stderr or "")[-300:]}')
        return None
    return out_wav if os.path.isfile(out_wav) else None


# ---------------------------------------------------------------- maya1 seed design
def maya1_design_candidates(
    out_dir,
    description=ABEL_VOICE_DESCRIPTION,
    calibration_text=None,
    seeds=(11, 23, 47, 89, 131, 167),
    device='cuda',
    timeout=900,
    log_fn=None,
):
    """One-off GPU batch: N Maya1 takes of a calibration paragraph. Returns candidate
    wav paths. The OPERATOR auditions and freezes the winner via freeze_abel_seed()."""
    log = log_fn or _log_noop
    if not (os.path.isfile(_MAYA1_PY) and os.path.isfile(_MAYA1_WORKER)):
        log('[abel] maya1 venv/worker missing')
        return []
    text = calibration_text or (
        'The harbour was quiet that morning. I counted the barrels twice, '
        'as my father taught me, and wrote each number in the ledger. '
        'The sea does not forgive a careless hand.'
    )
    os.makedirs(out_dir, exist_ok=True)
    out = []
    for sd in seeds:
        wav = os.path.join(out_dir, f'abel_candidate_seed{sd}.wav')
        try:
            r = subprocess.run(
                [
                    _MAYA1_PY,
                    _MAYA1_WORKER,
                    '--description',
                    description,
                    '--text',
                    text,
                    '--out',
                    wav,
                    '--seed',
                    str(sd),
                    '--device',
                    device,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            log(f'[abel] maya1 seed {sd}: timeout')
            continue
        res = _last_json_line(r.stdout)
        if res and res.get('ok') and res.get('truncated'):
            # hit the token cap mid-speech — clipped audio must never seed the voice
            log(f'[abel] maya1 seed {sd}: TRUNCATED at token cap — discarded')
            continue
        if res and res.get('ok') and os.path.isfile(wav):
            out.append(wav)
            log(f'[abel] maya1 candidate seed={sd} ({res.get("duration_s", 0):.1f}s)')
        elif res is None and r.returncode == 0 and os.path.isfile(wav) and os.path.getsize(wav) > 44:
            # Native fd-1 writes can mangle the JSON line; artifact evidence wins.
            out.append(wav)
            log(
                f'[abel] maya1 seed {sd}: worker stdout unparseable but rc=0 and '
                'wav present — accepting (JSON-parse anomaly)'
            )
        else:
            log(f'[abel] maya1 seed {sd} failed: {(res or {}).get("error") or (r.stderr or "")[-200:]}')
    return out


def rank_seed_candidates(candidates, calibration_text=None, log_fn=None):
    """Objective pre-ranking for the operator: transcript match + duration sanity +
    loudness sanity. AESTHETIC choice stays with the operator."""
    from zyg_workflows import audio_qc

    log = log_fn or _log_noop
    text = calibration_text or ''
    ranked = []
    for wav in candidates:
        score, notes = 0.0, []
        wpm = audio_qc.qc_wpm(wav, text, wpm_range=(90, 190)) if text else {'ok': None}
        if wpm.get('match_ratio') is not None:
            score += wpm['match_ratio']
            notes.append(f'match {wpm["match_ratio"]:.2f}')
        loud = audio_qc.measure_loudness(wav)
        if loud.get('ok') and loud.get('lufs') is not None and loud['lufs'] > -45:
            score += 0.2
        ranked.append({'wav': wav, 'score': round(score, 3), 'notes': ', '.join(notes)})
        log(f'[abel] candidate {os.path.basename(wav)} score={score:.2f}')
    return sorted(ranked, key=lambda r: -r['score'])


def freeze_abel_seed(wav_path, log_fn=None):
    """Freeze the chosen take as THE canonical Abel seed: light denoise, EDGE-ONLY
    trim (leading + trailing via the areverse trick — a plain stop_periods=1 would
    cut at the FIRST internal sentence pause), -20 LUFS, 24k mono. A >=0.8x duration
    sanity guard rejects any freeze that ate speech. Provenance sidecar records
    engine + license."""
    from zyg_workflows import audio_mix

    log = log_fn or _log_noop
    os.makedirs(_SEED_DIR, exist_ok=True)
    tmp = ABEL_SEED_WAV + '.tmp.wav'
    r = subprocess.run(
        [
            'ffmpeg',
            '-y',
            '-loglevel',
            'error',
            '-i',
            wav_path,
            '-af',
            'afftdn=nf=-28,'
            'silenceremove=start_periods=1:start_threshold=-45dB,'
            'areverse,'
            'silenceremove=start_periods=1:start_threshold=-45dB,'
            'areverse,loudnorm=I=-20:TP=-2',
            '-ar',
            '24000',
            '-ac',
            '1',
            tmp,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not os.path.isfile(tmp):
        log(f'[abel] seed freeze failed: {(r.stderr or "")[-200:]}')
        return None
    src_dur = audio_mix.probe_duration(wav_path)
    frozen_dur = audio_mix.probe_duration(tmp)
    if not src_dur or not frozen_dur or frozen_dur < 0.8 * src_dur:
        log(f'[abel] seed freeze REJECTED: frozen {frozen_dur}s vs source {src_dur}s (< 0.8x — trim ate speech?)')
        try:
            os.remove(tmp)
        except OSError as _exc:
            _zyg_log.debug('rejected freeze temp file cleanup skipped: %s', _exc)
        return None
    os.replace(tmp, ABEL_SEED_WAV)
    with open(ABEL_SEED_WAV + '.json', 'w', encoding='utf-8') as f:
        json.dump(
            {
                'source': wav_path,
                'engine': 'maya-research/maya1',
                'engine_license': 'Apache-2.0',
                'description': ABEL_VOICE_DESCRIPTION,
                'frozen': time.strftime('%Y-%m-%d %H:%M'),
            },
            f,
            indent=2,
        )
    log(f'[abel] seed frozen -> {ABEL_SEED_WAV}')
    return ABEL_SEED_WAV


# ---------------------------------------------------------------- narration + scene mix
def build_abel_narration(out_dir, engine='chatterbox', device='cpu', target_runtime_s=18.5, log_fn=None):
    """Script -> pause-map assembled stem -> -16 LUFS -> stem QC. The indextts2 path
    goes through tts_service (seed-pool voice); the chatterbox path requires the
    frozen Abel seed."""
    from zyg_workflows import audio_mix
    from zyg_workflows import audio_qc
    from zyg_workflows import narration_service

    log = log_fn or _log_noop
    os.makedirs(out_dir, exist_ok=True)
    kw = {}
    # 2026-08-06: NO pitch lift. The +2 st lift existed only because the Kokoro
    # stopgap voice (am_michael @ 0.87) was an adult man being nudged younger.
    # The frozen seed IS a child now (231 Hz / 12.26 cm vocal tract), so lifting
    # it again would push Abel above a twelve-year-old.
    pitch = 0.0
    if not os.path.isfile(ABEL_SEED_WAV):
        log(
            '[abel] no frozen Abel seed at %s — both engines are cloners and '
            'cannot synthesise without one' % ABEL_SEED_WAV
        )
        return None
    if engine == 'indextts2':
        kw = {'seed_wav': ABEL_SEED_WAV}
    elif engine == 'chatterbox':
        kw = {'device': device, 'ref': ABEL_SEED_WAV}
    res = narration_service.assemble_narration(
        [dict(s) for s in ABEL_SEGMENTS_1672],
        os.path.join(out_dir, f'abel_1672_{engine}.wav'),
        profile='calm_period_drama',
        engine=engine,
        engine_kwargs=kw,
        pitch_semitones=pitch,
        target_runtime_s=target_runtime_s,
        log_fn=log,
    )
    if not res:
        return None
    norm = audio_mix.loudnorm_two_pass(
        res['wav'], os.path.join(out_dir, f'abel_1672_{engine}_-16.wav'), i=-16.0, tp=-1.5
    )
    if not norm:
        return None
    gates = audio_qc.run_stem_gates(
        norm['out'],
        res['pause_map'],
        ABEL_SCRIPT_1672,
        max_s=target_runtime_s + 1.5,
        reference_wav=(ABEL_IDENTITY_REF if os.path.isfile(ABEL_IDENTITY_REF) else ''),
        expect_age='teen_male',
    )
    return {
        'stem': norm['out'],
        'raw': res['wav'],
        'pause_map': res['pause_map'],
        'duration_s': res['duration_s'],
        'qc': gates,
        'engine': engine,
        'over_runtime': bool(res.get('over_runtime')),
    }


DEFAULT_BED = [  # (sfx-library file id, gain_db) — gentle hull water base, distant extras
    ('waves_hull_01.wav', 0.0),
    ('waves_hull_02.wav', -4.0),
    ('seagulls_02.wav', -9.0),
    ('ship_creak_01.wav', -7.0),
]


def build_scene_audio(
    stem_wav, out_dir, duration_s, fade_start_s, fade_dur_s=2.5, bed=None, bed_lufs=-32.0, log_fn=None
):
    """License-gated maritime bed under the narration stem -> duck -> fade -> master.
    bed_lufs -32 + the calibrated soft duck (audio_mix defaults) keep the ambience
    softly hearable UNDER the voice and clearly present in Abel's pauses.
    Returns {'master', 'bed', 'qc', 'attributions'} or None. 'attributions' (always
    present, possibly empty) carries required credit lines from the license gate;
    non-empty means the publish/description stage MUST inject them (also written to
    <out_dir>/ATTRIBUTIONS.txt)."""
    from zyg_workflows import ambience_ingest
    from zyg_workflows import asset_library_service
    from zyg_workflows import audio_mix
    from zyg_workflows import audio_qc

    log = log_fn or _log_noop
    os.makedirs(out_dir, exist_ok=True)
    bed = bed or DEFAULT_BED
    gate = ambience_ingest.license_gate([('sfx', fid) for fid, _g in bed])
    if not gate.get('ok'):
        log(f'[abel] LICENSE GATE FAILED: {gate.get("violations")}')
        return None
    attributions = list(gate.get('attributions') or [])
    if attributions:
        try:
            with open(os.path.join(out_dir, 'ATTRIBUTIONS.txt'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(attributions) + '\n')
        except OSError as e:
            log(f'[abel] could not write ATTRIBUTIONS.txt: {e}')
        for a in attributions:
            log(f'[abel] bed attribution required: {a}')
    audio_dir = asset_library_service._audio_dir('sfx')
    layers = [{'path': os.path.join(audio_dir, fid), 'gain_db': g} for fid, g in bed]
    bed_raw = audio_mix.prep_bed(layers, duration_s, os.path.join(out_dir, 'bed_raw.wav'))
    if not bed_raw:
        return None
    bed_norm = audio_mix.loudnorm_two_pass(bed_raw, os.path.join(out_dir, 'bed.wav'), i=bed_lufs, tp=-6.0)
    if not bed_norm:
        return None
    clap = audio_qc.qc_clap(
        bed_norm['out'],
        positives=['ocean waves lapping against a wooden hull', 'distant seagulls', 'creaking wooden ship'],
        negatives=['music', 'speech', 'traffic', 'rain'],
    )
    # VO padded to program length so duck's duration=first covers the whole clip
    vo_full = os.path.join(out_dir, 'vo_program.wav')
    r = subprocess.run(
        [
            'ffmpeg',
            '-y',
            '-loglevel',
            'error',
            '-i',
            stem_wav,
            '-af',
            f'apad=whole_dur={duration_s}',
            '-t',
            str(duration_s),
            vo_full,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    ducked = audio_mix.duck_mix(vo_full, bed_norm['out'], os.path.join(out_dir, 'mix_ducked.wav'))
    if not ducked:
        return None
    faded = audio_mix.fade_out(ducked, os.path.join(out_dir, 'mix_faded.wav'), fade_start_s, fade_dur_s)
    if not faded:
        return None
    master = audio_mix.master(faded, os.path.join(out_dir, 'scene_audio_master.wav'))
    if not master:
        return None
    qc = audio_qc.run_master_gates(master)
    qc['clap_bed'] = clap
    return {'master': master, 'bed': bed_norm['out'], 'qc': qc, 'attributions': attributions}


def narrate_video(video_path, out_path, engine='chatterbox', device='cpu', fade_tail_s=2.5, log_fn=None):
    """Full pipeline for one clip: narration stem -> scene audio at the video's exact
    duration -> mux (video stream copied untouched).

    QC is ENFORCED by default (ZYG_AUDIO_QC_ENFORCE, default '1'; '0' = warn-only,
    mirroring ZYG_AUDIO_LICENSE_GATE): stem-gate fail, over_runtime, master-gate
    fail and a CLAP bed ok=False all refuse the mux (return None). CLAP ok=None
    NEVER vetoes (soft gate — operator escalation only). Two structural refusals
    are unconditional regardless of the env: video too short to narrate
    (dur - 1.5 <= 0) and an assembled stem longer than the video itself (muxing
    would hard-cut speech at the boundary)."""
    from zyg_workflows import audio_mix

    log = log_fn or _log_noop
    # Unique work dir per output — parallel narrations into one parent folder must
    # never share intermediates (bed_raw.wav, vo_program.wav, mix_*.wav).
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(out_path)), 'audio_work_' + os.path.splitext(os.path.basename(out_path))[0]
    )
    dur = audio_mix.probe_duration(video_path, log_fn=log)
    if not dur:
        log('[abel] ffprobe failed on video')
        return None
    if dur - 1.5 <= 0:
        log(f'[abel] REFUSED: video too short to narrate ({dur:.2f}s — needs >1.5s)')
        return None
    enforce = os.environ.get('ZYG_AUDIO_QC_ENFORCE', '1') != '0'
    warn_tag = '' if enforce else ' — warn-only (ZYG_AUDIO_QC_ENFORCE=0)'
    narr = build_abel_narration(
        out_dir, engine=engine, device=device, target_runtime_s=min(18.5, dur - 1.5), log_fn=log
    )
    if not narr:
        return None
    if narr['qc'].get('ok') is False:
        failing = ', '.join(
            k for k, g in (narr['qc'].get('gates') or {}).items() if isinstance(g, dict) and g.get('ok') is False
        )
        log(f'[abel] STEM QC FAILED ({failing or "aggregate"}){warn_tag}')
        if enforce:
            return None
    if narr.get('over_runtime'):
        log(f'[abel] narration over_runtime: stem exceeds target even after silence shrink{warn_tag}')
        if enforce:
            return None
    stem_dur = audio_mix.probe_duration(narr['stem'], log_fn=log)
    if not stem_dur or stem_dur > dur + 0.05:
        log(
            f'[abel] REFUSED: assembled stem ({stem_dur}s) exceeds video '
            f'({dur:.2f}s) — muxing would hard-cut narration mid-speech'
        )
        return None
    scene = build_scene_audio(
        narr['stem'],
        out_dir,
        duration_s=round(dur, 2),
        fade_start_s=max(0.0, dur - fade_tail_s - 0.1),
        fade_dur_s=fade_tail_s,
        log_fn=log,
    )
    if not scene:
        return None
    if scene['qc'].get('ok') is False:
        failing = ', '.join(
            k for k, g in (scene['qc'].get('gates') or {}).items() if isinstance(g, dict) and g.get('ok') is False
        )
        log(f'[abel] MASTER QC FAILED ({failing or "aggregate"}){warn_tag}')
        if enforce:
            return None
    clap_ok = (scene['qc'].get('clap_bed') or {}).get('ok')
    if clap_ok is False:
        log(f'[abel] CLAP bed QC FAILED{warn_tag}')
        if enforce:
            return None
    elif clap_ok is None:
        log('[abel] CLAP bed QC unavailable (ok=None) — soft gate, not vetoing')
    mux = audio_mix.mux_onto_video(video_path, scene['master'], out_path)
    if not mux:
        return None
    attributions = list(scene.get('attributions') or [])
    for a in attributions:
        log(f'[abel] ATTRIBUTION required in published credits: {a}')
    log(f'[abel] narrated video -> {out_path}')
    engine_license = ''
    try:
        with open(narr['pause_map'], 'r', encoding='utf-8') as f:
            engine_license = (json.load(f).get('engine_params') or {}).get('engine_license', '')
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('engine license read from pause map failed, leaving it empty: %s', _exc)
    return {
        'video': out_path,
        'narration_qc': narr['qc'],
        'audio_qc': scene['qc'],
        'pause_map': narr['pause_map'],
        'engine': engine,
        'engine_license': engine_license,
        'over_runtime': bool(narr.get('over_runtime')),
        'attributions': attributions,
    }


if __name__ == '__main__':  # the CLI lives in abel_voice_cli
    from zyg_workflows.abel_voice_cli import main as _cli_main

    raise SystemExit(_cli_main())
