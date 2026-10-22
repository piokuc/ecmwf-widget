# Workflows

Every command in the project, what it does and when to use it.

## Setting up

```bash
pip install ecmwf-widget      # the package and its dependencies
pip install -e ".[dev]"       # from a checkout, with the tools of the tests
pip install -e ".[icons]"     # from a checkout, with the icon generator
```

The dependencies are declared in `pyproject.toml` and nowhere else:
`requests`, `PyYAML` and `eccodes`. The service needs `eccodes`, the
official ECMWF decoder; the widget does not, it only reads the database.

Every command has a console script (`ecmwf-service`, `ecmwf-widget`, ...)
and is also a module of the package, so `python -m ecmwf_widget service
once` does the same thing when the scripts are not on the path.

## The configuration

The service reads a configuration file. Without `--config` it looks for
one, in this order:

1. the file named by the `ECMWF_WIDGET_CONFIG` environment variable;
2. `places.yml` in the working directory;
3. `config/places.yml` of a checkout of the repository;
4. the starter configuration that comes with the package.

The configurations of the repository are in [`config/`](../config): one
for the local service and one for the published page.

## The data

```bash
ecmwf-service once      # check for a new run, fetch what is there, stop
ecmwf-service run       # the same, but keep going
ecmwf-service status    # what has been fetched
ecmwf-service export    # write everything to a CSV
```

`once` is the one to use by hand. It does the same work as the daemon but
stops when it is done.

`status` shows every run that has been fetched, with the model, how many
values it holds and the places that are followed.

What the service prints can be kept with `--log-file`: the log file gets a
UTC stamp on every line, and it answers even when the terminal that started
the service is long gone.

```bash
ecmwf-service run --log-file data/service.log
ecmwf-service status --log-file data/service.log   # the option can come after the command
```

**As a service.** On macOS and Linux the ingestor is a user service,
defined in [`deploy/`](deploy). It runs the command above, keeps itself
alive with `Restart` (systemd) or `KeepAlive` (launchd), so a momentary
network failure does not stop the data flow, and it starts again on its
own when the machine does:

```bash
# macOS, launchd
sed -e "s|REPOSITORY|$PWD|" -e "s|PYTHON|$(which python3)|" \
    deploy/com.piokuc.ecmwf-ingestd.plist \
    > ~/Library/LaunchAgents/com.piokuc.ecmwf-ingestd.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.piokuc.ecmwf-ingestd.plist

# Linux, systemd
sed -e "s|REPOSITORY|$PWD|" -e "s|PYTHON|$(which python3)|" \
    deploy/ecmwf-ingestd.service > ~/.config/systemd/user/ecmwf-ingestd.service
systemctl --user daemon-reload && systemctl --user enable --now ecmwf-ingestd
```

The `--log-file` in the service definition is what makes
`data/service.log` the ingestor's log; `data/ingestd.log` holds whatever
came on stderr, a crash traceback included.

## The widget

```bash
ecmwf-widget            # serve on http://localhost:8765
ecmwf-widget --open     # and open a browser
ecmwf-widget --port 9000
ecmwf-widget --text     # print the forecast as text, no server
```

The widget reads the database and never writes to it, so it can run on a
different machine from the service, pointing at a shared database.

## Publishing

The published page is built by a GitHub Action, every four hours, after the
ECMWF cycles. It fetches the forecast, builds the page and deploys it, and
the repository keeps nothing of it.

```bash
gh workflow run pages.yml    # start it by hand
gh run list --workflow=pages.yml
```

To publish from the laptop instead, which puts a copy of the built page into
the history on every publish:

```bash
ecmwf-publish           # fetch, rebuild the page, commit and push
ecmwf-publish --no-fetch
ecmwf-publish --dry-run # show what would change, do not push
```

Either way the page can look stale for up to ten minutes afterwards,
because of the cache in front of GitHub Pages.

## The daemon that keeps it up to date

```bash
ecmwf-publisher      # wait for the next run, then publish it
```

It follows the ECMWF schedule (`ecmwf_widget/scheduler`): it works out when
the next run is due — the cycle time plus the delay of publication — waits
until a minute after that, and polls the portal every two minutes until the
data appears. Then it fetches it, rebuilds the page and pushes.

| Option | What it does |
| --- | --- |
| `--now` | Do not wait, check straight away |
| `--once` | One cycle, then exit |
| `--delay 07:30` | When to expect the data, as hours and minutes after the cycle |
| `--poll 60` | Seconds between tries |
| `--dry-run` | Everything except the push |
| `--max-places 40` | How many places the page holds |
| `--full-places 25` | How many of them get every parameter |

**As a service.** On macOS and Linux the daemon is a user service, defined
in [`deploy/`](deploy):

```bash
# macOS, launchd: one substitution, then load it
sed -e "s|REPOSITORY|$PWD|" -e "s|PYTHON|$(which python3)|" \
    deploy/com.piokuc.ecmwf-publishd.plist \
    > ~/Library/LaunchAgents/com.piokuc.ecmwf-publishd.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.piokuc.ecmwf-publishd.plist

# Linux, systemd
sed -e "s|REPOSITORY|$PWD|" -e "s|PYTHON|$(which python3)|" \
    deploy/ecmwf-publishd.service > ~/.config/systemd/user/ecmwf-publishd.service
systemctl --user daemon-reload && systemctl --user enable --now ecmwf-publishd
```

The daemon logs to `data/publishd.log`, and `launchctl list` (or
`systemctl --user status ecmwf-publishd`) tells whether it is alive.

**The laptop has to be awake.** If it is asleep when the run comes out, the
daemon finds it on the next poll and publishes then. The page is never more
than one run behind, but it will not be exactly on time.

## The packages

The whole thing — the ingestor, the local widget, the site builder and the
publisher, with their dependencies already installed — is built by GitHub
Actions for Linux and macOS:

```bash
gh workflow run package.yml        # or push a tag v*
gh run download                    # • pick "dist-macos-15" or "dist-ubuntu-24.04"
```

Two kinds of artifact come out of every run:

| Artifact | What it is |
| --- | --- |
| `ecmwf_widget-*.whl` | The wheel: installable on any system with `pip install ecmwf_widget-*.whl`; the dependencies are fetched at install time. It brings the `ecmwf-service`, `ecmwf-widget`, `ecmwf-publisher`, `ecmwf-publish`, `ecmwf-build-site`, `ecmwf-build-places` and `ecmwf-download` commands. |
| `ecmwf-widget-<version>-<os>-<arch>.tar.gz` | The portable bundle, per platform. Unpack it anywhere and run from it — a `bin/` of launchers, the dependencies in `vendor/`, the documentation and a starting `places.yml`. Nothing is written outside the directory you run it from. |

```bash
tar -xzf ecmwf-widget-1.1.0-macos-arm64.tar.gz
cd ecmwf-widget-1.1.0-macos-arm64
./bin/ecmwf-service once      # fetch the latest run into ./data
./bin/ecmwf-widget --open     # and look at it
```

The bundle needs a `python3` of 3.10 or newer on the PATH and nothing else.
`scripts/make_bundle.sh` is what assembles it, so the same archive can be
made by hand on your own machine. The packages are checked in the workflow
before they are uploaded: the test suite runs on both platforms, the wheel
is installed into a fresh environment and asked a question, and the bundle
itself answers a command before it is packed.

## A one off download

For a single file, without the database or the service:

```bash
ecmwf-download --list                 # what is in the data
ecmwf-download --param 2t,msl --step 24
ecmwf-download --param t --levelist 500,850 --levtype pl
```

## The places

Your own places are in `places.yml`, and there is a catalogue of the world
with every capital, a lot of major cities and some peaks. The catalogue
comes with the package, in `ecmwf_widget/data/world_places.yml`, so it is
there however the package was installed.

```yaml
places:
  - id: sniezka
    name: Śnieżka
    latitude: 50.73617
    longitude: 15.73972
    elevation: 1603
    country: Poland
    country_code: PL
    flag: 🇵🇱
```

Which catalogue places are followed is set in `places.yml` too:

```yaml
catalogue: [region:europe, kind:peak]   # or all, or none, or a list of ids
```

`region:` and `kind:` pick by region or by kind, and plain ids are picked
one by one. The catalogue itself is rebuilt with:

```bash
ecmwf-build-places --fetch     # download the two source lists, then build
ecmwf-build-places             # writes the catalogue of the package
ecmwf-build-places --check     # how well the capitals matched
```

## The parameters

```yaml
parameters: [2t, 2d, msl, 10u, 10v, 10fg, tcc, tp, sf, sd, asn, mucape, z]
pressure_levels: []
backfill_runs: 2
keep_runs: 2
```

Two runs are fetched and kept: the newest one, and the one before it, which
is the 00 or 12 UTC run that reaches all the way to 360 hours. The widget
shows the run that reaches furthest, so the short 06 and 18 UTC runs are not
what ends up on screen.

The `z` is the orography, which the height correction needs. Without it a
summit would get the forecast of the cell below it.

`basic` is the small set the widget normally shows, `all` is every
parameter the 0.1° tier publishes, and a list is a list. The list above is
the interesting ones, all on the surface.

Changing this is easy to see the effect of: the panel in the widget always
lists every parameter ECMWF publishes, and the ones that are not in the list
are greyed out and cannot be ticked, with a note saying how many there are.
So it is clear what a change would bring in, and what it would cost.

The pressure levels are a separate setting, because each level of each
parameter costs another global field: 140 of them at 0.1°.

## The icons

```bash
ecmwf-make-icons                    # everything
ecmwf-make-icons sun rain           # just these two
ecmwf-make-icons --force            # regenerate the ones that exist
ecmwf-make-icons --backend ollama   # through Ollama instead
```

The icons are written into the assets of the package, so they end up in
the wheel and on the published page.

The default backend runs Z-Image-Turbo through PyTorch on the machine's
Metal GPU, about eighty seconds per icon. The Ollama backend needs an
Ollama build with image generation, which the current one does not have.

## The forecast steps

```yaml
steps: [0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72,
        84, 96, 108, 120, 132, 144,
        168, 192, 216, 240, 288, 336, 360]
```

That is 26 steps: every six hours for the first three days, every twelve
hours to a week, then once a day.

Every six hours for the first three days, then every twelve hours to a week,
then once a day. The open data only has those steps, and a step that the
current run does not have is simply skipped.

## Checking the data

The extraction is checked against the 0.25° data of the same run, which
should agree closely, and against the ECMWF charts. The interpolation was
verified by taking the same point from the 0.1° and the 0.25° files: they
agree to 0.03 K over flat ground and 0.25 K in the Beskids, and the
global minimum of the 2 m temperature lands in Antarctica at the same
place in both.

```bash
ecmwf-widget --text       # a quick look at what is stored
ecmwf-service status      # what has been fetched, and how much of it
```

## The logs

Everything the machine is doing is written down somewhere, and every log
answers one particular question:

| Log | Kept by | The question it answers |
| --- | --- | --- |
| `data/service.log` | the `--log-file` of the ingestor | What the ingestor is doing now, and what each run cost: steps, values, megabytes |
| `data/ingestd.log` | launchd or systemd | Did the ingestor crash? stderr and the traceback land here |
| `data/publishd.log` | launchd or systemd | When the publisher will look for a run, what it found, what it pushed |
| `ecmwf-service status` | the database | Which runs are stored, `complete` or `partial`, and how much of each |
| `gh run list --workflow=pages.yml` | GitHub Actions | Did the cloud build run, succeed, how long did it take |
| `latest.json` on the site | the published page | The honest verdict: when was the page last actually rebuilt |
| the commit log of the repository | git | What the publisher pushed, and when |

Two properties make these worth reading. First, both service logs are
stamped with UTC on every line, so a gap in the timestamps is a gap in
the work. Second, the three systems check each other: the database holds
a run that `data/service.log` describes; the publisher's log names a
push that is in the repository's own history; and `latest.json` on the
live site carries the built time of the page one of the two pushed.

If the logs and the site disagree — the database has a run that
`latest.json` does not know about — then the chain is broken and the
`data/publishd.log` tells which piece went missing.

## The tests

```bash
pip install -e ".[dev]"
pytest
```

There is a whole page about them: [The tests](testing.md). The short
version: the schedule, the configuration, the parameters, the store, the
ingester (with the network faked away) and the publishing step (against a
throwaway git repository) are covered by pytest; the published page is
described in a Cucumber feature file and exercised with pytest-bdd against
a served copy of the built bundle.

The hand checks below were done once, about the interpolation itself, and
they stay true:

```text
The same point was taken from the 0.1 degree and the 0.25 degree files of
the same run: they agree to 0.03 K over flat ground and 0.25 K in the
Beskids, and the global minimum of the 2 m temperature lands in Antarctica
at the same place in both.
```
