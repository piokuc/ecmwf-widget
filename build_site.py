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
import json
import os
import shutil

import models
import widget
from config import load_config
from forecast import ForecastReader
from store import ForecastStore


def build(out_dir: str, config_path: str = "places.yml", max_places: int | None = None) -> dict:
    """Write the static site and return a small summary."""
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

    # Keep the page a sensible size when there are many places.
    if max_places:
        for payload in embedded.values():
            payload["places"] = payload["places"][:max_places]

    os.makedirs(out_dir, exist_ok=True)
    icons_out = os.path.join(out_dir, "icons")
    if os.path.isdir(icons_out):
        shutil.rmtree(icons_out)
    if os.path.isdir(widget.ICON_DIR):
        shutil.copytree(widget.ICON_DIR, icons_out)

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
    args = parser.parse_args(argv)

    summary = build(args.out, args.config, args.max_places)
    print(f"wrote {summary['file']} ({summary['size'] / 1e6:.2f} MB)")
    for model, places in summary["models"].items():
        print(f"  {model}: {places} places")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
