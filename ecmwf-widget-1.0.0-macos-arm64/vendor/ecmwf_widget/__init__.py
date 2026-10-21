"""ECMWF forecast widget.

The package contains every part of the service:

| module               | role                                                |
| -------------------- | --------------------------------------------------- |
| ``parameters``       | the catalogue of published parameters               |
| ``models``           | the forecast models (IFS 0.1°, IFS 0.25°, AIFS)     |
| ``points``           | places, GRIB grids and point extraction             |
| ``ecmwf_open_data``  | the anonymous HTTPS client for the open data portal |
| ``store``            | the SQLite store of extracted values                |
| ``service``          | the ingester: find runs, download, extract, store   |
| ``scheduler``        | the ECMWF publication schedule                      |
| ``auto_publish``     | the daemon that publishes on that schedule          |
| ``publish``          | one-shot fetch, build and push                      |
| ``build_site``       | the static page for GitHub Pages                    |
| ``widget``           | the local widget server and the page itself         |
| ``forecast``         | turning stored values into display structures       |
| ``config``           | ``places.yml`` loading and validation               |
| ``build_places``     | rebuilding ``world_places.yml``                     |
| ``make_icons``       | generating the weather icons                        |
| ``download_9km``     | downloading a single file, without the database     |
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
