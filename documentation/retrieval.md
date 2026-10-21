# The data retriever

How a forecast run is found, fetched, decoded and stored.

## Finding a run

The service does not poll the portal blindly. ECMWF publishes the 0.1° tier
about two hours after the 0.25° tier, which lands roughly eight hours and
forty minutes after the cycle time:

| Cycle | Expected on the portal |
| --- | --- |
| 00 UTC | 08:40 UTC |
| 06 UTC | 14:40 UTC |
| 12 UTC | 20:40 UTC |
| 18 UTC | 02:40 UTC |

`auto_publish.py` works out the next expected time, waits until a minute
after it, and then polls every two minutes until the data is there. The
delay is a setting (`--delay`), because the exact timing is a property of
ECMWF's dissemination and not of this code.

The check itself is one request: does the index file for step 0 of that run
exist? A 200 means it is published.

## Downloading only what is wanted

The files are large. A single step of the 0.1° surface file with every
parameter in it is 84 MB, and a run is 26 of those.

Each file comes with an `index` file next to it, one JSON object per line,
describing a GRIB message and where it sits in the file:

```json
{"param": "2t", "levtype": "sfc", "level": 2, "step": 24,
 "date": 20261020, "time": 120000, "stream": "oper", "type": "fc",
 "_offset": 75283831, "_length": 1378302}
```

The offsets are byte ranges, and HTTP has range requests. So instead of
downloading a file and throwing most of it away, the retriever asks for the
ranges it wants:

```
Range: bytes=75283831-76662132
```

When several fields are wanted the portal can serve them in one request with
a multi range header. The S3, Google Cloud and Azure mirrors do not do
that, they return the whole object instead, so the code sends one range per
request to them.

The result is that fetching 8 fields out of 48 costs about a fifth of the
file, and the download for a run of 26 steps and 90 parameters is 4.6 GB
rather than the 40 GB it would be if every file were taken whole.

## Decoding

The downloaded ranges are complete GRIB messages, so they can be decoded on
their own. `points.py` uses the `eccodes` library, which is the official
ECMWF decoder and comes with the `ecmwf-opendata` package as a dependency.

## Putting a field on a point

The 0.1° grid is a regular latitude and longitude grid, 3600 by 1801 points,
covering the whole globe. The geometry is read from the file itself rather
than assumed, so the same code works for the 0.25° grid.

For a point at 50.294° N, 18.666° E:

1. Work out which grid row and column it falls between.
2. Take the four surrounding grid values.
3. Interpolate between them.

Bilinear interpolation is the default, and nearest neighbour is available
for the cases where the smooth value is not what is wanted.

The grid starts at 180° E, not 0°, which is a detail worth knowing when the
column arithmetic is done by hand.

## Heights that do not match

A 9 km grid cannot resolve a mountain. The forecast for a summit comes from
the surrounding cell, which can be hundreds of metres below the real peak.

The service therefore also reads the orography, which ECMWF publishes as
`z` at step 0, and works out the height of the model cell. The difference
to the real elevation of the place is then used to correct the temperature
with a standard lapse rate, 6.5 K per kilometre by default. The widget
shows both heights, so the correction is never a surprise.

## The ensemble

The AIFS ensemble publishes all fifty perturbed members in one file per
step. The retriever takes the range for the members it wants, extracts each
one at the place, and the service averages them. The spread it stores is
the range between the 10th and the 90th percentile of the members, which is
the usual "likely range" of an ensemble.

## Storing it

Everything lands in one SQLite file, `data/forecast.sqlite`:

| Table | Holds |
| --- | --- |
| `runs` | One row per model and run, with the status and the times |
| `places` | The places a run was evaluated at, with their coordinates |
| `point_values` | One row per model, run, place, parameter, level and step |

The values are stored in the unit the GRIB message used, not in the display
unit, so that nothing is lost and the conversion happens on the way out.

The service keeps the last few runs and prunes the rest, so the database
does not grow without bound. With 153 places, 90 parameters and 26 steps
that is about 3400 values per place per model, or 171 MB for three models and
three runs.

## The mirrors

If the portal does not answer, the same file is tried on AWS, and then on
Google Cloud. The bytes are identical, which is checked by the fact that the
index files agree.
