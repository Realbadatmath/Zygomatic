# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""provenance_seal.py — C2PA content credentials on every deliverable.

2026-10-06. Everything this studio ships is synthetic, and nothing in a frame says so.
A C2PA manifest does: a signed, tamper-evident statement embedded in the file itself,
naming the generator, the pipeline that produced it, the models it used and the licence
it ships under. One flipped byte and a verifier reports ``Invalid``.

    from zyg_workflows import provenance_seal as _seal

    _seal.seal(out_path, pipeline='kidsvideo', run_id=run_id, models=models, log_fn=log)
    _seal.seal_derived(web_mp4, master_mp4, pipeline='kidsvideo', run_id=run_id)
    _seal.verify(path)        # {'sealed': True, 'state': 'Valid', 'provenance': {...}, ...}

The seal is FAIL-SAFE, modelled on :func:`lora_attest.attest_submit`: a missing key, a
format the library cannot sign, a venv without the wheel — none of those may ever break a
render. In the default ``warn`` mode :func:`seal` logs and returns; it never raises and
never touches the file. ``ZYG_C2PA=strict`` turns the same conditions into
:class:`SealError` (and only :class:`SealError` ever escapes); ``ZYG_C2PA=off`` skips
everything.

Signing is IN PLACE: the library writes a new file, so we sign to a temp file beside the
original and ``os.replace`` it over the top — an interrupted seal leaves the original
intact, never a half-written deliverable.

Keys (operator material, never in the repo):

    ZYG_C2PA_KEY         PKCS#8 ES256 private key   ~/.config/zygomatic/c2pa/signer.key
    ZYG_C2PA_CERT_CHAIN  end-entity + issuing CA    ~/.config/zygomatic/c2pa/signer_chain.pem
    ZYG_C2PA_TSA_URL     optional RFC-3161 timestamp authority (empty = no timestamp)
    ZYG_C2PA_ROOT_CERT   the public root, for the trust check in :func:`verify`

A self-signed certificate is refused by the library: the chain must be end-entity plus
issuing CA. Trust is a property of the *verifier*, not of the file — a reader that does not
hold our root reports ``Valid`` with an untrusted issuer, and one that does reports
``Trusted``, which is what ``verify()['trusted']`` reflects.

    python -m zyg_workflows.provenance_seal verify PATH
    python -m zyg_workflows.provenance_seal sign PATH --pipeline kidsvideo --run-id 42
"""

from __future__ import annotations

import os
import tempfile

#: Extensions the library embeds a manifest into. Anything else is skipped, not an error:
#: subtitles, JSON sidecars and MIDI have nowhere to carry one.
SUPPORTED = frozenset(
    {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif', '.mp4', '.mov', '.m4a', '.wav', '.mp3', '.flac'}
)

#: IPTC digital-source-type for media a model made. A ``c2pa.created`` action without one
#: is refused by the library.
TRAINED_ALGORITHMIC_MEDIA = 'http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia'

#: Our own assertion: the pipeline facts a C2PA label has no vocabulary for.
PROVENANCE_LABEL = 'org.zygomatic.provenance'

GENERATOR = 'Zygomatic'

_OFF = frozenset({'off', '0', 'false', 'no', 'none'})

#: ``Signer`` instances are reusable and parsing the key is the slow part; keyed by the
#: three inputs that define one.
_SIGNERS: dict[tuple[str, str, str], object] = {}


class SealError(RuntimeError):
    """The only exception :func:`seal` raises, and only under ``ZYG_C2PA=strict``."""


def _log_noop(*_args, **_kwargs):
    pass


def _c2pa():
    """The ``c2pa`` module, or None when the wheel is not installed.

    Imported lazily so this module imports in a venv without it — a missing library is
    "not configured", not an ImportError at the top of every pipeline.
    """
    try:
        import c2pa
    except ImportError:
        return None
    return c2pa


def _config() -> dict[str, str]:
    """The five flags, read now (not at import) so tests can monkeypatch them."""
    return {
        'mode': (os.environ.get('ZYG_C2PA', 'warn') or 'warn').strip().lower(),
        'key': _expand(os.environ.get('ZYG_C2PA_KEY', '~/.config/zygomatic/c2pa/signer.key')),
        'chain': _expand(os.environ.get('ZYG_C2PA_CERT_CHAIN', '~/.config/zygomatic/c2pa/signer_chain.pem')),
        'tsa': (os.environ.get('ZYG_C2PA_TSA_URL', '') or '').strip(),
        'root': _expand(os.environ.get('ZYG_C2PA_ROOT_CERT', '~/.config/zygomatic/c2pa/root/ca.pem')),
    }


def _expand(value: str | None) -> str:
    """``~`` expanded at use time; an empty setting stays empty (= not set)."""
    return os.path.expanduser(value) if value else ''


def configured() -> bool:
    """True when the library is installed and both key and certificate chain are on disk."""
    cfg = _config()
    return _c2pa() is not None and os.path.isfile(cfg['key']) and os.path.isfile(cfg['chain'])


def _version() -> str:
    """The package version that goes into the claim generator. '0' when unknown."""
    try:
        from importlib.metadata import version

        return version('zygomatic-workflows')
    except Exception:
        return '0'


def _signer(cfg: dict[str, str]):
    """A cached ``c2pa.Signer`` for the configured key, chain and timestamp authority."""
    c2pa = _c2pa()
    ck = (cfg['key'], cfg['chain'], cfg['tsa'])
    signer = _SIGNERS.get(ck)
    if signer is None:
        with open(cfg['chain'], 'rb') as fh:
            chain = fh.read()
        with open(cfg['key'], 'rb') as fh:
            key = fh.read()
        info = c2pa.C2paSignerInfo(
            alg=b'es256',
            sign_cert=chain,
            private_key=key,
            ta_url=cfg['tsa'].encode() if cfg['tsa'] else None,
        )
        signer = c2pa.Signer.from_info(info)
        _SIGNERS[ck] = signer
    return signer


def _manifest(title, pipeline, run_id, models, prompt_ids, licence, extra, derived=False) -> dict:
    """The manifest the builder signs: claim generator, actions, our own assertion.

    A derived file carries ``c2pa.created`` *and* ``c2pa.transcoded``: the library refuses a
    manifest whose first action is neither ``created`` nor ``opened``, and ``c2pa.opened``
    needs an ingredient reference we cannot compute before signing.
    """
    agent = {'name': GENERATOR, 'version': _version()}
    actions = [{'action': 'c2pa.created', 'digitalSourceType': TRAINED_ALGORITHMIC_MEDIA, 'softwareAgent': agent}]
    if derived:
        actions.append(
            {'action': 'c2pa.transcoded', 'digitalSourceType': TRAINED_ALGORITHMIC_MEDIA, 'softwareAgent': agent}
        )
    provenance = {
        'pipeline': pipeline,
        'run_id': run_id,
        'models': models,
        'prompt_ids': prompt_ids,
        'licence': licence,
        'extra': extra,
    }
    return {
        'claim_generator_info': [agent],
        'title': title,
        'assertions': [
            {'label': 'c2pa.actions', 'data': {'actions': actions}},
            {'label': PROVENANCE_LABEL, 'data': {k: v for k, v in provenance.items() if v is not None}},
        ],
    }


def _mime(path: str) -> str:
    """The format string the builder wants for an ingredient: just its extension."""
    return os.path.splitext(path)[1].lower().lstrip('.')


def _sign_in_place(path, manifest, master_path, cfg, log):
    """Sign *path* to a temp file beside it and ``os.replace`` it over the original."""
    c2pa = _c2pa()
    ext = os.path.splitext(path)[1].lower()
    signer = _signer(cfg)
    handle = tempfile.NamedTemporaryFile(dir=os.path.dirname(os.path.abspath(path)), delete=False, suffix=ext)
    tmp = handle.name
    handle.close()
    try:
        builder = c2pa.Builder.from_json(manifest)
        try:
            if master_path:
                ingredient = {'title': os.path.basename(master_path), 'relationship': 'parentOf'}
                with open(master_path, 'rb') as source:
                    builder.add_ingredient(ingredient, _mime(master_path), source)
            builder.sign_file(path, tmp, signer)
        finally:
            builder.close()
        os.replace(tmp, path)
    finally:
        # Nothing to remove once os.replace moved it; this is the failure path.
        if os.path.exists(tmp):
            os.unlink(tmp)
    log(f'[seal] signed {path}')


def _seal(path, *, pipeline, run_id, title, models, prompt_ids, licence, extra, log_fn, master_path, derived):
    """The body of :func:`seal` and :func:`seal_derived`; fail-safe in every branch."""
    log = log_fn or _log_noop
    path = str(path)
    out: dict = {'ok': None, 'path': path, 'state': None}
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        out['skipped'] = f'unsupported extension {ext or "(none)"}'
        return out
    cfg = _config()
    if cfg['mode'] in _OFF:
        out['skipped'] = 'ZYG_C2PA=off'
        return out
    strict = cfg['mode'] == 'strict'
    if not configured():
        log(f'[seal] not configured, {path} left unsigned')
        if strict:
            raise SealError(f'ZYG_C2PA=strict but no signing key: {cfg["key"]} / {cfg["chain"]}')
        out['skipped'] = 'not configured'
        return out
    try:
        manifest = _manifest(
            title or os.path.basename(path), pipeline, run_id, models, prompt_ids, licence, extra, derived=derived
        )
        _sign_in_place(path, manifest, master_path, cfg, log)
        out['ok'] = True
        out['state'] = verify(path).get('state')
    except Exception as exc:
        out['ok'] = False
        out['error'] = f'{type(exc).__name__}: {exc}'
        log(f'[seal] FAILED for {path} (deliverable kept unsigned): {out["error"]}')
        if strict:
            raise SealError(f'sealing {path} failed: {out["error"]}') from exc
    return out


def seal(
    path,
    *,
    pipeline,
    run_id='',
    title=None,
    models=None,
    prompt_ids=None,
    licence=None,
    extra=None,
    log_fn=None,
) -> dict:
    """Embed a content credential in *path*, in place. Never raises outside strict mode.

    Returns ``{'ok': True|None|False, 'path', 'state', 'skipped'|'error'}``: True signed,
    None skipped (mode off, unsupported extension, no keys), False tried and failed.
    """
    return _seal(
        path,
        pipeline=pipeline,
        run_id=run_id,
        title=title,
        models=models,
        prompt_ids=prompt_ids,
        licence=licence,
        extra=extra,
        log_fn=log_fn,
        master_path=None,
        derived=False,
    )


def seal_derived(path, master_path, *, pipeline, run_id='', log_fn=None) -> dict:
    """Seal a re-encoded copy, naming *master_path* as its parent ingredient.

    Re-encoding strips the master's manifest, so a web proxy or a delivery transcode has to
    be signed again — this records what it came from instead of pretending it is an original.
    """
    return _seal(
        path,
        pipeline=pipeline,
        run_id=run_id,
        title=None,
        models=None,
        prompt_ids=None,
        licence=None,
        extra=None,
        log_fn=log_fn,
        master_path=str(master_path),
        derived=True,
    )


def _provenance_of(manifest: dict | None):
    """Our own assertion's data out of an active manifest, or None."""
    for assertion in (manifest or {}).get('assertions') or []:
        if assertion.get('label') == PROVENANCE_LABEL:
            return assertion.get('data')
    return None


def _trusted(path: str, root: str) -> bool:
    """True when the signature validates against *root* as a user trust anchor.

    Settings only reach the reader through a Context in c2pa-python 0.38; a plain
    ``Reader.try_create`` ignores them and always reports the untrusted ``Valid``.
    """
    c2pa = _c2pa()
    if not (c2pa and root and os.path.isfile(root)):
        return False
    try:
        with open(root, encoding='utf-8') as fh:
            anchors = fh.read()
        settings = c2pa.Settings.from_dict({'trust': {'user_anchors': anchors}, 'verify': {'verify_trust': True}})
        context = c2pa.Context.builder().with_settings(settings).build()
        reader = c2pa.Reader.try_create(path, context=context)
        if reader is None:
            return False
        try:
            return reader.get_validation_state() == 'Trusted'
        finally:
            reader.close()
    except Exception:
        return False


def verify(path) -> dict:
    """Read the credential in *path*. Never raises.

    ``sealed`` says a manifest is there, ``state`` is the library's verdict ('Valid' /
    'Invalid'), and ``trusted`` says the signature chains to ``ZYG_C2PA_ROOT_CERT``.
    """
    path = str(path)
    out: dict = {
        'sealed': False,
        'state': None,
        'issuer': None,
        'time': None,
        'manifest': None,
        'provenance': None,
        'trusted': False,
    }
    c2pa = _c2pa()
    if c2pa is None:
        out['error'] = 'the c2pa library is not installed'
        return out
    try:
        reader = c2pa.Reader.try_create(path)
        if reader is None:
            return out
        try:
            manifest = reader.get_active_manifest()
            out['state'] = reader.get_validation_state()
        finally:
            reader.close()
    except Exception as exc:
        out['error'] = f'{type(exc).__name__}: {exc}'
        return out
    signature = (manifest or {}).get('signature_info') or {}
    out['sealed'] = True
    out['manifest'] = manifest
    out['issuer'] = signature.get('issuer')
    out['time'] = signature.get('time')
    out['provenance'] = _provenance_of(manifest)
    out['trusted'] = _trusted(path, _config()['root'])
    return out


def is_sealed(path) -> bool:
    """True when *path* carries a C2PA manifest, whatever its validation state."""
    return verify(path)['sealed']


__all__ = [
    'PROVENANCE_LABEL',
    'SUPPORTED',
    'TRAINED_ALGORITHMIC_MEDIA',
    'SealError',
    'configured',
    'is_sealed',
    'seal',
    'seal_derived',
    'verify',
]


if __name__ == '__main__':  # the CLI lives in provenance_seal_cli
    from zyg_workflows.provenance_seal_cli import main as _cli_main

    raise SystemExit(_cli_main())
