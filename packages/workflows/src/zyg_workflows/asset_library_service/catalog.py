# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.asset_library_service.catalog — verbatim from asset_library_service.py lines 44-455.

the original import block, the logger, the data roots, the
_CATEGORIES registry, the _DEFAULTS starter libraries and the small
category/path accessors
"""

# ruff: noqa: F401  this module inherits asset_library_service.py's original top import
# block verbatim; __init__ re-exports the names it binds so old attribute
# accesses off the module (asset_library_service.os, .json, …) still resolve.

import os
import json
import copy
import math
import threading
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.asset_library_service')


# The package's files ship under the zyg_workflows package directory, where the
# pre-split asset_library_service.py lived.
_HERE = str(paths.PKG_DIR)
_CHARS_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')
_AUDIO_ROOT = str(paths.DATA_DIR / 'asset_libraries')
_AUDIO_EXTS = ('.wav', '.mp3', '.ogg', '.flac', '.m4a')

_CATEGORIES = {
    'items': {'label': 'Items', 'kind': 'visual', 'preview_shape': 'object'},
    'food': {'label': 'Food', 'kind': 'visual', 'preview_shape': 'object'},
    'weapons': {'label': 'Weapons', 'kind': 'visual', 'preview_shape': 'object'},
    'agriculture': {'label': 'Agriculture', 'kind': 'visual', 'preview_shape': 'scene'},
    'water': {'label': 'Water', 'kind': 'visual', 'preview_shape': 'scene'},
    'clouds': {'label': 'Clouds', 'kind': 'visual', 'preview_shape': 'scene'},
    'geology': {'label': 'Geology', 'kind': 'visual', 'preview_shape': 'scene'},
    'furniture': {'label': 'Furniture', 'kind': 'visual', 'preview_shape': 'object'},
    'sfx': {'label': 'SFX', 'kind': 'audio'},
    'vocal_fx': {'label': 'Vocal FX', 'kind': 'audio'},
    # 2026-08-25: one-shot foley (weapons, gore, impacts, designed hits, raw
    # object recordings). Kept OUT of `sfx`, which is the ambience-BED library a
    # scene loops under dialogue — a thousand one-shots in that dir would make
    # choosing a bed impossible. See pack_ingest.py.
    'foley': {'label': 'Foley', 'kind': 'audio'},
    'soundtracks': {'label': 'Soundtracks', 'kind': 'audio'},
    # 2026-09-02: sampled MUSICAL INSTRUMENT one-shots (plucked/bowed/blown/
    # struck notes, per pitch, dynamic and articulation). Kept OUT of `foley`
    # for the same reason `foley` was kept out of `sfx`: foley is the library a
    # scene picks a single PROP beat from, and tens of thousands of pitched
    # notes there would drown that choice. Instruments also carry axes nothing
    # else in the library has — instrument / pitch / dynamic / articulation —
    # which the SFX tab groups on. See instrument_pack_ingest.py.
    'instruments': {'label': 'Instruments', 'kind': 'audio'},
    # 2026-08-25: merges saved from the SFX Merger (:8899 SFX Library tab).
    # Each file's sidecar carries a licence DERIVED from its sources (strictest
    # wins, an unclean source fails the merge closed) plus `merge_recipe`, so
    # the gate audits it like any other file and the tab can reopen it.
    'merged': {'label': 'Merged', 'kind': 'audio'},
    # 2026-08-30: live mic takes recorded straight from the SFX Merger mixer's
    # own input picker. An operator's own performance, so it lands at ingest
    # with license_id 'royalty-free-verified' — the same bucket
    # sfx_merger.derive_licence() already falls back to for a clean merge of
    # unrelated commercial sources — rather than inventing a new license id
    # the downstream ambience_ingest.license_gate allowlist would not know.
    'recorded': {'label': 'Recorded', 'kind': 'audio'},
    # 2026-08-31: merges saved from the Voice Merger (:8899 Voices tab) — the
    # same lane-board/knob-rack/save mechanism as the SFX Merger above, just
    # layering rendered voice takes instead of library files. Its licence
    # sidecar is derived from voice_studio.publication_policy() per source
    # voice rather than from asset-library metadata: a merge with any
    # non-publishable voice in it (Kyutai-descended, or an excluded age band)
    # fails closed the same way an unclean SFX source does. See voice_merger.py.
    'voice_mix': {'label': 'Voice Mix', 'kind': 'audio'},
    # live mic takes recorded from the Voice Merger mixer's own input picker —
    # mirrors 'recorded' above.
    'voice_recorded': {'label': 'Voice Recorded', 'kind': 'audio'},
}

# Starter libraries — period-appropriate but general. Each: id, name, prompt_clause,
# negative (bleed suppression), anchor (drives the apply instruction).
_DEFAULTS = {
    'items': [
        {
            'id': 'quill_pen',
            'name': 'Quill Pen',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a white goose-feather quill pen with a sharpened nib',
            'negative': '',
        },
        {
            'id': 'clay_pipe',
            'name': 'Clay Pipe',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a long thin white clay smoking pipe with a small round bowl',
            'negative': 'quill, pen, feather',
        },
        {
            'id': 'brass_lantern',
            'name': 'Brass Lantern',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a brass ship lantern with leaded glass panes and a carry ring',
            'negative': '',
        },
        {
            'id': 'leather_ledger',
            'name': 'Leather Ledger',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a thick leather-bound ledger book with brass clasps',
            'negative': '',
        },
        {
            'id': 'spyglass',
            'name': 'Spyglass',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a collapsible brass spyglass telescope',
            'negative': '',
        },
        {
            'id': 'rope_coil',
            'name': 'Coil of Rope',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a coil of thick hemp ship rope',
            'negative': '',
        },
    ],
    'food': [
        {
            'id': 'bread_loaf',
            'name': 'Bread Loaf',
            'anchor': 'on-table',
            'prompt_clause': 'a rustic round loaf of dark bread on a wooden board',
            'negative': '',
        },
        {
            'id': 'cheese_wheel',
            'name': 'Cheese Wheel',
            'anchor': 'on-table',
            'prompt_clause': 'a wedge cut from a golden wheel of aged cheese',
            'negative': '',
        },
        {
            'id': 'stew_bowl',
            'name': 'Bowl of Stew',
            'anchor': 'on-table',
            'prompt_clause': 'a steaming wooden bowl of thick brown stew with a spoon',
            'negative': '',
        },
        {
            'id': 'wine_jug',
            'name': 'Wine Jug',
            'anchor': 'on-table',
            'prompt_clause': 'a stoneware jug of red wine with a pewter cup beside it',
            'negative': '',
        },
        {
            'id': 'dried_fish',
            'name': 'Dried Fish',
            'anchor': 'on-table',
            'prompt_clause': 'salted dried fish on a wooden platter',
            'negative': '',
        },
        {
            'id': 'apples_basket',
            'name': 'Basket of Apples',
            'anchor': 'on-table',
            'prompt_clause': 'a woven basket of red and green apples',
            'negative': '',
        },
    ],
    'weapons': [
        {
            'id': 'musket',
            'name': 'Musket',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a long 17th-century flintlock musket with a walnut stock and brass fittings',
            'negative': '',
        },
        {
            'id': 'cutlass',
            'name': 'Cutlass',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a curved steel naval cutlass with a brass basket hilt',
            'negative': '',
        },
        {
            'id': 'dagger',
            'name': 'Dagger',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a short steel dagger with a dark leather-wrapped grip',
            'negative': '',
        },
        {
            'id': 'flintlock_pistol',
            'name': 'Flintlock Pistol',
            'anchor': 'held-in-hand',
            'prompt_clause': 'an ornate flintlock pistol with engraved silver mounts',
            'negative': '',
        },
        {
            'id': 'boarding_axe',
            'name': 'Boarding Axe',
            'anchor': 'held-in-hand',
            'prompt_clause': 'a naval boarding axe with a spiked poll and hardwood haft',
            'negative': '',
        },
    ],
    'agriculture': [
        {
            'id': 'wheat_field',
            'name': 'Wheat Field',
            'anchor': 'scene',
            'prompt_clause': 'a golden wheat field ready for harvest under a wide sky',
            'negative': '',
        },
        {
            'id': 'plough',
            'name': 'Ox Plough',
            'anchor': 'scene',
            'prompt_clause': 'a wooden ox-drawn plough turning dark farmland soil',
            'negative': '',
        },
        {
            'id': 'hay_cart',
            'name': 'Hay Cart',
            'anchor': 'scene',
            'prompt_clause': 'a wooden cart stacked high with hay on a dirt farm track',
            'negative': '',
        },
        {
            'id': 'windmill',
            'name': 'Windmill',
            'anchor': 'scene',
            'prompt_clause': 'a Dutch windmill with canvas sails beside a polder canal',
            'negative': '',
        },
        {
            'id': 'vegetable_garden',
            'name': 'Vegetable Garden',
            'anchor': 'scene',
            'prompt_clause': 'neat rows of a kitchen vegetable garden with cabbages and beans',
            'negative': '',
        },
    ],
    'water': [
        {
            'id': 'ocean_waves',
            'name': 'Ocean Waves',
            'anchor': 'scene',
            'prompt_clause': 'rolling open-ocean waves with whitecaps and sea spray',
            'negative': '',
        },
        {
            'id': 'calm_harbor',
            'name': 'Calm Harbor',
            'anchor': 'scene',
            'prompt_clause': 'a calm harbor at dusk with moored sailing ships reflected in still water',
            'negative': '',
        },
        {
            'id': 'river',
            'name': 'River',
            'anchor': 'scene',
            'prompt_clause': 'a broad slow river winding through green banks',
            'negative': '',
        },
        {
            'id': 'storm_sea',
            'name': 'Storm Sea',
            'anchor': 'scene',
            'prompt_clause': 'a violent storm-tossed sea with towering dark waves and driving rain',
            'negative': '',
        },
        {
            'id': 'waterfall',
            'name': 'Waterfall',
            'anchor': 'scene',
            'prompt_clause': 'a tall waterfall crashing into a misty rock pool',
            'negative': '',
        },
    ],
    'clouds': [
        {
            'id': 'storm_clouds',
            'name': 'Storm Clouds',
            'anchor': 'scene',
            'prompt_clause': 'towering dark storm clouds with distant lightning',
            'negative': '',
        },
        {
            'id': 'cumulus',
            'name': 'Cumulus Sky',
            'anchor': 'scene',
            'prompt_clause': 'bright white cumulus clouds in a deep blue summer sky',
            'negative': '',
        },
        {
            'id': 'sunset_sky',
            'name': 'Sunset Sky',
            'anchor': 'scene',
            'prompt_clause': 'a dramatic orange-and-purple sunset sky with layered clouds',
            'negative': '',
        },
        {
            'id': 'fog_bank',
            'name': 'Fog Bank',
            'anchor': 'scene',
            'prompt_clause': 'a low dense fog bank rolling over the ground at dawn',
            'negative': '',
        },
        {
            'id': 'night_sky',
            'name': 'Night Sky',
            'anchor': 'scene',
            'prompt_clause': 'a clear moonlit night sky with stars and thin silver clouds',
            'negative': '',
        },
    ],
    'geology': [
        {
            'id': 'sea_cliffs',
            'name': 'Sea Cliffs',
            'anchor': 'scene',
            'prompt_clause': 'sheer chalk sea cliffs battered by waves',
            'negative': '',
        },
        {
            'id': 'mountain_range',
            'name': 'Mountain Range',
            'anchor': 'scene',
            'prompt_clause': 'a jagged snow-capped mountain range under clear light',
            'negative': '',
        },
        {
            'id': 'rocky_shore',
            'name': 'Rocky Shore',
            'anchor': 'scene',
            'prompt_clause': 'a rocky boulder-strewn shoreline with tide pools',
            'negative': '',
        },
        {
            'id': 'cave',
            'name': 'Cave',
            'anchor': 'scene',
            'prompt_clause': 'the mouth of a dark limestone cave with dripping stalactites',
            'negative': '',
        },
        {
            'id': 'canyon',
            'name': 'Canyon',
            'anchor': 'scene',
            'prompt_clause': 'a deep red-rock canyon with layered stone walls',
            'negative': '',
        },
    ],
    'furniture': [
        {
            'id': 'oak_table',
            'name': 'Oak Table',
            'anchor': 'in-scene',
            'prompt_clause': 'a heavy dark oak refectory table with thick turned legs',
            'negative': '',
        },
        {
            'id': 'captains_chair',
            'name': "Captain's Chair",
            'anchor': 'in-scene',
            'prompt_clause': "a carved wooden captain's armchair with a worn leather seat",
            'negative': '',
        },
        {
            'id': 'sea_chest',
            'name': 'Sea Chest',
            'anchor': 'in-scene',
            'prompt_clause': 'an iron-banded wooden sea chest with a domed lid',
            'negative': '',
        },
        {
            'id': 'bookshelf',
            'name': 'Bookshelf',
            'anchor': 'in-scene',
            'prompt_clause': 'a tall dark wooden bookshelf filled with leather-bound books',
            'negative': '',
        },
        {
            'id': 'writing_desk',
            'name': 'Writing Desk',
            'anchor': 'in-scene',
            'prompt_clause': 'a slant-top wooden writing desk with brass fittings and an inkwell',
            'negative': '',
        },
        {
            'id': 'canopy_bed',
            'name': 'Canopy Bed',
            'anchor': 'in-scene',
            'prompt_clause': 'a carved four-poster canopy bed with heavy dark drapes',
            'negative': '',
        },
    ],
}


def _log_noop(_m):
    pass


def categories():
    return {k: dict(v) for k, v in _CATEGORIES.items()}


def category_info(cat):
    return _CATEGORIES.get(cat)


def _lib_path(cat):
    return os.path.join(_HERE, 'data', 'runtime', f'asset_library_{cat}.json')


def _audio_dir(cat):
    d = os.path.join(_AUDIO_ROOT, cat)
    os.makedirs(d, exist_ok=True)
    return d
