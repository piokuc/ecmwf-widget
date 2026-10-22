# The everyday commands of the project.
#
#     make help        what every target does
#     make install    the package and its dependencies, in editable mode
#     make test       the unit tests and the scenarios of the page
#     make build      the wheel and the sdist, in dist/
#
# The targets are thin wrappers around the commands in pyproject.toml and
# the documentation, so nothing here hides a step.

PYTHON ?= python3
PIP    ?= $(PYTHON) -m pip
# The sources are put on the path, so the targets work in a checkout that
# has not been installed.
SRC    := $(CURDIR)/src
export PYTHONPATH := $(SRC)$(if $(PYTHONPATH),:$(PYTHONPATH))

.DEFAULT_GOAL := help
.PHONY: help install install-dev install-icons test test-unit test-scenarios \
        lint format build bundle site clean distclean version

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package in editable mode, with its dependencies
	$(PIP) install -e .

install-dev:  ## Install the package with the tools of the tests
	$(PIP) install -e ".[dev]"

install-icons:  ## Install the package with the tools of the icon generator
	$(PIP) install -e ".[icons]"

test:  ## Run everything: the unit tests and the scenarios of the page
	$(PYTHON) -m pytest

test-unit:  ## Run only the unit tests
	$(PYTHON) -m pytest tests/unit

test-scenarios:  ## Run only the scenarios of the published page
	$(PYTHON) -m pytest tests/features

lint:  ## Check the code with ruff
	$(PYTHON) -m ruff check src tests

format:  ## Format the code with ruff
	$(PYTHON) -m ruff format src tests

build: clean  ## Build the wheel and the sdist
	$(PYTHON) -m build

bundle:  ## Build the portable bundle for this machine
	sh scripts/make_bundle.sh

site:  ## Build the static page into site/
	$(PYTHON) -m ecmwf_widget build-site

clean:  ## Remove the build artefacts
	rm -rf build dist site .pytest_cache .ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

distclean: clean  ## Remove the build artefacts and the state of the machine
	rm -rf data

version:  ## Print the version of the package
	@$(PYTHON) -c "import ecmwf_widget; print(ecmwf_widget.__version__)"
