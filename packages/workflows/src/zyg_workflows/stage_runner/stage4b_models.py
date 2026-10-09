# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4b GitHub-Models directors: per-video and bulk moment selection."""

from zyg_workflows.stage_runner import stage4b_models_director as _director


def _make_github_models(_log_info, _log_warn, _vid_channel_map):
    """Build Stage 4b's GPT-4o director helpers.

    The bodies live in :mod:`zyg_workflows.stage_runner.stage4b_models_director`;
    what used to be captured in a closure (the two loggers and the video→channel
    map) is passed along in a ``DirectorContext``.  ``_ask_github_models`` is
    returned to nobody because the single file never called it either.
    """
    _ctx = _director.DirectorContext(
        log_info=_log_info,
        log_warn=_log_warn,
        vid_channel_map=_vid_channel_map,
    )

    def _ask_github_models(
        tx_path_: str, motion_: dict, video_duration_: float, vid_id_: str, n_clips_: int = 5
    ) -> 'list | None':
        """
        Send transcript + audio energy to GitHub Models (Claude) and get back
        smart clip start timestamps. Returns list of floats on success, None on failure.
        Falls back to _pick_top_timestamps if anything goes wrong.
        """
        return _director.ask_github_models(_ctx, tx_path_, motion_, video_duration_, vid_id_, n_clips_)

    def _ask_github_models_bulk(scored_raw_: list, n_clips: int = 5) -> tuple:
        """
        Per-video director AI calls — GPT-4o via GitHub Models when GITHUB_TOKEN set,
        Ollama qwen3.6:35b-a3b as fallback when not.
        Returns (moments_dict, titles_dict, sfx_dict, react_dict, intro_dict)
        """
        return _director.ask_github_models_bulk(_ctx, scored_raw_, n_clips)

    return _ask_github_models_bulk
