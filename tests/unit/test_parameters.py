"""The parameters, the units and the derived quantities."""

from __future__ import annotations

import pytest

from ecmwf_widget import parameters

# -- catalogue -------------------------------------------------------------- #

def test_every_parameter_has_a_levtype():
    for spec in parameters.PARAMETERS.values():
        assert spec.levtype == "sfc"
    for spec in parameters.PRESSURE_PARAMETERS.values():
        assert spec.levtype == "pl"


def test_names_covers_every_catalogue():
    names = parameters.names()
    assert "2t" in names
    assert "t" in names
    assert "apparent_temperature" in names
    # ``z`` exists on the surface and on the pressure levels, so the flat
    # list carries it twice; the set is full already.
    assert set(names) == (
        set(parameters.PARAMETERS) | set(parameters.PRESSURE_PARAMETERS) | set(parameters.DERIVED)
    )


def test_available_lists_match_the_catalogues():
    assert set(parameters.available_sfc()) == set(parameters.PARAMETERS)
    assert set(parameters.available_pl()) == set(parameters.PRESSURE_PARAMETERS)
    # ``basic`` is a subset of the surface catalogue.
    basic = [n for n, spec in parameters.PARAMETERS.items() if spec.basic]
    assert basic
    assert set(basic) <= set(parameters.available_sfc())


def test_z_exists_on_surface_and_on_pressure_levels():
    assert parameters.PARAMETERS["z"].levtype == "sfc"
    assert parameters.PRESSURE_PARAMETERS["z"].levtype == "pl"


def test_get_prefers_the_levtype():
    assert parameters.get("z", "sfc").name == "z"
    assert parameters.get("z", "pl").name == "z"
    with pytest.raises(KeyError):
        parameters.get("no_such_parameter")


def test_get_does_not_guess_a_pressure_level_for_a_surface_name():
    # ``2t`` only exists on the surface.
    assert parameters.get("2t", "sfc").levtype == "sfc"


def test_restore_split():
    surface, pressure, derived = parameters.resolve(["2t", "u", "wind_speed"])
    assert surface == ["2t", "10u", "10v"]
    assert pressure == ["u"]
    assert derived == ["wind_speed"]
    with pytest.raises(KeyError):
        parameters.resolve(["nonsense"])


# -- units and conversions -------------------------------------------------- #

def test_display_temperature_in_celsius():
    value, unit = parameters.to_display(273.15, "K", "2t")
    assert value == pytest.approx(0.0)
    assert unit == "degC"


def test_display_pressure_in_hectopascals():
    value, unit = parameters.to_display(101325.0, "Pa", "msl")
    assert value == pytest.approx(1013.25)
    assert unit == "hPa"


def test_display_wind_speed_in_km_per_hour():
    value, unit = parameters.to_display(10.0, "m s-1", "wind_speed")
    assert value == pytest.approx(36.0)
    assert unit == "km/h"


def test_display_precipitation_from_m_for_ifs():
    unit, scale, _offset = parameters.display_for("tp", "m")
    assert unit == "mm"
    assert scale == pytest.approx(1000.0)
    converted, unit = parameters.to_display(0.002, "m", "tp")
    assert converted == pytest.approx(2.0)
    assert unit == "mm"


def test_display_precipitation_from_kg_m2_for_the_ai_models():
    unit, scale, _offset = parameters.display_for("tp", "kg m-2")
    assert unit == "mm"
    assert scale == pytest.approx(1.0)


def test_display_fraction_cloud_cover():
    unit, scale, _offset = parameters.display_for("tcc", "(0 - 1)")
    assert unit == "%"
    assert scale == pytest.approx(100.0)
    assert parameters.display_for("tcc", "%")[1] == pytest.approx(1.0)


def test_normalise_units_takes_the_exponents_apart():
    assert parameters.normalise_units("m s**-1") == "m s-1"
    assert parameters.normalise_units("") == ""


# -- physics helpers --------------------------------------------------------- #

def test_wind_speed_is_the_length_of_the_vector():
    assert parameters.wind_speed(3.0, 4.0) == pytest.approx(5.0)


def test_wind_direction_is_meteorological():
    # A wind blowing towards the east comes from the west.
    assert parameters.wind_direction(u=10.0, v=0.0) == pytest.approx(270.0)
    # towards the north comes from the south
    assert parameters.wind_direction(u=0.0, v=10.0) == pytest.approx(180.0)
    # towards the south comes from the north
    assert parameters.wind_direction(u=0.0, v=-10.0) == pytest.approx(0.0)


def test_wind_direction_stays_in_range():
    for u in (-5.0, 0.0, 5.0):
        for v in (-5.0, 0.0, 5.0):
            if u == v == 0.0:
                continue
            assert 0.0 <= parameters.wind_direction(u, v) < 360.0


def test_apparent_temperature_is_warmer_than_the_air():
    t = 293.15          # 20 degC
    dew = 288.15        # 15 degC, humid
    apparent = parameters.apparent_temperature(t, dew, wind=2.0)
    assert apparent == pytest.approx(293.15, abs=3.0)
    celsius = apparent - 273.15
    assert celsius > t - 273.15   # it feels warmer than the air when humid


def test_geopotential_to_height():
    assert parameters.geopotential_to_height(9.80665) == pytest.approx(1.0)


def test_lapse_correction_cools_for_an_elevated_place():
    corrected = parameters.lapse_correction(288.15, place_elevation=1603, model_elevation=400)
    assert corrected == pytest.approx(288.15 - (1603 - 400) * 6.5 / 1000.0, rel=1e-4)


def test_lapse_correction_needs_both_elevations():
    assert parameters.lapse_correction(288.15, None, 400) is None
    assert parameters.lapse_correction(288.15, 1603, None) is None
