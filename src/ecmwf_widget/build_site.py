#!/usr/bin/env python3
"""Build the static page that is published on GitHub Pages.

The page is the same one the local widget serves, but the forecast is
embedded in it instead of being fetched. That way it works from a plain
file server and on GitHub Pages, with no backend at all.

    ecmwf-build-site                     # write site/
    ecmwf-build-site --max-places 60     # keep the page small
    ecmwf-build-site --out /tmp/site     # somewhere else
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil

from . import models, paths, widget
from .config import load_config
from .forecast import ForecastReader
from .store import ForecastStore

#: The parameters the page shows when nothing else is picked.
BASIC = {"2t", "2d", "msl", "10u", "10v", "10fg", "tcc", "tp",
         "apparent_temperature", "wind_speed", "wind_dir", "gust",
         "precip_increment", "temperature_adjusted"}

#: Where the page is written by default.
DEFAULT_OUT = "site"


def _trim(place: dict) -> dict:
    """Keep only the basic series of a place."""
    trimmed = dict(place)
    trimmed["series"] = {k: v for k, v in place["series"].items() if k in BASIC}
    return trimmed


def build(
    out_dir: str,
    config_path: str | None = None,
    max_places: int | None = None,
    full_places: int = 25,
) -> dict:
    """Write the static site and return a small summary.

    Every parameter of the first ``full_places`` places is embedded, the rest
    only get the basic set. With every parameter of every place the page
    would be tens of megabytes.
    """
    config = load_config(config_path)
    store = ForecastStore(config.database)
    reader = ForecastReader(store, lapse_rate=config.lapse_rate, catalogue=config.all_places)

    embedded: dict[str, dict] = {}
    newest: dict[str, str] = {}
    for info in store.runs():
        if info.run > newest.get(info.model, ""):
            newest[info.model] = info.run
    # The order decides which model the page shows first, so keep the order
    # of the model catalogue.
    for model in models.MODELS:
        if model not in newest:
            continue
        # No run is given, so the reader picks the one that reaches furthest,
        # which is the 00 or 12 UTC run. The page and the run selector then
        # talk about the same run.
        payload = reader.widget_payload(model=model)
        if not payload["places"]:
            continue
        embedded[model] = payload

    if not embedded:
        raise SystemExit(
            "no forecast data in the database; run 'ecmwf-service once' first"
        )

    # Every offered run must have actual data in the static bundle.
    embedded_runs = {}
    for info in store.runs():
        payload = reader.widget_payload(run=info.run, model=info.model)
        if payload["places"]:
            embedded_runs.setdefault(info.model, {})[info.run] = payload
    store.close()

    # Keep the page a sensible size: every parameter for the first few
    # places, the basic set for the rest.
    payloads = list(embedded.values()) + [p for runs in embedded_runs.values() for p in runs.values()]
    for payload in payloads:
        if max_places:
            payload["places"] = payload["places"][:max_places]
        kept = {place["id"] for place in payload["places"]}
        payload["place_list"] = [place for place in payload["place_list"] if place["id"] in kept]
        payload["runs"] = [run for run in payload["runs"]
                           if run["run"] in embedded_runs.get(run["model"], {})]
    for payload in payloads:
        places = payload["places"]
        payload["places"] = places[:full_places] + [_trim(p) for p in places[full_places:]]

    os.makedirs(out_dir, exist_ok=True)
    icons_out = os.path.join(out_dir, "icons")
    if os.path.isdir(icons_out):
        shutil.rmtree(icons_out)
    if os.path.isdir(paths.ICON_DIR):
        shutil.copytree(paths.ICON_DIR, icons_out)

    # A small file with the state of the data. It changes on every publish, so
    # the commit is a visible data change and not just a rebuilt page.
    latest = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "models": {
            model: {
                "run": payload["run"],
                "cycle": payload["cycle_utc"],
                "places": len(payload["places"]),
            }
            for model, payload in embedded.items()
        },
    }
    with open(os.path.join(out_dir, "latest.json"), "w") as handle:
        json.dump(latest, handle, indent=2, sort_keys=True)

    # The web app manifest, so the page can be installed on a phone.
    with open(os.path.join(out_dir, "manifest.webmanifest"), "w") as handle:
        json.dump(widget.manifest(), handle, indent=2, sort_keys=True)

    for size in (192, 512):
        source = paths.ASSETS_DIR / f"app-icon-{size}.png"
        if source.exists():
            shutil.copy(source, os.path.join(out_dir, f"app-icon-{size}.png"))

    # Escape script delimiters in user-supplied place metadata.
    data = json.dumps(embedded, separators=(",", ":")).replace("<", "\\u003c")
    runs_data = json.dumps(embedded_runs, separators=(",", ":")).replace("<", "\\u003c")
    page = widget.PAGE.replace(
        "<script>\nconst REFRESH_MS = 60000;",
        "<script>window.FORECAST_DATA = " + data + ";</script>\n<script>window.FORECAST_RUNS = " + runs_data + ";</script>\n"
        "<script>\nconst REFRESH_MS = 60000;",
        1,
    )
    if "window.FORECAST_DATA" not in page:
        raise SystemExit("could not embed the data into the page")

    index = os.path.join(out_dir, "index.html")
    with open(index, "w") as handle:
        handle.write(page)

    return {
        "file": index,
        "size": os.path.getsize(index),
        "models": {key: len(value["places"]) for key, value in embedded.items()},
        "places": sum(len(value["places"]) for value in embedded.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ecmwf-build-site", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, help="configuration file")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    parser.add_argument("--max-places", type=int, default=None, help="limit the number of places")
    parser.add_argument(
        "--full-places",
        type=int,
        default=25,
        help="how many places get every parameter, the rest get the basic set",
    )
    args = parser.parse_args(argv)

    summary = build(args.out, args.config, args.max_places, args.full_places)
    print(f"wrote {summary['file']} ({summary['size'] / 1e6:.2f} MB)")
    for model, places in summary["models"].items():
        print(f"  {model}: {places} places")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
