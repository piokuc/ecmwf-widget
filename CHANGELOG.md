# Changelog

## 1.1.0

The project was put in the usual shape of a Python package, and the way it
is installed and used changed with it.

### The layout

- The package moved to `src/ecmwf_widget`, so an import from the repository
  root cannot pick up a stale copy of the code.
- The documentation moved from `documentation/` to `docs/`, the built page
  from `docs/` to `site/`, and the configurations from the top of the
  repository to `config/`.
- The weather icons, the app icons and the catalogue of world places are
  data of the package now (`src/ecmwf_widget/assets` and
  `src/ecmwf_widget/data`), so they travel with the wheel.
- The launchers at the top of the repository (`service.py`, `widget.py`,
  `publish.py`, `auto_publish.py`, `build_site.py`, `build_places.py`,
  `make_icons.py`, `download_9km.py`) are gone. The console scripts do the
  same, and every command is also `python -m ecmwf_widget <command>`.
- The build artefacts that had been committed by accident — a copy of the
  package under `build/`, the `.egg-info` and a whole vendored copy of
  numpy — are out of the repository.

### The dependencies

- `pyproject.toml` is the only place where dependencies are written down;
  the `requirements.txt` files are gone. The extras are `icons` and `dev`.
- `eccodes` is required from 2.40, which comes with the ECMWF library as a
  binary wheel: installing the package needs no compiler on macOS or Linux.
- The configuration of pytest, of ruff and of the coverage report moved
  into `pyproject.toml`.

### The packages

- `python -m build` writes a wheel and an sdist that carry the icons and
  the catalogue of world places.
- The portable bundle is assembled by `scripts/make_bundle.sh`, and it is
  checked in the workflow: the wheel is installed into a fresh environment
  and asked a question before anything is released.
- The workflow that packages the project runs the tests first, and the
  workflow that publishes the page installs the package instead of the
  requirements.

### Fixed

- The units of a GRIB message are read again. The lookup of the catalogue
  used an import that only worked by accident, so every value was stored
  without its unit.
- `ecmwf-download --list` works again: it imported a module of the package
  as if it were a top level one.
- The catalogue of world places is found in the installed package, so the
  widget can follow the capitals and the peaks however it was installed.

### The tests

- The unit tests live in `tests/unit`, the scenarios of the page in
  `tests/features`.
- The scenarios no longer have to be skipped when no page has been built:
  they build a small bundle of their own.
- New tests for the paths of the package and of the machine, and for the
  commands of the package.

## 1.0.0

The first release: the service, the widget, the publisher and the
packages.
