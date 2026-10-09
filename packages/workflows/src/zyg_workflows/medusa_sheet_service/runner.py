# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.medusa_sheet_service.constants import (
    Callable,
    _WORKERS,
    detectors_available,
    json,
    os,
    threading,
    time,
)
from zyg_workflows.medusa_sheet_service.analysis import analyze_image, caption_for
from zyg_workflows.medusa_sheet_service.montage import _duplicate_groups, build_montage, coverage_report

import logging as _zyg_logging

# Bound by ASSIGNMENT (not `from .constants import _zyg_log`) so the moved
# `_zyg_log.debug(...)` calls keep compiling to the same method form; the
# channel is kept from the pre-split module.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.medusa_sheet_service')

# ══════════════════════════════════════════════════════════════════════════
# Job runner
# ══════════════════════════════════════════════════════════════════════════
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def get_status(char_id: str) -> dict | None:
    with _jobs_lock:
        j = _jobs.get(char_id)
        return dict(j) if j else None


def _set(char_id: str, **kw) -> None:
    with _jobs_lock:
        j = _jobs.setdefault(char_id, {})
        j.update(kw)


def is_running(char_id: str) -> bool:
    j = get_status(char_id)
    return bool(j and j.get('running'))


def sheet_dir(char_dir: str) -> str:
    return os.path.join(char_dir, 'contact_sheet')


def sheet_json_path(char_dir: str) -> str:
    return os.path.join(sheet_dir(char_dir), 'sheet.json')


def load_sheet(char_dir: str) -> dict | None:
    p = sheet_json_path(char_dir)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def summary_path(char_dir: str) -> str:
    return os.path.join(sheet_dir(char_dir), 'sheet_summary.json')


def load_summary(char_dir: str) -> dict | None:
    """The small half of sheet.json — everything except the per-image array.

    Listing 80 characters must not mean parsing 80 full sheet.json files (each
    carrying a per-image measurement array) just to show a coverage percentage.
    Falls back to the full file for sheets built before this split existed.
    """
    p = summary_path(char_dir)
    if os.path.isfile(p):
        try:
            with open(p, encoding='utf-8') as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                return d
        except Exception as _exc:
            _zyg_log.debug('sheet summary %s unreadable, falling back to the full sheet: %s', p, _exc)
    full = load_sheet(char_dir)
    if not full:
        return None
    return {k: v for k, v in full.items() if k != 'images'}


def build_sheet(
    char_id: str,
    char_dir: str,
    *,
    trigger: str = '',
    suffix: str = '',
    write_captions: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Classify every training image, caption it, QC it, assemble the montage.

    Synchronous. Callers wanting a background run should use start_build().
    """

    def log(msg: str) -> None:
        if log_fn:
            try:
                log_fn(msg)
            except Exception as _exc:
                _zyg_log.debug('log callback raised, message dropped: %s', _exc)

    t0 = time.time()
    train_dir = os.path.join(char_dir, 'training')

    # The character may have been deleted while this build sat in the queue —
    # an 80-folder import queues dozens of builds behind one pump thread, so
    # the wait can be minutes. Bail rather than os.makedirs it back into
    # existence, which would resurrect a metadata-less directory that the
    # Training tab cannot render (and therefore cannot delete again).
    if not os.path.isdir(char_dir):
        _set(
            char_id,
            running=False,
            done=False,
            failed=True,
            error='character was deleted before its sheet could be built',
        )
        return {'ok': False, 'error': 'character no longer exists'}

    out_dir = sheet_dir(char_dir)
    os.makedirs(out_dir, exist_ok=True)

    try:
        names = sorted(n for n in os.listdir(train_dir) if n.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')))
    except OSError:
        names = []

    total = len(names)
    _set(
        char_id,
        running=True,
        done=False,
        failed=False,
        error=None,
        total=total,
        processed=0,
        started_at=time.time(),
        phase='classify',
    )
    log(f'[sheet] {char_id}: classifying {total} image(s) with {_WORKERS} worker(s)')

    if not total:
        _set(char_id, running=False, done=False, failed=True, error='no images to classify')
        return {'ok': False, 'error': 'no images to classify'}

    ok, why = detectors_available()
    if not ok:
        _set(char_id, running=False, done=False, failed=True, error=why)
        return {'ok': False, 'error': why}

    measures: list[dict] = []
    m_lock = threading.Lock()
    counter = {'n': 0}

    def worker(subset: list[str]) -> None:
        for n in subset:
            try:
                m = analyze_image(os.path.join(train_dir, n))
            except Exception as exc:
                m = {'file': n, 'error': f'{exc.__class__.__name__}: {exc}'}
            with m_lock:
                measures.append(m)
                counter['n'] += 1
                if counter['n'] % 10 == 0 or counter['n'] == total:
                    _set(char_id, processed=counter['n'])

    chunks: list[list[str]] = [[] for _ in range(_WORKERS)]
    for i, n in enumerate(names):
        chunks[i % _WORKERS].append(n)
    threads = [threading.Thread(target=worker, args=(c,), daemon=True) for c in chunks if c]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    measures.sort(key=lambda m: m.get('file') or '')

    # A detector that failed to initialise (truncated bundle, native-lib or
    # memory failure) errors on EVERY image. Without this check that lands as a
    # cheerful "sheet built, 0% coverage" with placeholder captions intact —
    # and worse, sheets/build-all would then skip the character forever as
    # 'already built'. Fail loudly instead, and write no sheet.json.
    if measures and all(m.get('error') for m in measures):
        why = next((m['error'] for m in measures if m.get('error')), 'unknown')
        _set(char_id, running=False, done=False, failed=True, error=f'every image failed to analyse ({why})')
        log(f'[sheet] {char_id}: aborted — every image failed ({why})')
        return {'ok': False, 'error': f'every image failed to analyse: {why}'}

    _set(char_id, processed=total, phase='caption')

    # Captions — rewritten from the fixed vocabulary.
    captions_written = 0
    if write_captions:
        for m in measures:
            if m.get('error'):
                continue
            txt = os.path.join(train_dir, os.path.splitext(m['file'])[0] + '.txt')
            try:
                with open(txt, 'w', encoding='utf-8') as fh:
                    fh.write(caption_for(m, trigger, suffix))
                captions_written += 1
            except OSError as _exc:
                _zyg_log.warning('caption write to %s failed, the image stays uncaptioned: %s', txt, _exc)

    _set(char_id, phase='montage')
    log(f'[sheet] {char_id}: assembling montage')
    try:
        pages = build_montage(measures, train_dir, out_dir)
    except Exception as exc:
        pages = []
        log(f'[sheet] {char_id}: montage failed ({exc.__class__.__name__}: {exc})')

    cov = coverage_report(measures)
    dupes = _duplicate_groups(measures)
    flagged = [m['file'] for m in measures if m.get('flags')]

    sheet = {
        'char_id': char_id,
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'duration_s': round(time.time() - t0, 1),
        'image_count': total,
        'captions_written': captions_written,
        'coverage': cov,
        'duplicate_groups': dupes,
        'flagged': flagged,
        'pages': [os.path.basename(p) for p in pages],
        'trigger': trigger,
        'images': measures,
    }
    try:
        for path, payload in (
            (sheet_json_path(char_dir), sheet),
            (summary_path(char_dir), {k: v for k, v in sheet.items() if k != 'images'}),
        ):
            tmp = f'{path}.tmp.{os.getpid()}'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, path)
    except OSError as exc:
        _set(char_id, running=False, failed=True, error=f'could not write sheet.json: {exc}')
        return {'ok': False, 'error': 'could not write sheet.json'}

    _set(
        char_id,
        running=False,
        done=True,
        failed=False,
        phase='done',
        finished_at=time.time(),
        coverage_pct=cov['yaw_coverage_pct'],
    )
    log(
        f'[sheet] {char_id}: done in {sheet["duration_s"]}s — '
        f'yaw coverage {cov["yaw_coverage_pct"]}%, {len(flagged)} flagged, {len(dupes)} dupe group(s)'
    )
    return {'ok': True, 'sheet': sheet}


# Builds run through a SINGLE serialising worker rather than a thread each.
# An 80-character import would otherwise spawn 80 concurrent builds x _WORKERS
# threads apiece and thrash a box that already caps itself at 20 of 24 cores.
# One build at a time already saturates _WORKERS cores, so this costs nothing.
_queue: list[tuple[str, str, dict]] = []
_queue_cv = threading.Condition()
_pump_started = False


def queue_depth() -> int:
    with _queue_cv:
        return len(_queue)


def forget(char_id: str) -> None:
    """Drop a character from the queue and the status table.

    Called when the character is deleted. Without this the stale _jobs entry
    keeps api_training_list_sheets rendering a card for a character that no
    longer exists — one the Training tab cannot show a Delete button for.
    """
    with _queue_cv:
        _queue[:] = [q for q in _queue if q[0] != char_id]
    with _jobs_lock:
        _jobs.pop(char_id, None)


def _pump() -> None:
    while True:
        with _queue_cv:
            while not _queue:
                _queue_cv.wait()
            char_id, char_dir, kw = _queue.pop(0)
        try:
            build_sheet(char_id, char_dir, **kw)
        except Exception as exc:
            _set(char_id, running=False, done=False, failed=True, error=f'{exc.__class__.__name__}: {exc}')


def _ensure_pump() -> None:
    global _pump_started
    with _jobs_lock:
        if _pump_started:
            return
        _pump_started = True
    threading.Thread(target=_pump, daemon=True, name='medusa-sheet-pump').start()


def start_build(char_id: str, char_dir: str, **kw) -> bool:
    """Enqueue a sheet build. False if this character is already queued/running."""
    _ensure_pump()
    with _queue_cv:
        if any(q[0] == char_id for q in _queue):
            return False
        if is_running(char_id):
            return False
        _set(char_id, running=True, done=False, failed=False, error=None, phase='queued', processed=0, total=0)
        _queue.append((char_id, char_dir, kw))
        _queue_cv.notify()
    return True
