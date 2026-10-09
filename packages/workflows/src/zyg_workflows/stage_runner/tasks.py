# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Building a stage agent task description out of live pipeline state."""

import json
from zyg_workflows.runtime import _runtime_path


def _build_task_desc(stage_name: str, template: str, state_file: str, state: dict) -> str:
    """
    Build a concrete, actionable task description for an agent by injecting
    real pipeline state — channel names, discovered video URLs, approved clip
    list, downloaded file paths — so agents call their tools on actual data
    rather than hallucinating results.
    """
    channels = state.get('channels', [])
    candidates = state.get('video_candidates', [])
    approved = state.get('approved_clips', [])
    fetched = state.get('fetched_files', {})
    processed = state.get('processed_clips', [])
    output_dir = state.get('output_dir', _runtime_path('output'))
    ch_names = ', '.join(c.get('name', c.get('channel_id', '')) for c in channels) or 'none registered'

    ctx = f'\n\n=== PIPELINE STATE (read/write: {state_file}) ===\nOutput directory: {output_dir}'

    if 'Stage 1' in stage_name:
        ctx += (
            f'\nChannels approved for clipping: {ch_names}'
            f'\nINSTRUCTIONS:'
            f"\n1. Use 'YouTube Channel RSS Scanner' tool to scan each registered channel for recent videos."
            f"\n2. Use 'YouTube Data API' tool to discover additional trending videos in the same niche."
            f"\n3. For every video found write a JSON record to the state file under the key 'video_candidates'."
            f'\n   Each record must have: video_id, title, url, channel_name, view_count, published_at.'
            f'\n4. Write the updated state back to: {state_file}'
        )
    elif 'Stage 2' in stage_name:
        sample = [v.get('url', f'https://youtube.com/watch?v={v.get("video_id", "")}') for v in candidates[:10]]
        ctx += (
            f'\nVideo candidates to analyse ({len(candidates)} total): {json.dumps(sample)}'
            f'\nFull candidate list is in state file.'
            f'\nINSTRUCTIONS:'
            f"\n1. Use 'Engagement Rate Calculator' and 'VPH Calculator' on each candidate."
            f"\n2. Use 'Virality Score Calculator' and 'Momentum Detector' to score trends."
            f"\n3. Use 'pytrends (Google Trends)' to verify topic momentum."
            f"\n4. Write updated scores into each candidate record in state file under 'video_candidates'."
        )
    elif 'Stage 3' in stage_name:
        ctx += (
            f'\nScored candidates ({len(candidates)}): read from state file.'
            f'\nINSTRUCTIONS:'
            f"\n1. Use 'Duplicate Flag Checker' on each candidate to skip already-processed videos."
            f"\n2. Use 'VPH Ranker' and 'Clip Potential Scorer' to rank remaining candidates."
            f'\n3. Select the top 5 highest-scoring non-duplicate videos.'
            f"\n4. Write the approved list to state file under 'approved_clips'."
            f'\n   Each record: video_id, url, title, score.'
            f"\n5. Register each approved video in 'Duplicate Flag Registry'."
        )
    elif 'Stage 4a' in stage_name:
        targets = approved[:5] if approved else candidates[:5]
        dl_list = [
            {
                'video_id': v.get('video_id', ''),
                'url': v.get('url', f'https://youtube.com/watch?v={v.get("video_id", "")}'),
            }
            for v in targets
        ]
        ctx += (
            f'\nVideos approved for download ({len(dl_list)}): {json.dumps(dl_list)}'
            f'\nOutput directory: {output_dir}'
            f'\nINSTRUCTIONS: For each video in the list above:'
            f"\n1. Use 'YouTube Transcript API' tool — fetch transcript, save as {{video_id}}_transcript.json in {output_dir}."
            f"\n2. Use 'yt-dlp (video download)' tool — download to {output_dir}/{{video_id}}.mp4."
            f"\n3. Use 'Rights Assessment Reader' — confirm rights status (all channels have granted clipping permission)."
            f"\n4. Update state file 'fetched_files' with {{video_id: absolute_path}} for every downloaded file."
        )
    elif 'Stage 4b' in stage_name:
        fetch_list = [{'video_id': k, 'path': v} for k, v in fetched.items()]
        ctx += (
            f'\nDownloaded files ({len(fetch_list)}): {json.dumps(fetch_list)}'
            f'\nOutput directory: {output_dir}'
            f'\nINSTRUCTIONS: For each downloaded video file:'
            f"\n1. Use 'Scene Change Detector (OpenCV)' — detect top 3 highlight moments (timestamps)."
            f"\n2. Use 'FFmpeg (clip rendering)' — cut each highlight as a 30-90s clip into {output_dir}."
            f"\n3. Use 'Whisper (speech-to-text)' — transcribe each clip audio."
            f"\n4. Use 'SRT / VTT Caption Builder' — generate .srt subtitle file per clip."
            f"\n5. Use 'FFmpeg (resolution/fps normalization)' — normalise to 1080p / 30fps."
            f"\n6. Use 'Text Overlay Renderer (Pillow)' — generate thumbnail image per clip."
            f"\n7. Write completed clip paths to state file under 'processed_clips'."
        )
    elif 'Stage 5' in stage_name:
        ctx += (
            f'\nProcessed clips ({len(processed)}): {json.dumps(processed[:5])}'
            f'\nINSTRUCTIONS: For each clip:'
            f"\n1. Use 'Resolution Checker (FFprobe)' — verify resolution and codec."
            f"\n2. Use 'Clip Duration Validator' — check fits platform limits (15-60s TikTok, up to 15min YouTube)."
            f"\n3. Use 'Audio Level Meter (FFmpeg)' — check loudness; if outside -14 LUFS use 'Audio Level Normalizer (FFmpeg)'."
            f"\n4. Use 'FFmpeg (aspect ratio conversion)' — create 9:16 vertical variant per clip."
            f"\n5. Use 'Markdown / HTML Report Builder' — write QC report to {output_dir}/qc_report.md."
        )
    elif 'Stage 6' in stage_name or 'Publish' in stage_name:
        ctx += (
            f'\nNo upload platform configured — save locally.'
            f'\nINSTRUCTIONS:'
            f"\n1. Use 'Publish Time Scheduler' — calculate optimal posting windows."
            f"\n2. Use 'Markdown / HTML Report Builder' — write manifest to {output_dir}/manifest.md"
            f'\n   listing every clip: path, title, duration, score, recommended publish time.'
            f"\n3. Use 'Report Generator' — write {output_dir}/manifest.json with same data as JSON."
        )

    return template + ctx
