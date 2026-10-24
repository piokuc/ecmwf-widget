"""The ECMWF models that are available as free and open data.

All of them are published on the same open data portal and are downloaded
without any registration.

``ifs``
    The high resolution deterministic forecast. This is the model the 0.1
    degree tier is made from, and the one to use for detailed forecasts.
``ifs025``
    The same forecast on the coarser 0.25 degree grid. It is published
    sooner, so it is useful while the 0.1 degree tier is still on its way.
``aifs``
    The artificial intelligence forecast, a single deterministic run.
"""

from __future__ import annotations

import dataclasses

__all__ = ["MODELS", "Model", "get", "names", "resolve"]


@dataclasses.dataclass(frozen=True)
class Model:
    """One forecast model in the open data."""

    key: str
    label: str
    short: str
    model: str
    resol: str
    stream: str
    type: str = "fc"
    description: str = ""
    cycles: tuple[int, ...] = (0, 6, 12, 18)
    short_horizon: int = 144
    step_interval: int = 3
    surface_parameters: tuple[str, ...] | None = None
    pressure_parameters: tuple[str, ...] | None = None

    def steps(self, hour: int) -> tuple[int, ...]:
        """Supported lead hours, following ECMWF's open-data product schedule."""
        if hour not in self.cycles:
            return ()
        horizon = 360 if hour in (0, 12) else self.short_horizon
        return tuple(step for step in range(0, horizon + 1, self.step_interval)
                     if step <= 144 or step % 6 == 0)

    def supports(self, param: str, levtype: str) -> bool:
        supported = self.surface_parameters if levtype == "sfc" else self.pressure_parameters
        return supported is None or param in supported

    @property
    def resolution(self) -> str:
        """Human readable resolution."""
        return {"0p1": "0.1° (~9 km)", "0p25": "0.25° (~25 km)"}.get(self.resol, self.resol)


MODELS: dict[str, Model] = {
    m.key: m
    for m in [
        Model(
            key="ifs",
            label="IFS 0.1°",
            short="IFS",
            model="ifs",
            resol="0p1",
            stream="oper",
            type="fc",
            description="High resolution deterministic forecast, about 9 km. Published two hours after the 0.25° tier.",
        ),
        Model(
            key="ifs025",
            label="IFS 0.25°",
            short="IFS 0.25",
            model="ifs",
            resol="0p25",
            stream="oper",
            type="fc",
            description="The same forecast on the 0.25° grid, available sooner.",
        ),
        Model(
            key="aifs",
            short_horizon=360,
            step_interval=6,
            surface_parameters=("z", "sp", "tcw", "msl", "sdor", "slor", "10u", "10v",
                                "2t", "2d", "ssrd", "lsm", "strd", "skt", "lcc", "mcc",
                                "hcc", "cp", "sf", "tcc", "tp", "100u", "100v", "rowe", "fscov"),
            pressure_parameters=("z", "t", "u", "v", "q", "w"),
            label="AIFS",
            short="AIFS",
            model="aifs-single",
            resol="0p25",
            stream="oper",
            type="fc",
            description="Artificial intelligence forecast, a single deterministic run.",
        ),
    ]
}


def get(key: str) -> Model:
    """Look up a model by key."""
    if key not in MODELS:
        raise KeyError(f"unknown model {key!r}, choose from {sorted(MODELS)}")
    return MODELS[key]


def names() -> list[str]:
    """All model keys."""
    return list(MODELS)


def resolve(selection) -> list[Model]:
    """Turn a selection into models, expanding ``all``."""
    if isinstance(selection, str):
        selection = [selection]
    result: list[Model] = []
    for item in selection:
        if item == "all":
            result.extend(MODELS.values())
        else:
            result.append(get(item))
    return list(dict.fromkeys(result))
