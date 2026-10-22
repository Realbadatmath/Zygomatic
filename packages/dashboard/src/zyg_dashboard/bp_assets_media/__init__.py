# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
# 2026-10-06 modularization: bp_assets_media.py (2,036 lines) became this package.
# Every section was moved verbatim; this __init__ re-does the original top import
# block (so attribute access such as bp_assets_media.os still resolves), imports the
# section modules in the original section order, and re-exports every name the old
# module defined, so no importer needed a change.
import logging as _zyg_logging
import json
import os
import re
import subprocess
import time
import threading
from datetime import datetime, timezone
from flask import (
    Blueprint,
    jsonify,
    request,
    send_file,
    send_from_directory,
)
from zyg_workflows.bin import exe
from zyg_dashboard.cors import apply_cors

from zyg_dashboard.bp_assets_media import base as _base_mod
from zyg_dashboard.bp_assets_media.base import (
    bp,
    _RUNTIME_DIR,
    _runtime_path,
    _AMS_TZ,
    _ams_now,
    _ASSETS_REACTION_DIR,
    _ASSETS_SFX_DIR,
    _CLIPS_OUTPUT_DIR,
    _SV_STATUS_FILE,
    _TSTORE_FILE,
    _YT_TOKEN_FILE,
    _YT_UPLOAD_SCRIPT,
    _YT_VENV_PYTHON,
    _agent_log,
    _register_prompt,
    _zero_claim_batch_slot,
    limiter,
    _main_mod,
    _zyg_log,
    _CDR_OK,
    _cdr,
    _cdr_e_str,
)
from zyg_dashboard.bp_assets_media import assets as _assets_mod
from zyg_dashboard.bp_assets_media.assets import (
    get_scp_config,
    patch_scp_config,
    _parse_sfx_catalogue,
    _parse_reaction_catalogue,
    _download_assets_background,
    trigger_asset_download,
    asset_status,
    asset_preview,
)
from zyg_dashboard.bp_assets_media import scholarly as _scholarly_mod
from zyg_dashboard.bp_assets_media.scholarly import (
    api_rfd_clips,
    api_scholarly_imagery,
    api_scholarly_imagery_thumb,
    api_scholarly_videos,
    api_storyteller_episodes,
    api_storyteller_episode_video,
)
from zyg_dashboard.bp_assets_media import library as _library_mod
from zyg_dashboard.bp_assets_media.library import (
    _ENVFX_OUT_BASE,
    _envfx_scan,
    api_environments_list,
    api_effects_list,
    api_wardrobe_list,
    api_wardrobe_outfits,
    api_wardrobe_preview,
    api_wardrobe_delete,
    api_effects_library,
    api_effects_preview,
    api_effects_delete,
    _ASSETLIB_DEPTS,
    api_assetlib_list,
    _AUDIO_MIME,
    api_assetlib_preview,
    api_assetlib_delete,
    api_assetlib_generated,
    api_envfx_media,
)
from zyg_dashboard.bp_assets_media import marketing as _marketing_mod
from zyg_dashboard.bp_assets_media.marketing import (
    _MKT_DISMISS_PATH,
    _MKT_DISMISS_LOCK,
    _mkt_ep_key,
    _mkt_load_dismissed,
    _mkt_save_dismissed,
    _mkt_is_dismissed,
    _mkt_cors,
    api_marketing_dismissed,
    api_marketing_dismiss,
    api_marketing_undismiss,
    api_output_new_videos,
    api_youtube_channel_videos,
)
from zyg_dashboard.bp_assets_media import upload as _upload_mod
from zyg_dashboard.bp_assets_media.upload import (
    api_marketing_upload,
)
from zyg_dashboard.bp_assets_media import prompts as _prompts_mod
from zyg_dashboard.bp_assets_media.prompts import (
    api_asset_manager_prompts,
    api_prompt_registry_update,
    api_prompt_registry_revert,
    api_channel_data_groups,
    api_channel_data_fetch,
    sv_status_proxy,
)
from zyg_dashboard.bp_assets_media import templates as _templates_mod
from zyg_dashboard.bp_assets_media.templates import (
    _tstore_read,
    _tstore_write,
    api_templates_list,
    api_templates_store,
    api_templates_delete,
    _parse_clip_yaml,
    api_templates_outputs,
    api_templates_thumb,
    asset_manager_templates_board,
)


# ── re-export surface ──
# Every name below is imported above and NOT used in this module; it is here so
# importers keep resolving it through this module. Nothing does ``import *`` from
# here, so __all__ changes no behaviour -- it is how ruff is told these are public.
__all__ = [
    '_zyg_logging',
    'json',
    'os',
    're',
    'subprocess',
    'time',
    'threading',
    'datetime',
    'timezone',
    'Blueprint',
    'jsonify',
    'request',
    'send_file',
    'send_from_directory',
    'exe',
    'apply_cors',
    '_base_mod',
    'bp',
    '_RUNTIME_DIR',
    '_runtime_path',
    '_AMS_TZ',
    '_ams_now',
    '_ASSETS_REACTION_DIR',
    '_ASSETS_SFX_DIR',
    '_CLIPS_OUTPUT_DIR',
    '_SV_STATUS_FILE',
    '_TSTORE_FILE',
    '_YT_TOKEN_FILE',
    '_YT_UPLOAD_SCRIPT',
    '_YT_VENV_PYTHON',
    '_agent_log',
    '_register_prompt',
    '_zero_claim_batch_slot',
    'limiter',
    '_main_mod',
    '_zyg_log',
    '_CDR_OK',
    '_cdr',
    '_cdr_e_str',
    '_assets_mod',
    'get_scp_config',
    'patch_scp_config',
    '_parse_sfx_catalogue',
    '_parse_reaction_catalogue',
    '_download_assets_background',
    'trigger_asset_download',
    'asset_status',
    'asset_preview',
    '_scholarly_mod',
    'api_rfd_clips',
    'api_scholarly_imagery',
    'api_scholarly_imagery_thumb',
    'api_scholarly_videos',
    'api_storyteller_episodes',
    'api_storyteller_episode_video',
    '_library_mod',
    '_ENVFX_OUT_BASE',
    '_envfx_scan',
    'api_environments_list',
    'api_effects_list',
    'api_wardrobe_list',
    'api_wardrobe_outfits',
    'api_wardrobe_preview',
    'api_wardrobe_delete',
    'api_effects_library',
    'api_effects_preview',
    'api_effects_delete',
    '_ASSETLIB_DEPTS',
    'api_assetlib_list',
    '_AUDIO_MIME',
    'api_assetlib_preview',
    'api_assetlib_delete',
    'api_assetlib_generated',
    'api_envfx_media',
    '_marketing_mod',
    '_MKT_DISMISS_PATH',
    '_MKT_DISMISS_LOCK',
    '_mkt_ep_key',
    '_mkt_load_dismissed',
    '_mkt_save_dismissed',
    '_mkt_is_dismissed',
    '_mkt_cors',
    'api_marketing_dismissed',
    'api_marketing_dismiss',
    'api_marketing_undismiss',
    'api_output_new_videos',
    'api_youtube_channel_videos',
    '_upload_mod',
    'api_marketing_upload',
    '_prompts_mod',
    'api_asset_manager_prompts',
    'api_prompt_registry_update',
    'api_prompt_registry_revert',
    'api_channel_data_groups',
    'api_channel_data_fetch',
    'sv_status_proxy',
    '_templates_mod',
    '_tstore_read',
    '_tstore_write',
    'api_templates_list',
    'api_templates_store',
    'api_templates_delete',
    '_parse_clip_yaml',
    'api_templates_outputs',
    'api_templates_thumb',
    'asset_manager_templates_board',
]
