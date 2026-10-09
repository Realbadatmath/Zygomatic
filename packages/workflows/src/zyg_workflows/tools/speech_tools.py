# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Speech tools: Whisper (faster-whisper), Bark TTS, word-level alignment.
"""

import json

try:
    from langchain.tools import BaseTool
except ImportError:
    try:
        from langchain_core.tools import BaseTool
    except ImportError:

        class BaseTool:
            name: str = ''
            description: str = ''

            def _run(self, *args, **kwargs):
                raise NotImplementedError


class WhisperSpeechToTextTool(BaseTool):
    name: str = 'Whisper (speech-to-text)'
    description: str = (
        'Transcribe audio to text using faster-whisper. Returns full transcript with per-segment timestamps.'
    )

    def _run(self, audio_path: str, model_size: str = None, language: str = 'en', task: str = 'transcribe') -> str:
        # 2026-07-28: large-v3 + VAD via shared VRAM-aware loader (was base, no VAD).
        import zyg_whisper as _zw

        seg_list, info = _zw.transcribe_segments(
            audio_path, language=language, want_words=False, vad=True, model_size=model_size, task=task
        )
        full_text = [s['text'] for s in seg_list]
        return json.dumps(
            {
                'language': info.language,
                'language_probability': round(info.language_probability, 4),
                'duration': round(info.duration, 3),
                'full_text': ' '.join(full_text),
                'segments': [
                    {'start': round(s['start'], 3), 'end': round(s['end'], 3), 'text': s['text']} for s in seg_list
                ],
            }
        )


class WhisperTranscriptAlignmentTool(BaseTool):
    name: str = 'Whisper (transcript alignment)'
    description: str = (
        'Align an existing transcript text to audio timestamps using faster-whisper. '
        'Returns per-segment alignment with start/end times.'
    )

    def _run(self, audio_path: str, model_size: str = None, language: str = 'en') -> str:
        # 2026-07-28: large-v3 + VAD via shared VRAM-aware loader (was base, no VAD).
        import zyg_whisper as _zw

        seg_list, info = _zw.transcribe_segments(
            audio_path, language=language, want_words=True, vad=True, model_size=model_size
        )
        aligned = []
        for s in seg_list:
            aligned.append(
                {
                    'start': round(s['start'], 3),
                    'end': round(s['end'], 3),
                    'text': s['text'],
                    'words': s.get('words', []),
                }
            )
        return json.dumps({'language': info.language, 'segments': aligned, 'total_segments': len(aligned)})


class WordLevelTimestampAlignerTool(BaseTool):
    name: str = 'Word-level Timestamp Aligner'
    description: str = (
        'Generate word-level timestamps for audio using faster-whisper. '
        'Returns each word with its precise start and end time in seconds.'
    )

    def _run(self, audio_path: str, model_size: str = None, language: str = 'en') -> str:
        # 2026-07-28: large-v3 + VAD via shared VRAM-aware loader (was base, no VAD).
        import zyg_whisper as _zw

        seg_list, info = _zw.transcribe_segments(
            audio_path, language=language, want_words=True, vad=True, model_size=model_size
        )
        words = []
        for s in seg_list:
            for w in s.get('words', []):
                words.append({'word': w['word'], 'start': w['start'], 'end': w['end'], 'prob': w['prob']})
        return json.dumps(
            {
                'word_count': len(words),
                'language': info.language,
                'duration': round(info.duration, 3),
                'words': words,
            }
        )


class VoiceoverScriptBuilderTool(BaseTool):
    name: str = 'Voiceover Script Builder'
    description: str = (
        'Build a voiceover script from raw content: clean text, add pauses, '
        'format for TTS, and optionally split into timed segments.'
    )

    def _run(
        self, raw_text: str, words_per_minute: int = 150, add_pauses: bool = True, max_segment_words: int = 30
    ) -> str:
        import re

        # Clean and normalize
        text = re.sub(r'\s+', ' ', raw_text).strip()
        text = re.sub(r'[^\w\s.,!?;:()\-\'"]', '', text)

        if add_pauses:
            text = re.sub(r'([.!?])\s+', r'\1 ... ', text)
            text = re.sub(r'([,;:])\s+', r'\1 .. ', text)

        # Split into segments
        words = text.split()
        segments = []
        for i in range(0, len(words), max_segment_words):
            chunk = ' '.join(words[i : i + max_segment_words])
            word_count = len(chunk.split())
            duration_sec = (word_count / words_per_minute) * 60
            segments.append(
                {
                    'segment': i // max_segment_words + 1,
                    'text': chunk,
                    'word_count': word_count,
                    'estimated_duration_sec': round(duration_sec, 1),
                }
            )

        total_words = len(words)
        total_duration = (total_words / words_per_minute) * 60
        return json.dumps(
            {
                'script': text,
                'total_words': total_words,
                'segment_count': len(segments),
                'estimated_total_duration_sec': round(total_duration, 1),
                'segments': segments,
            }
        )


SPEECH_TOOLS = [
    WhisperSpeechToTextTool(),
    WhisperTranscriptAlignmentTool(),
    WordLevelTimestampAlignerTool(),
    VoiceoverScriptBuilderTool(),
]

__all__ = [
    'WhisperSpeechToTextTool',
    'WhisperTranscriptAlignmentTool',
    'WordLevelTimestampAlignerTool',
    'VoiceoverScriptBuilderTool',
    'SPEECH_TOOLS',
]
