"""Pure ingest planning and configuration identity, independent of network and storage."""

from __future__ import annotations

import dataclasses
import hashlib
import json

from . import models, parameters
from .config import Config

# Increment when stored scientific transformations change.
DERIVATION_VERSION = 2


@dataclasses.dataclass(frozen=True)
class Job:
    step: int
    levtype: str
    params: tuple[str, ...]
    levels: tuple[int, ...] = ()

    def expected(self, place_ids: list[str]) -> set[tuple[str, str, int | None]]:
        return {(place, param, level) for place in place_ids for param in self.params
                for level in (self.levels if self.levtype == 'pl' else (None,))}


def plan(config: Config, model: models.Model, run: str) -> list[Job]:
    surface, pressure, _ = parameters.resolve(config.parameters)
    steps = sorted(set(config.steps) & set(model.steps(int(run[8:]))))
    jobs = []
    for step in steps:
        for levtype, names, catalogue in (
            ('sfc', surface, parameters.PARAMETERS), ('pl', pressure, parameters.PRESSURE_PARAMETERS)
        ):
            wanted = tuple(name for name in names if model.supports(name, levtype)
                           and (not catalogue[name].step_only or step in catalogue[name].step_only))
            if wanted:
                jobs.append(Job(step, levtype, wanted,
                                tuple(config.pressure_levels or parameters.PRESSURE_LEVELS)
                                if levtype == 'pl' else ()))
    return jobs


def fingerprint(config: Config, model: models.Model) -> str:
    payload = dict(model=dataclasses.asdict(model), places=[dataclasses.asdict(p) for p in config.all_places],
                   parameters=sorted(config.parameters), levels=sorted(config.pressure_levels),
                   steps=sorted(set(config.steps)), method=config.method,
                   derivation_version=DERIVATION_VERSION)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
