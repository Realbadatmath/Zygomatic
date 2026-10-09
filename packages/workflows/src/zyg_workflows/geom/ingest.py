# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ingest.py — admit CC0 / public-domain assets from external libraries (2026-08-04).

Three sources, all keyless, all verified live on 2026-08-04:

  Poly Haven   521 models + 789 textures, ALL CC0 (https://polyhaven.com/license).
               Textures ship Diffuse, Displacement, nor_gl, Rough, AO and Bump at up to
               8k — the displacement is what puts real relief on a trunk instead of a
               painted normal map. Every model entry also carries `polycount` and
               `texel_density` in its metadata, which are two of the gate's inputs
               arriving pre-computed from the source.
               NOTE: the API 403s without a User-Agent header. It is not rate limiting.

  ambientCG    CC0 1.0 for every asset and every preview render. /api/v2/full_json.

  Openverse    ~800M openly licensed items aggregating Flickr, Wikimedia, Europeana,
               Smithsonian and NASA, with the licence on each result. Filtered to cc0
               here; the licence recorded is the one the API reported, never assumed.

WHAT THIS DELIBERATELY DOES NOT DO.
It does not fetch from GBIF/iNaturalist without a per-photo licence read. Their CC0 and
CC-BY filters apply to the OBSERVATION RECORD, not to the attached photograph — a CC-BY-SA
or CC-BY-ND image can legitimately sit inside a CC0 observation. Filtering on the
observation and harvesting the photo would quietly poison a CC0-only library, so those
sources need their own per-media check before they are wired in.

Everything admitted goes through manifest.provenance(), which refuses any licence outside
the allow list rather than warning about it.
"""

import json
import os
import urllib.parse
import urllib.request

from zyg_workflows.contact import contact_email

from . import manifest
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


UA = {'User-Agent': f'zygomatic-asset-ingest/1.0 (+{contact_email()})'}

ASSET_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'assets')

POLYHAVEN_LICENCE = 'CC0'  # https://polyhaven.com/license
AMBIENTCG_LICENCE = 'CC0'  # https://docs.ambientcg.com/


def _open_http(url, *, headers=None, data=None, method=None, timeout=60):
    """``urlopen`` restricted to http/https.

    Plain ``urlopen`` follows ``file:`` and any custom scheme, so a URL that arrives from
    configuration or from an API response can read local files. Headers are needed here, so
    :func:`zyg_workflows.net.safe_urlopen` (which takes a bare URL) cannot be used directly;
    the same scheme check is applied to the composed ``Request`` instead.
    """
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)  # noqa: S310  scheme checked on the next line
    if req.type not in ('http', 'https'):
        raise ValueError(f'refusing to open a {req.type!r} URL: {url!r}')
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310  scheme validated two lines above  # nosec B310


def _get_json(url, headers=UA, timeout=60):
    with _open_http(url, headers=headers, timeout=timeout) as r:
        return json.load(r)


def _download(url, dest, headers=UA, timeout=300):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with _open_http(url, headers=headers, timeout=timeout) as r, open(dest, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    return dest


# ── Poly Haven ───────────────────────────────────────────────────────────────

# Which maps a surface actually needs here. Displacement is not optional: it is the only
# one of these that changes GEOMETRY, and the gate's G3 measures geometry.
PH_MAPS = ('Diffuse', 'Displacement', 'nor_gl', 'Rough', 'AO')


def polyhaven_search(kind='textures', words=()):
    """{id: metadata} filtered by word match over id, tags and categories."""
    d = _get_json('https://api.polyhaven.com/assets?t=%s' % kind)
    if not words:
        return d
    out = {}
    for k, v in d.items():
        hay = ' '.join([k] + list(v.get('tags') or []) + list(v.get('categories') or [])).lower()
        if any(w.lower() in hay for w in words):
            out[k] = v
    return out


def polyhaven_texture(asset_id, res='4k', maps=PH_MAPS, root=None, fmt='png'):
    """Download one CC0 texture set. Returns a material block for the manifest."""
    root = root or os.path.join(ASSET_ROOT, 'materials', asset_id)
    files = _get_json('https://api.polyhaven.com/files/%s' % asset_id)
    info = _get_json('https://api.polyhaven.com/info/%s' % asset_id)
    page = 'https://polyhaven.com/a/%s' % asset_id

    got, prov = {}, []
    for m in maps:
        node = files.get(m)
        if not node:
            continue
        by_res = node.get(res) or node.get('4k') or node.get('2k') or {}
        pick = by_res.get(fmt) or by_res.get('jpg') or by_res.get('exr')
        if not pick or not pick.get('url'):
            continue
        dest = os.path.join(root, '%s.%s' % (m.lower(), pick['url'].rsplit('.', 1)[-1]))
        _download(pick['url'], dest)
        got[m.lower()] = dest
        prov.append(manifest.provenance(dest, POLYHAVEN_LICENCE, 'polyhaven', page, extra={'map': m, 'res': res}))

    if not got:
        raise RuntimeError('polyhaven: no maps downloaded for %s at %s' % (asset_id, res))
    px = int(str(res).lower().rstrip('k')) * 1024 if str(res).lower().endswith('k') else None
    return {
        'maps': got,
        'texture_px': px,
        'licence': manifest.normalise_licence(POLYHAVEN_LICENCE),
        'source': 'polyhaven',
        'url': page,
        'asset_id': asset_id,
        'authors': info.get('authors'),
        'categories': info.get('categories'),
        'provenance': prov,
    }


def polyhaven_model(asset_id, res='4k', root=None):
    """Download one CC0 model (blend preferred, gltf fallback) + its metadata.

    polycount and texel_density come straight from the API, so two gate inputs are known
    before the asset is ever rendered.
    """
    root = root or os.path.join(ASSET_ROOT, 'models', asset_id)
    files = _get_json('https://api.polyhaven.com/files/%s' % asset_id)
    info = _get_json('https://api.polyhaven.com/info/%s' % asset_id)
    page = 'https://polyhaven.com/a/%s' % asset_id

    chosen = None
    for fmt in ('blend', 'gltf', 'fbx', 'usd'):
        node = (files.get(fmt) or {}).get(res) or (files.get(fmt) or {}).get('4k')
        if not node:
            continue
        inner = node.get(fmt) or next(iter(node.values()), None)
        if isinstance(inner, dict) and inner.get('url'):
            chosen = (fmt, inner)
            break
    if not chosen:
        raise RuntimeError('polyhaven: no downloadable mesh for %s' % asset_id)

    fmt, node = chosen
    dest = os.path.join(root, '%s.%s' % (asset_id, node['url'].rsplit('.', 1)[-1]))
    _download(node['url'], dest)
    # a .blend references its textures as siblings; fetch them so the file opens clean
    for rel, sub in (node.get('include') or {}).items():
        if sub.get('url'):
            _download(sub['url'], os.path.join(root, rel.replace('\\', '/')))

    dims = info.get('dimensions') or []
    return {
        'file': dest,
        'format': fmt,
        'polycount': info.get('polycount'),
        'texel_density': info.get('texel_density'),
        'max_resolution': info.get('max_resolution'),
        # Poly Haven publishes dimensions in millimetres
        'world_span_m': (max(dims) / 1000.0) if dims else None,
        'licence': manifest.normalise_licence(POLYHAVEN_LICENCE),
        'source': 'polyhaven',
        'url': page,
        'asset_id': asset_id,
        'provenance': [manifest.provenance(dest, POLYHAVEN_LICENCE, 'polyhaven', page)],
    }


def polyhaven_hdri(asset_id, res='4k', root=None):
    """Download one CC0 HDRI. Returns a material block usable as a world.

    Needed for more than mood: a metallic surface renders whatever is around it, so the
    hurlbat against a flat-colour world came back as a grey cardboard shape no matter what
    its material said. Steel needs an environment to be steel.
    """
    root = root or os.path.join(ASSET_ROOT, 'hdri', asset_id)
    files = _get_json('https://api.polyhaven.com/files/%s' % asset_id)
    info = _get_json('https://api.polyhaven.com/info/%s' % asset_id)
    page = 'https://polyhaven.com/a/%s' % asset_id
    node = (files.get('hdri') or {}).get(res) or (files.get('hdri') or {}).get('4k') or {}
    pick = node.get('hdr') or node.get('exr')
    if not pick or not pick.get('url'):
        raise RuntimeError('polyhaven: no HDRI file for %s at %s' % (asset_id, res))
    dest = os.path.join(root, '%s_%s.%s' % (asset_id, res, pick['url'].rsplit('.', 1)[-1]))
    _download(pick['url'], dest)
    return {
        'maps': {'hdri': dest},
        'texture_px': int(str(res).lower().rstrip('k')) * 1024,
        'licence': manifest.normalise_licence(POLYHAVEN_LICENCE),
        'source': 'polyhaven',
        'url': page,
        'asset_id': asset_id,
        'categories': info.get('categories'),
        'whitebalance': info.get('whitebalance'),
        'provenance': [manifest.provenance(dest, POLYHAVEN_LICENCE, 'polyhaven', page)],
    }


# ── ambientCG ────────────────────────────────────────────────────────────────


def ambientcg_search(query, limit=20, asset_type='Material'):
    q = urllib.parse.urlencode({'q': query, 'type': asset_type, 'limit': limit, 'include': 'downloadData'})
    return _get_json('https://ambientcg.com/api/v2/full_json?' + q).get('foundAssets', [])


def ambientcg_material(asset_id, res='4K', root=None, fmt='PNG'):
    """Download one CC0 ambientCG material zip. Returns a material block."""
    root = root or os.path.join(ASSET_ROOT, 'materials', asset_id)
    hits = ambientcg_search(asset_id, limit=8)
    rec = next((a for a in hits if a.get('assetId') == asset_id), None)
    if not rec:
        raise RuntimeError('ambientcg: %s not found' % asset_id)
    page = 'https://ambientcg.com/view?id=%s' % asset_id

    want = '%s-%s' % (res, fmt)
    url = None
    for folder in (rec.get('downloadFolders') or {}).values():
        for f in (folder.get('downloadFiletypeCategories') or {}).values():
            for d in f.get('downloads') or []:
                if want.lower() in str(d.get('attribute', '')).lower() and d.get('downloadLink'):
                    url = d['downloadLink']
                    break
    if not url:
        raise RuntimeError('ambientcg: no %s download for %s' % (want, asset_id))
    dest = os.path.join(root, '%s_%s.zip' % (asset_id, want))
    _download(url, dest)
    return {
        'maps': {'zip': dest},
        'texture_px': int(str(res).upper().rstrip('K')) * 1024,
        'licence': manifest.normalise_licence(AMBIENTCG_LICENCE),
        'source': 'ambientcg',
        'url': page,
        'asset_id': asset_id,
        'provenance': [manifest.provenance(dest, AMBIENTCG_LICENCE, 'ambientcg', page)],
    }


# ── Openverse ────────────────────────────────────────────────────────────────

# ── Wikimedia Commons ────────────────────────────────────────────────────────

COMMONS_API = 'https://commons.wikimedia.org/w/api.php?'


def _commons(params):
    p = dict(params)
    p['format'] = 'json'
    return _get_json(COMMONS_API + urllib.parse.urlencode(p))


def commons_search(query, limit=40):
    d = _commons({'action': 'query', 'list': 'search', 'srsearch': query, 'srnamespace': 6, 'srlimit': limit})
    return [m['title'] for m in d.get('query', {}).get('search', [])]


def commons_category(name, limit=100):
    d = _commons(
        {
            'action': 'query',
            'list': 'categorymembers',
            'cmtitle': 'Category:' + name,
            'cmtype': 'file',
            'cmlimit': limit,
        }
    )
    return [m['title'] for m in d.get('query', {}).get('categorymembers', [])]


def commons_info(titles):
    """imageinfo + extmetadata for up to 50 titles at a time.

    The licence comes from extmetadata.LicenseShortName, read per file. Commons hosts
    everything from CC0 to fully restricted, and the category a file sits in says nothing
    about its licence — so this is checked per file and never inferred from the query.
    """
    out = {}
    titles = list(titles)
    for i in range(0, len(titles), 50):
        chunk = titles[i : i + 50]
        d = _commons(
            {'action': 'query', 'titles': '|'.join(chunk), 'prop': 'imageinfo', 'iiprop': 'url|size|extmetadata'}
        )
        for page in (d.get('query', {}).get('pages') or {}).values():
            ii = (page.get('imageinfo') or [{}])[0]
            ex = ii.get('extmetadata') or {}
            out[page.get('title', '')] = {
                'url': ii.get('url'),
                'descriptionurl': ii.get('descriptionurl'),
                'width': ii.get('width') or 0,
                'height': ii.get('height') or 0,
                'licence': (ex.get('LicenseShortName') or {}).get('value'),
                'artist': (ex.get('Artist') or {}).get('value'),
                'title': page.get('title', ''),
            }
    return out


IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp')


def commons_refs(
    queries=(), categories=(), count=8, root=None, min_px=800, name_hint='commons', must_match=(), reject=()
):
    """Licence-verified reference images from Commons.

    Titles are gathered from searches and categories, then every candidate's licence is
    read from its own extmetadata and passed to manifest.provenance(), which refuses
    anything outside the allow list. Files that fail the check are skipped and counted,
    not downloaded.

    TWO FILTERS THAT ARE NOT OPTIONAL. Commons full-text search matches the TEXT OF
    DOCUMENTS, so a sweep for "hurlbat" returned fourteen public-domain scans of books,
    newspapers and an EU regulation that merely contain the word — every one of them
    correctly licensed and completely useless. `IMAGE_EXT` drops .pdf/.djvu, and
    `must_match` requires the file's own title to name the thing we are looking for.
    Without both, a licence-clean sweep still fills the library with noise.
    """
    root = root or os.path.join(ASSET_ROOT, 'refs', name_hint)
    titles = []
    for q in queries:
        titles += commons_search(q)
    for c in categories:
        try:
            titles += commons_category(c)
        except Exception as _exc:
            _zyg_log.warning('commons category %s listing failed, continuing without it: %s', c, _exc)
    seen, uniq = set(), []
    for t in titles:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    info = commons_info(uniq)
    out, refused, off_topic = [], 0, 0
    for t, meta in info.items():
        if len(out) >= count:
            break
        low = t.lower()
        if not low.endswith(IMAGE_EXT):
            off_topic += 1
            continue
        if must_match and not any(w.lower() in low for w in must_match):
            off_topic += 1
            continue
        if reject and any(w.lower() in low for w in reject):
            off_topic += 1
            continue
        if not meta.get('url') or min(meta['width'], meta['height']) < min_px:
            continue
        if not manifest.is_allowed(meta.get('licence')):
            refused += 1
            continue
        ext = os.path.splitext(urllib.parse.urlparse(meta['url']).path)[1] or '.jpg'
        safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in t.replace('File:', ''))[:70]
        dest = os.path.join(root, os.path.splitext(safe)[0] + ext)
        try:
            _download(meta['url'], dest)
            out.append(
                manifest.provenance(
                    dest,
                    meta['licence'],
                    'wikimedia-commons',
                    meta.get('descriptionurl') or meta['url'],
                    extra={'title': t, 'artist': meta.get('artist'), 'res': [meta['width'], meta['height']]},
                )
            )
        except manifest.LicenceRefused:
            if os.path.exists(dest):
                os.remove(dest)
            refused += 1
        except Exception:
            if os.path.exists(dest):
                os.remove(dest)
    return out, {'candidates': len(info), 'refused_licence': refused, 'off_topic': off_topic, 'kept': len(out)}


# ── Openverse ────────────────────────────────────────────────────────────────


def openverse_refs(query, count=6, root=None, licences=('cc0', 'pdm'), min_px=900, name_hint=None, pages=3):
    """Fetch photoreal reference images, keeping the licence the API reported.

    The licence is read off each result and passed to manifest.provenance(), which refuses
    anything outside the allow list — so a source that starts returning CC-BY under a cc0
    filter fails loudly here instead of entering the library.

    `query` may be a list, tried in order until `count` images are in hand. Specific
    queries fail hard here: 'hatchet axe wood handle' returned 0 CC0 results while 'axe in
    tree stump' returned 7 above 900px. The corpus is large but sparsely tagged, so the
    fallback chain is doing real work, not being defensive.
    """
    queries = [query] if isinstance(query, str) else list(query)
    root = root or os.path.join(ASSET_ROOT, 'refs', (name_hint or queries[0]).replace(' ', '_'))
    res, seen = [], set()
    for qtext in queries:
        for page in range(1, pages + 1):
            q = urllib.parse.urlencode({'q': qtext, 'license': ','.join(licences), 'page_size': 20, 'page': page})
            try:
                got = _get_json('https://api.openverse.org/v1/images/?' + q).get('results', [])
            except Exception:
                break
            if not got:
                break
            for r in got:
                if r.get('id') and r['id'] not in seen:
                    seen.add(r['id'])
                    res.append(r)
        big = [r for r in res if min(r.get('width') or 0, r.get('height') or 0) >= min_px]
        if len(big) >= count:
            break

    out = []
    for r in res:
        if len(out) >= count:
            break
        w, h = r.get('width') or 0, r.get('height') or 0
        if min(w, h) < min_px:
            continue
        url = r.get('url')
        if not url:
            continue
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
            ext = '.jpg'
        dest = os.path.join(root, '%s%s' % (r.get('id', 'ov')[:16], ext))
        try:
            _download(url, dest)
            out.append(
                manifest.provenance(
                    dest,
                    r.get('license'),
                    'openverse',
                    r.get('foreign_landing_url') or url,
                    extra={
                        'title': r.get('title'),
                        'creator': r.get('creator'),
                        'provider': r.get('source'),
                        'res': [w, h],
                        'attribution': r.get('attribution'),
                    },
                )
            )
        except manifest.LicenceRefused:
            if os.path.exists(dest):
                os.remove(dest)
            raise
        except Exception:
            if os.path.exists(dest):
                os.remove(dest)
    return out
