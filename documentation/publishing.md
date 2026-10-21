# Publishing

The page is static. The forecast is written into it, and GitHub Pages
serves it. There is no backend on the other side of the URL.

## How it is published

The repository has a `docs` folder, and GitHub Pages is set to publish it
from the `main` branch. Every push to `main` rebuilds the site.

```
python publish.py
```

which does four things:

1. Runs the service, so anything new on the portal is fetched.
2. Rebuilds `docs/index.html` with the forecast written into it.
3. Writes `docs/latest.json` with the run and the time of the data.
4. Commits and pushes.

The push is the trigger. Pages picks it up, usually within a minute or two.

## The daemon

`auto_publish.py` does the same thing on a schedule:

```bash
python auto_publish.py
```

It waits until a minute after the expected publication time, polls the
portal until the data is there, and then publishes. See
[the workflows](workflows.md) for the options.

## The size of the page

With every parameter of every place the page would be eighteen megabytes,
which is too much to serve comfortably. The build keeps it in check:

- Every parameter for the first 25 places.
- The basic set for the rest.
- All three models.

That comes to about 5 MB, or 1.8 MB compressed, which is what the page
weighs now. `--full-places` and `--max-places` on `build_site.py` change it.

## How much can be kept on GitHub

| | Limit | Where we are |
| --- | --- | --- |
| A published site | 1 GB | 5 MB |
| A single file | 100 MB | 5 MB |
| A repository | 5 GB recommended, 100 GB hard | 22 MB |
| A file in the repository | 100 MB | 5 MB |

The repository is the part that grows. Every commit stores a new copy of the
page, and the page is 5 MB, so each publish adds about 5 MB to `.git`. At
four publishes a day that is 7 GB a year, which would reach the recommended
limit in a couple of years.

There are three ways to keep that in check, in the order I would use them:

1. **Publish less often.** Once a day instead of four times. That is a
   quarter of the growth and the forecast is barely different.
2. **Make the page smaller.** The basic set for every place instead of every
   parameter for the first 25, which takes it from 5 MB to about 1 MB.
3. **Let git compress it.** `git gc --aggressive` packs the loose objects
   into a pack file, and since the pages are nearly identical from one
   commit to the next the delta is small.

## The cache

GitHub Pages serves the page with `cache-control: max-age=600`, so a reader
can see the old page for up to ten minutes after a publish. A hard refresh
clears it. The `?t=` trick that a query string would normally give does not
help here, because the cache in front of the site ignores it.

## The local widget

The static page and the local widget are the same page. The difference is
where the data comes from:

| | The local widget | The published page |
| --- | --- | --- |
| The data | Fetched from `/api/forecast` | Written into the page |
| New data | Within a minute of the service fetching it | At the next publish |
| The places | All of them | All of them, but only the basic set for most |

The published page is the local widget frozen at a moment in time, with the
forecast inside it.
