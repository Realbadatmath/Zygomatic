# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 4.5 — the music bed (`stage_16_music_bed`)."""

from ._common import (
    _FORCE_CPU_POST_ENCODE,
    _cq_for_crf,
    _ffmpeg_popen_nvenc_first,
    os,
)
from .music_bed_mix import (
    BedJob,
    black_assembly_commands,
    build_music_bed,
    concat_assembly_commands,
    plan_clip_sequence,
)


def stage_16_music_bed(ctx):
    _debug = ctx._debug
    _log = ctx._log
    _sch_voice = ctx._sch_voice
    _slug = ctx._slug
    downloaded_clips = ctx.downloaded_clips
    out_dir = ctx.out_dir
    pipeline_id = ctx.pipeline_id
    pipeline_state = ctx.pipeline_state
    tts_duration = ctx.tts_duration
    tts_path = ctx.tts_path

    # ── Stage 6a: music bed ──────────────────────────────────────────────
    # The documentary shipped as dry narration over stills — no bed, no
    # score, while pipeline_video and the storyteller scene service both
    # run a full bed/duck/master chain through audio_mix. The chain now
    # lives in music_bed_mix.build_music_bed; this stage only orders it.
    _bed_job = BedJob(
        out_dir=out_dir,
        pipeline_state=pipeline_state,
        sch_voice=_sch_voice,
        log=_log,
        debug=_debug,
    )

    # Build concat list or loop a single clip to match TTS duration
    concat_list = os.path.join(out_dir, 'concat.txt')
    final_video_path = os.path.join(out_dir, f'{_slug}.mp4')

    if downloaded_clips:
        _looped = plan_clip_sequence(downloaded_clips, tts_duration, _slug, _log)
        with open(concat_list, 'w') as _cf:
            for _cp in _looped:
                _cf.write(f"file '{_cp}'\n")

        _mux_audio = build_music_bed(_bed_job, tts_path, tts_duration)
        _asm_nvenc, _asm_x264 = concat_assembly_commands(concat_list, _mux_audio, tts_duration, final_video_path)
    else:
        # No video — create a black video with the TTS audio
        _mux_audio = build_music_bed(_bed_job, tts_path, tts_duration)
        _asm_nvenc, _asm_x264 = black_assembly_commands(_mux_audio, tts_duration, final_video_path)

    _asm_rc, _stdout, _stderr = _ffmpeg_popen_nvenc_first(
        _asm_nvenc,
        _asm_x264,
        600,
        pipeline_id=pipeline_id,
        label='scholarly-ffmpeg',
    )
    if _asm_rc != 0:
        _log('WARNING', 'Stage 6', f'ffmpeg assembly returned {_asm_rc}: {_stderr[-200:].decode(errors="replace")}')

    if not os.path.exists(final_video_path):
        raise RuntimeError('Stage 6: Video file not created')

    _vid_size = os.path.getsize(final_video_path)
    _log(
        'INFO',
        'Stage 6',
        f'ffmpeg assembly complete (video: '
        f'{"libx264" if _FORCE_CPU_POST_ENCODE else "NVENC h264_nvenc"}, '
        f'CQ~{_cq_for_crf(23)})',
    )
    _book_intro_prepended = False  # track whether 9s intro was added (affects subtitle offset)

    ctx.final_video_path = final_video_path
    ctx._book_intro_prepended = _book_intro_prepended
