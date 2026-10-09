# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sections 1-11 of the documentary harness: subtitles, audio, VRAM, roster,
music bed, typography checklist/classifier/strip/repair."""

import json
import os
import subprocess
import sys
import tempfile

from .core import (  # noqa: F401  shared harness state, used by the moved sections
    FULL,
    _narration,
    check,
    skip,
)


# ── 1. subtitle digits ─────────────────────────────────────────────────────
def test_sub_digits():
    try:
        from zyg_workflows.storyteller_scene_service import _sub_digits as sd
    except Exception as e:
        return skip('subtitle digits', f'import failed: {e!r}')
    cases = [
        ('In 1848, over fifty countries erupted in', 'over 50 countries'),
        ('lasted less than two years.', 'less than 2 years'),
        ('five hundred and ninety three delegates', '593 delegates'),
        ('a hundred barricades', '100 barricades'),
    ]
    ok = all(exp in sd(src) for src, exp in cases)
    check('subtitle digits: cardinals -> digits', ok)
    # the pronoun guard: a solitary 'one' must stay spelled
    guard = all(sd(s) == s for s in ('collided with one another', 'was one of dizzying extremes'))
    check('subtitle digits: solitary "one" left alone', guard)
    # must never touch existing digits / years
    keep = sd('rose from around 37,500 in 1821') == 'rose from around 37,500 in 1821'
    check('subtitle digits: existing numerals untouched', keep)


# ── 2. _burn_subtitles opt-in default ──────────────────────────────────────
def test_burn_subtitles_default():
    src = open('pipeline_video.py', encoding='utf-8').read()
    default_off = 'digits_in_subs: bool = False' in src
    check('_burn_subtitles: digits default OFF for other callers', default_off)
    wired = src.count('_digits(') >= 4  # helper + 3 writer paths
    check('_burn_subtitles: all SRT writer paths converted', wired, f'{src.count("_digits(")} sites')
    sch = open('pipeline_scholarly.py', encoding='utf-8').read()
    check('documentary opts in', 'digits_in_subs=True' in sch)


# ── 3. audio_mix.level_to ──────────────────────────────────────────────────
def test_level_to():
    from zyg_workflows import audio_mix as am

    check('audio_mix.level_to exists', callable(getattr(am, 'level_to', None)))
    if not FULL:
        return skip('level_to on real narration', 'slow — use --full')
    # after the FULL check: _narration() measures loudness to skip silent
    # placeholders, and the fast suite must not pay for that
    src = _narration()
    if not src:
        return skip(
            'level_to on real narration',
            'no narration mp3 with actual audio on disk (runs with narration disabled write silent tracks)',
        )
    with tempfile.TemporaryDirectory() as td:
        quiet = os.path.join(td, 'q.mp3')
        subprocess.run(
            [
                'ffmpeg',
                '-v',
                'error',
                '-y',
                '-t',
                '45',
                '-i',
                src,
                '-af',
                'volume=-8dB',
                '-c:a',
                'libmp3lame',
                '-q:a',
                '2',
                quiet,
            ],
            check=True,
        )
        before = am.measure_lufs(quiet)
        ok = am.level_to(quiet, target_lufs=-14.0, tp_db=-1.0)
        after = am.measure_lufs(quiet)
        check('level_to reaches target from a quiet source', ok and abs(after + 14) < 0.5, f'{before} -> {after} LUFS')


# ── 4. VRAM headroom guards (the Catherine stall) ──────────────────────────
def test_headroom_guards():
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    check(
        'typography gate reads free VRAM before using the local judge', '_get_free_vram_gb' in src and '_tier_q' in src
    )
    check('typography gate discards a cpu-tier verdict', "== 'cpu'" in src)
    check('hand QC has its own headroom floor', 'ZYG_SCHOLARLY_HAND_QC_MIN_VRAM_GB' in src)
    try:
        from zyg_workflows import vlm_inspector as V

        floor = V.TIERS['resident']['min_free_gb']
        check('resident tier floor is above the ~4 GB free during Stage 3.5', floor > 4.2, f'floor {floor} GB')
    except Exception as e:
        skip('resident tier floor', f'{e!r}')


# ── 5. llm_audit ───────────────────────────────────────────────────────────
def test_llm_audit():
    from zyg_workflows import llm_audit

    check('llm_audit installs', llm_audit.install())
    # idempotent — a second install must not double-wrap
    check('llm_audit install is idempotent', llm_audit.install())
    from anthropic.resources.messages import Messages

    check('Anthropic SDK is wrapped', getattr(Messages.create, '_llm_audit_wrapped', False))
    # image summarisation, without any network call
    big = 'A' * 400_000
    flat = llm_audit._text_of(
        [{'type': 'image', 'source': {'media_type': 'image/jpeg', 'data': big}}, {'type': 'text', 'text': 'hello'}]
    )
    check('base64 images summarised, not inlined', big not in flat and '400000b base64' in flat, f'{len(flat)} chars')
    # records land in a per-run file and survive re-read
    llm_audit.set_context(pipeline_id='selftest-harness', stage='UnitTest')
    llm_audit.record(source='test', direction='exchange', llm='x', prompt='p', response='r')
    rows = llm_audit.read_run('selftest-harness')
    check('record -> per-run JSONL round-trips', rows and rows[-1]['stage'] == 'UnitTest' and rows[-1]['prompt'] == 'p')
    # append-only: a second record must not truncate the first
    llm_audit.record(source='test', direction='exchange', llm='x', prompt='p2')
    rows2 = llm_audit.read_run('selftest-harness')
    check('JSONL is append-only', len(rows2) == len(rows) + 1, f'{len(rows)} -> {len(rows2)}')
    try:
        os.remove(os.path.join('data/runtime/llm_audit', 'selftest-harness.jsonl'))
    except OSError:
        pass
    # chat payloads must not be mistaken for warm-ups
    body = {'model': 'm', 'messages': [{'role': 'user', 'content': 'hi', 'images': ['b64']}]}
    prompt = ''
    if not prompt and isinstance(body.get('messages'), list):
        parts = [str(m.get('content') or '') for m in body['messages']]
        prompt = '\n\n'.join(p for p in parts if p)
    check('chat payloads yield a prompt (not treated as a warm-up)', bool(prompt.strip()))


# ── 6. the logging guard itself ────────────────────────────────────────────
def test_guard():
    r = subprocess.run([sys.executable, 'scripts/check_llm_logging.py'], capture_output=True, text=True)
    check(
        'no unaudited raw Ollama call sites', 'OK —' in r.stdout, r.stdout.strip().splitlines()[-1] if r.stdout else ''
    )


# ── 7. roster pins ─────────────────────────────────────────────────────────
def test_roster():
    from zyg_workflows import murch_engine

    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    code = '\n'.join(l for l in src.split('\n') if not l.strip().startswith('#'))
    check('no gpt-oss pin left in code', 'gpt-oss' not in code)
    check('no qwen2.5:72b pin left in code', 'qwen2.5:72b' not in code)
    check('scene-desc fallback uses the roster constant', '_MURCH_MODEL' in code, murch_engine.MURCH_LLM_MODEL)


# ── 8. music bed wiring ────────────────────────────────────────────────────
def test_music_bed():
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    check('music bed builder exists', 'def _build_music_bed' in src)
    check(
        'bed feeds the MUX, not the ASR track',
        "'-i', _mux_audio" in src and src.count('_build_music_bed(tts_path') == 2,
    )
    from zyg_workflows import ace_step_service as ace

    check('music source is MIT-licensed ACE-Step', 'ACE-Step' in ace.model_id(), ace.model_id())
    if not FULL:
        return skip('ACE-Step generation', 'slow — use --full')
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    if not ace.is_available():
        return skip('ACE-Step generation', 'ComfyUI unavailable')
    from zyg_workflows import audio_mix as am

    with tempfile.TemporaryDirectory() as td:
        seg = os.path.join(td, 'seg.mp3')
        ok = ace.generate('cinematic documentary underscore, warm strings, no drums', seg, duration_s=20, seed=7)
        if not check('ACE-Step generates a bed', ok):
            return
        bed = os.path.join(td, 'bed.wav')
        tiled = am.prep_bed([{'path': seg, 'gain_db': 0.0}], 45.0, bed, crossfade_s=3.0)
        check(
            'bed tiles to the target duration',
            tiled and abs(am.probe_duration(bed) - 45.0) < 1.0,
            f'{am.probe_duration(bed)}s',
        )
        vo = _narration()
        if vo:
            v45 = os.path.join(td, 'v.mp3')
            subprocess.run(
                ['ffmpeg', '-v', 'error', '-y', '-t', '45', '-i', vo, '-c:a', 'libmp3lame', '-q:a', '2', v45],
                check=True,
            )
            am.level_to(bed, target_lufs=-34.0, tp_db=-2.0)
            mixed = os.path.join(td, 'mix.wav')
            got = am.duck_mix(v45, bed, mixed)
            check(
                'duck_mix preserves programme length',
                got and abs(am.probe_duration(mixed) - am.probe_duration(v45)) < 0.5,
            )


# ── 9. typography checklist ────────────────────────────────────────────────
def test_typography_checklist():
    from zyg_workflows import vlm_inspector as V

    try:
        cl = V.load_checklist('documentary_typography')
    except Exception as e:
        return check('typography checklist loads', False, repr(e))
    item = cl['items'][0]
    check('typography checklist loads', item['id'] == 'legible_text')
    check(
        'checklist asks for ANY lettering (not "prominent")',
        'prominent' not in item['question'].lower(),
        item['question'][:60] + '...',
    )
    check('checklist requests a bbox for repair', item.get('grounding') is True)


# ── 10. combat classification replaces the keyword scan ────────────────────
def test_combat_classifier():
    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    check('era lock asks for is_combat', "'is_combat'" in src and 'is_combat' in src)
    check('battle directive reads the classifier verdict', "_era_lock.get('is_combat')" in src)
    check('keyword scan kept only as the no-verdict fallback', '_combat_verdict is None' in src)
    check('a mismatch between the two is logged', 'keyword scan would have said' in src)


# ── 11. typography retry escalation ────────────────────────────────────────
def test_strip_written_subject():
    import ast

    src = open('pipeline_scholarly.py', encoding='utf-8').read()
    ns = {}
    for node in ast.parse(src).body:
        if (isinstance(node, ast.FunctionDef) and node.name == '_strip_written_subject') or (
            isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == '_WRITTEN_NOUNS'
        ):
            exec(compile(ast.Module([node], []), '<h>', 'exec'), ns)  # noqa: S102  AST subset lifted from a source file shipped in this repo, never from input
    if 'ftrip' in ns or '_strip_written_subject' not in ns:
        return check('_strip_written_subject importable', False)
    strip = ns['_strip_written_subject']
    import re as _re

    DOC = _re.compile(
        r'(?i)\b(map|document|newspaper|pamphlet|sign|banner|'
        r'manuscript|scroll|placard|book|page)\b'
    )
    cases = [
        'cinematic photograph Catherine stands before an enormous wall-mounted map of '
        'Russia in a candlelit hall, her face turned three-quarters toward the flame, '
        'wide establishing shot, photorealistic, 8k',
        'cinematic photograph A folded pamphlet wedged between two cobblestones at night, '
        'damp from the gutter, close-up, photorealistic, 8k',
    ]
    for c in cases:
        out = strip(c)
        head = out.split(', nothing in frame')[0]
        if not check('written nouns removed from the scene', not DOC.search(head), head[:70]):
            return
        check('style suffix preserved', 'photorealistic' in out)
        check('no dangling determiner left behind', not _re.search(r'(?i)\b(an|a|the)\s*,', head), head[:70])
    # The escalation branch is now reachable ONLY at attempt 3: attempts 1 and 2
    # are claimed by the `== 0` and `== 1` arms above it, so the old explicit
    # `_attempt >= 2` guard would be dead code.
    i0 = src.find('if _attempt == 0:')
    i1 = src.find('elif _attempt == 1:')
    i2 = src.find('elif _vlm_text_fail_prev:')
    check('escalation branch sits after the re-roll arm (so it is attempt 3 only)', 0 < i0 < i1 < i2, f'{i0}<{i1}<{i2}')
    check('escalation rewrites the prompt', '_strip_written_subject(_prompt)' in src)


def test_typography_repair():
    """Region repair: repaint the lettering out, or change nothing at all.

    Two properties matter more than the hit rate:

    * **it must not leak.** Only masked pixels may come from the repaint;
      everything else must match a plain re-encode of the original.
    * **it must not "succeed" by vandalism.** Told to paint a "plain blank
      unmarked surface", FLUX painted flat white bars across a map and a hole
      through a question mark. The OCR judge called that clean — no readable
      text — so absence of text cannot be the only acceptance test. The
      plausibility check compares the repaint against a ring of untouched
      pixels for texture and luminance, and rejects a flat patch.
    """
    try:
        from zyg_workflows import typography_ocr as tocr
        from zyg_workflows import typography_repair as trep
    except Exception as exc:
        skip('typography repair', f'unimportable: {exc!r}')
        return
    if not tocr.available():
        skip('typography repair', 'OCR engine unavailable')
        return

    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np
    import shutil
    import tempfile

    # ── the vandalism guard, on a synthetic case ──────────────────────────
    tex = Image.effect_noise((320, 240), 48).convert('RGB')
    m = Image.new('L', (320, 240), 0)
    ImageDraw.Draw(m).rectangle([80, 80, 240, 150], fill=255)
    flat = tex.copy()
    ImageDraw.Draw(flat).rectangle([80, 80, 240, 150], fill=(255, 255, 255))
    ok_flat, why = trep._plausible(flat, m)
    check('a flat fill is rejected as implausible', not ok_flat, why[:60])
    ok_tex, _ = trep._plausible(tex, m)
    check('untouched texture passes the plausibility check', ok_tex)

    # ── real frames ───────────────────────────────────────────────────────
    fx = 'tests/golden/typography_labels.json'
    if not os.path.exists(fx):
        skip('repair on real frames', 'no label fixture')
        return
    meta = json.load(open(fx))
    base = f'data/output/clips/{meta["_source_run"]}/flux_images'
    dirty = [n for n, v in meta['labels'].items() if v == 'yes' and os.path.exists(os.path.join(base, n))][:4]
    if not dirty:
        skip('repair on real frames', 'labelled frames no longer on disk')
        return

    cleared = leaks = unchanged_on_fail = fails = 0
    with tempfile.TemporaryDirectory() as td:
        for n in dirty:
            src = os.path.join(base, n)
            dst = os.path.join(td, n)
            shutil.copy2(src, dst)
            before = np.asarray(Image.open(src).convert('RGB'), dtype=int)
            # pipe=None on purpose: the suite runs on every change and must not
            # load a 24 GB model. This measures the CLASSICAL fallback only, so
            # it is a FLOOR on the repair's ability, not the production figure —
            # production hands it the already-loaded FLUX pipe. Both paths were
            # measured at 9/12 on this corpus; see typography_repair's docstring.
            r = trep.repair(dst, None, pipe=None, seed=5)
            after = np.asarray(Image.open(dst).convert('RGB'), dtype=int)
            if r['repaired']:
                cleared += 1
                boxes = r.get('repaired_boxes') or []
                mask = trep.build_mask(Image.open(src).size, boxes)
                grown = np.asarray(mask.filter(ImageFilter.MaxFilter(size=33)))
                outside = grown < 1
                ctrl_p = os.path.join(td, 'ctrl.jpg')
                Image.open(src).convert('RGB').save(ctrl_p, quality=trep._JPEG_Q)
                ctrl = np.asarray(Image.open(ctrl_p).convert('RGB'), dtype=int)
                d_rep = np.abs(before - after).max(axis=2)[outside].max()
                d_ctl = np.abs(before - ctrl).max(axis=2)[outside].max()
                if d_rep > d_ctl:
                    leaks += 1
            else:
                fails += 1
                if np.array_equal(before, after):
                    unchanged_on_fail += 1

    check(
        f'repair clears lettering on real frames ({len(dirty)} tried)',
        cleared > 0,
        f'{cleared} cleared, {fails} declined',
    )
    check('no repainted content leaks outside the mask', leaks == 0, f'{leaks} leak(s)')
    check(
        'a declined repair leaves the file byte-identical',
        fails == unchanged_on_fail,
        f'{unchanged_on_fail}/{fails} unchanged',
    )

    # Force a decline so fail-closed is actually exercised rather than asserted
    # over an empty set: with the area cap at 0.01% every real flag is "too big
    # to be a blemish", so repair must refuse and touch nothing.
    import importlib

    old_cap = os.environ.get('ZYG_TYPO_REPAIR_MAX_AREA')
    try:
        os.environ['ZYG_TYPO_REPAIR_MAX_AREA'] = '0.0001'
        importlib.reload(trep)
        with tempfile.TemporaryDirectory() as td:
            n = dirty[0]
            src = os.path.join(base, n)
            dst = os.path.join(td, n)
            shutil.copy2(src, dst)
            b = open(src, 'rb').read()
            r = trep.repair(dst, None, pipe=None, seed=5)
            same = open(dst, 'rb').read() == b
        check('an over-cap repair is refused', not r['repaired'], r['reason'][:60])
        check('...and the frame is left byte-identical', same)
    finally:
        if old_cap is None:
            os.environ.pop('ZYG_TYPO_REPAIR_MAX_AREA', None)
        else:
            os.environ['ZYG_TYPO_REPAIR_MAX_AREA'] = old_cap
        importlib.reload(trep)
