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
   +---------------------------+
   |  service.py               |  finds a new run, downloads the fields it
   |  ecmwf_open_data.py       |  needs, evaluates them at every place
   |  points.py                |  and stores the result
   |  store.py  (SQLite)       |
   +---------------------------+
          |
          |  one table of values
          v
   +---------------------------+
   |  widget.py                |  serves the page and the data
   |  forecast.py              |  turns the stored values into a tidy
   |  parameters.py            |  structure the page can render
   +---------------------------+
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

## The modules

| File | What it does |
| --- | --- |
| `ecmwf_open_data.py` | Finds and downloads files from the portal, using the index files and HTTP range requests so that only the wanted fields are transferred |
| `models.py` | The catalogue of models that are published, and how long each one reaches |
| `parameters.py` | Every parameter the data has, with its label, unit, group and the order it is shown in |
| `points.py` | Reads a GRIB file and evaluates it at a list of coordinates |
| `store.py` | The SQLite database: runs, places and values |
| `config.py` | Reads `places.yml` and `world_places.yml` |
| `service.py` | The daemon that keeps the database up to date |
| `forecast.py` | Turns the stored values into what the page needs |
| `widget.py` | The page itself, and the small server that serves it |
| `build_site.py` | Builds the static page for GitHub Pages |
| `download_9km.py` | A small command line tool for a one off download |
| `auto_publish.py` | Waits for a new run, then rebuilds and pushes the page |
| `publish.py` | One shot: fetch, rebuild, commit, push |
| `make_icons.py` | Generates the weather icons with a local image model |
| `build_places.py` | Builds the catalogue of world places |

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
