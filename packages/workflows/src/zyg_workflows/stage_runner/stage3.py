# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 3 preflight: rank candidates and write approved_clips."""

import json
from zyg_workflows.runtime import _ams_now
from zyg_workflows.runtime import _parse_iso_to_ams
from zyg_workflows.stage_runner.agents import _pf_agents_active
from zyg_workflows.stage_runner.agents import _pf_agents_done
from zyg_workflows.runtime import _runtime_path


def _pf_stage_3(stage_name, state, pipeline_id, _save, _log_err, _log_warn, _log_info):
    """The Stage 3 branch of _stage_preflight, verbatim (original lines 691-805).

    Only the branch keyword changed: the original ``elif`` is an ``if`` here.
    """
    # ── Stage 3: rank candidates and write approved_clips ───────────────────
    if 'Stage 3' in stage_name:
        _pf_agents_active(pipeline_id, stage_name, ['CLIPFARM-Selection-Agent', 'CLIPFARM-Deduplication-Agent'])
        candidates = state.get('video_candidates', [])
        _log_info(f'{len(candidates)} candidates to rank')
        if candidates:

            def _score(v):
                try:
                    views = int(v.get('views', 0))
                    pub = v.get('published', '')
                    if pub:
                        _pub_dt = _parse_iso_to_ams(pub)
                        age_days = (_ams_now() - _pub_dt).days + 1 if _pub_dt else 1
                        # If views are unknown (RSS Shorts), rank purely by recency
                        return (views / age_days) if views > 0 else (1.0 / max(age_days, 1))
                    return views
                except Exception:
                    return 0

            # Hard-filter Shorts — they are always under 60s and will never pass the 90s minimum
            long_form = [v for v in candidates if '/shorts/' not in v.get('url', '').lower()]
            # Hard-filter upcoming/active livestreams — yt-dlp cannot download them
            _live_keywords = (
                'is live',
                ' live',
                '🔴',
                'live now',
                'live stream',
                'livestream',
                'live event',
                'premiere',
                'premieres',
                'watch live',
                'starting soon',
            )

            def _is_live(v):
                t = v.get('title', '').lower()
                return any(kw in t for kw in _live_keywords)

            _live_filtered = [v for v in long_form if _is_live(v)]
            if _live_filtered:
                _log_warn(
                    f'Stage 3: filtered out {len(_live_filtered)} live/upcoming video(s): '
                    f'{[v["video_id"] for v in _live_filtered]}'
                )
            long_form = [v for v in long_form if not _is_live(v)]
            if not long_form:
                _log_warn('Stage 3: no long-form videos found this run (all candidates were Shorts) — skipping')
                state['approved_clips'] = []
                _save(state)
                return
            ranked = sorted(long_form, key=_score, reverse=True)
            # ── Cross-run deduplication: skip videos clipped in recent runs ──
            _dedup_path = _runtime_path('clipped_video_ids.json')
            try:
                with open(_dedup_path) as _df:
                    _clipped_ids = set(json.load(_df))
            except Exception:
                _clipped_ids = set()
            # ── Per-channel dedup reset: each channel gets its own fresh pool ──
            # If a channel has no unclipped videos left, reset dedup for that channel only
            # so it recycles rather than going silent while other channels still have fresh content.
            _PER_CHANNEL_MAX = 2
            _all_channels = list({v.get('channel_name', '') or v.get('channel_id', '') for v in ranked})
            _fresh_pool = []
            for _ch in _all_channels:
                _ch_ranked = [v for v in ranked if (v.get('channel_name', '') or v.get('channel_id', '')) == _ch]
                _ch_fresh = [v for v in _ch_ranked if v['video_id'] not in _clipped_ids]
                if not _ch_fresh:
                    _log_info(f'Stage 3: all {_ch} videos already clipped — resetting dedup for this channel only')
                    # Remove this channel's IDs from the global clipped set so they're eligible again
                    _ch_ids = {v['video_id'] for v in _ch_ranked}
                    _clipped_ids -= _ch_ids
                    _ch_fresh = _ch_ranked
                _fresh_pool.extend(_ch_fresh)
            # Re-sort combined pool by score (channels were processed independently above)
            _fresh_pool.sort(key=_score, reverse=True)
            _ch_counts: dict = {}
            selected = []
            for v in _fresh_pool:
                ch = v.get('channel_name', '') or v.get('channel_id', '')
                if _ch_counts.get(ch, 0) < _PER_CHANNEL_MAX:
                    selected.append(v)
                    _ch_counts[ch] = _ch_counts.get(ch, 0) + 1
            _log_info(
                f'Stage 3: per-channel selection ({_PER_CHANNEL_MAX}/channel): '
                + ', '.join(f'{ch}={n}' for ch, n in _ch_counts.items())
            )
            state['approved_clips'] = [
                {
                    'video_id': v['video_id'],
                    'url': v['url'],
                    'title': v['title'],
                    'channel_name': v.get('channel_name', ''),
                    'score': _score(v),
                }
                for v in selected
            ]
            # Persist newly approved video IDs — cap at last 50 to avoid growing forever
            _clipped_ids.update(v['video_id'] for v in selected)
            _clipped_ids_list = list(_clipped_ids)[-50:]
            try:
                with open(_dedup_path, 'w') as _df:
                    json.dump(_clipped_ids_list, _df)
            except Exception as _de:
                _log_info(f'Stage 3: could not save dedup list: {_de}')
            _save(state)
            _log_info(
                f'approved_clips ({len(state["approved_clips"])} long-form): {[c["video_id"] for c in state["approved_clips"]]}'
            )
        else:
            _log_err('Stage 3', 'No video_candidates in state — Stage 1 preflight may have failed')
        _pf_agents_done(pipeline_id, stage_name, ['CLIPFARM-Selection-Agent', 'CLIPFARM-Deduplication-Agent'])
