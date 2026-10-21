#!/usr/bin/env python3
"""Build the static page that is published on GitHub Pages.

The page is the same one the local widget serves, but the forecast is
embedded in it instead of being fetched. That way it works from a plain
file server and on GitHub Pages, with no backend at all.

    python build_site.py                     # write docs/
    python build_site.py --max-places 60     # keep the page small
    python build_site.py --out /tmp/site     # somewhere else
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil

import models
import widget
from config import load_config
from forecast import ForecastReader
from store import ForecastStore

#: The parameters the page shows when nothing else is picked.
BASIC = {"2t", "2d", "msl", "10u", "10v", "10fg", "tcc", "tp",
         "apparent_temperature", "wind_speed", "wind_dir", "gust",
         "precip_increment", "temperature_adjusted"}


def _trim(place: dict) -> dict:
    """Keep only the basic series of a place."""
    trimmed = dict(place)
    trimmed["series"] = {k: v for k, v in place["series"].items() if k in BASIC}
    return trimmed


def build(
    out_dir: str,
    config_path: str = "places.yml",
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
        payload = reader.widget_payload(run=newest[model], model=model)
        if not payload["places"]:
            continue
        embedded[model] = payload

    if not embedded:
        raise SystemExit(
            "no forecast data in the database; run 'python service.py once' first"
        )

    # Keep the page a sensible size: every parameter for the first few
    # places, the basic set for the rest.
    if max_places:
        for payload in embedded.values():
            payload["places"] = payload["places"][:max_places]
    for payload in embedded.values():
        places = payload["places"]
        payload["places"] = places[:full_places] + [_trim(p) for p in places[full_places:]]

    os.makedirs(out_dir, exist_ok=True)
    icons_out = os.path.join(out_dir, "icons")
    if os.path.isdir(icons_out):
        shutil.rmtree(icons_out)
    if os.path.isdir(widget.ICON_DIR):
        shutil.copytree(widget.ICON_DIR, icons_out)

    # A small file with the state of the data. It changes on every publish, so
    # the commit is a visible data change and not just a rebuilt page.
    latest = {
        "updated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
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
    manifest = {
        "name": "ECMWF forecast",
        "short_name": "ECMWF",
        "description": "Point forecasts from ECMWF's free and open 0.1° data",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#12161c",
        "theme_color": "#1d6fb8",
        "icons": [
            {"src": "app-icon-192.png", "sizes": "192x192", "type": "image/png"},
            {
                "src": "app-icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    with open(os.path.join(out_dir, "manifest.webmanifest"), "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)

    for size in (192, 512):
        source = os.path.join("assets", f"app-icon-{size}.png")
        if os.path.exists(source):
            shutil.copy(source, os.path.join(out_dir, f"app-icon-{size}.png"))

    data = json.dumps(embedded, separators=(",", ":"))
    page = widget.PAGE.replace(
        "<script>\nconst REFRESH_MS = 60000;",
        "<script>window.FORECAST_DATA = " + data + ";</script>\n"
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="places.yml")
    parser.add_argument("--out", default="docs", help="output directory")
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
