# The web page

One page, no framework, no build step for the front end. The page is a
Python string that is served as it is, or written into a static file for
GitHub Pages.

## What the reader sees

```
┌──────────────────────────────────────────────────────────────┐
│ ECMWF forecast   Run 2026-10-21 00:00 UTC · until Thu 05 Nov  │
│                 [model] [place] [run] [Local] [Parameters] [☾] │
├──────────────────────────────────────────────────────────────┤
│ ⌖ Gliwice 🇵🇱                          Wednesday, 21 October  │
│   50.2942, 18.6658 · Poland · 230 m      2026 at 14:00        │
│   model height 241 m                            (12:00 UTC)   │
│                                                              │
│  [Temp 20°] [Feels 17°] [Precip 0] [Wind 13] [Gust 28] ...  │
│                                                              │
│            WED              THU              FRI            │
│         02:00 08:00 ...                                      │
│  Day            10–20°         8–10° · 21.8 mm              │
│  ☁  ☀  ⛅  ☁  ⛅  🌧  🌧  🌧  ☀ ...                           │
│  🌡  9.7° 9.8° 20.0° 13.5° ...                              │
│  ╱‾╲__╱‾‾‾╲___   ← the plot of the same row                 │
│  💧 0.0  0.0  0.0  0.0 ...                                  │
│  ╱‾‾‾‾‾‾‾‾‾‾   ← and the plot under it                     │
└──────────────────────────────────────────────────────────────┘
```

## The parts

**The header** has the run, the model, the place, the run to show, a switch
between local time and UTC, the parameter panel and the theme.

**The card** has the place with its flag and coordinates, the time the
values belong to in the top right, the current conditions as a row of cards,
and the table.

The cards show the parameters that are switched on, in the same order as
everything else, up to twelve of them.

**The table** is the heart of it. Two header rows, the days and then the
times, and then one row of numbers per parameter with the plot of that same
parameter right underneath it. A day spans its columns, with a rule between
the days and a summary of the day in the row above.

The long parameter names have a short form for the table, where there is only
room for a few words, and the full name is in the tooltip.

## How the table and the plots line up

The table uses fixed layout with a 190 pixel label column and equal data
columns, so every column is the same width. The plots are drawn in the same
coordinate system: the SVG for a plot is as wide as the data columns and
each point sits in the middle of its column.

That is why the two are built in two passes. The table is built first and
put in the page, and only then is it measured, so that the plots can be
drawn on exactly the same grid. The result is that the points line up with
the numbers to the pixel, which was checked by measuring them in the browser.

## Interaction

| | |
| --- | --- |
| Move the mouse over the table | The column is highlighted, a box shows the values of every parameter that is on screen, and the marker moves through all the plots |
| Click a number, an icon, a time or a day | That column is selected: the cards and the time change, and a banner offers a way back |
| Click the same one again | Back to the current hour |
| The plot under a row | The same parameter, plotted |

The marker in every plot follows the mouse, so a whole column can be read
across all the parameters at once.

## The data behind it

The page gets its data from `/api/forecast`, which returns JSON:

```json
{
  "run": "2026102100",
  "model": "ifs",
  "cycle_utc": "2026-10-21 00:00 UTC",
  "now_step": 12,
  "models": [{"key": "ifs", "label": "IFS 0.1°", "run": "...", "cycle": "..."}],
  "runs": [{"model": "ifs", "run": "...", "steps": 26, "until": "Thu 05 Nov 00:00"}],
  "place_list": [{"id": "gliwice", "name": "Gliwice", "flag": "🇵🇱"}],
  "catalogue": [{"key": "2t", "label": "Temperature", "unit": "K",
                 "group": "temperature", "downloaded": true, "series": ["2t"]}],
  "places": [{
    "id": "gliwice", "name": "Gliwice", "times": ["Wed 02:00", "..."],
    "times_utc": ["Tue 00:00", "..."],
    "steps": [0, 6, 12],
    "series": {
      "2t": {"param": "2t", "label": "Temperature", "short": "Temperature",
             "unit": "degC", "values": [9.7, 9.8, 20.0]}
    }
  }]
}
```

The values in a series are aligned on the step list of the place, so the
table is a straight transpose of the data. The unit is already the display
unit, because `forecast.py` does the conversion once rather than the page
doing it in fifty places.

The static build embeds exactly the same structure, so the page runs the same
way whether it fetches from `/api/forecast` or reads the data it was built
with.

## The icons

The weather icons are pictures generated with a local image model, Z-Image
Turbo, on the machine that runs `ecmwf-make-icons`. They are PNGs with an alpha
channel, so they work on the light and the dark theme.

The map pin and the clock are drawn as SVG instead, because a line drawing is
better for those than a picture.

## The parameter panel

It lists every parameter ECMWF publishes, in groups. The ones that have been
downloaded can be ticked; the ones that have not are greyed out and cannot,
with a note at the bottom saying how many are missing and where to change the
list. So the panel is both a picker and a picture of what the data holds.

Ticking a parameter switches it on everywhere at once: in the cards at the
top, in the chart, in the table and in the box that follows the mouse. The
cards show the parameters that are on, up to twelve, in the same order as
everything else.

## The wind

The wind is stored as the two components, `10u` and `10v`, and the speed and
the direction are worked out from them.

The table has a **Wind (u, v)** row where each column holds an arrow built
from the two components: it points the way the wind blows, its length grows
with the speed, and it is coloured by the Beaufort force.

The rows **Wind speed** and **Wind direction** then give the numbers: the
direction of a column is its degrees, and the speed of a column is the one
of that column.

The arrow is the direction the wind blows **towards**, which is the opposite
of the meteorological direction, where 90 degrees means a wind from the
east.

## The place picker

A combobox. Clicking it selects the current name so that the first
keystroke replaces it, and typing filters the list. The list shows the flag,
the name and the country.

## Responsiveness

One layout for everything. On a phone the header wraps, the cards go two
across, and the table scrolls sideways with the first column stuck in place.
The table and the plots share that scroll container, so they stay in step.

The page is also an installable web app, with a manifest and an icon, so it
can be added to the home screen of a phone.


## Tooltips and selections

Forecast tooltips are off by default. The **Tooltips** checkbox enables or
disables them and remembers the choice in this browser. Hovering still
updates the highlighted hour and summary when tooltips are disabled.

The static bundle carries the data for every run offered by its selector.
Changing a run updates the values as well as the timestamp. Model, run, place
and parameter selections are reflected in the URL; theme, time mode and
parameter visibility are also remembered locally. Deselecting every parameter
shows an empty state with a **Use the default set** button.
