#!/usr/bin/env python3
"""The widget, in a browser or as text.

This is a thin wrapper; the implementation lives in ``ecmwf_widget/widget``.

    python widget.py --open     # serve the widget and open it
    python widget.py --text     # the forecast as text
"""

from ecmwf_widget.widget import main

if __name__ == "__main__":
    raise SystemExit(main())
