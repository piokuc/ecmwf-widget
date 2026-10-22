# Development

How the project is put together, how the dependencies are handled, and how
the packages are built and released.

## The layout

The project follows the usual shape of a Python package: the code in
`src/`, the tests in `tests/`, the documents in `docs/`, and everything
that belongs to the machine in `data/`.

```
.
├── pyproject.toml          the metadata, the dependencies, the tools
├── Makefile                the everyday commands
├── src/ecmwf_widget/       the package
├── tests/                  the tests
├── docs/                   the documentation
├── config/                 the configurations of the repository
├── deploy/                 launchd and systemd service files
├── scripts/                the build of the portable bundle
├── data/                   the state of the machine (not in the repository)
├── dist/                   the built packages (not in the repository)
└── site/                   the built page (not in the repository)
```

**The `src/` layout.** The package lives in `src/ecmwf_widget`, not in
`ecmwf_widget` at the root. Two things follow from it: an import from the
repository root cannot pick up a stale copy of the code, and the tests
have to be told where the package is — which `pyproject.toml` does, once:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
```

**The package carries its own files.** The weather icons, the app icons and
the catalogue of world places are data of the package, so they travel with
it:

```
src/ecmwf_widget/assets/      the weather icons and the app icons
src/ecmwf_widget/data/        the catalogue of world places, the starter
                              configuration
```

They are declared in `pyproject.toml`:

```toml
[tool.setuptools.package-data]
ecmwf_widget = ["assets/*.png", "assets/icons/*.png", "data/*.yml"]
```

Without that declaration the wheel would install, but the icons would be
missing and the page would have none.

**The machine has its own files.** The configuration, the database, the
GRIB cache and the logs belong to the machine that runs the service, not to
the package. The configuration is looked for in a fixed order, which
`ecmwf_widget/paths.py` holds:

1. the file named by `--config`;
2. the file named by `ECMWF_WIDGET_CONFIG`;
3. `places.yml` in the working directory;
4. `config/places.yml` of a checkout of the repository;
5. the starter configuration that comes with the package.

## The dependencies

`pyproject.toml` is the only place where dependencies are written down.
There are no `requirements.txt` files to keep in step with it.

| Where | What |
| --- | --- |
| `project.dependencies` | What the package needs to run: `requests`, `PyYAML`, `eccodes` |
| `project.optional-dependencies.icons` | The image model of `ecmwf-make-icons` |
| `project.optional-dependencies.dev` | `pytest`, `pytest-bdd`, `ruff` and `build` |

```bash
pip install ecmwf-widget          # the package and its dependencies
pip install -e ".[dev]"           # from a checkout, with the tools of the tests
pip install -e ".[icons]"         # from a checkout, with the icon generator
```

`eccodes` is the ECMWF decoder. From 2.40 it comes with the ECMWF library
as a binary wheel, so `pip install` needs no compiler on macOS and on
Linux — which is what makes the package easy to install.

## The everyday commands

The `Makefile` is a list of the commands that are run often:

```bash
make install         # the package, in editable mode
make install-dev     # the package and the tools of the tests
make test            # everything: the unit tests and the scenarios
make lint            # ruff over the code and the tests
make build           # the wheel and the sdist, in dist/
make bundle          # the portable bundle for this machine
make site            # the static page, in site/
make clean           # the build artefacts away
```

## The tests

```bash
pip install -e ".[dev]"
pytest                        # everything
pytest tests/unit             # the unit tests
pytest tests/features         # the scenarios of the published page
```

The tests need neither the network nor a fetched forecast. Everything that
talks to the portal or to git is faked away, and the scenarios of the page
run against a bundle that the tests build themselves when there is none.

They run on every push, on macOS and on Linux, on every version of Python
the package supports: `.github/workflows/ci.yml`.

## The packages

```bash
python -m build            # the wheel and the sdist, in dist/
sh scripts/make_bundle.sh  # the portable bundle, in dist/
```

`python -m build` writes two things:

| File | What it is |
| --- | --- |
| `ecmwf_widget-<version>-py3-none-any.whl` | The wheel: pure Python, so the same file works on macOS and on Linux |
| `ecmwf_widget-<version>.tar.gz` | The sdist: the sources, from which the wheel is built again |

`scripts/make_bundle.sh` writes a third thing, for the machines that cannot
install anything:

| File | What it is |
| --- | --- |
| `ecmwf-widget-<version>-<os>-<arch>.tar.gz` | The package with its dependencies in `vendor/`, the launchers in `bin/`, the documentation and a starting configuration |

The bundle is built per platform, so it is built twice: once on Linux and
once on macOS. Both are done by `.github/workflows/package.yml`, which
also installs the wheel into a fresh environment and asks it a question,
so a broken package never reaches a release.

## The release

```bash
git tag v1.1.0
git push --tags
```

The tag starts the packaging workflow. It builds the wheel, the sdist and
the bundle for both platforms, checks them, uploads them as artifacts and
attaches them to the release the tag names.

The version lives in one place, `src/ecmwf_widget/__init__.py`, and the
packaging reads it from there:

```toml
[tool.setuptools.dynamic]
version = { attr = "ecmwf_widget.__version__" }
```

So a release is: change the version, write what changed in
`CHANGELOG.md`, tag it.

## The code

The style is the one of the standard library: type hints, docstrings that
say what the thing is for, and no clever tricks. `ruff` checks the code
with the rules in `pyproject.toml`:

```bash
make lint
```
