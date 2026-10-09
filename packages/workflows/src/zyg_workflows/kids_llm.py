# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_llm.py — the children's-music writing legs on Claude Opus 5 through the login. 2026-10-02.

Why this exists. Two steps decide what a children's song IS: the lyric
(`kids_music_service.write_lyrics`) and the storyboard — one picture description per clip
(`kids_video_service._llm_ideas_once`). Both ran on local `qwen3.5:9b`, which is why they
needed the scaffolding around them: a banned-word filter, a padding path that repeats the
model's own lines, a template fallback, batches of ten because one request for twenty-four
came back with eight usable descriptions. The operator's decision (2026-10-02): both steps
run on **Claude Opus 5 through the Max subscription**, never on the API key.

How. A subscription can only be spent through Claude Code, so each call is one headless
`claude -p` turn — the same path the documentary pipeline uses, so this module is a thin
router over `subscription_llm.run_turn` rather than a second implementation of it. That
module already guarantees the two things that matter here: the spawn environment carries no
`ANTHROPIC_*` variable (the CLI prefers a key over the login whenever one is set, and would
silently bill it), and a refused session/weekly limit raises `SubscriptionLimitError`
instead of quietly switching backends.

Rules:
  * Opus first, Ollama second, template last. A limit refusal, a dead CLI, a missing login
    or an unparseable answer falls back to the LOCAL model — never to an API key — and the
    caller's own fallback (the lyric template, the motif deck) stays the last resort. The
    backend that actually answered is returned in `info` and reaches the manifest, so a
    song can always be read back to the model that wrote it.
  * The CLI has no `format: json` mode, so the JSON contract is carried by the prompt and
    the answer is parsed defensively (fences stripped, outermost braces taken). The callers'
    key-folding, line filters and padding are untouched: Opus writes better input to the
    same validators, it does not get a shorter leash.
  * Each leg passes TWO prompts — `opus_prompt` and `ollama_prompt`. The Ollama prompt is
    byte-identical to what it was before this module existed, so the fallback path is a
    regression of nothing; the Opus prompt is the one that exploits the bigger model.
  * Every turn is recorded in llm_audit by subscription_llm (`source='claude_code'`,
    `backend='subscription'`, stage = the caller's stage) and leaves a transcript the quota
    meter reads. Never quote the CLI's `total_cost_usd` as a cost — the Quota tab is the meter.

Env:
  ZYG_KIDSMUSIC_LLM_BACKEND   subscription (default) | ollama   — 'ollama' restores the old path
  ZYG_KIDSMUSIC_OPUS_MODEL    claude-opus-5 (default)
  ZYG_KIDSMUSIC_OPUS_TIMEOUT  seconds for one turn (default 600)
  ZYG_KIDSMUSIC_LLM           the local fallback model (default qwen3.5:9b), as before
"""

from __future__ import annotations

import json
import os
import re
import time
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


BACKEND = (os.environ.get('ZYG_KIDSMUSIC_LLM_BACKEND', 'subscription') or 'subscription').strip().lower()
OPUS_MODEL = (os.environ.get('ZYG_KIDSMUSIC_OPUS_MODEL', '') or 'claude-opus-5').strip()
OPUS_TIMEOUT_S = float(os.environ.get('ZYG_KIDSMUSIC_OPUS_TIMEOUT', '600') or 600)

OLLAMA_URL = paths.ZYG_OLLAMA_URL.rstrip('/')
OLLAMA_MODEL = os.environ.get('ZYG_KIDSMUSIC_LLM', 'qwen3.5:9b')


def _log_noop(_m):
    pass


# ── which backend ────────────────────────────────────────────────────────────


def opus_on() -> bool:
    """True when this run should ask Opus 5 on the login.

    Checked per call rather than cached at import: the GUI is a long-lived process and the
    operator switching `ZYG_KIDSMUSIC_LLM_BACKEND` should not need a restart to take effect.
    """
    want = (os.environ.get('ZYG_KIDSMUSIC_LLM_BACKEND', '') or BACKEND).strip().lower()
    if want not in ('subscription', 'claude', 'opus', 'login'):
        return False
    return opus_available()


def opus_available() -> bool:
    """The CLI is on disk and a Claude login exists. No key is ever consulted."""
    try:
        from zyg_workflows import subscription_llm as S

        return bool(os.path.exists(S.CLI_BIN) and S.login_present())
    except Exception:  # noqa: BLE001 — the module is optional
        return False


def model_label() -> str:
    """What to show in a log line / the manifest for the model that will be asked."""
    return OPUS_MODEL if opus_on() else OLLAMA_MODEL


# ── JSON out of prose ────────────────────────────────────────────────────────

_FENCE = re.compile(r'^\s*```(?:json)?\s*|\s*```\s*$', re.IGNORECASE)


def parse_json(raw: str):
    """The outermost JSON object in a model answer, or None.

    The CLI has no JSON mode, so an answer can arrive fenced, prefaced, or followed by a
    closing remark however firmly the prompt says otherwise. Tried in order: the whole
    string, the string with fences stripped, and the span between the first '{' and the
    last '}'.
    """
    s = str(raw or '').strip()
    if not s:
        return None
    for cand in (s, _FENCE.sub('', s).strip()):
        try:
            d = json.loads(cand)
        except ValueError as _exc:
            _zyg_log.debug('JSON candidate did not parse, trying the next one: %s', _exc)
            continue
        if isinstance(d, dict):
            return d
    a, b = s.find('{'), s.rfind('}')
    if a >= 0 and b > a:
        try:
            d = json.loads(s[a : b + 1])
            return d if isinstance(d, dict) else None
        except ValueError:
            return None
    return None


# ── the two legs ─────────────────────────────────────────────────────────────


def ask_json(
    *,
    opus_prompt: str,
    ollama_prompt: str,
    system: str = '',
    stage: str = '',
    max_tokens: int = 4000,
    options: dict = None,
    ollama_timeout: int = 240,
    label: str = 'llm',
    log_fn=None,
):
    """Ask for one JSON object. Returns ``(data | None, info)``.

    ``info`` carries ``backend`` ('subscription' | 'ollama' | 'none'), ``model``,
    ``reason`` (empty when the answer came back clean), ``fallback`` (True when Opus was
    asked and Ollama answered) and, on the Opus path, the measured ``seconds``,
    ``input_tokens`` / ``output_tokens`` and ``session``.
    """
    log_fn = log_fn or _log_noop
    info = {'backend': 'none', 'model': '', 'reason': '', 'fallback': False}
    if opus_on():
        data, oinfo = _ask_opus(
            opus_prompt, system=system, stage=stage, max_tokens=max_tokens, label=label, log_fn=log_fn
        )
        info.update(oinfo)
        if data is not None:
            return data, info
        info['fallback'] = True
        log_fn(f'{label}: falling back to the local model ({OLLAMA_MODEL})')
    data, linfo = _ask_ollama(
        ollama_prompt, stage=stage, options=options, timeout=ollama_timeout, label=label, log_fn=log_fn
    )
    # The Opus reason is the one worth keeping when both legs failed: "the local model was
    # also down" explains nothing about why the good model did not answer.
    reason = info.get('reason') or ''
    info.update(linfo)
    if reason and linfo.get('reason'):
        info['reason'] = f'{reason}; then {linfo["reason"]}'
    elif reason:
        info['reason'] = reason
    return data, info


def _ask_opus(prompt: str, *, system: str, stage: str, max_tokens: int, label: str, log_fn):
    """One headless Opus turn on the login. Never raises."""
    info = {'backend': 'subscription', 'model': OPUS_MODEL, 'reason': ''}
    t0 = time.time()
    try:
        from zyg_workflows import subscription_llm as S

        # model= is passed explicitly: run_turn's resolve_model() maps a REQUESTED name onto
        # the documentary pipeline's own three tiers, and 'opus' there means the script tier,
        # not necessarily this model. Naming it leaves nothing to infer.
        r = S.run_turn(
            [{'role': 'user', 'content': prompt}],
            system=system or None,
            max_tokens=max_tokens,
            model=OPUS_MODEL,
            stage=stage,
            timeout=OPUS_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — a limit, a dead CLI, a cut stream
        kind = type(exc).__name__
        info['reason'] = f'Opus unavailable ({kind}: {str(exc)[:120]})'
        info['seconds'] = round(time.time() - t0, 1)
        log_fn(f'{label}: {info["reason"]}')
        return None, info
    text = (r.content[0].text if r.content else '') or ''
    info['seconds'] = round(time.time() - t0, 1)
    info['input_tokens'] = r.usage.input_tokens
    info['output_tokens'] = r.usage.output_tokens
    info['session'] = r.session_id
    data = parse_json(text)
    if data is None:
        info['reason'] = f'Opus replied {len(text)} chars with no JSON object'
        log_fn(f'{label}: {info["reason"]}')
        return None, info
    log_fn(
        f'{label}: {OPUS_MODEL} on the subscription · {info["seconds"]:.1f}s · '
        f'in {r.usage.input_tokens} out {r.usage.output_tokens}'
    )
    return data, info


def _ask_ollama(prompt: str, *, stage: str, options: dict, timeout: int, label: str, log_fn):
    """The local model, exactly as both call sites asked it before this module existed:
    /api/version probed first, `format: json`, `think: false` for the qwen3.x thinking
    models (without it the budget goes to reasoning tokens and `response` comes back empty),
    through llm_audit when it is importable."""
    info = {'backend': 'ollama', 'model': OLLAMA_MODEL, 'reason': ''}
    try:
        import urllib.request as _ur

        from zyg_workflows.net import safe_urlopen as _safe_urlopen

        with _safe_urlopen(f'{OLLAMA_URL}/api/version', timeout=3):
            pass
        payload = {
            'model': OLLAMA_MODEL,
            'prompt': prompt,
            'stream': False,
            'format': 'json',
            **({'think': False} if OLLAMA_MODEL.startswith('qwen3') else {}),
            'keep_alive': '2m',
            'options': dict(options or {}),
        }
        try:
            from zyg_workflows import llm_audit as _la

            d = _la.ollama_post(f'{OLLAMA_URL}/api/generate', payload, timeout=timeout, stage=stage)
        except ImportError:
            # safe_urlopen takes a bare URL and this POST needs headers, so the same
            # scheme check is applied to the composed Request instead.
            req = _ur.Request(  # noqa: S310  scheme checked on the next line
                f'{OLLAMA_URL}/api/generate',
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            if req.type not in ('http', 'https'):
                # from None: the enclosing handler's ImportError says nothing about the scheme
                raise ValueError(f'refusing to open a {req.type!r} URL: {OLLAMA_URL!r}') from None
            with _ur.urlopen(req, timeout=timeout) as r:  # noqa: S310  scheme validated above  # nosec B310
                d = json.loads(r.read().decode('utf-8'))
    except Exception as exc:  # noqa: BLE001
        info['reason'] = f'LLM unavailable ({type(exc).__name__})'
        log_fn(f'{label}: {info["reason"]} — using the template')
        return None, info
    raw = (d.get('response') or '').strip() or (d.get('thinking') or '')
    data = parse_json(raw)
    if data is None:
        info['reason'] = 'the local model returned no JSON object'
        log_fn(f'{label}: {info["reason"]}')
    return data, info


if __name__ == '__main__':  # python3 kids_llm.py  — one live probe per backend
    print(
        json.dumps(
            {
                'backend': 'subscription' if opus_on() else 'ollama',
                'opus_available': opus_available(),
                'opus_model': OPUS_MODEL,
                'ollama_model': OLLAMA_MODEL,
            },
            indent=1,
        )
    )
    d, i = ask_json(
        opus_prompt='Reply with JSON only: {"ok": true, "who": "<the model name>"}',
        ollama_prompt='Reply with JSON only: {"ok": true, "who": "<the model name>"}',
        system='You answer with one JSON object and nothing else.',
        stage='kids_llm_probe',
        max_tokens=200,
        log_fn=lambda m: print('·', m),
    )
    print(json.dumps({'data': d, 'info': i}, indent=1, default=str))
