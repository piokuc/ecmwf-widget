"""Where the files of the package and of the machine are found."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ecmwf_widget import paths

# -- the files that travel with the package ---------------------------------- #

def test_the_package_carries_its_assets():
    assert paths.ASSETS_DIR.is_dir()
    assert (paths.ASSETS_DIR / "app-icon-192.png").is_file()
    assert (paths.ASSETS_DIR / "app-icon-512.png").is_file()


def test_the_package_carries_the_weather_icons():
    icons = paths.ICON_DIR
    assert icons.is_dir()
    assert (icons / "sun.png").is_file()
    assert (icons / "rain.png").is_file()
    assert (icons / "manifest.json").is_file()


def test_the_package_carries_the_catalogue_of_the_world():
    assert paths.WORLD_PLACES.is_file()
    assert paths.WORLD_PLACES.name == "world_places.yml"


def test_the_package_carries_a_starter_configuration():
    assert paths.PACKAGED_CONFIG.is_file()
    assert paths.PACKAGED_CONFIG.name == paths.DEFAULT_CONFIG_NAME


# -- the icons ---------------------------------------------------------------- #

def test_the_icon_directory_can_be_pointed_somewhere_else(tmp_path, monkeypatch):
    monkeypatch.setenv("ICON_DIR", str(tmp_path))
    assert paths.icon_dir() == tmp_path


def test_the_icon_directory_is_the_one_of_the_package_without_the_variable(monkeypatch):
    monkeypatch.delenv("ICON_DIR", raising=False)
    assert paths.icon_dir() == paths.ICON_DIR


# -- the configuration file --------------------------------------------------- #

def test_the_environment_variable_names_the_configuration(tmp_path, monkeypatch):
    named = tmp_path / "elsewhere.yml"
    named.write_text("places: []\n")
    monkeypatch.setenv(paths.CONFIG_ENV, str(named))
    assert paths.default_config() == named


def test_the_configuration_of_the_working_directory_wins(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    local = tmp_path / paths.DEFAULT_CONFIG_NAME
    local.write_text("places: []\n")
    monkeypatch.chdir(tmp_path)
    assert paths.default_config() == local


def test_the_configuration_of_a_checkout_is_used_when_there_is_none(tmp_path, monkeypatch):
    """A checkout of the repository has its own configuration."""
    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / paths.DEFAULT_CONFIG_NAME).exists()

    checkout = paths.PACKAGE_DIR.parent.parent
    candidate = checkout / "config" / paths.DEFAULT_CONFIG_NAME
    if not candidate.is_file():
        pytest.skip("not a checkout of the repository")

    assert paths.default_config() == candidate


def test_the_checkout_is_found_from_the_working_directory(tmp_path, monkeypatch):
    """The command is run from the repository, wherever the package is."""
    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)

    checkout = tmp_path / "repository"
    (checkout / "config").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\n")
    (checkout / "config" / paths.DEFAULT_CONFIG_NAME).write_text("places: []\n")
    inside = checkout / "data" / "logs"
    inside.mkdir(parents=True)
    monkeypatch.chdir(inside)

    assert paths.default_config() == checkout / "config" / paths.DEFAULT_CONFIG_NAME


def test_a_directory_that_is_not_a_checkout_is_not_used(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / paths.DEFAULT_CONFIG_NAME).write_text("places: []\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "_checkout_config", lambda: None)
    assert paths.default_config() == paths.PACKAGED_CONFIG


def test_the_starter_configuration_is_the_last_resort(tmp_path, monkeypatch):
    """Without any configuration of its own, the machine gets the starter one."""
    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "_checkout_config", lambda: None)
    assert paths.default_config() == paths.PACKAGED_CONFIG


def test_the_configuration_of_the_machine_loads_without_arguments(monkeypatch):
    """``load_config()`` with no arguments finds a configuration to load."""
    from ecmwf_widget import config

    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    loaded = config.load_config()
    assert loaded.path
    assert Path(loaded.path).is_file()
    assert loaded.places is not None


def test_the_environment_variable_is_used_by_the_loader(tmp_path, monkeypatch):
    from ecmwf_widget import config

    named = tmp_path / "machine.yml"
    named.write_text(
        "places:\n"
        "  - id: warsaw\n"
        "    name: Warszawa\n"
        "    latitude: 52.2297\n"
        "    longitude: 21.0122\n"
    )
    monkeypatch.setenv(paths.CONFIG_ENV, str(named))
    loaded = config.load_config()
    assert loaded.path == str(named)
    assert [place.id for place in loaded.places] == ["warsaw"]


def test_the_paths_are_not_written_outside_the_machine(monkeypatch, tmp_path):
    """The database and the cache are relative to the working directory."""
    from ecmwf_widget import config

    monkeypatch.chdir(tmp_path)
    assert os.path.isabs(config.load_config(paths.PACKAGED_CONFIG).database) is False
