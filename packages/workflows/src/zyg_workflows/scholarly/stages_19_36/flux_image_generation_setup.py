# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The prompt tables and the setup steps of Stage 3.5's still-generation stage.

`stage_10_flux_image_generation` in `flux_image_generation` was 452 lines of
constant tables interleaved with six independent setup steps. The tables are
module-level constants here and the steps are named functions, so the stage
function is the orchestrator that calls them in the order the monolith ran
them. Every log line, every `pipeline_state` write and their order are the
ones the stage had.
"""

from dataclasses import dataclass

from ._common import (
    _SCHOLARLY_SEC_PER_WORD,
    _derive_episode_era,
    _load_flux_seconds_per_image_estimate,
    _scholarly_motion,
    _scholarly_n_images,
    _smoke_cap,
    os,
    paths,
)

# ── Prompt templates: tag → template string (subject filled per-image)
# Tag keys match Stage 3b _TAG_KEYWORDS categories PLUS history-specific event tags.
FLUX_PROMPT_TEMPLATES = {
    # Generic scholarly tags
    'historical archive': 'dramatic cinematic scene of {subject}, ancient setting, oil painting style, moody lighting, photorealistic, 8k, epic composition',
    'library books': 'ornate historical library with ancient manuscripts and {subject} related artifacts, candlelight, cinematic depth of field',
    'data charts': 'dramatic documentary visualization of {subject}, stylized ancient infographic scroll, illuminated manuscript style, cinematic',
    'scientific equipment': 'ancient scientific instruments and {subject} artifacts, museum display, dramatic lighting, detailed photorealistic',
    'nature landscape': 'epic landscape of {subject} historical location, golden hour, ultra detailed, cinematic wide angle, breathtaking',
    'city skyline': 'grand ancient city of {subject} at its height, crowded stone streets, monumental architecture, golden hour, photorealistic',
    'protest crowd': 'dramatic historical crowd scene of {subject}, revolution and uprising, oil painting realism, epic cinematic composition',
    'university campus': 'grand ancient academy with scholars studying {subject}, arched stone hall, candlelight, painterly atmosphere',
    # History-specific event tags (extracted from narration sentences)
    'battle': 'epic oil painting of the battle of {subject}, ancient soldiers clashing, blood and banners, dramatic stormy sky, cinematic realism',
    'conquest': 'dramatic scene of {subject} conquest, army marching through ruins, dust and fire, cinematic epic scale',
    'leader': 'regal portrait of {subject}, ancient throne room, dramatic side lighting, photorealistic oil painting, commanding presence',
    'emperor': 'majestic emperor {subject} on throne, imperial hall, gold and marble, dramatic lighting, epic historical portrait',
    'king': 'medieval king {subject}, great hall, firelight, armored court, dramatic portrait, oil painting style',
    'death': 'somber dramatic scene of the death of {subject}, torchlit chamber, grief and ceremony, cinematic oil painting',
    'fall': 'dramatic scene of the fall of {subject}, crumbling walls, fire and smoke, chaos, cinematic wide angle realism',
    'collapse': 'ruins of the empire of {subject}, overgrown stone, dramatic moody sky, cinematic desolation, epic scale',
    'religion': 'ancient temple ritual of {subject} civilization, priests at altar, torchlight and incense, atmospheric oil painting',
    'ritual': 'sacred ceremony of {subject}, robed figures, firelight, ancient stone altar, cinematic documentary realism',
    'voyage': 'ancient ships of {subject} on open sea, sails and storm clouds, dramatic wide angle, cinematic nautical epic',
    'exploration': 'explorers of {subject} reaching new shores, dramatic dawn light, cinematic panorama, epic historical realism',
    'trade': 'bustling ancient market of the {subject} trade route, merchants and goods, cinematic wide angle, golden hour',
    'map': 'ancient illustrated parchment map of {subject} territory, hand-drawn borders, aged texture, dramatic candlelight',
    'diplomacy': 'two ancient rulers of {subject} in formal treaty ceremony, grand hall, candlelight, oil painting realism',
    'alliance': 'ancient leaders of {subject} clasping hands in alliance, stone hall, dramatic lighting, photorealistic historical painting',
    'invasion': 'dramatic scene of {subject} invasion, armies crossing a river, banners and dust, epic oil painting style',
    'siege': 'epic siege of the city of {subject}, catapults and fire, massive stone walls, cinematic battle realism',
    'plague': 'grim medieval scene of plague during {subject} era, dark streets, cloaked figures, dramatic moody atmosphere',
    'migration': 'mass migration of the people of {subject}, long caravan through harsh landscape, cinematic epic wide angle',
    # Modern / documentary topics — clean photorealistic style, no forced medieval framing
    'documentary scene': 'cinematic documentary scene depicting {subject}, natural lighting, photorealistic, shallow depth of field, film grain, 8k',
}

DEFAULT_FLUX_PROMPT = (
    'dramatic cinematic documentary scene depicting {subject}, photorealistic, 8k, moody atmospheric lighting'
)

# Era-anchoring prefix injected at the START of every positive prompt.
# FLUX.1-schnell runs at guidance_scale=0.0 so negative prompts are ignored —
# anachronism prevention must happen entirely through the positive prompt.
# IMPORTANT: Do NOT use "no X" phrasing — diffusion models encode the concept
# of X regardless of negation. Use strong positive era descriptors instead.
# Era anchoring: 4 rotating variant prefixes (landscape / people / objects / architecture)
# Applied at END of prompt so scene description + shot type carry more weight.
# FLUX.1-schnell uses guidance_scale=0.0 — positive phrasing only, never "no X".
ERA_CONTEXT = {
    'history': [
        (
            'period-accurate medieval setting, stone walls torchlight oil lamps, '
            'cobblestone streets dirt paths wooden carts horses oxen, oil painting realism'
        ),
        (
            'period-accurate ancient figures, hand-woven tunics robes chainmail plate armour leather sandals, '
            'period-authentic clothing and weapons, historical realism'
        ),
        (
            'period-accurate artifacts and objects, parchment quill ink manuscript, '
            'iron tools bronze weapons clay pottery wooden furniture, detailed historical'
        ),
        (
            'period-accurate architecture, timber-framed buildings thatched roofs stone castles '
            'arched doorways vaulted ceilings stained glass, 12th century construction'
        ),
    ],
    'war': [
        ('ancient or medieval battlefield, swords spears shields chainmail plate armour, historical'),
        ('cavalry horses archers siege weapons catapults battering rams, period-accurate warriors'),
        ('smoke and dust hand-to-hand combat, blood and banners, historical realism'),
        ('ancient fortifications walls towers ramparts, period siege warfare, historical'),
    ],
    'religion': [
        ('ancient sacred stone cathedral monastery, stained glass candlelight incense, historical'),
        ('robed monks priests scribes, period-accurate sacred clothing and ritual objects'),
        ('illuminated manuscripts stone altars relics, period-accurate sacred artifacts'),
        ('ancient pilgrimage roads holy sites crowds worshippers, period religious realism'),
    ],
    'philosophy': [
        ('ancient Greek or medieval European scholarly setting, marble columns togas scrolls, historical'),
        ('ancient philosophers debating, period-accurate robes sandals amphitheatre, historical'),
        ('parchment scrolls manuscripts quills, ancient writing materials, historical realism'),
        ('ancient academies libraries stone halls, period-accurate scholarly architecture'),
    ],
    'science': [
        ('period scientific instruments astrolabes globes, ancient laboratory, historical realism'),
        ('medieval scholars observing stars, period-accurate robes and instruments'),
        ('ancient manuscripts diagrams illustrations, period scientific texts, historical'),
        ('medieval observatory tower, stone architecture, candlelight study, historical'),
    ],
}

# Fallback for unknown topics — neutral cinematic documentary style (not forced medieval)
ERA_CONTEXT_DEFAULT = [
    'cinematic documentary style, natural soft lighting, photorealistic, shallow depth of field',
    'cinematic close-up, warm ambient light, photorealistic skin and fabric detail, film grain',
    'wide establishing shot, natural environment, golden hour light, cinematic photorealism',
    'intimate interior scene, ambient practical lighting, photorealistic, documentary film style',
]

# Documentary / medical topics — clean modern cinematic style
ERA_CONTEXT_DOCUMENTARY = [
    'cinematic documentary cinematography, soft natural light, photorealistic, 8k, film grain',
    'intimate close-up, warm ambient light, skin detail and texture, documentary film style',
    'wide establishing shot, diffused daylight, photorealistic, shallow depth of field',
    'clinical clean environment, soft studio lighting, photorealistic, educational clarity',
]

# Style cycle — 20 distinct styles so a 60-image run never repeats a style twice.
# Ordered so progression feels cinematic: wide establishing → intimate details → epic.
STYLE_SUFFIXES = [
    ', oil painting, dramatic chiaroscuro lighting, deep shadows',
    ', photorealistic cinematic render, golden hour, anamorphic lens flare',
    ', dramatic black and white engraving, high contrast, etching texture',
    ", aerial bird's-eye view, wide panorama, epic landscape scale",
    ', extreme close-up portrait, soft diffused light, textured skin and fabric detail',
    ', dark dramatic chiaroscuro, cinematic realism, Rembrandt lighting',
    ', epic matte painting, atmospheric haze, layered depth',
    ', detailed pen and ink illustration, vintage crosshatching',
    ', cinematic shallow depth of field, soft diffused light, photorealistic',
    ', deep focus wide shot, moody interior, ambient practical lighting',
    ', silhouette against bright window, backlit dramatic rim light',
    ', low angle shot, looming figure, dramatic sky overhead',
    ", bird's-eye wide shot, masses of people, epic scale overhead",
    ', intimate natural light interior, warm ambient glow, shallow depth of field',
    ', stormy dramatic sky, dark clouds, epic wide angle',
    ', rich warm tones, golden hour, cinematic color grade',
    ', cool blue tones, atmospheric haze, volumetric light beams',
    ', twilight blue hour, cool desaturated tones, melancholy mood',
    ', sunrise golden light, long shadows, hopeful warm atmosphere',
    ', moonlit night scene, silver blue tones, mysterious shadow play',
]

# Arc-zone style mapping for HISTORICAL topics — ensures style reinforces narrative position.
# For modern/documentary topics a separate mapping is used (no oil painting / manuscript styles).
ARC_STYLE_MAP_HISTORICAL = {
    'exposition': [0, 9, 13],  # establishing oil painting, architecture, intimate interior
    'rising': [1, 4, 6],  # cinematic, close-up, matte painting
    'climax': [2, 10, 14],  # high contrast engraving, silhouette, storm
    'falling': [17, 15, 7],  # blue hour, illuminated manuscript, pen-ink
    'resolution': [18, 19, 3],  # sunrise, moonlit, aerial wide
    # HOOK — image slot 0 only, and only when the intensity dial is up.
    # Deliberately NOT the exposition row: 0/9/13 are establishing
    # oil-painting, moody interior and "intimate warm ambient glow",
    # which is how the coldest frame in the episode ended up first.
    'hook': [11, 14, 5],  # low-angle looming figure, storm sky, hard chiaroscuro
}

# Arc-zone style mapping for MODERN/DOCUMENTARY topics — cinematic photorealistic only.
ARC_STYLE_MAP_MODERN = {
    'exposition': [1, 9, 13],  # cinematic render, wide interior, warm ambient
    'rising': [4, 8, 6],  # close-up portrait, shallow DOF, matte painting
    'climax': [10, 11, 14],  # silhouette, low angle, dramatic sky
    'falling': [17, 16, 7],  # blue hour, cool tones, vintage illustration
    'resolution': [18, 19, 3],  # sunrise, moonlit, aerial wide
    'hook': [11, 14, 10],  # low angle, dramatic sky, silhouette
}

SHOT_ROTATION = [
    'wide establishing shot, cinematic',
    'close-up, tight focus',
    'extreme close-up, raw detail',
    'low-angle hero shot',
    "overhead drone shot, bird's eye view",
    'medium wide shot, cinematic',
    'Dutch angle, unsettling tilt',
    'over-the-shoulder shot, intimate',
]

# Emotion diversity enforcer: inject a calm/mystery beat every 6 slots to prevent monotony
EMOTION_RELIEF_SLOTS = {'calm', 'mystery', 'contemplative', 'wonder'}

# Fallback subject: essay title stripped of academic filler
FILLER_PATTERN = (
    r'\b(an|a|the|of|in|on|at|to|for|and|or|with|from|essay|analysis|study|research|paper|dissertation|journal)\b'
)


def resolve_still_family_label():
    """Return `(family, label)` for the renderer that will actually produce the stills.

    `family` is `scholarly_stills_backend.scholarly_still_family()` (`'flux'` when
    the backend module cannot be reached); `label` is the human name of it. The
    family can still fall back to FLUX at the backend decision in Stage 3.5b.
    """
    # Label the REAL renderer (P-13): this line said FLUX.1-schnell on a
    # run whose stills came from Qwen-Image-2512. The family can still
    # fall back to FLUX at the backend decision below (Qwen unavailable);
    # _sch_family_label is re-derived there from _sch_qwen_stills.
    try:
        from zyg_workflows import scholarly_stills_backend as _ssb_lbl

        family = _ssb_lbl.scholarly_still_family()
    except Exception:
        family = 'flux'
    return family, ('Qwen-Image-2512' if family == 'qwen' else 'FLUX.1-schnell')


def prepare_character_bible(pipeline_state, sch_char_id, log):
    """Load this run's character bible (if any) into `pipeline_state`.

    Always sets `pipeline_state['character_bible']` — to `None` when the run has
    no character — and sets `pipeline_state['char_reference_image']` to the first
    usable portrait found in the character's LoRA dataset. Failures are logged as
    a warning and leave the run without a bible.
    """
    pipeline_state['character_bible'] = None
    if not sch_char_id:
        return
    try:
        import copy as _copy_sch_bible
        from zyg_workflows import character_bible_service as _cbs_sch
        from zyg_workflows import consistency_qa_service as _cqa_sch

        _bible_sch = _cbs_sch.load(sch_char_id)
        if _bible_sch:
            _bible_sch = _copy_sch_bible.deepcopy(_bible_sch)
            _cbs_sch.apply_scholarly_conditioning_defaults(_bible_sch)
            pipeline_state['character_bible'] = _bible_sch
            _cqa_sch.ensure_reference_from_bible(
                sch_char_id,
                log_fn=lambda m: log('INFO', 'Stage 3.5', m),
            )
            log('INFO', 'Stage 3.5', f'Character bible loaded for scholarly run ({sch_char_id[:8]})')
        _ds = os.path.join(paths.ZYG_LORA_DATASETS, 'storyteller_chars', sch_char_id)
        for _pc in (
            'portrait_00_000deg.png',
            'preview_flux_front.png',
            'full_neutral_000deg.png',
        ):
            _pp = os.path.join(_ds, _pc)
            if os.path.isfile(_pp) and os.path.getsize(_pp) > 10_000:
                pipeline_state['char_reference_image'] = _pp
                break
    except Exception as _bible_sch_e:
        log('WARNING', 'Stage 3.5', f'Character bible (scholarly): {_bible_sch_e}')


@dataclass
class ImageCountPlan:
    """How many stills Stage 3.5 will render, and the sentence that explains why."""

    word_count_est: int
    est_duration: float
    n_flux_images: int
    n_images_source: str


def resolve_image_count(pipeline_state, sch_duration_targets, log) -> ImageCountPlan:
    """Decide the still count for this run and record it on `pipeline_state`.

    Reads the Advanced-Settings cap, the time-locked count Stage 3.5a may have
    left in `_tls_n_images`, the LTX motion floor and the smoke cap, in that
    order of precedence, and writes `n_flux_images` / `n_flux_images_source`.
    """
    # Image count: pipeline_options cap, else one picture per LTX clip (scholarly_motion).
    _word_count_est = pipeline_state.get('word_count', sch_duration_targets.get('target_words', 2000))
    # Measured narration length wins over the word-rate estimate (P-13).
    _est_duration = float(pipeline_state.get('tts_duration') or (_word_count_est * _SCHOLARLY_SEC_PER_WORD))
    _sch_flux_cap = (pipeline_state.get('scholarly_duration_targets') or sch_duration_targets).get('n_flux_images')
    if _sch_flux_cap is not None:
        _n_flux_images = int(_sch_flux_cap)
        _n_images_source = f'Advanced Settings cap ({_sch_flux_cap})'
    else:
        _n_flux_images = _scholarly_n_images(_est_duration)
        _n_images_source = (
            f'one picture per {_scholarly_motion.clip_target_s():.0f}s LTX clip '
            f'over {_est_duration:.0f}s of estimated narration'
        )
    # Stage 3.5a ran TTS first and computed an exact count from tts_duration — prefer it
    _tls_override = pipeline_state.get('_tls_n_images')
    if _tls_override and _sch_flux_cap is None:
        _n_flux_images = _tls_override
        _n_images_source = f'time-locked scenes from tts_duration ({_tls_override})'
    # A slot can never be longer than the clip that has to cover it. The caps
    # above are derived from the REQUESTED length, and narration routinely
    # overshoots it — a 150 s request measured 221.8 s, which turned an
    # 8-picture cap into 27.7 s slots against a 20 s LTX ceiling, i.e. every
    # shot visibly looping 7.7 s before its cut. Raise the count to the
    # minimum LTX can actually cover, and say so rather than ship the loop.
    if _scholarly_motion.enabled() and _est_duration > 0:
        _motion_floor = _scholarly_n_images(_est_duration)
        if _n_flux_images < _motion_floor:
            log(
                'INFO',
                'Stage 3.5',
                f'Picture count raised {_n_flux_images} → {_motion_floor}: '
                f'{_est_duration:.0f}s of narration over {_n_flux_images} slot(s) is '
                f'{_est_duration / max(_n_flux_images, 1):.1f}s each, longer than the '
                f'{_scholarly_motion.clip_target_s():.0f}s an LTX clip can cover '
                f'(count was: {_n_images_source})',
            )
            _n_images_source = f'{_n_images_source}, raised to {_motion_floor} so no slot outruns its LTX clip'
            _n_flux_images = _motion_floor
    _smoke_cap_n = _smoke_cap()
    if _smoke_cap_n > 0 and _n_flux_images > _smoke_cap_n:
        _n_images_source = f'smoke cap {_smoke_cap_n} (would have been {_n_flux_images})'
        _n_flux_images = _smoke_cap_n
    pipeline_state['n_flux_images'] = _n_flux_images
    pipeline_state['n_flux_images_source'] = _n_images_source
    return ImageCountPlan(
        word_count_est=_word_count_est,
        est_duration=_est_duration,
        n_flux_images=_n_flux_images,
        n_images_source=_n_images_source,
    )


def log_generation_estimate(pipeline_state, plan: ImageCountPlan, family, family_label, log) -> None:
    """Record the per-image seconds estimate for `family` and log the stage target.

    Writes `pipeline_state['flux_seconds_per_image_estimate']` (never ≤ 0) and
    emits the "Target: N images …" line the stage has always logged.
    """
    # Per-family estimate (P-13): Qwen queue-wait numbers used to be
    # written into the FLUX estimate and read back as FLUX render cost.
    _learned_flux_s_per_img = _load_flux_seconds_per_image_estimate(
        default=10.0, family=('qwen' if family == 'qwen' else 'flux')
    )
    _est_flux_seconds_per_image = float(pipeline_state.get('flux_seconds_per_image_estimate', _learned_flux_s_per_img))
    if _est_flux_seconds_per_image <= 0:
        _est_flux_seconds_per_image = 10.0
    pipeline_state['flux_seconds_per_image_estimate'] = round(_est_flux_seconds_per_image, 3)
    log(
        'INFO',
        'Stage 3.5',
        f'Target: {plan.n_flux_images} images for ~{plan.est_duration:.0f}s narration '
        f'(count from: {plan.n_images_source} — est. gen time '
        f'~{plan.n_flux_images * _est_flux_seconds_per_image / 60:.1f}min @ '
        f'~{_est_flux_seconds_per_image:.1f}s/image on {family_label})',
    )


def build_flux_negative(sch_intensity) -> str:
    """Assemble the negative prompt for this run's intensity rank.

    INTENSITY DIAL: the gore and mutilation terms are only relaxed at rank ≥ 2
    ('extreme'), which a person has to select deliberately. At the default
    'high' the block is byte-for-byte the one the stage always used.
    """
    # The dial asks for ARRESTING imagery, not graphic imagery, so at the
    # default 'high' the gore block stays exactly where it was — an episode
    # pitched for impact should not be quietly drifting graphic as a side
    # effect. Only 'extreme' unblocks them, and even there the prompt side
    # still says not to reach for gore gratuitously. (Mostly inert in
    # production anyway: schnell drops the negative at guidance_scale=0.0,
    # measured. It is LIVE on the anatomy branch where the ladder raises
    # guidance.)
    _neg_relax = sch_intensity['rank'] >= 2
    _neg_content_terms = '' if _neg_relax else 'gore, '
    _neg_figure_terms = 'disfigured, malformed' if _neg_relax else 'disfigured, mutilated, amputation, malformed'
    return (
        'nude, nudity, naked, explicit, nsfw, sexual, genitals, genitalia, '
        'penis, vagina, vulva, breasts, nipples, pubic, groin, buttocks, anus, '
        + _neg_content_terms
        + 'modern technology, cartoon, anime, watermark, logo, text overlay, '
        'ugly, blurry, low quality, cars, automobiles, electricity, skyscrapers, modern clothing, '
        # Figure quality negatives (active when guidance_scale > 0)
        'extra fingers, missing fingers, fused fingers, deformed hands, mutated hands, '
        'extra limbs, missing limbs, fused limbs, melting limbs, floating body parts, '
        'extra arms, extra legs, misshapen feet, deformed toes, '
        'warped face, distorted face, clone face, duplicate person, '
        'bad anatomy, wrong anatomy, unrealistic anatomy, '
        'poorly drawn hands, poorly drawn face, poorly drawn body, ' + _neg_figure_terms
    )


def era_variants_for(era_lock, topic, is_modern_topic) -> list:
    """Pick the four rotating era-anchoring suffixes this episode will cycle.

    Modern episodes get the clean documentary set; a historical episode whose own
    script yielded period anchors uses those (they beat the static topic table,
    which hardcodes *medieval* for every 'history' run and would put chainmail in
    an 1801 durbar); anything else falls back to the topic table.
    """
    if is_modern_topic:
        return ERA_CONTEXT_DOCUMENTARY
    if era_lock.get('anchors'):
        return era_lock['anchors']
    return ERA_CONTEXT.get(topic, ERA_CONTEXT_DEFAULT)


def resolve_era_lock(ctx, log, debug):
    """Derive this episode's period once and return `(era_lock, is_modern, variants)`.

    `topic` is a DEPARTMENT bucket, not a description of the subject: every
    free-text documentary launched from the board arrives as topic='general'.
    Keying era anchoring off it meant an episode about an empire that fell in
    1849 was classified 'modern', told its visual style was "modern setting",
    and handed a clean-modern era suffix — so any narration clause containing
    "today"/"still"/"now" produced a present-day photograph mid-episode (Sikh
    Empire run c070c1c1 slot 4). The period is derived from the SCRIPT instead,
    once, written to `pipeline_state['episode_era']`, and every downstream
    visual decision reads it from there.
    """
    pipeline_state = ctx.pipeline_state
    topic = ctx.topic
    era_lock = _derive_episode_era(
        directive=ctx.directive or '',
        essay_title=pipeline_state.get('essay_title', '') or topic,
        script=ctx.narration_script or '',
        topic=topic,
        log=lambda m, lvl='INFO': log(lvl, 'Stage 3.5', m),
        debug=lambda m: debug('Stage 3.5', m),
        pipeline_id=ctx.pipeline_id,
    )
    pipeline_state['episode_era'] = era_lock
    is_modern_topic = not era_lock['is_historical']
    era_variants = era_variants_for(era_lock, topic, is_modern_topic)
    log(
        'INFO',
        'Stage 3.5',
        f'Era lock: {"historical" if era_lock["is_historical"] else "modern"} — '
        f'{era_lock["period_label"]} (source: {era_lock["source"]})',
    )
    return era_lock, is_modern_topic, era_variants


def build_fallback_subject(essay_title_for_prompt, topic) -> str:
    """Return the ≤6-word subject used when no entity can be pulled from a slot.

    The essay title with academic filler words dropped; the department topic when
    nothing survives the strip.
    """
    import re as _re_flux_sub

    return (
        ' '.join(
            _re_flux_sub.sub(FILLER_PATTERN, '', essay_title_for_prompt, flags=_re_flux_sub.IGNORECASE).split()[:6]
        )
        or topic
    )


def split_narration_sentences(narration_script) -> list:
    """Split the narration into the sentence list used to time-lock image slots.

    Sentence-final punctuation is the boundary; fragments of 20 characters or
    fewer are dropped.
    """
    import re as _re_flux_sub

    return [s.strip() for s in _re_flux_sub.split(r'(?<=[.!?])\s+', narration_script) if len(s.strip()) > 20]
