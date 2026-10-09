# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
FFmpeg wrapper tools for CLIPFARM pipeline.
Wraps ffmpeg-python (import ffmpeg) for all video/audio processing operations.
"""

import json
import os
import subprocess
from pydantic import BaseModel, Field
from zyg_workflows.bin import exe

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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _ffprobe(path: str) -> dict:
    """Run ffprobe and return stream/format info as dict."""
    cmd = [exe('ffprobe'), '-v', 'quiet', '-print_format', 'json', '-show_streams', '-show_format', path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f'ffprobe failed: {result.stderr.strip()}')
    return json.loads(result.stdout)


def _fps(rate):
    """ffprobe's 'num/den' frame rate ('30000/1001') as a float.

    This division used to be done with eval(), which handed Python's expression
    parser a string lifted out of a media file's metadata."""
    num, _, den = str(rate or '').partition('/')
    try:
        n, d = float(num), float(den or 1)
    except ValueError:
        return rate
    return n / d if d else 0.0


def _run_ffmpeg(*args, timeout: int = 300) -> str:
    """Run ffmpeg with the given args list, return stdout+stderr summary."""
    cmd = [exe('ffmpeg'), '-y'] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f'ffmpeg error: {result.stderr[-500:]}')
    return 'OK'


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class AudioExtractionInput(BaseModel):
    input_path: str = Field(..., description='Path to video file')
    output_path: str = Field(..., description='Output audio file path (.wav/.mp3/.aac)')
    sample_rate: int = Field(44100, description='Sample rate in Hz')
    channels: int = Field(2, description='Number of audio channels')


class AudioMixingInput(BaseModel):
    video_path: str = Field(..., description='Path to video file')
    audio_path: str = Field(..., description='Path to audio file to mix in')
    output_path: str = Field(..., description='Output video file path')
    audio_volume: float = Field(1.0, description='Volume multiplier for the mixed audio (0.0–2.0)')


class AudioTrackExtractionInput(BaseModel):
    input_path: str = Field(..., description='Path to video file')
    track_index: int = Field(0, description='Zero-based audio stream index')
    output_path: str = Field(..., description='Output audio file path')


class AudioLevelInput(BaseModel):
    input_path: str = Field(..., description='Path to audio or video file')


class AudioNormalizeInput(BaseModel):
    input_path: str = Field(..., description='Path to audio or video file')
    output_path: str = Field(..., description='Output file path')
    target_lufs: float = Field(-16.0, description='Target loudness in LUFS (e.g. -16.0 for YouTube)')


class AspectRatioInput(BaseModel):
    input_path: str = Field(..., description='Path to video file')
    output_path: str = Field(..., description='Output video file path')
    aspect_ratio: str = Field(..., description="Target aspect ratio, e.g. '16:9', '9:16', '1:1'")
    width: int = Field(1920, description='Output width in pixels')
    height: int = Field(1080, description='Output height in pixels')


class ClipRenderInput(BaseModel):
    input_path: str = Field(..., description='Path to source video')
    output_path: str = Field(..., description='Output clip path')
    start_time: float = Field(..., description='Start time in seconds')
    end_time: float = Field(..., description='End time in seconds')
    video_codec: str = Field('libx264', description='Video codec')
    audio_codec: str = Field('aac', description='Audio codec')
    crf: int = Field(23, description='CRF quality factor (lower = higher quality)')


class FormatConversionInput(BaseModel):
    input_path: str = Field(..., description='Path to source file')
    output_path: str = Field(..., description='Output file path (extension determines format)')
    video_codec: str = Field('libx264', description="Video codec or 'copy'")
    audio_codec: str = Field('aac', description="Audio codec or 'copy'")


class ResolutionFpsInput(BaseModel):
    input_path: str = Field(..., description='Path to video file')
    output_path: str = Field(..., description='Output video file path')
    width: int = Field(1920, description='Target width')
    height: int = Field(1080, description='Target height')
    fps: float = Field(30.0, description='Target frames per second')


class LengthTrimmerInput(BaseModel):
    input_path: str = Field(..., description='Path to video file')
    output_path: str = Field(..., description='Output file path')
    max_duration: float = Field(..., description='Maximum duration in seconds')
    from_end: bool = Field(False, description='If True, trim from the end; else from start')


class BitrateInput(BaseModel):
    input_path: str = Field(..., description='Path to video file')
    output_path: str = Field(..., description='Output file path')
    video_bitrate: str = Field('4000k', description="Video bitrate, e.g. '4000k'")
    audio_bitrate: str = Field('192k', description="Audio bitrate, e.g. '192k'")


class ResolutionCheckInput(BaseModel):
    input_path: str = Field(..., description='Path to video file to inspect')


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class AudioExtractionTool(BaseTool):
    name: str = 'FFmpeg (audio extraction)'
    description: str = 'Extract audio track from a video file using FFmpeg.'

    def _run(self, input_path: str, output_path: str, sample_rate: int = 44100, channels: int = 2) -> str:
        _run_ffmpeg('-i', input_path, '-vn', '-ar', str(sample_rate), '-ac', str(channels), output_path)
        return json.dumps({'status': 'ok', 'output': output_path})


class AudioMixingTool(BaseTool):
    name: str = 'FFmpeg (audio mixing)'
    description: str = 'Mix an external audio file into a video file using FFmpeg.'

    def _run(self, video_path: str, audio_path: str, output_path: str, audio_volume: float = 1.0) -> str:
        vol = str(audio_volume)
        _run_ffmpeg(
            '-i',
            video_path,
            '-i',
            audio_path,
            '-filter_complex',
            f'[1:a]volume={vol}[a1];[0:a][a1]amix=inputs=2:duration=first[aout]',
            '-map',
            '0:v',
            '-map',
            '[aout]',
            '-c:v',
            'copy',
            '-c:a',
            'aac',
            output_path,
        )
        return json.dumps({'status': 'ok', 'output': output_path})


class AudioTrackExtractionTool(BaseTool):
    name: str = 'FFmpeg (audio track extraction)'
    description: str = 'Extract a specific audio stream/track from a video file.'

    def _run(self, input_path: str, track_index: int = 0, output_path: str = '') -> str:
        if not output_path:
            base, _ = os.path.splitext(input_path)
            output_path = f'{base}_track{track_index}.wav'
        _run_ffmpeg('-i', input_path, '-map', f'0:a:{track_index}', '-vn', output_path)
        return json.dumps({'status': 'ok', 'output': output_path})


class AudioLevelMeterTool(BaseTool):
    name: str = 'Audio Level Meter (FFmpeg)'
    description: str = 'Measure peak and RMS audio levels of a file using FFmpeg volumedetect.'

    def _run(self, input_path: str) -> str:
        cmd = [exe('ffmpeg'), '-i', input_path, '-af', 'volumedetect', '-f', 'null', '/dev/null']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        lines = [
            l for l in result.stderr.splitlines() if 'volumedetect' in l or 'mean_volume' in l or 'max_volume' in l
        ]
        return json.dumps({'levels': lines, 'raw': result.stderr[-800:]})


class AudioLevelNormalizerTool(BaseTool):
    name: str = 'Audio Level Normalizer (FFmpeg)'
    description: str = 'Normalize audio loudness using FFmpeg loudnorm filter to a target LUFS level.'

    def _run(self, input_path: str, output_path: str, target_lufs: float = -16.0) -> str:
        _run_ffmpeg('-i', input_path, '-af', f'loudnorm=I={target_lufs}:TP=-1.5:LRA=11', output_path)
        return json.dumps({'status': 'ok', 'output': output_path, 'target_lufs': target_lufs})


class AspectRatioConversionTool(BaseTool):
    name: str = 'FFmpeg (aspect ratio conversion)'
    description: str = 'Convert video to a target aspect ratio with padding or cropping.'

    def _run(
        self, input_path: str, output_path: str, aspect_ratio: str = '16:9', width: int = 1920, height: int = 1080
    ) -> str:
        # Use scale + pad to letterbox/pillarbox into exact dimensions
        vf = f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2'
        _run_ffmpeg('-i', input_path, '-vf', vf, '-c:a', 'copy', output_path)
        return json.dumps(
            {'status': 'ok', 'output': output_path, 'dimensions': f'{width}x{height}', 'aspect': aspect_ratio}
        )


class ClipRenderTool(BaseTool):
    name: str = 'FFmpeg (clip rendering)'
    description: str = 'Render a clip from a source video between start and end times.'

    def _run(
        self,
        input_path: str,
        output_path: str,
        start_time: float = 0.0,
        end_time: float = 10.0,
        video_codec: str = 'libx264',
        audio_codec: str = 'aac',
        crf: int = 23,
    ) -> str:
        duration = end_time - start_time
        _run_ffmpeg(
            '-ss',
            str(start_time),
            '-i',
            input_path,
            '-t',
            str(duration),
            '-c:v',
            video_codec,
            '-crf',
            str(crf),
            '-c:a',
            audio_codec,
            output_path,
        )
        return json.dumps(
            {'status': 'ok', 'output': output_path, 'start': start_time, 'end': end_time, 'duration': duration}
        )


class FormatConversionTool(BaseTool):
    name: str = 'FFmpeg (format conversion)'
    description: str = 'Convert a video/audio file to a different container format.'

    def _run(self, input_path: str, output_path: str, video_codec: str = 'libx264', audio_codec: str = 'aac') -> str:
        _run_ffmpeg('-i', input_path, '-c:v', video_codec, '-c:a', audio_codec, output_path)
        return json.dumps({'status': 'ok', 'output': output_path})


class ResolutionFpsNormalizationTool(BaseTool):
    name: str = 'FFmpeg (resolution/fps normalization)'
    description: str = 'Normalize video to a target resolution and frame rate.'

    def _run(self, input_path: str, output_path: str, width: int = 1920, height: int = 1080, fps: float = 30.0) -> str:
        vf = f'scale={width}:{height},fps={fps}'
        _run_ffmpeg('-i', input_path, '-vf', vf, '-c:a', 'copy', output_path)
        return json.dumps({'status': 'ok', 'output': output_path, 'resolution': f'{width}x{height}', 'fps': fps})


class LengthTrimmerTool(BaseTool):
    name: str = 'Length Trimmer (FFmpeg)'
    description: str = 'Trim a video to a maximum duration using FFmpeg.'

    def _run(self, input_path: str, output_path: str, max_duration: float = 60.0, from_end: bool = False) -> str:
        if from_end:
            # Get duration first
            info = _ffprobe(input_path)
            total = float(info.get('format', {}).get('duration', max_duration))
            start = max(0.0, total - max_duration)
            _run_ffmpeg('-ss', str(start), '-i', input_path, '-t', str(max_duration), '-c', 'copy', output_path)
        else:
            _run_ffmpeg('-i', input_path, '-t', str(max_duration), '-c', 'copy', output_path)
        return json.dumps({'status': 'ok', 'output': output_path, 'max_duration': max_duration})


class BitrateControllerTool(BaseTool):
    name: str = 'Bitrate Controller (FFmpeg)'
    description: str = 'Re-encode a video to specific video and audio bitrates.'

    def _run(self, input_path: str, output_path: str, video_bitrate: str = '4000k', audio_bitrate: str = '192k') -> str:
        _run_ffmpeg(
            '-i',
            input_path,
            '-c:v',
            'libx264',
            '-b:v',
            video_bitrate,
            '-c:a',
            'aac',
            '-b:a',
            audio_bitrate,
            output_path,
        )
        return json.dumps(
            {'status': 'ok', 'output': output_path, 'video_bitrate': video_bitrate, 'audio_bitrate': audio_bitrate}
        )


class ResolutionCheckerTool(BaseTool):
    name: str = 'Resolution Checker (FFprobe)'
    description: str = 'Read resolution, fps, duration and codec info from a video file using FFprobe.'

    def _run(self, input_path: str) -> str:
        info = _ffprobe(input_path)
        video_streams = [s for s in info.get('streams', []) if s.get('codec_type') == 'video']
        audio_streams = [s for s in info.get('streams', []) if s.get('codec_type') == 'audio']
        fmt = info.get('format', {})
        result = {
            'duration': float(fmt.get('duration', 0)),
            'size_bytes': int(fmt.get('size', 0)),
            'format': fmt.get('format_name'),
            'video': [
                {
                    'codec': s.get('codec_name'),
                    'width': s.get('width'),
                    'height': s.get('height'),
                    'fps': _fps(s.get('r_frame_rate')),
                    'bitrate': s.get('bit_rate'),
                }
                for s in video_streams
            ],
            'audio': [
                {
                    'codec': s.get('codec_name'),
                    'sample_rate': s.get('sample_rate'),
                    'channels': s.get('channels'),
                    'bitrate': s.get('bit_rate'),
                }
                for s in audio_streams
            ],
        }
        return json.dumps(result)


# Export list
FFMPEG_TOOLS = [
    AudioExtractionTool(),
    AudioMixingTool(),
    AudioTrackExtractionTool(),
    AudioLevelMeterTool(),
    AudioLevelNormalizerTool(),
    AspectRatioConversionTool(),
    ClipRenderTool(),
    FormatConversionTool(),
    ResolutionFpsNormalizationTool(),
    LengthTrimmerTool(),
    BitrateControllerTool(),
    ResolutionCheckerTool(),
]

__all__ = [
    'AudioExtractionTool',
    'AudioMixingTool',
    'AudioTrackExtractionTool',
    'AudioLevelMeterTool',
    'AudioLevelNormalizerTool',
    'AspectRatioConversionTool',
    'ClipRenderTool',
    'FormatConversionTool',
    'ResolutionFpsNormalizationTool',
    'LengthTrimmerTool',
    'BitrateControllerTool',
    'ResolutionCheckerTool',
    'FFMPEG_TOOLS',
]
