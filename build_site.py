#!/usr/bin/env python3
"""Build the static page that is published on GitHub Pages.

This is a thin wrapper; the implementation lives in ``ecmwf_widget/build_site``.

    python build_site.py                     # write docs/
    python build_site.py --max-places 60     # keep the page small
    python build_site.py --out /tmp/site     # somewhere else
"""

from ecmwf_widget.build_site import main

if __name__ == "__main__":
    raise SystemExit(main())
