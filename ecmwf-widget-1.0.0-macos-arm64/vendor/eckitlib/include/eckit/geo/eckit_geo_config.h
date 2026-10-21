// SPDX-FileCopyrightText: 1996- European Centre for Medium-Range Weather Forecasts (ECMWF)
// SPDX-License-Identifier: Apache-2.0


#pragma once


#define eckit_HAVE_GEO_AREA_SHAPEFILE 0


constexpr bool _to_bool(int x) {
    return x != 0;
}

#define eckit_HAVE_PROJ 1

constexpr bool eckit_HAVE_GEO_CACHING                 = _to_bool(0);
constexpr bool eckit_HAVE_GEO_BITREPRODUCIBLE         = _to_bool(0);
constexpr bool eckit_HAVE_GEO_PROJECTION_PROJ_DEFAULT = _to_bool(0);

constexpr const char* eckit_GEO_CACHE_PATH       = "~/.cache/eckit/geo";
constexpr const char* eckit_GEO_SHARE_URL_PREFIX = "https://sites.ecmwf.int/repository/eckit/geo";

constexpr const char* eckit_GEO_SHARE_AREA       = "~eckit/share/eckit/geo/area.yaml";
constexpr const char* eckit_GEO_SHARE_GRID       = "~eckit/share/eckit/geo/grid.yaml:~eckit/share/eckit/geo/FESOM.yaml:~eckit/share/eckit/geo/ICON-CH.yaml:~eckit/share/eckit/geo/ICON-DWD.yaml:~eckit/share/eckit/geo/ICON-MPIM.yaml:~eckit/share/eckit/geo/ORCA.yaml:~eckit/share/eckit/geo/hydro.yaml";
constexpr const char* eckit_GEO_SHARE_PROJECTION = "~eckit/share/eckit/geo/projection.yaml";
