# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The kanban stage maps and the department -> stage-map step.

Moved verbatim from ``bp_pipeline_api_steps.py`` lines 25-529 by the
2026-10-06 modularization split.
"""

import logging as _zyg_logging

from zyg_workflows import paths
from zyg_workflows.char_state_service import (
    _char_derive_pipeline_stage,
    _contact_sheet_derive_stage,
    _creature_derive_pipeline_stage,
    _normalize_char_model_family,
)
from zyg_workflows.pipeline_common import _parse_pipeline_model_family

# ── re-export surface ────────────────────────────────────────────────────────
# The private helpers above came with the pre-split top import block and this
# file does not read them itself; they stay because the siblings re-import the
# block off each other. Declaring them is what makes the re-export deliberate
# rather than an unused import; nothing does ``import *`` from here, so __all__
# changes no behaviour. `json`, `os` and `zyg_workflows.bin.exe` are gone: every
# sibling that needs them imports them itself.
__all__ = [
    '_char_derive_pipeline_stage',
    '_contact_sheet_derive_stage',
    '_creature_derive_pipeline_stage',
    '_normalize_char_model_family',
    '_parse_pipeline_model_family',
]

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_pipeline_api_steps')

# Resolved once at import, as the portability recipe asks. Every default below
# reproduces the location the literal `os.path.expanduser('~/…')` it replaces
# pointed at, so behaviour on the production box is unchanged.
_FLUX_SCHNELL_DIR = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
_COMFY_CHECKPOINTS_DIR = str(paths.ZYG_COMFY_ROOT / 'models' / 'checkpoints')
_REALESRGAN_WEIGHTS = str(paths.ZYG_REALESRGAN_ROOT / 'RealESRGAN_x4plus.pth')
_SPORTS_VIDEO_STATUS = str(paths.ZYG_HOME / 'sports-video-pipeline' / 'status.json')
_HOME_DIR = str(paths.ZYG_HOME)
# The HuggingFace cache keeps its upstream name and its upstream default; only
# the hard-coded home prefix is replaced.
_HF_HOME_DEFAULT = str(paths.ZYG_HOME / '.cache' / 'huggingface')


# Children's-music styles that have a LIVE board of their own on the Workflows
# view (kanban_main.js MELODY_WIRED / TEMPLATES['mel_children_<style>']). A run
# of one of these reports its own board so the operator sees the style light up
# instead of the shared 'kidsmusic' board. 'dance' is deliberately absent —
# operator decision 2026-09-06, it is not a library shelf and no composer style
# writes it. Same eleven keys as kanban_server._KM_FAMILIES['children'].
_MEL_WIRED_CHILDREN = (
    'playtime',
    'sleeptime',
    'storytime',
    'learning',
    'lullaby',
    'nursery',
    'counting',
    'singalong',
    'animals',
    'seasons',
    'bedtime',
)

# Cinematic styles with a live board of their own (kanban_main.js
# MELODY_WIRED.cinematic / TEMPLATES['mel_cinematic_<style>']). Those boards are
# the composer board MINUS the Pictures column and the Lyrics card, so they
# share KANBAN_STAGE_MAP below unchanged: the picture and lyric stage fragments
# simply never find a card to stamp. 'storytime' and 'sonata' deliberately
# repeat keys from other families — a shelf is only ever addressed as
# (family, style), which is why the family has to be read before the style.
_MEL_WIRED_CINEMATIC = (
    'cheerful',
    'sad',
    'heroic',
    'tavern',
    'storytime',
    'mystery',
    'battle',
    'sonata',
    'waltz',
    'nocturne',
    'march',
)

# Maps kanban card name → list of stage-name fragments to match against
# stage_timeline.  Order matters: FIRST MATCH WINS, most specific first —
# a bare 'stage 4' also matches 'Stage 4b: Rhythm Refresh'.
#
# ── The keys ARE the board's card titles ─────────────────────────────────
# kanban_main.js joins `cards[job.prompt]` by EXACT string match, so a key
# that is not a card title on the board it names is dead weight, and a card
# whose title is not a key can never leave 'queued'.  This map used to be
# keyed by stage-level names ('Web Research', 'TTS Narration', …) while the
# documentary board had long since been rewritten to tool-level cards
# ('Playwright Web Research', 'IndexTTS-2 — en-GB-RyanNeural', …): 15 of the
# 19 keys matched nothing and 24 of the board's 28 cards sat permanently
# queued through a completed run.  Re-keyed to the board 2026-08-30, the way
# the storyteller map below already was.
#
# Fallback and (optional) cards are deliberately LEFT OUT — 'yt-dlp Music
# Fallback', 'ffmpeg minterpolate', 'OpenCV TELEA Inpainting' and the two
# '(optional)' identity cards.  They share a stage with the primary tool, so
# mapping them would light them on every run and claim a path that never
# ran; the same reasoning already excludes the storyteller IPAdapter card.
KANBAN_STAGE_MAP_DOCUMENTARY = {
    # Research column — Stages 1-2
    'Topic Setup': ['stage 1', 'topic setup', 'topic'],
    'Playwright Web Research': ['web research', 'stage 2', 'academic research', 'research'],
    'Semantic Scholar + arXiv': ['academic research', 'stage 2', 'research'],
    'PDF + Vector Document Search': ['document research', 'stage 2', 'research'],
    # Scripting column — Stages 3, 3.1, 3b
    'Script Generation': ['stage 3:', 'script prep', 'script'],
    'Murch Engine — Emotion & Rhythm': ['stage 3.1', 'emotion'],
    'Visual Intent Tagging': ['stage 3b', 'visual tag'],
    # Generation column — Stages 3.5, 3.6, 4
    'IndexTTS-2 — en-GB-RyanNeural': ['tts narration', 'stage 4:', 'tts'],
    'FLUX.1-schnell Image Generation': ['stage 3.5:', 'ai image generation', 'image gen'],
    'WAN2.1-I2V Video Generation': ['stage 4/wan', 'wan', 'video gen'],
    # QA & Repair column — Stage 3.6 / 4.1 / 4.2
    'MediaPipe Anatomy QA': ['stage 3.6', 'anatomy repair', 'flux fill'],
    'MediaPipe Anatomy Mask': ['stage 3.6', 'anatomy repair', 'flux fill'],
    'Diffusion Inpaint (Qwen InstantX)': ['stage 3.6', 'anatomy repair', 'flux fill'],
    'YOLOv8 Object Tracking': ['stage 4.1', 'object track'],
    'RIFE ncnn-Vulkan Frame Interpolation': ['stage 4.2', 'temporal repair', 'rife'],
    # Assets column — Stage 5
    'Smart Clip Scoring + Trim': ['stage 5', 'stock', 'clip'],
    # Assembly column — Stage 6 and the finishing passes
    'ffmpeg lut3d Color Grade': ['color grade', 'lut'],
    'Ken Burns Animation': ['ken burns', 'stage 6', 'video assembly'],
    'Murch Engine — Transition Graph': ['stage 6', 'video assembly', 'assembly'],
    'ffmpeg concat — Final Assembly': ['stage 6', 'video assembly', 'assembly'],
    'Book Intro Title Card': ['book intro'],
    'ffmpeg Subtitle Burn-In': ['subtitle burn', 'subtitle'],
    'ACE-Step Background Music': ['background music', 'ace-step', 'bgm', 'soundtrack'],
}

# Keyed by the video board's card titles (see the documentary map above for
# why): the stage-level keys this used to carry matched exactly ONE of the
# board's 23 cards, so a running video render lit the image-gen card and
# left the whole rest of the board queued.
KANBAN_STAGE_MAP_VIDEO = {
    # Planning
    'Scene Planning': ['topic setup', 'scene planning', 'stage 1', 'topic'],
    # Visuals
    'Qwen-2512 Image Generation': ['ai image generation', 'stage 2', 'image gen'],
    'MediaPipe Anatomy QA': ['anatomy repair', 'stage 2b', 'anatomy'],
    # Audio
    'IndexTTS-2 — en-GB-RyanNeural': ['tts narration', 'stage 3', 'tts'],
    'Chatterbox — seed-pool voice': ['tts narration', 'stage 3', 'tts'],
    'soundbible.com Foley Downloader': ['foley sfx', 'foley', 'audiogen sfx', 'audiogen'],
    'ffmpeg amix — Foley Mixer': ['foley sfx', 'foley', 'audiogen sfx', 'audiogen'],
    # Video
    'WAN2.1-I2V Video Generation': ['video generation', 'stage 4', 'wan', 'video gen'],
    'ffmpeg Stream Loop + SRT Burn-In': ['subtitle burn', 'stream loop', 'video assembly', 'stage 5'],
    'FLUX img2img Scene Chaining': ['scene chaining', 'chaining', 'img2img chain'],
    # QA & Repair
    'MediaPipe Anatomy Mask': ['anatomy repair', 'stage 2b', 'anatomy'],
    'Diffusion Inpaint (Qwen InstantX)': ['anatomy repair', 'stage 2b', 'anatomy'],
    'YOLOv8 Object Tracking': ['object tracking', 'stage 4b', 'object track'],
    'RIFE ncnn-Vulkan Interpolation': ['temporal repair', 'stage 4c', 'rife'],
    # Assembly
    'ffmpeg lut3d Color Grade': ['color grade', 'lut'],
    'ffmpeg concat — Final Assembly': ['video assembly', 'stage 5', 'assembly'],
    'ACE-Step Background Music': ['background music', 'stage 5b', 'bgm', 'soundtrack'],
}

# Keyed by the manga board's card titles — same re-key as documentary/video.
KANBAN_STAGE_MAP_MANGA = {
    'Scene Planning': ['topic setup', 'scene planning', 'stage 1', 'topic'],
    'Qwen-2512 Image Generation': ['ai image generation', 'stage 2', 'image gen'],
    'MediaPipe Anatomy QA': ['anatomy repair', 'stage 2b', 'anatomy'],
    'IndexTTS-2 — en-GB-RyanNeural': ['tts narration', 'stage 3', 'tts'],
    'Chatterbox — seed-pool voice': ['tts narration', 'stage 3', 'tts'],
    'Ken Burns Panel Animation': ['panel animation', 'stage 4', 'ken burns'],
    'ffmpeg Stream Loop + SRT Burn-In': ['subtitle burn', 'stream loop', 'video assembly', 'stage 5'],
    'ffmpeg concat — Final Assembly': ['video assembly', 'stage 5', 'assembly'],
    'ACE-Step Background Music': ['background music', 'stage 5b', 'bgm', 'soundtrack'],
}

# (There is no KANBAN_STAGE_MAP for creatures. The creature board is built
#  card-by-card from char_state_service.CREATURE_STAGE_ORDER in the
#  `active_creature_job` branch of kanban_status — the stage-fragment map that
#  used to sit here named the OLD video-style cards, matched nothing on the
#  current sheet-workflow board, and was never assigned to KANBAN_STAGE_MAP.)

KANBAN_STAGE_MAP_STORYTELLER_SDXL = {
    # Character column — all belong to Stage 1
    'Blender 4.3.2 Headless Render': ['stage 1 — character prep'],
    'FLUX Character Render': ['stage 1 — character prep'],
    'Caption Generation': ['stage 1 — character prep'],
    # LoRA Training column — also Stage 1
    'SimpleTuner FLUX LoRA Training': ['stage 1 — character prep'],
    'IPAdapter-Only Mode (LoRA timeout fallback)': ['stage 1 — character prep'],
    # Story Script column — Stage 2
    'Claude claude-sonnet-4-6 — Story Script': ['stage 2 — story script'],
    'Murch Engine — Emotion & Shot Analysis': ['stage 2 — story script'],
    # Narration column — Stage 3
    'IndexTTS-2': ['stage 3 — tts narration'],
    'Chatterbox — seed-pool voice': ['stage 3 — tts narration'],
    # Image Gen column — Stage 3.5 (SDXL)
    'SDXL Image Generation': ['stage 3.5 — ai image generation'],
    # Ken Burns column — Stage 4
    'PIL Ken Burns Renderer': ['stage 4 — ken burns animation'],
    'ffmpeg libx264 Frame Encoder': ['stage 4 — ken burns animation'],
    # Assembly column — Stage 5
    'Murch Engine — xfade Graph Builder': ['stage 5 — final assembly'],
    'ffmpeg xfade — Transition Assembly': ['stage 5 — final assembly'],
    'ffmpeg Audio + Video Merge': ['stage 5 — final assembly'],
    'ACE-Step Background Music': ['stage 5 — final assembly'],
    'yt-dlp Music Fallback': ['stage 5 — final assembly'],
    'soundbible.com Ambient Fallback': ['stage 5 — final assembly'],
}

KANBAN_STAGE_MAP_STORYTELLER_FLUX = {
    # Character column — all belong to Stage 1
    'Blender 4.3.2 Headless Render': ['stage 1 — character prep'],
    'FLUX Character Render': ['stage 1 — character prep'],
    'Caption Generation': ['stage 1 — character prep'],
    # LoRA Training column — also Stage 1
    'SimpleTuner FLUX LoRA Training': ['stage 1 — character prep'],
    'IPAdapter-Only Mode (LoRA timeout fallback)': ['stage 1 — character prep'],
    # Story Script column — Stage 2
    'Claude claude-sonnet-4-6 — Story Script': ['stage 2 — story script'],
    'Murch Engine — Emotion & Shot Analysis': ['stage 2 — story script'],
    # Narration column — Stage 3
    'IndexTTS-2': ['stage 3 — tts narration'],
    'Chatterbox — seed-pool voice': ['stage 3 — tts narration'],
    # Image Gen column — Stage 3.5
    'FLUX + Character LoRA': ['stage 3.5 — ai image generation'],
    # 2026-07-24 fix: IPAdapter card no longer mapped to stage 3.5 — it lit 'running'
    # alongside the LoRA card on every run even though IPAdapter never engages.
    # Ken Burns column — Stage 4
    'PIL Ken Burns Renderer': ['stage 4 — ken burns animation'],
    'ffmpeg libx264 Frame Encoder': ['stage 4 — ken burns animation'],
    # Assembly column — Stage 5
    'Murch Engine — xfade Graph Builder': ['stage 5 — final assembly'],
    'ffmpeg xfade — Transition Assembly': ['stage 5 — final assembly'],
    'ffmpeg Audio + Video Merge': ['stage 5 — final assembly'],
    'ACE-Step Background Music': ['stage 5 — final assembly'],
    'yt-dlp Music Fallback': ['stage 5 — final assembly'],
    'soundbible.com Ambient Fallback': ['stage 5 — final assembly'],
}

KANBAN_STAGE_MAP_CLIPFARM = {
    # Stage 1 — Discovery
    'Source Scanner': ['stage 1', 'discovery'],
    # Stage 2 — Analysis (parallel)
    'Metrics Agent': ['stage 2', 'analysis'],
    'Trend Detector': ['stage 2', 'analysis'],
    'Research Agent': ['stage 2', 'analysis'],
    'Overview Agent': ['stage 2', 'analysis'],
    'Compliance Check': ['stage 2', 'analysis'],
    # Stage 3 — Selection & Deduplication
    'Selection Agent': ['stage 3', 'selection'],
    'Deduplication': ['stage 3', 'selection', 'deduplication'],
    # Stage 4a — Fetch (parallel)
    'Transcript Fetch': ['stage 4a', 'fetch'],
    'Video Download': ['stage 4a', 'fetch'],
    'Rights Check': ['stage 4a', 'fetch'],
    'Content Indexer': ['stage 4a', 'fetch'],
    # Stage 4b — Processing (parallel)
    'Moment Detection': ['stage 4b', 'processing'],
    'Variant Generator': ['stage 4b', 'processing'],
    'Hook Generator': ['stage 4b', 'processing'],
    'Commentary Agent': ['stage 4b', 'processing'],
    'Subtitle Generator': ['stage 4b', 'processing'],
    'Sound Effects': ['stage 4b', 'processing'],
    'Thumbnail Agent': ['stage 4b', 'processing'],
    'Library Agent': ['stage 4b', 'processing'],
    # Stage 5 — QC & Adaptation
    'QC Agent': ['stage 5', 'qc', 'adaptation'],
    'Error Detection': ['stage 5', 'qc'],
    'Platform Adapter': ['stage 5', 'qc', 'adaptation'],
    # Stage 6 — Publish
    'Assignment Agent': ['stage 6', 'publish'],
    'YouTube Scheduler': ['stage 6', 'publish'],
    'Upload Scheduler': ['stage 6', 'publish'],
    'Upload Agent': ['stage 6', 'publish'],
    'Air Time Agent': ['stage 6', 'publish'],
}

KANBAN_STAGE_MAP_ENVIRONMENTS = {
    'Environment Brief': ['environment brief', 'brief'],
    '2D Scenery Plate': ['2d scenery', 'scenery plate'],
    '3D Camera-Move Clip': ['3d camera', 'camera-move'],
    'Character Composite': ['composite'],
    'Grade & Deliver': ['grade', 'deliver'],
}

KANBAN_STAGE_MAP_EFFECTS = {
    'Effect Brief': ['effect brief', 'brief'],
    '2D FX Layer': ['2d fx', 'fx layer'],
    '3D Motion FX Clip': ['3d motion', 'motion fx'],
    'Composite / Blend': ['composite', 'blend'],
    'Grade & Deliver': ['grade', 'deliver'],
}

KANBAN_STAGE_MAP_WARDROBE = {
    'Wardrobe Brief': ['wardrobe brief', 'brief'],
    'Apply Outfit': ['apply outfit', 'outfit'],
    'Deliver': ['deliver'],
}

# Card title (JS TEMPLATES.kidsmusic card.prompt) → lowercase stage-name
# fragments. Substring, FIRST-MATCH-WINS, so the two 'Measure …' cards
# must be matched on their distinguishing word: 'measure score' and
# 'measure produced' — a shared 'measure' fragment would stamp both
# cards from whichever ran first.
KANBAN_STAGE_MAP_KIDSMUSIC = {
    'Song Brief': ['song brief'],
    'Lyrics': ['lyrics'],
    'Compose & Score': ['compose'],
    'Score Render': ['score render'],
    'Measure Score Render': ['measure score'],
    'Produced Track (ACE-Step)': ['produced track'],
    'Measure Produced Track': ['measure produced'],
    'Master & Deliver': ['master', 'deliver'],
    # The picture leg, added to pipeline_kidsmusic.STAGES and to the
    # board on 2026-08-29 but not here — so a run sitting in
    # 'Illustrate' (measured 2026-08-30 00:23) reported that stage in
    # the header while the card itself stayed queued.
    'Storyboard': ['storyboard'],
    'Illustrate': ['illustrate'],
    'Measure Frames': ['measure frames'],
    'Assemble Video': ['assemble video'],
}

# Card title (JS TEMPLATES.remix_ai card.prompt) → lowercase stage-name
# fragments. Substring, FIRST-MATCH-WINS, so every fragment here must be
# unique across the cards: 'analysis' alone would stamp the Frame,
# Transcript and Soundtrack cards from whichever ran first, and
# 'regeneration' would collide Script with Title the same way.
KANBAN_STAGE_MAP_REMIX_AI = {
    'Source Sweep': ['source sweep'],
    'Source Download': ['source download'],
    'Frame Analysis': ['frame analysis'],
    'Transcript Analysis': ['transcript analysis'],
    'Soundtrack Analysis': ['soundtrack analysis'],
    'Script Regeneration': ['script regeneration'],
    'Title Regeneration': ['title regeneration'],
    'AI Image Generation': ['ai image generation'],
    'TTS Narration': ['tts narration'],
    'Ken Burns Animation': ['ken burns'],
    'Video Assembly': ['video assembly'],
    'Soundtrack Replacement': ['soundtrack replacement'],
    'Subtitle Burn': ['subtitle burn'],
    'Delivery': ['delivery'],
}

# Card title (JS TEMPLATES.remix card.prompt) → lowercase stage-name fragments.
# Substring, first-match-wins — keep fragments unique across cards.
KANBAN_STAGE_MAP_REMIX = {
    'Watch Channels': ['watch channels'],
    'Score Candidates': ['score candidates'],
    'Download Source': ['download source'],
    'Transcribe': ['transcribe'],
    'Select Moments': ['select moments'],
    'Write Narration': ['write narration'],
    'Split-Screen Render': ['render'],  # matches Split-Screen + Compilation Render
    'QC Gates': ['qc gates'],
    'Deliver': ['deliver'],
    'Cleanup': ['cleanup'],
}

# Card title (JS TEMPLATES.ch_fin_stockmarket / ch_fin_crypto card.prompt)
# → lowercase stage-name fragments. Substring, first-match-wins.
KANBAN_STAGE_MAP_FINANCE = {
    'Collect Market Data': ['collect market data'],
    'Score & Rank': ['score & rank'],
    'Write Script': ['write script'],
    'Build Charts': ['build charts'],
    'Narrate': ['narrate'],
    'Render Episode': ['render episode'],
    'QC Gates': ['qc gates'],
    'Deliver': ['deliver'],
    'Ice Box': ['ice box'],
    'Cleanup': ['cleanup'],
}

KANBAN_STAGE_MAP_SPORTSBET = {
    'Collect Fixtures': ['collect fixtures'],
    'Price & Select Bets': ['price & select'],
    'Pull Team Art': ['pull team art'],
    'Write Script': ['write script'],
    'Build Charts': ['build charts'],
    'Narrate': ['narrate'],
    'Render Episode': ['render episode'],
    'QC Gates': ['qc gates'],
    'Deliver': ['deliver'],
    'Ice Box': ['ice box'],
    'Cleanup': ['cleanup'],
}

# Keys are the WARDROBE board's card titles, because that is the board
# the assetlib_* departments render on — 'Asset Brief'/'Apply Asset' matched no
# card there, so two of the three cards never left 'queued'.
KANBAN_STAGE_MAP_ASSETLIB = {
    'Wardrobe Brief': ['asset brief', 'brief'],
    'Apply Outfit': ['apply asset', 'asset'],
    'Deliver': ['deliver'],
}


def _step_stage_map_for_department(dept, model_family, active_job):
    """``(KANBAN_STAGE_MAP, template_name)`` for the focused job's department.

    ``dept`` is already lower-cased; ``model_family`` is the job's
    ``model_family`` with the same ``or 'flux'`` default the caller applied.
    Every branch returns a FRESH dict where the original mutated one, so a
    per-run card swap can never leak into the next request.
    """
    if dept == 'video':
        # Family-specific labels so the board matches the active run (FLUX vs SDXL).
        if model_family == 'sdxl':
            # TEMPLATES_SDXL renames exactly two of the video board's cards; the
            # other 21 are shared, so clone the FLUX map and swap those two
            # rather than maintaining a second copy that drifts.
            stage_map = dict(KANBAN_STAGE_MAP_VIDEO)
            stage_map.pop('Qwen-2512 Image Generation', None)
            stage_map['SDXL Image Generation'] = ['ai image generation', 'stage 2', 'image gen']
            stage_map.pop('FLUX img2img Scene Chaining', None)
            stage_map['SDXL Scene Chaining (not enabled)'] = ['scene chaining', 'chaining', 'img2img chain']
        else:
            stage_map = dict(KANBAN_STAGE_MAP_VIDEO)
        # Only show Scene Chaining card when job is using continuous mode
        if active_job.get('scene_mode', 'independent') != 'continuous':
            stage_map.pop('Scene Chaining', None)
        return stage_map, 'video'
    if dept == 'manga':
        if model_family == 'sdxl':
            stage_map = dict(KANBAN_STAGE_MAP_MANGA)
            stage_map.pop('Qwen-2512 Image Generation', None)
            stage_map['SDXL Image Generation'] = ['stage 2', 'ai image generation', 'image gen']
        else:
            stage_map = dict(KANBAN_STAGE_MAP_MANGA)
        return stage_map, 'manga'
    if dept == 'storyteller':
        if model_family == 'sdxl':
            stage_map = dict(KANBAN_STAGE_MAP_STORYTELLER_SDXL)
        else:
            stage_map = dict(KANBAN_STAGE_MAP_STORYTELLER_FLUX)
        return stage_map, 'storyteller'
    if dept == 'clipfarm':
        return dict(KANBAN_STAGE_MAP_CLIPFARM), 'ch_clipped'
    if dept == 'environments':
        return dict(KANBAN_STAGE_MAP_ENVIRONMENTS), 'environments'
    if dept == 'effects':
        return dict(KANBAN_STAGE_MAP_EFFECTS), 'effects'
    if dept == 'wardrobe':
        return dict(KANBAN_STAGE_MAP_WARDROBE), 'wardrobe'
    if dept == 'kidsmusic':
        # Every wired style's board is built from the kidsmusic board with the
        # card titles kept byte-identical, so the map above is shared and only
        # the board the operator is sent to changes. A cinematic board is that
        # board minus the Pictures column and the Lyrics card; the fragments for
        # those stages stay in the map and simply match nothing there.
        #
        # FAMILY FIRST, THEN STYLE: 'storytime' and 'sonata' exist under more
        # than one family, so the style alone does not identify a board.
        _st = (active_job.get('song') or {}).get('style') or ''
        _fam = active_job.get('family') or (active_job.get('song') or {}).get('family') or 'children'
        if _fam == 'cinematic' and _st in _MEL_WIRED_CINEMATIC:
            template_name = f'mel_cinematic_{_st}'
        else:
            # An unwired or missing style falls back to the shared live composer
            # board rather than naming a template the JS does not have (which
            # would silently land on Documentary via _buildFromTemplate).
            template_name = f'mel_children_{_st}' if _st in _MEL_WIRED_CHILDREN else 'kidsmusic'
        return dict(KANBAN_STAGE_MAP_KIDSMUSIC), template_name
    if dept == 'char2d':
        # 2D Character Basics I (2026-09-16). The columns ARE the runner's
        # STAGES and the JS builds each card with prompt === stage title, so the
        # map is the identity — title -> [title.lower()].
        #
        # THE CONTRACT THIS RELIES ON: matching is substring, first-match-wins,
        # so no stage title may be a substring of another. The 14 titles were
        # chosen so none is; tests/test_char2d_runner.py pins that.
        from zyg_workflows import pipeline_char2d as _c2

        return {s: [str(s).lower()] for s in _c2.STAGES}, 'char2d_basics_1'
    if dept.startswith('kids_'):
        # Children's series (2026-09-06). GENERIC: the columns ARE the runner's
        # STAGES, and the JS builds each card with prompt === stage title, so the
        # map is the identity — title -> [title.lower()]. No per-series entry
        # here, ever; a new pipeline_kids_<slug>.py is picked up by discover().
        #
        # THE CONTRACT THIS RELIES ON: matching is substring, first-match-wins,
        # so no stage title may be a substring of another one in the same series
        # ('Render' inside 'Render Audio' would stamp both cards from whichever
        # ran first). kids_series_common.discover() is the place to assert that;
        # it is not fixed here on purpose — this branch must stay dumb.
        from zyg_workflows import kids_series_common as _ks_common

        _ks_mod = _ks_common.discover().get(dept[5:])
        _ks_stages = list(getattr(_ks_mod, 'STAGES', []) or []) if _ks_mod else []
        return {s: [str(s).lower()] for s in _ks_stages}, dept
    if dept == 'remix_ai':
        return dict(KANBAN_STAGE_MAP_REMIX_AI), 'remix_ai'
    if dept == 'remix':
        return dict(KANBAN_STAGE_MAP_REMIX), 'remix'
    if dept in ('stocks', 'crypto'):
        return dict(KANBAN_STAGE_MAP_FINANCE), ('ch_fin_stockmarket' if dept == 'stocks' else 'ch_fin_crypto')
    if dept in ('tokitoki', 'arena'):
        # Sub-channel boards: tokitoki + 'soccer' → 'ch_tokitoki_soccer'. The two
        # keys that do not match their category name are mapped explicitly.
        _sub = (active_job or {}).get('sub_channel') or ''
        _board = {'basketball': 'nba', 'mma': 'ufc'}.get(_sub, _sub)
        return dict(KANBAN_STAGE_MAP_SPORTSBET), (f'ch_{dept}_{_board}' if _board else f'ch_{dept}')
    if str(dept or '').startswith('assetlib_'):
        return dict(KANBAN_STAGE_MAP_ASSETLIB), 'wardrobe'  # reuse the 3-stage board layout
    if model_family == 'sdxl':
        # Swap only the label so the SDXL Kanban board lights up properly.
        # The underlying stage names remain "Stage 3.5 — Image Gen".
        stage_map = dict(KANBAN_STAGE_MAP_DOCUMENTARY)
        stage_map.pop('FLUX.1-schnell Image Generation', None)
        stage_map['SDXL Image Generation'] = ['stage 3.5:', 'ai image generation', 'image gen']
    else:
        stage_map = dict(KANBAN_STAGE_MAP_DOCUMENTARY)
    return stage_map, 'documentary'
