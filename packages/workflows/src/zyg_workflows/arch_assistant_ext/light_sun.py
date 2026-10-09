# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""light_sun — a real sun for Architecture Studio: solar position from a date,
a site latitude/longitude/time-zone and the drawing's north angle.

THE ARITHMETIC (one algorithm, written twice — here and in arch_ext/light_sun.js;
tests_arch_ext/test_light_sun.py proves the two agree to 0.5 degrees).
It is the NOAA Solar Calculator's algorithm, which is Jean Meeus, *Astronomical
Algorithms* (2nd ed., 1998), chapters 7 (Julian day), 22 (obliquity), 25 (solar
coordinates) and 28 (equation of time), in the low-accuracy form NOAA publishes
at gml.noaa.gov/grad/solcalc/calcdetails.html. Accuracy is about 0.01 degrees
for the declination and better than a minute for the equation of time over
1800-2100 — far inside the 0.1 degrees this drawing board needs. No library is
used and none is needed: it is fifteen polynomials and a spherical triangle.

Refraction is NOT applied to `elevation` — that number is the true geometric
altitude of the sun's centre, which is what a shadow is cast from. Sunrise and
sunset DO use the conventional -0.833 degrees (refraction at the horizon plus
the solar semi-diameter), which is why they agree with an almanac.

FRAMES. `azimuth` is the compass bearing of the sun, degrees clockwise from
TRUE north (0 = N, 90 = E, 180 = S, 270 = W). The drawing has its own north:
AR.doc.ext.light_sun.north is how many degrees CLOCKWISE of the drawing's -Z
axis (the top view's "up") true north lies. So the sun's bearing inside the
drawing is `azimuth + north`, and a direction of bearing b is
(sin b, 0, -cos b) in the studio's (x, y, z).

STATE. Everything persists in the drawing: AR.doc.ext.light_sun =
{date, lat, lon, tz, north}. Defaults are Amsterdam on the June solstice.

No third-party package, no network: stdlib only (math, datetime).
"""

from __future__ import annotations

import datetime
import math

from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []

# Amsterdam, June solstice — the default site until someone geolocates the drawing.
DEFAULTS = {'date': '2026-06-21', 'lat': 52.37, 'lon': 4.90, 'tz': 2.0, 'north': 0.0}


# ── the NOAA / Meeus solar position ─────────────────────────────────────────
def parse_date(s, fallback=None) -> tuple:
    """'YYYY-MM-DD' -> (y, m, d). Raises ValueError on anything else."""
    if isinstance(s, (list, tuple)) and len(s) == 3:
        return int(s[0]), int(s[1]), int(s[2])
    txt = str(s or '').strip()
    if not txt:
        if fallback is None:
            raise ValueError('no date')
        return parse_date(fallback)
    parts = txt.replace('/', '-').split('-')
    if len(parts) != 3:
        raise ValueError('date must be YYYY-MM-DD, not %r' % txt)
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    datetime.date(y, m, d)  # refuses 2026-02-31
    return y, m, d


def julian_day(y: int, m: int, d: int, hour_utc: float = 0.0) -> float:
    """Julian Day of the given Gregorian calendar date at `hour_utc` UT.
    Meeus ch. 7 (7.1), valid for any date after the Gregorian reform."""
    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100.0)
    b = 2 - a + math.floor(a / 4.0)
    jd = math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5
    return jd + hour_utc / 24.0


def _julian_century(jd: float) -> float:
    return (jd - 2451545.0) / 36525.0


def _sun_terms(t: float) -> dict:
    """The date-only half of the NOAA sheet: declination (deg) and the
    equation of time (minutes) for Julian century `t`."""
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0  # geometric mean longitude
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)  # geometric mean anomaly
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)  # eccentricity of earth's orbit
    mr = math.radians(m)
    c = (
        math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
        + math.sin(3 * mr) * 0.000289
    )  # equation of centre
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))  # corrected obliquity
    decl = math.degrees(math.asin(max(-1.0, min(1.0, math.sin(math.radians(eps)) * math.sin(math.radians(app_long))))))
    y = math.tan(math.radians(eps / 2.0)) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0r)
        - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * e * e * math.sin(2 * mr)
    )
    return {'decl': decl, 'eot': eot, 'eps': eps, 'l0': l0}


def solar_position(date, hour: float, lat: float, lon: float, tz: float) -> dict:
    """Sun for a local civil time. `hour` is 0..24 local clock time, `tz` the
    offset from UTC in hours (east positive), `lon` east positive.

    Returns degrees and local decimal hours:
      elevation  true geometric altitude of the sun's centre (negative at night)
      azimuth    compass bearing, clockwise from true north
      declination, eot (minutes), hour_angle
      noon, sunrise, sunset, day_length  (None sunrise/sunset on a polar day/night)
    """
    y, mo, d = parse_date(date)
    hour = float(hour)
    lat, lon, tz = float(lat), float(lon), float(tz)
    jd = julian_day(y, mo, d, hour - tz)
    t = _julian_century(jd)
    s = _sun_terms(t)
    decl, eot = s['decl'], s['eot']

    # true solar time in minutes; 4 minutes of clock per degree of longitude
    tst = (hour * 60.0 + eot + 4.0 * lon - 60.0 * tz) % 1440.0
    ha = tst / 4.0 - 180.0  # degrees, 0 at solar noon
    if ha < -180.0:
        ha += 360.0

    latr, declr, har = math.radians(lat), math.radians(decl), math.radians(ha)
    cos_z = math.sin(latr) * math.sin(declr) + math.cos(latr) * math.cos(declr) * math.cos(har)
    cos_z = max(-1.0, min(1.0, cos_z))
    zenith = math.degrees(math.acos(cos_z))
    elevation = 90.0 - zenith

    sin_z = math.sin(math.radians(zenith))
    if abs(sin_z) < 1e-9 or abs(math.cos(latr)) < 1e-9:
        azimuth = 180.0 if lat >= 0 else 0.0
    else:
        arg = (math.sin(latr) * cos_z - math.sin(declr)) / (math.cos(latr) * sin_z)
        arg = max(-1.0, min(1.0, arg))
        x = math.degrees(math.acos(arg))
        azimuth = (x + 180.0) % 360.0 if ha > 0 else (540.0 - x) % 360.0

    noon = (720.0 - 4.0 * lon - eot + 60.0 * tz) / 60.0  # local decimal hours
    sunrise = sunset = day_length = None
    cos_ha0_den = math.cos(latr) * math.cos(declr)
    if abs(cos_ha0_den) > 1e-9:
        cos_ha0 = math.cos(math.radians(90.833)) / cos_ha0_den - math.tan(latr) * math.tan(declr)
        if -1.0 <= cos_ha0 <= 1.0:
            ha0 = math.degrees(math.acos(cos_ha0))  # degrees of half-day
            sunrise = noon - ha0 / 15.0
            sunset = noon + ha0 / 15.0
            day_length = 2.0 * ha0 / 15.0
    if day_length is None:  # polar day or polar night
        day_length = 24.0 if (lat * decl) > 0 else 0.0

    return {
        'elevation': elevation,
        'azimuth': azimuth,
        'zenith': zenith,
        'declination': decl,
        'eot': eot,
        'hour_angle': ha,
        'noon': noon,
        'sunrise': sunrise,
        'sunset': sunset,
        'day_length': day_length,
    }


def hm(h) -> str:
    """Decimal local hours -> 'HH:MM' (or '—' for a polar day/night)."""
    if h is None:
        return '\u2014'
    h = float(h) % 24.0
    m = int(round(h * 60.0))
    return '%02d:%02d' % ((m // 60) % 24, m % 60)


def direction(azimuth: float, elevation: float, north: float = 0.0) -> tuple:
    """Unit vector pointing from the site TOWARDS the sun, in the studio's
    (x, y, z): y up, -z the drawing's own "north" before `north` is applied."""
    b = math.radians(float(azimuth) + float(north))
    e = math.radians(float(elevation))
    return (math.cos(e) * math.sin(b), math.sin(e), -math.cos(e) * math.cos(b))


# ── the drawing's site ──────────────────────────────────────────────────────
def site(d: Drawing) -> dict:
    """AR.doc.ext.light_sun with the Amsterdam defaults filled in."""
    ext = getattr(d, 'ext', None) or {}
    cur = ext.get('light_sun') if isinstance(ext.get('light_sun'), dict) else {}
    out = dict(DEFAULTS)
    for k in ('lat', 'lon', 'tz', 'north'):
        if k in cur:
            out[k] = _num(cur.get(k), DEFAULTS[k])
    if cur.get('date'):
        try:
            y, m, dd = parse_date(cur['date'])
            out['date'] = '%04d-%02d-%02d' % (y, m, dd)
        except ValueError as _exc:
            _zyg_log.warning('invalid stored sun date %r, keeping the default: %s', cur['date'], _exc)
    return out


DEFAULT_HOUR = 14.0  # the studio's own default time of day (arSunTime)


def _hour_of(d: Drawing, hour=None) -> float:
    if hour is None:
        hour = DEFAULT_HOUR
    return max(0.0, min(24.0, _num(hour, DEFAULT_HOUR)))


def _report(s: dict, st: dict, hour: float) -> str:
    bearing = (s['azimuth'] + st['north']) % 360.0
    return (
        '%s %s local (UTC%+g) at %.4f, %.4f — sun elevation %.2f deg, azimuth %.2f deg from true north '
        '(%.2f deg in the drawing, north offset %g deg). Sunrise %s, solar noon %s, sunset %s, day length %.2f h. '
        'Declination %.2f deg, equation of time %+.1f min.'
        % (
            st['date'],
            hm(hour),
            st['tz'],
            st['lat'],
            st['lon'],
            s['elevation'],
            s['azimuth'],
            bearing,
            st['north'],
            hm(s['sunrise']),
            hm(s['noon']),
            hm(s['sunset']),
            s['day_length'],
            s['declination'],
            s['eot'],
        )
        + ('' if s['elevation'] > 0 else ' The sun is below the horizon: no shadows.')
    )


def t_set_sun(d: Drawing, a, date=None, hour=None, lat=None, lon=None, tz=None, north=None):
    st = site(d)
    if date is not None:
        y, m, dd = parse_date(date, st['date'])
        st['date'] = '%04d-%02d-%02d' % (y, m, dd)
    if lat is not None:
        st['lat'] = max(-90.0, min(90.0, _num(lat, st['lat'])))
    if lon is not None:
        st['lon'] = max(-180.0, min(180.0, _num(lon, st['lon'])))
    if tz is not None:
        st['tz'] = max(-14.0, min(14.0, _num(tz, st['tz'])))
    if north is not None:
        st['north'] = _num(north, st['north']) % 360.0
    h = _hour_of(d, hour)
    # the site is the document's; the hour is a VIEW setting (AR.sunHour), so it
    # travels as a ui command and never lands in ext — the same split as the tab's.
    d.ext['light_sun'] = {'date': st['date'], 'lat': st['lat'], 'lon': st['lon'], 'tz': st['tz'], 'north': st['north']}
    s = solar_position(st['date'], h, st['lat'], st['lon'], st['tz'])
    d.ui.append({'cmd': 'sun', 'args': {'hour': h}})  # the tab re-applies through light_sunApply
    return 'sun set. ' + _report(s, st, h)


def t_sun_position(d: Drawing, a, date=None, hour=None):
    st = site(d)
    if date is not None:
        y, m, dd = parse_date(date, st['date'])
        st['date'] = '%04d-%02d-%02d' % (y, m, dd)
    h = _hour_of(d, hour)
    s = solar_position(st['date'], h, st['lat'], st['lon'], st['tz'])
    return _report(s, st, h)


TOOLS = [
    (
        {
            'name': 'set_sun_model',
            'description': "Set the drawing's solar model: date (YYYY-MM-DD), the hour of the day, site latitude/longitude/"
            'time zone and the north angle, and get back the solar elevation and azimuth it produces. This is '
            'the same solar model the viewport uses, so the shadows follow. Use it before any daylight or '
            'overshadowing question. To move the sun to an hour only, use set_sun.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                    'hour': {'type': 'number', 'description': 'local clock time, 0-24'},
                    'lat': {'type': 'number'},
                    'lon': {'type': 'number'},
                    'tz': {'type': 'number', 'description': 'hours from UTC, east positive'},
                    'north': {
                        'type': 'number',
                        'description': "degrees clockwise of the drawing's -Z that true north lies at",
                    },
                },
                'required': [],
            },
        },
        t_set_sun,
    ),
    (
        {
            'name': 'sun_position',
            'description': "Where the sun is for a date and time at the drawing's site, without changing anything: elevation, "
            'azimuth from true north, sunrise, solar noon, sunset and the day length. Read-only.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                    'hour': {'type': 'number', 'description': 'local clock time, 0-24'},
                },
                'required': [],
            },
        },
        t_sun_position,
    ),
]

BUTTONS = ['l_date', 'l_north', 'l_geo', 'st_geo', 'st_north']

PROMPT = (
    'Sun and site (real solar position, NOAA/Meeus, stored in the drawing as ext.light_sun = '
    '{date, lat, lon, tz, north}; the default site is Amsterdam on 21 June). sun_position(date, hour) reads the '
    'elevation, azimuth, sunrise, solar noon, sunset and day length without touching the drawing; '
    'set_sun_model(date, hour, lat, lon, tz, north) sets them and returns the same numbers (set_sun moves the sun to '
    'an hour of the day only). The dock icons do the same job '
    'in the viewport: press_button("l_date", {"date": "2026-12-21"}) sets the date, '
    'press_button("l_north", {"north": 30}) the north angle (degrees clockwise of the drawing\'s -Z that true north '
    'lies at), press_button("l_geo", {"lat": 52.37, "lon": 4.90, "tz": 2}) and '
    'press_button("st_geo", {"place": "Rotterdam"}) the site (st_geo can resolve a place name through '
    'OpenStreetMap/Nominatim), press_button("st_north") toggles the north arrow in the viewport. '
    'The existing Time icon (and the sun command) now runs through this solar model, so a time of day is a real '
    'sun height for that date and place; below the horizon there are no shadows.'
)

EXAMPLES = [
    {
        'ask': 'how high is the sun here at 3 in the afternoon on the longest day?',
        'calls': [{'tool': 'sun_position', 'args': {'date': '2026-06-21', 'hour': 15}}],
    },
    {
        'ask': 'the site is in Rotterdam and the plan faces 30 degrees off north — set that up for midwinter noon',
        'calls': [
            {
                'tool': 'set_sun_model',
                'args': {'date': '2026-12-21', 'hour': 12, 'lat': 51.92, 'lon': 4.48, 'tz': 1, 'north': 30},
            }
        ],
    },
    {'ask': 'turn on the north arrow', 'calls': [{'tool': 'press_button', 'args': {'id': 'st_north'}}]},
    {
        'ask': 'put the site in Barcelona',
        'calls': [{'tool': 'press_button', 'args': {'id': 'st_geo', 'args': {'place': 'Barcelona'}}}],
    },
]
