# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Imports, paths, browser-sandbox helpers and topic→discipline tables."""

# This module re-does the original single-file import block verbatim; every name here is
# re-exported to the package __init__ and to the sibling modules, so F401 is expected.

import os
import re
import time
import random
from zyg_workflows import pgdb
from zyg_workflows.contact import contact_email
from psycopg.rows import dict_row
import urllib.parse as _up
import urllib.request as _ur
from zyg_workflows import http_json as _hj

# ── Reuse all browser/timing constants from the crime research agent ──────────
from zyg_workflows.web_research_agent import (
    _USER_AGENTS,
    _PlaywrightAdapter,
    _PAGE_LOAD_TIMEOUT,
    _between_pages,
    _between_sites,
)

# ── Visual Framework (optional — graceful fallback if module not on path) ─────
try:
    from zyg_workflows.clipfarm_visual_framework import VisualFrameworkResolver as _VisualFrameworkResolver

    _VF_RESOLVER = _VisualFrameworkResolver()
except ImportError:
    _VF_RESOLVER = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.scholarly_research_agent')

# ── re-export surface ────────────────────────────────────────────────────────
# These names of the inherited import block are not used in this file: the
# siblings re-import them off this module — directive.py takes ``re``, core.py
# ``dict_row``/``pgdb``/``random``/``time``/``_USER_AGENTS``, extraction.py
# ``random``/``re``/``_PAGE_LOAD_TIMEOUT``/``_PlaywrightAdapter``/``_up``,
# run_stages.py ``random``/``re``/``_between_sites``/``_up``/``_ur``,
# legacy_sources.py ``_between_pages``/``_up``, sources.py
# ``contact_email``/``time``, and the package __init__ re-exports all of them.
# Declaring them is what makes the re-export deliberate rather than an unused
# import; nothing does ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    're',
    'time',
    'random',
    'pgdb',
    'contact_email',
    'dict_row',
    '_up',
    '_ur',
    '_USER_AGENTS',
    '_PlaywrightAdapter',
    '_PAGE_LOAD_TIMEOUT',
    '_between_pages',
    '_between_sites',
]


# ── Paths ─────────────────────────────────────────────────────────────────────
_AGENT_DIR = os.path.dirname(os.path.dirname(__file__))
_DATA_DIR = os.path.join(_AGENT_DIR, 'data', 'runtime')
_IMG_BASE = os.path.join(_DATA_DIR, 'scholarly_images')

# ── Browser Sandbox helpers ───────────────────────────────────────────────────
_BROWSER_SANDBOX_BASE = f'http://127.0.0.1:{os.getenv("BROWSER_SANDBOX_PORT", "7200")}'


def _sb_fetch(url: str, timeout: int = 20) -> dict | None:
    """Fetch a URL through the browser sandbox.
    Returns dict with keys: ok, url, status_code, content_type, title, text, links.
    Returns None if the sandbox is unavailable or the request fails.
    """
    try:
        return _hj.post_json(f'{_BROWSER_SANDBOX_BASE}/fetch', {'url': url}, timeout=timeout)
    except Exception:
        return None


def _sb_search(query: str, num_results: int = 10) -> list:
    """Search via the browser sandbox. Returns list of {title, url, snippet} dicts."""
    try:
        _res = _hj.post_json(
            f'{_BROWSER_SANDBOX_BASE}/search', {'query': query, 'num_results': num_results}, timeout=20
        )
        return (_res or {}).get('results', [])
    except Exception:
        return []


# ── Topic → academic discipline mapping ───────────────────────────────────────
_TOPIC_DISCIPLINES = {
    'crime': ['law', 'criminology', 'criminal-justice', 'sociology'],
    'war': ['history', 'military-history', 'political-science', 'international-relations'],
    'technology': ['computer-science', 'engineering', 'electrical-engineering', 'information-science'],
    'luxury': ['business', 'economics', 'marketing', 'sociology'],
    'entertainment': ['communication', 'film', 'media-studies', 'cultural-studies'],
    'cosmetics': ['chemistry', 'business', 'marketing', 'public-health'],
    'clothes': ['fashion', 'business', 'textile-science', 'cultural-studies'],
    'hypes': ['sociology', 'marketing', 'communication', 'psychology'],
    'history': ['history', 'humanities', 'archaeology', 'cultural-studies'],
    'psychology': ['psychology', 'behavioral-science', 'neuroscience', 'cognitive-science'],
    'philosophy': ['philosophy', 'ethics', 'humanities', 'political-science'],
    'economics': ['economics', 'finance', 'business', 'political-science'],
    'politics': ['political-science', 'international-relations', 'public-policy', 'sociology'],
    'environment': ['environmental-science', 'ecology', 'public-policy', 'geography'],
    'medicine': ['medicine', 'public-health', 'biology', 'neuroscience'],
    'religion': ['religion', 'humanities', 'sociology', 'anthropology'],
    'space': ['astronomy', 'astrophysics', 'engineering', 'physics'],
    'architecture': ['architecture', 'urban-planning', 'engineering', 'cultural-studies'],
    'art': ['art', 'humanities', 'cultural-studies', 'communication'],
    'music': ['music', 'cultural-studies', 'communication', 'humanities'],
}

_TOPIC_QUERIES = {
    'crime': [
        'criminal justice system essay',
        'criminology research paper',
        'law enforcement crime analysis',
        'criminal psychology dissertation',
    ],
    'war': [
        'military history essay',
        'war and society research paper',
        'armed conflict international relations',
        'warfare historical analysis',
    ],
    'technology': [
        'technology society impact essay',
        'digital innovation research',
        'computer science emerging technology',
        'artificial intelligence society',
    ],
    'luxury': [
        'luxury goods consumer behavior',
        'luxury market economics essay',
        'conspicuous consumption research',
        'high end brand sociology',
    ],
    'entertainment': [
        'entertainment industry analysis',
        'media culture essay',
        'film industry economics research',
        'popular culture study',
    ],
    'cosmetics': [
        'cosmetics industry research essay',
        'beauty standards sociology',
        'personal care products analysis',
        'cosmetic chemistry paper',
    ],
    'clothes': [
        'fashion industry research essay',
        'textile and apparel economics',
        'clothing culture sociology',
        'fast fashion environmental impact',
    ],
    'hypes': [
        'social media hype consumer behavior',
        'viral trend sociology essay',
        'marketing hype psychology',
        'influencer culture research',
    ],
    'history': [
        # ── Ancient Greece ──────────────────────────────────────────
        'Alexander the Great Macedonian conquest ancient Greece empire essay',
        'Athenian democracy Pericles Golden Age ancient Greece civilization',
        'Battle of Thermopylae Leonidas Spartan warriors Persian Wars history',
        'Peloponnesian War Athens Sparta ancient Greek city-states conflict',
        'Persian Wars Battle of Marathon Xerxes invasion ancient Greece history',
        'Trojan War Homer Iliad Bronze Age ancient Greece legendary history',
        'ancient Greek Olympics Olympia athletes gods games history essay',
        'Alexander the Great India Punjab Indus conquest Maurya history',
        # ── Ancient Rome ────────────────────────────────────────────
        'Roman Empire founding Romulus Julius Caesar ancient civilization analysis',
        'Julius Caesar Roman Republic civil war assassination Brutus Ides March',
        'Augustus Caesar first Roman emperor Pax Romana empire essay',
        'fall of Western Roman Empire barbarian invasions Visigoths history',
        'Punic Wars Hannibal Barca Carthage Rome republic military history',
        'Roman gladiators Colosseum ancient Rome spectacle society history',
        'Roman army legions tactics military campaigns empire expansion history',
        # ── Ancient Egypt ───────────────────────────────────────────
        'Cleopatra Egypt Ptolemaic dynasty ancient history essay',
        'Ramesses II pharaoh Battle of Kadesh New Kingdom ancient Egypt history',
        'ancient Egypt pyramids Giza Tutankhamun pharaoh civilization essay',
        'Egyptian civilization Nile religion gods Osiris Isis dynasty history',
        # ── Mesopotamia and Near East ───────────────────────────────
        'Babylonian Empire Hammurabi code ancient Mesopotamia civilization history',
        'Assyrian Empire ancient Near East military conquest Nineveh history',
        'Persian Empire Cyrus the Great Achaemenid dynasty conquest history',
        'Sumerian civilization Ur Mesopotamia first cities writing cuneiform history',
        # ── Mongols, Huns and Central Asia ─────────────────────────
        'Genghis Khan Mongol Empire expansion conquest medieval history',
        'Attila the Hun Hunnic Empire Rome invasion barbarian history',
        'Timur Tamerlane Central Asian empire conquest Samarkand medieval history',
        'Mongol invasion siege Baghdad medieval Islamic empire destruction',
        'Kublai Khan Yuan dynasty China Mongol rule history essay',
        # ── Vikings and Norse ────────────────────────────────────────
        'Viking Age raids Scandinavia medieval Europe settlement history',
        'Norse mythology Odin Thor Valhalla Viking warriors longships history',
        'Leif Erikson Norse exploration Vinland North America history essay',
        # ── Medieval Europe ──────────────────────────────────────────
        'Black Death bubonic plague medieval Europe demographic history',
        'Crusades holy war Jerusalem Christian Muslim medieval history essay',
        'Hundred Years War England France Joan of Arc medieval history essay',
        'Norman Conquest William the Conqueror 1066 England feudal history',
        'medieval feudalism knights lords castles European society essay',
        'Charlemagne Holy Roman Empire Carolingian dynasty medieval history',
        'Byzantine Empire Constantinople Eastern Roman Emperor history essay',
        'Ottoman Empire Suleiman the Magnificent Constantinople conquest 1453',
        'Saladin Muslim leader Crusades Jerusalem Ayyubid dynasty history',
        # ── Pre-Columbian Americas ───────────────────────────────────
        'Maya civilization origins calendar astronomy collapse pre-Columbian history',
        'Aztec Empire Tenochtitlan Hernan Cortes Spanish conquest Mesoamerica',
        'Inca Empire Peru Andes Francisco Pizarro Spanish conquest history',
        'ancient Americas Olmec Zapotec Toltec pre-Columbian civilizations',
        # ── Asia ────────────────────────────────────────────────────
        'Silk Road ancient trade routes China Rome civilizations essay',
        'ancient China Han Dynasty emperor civilization silk history essay',
        'Qin Shi Huang first Chinese emperor Great Wall unification dynasty',
        'feudal Japan samurai Tokugawa shogunate Edo period history essay',
        # ── Specific events and figures ──────────────────────────────
        'ancient maritime history Phoenician sailors navigation sea trade',
        'ancient warfare siege catapult trireme naval battle tactics history',
        'Sparta ancient Greece military culture warriors agoge society history',
        'ancient Rome Republic Senate governance law politics history essay',
        # ── Broad catch-all queries (find ANY historical paper) ───────
        # These cast a wide net so unknown/niche topics get discovered too
        'ancient world civilizations rise fall warfare empire history essay',
        'medieval history kingdoms rulers warfare society Europe essay',
        'ancient military history battle tactics weapons soldiers conquest',
        'world history empire ruler dynasty political power history essay',
        'ancient civilization culture religion society trade history essay',
        'pre-modern history warfare conquest ruler kingdom ancient essay',
        'historical biography ancient ruler emperor king military leader',
        'ancient peoples tribes nomads migration conquest settlement history',
        'ancient religion mythology gods temples ritual society history',
        'early human civilization agriculture city-state ancient history',
        'ancient trade economy merchant civilization empire history essay',
        'medieval Islamic empire caliphate scholar civilization history',
        'ancient African kingdoms empire history civilization essay',
        'ancient India Maurya Gupta civilization history empire essay',
        'ancient Southeast Asia kingdom civilization history empire essay',
        'colonial conquest indigenous people empire history essay',
    ],
    'psychology': [
        'psychology human behavior research paper',
        'cognitive psychology essay',
        'mental health societal impact dissertation',
        'behavioral science study',
    ],
    'philosophy': [
        'philosophy ethics essay dissertation',
        'moral philosophy research paper',
        'epistemology and knowledge essay',
        'political philosophy analysis',
    ],
    'economics': [
        'economics inequality research paper',
        'macroeconomics essay dissertation',
        'global markets economic analysis',
        'behavioral economics study',
    ],
    'politics': [
        'political science democracy essay',
        'government policy research paper',
        'international relations dissertation',
        'political theory analysis',
    ],
    'environment': [
        'environmental science climate essay',
        'ecology sustainability research',
        'climate change policy dissertation',
        'environmental impact study',
    ],
    'medicine': [
        'medicine public health essay research',
        'disease epidemiology dissertation',
        'healthcare systems analysis paper',
        'neuroscience medical research',
    ],
    'religion': [
        'religion society sociology essay',
        'comparative religion research paper',
        'religious history dissertation',
        'faith and culture analysis',
    ],
    'space': [
        'space exploration astronomy essay',
        'astrophysics research paper dissertation',
        'cosmology universe study',
        'space technology engineering research',
    ],
    'architecture': [
        'architecture urban design essay',
        'city planning research paper',
        'architectural history dissertation',
        'sustainable design analysis',
    ],
    'art': [
        'art history analysis essay',
        'visual culture research paper',
        'contemporary art dissertation',
        'aesthetics art theory study',
    ],
    'music': [
        'music culture society essay',
        'musicology research paper dissertation',
        'music industry economics analysis',
        'ethnomusicology study',
    ],
}
