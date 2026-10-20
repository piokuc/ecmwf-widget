"""Read the stored forecasts in a shape a widget can render directly.

The service writes raw SI values into SQLite; this module turns them into
tidy, display ready structures: valid times, converted units and a plain text
rendering that is good enough for a first version of the widget.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

import models
import parameters
from points import Place
from store import ForecastStore

__all__ = ["ForecastReader", "local_time", "render_text"]


#: Order the parameters are shown in.
_DISPLAY_ORDER = [
    "temperature_adjusted",
    "apparent_temperature",
    "2t",
    "2d",
    "wind_speed",
    "wind_dir",
    "gust",
    "msl",
    "tp",
    "precip_increment",
    "tcc",
]

#: Overrides for the label of a parameter.
_LABELS = {
    "apparent_temperature": "Feels like",
    "2t": "Temperature",
    "2d": "Dew point",
    "wind_speed": "Wind speed",
    "wind_dir": "Wind direction",
    "gust": "Gusts",
    "msl": "Pressure",
    "tp": "Precipitation (total)",
    "precip_increment": "Precipitation",
    "tcc": "Cloud cover",
}

#: The unit each parameter is displayed in.
_UNITS = {
    "apparent_temperature": "degC",
    "2t": "degC",
    "2d": "degC",
    "wind_speed": "km/h",
    "wind_dir": "deg",
    "gust": "km/h",
    "msl": "hPa",
    "tp": "mm",
    "precip_increment": "mm",
    "tcc": "%",
}

#: Rows that are shown in the header rather than in the table.
_HIDDEN = {"z", "model_elevation"}

#: A raw component is hidden when its derived counterpart is present.
_REDUNDANT = {
    "10u": "wind_speed",
    "10v": "wind_dir",
    "10fg": "gust",
}


def _valid_time(run: str, step: int) -> dt.datetime:
    """Valid time of a forecast step."""
    base = dt.datetime.strptime(run[:8], "%Y%m%d") + dt.timedelta(hours=int(run[8:]))
    return base + dt.timedelta(hours=step)


def local_time(moment: dt.datetime, timezone: str) -> dt.datetime:
    """Convert a UTC moment to the local time of a place."""
    if ZoneInfo is None:
        return moment
    try:
        zone = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001 - an unknown timezone is not fatal
        return moment
    return moment.replace(tzinfo=dt.UTC).astimezone(zone)


def local_label(moment: dt.datetime, timezone: str) -> str:
    """Short local time label, for example ``Sat 08:00``."""
    return local_time(moment, timezone).strftime("%a %H:%M")


def _parameter_catalogue(available: set[str]) -> list[dict]:
    """Describe the parameters that can be switched on and off."""
    catalogue = []
    for key in sorted(available):
        try:
            spec = parameters.get(key)
        except KeyError:
            continue
        catalogue.append(
            {
                "key": key,
                "param": spec.name,
                "label": getattr(spec, "label", key),
                "unit": getattr(spec, "units", ""),
                "group": getattr(spec, "group", ""),
            }
        )
    return catalogue


def _prune_series(series: dict[str, dict]) -> dict[str, dict]:
    """Remove rows that say the same thing as another row.

    The wind components are only interesting when there is no wind speed, and
    the temperature corrected to the real elevation only when it actually
    differs from the temperature of the model grid.
    """
    pruned = dict(series)

    for raw, derived in _REDUNDANT.items():
        if raw in pruned and derived in pruned:
            pruned.pop(raw)

    adjusted = pruned.get("temperature_adjusted")
    plain = pruned.get("2t")
    if adjusted and plain:
        differences = [
            abs(a - b)
            for a, b in zip(adjusted["values"], plain["values"])
            if a is not None and b is not None
        ]
        if differences and max(differences) < 0.2:
            pruned.pop("temperature_adjusted")

    return pruned


class ForecastReader:
    """Convenience access to the forecast store."""

    def __init__(
        self,
        store: ForecastStore,
        lapse_rate: float = parameters.LAPSE_RATE,
        catalogue: Sequence[Place] = (),
    ):
        self.store = store
        self.lapse_rate = lapse_rate
        # Every place that can be chosen, including the ones without data.
        self.catalogue = list(catalogue)

    # -- places ------------------------------------------------------------ #

    def places(self, run: str | None = None) -> list[Place]:
        """The places known for a run."""
        rows = self.store.places(run)
        if not rows and self.catalogue:
            return list(self.catalogue)
        return [
            Place(
                id=row["place_id"],
                name=row["name"] or row["place_id"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                elevation=row["elevation"],
                timezone=row["timezone"] or "UTC",
                country=row["country"] or "",
                country_code=row["country_code"] or "",
                flag=row["flag"] or "",
                note=row["note"] or "",
            )
            for row in rows
        ]

    def latest_run(self, model: str | None = None) -> str | None:
        return self.store.latest_run(model)

    def known_place(self, place_id: str) -> bool:
        """Whether a place can be chosen."""
        if any(item.id == place_id for item in self.places()):
            return True
        return any(item.id == place_id for item in self.catalogue)

    # -- series ------------------------------------------------------------ #

    def series_for_place(
        self,
        place_id: str,
        run: str | None = None,
        params: Sequence[str] | None = None,
        model: str | None = None,
    ) -> dict[str, dict]:
        """All parameters of one place for one run.

        Returns a mapping of parameter name to a dictionary with the label,
        the unit, and the list of steps.
        """
        run = run or self.latest_run(model)
        if run is None:
            return {}

        wanted = list(params) if params else None
        result: dict[str, dict] = {}

        for param, level in self.store.distinct_params(run, model=model):
            if wanted is not None and param not in wanted:
                continue
            key = f"{param}:{level}" if level >= 0 else param

            rows = self.store.series(place_id, param, level=level, run=run, model=model)
            points = []
            for row in rows:
                if row["value"] is None:
                    points.append(
                        {
                            "step": row["step"],
                            "valid": _valid_time(run, row["step"]).isoformat(),
                            "value": None,
                            "raw": None,
                            "spread": row["spread"],
                            "units": "",
                        }
                    )
                    continue
                display_value, display_unit = self._convert(param, row["value"], row["units"])
                points.append(
                    {
                        "step": row["step"],
                        "valid": _valid_time(run, row["step"]).isoformat(),
                        "value": display_value,
                        "raw": row["value"],
                        "spread": row["spread"],
                        "units": display_unit,
                    }
                )
            if not points:
                continue
            points.sort(key=lambda p: p["step"])

            if key in result:
                continue
            result[key] = {
                "param": param,
                "level": level if level >= 0 else None,
                "label": _LABELS.get(param) or parameters.label_for(param, level if level >= 0 else None),
                "units": _UNITS.get(param, points[0]["units"]),
                "points": points,
            }

        # ECMWF publishes precipitation as an accumulation from the start of
        # the run. The per step increment is what a widget usually shows.
        total = result.get("tp")
        if total:
            increment = self._increments(total["points"])
            if increment:
                result["precip_increment"] = {
                    "param": "precip_increment",
                    "level": None,
                    "label": _LABELS["precip_increment"],
                    "units": "mm",
                    "points": increment,
                }

        self._add_model_elevation(result, place_id, run, model)
        return result

    def _add_model_elevation(
        self,
        result: dict[str, dict],
        place_id: str,
        run: str,
        model: str | None,
    ) -> None:
        """Add the height of the model's own terrain and correct for it.

        The model grid is about 9 km across, so for a summit the forecast
        refers to the height of the surrounding cell. The orography (``z`` at
        step 0) gives that height, and the difference to the real elevation
        of the place is used to correct the temperature.
        """
        orography = result.get("z")
        if orography is None:
            return

        model_elevation = None
        for point in orography["points"]:
            if point["raw"] is not None:
                model_elevation = parameters.geopotential_to_height(point["raw"])
                break
        if model_elevation is None:
            return

        result["model_elevation"] = {
            "param": "model_elevation",
            "level": None,
            "label": "Model height",
            "units": "m",
            "points": [
                {
                    "step": orography["points"][0]["step"],
                    "valid": orography["points"][0]["valid"],
                    "value": model_elevation,
                    "raw": model_elevation,
                    "spread": None,
                    "units": "m",
                }
            ],
        }

        place = next((p for p in self.places(run) if p.id == place_id), None)
        temperature = result.get("2t")
        if place is None or place.elevation is None or temperature is None:
            return

        adjusted = []
        for point in temperature["points"]:
            if point["raw"] is None:
                adjusted.append({**point, "value": None})
                continue
            corrected = parameters.lapse_correction(
                point["raw"], place.elevation, model_elevation, self.lapse_rate
            )
            adjusted.append(
                {
                    "step": point["step"],
                    "valid": point["valid"],
                    "value": corrected - 273.15,
                    "raw": corrected,
                    "spread": point.get("spread"),
                    "units": "degC",
                }
            )

        result["temperature_adjusted"] = {
            "param": "temperature_adjusted",
            "level": None,
            "label": "Temperature at height",
            "units": "degC",
            "points": adjusted,
        }

    @staticmethod
    def _convert(param: str, value: float, units: str) -> tuple[float, str]:
        """Convert a stored SI value into the unit used for display."""
        converted, display = parameters.to_display(value, units, param)
        if param in _UNITS:
            display = _UNITS[param]
        return converted, display

    @staticmethod
    def _increments(points: list[dict]) -> list[dict]:
        """Turn an accumulation into per step increments."""
        result = []
        previous = 0.0
        for point in points:
            value = point["value"] or 0.0
            result.append(
                {
                    "step": point["step"],
                    "valid": point["valid"],
                    "value": max(value - previous, 0.0),
                    "raw": point["raw"],
                    "spread": point.get("spread"),
                    "units": "mm",
                }
            )
            previous = value
        return result

    # -- whole places ------------------------------------------------------ #

    def place_forecast(
        self,
        place_id: str,
        run: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Everything a widget needs about one place."""
        run = run or self.latest_run(model)
        places = {place.id: place for place in self.places(run)}
        place = places.get(place_id)
        return {
            "run": run,
            "model": model,
            "cycle": _valid_time(run, 0).isoformat() if run else None,
            "place": {
                "id": place_id,
                "name": place.name if place else place_id,
                "flag": place.flag if place else "",
                "country": place.country if place else "",
                "latitude": place.latitude if place else None,
                "longitude": place.longitude if place else None,
                "elevation": place.elevation if place else None,
                "timezone": place.timezone if place else "UTC",
            },
            "series": self.series_for_place(place_id, run, model=model),
        }

    def all_places(self, run: str | None = None, model: str | None = None) -> list[dict]:
        """The forecast of every place, for a dashboard."""
        run = run or self.latest_run(model)
        return [self.place_forecast(place.id, run, model) for place in self.places(run)]

    # -- the widget payload ------------------------------------------------ #

    def widget_payload(
        self,
        run: str | None = None,
        place: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Everything the widget needs, ready to be serialised as JSON.

        The values of every parameter are aligned on one list of forecast
        steps, so the page can render them as a grid. When ``place`` is given
        only that place is included; the list of all places comes back
        separately so the page can offer a choice.
        """
        now = dt.datetime.now(dt.UTC)

        # The models that have data, and their newest run.
        seen_models: set[str] = set()
        model_list = []
        for info in self.store.runs():
            if info.model in seen_models:
                continue
            seen_models.add(info.model)
            spec = models.MODELS.get(info.model)
            model_list.append(
                {
                    "key": info.model,
                    "label": info.label or (spec.label if spec else info.model),
                    "short": spec.short if spec else info.model,
                    "resolution": spec.resolution if spec else info.resol,
                    "description": spec.description if spec else "",
                    "ensemble": spec.ensemble if spec else False,
                    "members": spec.members if spec else 1,
                    "run": info.run,
                    "cycle": f"{info.cycle[:4]}-{info.cycle[4:6]}-{info.cycle[6:]} {info.time}:00 UTC",
                    "status": info.status,
                }
            )
        model_list.sort(
            key=lambda m: list(models.MODELS).index(m["key"]) if m["key"] in models.MODELS else 99
        )

        if model is None and model_list:
            model = model_list[0]["key"]
        if run is None and model:
            run = self.store.latest_run(model)

        # Every place that can be chosen.
        place_list = []
        seen_places: set[str] = set()
        # The configured order comes first, so the page opens on the place
        # the user cares about most.
        for item in list(self.catalogue) + list(self.places(run)):
            if item.id in seen_places:
                continue
            seen_places.add(item.id)
            place_list.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "country": item.country,
                    "country_code": item.country_code,
                    "flag": item.flag,
                    "kind": item.kind,
                }
            )

        if run is None:
            return {
                "generated": now.isoformat(timespec="seconds"),
                "run": None,
                "model": model,
                "cycle_utc": None,
                "now_step": None,
                "models": model_list,
                "place_list": place_list,
                "params": [],
                "places": [],
            }

        known = self.places(run)
        chosen = [item for item in known if item.id == place] if place else known

        places = []
        steps: list[int] = []
        available: set[str] = set()
        for item in chosen:
            series = self.series_for_place(item.id, run, model=model)
            place_steps = sorted(
                {point["step"] for entry in series.values() for point in entry["points"]}
            )
            steps = place_steps or steps

            model_height = None
            if "model_elevation" in series:
                model_height = series["model_elevation"]["points"][0]["value"]

            payload_series = {}
            for key, entry in series.items():
                # The orography is reported as the model height in the header.
                if key in ("model_elevation", "z"):
                    continue
                by_step = {point["step"]: point["value"] for point in entry["points"]}
                spreads = {point["step"]: point.get("spread") for point in entry["points"]}
                payload_series[key] = {
                    "param": entry["param"],
                    "level": entry["level"],
                    "label": entry["label"],
                    "unit": entry["units"],
                    "values": [by_step.get(step) for step in place_steps],
                    "spreads": [spreads.get(step) for step in place_steps],
                }
                available.add(key)

            payload_series = _prune_series(payload_series)

            timezone = item.timezone or "UTC"
            places.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "flag": item.flag,
                    "country": item.country,
                    "country_code": item.country_code,
                    "latitude": item.latitude,
                    "longitude": item.longitude,
                    "elevation": item.elevation,
                    "model_height": model_height,
                    "timezone": timezone,
                    "note": item.note,
                    "times": [local_label(_valid_time(run, step), timezone) for step in place_steps],
                    "steps": place_steps,
                    "series": payload_series,
                }
            )

        # The forecast step that is closest to now.
        now_step = None
        if steps:
            now_step = min(
                steps, key=lambda step: abs(_valid_time(run, step) - now.replace(tzinfo=None))
            )

        cycle = _valid_time(run, 0)
        return {
            "generated": now.isoformat(timespec="seconds"),
            "run": run,
            "model": model,
            "cycle_utc": cycle.strftime("%Y-%m-%d %H:%M UTC"),
            "now_step": now_step,
            "models": model_list,
            "place_list": place_list,
            "params": _parameter_catalogue(available),
            "places": places,
        }


def _format_value(param: str, value: float | None, units: str) -> str:
    """Format a single value for display."""
    if value is None:
        return "-"
    if param in ("wind_dir",):
        return f"{value:.0f}°"
    if param in ("wind_speed", "gust"):
        return f"{value:.0f} {units}"
    if param == "tp":
        return f"{value:.1f} {units}"
    if param in ("tcc", "hcc", "mcc", "lcc"):
        return f"{value:.0f}%"
    if param == "msl":
        return f"{value:.0f} {units}"
    if units == "degC":
        return f"{value:.1f}°C"
    return f"{value:.1f} {units}"


def render_text(forecast: dict, max_steps: int = 9) -> str:
    """Render a place forecast as plain text."""
    place = forecast["place"]
    series = forecast["series"]
    lines: list[str] = []
    flag = place.get("flag") or ""
    lines.append(f"{flag} {place['name']}  ({place['latitude']:.4f}, {place['longitude']:.4f})")
    if place.get("elevation") is not None:
        height = f"elevation {place['elevation']:.0f} m"
        model_height = series.get("model_elevation")
        if model_height:
            height += f" (model height {model_height['points'][0]['value']:.0f} m)"
        lines.append(height)
    lines.append(f"ECMWF IFS 0.1° run {forecast['run']}  published {forecast['cycle']}")
    lines.append("")

    ordered = [key for key in _DISPLAY_ORDER if key in series]
    # The orography is shown in the header instead of in the table.
    ordered += [
        key for key in sorted(series) if key not in _DISPLAY_ORDER and key not in _HIDDEN
    ]
    if not ordered:
        return "\n".join(lines) + "\n(no data)"

    steps = sorted({point["step"] for key in ordered for point in series[key]["points"]})
    steps = steps[:max_steps]

    label_width = max(len(series[key]["label"]) for key in ordered)
    header = "  ".join(f"{_valid_time(forecast['run'], step).strftime('%d %H%M'):>9s}" for step in steps)
    lines.append(f"{'':>{label_width}}  {header}")

    for key in ordered:
        entry = series[key]
        cells = []
        for step in steps:
            match = next((p for p in entry["points"] if p["step"] == step), None)
            cells.append(
                f"{_format_value(entry['param'], match['value'], match['units']):>9s}"
                if match
                else f"{'-':>9s}"
            )
        lines.append(f"{entry['label']:>{label_width}}  " + "  ".join(cells))

    lines.append("")
    lines.append("Generated using ECMWF free and open data (CC-BY-4.0).")
    return "\n".join(lines)
