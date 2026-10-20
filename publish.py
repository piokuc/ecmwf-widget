#!/usr/bin/env python3
"""Refresh the published page.

Fetches the latest forecast, rebuilds the static page with the data embedded
in it, and pushes it to GitHub. Pushing is what makes GitHub Pages pick the
new page up, so the whole refresh is one command.

    python publish.py                    # fetch, build, commit, push
    python publish.py --no-fetch         # rebuild with what is already stored
    python publish.py --dry-run          # show what would change
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys

import build_site
from config import load_config


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and print it."""
    print("  $ " + " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.stdout.strip():
        print("    " + result.stdout.strip().replace("\n", "\n    "))
    if result.returncode != 0 and check:
        if result.stderr.strip():
            print("    " + result.stderr.strip(), file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(command)}")
    return result


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(["git", *arguments], check=check)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="places.yml")
    parser.add_argument("--out", default="docs")
    parser.add_argument("--no-fetch", action="store_true", help="do not download anything")
    parser.add_argument("--dry-run", action="store_true", help="do not commit or push")
    parser.add_argument("--max-places", type=int, default=None)
    parser.add_argument("--message", default=None, help="commit message")
    args = parser.parse_args(argv)

    load_config(args.config)  # fail early when the configuration is broken

    if not args.no_fetch:
        print("Fetching the latest forecast")
        run([sys.executable, "-u", "service.py", "once", "--config", args.config])

    print("Building the page")
    summary = build_site.build(args.out, args.config, args.max_places)
    print(f"  {summary['file']} ({summary['size'] / 1e6:.2f} MB)")
    for model, places in summary["models"].items():
        print(f"  {model}: {places} places")

    print("Checking the repository")
    status = git("status", "--porcelain", check=False)
    if not status.stdout.strip():
        print("  nothing changed")
        return 0

    if args.dry_run:
        print("Dry run, not committing. Changed files:")
        print(status.stdout)
        return 0

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    message = args.message or f"Update the forecast ({stamp})"

    git("add", "--all")
    git("commit", "-m", message)
    git("push")

    print("Pushed. GitHub Pages will publish the new page in a minute or two.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
