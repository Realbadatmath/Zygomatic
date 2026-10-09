# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The FLUX inpaint contract and live run, the repair wiring, the CPU core ceiling,
the OCR typography judges and the strip pass over real prompts."""

import glob
import json
import os

from .core import (  # noqa: F401  shared harness state, used by the moved sections
    FULL,
    _ast,
    _zyg_log,
    check,
    paths,
    skip,
)


def test_flux_inpaint_contract():
    """Static guards on the FLUX strategy — these run WITHOUT a GPU.

    The fast suite cannot load a 24 GB model, so it cannot execute
    _flux_inpaint. That is exactly how a production path rots unnoticed, so the
    two bugs that actually bit are pinned here by inspection instead:

    * ``FluxInpaintPipeline.from_pipe(pipe)`` unifies devices with a ``.to()``,
      which drags T5-XXL (~9 GB, deliberately left in CPU RAM by the production
      loader) onto the card. Measured: 18.2 GB free -> 0.1 GB and an OOM inside
      torch's ``convert``, on a crop needing about 2 GB.
    * ``encode_prompt`` takes ONE device for both text towers, so with T5 on the
      CPU and CLIP on the GPU it sends cuda input ids to a cpu module and
      raises. Each tower must be encoded where it lives.

    The real execution test is test_flux_inpaint_live, which needs --full.
    """
    src = open('typography_repair.py', encoding='utf-8').read()
    body = src[src.find('def _flux_inpaint') : src.find('def _telea_inpaint')]
    check('FLUX strategy exists', bool(body))
    # Scan CODE only. The function's own comment explains why from_pipe is
    # wrong, and scanning the comment made this check fire on the fix.
    code = '\n'.join(ln.split('#', 1)[0] for ln in body.split('\n'))
    check(
        'does NOT use from_pipe (it drags T5 onto the GPU)',
        'from_pipe' not in code,
        'from_pipe unifies devices and OOMs',
    )
    check('builds the inpaint pipeline from existing components', 'FluxInpaintPipeline(**pipe.components)' in body)
    check('encodes each text tower on the device it lives on', '_t5_dev' in body and '_clip_dev' in body)
    check('works on a crop, not the whole frame', 'crop(' in body)
    check('caches the constant prompt embedding', '_EMB_CACHE' in body)


def test_flux_inpaint_live():
    """Actually run the FLUX strategy. Needs --full and a GPU.

    Without this, `pipe=None` everywhere means _flux_inpaint is never executed
    by any test — the fast suite would stay green through a diffusers API change
    or another device bug. It SKIPs (never silently passes) when it cannot run.
    """
    if not FULL:
        skip('FLUX inpaint (live)', 'needs --full (loads a 24 GB model)')
        return
    try:
        import torch
        from zyg_workflows import typography_ocr as tocr
        from zyg_workflows import typography_repair as trep
    except Exception as exc:
        skip('FLUX inpaint (live)', f'unimportable: {exc!r}')
        return
    if not torch.cuda.is_available():
        skip('FLUX inpaint (live)', 'no CUDA')
        return
    free_gb = torch.cuda.mem_get_info()[0] / 1024**3
    if free_gb < 28:
        skip('FLUX inpaint (live)', f'only {free_gb:.1f} GB free, needs ~28')
        return
    if not tocr.available():
        skip('FLUX inpaint (live)', 'OCR judge unavailable')
        return

    fx = 'tests/golden/typography_labels.json'
    if not os.path.exists(fx):
        skip('FLUX inpaint (live)', 'no label fixture')
        return
    meta = json.load(open(fx))
    base = f'data/output/clips/{meta["_source_run"]}/flux_images'
    dirty = [
        n for n, v in meta['labels'].items() if v == 'yes' and os.path.exists(os.path.join(base, n)) and '_4x' not in n
    ][:3]
    if not dirty:
        skip('FLUX inpaint (live)', 'labelled frames no longer on disk')
        return

    import shutil
    import tempfile
    from diffusers import FluxPipeline
    from PIL import Image

    model = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
    if not os.path.isdir(model):
        skip('FLUX inpaint (live)', 'flux1-schnell not on this box')
        return
    # Production memory layout: transformer+CLIP+VAE on cuda, T5-XXL on cpu.
    pipe = FluxPipeline.from_pretrained(
        model, torch_dtype=torch.bfloat16, local_files_only=True, low_cpu_mem_usage=True
    )
    pipe.transformer.to('cuda')
    pipe.text_encoder.to('cuda')
    pipe.vae.to('cuda')
    try:
        pipe.enable_vae_tiling()
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    pipe.set_progress_bar_config(disable=True)
    check(
        'T5 stays on the CPU (the layout the OOM bug came from)',
        str(next(pipe.text_encoder_2.parameters()).device) == 'cpu',
    )

    ran_flux = cleared = 0
    try:
        with tempfile.TemporaryDirectory() as td:
            for n in dirty:
                dst = os.path.join(td, n)
                shutil.copy2(os.path.join(base, n), dst)
                r = trep.repair(dst, None, pipe=pipe, seed=11)
                trail = ' '.join(r.get('trail') or [])
                if 'flux:' in trail:
                    ran_flux += 1
                if r['repaired']:
                    cleared += 1
                    check(
                        f'{n}: repaired frame still opens',
                        Image.open(dst).size == Image.open(os.path.join(base, n)).size,
                    )
    finally:
        del pipe
        import gc

        gc.collect()
        torch.cuda.empty_cache()

    # The point of this test: prove the branch EXECUTED, not merely that
    # repair() returned something the classical fallback could have produced.
    check(f'the FLUX strategy actually executed ({len(dirty)} frames)', ran_flux > 0, f'flux ran on {ran_flux}')
    check('FLUX path clears real lettering', cleared > 0, f'{cleared} cleared')


def test_repair_wiring():
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    check('repair is wired into the ladder', 'typography_repair as _trep_sch' in src)
    i_rep = src.find('_trep_sch.repair(')
    i_flag = src.find('SHIPPED FLAGGED after')
    check('repair is attempted BEFORE the slot is reported flagged', 0 < i_rep < i_flag, f'{i_rep} < {i_flag}')
    # Textual order proves nothing here: _typography_post_pass is DEFINED
    # earlier in the file but RUNS later, after the worker has stood down. What
    # matters is which function the call sits in — _generate_one still holds the
    # loaded pipe; the sweep does not.
    tree = _ast.parse(src)
    holder = ''
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.FunctionDef):
            continue
        for sub in _ast.walk(node):
            if (
                isinstance(sub, _ast.Call)
                and getattr(sub.func, 'attr', '') == 'repair'
                and getattr(getattr(sub.func, 'value', None), 'id', '') == '_trep_sch'
            ):
                inner = [
                    f.name
                    for f in _ast.walk(node)
                    if isinstance(f, _ast.FunctionDef) and f is not node and any(c is sub for c in _ast.walk(f))
                ]
                holder = inner[0] if inner else node.name
    check(
        'repair runs where FLUX is still loaded (not in the 3.6 sweep)',
        holder == '_generate_one',
        f'called from {holder!r}',
    )
    check('a successful repair clears the typography issue', "if 'typography' not in _i" in src)
    check(
        'repair attempts and successes are counted',
        "_ladder_stats['repair_tried']" in src and "_ladder_stats['repair_ok']" in src,
    )
    check('repair can be switched off', 'ZYG_SCHOLARLY_TYPO_REPAIR' in src)


def test_cpu_core_ceiling():
    """No module may raise the CPU ceiling from inside.

    CPU affinity is inherited, so pinning the process tree once caps everything
    below it — but a process can set its OWN mask WIDER than the one it
    inherited, and four places did, each hardcoding 21 cores:

        crewai_web_gui.py:133   os.sched_setaffinity(0, set(range(21)))
        vram_manager.py:414     os.sched_setaffinity(comfy_pid, set(range(21)))
        stage_runner.py:1583    taskset -c 0-20
        stage_runner.py:1938    taskset -c 0-20

    The first runs at import, so every process that imported the GUI widened
    itself back to 21 cores. Demonstrated: a python inheriting 20 cores reports
    21 immediately after that call. One number, in cpu_cap, is the fix.
    """
    import re as _re

    try:
        from zyg_workflows import cpu_cap
    except Exception as exc:
        check('cpu_cap module exists', False, repr(exc))
        return
    check(
        'default ceiling is 20 cores',
        len(cpu_cap.cores()) == 20,
        f'{len(cpu_cap.cores())} cores from spec {cpu_cap.spec()!r}',
    )
    check('ceiling never exceeds the box', max(cpu_cap.cores()) < (os.cpu_count() or 1))
    check(
        'taskset prefix uses the same spec',
        cpu_cap.taskset_prefix()[-1] == cpu_cap.spec() if cpu_cap.taskset_prefix() else True,
    )

    old = os.environ.get('ZYG_CPU_CORES')
    try:
        os.environ['ZYG_CPU_CORES'] = '0-7'
        check('ZYG_CPU_CORES overrides the default', len(cpu_cap.cores()) == 8, f'{len(cpu_cap.cores())} cores')
    finally:
        if old is None:
            os.environ.pop('ZYG_CPU_CORES', None)
        else:
            os.environ['ZYG_CPU_CORES'] = old

    # No source file may pin cores by hand any more.
    aff = _re.compile(r'sched_setaffinity\s*\(\s*[^,]+,\s*set\(range\(')
    tsk = _re.compile(r"""['"]-c['"]\s*,\s*['"]\d+-\d+['"]|taskset\s+-c\s+\d+-\d+""")
    offenders = []
    for f in glob.glob('*.py'):
        if f == 'cpu_cap.py':
            continue
        try:
            raw = open(f, encoding='utf-8').readlines()
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        # Strip comments first: a comment that merely MENTIONS cpu_cap must not
        # grant the line immunity. That is what let the mutation through when
        # this check was first written.
        code = [ln.split('#', 1)[0] for ln in raw]
        for i, ln in enumerate(code):
            for rx, what in ((aff, 'sched_setaffinity(range(...))'), (tsk, 'hardcoded taskset -c')):
                if not rx.search(ln):
                    continue
                # Only a literal inside an `except:` fallback is allowed.
                prev = [c.strip() for c in code[max(0, i - 3) : i] if c.strip()]
                if any(c.startswith('except') for c in prev):
                    continue
                offenders.append(f'{f}:{i + 1} {what}')
    check('no module hardcodes a core range outside cpu_cap', not offenders, '; '.join(offenders[:3]))
    check(
        'the GUI pins itself through cpu_cap',
        'cpu_cap.apply_to_self()' in open('crewai_web_gui.py', encoding='utf-8').read(),
    )


def test_typography_ocr_judge():
    """The OCR judge must agree with the GPU judge it replaces, on real frames.

    Ground truth: tests/golden/typography_labels.json — 48 frames from scholarly
    run 85f0659c labelled by Qwen3-VL, 12 with lettering. The OCR judge exists
    because neither vision judge could answer in production: the local one needs
    14 GB and Stage 3.5 runs with FLUX resident (5.9 GB free), and the Anthropic
    fallback returned HTTP 400 "credit balance is too low" on every frame. A
    gate whose judges cannot run flags nothing, and a ladder that is never
    asked to fix anything converges 100% of the time.
    """
    fx = 'tests/golden/typography_labels.json'
    if not os.path.exists(fx):
        skip('OCR judge', 'no label fixture')
        return
    try:
        from zyg_workflows import typography_ocr as tocr
    except Exception as exc:
        skip('OCR judge', f'typography_ocr unimportable: {exc!r}')
        return
    if not check('OCR engine is available', tocr.available()):
        return

    labels = json.load(open(fx))['labels']
    run = json.load(open(fx))['_source_run']
    base = f'data/output/clips/{run}/flux_images'
    have = [(n, v) for n, v in labels.items() if os.path.exists(os.path.join(base, n))]
    if len(have) < 20:
        skip('OCR judge vs labels', f'only {len(have)} labelled frames still on disk')
        return

    tp = fp = fn = tn = 0
    contract_ok = True
    for name, lab in have:
        res = tocr.judge(os.path.join(base, name))
        if res is None:
            contract_ok = False
            continue
        ok, reason, boxes = res
        pred = not ok
        if pred:
            # A flag must quote what it read and carry a box, or nobody can check it.
            if 'reads' not in reason or not boxes:
                contract_ok = False
            for b in boxes:
                if not (len(b) == 4 and all(0 <= c <= 1000 for c in b)):
                    contract_ok = False
        if lab == 'yes' and pred:
            tp += 1
        elif lab == 'yes':
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1

    n = tp + fp + fn + tn
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    check(
        f'OCR judge agrees with Qwen3-VL on {n} real frames',
        prec >= 0.90 and rec >= 0.90,
        f'precision={prec:.2f} recall={rec:.2f} (TP{tp} FP{fp} FN{fn} TN{tn})',
    )
    check('every flag quotes its text and carries a 0-1000 bbox', contract_ok)
    check(
        'a clean frame returns ok with no boxes',
        any(tocr.judge(os.path.join(base, nm)) == (True, '', []) for nm, lb in have if lb == 'no'),
    )


def test_typography_judge_order():
    """OCR must be asked FIRST — it is the only judge that can run in-loop."""
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    i_ocr = src.find('import typography_ocr as _tocr')
    i_qwen = src.find('_q_res = _vlm_text_gate_qwen(image_path)')
    i_api = src.find("_tk = os.environ.get('ANTHROPIC_API_KEY', '')")
    check('OCR judge is wired into the text gate', i_ocr > 0)
    check('OCR is tried before the GPU judge', 0 < i_ocr < i_qwen, f'{i_ocr}<{i_qwen}')
    check('OCR is tried before the paid API', 0 < i_ocr < i_api, f'{i_ocr}<{i_api}')
    check(
        'a permanent API failure is latched, not retried per frame', '_tx_api_dead' in src and 'credit balance' in src
    )
    check('the API is skipped once it is known dead', 'if not _tk or _tx_api_dead[0]:' in src)
    check('the post-render sweep can also run without a GPU or an API', '_have_ocr' in src)
    # Anatomy and typography are independent checks. An unreadable ANATOMY
    # answer used to `return True, ''`, which skipped the typography gate for
    # that frame — measured as 5 gated attempts but only 4 typography checks,
    # the missing one being exactly the frame with the empty anatomy verdict.
    i_nov = src.find('unreviewed, still checking typography')
    check(
        'an unreadable anatomy verdict still checks typography',
        i_nov > 0 and 'return _vlm_text_gate(image_path' in src[i_nov : i_nov + 1600],
        'no-verdict branch must not short-circuit the text gate',
    )


def test_strip_against_real_prompts():
    """Run the stripper over every real prompt this box has ever rendered.

    Hand-written examples are not a corpus. Four short synthetic prompts made
    the stripper look like it collapsed everything to one generic sentence;
    against the 800-odd prompts in data/output it collapsed 5%. The opposite
    error is just as easy, so the check runs on what was actually shipped.
    """
    import ast as _a
    import re as _re

    ns = {}
    full = open('pipeline_scholarly.py', encoding='utf-8').read()
    for node in _a.parse(full).body:
        if (isinstance(node, _a.FunctionDef) and node.name == '_strip_written_subject') or (
            isinstance(node, _a.Assign) and getattr(node.targets[0], 'id', '') == '_WRITTEN_NOUNS'
        ):
            exec(compile(_a.Module([node], []), '<h>', 'exec'), ns)  # noqa: S102  AST subset lifted from a source file shipped in this repo, never from input
    strip, NOUNS = ns['_strip_written_subject'], ns['_WRITTEN_NOUNS']
    doc = _re.compile(r'(?i)\b(?:' + NOUNS + r')\b')

    prompts, seen = [], set()
    for f in glob.glob('data/output/clips/*/flux_images/flux_manifest.json'):
        try:
            d = json.load(open(f))
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        for im in d.get('images', []):
            pr = im.get('prompt') or ''
            if pr and doc.search(pr) and pr not in seen:
                seen.add(pr)
                prompts.append(pr)
    if len(prompts) < 50:
        skip('stripper corpus', f'only {len(prompts)} real prompts on this box')
        return

    resid, stub, dangling, outs, variants = [], 0, 0, set(), set()
    dre = _re.compile(r'(?i)(^|,\s*)(an?|the|his|her|their|two|several)\s*(,|$)')
    for pr in prompts:
        head = strip(pr).split(', nothing in frame')[0]
        outs.add(head)
        if doc.search(head):
            resid.append((pr, head))
        if 'faces and hands of the people' in head:
            stub += 1
            variants.add(head)
        if dre.search(head):
            dangling += 1

    n = len(prompts)
    # The one thing it must never do: leave the written object in the prompt.
    check(f'no written noun survives the strip ({n} real prompts)', not resid, resid[0][1][:80] if resid else '')
    # It must not answer every flagged slot with the same picture.
    check('stub fallback stays rare', stub <= n * 0.10, f'{stub}/{n}')
    check(
        'stub fallback varies with the scene',
        stub == 0 or len(variants) >= 5,
        f'{len(variants)} variants for {stub} stubs',
    )
    check(
        'the style suffix is preserved', all('photorealistic' in strip(pr) for pr in prompts if 'photorealistic' in pr)
    )
    check('almost no dangling determiners', dangling <= 2, f'{dangling}/{n}')
    check('"signs of X" is not treated as signage', not doc.search('showing signs of age and weather'))
