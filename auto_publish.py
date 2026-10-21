#!/usr/bin/env python3
"""Publish on the ECMWF schedule.

This is a thin wrapper; the implementation lives in
``ecmwf_widget/auto_publish``. The ECMWF schedule itself lives in
``ecmwf_widget/scheduler``.

    python auto_publish.py            # wait for each new run, then push
    python auto_publish.py --once     # one cycle, then exit
    python auto_publish.py --dry-run  # do everything except the push
"""

from ecmwf_widget.auto_publish import main

if __name__ == "__main__":
    raise SystemExit(main())
