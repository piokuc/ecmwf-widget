#!/usr/bin/env python3
"""Keep the published page up to date.

This is the publishing daemon: it follows the ECMWF schedule, waits for the
data of each cycle to appear, pulls it into the database, rebuilds the page
with the new forecast and pushes it to the repository. Pushing is what
publishes a new version on GitHub Pages.

    python auto_publish.py            # run it
    python auto_publish.py --dry-run  # do everything except the push
    python auto_publish.py --once     # one cycle, then exit

The schedule comes from :mod:`ecmwf_widget.scheduler`; the delay of the
0.1 degree tier can be changed with ``--delay`` if the timing shifts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import time

from . import build_site
from .config import load_config
from .scheduler import next_expected
from .service import Service
from .store import ForecastStore


def _wait_until(expected: dt.datetime, now=None) -> None:
    """Sleep until a minute after ``expected``, watching the wall clock.

    The wait is taken in short slices and every slice re-reads the clock.
    A plain sleep pauses while the machine sleeps, which can make a daemon
    overshoot its deadline by hours; a deadline checked against the wall
    clock does not, so the daemon recovers within the minute after the
    machine wakes.
    """

    clock = now or (lambda: dt.datetime.now(dt.UTC))
    while True:
        wait = (expected + dt.timedelta(minutes=1) - clock()).total_seconds()
        if wait <= 0:
            return
        time.sleep(min(wait, 60.0))


def run_git(*arguments: str) -> subprocess.CompletedProcess:
    """Run a git command."""
    return subprocess.run(["git", *arguments], capture_output=True, text=True, check=False)


def publish(out_dir: str, config_path: str, dry_run: bool, max_places: int | None) -> bool:
    """Rebuild the page and push it. Returns True when something was pushed."""
    summary = build_site.build(out_dir, config_path, max_places)
    print(f"  built {summary['file']} ({summary['size'] / 1e6:.2f} MB)")

    # The built page is in .gitignore (the GitHub Action builds it too), so
    # it has to be added by force to be a visible change at all.
    built = [
        os.path.join(out_dir, name)
        for name in ("index.html", "latest.json")
        if os.path.exists(os.path.join(out_dir, name))
    ]
    if built:
        run_git("add", "--force", *built)
    status = run_git("status", "--porcelain")
    if not status.stdout.strip():
        print("  nothing changed, no push needed")
        return False

    if dry_run:
        print("  dry run, not committing:")
        print("   " + status.stdout.strip().replace("\n", "\n   "))
        if built:
            run_git("restore", "--staged", *built)
        return False

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    run_git("add", "--all")
    commit = run_git("commit", "-m", f"Update the forecast ({stamp})")
    if commit.returncode != 0:
        print(f"  commit failed: {commit.stderr.strip()}")
        return False
    push = run_git("push")
    if push.returncode != 0:
        print(f"  push failed: {push.stderr.strip()}")
        return False
    print(f"  pushed ({commit.stdout.strip().splitlines()[0] if commit.stdout.strip() else ''})")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="places.yml")
    parser.add_argument("--out", default="docs", help="where the page is written")
    parser.add_argument("--database", help="override the database path")
    parser.add_argument(
        "--delay",
        default="08:40",
        help="how long after the cycle the data is expected, as HH:MM",
    )
    parser.add_argument("--poll", type=int, default=120, help="seconds between tries")
    parser.add_argument("--max-places", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="do everything but push")
    parser.add_argument("--once", action="store_true", help="one cycle, then exit")
    parser.add_argument(
        "--now",
        action="store_true",
        help="do not wait for the expected time, check straight away",
    )
    args = parser.parse_args(argv)

    hours, minutes = (int(part) for part in args.delay.split(":"))
    delay = dt.timedelta(hours=hours, minutes=minutes)

    config = load_config(args.config)
    if args.database:
        config.database = args.database
    store = ForecastStore(config.database)
    service = Service(config, store)

    now = dt.datetime.now(dt.UTC)
    expected = next_expected(now, delay)
    print("ECMWF open data publisher")
    print(f"  database  {config.database}")
    print(f"  page      {args.out}")
    print(f"  next run  {expected.strftime('%Y-%m-%d %H:%M')} UTC "
          f"(cycle + {args.delay})")
    print(f"  polling every {args.poll} s")

    while True:
        # Wait until a minute after the expected time. The wait watches the
        # wall clock in short slices, so a machine that slept does not stay
        # behind for long.
        if not args.now:
            remaining = (
                expected + dt.timedelta(minutes=1) - dt.datetime.now(dt.UTC)
            ).total_seconds()
            if remaining > 0:
                print(f"  waiting {remaining / 60:.0f} min for the run")
                if args.once:
                    return 0
                _wait_until(expected)

        print(f"  {dt.datetime.now(dt.UTC).strftime('%H:%M:%S')} looking for the data")
        while True:
            reports = service.poll()
            fresh = [r for r in reports if r.values_stored]
            if fresh:
                for report in fresh:
                    print(f"  got {report.model} run {report.run}: "
                          f"{report.values_stored} values")
                break
            print(f"  not there yet, trying again in {args.poll} s")
            if args.once:
                return 0
            time.sleep(args.poll)

        publish(args.out, args.config, args.dry_run, args.max_places)

        if args.once:
            return 0
        expected = next_expected(dt.datetime.now(dt.UTC), delay)


if __name__ == "__main__":
    raise SystemExit(main())
