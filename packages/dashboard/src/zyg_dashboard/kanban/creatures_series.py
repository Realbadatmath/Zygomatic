# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban/creatures_series.py — medusa pictures, creature datasets/bakeoffs and the series + children's-series listings.

Split verbatim out of ``kanban_server.py`` (lines 892-1500) on 2026-10-06; the handler
re-imports every name from here, so ``zyg_dashboard.kanban_server.<name>`` still resolves.
"""

import os
import json
from urllib.parse import quote as _urlquote
from zyg_dashboard.kanban.common import HERE, _DATA_OUTPUT_ROOT, _OUTPUT_ROOT, _RUNTIME, _zyg_log
from zyg_dashboard.kanban.review_mesh import _CREATURE_ID_RE, _CREATURE_ROOT, _NAME_RE, _api_pictures

# ── Medusa pictures (2026-09-23) ─────────────────────────────────────────────
# Medusa's Library is ONE card, "Pictures", and this fills it: every picture
# that app has made, newest first, in one list.
#
# Two sources, because Medusa makes pictures two ways and neither half alone is
# "every picture":
#   chat — picture_generate inside a Vicky/Victor turn. Those render through the
#          SHARED still service into output/video_studio/_stills, a folder Video
#          Studio writes to as well, so the file itself says nothing about which
#          app ordered it. The sidecar's "medusa": true is the only durable
#          answer (video_stills writes it now; the ones rendered before that was
#          recorded were backfilled from the Medusa chat store) — the job
#          registry is in-memory and pruned, and a chat can be deleted.
#   char — the renders a Medusa CHARACTER owns (sheets, cells, validation).
#          Already listed and already scope-guarded: _api_pictures('medusa').
#
# Fail-closed like the rest of the scope: any scope but 'medusa' gets an empty
# list rather than Medusa content leaking into the default app.
_MEDUSA_STILL_DIR = os.path.join(_OUTPUT_ROOT, 'video_studio', '_stills')


def _medusa_still_side(fp):
    """The sidecar written beside one still, or {} when there is none."""
    try:
        with open(os.path.splitext(fp)[0] + '.json', encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _medusa_still_path(name):
    """Absolute path of ONE Medusa still by file name, or None.

    A still whose sidecar does not flag it as Medusa's is not one of these
    pictures and is refused here exactly like a file that does not exist — so
    this route can never be used to read the Video Studio stills sitting in the
    same folder."""
    if not name or os.path.basename(name) != name or name.startswith('.'):
        return None
    if os.path.splitext(name)[1].lower() != '.png':
        return None
    fp = os.path.realpath(os.path.join(_MEDUSA_STILL_DIR, name))
    if not (fp.startswith(os.path.realpath(_MEDUSA_STILL_DIR) + os.sep) and os.path.isfile(fp)):
        return None
    return fp if _medusa_still_side(fp).get('medusa') else None


def _api_medusa_pictures(scope):
    if scope != 'medusa':
        return {'pictures': []}
    out = []
    try:
        names = os.listdir(_MEDUSA_STILL_DIR)
    except OSError:
        names = []
    for name in names:
        fp = _medusa_still_path(name)
        if not fp:
            continue
        side = _medusa_still_side(fp)
        try:
            mtime = os.path.getmtime(fp)
        except OSError as _exc:
            _zyg_log.debug('%s not statable, left out of the stills: %s', fp, _exc)
            continue
        url = '/inspect/medusa-img?scope=medusa&name=' + _urlquote(name)
        out.append(
            {
                'src': 'chat',
                'key': 'still:' + name,
                'url': url,
                'thumb': url + '&thumb=1',
                'title': (side.get('prompt') or name).strip(),
                'sub': 'Chat picture',
                'prompt': side.get('prompt') or '',
                'negative': side.get('negative') or '',
                'family': side.get('family') or '',
                'seed': side.get('seed'),
                'w': side.get('width') or 0,
                'h': side.get('height') or 0,
                'seconds': side.get('seconds') or 0,
                'backend': side.get('backend') or '',
                'file': name,
                'mtime': mtime,
            }
        )
    # The same character renders /inspect/api/pictures already serves for this
    # scope — listed through it rather than re-walked, so the two views can
    # never disagree about which characters are Medusa's.
    for p in _api_pictures('medusa').get('pictures') or []:
        url = (
            '/inspect/img?scope=medusa&id='
            + _urlquote(str(p.get('id') or ''))
            + '&cat='
            + _urlquote(str(p.get('cat') or ''))
            + '&name='
            + _urlquote(str(p.get('file') or ''))
        )
        out.append(
            {
                'src': 'character',
                'key': 'char:%s:%s:%s' % (p.get('id'), p.get('cat'), p.get('file')),
                'url': url,
                'thumb': url + '&thumb=1',
                'title': p.get('name') or p.get('id') or '',
                'sub': p.get('label') or '',
                'prompt': '',
                'char': p.get('id') or '',
                'file': p.get('file') or '',
                'mtime': p.get('mtime') or 0,
            }
        )
    out.sort(key=lambda x: x.get('mtime') or 0, reverse=True)
    return {'pictures': out}


# ── Creatures (2026-08-26) ───────────────────────────────────────────────────
# A creature is neither a character (no /inspect/api/char shape: no arcane, no
# valve, no expansion) nor a loose picture, and its two halves live in two trees:
# the DATASET (lora-datasets/creatures/<id> — brief, contact sheet, anchor locks)
# and the TRAINED WEIGHTS (lora-outputs/creatures/<id>/lora-weights-<family>).
# Neither half alone answers "what did I make and can I use it", so the tab
# joins them per id and reads the runtime job for live status.
_CREATURE_OUT_ROOT = os.path.realpath(
    os.environ.get('ZYG_CREATURE_OUTPUTS', os.path.expanduser('~/lora-outputs/creatures'))
)
# Which subdirectory each image category resolves to, relative to the DATASET
# dir — except 'val', the one category that lives in the OUTPUT tree.
_CREATURE_CATS = {
    'preview': ('', 'Preview render'),
    'sheet': ('contact_sheet', 'Contact sheet'),
    'cell': (os.path.join('contact_sheet', 'cells'), 'Sheet cell'),
    'anchor': (os.path.join('contact_sheet', 'anchors'), 'Anchor'),
    'lock': ('locks', 'Operator lock'),
    'ref': ('', 'Reference'),
    'val': ('__out__', 'Validation'),
    # 2026-09-01: renders of the image->mesh reconstruction (TRELLIS.2). These are
    # NOT the procedural prop-mesh beauty renders under data/assets/prop_meshes --
    # that asset is a different mesh built by prop_mesh/pufferball.py. This lane is
    # the reconstruction, kept beside the creature it reconstructs so the two can be
    # compared without leaving the card.
    'mesh': ('mesh_trellis', 'Mesh reconstruction'),
    # 2026-09-02: what Creature Studio's toolbox bakes. Its own category so a
    # derived edit can never be confused with a pipeline image, and so nothing
    # in the studio's dock can reach a preview, a cell, a lock or a reference
    # when it deletes ([[creature_fx]]).
    'studio': ('studio', 'Studio edit'),
}
# The licence a creature's renders inherit from the base model it was trained
# on. The channel is monetised, so a non-commercial base is a live exposure, not
# a footnote — the tab says so on the card rather than making it a lookup.
_CREATURE_LICENCE = {
    'klein': ('Apache-2.0', True, 'FLUX.2 klein-4B base — commercial use OK'),
    'flux': (
        'FLUX.1-dev non-commercial',
        False,
        'FLUX.1-dev base — NON-COMMERCIAL; renders paused by the licence gate',
    ),
}
# FLUX.1-dev is non-commercial and the channel is monetised, so its renders are
# already paused by the licence gate — a dashboard that keeps displaying them is
# the same exposure in a nicer frame. Every image a flux-family creature owns
# came out of FLUX.1-dev (previews and refs are flux_reference_gen output, sheet
# cells are captioned crops of those refs, validation frames are the flux base
# rendering the trigger), so the whole set is withheld rather than filtered file
# by file. The CARD stays — "what did I make, and may I ship it" is still a
# question, and a blank card answers neither half.
# FLUX.2 klein-4B ('klein') is Apache-2.0 and is NOT affected by this.
_FLUX1_FAMILIES = {'flux', 'flux1', 'flux-dev', 'flux_dev', 'flux.1-dev', 'flux1-dev'}
_FLUX1_BLOCK_NOTE = (
    'FLUX.1-dev imagery is withheld from this tab \u2014 the base licence is '
    'non-commercial and the channel is monetised. Dataset and weights are untouched '
    'on disk; only the display is suppressed.'
)


def _is_flux1(fam):
    """True when a creature's train family is FLUX.1-dev (never FLUX.2 klein)."""
    return (fam or '').strip().lower() in _FLUX1_FAMILIES


def _creature_manifest(ds_dir):
    """manifest.json merged over brief.json for one creature dataset, or {}."""
    man = {}
    for fn in ('manifest.json', 'brief.json'):
        try:
            with open(os.path.join(ds_dir, fn), encoding='utf-8') as fh:
                man = {**(json.load(fh) or {}), **man}
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('%s not readable in %s, skipped: %s', fn, ds_dir, _exc)
            continue
    return man


# Phrases that appear ONLY in lora_trainer_service's own character defaults —
# the two train_mode branches ('identity' and 'body'), both of which describe a
# HUMAN. Until 2026-08-26 there was no creature case, so every creature LoRA was
# validated as "<trigger> person, head and shoulders portrait ... visible pores"
# and its frames came back as people. Training weights are unaffected (a
# validation prompt only renders a sample), but the frames prove nothing about
# the creature — so the tab shows the prompt and says so rather than presenting
# them as the LoRA's own work. Every creature trained BEFORE the fix still has
# such frames on disk, which is why the detector stays.
#
# Matched on SUBJECT phrases, not on attribute words. 'skin texture' and
# 'portrait' were both in this list and both are things a legitimate creature or
# animal brief says — the Pufferball brief reads "Subtle skin texture visible on
# face" and the animal prompt ends "cinematic animal portrait" — so they flagged
# correctly-validated subjects as human. A leading space keeps ' person,' off
# 'salesperson'.
_HUMANISH = (' person,', ' person ', 'head and shoulders portrait', ' body type,', 'visible pores', 'unretouched')


def _val_prompt(weights_dir):
    """The validation prompt the trainer actually rendered with, or ''."""
    try:
        with open(os.path.join(weights_dir, 'simpletuner_config.json'), encoding='utf-8') as fh:
            return str((json.load(fh) or {}).get('validation_prompt') or '')
    except (OSError, ValueError):
        return ''


def _creature_dir(cid, root):
    """realpath of <root>/<cid>, or None — id must be 12-hex and stay inside."""
    if not cid or not _CREATURE_ID_RE.match(cid):
        return None
    d = os.path.realpath(os.path.join(root, cid))
    return d if (d.startswith(root + os.sep) and os.path.isdir(d)) else None


def _creature_weights(cid):
    """{'family','path','size','mtime','dir'} for the trained LoRA, or None.

    The family is read off the directory name (lora-weights-klein), not the
    manifest: the three May creatures predate train_family and would otherwise
    report no licence at all — which for a FLUX-trained creature is the one
    answer that must never be blank.
    """
    out = _creature_dir(cid, _CREATURE_OUT_ROOT)
    if not out:
        return None
    best = None
    for entry in sorted(os.listdir(out)):
        if not entry.startswith('lora-weights-'):
            continue
        wdir = os.path.realpath(os.path.join(out, entry))
        if not (wdir.startswith(out + os.sep) and os.path.isdir(wdir)):
            continue
        fp = os.path.join(wdir, 'pytorch_lora_weights.safetensors')
        if not os.path.isfile(fp):
            continue
        try:
            st = os.stat(fp)
        except OSError as _exc:
            _zyg_log.debug('%s not statable, left out of the weights list: %s', fp, _exc)
            continue
        rec = {
            'family': entry[len('lora-weights-') :] or 'unknown',
            'path': fp,
            'size': st.st_size,
            'mtime': st.st_mtime,
            'dir': wdir,
            'val_prompt': _val_prompt(wdir),
        }
        if best is None or rec['mtime'] > best['mtime']:
            best = rec
    return best


def _creature_job(cid):
    """The runtime job record for one creature, or {}."""
    try:
        with open(os.path.join(_RUNTIME, f'creature_gen_{cid}.json'), encoding='utf-8') as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def _creature_images(cid, ds_dir, weights, fam=''):
    """[{cat,label,name,mtime}] — every image worth looking at, newest first
    within each category, capped per category so one creature cannot flood the
    grid with 48 sheet cells before the previews are reached.

    A FLUX.1-dev creature returns NOTHING: the licence, not the file, is what
    disqualifies it, and every category it owns is flux output."""
    if _is_flux1(fam):
        return []
    caps = {'preview': 12, 'sheet': 4, 'cell': 24, 'anchor': 8, 'lock': 8, 'ref': 24, 'val': 12, 'mesh': 24}
    out = []
    for cat, (sub, label) in _CREATURE_CATS.items():
        # `weights` is None for any creature that has not been trained yet, and
        # the guard below already knew that — it just sat two lines too low, so
        # weights['dir'] was dereferenced first and raised. The handler has no
        # try/except, so the connection closed with NO RESPONSE and the browser
        # reported "TypeError: Failed to fetch" — which reads like a network
        # fault rather than one untrained creature. Three of four creatures had
        # no weights, so the tab was down for the whole list.
        if cat == 'val':
            if not weights or not weights.get('dir'):
                continue
            d = os.path.join(weights['dir'], 'validation_images')
        else:
            d = os.path.join(ds_dir, sub) if sub else ds_dir
        d = os.path.realpath(d)
        root = _CREATURE_OUT_ROOT if cat == 'val' else _CREATURE_ROOT
        if not (d.startswith(root + os.sep) and os.path.isdir(d)):
            continue
        rows = []
        for name in os.listdir(d):
            if not _NAME_RE.match(name):
                continue
            # the dataset root holds previews AND refs side by side
            if cat == 'preview' and not name.startswith('preview_'):
                continue
            if cat == 'ref' and not name.startswith('ref_'):
                continue
            if cat == 'sheet' and not name.startswith('sheet'):
                continue
            fp = os.path.join(d, name)
            try:
                rows.append({'cat': cat, 'label': label, 'name': name, 'mtime': os.stat(fp).st_mtime})
            except OSError as _exc:
                _zyg_log.debug('%s not statable, left out of the asset rows: %s', fp, _exc)
                continue
        # 'mesh' sorts by name too: the files are numbered so the turntable reads
        # front -> round -> clay -> input, which mtime order would scramble.
        rows.sort(key=lambda r: r['name'] if cat in ('cell', 'ref', 'mesh') else -r['mtime'])
        out.extend(rows[: caps.get(cat, 12)])
    return out


def _api_creatures():
    """Every creature: dataset + trained weights + live job status, newest first."""
    out = []
    try:
        ids = sorted(os.listdir(_CREATURE_ROOT))
    except OSError:
        return {'creatures': [], 'error': f'no creature datasets under {_CREATURE_ROOT}'}
    for cid in ids:
        ds = _creature_dir(cid, _CREATURE_ROOT)
        if not ds:
            continue
        man = _creature_manifest(ds)
        job = _creature_job(cid)
        weights = _creature_weights(cid)
        fam = (weights or {}).get('family') or man.get('train_family') or ''
        lic, lic_ok, lic_note = _CREATURE_LICENCE.get(
            fam, ('unknown', None, 'no trained weights yet — licence follows the base model')
        )
        report = man.get('sheet_report') or {}
        cells_dir = os.path.join(ds, 'contact_sheet', 'cells')
        n_cells = len([f for f in os.listdir(cells_dir) if _NAME_RE.match(f)]) if os.path.isdir(cells_dir) else 0
        n_train = (
            len([f for f in os.listdir(os.path.join(ds, 'training')) if _NAME_RE.match(f)])
            if os.path.isdir(os.path.join(ds, 'training'))
            else 0
        )
        try:
            mtime = os.stat(weights['path']).st_mtime if weights else os.stat(ds).st_mtime
        except OSError:
            mtime = 0
        # Per-creature isolation. Whatever is wrong with ONE creature's files, the
        # other three must still reach the grid — the tab exists to inspect them,
        # and a list that renders nothing is worse than a list with one gap in it.
        try:
            images, img_error = _creature_images(cid, ds, weights, fam), ''
        except Exception as exc:  # noqa: BLE001
            images, img_error = [], '%s: %s' % (type(exc).__name__, exc)
            _zyg_log.info(f'[KANBAN-SERVER] creature {cid}: listing images failed: {exc!r}')
        out.append(
            {
                'id': cid,
                'name': man.get('name') or cid,
                'species': man.get('species') or '',
                'description': man.get('description') or '',
                'body_plan': man.get('body_plan') or '',
                'trigger': man.get('trigger_token') or '',
                'source': man.get('source') or (job.get('creature_options') or {}).get('source') or '',
                'family': fam,
                'licence': lic,
                'licence_ok': lic_ok,
                'licence_note': lic_note,
                'status': job.get('status') or ('completed' if weights else 'unknown'),
                'stage': job.get('stage') or '',
                'error': job.get('error') or '',
                'images_error': img_error,
                'lora': (
                    {'size': weights['size'], 'mtime': weights['mtime'], 'path': weights['path']} if weights else None
                ),
                'val_prompt': (weights or {}).get('val_prompt') or '',
                'val_human': bool(any(w in ((weights or {}).get('val_prompt') or '').lower() for w in _HUMANISH)),
                'sheet_cells': n_cells,
                'train_tiles': n_train,
                'pass_rate': report.get('pass_rate'),
                'soft_count': report.get('soft_count'),
                'excluded': report.get('excluded') or [],
                'mtime': mtime,
                'imagery_blocked': _is_flux1(fam),
                'imagery_note': _FLUX1_BLOCK_NOTE if _is_flux1(fam) else '',
                'hero_image': man.get('hero_image') or None,
                'images': images,
            }
        )
    out.sort(key=lambda c: c['mtime'], reverse=True)
    return {'creatures': out}


def _api_bakeoffs():
    """Model-pathway bake-off runs, newest first.

    A bake-off is not a character, so it has no home in /inspect/api/char or the
    Pictures gallery — both key everything on a character id. It is its own
    shape: N prompts rendered identically on M pathways, and the only useful way
    to look at it is one ROW PER PROMPT with the pathways side by side. Two
    separate galleries would force the comparison to happen from memory, which
    is the one thing the run exists to avoid.

    Images are NOT served by a new route — they already sit under data/output,
    so /inspect/media?path=dout/bakeoff/... reaches them through the existing
    whitelist, realpath containment and medusa block.
    """
    root = os.path.join(_DATA_OUTPUT_ROOT, 'bakeoff')
    runs = []
    if not os.path.isdir(root):
        return {'runs': []}
    for entry in sorted(os.listdir(root), reverse=True):
        rd = os.path.join(root, entry)
        rp = os.path.join(rd, 'report.json')
        if not os.path.isfile(rp):
            continue
        try:
            with open(rp, encoding='utf-8') as fh:
                rep = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('%s not readable, run left out of the list: %s', rp, _exc)
            continue
        pathways, prompts = [], {}
        for res in rep.get('results') or []:
            pw = str(res.get('pathway') or '')
            if not pw:
                continue
            # Cache hits distort the headline: the harness re-uses seeds across
            # runs, so a repeated prompt comes back from Comfy's cache in ~3s.
            # Report both numbers rather than one that quietly flatters.
            secs = [float(i.get('seconds') or 0) for i in (res.get('images') or []) if i.get('ok')]
            uncached = [x for x in secs if x > 5.0]
            pathways.append(
                {
                    'name': pw,
                    'ok': int(res.get('ok_count') or 0),
                    'n': len(res.get('images') or []),
                    'mean': round(sum(secs) / len(secs), 1) if secs else 0,
                    'mean_uncached': round(sum(uncached) / len(uncached), 1) if uncached else 0,
                    'cached': len(secs) - len(uncached),
                    'skipped': res.get('skipped') or '',
                    # character mode: ArcFace similarity vs the verified anchor face
                    'mean_identity': res.get('mean_identity'),
                    'faces_detected': res.get('faces_detected'),
                }
            )
            for img in res.get('images') or []:
                tag = str(img.get('tag') or '')
                slot = prompts.setdefault(tag, {'tag': tag, 'idx': img.get('idx', 0), 'cells': {}})
                fp = str(img.get('path') or '')
                rel = ''
                if fp:
                    try:
                        rel = 'dout/' + os.path.relpath(os.path.realpath(fp), _DATA_OUTPUT_ROOT).replace(os.sep, '/')
                    except ValueError:
                        rel = ''
                    if rel.startswith('dout/..'):
                        rel = ''
                slot['cells'][pw] = {
                    'path': rel,
                    'seconds': img.get('seconds'),
                    'ok': bool(img.get('ok')),
                    'seed': img.get('seed'),
                    'backend': img.get('backend') or '',
                    'identity': img.get('identity'),
                    'identity_verdict': img.get('identity_verdict') or '',
                }
        sheet = rep.get('sheet') or ''
        sheet_rel = ''
        if sheet and os.path.isfile(sheet):
            try:
                sheet_rel = 'dout/' + os.path.relpath(os.path.realpath(sheet), _DATA_OUTPUT_ROOT).replace(os.sep, '/')
            except ValueError:
                sheet_rel = ''

        def _rel(p):
            if not p or not os.path.isfile(p):
                return ''
            try:
                r = 'dout/' + os.path.relpath(os.path.realpath(p), _DATA_OUTPUT_ROOT).replace(os.sep, '/')
            except ValueError:
                return ''
            return '' if r.startswith('dout/..') else r

        ident = rep.get('identity') or {}
        runs.append(
            {
                'id': entry,
                'when': rep.get('when') or entry,
                'size': rep.get('size'),
                'steps': rep.get('steps'),
                'cfg': rep.get('cfg'),
                'seed0': rep.get('seed0'),
                'char': rep.get('char') or '',
                'anchor': _rel(ident.get('anchor')),
                'profile_anchor': _rel(ident.get('profile_anchor')),
                'sheet': sheet_rel,
                'pathways': pathways,
                'prompts': sorted(prompts.values(), key=lambda p: p['idx']),
            }
        )
    return {'runs': runs}


def _api_series():
    """List the prepared storyteller/video series (id + display title) for the Workflows
    'Video' flyout menu. Read-only, same-origin for the :8899 kanban iframe (no auth needed —
    only names/ids are exposed)."""
    fp = os.path.join(HERE, 'data', 'runtime', 'storyteller_templates.json')
    out = []
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        for t in doc.get('templates') or []:
            if not isinstance(t, dict):
                continue
            sid = str(t.get('id') or '').strip()
            if not sid:
                continue
            out.append(
                {
                    'id': sid,
                    'title': str(t.get('series_title') or sid),
                    'order': t.get('order') or 0,
                    'enabled': bool(t.get('enabled', True)),
                }
            )
        out.sort(key=lambda x: (x.get('order') or 0, str(x.get('title') or '')))
    except Exception as e:
        return {'series': [], 'error': str(e)[:120]}
    return {'series': out}


# ── children's series (2026-09-06) ───────────────────────────────────────────

_KS_MOD = {'m': None, 'err': ''}


def _ks_common():
    """kids_series_common, imported lazily and defensively (the _ALIB_MOD
    pattern): a missing or broken module must cost the Kids Series menu, not
    the whole kanban server."""
    if _KS_MOD['m'] is None and not _KS_MOD['err']:
        try:
            from zyg_workflows import kids_series_common

            _KS_MOD['m'] = kids_series_common
        except Exception as e:  # noqa: BLE001 — failure is fatal to the menu only
            _KS_MOD['err'] = f'{type(e).__name__}: {e}'
            _zyg_log.info(f'[KANBAN-SERVER] kids_series_common unavailable — {_KS_MOD["err"]}')
    return _KS_MOD['m']


def _api_kids_series():
    """The ten children's series for the Workflows 'Kids Series' menu.

    GENERIC: nothing here names a series. kids_series_common.discover() re-globs
    pipeline_kids_*.py on every call, so a runner another session is still
    writing simply appears the moment it imports — no edit, no restart. A runner
    that will not import is reported in 'errors' and skipped; one broken file
    must not take the other nine off the board.
    """
    ks = _ks_common()
    if ks is None:
        return {'series': [], 'errors': [{'file': 'kids_series_common.py', 'error': _KS_MOD['err']}]}
    try:
        found = ks.discover()
    except Exception as e:  # noqa: BLE001
        return {'series': [], 'errors': [{'file': 'discover()', 'error': f'{type(e).__name__}: {e}'[:300]}]}
    out = []
    for slug, mod in sorted(found.items()):
        meta = getattr(mod, 'SERIES', {}) or {}
        out.append(
            {
                'slug': str(meta.get('slug') or slug),
                'title': str(meta.get('title') or slug),
                'tagline': str(meta.get('tagline') or ''),
                'voice': bool(meta.get('voice')),
                'characters': bool(meta.get('characters')),
                'gpu': bool(meta.get('gpu')),
                'age_band': str(meta.get('age_band') or ''),
                'episode_seconds': meta.get('episode_seconds'),
                'episodes': meta.get('episodes'),
                'stages': list(getattr(mod, 'STAGES', []) or []),
                'agents': dict(meta.get('agents') or {}),
            }
        )
    try:
        errs = ks.discover_errors()
    except Exception:  # noqa: BLE001
        errs = []
    return {'series': out, 'errors': errs}
