"""Extract forecast values at a set of points from ECMWF GRIB2 files.

The 0.1 deg tier is published on a regular latitude/longitude grid, so the
value at an arbitrary point can be obtained by interpolating between the four
surrounding grid points. The grid geometry is read from the file itself
rather than assumed, so the same code works for the 0.25 deg tier.

Two interpolation methods are offered:

``bilinear``
    Interpolate between the four surrounding grid points. Smooth, and the
    default.
``nearest``
    Take the value of the closest grid point. Roughly 5 km away at 0.1 deg,
    which matters for sharp terrain.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable, Sequence

try:
    import eccodes
except ImportError:  # pragma: no cover - only the service needs to read GRIB
    eccodes = None

__all__ = [
    "Grid",
    "GridGeometry",
    "Place",
    "PointValue",
    "extract_points",
    "read_geometry",
]


def _eccodes():
    """The eccodes module, with a helpful message when it is missing."""
    if eccodes is None:
        raise ImportError(
            "reading GRIB files needs the eccodes package: "
            "pip install -r requirements.txt"
        )
    return eccodes



@dataclasses.dataclass(frozen=True)
class Place:
    """A point the forecast is evaluated for."""

    id: str
    name: str
    latitude: float
    longitude: float
    elevation: float | None = None
    timezone: str = "UTC"
    country: str = ""
    note: str = ""
    country_code: str = ""
    flag: str = ""
    kind: str = ""
    region: str = ""

    @property
    def coordinates(self) -> str:
        return f"{self.latitude:.5f}, {self.longitude:.5f}"


@dataclasses.dataclass(frozen=True)
class PointValue:
    """One extracted value."""

    place_id: str
    param: str
    level: int | None
    step: int
    value: float | None
    units: str
    method: str = "bilinear"
    levtype: str = "sfc"

    @property
    def key(self) -> str:
        """Storage key of the value."""
        return f"{self.param}:{self.level if self.level is not None else '-'}"


@dataclasses.dataclass(frozen=True)
class GridGeometry:
    """The regular latitude/longitude grid a file is stored on."""

    ni: int
    nj: int
    lat_first: float
    lon_first: float
    lat_last: float
    lon_last: float

    @property
    def dlat(self) -> float:
        """Latitude step, negative because rows run north to south."""
        return (self.lat_last - self.lat_first) / (self.nj - 1)

    @property
    def dlon(self) -> float:
        """Longitude step, accounting for a grid that wraps around the globe."""
        span = self.lon_last - self.lon_first
        if span <= 0:
            span += 360.0
        return span / (self.ni - 1)

    def describe(self) -> str:
        return (
            f"{self.ni} x {self.nj} regular_ll, "
            f"lat {self.lat_first} -> {self.lat_last}, "
            f"lon {self.lon_first} -> {self.lon_last}, "
            f"step {self.dlon:.4g} x {abs(self.dlat):.4g}"
        )


def read_geometry(handle) -> GridGeometry:
    """Read the grid geometry from the first message of an open GRIB file.

    The file position is restored afterwards, so the caller can still read the
    first message.
    """
    eccodes = _eccodes()
    position = handle.tell()
    handle.seek(0)
    message_id = eccodes.codes_grib_new_from_file(handle)
    if message_id is None:
        raise ValueError("no GRIB message found in file")
    try:
        return _geometry_from(message_id)
    finally:
        eccodes.codes_release(message_id)
        handle.seek(position)


def _geometry_from(message_id) -> GridGeometry:
    """Extract the grid geometry from a single GRIB message."""
    return GridGeometry(
        ni=int(eccodes.codes_get(message_id, "Ni")),
        nj=int(eccodes.codes_get(message_id, "Nj")),
        lat_first=float(eccodes.codes_get(message_id, "latitudeOfFirstGridPointInDegrees")),
        lon_first=float(eccodes.codes_get(message_id, "longitudeOfFirstGridPointInDegrees")),
        lat_last=float(eccodes.codes_get(message_id, "latitudeOfLastGridPointInDegrees")),
        lon_last=float(eccodes.codes_get(message_id, "longitudeOfLastGridPointInDegrees")),
    )


class Grid:
    """Interpolates a field on a regular lat/lon grid at arbitrary points."""

    def __init__(self, geometry: GridGeometry, values):
        self.geometry = geometry
        self.values = values

    def _flatten(self) -> list[float]:
        return self.values.flatten().tolist() if hasattr(self.values, "flatten") else list(self.values)

    def at(self, latitude: float, longitude: float, method: str = "bilinear") -> float:
        """Value at a point, interpolated or taken from the nearest node."""
        geo = self.geometry
        values = self.values

        # Position in grid coordinates.
        x = ((longitude - geo.lon_first) % 360.0) / geo.dlon
        y = (geo.lat_first - latitude) / (-geo.dlat)

        # Clamp to the grid; the poles are represented by the first and last row.
        x = min(max(x, 0.0), geo.ni - 1.0)
        y = min(max(y, 0.0), geo.nj - 1.0)

        i0 = math.floor(x)
        j0 = math.floor(y)
        i1 = min(i0 + 1, geo.ni - 1)
        j1 = min(j0 + 1, geo.nj - 1)
        dx = x - i0
        dy = y - j0

        if method == "nearest":
            # Nearest node, with ties resolved towards the south/west.
            if dx > 0.5:
                i0 = i1
            if dy > 0.5:
                j0 = j1
            return float(values[j0 * geo.ni + i0])

        v00 = float(values[j0 * geo.ni + i0])
        v01 = float(values[j0 * geo.ni + i1])
        v10 = float(values[j1 * geo.ni + i0])
        v11 = float(values[j1 * geo.ni + i1])

        top = v00 + (v01 - v00) * dx
        bottom = v10 + (v11 - v10) * dx
        return top + (bottom - top) * dy


def extract_points(
    path: str,
    places: Sequence[Place],
    *,
    params: Sequence[str] | None = None,
    levels: Sequence[int] | None = None,
    method: str = "bilinear",
    levtype: str | None = None,
    step: int | None = None,
) -> list[PointValue]:
    """Extract the requested fields at every place.

    Parameters
    ----------
    path
        GRIB2 file to read.
    places
        Points to evaluate.
    params
        Parameter short names to keep. ``None`` keeps everything.
    levels
        Pressure levels to keep. ``None`` keeps every level.
    method
        ``bilinear`` or ``nearest``.
    levtype
        ``sfc`` or ``pl``. Inferred from the file name when not given.
    step
        Forecast step to record. ECMWF publishes the 3 hourly maximum and
        minimum in the file of the preceding step, and its own index lists
        them under the step of the file. Passing the step of the file keeps
        every parameter on one time axis.

    Returns
    -------
    list of PointValue
        One entry per parameter, level, step and place.
    """
    eccodes = _eccodes()
    wanted = set(params) if params else None
    wanted_levels = set(levels) if levels else None
    if levtype is None:
        levtype = "pl" if path.endswith("-pl.grib2") else "sfc"
    results: list[PointValue] = []

    with open(path, "rb") as handle:
        geometry = read_geometry(handle)

        while True:
            message_id = eccodes.codes_grib_new_from_file(handle)
            if message_id is None:
                break
            try:
                short_name = eccodes.codes_get(message_id, "shortName")
                if wanted is not None and short_name not in wanted:
                    continue

                try:
                    level = int(eccodes.codes_get(message_id, "level"))
                except Exception:  # noqa: BLE001 - eccodes raises several types
                    level = None
                if wanted_levels is not None and level not in wanted_levels:
                    continue

                if step is None:
                    try:
                        step = int(eccodes.codes_get(message_id, "step"))
                    except Exception:  # noqa: BLE001 - eccodes raises several types
                        step = 0

                units = _units_of(message_id, short_name)
                missing = _missing_value(message_id)
                values = eccodes.codes_get_values(message_id)
                grid = Grid(geometry, values)

                for place in places:
                    value = grid.at(place.latitude, place.longitude, method=method)
                    if _is_missing(short_name, value, missing):
                        value = None
                    results.append(
                        PointValue(
                            place_id=place.id,
                            param=short_name,
                            level=level,
                            step=step,
                            value=value,
                            units=units,
                            method=method,
                            levtype=levtype,
                        )
                    )
            finally:
                eccodes.codes_release(message_id)

    return results


def _missing_value(message_id) -> float | None:
    """The missing value marker of a message, if it has one."""
    eccodes = _eccodes()
    try:
        value = eccodes.codes_get(message_id, "missingValue")
    except Exception:  # noqa: BLE001 - eccodes raises several types
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


#: Parameters whose value must be above this to be physically possible.
#: The open data leaves a few fields, notably the three hourly maximum and
#: minimum at the first step, filled with zero.
_FLOORS: dict[str, float] = {
    "2t": 1.0,
    "2d": 1.0,
    "skt": 1.0,
    "t": 1.0,
    "mx2t3": 1.0,
    "mn2t3": 1.0,
    "mx2t6": 1.0,
    "mn2t6": 1.0,
}


def _is_missing(param: str, value: float, missing: float | None) -> bool:
    """Whether a value should be treated as missing."""
    if missing is not None and abs(value - missing) < 1e-6:
        return True
    floor = _FLOORS.get(param)
    return floor is not None and value <= floor


def _units_of(message_id, short_name: str) -> str:
    """Unit of a message, falling back to the catalogue."""
    eccodes = _eccodes()
    try:
        units = eccodes.codes_get(message_id, "units")
        if units:
            import parameters

            return parameters.normalise_units(units)
    except Exception:  # noqa: BLE001, S110 - eccodes raises several types
        pass
    try:
        import parameters

        return parameters.get(short_name).units
    except Exception:  # noqa: BLE001 - eccodes raises several types
        return ""


def summarise(values: Iterable[PointValue]) -> dict[tuple[str, str], list[PointValue]]:
    """Group extracted values by place and parameter key."""
    grouped: dict[tuple[str, str], list[PointValue]] = {}
    for value in values:
        grouped.setdefault((value.place_id, value.key), []).append(value)
    for series in grouped.values():
        series.sort(key=lambda v: v.step)
    return grouped
