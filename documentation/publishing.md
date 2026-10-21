# Publishing

The page is static. The forecast is written into it, and GitHub Pages serves
it. There is no backend on the other side of the URL.

## The Action does it

The published page is built in GitHub Actions, not on the laptop:

```
.github/workflows/pages.yml
```

Every four hours it checks out the repository, installs the dependencies,
fetches the newest forecast from ECMWF, builds the page and deploys it to
Pages. The schedule is a quarter past the ECMWF cycles, with an hour and ten
minutes of slack for the 0.1 degree tier to arrive:

| Cycle | The Action runs at |
| --- | --- |
| 00 UTC | 01:50 UTC |
| 06 UTC | 07:50 UTC |
| 12 UTC | 13:50 UTC |
| 18 UTC | 19:50 UTC |

It can also be started by hand from the Actions tab, or with:

```bash
gh workflow run pages.yml
```

**The repository keeps nothing of the page.** The Action builds it into a
temporary folder and deploys that. So the repository no longer grows on
every publish, which it did when the built page was committed: 5.5 MB per
publish is 8 GB a year at four publishes a day.

## The configuration the page is built from

The page is built with `places.pages.yml`, not `places.yml`, so it holds
less than the local service does:

| | The published page | The local service |
| --- | --- | --- |
| Places | 41 | 153 |
| Models | IFS 0.1°, AIFS | IFS 0.1°, IFS 0.25°, AIFS |
| Parameters | 13, surface only | 13, surface only |
| Pressure levels | none | none |
| Downloaded per run | 630 MB | 750 MB |
| Size of the page | 718 KB | 718 KB |

The places are the two in `places.yml` plus a capital or a major city from
each of a list of countries, and the peaks.

The 0.25 degree IFS is left out of the published page: it is the same
forecast as the 0.1 degree one and costs another gigabyte to fetch.

## The local service

The laptop still runs the service, for the local widget:

```bash
python service.py run
```

It follows 153 places, keeps all three models, and prunes the GRIB files
down to the newest run. That cache is about 540 MB with the parameters it
downloads, and the database is about 80 MB for the two runs it keeps.

The pressure levels are not downloaded at the moment, so the whole thing
costs less than a gigabyte a run.

## Publishing by hand

If you would rather not use Actions, `publish.py` does the whole thing
locally: it fetches, builds the page, commits it and pushes. The page is in
`.gitignore`, so it is added to the commit by force.

```bash
python publish.py
python publish.py --no-fetch
python publish.py --dry-run
python publish.py --full-places 60   # more places with every parameter
```

This is the flow that was used before the Action, and it is what puts a
copy of the page into the history on every publish.

## The size limits

| | Limit | Where we are |
| --- | --- | --- |
| A published site | 1 GB | 718 KB |
| A single file | 100 MB | 718 KB |
| A repository | 5 GB recommended, 100 GB hard | 25 MB |
| A file in the repository | 100 MB | 718 KB |

The repository is at 25 MB, and it holds the history of the old approach
with the built page in it. It does not grow any more.

## The cache in front of the site

GitHub Pages serves the page with `cache-control: max-age=600`, so a reader
can see the old page for up to ten minutes after a publish. A hard refresh
clears it. A query string does not help, because the cache in front of the
site ignores it.

## The local widget

The static page and the local widget are the same page. The difference is
where the data comes from:

| | The local widget | The published page |
| --- | --- | --- |
| The data | Fetched from `/api/forecast` | Written into the page |
| New data | Within a minute of the service fetching it | Within four hours, when the Action runs |
| The places | All of them | 41 of them |
| The parameters | All of them | 13 of them |
