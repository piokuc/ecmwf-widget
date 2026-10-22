"""The commands of the package, under one name."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ecmwf_widget import __main__ as dispatcher

#: The root of the repository.
REPO_ROOT = Path(__file__).resolve().parents[2]

SRC = REPO_ROOT / "src"


def _run(*arguments: str) -> subprocess.CompletedProcess:
    """Run the package as a module, with the sources on the path."""
    import os

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "ecmwf_widget", *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


# -- the dispatcher ------------------------------------------------------------ #

def test_every_command_of_the_dispatcher_exists():
    import importlib

    for name, module in dispatcher.COMMANDS.items():
        imported = importlib.import_module(module)
        assert callable(imported.main), name


def test_the_help_lists_every_command():
    result = _run("--help")
    assert result.returncode == 0
    for name in dispatcher.COMMANDS:
        assert name in result.stdout


def test_without_arguments_the_usage_is_printed():
    result = _run()
    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_an_unknown_command_is_refused():
    result = _run("nonsense")
    assert result.returncode == 2
    assert "unknown command" in result.stderr


def test_a_command_is_passed_its_arguments():
    result = _run("service", "--help")
    assert result.returncode == 0
    assert "once" in result.stdout


# -- the console scripts ------------------------------------------------------- #

def test_the_console_scripts_are_declared():
    """Every command of the package has a console script."""
    import tomllib

    with open(REPO_ROOT / "pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    scripts = pyproject["project"]["scripts"]
    assert scripts["ecmwf-service"] == "ecmwf_widget.service:main"
    assert scripts["ecmwf-widget"] == "ecmwf_widget.widget:main"
    assert set(scripts.values()) == {
        "ecmwf_widget.service:main",
        "ecmwf_widget.widget:main",
        "ecmwf_widget.auto_publish:main",
        "ecmwf_widget.publish:main",
        "ecmwf_widget.build_site:main",
        "ecmwf_widget.build_places:main",
        "ecmwf_widget.make_icons:main",
        "ecmwf_widget.download_9km:main",
    }


def test_the_package_data_is_declared():
    """The icons and the catalogue have to travel with the package."""
    import tomllib

    with open(REPO_ROOT / "pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    package_data = pyproject["tool"]["setuptools"]["package-data"]["ecmwf_widget"]
    assert "assets/icons/*.png" in package_data
    assert "data/*.yml" in package_data


@pytest.mark.parametrize(
    "module",
    ["service", "widget", "auto_publish", "publish", "build_site", "build_places",
     "make_icons", "download_9km"],
)
def test_every_module_of_the_package_has_a_main(module):
    import importlib

    imported = importlib.import_module(f"ecmwf_widget.{module}")
    assert callable(imported.main)
