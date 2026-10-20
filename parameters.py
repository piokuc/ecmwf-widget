"""Catalogue of the parameters published in ECMWF's 0.1 deg open data tier.

Every parameter of the 0.1 deg IFS open subset is listed here with a human
readable label, the unit it is stored in and the group it belongs to. The
service uses this to turn a short parameter list into a request and to turn
raw GRIB values into something a widget can display.

Values in the GRIB files are SI. The ``display`` helpers convert them to the
units a person expects (degrees Celsius, hPa, mm).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable

__all__ = [
    "BASIC_PARAMETERS",
    "DERIVED",
    "PARAMETERS",
    "Parameter",
    "apparent_temperature",
    "available_pl",
    "available_sfc",
    "get",
    "names",
    "to_display",
    "wind_direction",
    "wind_speed",
]


@dataclasses.dataclass(frozen=True)
class Parameter:
    """One published parameter."""

    name: str
    label: str
    units: str
    levtype: str
    group: str
    basic: bool = False
    step_only: tuple[int, ...] = ()

    @property
    def levels(self) -> tuple[int, ...]:
        """Pressure levels this parameter is published on."""
        return PRESSURE_LEVELS if self.levtype == "pl" else ()


#: The pressure levels published by the 0.1 deg tier.
PRESSURE_LEVELS: tuple[int, ...] = (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50, 10)


def _p(name, label, units, levtype, group, basic=False, step_only=()):
    return Parameter(name, label, units, levtype, group, basic, step_only)


#: Everything the 0.1 deg tier publishes. Surface parameters live in
#: ``PARAMETERS``, pressure level ones in ``PRESSURE_PARAMETERS``. They are
#: kept apart because a few short names exist in both (notably ``z``, which is
#: the orography on the surface and the geopotential on a pressure level).
PARAMETERS: dict[str, Parameter] = {
    p.name: p
    for p in [
        # --- surface -------------------------------------------------------- #
        _p("2t", "Temperature", "K", "sfc", "temperature", basic=True),
        _p("2d", "Dew point", "K", "sfc", "temperature", basic=True),
        _p("skt", "Skin temperature", "K", "sfc", "temperature"),
        _p("mx2t3", "Max 2 m temperature (3 h)", "K", "sfc", "temperature"),
        _p("mn2t3", "Min 2 m temperature (3 h)", "K", "sfc", "temperature"),
        _p("mx2t6", "Max 2 m temperature (6 h)", "K", "sfc", "temperature"),
        _p("mn2t6", "Min 2 m temperature (6 h)", "K", "sfc", "temperature"),
        _p("tcw", "Total column water", "kg m-2", "sfc", "humidity"),
        _p("tcwv", "Total column water vapour", "kg m-2", "sfc", "humidity"),
        _p("tciw", "Total column cloud ice water", "kg m-2", "sfc", "humidity"),
        _p("tclw", "Total column cloud liquid water", "kg m-2", "sfc", "humidity"),
        _p("tcrw", "Total column rain water", "kg m-2", "sfc", "humidity"),
        _p("msl", "Pressure", "Pa", "sfc", "pressure", basic=True),
        _p("sp", "Surface pressure", "Pa", "sfc", "pressure"),
        _p("10u", "Wind U", "m s-1", "sfc", "wind", basic=True),
        _p("10v", "Wind V", "m s-1", "sfc", "wind", basic=True),
        _p("100u", "Wind U 100 m", "m s-1", "sfc", "wind"),
        _p("100v", "Wind V 100 m", "m s-1", "sfc", "wind"),
        _p("10fg", "Gust", "m s-1", "sfc", "wind", basic=True),
        _p("tcc", "Cloud cover", "%", "sfc", "cloud", basic=True),
        _p("hcc", "High cloud cover", "%", "sfc", "cloud"),
        _p("mcc", "Medium cloud cover", "%", "sfc", "cloud"),
        _p("lcc", "Low cloud cover", "%", "sfc", "cloud"),
        _p("tp", "Precipitation total", "m", "sfc", "precipitation", basic=True),
        _p("cp", "Convective precipitation", "m", "sfc", "precipitation"),
        _p("sf", "Snowfall (water equivalent)", "m", "sfc", "precipitation"),
        _p("tprate", "Total precipitation rate", "kg m-2 s-1", "sfc", "precipitation"),
        _p("ptype", "Precipitation type", "code table", "sfc", "precipitation"),
        _p("sd", "Snow depth (water equivalent)", "m", "sfc", "precipitation"),
        _p("rsn", "Snow density", "kg m-3", "sfc", "precipitation"),
        _p("asn", "Snow albedo", "%", "sfc", "precipitation"),
        _p("mucape", "Most-unstable CAPE", "J kg-1", "sfc", "thermodynamics"),
        _p("lsm", "Land-sea mask", "(0 - 1)", "sfc", "surface"),
        _p("zos", "Sea surface height", "m", "sfc", "sea"),
        _p("sithick", "Sea ice thickness", "m", "sfc", "sea"),
        _p("sve", "Eastward sea-water velocity", "m s-1", "sfc", "sea"),
        _p("svn", "Northward sea-water velocity", "m s-1", "sfc", "sea"),
        _p("ro", "Runoff", "m", "sfc", "water"),
        _p("ssr", "Surface net shortwave radiation", "W m-2", "sfc", "radiation"),
        _p("ssrd", "Surface downward shortwave radiation", "W m-2", "sfc", "radiation"),
        _p("str", "Surface net longwave radiation", "W m-2", "sfc", "radiation"),
        _p("strd", "Surface downward longwave radiation", "W m-2", "sfc", "radiation"),
        _p("ttr", "Top net longwave radiation", "W m-2", "sfc", "radiation"),
        _p("ewss", "Eastward turbulent surface stress", "N m-2", "sfc", "stress"),
        _p("nsss", "Northward turbulent surface stress", "N m-2", "sfc", "stress"),
        _p("z", "Geopotential (orography)", "m2 s-2", "sfc", "surface", basic=True, step_only=(0,)),
        _p("sdor", "St. dev. of sub-grid orography", "m", "sfc", "surface", step_only=(0,)),
        _p("slor", "Slope of sub-grid orography", "(0 - 1)", "sfc", "surface", step_only=(0,)),
    ]
}

#: Pressure level parameters, published on ``PRESSURE_LEVELS``.
PRESSURE_PARAMETERS: dict[str, Parameter] = {
    p.name: p
    for p in [
        _p("t", "Temperature", "K", "pl", "temperature"),
        _p("u", "U wind component", "m s-1", "pl", "wind"),
        _p("v", "V wind component", "m s-1", "pl", "wind"),
        _p("q", "Specific humidity", "kg kg-1", "pl", "humidity"),
        _p("r", "Relative humidity", "%", "pl", "humidity"),
        _p("z", "Geopotential", "m2 s-2", "pl", "dynamics"),
        _p("gh", "Geopotential height", "gpm", "pl", "dynamics"),
        _p("w", "Vertical velocity", "Pa s-1", "pl", "dynamics"),
        _p("vo", "Relative vorticity", "s-1", "pl", "dynamics"),
        _p("d", "Divergence", "s-1", "pl", "dynamics"),
    ]
}

#: The subset a widget normally shows. Surface parameters only, so the
#: service does not have to pull the much larger pressure level files.
BASIC_PARAMETERS: tuple[str, ...] = tuple(name for name, p in PARAMETERS.items() if p.basic)


# --------------------------------------------------------------------------- #
# Derived quantities
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class Derived:
    """A quantity computed from other parameters."""

    name: str
    label: str
    units: str
    group: str
    needs: tuple[str, ...]
    level: int | None = None
    basic: bool = True


DERIVED: dict[str, Derived] = {
    d.name: d
    for d in [
        Derived("wind_speed", "10 m wind speed", "m s-1", "wind", ("10u", "10v")),
        Derived("wind_dir", "10 m wind direction", "deg", "wind", ("10u", "10v")),
        Derived("gust", "10 m wind gust", "m s-1", "wind", ("10fg",)),
        Derived(
            "apparent_temperature",
            "Apparent temperature",
            "K",
            "temperature",
            ("2t", "2d", "10u", "10v"),
        ),
        Derived("wind_speed_pl", "Wind speed", "m s-1", "wind", ("u", "v"), basic=False),
        Derived("wind_dir_pl", "Wind direction", "deg", "wind", ("u", "v"), basic=False),
    ]
}

#: Derived quantities that are part of the basic set.
BASIC_DERIVED: tuple[str, ...] = tuple(name for name, d in DERIVED.items() if d.basic)


def get(name: str, levtype: str | None = None) -> Parameter | Derived:
    """Look up a parameter or derived quantity by name.

    ``levtype`` disambiguates the short names that exist on more than one
    level type (``z`` for instance).
    """
    if name in DERIVED:
        return DERIVED[name]
    if levtype == "pl" and name in PRESSURE_PARAMETERS:
        return PRESSURE_PARAMETERS[name]
    if levtype == "sfc" and name in PARAMETERS:
        return PARAMETERS[name]
    if name in PARAMETERS:
        return PARAMETERS[name]
    if name in PRESSURE_PARAMETERS:
        return PRESSURE_PARAMETERS[name]
    raise KeyError(name)


def names() -> list[str]:
    """All selectable names (parameters and derived quantities)."""
    return list(PARAMETERS) + list(PRESSURE_PARAMETERS) + list(DERIVED)


def available_sfc() -> list[str]:
    """Surface parameters the 0.1 deg tier publishes."""
    return list(PARAMETERS)


def available_pl() -> list[str]:
    """Pressure level parameters the 0.1 deg tier publishes."""
    return list(PRESSURE_PARAMETERS)


# --------------------------------------------------------------------------- #
# Conversions
# --------------------------------------------------------------------------- #

#: unit -> (multiplier, offset, display unit)
_CONVERSIONS: dict[str, tuple[float, float, str]] = {
    "K": (1.0, -273.15, "degC"),
    "Pa": (0.01, 0.0, "hPa"),
    "m": (1000.0, 0.0, "mm"),
    "m s-1": (1.0, 0.0, "m/s"),
    "%": (1.0, 0.0, "%"),
}


def normalise_units(units: str) -> str:
    """Tidy a GRIB unit string.

    ECMWF writes exponents as ``m s**-1``; the catalogue uses ``m s-1``.
    """
    return units.replace("**", "").strip() if units else ""


#: Parameters that are a depth of water. ECMWF publishes them in metres for
#: the IFS model and in kilograms per square metre, which is the same as
#: millimetres, for the AI models.
_WATER_PARAMS = {"tp", "cp", "sf", "sd", "ro"}

#: Parameters that are a fraction. ECMWF publishes the cloud cover as a
#: fraction for the IFS model and as a percentage for the AI models.
_FRACTION_PARAMS = {"tcc", "hcc", "mcc", "lcc", "asn"}

#: How a parameter is shown: display unit, scale and offset applied to the
#: value stored in the GRIB message. Parameters that are not listed keep
#: their own unit.
_DISPLAY: dict[str, tuple[str, float, float]] = {
    "2t": ("degC", 1.0, -273.15),
    "2d": ("degC", 1.0, -273.15),
    "apparent_temperature": ("degC", 1.0, -273.15),
    "msl": ("hPa", 0.01, 0.0),
    "sp": ("hPa", 0.01, 0.0),
    "wind_speed": ("km/h", 3.6, 0.0),
    "gust": ("km/h", 3.6, 0.0),
    "lsm": ("%", 100.0, 0.0),
    "slor": ("", 1.0, 0.0),
    "q": ("g/kg", 1000.0, 0.0),
    "ptype": ("code", 1.0, 0.0),
    "ewss": ("N m-2", 1.0, 0.0),
    "nsss": ("N m-2", 1.0, 0.0),
}


def display_for(param: str, units: str = "") -> tuple[str, float, float]:
    """Display unit, scale and offset of a parameter.

    The unit the value is stored in matters, because ECMWF publishes the same
    parameter in different units depending on the model: the IFS total
    precipitation is in metres and the AI model publishes it in kilograms per
    square metre, which is millimetres.
    """
    unit = normalise_units(units)

    if param in _WATER_PARAMS:
        return "mm", (1.0 if unit == "kg m-2" else 1000.0), 0.0

    if param in _FRACTION_PARAMS:
        return "%", (1.0 if unit == "%" else 100.0), 0.0

    if param in _DISPLAY:
        return _DISPLAY[param]
    try:
        spec = get(param)
    except KeyError:
        return unit, 1.0, 0.0
    return normalise_units(getattr(spec, "units", "")), 1.0, 0.0


def label_for(param: str, level: int | None = None) -> str:
    """Human readable label, with the pressure level when there is one."""
    try:
        spec = get(param)
        label = getattr(spec, "label", param)
    except KeyError:
        label = param
    if level is not None:
        return f"{label} @{level} hPa"
    return label


#: Standard acceleration used to turn geopotential into height.
GRAVITY = 9.80665

#: Default lapse rate in K per km, used to correct the temperature of a
#: point that sits above the model's own terrain.
LAPSE_RATE = 6.5


def geopotential_to_height(geopotential: float) -> float:
    """Geopotential (m2 s-2) to geometric height above sea level (m)."""
    return geopotential / GRAVITY


def lapse_correction(
    temperature_kelvin: float,
    place_elevation: float | None,
    model_elevation: float | None,
    lapse_rate: float = LAPSE_RATE,
) -> float | None:
    """Temperature corrected to the real elevation of a place.

    A 9 km model cannot resolve a summit, so the forecast it publishes for a
    mountain refers to the height of the surrounding grid cell. Moving the
    value up to the real elevation with a standard lapse rate gives a much
    better estimate.
    """
    if place_elevation is None or model_elevation is None:
        return None
    return temperature_kelvin - (place_elevation - model_elevation) * lapse_rate / 1000.0


def to_display(value: float, units: str, param: str | None = None) -> tuple[float, str]:
    """Convert an SI value into the unit a person expects.

    When ``param`` is given the per parameter display rules apply, otherwise
    the unit alone decides.
    """
    if param is not None:
        display, scale, offset = display_for(param, units)
        return value * scale + offset, display
    key = normalise_units(units)
    if key in _CONVERSIONS:
        scale, offset, display = _CONVERSIONS[key]
        return value * scale + offset, display
    return value, key or units


def wind_speed(u: float, v: float) -> float:
    """Wind speed in m/s from the U and V components."""
    return math.hypot(u, v)


def wind_direction(u: float, v: float) -> float:
    """Meteorological wind direction in degrees (the direction it blows from)."""
    return (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def apparent_temperature(t_kelvin: float, td_kelvin: float, wind: float) -> float:
    """Apparent temperature in K (Australian AT formula, valid for warm conditions).

    The formula itself works in degrees Celsius.
    """
    t_celsius = t_kelvin - 273.15
    td_celsius = td_kelvin - 273.15
    vapour = 6.105 * math.exp(17.27 * td_celsius / (237.7 + td_celsius))
    return t_celsius + 0.33 * vapour - 0.70 * wind - 4.00 + 273.15


def resolve(
    selection: Iterable[str],
) -> tuple[list[str], list[str], list[str]]:
    """Split a selection into surface params, pressure params and derived names."""
    surface: list[str] = []
    pressure: list[str] = []
    derived: list[str] = []
    for name in selection:
        if name in DERIVED:
            derived.append(name)
        elif name in PARAMETERS:
            surface.append(name)
        elif name in PRESSURE_PARAMETERS:
            pressure.append(name)
        else:
            raise KeyError(f"unknown parameter {name!r}")
    return surface, pressure, derived
