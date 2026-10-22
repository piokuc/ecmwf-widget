<div align="center">

# ECMWF forecast widget

**A point forecast service for ECMWF's free and open 0.1° data, and the
widget that shows it.**

[Open the live page](https://piokuc.github.io/ecmwf-widget/) ·
[Documentation](documentation/index.md) ·
[ECMWF open data](https://www.ecmwf.int/en/forecasts/datasets/open-data)

</div>

---

<p align="center">
  <img src="docs/screenshot.png" width="820" alt="The widget showing the forecast for Górki Wielkie">
</p>

## What it does

Since the 20th of October 2026 ECMWF publishes its highest resolution
forecast at **0.1°, about 9 km**, as free and open data. There is no
account, no API key and no registration.

This project fetches that data, evaluates it at the places you care about
— cities, villages, summits — and serves it as a page you can use on a
phone.

- **Every parameter** ECMWF publishes is listed, and the ones you have
  downloaded can be switched on and off. The service fetches the thirteen
  interesting ones, all on the surface, and one line of configuration
  changes that.
- **Three models**: IFS at 0.1° and 0.25°, and the AIFS machine learning
  forecast.
- **Every capital**, a lot of major cities and some notable peaks, with
  flags, and any place you add yourself.
- **Fifteen days** of forecast, grouped by day, with the numbers and the
  plot of each parameter together.
- **The wind as arrows**, built from the two components, coloured by the
  Beaufort scale.
- **Local time and UTC**, a switch between the two, and the time the values
  belong to always in the corner.

The published page is built by a GitHub Action, every four hours after the
ECMWF cycles: it fetches the forecast, builds the page and deploys it. The
repository keeps nothing of it, so it does not fill up.

## Getting started

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # only for the tests

python service.py once     # fetch the latest run
python widget.py --open    # and look at it
```

The widget is then on <http://localhost:8765>.

To keep it up to date, run the service as a daemon, and optionally the
publisher with it:

```bash
python service.py run      # keep the database up to date
```

The published page is updated by a GitHub Action, so it does not need the
laptop. To publish from the laptop instead, the publisher daemon follows
the ECMWF schedule itself — it waits for each cycle, pulls the data as
soon as it appears, rebuilds the page and pushes to GitHub, which is what
publishes the new version:

```bash
python auto_publish.py             # waits for each new run, then pushes
python auto_publish.py --dry-run   # do everything except the push
```

Ready-made service definitions for macOS (`launchd`) and Linux
(`systemd`) are in [`deploy/`](deploy) — the ingestor as
`ecmwf-ingestd`, publishing as `ecmwf-publishd` — and GitHub Actions
builds
[distributable packages](documentation/workflows.md#the-packages) for
both platforms: a wheel and a portable bundle per OS.

## The structure

The application lives in the `ecmwf_widget` package; the files on the top
level are thin launchers for the commands above:

```
ecmwf_widget/          the package
├── scheduler          the ECMWF publication schedule (0, 6, 12, 18 UTC)
├── service            the ingester: find runs, download, extract, store
├── auto_publish       the publishing daemon, on the schedule above
├── publish            one-shot fetch, build and push
├── build_site         the static page for GitHub Pages
├── widget             the local widget server, and the page itself
├── forecast           turning stored values into display structures
├── store              the SQLite store
├── points             places, GRIB grids and point extraction
├── ecmwf_open_data    the anonymous HTTPS client for the open data portal
├── models, parameters the catalogue of models and parameters
├── config             places.yml loading and validation
├── build_places       rebuilding world_places.yml
├── make_icons         generating the weather icons
└── download_9km       downloading a single file, without the database
tests/                 unit tests (pytest) and the website scenarios
├── test_*.py          the unit tests
└── features           Cucumber descriptions of the published page,
                       executed with pytest-bdd against a served bundle
deploy/                service files for launchd and systemd
```

## The tests

```bash
pip install -r requirements-dev.txt
pytest                    # unit tests and website scenarios
pytest tests/features     # just the website scenarios
```

The unit tests cover the schedule, the configuration, the parameters, the
store, the service (with the network faked away) and the publishing step
(against a throwaway git repository). The scenarios in
`tests/features/published_page.feature` describe what the published page
promises; they serve the built bundle over HTTP and check it the way a
visitor would receive it. Build the page first with `python build_site.py`
if `docs/index.html` is not there yet.

## The places

Your own places go in `places.yml`:

```yaml
places:
  - id: sniezka
    name: Śnieżka
    latitude: 50.73617
    longitude: 15.73972
    elevation: 1603
    country: Poland
    country_code: PL
    flag: 🇵🇱
```

And the catalogue of the world is in `world_places.yml`, which you can
follow all of, or part of:

```yaml
catalogue: [region:europe, kind:peak]
```

## How it works

```
   ECMWF open data portal
          |  anonymous HTTPS
          v
   service.py ────► SQLite ────► widget.py ────► the page
```

The service finds the runs that are published, downloads only the fields it
needs using the index files and HTTP range requests, and evaluates them at
every place. The widget reads those values and draws them.

There is more in the [documentation](documentation/index.md):

| | |
| --- | --- |
| [Overview](documentation/overview.md) | How the pieces fit together |
| [The data](documentation/data.md) | What ECMWF publishes, the parameters, the units, the licence |
| [The data retriever](documentation/retrieval.md) | How a run is found, fetched, decoded and stored |
| [The web page](documentation/page.md) | How the page is built and how it renders |
| [Workflows](documentation/workflows.md) | Every command and when to use it |
| [Publishing](documentation/publishing.md) | GitHub Pages, the schedule daemon, the size limits |
| [The tests](documentation/testing.md) | The unit tests and the Cucumber description of the page |

## The commands

| | |
| --- | --- |
| `python service.py once` | Fetch the latest run and stop |
| `python service.py run` | Keep the database up to date |
| `python service.py status` | What has been fetched |
| `python service.py export` | Everything, as a CSV |
| `python widget.py --open` | The widget, in a browser |
| `python widget.py --text` | The forecast as text |
| `python publish.py` | Fetch, rebuild the page, commit and push |
| `python auto_publish.py` | The same, on a schedule, on the laptop |
| `gh workflow run pages.yml` | Build and publish the page in GitHub |
| `python make_icons.py` | Generate the weather icons |
| `python build_places.py` | Rebuild the catalogue of world places |
| `python build_site.py` | Build the static page on its own |
| `python download_9km.py` | Download a single file, without the database |

## A note on the data

The 0.1° tier is published about two hours after the 0.25° one, and only
the 00 and 12 UTC runs carry the long range: the 06 and 18 UTC runs stop
at 144 hours. The widget shows the run that reaches furthest and says where
each run ends, so there is no guessing.

Every parameter is a full global field, so the twelve that are fetched cost
about 750 MB a run and asking for all forty-eight would cost six times
that. `parameters: all` in `places.yml` is the greedy option.

## Credits

Generated using [ECMWF free and open data](https://www.ecmwf.int/en/forecasts/datasets/open-data),
licensed under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).
ECMWF must be attributed.

The weather icons are generated with
[Z-Image-Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo).
