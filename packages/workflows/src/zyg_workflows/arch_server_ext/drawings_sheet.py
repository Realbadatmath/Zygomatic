# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""drawings_sheet — the server half: an SVG sheet turned into a vector PDF.

The browser composes the page (arch_ext/drawings_sheet.js) and POSTs it here;
this module is the only place that can run a PDF writer.

Licences of the two libraries used, both installed into the GUI venv
(the `.venv` beside ZYG_CREWS_ROOT):
  * svglib      2.2.0  — BSD 3-Clause
  * reportlab   5.0.1  — BSD 3-Clause
(both pull in lxml (BSD), tinycss2/cssselect2 (BSD) and Pillow (MIT-CMU)).

ROUTES
  pdf  payload {svg, w_mm, h_mm, name} -> (pdf bytes, 'application/pdf', name + '.pdf')

The caller sends the `pdf` body of the composition, not the `svg` one: svglib
drops <pattern> fills and mis-scales nested <svg> viewports, so the tab
flattens the viewports to <g transform> and expands the hatch into clipped
lines before it posts. Nothing is fixed up here — what is drawn is what was
sent.
"""

import os
import re
import tempfile
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


MM = 72.0 / 25.4  # a millimetre in PostScript points
MAX_SVG = 40 * 1024 * 1024  # a sheet larger than this is a mistake


def _slug(s):
    s = re.sub(r'[^a-z0-9]+', '-', str(s or '').lower()).strip('-')
    return s[:64] or 'sheet'


def _num(v, d):
    try:
        f = float(v)
        return f if f > 0 else d
    except (TypeError, ValueError):
        return d


def pdf(payload, method):
    svg = payload.get('svg') or ''
    if not isinstance(svg, str) or '<svg' not in svg:
        return {'error': 'no SVG in the payload', 'code': 400}
    if len(svg) > MAX_SVG:
        return {'error': 'the SVG is %d bytes, over the %d byte limit' % (len(svg), MAX_SVG), 'code': 400}
    w_mm = _num(payload.get('w_mm'), 297.0)
    h_mm = _num(payload.get('h_mm'), 210.0)
    name = _slug(payload.get('name') or 'sheet')

    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF
    except ImportError as exc:  # pragma: no cover
        return {'error': 'svglib/reportlab are not installed in the GUI venv: %s' % exc, 'code': 500}

    fd, path = tempfile.mkstemp(suffix='.svg', prefix='ar_sheet_')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(svg.encode('utf-8'))
        drawing = svg2rlg(path)
    except Exception as exc:  # noqa: BLE001
        return {'error': 'the SVG could not be parsed: %s' % exc, 'code': 400}
    finally:
        try:
            os.unlink(path)
        except OSError as _exc:
            _zyg_log.debug('temporary SVG removal skipped: %s', _exc)
    if drawing is None:
        return {'error': 'the SVG could not be parsed', 'code': 400}

    # The page IS the paper: w_mm x h_mm in points. svg2rlg sizes the drawing
    # from the root width/height, so scale it onto the page if they disagree.
    page_w, page_h = w_mm * MM, h_mm * MM
    dw = float(getattr(drawing, 'width', 0) or 0)
    dh = float(getattr(drawing, 'height', 0) or 0)
    if dw > 0 and dh > 0 and (abs(dw - page_w) > 0.5 or abs(dh - page_h) > 0.5):
        drawing.scale(page_w / dw, page_h / dh)
    drawing.width, drawing.height = page_w, page_h

    try:
        # pageCompression=0: the content stream stays plain text, so the vector
        # drawing in a sheet can be read (and diffed) straight out of the file.
        data = renderPDF.drawToString(drawing, pageCompression=0)
    except Exception as exc:  # noqa: BLE001
        return {'error': 'the PDF writer failed: %s' % exc, 'code': 500}
    if not data.startswith(b'%PDF'):
        return {'error': 'the PDF writer produced something that is not a PDF', 'code': 500}
    return (data, 'application/pdf', name + '.pdf')


def paper(payload, method):
    """The ISO A sizes the tab lays out on, in millimetres (portrait w x h)."""
    return {
        'ok': True,
        'sizes': {'A4': [210, 297], 'A3': [297, 420], 'A2': [420, 594], 'A1': [594, 841]},
        'mm_per_point': 25.4 / 72.0,
    }


ROUTES = {'pdf': pdf, 'paper': paper}
