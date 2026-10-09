# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ambience_ingest.py — license-gated ingest + publish gate for library audio (2026-07-30).

WHY: the 1672 Dutch-drama narration+ambience stack publishes COMMERCIALLY. Only
allowlisted licenses may reach a published mix: CC0 / public-domain / Apache-2.0 /
MIT / verified royalty-free unconditionally, plus CC-BY-3.0/4.0 ONLY when a
non-empty attribution credit is recorded (the gate surfaces those credits in
'attributions' and the publish stage must inject them into episode credits).
A single CC-BY-NC or BBC-RemArc file in the soundtrack is a takedown risk, and an
uncredited CC-BY file is a license breach. Free-sound sites mix licenses per-file,
so the safe point of control is INGEST: every file entering
data/asset_libraries/<cat>/ goes through register_audio_asset(), which refuses
anything without an allowlisted commercial-ok license (and refuses
attribution-required files with a blank attribution) and records provenance in the
asset_library_service sidecar. license_gate() is the second (publish-stage) fence:
it re-checks every referenced file — including that the file still EXISTS in the
library dir — so raw files dropped into the dir by hand, or stale sidecar entries
for deleted files, can never silently reach a published episode.

Env: ZYG_AUDIO_LICENSE_GATE=0 downgrades license_gate to warn-only (violations are
still listed, 'ok' is forced True with 'forced': True) — for internal previews only.

Public API:
    BANNED_LICENSE_IDS / ALLOWED_LICENSE_IDS / ATTRIBUTION_LICENSE_IDS
    register_audio_asset(cat, src_path, meta, name=None, convert=True, log_fn=None)
        -> merged record | None    (converts to 48 kHz wav via ffmpeg by default)
    license_gate(assets, log_fn=None)
        -> {'ok': bool, 'violations': [...], 'attributions': [str, ...]}
        assets = [(cat, file_id), ...]
    audit_category(cat) -> [records lacking clean metadata, incl. stale sidecar
                            entries whose file is gone]
    training_gate(paths, log_fn=None)
        -> {'ok': bool, 'violations': [...]}    # AI-TRAINING fence, see below

2026-08-21 — the AI-TRAINING fence. Every licence the library held until now was
CC0/public-domain, where the only question is "may this ship in a commercial mix".
The 344 Audio Human Mouth Noises library (purchased, perpetual royalty-free) is the
first PAID licence here, and it grants LESS than CC0 in one specific direction:

    3. Restrictions — You may not: ... Use the Sounds to train AI, machine
       learning, or neural networks.  (344 Audio EULA, 20 Mar 2025)

That is invisible to license_gate, which asks about PUBLISHING. This pipeline also
CONSUMES audio as model input — a Chatterbox/IndexTTS-2 voice-clone reference is
literally "audio fed to a neural network" — so a licence-clean file could still
breach its terms without ever reaching a mix. Hence a second, orthogonal fence:
meta['no_ai_training'] marks a file as mix-only, and training_gate() refuses it at
every point where audio becomes model INPUT rather than model output. It fails
CLOSED on unreadable metadata, and unlike license_gate it has NO env override —
the publish gate's warn-only mode exists for internal previews, but there is no
such thing as an internal-preview licence breach: a model trained on a forbidden
file stays trained.
"""

import os
import re
import time
import logging as _zyg_logging

from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


# License ids that must NEVER touch published audio. Kept as defense-in-depth —
# the ALLOWED_LICENSE_IDS allowlist below is the primary fence. Matched on the
# NORMALIZED id (lowercase, whitespace/underscores -> hyphens), plus an
# 'nc'-component / 'cc-by-nc' prefix check so space/typo variants still ban.
BANNED_LICENSE_IDS = frozenset(
    {
        'CC-BY-NC',
        'CC-BY-NC-4.0',
        'CC-BY-NC-3.0',
        'CC-BY-NC-SA',
        'CC-BY-NC-SA-4.0',
        'CC-BY-NC-SA-3.0',
        'CC-BY-NC-ND',
        'CC-BY-NC-ND-4.0',
        'BBC-RemArc',
        'NonCommercial',
        'research-only',
    }
)

# PRIMARY fence: the normalized license_id must be one of these, or (with a
# recorded credit) one of ATTRIBUTION_LICENSE_IDS — anything else is a
# violation, so typo'd/unknown/mislabelled ids fail CLOSED instead of riding
# through on commercial_ok=True.
ALLOWED_LICENSE_IDS = frozenset(
    {
        'cc0',
        'cc0-1.0',
        'public-domain',
        'apache-2.0',
        'mit',
        'royalty-free-verified',
    }
)
# Commercially usable ONLY with attribution: these pass the gate solely when a
# non-empty attribution string is recorded; the gate collects the credit into
# result['attributions'] for the publish stage. Blank credit = violation.
ATTRIBUTION_LICENSE_IDS = frozenset({'cc-by-3.0', 'cc-by-4.0'})


def _norm_license_id(lic):
    """Normalize a license id for matching: lowercase, whitespace/underscores
    collapsed to single hyphens ('CC BY 3.0' -> 'cc-by-3.0')."""
    return re.sub(r'[\s_]+', '-', str(lic or '').strip().lower()).strip('-')


_BANNED_LOWER = frozenset(_norm_license_id(x) for x in BANNED_LICENSE_IDS)


def _log_noop(_m):
    pass


def _violation_reasons(meta):
    """All license problems with one file's meta dict. [] == clean."""
    if not meta:
        return ['no license metadata recorded']
    reasons = []
    if meta.get('banned'):
        reasons.append('banned flag set')
    if meta.get('deleted'):
        # tombstone stamped by asset_library_service.remove_asset — license
        # history survives in the sidecar but the entry must never pass a gate
        reasons.append('asset was deleted from the library')
    lic = str(meta.get('license_id') or '').strip()
    n = _norm_license_id(lic)
    if not lic:
        reasons.append('license_id missing')
    elif n in _BANNED_LOWER or n.startswith('cc-by-nc') or 'nc' in n.split('-'):
        reasons.append(f'non-commercial license: {lic}')
    elif n in ATTRIBUTION_LICENSE_IDS:
        if not str(meta.get('attribution') or '').strip():
            reasons.append(f'{lic} requires attribution but attribution is empty')
    elif n not in ALLOWED_LICENSE_IDS:
        reasons.append(f'license_id not in the commercial allowlist: {lic}')
    if meta.get('commercial_ok') is not True:
        reasons.append('commercial_ok is not True')
    if meta.get('attribution_required') and not str(meta.get('attribution') or '').strip():
        # independent of license family — an operator-set flag with no credit
        # recorded can never publish (fail closed)
        reasons.append('attribution_required but attribution is empty')
    return reasons


def _sanitize_name(name):
    import re

    s = re.sub(r'[^a-z0-9]+', '_', str(name or '').strip().lower()).strip('_')
    return s[:80] or 'audio'


def register_audio_asset(cat, src_path, meta, name=None, convert=True, log_fn=None, meta_sink=None):
    """Ingest ONE audio file into the library, license-first.

    Refuses (returns None, logs why) unless meta carries an ALLOWLISTED
    license_id AND commercial_ok is True — and, for attribution-required
    licenses (CC-BY-3.0/4.0 or attribution_required=True), a NON-EMPTY
    attribution string. When convert=True the file is transcoded to
    48 kHz 16-bit wav (channel count preserved) — the mux stage's native format;
    convert=False copies the file as-is. The sanitized snake_case filename comes
    from `name` or the source stem. Provenance lands in the sidecar with
    added_date. Returns the merged library record.

    meta_sink (2026-09-02): a dict to COLLECT this file's meta into instead of
    writing the sidecar now. The licence fence above still runs — nothing
    unlicensed is copied either way — but the sidecar write is the caller's
    job, via flush_meta_sink(). It exists because the per-file write re-reads
    and rewrites the WHOLE licence book (O(n) per call), which is invisible at
    2,800 files and hours at 66,000. A caller that uses a sink MUST flush it,
    including on the error path: until it does, the files on disk have no
    licence record, and audit_category() will report exactly that.
    """
    log = log_fn or _log_noop
    try:
        from zyg_workflows import asset_library_service as AL
    except Exception as e:
        log(f'[ambience] asset_library_service unavailable: {e}')
        return None
    info = AL.category_info(cat)
    if not info or info.get('kind') != 'audio':
        log(f'[ambience] refuse: "{cat}" is not an audio category')
        return None
    if not isinstance(meta, dict):
        log('[ambience] refuse: meta dict required')
        return None
    reasons = _violation_reasons(meta)
    if reasons:
        log(f'[ambience] refuse {os.path.basename(str(src_path))}: ' + '; '.join(reasons))
        return None
    if not (src_path and os.path.isfile(src_path)):
        log(f'[ambience] refuse: source file not found: {src_path}')
        return None

    base = _sanitize_name(name or os.path.splitext(os.path.basename(src_path))[0])
    src_ext = os.path.splitext(src_path)[1].lower()
    ext = '.wav' if convert else src_ext
    if not convert and ext not in AL._AUDIO_EXTS:
        log(f'[ambience] refuse: "{ext}" is not a supported library format (use convert=True)')
        return None
    dest_dir = AL._audio_dir(cat)
    fn, i = base + ext, 2
    while os.path.exists(os.path.join(dest_dir, fn)):
        fn = f'{base}_{i}{ext}'
        i += 1
    dest = os.path.join(dest_dir, fn)

    if convert:
        import subprocess

        cmd = [exe('ffmpeg'), '-y', '-i', src_path, '-vn', '-ar', '48000', '-c:a', 'pcm_s16le', dest]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300)
        except Exception as e:
            log(f'[ambience] ffmpeg failed: {e}')
            return None
        if r.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) < 128:
            err = (r.stderr or b'').decode('utf-8', errors='replace')[-200:]
            log(f'[ambience] ffmpeg convert failed: {err}')
            try:
                if os.path.isfile(dest):
                    os.remove(dest)
            except OSError as _exc:
                _zyg_log.debug('failed-convert output cleanup skipped: %s', _exc)
            return None
    else:
        import shutil

        try:
            shutil.copy2(src_path, dest)
        except OSError as e:
            log(f'[ambience] copy failed: {e}')
            return None

    full_meta = dict(meta)
    full_meta.setdefault('added_date', time.strftime('%Y-%m-%d %H:%M:%S'))
    if meta_sink is not None:
        meta_sink[fn] = full_meta
        return {
            'id': fn,
            'name': base.replace('_', ' ').title(),
            'file': fn,
            'anchor': 'audio',
            'prompt_clause': '',
            'pending_meta': True,
        }
    if not AL.set_audio_meta(cat, fn, full_meta):
        # a library file WITHOUT its license record would dodge the audit — undo
        log('[ambience] sidecar write failed — removing ingested file')
        try:
            os.remove(dest)
        except OSError as _exc:
            _zyg_log.warning('rollback removal of %s failed — unlicensed file left in the library: %s', dest, _exc)
        return None
    rec = AL.get_asset(cat, fn)
    log(f'[ambience] registered {cat}/{fn} ({full_meta.get("license_id")})')
    return rec


def flush_meta_sink(cat, meta_sink, log_fn=None):
    """Write a sink collected by register_audio_asset(meta_sink=...) in ONE
    atomic sidecar write, and clear it. Keeps the same fail-closed promise as
    the per-file path: if the write is refused, every file it covered is
    REMOVED, because a library file without a licence record would dodge the
    audit. Returns the number of records written."""
    log = log_fn or _log_noop
    if not meta_sink:
        return 0
    try:
        from zyg_workflows import asset_library_service as AL
    except Exception as e:
        log(f'[ambience] asset_library_service unavailable: {e}')
        return 0
    n = len(meta_sink)
    if AL.set_audio_meta_many(cat, meta_sink):
        meta_sink.clear()
        return n
    log(f'[ambience] sidecar batch write FAILED — removing {n} ingested files')
    d = AL._audio_dir(cat)
    for fn in list(meta_sink):
        try:
            os.remove(os.path.join(d, fn))
        except OSError as _exc:
            _zyg_log.warning('rollback removal of %s failed — unlicensed file left in the library: %s', fn, _exc)
    meta_sink.clear()
    return 0


def license_gate(assets, log_fn=None):
    """Publish-stage fence. assets = [(cat, file_id), ...] for every library audio
    file about to enter a published mix. Returns
    {'ok': bool, 'violations': [...], 'attributions': [str, ...]};
    each violation is {'cat', 'id', 'reasons': [...]}. 'attributions' is ALWAYS
    present (possibly empty) and carries the credit line of every passing
    attribution-required file — the publish stage must inject these into the
    episode credits. A referenced file missing from the library dir is a
    violation (stale sidecar meta must never wave a deleted/renamed file
    through). ZYG_AUDIO_LICENSE_GATE=0 downgrades to warn-only: violations
    still listed, ok forced True + 'forced'."""
    log = log_fn or _log_noop
    violations = []
    attributions = []
    try:
        from zyg_workflows import asset_library_service as AL

        # 2026-09-02: the sidecar of each referenced category is read ONCE.
        # get_audio_meta() re-parses the whole book per call, so gating a mix
        # that draws on the instruments library (66k entries, ~90 MB) was
        # O(refs x book) — the publish gate is the LAST place that may be slow
        # enough to be skipped. Same fix as audit_category().
        books = {}

        def _meta(cat, fid):
            if cat not in books:
                try:
                    books[cat] = AL._load_audio_meta(cat) or {}
                except Exception:
                    books[cat] = {}
            m = books[cat].get(str(fid or ''))
            return dict(m) if isinstance(m, dict) else {}

        for ref in assets or []:
            try:
                cat, fid = ref[0], ref[1]
            except (TypeError, IndexError):
                violations.append({'cat': None, 'id': str(ref), 'reasons': ['malformed asset ref']})
                continue
            meta = _meta(cat, fid)
            reasons = _violation_reasons(meta)
            fn = str(fid or '')
            info = AL.category_info(cat)
            if not info or info.get('kind') != 'audio':
                reasons.append(f'"{cat}" is not an audio category')
            elif os.path.basename(fn) != fn or not os.path.isfile(os.path.join(AL._audio_dir(cat), fn)):
                reasons.append('file missing from library')
            if reasons:
                violations.append({'cat': cat, 'id': fid, 'reasons': reasons})
                continue
            att = str(meta.get('attribution') or '').strip()
            if att and (
                meta.get('attribution_required') or _norm_license_id(meta.get('license_id')) in ATTRIBUTION_LICENSE_IDS
            ):
                if att not in attributions:
                    attributions.append(att)
    except Exception as e:
        # a broken gate must FAIL CLOSED, never wave audio through
        violations.append({'cat': None, 'id': None, 'reasons': [f'gate error: {e}']})
    result = {'ok': not violations, 'violations': violations, 'attributions': attributions}
    if violations:
        for v in violations:
            log(f'[license-gate] {v.get("cat")}/{v.get("id")}: ' + '; '.join(v['reasons']))
        if os.environ.get('ZYG_AUDIO_LICENSE_GATE', '1') == '0':
            log('[license-gate] ZYG_AUDIO_LICENSE_GATE=0 — WARN-ONLY, publishing anyway')
            result['ok'] = True
            result['forced'] = True
    return result


def audit_category(cat, log_fn=None):
    """Every record in an audio category that lacks clean commercial metadata
    (each returned record gains a 'violations' reasons list), PLUS stale
    sidecar entries whose audio file is gone (deleted via remove_asset or
    removed by hand) — those must stay visible here or the audit and the
    publish gate would disagree about the same file id. [] == all clear."""
    log = log_fn or _log_noop
    try:
        from zyg_workflows import asset_library_service as AL

        info = AL.category_info(cat)
        if not info or info.get('kind') != 'audio':
            return []
        bad = []
        seen = set()
        # 2026-09-02: the sidecar is read ONCE. It used to be re-read per record
        # (get_audio_meta parses the whole file), which is O(n^2) — fine at
        # 2,800 rows, minutes at 60,000 once the instruments library landed.
        meta_all = AL._load_audio_meta(cat) or {}
        for rec in AL.load_assets(cat):
            seen.add(rec.get('id'))
            m = meta_all.get(rec.get('id'))
            reasons = _violation_reasons(dict(m) if isinstance(m, dict) else {})
            if reasons:
                r = dict(rec)
                r['violations'] = reasons
                bad.append(r)
        d = AL._audio_dir(cat)
        for fn, meta in meta_all.items():
            if fn in seen:
                continue
            # STAT, don't trust the listing taken above: an ingest running in
            # another process adds files between the listdir and this loop, and
            # every one of them used to be reported as a missing file (585 false
            # positives on the first instruments run).
            if os.path.isfile(os.path.join(d, fn)):
                continue
            reasons = _violation_reasons(meta if isinstance(meta, dict) else {})
            reasons.append('file missing from library')
            bad.append({'id': fn, 'name': fn, 'file': fn, 'size': 0, 'anchor': 'audio', 'violations': reasons})
        return bad
    except Exception as e:
        log(f'[ambience] audit failed: {e}')
        return []


def training_gate(paths, log_fn=None):
    """May these audio files be fed to a model as INPUT? (training, fine-tuning,
    or voice-clone reference — anything where the audio reaches network weights
    or conditions a generator.)

    `paths` = filesystem paths, or (cat, file_id) refs. A path is checked by
    resolving it against every audio category's library dir, so an ABSOLUTE path
    into data/asset_libraries/vocal_fx/ is caught exactly like the ref form —
    that is the shape a voice-clone reference actually arrives in.

    Returns {'ok': bool, 'violations': [{'path','cat','id','reasons'}]}.

    Fails CLOSED: a file that lives in a library dir but whose sidecar cannot be
    read is refused, because "no metadata" is indistinguishable from "metadata
    that forbids this". Files OUTSIDE every library dir pass untouched — this
    fence governs the licensed library, not the pipeline's own renders.

    There is deliberately NO env override (see the module docstring).
    """
    log = log_fn or _log_noop
    violations = []
    try:
        from zyg_workflows import asset_library_service as AL

        audio_cats = [c for c, i in AL.categories().items() if i.get('kind') == 'audio']
        dirs = {c: os.path.realpath(AL._audio_dir(c)) for c in audio_cats}
        for ref in paths or []:
            cat = fid = None
            if isinstance(ref, (tuple, list)) and len(ref) >= 2:
                cat, fid = ref[0], ref[1]
            else:
                rp = os.path.realpath(str(ref))
                parent = os.path.dirname(rp)
                for c, d in dirs.items():
                    if parent == d:
                        cat, fid = c, os.path.basename(rp)
                        break
                if cat is None:
                    continue  # not a library file — not our business
            meta = AL.get_audio_meta(cat, fid)
            reasons = []
            if not meta:
                reasons.append('no licence metadata recorded — cannot prove training is permitted')
            elif meta.get('no_ai_training'):
                lic = meta.get('license_id') or 'unknown licence'
                reasons.append(
                    f'licence forbids AI/ML training or model input ({lic}: {meta.get("source") or "see EULA"})'
                )
            if reasons:
                violations.append({'path': str(ref), 'cat': cat, 'id': fid, 'reasons': reasons})
    except Exception as e:
        violations.append({'path': None, 'cat': None, 'id': None, 'reasons': [f'gate error: {e}']})
    for v in violations:
        log(f'[training-gate] REFUSED {v.get("cat")}/{v.get("id")}: ' + '; '.join(v['reasons']))
    return {'ok': not violations, 'violations': violations}
