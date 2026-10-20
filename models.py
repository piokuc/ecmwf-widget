"""The ECMWF models that are available as free and open data.

All of them are published on the same open data portal and are downloaded
without any registration.

``ifs``
    The high resolution deterministic forecast. This is the model the 0.1
    degree tier is made from, and the one to use for detailed forecasts.
``ifs025``
    The same forecast on the coarser 0.25 degree grid.
``aifs``
    The artificial intelligence forecast, a single deterministic run.
``aifs_ens``
    The artificial intelligence ensemble. The open data publishes all the
    perturbed members in one file, so the spread can be computed.
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
    ensemble: bool = False
    description: str = ""
    #: How many ensemble members to use. Zero means all of them.
    members_limit: int = 0

    @property
    def resolution(self) -> str:
        """Human readable resolution."""
        return "0.1° (~9 km)" if self.resol == "0p1" else "0.25° (~25 km)"

    @property
    def members(self) -> int:
        """Number of ensemble members, 1 for a deterministic model."""
        if not self.ensemble:
            return 1
        return self.members_limit or 50

    def member_numbers(self) -> list[str] | None:
        """The members to download, or None for every member."""
        if not self.ensemble:
            return None
        if not self.members_limit:
            return None
        return [str(number) for number in range(1, self.members_limit + 1)]


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
            label="AIFS",
            short="AIFS",
            model="aifs-single",
            resol="0p25",
            stream="oper",
            type="fc",
            description="Artificial intelligence forecast, a single deterministic run.",
        ),
        Model(
            key="aifs_ens",
            label="AIFS ensemble",
            short="AIFS ens",
            model="aifs-ens",
            resol="0p25",
            stream="enfo",
            type="pf",
            ensemble=True,
            description="Artificial intelligence ensemble with 50 perturbed members, so the spread can be shown.",
            members_limit=8,
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
    return result
