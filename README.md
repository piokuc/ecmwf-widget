# ECMWF 0.1° forecast widget

Point forecasts from ECMWF's free and open 0.1° (about 9 km) IFS data, for
any set of places, with a small web widget and a service that keeps the data
up to date.

![The widget](docs/screenshot.png)

## What it does

- Downloads ECMWF's highest resolution open forecast data. No API key, no
  registration, no account. The data is CC-BY-4.0.
- Evaluates the forecast at the points you care about: cities, villages,
  summits, anywhere.
- Keeps running and picks up each new run as it is published.
- Serves a widget that shows one place at a time, with a searchable list of
  places, several models to choose from, and a chart where every parameter
  has its own colour, scale and hover description.

## The models

| Key | What it is |
| --- | --- |
| `ifs` | The high resolution deterministic forecast, 0.1° (about 9 km) |
| `ifs025` | The same forecast on the 0.25° grid, published sooner |
| `aifs` | The artificial intelligence forecast |

The AI ensemble is not set up at the moment. ECMWF serves it, and the
service can ingest an ensemble again by adding the model back to `models.py`.

## Getting started

```bash
pip install -r requirements.txt

python service.py once     # fetch the latest run
python widget.py --open    # serve the widget on http://localhost:8765
```

To keep it up to date, run the service as a daemon:

```bash
python service.py run      # checks every 15 minutes
```

## Choosing places

Your own places live in `places.yml`. Add an entry and it is followed from
the next run:

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

There is also a catalogue of every capital, a lot of major cities and some
notable peaks in `world_places.yml`. To follow them as well, set
`catalogue: all` in `places.yml`, or list the ones you want.

## Publishing to GitHub Pages

The page is static, with the forecast embedded in it, so it works on GitHub
Pages without any backend.

```bash
python publish.py          # fetch, rebuild the page, commit and push
```

That publishes to <https://piokuc.github.io/ecmwf-widget/>.

## Keeping the page up to date

`auto_publish.py` is a daemon that does the whole thing on its own. It works
out when the next run is due, waits until a minute after that, polls the
portal until the data shows up, then rebuilds the page and pushes it. The push
is what makes GitHub Pages publish the new page.

```bash
python auto_publish.py
```

The 0.1 degree tier appears about two hours after the 0.25 degree tier, which
is roughly eight hours and forty minutes after the cycle time. The daemon
uses that as its schedule:

| Cycle | Expected on the portal |
| --- | --- |
| 00z | 08:40 UTC |
| 06z | 14:40 UTC |
| 12z | 20:40 UTC |
| 18z | 02:40 UTC |

If the timing shifts, change it with `--delay 07:30`. Other options:

```bash
python auto_publish.py --now          # check straight away, do not wait
python auto_publish.py --once         # one cycle, then exit
python auto_publish.py --dry-run      # everything except the push
python auto_publish.py --poll 60      # seconds between tries
```

Each publish writes `docs/latest.json` next to the page, with the run and
the time of the data in it.

## On a phone

The page is responsive and works on a phone. It is also an installable web
app: open it in Safari or Chrome and use "Add to Home Screen", and it opens
without the browser chrome, with its own icon.

## Notes on the data

- The 0.1° tier is published about two hours after the 0.25° tier.
- Only the last twelve runs are kept by ECMWF, so the service should not be
  left off for more than a couple of days.
- The forecast for a summit comes from the surrounding grid cell, which can
  be hundreds of metres below the real peak. The widget corrects the
  temperature for the height difference and shows both heights.

## Attribution

Generated using ECMWF free and open data, licensed under CC-BY-4.0.
