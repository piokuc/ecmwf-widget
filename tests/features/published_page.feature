Feature: The published forecast page

  GitHub Pages serves the page that the publisher built from ECMWF's own
  open data. Every scenario here is a promise about the bundle that a
  visitor receives: it answers, it carries the forecast of the runs that
  reached furthest, it can be installed on a phone, and it credits ECMWF.

  The page is built by `build_site.py` from the values the service stored.
  Build it with `python build_site.py` before running these scenarios
  against a local server (GitHub Pages serves the same bundle).

  Background: The page is being served
    Given the published page is served

  Scenario: A visitor can open the page
    When I fetch the page
    Then the response is successful
    And the response is an HTML page
    And the page embeds the forecast data of every published model
    And the page offers the manifest of an installable app

  Scenario: The page advertises the state of the data
    When I fetch "latest.json" as JSON
    Then the response is successful
    And it lists the time of the last update
    And every model in it lists its run and its number of places
    And every run in it is a ten digit run stamp

  Scenario: The page can be installed on a phone
    When I fetch "manifest.webmanifest" as JSON
    Then the response is successful
    And its name is "ECMWF" for short
    And it points at icons that exist on the server
    And it launches standalone without a browser bar

  Scenario: The weather icons are published
    When I fetch "icons/cloud.png"
    Then the response is successful
    And the response is a PNG image

  Scenario: The data source is credited
    When I fetch the page
    Then the response is successful
    And the page credits ECMWF open data

  Scenario: Nothing essential is missing
    When I try to fetch "index.html"
    And I try to fetch "latest.json"
    And I try to fetch "manifest.webmanifest"
    Then no response failed
