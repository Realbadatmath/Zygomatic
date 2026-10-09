# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# This module inherits web_research_agent.py's own top import block verbatim, so every
# name the single file exposed as an attribute still resolves. Names used only by sibling
# sections are therefore 'unused' here on purpose.
# ruff: noqa: F401
import os
import re
import time
import random
import traceback
import threading
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.web_research_agent')


# ── Constants ─────────────────────────────────────────────────────────────────

_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0',
]

_PAYWALL_SIGNALS = [
    'subscribe to continue',
    'subscribe now',
    'create a free account',
    'sign in to read',
    'this article is for subscribers',
    'premium content',
    'register to read',
    'you have reached your',
    'reading limit',
    'unlimited access',
    'start your free trial',
]

_CAPTCHA_SIGNALS = [
    'recaptcha',
    'hcaptcha',
    'are you a robot',
    'verify you are human',
    'unusual traffic',
    'automated requests',
    'security check',
    'please verify',
    'cf-challenge',
    'challenge-form',
]

_COOKIE_BUTTON_TEXTS = [
    'accept all',
    'accept cookies',
    'allow all',
    'agree',
    'i accept',
    'ok',
    'got it',
    'consent',
    'accept & continue',
    'yes, i agree',
]

_SOURCE_TIMEOUT = 180  # seconds per source before moving on
_PAGE_LOAD_TIMEOUT = 30


# ── Human timing ──────────────────────────────────────────────────────────────


def _gauss_delay(mean, sigma):
    """Gaussian random delay — feels human, not flat random."""
    t = max(0.3, random.gauss(mean, sigma))
    time.sleep(t)
    return t


def _between_pages():
    _gauss_delay(3.5, 0.9)


def _between_searches():
    _gauss_delay(6.0, 1.5)


def _after_load():
    _gauss_delay(2.0, 0.6)


def _between_sites():
    _gauss_delay(8.0, 2.0)


def _reading_pause():
    _gauss_delay(1.5, 0.4)


def _micro_pause():
    _gauss_delay(0.4, 0.1)
