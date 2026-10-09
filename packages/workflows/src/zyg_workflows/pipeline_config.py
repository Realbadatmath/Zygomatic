# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_config.py — the pipeline constants, in the base library.

Every name here was a module-level constant in ``zyg_dashboard.crewai_web_gui``
until 2026-10-05, from-imported by the pipelines in this package — the base
library importing the application above it. The definitions moved down here
unchanged and the dashboard imports them back, so there is still exactly one
of each.

Shared mutable state (job registries, semaphores, locks) and the behaviour the
dashboard provides (the audit log, the error log) live in
:mod:`zyg_workflows.runtime` instead; this module holds only constants.
"""

import os

from zyg_workflows import paths

# ── Pipeline DSL + caveman style adapter (opt-in, env-gated, soft-fail) ─────
try:
    from zyg_workflows import pipeline_dsl_adapter as _dsl
except ImportError:
    _dsl = None  # adapter missing → all hooks are no-ops downstream


def _caveman_kw(mode: str = '') -> dict:
    """Token-log metadata when caveman was applied (mode: planner|user_planner|system)."""
    if not mode or _dsl is None:
        return {}
    try:
        return _dsl.caveman_record_meta(mode)
    except Exception:
        return {}


# Stage 6 Ken Burns: duration-scaled ffmpeg wait + thread stagger (single source of truth).
_KB_ENCODE_WAIT_MIN_S = 120


_KB_ENCODE_WAIT_PER_DUR_S = 6


_KB_ENCODE_WAIT_PAD_S = 30


# Post-encode (Stage 6 assembly / color grade / subtitles): NVENC primary, libx264 fallback.
# Set ZYG_POST_ENCODE=cpu to force CPU x264 (debug or driver issues).
_FORCE_CPU_POST_ENCODE = os.environ.get('ZYG_POST_ENCODE', '').strip().lower() in (
    'cpu',
    'x264',
    'libx264',
    '1',
    'true',
)


# The runtime scratch directory every pipeline writes transient state into.
# In the GUI this was ``os.path.join(DATA_DIR, 'runtime')``; it is rebased on
# paths.ZYG_DATA_ROOT here, which resolves to the same directory.
_RUNTIME_DIR = str(paths.ZYG_DATA_ROOT / 'runtime')
_FLUX_PERF_TELEMETRY_PATH = os.path.join(_RUNTIME_DIR, 'flux_perf_telemetry.json')


# ── Narrator voice helpers ────────────────────────────────────────────────────
_VOICE_LIBRARY_PATH = os.path.join(_RUNTIME_DIR, 'narrator_voices.json')


_CHANNEL_VOICES_PATH = os.path.join(_RUNTIME_DIR, 'narrator_channel_voices.json')


_INTROS_GENERAL_PATH = os.path.join(_RUNTIME_DIR, 'narrator_intros_general.json')


_INTROS_FEMALE_PATH = os.path.join(_RUNTIME_DIR, 'narrator_intros_female.json')


# Category keyword maps: used to pick the best intro category from a transcript excerpt
_INTRO_CATEGORY_KEYWORDS = {
    'HUMOR / ANIMAL HUMOR': ['animal', 'dog', 'cat', 'bird', 'zoo', 'monkey', 'funny', 'humor'],
    'SPORTS / FAILS': ['sport', 'game', 'player', 'team', 'score', 'win', 'loss', 'fail', 'tournament'],
    'FAILS': ['fail', 'fall', 'crash', 'accident', 'mistake', 'wrong', 'oops'],
    'FUNNY STREET MOMENTS': ['street', 'city', 'crowd', 'public', 'random', 'people'],
    'SHOCKING / UNEXPECTED': ['shocking', 'unexpected', 'surprise', 'twist', 'reveal', 'unbelievable'],
    'NIGHTLIFE / PARTY': ['nightlife', 'party', 'club', 'bar', 'night', 'drunk', 'dance', 'drinks'],
    'SATISFYING / SKILL': ['skill', 'satisfying', 'perfect', 'amazing', 'incredible', 'talent'],
    'WHOLESOME / HEARTWARMING': ['wholesome', 'heartwarming', 'kind', 'sweet', 'love', 'family', 'child'],
    'CRIME / DASHCAM / CAUGHT ON CAMERA': ['crime', 'police', 'caught', 'camera', 'dashcam', 'arrest', 'theft'],
    'TRAVEL / DESTINATIONS': ['travel', 'trip', 'country', 'city', 'tourist', 'destination', 'visit'],
    'STORYTELLING / DOCUMENTARY STYLE': ['story', 'documentary', 'interview', 'narrative', 'history', 'explain'],
    'FASHION / STYLE': ['fashion', 'style', 'outfit', 'clothes', 'dress', 'wear', 'look'],
    'DANCING': ['dance', 'dancing', 'choreography', 'move', 'rhythm', 'music'],
    'NBA': ['nba', 'basketball', 'lebron', 'curry', 'lakers', 'celtics', 'dunk', 'three'],
    'SOCCER / FOOTBALL': ['soccer', 'football', 'goal', 'ronaldo', 'messi', 'premier', 'champions'],
    'MMA / UFC': ['mma', 'ufc', 'fight', 'knock', 'boxing', 'punch', 'combat', 'martial'],
    'TENNIS': ['tennis', 'serve', 'court', 'slam', 'federer', 'djokovic', 'nadal'],
    'FOOD / MUKBANG / COOKING': ['food', 'eat', 'cook', 'recipe', 'restaurant', 'mukbang', 'meal', 'taste'],
    'MONEY / LUXURY / FLEX': ['money', 'luxury', 'rich', 'wealth', 'crypto', 'invest', 'flex', 'expensive'],
    'GAMING / ESPORTS': ['game', 'gaming', 'esport', 'stream', 'twitch', 'play', 'gamer', 'console'],
    'MOTIVATION / GRIND / DISCIPLINE': ['motivation', 'grind', 'discipline', 'success', 'hustle', 'mindset', 'goal'],
    'KIDS / FAMILY': ['kid', 'child', 'baby', 'parent', 'family', 'school', 'mom', 'dad'],
    'NATURE / WEATHER / EXTREME': ['nature', 'weather', 'storm', 'flood', 'earthquake', 'extreme', 'wild'],
    'EDUCATIONAL': ['educate', 'learn', 'explain', 'theory', 'science', 'research', 'study', 'fact'],
    'CYBER CRIME / HACKING': ['hack', 'cyber', 'scam', 'phish', 'data', 'breach', 'fraud', 'online crime'],
    'FRAUD / SCAMS': ['fraud', 'scam', 'con', 'fake', 'lie', 'cheat', 'trick', 'deceive'],
    'VIOLENCE / CONFLICT / WAR': [
        'war',
        'conflict',
        'military',
        'violence',
        'weapon',
        'attack',
        'soldier',
        'geopolitics',
    ],
}


_INTRO_FEMALE_KEYWORDS = {
    'GET READY WITH ME (GRWM)': ['grwm', 'morning routine', 'get ready', 'routine'],
    '💄 MAKEUP TUTORIALS / TRANSFORMATIONS': ['makeup', 'contour', 'foundation', 'lipstick', 'blush', 'tutorial'],
    '👗 OUTFIT / FASHION HAULS': ['haul', 'outfit', 'fashion', 'clothes', 'style', 'thrift'],
    '💔 RELATIONSHIP / DATING ADVICE': ['relationship', 'dating', 'breakup', 'love', 'partner', 'red flag'],
    '🏋️ FITNESS / BODY TRANSFORMATION': ['fitness', 'gym', 'workout', 'transform', 'body', 'weight', 'cardio'],
    '🧴 SKINCARE ROUTINES': ['skincare', 'skin', 'moisturizer', 'serum', 'face', 'glow'],
    '🍽️ RECIPES / WHAT I EAT IN A DAY': ['recipe', 'cook', 'meal', 'eat', 'food', 'diet'],
    '🧠 MENTAL HEALTH / SELF IMPROVEMENT': ['mental health', 'anxiety', 'therapy', 'self', 'improve', 'mindset'],
    '💅 NAIL ART / BEAUTY TRENDS': ['nail', 'manicure', 'pedicure', 'beauty trend'],
    '👶 PREGNANCY / MOTHERHOOD': ['pregnancy', 'baby', 'mom', 'motherhood', 'birth', 'newborn'],
    '🏠 INTERIOR DESIGN / APARTMENT DECOR': ['interior', 'decor', 'apartment', 'room', 'home design'],
    '💰 MONEY / FINANCIAL INDEPENDENCE': ['money', 'budget', 'invest', 'financial', 'independence', 'saving'],
    '✈️ SOLO FEMALE TRAVEL': ['solo travel', 'female travel', 'trip', 'destination', 'abroad'],
    '📖 BOOKTOK / READING': ['book', 'read', 'novel', 'booktok', 'literature'],
    '🌙 GLOW UP / ERA SHIFT': ['glow up', 'era', 'transformation', 'new chapter', 'change'],
}


# Tier 1: always bleep in audio + mask in subtitles/titles
_DEMONET_TIER1 = {
    # Hard profanity
    'fuck',
    'fucking',
    'fucked',
    'fucker',
    'fucks',
    'motherfucker',
    'motherfucking',
    'shit',
    'shitting',
    'bullshit',
    'bullshitting',
    'cunt',
    'cunts',
    'bitch',
    'bitches',
    'bitching',
    'asshole',
    'assholes',
    'ass',
    'asses',
    'dick',
    'dicks',
    'cock',
    'cocks',
    'pussy',
    'pussies',
    'whore',
    'whores',
    'slut',
    'sluts',
    'skank',
    'nigger',
    'nigga',
    'niggas',
    'faggot',
    'fag',
    'dyke',
    'spic',
    'kike',
    'chink',
    # Sexual
    'sex',
    'sexual',
    'porn',
    'pornography',
    'pornographic',
    'nude',
    'nudity',
    'naked',
    'masturbate',
    'masturbation',
    'orgasm',
    'erection',
    'penis',
    'vagina',
    'blowjob',
    'handjob',
    'anal',
    'fetish',
    'rape',
    'raping',
    'raped',
    # Hard drugs
    'cocaine',
    'heroin',
    'methamphetamine',
    'meth',
    'fentanyl',
    'crack',
    'ecstasy',
    'mdma',
    'lsd',
    'acid',
    'ketamine',
    'opioid',
    'opioids',
    # Self-harm / suicide
    'suicide',
    'suicidal',
    'self-harm',
    'selfharm',
    'cutting myself',
    'kill myself',
    'killing myself',
    'hang myself',
    # Terrorism
    'isis',
    'al-qaeda',
    'al qaeda',
    'jihad',
    'jihadist',
    'terrorist bombing',
}


# Tier 3: never allowed in clip titles/filenames (metadata only, not audio)
_DEMONET_TIER3_TITLE = {
    'conspiracy',
    'hoax',
    'misleading',
    'misinformation',
    'disinformation',
    'fake news',
    'clickbait',
    'scam',
    'fraud',
    'fraudulent',
    'piracy',
    'gore',
    'graphic',
    'disturbing',
    'shocking',
    'suicide',
    'self-harm',
    'overdose',
}


# ---------------------------------------------------------------------------
# Clipfarm Pipeline Stages — defines the dependency graph and parallelism.
# Each stage is a list of agent IDs. Stages run sequentially; agents WITHIN
# a stage run in parallel threads (each gets its own crew.kickoff() call).
# ---------------------------------------------------------------------------
_CLIPFARM_STAGES = [
    {
        'name': 'Stage 1 — Discovery',
        'parallel': False,
        'agents': ['CLIPFARM-Source-Scanner-Agent'],
        'task': (
            'Scan trending YouTube content via RSS for known channels and use the '
            'YouTube Data API to discover new channels. Skip Reddit (API pending). '
            'Return a list of candidate video URLs with metadata.'
        ),
    },
    {
        'name': 'Stage 2 — Analysis (parallel)',
        'parallel': True,
        'agents': [
            'CLIPFARM-Metrics-Agent',
            'CLIPFARM-Trend-Detector-Agent',
            'CLIPFARM-Research-Agent',
            'CLIPFARM-Overview-Agent',
            'CLIPFARM-Compliance-Agent',
        ],
        'task': (
            'Analyse the candidate videos from Stage 1. Calculate engagement metrics, '
            'detect trending signals, research topics, build channel overviews, and '
            'check compliance. Work independently — your results feed Stage 3.'
        ),
    },
    {
        'name': 'Stage 3 — Selection & Deduplication',
        'parallel': True,
        'agents': ['CLIPFARM-Selection-Agent', 'CLIPFARM-Deduplication-Agent'],
        'task': (
            'Using Stage 2 analysis, score and rank all candidates. Remove duplicates '
            'and already-published content. Output the final approved clip list.'
        ),
    },
    {
        'name': 'Stage 4a — Fetch (parallel)',
        'parallel': True,
        'agents': [
            'CLIPFARM-Transcript-Fetch-Agent',
            'CLIPFARM-Video-Fetch-Agent',
            'CLIPFARM-Rights-Check-Agent',
            'CLIPFARM-Content-Indexer-Agent',
        ],
        'task': (
            'Fetch transcripts, download video, verify rights, and index content for the approved clips from Stage 3.'
        ),
    },
    {
        'name': 'Stage 4b — Processing (parallel)',
        'parallel': True,
        'agents': [
            'CLIPFARM-Moment-Detection-Agent',
            'CLIPFARM-Variant-Generator-Agent',
            'CLIPFARM-Hook-Generator-Agent',
            'CLIPFARM-Commentary-Agent',
            'CLIPFARM-Subtitle-Generator-Agent',
            'CLIPFARM-Sound-Effects-Agent',
            'CLIPFARM-Thumbnail-Agent',
            'CLIPFARM-Library-Agent',
        ],
        'task': (
            'Process fetched clips: detect highlight moments, generate variants, '
            'write hooks, add commentary, generate subtitles, add SFX, create thumbnails, '
            'and register assets to the library.'
        ),
    },
    {
        'name': 'Stage 5 — QC & Adaptation',
        'parallel': True,
        'agents': [
            'CLIPFARM-QC-Agent',
            'CLIPFARM-Error-Detection-Agent',
            'CLIPFARM-Platform-Adapter-Agent',
        ],
        'task': (
            'Quality-check all processed clips. Detect any encoding or sync errors. '
            'Adapt each clip to platform spec (aspect ratio, bitrate, duration limits).'
        ),
    },
    {
        'name': 'Stage 6 — Publish',
        'parallel': True,
        'agents': [
            'CLIPFARM-Assignment-Agent',
            'YouTube-Scheduling-Agent',
            'CLIPFARM-Upload-Schedule-Agent',
            'CLIPFARM-Upload-Agent',
            'CLIPFARM-Air-Time-Agent',
        ],
        'task': (
            'Assign final clips to channels. Schedule uploads at optimal air times. Upload to all configured platforms.'
        ),
    },
]


_CONTACT_SHEET_STATE_FMT = 'contact_sheet_{char_id}.json'


# ── Character generation state persistence ────────────────────────────────────
# Mirrors how story pipelines persist to data/runtime/pipeline_*_state.json so
# the metrics dashboard can aggregate timings across server restarts. Each
# character-gen run is written to data/runtime/char_gen_<char_id>.json after
# every stage transition. Write failures are non-fatal (logged but ignored).
_CHAR_STATE_FILENAME_FMT = 'char_gen_{char_id}.json'


# Known model VRAM requirements in GB (approximate Q4_K_M footprint)
_MODEL_VRAM_GB = {
    'mistral:7b': 5,
    'llama3': 5,
    'llama3:8b': 5,
    'llama3:70b': 41,
    'qwen3.6:35b-a3b': 22,  # MoE Q4 — 3B active but full weights resident
    'gpt-oss:20b': 14,  # MXFP4
    'qwen3.5:9b': 7,
    'qwen2.5-coder:32b': 21,
    'deepseek-coder:33b': 20,
}


_LARGE_MODEL_THRESHOLD_GB = 20  # models above this use _large_llm_semaphore


_PUBLISH_STAGE_NAME = 'Stage 6 — Publish'


_UPLOAD_AGENTS = {
    'CLIPFARM-Upload-Agent',
    'CLIPFARM-Upload-Schedule-Agent',
    'YouTube-Scheduling-Agent',
    'CLIPFARM-Air-Time-Agent',
    'CLIPFARM-Assignment-Agent',
}


# ── Reusable per-character FLUX preview render (Stage 1d body) ─────────────────
_PREVIEW_LORA_WAIT_S = int(os.environ.get('ZYG_PREVIEW_LORA_WAIT_S', '60'))


_CHAR_DRIFT_MIN = float(os.environ.get('ZYG_CHAR_DRIFT_MIN', '0.60'))


_CHAR_DRIFT_ANIMATED = float(os.environ.get('ZYG_CHAR_DRIFT_ANIMATED', '0.45'))


_ANIMATED_USE_FLUX = os.environ.get('ZYG_ANIMATED_USE_FLUX', '1').strip().lower() in (
    '1',
    'true',
    'yes',
    'on',
)


# Eva path: FLUX + photorealistic, single-pass preview by default.
_PREVIEW_SEED_CANDIDATES = max(1, int(os.environ.get('ZYG_PREVIEW_SEED_CANDIDATES', '1')))


_PREVIEW_FACE_SEED_CANDIDATES = max(1, int(os.environ.get('ZYG_PREVIEW_FACE_SEED_CANDIDATES', '1')))


_CHAR_DEFAULT_MODEL_FAMILY = os.environ.get('ZYG_CHAR_DEFAULT_MODEL_FAMILY', 'flux').strip().lower()


_CHAR_PHOTOREAL_HYBRID_PREVIEW = os.environ.get(
    'ZYG_CHAR_PHOTOREAL_HYBRID_PREVIEW',
    '1',
).strip().lower() not in ('0', 'false', 'no')


_CHAR_DUAL_LORA_PHOTOREAL = os.environ.get(
    # Default OFF since 2026-07-18: the SDXL twin roughly doubled training GPU
    # per character while its LoRA trained on SDXL base but rendered on
    # Juggernaut (base mismatch). FLUX is the primary identity path; set
    # ZYG_CHAR_DUAL_LORA_PHOTOREAL=1 to train the SDXL twin again.
    'ZYG_CHAR_DUAL_LORA_PHOTOREAL',
    '0',
).strip().lower() not in ('0', 'false', 'no')


_PHOTOREAL_CLIP_POS = (
    'professional DSLR photograph, natural unretouched skin, realistic portrait, visible pores, film grain, real person'
)


_PHOTOREAL_CLIP_NEG = 'anime illustration, cel shaded cartoon, 3d game character, mannequin'


# ── second batch: the constants the stage/TTS/VRAM/video pipelines read ────────
# Same move as the block above, for the seven pipeline modules converted in the
# second pass. Verbatim from crewai_web_gui.py except where a value was a
# machine-specific literal under the legacy default home or a dashboard-package
# path — those are expressed through zyg_workflows.paths so the base library
# carries no absolute path.

# Stage 6 Ken Burns: stagger between encode threads (single source of truth).
_KB_THREAD_STAGGER_S = 0.25


# Where the safety-threshold overrides are read from. In the GUI this was a file
# next to crewai_web_gui.py; a base-library module must not reach into the
# dashboard package, so it is the crews root by default and
# ZYG_SAFETY_THRESHOLDS_PATH overrides. The loader degrades when it is absent.
_SAFETY_THRESHOLDS_PATH = os.environ.get('ZYG_SAFETY_THRESHOLDS_PATH', '').strip() or str(
    paths.ZYG_CREWS_ROOT / 'safety_thresholds.json'
)


# The Ollama endpoint. The GUI bound this inside the crewai import try/except as
# a literal; paths.ZYG_OLLAMA_URL is the same endpoint, overridable.
_OLLAMA_BASE_URL = paths.ZYG_OLLAMA_URL


# Fixed outro CTA line spoken at the end of every clip
_NARRATOR_OUTRO = "Comment down below what you think about this video, and don't forget to like and subscribe."

# Tier 2: bleep in audio + mask in subtitles, but NOT removed from titles
_DEMONET_TIER2 = {
    'kill',
    'killing',
    'killed',
    'murder',
    'murdering',
    'murdered',
    'blood',
    'bloody',
    'massacre',
    'slaughter',
    'execution',
    'executed',
    'assault',
    'assaulted',
    'stabbed',
    'stab',
    'shoot',
    'shooting',
    'shot',
    'overdose',
    'overdosed',
    'drugs',
    'marijuana',
    'weed',
    'drunk',
    'intoxicated',
    'drunk driving',
    'alcohol abuse',
    'substance abuse',
    'hate',
    'racist',
    'racism',
    'bigot',
    'bigotry',
    'discrimination',
    'harassment',
    'harassing',
    'stalking',
    'bully',
    'bullying',
    'abuse',
    'abusive',
    'abused',
    'molest',
    'molestation',
    'bomb',
    'bombing',
    'bombed',
    'explosive',
    'weapon',
    'weapons',
    'extremist',
    'extremism',
    'radicalized',
    'terror',
    'terrorist',
}

# Synonym replacement table for titles (Tier 1 + Tier 3 hits in titles)
_TITLE_SYNONYMS = {
    'kill': 'end',
    'killing': 'incident',
    'killed': 'lost',
    'murder': 'incident',
    'murdering': 'incident',
    'murdered': 'lost',
    'blood': 'chaos',
    'bloody': 'intense',
    'massacre': 'incident',
    'slaughter': 'defeat',
    'execution': 'removal',
    'executed': 'removed',
    'assault': 'attack',
    'stabbed': 'attacked',
    'shoot': 'confront',
    'shooting': 'confrontation',
    'shot': 'hit',
    'bomb': 'blast',
    'bombing': 'blast',
    'explosive': 'device',
    'weapon': 'tool',
    'weapons': 'tools',
    'terrorist': 'suspect',
    'terror': 'threat',
    'extremist': 'radical',
    'drugs': 'substances',
    'marijuana': 'substance',
    'cocaine': 'substance',
    'heroin': 'substance',
    'meth': 'substance',
    'overdose': 'incident',
    'drunk': 'reckless',
    'alcohol': 'drink',
    'suicide': 'tragedy',
    'suicidal': 'desperate',
    'rape': 'assault',
    'raping': 'assaulting',
    'raped': 'attacked',
    'sex': 'situation',
    'sexual': 'personal',
    'porn': 'content',
    'nude': 'revealing',
    'naked': 'exposed',
    'racist': 'offensive',
    'racism': 'controversy',
    'hate': 'anger',
    'conspiracy': 'theory',
    'hoax': 'claim',
    'misleading': 'questionable',
    'misinformation': 'claims',
    'fake news': 'claims',
    'clickbait': 'content',
    'scam': 'scheme',
    'fraud': 'scheme',
    'gore': 'graphic content',
    'disturbing': 'intense',
    'shocking': 'surprising',
    'fuck': 'mess',
    'fucking': 'seriously',
    'shit': 'mess',
    'bullshit': 'nonsense',
    'bitch': 'person',
    'bitches': 'people',
    'ass': 'person',
    'asshole': 'jerk',
    'dick': 'person',
    'cunt': 'person',
    'whore': 'person',
    'slut': 'person',
    'nigger': 'person',
    'nigga': 'person',
    'faggot': 'person',
}

# Sensitive topic keywords — trigger REVIEW REQUIRED warning in logs only
_SENSITIVE_TOPIC_KEYWORDS = {
    'POLITICS': [
        'election',
        'election fraud',
        'political violence',
        'coup',
        'january 6',
        'antifa',
        'proud boys',
        'qanon',
        'deep state',
    ],
    'RELIGION': ['blasphemy', 'cult', 'heresy', 'infidel', 'kafir', 'crusade'],
    'TRAGEDY': ['natural disaster', 'mass shooting', 'school shooting', 'genocide', 'ethnic cleansing', 'war crime'],
    'SELF-HARM': ['cutting', 'self harm', 'eating disorder', 'anorexia', 'bulimia'],
}

# ── documentary-cinematic style LoRA ─────────────────────────────────────────
# The path was wrong: checkpoint-6000/ does not exist. SimpleTuner left the final
# weights at the ROOT of lora-weights/, so every scholarly run since has logged
# "lora_dir LoRA file not found" and rendered with no style LoRA at all.
#
# Fixing the path alone would be a licence regression, so it is OFF by default.
# The LoRA's own README declares base_model "black-forest-labs/FLUX.1-dev",
# license "other" — non-commercial. Renders run on FLUX.1-schnell (Apache-2.0)
# specifically so published episodes stay commercially clean, and a LoRA is
# charged with its BASE model's licence. Loading this one puts a non-commercial
# derivative into monetised output. Opt in only for internal, non-published work:
#   ZYG_FLUX_STYLE_LORA=1
# The literal was 'documentary-cinematic/lora-weights' under the legacy default
# lora-outputs directory; paths.ZYG_LORA_OUTPUTS resolves to the same place.
_FLUX_LORA_DIR = str(paths.ZYG_LORA_OUTPUTS / 'documentary-cinematic' / 'lora-weights')
_FLUX_LORA_ENABLED = os.environ.get('ZYG_FLUX_STYLE_LORA', '0').strip().lower() in ('1', 'true', 'yes', 'on')
_FLUX_LORA_PATH = _FLUX_LORA_DIR if _FLUX_LORA_ENABLED else None
# Trained lora_alpha=64 / lora_rank=128 → effective strength 0.5. The export
# carries no alpha keys, so a loader assumes alpha=rank and the nominal scale IS
# the effective one — 0.5 reproduces training, the previous 0.75 was 1.5x it.
_FLUX_LORA_SCALE = 0.5

# ── Visual Style LoRA config ─────────────────────────────────────────────────
# Each style maps to a LoRA file + scale + prompt prefix/suffix injected into FLUX.
# 'lora' = filename in _STYLE_LORA_DIR, or None for prompt-only styles.
#
# 2026-08-27 — EVERY FILE IN _STYLE_LORA_DIR WAS DELETED ON LICENCE GROUNDS.
# The 'lora' keys below are deliberately LEFT IN PLACE: pipeline_video guards the
# load with os.path.exists() and degrades to the prefix/suffix/claude_hint text,
# which is where most of each style's direction already lived. Keeping the key
# documents the slot a cleared replacement plugs into. Expect one
# "Style LoRA file not found" WARNING per render until one is wired.
#
# What was removed, and why — identified by exact filename + byte-size match
# against the source repo, not by assumption:
#   anime / art / disney / mjv6 / realism / scenery
#       -> XLabs-AI/flux-lora-collection, license_name = flux-1-dev-non-commercial-license
#   3d_render_lora  -> goofyai/3D_Render_for_flux; repo tags itself apache-2.0 but the
#       file's own header says modelspec.architecture = flux-1-dev/lora. An uploader's
#       tag does not override the base model's terms, so it was treated as NC.
#   filmic_lora     -> header ss_output_name = flux_dev_flmft5, FLUX tensor layout.
#   style_lora      -> header modelspec.architecture = flux-1-dev/lora (the amateurphoto
#       LoRA staged under a second name).
#   style_arcane    -> trained on sd_xl_base_0.9_half. SDXL 0.9 is the SDXL RESEARCH
#       licence, NOT the OpenRAIL++-M of SDXL 1.0: it grants use "solely for your
#       non-commercial research purposes" and separately bars using the Software
#       "or any data produced by the Software" for "any commercial or production
#       purposes" — an OUTPUT restriction, which is why it mattered more than the rest.
#
# Verified Apache-2.0/MIT replacements on the Qwen-Image base (licence read from the
# HF API, not recalled). All are LoRAs for Qwen, so they need the Qwen render path,
# not the retired FLUX one:
#   realism   -> flymy-ai/qwen-image-realism-lora            (apache-2.0)
#   anime     -> prithivMLmods/Qwen-Image-Anime-LoRA         (apache-2.0)
#                alfredplpl/qwen-image-modern-anime-lora     (apache-2.0)
#                autoweeb/Qwen-Image-Edit-2509-Photo-to-Anime (mit)
#   disney    -> furaidosu/masha2d-cartoon-qwen-image-lora   (apache-2.0)
#   art/scenery/filmic -> dx8152/Qwen-Image-Edit-2511-Style-Transfer (apache-2.0)
#                         strangerzonehf/Qwen-Image-Edit-LoRA-Collection (apache-2.0)
#   NO cleanly-licensed ARCANE LoRA was found. Every candidate was either a FLUX-dev
#   derivative wearing an openrail++ tag (the 3d_render trap again) or carried no
#   licence at all. Arcane needs either a Qwen style-transfer reference image you own,
#   or a LoRA trained in-house on licensed material.
# The literal was 'style-loras' under the legacy default ai-models directory;
# paths.ZYG_MODELS_ROOT resolves to the same place.
_STYLE_LORA_DIR = str(paths.ZYG_MODELS_ROOT / 'style-loras')
_STYLE_LORA_CONFIG: dict = {
    'cinematic': {
        'lora': None,
        'scale': 0.0,
        # documentary-cinematic LoRA — see _FLUX_LORA_PATH above. None unless
        # ZYG_FLUX_STYLE_LORA=1, because it is FLUX.1-dev-derived (non-commercial)
        # and this channel is monetised. The export is already in diffusers
        # convention (lora_A/lora_B), so the loader's SimpleTuner key
        # normalization is a harmless no-op for it.
        'lora_dir': _FLUX_LORA_PATH,
        'lora_dir_scale': _FLUX_LORA_SCALE,
        'prefix': 'cinematic photograph',
        'suffix': 'photorealistic, dramatic lighting, 16:9 composition, film grain, anamorphic lens',
        'claude_hint': 'cinematic, photorealistic, dramatic lighting, film grain',
    },
    'anime': {
        'lora': 'anime_lora.safetensors',
        'scale': 1.0,
        'prefix': 'anime style illustration',
        'suffix': 'cel shading, vibrant colors, studio quality, clean lines, expressive',
        'claude_hint': 'anime style, cel shading, vibrant colors, Japanese animation',
    },
    'disney': {
        'lora': 'disney_lora.safetensors',
        'scale': 1.0,
        'prefix': '2D cartoon Disney animation style',
        'suffix': 'expressive characters, clean bold colors, animated, classic cartoon, smooth',
        'claude_hint': 'Disney 2D animation style, cartoon, expressive characters, bold colors',
    },
    'art': {
        'lora': 'art_lora.safetensors',
        'scale': 0.85,
        'prefix': 'stylized digital art illustration',
        'suffix': 'concept art, detailed, vibrant colors, artistic rendering, professional',
        'claude_hint': 'stylized digital art, concept art, illustration, artistic',
    },
    'realism': {
        'lora': 'realism_lora.safetensors',
        'scale': 1.0,
        'prefix': 'hyperrealistic photograph',
        'suffix': 'photorealistic, ultra-detailed, 8K resolution, sharp focus, professional camera',
        'claude_hint': 'photorealistic, hyperrealistic, ultra-detailed, 8K, sharp focus',
    },
    'scenery': {
        'lora': 'scenery_lora.safetensors',
        'scale': 1.0,
        'prefix': 'epic cinematic landscape',
        'suffix': 'beautiful environment, dramatic lighting, vast scenery, golden hour, sweeping vistas',
        'claude_hint': 'cinematic landscape, beautiful scenery, dramatic environment, sweeping vistas',
    },
    '3d_render': {
        'lora': '3d_render_lora.safetensors',
        'scale': 1.0,
        'prefix': '3D CGI render',
        'suffix': 'smooth shading, Pixar style, studio lighting, animated movie quality, vibrant',
        'claude_hint': '3D render, CGI, Pixar style, smooth shading, studio lighting',
    },
    'filmic': {
        'lora': 'filmic_lora.safetensors',
        'scale': 0.75,
        'prefix': 'filmic analog photography',
        'suffix': 'vintage 35mm film, Kodak grain, organic texture, warm tones, cinematic',
        'claude_hint': 'filmic photography, vintage 35mm film, Kodak grain, analog, warm tones',
    },
    'mjv6': {
        'lora': 'mjv6_lora.safetensors',
        'scale': 1.0,
        'prefix': 'highly detailed artistic scene',
        'suffix': 'rich detail, artistic composition, vibrant, professional photography, stunning',
        'claude_hint': 'highly detailed, artistic composition, vibrant, rich detail, stunning visuals',
    },
    'manga': {
        'lora': None,
        'scale': 0.0,
        'prefix': 'manga comic panel illustration',
        'suffix': 'ink linework, screentone shading, bold composition, Japanese manga style, high contrast, panel layout, no photorealism',
        'claude_hint': 'manga comic panel, ink lines, screentone, bold composition, illustrated not photographic',
    },
}

# Book-intro assets. The GUI spelled these ``os.path.dirname(_RUNTIME_DIR)``,
# i.e. the data root the runtime directory sits in; that is kept.
_BOOK_PNG = os.path.join(os.path.dirname(_RUNTIME_DIR), 'assets', 'book_open.png')
_BOOK_FONT = os.path.join(os.path.dirname(_RUNTIME_DIR), 'assets', 'fonts', 'IMFellEnglish-Italic.ttf')


# Smoke-test override: set to a positive int to cap FLUX image count in the
# scholarly pipeline. The smoke test script sets this to 3 to avoid generating
# 79 images. 0 = production (no cap). pipeline_scholarly._smoke_cap() reads this
# attribute off THIS module at call time, so setting it here takes effect.
_SCHOLARLY_SMOKE_MAX_IMAGES: int = 0
