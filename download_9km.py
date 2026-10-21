#!/usr/bin/env python3
"""Download a single 0.1 degree file, without the database.

This is a thin wrapper; the implementation lives in
``ecmwf_widget/download_9km``.

    python download_9km.py --help
"""

from ecmwf_widget.download_9km import main

if __name__ == "__main__":
    raise SystemExit(main())
