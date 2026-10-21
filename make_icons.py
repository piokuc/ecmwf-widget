#!/usr/bin/env python3
"""Generate the weather icons.

This is a thin wrapper; the implementation lives in ``ecmwf_widget/make_icons``.

    python make_icons.py
"""

from ecmwf_widget.make_icons import main

if __name__ == "__main__":
    raise SystemExit(main())
