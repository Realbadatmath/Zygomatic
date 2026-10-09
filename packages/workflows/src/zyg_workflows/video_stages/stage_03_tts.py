# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 3 of the video pipeline: IndexTTS-2 narration, one clip per scene.

Lines 1116-1176 of `pipeline_video._run_video_pipeline` at 770c30a, verbatim.
With narration disabled the stage logs it and leaves `ctx.tts_files` the empty
list the next stage expects.
"""

import os

from zyg_workflows.narrator_voice_service import _get_narrator_voice
from zyg_workflows.tts_service import _tts_shared


def stage_03_tts(ctx):
    _complete_stage = ctx._complete_stage
    _log = ctx._log
    _set_stage = ctx._set_stage
    n_scenes = ctx.n_scenes
    narration_enabled = ctx.narration_enabled
    out_dir = ctx.out_dir
    scenes = ctx.scenes
    # ── Stage 3: TTS Narration ────────────────────────────────────────────
    _set_stage('TTS Narration')

    tts_dir = os.path.join(out_dir, 'tts')
    os.makedirs(tts_dir, exist_ok=True)
    tts_files = []  # one mp3 per scene
    _tts_engine_used = 'none'

    if not narration_enabled:
        tts_files = [None] * n_scenes
        _log('INFO', 'Stage 3', '🔇 Narrator disabled — skipping voice narration')
        _complete_stage('TTS Narration')
    else:
        _log('INFO', 'Stage 3', 'Generating TTS narration per scene…')

        # 2026-08-06 engine swap: IndexTTS-2 primary, Chatterbox fallback.
        # Both are cloners — tts_service resolves the voice id to a seed-pool
        # reference wav and handles the fallback internally, per scene.
        _tts_engine_used = 'indextts2'
        voice, rate, pitch = _get_narrator_voice('')
        _log('INFO', 'Stage 3', f'🎙️ TTS engine: IndexTTS-2 (voice {voice})')

        while len(tts_files) < n_scenes:
            tts_files.append(None)

        _scene_ok, _engines_seen = 0, set()
        for _si, _sc in enumerate(scenes):
            if tts_files[_si] is not None:
                continue
            _text = _sc.get('narration', f'Scene {_si + 1}.')
            _out = os.path.join(tts_dir, f'tts_{_si:04d}.mp3')
            _eng: dict = {}
            _ok, _ = _tts_shared(
                _text,
                _out,
                f'Stage 3/scene-{_si}',
                _log,
                voice_id=voice,
                engine_out=_eng,
            )
            if _ok:
                tts_files[_si] = _out
                _scene_ok += 1
                _engines_seen.add(_eng.get('engine', 'indextts2'))
            else:
                _log('WARNING', 'TTS Narration', f'TTS failed for scene {_si}')
        if _engines_seen:
            _tts_engine_used = ' + '.join(sorted(_engines_seen))
        _log('INFO', 'Stage 3', f'TTS: {_scene_ok}/{n_scenes} scenes OK')

        _ok_count = sum(1 for t in tts_files if t)
        _log('INFO', 'Stage 3', f'TTS complete ({_tts_engine_used}): {_ok_count}/{n_scenes} segments ready')
        # 2026-07-24 audio-loss gate: a narrated video with ZERO voiced
        # scenes must not assemble silently (mirrors crime/scholarly).
        if _ok_count == 0:
            raise RuntimeError(
                f'Stage 3: TTS failed for all {n_scenes} scenes on both engines '
                f'(IndexTTS-2 primary + Chatterbox fallback) — aborting narrated run'
            )

        _complete_stage('TTS Narration')
    ctx.tts_dir = tts_dir
    ctx.tts_files = tts_files
