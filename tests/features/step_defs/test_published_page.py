"""The step definitions of the published page scenarios."""

from __future__ import annotations

import datetime as dt
import json
import re

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("published_page.feature")


# -- background -------------------------------------------------------------- #

@given("the published page is served", target_fixture="page")
def the_page_is_served(site):
    return site.fetch("/")


# -- when ---------------------------------------------------------------------#

@when("I fetch the page")
def fetch_the_page(page):
    assert page.status == 200, "the background should have fetched the page"


@when('I fetch "latest.json" as JSON')
def fetch_latest_json(page):
    page.fetch("latest.json", as_json=True)


@when('I fetch "manifest.webmanifest" as JSON')
def fetch_manifest(page):
    page.fetch("manifest.webmanifest", as_json=True)


@when('I fetch "icons/cloud.png"')
def fetch_cloud_icon(page):
    page.fetch("icons/cloud.png")


@when('I try to fetch "index.html"')
def try_index(page):
    page.fetch("/index.html")


@when('I try to fetch "latest.json"')
def try_latest(page):
    page.fetch("latest.json", as_json=True)


@when('I try to fetch "manifest.webmanifest"')
def try_manifest(page):
    page.fetch("manifest.webmanifest", as_json=True)


# -- then ---------------------------------------------------------------------#

@then("the response is successful")
def response_successful(page):
    assert page.response is not None
    assert page.status == 200, f"{page.url} answered {page.status}"


@then("the response is an HTML page")
def response_is_html(page):
    assert "text/html" in page.content_type


@then("the page embeds the forecast data of every published model")
def page_embeds_forecast(page):
    assert "window.FORECAST_DATA" in page.text, "the forecast is not embedded"
    # the models are in the data as keys
    match = re.search(r"window\.FORECAST_DATA\s*=\s*(\{.*?\});</script>", page.text, re.DOTALL)
    assert match, "the embedded forecast data is not a JSON object"
    data = json.loads(match.group(1))
    assert data, "no model at all is embedded"
    for model, payload in data.items():
        assert payload["places"], f"model {model} has no places"


@then("the page offers the manifest of an installable app")
def page_offers_manifest(page):
    match = re.search(
        r'<link[^>]+rel="manifest"[^>]+href="([^"]+)"', page.text
    )
    assert match, "the page carries no manifest link"
    page.fetch(match.group(1))


@then("it lists the time of the last update")
def latest_lists_update(page):
    assert page.json is not None, "latest.json is not JSON"
    assert "updated" in page.json
    updated = dt.datetime.fromisoformat(page.json["updated"])
    assert updated.date() >= dt.date(2026, 1, 1)


@then("every model in it lists its run and its number of places")
def latest_lists_models(page):
    assert page.json.get("models"), "no model is advertised in latest.json"
    for model, state in page.json["models"].items():
        assert state["run"], f"model {model} has no run"
        assert state["places"] >= 1, f"model {model} advertises no places"


@then("every run in it is a ten digit run stamp")
def latest_runs_are_stamps(page):
    for model, state in page.json["models"].items():
        assert re.fullmatch(r"\d{10}", str(state["run"])), (
            f"run of {model} is not a stamp: {state['run']}"
        )


@then(parsers.parse('its name is "{name}" for short'))
def manifest_short_name(page, name):
    assert page.json["short_name"] == name
    assert re.search(r"ECMWF|forecast", page.json["name"], re.IGNORECASE)


@then("it points at icons that exist on the server")
def manifest_icons_exist(page):
    icons = page.json.get("icons")
    assert icons, "the manifest lists no icons"
    for icon in icons:
        src = icon["src"]
        if not src.startswith("http"):
            base = page.base
            src = f"{base}/{src}"
        import urllib.request

        with urllib.request.urlopen(src, timeout=30) as response:
            assert response.status == 200
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"


@then("it launches standalone without a browser bar")
def manifest_standalone(page):
    assert page.json["display"] == "standalone"


@then("the response is a PNG image")
def response_is_png(page):
    assert page.body[:8] == b"\x89PNG\r\n\x1a\n"


@then("the page credits ECMWF open data")
def page_credits_ecmwf(page):
    text = page.text
    assert "ECMWF" in text
    assert re.search(r"CC-BY|attribution|open data", text, re.IGNORECASE), (
        "the credits are missing"
    )


@then("no response failed")
def no_response_failed(page):
    assert page.response is not None
    assert page.status == 200, f"{page.path} answered {page.status}"
