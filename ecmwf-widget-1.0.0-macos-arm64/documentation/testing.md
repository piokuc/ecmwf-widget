# The tests

The project is testable without touching the network: the schedule, the
configuration, the catalogue and the storage are pure enough to be examined
directly, and everything that talks to the portal or to git is faked away.

## Running them

```bash
pip install -r requirements-dev.txt     # pytest, pytest-bdd
pytest                                  # everything: unit tests and scenarios
pytest tests                            # only the pytest suite (no Cucumber)
pytest tests/features                   # only the website scenarios
```

`pytest.ini` points Python at the repository root, so the `ecmwf_widget`
package is imported no matter where pytest is started from.

## Where the tests live

```
tests/
├── conftest.py                 shared fixtures: the served page bundle
├── test_scheduler.py           the ECMWF publication schedule
├── test_config.py              places.yml loading, validation, the catalogue
├── test_parameters.py          the parameter catalogue, the units, the physics
├── test_models.py              the catalogue of models
├── test_store.py               the SQLite store
├── test_service.py             the ingester, with the network faked away
└── test_publishing.py          the publishing daemon, against a real git repo
```

## What the unit tests cover

| File | The promise it checks |
| --- | --- |
| `test_scheduler.py` | The cycles are 0, 6, 12, 18 UTC; the next expected run is always **cycle + the delay** and always in the future; the delay moves on to the next cycle once it has passed |
| `test_config.py` | `places.yml` loads; duplicate or incomplete places are rejected; `catalogue` picks by id, by `region:` and `kind:`, or `all` and `none`; `basic` and `all` expand; unknown parameters are rejected |
| `test_parameters.py` | Units convert as they should (K → °C, Pa → hPa, m → mm and the kg m-2 form of the AI models); the wind direction is meteorological; the derived quantities agree with hand-computed values |
| `test_models.py` | `ifs`, `ifs025` and `aifs` resolve, `all` expands, unknown models raise |
| `test_store.py` | Runs are upserted and dated once; surface values get level −1, pressure values their hPa level; several threads can write at once; pruning keeps the newest runs of every model; the CSV export carries the model |
| `test_service.py` | The service only asks for the parameters a step actually publishes; a failed step marks the run `partial` and is retried on the next poll; derived values are computed from the downloaded fields; the GRIB cache is pruned to the last run |
| `test_publishing.py` | The daemon pushes a new version when the page changed, does nothing when it did not, keeps the index clean on a dry run, and pushes the built page even though it is in `.gitignore` |

The ingestion test is worth a note: the network is replaced with fakes that
answer the questions the real portal answers — which parameters a step
published, what a downloaded GRIB contains — and then the whole
`ingest_run` flow runs against a real temporary database. Nothing in it is
hardcoded around the fakes, so a change in behaviour shows up as a failure.

## The Cucumber description of the page

`tests/features/published_page.feature` is a plain-text description of what
the published page promises. It reads like the visitor's experience:

```gherkin
Scenario: The page advertises the state of the data
    When I fetch "latest.json" as JSON
    Then the response is successful
    And it lists the time of the last update
    And every model in it lists its run and its number of places
    And every run in it is a ten digit run stamp
```

The step definitions (in `tests/features/step_defs/`) turn those sentences
into requests against the **built page bundle**, served from a directory
over HTTP, exactly the way GitHub Pages serves it:

```python
import http.server, functools
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DOCS)
```

So the scenarios test the artefact a visitor receives — the same byte
count, the same cache headers, the same content types — and not the internals
that produced it.

## What the scenarios promise

1. **A visitor can open the page** — it answers, it is HTML, the forecast
   of every published model is embedded in it, and it links a manifest.
2. **The page advertises the state of the data** — `latest.json` exists,
   says when it was built, and lists a run stamp and a place count per model.
3. **The page can be installed on a phone** — the manifest names the app,
   its icons really exist as PNG files on the server, and it launches standalone.
4. **The weather icons are published** — `icons/*.png` answer as real PNGs.
5. **The data source is credited** — ECMWF's open data licence is on the page.
6. **Nothing essential is missing** — the bundle holds every file the page needs.

## Testing the page that is actually online

The scenarios run against the local bundle. For the page as GitHub Pages
serves it right now:

```bash
curl -s https://piokuc.github.io/ecmwf-widget/latest.json | python3 -m json.tool
gh workflow run pages.yml        # rebuild and redeploy it
```

The last deploy can be watched with `gh run watch`, and `latest.json` is
the honest verdict: its `updated` stamp is the moment the page last changed.

## A note on what is *not* tested

- The GRIB download itself (`ecmwf_open_data.py`), because it needs the
  network; the retrieval is checked in [`retrieval.md`](retrieval.md) by
  hand against the 0.25° data of the same run.
- The rendering of the widget page, which is a single HTML/JS file; the
  scenarios check that it answers, embeds data and links its manifest, not
  that every pixel looks right.
- The icon generation, which is a slow local image model.
