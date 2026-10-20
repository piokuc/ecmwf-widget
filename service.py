#!/usr/bin/env python3
"""The service that keeps point forecasts up to date.

It watches ECMWF's open data portal for a new run of each configured model,
downloads the fields it needs, evaluates them at the configured places and
stores the result.

    python service.py once      # one cycle, then exit
    python service.py run       # keep running, checking every poll_interval
    python service.py status    # what has been ingested
    python service.py export    # write a CSV of everything stored
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from dataclasses import dataclass, field

import ecmwf_open_data as eod
import models
import parameters
from config import Config, load_config
from points import PointValue, extract_points
from store import ForecastStore

__all__ = ["IngestReport", "Service"]


@dataclass
class IngestReport:
    """What a single poll did."""

    model: str
    run: str
    steps_ingested: int = 0
    values_stored: int = 0
    bytes_downloaded: int = 0
    errors: list[str] = field(default_factory=list)


class Service:
    """Downloads new ECMWF runs and extracts values at the configured places."""

    def __init__(self, config: Config, store: ForecastStore | None = None):
        self.config = config
        self.store = store or ForecastStore(config.database)
        self.session = eod._session()
        self.places = config.all_places

        surface, pressure, derived = parameters.resolve(config.parameters)
        self.surface_params = surface
        self.pressure_params = pressure
        self.derived_params = derived

        # Which levels are needed for the pressure level parameters.
        self.levels = config.pressure_levels or parameters.PRESSURE_LEVELS

    # -- helpers ----------------------------------------------------------- #

    def _sources(self) -> list[str]:
        return [self.config.source] + [
            source for source in self.config.fallback_sources if source != self.config.source
        ]

    def _download(
        self,
        source: str,
        model: models.Model,
        run: str,
        step: int,
        levtype: str,
        params: list[str],
        levels: list[int] | None,
    ) -> str | None:
        """Download one step, trying the mirrors in order."""
        suffix = "sfc" if levtype in ("sfc", "sol") else "pl"
        for candidate in self._sources():
            try:
                path = eod.download_step(
                    run[:8],
                    run[8:],
                    step,
                    source=candidate,
                    param=params,
                    levelist=levels,
                    levtype=levtype,
                    out=os.path.join(
                        self.config.cache_dir,
                        model.key,
                        run,
                        f"{run}-{step}h-{suffix}.grib2",
                    ),
                    session=self.session,
                    model=model.model,
                    resol=model.resol,
                    stream=model.stream,
                    type=model.type,
                )
            except eod.OpenDataError as exc:
                print(f"  {candidate}: {exc}", file=sys.stderr)
                continue
            if path:
                return path
        return None

    # -- ingestion --------------------------------------------------------- #

    def ingest_run(self, model: models.Model, run: str) -> IngestReport:
        """Download and extract one forecast run of one model."""
        cycle, time = run[:8], run[8:]
        report = IngestReport(model=model.key, run=run)
        self.store.upsert_run(
            run,
            cycle,
            time,
            model=model.key,
            resol=model.resol,
            status="partial",
            label=model.label,
        )
        self.store.store_places(run, self.places, model=model.key)

        jobs: list[tuple[int, str]] = []
        for step in self.config.steps:
            if self.surface_params:
                jobs.append((step, "sfc"))
            if self.pressure_params:
                jobs.append((step, "pl"))

        for step, levtype in jobs:
            params = self.surface_params if levtype == "sfc" else self.pressure_params
            levels = None if levtype == "sfc" else self.levels

            # Some parameters only exist at certain steps, for example the
            # orography at step 0. Ask the index which of the wanted
            # parameters this step actually has before requesting anything.
            try:
                index_url = eod.build_index_url(
                    self.config.source,
                    run[:8],
                    run[8:],
                    step,
                    levtype=levtype,
                    model=model.model,
                    resol=model.resol,
                    stream=model.stream,
                    type=model.type,
                )
                entries = eod.fetch_index(index_url, session=self.session)
            except eod.OpenDataError:
                # The step is not published for this cycle.
                continue
            present = {entry.param for entry in entries}
            wanted = [param for param in params if param in present]
            if not wanted:
                continue

            try:
                path = self._download(
                    self.config.source, model, run, step, levtype, wanted, levels
                )
            except eod.OpenDataError as exc:
                report.errors.append(f"step {step} {levtype}: {exc}")
                continue

            if not path:
                continue

            try:
                values = extract_points(
                    path,
                    self.places,
                    params=wanted,
                    levels=levels,
                    method=self.config.method,
                    levtype=levtype,
                    step=step,
                )
            except Exception as exc:  # noqa: BLE001 - keep the service alive
                report.errors.append(f"step {step} {levtype}: {exc}")
                continue

            values = values + self._derived(values, step)
            report.values_stored += self.store.store_values(run, values, model=model.key)
            report.steps_ingested += 1
            report.bytes_downloaded += os.path.getsize(path)

        status = "complete" if report.steps_ingested >= len(jobs) else "partial"
        self.store.set_run_status(run, status, model=model.key)
        return report

    def _derived(self, values: list[PointValue], step: int) -> list[PointValue]:
        """Compute the derived quantities for one step."""
        # Surface fields are keyed by name only; the GRIB level of a surface
        # field is its height (2 m, 10 m, surface) and not a pressure level.
        surface: dict[str, dict[str, PointValue]] = {}
        pressure: dict[str, dict[tuple[str, int | None], PointValue]] = {}
        for value in values:
            if value.levtype == "pl":
                pressure.setdefault(value.place_id, {})[(value.param, value.level)] = value
            else:
                surface.setdefault(value.place_id, {})[value.param] = value

        result: list[PointValue] = []
        for place_id, fields in surface.items():
            for name in self.derived_params:
                spec = parameters.DERIVED.get(name)
                if spec is None:
                    continue
                try:
                    computed = self._compute_derived(spec, fields, pressure.get(place_id, {}))
                except (KeyError, TypeError, ValueError):
                    continue
                result.extend(computed)
        return result

    @staticmethod
    def _compute_derived(
        spec,
        fields: dict[str, PointValue],
        pressure: dict[tuple[str, int | None], PointValue],
    ):
        """Evaluate one derived quantity from the extracted fields."""
        if spec.name in ("wind_speed", "wind_dir"):
            u = fields["10u"]
            v = fields["10v"]
            value = (
                parameters.wind_speed(u.value, v.value)
                if spec.name == "wind_speed"
                else parameters.wind_direction(u.value, v.value)
            )
            return [
                PointValue(
                    place_id=u.place_id,
                    param=spec.name,
                    level=None,
                    step=u.step,
                    value=value,
                    units=spec.units,
                    method=u.method,
                    levtype="sfc",
                )
            ]

        if spec.name == "gust":
            gust = fields["10fg"]
            return [
                PointValue(
                    place_id=gust.place_id,
                    param=spec.name,
                    level=None,
                    step=gust.step,
                    value=gust.value,
                    units=spec.units,
                    method=gust.method,
                    levtype="sfc",
                )
            ]

        if spec.name == "apparent_temperature":
            t = fields["2t"]
            td = fields["2d"]
            u = fields["10u"]
            v = fields["10v"]
            wind = parameters.wind_speed(u.value, v.value)
            value = parameters.apparent_temperature(t.value, td.value, wind)
            return [
                PointValue(
                    place_id=t.place_id,
                    param=spec.name,
                    level=None,
                    step=t.step,
                    value=value,
                    units=spec.units,
                    method=t.method,
                    levtype="sfc",
                )
            ]

        if spec.name in ("wind_speed_pl", "wind_dir_pl"):
            levels = sorted({level for (param, level) in pressure if param == "u"})
            result = []
            for level in levels:
                u = pressure[("u", level)]
                v = pressure[("v", level)]
                value = (
                    parameters.wind_speed(u.value, v.value)
                    if spec.name == "wind_speed_pl"
                    else parameters.wind_direction(u.value, v.value)
                )
                result.append(
                    PointValue(
                        place_id=u.place_id,
                        param=spec.name,
                        level=level,
                        step=u.step,
                        value=value,
                        units=spec.units,
                        method=u.method,
                        levtype="pl",
                    )
                )
            return result

        return []

    # -- polling ----------------------------------------------------------- #

    def candidate_runs(self, count: int = 12) -> list[str]:
        """Forecast runs that could be available, newest first.

        The 0.1 deg tier is published about two hours after the 0.25 deg tier,
        so the newest run is usually older than the current cycle.
        """
        now = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
        now = now.replace(minute=0, second=0, microsecond=0)
        now -= dt.timedelta(hours=now.hour % 6)
        return [
            (now - dt.timedelta(hours=6 * index)).strftime("%Y%m%d%H")
            for index in range(count)
        ]

    def poll(self) -> list[IngestReport]:
        """Ingest every run that is available and not stored yet."""
        reports: list[IngestReport] = []
        for model in self.config.models:
            candidates = self.candidate_runs()
            incomplete = [
                run
                for run in candidates
                if self.store.run_status(run, model=model.key) not in (None, "complete")
            ]
            # Take the newest runs that are actually published.
            fresh = []
            for run in candidates:
                if self.store.run_status(run, model=model.key) is not None:
                    continue
                if self._published(model, run):
                    fresh.append(run)
                    if len(fresh) >= self.config.backfill_runs:
                        break

            for run in incomplete + fresh:
                if not self._published(model, run):
                    continue

                stamp = dt.datetime.now().strftime("%H:%M:%S")
                print(f"[{stamp}] ingesting {model.label} run {run}")
                report = self.ingest_run(model, run)
                reports.append(report)
                print(
                    f"  {report.steps_ingested} steps, {report.values_stored} values, "
                    f"{report.bytes_downloaded / 1e6:.1f} MB downloaded"
                )
                for error in report.errors:
                    print(f"  error: {error}", file=sys.stderr)

        self.prune_cache()
        self.store.prune_runs(self.config.keep_runs)
        return reports

    def _published(self, model: models.Model, run: str) -> bool:
        """Whether the run of this model is on the portal."""
        try:
            index_url = eod.build_index_url(
                self.config.source,
                run[:8],
                run[8:],
                0,
                levtype="sfc",
                model=model.model,
                resol=model.resol,
                stream=model.stream,
                type=model.type,
            )
            response = self.session.get(index_url, timeout=30)
        except Exception:  # noqa: BLE001 - network hiccup, try the next cycle
            return False
        return response.status_code == 200

    def prune_cache(self, keep_runs: int = 2) -> int:
        """Delete cached GRIB files of runs that are no longer needed.

        The files are only a cache; the extracted values live in the database.
        """
        cache = self.config.cache_dir
        if not os.path.isdir(cache):
            return 0
        removed = 0
        for model in os.listdir(cache):
            model_dir = os.path.join(cache, model)
            if not os.path.isdir(model_dir):
                continue
            runs = sorted(
                (name for name in os.listdir(model_dir) if os.path.isdir(os.path.join(model_dir, name))),
                reverse=True,
            )
            for run in runs[keep_runs:]:
                path = os.path.join(model_dir, run)
                for name in os.listdir(path):
                    try:
                        os.remove(os.path.join(path, name))
                        removed += 1
                    except OSError:
                        continue
                try:
                    os.rmdir(path)
                except OSError:
                    pass
        return removed

    def run_forever(self) -> None:
        """Poll until interrupted."""
        print(
            f"Watching {self.config.source} every {self.config.poll_interval} s for "
            f"{len(self.places)} place(s) and "
            f"{', '.join(model.label for model in self.config.models)}"
        )
        while True:
            try:
                self.poll()
                time.sleep(self.config.poll_interval)
            except KeyboardInterrupt:
                print("interrupted")
                return
            except Exception as exc:  # noqa: BLE001 - never die on a transient error
                print(f"poll failed: {exc}", file=sys.stderr)
                time.sleep(min(self.config.poll_interval, 60))


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="places.yml", help="configuration file")
    common.add_argument("--database", default=None, help="override the database path")

    sub_common = argparse.ArgumentParser(add_help=False)
    sub_common.add_argument("--config", default=argparse.SUPPRESS, help="configuration file")
    sub_common.add_argument("--database", default=argparse.SUPPRESS, help="override the database path")

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("once", help="check for new data once and exit", parents=[sub_common])
    sub.add_parser("run", help="keep checking for new data", parents=[sub_common])
    status = sub.add_parser("status", help="show what has been ingested", parents=[sub_common])
    status.add_argument("--limit", type=int, default=12)
    export = sub.add_parser("export", help="write the stored values to a CSV file", parents=[sub_common])
    export.add_argument("path", nargs="?", default="data/forecast.csv")

    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.database:
        config.database = args.database

    store = ForecastStore(config.database)

    if args.command == "once":
        service = Service(config, store)
        reports = service.poll()
        if not reports:
            print("no new runs available")
        return 0

    if args.command == "run":
        Service(config, store).run_forever()
        return 0

    if args.command == "status":
        runs = store.runs()
        print(f"{len(runs)} run(s) in {config.database}")
        for run in runs[-args.limit :]:
            print(
                f"  {run.model:10s} {run.run}  {run.status:8s}  {run.label or '':12s} "
                f"values={store.count_values(run.run, run.model)}"
            )
        places = store.places()
        if places:
            print(f"places ({len(places)}):")
            for place in places[:20]:
                print(
                    f"  {place['flag'] or '  '} {place['place_id']:20s} {place['name']:20s} "
                    f"{place['latitude']:.4f}, {place['longitude']:.4f}"
                )
            if len(places) > 20:
                print(f"  ... and {len(places) - 20} more")
        return 0

    if args.command == "export":
        path = store.export_csv(args.path)
        print(f"wrote {path}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
