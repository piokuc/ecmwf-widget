"""Shared fixtures for the test suite."""

from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

#: The root of the repository, so the tests find the configuration files
#: whatever directory pytest was started from.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where the built page is written.
SITE_DIR = REPO_ROOT / "site"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """The request handler, without the log line per request."""

    def log_message(self, format, *args):
        pass


def _build_a_page_of_its_own(directory: Path) -> Path:
    """Build a page from made up values, so the scenarios always have one.

    The real page is built from a forecast that has been fetched, which
    needs the network. The scenarios are about the bundle a visitor
    receives, not about the data in it, so a small store of invented values
    is enough to exercise them.
    """
    from ecmwf_widget import build_site
    from ecmwf_widget.points import Place, PointValue
    from ecmwf_widget.store import ForecastStore

    database = directory / "forecast.sqlite"
    config = directory / "places.yml"
    config.write_text(
        "places:\n"
        "  - id: testville\n"
        "    name: Testville\n"
        "    latitude: 50.0\n"
        "    longitude: 10.0\n"
        "    elevation: 120\n"
        "    country: Poland\n"
        "    country_code: PL\n"
        "catalogue: none\n"
        "models: [ifs]\n"
        "parameters: [2t, msl, 10u, 10v, tcc, tp]\n"
        f"database: {database}\n"
        "cache_dir: " + str(directory / "grib") + "\n"
    )

    place = Place(
        id="testville",
        name="Testville",
        latitude=50.0,
        longitude=10.0,
        elevation=120,
        country="Poland",
        country_code="PL",
        flag="🇵🇱",
    )
    run = "2026010100"
    fields = (
        ("2t", 281.3, "K"),
        ("msl", 101325.0, "Pa"),
        ("10u", 3.5, "m s-1"),
        ("10v", 1.5, "m s-1"),
        ("tcc", 42.0, "%"),
        ("tp", 0.0, "m"),
    )
    values = [
        PointValue(
            place_id=place.id,
            param=param,
            level=None,
            step=step,
            value=value + step / 100.0,
            units=units,
            method="bilinear",
            levtype="sfc",
        )
        for step in (0, 6, 12, 24)
        for param, value, units in fields
    ]

    with ForecastStore(database) as store:
        store.upsert_run(
            run, run[:8], run[8:], model="ifs", resol="0p1", status="complete", label="IFS 0.1°"
        )
        store.store_places(run, [place], model="ifs")
        store.store_values(run, values, model="ifs")

    out = directory / "site"
    build_site.build(str(out), str(config))
    return out


@pytest.fixture(scope="session")
def built_site(tmp_path_factory):
    """The directory the published page is served from.

    The page that was built on the machine is used when there is one;
    otherwise a page is built from made up values, so the scenarios never
    have nothing to look at.
    """
    if (SITE_DIR / "index.html").exists():
        return SITE_DIR
    return _build_a_page_of_its_own(tmp_path_factory.mktemp("site"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The root of the repository."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def site_dir() -> Path:
    """The directory the built page is written to."""
    return SITE_DIR


@pytest.fixture(scope="session")
def site_base_url(built_site):
    """Serve the built page over HTTP, like GitHub Pages would.

    The published page is a plain static bundle, so serving the directory
    from a local port exercises exactly what the visitors receive.
    """
    handler = functools.partial(_QuietHandler, directory=str(built_site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def site(site_base_url):
    """The state of the website test: where it is served and what was fetched."""

    class Site:
        def __init__(self, base):
            self.base = base
            self.path = "/"
            self.response = None
            self.body = b""
            self.json = None

        @property
        def url(self):
            suffix = self.path.lstrip("/")
            return f"{self.base}/{suffix}" if suffix else self.base + "/"

        def fetch(self, path, as_json=False):
            import urllib.error
            import urllib.request

            self.path = path
            try:
                with urllib.request.urlopen(self.url, timeout=30) as response:
                    self.response = response
                    self.body = response.read()
            except urllib.error.HTTPError as error:
                self.response = error
                self.body = error.read()
            if as_json and self.response.status == 200:
                import json

                self.json = json.loads(self.body)
            return self

        @property
        def text(self):
            return self.body.decode("utf-8", "replace")

        @property
        def status(self):
            return self.response.status

        @property
        def content_type(self):
            return self.response.headers.get("Content-Type", "")

    return Site(site_base_url)
