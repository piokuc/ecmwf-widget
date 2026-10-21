"""Shared fixtures for the test suite."""

from __future__ import annotations

import functools
import http.server
import os
import threading

import pytest

DOCS = os.path.join(os.path.dirname(__file__), os.pardir, "docs")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """The request handler, without the log line per request."""

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass


@pytest.fixture(scope="session")
def site_base_url():
    """Serve the built page in ``docs/`` over HTTP, like GitHub Pages would.

    The published page is a plain static bundle, so serving the directory
    from a local port exercises exactly what the visitors receive.
    """
    if not os.path.exists(os.path.join(DOCS, "index.html")):
        pytest.skip("docs/index.html does not exist; build the site first")
    handler = functools.partial(_QuietHandler, directory=DOCS)
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
