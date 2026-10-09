# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.stills — the still-rendering section — Qwen edits, ESRGAN resize and per-shot stills (lines 3057-3413).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    Image,
    ImageDraw,
    ImageFilter,
    _ESRGAN_WEIGHTS,
    _log_noop,
    _zyg_log,
    np,
    os,
)

# ── still rendering ──────────────────────────────────────────────────────────


def _qwen_scene_edit(
    src_path: str, dst_path: str, instruction: str, negative: str = '', seed: int = 42, log_fn=None
) -> bool:
    """General Qwen-Image-Edit pass on a rendered still (same graph the wardrobe
    service uses): source enters as conditioning, denoise 1.0 → identity, pose,
    lighting and art style survive; only what the instruction names changes.
    Used for DERIVED shots (e.g. remove one character from a two-shot so both
    shots share literally the same scene — zero continuity drift)."""
    import copy as _copy
    import math as _math

    log = log_fn or _log_noop
    try:
        from zyg_workflows import comfy_generation_service as _cgs

        qwen_unet = _cgs.qwen_edit_unet() or ''
        from zyg_workflows import _comfy_client as _comfy

        g = _copy.deepcopy(_comfy.load_workflow('qwen_edit_angle'))
        src_name = _comfy.stage_input_image(src_path)
    except Exception as e:
        log(f'[scene] qwen edit setup failed ({e})')
        return False
    if not qwen_unet:
        log('[scene] qwen unet unavailable — cannot derive shot')
        return False
    with Image.open(src_path) as im:
        ow, oh = im.size
    w, h = ow, oh
    budget = 1.0 * 1024 * 1024
    if w * h > budget:
        s = _math.sqrt(budget / float(w * h))
        w, h = int(w * s), int(h * s)
    neg = 'deformed, extra limbs, extra person, changed face, different person, blurry, watermark, text'
    if negative:
        neg = f'{negative}, {neg}'
    g['10']['inputs']['unet_name'] = qwen_unet
    g['14']['inputs']['strength_model'] = 0.0
    g['15']['inputs']['image'] = src_name
    g['20']['inputs']['prompt'] = instruction
    g['21']['inputs']['prompt'] = neg
    g['30']['inputs']['width'] = max(256, (w // 16) * 16)
    g['30']['inputs']['height'] = max(256, (h // 16) * 16)
    g['31']['inputs'].update({'seed': int(seed), 'steps': 32, 'cfg': 3.0, 'denoise': 1.0})
    g['50']['inputs']['filename_prefix'] = 'ZygSceneEdit'
    try:
        outs = _comfy.submit(g, timeout_s=600)
    except Exception as e:
        log(f'[scene] qwen edit submit failed ({e})')
        return False
    if not (outs and os.path.isfile(outs[0])):
        log('[scene] qwen edit produced no output')
        return False
    res = Image.open(outs[0]).convert('RGB')
    if res.size != (ow, oh):
        res = res.resize((ow, oh), Image.LANCZOS)
    res.save(dst_path)
    return True


def _prop_edit_region(still: str, cfg: dict, log_fn=None) -> bool:
    """A Qwen edit SCOPED TO A CROP, then feathered back in.

    Whole-frame prop edits failed on this scene in a way worth recording,
    because the failure mode is systematic rather than bad luck. Qwen's graph
    downsamples the input to a ~1 MP budget, so a hand that is 180 px across in
    a 1344×768 still arrives as a smudge — and asked for "a white clay pipe" it
    would either keep the source silhouette and merely recolour it (a straight
    stick became a straight white rod, a wand, a lit taper) or find some OTHER
    object in the frame with roughly the right shape and convert THAT instead:
    one pass turned the candle into a goblet and left the hand untouched. Three
    prompt families and six base seeds all landed in that set.

    Cropping fixes both halves at once. The region is upscaled to fill the pixel
    budget, so the prop is synthesised at ~4× the linear detail — the same
    reasoning that made the hand fixer upscale first — and nothing outside the
    box can be repurposed, because nothing outside the box is sent.

    The paste is feathered: denoise is 1.0, so the crop comes back re-synthesised
    and its edge will not match to the pixel.
    """
    log = log_fn or _log_noop
    src = Image.open(still).convert('RGB')
    W0, H0 = src.size
    b = cfg['box']
    px = (max(0, int(b[0] * W0)), max(0, int(b[1] * H0)), min(W0, int(b[2] * W0)), min(H0, int(b[3] * H0)))
    crop = src.crop(px)
    if crop.width < 16 or crop.height < 16:
        log('[scene] prop edit: box too small')
        return False
    budget = float(cfg.get('budget_px', 1024 * 1024))
    scale = min(4.0, max(1.0, (budget / float(crop.width * crop.height)) ** 0.5))
    big = _esrgan_resize(crop, int(crop.width * scale), int(crop.height * scale), log_fn=log) if scale > 1.05 else crop
    tmp_in = still + '.pe_in.png'
    tmp_out = still + '.pe_out.png'
    big.save(tmp_in)
    try:
        ok = _qwen_scene_edit(
            tmp_in,
            tmp_out,
            cfg['instruction'],
            negative=cfg.get('negative', ''),
            seed=int(cfg.get('seed', 42)),
            log_fn=log,
        )
        if not ok:
            return False
        out = Image.open(tmp_out).convert('RGB').resize(crop.size, Image.LANCZOS)
        f = int(cfg.get('feather', 24))
        mask = Image.new('L', crop.size, 0)
        ImageDraw.Draw(mask).rectangle([f, f, crop.width - f, crop.height - f], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(f * 0.6))
        src.paste(out, (px[0], px[1]), mask)
        src.save(still)
        log(f'[scene] prop edit region {px} @ ×{scale:.2f} ({big.width}×{big.height} to the sampler)')
        return True
    finally:
        for p in (tmp_in, tmp_out):
            if os.path.isfile(p):
                os.remove(p)


def _esrgan_resize(img: Image.Image, W: int, H: int, log_fn=None) -> Image.Image:
    """RealESRGAN 4x then downscale to (W,H). Falls back to LANCZOS.
    (RealESRGAN is the measured-best upscaler on this box — see the SeedVR2
    comparison; a crop upscaled by LANCZOS alone reads soft against native
    renders.)"""
    log = log_fn or _log_noop
    try:
        import cv2
        import realesrgan
        from basicsr.archs.rrdbnet_arch import RRDBNet

        mdl = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        up = realesrgan.RealESRGANer(scale=4, model_path=_ESRGAN_WEIGHTS, model=mdl, half=True)
        bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
        out, _ = up.enhance(bgr, outscale=4)
        big = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
        try:
            up.model.cpu()
            del up, mdl
            import torch

            torch.cuda.empty_cache()
        except Exception as _exc:
            _zyg_log.debug('esrgan vram release skipped: %s', _exc)
        return big.resize((W, H), Image.LANCZOS)
    except Exception as e:
        log(f'[scene] ESRGAN unavailable ({e}) — LANCZOS resize')
        return img.resize((W, H), Image.LANCZOS)


def shot_by_id_spec(spec: dict, sid: str) -> dict:
    for s in spec['shots']:
        if s['id'] == sid:
            return s
    raise KeyError(f'no shot {sid!r} in spec')


def _base_scale_for(spec: dict) -> dict:
    """Per-shot delivery-frame scale: the tightest zoom any window asks of that
    still. 1.0 means it is only ever seen whole. Capped at 2× (ESRGAN cost and
    VRAM), and computed from the SPEC alone so the hi-res base can be built
    before the timeline exists."""
    out = {s['id']: 1.0 for s in spec['shots']}
    charts = {s['id'] for s in spec['shots'] if s.get('kind') == 'map'}
    for s in spec['shots']:
        fx = s.get('fx', {}) or {}
        z = fx.get('kb_zoom')
        if fx.get('kb_keys'):
            cap = max(float(k['z']) for k in fx['kb_keys'])
        else:
            cap = max(z) if z else 1.0 + float(fx.get('kb_amount', 0.06))
        out[s['id']] = max(out[s['id']], cap)
    pull = spec.get('pullout') or {}
    if pull.get('shot_id') and pull.get('zoom'):
        out[pull['shot_id']] = max(out.get(pull['shot_id'], 1.0), max(pull['zoom']))
    return {k: (v if k in charts else min(v, 2.0)) for k, v in out.items()}


def _hires_path(still_path: str) -> str:
    return still_path[:-4] + '.hires.png'


class _env_overrides:
    """Temporarily set env knobs read by another module's function."""

    def __init__(self, **kv):
        self._kv = {k: (None if v is None else str(v)) for k, v in kv.items()}
        self._old = {}

    def __enter__(self):
        for k, v in self._kv.items():
            self._old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *_):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def _canon_lock(cid: str) -> tuple[str, str]:
    """(canon_phrase, canon_negative) — the pixel-derived appearance that matches
    the char's LoRA data. This is the wardrobe/identity LOCK: it goes into every
    shot's prompt so clothing cannot drift between shots of one scene."""
    try:
        from zyg_workflows import canon_service as CS

        return (CS.canon_phrase(cid) or '', CS.canon_negative(cid) or '')
    except Exception:
        return '', ''


def _render_shot_still(
    shot: dict, out_path: str, W: int, H: int, log_fn=None, continuity: dict | None = None
) -> str | None:
    log = log_fn or _log_noop
    kind = shot.get('kind', 'solo')
    seed = int(shot.get('seed', 7))
    if os.path.isfile(out_path) and not shot.get('force'):
        log(f'[scene] still exists, reusing: {os.path.basename(out_path)}')
        return out_path
    # Scene-level continuity: shared props/set clause + anti-drift negatives,
    # applied to every shot that opts in (continuity=True). Keeps the SAME
    # candle/journal/walls across cuts instead of per-shot prop lottery.
    cont = continuity if (continuity and shot.get('continuity')) else {}
    cont_props = (cont.get('props') or '').strip()
    cont_neg = (cont.get('negative') or '').strip()

    if kind == 'multichar':
        from zyg_workflows import arcane_multichar

        # region_actions EXTEND each character's canon person description with a
        # scene action. Raw region_prompts REPLACE it (a prompt without a person
        # noun renders an empty room — the porridge scene failed exactly so).
        region_prompts = shot.get('region_prompts')
        actions = shot.get('region_actions')
        if actions and not region_prompts:
            framing = shot.get('framing', 'waist-up')
            descs = [arcane_multichar._char_desc(c, shot=framing) for c in shot['char_ids']]
            acts = list(actions) + [''] * (len(descs) - len(actions))
            region_prompts = [(d['region_prompt'] + (f', {a}' if a else '')) for d, a in zip(descs, acts)]
        # Wardrobe/identity lock: each region actively repels its char's known
        # drift modes (canon_negative) + the scene's continuity negatives.
        region_negatives = shot.get('region_negatives')
        if not region_negatives:
            region_negatives = []
            for c in shot['char_ids']:
                _, cn = _canon_lock(c)
                region_negatives.append(', '.join(x for x in (cn, cont_neg) if x))
            if not any(region_negatives):
                region_negatives = None
        bg_prompt = shot.get('bg_prompt')
        if bg_prompt and cont_props:
            bg_prompt = f'{bg_prompt}, {cont_props}'
        return arcane_multichar.generate_multichar_still(
            shot['char_ids'],
            shot['scene_desc'],
            out_path,
            seed=seed,
            W=W,
            H=H,
            log_fn=log,
            shot=shot.get('framing', 'waist-up'),
            bg_prompt=bg_prompt,
            region_prompts=region_prompts,
            region_negatives=region_negatives,
        )

    if kind == 'scenery':
        from zyg_workflows import pipeline_environments

        return pipeline_environments.generate_scenery_2d(
            shot['scene_desc'],
            out_path,
            seed=seed,
            W=W,
            H=H,
            arcane=bool(shot.get('arcane', True)),
            log_fn=log,
        )

    # solo — the production episode path: bible package + generate_still;
    # the arcane restyle hook runs post-save for restyle characters.
    from zyg_workflows import character_bible_service
    from zyg_workflows import comfy_generation_service as cgs

    cid = shot['char_ids'][0]
    pkg = character_bible_service.load(cid)
    if not pkg:
        log(f'[scene] no bible for {cid}')
        return None
    # Identity + wardrobe lock. Without it SDXL drifts on period props (quill+
    # journal → a girl in a gown; priors invented a purple ruff doublet). The
    # canon phrase (pixel-derived, matches the LoRA data) IS the lock: it names
    # age, gender AND the exact clothing, so every shot wears the same costume.
    ident = pkg.get('identity') or {}
    age = ident.get('age')
    gender = str(ident.get('gender') or '').lower()
    noun = (
        'boy'
        if (gender == 'male' and isinstance(age, int) and age < 17)
        else 'man'
        if gender == 'male'
        else 'girl'
        if (gender == 'female' and isinstance(age, int) and age < 17)
        else 'woman'
        if gender == 'female'
        else 'person'
    )
    canon_phrase, canon_neg = _canon_lock(cid)
    subject = (
        f'{canon_phrase}, '
        if canon_phrase
        else (f'a {age} year old {noun}, ' if age else (f'a {noun}, ' if gender else ''))
    )
    gender_neg = (
        'woman, female, girl, dress, gown, bonnet'
        if gender == 'male'
        else 'man, male, boy, beard, moustache'
        if gender == 'female'
        else ''
    )
    scene_txt = shot['scene_desc'] + (f', {cont_props}' if cont_props else '')
    extra_neg = ', '.join(x for x in (gender_neg, canon_neg, cont_neg, shot.get('negative', '')) if x)
    ok, backend = cgs.generate_still(
        out_path,
        subject + scene_txt,
        width=W,
        height=H,
        steps=30,
        cfg=6.0,
        seed=seed,
        character_package=pkg,
        char_id=cid,
        model_family='sdxl',
        log_fn=log,
        enable_face_detailer=False,
        extra_negative=extra_neg,
    )
    if not ok:
        log(f'[scene] solo still failed ({backend}) for {cid}')
        return None
    return out_path
