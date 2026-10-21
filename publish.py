#!/usr/bin/env python3
"""Refresh the published page: fetch, rebuild, commit and push.

This is a thin wrapper; the implementation lives in ``ecmwf_widget/publish``.

    python publish.py                    # fetch, build, commit, push
    python publish.py --no-fetch         # rebuild with what is already stored
    python publish.py --dry-run          # show what would change
"""

from ecmwf_widget.publish import main

if __name__ == "__main__":
    raise SystemExit(main())
