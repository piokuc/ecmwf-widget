# Overview

A point forecast service for ECMWF's free and open 0.1° data, and a web
widget that shows it.

The published page is at <https://piokuc.github.io/ecmwf-widget/>.

## The shape of it

```
    ECMWF open data portal
           |
           |  anonymous HTTPS, no key, no login
           v
    +--------------------------------+
    |  ecmwf_widget/                 |  finds a new run, downloads the
    |    service.py                  |  fields it needs, evaluates them
    |    ecmwf_open_data.py          |  at every place and stores the result
    |    points.py                   |
    |    store.py  (SQLite)          |
    +--------------------------------+
      |           ^
      |           | ecmwf_widget/scheduler.py tells both
      |           | how the cycles are scheduled
      v           |
    +--------------------------------+
    |  ecmwf_widget/                 |  keeps the database and the
    |    auto_publish.py             |  published page up to date:
    |    publish.py                  |  fetch, build, commit, push
    |    build_site.py               |
    +--------------------------------+
           |
           |  one table of values
           v
    +--------------------------------+
    |  ecmwf_widget/                 |  serves the page and the data
    |    widget.py                   |  turns the stored values into a
    |    forecast.py                 |  structure the page can render
    |    parameters.py               |
    +--------------------------------+
           |
           |  a static page with the data in it
           v
    build_site.py  -->  site/index.html  -->  GitHub Pages
                             ^
                             |
                  .github/workflows/pages.yml
                  does this part, in the cloud
```

Two processes, and they are deliberately separate:

- **The service** owns the download and the database. It only ever writes.
- **The widget** owns the page. It only ever reads.

That way the page can be built into a static file and published, and the
service can keep running on a machine of its own.

## The layout

The application lives in the `ecmwf_widget` package, under `src/`, so an
import from the repository root cannot pick up a stale copy. Every part
of the project has a directory of its own:

```
src/ecmwf_widget/     the package
├── scheduler          the ECMWF publication schedule, as functions
├── auto_publish       the daemon that follows it: pull, build, push
├── service            the ingester that keeps the database up to date
├── publish            one-shot fetch, build, commit, push
├── build_site         the static page for GitHub Pages
├── widget             the page itself, and the local server
├── forecast           stored values turned into display structures
├── points             places, GRIB grids and point extraction
├── store              the SQLite database
├── models, parameters the catalogue of models and parameters
├── config             the configuration file, loading and validation
├── paths              where the files of the package and of the machine are
├── ecmwf_open_data    the client for the portal
├── build_places       rebuilding the catalogue of world places
├── make_icons         generating the weather icons
├── download_9km       a one-off download, without the database
├── assets             the weather icons and the app icons
└── data               the catalogue of world places, the starter configuration
tests/                 the tests: pytest unit tests, and the Cucumber
├── unit/              scenarios for the published page, executed with
└── features/          pytest-bdd
config/                the configurations of the repository
docs/                  the documentation of the project
deploy/                launchd and systemd service files
scripts/               the build of the portable bundle
```

The commands are the console scripts of the package — `ecmwf-service`,
`ecmwf-widget`, `ecmwf-publisher` and the rest — and every one of them is
also `python -m ecmwf_widget <command>`. The files at the top of the
repository are gone: they only ever repeated what the console scripts do.

## The modules

| File | What it does |
| --- | --- |
| `ecmwf_widget/scheduler.py` | The cycles (0, 6, 12, 18 UTC) and when each run is expected on the portal, as pure functions a daemon and its tests can share |
| `ecmwf_widget/ecmwf_open_data.py` | Finds and downloads files from the portal, using the index files and HTTP range requests so that only the wanted fields are transferred |
| `ecmwf_widget/models.py` | Model product identities, download routing and display metadata; see the [architecture review](model-architecture.md) for capability and horizon limitations |
| `ecmwf_widget/parameters.py` | Every parameter the data has, with its label, unit, group, display conversion and the order it is shown in |
| `ecmwf_widget/points.py` | Reads a GRIB file and evaluates it at a list of coordinates |
| `ecmwf_widget/store.py` | The SQLite database: runs, places and values |
| `ecmwf_widget/config.py` | Reads the configuration file and validates it |
| `ecmwf_widget/paths.py` | Where the files of the package and of the machine are |
| `ecmwf_widget/service.py` | The daemon that keeps the database up to date |
| `ecmwf_widget/forecast.py` | Turns the stored values into what the page needs |
| `ecmwf_widget/widget.py` | The page itself, and the small server that serves it |
| `ecmwf_widget/build_site.py` | Builds the static page for GitHub Pages |
| `ecmwf_widget/download_9km.py` | A small command line tool for a one off download |
| `ecmwf_widget/auto_publish.py` | Follows the schedule: waits for a new run, then publishes the page |
| `ecmwf_widget/publish.py` | One shot: fetch, rebuild, commit, push |
| `ecmwf_widget/make_icons.py` | Generates the weather icons with a local image model |
| `ecmwf_widget/build_places.py` | Builds the catalogue of world places |

## The data flow, in one paragraph

The service looks for a run that is expected to be on the portal, polls
until it is there, and then for each forecast step it reads the index file,
asks for the byte ranges of the fields it wants, downloads only those, and
decodes them. For every place in the list it interpolates the field onto the
place's coordinates and writes one row per place, parameter and step into
SQLite. The widget reads those rows, turns them into a JSON payload, and the
page draws them as a table with a plot under every row.

## Why the data is stored rather than computed on the fly

A run is downloaded once and evaluated at every place at the same time.
Decoding a GRIB field is the expensive part, and doing it once per run
rather than once per request is what makes the page fast with 153 places
behind it.

The page itself is built from the same values, so the published page and the
local widget render exactly the same thing. The only difference is where the
data comes from: the local widget asks for it, the published page has it
inside.
