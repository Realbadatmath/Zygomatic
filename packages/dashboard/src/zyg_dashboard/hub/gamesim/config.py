# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Flask app, GameSim paths and the game-name/folder map."""

import os
from pathlib import Path

from flask import Flask


app = Flask(__name__)

GAMESIM_DIR = os.path.expanduser('~/Zygomatic/GameSim')

# The "← Hub" link points at hub_server on :7000, a different port on the same
# box, so it cannot be a relative URL. See docs/configuration.md.
LAN_HOST_PLACEHOLDER = '__ZYG_LAN_HOST__'


def lan_host() -> str:
    return os.environ.get('ZYG_LAN_HOST', '127.0.0.1')


# Maps game names (as they appear in the UI) to their GameSim subfolder
GAME_FOLDER_MAP = {
    'Minecraft': 'minecraft',
    'Minecraft Build/Mine': 'minecraft_build',
    'Minecraft Dig FP': 'minecraft_dig_fp',
    'Minecraft Build FP': 'minecraft_build_fp',
    'CS2 / CS:GO': 'cs2',
    'DOTA 2': 'dota2',
    'Team Fortress 2': 'tf2',
    'Valheim': 'valheim',
    'Rust': 'rust',
    'Overwatch 2': 'overwatch2',
    'Roblox': 'roblox',
    "Garry's Mod": 'gmod',
    'StarCraft II': 'sc2',
    'Left 4 Dead 2': 'l4d2',
    'ARK: Survival Evolved': 'ark',
    'Screeps': 'screeps',
    'Warcraft III': 'wc3',
    'Unreal Tournament': 'ut',
    'Among Us': 'amongus',
    'GTA V (FiveM/RAGE)': 'gtav',
    'Age of Empires II DE': 'aoe2',
    'Halo MCC': 'halo',
    'Fortnite': 'fortnite',
    'League of Legends': 'lol',
    'OpenAI Gym': 'openai_gym',
    'Unity ML-Agents': 'unity_ml',
    'PySC2 (DeepMind API)': 'pySC2',
    'OpenSpiel': 'openspiel',
    'Pygame (custom arena)': 'pygame',
}

RECORDINGS_DIR = Path('~/Zygomatic/GameSim/recordings').expanduser()
DISPLAY_BASE = 10  # virtual displays :10, :11, :12 ...
