# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .pricing import (
    BUCKET_S,
    CACHE_PATH,
    CACHE_VERSION,
    DEFAULT_LANES,
    INTERACTIVE_ENTRYPOINTS,
    PROJECTS_DIR,
    TREE_MARKER,
    TREE_MARKER_ROWS,
    TREE_TASK_RE,
    TZ,
    USAGE_KEYS,
    _add,
    _zero,
    _zyg_log,
    datetime,
    json,
    model_key,
    os,
    price_row,
    price_usage,
    re,
    timedelta,
    usage_from_message,
)

# ── transcripts ──────────────────────────────────────────────────────────────


def _ts_iso(v):
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def _tree_task(row: dict):
    """The tree slug and task number if `row` is the spawn prompt the board sends an
    executor, else None. Only the opening rows of a session are offered to this: the
    marker is quoted in any session that merely TALKS about the board (this file is read
    by agents that do), and a substring match anywhere would file those under the tree."""
    if row.get('type') == 'queue-operation':
        text = row.get('content')
    elif row.get('type') == 'user':
        content = (row.get('message') or {}).get('content')
        if isinstance(content, list):
            text = ''.join(b.get('text') or '' for b in content if isinstance(b, dict))
        else:
            text = content
    else:
        return None
    if not isinstance(text, str) or not text.startswith(TREE_MARKER):
        return None
    m = TREE_TASK_RE.match(text)
    return (m.group(1), m.group(2)) if m else None


def parse_transcript(path: str) -> dict:
    """One session file -> {'models': {model: {bucket: [7 counters]}}, 'first', 'last',
    'messages'} plus what the session WAS: 'cwd', 'entrypoint' and, for a board-spawned
    executor, 'tree' and 'task'. Messages are de-duplicated by message id (one line per
    content block, identical usage); the last line of a message wins."""
    seen: dict = {}
    order: list = []
    cwd = entrypoint = None
    tree = task = None
    head = 0
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if head < TREE_MARKER_ROWS and tree is None:
                head += 1
                if TREE_MARKER in line:
                    try:
                        hit = _tree_task(json.loads(line))
                    except ValueError:
                        hit = None
                    if hit:
                        tree, task = hit
            if '"assistant"' not in line or '"usage"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('malformed transcript record skipped: %s', _exc)
                continue
            if row.get('type') != 'assistant':
                continue
            cwd = row.get('cwd') or cwd
            entrypoint = row.get('entrypoint') or entrypoint
            msg = row.get('message') or {}
            usage = msg.get('usage')
            mid = msg.get('id')
            if not usage or not mid or not isinstance(usage, dict):
                continue
            model = model_key(msg.get('model'))
            if model in ('unknown', '<synthetic>'):
                continue
            ts = _ts_iso(row.get('timestamp'))
            if ts is None:
                continue
            if mid not in seen:
                order.append(mid)
            seen[mid] = (model, int(ts // BUCKET_S), usage_from_message(usage))
    models: dict = {}
    first = last = None
    for mid in order:
        model, bucket, vec = seen[mid]
        b = models.setdefault(model, {}).setdefault(str(bucket), [0] * len(USAGE_KEYS))
        for i, k in enumerate(USAGE_KEYS):
            b[i] += vec[k]
        t = bucket * BUCKET_S
        first = t if first is None or t < first else first
        last = t if last is None or t > last else last
    return {
        'models': models,
        'first': first,
        'last': last,
        'messages': len(order),
        'cwd': cwd,
        'entrypoint': entrypoint,
        'tree': tree,
        'task': task,
    }


def _slug_words(slug: str) -> str:
    """A tree slug as plain lowercase words, padded with a space at each end, so a keyword
    can anchor on a word boundary ("...-real-anatomy-..." contains " anatomy ")."""
    return ' ' + re.sub(r'[^a-z0-9]+', ' ', (slug or '').lower()).strip() + ' '


def _norm_kw(kw: str) -> str:
    """A lane keyword in the same alphabet as `_slug_words`, matched as a SUBSTRING so
    both shapes work: `-intro-` becomes ' intro ' and only matches the whole word, while a
    bare stem like `capabilit` still catches "capabilities". Padding is deliberately not
    stripped — it is how a keyword asks for a word boundary."""
    return re.sub(r'[^a-z0-9]+', ' ', (kw or '').lower())


def classify(parsed: dict, lanes: dict = None) -> dict:
    """Which lane one parsed transcript belongs to.

    Returns {'lane', 'side', 'label', 'tree'}: `lane` is production | session_tree |
    interactive, `side` is the production/infrastructure roll-up the operator asked for,
    `label` is the row the tab prints. Order matters — a board executor is a board
    executor whatever directory it was spawned in, so the tree marker is tested first."""
    lanes = lanes or DEFAULT_LANES
    cwd = parsed.get('cwd') or ''
    entrypoint = parsed.get('entrypoint') or ''
    tree = parsed.get('tree')
    if tree:
        words = _slug_words(tree)
        side = None
        for kw in lanes.get('tree_content') or ():
            if _norm_kw(kw) in words:
                side = 'production'
                break
        if side is None:
            for kw in lanes.get('tree_infra') or ():
                if _norm_kw(kw) in words:
                    side = 'infrastructure'
                    break
        if side is None:
            side = 'production' if (lanes.get('tree_default') == 'content') else 'infrastructure'
        return {'lane': 'session_tree', 'side': side, 'label': tree, 'tree': tree}
    for row in lanes.get('workflow_dirs') or ():
        match = (row or {}).get('match')
        if not match or match not in cwd:
            continue
        if row.get('headless_only') and entrypoint in INTERACTIVE_ENTRYPOINTS:
            continue
        return {'lane': 'production', 'side': 'production', 'label': row.get('label') or match, 'tree': None}
    return {'lane': 'interactive', 'side': 'infrastructure', 'label': cwd or 'unknown', 'tree': None}


def _write_json_atomic(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, separators=(',', ':'))
    os.replace(tmp, path)


def scan_transcripts(since: float, projects_dir: str = None, cache_path: str = None) -> dict:
    """Every transcript written since `since` -> {path: parsed}. A file is parsed once
    per (mtime, size); the cache lives in data/runtime and survives restarts. Returns
    {'files': {path: parsed}, 'parsed_now': n, 'skipped': n, 'errors': [...]}."""
    projects_dir = projects_dir or PROJECTS_DIR
    cache_path = cache_path or CACHE_PATH
    cache = _read_cache_at(cache_path)
    files: dict = {}
    parsed_now = errors = 0
    err_list = []
    live = set()
    for root, _dirs, names in os.walk(projects_dir):
        for name in names:
            if not name.endswith('.jsonl'):
                continue
            path = os.path.join(root, name)
            try:
                st = os.stat(path)
            except OSError as _exc:
                _zyg_log.debug('%s vanished while being stat-ed, skipped: %s', path, _exc)
                continue
            if st.st_mtime < since:
                continue
            live.add(path)
            sig = [st.st_mtime_ns, st.st_size]
            hit = cache.get(path)
            if hit and hit.get('sig') == sig:
                files[path] = hit['data']
                continue
            try:
                data = parse_transcript(path)
                parsed_now += 1
            except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
                errors += 1
                err_list.append(f'{os.path.basename(path)}: {type(exc).__name__}: {exc}'[:160])
                continue
            cache[path] = {'sig': sig, 'data': data}
            files[path] = data
    changed = parsed_now > 0
    for path in [p for p in cache if p not in live]:
        # keep entries for files still on disk but older than the window (a wider window
        # can reuse them); drop entries whose file is gone
        if not os.path.exists(path):
            del cache[path]
            changed = True
    if changed:
        try:
            _write_json_atomic(cache_path, {'version': CACHE_VERSION, 'entries': cache})
        except OSError as _exc:
            _zyg_log.warning(
                'parse cache %s not written, the next scan re-reads every transcript: %s', cache_path, _exc
            )
    return {
        'files': files,
        'parsed_now': parsed_now,
        'skipped': len(files) - parsed_now,
        'errors': err_list[:10],
        'error_count': errors,
        'cache_entries': len(cache),
    }


def _read_cache_at(path):
    """The parsed-transcript cache, or an empty one when it was written by a build whose
    parse_transcript had a different shape (the entries are keyed on mtime+size alone, so
    a stale entry would be reused forever without a field this build needs)."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get('version') != CACHE_VERSION or not isinstance(data.get('entries'), dict):
        return {}
    return data['entries']


def aggregate(files: dict, start: float, end: float) -> dict:
    """Per-model usage vectors for messages with start <= t < end."""
    out: dict = {}
    for data in files.values():
        for model, buckets in (data.get('models') or {}).items():
            acc = out.setdefault(model, _zero())
            for bk, vec in buckets.items():
                t = int(bk) * BUCKET_S
                if start <= t < end:
                    _add(acc, vec)
    return {m: v for m, v in out.items() if v['messages']}


def aggregate_lanes(files: dict, start: float, end: float, lanes: dict = None) -> dict:
    """Per-lane usage for messages with start <= t < end.

    {(lane, side, label): {'usage': vec, 'sessions': n, 'models': {model: vec}}} — the same
    window and the same messages `aggregate` sees, cut by who spent them instead of by
    which model spent them, so the two add up to the same API-equivalent total."""
    lanes = lanes or DEFAULT_LANES
    out: dict = {}
    for data in files.values():
        who = classify(data, lanes)
        key = (who['lane'], who['side'], who['label'])
        row = out.get(key)
        if row is None:
            row = out[key] = {'usage': _zero(), 'sessions': 0, 'models': {}, 'tree': who['tree']}
        touched = False
        for model, buckets in (data.get('models') or {}).items():
            for bk, vec in buckets.items():
                t = int(bk) * BUCKET_S
                if not (start <= t < end):
                    continue
                _add(row['usage'], vec)
                _add(row['models'].setdefault(model, _zero()), vec)
                touched = True
        if touched:
            row['sessions'] += 1
    return {k: v for k, v in out.items() if v['usage']['messages']}


def daily_series(files: dict, start: float, end: float) -> dict:
    """{'keys': [YYYY-MM-DD...], 'by_model': {model: [usd per day]}} in Europe/Amsterdam days."""
    d = datetime.fromtimestamp(start, TZ).date()
    last = datetime.fromtimestamp(end, TZ).date()
    keys = []
    while d <= last:
        keys.append(d.isoformat())
        d += timedelta(days=1)
    idx = {k: i for i, k in enumerate(keys)}
    by_model: dict = {}
    for data in files.values():
        for model, buckets in (data.get('models') or {}).items():
            rates = price_row(model)
            if not rates:
                continue
            series = by_model.setdefault(model, [0.0] * len(keys))
            for bk, vec in buckets.items():
                t = int(bk) * BUCKET_S
                if not (start <= t < end):
                    continue
                i = idx.get(datetime.fromtimestamp(t, TZ).date().isoformat())
                if i is None:
                    continue
                u = dict(zip(USAGE_KEYS, vec))
                series[i] += price_usage(model, u, rates) or 0.0
    return {'keys': keys, 'by_model': {m: [round(v, 4) for v in s] for m, s in by_model.items()}}
