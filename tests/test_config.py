"""The configuration loader."""

from __future__ import annotations

import textwrap

import pytest

from ecmwf_widget import config, models, parameters


# -- the real file ------------------------------------------------------------#

def test_loads_the_real_pages_configuration():
    loaded = config.load_config("places.pages.yml")
    assert loaded.places
    assert loaded.parameters
    assert loaded.steps
    assert all(isinstance(step, int) for step in loaded.steps)
    assert [model.key for model in loaded.models] == ["ifs", "aifs"]
    assert all(place.id for place in loaded.all_places)


def test_own_places_come_first_in_all_places():
    loaded = config.load_config("places.pages.yml")
    own = {place.id for place in loaded.places}
    catalogue = {place.id for place in loaded.catalogue}
    assert own
    assert not (own & catalogue)
    ids = [place.id for place in loaded.all_places]
    assert len(ids) == len(set(ids))
    # every own place is in there, before every catalogue place
    assert ids[: len(loaded.places)] == [place.id for place in loaded.places]


# -- a small synthetic file ---------------------------------------------------#

@pytest.fixture
def config_path(tmp_path):
    """Write a configuration file and return its path."""

    def write(text, name="places.yml"):
        path = tmp_path / name
        path.write_text(textwrap.dedent(text))
        return str(path)

    return write


def test_defaults_are_taken_when_settings_are_missing(config_path):
    path = config_path(
        """
        places:
          - id: poznan
            name: Poznań
            latitude: 52.4082
            longitude: 16.9335
        """
    )
    loaded = config.load_config(path)
    assert loaded.poll_interval == 900
    assert loaded.database == "data/forecast.sqlite"
    assert loaded.cache_dir == "data/grib"
    assert loaded.method == "bilinear"
    assert loaded.keep_runs == 3
    assert loaded.models == models.resolve("ifs")
    assert loaded.source == "ecmwf"
    assert [place.id for place in loaded.places] == ["poznan"]


def test_places_keep_their_fields(config_path):
    path = config_path(
        """
        places:
          - id: sniezka
            name: Śnieżka
            latitude: 50.73617
            longitude: 15.73972
            elevation: 1603
            country: Poland
            country_code: PL
            flag: 🇵🇱
            note: the highest summit of the Sudetes
            kind: peak
            region: europe
        """
    )
    place, = config.load_config(path).places
    assert place.id == "sniezka"
    assert place.name == "Śnieżka"
    assert place.elevation == 1603
    assert place.flag == "🇵🇱"
    assert place.country_code == "PL"
    assert place.kind == "peak"
    assert place.region == "europe"


def test_duplicate_ids_are_rejected(config_path):
    path = config_path(
        """
        places:
          - id: twice
            latitude: 0.0
            longitude: 0.0
          - id: twice
            latitude: 1.0
            longitude: 1.0
        """
    )
    with pytest.raises(ValueError):
        config.load_config(path)


def test_incomplete_place_is_rejected(config_path):
    path = config_path(
        """
        places:
          - id: incomplete
        """
    )
    with pytest.raises(ValueError):
        config.load_config(path)


def test_missing_place_id_is_rejected(config_path):
    path = config_path(
        """
        places:
          - latitude: 52.0
            longitude: 16.0
        """
    )
    with pytest.raises(ValueError):
        config.load_config(path)


# -- the catalogue of the world ------------------------------------------------#

WORLD = """
        places:
          - id: krakow
            name: Kraków
            latitude: 50.06
            longitude: 19.94
            kind: city
            region: europe
          - id: reykjavik
            name: Reykjavík
            latitude: 64.0
            longitude: -21.9
            kind: capital
            region: arctic
          - id: sniezka
            name: Śnieżka
            latitude: 50.73617
            longitude: 15.73972
            elevation: 1603
            kind: peak
            region: europe
"""


def test_catalogue_selects_by_kind_and_id(config_path, tmp_path, monkeypatch):
    """Two kinds of selection at once: a kind and an id.

    The world file is found relative to the working directory, so the
    catalogue tests run inside the temporary one.
    """
    monkeypatch.chdir(tmp_path)
    config_path(WORLD, name="world.yml")
    path = config_path(
        """
        places:
          - id: home
            latitude: 50.0
            longitude: 16.0

        world_places: world.yml
        catalogue:
          - kind:peak
          - reykjavik
        """
    )
    loaded = config.load_config(path)
    assert [place.id for place in loaded.catalogue] == ["reykjavik", "sniezka"]
    assert [place.id for place in loaded.all_places] == ["home", "reykjavik", "sniezka"]


def test_catalogue_selects_by_region(config_path, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path(WORLD, name="world.yml")
    path = config_path(
        "places: []\nworld_places: world.yml\ncatalogue: [region:arctic]\n"
    )
    assert [place.id for place in config.load_config(path).catalogue] == ["reykjavik"]


def test_catalogue_all_selects_everything(config_path, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path(WORLD, name="world.yml")
    path = config_path("places: []\nworld_places: world.yml\ncatalogue: all\n")
    assert len(config.load_config(path).catalogue) == 3


def test_catalogue_none_selects_nothing(config_path, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path(WORLD, name="world.yml")
    path = config_path("places: []\nworld_places: world.yml\ncatalogue: none\n")
    assert config.load_config(path).catalogue == []


def test_missing_world_file_is_not_an_error(config_path):
    path = config_path(
        """
        places:
          - id: home
            latitude: 50.0
            longitude: 16.0
        world_places: not_there.yml
        catalogue: all
        """
    )
    loaded = config.load_config(path)
    assert loaded.catalogue == []
    assert [place.id for place in loaded.all_places] == ["home"]


# -- the parameter setting ------------------------------------------------------#

def test_basic_expands_to_the_basic_set():
    selection = config._resolve_parameters("basic")
    assert "2t" in selection
    assert "apparent_temperature" in selection
    assert "t" not in selection             # pressure levels stay out
    assert "tp" in selection
    assert len(selection) == len(set(selection))   # no duplicates


def test_all_expands_to_everything():
    selection = config._resolve_parameters("all")
    assert set(selection) >= set(parameters.names())
    assert len(selection) == len(set(selection))


def test_explicit_names_are_kept():
    assert config._resolve_parameters(["2t", "u"]) == ["2t", "u"]


def test_unknown_parameter_is_rejected():
    with pytest.raises(ValueError):
        config._resolve_parameters(["tp", "calf_temperature"])


def test_pressure_levels_and_steps(config_path):
    path = config_path(
        "places: []\nparameters: [2t, t]\npressure_levels: [850]\nsteps: [6]\n"
    )
    loaded = config.load_config(path)
    assert loaded.pressure_levels == [850]
    assert loaded.steps == [6]
    assert loaded.parameters == ["2t", "t"]
