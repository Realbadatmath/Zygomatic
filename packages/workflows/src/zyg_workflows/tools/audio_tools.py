# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Audio analysis tools using librosa, pydub, and soundfile.
"""

import json
import os

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


class AudioEnergyAnalyzerTool(BaseTool):
    name: str = 'Audio Energy Analyzer (librosa)'
    description: str = (
        'Analyze audio energy, RMS levels, and onset strength over time using librosa. '
        'Returns per-frame RMS energy, mean/max energy, and onset timestamps.'
    )

    def _run(self, audio_path: str, frame_length: int = 2048, hop_length: int = 512) -> str:
        import librosa
        import numpy as np

        y, sr = librosa.load(audio_path, sr=None)
        rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units='time').tolist()
        return json.dumps(
            {
                'duration_sec': float(len(y) / sr),
                'sample_rate': int(sr),
                'mean_rms': float(np.mean(rms)),
                'max_rms': float(np.max(rms)),
                'min_rms': float(np.min(rms)),
                'onset_times': onsets[:50],  # cap at 50
                'frame_count': int(len(rms)),
            }
        )


class BeatSyncDetectorTool(BaseTool):
    name: str = 'Beat Sync Detector'
    description: str = (
        'Detect beats, tempo, and beat timestamps in an audio file using librosa. '
        'Returns BPM, beat times, and beat strength values.'
    )

    def _run(self, audio_path: str) -> str:
        import librosa

        y, sr = librosa.load(audio_path, sr=None)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        return json.dumps(
            {
                'tempo_bpm': float(tempo),
                'beat_count': len(beat_times),
                'beat_times': beat_times[:100],
                'duration_sec': float(len(y) / sr),
            }
        )


class SRTVTTCaptionBuilderTool(BaseTool):
    name: str = 'SRT / VTT Caption Builder'
    description: str = (
        'Build SRT or VTT caption files from a list of timed transcript segments. '
        'Input: JSON list of {start, end, text} dicts. Output: SRT or VTT string.'
    )

    def _run(self, segments_json: str, output_format: str = 'srt', output_path: str = '') -> str:
        segments = json.loads(segments_json) if isinstance(segments_json, str) else segments_json

        def _fmt_time_srt(sec: float) -> str:
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s = int(sec % 60)
            ms = int((sec - int(sec)) * 1000)
            return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

        def _fmt_time_vtt(sec: float) -> str:
            return _fmt_time_srt(sec).replace(',', '.')

        lines = []
        if output_format.lower() == 'vtt':
            lines.append('WEBVTT\n')
            for seg in segments:
                lines.append(f'{_fmt_time_vtt(seg["start"])} --> {_fmt_time_vtt(seg["end"])}')
                lines.append(seg['text'].strip())
                lines.append('')
        else:
            for i, seg in enumerate(segments, 1):
                lines.append(str(i))
                lines.append(f'{_fmt_time_srt(seg["start"])} --> {_fmt_time_srt(seg["end"])}')
                lines.append(seg['text'].strip())
                lines.append('')

        content = '\n'.join(lines)
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
        return json.dumps(
            {
                'status': 'ok',
                'format': output_format,
                'segments': len(segments),
                'output_path': output_path,
                'preview': content[:500],
            }
        )


class SubtitleStyleApplierTool(BaseTool):
    name: str = 'Subtitle Style Applier'
    description: str = (
        'Apply a named style (font, color, size, position) to an SRT/VTT file, '
        'converting it to ASS format for video burning.'
    )

    def _run(self, subtitle_path: str, style_name: str = 'default', output_path: str = '') -> str:
        import re

        STYLES = {
            'default': {'font': 'Arial', 'size': 24, 'color': '&H00FFFFFF', 'outline': 2, 'shadow': 1},
            'bold': {'font': 'Arial Bold', 'size': 28, 'color': '&H00FFFFFF', 'outline': 3, 'shadow': 2},
            'minimal': {'font': 'Helvetica', 'size': 20, 'color': '&H00F0F0F0', 'outline': 1, 'shadow': 0},
            'youtube': {'font': 'Roboto', 'size': 26, 'color': '&H00FFFF00', 'outline': 2, 'shadow': 1},
        }
        style = STYLES.get(style_name, STYLES['default'])
        if not output_path:
            base, _ = os.path.splitext(subtitle_path)
            output_path = base + f'_{style_name}.ass'

        with open(subtitle_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Generate ASS header. MarginV=54 is the SMPTE/EBU ACTION-safe line —
        # 5% of the 1080 PlayResY declared just below — matching the burnt
        # captions the Videos tab produces (kanban_server._SUBBURN_STYLE). It
        # was 10, i.e. 0.9% of height, which sits under the picture edge and
        # under most players' overscan. NOTE this script declares its own
        # PlayResY, so unlike an ffmpeg-converted SRT (which lands at 288) the
        # unit here IS a 1080-frame pixel: 5% = 54, not 14.
        ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, Strikeout, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {style_name},{style['font']},{style['size']},{style['color']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},2,10,10,54,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        # Carry the cues across. Writing the header alone produced a valid .ass
        # with the requested style and NO text, so burning it showed nothing —
        # the styled subtitles the description promises never appeared.
        def _ass_time(ts: str) -> str:
            h, m, rest = ts.replace(',', '.').split(':')
            s, ms = rest.split('.')
            return f'{int(h)}:{int(m):02d}:{int(s):02d}.{int(ms) // 10:02d}'

        cues = re.findall(
            r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})[^\n]*\n(.*?)(?=\n[ \t]*\n|\Z)',
            content,
            re.DOTALL,
        )
        events = [
            f'Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,' + text.strip().replace('\n', '\\N')
            for start, end, text in cues
        ]

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(ass_header + '\n'.join(events) + '\n')
        return json.dumps({'status': 'ok', 'style': style_name, 'output': output_path, 'events': len(events)})


class SubtitleSyncValidatorTool(BaseTool):
    name: str = 'Subtitle Sync Validator'
    description: str = (
        'Validate that subtitle timestamps are sequential, non-overlapping, '
        'and within video duration. Returns a list of sync issues found.'
    )

    def _run(self, subtitle_path: str, video_duration: float = 0.0) -> str:
        import re

        with open(subtitle_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse SRT timestamps
        pattern = r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s-->\s(\d{2}:\d{2}:\d{2}[,\.]\d{3})'
        matches = re.findall(pattern, content)

        def to_sec(ts: str) -> float:
            ts = ts.replace(',', '.')
            h, m, rest = ts.split(':')
            s, ms = rest.split('.')
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        issues = []
        prev_end = 0.0
        for i, (start_str, end_str) in enumerate(matches):
            start = to_sec(start_str)
            end = to_sec(end_str)
            if start >= end:
                issues.append(f'Segment {i + 1}: start ({start:.3f}) >= end ({end:.3f})')
            if start < prev_end:
                issues.append(f'Segment {i + 1}: overlaps previous (starts {start:.3f}, prev ended {prev_end:.3f})')
            if video_duration > 0 and end > video_duration:
                issues.append(f'Segment {i + 1}: end ({end:.3f}) exceeds video duration ({video_duration:.3f})')
            prev_end = end

        return json.dumps(
            {
                'total_segments': len(matches),
                'issues_found': len(issues),
                'issues': issues,
                'valid': len(issues) == 0,
            }
        )


class TranscriptSegmentReaderTool(BaseTool):
    name: str = 'Transcript Segment Reader'
    description: str = (
        'Read and parse a transcript file (SRT, VTT, JSON, or plain text) '
        'and return segments as a structured JSON list of {start, end, text}.'
    )

    def _run(self, transcript_path: str) -> str:
        import re

        ext = os.path.splitext(transcript_path)[1].lower()
        with open(transcript_path, 'r', encoding='utf-8') as f:
            content = f.read()

        def to_sec(ts: str) -> float:
            ts = ts.replace(',', '.')
            parts = ts.split(':')
            if len(parts) == 3:
                h, m, rest = parts
                s, ms = rest.split('.')
                return int(h) * 3600 + int(m) * 60 + int(s) + float(f'0.{ms}')
            elif len(parts) == 2:
                m, rest = parts
                s, ms = rest.split('.')
                return int(m) * 60 + int(s) + float(f'0.{ms}')
            return 0.0

        if ext == '.json':
            segments = json.loads(content)
        elif ext in ('.srt', '.vtt'):
            pattern = r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s-->\s(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n([\s\S]*?)(?=\n\n|\Z)'
            segments = []
            for m in re.finditer(pattern, content):
                segments.append(
                    {
                        'start': to_sec(m.group(1)),
                        'end': to_sec(m.group(2)),
                        'text': m.group(3).strip(),
                    }
                )
        else:
            # Plain text: one line per segment
            segments = [{'start': 0, 'end': 0, 'text': line.strip()} for line in content.splitlines() if line.strip()]

        return json.dumps({'segment_count': len(segments), 'segments': segments})


AUDIO_TOOLS = [
    AudioEnergyAnalyzerTool(),
    BeatSyncDetectorTool(),
    SRTVTTCaptionBuilderTool(),
    SubtitleStyleApplierTool(),
    SubtitleSyncValidatorTool(),
    TranscriptSegmentReaderTool(),
]

__all__ = [
    'AudioEnergyAnalyzerTool',
    'BeatSyncDetectorTool',
    'SRTVTTCaptionBuilderTool',
    'SubtitleStyleApplierTool',
    'SubtitleSyncValidatorTool',
    'TranscriptSegmentReaderTool',
    'AUDIO_TOOLS',
]
