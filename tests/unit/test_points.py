"""Reading values out of GRIB files."""

from __future__ import annotations

import pytest

from ecmwf_widget import parameters, points


class FakeCodes:
    """A stand-in for the eccodes module."""

    def __init__(self, units: str | None = "K"):
        self.units = units

    def codes_get(self, message_id, key):
        if key == "units":
            if self.units is None:
                raise KeyError("units")
            return self.units
        raise KeyError(key)


# -- the units ---------------------------------------------------------------- #

def test_the_units_of_a_message_are_read(monkeypatch):
    """The unit of the value has to travel with it into the database."""
    monkeypatch.setattr(points, "eccodes", FakeCodes("K"))
    assert points._units_of(1, "2t") == "K"


def test_the_units_are_normalised(monkeypatch):
    monkeypatch.setattr(points, "eccodes", FakeCodes("m s-1"))
    assert points._units_of(1, "10u") == parameters.normalise_units("m s-1")


def test_the_units_fall_back_to_the_catalogue(monkeypatch):
    """A message without a unit of its own gets the one of the catalogue."""
    monkeypatch.setattr(points, "eccodes", FakeCodes(None))
    assert points._units_of(1, "2t") == parameters.get("2t").units


def test_an_unknown_parameter_has_no_units(monkeypatch):
    monkeypatch.setattr(points, "eccodes", FakeCodes(None))
    assert points._units_of(1, "not_a_parameter") == ""


# -- the interpolation -------------------------------------------------------- #

#: A field of four points, in the order the grid holds them: the northern
#: row first (0 and 10), the southern row after it (20 and 30).
VALUES = [0.0, 10.0, 20.0, 30.0]


def _grid() -> points.Grid:
    geometry = points.GridGeometry(
        ni=2, nj=2, lat_first=1.0, lon_first=0.0, lat_last=0.0, lon_last=1.0
    )
    return points.Grid(geometry, VALUES)


def test_the_value_at_a_point_is_interpolated():
    """A field of four points, and the value in the middle of it."""
    assert _grid().at(0.5, 0.5) == pytest.approx(15.0)


def test_the_nearest_point_is_taken_when_asked_for():
    grid = _grid()
    # a little to the south of the middle: the southern row, the western
    # column, which holds 20
    assert grid.at(0.4, 0.4, method="nearest") == pytest.approx(20.0)
    # a little to the north of it: the northern row, the eastern column
    assert grid.at(0.6, 0.6, method="nearest") == pytest.approx(10.0)


def test_a_point_outside_the_grid_is_clamped_to_it():
    grid = _grid()
    # the corner of the grid that the point ends up in
    assert grid.at(-80.0, -170.0) == pytest.approx(30.0)
    assert grid.at(80.0, 170.0) == pytest.approx(10.0)
