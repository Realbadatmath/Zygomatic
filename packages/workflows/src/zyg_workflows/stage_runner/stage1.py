# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 1 preflight: scan RSS feeds and write video_candidates."""

import json
from zyg_workflows.stage_runner.agents import _pf_agents_active
from zyg_workflows.stage_runner.agents import _pf_agents_done


def _pf_stage_1(stage_name, state, pipeline_id, _save, _log_err, _log_warn, _log_info):
    """The Stage 1 branch of _stage_preflight, verbatim (original lines 655-689)."""
    # ── Stage 1: scan RSS feeds and write video_candidates ──────────────────
    if 'Stage 1' in stage_name:
        _pf_agents_active(pipeline_id, stage_name, ['CLIPFARM-Source-Scanner-Agent'])
        try:
            from zyg_workflows.tools.data_tools import YouTubeChannelRSSScannerTool

            scanner = YouTubeChannelRSSScannerTool()
            raw = scanner._run(max_videos_per_channel=100)
            result = json.loads(raw)
            videos = result.get('videos', [])
            _log_info(f'RSS scan returned {len(videos)} videos')
            if videos:
                state['video_candidates'] = [
                    {
                        'video_id': v.get('video_id', ''),
                        'title': v.get('title', ''),
                        'url': v.get('url', f'https://www.youtube.com/watch?v={v.get("video_id", "")}'),
                        'channel_name': v.get('channel_name', ''),
                        'views': v.get('views', '0'),
                        'published': v.get('published', ''),
                        'source': 'rss',
                    }
                    for v in videos
                    if v.get('video_id')
                ]
                _save(state)
                _log_info(f'Saved {len(state["video_candidates"])} candidates to state')
            else:
                _log_err('Stage 1', f'RSS scan returned 0 videos. Raw: {raw[:300]}')
        except Exception as _e:
            _log_err('Stage 1', str(_e))
        _pf_agents_done(pipeline_id, stage_name, ['CLIPFARM-Source-Scanner-Agent'])
