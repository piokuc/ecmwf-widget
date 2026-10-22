"""The local widget: the page, the icons and the API."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from ecmwf_widget import paths
from ecmwf_widget.points import Place, PointValue
from ecmwf_widget.store import ForecastStore
from ecmwf_widget.widget import Handler, WidgetServer, manifest

PLACE = Place(
    id="gliwice",
    name="Gliwice",
    latitude=50.29417,
    longitude=18.66583,
    elevation=230,
    country="Poland",
    country_code="PL",
    flag="🇵🇱",
)


@pytest.fixture
def server(tmp_path):
    """A widget server with a small store behind it."""
    from ecmwf_widget.forecast import ForecastReader

    run = "2026010100"
    with ForecastStore(tmp_path / "forecast.sqlite") as store:
        store.upsert_run(
            run, run[:8], run[8:], model="ifs", resol="0p1", status="complete", label="IFS 0.1°"
        )
        store.store_places(run, [PLACE], model="ifs")
        store.store_values(
            run,
            [
                PointValue(
                    place_id=PLACE.id,
                    param="2t",
                    level=None,
                    step=step,
                    value=281.0,
                    units="K",
                    method="bilinear",
                    levtype="sfc",
                )
                for step in (0, 6, 12)
            ],
            model="ifs",
        )
        reader = ForecastReader(store, catalogue=[PLACE])
        httpd = WidgetServer(("127.0.0.1", 0), Handler, reader)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()
            httpd.server_close()


def _fetch(url: str) -> tuple[int, bytes, str]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        return error.status, error.read(), error.headers.get("Content-Type", "")


# -- the page ----------------------------------------------------------------- #

def test_the_page_answers(server):
    status, body, kind = _fetch(f"{server}/")
    assert status == 200
    assert "text/html" in kind
    assert b"ECMWF" in body


def test_the_page_answers_under_its_own_name(server):
    status, _, _ = _fetch(f"{server}/index.html")
    assert status == 200


# -- the icons ---------------------------------------------------------------- #

def test_the_weather_icons_are_served(server):
    status, body, kind = _fetch(f"{server}/icons/sun.png")
    assert status == 200
    assert kind == "image/png"
    assert body[:8] == b"\x89PNG\r\n\x1a\n"


def test_an_icon_that_is_not_there_is_not_found(server):
    status, _, _ = _fetch(f"{server}/icons/nonsense.png")
    assert status == 404


def test_the_app_icons_are_served(server):
    for size in (192, 512):
        status, body, kind = _fetch(f"{server}/app-icon-{size}.png")
        assert status == 200, size
        assert kind == "image/png"
        assert body[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_manifest_is_served(server):
    status, body, kind = _fetch(f"{server}/manifest.webmanifest")
    assert status == 200
    assert "manifest" in kind
    assert json.loads(body)["short_name"] == "ECMWF"


def test_the_manifest_names_the_icons_that_exist():
    for icon in manifest()["icons"]:
        assert (paths.ASSETS_DIR / icon["src"]).is_file()


# -- the API ------------------------------------------------------------------ #

def test_the_places_are_served(server):
    status, body, kind = _fetch(f"{server}/api/places")
    assert status == 200
    assert "json" in kind
    places = json.loads(body)
    assert [place["id"] for place in places] == ["gliwice"]


def test_the_forecast_is_served(server):
    status, body, _ = _fetch(f"{server}/api/forecast")
    assert status == 200
    payload = json.loads(body)
    assert payload["places"]
    assert payload["places"][0]["id"] == "gliwice"


def test_an_unknown_route_is_not_found(server):
    status, _, _ = _fetch(f"{server}/api/nonsense")
    assert status == 404
