# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""
Pipeline/custom logic tools: registries, schedulers, queues, monitors, scorers,
emitters, gates, and all internal CLIPFARM pipeline utilities.
All tools use only stdlib + sqlalchemy/redis where available; pure-Python fallbacks
ensure they run even without those services.
"""


# Re-export block: every name the single-file pipeline_tools.py defined, so that
# attribute access such as pipeline_tools.os / pipeline_tools.ConfigStoreTool and
# `from ...pipeline_tools import X` keep resolving unchanged.

from .base import (
    _AMS_TZ,
    _LOCKS,
    _RUNTIME_DIR,
    _STORES,
    _ams_iso,
    _ams_now,
    _now_iso,
    _runtime_path,
    _store_all,
    _store_get,
    _store_set,
    _zyg_log,
    _zyg_logging,
    datetime,
    defaultdict,
    exe,
    hashlib,
    importlib,
    json,
    os,
    threading,
    time,
    timezone,
)

from .config_registry import (
    ChannelRegistryTool,
    ConfigStoreTool,
    DuplicateFlagCheckerTool,
    DuplicateFlagRegistryTool,
    FileRegistryTool,
    PlatformCredentialsRegistryTool,
    SafetyThresholdCheckerTool,
    SystemParameterStoreTool,
)

from .scheduling_queue import (
    CronTaskSchedulerTool,
    JobQueueBuilderTool,
    PrioritySchedulerTool,
    RetryQueueManagerTool,
)

from .scoring_analytics import (
    ClipPotentialRankerTool,
    ClipPotentialScorerTool,
    CompositeMetricScorerTool,
    EngagementRateCalculatorTool,
    LikeRatioAnalyzerTool,
    MomentumDetectorTool,
    PercentileRankerTool,
    VPHCalculatorTool,
    VPHRankerTool,
    ViralityScoreCalculatorTool,
)

from .clip_logging import (
    AlertNotifierTool,
    AuditLoggerTool,
    BlockerReportEmitterTool,
    CleanupLoggerTool,
    ClipBoundaryExtractorTool,
    ClipDurationValidatorTool,
    ClipMetadataReaderTool,
    ConfigChangeLoggerTool,
    ConfigErrorReportEmitterTool,
    DiskBlockReportEmitterTool,
    HardwareBlockReportEmitterTool,
    PostIDLoggerTool,
    PublishedStatusLoggerTool,
    QuotaExhaustedEmitterTool,
    StorageWarningEmitterTool,
    _log_event,
)

from .gates_hooks import (
    HookInjectorTool,
    HookScriptReaderTool,
    HookTemplateStoreTool,
    HookTemplateTool,
    HookTemplateUpdaterTool,
    JobApprovalGateTool,
    TokenGrantDelayDenyTool,
    ZeroApprovalGateTool,
    ZeroApprovalRequestSenderTool,
)

from .misc_pipeline import (
    CPUResourceAllocatorTool,
    GPUResourceAllocatorTool,
    MarkdownHTMLReportBuilderTool,
    PublishTimeSchedulerTool,
    QuotaTrackerTool,
    TaskDecomposerTool,
    TaskTypeClassifierTool,
    TempFileCleanerTool,
    TimeslotAllocatorTool,
)

from .new_tools import (
    AudienceActivityAnalyzerTool,
    CompositeScoreEngineTool,
    EditingPatternEngineTool,
    ErrorClassifierTool,
    ExecutionCalendarTool,
    KeywordTriggerMatcherTool,
    NicheKeywordMergerTool,
    OptimalTimeCalculatorTool,
    ProcessingLogParserTool,
    QuotaWarningEmitterTool,
    ReportGeneratorTool,
    RightsAssessmentReaderTool,
    RiskLevelFilterTool,
    SelectionRuleUpdaterTool,
    TimeslotConflictCheckerTool,
    TopBottomClipComparatorTool,
    TopChannelAggregatorTool,
    TrendRelevanceFilterTool,
    TrendWeightUpdaterTool,
    VariantSetBuilderTool,
    VideoSetSelectorTool,
    ViewVelocityTrackerTool,
    WindowResetTimerTool,
    WinningPatternRegistryTool,
)

from .registry import (
    PIPELINE_TOOLS,
)

# The re-export surface, in the import order above: .registry computes the same
# list of tool classes plus PIPELINE_TOOLS, and this one adds the module-level
# plumbing names the single file also bound.
__all__ = [
    '_AMS_TZ',
    '_LOCKS',
    '_RUNTIME_DIR',
    '_STORES',
    '_ams_iso',
    '_ams_now',
    '_now_iso',
    '_runtime_path',
    '_store_all',
    '_store_get',
    '_store_set',
    '_zyg_log',
    '_zyg_logging',
    'datetime',
    'defaultdict',
    'exe',
    'hashlib',
    'importlib',
    'json',
    'os',
    'threading',
    'time',
    'timezone',
    'ChannelRegistryTool',
    'ConfigStoreTool',
    'DuplicateFlagCheckerTool',
    'DuplicateFlagRegistryTool',
    'FileRegistryTool',
    'PlatformCredentialsRegistryTool',
    'SafetyThresholdCheckerTool',
    'SystemParameterStoreTool',
    'CronTaskSchedulerTool',
    'JobQueueBuilderTool',
    'PrioritySchedulerTool',
    'RetryQueueManagerTool',
    'ClipPotentialRankerTool',
    'ClipPotentialScorerTool',
    'CompositeMetricScorerTool',
    'EngagementRateCalculatorTool',
    'LikeRatioAnalyzerTool',
    'MomentumDetectorTool',
    'PercentileRankerTool',
    'VPHCalculatorTool',
    'VPHRankerTool',
    'ViralityScoreCalculatorTool',
    'AlertNotifierTool',
    'AuditLoggerTool',
    'BlockerReportEmitterTool',
    'CleanupLoggerTool',
    'ClipBoundaryExtractorTool',
    'ClipDurationValidatorTool',
    'ClipMetadataReaderTool',
    'ConfigChangeLoggerTool',
    'ConfigErrorReportEmitterTool',
    'DiskBlockReportEmitterTool',
    'HardwareBlockReportEmitterTool',
    'PostIDLoggerTool',
    'PublishedStatusLoggerTool',
    'QuotaExhaustedEmitterTool',
    'StorageWarningEmitterTool',
    '_log_event',
    'HookInjectorTool',
    'HookScriptReaderTool',
    'HookTemplateStoreTool',
    'HookTemplateTool',
    'HookTemplateUpdaterTool',
    'JobApprovalGateTool',
    'TokenGrantDelayDenyTool',
    'ZeroApprovalGateTool',
    'ZeroApprovalRequestSenderTool',
    'CPUResourceAllocatorTool',
    'GPUResourceAllocatorTool',
    'MarkdownHTMLReportBuilderTool',
    'PublishTimeSchedulerTool',
    'QuotaTrackerTool',
    'TaskDecomposerTool',
    'TaskTypeClassifierTool',
    'TempFileCleanerTool',
    'TimeslotAllocatorTool',
    'AudienceActivityAnalyzerTool',
    'CompositeScoreEngineTool',
    'EditingPatternEngineTool',
    'ErrorClassifierTool',
    'ExecutionCalendarTool',
    'KeywordTriggerMatcherTool',
    'NicheKeywordMergerTool',
    'OptimalTimeCalculatorTool',
    'ProcessingLogParserTool',
    'QuotaWarningEmitterTool',
    'ReportGeneratorTool',
    'RightsAssessmentReaderTool',
    'RiskLevelFilterTool',
    'SelectionRuleUpdaterTool',
    'TimeslotConflictCheckerTool',
    'TopBottomClipComparatorTool',
    'TopChannelAggregatorTool',
    'TrendRelevanceFilterTool',
    'TrendWeightUpdaterTool',
    'VariantSetBuilderTool',
    'VideoSetSelectorTool',
    'ViewVelocityTrackerTool',
    'WindowResetTimerTool',
    'WinningPatternRegistryTool',
    'PIPELINE_TOOLS',
]


# Conditionally-bound names: present only when their optional import succeeded.
from . import base as _base

for _n in ('BaseTool', 'ZoneInfo'):
    if hasattr(_base, _n):
        globals()[_n] = getattr(_base, _n)
del _n, _base
