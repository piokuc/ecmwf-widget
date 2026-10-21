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
  <img src="docs/screenshot.png" width="820" alt="The widget showing the forecast for Gliwice">
</p>

## What it does

Since the 20th of October 2026 ECMWF publishes its highest resolution
forecast at **0.1°, about 9 km**, as free and open data. There is no
account, no API key and no registration.

This project fetches that data, evaluates it at the places you care about
— cities, villages, summits — and serves it as a page you can use on a
phone.

- **Every parameter** the 0.1° tier publishes: 48 surface parameters and 10
  on four pressure levels.
- **Three models**: IFS at 0.1° and 0.25°, and the AIFS machine learning
  forecast.
- **Every capital**, a lot of major cities and some notable peaks, with
  flags, and any place you add yourself.
- **Fifteen days** of forecast, grouped by day, with the numbers and the
  plot of each parameter together.
- **Local time and UTC**, a switch between the two, and the time the values
  belong to always in the corner.

## Getting started

```bash
pip install -r requirements.txt

python service.py once     # fetch the latest run
python widget.py --open    # and look at it
```

The widget is then on <http://localhost:8765>.

To keep it up to date, run the service as a daemon, and optionally the
publisher with it:

```bash
python service.py run
python auto_publish.py     # waits for each new run, then updates the page
```

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
| [Publishing](documentation/publishing.md) | GitHub Pages, the daemon, the size limits |

## The commands

| | |
| --- | --- |
| `python service.py once` | Fetch the latest run and stop |
| `python service.py run` | Keep the database up to date |
| `python service.py status` | What has been fetched |
| `python widget.py --open` | The widget, in a browser |
| `python widget.py --text` | The forecast as text |
| `python publish.py` | Fetch, rebuild the page, commit and push |
| `python auto_publish.py` | The same, on a schedule |
| `python make_icons.py` | Generate the weather icons |
| `python build_places.py` | Rebuild the catalogue of world places |

## A note on the data

The 0.1° tier is published about two hours after the 0.25° one, and only
the 00 and 12 UTC runs carry the long range: the 06 and 18 UTC runs stop
at 144 hours. The widget shows the run that reaches furthest and says where
each run ends, so there is no guessing.

Every parameter is a full global field, so asking for all of them is a lot
of downloading — about 6 GB and fifteen minutes per run. `parameters: basic`
in `places.yml` is the lighter option.

## Credits

Generated using [ECMWF free and open data](https://www.ecmwf.int/en/forecasts/datasets/open-data),
licensed under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).
ECMWF must be attributed.

The weather icons are generated with
[Z-Image-Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo).
