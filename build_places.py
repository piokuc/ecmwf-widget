#!/usr/bin/env python3
"""Rebuild the catalogue of world places, ``world_places.yml``.

This is a thin wrapper; the implementation lives in
``ecmwf_widget/build_places``.

    python build_places.py                 # write world_places.yml
"""

from ecmwf_widget.build_places import main

if __name__ == "__main__":
    raise SystemExit(main())
