# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Dashboard configuration paths and constants.
Centralizes paths to Layouts and Themes and dashboard data files.
"""

import os

# Project root: Zygomatic Origin (parent of Agents)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LAYOUTS_THEMES_ROOT = os.path.join(_PROJECT_ROOT, 'Layouts and Themes')
BUTTONS_DIR = os.path.join(LAYOUTS_THEMES_ROOT, 'Buttons')
BACKGROUNDS_DIR = os.path.join(LAYOUTS_THEMES_ROOT, 'Background')
SIDEBAR_DIR = os.path.join(LAYOUTS_THEMES_ROOT, 'Sidebar')

# Dashboard data files (in crewai_project)
DASHBOARD_DIR = os.path.dirname(__file__)
THEME_CONFIG_PATH = os.path.join(DASHBOARD_DIR, 'dashboard_theme_config.json')
USERS_DATA_PATH = os.path.join(DASHBOARD_DIR, 'dashboard_users.json')
ERROR_LOGS_DATA_PATH = os.path.join(DASHBOARD_DIR, 'dashboard_error_logs.json')
JOB_STATUS_DATA_PATH = os.path.join(DASHBOARD_DIR, 'dashboard_job_status.json')
MONITORING_JOBS_PATH = os.path.join(DASHBOARD_DIR, 'dashboard_monitoring_jobs.json')
SAFETY_THRESHOLDS_PATH = os.path.join(DASHBOARD_DIR, 'safety_thresholds.json')
SAFETY_AUDIT_LOG_PATH = os.path.join(DASHBOARD_DIR, 'safety_audit_log.jsonl')

# Avatars stored under static/avatars
AVATARS_DIR = os.path.join(DASHBOARD_DIR, 'static', 'avatars')

# Languages (project root level)
LANGUAGES_DIR = os.path.join(_PROJECT_ROOT, 'Languages')
LANGUAGE_LINKS_DIR = os.path.join(LANGUAGES_DIR, 'Language Links')
LANGUAGE_LINKS_FILE = os.path.join(LANGUAGE_LINKS_DIR, 'language_links.json')

# Default theme keys (from Layouts and Themes HTML files)
DEFAULT_BUTTON_THEME = {'file': 'scaled_steel_buttons_test.html', 'variant': 's18', 'label': 'Scaled 18 Subtle'}
DEFAULT_BACKGROUND_THEME = {'file': 'soft_backgrounds_test.html', 'variant': 'bg37', 'label': 'Smoky Pearl'}
