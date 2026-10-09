# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Configuration constants and the section-filtering phrase lists.

Moved verbatim out of medusa_resources.py (original lines 98-200).
"""

import os
import re
import threading

from zyg_zero import settings


# ── Configuration ───────────────────────────────────────────────────────────
# Default root is the Training import root on purpose — see module docstring.
RESOURCES_ROOT = os.path.realpath(os.environ.get('ZYG_MEDUSA_RESOURCES_ROOT') or settings.ZYG_MEDUSA_IMPORT_DIR)

META_DIR = '.meta'
THUMB_DIR = '.thumbs'
THUMB_PX = 256

# Extensions the Training importer actually reads (README.txt in the import
# root). Anything else that downloads fine — avif, bmp, tiff, gif — is
# transcoded to PNG on save so no picture lands in a set that Training would
# then silently ignore.
IMPORTABLE_EXTS = {'.png', '.jpg', '.jpeg', '.webp'}
IMAGE_EXTS = IMPORTABLE_EXTS | {'.gif', '.avif', '.bmp', '.tif', '.tiff', '.jfif'}
PAGE_EXTS = {'.html', '.htm', '.xhtml', '.mhtml', '.mht'}

DEFAULT_DELAY = 2.0  # seconds between re-fetches
DEFAULT_MIN_BYTES = 15000  # drops spacers, icons and tracking pixels
DEFAULT_MIN_EDGE = 256  # drops thumbnails that survived the byte filter
MAX_FILES_PER_SET = 2000
# How many typed addresses may be opened as pages in one job. A ceiling, not a
# target — it exists so a pasted wall of links stays a bounded, visible amount
# of traffic against someone else's server.
MAX_SEED_PAGES = 200
MAX_IMAGE_BYTES = 60 * 1024 * 1024
MAX_PAGE_BYTES = 300 * 1024 * 1024
REQUEST_TIMEOUT = 45
MAX_RETRIES = 3
MAX_RECORDED_ERRORS = 60

USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
_SAVED_FROM_RE = re.compile(r'<!--\s*saved from url=\(\d+\)(?P<url>[^\s>]+?)\s*-->', re.I)
_ABS_IMG_RE = re.compile(
    r"""https?://[^\s"'<>\\)\]]+?\.(?:jpe?g|jfif|png|webp|gif|avif|bmp|tiff?)"""
    r"""(?:\?[^\s"'<>\\)\]]*)?""",
    re.I,
)

# ── Section filtering ───────────────────────────────────────────────────────
# A gallery page reads: <character name> … the pictures you want … then
# "Related Galleries" … then "Free sites" … each followed by pictures you do
# NOT want. Collection therefore STOPS at the first of these headings, and any
# block whose id/class advertises itself as related/sponsored/etc is skipped
# outright. Both lists are operator-editable from the GUI — they have to be,
# because every site words its headings differently.
DEFAULT_STOP_PHRASES = (
    'related galler',
    'related set',
    'related video',
    'related model',
    'more galler',
    'more from',
    'more like this',
    'similar galler',
    'you may also like',
    'you might also like',
    'recommended',
    'free site',
    'free galler',
    'our friends',
    'friend site',
    'popular galler',
    'top sites',
    'also visit',
    'suggested',
    'you may like',
)
# NOTE: "sponsor", "advertis", "partner" and "trending" are deliberately NOT
# cut phrases — they live in _JUNK_BLOCK_RE below, which matches a container's
# id/class. As cut phrases they end the document at the first ad slot, which on
# a real page sits above the gallery.
_JUNK_BLOCK_RE = re.compile(
    r'related|recommend|similar|sponsor|promo|advert|banner|footer|'
    r'also-?like|more-?galler|partner|friend|free-?site|trending|'
    r'popular|suggest|widget|outbrain|taboola|adsbox|ad-?slot|ad-?unit',
    re.I,
)

# Addresses containing any of these are never queued. "masonry" is the name
# these gallery sites give the tiles of their grid layout: a folder pulled
# before this existed came back 198 files, of which 118 were
# <id>_masonry_1200.jpg — one cover per OTHER gallery on the page, not the set
# that was asked for. Matched case-insensitively anywhere in the URL.
# NOTE: keep this OUT of _JUNK_BLOCK_RE. "masonry" is also the usual class name
# for the container holding the wanted pictures, so suppressing blocks by that
# word would throw away the whole gallery.
DEFAULT_EXCLUDE_WORDS = ('masonry',)

DEFAULT_WORKERS = 2  # parallel fetches; see _run_job's worker pool
MAX_WORKERS = 6
# dHash Hamming distance under which two pictures are treated as the same
# photograph at different sizes. 64 bits total; 5 is tight enough that two
# different shots from the same set stay separate, loose enough that a 300px
# thumbnail matches its 1600px original.
PHASH_DISTANCE = 5

_JOBS = {}
_JOBS_LOCK = threading.Lock()
_ROBOTS = {}
_ROBOTS_LOCK = threading.Lock()
_JOB_SEQ = [0]
