# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Scoring & Analytics tools (lines 551-812 of the original pipeline_tools.py)."""

# `datetime` / `timezone` are re-imported at module level even though every use in
# this section is behind a function-local `import`: the single file bound them at
# module level, and CPython's is_import_originated() consults the MODULE symbol table
# when it chooses the LOAD_METHOD vs PUSH_NULL+LOAD_ATTR call form. Keeping them here
# keeps the compiled bytecode of the moved bodies identical to the original's.
from .base import BaseTool, datetime, json, timezone

__all__ = [
    'datetime',
    'timezone',
]

# ---------------------------------------------------------------------------
# Scoring & Analytics tools
# ---------------------------------------------------------------------------


class EngagementRateCalculatorTool(BaseTool):
    name: str = 'Engagement Rate Calculator'
    description: str = (
        'Calculate engagement rate for a piece of content. Formula: (likes + comments + shares) / views * 100.'
    )

    def _run(self, views: float, likes: float = 0, comments: float = 0, shares: float = 0) -> str:
        if views <= 0:
            return json.dumps({'error': 'views must be > 0'})
        engagement = (likes + comments + shares) / views * 100
        return json.dumps(
            {
                'views': views,
                'likes': likes,
                'comments': comments,
                'shares': shares,
                'engagement_rate_percent': round(engagement, 4),
                'grade': 'high' if engagement > 5 else 'medium' if engagement > 2 else 'low',
            }
        )


class VPHCalculatorTool(BaseTool):
    name: str = 'VPH Calculator (views / hours since upload)'
    description: str = 'Calculate Views Per Hour (VPH) for a video given total views and upload time.'

    def _run(self, views: float, uploaded_at_iso: str = '', hours_since_upload: float = 0.0) -> str:
        if hours_since_upload <= 0 and uploaded_at_iso:
            from datetime import datetime, timezone

            uploaded = datetime.fromisoformat(uploaded_at_iso.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            hours_since_upload = (now - uploaded).total_seconds() / 3600
        if hours_since_upload <= 0:
            return json.dumps({'error': 'Provide hours_since_upload or uploaded_at_iso'})
        vph = views / hours_since_upload
        return json.dumps(
            {
                'views': views,
                'hours_since_upload': round(hours_since_upload, 2),
                'vph': round(vph, 2),
                'velocity': 'viral' if vph > 10000 else 'fast' if vph > 1000 else 'normal' if vph > 100 else 'slow',
            }
        )


class VPHRankerTool(BaseTool):
    name: str = 'VPH Ranker'
    description: str = 'Rank a list of videos by their VPH (views per hour) score.'

    def _run(self, videos_json: str) -> str:
        videos = json.loads(videos_json) if isinstance(videos_json, str) else videos_json
        for v in videos:
            views = v.get('views', 0)
            hours = v.get('hours_since_upload', 1) or 1
            v['vph'] = round(views / hours, 2)
        ranked = sorted(videos, key=lambda x: x.get('vph', 0), reverse=True)
        for i, v in enumerate(ranked):
            v['rank'] = i + 1
        return json.dumps({'count': len(ranked), 'ranked': ranked})


class ViralityScoreCalculatorTool(BaseTool):
    name: str = 'Virality Score Calculator'
    description: str = (
        'Calculate a virality score (0–100) from video metrics: VPH, engagement rate, like ratio, and share velocity.'
    )

    def _run(
        self, vph: float = 0, engagement_rate: float = 0, like_ratio: float = 0, shares: float = 0, views: float = 1
    ) -> str:
        # Normalized weighted score
        vph_score = min(100, vph / 1000 * 100) * 0.4
        eng_score = min(100, engagement_rate * 10) * 0.3
        like_score = min(100, like_ratio * 100) * 0.2
        share_score = min(100, (shares / max(views, 1)) * 10000) * 0.1
        total = vph_score + eng_score + like_score + share_score
        return json.dumps(
            {
                'virality_score': round(total, 2),
                'components': {
                    'vph_contribution': round(vph_score, 2),
                    'engagement_contribution': round(eng_score, 2),
                    'like_ratio_contribution': round(like_score, 2),
                    'share_contribution': round(share_score, 2),
                },
                'tier': 'viral' if total > 75 else 'trending' if total > 50 else 'growing' if total > 25 else 'low',
            }
        )


class LikeRatioAnalyzerTool(BaseTool):
    name: str = 'Like Ratio Analyzer'
    description: str = 'Analyze the like/dislike ratio and sentiment signal for a video.'

    def _run(self, likes: float, dislikes: float = 0, views: float = 0) -> str:
        total_votes = likes + dislikes
        ratio = likes / total_votes if total_votes > 0 else 0
        like_rate = likes / views if views > 0 else 0
        return json.dumps(
            {
                'likes': likes,
                'dislikes': dislikes,
                'views': views,
                'like_ratio': round(ratio, 4),
                'like_rate_per_view': round(like_rate, 6),
                'sentiment': 'positive' if ratio > 0.9 else 'mixed' if ratio > 0.7 else 'negative',
            }
        )


class MomentumDetectorTool(BaseTool):
    name: str = 'Momentum Detector'
    description: str = (
        'Detect upward or downward momentum in a time series of view counts. '
        'Input: JSON list of {timestamp, views} dicts. Returns trend direction and rate.'
    )

    def _run(self, datapoints_json: str, window: int = 5) -> str:
        import statistics

        data = json.loads(datapoints_json) if isinstance(datapoints_json, str) else datapoints_json
        if len(data) < 2:
            return json.dumps({'error': 'Need at least 2 data points'})
        views = [float(d.get('views', 0)) for d in data]
        recent = views[-window:] if len(views) >= window else views
        older = views[: len(views) - len(recent)] or [views[0]]
        recent_avg = statistics.mean(recent)
        older_avg = statistics.mean(older)
        change_pct = ((recent_avg - older_avg) / max(older_avg, 1)) * 100
        return json.dumps(
            {
                'data_points': len(data),
                'recent_avg_views': round(recent_avg, 2),
                'older_avg_views': round(older_avg, 2),
                'change_percent': round(change_pct, 2),
                'momentum': 'accelerating'
                if change_pct > 20
                else 'growing'
                if change_pct > 5
                else 'stable'
                if change_pct > -5
                else 'declining',
            }
        )


class PercentileRankerTool(BaseTool):
    name: str = 'Percentile Ranker'
    description: str = 'Rank a value within a dataset by percentile. Input: value and JSON list of comparison values.'

    def _run(self, value: float, dataset_json: str) -> str:
        import statistics

        dataset = json.loads(dataset_json) if isinstance(dataset_json, str) else dataset_json
        dataset = [float(x) for x in dataset]
        if not dataset:
            return json.dumps({'error': 'Empty dataset'})
        below = sum(1 for x in dataset if x < value)
        percentile = (below / len(dataset)) * 100
        return json.dumps(
            {
                'value': value,
                'percentile': round(percentile, 2),
                'dataset_size': len(dataset),
                'dataset_min': min(dataset),
                'dataset_max': max(dataset),
                'dataset_median': round(statistics.median(dataset), 4),
            }
        )


class ClipPotentialScorerTool(BaseTool):
    name: str = 'Clip Potential Scorer'
    description: str = (
        "Score a clip's viral/engagement potential based on metadata. "
        'Returns composite score and per-dimension breakdown.'
    )

    def _run(
        self,
        duration_sec: float = 60,
        has_hook: bool = True,
        energy_level: float = 0.5,
        topic_trending_score: float = 0.5,
        visual_quality: float = 0.7,
    ) -> str:
        # Duration score: 30-90s is optimal for shorts
        dur_score = 1.0 if 30 <= duration_sec <= 90 else max(0, 1 - abs(duration_sec - 60) / 120)
        hook_score = 1.0 if has_hook else 0.3
        scores = {
            'duration': round(dur_score * 100, 1),
            'hook': round(hook_score * 100, 1),
            'energy': round(energy_level * 100, 1),
            'trending_topic': round(topic_trending_score * 100, 1),
            'visual_quality': round(visual_quality * 100, 1),
        }
        weights = {'duration': 0.2, 'hook': 0.25, 'energy': 0.2, 'trending_topic': 0.25, 'visual_quality': 0.1}
        composite = sum(scores[k] * weights[k] for k in scores)
        return json.dumps(
            {
                'composite_score': round(composite, 2),
                'tier': 'high' if composite > 70 else 'medium' if composite > 45 else 'low',
                'dimensions': scores,
            }
        )


class ClipPotentialRankerTool(BaseTool):
    name: str = 'Clip Potential Ranker'
    description: str = 'Rank a list of clip metadata dicts by potential score.'

    def _run(self, clips_json: str) -> str:
        clips = json.loads(clips_json) if isinstance(clips_json, str) else clips_json
        scorer = ClipPotentialScorerTool()
        for clip in clips:
            result = json.loads(
                scorer._run(
                    duration_sec=clip.get('duration_sec', 60),
                    has_hook=clip.get('has_hook', True),
                    energy_level=clip.get('energy_level', 0.5),
                    topic_trending_score=clip.get('topic_trending_score', 0.5),
                    visual_quality=clip.get('visual_quality', 0.7),
                )
            )
            clip['potential_score'] = result['composite_score']
            clip['potential_tier'] = result['tier']
        ranked = sorted(clips, key=lambda x: x.get('potential_score', 0), reverse=True)
        for i, c in enumerate(ranked):
            c['rank'] = i + 1
        return json.dumps({'count': len(ranked), 'ranked': ranked})


class CompositeMetricScorerTool(BaseTool):
    name: str = 'Composite Metric Scorer'
    description: str = (
        'Compute a weighted composite score from multiple metric inputs. '
        'Input: JSON dict of {metric: value} and optional {metric: weight}.'
    )

    def _run(self, metrics_json: str, weights_json: str = '{}') -> str:
        metrics = json.loads(metrics_json) if isinstance(metrics_json, str) else metrics_json
        weights = json.loads(weights_json) if isinstance(weights_json, str) else weights_json
        if not weights:
            weights = {k: 1.0 for k in metrics}
        total_weight = sum(weights.get(k, 1.0) for k in metrics)
        composite = sum(float(v) * weights.get(k, 1.0) for k, v in metrics.items()) / max(total_weight, 1)
        return json.dumps(
            {
                'composite_score': round(composite, 4),
                'metrics': metrics,
                'weights': weights,
                'total_weight': round(total_weight, 4),
            }
        )
