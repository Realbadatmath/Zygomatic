#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
medusa_resources.py — Resources tab backend (2026-08-09).

WHAT THIS IS. Two ways in, one thing out — ONE FOLDER OF PICTURES on disk:

    upload page.mhtml   ->  <resources root>/page/*.jpg
    paste addresses     ->  <resources root>/<named set>/*.jpg

Either the operator saves a gallery page in their own browser ("Save Page As…")
and uploads it, or they type/paste the addresses themselves. Nothing more.

That destination is deliberate: the Training tab's importer already treats the
same root (ZYG_MEDUSA_IMPORT_DIR) as "one subfolder == one character" (see
bp_medusa_training.py::_scan_parent), so a set produced here is immediately
visible to Training -> Scan folder with no copying step in between.

WHAT THIS IS NOT, ON PURPOSE.
  * There is NO directory walker. This module never enumerates a remote site's
    tree, never guesses subdirectory names, and never follows links to discover
    further pages. Every request it makes traces back to something the operator
    named: a picture on a page they saved, or an address they typed.
  * A typed address that is a PAGE is read exactly ONE HOP — the pictures on it
    are fetched, links it holds to other pages are not. That rule is what keeps
    a typed list a fetcher instead of a crawler; _run_job repeats it where it
    is enforced.
  * There is NO credential replay. No cookie jar, no Authorization header, no
    browser-cookie import. If a resource needs a session to be fetched, it is
    not fetched, and the set reports it as failed.
Both omissions are the design, not a gap to be filled in later. Removing either
one turns a "keep the page I opened" tool into a site-scraper, which is a
different thing with different consequences.

MHTML IS THE PREFERRED FORMAT. A .mhtml is self-contained: every picture the
page displayed is already inside the file, so extraction is pure local parsing
and touches the network zero times. Plain .html only carries URLs, so those have
to be re-fetched, which is where the rate limiting below applies.

POLITENESS. Re-fetches run on a small worker pool (2 by default, 6 max), each
worker spacing its OWN requests by the operator's delay (2s default) — so the
aggregate is workers/delay, one request a second at the defaults. Plus
exponential backoff honouring Retry-After on 429/5xx and a robots.txt check
that is ON by default. None of this is load-bearing for correctness; it is
there so the tool cannot behave like a hammer against someone else's server.

WHAT GETS COLLECTED. Only the run of pictures BEFORE the first "Related
Galleries" / "Free sites" style heading, and never from a block whose id/class
advertises it as related/sponsored/promo. See DEFAULT_STOP_PHRASES. The
/api/resources/preview endpoint is the dry run that explains any count: it
reports each candidate's collector and folder, and the same page parsed with
every filter off, so "it found more than are on the page" has an answer rather
than a guess.

STORAGE LAYOUT (per set):
    <set>/               *.jpg *.png *.webp  <- only images, so the Training
                                               importer's count is honest
    <set>/.meta/         source page + manifest.json (hidden: the importer
                                               skips dotted subfolders)
    <set>/.thumbs/       256px previews for the GUI gallery
"""

import email
import email.parser
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

from flask import Blueprint, jsonify, request, send_file

from zyg_zero import settings

try:
    from PIL import Image
except Exception:  # pragma: no cover - PIL is present on this box (12.2.0)
    Image = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('medusa_resources', __name__)

# The sections of the original medusa_resources.py, imported in their original
# order so module-level side effects still run in that order.
from .config import (  # noqa: E402
    RESOURCES_ROOT,
    META_DIR,
    THUMB_DIR,
    THUMB_PX,
    IMPORTABLE_EXTS,
    IMAGE_EXTS,
    PAGE_EXTS,
    DEFAULT_DELAY,
    DEFAULT_MIN_BYTES,
    DEFAULT_MIN_EDGE,
    MAX_FILES_PER_SET,
    MAX_SEED_PAGES,
    MAX_IMAGE_BYTES,
    MAX_PAGE_BYTES,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    MAX_RECORDED_ERRORS,
    USER_AGENT,
    _CSS_URL_RE,
    _SAVED_FROM_RE,
    _ABS_IMG_RE,
    DEFAULT_STOP_PHRASES,
    _JUNK_BLOCK_RE,
    DEFAULT_EXCLUDE_WORDS,
    DEFAULT_WORKERS,
    MAX_WORKERS,
    PHASH_DISTANCE,
    _JOBS,
    _JOBS_LOCK,
    _ROBOTS,
    _ROBOTS_LOCK,
    _JOB_SEQ,
)
from .urls import (  # noqa: E402
    _slugify,
    _safe_leaf,
    _set_dir,
    _folder_for_name,
    _claim_set_dir,
    _unique_set_dir,
    _ext_of,
    _looks_like_image,
    _SIZE_DIR_RE,
    _SIZE_IN_NAME_RE,
    _SIZE_HINT_RE,
    _TRAILING_NUM_RE,
    _COMMON_WIDTHS,
    _strip_size_suffix,
    _BIG_WORDS_RE,
    _SMALL_WORDS_RE,
    _HOW_RANK,
    _variant_key,
    _variant_rank,
    _collapse_variants,
    _excluded,
    _origin,
    _split_urls,
    _slug_from_url,
    _best_from_srcset,
    _read_manifest,
)
from .parsing import (  # noqa: E402
    _ImageRefParser,
    _abs_offset,
    _parse_html,
    _MODEL_HREF_RE,
    _NAME_SHAPE_RE,
    _NAME_LEAD_RE,
    _NOT_A_NAME,
    _clean_name,
    _name_slug,
    _NameParser,
    _model_key,
    _extract_name,
    _name_from_page_file,
    _parse_mhtml,
)
from .network import (  # noqa: E402
    _urlopen_http,
    _load_robots,
    _robots_allows,
    _fetch,
    _fetch_page,
    _fetch_with_retry,
    _decode_image,
    _hamming,
    _write_image,
)
from .jobs import (  # noqa: E402
    _new_job,
    _job_update,
    _job_error,
    _cancelled,
    _write_manifest,
    _consider,
    _seed_existing,
    _sleep_politely,
    _run_job,
    _bump,
    _set_images,
    _list_sets,
)
from .routes import (  # noqa: E402
    api_resources_config,
    api_resources_upload,
    _as_float,
    _parse_phrases,
    _opts_from,
    api_resources_fetch_urls,
    _plan_typed_urls,
    api_resources_preview,
    api_resources_jobs,
    api_resources_cancel,
    api_resources_sets,
    api_resources_set,
    api_resources_delete_set,
    api_resources_image,
    api_resources_thumb,
    install,
)

# ── re-export surface ────────────────────────────────────────────────────────
# This package re-exports every name the single medusa_resources.py defined, so
# a caller that reached for ``medusa_resources.<anything>`` before the split
# still finds it. Declaring them is what makes the re-export deliberate rather
# than an unused import; nothing does ``import *`` from here, so __all__ changes
# no behaviour.
__all__ = [
    'bp',
    'email',
    'hashlib',
    'io',
    'json',
    'os',
    're',
    'shutil',
    'threading',
    'time',
    'urllib',
    'HTMLParser',
    'Blueprint',
    'jsonify',
    'request',
    'send_file',
    'settings',
    'Image',
    'RESOURCES_ROOT',
    'META_DIR',
    'THUMB_DIR',
    'THUMB_PX',
    'IMPORTABLE_EXTS',
    'IMAGE_EXTS',
    'PAGE_EXTS',
    'DEFAULT_DELAY',
    'DEFAULT_MIN_BYTES',
    'DEFAULT_MIN_EDGE',
    'MAX_FILES_PER_SET',
    'MAX_SEED_PAGES',
    'MAX_IMAGE_BYTES',
    'MAX_PAGE_BYTES',
    'REQUEST_TIMEOUT',
    'MAX_RETRIES',
    'MAX_RECORDED_ERRORS',
    'USER_AGENT',
    '_CSS_URL_RE',
    '_SAVED_FROM_RE',
    '_ABS_IMG_RE',
    'DEFAULT_STOP_PHRASES',
    '_JUNK_BLOCK_RE',
    'DEFAULT_EXCLUDE_WORDS',
    'DEFAULT_WORKERS',
    'MAX_WORKERS',
    'PHASH_DISTANCE',
    '_JOBS',
    '_JOBS_LOCK',
    '_ROBOTS',
    '_ROBOTS_LOCK',
    '_JOB_SEQ',
    '_slugify',
    '_safe_leaf',
    '_set_dir',
    '_folder_for_name',
    '_claim_set_dir',
    '_unique_set_dir',
    '_ext_of',
    '_looks_like_image',
    '_SIZE_DIR_RE',
    '_SIZE_IN_NAME_RE',
    '_SIZE_HINT_RE',
    '_TRAILING_NUM_RE',
    '_COMMON_WIDTHS',
    '_strip_size_suffix',
    '_BIG_WORDS_RE',
    '_SMALL_WORDS_RE',
    '_HOW_RANK',
    '_variant_key',
    '_variant_rank',
    '_collapse_variants',
    '_excluded',
    '_origin',
    '_split_urls',
    '_slug_from_url',
    '_best_from_srcset',
    '_read_manifest',
    '_ImageRefParser',
    '_abs_offset',
    '_parse_html',
    '_MODEL_HREF_RE',
    '_NAME_SHAPE_RE',
    '_NAME_LEAD_RE',
    '_NOT_A_NAME',
    '_clean_name',
    '_name_slug',
    '_NameParser',
    '_model_key',
    '_extract_name',
    '_name_from_page_file',
    '_parse_mhtml',
    '_urlopen_http',
    '_load_robots',
    '_robots_allows',
    '_fetch',
    '_fetch_page',
    '_fetch_with_retry',
    '_decode_image',
    '_hamming',
    '_write_image',
    '_new_job',
    '_job_update',
    '_job_error',
    '_cancelled',
    '_write_manifest',
    '_consider',
    '_seed_existing',
    '_sleep_politely',
    '_run_job',
    '_bump',
    '_set_images',
    '_list_sets',
    'api_resources_config',
    'api_resources_upload',
    '_as_float',
    '_parse_phrases',
    '_opts_from',
    'api_resources_fetch_urls',
    '_plan_typed_urls',
    'api_resources_preview',
    'api_resources_jobs',
    'api_resources_cancel',
    'api_resources_sets',
    'api_resources_set',
    'api_resources_delete_set',
    'api_resources_image',
    'api_resources_thumb',
    'install',
]
