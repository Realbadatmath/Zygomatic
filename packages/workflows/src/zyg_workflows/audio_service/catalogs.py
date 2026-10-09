# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_service.py — Background music + foley SFX for Zygomatic video pipeline.

Manages downloading, caching, and mixing of royalty-free audio assets.

Foley SFX pipeline (priority order per scene):
  1. [DISABLED 2026-08-09] generative foley — AudioGen removed (CC-BY-NC
     weights); slot reserved for a licence-clean V2A engine (Foley-Omni, MIT)
  2. Freesound API — 530k+ CC recordings searched by keyword (needs API key)
  3. soundbible.com hardcoded catalog — CC0 fallback (IDs verified at build time)

Background music (priority order):
  1. ACE-Step 1.5 (local AI, MIT weights) — replaced CC-BY-NC MusicGen 2026-08-09
  2. yt-dlp from known royalty-free YouTube sources
  3. soundbible ambient loops as last-resort fallback

Main API
--------
  get_music_for_topic(topic, emotion, out_dir, duration_s)  → local path or None
  get_foley_for_scene(description)                          → [(path, volume), ...]
  mix_bgm_into_video(video_path, music_path, out_path, music_vol=0.12)  → bool
  mix_foley_into_audio(tts_path, foley_list, out_path, tts_dur)         → bool
"""

from __future__ import annotations

# ruff: noqa: F401  this module inherits the pre-split top import block: its
# siblings re-import those names from here.

import os
import re
import json
import subprocess
import logging
import urllib.request
import urllib.parse
import logging as _zyg_logging

from zyg_workflows import paths
from zyg_workflows.bin import exe

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.audio_service')


# channel kept from the pre-split module
_log = logging.getLogger('zyg_workflows.audio_service')

# ── Directory setup ────────────────────────────────────────────────────────
_CREWS_DIR = str(paths.PKG_DIR)
# The '..' is the pre-package value and is kept: the assets tree sits BESIDE the
# package (src/data/assets), not inside it, and the catalogs on disk live there.
_ASSETS_DIR = os.path.join(_CREWS_DIR, '..', 'data', 'assets')
MUSIC_DIR = os.path.join(_ASSETS_DIR, 'music')
FOLEY_DIR = os.path.join(_ASSETS_DIR, 'foley')

os.makedirs(MUSIC_DIR, exist_ok=True)
os.makedirs(FOLEY_DIR, exist_ok=True)

# ── yt-dlp binary (used for music downloads) ──────────────────────────────
_YTDLP_LOCAL = paths.ZYG_HOME / '.local' / 'bin' / 'yt-dlp'
_YTDLP = str(_YTDLP_LOCAL) if _YTDLP_LOCAL.exists() else 'yt-dlp'

# ── Background music catalog ──────────────────────────────────────────────
# Primary: yt-dlp from YouTube (royalty-free / CC).
# Fallback: soundbible.com ambient loops (shorter, but always work).
#
# YouTube IDs: all are from royalty-free / CC licensed sources designed for
# video production. Attribution may be required for public distribution.
#
# Format: (filename, youtube_id_or_url, soundbible_fallback_id)
_MUSIC_CATALOG: dict[str, list[tuple[str, str, str]]] = {
    'epic': [
        ('epic_01.mp3', 'https://www.youtube.com/watch?v=Dm2fZqTkCFY', '2036'),
        ('epic_02.mp3', 'https://www.youtube.com/watch?v=O2pkplfd3Ig', '2036'),
    ],
    'battle': [
        ('battle_01.mp3', 'https://www.youtube.com/watch?v=bm_SXoBes-s', '2022'),
        ('battle_02.mp3', 'https://www.youtube.com/watch?v=nX0Z3klsAkI', '2022'),
    ],
    'triumphant': [
        ('triumph_01.mp3', 'https://www.youtube.com/watch?v=kG3MFXYxFHs', '1973'),
        ('triumph_02.mp3', 'https://www.youtube.com/watch?v=p9tP5QKGQT8', '1973'),
    ],
    'mysterious': [
        ('mystery_01.mp3', 'https://www.youtube.com/watch?v=Nl_MtBqD1Og', '2059'),
        ('mystery_02.mp3', 'https://www.youtube.com/watch?v=Wsx-2K8z2Nk', '2059'),
    ],
    'sad': [
        ('sad_01.mp3', 'https://www.youtube.com/watch?v=4To2wMbzFgA', '1447'),
        ('sad_02.mp3', 'https://www.youtube.com/watch?v=0Gfde1eJJMU', '1447'),
    ],
    'peaceful': [
        ('peaceful_01.mp3', 'https://www.youtube.com/watch?v=1ZYbU82GVz4', '1753'),
        ('peaceful_02.mp3', 'https://www.youtube.com/watch?v=jgMqlSEGFEE', '1753'),
    ],
    'dark': [
        ('dark_01.mp3', 'https://www.youtube.com/watch?v=OB6WEBaHC-s', '2059'),
        ('dark_02.mp3', 'https://www.youtube.com/watch?v=aRl_bGqGVm0', '2059'),
    ],
    'adventure': [
        ('adventure_01.mp3', 'https://www.youtube.com/watch?v=rTyKk53Wq3o', '1973'),
        ('adventure_02.mp3', 'https://www.youtube.com/watch?v=qcPW0WCpHuY', '1973'),
    ],
}

# ── Foley SFX catalog (soundbible.com — public domain, confirmed accessible) ──
# Format: (filename, soundbible_id)
_FOLEY_CATALOG: dict[str, tuple[str, str]] = {
    'sword_clash': ('foley_sword_clash.mp3', '1499'),  # sword slash
    'crowd_cheer': ('foley_crowd_cheer.mp3', '1986'),  # crowd cheer/applause
    'crowd_roar': ('foley_crowd_roar.mp3', '2022'),  # large crowd
    'wind': ('foley_wind.mp3', '1779'),  # wind howling
    'thunder': ('foley_thunder.mp3', '1447'),  # thunder clap
    'fire': ('foley_fire.mp3', '1454'),  # campfire crackling
    'ocean_waves': ('foley_ocean.mp3', '1198'),  # ocean waves
    'rain': ('foley_rain.mp3', '1721'),  # rain / thunder storm (was 2019 — wrong file)
    'horse_hooves': ('foley_horse.mp3', '1887'),  # horse galloping
    'battle_drums': ('foley_battle_drums.mp3', '1742'),  # drumroll
    'trumpet': ('foley_trumpet.mp3', '1823'),  # winning triumphal fanfare (was 1761=glass break)
    'arrow_flight': ('foley_arrow.mp3', '1855'),  # arrow whoosh
    'explosion': ('foley_explosion.mp3', '1807'),  # explosion
    'footsteps': ('foley_footsteps.mp3', '2048'),  # footsteps
    'car_door': ('foley_car_door.mp3', '1697'),  # car door
    'car_engine': ('foley_car_engine.mp3', '1697'),  # car door (reuse until better ID)
    'gunshot': ('foley_gunshot.mp3', '1789'),  # 9mm gunshot
    'church_bells': ('foley_bells.mp3', '1853'),  # large bell
    'nature_birds': ('foley_birds.mp3', '1815'),  # morning birds
    'impact_boom': ('foley_boom.mp3', '2036'),  # impact/boom
    # ── Animal sounds ──────────────────────────────────────────────────────
    'lion_roar': ('foley_lion.mp3', '1282'),  # lion roar
    'elephant': ('foley_elephant.mp3', '1140'),  # elephant trumpeting
    'rooster': ('foley_rooster.mp3', '1134'),  # rooster crowing
    'dog_bark': ('foley_dog_bark.mp3', '2215'),  # labrador barking
    'cat_meow': ('foley_cat.mp3', '1954'),  # cat meow
    'cattle': ('foley_cattle.mp3', '1568'),  # cattle herd
    'frogs': ('foley_frogs.mp3', '2033'),  # frog chorus
    'wolf_howl': ('foley_wolf.mp3', '278'),  # wolf pack howling
    # ── Additional birds ───────────────────────────────────────────────────
    'crow_caw': ('foley_crow.mp3', '1285'),  # crow / raven cawing
    'owl_hoot': ('foley_owl.mp3', '1504'),  # owl hooting
    'eagle_cry': ('foley_eagle.mp3', '1796'),  # eagle / hawk screech
    'seagull': ('foley_seagull.mp3', '1583'),  # seagull calls
    # ── More mammals ──────────────────────────────────────────────────────
    'monkey_calls': ('foley_monkey.mp3', '1241'),  # chimp / monkey
    'snake_hiss': ('foley_snake.mp3', '1575'),  # snake hissing
    'bear_growl': ('foley_bear.mp3', '1268'),  # bear growling
    'tiger_roar': ('foley_tiger.mp3', '1283'),  # tiger roar
    'pig_oink': ('foley_pig.mp3', '1448'),  # pig oinking
    'sheep_baa': ('foley_sheep.mp3', '1462'),  # sheep baaing
    'horse_whinny': ('foley_horse_whinny.mp3', '1458'),  # horse neigh/whinny
    # ── Insects / small creatures ─────────────────────────────────────────
    'crickets': ('foley_crickets.mp3', '1549'),  # crickets at night
    'bee_buzz': ('foley_bees.mp3', '1388'),  # bees / insects buzzing
    # ── Marine animals ────────────────────────────────────────────────────
    'whale_song': ('foley_whale.mp3', '1622'),  # whale song
    'dolphin': ('foley_dolphin.mp3', '1631'),  # dolphin clicks
    # ── Object / material sounds ───────────────────────────────────────────
    'glass_break': ('foley_glass_break.mp3', '1761'),  # glass breaking / window smash
    'metal_clang': ('foley_metal_clang.mp3', '1781'),  # metal clang / chains
}


# ── AudioGen prompts — one per foley category ─────────────────────────────
# Each prompt is passed to facebook/audiogen-medium.  Designed for 8-second
# ambient / single-event generation that loops cleanly.  Ends with
# ", no music, no voice" on ambient sounds to prevent hallucinated vocals.
_AUDIOGEN_PROMPTS: dict[str, str] = {
    'wind': 'strong mountain wind howling through trees, ambient outdoor gusts, no music, no voice',
    'rain': 'gentle rain falling on stone ground, steady rainfall ambience, no music, no voice',
    'thunder': 'distant rolling thunder, single powerful thunder crack, outdoor storm',
    'ocean_waves': 'ocean waves crashing on a rocky shore, steady sea ambience, no music, no voice',
    'fire': 'campfire crackling with wood popping, warm fire ambience, no music, no voice',
    'nature_birds': 'birds chirping in a forest at dawn, morning bird calls, peaceful, no music',
    'crickets': 'crickets chirping at night, summer insect chorus, night ambience, no music, no voice',
    'frogs': 'frogs croaking near a pond at night, frog chorus, no music, no voice',
    'bee_buzz': 'bees buzzing in a field, insect sounds, ambient nature, no music, no voice',
    'footsteps': 'slow footsteps walking on stone ground, single person walking',
    'sword_clash': 'metal sword clash and scrape, steel on steel, combat sound effect',
    'crowd_cheer': 'large crowd cheering and applauding, stadium crowd reaction',
    'crowd_roar': 'large crowd roaring loudly, massive audience noise, battle rally',
    'horse_hooves': 'horse hooves galloping on dirt ground, single horse running fast',
    'horse_whinny': 'horse neighing and whinnying, single horse call',
    'battle_drums': 'war drums beating rhythmically, tribal battle drums, no music',
    'trumpet': 'triumphant trumpet fanfare, single brass horn call, victory sound',
    'arrow_flight': 'arrow whooshing through air, projectile flying fast',
    'explosion': 'large explosion, distant rumbling blast, debris impact',
    'gunshot': 'single pistol gunshot, sharp firearm crack',
    'church_bells': 'large church bell ringing slowly, deep bell toll, no music',
    'impact_boom': 'heavy impact boom, deep thud with reverb',
    'car_door': 'car door opening and closing, vehicle door slam',
    'car_engine': 'car engine idling and revving, internal combustion engine',
    'glass_break': 'glass window shattering, breaking glass crash',
    'metal_clang': 'metal chains clinking, heavy metal clang and rattle',
    'lion_roar': 'lion roaring loudly, powerful big cat roar',
    'elephant': 'elephant trumpeting, loud elephant call',
    'rooster': 'rooster crowing at dawn, cock-a-doodle-doo',
    'dog_bark': 'dog barking, single large dog bark',
    'cat_meow': 'cat meowing softly, domestic cat vocalization, no music',
    'cattle': 'cattle mooing, herd of cows, rural farm sounds, no music',
    'wolf_howl': 'wolf howling at night, lone wolf call, wilderness ambience',
    'crow_caw': 'crow cawing, raven call, dark bird sound',
    'owl_hoot': 'owl hooting at night, single owl call, night ambience',
    'eagle_cry': 'eagle screeching, hawk screech, bird of prey call',
    'seagull': 'seagulls calling, coastal bird sounds, ocean ambience',
    'monkey_calls': 'monkeys calling in jungle, primate sounds, tropical forest',
    'snake_hiss': 'snake hissing, reptile sound effect',
    'bear_growl': 'bear growling, large predator warning sound',
    'tiger_roar': 'tiger roaring, powerful big cat snarl',
    'pig_oink': 'pigs oinking, farmyard pig sounds, no music',
    'sheep_baa': 'sheep baaing, flock of sheep, pastoral rural sound',
    'whale_song': 'whale song, underwater whale call, deep ocean sound, no music',
    'dolphin': 'dolphin clicks and whistles, marine mammal sounds',
}


# ── Keyword → foley category mapping for scene descriptions ──────────────
_SCENE_FOLEY_KEYWORDS: dict[str, list[str]] = {
    'sword_clash': [
        'sword',
        'blade',
        'steel',
        'clash',
        'duel',
        'shield',
        'weapon',
        'warrior',
        'fight',
        'combat',
        'battle',
        'spartan',
        'gladiator',
        'knight',
    ],
    'crowd_roar': [
        'army',
        'legion',
        'soldiers',
        'troops',
        'crowd',
        'masses',
        'thousands',
        'thousands of',
        'cheering',
        'rally',
        'gathered',
    ],
    'crowd_cheer': ['victory', 'triumph', 'celebrate', 'celebration', 'applaud', 'welcome', 'parade'],
    'wind': [
        'hilltop',
        'mountain',
        'cliff',
        'ridge',
        'storm',
        'gale',
        'breeze',
        'open field',
        'plain',
        'desert',
        'barren',
    ],
    'thunder': ['thunder', 'lightning', 'storm', 'tempest', 'dark clouds', 'ominous'],
    'fire': ['fire', 'flame', 'burning', 'torch', 'campfire', 'blaze', 'smoke', 'ash'],
    'ocean_waves': [
        'ocean',
        'sea',
        'waves',
        'coast',
        'beach',
        'shore',
        'harbor',
        'ship',
        'fleet',
        'naval',
        'river',
        'water',
    ],
    'rain': ['rain', 'downpour', 'drizzle', 'wet', 'flood'],
    'horse_hooves': ['horse', 'cavalry', 'chariot', 'riding', 'gallop', 'steed'],
    'battle_drums': ['march', 'advance', 'formation', 'drum', 'military', 'charge', 'regiment'],
    'trumpet': ['trumpet', 'fanfare', 'herald', 'announcement', 'summons', 'call to arms'],
    'arrow_flight': ['arrow', 'bow', 'archer', 'volley', 'rain of arrows', 'projectile'],
    'explosion': ['explosion', 'blast', 'cannon', 'bomb', 'artillery', 'siege'],
    'footsteps': ['march', 'walk', 'approach', 'patrol', 'streets', 'cobblestone'],
    'car_door': ['car', 'vehicle', 'automobile', 'sedan', 'truck', 'parking'],
    'car_engine': ['driving', 'accelerate', 'highway', 'chase', 'motor'],
    'gunshot': ['gun', 'shot', 'bullet', 'pistol', 'rifle', 'sniper', 'firing', 'gunfire'],
    'church_bells': ['church', 'cathedral', 'bell', 'monastery', 'chapel', 'funeral'],
    'nature_birds': [
        'bird',
        'birds',
        'birdsong',
        'chirp',
        'tweet',
        'warble',
        'sing',
        'singing',
        'flock',
        'flutter',
        'perch',
        'nest',
        'feather',
        'wing',
        'avian',
        'songbird',
        'sparrow',
        'robin',
        'finch',
        'pigeon',
        'dove',
        'canary',
        'parakeet',
        'parrot',
        'dawn',
        'sunrise',
        'peaceful',
        'forest',
        'garden',
        'meadow',
        'countryside',
    ],
    'crow_caw': ['crow', 'raven', 'rook', 'jackdaw', 'caw', 'black bird', 'gothic', 'omen', 'carrion'],
    'owl_hoot': ['owl', 'hoot', 'barn owl', 'screech owl', 'nocturnal', 'night bird', 'wise owl'],
    'eagle_cry': [
        'eagle',
        'hawk',
        'falcon',
        'raptor',
        'screech',
        'talons',
        'osprey',
        'kite',
        'vulture',
        'condor',
        'soaring',
        'bald eagle',
        'peregrine',
    ],
    'seagull': ['seagull', 'gull', 'coastal', 'harbor', 'pier', 'dock', 'seaside', 'fisherman', 'seabird'],
    'impact_boom': ['impact', 'crash', 'collapse', 'fall', 'defeat', 'struck', 'hit'],
    # ── Animal sound keywords ───────────────────────────────────────────────
    'lion_roar': ['lion', 'pride', 'savannah', 'africa', 'predator', 'roar', 'big cat'],
    'elephant': ['elephant', 'herd', 'savannah', 'africa', 'mammoth', 'mastodon', 'tusks'],
    'rooster': ['rooster', 'cock', 'dawn', 'farm', 'morning', 'rural', 'village awakening', 'cockerel'],
    'dog_bark': ['dog', 'hound', 'guard', 'patrol', 'barking', 'kennel', 'canine', 'puppy'],
    'cat_meow': ['cat', 'feline', 'alley', 'stray', 'kitten', 'purr', 'tabby'],
    'cattle': ['cattle', 'herd', 'pasture', 'livestock', 'ranch', 'bull', 'cow', 'moo', 'beef'],
    'frogs': ['swamp', 'marsh', 'pond', 'wetland', 'tropical', 'amphibian', 'frog'],
    'wolf_howl': ['wolf', 'pack', 'tundra', 'moonlit', 'howl', 'winter night', 'wilderness'],
    'monkey_calls': [
        'monkey',
        'chimpanzee',
        'chimp',
        'gorilla',
        'ape',
        'primate',
        'orangutan',
        'macaque',
        'baboon',
        'jungle primate',
    ],
    'snake_hiss': ['snake', 'serpent', 'cobra', 'viper', 'python', 'boa', 'asp', 'hiss', 'slither', 'reptile'],
    'bear_growl': ['bear', 'grizzly', 'polar bear', 'black bear', 'growl', 'den', 'hibernate', 'paws', 'kodiak'],
    'tiger_roar': ['tiger', 'bengal', 'panthera', 'stripe', 'jungle cat', 'prowl', 'stalk', 'siberian tiger'],
    'pig_oink': ['pig', 'hog', 'swine', 'piglet', 'boar', 'oink', 'sow', 'wild boar', 'farmyard'],
    'sheep_baa': ['sheep', 'lamb', 'baa', 'flock', 'wool', 'ewe', 'ram', 'shepherd', 'grazing'],
    'horse_whinny': ['neigh', 'whinny', 'stallion', 'mare', 'foal', 'stable', 'paddock', 'horse call'],
    'crickets': [
        'cricket',
        'crickets',
        'cicada',
        'grasshopper',
        'insect',
        'nighttime',
        'summer night',
        'chirping insects',
    ],
    'bee_buzz': ['bee', 'bees', 'wasp', 'hornet', 'buzz', 'hive', 'honey', 'pollinate', 'swarm', 'bumblebee', 'flower'],
    'whale_song': ['whale', 'blue whale', 'humpback', 'submarine', 'deep sea', 'ocean deep', 'leviathan', 'cetacean'],
    'dolphin': ['dolphin', 'porpoise', 'marine mammal', 'echolocation', 'aquatic', 'bottlenose'],
    # ── Object / material sound keywords ───────────────────────────────────
    'glass_break': ['glass', 'window', 'shatter', 'smash', 'mirror', 'bottle', 'break'],
    'metal_clang': ['chains', 'iron', 'prison', 'dungeon', 'clang', 'gate', 'bars', 'metal'],
}


# ── Topic → music mood mapping ────────────────────────────────────────────
_TOPIC_MOOD_MAP: list[tuple[list[str], str]] = [
    (
        ['war', 'battle', 'spartan', 'soldier', 'military', 'army', 'fight', 'combat', 'siege', 'conquest', 'invasion'],
        'battle',
    ),
    (['victory', 'triumph', 'hero', 'glory', 'empire', 'king', 'crowned', 'legend'], 'triumphant'),
    (['mystery', 'secret', 'conspiracy', 'spy', 'unknown', 'hidden', 'enigma', 'ancient'], 'mysterious'),
    (['death', 'grief', 'tragedy', 'loss', 'fallen', 'funeral', 'mourning', 'sacrifice'], 'sad'),
    (['nature', 'landscape', 'peaceful', 'village', 'farm', 'pastoral', 'calm'], 'peaceful'),
    (['dark', 'evil', 'villain', 'shadow', 'corruption', 'doom', 'fall', 'decay'], 'dark'),
    (['journey', 'adventure', 'quest', 'explore', 'travel', 'discovery', 'expedition'], 'adventure'),
    (['epic', 'great', 'legend', 'ancient', 'civilization', 'history', 'rise'], 'epic'),
]

_EMOTION_MOOD_MAP: dict[str, str] = {
    'battle': 'battle',
    'triumph': 'triumphant',
    'awe': 'epic',
    'grief': 'sad',
    'tension': 'dark',
    'neutral': 'peaceful',
    'epic': 'epic',
    'mystery': 'mysterious',
}

# ── MusicGen text prompts per mood ────────────────────────────────────────
# These are passed directly to Meta MusicGen to generate unique music per run.
_MUSICGEN_PROMPTS: dict[str, str] = {
    'battle': 'epic orchestral battle music with war drums, heavy brass, intense strings, cinematic, powerful, 130 bpm',
    'triumphant': 'triumphant orchestral fanfare, soaring strings, brass horns, victorious cinematic score, heroic, uplifting',
    'epic': 'epic cinematic orchestral music, sweeping strings, powerful brass, dramatic timpani, blockbuster film score',
    'mysterious': 'mysterious atmospheric music, low strings, subtle percussion, tense ambient, cinematic suspense, dark orchestral',
    'sad': 'emotional sad orchestral music, solo cello, soft piano, melancholic strings, cinematic mourning score',
    'peaceful': 'peaceful ambient orchestral music, gentle strings, light harp, soft flute, serene cinematic landscape score',
    'dark': 'dark ominous orchestral music, deep bass, menacing brass, dissonant strings, villain cinematic theme',
    'adventure': 'adventurous orchestral music, bold brass, driving strings, heroic theme, cinematic journey score, upbeat',
}
