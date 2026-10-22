# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""remixai_analyze.py — source analysis + original regeneration for Remix Ai.

Four analyses run over a downloaded source (frames, transcript, soundtrack,
title), and each produces an ABSTRACT BRIEF — never a copy of the source.

THE LOAD-BEARING RULE OF THIS MODULE
------------------------------------
`analyze_transcript()` returns a STRUCTURAL brief: topic, beat list, hook shape,
register, pacing. It deliberately does NOT return the source's sentences, and
`regenerate_script()` deliberately does NOT accept the transcript — its only
input is that brief. The two functions cannot be wired to pass source wording
between them, which is the point: the output is new writing about the same
subject in the same proven shape, not the source's script reordered.

The same split applies to the title: `analyze_title()` extracts the FORMAT
(hook type, keyword slots, length), `regenerate_title()` writes a fresh title
into that format for our own topic. Formats are not ownable; sentences are.

Frames and music go the other way round on purpose — the visual brief IS
detailed, because matching an aesthetic is the explicit goal and a style is not
protectable. The music brief is a genre/mood label used to pick a DIFFERENT
track from our own licensed library.

Models: local ollama (qwen3.5:9b — gpt-oss returns EMPTY under format:'json',
verified ollama 0.17.7) for text, the same model's vision path for frames, and
CLAP (audio_qc.qc_clap) for the soundtrack. Claude Haiku is wired as an OPTIONAL
fallback for the two text-regeneration steps only, off unless ZYG_REMIXAI_HAIKU=1
and an API key is present — the local model handles this task fine.
"""

from __future__ import annotations

# This __init__ IS the re-export surface of the old remixai_analyze.py.
from __future__ import annotations

# The submodules are imported in the original section order, so any module-level
# side effect still runs exactly when it did in the single-file remixai_analyze.py.
from zyg_workflows.remixai_analyze.llm import (
    base64,
    json,
    os,
    re,
    subprocess,
    _hj,
    _safe_urlopen,
    paths,
    exe,
    _zyg_logging,
    _zyg_log,
    _CREWS,
    _OLLAMA,
    _llm_model,
    _vlm_model,
    _gpu_clear,
    _run,
    _ollama_json,
    _ollama_release,
    _haiku_enabled,
    _haiku_json,
    _llm,
)
from zyg_workflows.remixai_analyze.frames import (
    sample_frames,
    probe_duration,
    probe_video,
    _FRAME_PROMPT,
    describe_frames,
    visual_style_summary,
)
from zyg_workflows.remixai_analyze.brief import (
    _BEATS_PROMPT,
    _BRIEF_CAPS,
    _BRIEF_REQUIRED,
    _cap,
    _sanitize_brief,
    brief_prose,
    analyze_transcript,
    _SCRIPT_PROMPT,
    _TTS_WPM_DEFAULT,
    _tts_wpm,
    _BRIEF_LEVELS,
    _brief_level,
    _brief_for_writer,
    regenerate_script,
)
from zyg_workflows.remixai_analyze.title import (
    _TITLE_ANALYZE_PROMPT,
    analyze_title,
    _TITLE_WRITE_PROMPT,
    _TITLE_MAX_WORDS,
    _TITLE_MAX_CHARS,
    _tidy_title,
    regenerate_title,
)
from zyg_workflows.remixai_analyze.music import (
    _GENRES,
    _MOODS,
    extract_music_bed,
    _clap_rank,
    analyze_music,
    _GENRE_TO_MOOD,
    _MOOD_TO_MOOD,
    music_request,
)

# Re-export surface: every name below is imported above and not used in this
# module. Nothing does ``import *`` from here, so __all__ changes no behaviour;
# it declares the inherited namespace public so ruff does not read it as dead.
__all__ = [
    'base64',
    'json',
    'os',
    're',
    'subprocess',
    '_hj',
    '_safe_urlopen',
    'paths',
    'exe',
    '_zyg_logging',
    '_zyg_log',
    '_CREWS',
    '_OLLAMA',
    '_llm_model',
    '_vlm_model',
    '_gpu_clear',
    '_run',
    '_ollama_json',
    '_ollama_release',
    '_haiku_enabled',
    '_haiku_json',
    '_llm',
    'sample_frames',
    'probe_duration',
    'probe_video',
    '_FRAME_PROMPT',
    'describe_frames',
    'visual_style_summary',
    '_BEATS_PROMPT',
    '_BRIEF_CAPS',
    '_BRIEF_REQUIRED',
    '_cap',
    '_sanitize_brief',
    'brief_prose',
    'analyze_transcript',
    '_SCRIPT_PROMPT',
    '_TTS_WPM_DEFAULT',
    '_tts_wpm',
    '_BRIEF_LEVELS',
    '_brief_level',
    '_brief_for_writer',
    'regenerate_script',
    '_TITLE_ANALYZE_PROMPT',
    'analyze_title',
    '_TITLE_WRITE_PROMPT',
    '_TITLE_MAX_WORDS',
    '_TITLE_MAX_CHARS',
    '_tidy_title',
    'regenerate_title',
    '_GENRES',
    '_MOODS',
    'extract_music_bed',
    '_clap_rank',
    'analyze_music',
    '_GENRE_TO_MOOD',
    '_MOOD_TO_MOOD',
    'music_request',
]
