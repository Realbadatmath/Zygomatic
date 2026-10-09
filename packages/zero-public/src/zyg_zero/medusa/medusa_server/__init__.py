#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Medusa — Zygomatic
Standalone GUI with an 8-tab left sidebar. Port 5300.
Launchable from the Zygomatic Hub.

Run:  python3 medusa_server.py
Then: http://$ZYG_LAN_HOST:5300  (loopback unless ZYG_LAN_HOST names the box)
"""

# Split out of the single medusa_server.py file (2026-10-06); the import path is
# unchanged. The original top import block is repeated below so attribute access
# on this module (medusa_server.os, medusa_server.requests, ...) still resolves,
# and the submodules are imported in the original section order so their
# module-level side effects — the IP gate, the Resources blueprint and the route
# registrations — run exactly when they did before.
# ruff: noqa: F401

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import requests  # only for multipart-upload forwarding below — urllib's

# multipart support is fragile for binary file bodies.
# Everything else here stays urllib to match the file's
# existing zero-generation-deps proxy style.
from flask import Flask, Response, jsonify, request, send_file

from zyg_workflows import paths
from zyg_zero import settings

import medusa_ipgate
import medusa_resources
import medusa_vicky

from .app import BASE_DIR, FAVICON_ICO, FAVICON_PNG, PORT, app
from .html import HTML
from .routes import (
    favicon_png,
    favicon_ico,
    index,
    CREWS_API,
    _crews_urlopen,
    api_generate_character,
    _crews_proxy,
    api_medusa_angles_proxy,
    api_medusa_pending_proxy,
    api_medusa_decide_proxy,
    _training_proxy_json,
    api_models_root,
    api_models_sub,
    _models_image_passthrough,
    api_models_upload_images,
    api_training_characters,
    api_training_character,
    api_training_train,
    api_training_status,
    api_training_import_root,
    api_training_scan_folder,
    api_training_import_folders,
    api_training_import_status,
    api_training_sheet,
    api_training_body_prepare,
    api_training_sheets,
    api_training_sheets_build_all,
    api_training_loras,
    api_training_lora_sample,
    api_training_sheet_page,
    api_training_delete_image,
    api_training_get_image,
    api_training_upload_images,
    api_vicky_start,
    api_vicky_job,
    api_vicky_cancel,
    api_vicky_active,
    api_vicky_chats,
    api_vicky_pictures,
    api_vicky_chat,
    api_vicky_chat_action,
    api_vicky_chat_export,
    api_vicky_engines,
    api_vicky_info,
    VICKY_IMAGE_ROOTS,
    VICKY_IMAGE_EXT,
    api_vicky_image,
    api_vicky_upload,
)
