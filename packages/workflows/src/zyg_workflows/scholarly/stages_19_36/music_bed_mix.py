# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helpers of Stage 4.5 — the music bed and the ffmpeg assembly it feeds.

`stage_16_music_bed` keeps the order of the stage; everything it used to do
inline lives here: the bed generation chain (ACE-Step -> tile -> level -> duck
-> master trim), the clip sequence that the concat demuxer reads, and the two
ffmpeg command lines (NVENC first, libx264 fallback).
"""

from dataclasses import dataclass
from typing import Callable

from ._common import (
    _cq_for_crf,
    _nvenc_vcodec_args,
    _x264_vcodec_args,
    exe,
    os,
)


@dataclass
class BedJob:
    """The stage locals the bed chain needs: where to write, what to log, what state to fill.

    `log(level, stage, message)` and `debug(stage, message)` are the stage's own
    loggers; `pipeline_state` is the mutable run state the bed records itself in;
    `sch_voice` is the voice mode ('silent' when the run has no narration).
    """

    out_dir: str
    pipeline_state: dict
    sch_voice: str
    log: Callable[[str, str, str], None]
    debug: Callable[[str, str], None]


def music_bed_disabled() -> bool:
    """True when ZYG_SCHOLARLY_MUSIC asks for dry narration ('0', 'false', 'no')."""
    return os.environ.get('ZYG_SCHOLARLY_MUSIC', '1').lower() in ('0', 'false', 'no')


def bed_mood_prompt(emotion_curve) -> str:
    """Return the ACE-Step prompt for this film's emotional arc.

    The mood follows Murch's emotion curve rather than a fixed preset: a curve
    whose entries are at least 35 % grief/shock/fear/anger scores as sombre,
    anything else (including an empty curve) as reflective.
    """
    emos = [str(e.get('emotion') or '') for e in (emotion_curve or [])]
    dark = sum(1 for e in emos if e in ('grief', 'shock', 'fear', 'anger'))
    mood = (
        'sombre, mournful, low strings, sparse piano'
        if emos and dark >= len(emos) * 0.35
        else 'reflective, hopeful, warm strings, soft piano'
    )
    return (
        f'cinematic documentary underscore, {mood}, sustained legato, '
        f'slow tempo, no drums, no percussion, no vocals, minimal, '
        f'restrained, background score that sits under narration'
    )


def bed_segment_seconds() -> int:
    """Length of the one generated segment prep_bed tiles, capped at 120 s.

    ACE-Step is capped by ZYG_ACE_MAX_SECONDS (180 default) and a 15-minute film
    would be a very long single generation, so the bed is one short segment
    crossfaded into itself.
    """
    return int(min(float(os.environ.get('ZYG_ACE_MAX_SECONDS', '180')), 120))


def voice_is_absent(voice_lufs, sch_voice) -> bool:
    """True when the programme has no narration to duck against.

    Only a MEASURED silence (or the 'silent' placeholder voice) counts: an
    unmeasurable voice must never drop the narration from the deliverable on a
    meter hiccup, so `None` is treated as present.
    """
    return sch_voice == 'silent' or (voice_lufs is not None and float(voice_lufs) <= -45.0)


def _generate_bed(job: BedJob, ace, am_bed, dur: float):
    """Generate and tile the bed; return (prompt, segment_s, bed_full_path) or None.

    None means the chain failed and the caller must deliver dry narration; the
    reason is logged here.
    """
    bed_dir = os.path.join(job.out_dir, 'bed')
    os.makedirs(bed_dir, exist_ok=True)
    prompt_bed = bed_mood_prompt(job.pipeline_state.get('emotion_curve') or [])
    seg = os.path.join(bed_dir, 'ace_seg.mp3')
    seg_len = bed_segment_seconds()
    if not ace.generate(prompt_bed, seg, duration_s=seg_len, log_fn=lambda m: job.log('INFO', 'Stage 6a', str(m))):
        job.log('WARNING', 'Stage 6a', 'Music bed skipped — ACE-Step generation failed')
        return None
    bed_full = os.path.join(bed_dir, 'bed_full.wav')
    if not am_bed.prep_bed(
        [{'path': seg, 'gain_db': 0.0}],
        float(dur),
        bed_full,
        crossfade_s=4.0,
        log_fn=lambda m: job.debug('Stage 6a', str(m)),
    ):
        job.log('WARNING', 'Stage 6a', 'Music bed skipped — prep_bed failed')
        return None
    return prompt_bed, seg_len, bed_full


def _measure_voice(job: BedJob, am_bed, voice_path: str):
    """Return the voice track's integrated loudness, or None, warning once when unmeasurable.

    This runs BEFORE the master trim (P-04): the trim was written as a small
    correction and against a silent voice it lifted the -34 LUFS bed by +20 dB
    into the limiter and shipped a music-only film at full loudness.
    """
    try:
        voice_lufs = am_bed.measure_lufs(voice_path)
    except Exception:
        voice_lufs = None
    if voice_lufs is None and job.sch_voice != 'silent':
        job.log(
            'WARNING',
            'Stage 6a',
            'Voice loudness unmeasurable — mixing normally (Stage 4 already passed the silence guard)',
        )
    return voice_lufs


def _music_only_programme(job: BedJob, ace, am_bed, bed_full, prompt_bed, seg_len, dur, voice_lufs) -> str:
    """Level the bed as the whole programme and return it; records `music_bed` state.

    A music-only film is levelled to ZYG_SCHOLARLY_MUSIC_ONLY_LUFS (-24) and
    explicitly NOT mastered to the -14 voice target.
    """
    music_only_lufs = float(os.environ.get('ZYG_SCHOLARLY_MUSIC_ONLY_LUFS', '-24') or -24)
    job.log(
        'WARNING',
        'Stage 6a',
        f'Voice track is silent/absent (I={voice_lufs}, voice={job.sch_voice}) — '
        f'music-only programme levelled to {music_only_lufs:g} LUFS, '
        f'NOT mastered to the -14 voice target',
    )
    bed_res: dict = {}
    bed_ok = am_bed.level_to(
        bed_full,
        target_lufs=music_only_lufs,
        tp_db=-2.0,
        log_fn=lambda m: job.debug('Stage 6a', str(m)),
        result=bed_res,
    )
    if not bed_ok:
        job.log(
            'WARNING',
            'Stage 6a',
            f'Music-only bed did not reach {music_only_lufs:g} LUFS (measured {bed_res.get("final_lufs")})',
        )
    job.pipeline_state['music_bed'] = {
        'prompt': prompt_bed,
        'segment_s': seg_len,
        'bed_lufs': music_only_lufs,
        'model': ace.model_id(),
        'voice_lufs': voice_lufs,
        'music_only': True,
        'bed_measured_lufs': bed_res.get('final_lufs'),
    }
    job.log(
        'INFO',
        'Stage 6a',
        f'Music-only bed ({ace.model_id()}, {seg_len}s tiled to {dur:.0f}s, '
        f'{music_only_lufs:g} LUFS, no voice to duck against)',
    )
    return bed_full


def master_trim_applies(mix_lufs) -> bool:
    """True when voice+bed is within 6 dB of -14 LUFS, i.e. the trim is the small correction it was written to be.

    A larger correction means the voice energy is missing upstream, and the mix
    must ship as-is with a warning instead of a +20 dB lift into the limiter.
    """
    return mix_lufs is not None and abs(-14.0 - float(mix_lufs)) <= 6.0


def _ducked_programme(job: BedJob, ace, am_bed, bed_full, voice_path, prompt_bed, seg_len, dur, voice_lufs):
    """Level the bed, sidechain-duck the voice over it, master the sum; return the mix path.

    Returns `voice_path` unchanged when duck_mix fails. The bed sits at
    ZYG_SCHOLARLY_BED_LUFS (-34) far under a -14 LUFS voice; ducking takes
    another ~7 dB off under speech, so the bed is present in the pauses and
    barely there under the line.
    """
    bed_lufs = float(os.environ.get('ZYG_SCHOLARLY_BED_LUFS', '-34'))
    bed_res: dict = {}
    bed_ok = am_bed.level_to(
        bed_full,
        target_lufs=bed_lufs,
        tp_db=-2.0,
        log_fn=lambda m: job.debug('Stage 6a', str(m)),
        result=bed_res,
    )
    if not bed_ok:
        job.log('WARNING', 'Stage 6a', f'Bed did not reach {bed_lufs:g} LUFS (measured {bed_res.get("final_lufs")})')
    mixed = os.path.join(job.out_dir, 'bed', 'voice_plus_bed.wav')
    if not am_bed.duck_mix(voice_path, bed_full, mixed, log_fn=lambda m: job.debug('Stage 6a', str(m))):
        job.log('WARNING', 'Stage 6a', 'Music bed skipped — duck_mix failed')
        return voice_path
    # amix normalize=0 preserves the voice level, so the sum sits a touch hot;
    # bring the programme back to the publish target — but only as a small trim.
    try:
        mix_lufs = am_bed.measure_lufs(mixed)
    except Exception:
        mix_lufs = None
    mix_res: dict = {}
    mix_final = mix_lufs
    if master_trim_applies(mix_lufs):
        mix_ok = am_bed.level_to(
            mixed,
            target_lufs=-14.0,
            tp_db=-1.0,
            log_fn=lambda m: job.debug('Stage 6a', str(m)),
            result=mix_res,
        )
        mix_final = mix_res.get('final_lufs', mix_lufs)
        if not mix_ok:
            job.log('WARNING', 'Stage 6a', f'Master trim did not reach -14 LUFS (measured {mix_final})')
    else:
        job.log(
            'WARNING',
            'Stage 6a',
            f'Master trim SKIPPED — voice+bed measures {mix_lufs} LUFS, more than 6 dB from -14; check the voice track',
        )
    job.pipeline_state['music_bed'] = {
        'prompt': prompt_bed,
        'segment_s': seg_len,
        'bed_lufs': bed_lufs,
        'model': ace.model_id(),
        'voice_lufs': voice_lufs,
        'music_only': False,
        'bed_measured_lufs': bed_res.get('final_lufs'),
        'mix_pre_master_lufs': mix_lufs,
        'mix_lufs': mix_final,
    }
    job.log(
        'INFO',
        'Stage 6a',
        f'Music bed mixed ({ace.model_id()}, {seg_len}s tiled to '
        f'{dur:.0f}s, bed {bed_lufs:g} LUFS, sidechain-ducked, '
        f'programme {mix_final} LUFS)',
    )
    return mixed


def build_music_bed(job: BedJob, voice_path: str, dur: float) -> str:
    """Return a path to voice+bed, or the voice unchanged. Never raises.

    The mix is built for the MUX ONLY: `voice_path` stays voice-only, because
    Stage 4 derived the word timings, the forced alignment and the ASR read-back
    gate from it and the subtitle burn re-reads it as its Whisper fallback —
    running any of those over music would degrade all of them.

    Source is ACE-Step 1.5, whose engine weights are MIT: the channel is
    monetised and no other generator in this repo is licence-safe for published
    output.
    """
    if music_bed_disabled():
        return voice_path
    if not dur or dur < 30:
        return voice_path
    try:
        from zyg_workflows import ace_step_service as _ace
        from zyg_workflows import audio_mix as _am_bed

        if not _ace.is_available():
            job.log(
                'WARNING',
                'Stage 6a',
                'Music bed skipped — ACE-Step unavailable (ComfyUI down '
                'or checkpoint missing); delivering dry narration',
            )
            return voice_path
        generated = _generate_bed(job, _ace, _am_bed, dur)
        if generated is None:
            return voice_path
        prompt_bed, seg_len, bed_full = generated
        voice_lufs = _measure_voice(job, _am_bed, voice_path)
        if voice_is_absent(voice_lufs, job.sch_voice):
            return _music_only_programme(job, _ace, _am_bed, bed_full, prompt_bed, seg_len, dur, voice_lufs)
        return _ducked_programme(job, _ace, _am_bed, bed_full, voice_path, prompt_bed, seg_len, dur, voice_lufs)
    except Exception as _bed_e:
        job.log('WARNING', 'Stage 6a', f'Music bed skipped ({_bed_e!r}) — delivering dry narration')
        return voice_path


def _probe_duration(path: str, fallback: float) -> float:
    """Return the container duration of `path` in seconds, or `fallback` when ffprobe says nothing."""
    import subprocess as _sp6c

    try:
        probe = _sp6c.run(
            [exe('ffprobe'), '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return float(probe.stdout.strip()) if probe.stdout.strip() else fallback
    except Exception:
        return fallback


def slideshow_repeats(slide_dur: float, tts_duration: float) -> int:
    """How many times the single image slideshow must repeat to cover the narration.

    1 when the slideshow already covers the audio (within the 2 s tolerance the
    stage has always allowed), otherwise just enough passes to cover it.
    """
    if slide_dur >= tts_duration - 2:
        return 1
    return max(1, int(tts_duration / max(slide_dur, 1)) + 1)


def spread_clips(downloaded_clips, tts_duration: float):
    """Repeat the WAN/stock clips so the set spans the full narration.

    Each WAN clip is ~5 s, so the set is repeated to `clips_needed` entries
    (two spare) and truncated — the concat demuxer stops at `-t` anyway.
    """
    avg_clip_dur = max(5, tts_duration / max(len(downloaded_clips), 1))
    clips_needed = max(1, int(tts_duration / avg_clip_dur) + 2)
    return (downloaded_clips * ((clips_needed // len(downloaded_clips)) + 1))[:clips_needed]


def plan_clip_sequence(downloaded_clips, tts_duration: float, slug: str, log) -> list:
    """Return the clip list, in order, that the concat demuxer should read.

    A single image slideshow already covers the whole duration and is used as
    one pass; a short one is looped (and the looping is logged); several WAN or
    stock clips are spread across the narration instead.
    """
    is_single_slideshow = len(downloaded_clips) == 1 and downloaded_clips[0].endswith(f'{slug}_slideshow.mp4')
    if not is_single_slideshow:
        return spread_clips(downloaded_clips, tts_duration)
    slide_dur = _probe_duration(downloaded_clips[0], tts_duration)
    n_loops = slideshow_repeats(slide_dur, tts_duration)
    if n_loops == 1:
        return list(downloaded_clips)
    log(
        'INFO',
        'Stage 6',
        f'Slideshow ({slide_dur:.0f}s) shorter than audio ({tts_duration:.0f}s) — looping {n_loops}×',
    )
    return downloaded_clips * n_loops


def _with_vcodecs(base: list, final_video_path: str):
    """Return (nvenc_cmd, x264_cmd) — the same ffmpeg call with each video encoder appended."""
    return (
        base + _nvenc_vcodec_args(_cq_for_crf(23), 'p4') + [final_video_path],
        base + _x264_vcodec_args(23, 'fast') + [final_video_path],
    )


def concat_assembly_commands(concat_list: str, mux_audio: str, tts_duration: float, final_video_path: str):
    """ffmpeg command pair that muxes the concat list against the programme audio."""
    base = [
        exe('ffmpeg'),
        '-y',
        '-f',
        'concat',
        '-safe',
        '0',
        '-i',
        concat_list,
        '-i',
        mux_audio,
        '-map',
        '0:v:0',
        '-map',
        '1:a:0',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-t',
        str(tts_duration + 2),
        '-movflags',
        '+faststart',
    ]
    return _with_vcodecs(base, final_video_path)


def black_assembly_commands(mux_audio: str, tts_duration: float, final_video_path: str):
    """ffmpeg command pair for a run with no video: a slow gradient under the audio."""
    base = [
        exe('ffmpeg'),
        '-y',
        '-f',
        'lavfi',
        '-i',
        f'gradients=size=1920x1080:speed=0.05:c0=0x0d1b2a:c1=0x1b263b:nb_colors=2:x0=0:y0=0:x1=1920:y1=1080:duration={int(tts_duration) + 5}',
        '-i',
        mux_audio,
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-shortest',
        '-movflags',
        '+faststart',
    ]
    return _with_vcodecs(base, final_video_path)
