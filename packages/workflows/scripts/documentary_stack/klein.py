# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Klein work: the FLUX.2 [klein] pathway, the bake-off inspection tab and
the training path.

Moved verbatim out of scripts/test_documentary_stack.py lines 1292-1778."""

# E402: the __file__ re-anchor has to run before the moved sections.
# ruff: noqa: E402

import os as _zyg_os

# test_klein_pathway needs any real file to stand in for an init image and
# spells it `os.path.join(CREWS, 'scripts', os.path.basename(__file__))`. One
# directory deeper that basename names a file that does not exist, and
# _pick_workflow then answers klein_txt2img instead of klein_edit_angle — a
# silently weaker test. Re-anchor the dunder to the original path rather than
# edit the moved line.
__file__ = _zyg_os.path.join(
    _zyg_os.path.dirname(_zyg_os.path.dirname(_zyg_os.path.abspath(__file__))),
    'test_documentary_stack.py',
)
del _zyg_os

import os
import tempfile

from .core import CREWS, check, skip


def test_klein_pathway():
    """FLUX.2 [klein] 4B is a first-class pathway, and cannot clear its 9B sibling.

    klein splits what KSampler bundles — seed on RandomNoise, steps on
    Flux2Scheduler, guidance on CFGGuider. Comfy accepts unknown keys on a node
    silently, so a sampler patch aimed at the wrong node produces a perfectly
    good image at the graph's baked-in seed and step count. Every assertion here
    is therefore on BEHAVIOUR (run the patch, read the overrides) rather than on
    the source reading correctly.
    """
    import json as _json

    try:
        from zyg_workflows import comfy_generation_service as cgs
    except Exception as exc:
        return skip('klein pathway', f'unimportable: {exc!r}')

    # ── family is registered ────────────────────────────────────────────
    check(
        'klein normalises to itself (not silently to flux)',
        cgs._normalize_model_family('klein') == 'klein',
        cgs._normalize_model_family('klein'),
    )
    check('an unknown family still falls back to flux', cgs._normalize_model_family('nonsense') == 'flux')

    # ── workflow routing ────────────────────────────────────────────────
    wf_t2i = cgs._pick_workflow(None, None, None, None, model_family='klein')
    check('klein txt2img routes to klein_txt2img', wf_t2i == 'klein_txt2img', wf_t2i)
    _img = os.path.join(CREWS, 'scripts', os.path.basename(__file__))  # any real file
    wf_edit = cgs._pick_workflow(None, _img, None, None, model_family='klein')
    check('klein with an init image routes to the edit graph', wf_edit == 'klein_edit_angle', wf_edit)

    # ── graphs are well formed and keep the shared node-ID contract ─────
    for name in ('klein_txt2img', 'klein_edit_angle'):
        p = os.path.join(CREWS, '_comfy_workflows', f'{name}.json')
        if not os.path.isfile(p):
            check(f'{name}.json exists', False, p)
            continue
        g = _json.load(open(p, encoding='utf-8'))
        dangling = [
            (k, i, v[0])
            for k, n in g.items()
            for i, v in (n.get('inputs') or {}).items()
            if isinstance(v, list) and v and v[0] not in g
        ]
        check(f'{name} has no dangling node references', not dangling, str(dangling)[:90])
        # The IDs generate_still patches blind: 10 model, 20/21 prompts,
        # 30 latent, 31 sampler, 50 save. A klein graph that renumbered these
        # would render, and ignore every parameter it was given.
        for nid, want in (
            ('10', 'UNETLoader'),
            ('11', 'CLIPLoader'),
            ('12', 'VAELoader'),
            ('20', 'CLIPTextEncode'),
            ('21', 'CLIPTextEncode'),
            ('30', 'EmptyFlux2LatentImage'),
            ('31', 'SamplerCustomAdvanced'),
            ('50', 'SaveImage'),
        ):
            got = (g.get(nid) or {}).get('class_type')
            check(f'{name} node {nid} is {want}', got == want, str(got))

    # ── the sampler patch reaches the real owners ──────────────────────
    g = _json.load(open(os.path.join(CREWS, '_comfy_workflows', 'klein_txt2img.json'), encoding='utf-8'))
    ov = {}
    cgs._patch_flux_sampler(g, ov, seed=98765, steps=7, cfg=4.25, is_schnell=False)
    check('seed lands on RandomNoise (32)', (ov.get('32') or {}).get('noise_seed') == 98765, str(ov.get('32')))
    check('steps land on Flux2Scheduler (33)', (ov.get('33') or {}).get('steps') == 7, str(ov.get('33')))
    check('cfg lands on CFGGuider (34)', (ov.get('34') or {}).get('cfg') == 4.25, str(ov.get('34')))
    # The failure this replaces: writing seed/steps/cfg onto 31 is accepted and inert.
    check('nothing is written to the SamplerCustomAdvanced node itself', '31' not in ov, str(ov.get('31')))

    # ── the KSampler families are untouched by the new branch ──────────
    qg = _json.load(open(os.path.join(CREWS, '_comfy_workflows', 'qwen_txt2img.json'), encoding='utf-8'))
    qov = {}
    cgs._patch_flux_sampler(qg, qov, seed=11, steps=13, cfg=2.5, is_schnell=False)
    check(
        'qwen still patches its KSampler at node 31',
        (qov.get('31') or {}).get('seed') == 11 and (qov.get('31') or {}).get('steps') == 13,
        str(qov.get('31')),
    )

    # ── distilled vs base is detected, not assumed ─────────────────────
    check(
        'the undistilled base is not treated as distilled',
        cgs.klein_is_distilled('flux-2-klein-base-4b.safetensors') is False,
    )
    check('the distilled 4b is detected', cgs.klein_is_distilled('flux-2-klein-4b.safetensors') is True)

    # ── licence: 4B cleared, 9B and FLUX.2 dev refused ─────────────────
    try:
        from zyg_workflows import licence_provenance as lp
    except Exception as exc:
        skip('klein licence registration', f'unimportable: {exc!r}')
        return
    for w, want in (
        ('flux-2-klein-base-4b.safetensors', 'cleared'),
        ('flux-2-klein-4b.safetensors', 'cleared'),
        ('qwen_3_4b.safetensors', 'cleared'),
        ('flux2-vae.safetensors', 'cleared'),
        ('flux-2-klein-base-9b.safetensors', 'non_commercial'),
        ('flux2_dev_fp8mixed.safetensors', 'non_commercial'),
    ):
        got = (lp.classify_weight(w) or {}).get('status')
        check(f'licence: {w} -> {want}', got == want, str(got))

    # ── klein must NOT be caught by the FLUX render pause ───────────────
    # The pause exists because flux1-dev is non-commercial. klein is Apache-2.0,
    # so a pause that also stopped klein would block the migration it enables.
    src = open(os.path.join(CREWS, 'comfy_generation_service.py'), encoding='utf-8').read()
    check(
        'the licence pause is scoped to the flux family only',
        "if _normalize_model_family(model_family) == 'flux':" in src,
    )


def test_bakeoff_inspection_tab():
    """The bake-off is reachable from the Inspections page, and the page still parses.

    inspection.html is ONE 119 KB inline script. A syntax error anywhere in it
    blanks every tab — Inspections, Videos, Mesh, Pictures, Voices — not just
    the new one, and it does so silently: the server keeps serving 200s and the
    page renders an empty shell. That is the failure this guards, which is why
    the JS is actually parsed rather than grepped.
    """
    import re as _re
    import shutil as _sh
    import subprocess as _sp

    html_p = os.path.join(CREWS, 'inspection.html')
    if not os.path.isfile(html_p):
        return skip('bake-off tab', 'inspection.html not found')
    html = open(html_p, encoding='utf-8').read()

    # every wiring point — a tab that is declared but not switched to is dead UI
    for what, needle in (
        ('tab button', 'data-view="bakeoff"'),
        ('view container', 'id="view-bakeoff"'),
        ('switchView accepts it', "v!=='bakeoff'"),
        ('switchView shows it', "view-bakeoff').style.display"),
        ('loader is called', 'loadBakeoffs()'),
        ('deep link #bakeoff', "h==='bakeoff'"),
    ):
        check(f'bake-off tab: {what} present', needle in html, needle)

    # the whole inline script must parse
    blocks = _re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, _re.S)
    check('inspection.html has exactly one inline script block', len(blocks) == 1, str(len(blocks)))
    node = _sh.which('node')
    if not node:
        skip('inspection.html JS parses', 'node unavailable')
    elif blocks:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as fh:
            fh.write(blocks[0])
            jp = fh.name
        r = _sp.run([node, '--check', jp], capture_output=True, text=True, timeout=60)
        os.unlink(jp)
        check('inspection.html inline JS parses', r.returncode == 0, r.stderr[:160])

    # ── every scrolling tab must actually scroll ───────────────────────
    # #views is overflow:hidden. A view that omits overflow-y:auto renders its
    # full content and CLIPS everything past the fold, with no scrollbar to hint
    # that more exists — the bake-off tab shipped that way and showed 2 of 8
    # prompts. Without flex:1 it also collapses to content width. Checked for
    # ALL block-scrolling views, not just the new one, because the next tab
    # someone adds will hit exactly this.
    holder = _re.search(r'#views\{([^}]*)\}', html)
    check(
        '#views is still the overflow:hidden flex pane this rule assumes',
        bool(holder) and 'overflow:hidden' in holder.group(1),
        holder.group(1) if holder else 'not found',
    )
    for view in ('videos', 'pictures', 'bakeoff'):
        m = _re.search(r'#view-' + view + r'\{([^}]*)\}', html)
        if not m:
            check(f'#view-{view} has a CSS rule', False)
            continue
        rule = m.group(1).replace(' ', '')
        check(f'#view-{view} can scroll (overflow-y:auto)', 'overflow-y:auto' in rule, rule[:70])
        check(f'#view-{view} fills the pane (flex:1)', 'flex:1' in rule, rule[:70])

    # server side
    try:
        from zyg_dashboard import kanban_server as ks
    except Exception as exc:
        skip('bake-off API', f'kanban_server unimportable: {exc!r}')
        return
    check(
        'the /inspect/api/bakeoffs route is registered',
        "'/inspect/api/bakeoffs'" in open(os.path.join(CREWS, 'kanban_server.py'), encoding='utf-8').read(),
    )
    try:
        data = ks._api_bakeoffs()
    except Exception as exc:
        check('_api_bakeoffs runs', False, repr(exc))
        return
    check('_api_bakeoffs returns a runs list', isinstance(data.get('runs'), list))
    runs = data.get('runs') or []
    if not runs:
        skip('bake-off run shape', 'no bake-off runs on disk yet')
        return
    r0 = runs[0]
    for k in ('id', 'when', 'pathways', 'prompts'):
        check(f'run carries {k}', k in r0)
    check(
        'run has at least two pathways to compare', len(r0['pathways']) >= 2, str([p['name'] for p in r0['pathways']])
    )
    # Every image path must be root-prefixed and relative: /inspect/media rejects
    # absolute paths and anything with '..', so an unprefixed path would render
    # as a broken image with a 404 nobody looks at.
    bad = []
    for pr in r0['prompts']:
        for name, cell in (pr.get('cells') or {}).items():
            p = cell.get('path') or ''
            if p and (not p.startswith(('out/', 'dout/', 'drun/')) or p.startswith('/') or '..' in p):
                bad.append(f'{pr["tag"]}/{name}={p}')
    check('every image path is a media-root-relative path', not bad, str(bad[:3]))
    # the uncached mean must exclude cache hits, or the headline flatters a re-run
    for p in r0['pathways']:
        if p.get('cached'):
            check(
                f'{p["name"]}: uncached mean differs from raw mean when a cache hit exists',
                p.get('mean_uncached') != p.get('mean'),
                f'raw={p.get("mean")} uncached={p.get("mean_uncached")}',
            )


def test_klein_training_path():
    """A 'klein' LoRA trains on FLUX.2 klein-4B — never silently on flux1-dev.

    The failure this guards is quiet: _normalize_train_family used to map any
    unknown family to 'flux', so a klein request would have trained a NEW
    flux1-dev derivative (non-commercial) under a klein label, shared
    vae_cache_flux_1024 with real FLUX latents, and reported success. Every
    assertion here runs the real writer / resolver and reads what it emitted.
    """
    import json as _json

    try:
        from zyg_workflows import lora_trainer_service as lts
    except Exception as exc:
        return skip('klein training path', f'unimportable: {exc!r}')

    check('klein normalises to itself in the trainer', lts._normalize_train_family('klein') == 'klein')
    check('unknown families still fall back to flux', lts._normalize_train_family('nope') == 'flux')
    check(
        'klein weights dir is family-named', lts._family_lora_weights_dir('/o', 'klein').endswith('lora-weights-klein')
    )
    check(
        'klein status file is family-scoped', lts._status_path_for('/o', 'klein').endswith('training_status_klein.json')
    )

    # ── the emitted SimpleTuner config, on a real TrainingJob ────────────
    with tempfile.TemporaryDirectory() as td:
        job = lts.TrainingJob('0123456789ab', td, 'ZYG_CHAR_012345', 100, model_family='klein', output_root=td)
        cfg_dir = os.path.join(job.output_dir, 'st_config_klein')
        os.makedirs(cfg_dir)
        lts._write_st_config_klein(job, cfg_dir, train_path='/base/klein')
        lts._write_st_multidatabackend(job, cfg_dir, model_family='klein')
        c = _json.load(open(os.path.join(cfg_dir, 'config.json')))
        b = _json.load(open(os.path.join(cfg_dir, 'multidatabackend.json')))
        check(
            'config targets SimpleTuner family flux2', c.get('--model_family') == 'flux2', str(c.get('--model_family'))
        )
        check(
            'config targets the 4B BASE flavour (not 9b, not distilled)',
            c.get('--model_flavour') == 'klein-4b',
            str(c.get('--model_flavour')),
        )
        check(
            'config points at the klein base, not flux1-dev',
            c.get('--pretrained_model_name_or_path') == '/base/klein'
            and 'flux1' not in c.get('--pretrained_model_name_or_path', ''),
        )
        check(
            'config trains bf16, unquantised',
            c.get('--base_model_precision') == 'no_change' and c.get('--text_encoder_1_precision') == 'no_change',
        )
        check('no FLUX.1 guidance keys (klein has no guidance embeddings)', not any('flux_guidance' in k for k in c))
        check(
            'no text-encoder override (must load the bundled Qwen3)',
            '--pretrained_text_encoder_model_name_or_path' not in c and '--text_encoder_2_precision' not in c,
        )
        check(
            'resolution-dependent shift, not a static one',
            c.get('--flow_schedule_auto_shift') is True and '--flow_schedule_shift' not in c,
        )
        check(
            'validation carries a negative prompt (true CFG on the base)', bool(c.get('--validation_negative_prompt'))
        )
        check(
            'same rank/alpha/lr schedule as the FLUX and Qwen writers (controlled comparison)',
            c.get('--lora_rank') == int(os.environ.get('ZYG_LORA_RANK', '64'))
            and c.get('--learning_rate') == '1e-4'
            and c.get('--lr_scheduler') == 'cosine',
        )
        check('deprecated offload keys stripped', not any(k in c for k in lts._DEPRECATED_ST_CONFIG_KEYS))
        check('output dir is lora-weights-klein', c.get('--output_dir', '').endswith('lora-weights-klein'))
        check(
            'VAE/text caches are klein-scoped (never shared with FLUX latents)',
            'vae_cache_klein' in b[0]['cache_dir_vae'] and 'text_cache_klein' in b[1]['cache_dir'],
            f'{b[0]["cache_dir_vae"].split("/")[-1]} {b[1]["cache_dir"].split("/")[-1]}',
        )

        # ── checkpoint discovery never lets klein claim the legacy dir ─────
        legacy = os.path.join(job.output_dir, 'lora-weights')
        os.makedirs(legacy)
        open(os.path.join(legacy, 'pytorch_lora_weights.safetensors'), 'wb').write(b'x' * 10)
        check(
            'klein never claims the un-suffixed legacy (FLUX-era) weights dir',
            lts._find_latest_checkpoint(job.output_dir, 'klein') is None,
        )
        check(
            '...and a legacy-dir file is not a klein match',
            lts._checkpoint_matches_family(
                os.path.join(legacy, 'pytorch_lora_weights.safetensors'), job.output_dir, 'klein'
            )
            is False,
        )
        kdir = lts._family_lora_weights_dir(job.output_dir, 'klein')
        os.makedirs(kdir, exist_ok=True)
        kp = os.path.join(kdir, 'pytorch_lora_weights.safetensors')
        open(kp, 'wb').write(b'y' * 10)
        check('a klein export in its own dir IS found', lts._find_latest_checkpoint(job.output_dir, 'klein') == kp)

    # ── base-weight completeness is a WEIGHTS check, not a directory check ─
    with tempfile.TemporaryDirectory() as td:
        for sub in ('transformer', 'text_encoder', 'vae', 'tokenizer'):
            os.makedirs(os.path.join(td, sub))
        open(os.path.join(td, 'model_index.json'), 'w').write('{}')
        open(os.path.join(td, 'transformer', 'config.json'), 'w').write('{}')
        check(
            'a diffusers tree with config.json but no weights is INCOMPLETE', lts._klein_diffusers_complete(td) is False
        )
    check(
        'the real klein base is complete on this box',
        lts._klein_diffusers_complete(lts._resolve_klein_train_path()),
        lts._resolve_klein_train_path(),
    )

    # ── family helpers and the bible ─────────────────────────────────────
    try:
        from zyg_workflows import character_lora_family as clf

        check(
            'klein inferred from its weights dir',
            clf.infer_lora_family_from_path('/x/lora-weights-klein/a.safetensors') == 'klein',
        )
        check(
            'a klein path does not match the flux family',
            clf.lora_path_matches_family('/x/lora-weights-klein/a.safetensors', 'flux') is False,
        )
        check(
            'a flux path does not match the klein family',
            clf.lora_path_matches_family('/x/lora-weights-flux/a.safetensors', 'klein') is False,
        )
    except Exception as exc:
        check('character_lora_family importable', False, repr(exc))

    try:
        src = open(os.path.join(CREWS, 'character_bible_service.py'), encoding='utf-8').read()
        check(
            'update_lora treats klein as a COMPANION key (never clobbers the FLUX primary)',
            "if mf not in ('qwen', 'klein'):\n        cond['model_family'] = mf" in src
            and "cond[f'{mf}_lora_path'] = path_ok" in src,
        )
    except Exception as exc:
        check('character_bible_service importable', False, repr(exc))

    # ── the sheet pipeline must never pair klein with a FLUX twin ────────
    csp = open(os.path.join(CREWS, 'contact_sheet_pipeline.py'), encoding='utf-8').read()
    check('dual-LoRA twin is restricted to flux<->sdxl', "if (dual and model_family in ('flux', 'sdxl')" in csp)
    check('the sheet writes klein_lora_path for klein', "'klein_lora_path' if mf == 'klein'" in csp)

    # ── render side: a staged klein LoRA routes to the locked graph ──────
    try:
        from zyg_workflows import comfy_generation_service as cgs

        wf = cgs._pick_workflow(None, None, None, 'zygchar_x_klein.safetensors', model_family='klein')
        check('staged klein LoRA routes to klein_character_locked', wf == 'klein_character_locked', wf)
        g = _json.load(open(os.path.join(CREWS, '_comfy_workflows', 'klein_character_locked.json')))
        check('locked graph carries LoraLoader at node 13', (g.get('13') or {}).get('class_type') == 'LoraLoader')
        check('locked graph feeds the LoRA model into CFGGuider', g['34']['inputs']['model'] == ['13', 0])
        check(
            'locked graph feeds the LoRA clip into both encoders',
            g['20']['inputs']['clip'] == ['13', 1] and g['21']['inputs']['clip'] == ['13', 1],
        )
        check(
            'locked graph keeps the sampler ids the patch routes to',
            all(
                g.get(n, {}).get('class_type') == t
                for n, t in (
                    ('31', 'SamplerCustomAdvanced'),
                    ('32', 'RandomNoise'),
                    ('33', 'Flux2Scheduler'),
                    ('34', 'CFGGuider'),
                )
            ),
        )
        # the no-LoRA rewire must leave a klein graph whole
        import copy

        g2 = copy.deepcopy(g)
        cgs._flux_rewire_without_lora(g2)
        dangling = [
            (k, i)
            for k, n in g2.items()
            for i, v in n['inputs'].items()
            if isinstance(v, list) and v and v[0] not in g2
        ]
        check('rewiring the locked graph without a LoRA leaves no dangling refs', not dangling, str(dangling))
        src = open(os.path.join(CREWS, 'comfy_generation_service.py'), encoding='utf-8').read()
        check('generate_still reads klein_lora_path for klein', "_lora_p = cond_l.get('klein_lora_path')" in src)
        check(
            'klein_character_locked gets its lora_name override',
            "workflow_name == 'klein_character_locked' and '13' in workflow" in src,
        )
    except Exception as exc:
        check('comfy_generation_service klein LoRA wiring', False, repr(exc))

    # ── alpha stamp covers a MIXED-key export, per module, idempotently ───
    # ComfyUI applies a module with no .alpha at scale 1.0 = 2x the trained
    # strength at rank 64 / alpha 32. SimpleTuner's flux2 export mixes PEFT
    # (.lora_A) and diffusers (.lora.down) key forms in one file; a stamper
    # that knows only one form, or that stops at the first .alpha it sees,
    # ships a half-stamped adapter that looks stamped.
    try:
        import torch as _t
        from safetensors.torch import save_file as _sf, load_file as _lf

        with tempfile.TemporaryDirectory() as td:
            _json.dump({'lora_rank': 64, 'lora_alpha': 32.0}, open(os.path.join(td, 'simpletuner_config.json'), 'w'))
            p = os.path.join(td, 'pytorch_lora_weights.safetensors')
            r = 64
            _sf(
                {
                    'transformer.transformer_blocks.0.attn.to_q.lora.down.weight': _t.zeros(r, 8),
                    'transformer.transformer_blocks.0.attn.to_q.lora.up.weight': _t.zeros(8, r),
                    'transformer.single_transformer_blocks.0.attn.to_qkv_mlp_proj.lora_A.weight': _t.zeros(r, 8),
                    'transformer.single_transformer_blocks.0.attn.to_qkv_mlp_proj.lora_B.weight': _t.zeros(8, r),
                    # one module pre-stamped: the old any-key check would stop here
                    'transformer.transformer_blocks.1.attn.to_k.lora.down.weight': _t.zeros(r, 8),
                    'transformer.transformer_blocks.1.attn.to_k.lora.up.weight': _t.zeros(8, r),
                    'transformer.transformer_blocks.1.attn.to_k.alpha': _t.tensor(32.0),
                },
                p,
                metadata={'format': 'pt'},
            )
            ok1 = lts.stamp_lora_alpha(p)
            d = _lf(p)
            alphas = sorted(k for k in d if k.endswith('.alpha'))
            check('stamper returns True on a partially-stamped mixed-form file', ok1 is True)
            check(
                'stamper stamps the diffusers .lora.down form', 'transformer.transformer_blocks.0.attn.to_q.alpha' in d
            )
            check(
                'stamper stamps the PEFT .lora_A form',
                'transformer.single_transformer_blocks.0.attn.to_qkv_mlp_proj.alpha' in d,
            )
            check('every module has exactly one alpha (3 modules -> 3 alphas)', len(alphas) == 3, str(alphas))
            check(
                'stamped alpha is the trained value',
                float(d['transformer.transformer_blocks.0.attn.to_q.alpha']) == 32.0,
            )
            ok2 = lts.stamp_lora_alpha(p)
            d2 = _lf(p)
            check(
                're-stamping is a no-op that still reports stamped',
                ok2 is True and sorted(k for k in d2 if k.endswith('.alpha')) == alphas,
            )
    except Exception as exc:
        check('alpha stamper on a mixed-form export', False, repr(exc))

    # ── licence: the staged filename resolves to klein -> Apache-2.0 ──────
    try:
        from zyg_workflows import licence_provenance as lp

        fams, how = lp.lora_base_families('zygchar_0123456789ab_klein.safetensors')
        check(
            'staged klein LoRA name resolves to the klein family by convention',
            fams == ['klein'] and how == 'registry-convention',
            f'{fams} {how}',
        )
        c = lp.classify_weight('zygchar_0123456789ab_klein.safetensors', kind='lora')
        check('...and classifies as cleared', c.get('status') == 'cleared', str(c.get('status')))
    except Exception as exc:
        check('licence lineage for klein', False, repr(exc))
