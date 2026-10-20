#!/usr/bin/env python3
"""Command line downloader for ECMWF's free & open 0.1 deg (~9 km) IFS data.

No API key or registration is required; every request is anonymous.

Examples
--------
List what is in the newest run::

    python download_9km.py --latest --list

Fetch 2 m temperature and mean sea level pressure for the next two days::

    python download_9km.py --latest --param 2t,msl --step 24,48 --levtype sfc

Fetch upper-air wind and temperature on 500 and 850 hPa::

    python download_9km.py --latest --param t,u,v --levelist 500,850 --levtype pl

Fetch a specific run straight from the AWS mirror::

    python download_9km.py --date 20261020 --time 06 --source aws --param tp --step 0,24
"""

from __future__ import annotations

import argparse
import sys

from ecmwf_open_data import (
    ATTRIBUTION,
    SOURCES,
    OpenDataError,
    build_index_url,
    download,
    fetch_index,
    latest_run,
    select_entries,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download ECMWF free & open IFS 0.1 deg (~9 km) forecast data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=ATTRIBUTION,
    )
    run = parser.add_argument_group("run selection")
    run.add_argument("--date", help="forecast run date, YYYYMMDD (default: newest available)")
    run.add_argument("--time", help="forecast run time, 00/06/12/18 (default: newest available)")
    run.add_argument(
        "--latest", action="store_true", help="use the newest published run (the default)"
    )

    field = parser.add_argument_group("field selection")
    field.add_argument("--param", help="comma separated parameter names, e.g. 2t,msl,tp")
    field.add_argument("--levelist", help="comma separated pressure levels, e.g. 500,850")
    field.add_argument(
        "--levtype",
        default="sfc",
        help="sfc (surface), pl (pressure level) or sol (soil); comma separated to fetch several",
    )
    field.add_argument("--step", default="0", help="comma separated forecast steps in hours")

    output = parser.add_argument_group("output")
    output.add_argument("--out", default="data", help="output directory (default: data)")
    output.add_argument(
        "--whole-file",
        action="store_true",
        help="download complete files instead of only the requested fields",
    )
    output.add_argument("--source", default="ecmwf", choices=sorted(SOURCES), help="mirror to use")
    output.add_argument("--max-workers", type=int, default=4, help="parallel downloads")
    output.add_argument("--list", action="store_true", help="list available parameters and exit")

    return parser.parse_args(argv)


def split(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    date, time = args.date, args.time
    try:
        if date is None or time is None:
            date, time = latest_run(args.source)
    except OpenDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    levtypes = split(args.levtype) or ["sfc"]
    steps = [int(s) for s in split(args.step) or ["0"]]
    params = split(args.param)
    levels = split(args.levelist)
    if levels:
        levels = [int(lvl) for lvl in levels]

    print(f"run {date} {time}z  source={args.source}  steps={steps}  levtype={levtypes}")

    if args.list:
        from ecmwf_open_data import _session, authorize_url

        session = _session()
        token_cache: dict[str, str] = {}
        for levtype in levtypes:
            url = build_index_url(args.source, date, time, steps[0], levtype=levtype)
            url = authorize_url(url, args.source, session, token_cache)
            try:
                entries = fetch_index(url, session=session)
            except OpenDataError as exc:
                print(f"  {levtype}: {exc}", file=sys.stderr)
                continue
            selected = select_entries(entries, levtype=[levtype])
            params_available = sorted({e.param for e in selected})
            levels_available = sorted(
                {int(e.levelist) for e in selected if e.levelist and e.levelist.isdigit()}
            )
            total = sum(e.length for e in selected) / 1e6
            print(f"  {levtype}: {len(selected)} messages, {total:.1f} MB total")
            print(f"    params : {' '.join(params_available)}")
            if levels_available:
                print(f"    levels : {' '.join(str(lvl) for lvl in levels_available)}")
        return 0

    paths = download(
        date,
        time,
        step=steps,
        source=args.source,
        param=params,
        levelist=levels,
        levtype=levtypes,
        out=args.out,
        whole_file=args.whole_file,
        max_workers=args.max_workers,
    )

    if not paths:
        print(
            "error: nothing downloaded; check the run, step, parameter and level names",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
