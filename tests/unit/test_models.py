"""The forecast models."""

from __future__ import annotations

import pytest

from ecmwf_widget import models


def test_the_catalogue_has_three_models():
    assert sorted(models.names()) == ["aifs", "ifs", "ifs025"]


def test_high_resolution_is_the_0p1_tier():
    assert models.get("ifs").resol == "0p1"
    assert models.get("ifs").resolution == "0.1° (~9 km)"


def test_the_coarse_tiers_are_0p25():
    assert models.get("ifs025").resol == "0p25"
    assert models.get("aifs").resol == "0p25"


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        models.get("gfs")


def test_resolve_expands_all():
    resolved = models.resolve("all")
    assert [model.key for model in resolved] == list(models.names())
    assert {type(model) for model in resolved} == {models.Model}


def test_resolve_takes_a_list_and_keeps_the_order():
    resolved = models.resolve(["aifs", "ifs"])
    assert [model.key for model in resolved] == ["aifs", "ifs"]


def test_resolve_takes_a_single_string():
    assert [model.key for model in models.resolve("ifs")] == ["ifs"]


def test_model_has_catalogue_and_type():
    for model in models.MODELS.values():
        assert model.model in ("ifs", "aifs-single")
        assert model.stream == "oper"
        assert model.type == "fc"
