# Route inventory

| app | routes | GET-only | with params | body methods | danger | external |
|---|---:|---:|---:|---:|---:|---:|
| dashboard | 433 | 265 | 103 | 168 | 94 | 21 |
| zero_public | 83 | 60 | 33 | 23 | 14 | 13 |
| medusa | 52 | 28 | 20 | 24 | 18 | 6 |

## dashboard (433 routes)

| rule | methods | gate | danger | external | func |
|---|---|---|---|---|---|
| `/` | GET | login |  |  | src/zyg_dashboard/crewai_web_gui.py:1010 |
| `/api/admin/schedule-pause` | GET | login |  |  | src/zyg_dashboard/bp_jobs_audit.py:582 |
| `/api/admin/schedule-pause` | POST | login | yes |  | src/zyg_dashboard/bp_jobs_audit.py:605 |
| `/api/admin/security-controls` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:296 |
| `/api/admin/security-controls/<control_id>` | PATCH | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:308 |
| `/api/agent_model_audit` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1007 |
| `/api/agent_model_bar_mapping` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:674 |
| `/api/agent_network` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1042 |
| `/api/agent_tree` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1036 |
| `/api/agents` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:132 |
| `/api/agents/<path:agent_name>/logbook` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:598 |
| `/api/agents/active` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:956 |
| `/api/agents/assigned-to/<user_id>` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:396 |
| `/api/agents/config` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:490 |
| `/api/agents/config/<path:agent_name>` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:537 |
| `/api/agents/department/<department>` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:289 |
| `/api/agents/face/<path:identifier>` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:384 |
| `/api/agents/tier1` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:243 |
| `/api/approval_queue/<wf>/action` | POST | localhost |  |  | src/zyg_dashboard/bp_approval_queue.py:769 |
| `/api/approval_queue/<wf>/settings` | POST | localhost |  |  | src/zyg_dashboard/bp_approval_queue.py:829 |
| `/api/approval_queue/board` | GET | localhost |  |  | src/zyg_dashboard/bp_approval_queue.py:696 |
| `/api/approval_queue/calendar` | GET | localhost |  |  | src/zyg_dashboard/bp_approval_queue.py:748 |
| `/api/approval_queue/preempt/item/<item_id>/action` | POST | localhost |  |  | src/zyg_dashboard/bp_approval_queue.py:852 |
| `/api/approvals` | POST | login |  |  | src/zyg_dashboard/bp_jobs_audit.py:117 |
| `/api/approvals/queue` | GET | login |  |  | src/zyg_dashboard/bp_jobs_audit.py:50 |
| `/api/asset_manager/prompts` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:1670 |
| `/api/assetlib/delete` | POST | login | yes |  | src/zyg_dashboard/bp_assets_media.py:940 |
| `/api/assetlib/generated` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:967 |
| `/api/assetlib/list` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:890 |
| `/api/assetlib/preview` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:917 |
| `/api/assets/download` | POST | login | yes |  | src/zyg_dashboard/bp_assets_media.py:285 |
| `/api/assets/preview/<asset_type>/<path:filename>` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:329 |
| `/api/assets/status` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:294 |
| `/api/audit` | GET | login |  |  | src/zyg_dashboard/bp_jobs_audit.py:135 |
| `/api/available_models` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:997 |
| `/api/azure/config` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:625 |
| `/api/azure/config` | POST | login | yes |  | src/zyg_dashboard/bp_integrity_ops.py:647 |
| `/api/azure/reset_counter` | POST | login | yes |  | src/zyg_dashboard/bp_integrity_ops.py:672 |
| `/api/azure/usage` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:613 |
| `/api/benchmark` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:1191 |
| `/api/benchmark/multirun` | POST | login | yes |  | src/zyg_dashboard/bp_benchmark.py:1087 |
| `/api/benchmark/multirun/<session_id>` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:1118 |
| `/api/benchmark/pipeline_history` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:423 |
| `/api/benchmark/run` | POST | login | yes |  | src/zyg_dashboard/bp_benchmark.py:602 |
| `/api/benchmark/seeds` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:562 |
| `/api/benchmark/status/<run_id>` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:630 |
| `/api/benchmark/system` | GET | login |  | yes | src/zyg_dashboard/bp_benchmark.py:1128 |
| `/api/calibrate` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:379 |
| `/api/calibrate` | POST | login |  |  | src/zyg_dashboard/bp_benchmark.py:385 |
| `/api/channel-data/<channel_key>` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:1843 |
| `/api/channel-data/groups` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:1835 |
| `/api/context_ledger` | GET | login |  |  | src/zyg_dashboard/bp_skill_sandbox.py:24 |
| `/api/control-settings/data` | GET | login |  |  | src/zyg_dashboard/bp_control_settings.py:241 |
| `/api/control-settings/data/<category>` | GET | login |  |  | src/zyg_dashboard/bp_control_settings.py:252 |
| `/api/control-settings/data/<category>` | PATCH | login |  |  | src/zyg_dashboard/bp_control_settings.py:263 |
| `/api/control-settings/lock` | POST | login |  |  | src/zyg_dashboard/bp_control_settings.py:227 |
| `/api/control-settings/setup` | POST | login |  |  | src/zyg_dashboard/bp_control_settings.py:171 |
| `/api/control-settings/status` | GET | login |  |  | src/zyg_dashboard/bp_control_settings.py:156 |
| `/api/control-settings/unlock` | POST | login |  |  | src/zyg_dashboard/bp_control_settings.py:203 |
| `/api/court-cases` | GET | login |  |  | src/zyg_dashboard/bp_voices.py:124 |
| `/api/cpu/agent_model_bar_mapping` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:682 |
| `/api/cpu/timeline/24h` | GET | login |  |  | src/zyg_dashboard/bp_timeline_legacy.py:222 |
| `/api/cpu/timeline/add_entry` | POST | login |  |  | src/zyg_dashboard/bp_timeline_legacy.py:247 |
| `/api/cpu/timeline/delete_entry` | POST | login | yes |  | src/zyg_dashboard/bp_timeline_legacy.py:279 |
| `/api/creator-nexus/snapshots` | GET | open |  |  | ../creator-nexus/src/zyg_nexus/bp_creator_nexus.py:293 |
| `/api/creator-nexus/snapshots/<name>` | GET | open |  |  | ../creator-nexus/src/zyg_nexus/bp_creator_nexus.py:318 |
| `/api/creator-nexus/state` | GET POST | open |  |  | ../creator-nexus/src/zyg_nexus/bp_creator_nexus.py:174 |
| `/api/csrf-token` | GET | login |  |  | src/zyg_dashboard/bp_auth.py:290 |
| `/api/dashboard/blueprint` | POST | login |  |  | src/zyg_dashboard/bp_themes_users.py:133 |
| `/api/dashboard/error_logs` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:344 |
| `/api/dashboard/error_logs` | POST | login | yes |  | src/zyg_dashboard/bp_integrity_ops.py:364 |
| `/api/dashboard/job_status` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:370 |
| `/api/dashboard/job_status` | POST | login | yes |  | src/zyg_dashboard/bp_integrity_ops.py:469 |
| `/api/dashboard/language_link/<language_name>` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:589 |
| `/api/dashboard/language_pack/<language_name>` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:572 |
| `/api/dashboard/monitoring_jobs` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:475 |
| `/api/dashboard/monitoring_jobs` | POST | login | yes |  | src/zyg_dashboard/bp_integrity_ops.py:566 |
| `/api/dashboard/my_account` | GET | login |  |  | src/zyg_dashboard/bp_auth.py:260 |
| `/api/dashboard/my_account` | POST | login | yes |  | src/zyg_dashboard/bp_auth.py:284 |
| `/api/dashboard/themes/backgrounds/file/<path:filename>` | GET | login |  |  | src/zyg_dashboard/bp_themes_users.py:86 |
| `/api/dashboard/themes/backgrounds/list` | GET | login |  |  | src/zyg_dashboard/bp_themes_users.py:78 |
| `/api/dashboard/themes/buttons/file/<path:filename>` | GET | login |  |  | src/zyg_dashboard/bp_themes_users.py:68 |
| `/api/dashboard/themes/buttons/list` | GET | login |  |  | src/zyg_dashboard/bp_themes_users.py:60 |
| `/api/dashboard/themes/config` | GET | login |  |  | src/zyg_dashboard/bp_themes_users.py:29 |
| `/api/dashboard/themes/config` | POST | login | yes |  | src/zyg_dashboard/bp_themes_users.py:53 |
| `/api/dashboard/themes/sidebar/file/<path:filename>` | GET | login |  |  | src/zyg_dashboard/bp_themes_users.py:104 |
| `/api/dashboard/themes/sidebar/list` | GET | login |  |  | src/zyg_dashboard/bp_themes_users.py:96 |
| `/api/dashboard/users` | GET | login |  |  | src/zyg_dashboard/bp_themes_users.py:114 |
| `/api/dashboard/users` | POST | login | yes |  | src/zyg_dashboard/bp_themes_users.py:121 |
| `/api/dashboard/users/avatar/<user_id>` | POST | login | yes |  | src/zyg_dashboard/bp_themes_users.py:127 |
| `/api/departments` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:442 |
| `/api/dependencies/status` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:1045 |
| `/api/disk_usage` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:252 |
| `/api/effects/delete` | POST | login | yes |  | src/zyg_dashboard/bp_assets_media.py:863 |
| `/api/effects/library` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:830 |
| `/api/effects/list` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:764 |
| `/api/effects/preview` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:844 |
| `/api/envfx/media` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:978 |
| `/api/environments/list` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:759 |
| `/api/flagged/save` | POST | login | yes |  | src/zyg_dashboard/bp_timeline_legacy.py:49 |
| `/api/frequency/data` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:196 |
| `/api/frequency/history` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:275 |
| `/api/frequency/history/<pipeline_id>` | GET | login |  |  | src/zyg_dashboard/bp_benchmark.py:306 |
| `/api/frontend_log` | POST | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1697 |
| `/api/gpu/release` | POST | login |  |  | src/zyg_dashboard/bp_agents_api.py:480 |
| `/api/gpu/schedule` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:452 |
| `/api/gpu/timeline/24h` | GET | login |  |  | src/zyg_dashboard/bp_timeline_legacy.py:302 |
| `/api/gpu/timeline/add_entry` | POST | login |  |  | src/zyg_dashboard/bp_timeline_legacy.py:329 |
| `/api/gpu/timeline/delete_entry` | POST | login | yes |  | src/zyg_dashboard/bp_timeline_legacy.py:391 |
| `/api/gpu/timeline/generate` | GET | login | yes |  | src/zyg_dashboard/bp_timeline_legacy.py:465 |
| `/api/gpu/timeline/image/<date>` | GET | login |  |  | src/zyg_dashboard/bp_timeline_legacy.py:489 |
| `/api/hardware_table` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1063 |
| `/api/health` | GET | open |  |  | src/zyg_dashboard/bp_auth.py:202 |
| `/api/history` | GET | login |  |  | src/zyg_dashboard/bp_timeline_legacy.py:444 |
| `/api/integrity-gate` | GET | login |  | yes | src/zyg_dashboard/bp_integrity_ops.py:141 |
| `/api/integrity-gate/force-override` | POST | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:324 |
| `/api/internal/char2d/spec` | GET | localhost |  |  | src/zyg_dashboard/bp_char2d.py:38 |
| `/api/internal/char2d/start` | POST | localhost | yes |  | src/zyg_dashboard/bp_char2d.py:64 |
| `/api/internal/creature/<creature_id>/approve` | POST | login | yes |  | src/zyg_dashboard/bp_pipeline_api.py:633 |
| `/api/internal/creature/<creature_id>/reject` | POST | login | yes |  | src/zyg_dashboard/bp_pipeline_api.py:663 |
| `/api/internal/creature/<creature_id>/resume` | POST | login | yes |  | src/zyg_dashboard/bp_pipeline_api.py:641 |
| `/api/internal/creature/<creature_id>/sheet` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:672 |
| `/api/internal/creature/list` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:264 |
| `/api/internal/kidseries/list` | GET | localhost |  |  | src/zyg_dashboard/bp_kidseries.py:50 |
| `/api/internal/kidseries/start` | POST | localhost | yes | yes | src/zyg_dashboard/bp_kidseries.py:71 |
| `/api/internal/kidseries/status` | GET | localhost |  |  | src/zyg_dashboard/bp_kidseries.py:119 |
| `/api/internal/kidseries/stop` | POST | localhost | yes |  | src/zyg_dashboard/bp_kidseries.py:172 |
| `/api/internal/kidsmusic/delete` | POST | localhost | yes |  | src/zyg_dashboard/bp_kidsmusic.py:281 |
| `/api/internal/kidsmusic/remix` | POST | localhost |  |  | src/zyg_dashboard/bp_kidsmusic.py:235 |
| `/api/internal/kidsmusic/spec` | GET | localhost |  |  | src/zyg_dashboard/bp_kidsmusic.py:44 |
| `/api/internal/kidsmusic/start` | POST | localhost | yes | yes | src/zyg_dashboard/bp_kidsmusic.py:58 |
| `/api/internal/kidsmusic/status` | GET | localhost |  |  | src/zyg_dashboard/bp_kidsmusic.py:163 |
| `/api/internal/kidsmusic/stop` | POST | localhost | yes |  | src/zyg_dashboard/bp_kidsmusic.py:210 |
| `/api/internal/movement/delete` | POST | localhost | yes | yes | src/zyg_dashboard/bp_movement.py:693 |
| `/api/internal/movement/driver` | GET POST | localhost |  |  | src/zyg_dashboard/bp_movement.py:604 |
| `/api/internal/movement/plate` | POST | localhost |  |  | src/zyg_dashboard/bp_movement.py:463 |
| `/api/internal/movement/presets` | GET POST | localhost | yes |  | src/zyg_dashboard/bp_movement.py:669 |
| `/api/internal/movement/prompt` | POST | localhost |  |  | src/zyg_dashboard/bp_movement.py:425 |
| `/api/internal/movement/spec` | GET | localhost |  |  | src/zyg_dashboard/bp_movement.py:417 |
| `/api/internal/movement/start` | POST | localhost | yes |  | src/zyg_dashboard/bp_movement.py:717 |
| `/api/internal/movement/status` | GET | localhost |  |  | src/zyg_dashboard/bp_movement.py:792 |
| `/api/internal/movement/stop` | POST | localhost | yes |  | src/zyg_dashboard/bp_movement.py:805 |
| `/api/internal/picture_studio/capability` | GET | localhost |  | yes | src/zyg_dashboard/bp_picture_studio.py:248 |
| `/api/internal/picture_studio/job/<jid>` | GET | localhost |  |  | src/zyg_dashboard/bp_picture_studio.py:239 |
| `/api/internal/picture_studio/submit` | POST | localhost | yes |  | src/zyg_dashboard/bp_picture_studio.py:189 |
| `/api/internal/pipeline/download/<pipeline_id>/<path:filename>` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:926 |
| `/api/internal/pipeline/start` | POST | login | yes | yes | src/zyg_dashboard/bp_pipeline_api.py:273 |
| `/api/internal/pipeline/status/<pipeline_id>` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:734 |
| `/api/internal/storyteller/analyze-character-photo` | POST | login |  | yes | src/zyg_dashboard/bp_storyteller.py:546 |
| `/api/internal/storyteller/char-preview-status` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:2628 |
| `/api/internal/storyteller/character-bible/<char_id>` | GET | login |  | yes | src/zyg_dashboard/bp_storyteller.py:2008 |
| `/api/internal/storyteller/character-status/<char_id>` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:2023 |
| `/api/internal/storyteller/character/<char_id>/preview/regenerate` | POST | login | yes |  | src/zyg_dashboard/bp_storyteller.py:2252 |
| `/api/internal/storyteller/character/<char_id>/preview/status` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:2386 |
| `/api/internal/storyteller/contact-sheet/approve/<char_id>` | POST | login | yes |  | src/zyg_dashboard/bp_storyteller.py:738 |
| `/api/internal/storyteller/contact-sheet/image/<char_id>` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:898 |
| `/api/internal/storyteller/contact-sheet/pause/<char_id>` | POST | login | yes |  | src/zyg_dashboard/bp_storyteller.py:775 |
| `/api/internal/storyteller/contact-sheet/resume/<char_id>` | POST | login | yes |  | src/zyg_dashboard/bp_storyteller.py:801 |
| `/api/internal/storyteller/contact-sheet/start` | POST | login | yes |  | src/zyg_dashboard/bp_storyteller.py:575 |
| `/api/internal/storyteller/contact-sheet/status/<char_id>` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:662 |
| `/api/internal/storyteller/gen-char-previews` | POST | login |  |  | src/zyg_dashboard/bp_storyteller.py:2401 |
| `/api/internal/storyteller/generate-character` | POST | login | yes | yes | src/zyg_dashboard/bp_storyteller.py:1040 |
| `/api/internal/storyteller/list-chars` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:277 |
| `/api/internal/storyteller/list-contact-sheets` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:1013 |
| `/api/internal/storyteller/pipeline/pause` | POST | login | yes |  | src/zyg_dashboard/bp_storyteller.py:810 |
| `/api/internal/storyteller/pipeline/pause-state` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:868 |
| `/api/internal/storyteller/pipeline/resume` | POST | login | yes |  | src/zyg_dashboard/bp_storyteller.py:847 |
| `/api/internal/storyteller/voice-sample/<voice_id>/<variant>` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:1984 |
| `/api/internal/storyteller/voices` | GET | login |  |  | src/zyg_dashboard/bp_storyteller.py:1957 |
| `/api/internal/zero/classify` | POST | login |  |  | src/zyg_dashboard/bp_zero.py:711 |
| `/api/jackmona/abort` | POST | login |  |  | src/zyg_dashboard/bp_jackmona_daily.py:517 |
| `/api/jackmona/daily_batch` | GET | login |  |  | src/zyg_dashboard/bp_jackmona_daily.py:502 |
| `/api/jackmona/daily_mode` | GET POST | login |  |  | src/zyg_dashboard/bp_jackmona_daily.py:485 |
| `/api/jackmona/run_now` | POST | login | yes |  | src/zyg_dashboard/bp_jackmona_daily.py:524 |
| `/api/jobs/events` | GET | login |  |  | src/zyg_dashboard/bp_jobs_audit.py:368 |
| `/api/jobs/runs` | GET | login |  |  | src/zyg_dashboard/bp_jobs_audit.py:283 |
| `/api/jobs/runs/expire-leases` | POST | login | yes |  | src/zyg_dashboard/bp_jobs_audit.py:575 |
| `/api/jobs/specs` | GET | login |  |  | src/zyg_dashboard/bp_jobs_audit.py:226 |
| `/api/kanban/clear_errors` | POST | open | yes |  | src/zyg_dashboard/bp_pipeline_api.py:1304 |
| `/api/kanban/status` | GET | open |  |  | src/zyg_dashboard/bp_pipeline_api.py:1047 |
| `/api/live_log` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1704 |
| `/api/llms/list` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:983 |
| `/api/login` | POST | open | yes |  | src/zyg_dashboard/bp_auth.py:108 |
| `/api/logout` | POST | open | yes |  | src/zyg_dashboard/bp_auth.py:193 |
| `/api/market/episodes` | GET | login |  |  | src/zyg_dashboard/bp_market.py:147 |
| `/api/market/history` | GET | login |  |  | src/zyg_dashboard/bp_market.py:186 |
| `/api/market/icebox` | GET | login |  |  | src/zyg_dashboard/bp_market.py:169 |
| `/api/market/icebox/delete` | POST | login | yes |  | src/zyg_dashboard/bp_market.py:180 |
| `/api/market/icebox/used` | POST | login |  |  | src/zyg_dashboard/bp_market.py:174 |
| `/api/market/media/<dept>/<pid>/<path:fname>` | GET | login |  |  | src/zyg_dashboard/bp_market.py:152 |
| `/api/market/preview/<dept>` | GET | login |  |  | src/zyg_dashboard/bp_market.py:191 |
| `/api/market/run` | POST | login | yes |  | src/zyg_dashboard/bp_market.py:63 |
| `/api/market/settings` | GET | login |  |  | src/zyg_dashboard/bp_market.py:111 |
| `/api/market/settings` | POST | login |  |  | src/zyg_dashboard/bp_market.py:116 |
| `/api/market/status` | GET | login |  |  | src/zyg_dashboard/bp_market.py:75 |
| `/api/marketing/dismiss` | POST | open |  |  | src/zyg_dashboard/bp_assets_media.py:1066 |
| `/api/marketing/dismissed` | GET | open |  |  | src/zyg_dashboard/bp_assets_media.py:1056 |
| `/api/marketing/undismiss` | POST | open |  |  | src/zyg_dashboard/bp_assets_media.py:1097 |
| `/api/marketing/upload` | POST | open | yes | yes | src/zyg_dashboard/bp_assets_media.py:1375 |
| `/api/medusa/angles` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa.py:415 |
| `/api/medusa/generate` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa.py:356 |
| `/api/medusa/jobs` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa.py:474 |
| `/api/medusa/kanban_status` | GET | open |  |  | src/zyg_dashboard/bp_medusa.py:624 |
| `/api/medusa/models` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:309 |
| `/api/medusa/models` | POST | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:414 |
| `/api/medusa/models/<model_id>` | DELETE | localhost | yes |  | src/zyg_dashboard/bp_medusa_models.py:494 |
| `/api/medusa/models/<model_id>` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:451 |
| `/api/medusa/models/<model_id>` | PATCH | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:459 |
| `/api/medusa/models/<model_id>/activate` | POST | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:812 |
| `/api/medusa/models/<model_id>/attest` | POST | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:511 |
| `/api/medusa/models/<model_id>/captions/reset` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_models.py:876 |
| `/api/medusa/models/<model_id>/deactivate` | POST | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:828 |
| `/api/medusa/models/<model_id>/images` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:530 |
| `/api/medusa/models/<model_id>/images` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_models.py:557 |
| `/api/medusa/models/<model_id>/images/<name>` | DELETE | localhost | yes |  | src/zyg_dashboard/bp_medusa_models.py:601 |
| `/api/medusa/models/<model_id>/images/<name>` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:590 |
| `/api/medusa/models/<model_id>/ingest/folder` | POST | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:698 |
| `/api/medusa/models/<model_id>/ingest/urls` | POST | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:623 |
| `/api/medusa/models/<model_id>/sample` | POST | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:843 |
| `/api/medusa/models/<model_id>/sample/<name>` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:865 |
| `/api/medusa/models/<model_id>/status` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:794 |
| `/api/medusa/models/<model_id>/train` | POST | localhost | yes | yes | src/zyg_dashboard/bp_medusa_models.py:760 |
| `/api/medusa/models/active` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_models.py:442 |
| `/api/medusa/pending` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa.py:430 |
| `/api/medusa/pending/<req_id>/decide` | POST | localhost |  |  | src/zyg_dashboard/bp_medusa.py:437 |
| `/api/medusa/training/characters` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:1011 |
| `/api/medusa/training/characters` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:965 |
| `/api/medusa/training/characters/<char_id>` | DELETE | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:1036 |
| `/api/medusa/training/characters/<char_id>` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:1028 |
| `/api/medusa/training/characters/<char_id>/body-prepare` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:818 |
| `/api/medusa/training/characters/<char_id>/body-prepare` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:762 |
| `/api/medusa/training/characters/<char_id>/images` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:1071 |
| `/api/medusa/training/characters/<char_id>/images/<image_id>` | DELETE | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:1130 |
| `/api/medusa/training/characters/<char_id>/images/<image_id>` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:1118 |
| `/api/medusa/training/characters/<char_id>/sheet` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:738 |
| `/api/medusa/training/characters/<char_id>/sheet` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:715 |
| `/api/medusa/training/characters/<char_id>/sheet/page/<page>` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:748 |
| `/api/medusa/training/characters/<char_id>/status` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:1240 |
| `/api/medusa/training/characters/<char_id>/train` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:1153 |
| `/api/medusa/training/import-folders` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:643 |
| `/api/medusa/training/import-root` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:603 |
| `/api/medusa/training/import/<batch_id>` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:704 |
| `/api/medusa/training/loras` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:1275 |
| `/api/medusa/training/loras/<char_id>/<family>/sample/<name>` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:1328 |
| `/api/medusa/training/scan-folder` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:625 |
| `/api/medusa/training/sheets` | GET | localhost |  |  | src/zyg_dashboard/bp_medusa_training.py:825 |
| `/api/medusa/training/sheets/build-all` | POST | localhost | yes |  | src/zyg_dashboard/bp_medusa_training.py:879 |
| `/api/melody/daily_batch` | GET | login |  |  | src/zyg_dashboard/bp_melody_daily.py:812 |
| `/api/melody/daily_mode` | GET POST | login |  |  | src/zyg_dashboard/bp_melody_daily.py:798 |
| `/api/metrics/all` | GET | login |  |  | src/zyg_dashboard/bp_metrics.py:198 |
| `/api/metrics/analytics/config` | GET POST | login |  |  | src/zyg_dashboard/bp_metrics.py:156 |
| `/api/metrics/character-quality` | GET | login |  |  | src/zyg_dashboard/bp_metrics.py:49 |
| `/api/metrics/dashboard` | GET | login |  |  | src/zyg_dashboard/bp_metrics.py:217 |
| `/api/metrics/hub/<section>` | GET | login |  |  | src/zyg_dashboard/bp_metrics.py:128 |
| `/api/metrics/summary` | GET | login |  |  | src/zyg_dashboard/bp_metrics.py:174 |
| `/api/model_ids` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1100 |
| `/api/orchestration/permissions` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1107 |
| `/api/output-scp/config` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:56 |
| `/api/output-scp/config` | PATCH | login |  |  | src/zyg_dashboard/bp_assets_media.py:66 |
| `/api/output/new-videos` | GET | open |  |  | src/zyg_dashboard/bp_assets_media.py:1119 |
| `/api/pipeline/active` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1608 |
| `/api/pipeline/flags` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1746 |
| `/api/pipeline/murch_debug/<pipeline_id>` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1579 |
| `/api/pipeline/test` | POST | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1647 |
| `/api/pipeline/timeline/<pipeline_id>` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1350 |
| `/api/pipeline/timeline/<pipeline_id>/download` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1458 |
| `/api/pipeline_stages` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1048 |
| `/api/preempt/action` | POST | localhost |  |  | src/zyg_dashboard/bp_preempt.py:579 |
| `/api/preempt/entry/<entry_id>/verify` | POST | localhost |  |  | src/zyg_dashboard/bp_preempt.py:596 |
| `/api/preempt/job/<pid>` | GET | localhost |  |  | src/zyg_dashboard/bp_preempt.py:623 |
| `/api/preempt/state` | GET | localhost |  |  | src/zyg_dashboard/bp_preempt.py:574 |
| `/api/prompt_log` | GET | login |  | yes | src/zyg_dashboard/bp_agents_api.py:634 |
| `/api/prompt_registry/revert` | POST | login |  |  | src/zyg_dashboard/bp_assets_media.py:1798 |
| `/api/prompt_registry/update` | POST | login |  |  | src/zyg_dashboard/bp_assets_media.py:1753 |
| `/api/remix/candidates` | GET | login |  |  | src/zyg_dashboard/bp_remix.py:111 |
| `/api/remix/channels` | GET | login |  |  | src/zyg_dashboard/bp_remix.py:73 |
| `/api/remix/channels` | POST | login |  |  | src/zyg_dashboard/bp_remix.py:86 |
| `/api/remix/channels/<channel_id>` | DELETE | login |  |  | src/zyg_dashboard/bp_remix.py:97 |
| `/api/remix/channels/<channel_id>/toggle` | POST | login | yes |  | src/zyg_dashboard/bp_remix.py:102 |
| `/api/remix/clips` | GET | login |  |  | src/zyg_dashboard/bp_remix.py:185 |
| `/api/remix/compile` | POST | login |  |  | src/zyg_dashboard/bp_remix.py:127 |
| `/api/remix/media/<pid>/<path:fname>` | GET | login |  |  | src/zyg_dashboard/bp_remix.py:195 |
| `/api/remix/run` | POST | login | yes |  | src/zyg_dashboard/bp_remix.py:116 |
| `/api/remix/settings` | GET | login |  |  | src/zyg_dashboard/bp_remix.py:142 |
| `/api/remix/settings` | POST | login |  |  | src/zyg_dashboard/bp_remix.py:147 |
| `/api/remix/status` | GET | login |  |  | src/zyg_dashboard/bp_remix.py:152 |
| `/api/remixai/candidates` | GET | login |  |  | src/zyg_dashboard/bp_remixai.py:123 |
| `/api/remixai/library` | GET | login |  |  | src/zyg_dashboard/bp_remixai.py:194 |
| `/api/remixai/media/<pid>/<path:fname>` | GET | login |  |  | src/zyg_dashboard/bp_remixai.py:204 |
| `/api/remixai/run` | POST | login | yes |  | src/zyg_dashboard/bp_remixai.py:138 |
| `/api/remixai/settings` | GET | login |  |  | src/zyg_dashboard/bp_remixai.py:64 |
| `/api/remixai/settings` | POST | login |  |  | src/zyg_dashboard/bp_remixai.py:69 |
| `/api/remixai/status` | GET | login |  |  | src/zyg_dashboard/bp_remixai.py:158 |
| `/api/remixai/stop` | POST | login | yes |  | src/zyg_dashboard/bp_remixai.py:151 |
| `/api/remixai/sweep` | POST | login |  |  | src/zyg_dashboard/bp_remixai.py:103 |
| `/api/remixai/terms` | DELETE | login |  |  | src/zyg_dashboard/bp_remixai.py:92 |
| `/api/remixai/terms` | GET | login |  |  | src/zyg_dashboard/bp_remixai.py:74 |
| `/api/remixai/terms` | POST | login |  |  | src/zyg_dashboard/bp_remixai.py:79 |
| `/api/restart` | POST | login | yes | yes | src/zyg_dashboard/bp_auth.py:208 |
| `/api/restart_dashboard` | POST | login | yes |  | src/zyg_dashboard/bp_timeline_legacy.py:75 |
| `/api/rfd/clips` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:347 |
| `/api/run_single_agent` | POST | login | yes |  | src/zyg_dashboard/bp_pipeline_api.py:130 |
| `/api/run_task` | POST | login | yes |  | src/zyg_dashboard/bp_pipeline_api.py:86 |
| `/api/safety/confirm_recovery` | POST | login |  |  | src/zyg_dashboard/bp_safety.py:210 |
| `/api/safety/emergency_stop` | POST | login | yes |  | src/zyg_dashboard/bp_safety.py:123 |
| `/api/safety/emergency_stop_full` | POST | login | yes |  | src/zyg_dashboard/bp_safety.py:160 |
| `/api/safety/status` | GET | login |  |  | src/zyg_dashboard/bp_safety.py:72 |
| `/api/safety/thresholds` | GET | login |  |  | src/zyg_dashboard/bp_safety.py:240 |
| `/api/safety/thresholds` | PATCH | login |  |  | src/zyg_dashboard/bp_safety.py:258 |
| `/api/schedule/add_entry` | POST | login |  |  | src/zyg_dashboard/bp_schedule.py:123 |
| `/api/schedule/delete_entry` | POST | login | yes |  | src/zyg_dashboard/bp_schedule.py:139 |
| `/api/schedule/live` | GET | login |  |  | src/zyg_dashboard/bp_schedule.py:99 |
| `/api/schedule/meta` | GET | login |  |  | src/zyg_dashboard/bp_schedule.py:92 |
| `/api/schedule/telemetry_window` | GET | login |  |  | src/zyg_dashboard/bp_schedule.py:152 |
| `/api/schedule/upcoming` | GET | login |  |  | src/zyg_dashboard/bp_schedule.py:106 |
| `/api/scholarly/imagery` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:447 |
| `/api/scholarly/imagery/thumb` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:493 |
| `/api/scholarly/videos` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:510 |
| `/api/settings/huggingface` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:848 |
| `/api/settings/huggingface` | POST | login | yes |  | src/zyg_dashboard/bp_integrity_ops.py:856 |
| `/api/settings/huggingface/download` | POST | login | yes |  | src/zyg_dashboard/bp_integrity_ops.py:913 |
| `/api/settings/huggingface/test` | POST | login |  | yes | src/zyg_dashboard/bp_integrity_ops.py:881 |
| `/api/skill/sandbox/check` | POST | login | yes |  | src/zyg_dashboard/bp_skill_sandbox.py:93 |
| `/api/skill/sandbox/result/<skill_id>` | GET | login |  |  | src/zyg_dashboard/bp_skill_sandbox.py:107 |
| `/api/skill/sandbox/status` | GET | login |  |  | src/zyg_dashboard/bp_skill_sandbox.py:87 |
| `/api/smoke-test/list` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:787 |
| `/api/smoke-test/run` | POST | login | yes | yes | src/zyg_dashboard/bp_integrity_ops.py:691 |
| `/api/smoke-test/status/<run_id>` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:768 |
| `/api/sources` | GET | login |  |  | src/zyg_dashboard/bp_voices.py:112 |
| `/api/sports-video/status` | GET | open |  |  | src/zyg_dashboard/bp_assets_media.py:1857 |
| `/api/sports/episodes` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:193 |
| `/api/sports/fixtures/<category>` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:124 |
| `/api/sports/history` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:232 |
| `/api/sports/icebox` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:215 |
| `/api/sports/icebox/delete` | POST | login | yes |  | src/zyg_dashboard/bp_sports.py:226 |
| `/api/sports/icebox/used` | POST | login |  |  | src/zyg_dashboard/bp_sports.py:220 |
| `/api/sports/media/<dept>/<cat>/<pid>/<path:fname>` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:198 |
| `/api/sports/preview/<department>/<category>` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:153 |
| `/api/sports/run` | POST | login | yes |  | src/zyg_dashboard/bp_sports.py:62 |
| `/api/sports/settings` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:114 |
| `/api/sports/settings` | POST | login |  |  | src/zyg_dashboard/bp_sports.py:119 |
| `/api/sports/status` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:73 |
| `/api/start_clipfarm_workflow` | POST | login | yes |  | src/zyg_dashboard/bp_pipeline_api.py:162 |
| `/api/storyteller/daily_batch` | GET | login |  |  | src/zyg_dashboard/bp_storyteller_daily.py:757 |
| `/api/storyteller/daily_mode` | GET POST | login |  |  | src/zyg_dashboard/bp_storyteller_daily.py:743 |
| `/api/storyteller/episodes` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:582 |
| `/api/storyteller/episodes/<pipeline_id>/video` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:665 |
| `/api/storyteller/templates/<tid>` | GET | login |  |  | src/zyg_dashboard/bp_storyteller_daily.py:778 |
| `/api/storyteller/templates/list` | GET | login |  |  | src/zyg_dashboard/bp_storyteller_daily.py:764 |
| `/api/storyteller/training/characters/<char_id>/retrain` | POST | localhost | yes |  | src/zyg_dashboard/bp_storyteller.py:2181 |
| `/api/storyteller/training/characters/<char_id>/retrain/status` | GET | localhost |  |  | src/zyg_dashboard/bp_storyteller.py:2232 |
| `/api/subprocesses` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1332 |
| `/api/subprocesses/<int:pid>` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:1341 |
| `/api/telemetry` | GET | open |  |  | src/zyg_dashboard/bp_integrity_ops.py:230 |
| `/api/telemetry_log/<pipeline_id>` | GET | login |  |  | src/zyg_dashboard/bp_integrity_ops.py:280 |
| `/api/templates/delete/<tmpl_id>` | DELETE | login | yes |  | src/zyg_dashboard/bp_assets_media.py:1913 |
| `/api/templates/list` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:1885 |
| `/api/templates/outputs` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:1934 |
| `/api/templates/store` | POST | login |  |  | src/zyg_dashboard/bp_assets_media.py:1890 |
| `/api/templates/thumb/<clip_id>/<fname>` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:2007 |
| `/api/timeline/24h` | GET | login |  |  | src/zyg_dashboard/bp_timeline_legacy.py:92 |
| `/api/timeline/add_entry` | POST | login |  |  | src/zyg_dashboard/bp_timeline_legacy.py:116 |
| `/api/tools` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1129 |
| `/api/voices` | GET | login |  |  | src/zyg_dashboard/bp_voices.py:27 |
| `/api/voices/assign` | POST | login |  |  | src/zyg_dashboard/bp_voices.py:56 |
| `/api/voices/channel-assignments` | GET | login |  |  | src/zyg_dashboard/bp_voices.py:39 |
| `/api/voices/play` | POST | login |  |  | src/zyg_dashboard/bp_voices.py:81 |
| `/api/vram/free` | POST | open |  | yes | src/zyg_dashboard/bp_integrity_ops.py:179 |
| `/api/wardrobe/delete` | POST | login | yes |  | src/zyg_dashboard/bp_assets_media.py:807 |
| `/api/wardrobe/list` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:770 |
| `/api/wardrobe/outfits` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:776 |
| `/api/wardrobe/preview` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:790 |
| `/api/workflow/steps/agents` | GET | open |  |  | src/zyg_dashboard/bp_agents_api.py:690 |
| `/api/workflow_box_ids` | GET | login |  |  | src/zyg_dashboard/bp_agents_api.py:1024 |
| `/api/workflow_status/<job_id>` | GET | login |  |  | src/zyg_dashboard/bp_pipeline_api.py:942 |
| `/api/workflow_status/active` | GET | open |  |  | src/zyg_dashboard/bp_pipeline_api.py:978 |
| `/api/youtube/channel-videos` | GET | open | yes |  | src/zyg_dashboard/bp_assets_media.py:1256 |
| `/api/zero-admin-url` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:130 |
| `/api/zero/analyze` | POST | login |  |  | src/zyg_dashboard/bp_claude_clip.py:644 |
| `/api/zero/audit-trail` | GET | login |  |  | src/zyg_dashboard/bp_zero.py:1893 |
| `/api/zero/auto_mode` | GET POST | login |  |  | src/zyg_dashboard/bp_zero.py:1931 |
| `/api/zero/change-impact` | GET POST | login |  |  | src/zyg_dashboard/bp_zero.py:1875 |
| `/api/zero/chat` | POST | login |  | yes | src/zyg_dashboard/bp_zero.py:444 |
| `/api/zero/context` | GET | login |  |  | src/zyg_dashboard/bp_zero.py:311 |
| `/api/zero/decompose` | POST | login |  |  | src/zyg_dashboard/bp_zero.py:1722 |
| `/api/zero/execute_plan` | POST | login | yes |  | src/zyg_dashboard/bp_claude_clip.py:664 |
| `/api/zero/install-llms` | POST | login | yes | yes | src/zyg_dashboard/bp_zero.py:382 |
| `/api/zero/kanban` | GET | login |  |  | src/zyg_dashboard/bp_zero.py:1923 |
| `/api/zero/llms-status` | GET | login |  | yes | src/zyg_dashboard/bp_zero.py:354 |
| `/api/zero/stop` | POST | login | yes | yes | src/zyg_dashboard/bp_zero.py:1692 |
| `/api/zero/stop/reset` | POST | login | yes |  | src/zyg_dashboard/bp_zero.py:1715 |
| `/api/zero/task-state` | GET | login |  |  | src/zyg_dashboard/bp_zero.py:1770 |
| `/api/zero/task-state` | POST | login | yes |  | src/zyg_dashboard/bp_zero.py:1776 |
| `/api/zero/token_usage` | GET | login |  |  | src/zyg_dashboard/bp_claude_clip.py:695 |
| `/api/zero/validation-checklist` | GET | login |  |  | src/zyg_dashboard/bp_zero.py:1790 |
| `/api/zero/workflow-health` | GET | login |  |  | src/zyg_dashboard/bp_zero.py:265 |
| `/api/zero/workflow-override` | POST | login |  |  | src/zyg_dashboard/bp_zero.py:284 |
| `/api/zero_public/pending` | GET | login |  |  | src/zyg_dashboard/bp_zero_public_store.py:272 |
| `/api/zero_public/pending/<req_id>/decide` | POST | login |  |  | src/zyg_dashboard/bp_zero_public_store.py:291 |
| `/api/zero_public/token_check/<token>` | GET | login |  |  | src/zyg_dashboard/bp_zero_public_store.py:229 |
| `/api/zero_public/token_use/<token>` | POST | login |  |  | src/zyg_dashboard/bp_zero_public_store.py:241 |
| `/api/zero_public/urls` | GET | login |  |  | src/zyg_dashboard/bp_zero_public_store.py:167 |
| `/api/zero_public/urls` | POST | login |  |  | src/zyg_dashboard/bp_zero_public_store.py:175 |
| `/api/zero_public/urls/<token>` | DELETE | login |  |  | src/zyg_dashboard/bp_zero_public_store.py:216 |
| `/apple-touch-icon-precomposed.png` | GET | open |  |  | src/zyg_dashboard/crewai_web_gui.py:4205 |
| `/apple-touch-icon.png` | GET | open |  |  | src/zyg_dashboard/crewai_web_gui.py:4205 |
| `/approval_queue` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:54 |
| `/asset_manager/templates_board` | GET | login |  |  | src/zyg_dashboard/bp_assets_media.py:2030 |
| `/audit` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:62 |
| `/benchmark` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:112 |
| `/betting` | GET | login |  |  | src/zyg_dashboard/bp_sports.py:50 |
| `/cpu_schedule.html` | GET | login |  |  | src/zyg_dashboard/bp_schedule.py:44 |
| `/error_logs` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:22 |
| `/favicon.ico` | GET | open |  |  | src/zyg_dashboard/crewai_web_gui.py:4205 |
| `/frequency` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:106 |
| `/gpu_schedule.html` | GET | login |  |  | src/zyg_dashboard/bp_schedule.py:37 |
| `/integrity_gate` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:68 |
| `/job_lifecycle` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:76 |
| `/job_status` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:28 |
| `/login` | GET | open |  |  | src/zyg_dashboard/crewai_web_gui.py:969 |
| `/logout` | GET | open | yes |  | src/zyg_dashboard/bp_auth.py:184 |
| `/markets` | GET | login |  |  | src/zyg_dashboard/bp_market.py:51 |
| `/mechanics` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:88 |
| `/metrics` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:82 |
| `/monitoring_ui` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:34 |
| `/parameter_control` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:40 |
| `/publics_zero` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:100 |
| `/remix` | GET | login |  |  | src/zyg_dashboard/bp_remix.py:61 |
| `/remix-ai` | GET | login |  |  | src/zyg_dashboard/bp_remixai.py:52 |
| `/sandbox` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:124 |
| `/settings` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:48 |
| `/test_gradients.html` | GET | login |  |  | src/zyg_dashboard/crewai_web_gui.py:4218 |
| `/workflows` | GET | login |  |  | src/zyg_dashboard/bp_dashboard_pages.py:118 |

## zero_public (83 routes)

| rule | methods | gate | danger | external | func |
|---|---|---|---|---|---|
| `/` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:477 |
| `/.well-known/zygomatic-c2pa-root.pem` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:1234 |
| `/Portfolio` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:188 |
| `/admin-enter` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:98 |
| `/admin/logs` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_admin.py:314 |
| `/api/admin/logs` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_admin.py:286 |
| `/api/admin/run_approved/<req_id>` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_admin.py:105 |
| `/api/benchmark` | GET | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:2101 |
| `/api/cinema/board` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:146 |
| `/api/cinema/browse` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:421 |
| `/api/cinema/forget/<item_id>` | POST | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:504 |
| `/api/cinema/hls/<sess_id>/<path:name>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:326 |
| `/api/cinema/hls/<sess_id>/close` | POST | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:352 |
| `/api/cinema/hls/<sess_id>/index.m3u8` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:307 |
| `/api/cinema/hls/start/<item_id>` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:278 |
| `/api/cinema/item/<item_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:155 |
| `/api/cinema/lock` | POST | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:132 |
| `/api/cinema/play/<item_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:187 |
| `/api/cinema/prefs` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:518 |
| `/api/cinema/prefs` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:529 |
| `/api/cinema/scan` | POST | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:472 |
| `/api/cinema/scan/<scan_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:492 |
| `/api/cinema/seek/<item_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:242 |
| `/api/cinema/series_name` | POST | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:559 |
| `/api/cinema/subtitle/<item_id>/<sub_id>.vtt` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:364 |
| `/api/cinema/thumb/<item_id>.jpg` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:167 |
| `/api/cinema/transcode/<item_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:205 |
| `/api/cinema/unlock` | POST | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:111 |
| `/api/creature/creature-image/<creature_id>/<filename>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:1354 |
| `/api/creature/list-creatures` | GET | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:1384 |
| `/api/pending_status/<req_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_admin.py:247 |
| `/api/preview_upload` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:574 |
| `/api/queue` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:1171 |
| `/api/sports-video/status` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_sports.py:33 |
| `/api/sports-video/tournaments` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_sports.py:44 |
| `/api/sports-video/trigger` | POST | invite | yes | yes | ../zero-public/src/zyg_zero/zpub_routes_sports.py:63 |
| `/api/sports-video/videos` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_sports.py:118 |
| `/api/status/<job_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:1047 |
| `/api/storyteller/analyze-character-photo` | POST | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:152 |
| `/api/storyteller/char-image/<char_id>/<filename>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:772 |
| `/api/storyteller/char-preview-status` | GET | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:1433 |
| `/api/storyteller/character-status/<char_id>` | GET | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:564 |
| `/api/storyteller/contact-sheet/approve/<char_id>` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:291 |
| `/api/storyteller/contact-sheet/image/<char_id>` | GET | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:377 |
| `/api/storyteller/contact-sheet/pause/<char_id>` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:337 |
| `/api/storyteller/contact-sheet/resume/<char_id>` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:343 |
| `/api/storyteller/contact-sheet/start` | POST | invite | yes | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:248 |
| `/api/storyteller/contact-sheet/status/<char_id>` | GET | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:274 |
| `/api/storyteller/contact-sheet/training-image/<char_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:349 |
| `/api/storyteller/gen-char-previews` | POST | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:1399 |
| `/api/storyteller/generate` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:1998 |
| `/api/storyteller/generate-character` | POST | invite | yes | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:185 |
| `/api/storyteller/list-chars` | GET | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:1147 |
| `/api/storyteller/list-contact-sheets` | GET | invite |  | yes | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:444 |
| `/api/storyteller/pipeline/pause` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:325 |
| `/api/storyteller/pipeline/pause-state` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:319 |
| `/api/storyteller/pipeline/resume` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:331 |
| `/api/storyteller/voice-sample/<voice_id>/<variant>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:534 |
| `/api/storyteller/voice-samples-health` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:505 |
| `/api/storyteller/voices` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_storyteller.py:524 |
| `/api/stream/<job_id>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:1082 |
| `/api/submit` | POST | invite | yes |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:721 |
| `/api/token_jobs/<token>` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:1182 |
| `/api/tunnel-url` | GET | invite |  |  | ../zero-public/src/zyg_zero/zpub_routes_admin.py:294 |
| `/architecture` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:333 |
| `/architecture/download` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:340 |
| `/assets/zero/<path:filename>` | GET | public |  |  | ../zero-public/src/zyg_zero/zero_public_server.py:143 |
| `/atlas` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:319 |
| `/atlas/download` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:326 |
| `/cinema` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_cinema.py:138 |
| `/download/<job_id>/<filename>` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:1146 |
| `/job/<job_id>` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:506 |
| `/portfolio` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:188 |
| `/portfolio-slideshow` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:402 |
| `/portfolio-slideshow/cover` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:462 |
| `/portfolio-slideshow/deck.json` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:423 |
| `/portfolio-slideshow/slide/<name>` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:441 |
| `/portfolio-speedrun-stream` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:267 |
| `/portfolio-stream` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:261 |
| `/u/<token>` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:110 |
| `/uploads/<path:subpath>` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:524 |
| `/verify` | GET | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:1333 |
| `/verify` | POST | public |  |  | ../zero-public/src/zyg_zero/zpub_routes_public.py:1340 |

## medusa (52 routes)

| rule | methods | gate | danger | external | func |
|---|---|---|---|---|---|
| `/` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:3880 |
| `/api/generate_character` | POST | ipgate | yes | yes | ../../../../Zygomatic/medusa/medusa_server.py:3890 |
| `/api/medusa/angles` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:3934 |
| `/api/medusa/models` | GET POST | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4000 |
| `/api/medusa/models/<model_id>/images` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4029 |
| `/api/medusa/models/<path:sub>` | DELETE GET PATCH POST | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4006 |
| `/api/medusa/pending` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:3953 |
| `/api/medusa/pending/<req_id>/decide` | POST | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:3965 |
| `/api/medusa/training/characters` | GET POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4048 |
| `/api/medusa/training/characters/<char_id>` | DELETE GET | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4054 |
| `/api/medusa/training/characters/<char_id>/body-prepare` | GET POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4104 |
| `/api/medusa/training/characters/<char_id>/images` | POST | ipgate | yes | yes | ../../../../Zygomatic/medusa/medusa_server.py:4180 |
| `/api/medusa/training/characters/<char_id>/images/<image_id>` | DELETE | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4158 |
| `/api/medusa/training/characters/<char_id>/images/<image_id>` | GET | ipgate |  | yes | ../../../../Zygomatic/medusa/medusa_server.py:4164 |
| `/api/medusa/training/characters/<char_id>/sheet` | GET POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4097 |
| `/api/medusa/training/characters/<char_id>/sheet/page/<page>` | GET | ipgate |  | yes | ../../../../Zygomatic/medusa/medusa_server.py:4142 |
| `/api/medusa/training/characters/<char_id>/status` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4065 |
| `/api/medusa/training/characters/<char_id>/train` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4059 |
| `/api/medusa/training/import-folders` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4086 |
| `/api/medusa/training/import-root` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4075 |
| `/api/medusa/training/import/<batch_id>` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4092 |
| `/api/medusa/training/loras` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4122 |
| `/api/medusa/training/loras/<char_id>/<family>/sample/<name>` | GET | ipgate |  | yes | ../../../../Zygomatic/medusa/medusa_server.py:4127 |
| `/api/medusa/training/scan-folder` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4080 |
| `/api/medusa/training/sheets` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4111 |
| `/api/medusa/training/sheets/build-all` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4116 |
| `/api/resources/config` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_resources.py:1608 |
| `/api/resources/fetch-urls` | POST | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_resources.py:1767 |
| `/api/resources/jobs` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_resources.py:2003 |
| `/api/resources/jobs/<job_id>/cancel` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_resources.py:2015 |
| `/api/resources/preview` | POST | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_resources.py:1927 |
| `/api/resources/sets` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_resources.py:2025 |
| `/api/resources/sets/<set_name>` | DELETE | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_resources.py:2042 |
| `/api/resources/sets/<set_name>` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_resources.py:2030 |
| `/api/resources/sets/<set_name>/image/<image_name>` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_resources.py:2059 |
| `/api/resources/sets/<set_name>/thumb/<image_name>` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_resources.py:2071 |
| `/api/resources/upload` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_resources.py:1627 |
| `/api/vicky/active` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4225 |
| `/api/vicky/cancel` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4219 |
| `/api/vicky/chat` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4246 |
| `/api/vicky/chat/<action>` | POST | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4254 |
| `/api/vicky/chat/export` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4262 |
| `/api/vicky/chats` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4232 |
| `/api/vicky/engines` | GET | ipgate |  | yes | ../../../../Zygomatic/medusa/medusa_server.py:4278 |
| `/api/vicky/image` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4305 |
| `/api/vicky/info` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4286 |
| `/api/vicky/job` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4214 |
| `/api/vicky/pictures` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:4239 |
| `/api/vicky/start` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4208 |
| `/api/vicky/upload` | POST | ipgate | yes |  | ../../../../Zygomatic/medusa/medusa_server.py:4325 |
| `/favicon.ico` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:3875 |
| `/favicon.png` | GET | ipgate |  |  | ../../../../Zygomatic/medusa/medusa_server.py:3870 |
