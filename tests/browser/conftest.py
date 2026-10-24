"""Real browser fixtures for both delivery paths; never reuse a stale built site."""
from __future__ import annotations

import functools
import http.server
import os
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from ecmwf_widget import build_site, models
from ecmwf_widget.forecast import ForecastReader
from ecmwf_widget.points import Place, PointValue
from ecmwf_widget.store import ForecastStore
from ecmwf_widget.widget import Handler, WidgetServer


@pytest.fixture(scope="session")
def forecast_app(tmp_path_factory):
    directory = tmp_path_factory.mktemp("browser-app")
    database = directory / "forecast.sqlite"
    config = directory / "places.yml"
    config.write_text(f"catalogue: none\nplaces: []\ndatabase: {database}\n")
    places = [Place("warsaw", "Warsaw", 52.2, 21, timezone="Europe/Warsaw", country="Poland"),
              Place("tokyo", "Tokyo", 35.6, 139.6, timezone="Asia/Tokyo", country="Japan")]
    store = ForecastStore(database)
    for model_index, model in enumerate(models.MODELS.values()):
        for run_index, run in enumerate(("2026102100", "2026102112")):
            store.upsert_run(run, run[:8], run[8:], model=model.key, resol=model.resol,
                             status="complete", label=model.label)
            store.store_places(run, places, model.key)
            values = []
            for place_index, place in enumerate(places):
                for step in range(0, 73, 6):
                    fields = [("2t", 280 + model_index * 10 + run_index * 2 + place_index + step / 10, "K"),
                              ("2d", 275, "K"), ("10u", 3, "m s-1"), ("10v", 4, "m s-1"),
                              ("wind_speed", 5, "m s-1"), ("wind_dir", 220 + step, "deg"),
                              ("msl", 101325, "Pa"), ("tp", step / 1000, "m"),
                              ("tcc", 50, "%"), ("sf", None if step == 6 else 0, "m")]
                    values.extend(PointValue(place.id, param, None, step, value, units)
                                  for param, value, units in fields)
                    values.append(PointValue(place.id, "t", 850, step, 270, "K", levtype="pl"))
            store.store_values(run, values, model.key)
    site = directory / "site"
    build_site.build(str(site), str(config))
    static = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
        functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site)))
    live = WidgetServer(("127.0.0.1", 0), Handler, ForecastReader(store, catalogue=places))
    for server in (static, live):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"static": f"http://127.0.0.1:{static.server_port}",
           "live": f"http://127.0.0.1:{live.server_port}"}
    for server in (static, live):
        server.shutdown()
        server.server_close()
    store.close()


@pytest.fixture(scope="session")
def browser_engines():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(__file__).resolve().parents[2] / ".playwright"))
    with sync_playwright() as playwright:
        yield playwright


@pytest.fixture(params=[("chromium", False), ("chromium", True), ("webkit", False), ("webkit", True)],
                ids=["chromium-desktop", "chromium-mobile", "webkit-desktop", "webkit-mobile"])
def browser_page(request, browser_engines):
    engine, mobile = request.param
    browser = getattr(browser_engines, engine).launch()
    context = browser.new_context(viewport={"width": 390 if mobile else 1440, "height": 844 if mobile else 1000},
                                  is_mobile=mobile, has_touch=mobile, device_scale_factor=1)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page, mobile
    assert not errors, errors
    context.close()
    browser.close()
