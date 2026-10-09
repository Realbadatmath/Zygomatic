# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
clipfarm_visual_framework.py

10-Part Visual Framework for the CLIPFARM Scholarly Pipeline.

Provides
--------
DISCIPLINE_BASELINES      : per-topic default 10-block visual templates (the Floor)
BEAT_TYPE_OVERRIDES       : per-narrative-beat surgical block overrides (the Ceiling)
NarrativeBeatClassifier   : lexical beat detection from transcript text + audio energy
VisualFrameworkResolver   : combines baseline + beat override into a final resolved dict
build_sd_prompt()         : converts a resolved dict into SD/XL positive + negative prompts

Architecture
------------
1. Topic loads a DISCIPLINE_BASELINE (default aesthetic, visual style, locked Negatives).
2. NarrativeBeatClassifier reads the transcript and audio energy signal.
3. If a dominant beat is detected above the confidence threshold, BEAT_TYPE_OVERRIDES
   surgically replaces only the tone-expressive blocks (mood, lighting, camera).
4. Subject Definition, Visual Style, and Negative Constraints are NEVER overridden —
   they are the identity of the clip within its discipline.
5. build_sd_prompt() converts the final block dict into SD/XL prompt strings.

No external dependencies — pure Python standard library.
"""

from __future__ import annotations

import re


# ─────────────────────────────────────────────────────────────────────────────
# 1. DISCIPLINE BASELINES
#    One default 10-part framework per scholarly topic.
#    These are the Floor — the system falls back here when no strong beat fires.
#    Visual Style and Negative Constraints are identity blocks — never overridden.
# ─────────────────────────────────────────────────────────────────────────────

DISCIPLINE_BASELINES: dict[str, dict] = {
    'crime': {
        'subject_definition': 'criminal subject, urban or institutional setting, high-stakes tension',
        'action_and_context': 'perpetrator or investigator in motion; justice or wrongdoing in play',
        'environment_and_setting': 'urban streets, courtroom, prison, or crime scene; night or harsh fluorescent light',
        'mood_and_story': 'tense, morally ambiguous, investigative urgency',
        'visual_style': 'gritty photojournalism, David Fincher color palette, crime documentary realism',
        'lighting_and_color': 'harsh practical lighting, cold blue-grey grade, deep shadows, high contrast',
        'camera_and_composition': '35mm lens, eye-level or slightly low angle, tight framing, shallow depth of field',
        'detail_and_texture': 'worn concrete, institutional surfaces, weathered clothing, visible stress in faces',
        'quality_and_realism': 'high fidelity, sharp, raw documentary feel, DSLR quality',
        'negative_constraints': 'no cartoon violence, no sensationalism, no glamorization, no comic-book aesthetics, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
    'war': {
        'subject_definition': 'soldier or civilian, military gear, historical battlefield or command center',
        'action_and_context': 'combatant or strategist amid active conflict; survival or tactical decision',
        'environment_and_setting': 'battlefield, trench, war-torn city, or command tent; dusk, smoke, mud',
        'mood_and_story': 'solemn, brutal, historically weighty, human cost of conflict',
        'visual_style': 'war documentary realism, Saving Private Ryan desaturation, field photography',
        'lighting_and_color': 'overcast natural light, desaturated warm-grey grade, smoke diffusion, limited color range',
        'camera_and_composition': '50mm lens, eye-level handheld, medium-tight framing, slight motion blur',
        'detail_and_texture': 'mud-caked boots, tattered uniforms, smoke particles, shell casings, weathered metal',
        'quality_and_realism': 'cinematic high fidelity, sharp foreground, atmospheric soft background, filmic grain',
        'negative_constraints': 'no glorification, no video-game aesthetics, no clean pristine uniforms, no cartoon explosions, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
    'history': {
        'subject_definition': 'historical figure or artifact, period-accurate costume, monumental environment',
        'action_and_context': 'historical actor at a defining moment; the weight of an era visible in their posture',
        'environment_and_setting': 'ancient ruins, period architecture, or natural landscape; golden hour or overcast sky',
        'mood_and_story': 'solemn, reverential, authoritative; a window into a vanished world',
        'visual_style': 'archival documentary aesthetic, Ken Burns warmth, historical painting influence, NatGeo photography',
        'lighting_and_color': 'warm desaturated grade, aged film grain, golden-hour side light, soft vignette',
        'camera_and_composition': '50mm or 85mm lens, static or slow pan, wide establishing then tighter, symmetrical framing',
        'detail_and_texture': 'stone texture, aged fabric, dust, weathered surfaces, natural patina',
        'quality_and_realism': 'high fidelity, sharp, documentary cinematic polish, natural color science',
        'negative_constraints': 'no anachronistic elements, no stock-photo staging, no modern clothing, no plastic surfaces, no watermark, no text overlay, no extra limbs, no distorted anatomy',
    },
    'technology': {
        'subject_definition': 'engineer, researcher, or technological artifact; clean and precise visual',
        'action_and_context': 'innovation in progress; a system being built, tested, or demonstrated',
        'environment_and_setting': 'lab, server room, factory floor, or field test site; clean artificial light',
        'mood_and_story': 'precise, forward-looking, intellectually awe-inspiring',
        'visual_style': 'tech documentary realism, Wired Magazine editorial, clean minimalism',
        'lighting_and_color': 'cool white key light, blue-teal accent, clean neutral grade, minimal shadows',
        'camera_and_composition': '35mm lens, eye-level, clean symmetrical framing, moderate depth of field',
        'detail_and_texture': 'circuit traces, brushed metal, matte plastic, LED glow, precise stitching',
        'quality_and_realism': 'razor sharp, high fidelity, crisp textures, editorial quality',
        'negative_constraints': 'no sci-fi fantasy elements, no glowing holograms, no unrealistic tech, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
    'psychology': {
        'subject_definition': 'human subject in psychological context; emotional state as visual anchor',
        'action_and_context': 'person confronting a mental state or behavioral pattern; internal experience made visible',
        'environment_and_setting': 'clinical interior, domestic space, or minimal abstract background; neutral light',
        'mood_and_story': 'introspective, psychologically tense, quietly vulnerable',
        'visual_style': 'psychological portrait photography, muted editorial realism, clinical documentary',
        'lighting_and_color': 'soft diffused key light, muted colour grade, subtle cool or warm tint by emotional valence',
        'camera_and_composition': '85mm portrait lens, eye-level, close framing, shallow depth of field, direct gaze',
        'detail_and_texture': 'skin texture, fabric folds, environmental props suggesting mental state',
        'quality_and_realism': 'high fidelity, sharp on eyes, soft background, editorial portrait quality',
        'negative_constraints': 'no caricature of mental illness, no sensationalism, no sterile stock photo feel, no watermark, no text overlay, no distorted anatomy',
    },
    'philosophy': {
        'subject_definition': 'thinker or symbolic abstract subject; contemplative posture or symbolic object',
        'action_and_context': 'a mind engaging with a fundamental question; thought as visible weight',
        'environment_and_setting': 'study, ancient library, open landscape, or abstract space; quiet controlled light',
        'mood_and_story': 'contemplative, weighty, intellectually vast',
        'visual_style': 'classical portrait painting influence, Rembrandt chiaroscuro, philosophical documentary',
        'lighting_and_color': 'single warm source, deep shadows, Rembrandt triangle, aged warm grade',
        'camera_and_composition': '85mm lens, three-quarter angle, medium framing, chiaroscuro depth',
        'detail_and_texture': 'aged paper, leather-bound books, stone sculpture texture, candlelight warmth',
        'quality_and_realism': 'high fidelity, fine detail, painterly quality while photorealistic',
        'negative_constraints': 'no modern design elements, no minimalist flat style, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
    'economics': {
        'subject_definition': 'market environment, economic actor, or data visualization made tangible',
        'action_and_context': 'economic forces in motion; transaction, production, or systemic shift',
        'environment_and_setting': 'trading floor, factory, market, boardroom, or commercial district; day',
        'mood_and_story': 'analytical, high-stakes, systemically significant',
        'visual_style': 'financial journalism photography, Bloomberg editorial, economic documentary',
        'lighting_and_color': 'cool natural or office light, clean neutral grade, minimal color cast',
        'camera_and_composition': '35mm or 50mm lens, wide establishing or medium detail shot, level framing',
        'detail_and_texture': 'printed documents, currency texture, industrial materials, financial instruments',
        'quality_and_realism': 'sharp, high fidelity, journalistic documentary quality',
        'negative_constraints': 'no cartoon graphs, no abstract digital art, no watermark, no text overlay, no distorted anatomy',
    },
    'politics': {
        'subject_definition': 'political figure, crowd, or institutional symbol; power and representation',
        'action_and_context': 'political actor at a defining moment of governance or conflict',
        'environment_and_setting': 'parliament, protest venue, election site, or diplomatic setting; formal light',
        'mood_and_story': 'high-stakes, historically significant, contested and consequential',
        'visual_style': 'political photojournalism, Reuters editorial, documentary portrait',
        'lighting_and_color': 'natural press photography light, neutral grade, slight desaturation',
        'camera_and_composition': '50mm or 85mm lens, eye-level, medium framing, rule-of-thirds placement',
        'detail_and_texture': 'podium texture, crowd density, institutional architecture, formal attire',
        'quality_and_realism': 'sharp, high fidelity, press photography quality',
        'negative_constraints': 'no propaganda aesthetic, no caricature, no staged stock photo feel, no watermark, no text overlay, no distorted anatomy',
    },
    'environment': {
        'subject_definition': 'natural environment or ecological subject; landscape as protagonist',
        'action_and_context': 'ecological process in motion; nature asserting or losing its force',
        'environment_and_setting': 'wilderness, coastline, deforested land, or urban-natural interface; dawn or storm light',
        'mood_and_story': 'awe-inspiring, urgently fragile, ecologically significant',
        'visual_style': 'nature documentary photography, NatGeo landscape, Ansel Adams tonality',
        'lighting_and_color': 'natural golden-hour or stormy light, high dynamic range, rich nature palette',
        'camera_and_composition': '24mm wide lens, low angle, sweeping landscape framing, deep depth of field',
        'detail_and_texture': 'bark texture, water surface, soil, animal fur or feather detail',
        'quality_and_realism': 'high dynamic range, sharp, vivid natural colors, large-format quality',
        'negative_constraints': 'no generic stock nature photo, no cartoon animals, no artificial environments, no watermark, no text overlay',
    },
    'medicine': {
        'subject_definition': 'medical subject, patient, or scientific instrument; clinical precision',
        'action_and_context': 'medical intervention or discovery; life and its biological mechanisms',
        'environment_and_setting': 'hospital, lab, surgical theater, or research facility; clinical white light',
        'mood_and_story': 'precise, life-affirming, scientifically awe-inspiring',
        'visual_style': 'medical documentary photography, Lancet editorial realism, clinical precision',
        'lighting_and_color': 'clean white key light, neutral grade, slight cool tint, controlled shadows',
        'camera_and_composition': '100mm macro or 50mm lens, eye-level, close detail or medium full-body',
        'detail_and_texture': 'sterile surfaces, medical equipment texture, skin detail, tissue realism',
        'quality_and_realism': 'ultra-sharp, high fidelity, medical photography precision',
        'negative_constraints': 'no graphic gore, no horror aesthetic, no unrealistic biology, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
    'religion': {
        'subject_definition': 'religious subject, ritual participant, or sacred object; spiritual atmosphere',
        'action_and_context': 'spiritual act or theological moment; the sacred made visually present',
        'environment_and_setting': 'temple, church, mosque, or sacred outdoor site; low warm light or dawn',
        'mood_and_story': 'reverent, spiritually weighty, cross-culturally respectful',
        'visual_style': 'sacred art photography, documentary reverence, contemplative portrait',
        'lighting_and_color': 'warm candle or sacred directional light, golden grade, soft shadows, luminous atmosphere',
        'camera_and_composition': '50mm or 85mm lens, three-quarter or frontal, medium framing, peaceful composition',
        'detail_and_texture': 'aged stone, textile ritual objects, candlelight warmth, incense smoke, sacred iconography',
        'quality_and_realism': 'high fidelity, warm and luminous, reverent quality',
        'negative_constraints': 'no mockery, no sensationalism, no cultural disrespect, no watermark, no text overlay, no distorted anatomy',
    },
    'space': {
        'subject_definition': 'astronaut, spacecraft, or cosmic phenomenon; human scale against the infinite',
        'action_and_context': 'exploration or discovery in the cosmos; the frontier made tangible',
        'environment_and_setting': 'space station, lunar surface, interstellar void, or launch pad; harsh vacuum light',
        'mood_and_story': 'awe-inspiring, vast, humanly significant against infinite scale',
        'visual_style': 'NASA documentary photography, Kubrick 2001 precision, space science realism',
        'lighting_and_color': 'hard single-source sunlight, pure black vacuum, high contrast, no atmosphere diffusion',
        'camera_and_composition': '24mm wide or 50mm, dramatic low angle, subject framed against stars, deep depth of field',
        'detail_and_texture': 'spacesuit material, spacecraft surface, cosmic dust, star field depth',
        'quality_and_realism': 'ultra-sharp, high fidelity, scientifically accurate lighting',
        'negative_constraints': 'no science fiction fantasy, no colorful nebula clichés, no cartoon rockets, no watermark, no text overlay, no distorted anatomy',
    },
    'architecture': {
        'subject_definition': 'architectural structure or urban space; form and human scale as visual anchor',
        'action_and_context': 'structure in its context; human inhabitation or historical presence',
        'environment_and_setting': 'urban street, historical site, or landscape setting; golden hour or overcast',
        'mood_and_story': 'aesthetically significant, historically resonant, spatially commanding',
        'visual_style': 'architectural photography, Julius Shulman precision, urban documentary realism',
        'lighting_and_color': 'golden-hour natural light, warm-neutral grade, clean shadows, high material detail',
        'camera_and_composition': '24mm wide or tilt-shift lens, symmetrical or geometric framing, converging lines',
        'detail_and_texture': 'stone, concrete, glass, steel surface texture, material aging and patina',
        'quality_and_realism': 'large-format quality, sharp geometry, high fidelity',
        'negative_constraints': 'no CGI render feel, no fisheye distortion, no watermark, no text overlay, no distorted geometry',
    },
    'art': {
        'subject_definition': 'artist, artwork, or creative act; aesthetic intention as visual subject',
        'action_and_context': 'creation in progress or work in contemplation; the artistic act made visible',
        'environment_and_setting': 'studio, gallery, or public space; natural or dramatic studio light',
        'mood_and_story': 'aesthetically charged, emotionally resonant, culturally significant',
        'visual_style': 'art documentary photography, editorial portrait, gallery-quality realism',
        'lighting_and_color': 'dramatic studio or natural light, rich saturated grade, painterly quality',
        'camera_and_composition': '85mm portrait or 50mm, close to medium framing, composed with artistic intent',
        'detail_and_texture': 'paint on canvas, brushstroke texture, gallery wall, artist hands in motion',
        'quality_and_realism': 'high fidelity, rich color, editorial portrait quality',
        'negative_constraints': 'no generic stock art photo, no flat illustration style, no watermark, no text overlay, no distorted anatomy',
    },
    'music': {
        'subject_definition': 'musician, instrument, or performance moment; sound made visually present',
        'action_and_context': 'musician in performance or composition; music as physical act',
        'environment_and_setting': 'concert hall, recording studio, street, or rehearsal space; stage or ambient light',
        'mood_and_story': 'emotionally resonant, culturally charged, performance energy',
        'visual_style': 'music documentary photography, live concert realism, Anton Corbijn portrait style',
        'lighting_and_color': 'dramatic stage light or warm natural, rich moody grade, expressive color',
        'camera_and_composition': '85mm or 50mm, eye-level or slight low angle, medium-close framing, shallow depth of field',
        'detail_and_texture': 'instrument surface, string tension, musician hands, venue texture and atmosphere',
        'quality_and_realism': 'high fidelity, sharp on subject, atmospheric background, concert photography quality',
        'negative_constraints': 'no generic stock music photo, no cartoon instruments, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
    'luxury': {
        'subject_definition': 'luxury object or aspirational figure; material excellence as visual subject',
        'action_and_context': 'craftsmanship, ownership, or experience of luxury; quality made visible',
        'environment_and_setting': 'upscale interior, private venue, or pristine natural setting; controlled warm light',
        'mood_and_story': 'aspirational, aesthetically precise, emotionally refined',
        'visual_style': 'luxury brand editorial, Vogue commercial photography, high-fashion minimalism',
        'lighting_and_color': 'warm golden key light, soft fill, rich warm grade, controlled highlights',
        'camera_and_composition': '85mm or 100mm macro, close detail or three-quarter portrait, clean shallow depth of field',
        'detail_and_texture': 'fine leather, polished metal, crystal, precious material surface texture',
        'quality_and_realism': 'ultra-sharp, pristine, editorial quality, commercial grade',
        'negative_constraints': 'no cheap-looking materials, no over-saturation, no cluttered backgrounds, no watermark, no text overlay, no distorted anatomy',
    },
    'entertainment': {
        'subject_definition': 'performer, film subject, or entertainment moment; personality as visual anchor',
        'action_and_context': 'performer in their element; the entertainment act captured at peak energy',
        'environment_and_setting': 'stage, film set, premiere, or behind-the-scenes; dramatic or press lighting',
        'mood_and_story': 'dynamic, culturally resonant, personality-driven',
        'visual_style': 'entertainment journalism photography, celebrity portrait, film still aesthetic',
        'lighting_and_color': 'dramatic key light, rich saturated grade, high contrast, energetic palette',
        'camera_and_composition': '50mm or 85mm, eye-level or low-angle power shot, medium-close framing',
        'detail_and_texture': 'costume detail, makeup precision, stage or set texture',
        'quality_and_realism': 'sharp, high fidelity, celebrity press photography quality',
        'negative_constraints': 'no paparazzi aesthetic, no over-retouched skin, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
    'cosmetics': {
        'subject_definition': 'cosmetic product or beauty subject; surface perfection as visual language',
        'action_and_context': 'product in use or in aesthetic composition; beauty as craft',
        'environment_and_setting': 'clean studio, vanity surface, or natural daylight setting; soft controlled light',
        'mood_and_story': 'precise, sensory, aspirationally beautiful',
        'visual_style': 'beauty editorial photography, Vogue skincare aesthetic, commercial precision',
        'lighting_and_color': 'soft diffused key light, warm neutral grade, subtle highlights, clean shadows',
        'camera_and_composition': '100mm macro or 85mm, level or slightly above, extreme close detail or portrait',
        'detail_and_texture': 'skin texture, product surface, liquid or powder texture, material precision',
        'quality_and_realism': 'ultra-sharp, pristine, commercial beauty quality',
        'negative_constraints': 'no over-retouched plastic skin, no garish colors, no messy composition, no watermark, no text overlay, no distorted anatomy',
    },
    'clothes': {
        'subject_definition': 'garment, fashion subject, or textile craft; clothing as visual language',
        'action_and_context': 'garment in wear or in design context; fashion as cultural signal',
        'environment_and_setting': 'fashion studio, urban street, or natural landscape; editorial light',
        'mood_and_story': 'aesthetic, culturally coded, aspirational',
        'visual_style': 'fashion editorial photography, Helmut Newton tension, street style realism',
        'lighting_and_color': 'dramatic editorial light or natural daylight, high-contrast clean grade',
        'camera_and_composition': '85mm or 50mm, three-quarter or full-length, strong editorial framing',
        'detail_and_texture': 'fabric weave, stitching, drape, material surface, natural fiber texture',
        'quality_and_realism': 'sharp, high fidelity, editorial fashion quality',
        'negative_constraints': 'no garish styling, no amateur composition, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
    'hypes': {
        'subject_definition': 'viral cultural moment or hype object; crowd energy as visual subject',
        'action_and_context': 'moment of peak cultural excitement; the hype at its origin point',
        'environment_and_setting': 'urban street, social event, drop queue, or digital context made physical; high energy',
        'mood_and_story': 'electrifying, culturally urgent, moment-driven',
        'visual_style': 'street photography, hypebeast editorial, Vice documentary aesthetic',
        'lighting_and_color': 'natural street light or flash, high-energy grade, saturated accent colors',
        'camera_and_composition': '35mm wide, eye-level or low angle, dynamic framing, slight motion',
        'detail_and_texture': 'sneaker texture, crowd density, limited edition product surface, urban material',
        'quality_and_realism': 'sharp, high fidelity, street photography documentary quality',
        'negative_constraints': 'no stock photo staging, no over-posed subjects, no watermark, no text overlay, no distorted anatomy, no extra limbs',
    },
}

_DEFAULT_TOPIC = 'history'


# ─────────────────────────────────────────────────────────────────────────────
# 2. BEAT TYPE OVERRIDES
#    Surgical block overrides applied when a strong narrative beat is detected.
#    Only tone-expressive blocks change.
#    Subject Definition, Visual Style, Negative Constraints are NEVER touched.
# ─────────────────────────────────────────────────────────────────────────────

BEAT_TYPE_OVERRIDES: dict[str, dict] = {
    'climactic_conflict': {
        'mood_and_story': 'dangerous, high-stakes, life-or-death tension, brutal confrontation',
        'lighting_and_color': 'cold hard shadows, strong backlighting, high contrast, blue-grey grade, harsh practical sources',
        'camera_and_composition': 'tight framing, dutch angle, 35-50mm, fast shutter freeze-frame, medium depth of field',
    },
    'tragedy_loss': {
        'mood_and_story': 'grief-laden, devastating, heavy with loss, mournful and resigned',
        'lighting_and_color': 'desaturated blue-grey grade, overcast flat light, lifted shadows, cold muted palette',
        'camera_and_composition': 'slow deliberate framing, 85mm, static low-energy shot, symmetrical grief composition',
    },
    'discovery_revelation': {
        'mood_and_story': 'awe-inspiring, intellectually electric, the world changed in this moment',
        'lighting_and_color': 'dramatic single-source reveal light, warm-to-cool transition, deep dark background',
        'camera_and_composition': '50mm, slight low-angle uplift, subject emerging from shadow, clean reveal framing',
    },
    'tension_build': {
        'mood_and_story': 'creeping dread, mounting pressure, something inevitable approaching',
        'lighting_and_color': 'low key, deep shadow, single source, cool desaturated grade, shallow pools of light',
        'camera_and_composition': '85mm compressed perspective, slow zoom implied, tight shallow depth of field, slightly off-center',
    },
    'resolution_triumph': {
        'mood_and_story': 'triumphant, cathartic, hard-won victory, earned relief and dignity',
        'lighting_and_color': 'warm golden key light, lifted grade, saturated warm tones, bright even exposure',
        'camera_and_composition': '50mm or 35mm, level or slight low-angle empowerment shot, open framing, clear depth of field',
    },
    # reflective_memorial intentionally empty — maps to the baseline, no override applied
    'reflective_memorial': {},
}


# ─────────────────────────────────────────────────────────────────────────────
# 3. BEAT CLASSIFIER LEXICON
#    Keyword sets per beat type, scored against transcript tokens.
# ─────────────────────────────────────────────────────────────────────────────

_BEAT_LEXICON: dict[str, list[str]] = {
    'climactic_conflict': [
        'attack',
        'battle',
        'assault',
        'siege',
        'clash',
        'combat',
        'fight',
        'conflict',
        'struggle',
        'confrontation',
        'invasion',
        'conquest',
        'charge',
        'storm',
        'brutal',
        'violent',
        'fierce',
        'devastating',
        'overwhelming',
        'desperate',
        'outnumbered',
        'slaughter',
        'massacre',
        'ambush',
        'raid',
        'bloodshed',
        'warfare',
        'troops',
        'soldiers',
        'forces',
        'offensive',
        'decisive',
        'furious',
        'relentless',
        'crushed',
    ],
    'tragedy_loss': [
        'death',
        'died',
        'killed',
        'fell',
        'perished',
        'destroyed',
        'collapse',
        'defeat',
        'loss',
        'tragedy',
        'sorrow',
        'grief',
        'mourning',
        'ruin',
        'devastation',
        'failed',
        'ended',
        'fallen',
        'obliterated',
        'annihilated',
        'crushed',
        'surrender',
        'collapsed',
        'victims',
        'casualties',
        'lost',
        'suffering',
        'anguish',
        'shattered',
        'doom',
    ],
    'discovery_revelation': [
        'discovered',
        'revealed',
        'found',
        'uncovered',
        'realized',
        'breakthrough',
        'invention',
        'innovation',
        'theory',
        'proof',
        'evidence',
        'showed',
        'demonstrated',
        'proved',
        'exposed',
        'shocking',
        'surprising',
        'unexpected',
        'suddenly',
        'first time',
        'never before',
        'secret',
        'unknown',
        'extraordinary',
        'remarkable',
        'unprecedented',
        'unveiled',
        'classified',
        'hidden',
        'finally',
        'changed everything',
    ],
    'tension_build': [
        'threat',
        'danger',
        'risk',
        'approaching',
        'warned',
        'feared',
        'growing',
        'mounting',
        'rising',
        'looming',
        'imminent',
        'brewing',
        'escalating',
        'pressure',
        'tension',
        'crisis',
        'inevitable',
        'mysterious',
        'uncertain',
        'fragile',
        'vulnerable',
        'weakening',
        'threatening',
        'brink',
        'edge',
        'unstable',
        'spreading',
        'alarming',
    ],
    'resolution_triumph': [
        'victory',
        'won',
        'succeeded',
        'achieved',
        'peace',
        'reconciled',
        'established',
        'founded',
        'built',
        'celebrated',
        'triumphant',
        'liberated',
        'freed',
        'restored',
        'unified',
        'treaty',
        'agreement',
        'settled',
        'accomplished',
        'prevailed',
        'conquered',
        'independence',
        'secured',
        'overcame',
        'survived',
        'rebuilt',
        'flourished',
    ],
    'reflective_memorial': [
        'remembered',
        'honored',
        'legacy',
        'memory',
        'centuries',
        'endured',
        'shaped',
        'influenced',
        'stood',
        'remains',
        'testament',
        'monument',
        'reflects',
        'taught',
        'lesson',
        'significance',
        'impact',
        'heritage',
        'commemorate',
        'lasting',
        'profound',
        'echo',
        'still',
        'today',
        'modern',
        'left behind',
        'defined',
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# 4. NARRATIVE BEAT CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────

_CONFIDENCE_THRESHOLD = 0.30  # minimum normalised score to fire an override
_DOMINANCE_RATIO = 1.35  # winner must score ≥ this × second-place to be considered dominant


class NarrativeBeatClassifier:
    """
    Classifies a transcript segment into a narrative beat type using lexical scoring.

    No external dependencies — pure Python standard library.

    Parameters
    ----------
    confidence_threshold : float
        Minimum normalised score required to fire a tone override (default 0.30).
    dominance_ratio : float
        Winner's score must be ≥ this multiple of second-best to override (default 1.35).
        This prevents tonal whiplash when two beats score similarly close.
    """

    def __init__(
        self,
        confidence_threshold: float = _CONFIDENCE_THRESHOLD,
        dominance_ratio: float = _DOMINANCE_RATIO,
    ):
        self._threshold = confidence_threshold
        self._dominance = dominance_ratio
        self._lexicon = _BEAT_LEXICON

        # Pre-compile multi-word phrase patterns; collect single-word terms separately
        self._phrases: dict[str, list[re.Pattern]] = {}
        self._words: dict[str, list[str]] = {}
        for beat, terms in self._lexicon.items():
            phrase_pats: list[re.Pattern] = []
            word_list: list[str] = []
            for t in terms:
                if ' ' in t:
                    phrase_pats.append(re.compile(re.escape(t), re.IGNORECASE))
                else:
                    word_list.append(t.lower())
            self._phrases[beat] = phrase_pats
            self._words[beat] = word_list

    def classify(self, text: str, audio_energy: float = 0.5) -> dict:
        """
        Classify the narrative beat of a transcript segment.

        Parameters
        ----------
        text : str
            Transcript or abstract text to classify.
        audio_energy : float
            Normalised audio energy 0.0–1.0 (default 0.5).
            High energy (> 0.7) boosts conflict and tension scores.
            Low energy  (< 0.3) boosts reflective and tragedy scores.

        Returns
        -------
        dict
            beat_type    : str  — detected beat type (fallback: 'reflective_memorial')
            confidence   : float — normalised confidence score (0.0–1.0)
            tone_override: dict  — block overrides to apply (empty dict if no override fires)
        """
        if not text or not text.strip():
            return {
                'beat_type': 'reflective_memorial',
                'confidence': 0.0,
                'tone_override': {},
            }

        text_lower = text.lower()
        tokens = re.findall(r'\b\w+\b', text_lower)
        token_set = set(tokens)

        raw_scores: dict[str, float] = {}
        for beat in self._lexicon:
            score = 0.0
            for w in self._words[beat]:
                if w in token_set:
                    score += 1.0
            # Multi-word phrases weighted 2× — richer, more specific signal
            for pat in self._phrases[beat]:
                if pat.search(text_lower):
                    score += 2.0
            raw_scores[beat] = score

        # Audio energy modifiers — applied before normalisation
        if audio_energy > 0.7:
            raw_scores['climactic_conflict'] *= 1.25
            raw_scores['tension_build'] *= 1.15
        elif audio_energy < 0.3:
            raw_scores['reflective_memorial'] *= 1.25
            raw_scores['tragedy_loss'] *= 1.15

        total_score = sum(raw_scores.values())
        if total_score == 0:
            return {
                'beat_type': 'reflective_memorial',
                'confidence': 0.0,
                'tone_override': {},
            }

        normalised: dict[str, float] = {b: s / total_score for b, s in raw_scores.items()}
        ranked = sorted(normalised.items(), key=lambda x: x[1], reverse=True)
        best_beat, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0

        dominant = best_score >= self._threshold and (
            second_score == 0.0 or best_score / max(second_score, 1e-9) >= self._dominance
        )

        if dominant:
            override = dict(BEAT_TYPE_OVERRIDES.get(best_beat, {}))
            return {
                'beat_type': best_beat,
                'confidence': round(best_score, 4),
                'tone_override': override,
            }

        # No dominant beat — stay on baseline
        return {
            'beat_type': 'reflective_memorial',
            'confidence': round(best_score, 4),
            'tone_override': {},
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. VISUAL FRAMEWORK RESOLVER
#    Combines discipline baseline + beat override into a final 10-block dict.
# ─────────────────────────────────────────────────────────────────────────────

# These blocks define the aesthetic identity of the clip — never overridden by a beat
_LOCKED_BLOCKS = frozenset(
    {
        'subject_definition',
        'visual_style',
        'negative_constraints',
    }
)


class VisualFrameworkResolver:
    """
    Resolves the final 10-part visual framework for a given topic and transcript.

    The resolved framework is the input schema for the Thumbnail-Agent,
    Hook-Generator, and Commentary-Agent. It is also directly convertible to
    an SD/XL prompt pair via build_sd_prompt().

    Usage
    -----
        resolver = VisualFrameworkResolver()
        result   = resolver.resolve('history', transcript_text, audio_energy=0.6)

        result['framework']       # final 10-block dict (baseline + overrides applied)
        result['beat']            # NarrativeBeatClassifier output dict
        result['topic']           # resolved topic string
        result['override_applied'] # True if a beat override fired
    """

    def __init__(
        self,
        confidence_threshold: float = _CONFIDENCE_THRESHOLD,
        dominance_ratio: float = _DOMINANCE_RATIO,
    ):
        self._classifier = NarrativeBeatClassifier(confidence_threshold, dominance_ratio)

    def resolve(
        self,
        topic: str,
        transcript: str = '',
        audio_energy: float = 0.5,
    ) -> dict:
        """
        Build the final framework dict for a clip.

        Parameters
        ----------
        topic : str
            Scholarly topic key (must match a key in DISCIPLINE_BASELINES;
            falls back to _DEFAULT_TOPIC if unknown).
        transcript : str
            Transcript or abstract text for beat classification.
        audio_energy : float
            Normalised audio energy 0.0–1.0 (default 0.5).

        Returns
        -------
        dict
            topic            : str
            framework        : dict — final 10-block resolved dict
            beat             : dict — NarrativeBeatClassifier result
            override_applied : bool
        """
        topic_key = topic.lower().strip()
        baseline = dict(DISCIPLINE_BASELINES.get(topic_key, DISCIPLINE_BASELINES[_DEFAULT_TOPIC]))

        beat_result = self._classifier.classify(transcript, audio_energy)
        override = beat_result.get('tone_override', {})

        framework = dict(baseline)
        override_applied = False
        for block_key, override_value in override.items():
            if block_key not in _LOCKED_BLOCKS:
                framework[block_key] = override_value
                override_applied = True

        return {
            'topic': topic_key,
            'framework': framework,
            'beat': beat_result,
            'override_applied': override_applied,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 6. SD/XL PROMPT BUILDER
#    Converts a resolved framework dict into SD/XL positive + negative prompts.
#    The positive prompt is built from the 9 non-negative blocks in pipeline order.
#    The negative prompt is the negative_constraints block verbatim.
# ─────────────────────────────────────────────────────────────────────────────

_POSITIVE_BLOCK_ORDER = (
    'subject_definition',
    'action_and_context',
    'environment_and_setting',
    'mood_and_story',
    'visual_style',
    'lighting_and_color',
    'camera_and_composition',
    'detail_and_texture',
    'quality_and_realism',
)

_FALLBACK_NEGATIVE = (
    'no watermark, no text overlay, no extra limbs, no distorted anatomy, '
    'no blurry face, no low resolution, no compression artifacts, '
    'no duplicated subjects, no warped geometry, no melted objects'
)


def build_sd_prompt(framework: dict) -> tuple:
    """
    Convert a resolved 10-block framework dict into an SD/XL prompt pair.

    Parameters
    ----------
    framework : dict
        The 'framework' value from VisualFrameworkResolver.resolve().

    Returns
    -------
    (positive_prompt, negative_prompt) : tuple[str, str]
        positive_prompt : comma-joined positive prompt string
        negative_prompt : negative constraints string
    """
    positive_parts = [framework.get(block, '').strip().rstrip(',') for block in _POSITIVE_BLOCK_ORDER]
    positive = ', '.join(p for p in positive_parts if p)
    negative = framework.get('negative_constraints', _FALLBACK_NEGATIVE)
    return positive, negative
