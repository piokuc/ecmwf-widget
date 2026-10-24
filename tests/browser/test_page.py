"""Exercise the rendered JavaScript, not just HTML returned by an HTTP request."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize("delivery", ["live", "static"])
def test_forecast_controls(browser_page, forecast_app, delivery):
    page, mobile = browser_page
    page.goto(forecast_app[delivery] + "?place=warsaw&params=2t,wind_speed,wind_dir,10u,10v,tp,precip_increment,tcc")
    expect(page.locator(".place")).to_have_count(1)
    expect(page.locator("#placeInput")).to_have_value("Warsaw")
    expect(page.locator("#model option")).to_have_count(3)
    expect(page.locator("#run option")).to_have_count(2)
    expect(page.locator("#tooltips")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#tip")).not_to_be_visible()
    assert page.locator(".grid svg").count() > 0
    assert page.locator("svg.vector").count() > 0

    # Different model/run values must really reach the table in both delivery modes.
    # Use the payload-independent table text as evidence of a visible forecast change.
    original = page.locator("table").inner_text()
    page.select_option("#model", "aifs")
    expect(page.locator("#model")).to_have_value("aifs")
    expect(page.locator("table")).not_to_have_text(original)
    newest = page.locator("table").inner_text()
    page.select_option("#run", "2026102100")
    expect(page.locator("#run")).to_have_value("2026102100")
    expect(page.locator("table")).not_to_have_text(newest)
    expect(page.locator("#meta")).to_contain_text("2026-10-21 00:00")
    page.reload()
    expect(page.locator("#model")).to_have_value("aifs")
    expect(page.locator("#run")).to_have_value("2026102100")

    # Search plus Enter chooses the filtered result, including on touch screens.
    page.locator("#placeInput").fill("Tokyo")
    page.locator("#placeInput").press("Enter")
    expect(page.locator("#placeInput")).to_have_value("Tokyo")
    expect(page.locator(".place h2")).to_contain_text("Tokyo")
    local_stamp = page.locator(".stamp").inner_text()
    page.locator("#clock").click()
    expect(page.locator("#clock")).to_have_text("UTC")
    expect(page.locator(".stamp")).not_to_have_text(local_stamp)
    page.locator("#theme").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.locator("#theme").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator("#clock")).to_have_text("UTC")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")

    # Parameter searching, disabling unavailable fields, toggling a downloaded series.
    page.locator("#params").click()
    expect(page.locator("#panel")).to_have_class(re.compile("open"))
    assert page.locator('#panel input[type="checkbox"]:disabled').count() > 0
    search = page.locator("#panel .search")
    search.fill("Pressure")
    checkbox = page.locator('#panel label').filter(has_text=re.compile(r"^Pressure")).locator('input')
    expect(checkbox).to_be_enabled()
    checkbox.check()
    expect(page.locator("table")).to_contain_text("Pressure")
    checkbox.uncheck()
    expect(page.locator("table")).not_to_contain_text("Pressure")
    page.locator("#params").click()

    # The run's end is spoken of in UTC, like the cycle in the same sentence.
    expect(page.locator("#meta")).to_contain_text(re.compile(r"until .+ UTC"))

    # The wind direction row gives the direction in degrees, not the speed
    # of the hour the user has selected.
    wind_row = page.locator("tbody tr").filter(has=page.locator("th", has_text="Wind direction"))
    wind_cells = wind_row.locator("td")
    expect(wind_cells.nth(0)).to_contain_text("220°")
    expect(wind_cells.nth(1)).to_contain_text("226°")
    expect(wind_cells.nth(0)).not_to_contain_text("km/h")
    expect(wind_cells.nth(1)).not_to_contain_text("km/h")

    # The temperature cards speak of Celsius, not of the unit the data uses.
    temperature_card = page.locator(".stat.big").first
    expect(temperature_card.locator("small")).to_have_text("°C")
    expect(temperature_card).not_to_contain_text("degC")

    # A static page is a snapshot, not an endpoint that is polled.
    if delivery == "static":
        expect(page.locator(".foot")).not_to_contain_text("refreshed every 60")
    else:
        expect(page.locator(".foot")).to_contain_text("refreshed every 60")

    # Select an hour and return to the current hour.
    page.locator('thead [data-col="1"]').first.click()
    expect(page.locator(".banner")).to_be_visible()
    page.locator(".banner button").click()
    expect(page.locator(".banner")).to_have_count(0)

    # Opt-in is persistent, and disabling immediately removes the overlay.
    cell = page.locator('tbody [data-col="1"]').first
    cell.hover()
    expect(page.locator("#tip")).not_to_be_visible()
    page.locator("#tooltips").click()
    cell.hover()
    expect(page.locator("#tip")).to_be_visible()
    page.reload()
    expect(page.locator("#tooltips")).to_have_attribute("aria-pressed", "true")
    page.locator('tbody [data-col="1"]').first.hover()
    expect(page.locator("#tip")).to_be_visible()
    page.locator("#tooltips").click()
    expect(page.locator("#tip")).not_to_be_visible()

    # Horizontal scrolling is contained by the forecast, including on phones.
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    page.locator(".grid").evaluate("node => { node.scrollLeft = 350; }")
    assert page.locator(".grid").evaluate("node => node.scrollLeft") > 0
    broken = page.locator("img").evaluate_all("nodes => nodes.filter(n => n.complete && !n.naturalWidth).length")
    assert broken == 0
    output = Path("test-results")
    output.mkdir(exist_ok=True)
    page.screenshot(path=str(output / f"{delivery}-{'mobile' if mobile else 'desktop'}.png"), full_page=True)


@pytest.mark.parametrize("delivery", ["live", "static"])
def test_empty_selection_search_and_recovery(browser_page, forecast_app, delivery):
    page, _ = browser_page
    page.goto(forecast_app[delivery] + '?place=warsaw&params=2t')
    expect(page.locator('.place')).to_have_count(1)
    page.locator('#placeInput').fill('no-such-place')
    page.locator('#placeInput').press('Enter')
    assert 'place=warsaw' in page.url
    page.locator('#placeInput').press('Escape')
    expect(page.locator('#picker')).not_to_have_class(re.compile('open'))
    page.locator('#params').click()
    page.locator('#panel .search').fill('Temperature')
    check = page.locator('#panel label').filter(has_text=re.compile(r'^TemperatureK$')).locator('input')
    check.uncheck()
    expect(page.locator('.place .empty')).to_contain_text('None of the chosen parameters')
    page.reload()
    expect(page.locator('.place .empty')).to_contain_text('None of the chosen parameters')
    page.get_by_role('button', name='Use the default set').click()
    expect(page.locator('table')).to_be_visible()
    page.reload()
    expect(page.locator('table')).to_be_visible()


def test_live_error_and_refresh(browser_page, forecast_app):
    page, _ = browser_page
    page.goto(forecast_app['live'] + '?model=invalid')
    expect(page.locator('#content')).to_contain_text('Could not load the forecast: HTTP 404')
    page.clock.install()
    requests = []
    page.on('request', lambda request: requests.append(request.url) if '/api/forecast' in request.url else None)
    page.goto(forecast_app['live'] + '?place=warsaw')
    expect(page.locator('table')).to_be_visible()
    before = len(requests)
    page.clock.fast_forward(61000)
    expect(page.locator('table')).to_be_visible()
    assert len(requests) > before


def test_null_precipitation_is_not_reported_as_dry(browser_page, forecast_app):
    page, _ = browser_page
    def missing(route):
        response = route.fetch()
        payload = response.json()
        for place in payload['places']:
            place['series']['precip_increment']['values'][1] = None
        route.fulfill(response=response, json=payload)
    page.route('**/api/forecast*', missing)
    page.goto(forecast_app['live'] + '?place=warsaw&params=precip_increment,2t')
    expect(page.locator('table')).to_be_visible()
    expect(page.locator('tbody tr.summary')).to_contain_text('Rain incomplete')
