#!/usr/bin/env python3
"""The service that keeps point forecasts up to date.

This is a thin wrapper; the implementation lives in ``ecmwf_widget/service``.

    python service.py once      # one cycle, then exit
    python service.py run       # keep running, checking every poll_interval
    python service.py status    # what has been ingested
    python service.py export    # write a CSV of everything stored
"""

from ecmwf_widget.service import main

if __name__ == "__main__":
    raise SystemExit(main())
