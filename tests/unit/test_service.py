"""The ingesting service, with the network faked away."""

from __future__ import annotations

import datetime as dt
import itertools
import os
import re

import pytest

from ecmwf_widget import ecmwf_open_data as eod
from ecmwf_widget import models, parameters
from ecmwf_widget import service as service_module
from ecmwf_widget.config import Config
from ecmwf_widget.points import Place, PointValue
from ecmwf_widget.service import IngestReport, Service
from ecmwf_widget.store import ForecastStore

PLACE = Place(id="gliwice", name="Gliwice", latitude=50.29, longitude=18.67)
RUN = "2026102100"


def _config(tmp_path, steps=(0, 6), params=("2t", "apparent_temperature")):
    return Config(
        places=[PLACE],
        catalogue=[],
        parameters=list(params),
        pressure_levels=[],
        steps=list(steps),
        models=[models.MODELS["ifs"]],
        source="ecmwf",
        fallback_sources=[],
        poll_interval=900,
        database=str(tmp_path / "forecast.sqlite"),
        cache_dir=str(tmp_path / "grib"),
        path="places.yml",
    )


@pytest.fixture
def store(tmp_path):
    with ForecastStore(tmp_path / "forecast.sqlite") as store:
        yield store


def _fake_value(step, param="2t", value=280.0):
    return PointValue(
        place_id="gliwice", param=param, level=None, step=step,
        value=value, units="K", method="bilinear", levtype="sfc",
    )


# -- construction ------------------------------------------------------------ #

def test_service_resolves_the_parameters(tmp_path):
    config = _config(tmp_path, params=("2t", "wind_speed"))
    service = Service(config)
    assert service.surface_params == ["2t", "10u", "10v"]
    assert service.pressure_params == []
    # the derived quantities are always computed, they cost nothing
    assert "wind_speed" in service.derived_params
    assert "apparent_temperature" in service.derived_params
    assert service.levels == parameters.PRESSURE_LEVELS


def test_service_prepends_the_fallback_sources(tmp_path):
    config = _config(tmp_path)
    config.fallback_sources = ["mirror", "ecmwf"]
    assert Service(config)._sources() == ["ecmwf", "mirror"]


# -- the schedule ------------------------------------------------------------ #

def test_candidate_runs_are_aligned_and_descending():
    runs = Service.__new__(Service).candidate_runs(count=5)  # no state needed
    assert len(runs) == 5
    assert runs == sorted(runs, reverse=True)
    for run in runs:
        assert re.fullmatch(r"\d{10}", run)
        assert int(run[8:]) % 6 == 0

    # they are distinct six hours apart, newest first
    stamps = [dt.datetime.strptime(run, "%Y%m%d%H") for run in runs]
    for first, second in itertools.pairwise(stamps):
        assert first - second == dt.timedelta(hours=6)


def test_candidate_runs_start_two_hours_behind():
    runs = Service.__new__(Service).candidate_runs(count=1)
    newest = dt.datetime.strptime(runs[0], "%Y%m%d%H")
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    # the newest cycle it may consider is two hours old
    assert now - newest >= dt.timedelta(hours=1, minutes=55)
    assert now - newest <= dt.timedelta(hours=8)


# -- derived quantities -------------------------------------------------------- #

def test_derived_wind(tmp_path):
    _config(tmp_path)
    values = [
        _fake_value(6, "10u", 3.0), _fake_value(6, "10v", 4.0),
    ]
    spec = parameters.DERIVED["wind_speed"]
    computed = Service._compute_derived(spec, {v.param: v for v in values}, {})
    value, = computed
    assert value.param == "wind_speed"
    assert value.value == pytest.approx(5.0)
    assert value.step == 6
    assert value.levtype == "sfc"


def test_derived_wind_direction(tmp_path):
    spec = parameters.DERIVED["wind_dir"]
    values = {
        "10u": _fake_value(6, "10u", 0.0), "10v": _fake_value(6, "10v", 10.0),
    }
    computed = Service._compute_derived(spec, values, {})
    assert computed[0].value == pytest.approx(180.0)   # from the south


def test_derived_gust_is_a_copy(tmp_path):
    spec = parameters.DERIVED["gust"]
    values = {"10fg": _fake_value(6, "10fg", 21.5)}
    computed = Service._compute_derived(spec, values, {})
    assert computed[0].param == "gust"
    assert computed[0].value == pytest.approx(21.5)


def test_derived_apparent_temperature(tmp_path):
    spec = parameters.DERIVED["apparent_temperature"]
    values = {
        "2t": _fake_value(6, "2t", 293.15),
        "2d": _fake_value(6, "2d", 288.15),
        "10u": _fake_value(6, "10u", 0.0),
        "10v": _fake_value(6, "10v", 0.0),
    }
    computed = Service._compute_derived(spec, values, {})
    assert computed[0].value == pytest.approx(295.4, abs=1.0)


def test_derived_pressure_level_wind_for_every_level(tmp_path):
    spec = parameters.DERIVED["wind_speed_pl"]
    pressure = {
        ("u", 850): _fake_value(6, "u", 3.0), ("v", 850): _fake_value(6, "v", 4.0),
        ("u", 500): _fake_value(6, "u", 6.0), ("v", 500): _fake_value(6, "v", 8.0),
    }
    computed = Service._compute_derived(spec, {}, pressure)
    assert {entry.level for entry in computed} == {500, 850}
    by_level = {entry.level: entry.value for entry in computed}
    assert by_level[850] == pytest.approx(5.0)
    assert by_level[500] == pytest.approx(10.0)


def test_unknown_derived_name_yields_nothing(tmp_path):
    bogus = type("Spec", (), {"name": "nope", "units": ""})()
    assert Service._compute_derived(bogus, {}, {}) == []


def test_service_derives_what_it_can(tmp_path, store):
    config = _config(tmp_path, params=("2t", "10u", "10v"))
    service = Service(config, store)
    values = [
        _fake_value(0, "2t"), _fake_value(0, "10u", 1.0), _fake_value(0, "10v", 0.0),
    ]
    derived = service._derived(values, step=0)
    names = {value.param for value in derived}
    assert {"wind_speed", "wind_dir"} <= names


# -- ingest_run with everything faked ------------------------------------------- #

def test_ingest_run_downloads_and_stores(tmp_path, store, monkeypatch):
    config = _config(tmp_path, steps=(0,), params=("2t",))
    service = Service(config, store)
    grib = tmp_path / "grib" / "ifs" / RUN / f"{RUN}-0h-sfc.grib2"
    grib.parent.mkdir(parents=True)
    grib.write_bytes(b"GRIB")

    class Entry:
        def __init__(self, param):
            self.param = param

    def fake_build_index_url(*args, **kwargs):
        return f"https://example/{kwargs.get('step', 0)}"

    def fake_fetch_index(url, session=None):
        # step 0 has the orography question? no: it has 2t, later steps would not
        return [Entry("2t"), Entry("10u")]

    def fake_download(self, source, model, run, step, levtype, params, levels):
        assert run == RUN and levtype == "sfc"
        # only the parameters the index shows on this step are requested
        assert params == ["2t"]
        return str(grib)

    monkeypatch.setattr(service_module.eod, "build_index_url", fake_build_index_url)
    monkeypatch.setattr(service_module.eod, "fetch_index", fake_fetch_index)
    monkeypatch.setattr(Service, "_download", fake_download)
    monkeypatch.setattr(
        service_module, "extract_points", lambda *a, **kw: [_fake_value(0)]
    )

    report = service.ingest_run(models.MODELS["ifs"], RUN)
    assert isinstance(report, IngestReport)
    assert report.model == "ifs"
    assert report.run == RUN
    assert report.steps_ingested == 1
    assert report.values_stored >= 1   # 2t stored, plus its derived rows
    assert report.errors == []
    assert store.run_status(RUN, model="ifs") == "complete"
    assert store.count_values(RUN, model="ifs") >= 1


def test_ingest_run_records_a_partial_status_when_a_step_fails(tmp_path, store, monkeypatch):
    config = _config(tmp_path, steps=(0, 6))
    service = Service(config, store)

    class Entry:
        def __init__(self, param):
            self.param = param

    monkeypatch.setattr(
        service_module.eod, "build_index_url", lambda *a, **kw: "url",
    )
    monkeypatch.setattr(
        service_module.eod, "fetch_index", lambda *a, **kw: [Entry("2t")],
    )

    def fake_download(self, *args, **kwargs):
        raise eod.OpenDataError("portal is down")

    monkeypatch.setattr(Service, "_download", fake_download)

    report = service.ingest_run(models.MODELS["ifs"], RUN)
    assert report.steps_ingested == 0
    assert report.errors
    assert store.run_status(RUN, model="ifs") == "partial"


def test_ingest_run_skips_steps_without_wanted_parameters(tmp_path, store, monkeypatch):
    config = _config(tmp_path, steps=(0,), params=("skt",))
    service = Service(config, store)

    class Entry:
        def __init__(self, param):
            self.param = param

    monkeypatch.setattr(service_module.eod, "build_index_url", lambda *a, **kw: "url")
    monkeypatch.setattr(
        service_module.eod, "fetch_index", lambda *a, **kw: [Entry("2t")],  # skt missing
    )

    def fail_download(self, *args, **kwargs):  # nothing may be downloaded
        raise AssertionError("should not be reached")

    monkeypatch.setattr(Service, "_download", fail_download)
    report = service.ingest_run(models.MODELS["ifs"], RUN)
    assert report.steps_ingested == 0
    assert report.values_stored == 0


# -- poll ---------------------------------------------------------------------- #

def test_poll_does_nothing_when_nothing_is_published(tmp_path, store, monkeypatch):
    config = _config(tmp_path)
    service = Service(config, store)
    monkeypatch.setattr(service, "_published", lambda model, run: False)
    assert service.poll() == []
    assert store.known_runs() == []


def test_poll_ingests_fresh_runs(tmp_path, store, monkeypatch):
    config = _config(tmp_path)
    config.backfill_runs = 1
    service = Service(config, store)
    monkeypatch.setattr(service, "_published", lambda model, run: True)

    def fake_ingest_run(model, run):
        return IngestReport(model=model.key, run=run, values_stored=1)

    monkeypatch.setattr(service, "ingest_run", fake_ingest_run)
    reports = service.poll()
    assert len(reports) == 1
    assert reports[0].values_stored == 1


def test_poll_retries_incomplete_runs(tmp_path, store, monkeypatch):
    config = _config(tmp_path)
    service = Service(config, store)
    store.upsert_run(RUN, RUN[:8], RUN[8:], model="ifs", status="partial")
    monkeypatch.setattr(service, "_published", lambda model, run: True)
    polled = []
    monkeypatch.setattr(
        service, "ingest_run", lambda model, run: polled.append(run) or
        IngestReport(model=model.key, run=run)
    )
    service.poll()
    # the incomplete run is retried first, then the fresh ones follow
    assert polled[0] == RUN


# -- the cache ------------------------------------------------------------------- #

def test_prune_cache_keeps_the_last_run(tmp_path):
    config = _config(tmp_path)
    service = Service(config)
    cache = tmp_path / "grib"
    for run in ("2026102000", "2026102100"):
        directory = cache / "ifs" / run
        directory.mkdir(parents=True)
        (directory / f"{run}-0h-sfc.grib2").write_bytes(b"x")
        (directory / f"{run}-6h-sfc.grib2").write_bytes(b"x")
    model_root = cache / "aifs"
    model_root.mkdir()

    (cache / "stray").write_text("not a directory")   # must be ignored

    assert service.prune_cache(keep_runs=1) == 2
    remaining = sorted(os.listdir(cache / "ifs"))
    assert remaining == ["2026102100"]
    assert (cache / "stray").exists()   # a file that is not a run is untouched


def test_prune_cache_on_a_missing_directory(tmp_path):
    config = _config(tmp_path)
    assert Service(config).prune_cache() == 0


# -- the log -------------------------------------------------------------------- #

def test_stamp_tee_echoes_into_the_log_and_stamps_lines(tmp_path):
    import io

    from ecmwf_widget.service import StampTee

    stream = io.StringIO()
    path = tmp_path / "service.log"
    tee = StampTee(stream, str(path))
    tee.write("ingesting ifs 2026102100\n")
    tee.write("  3 steps, 120 values")
    tee.flush()

    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", lines[0])
    assert "ingesting ifs 2026102100" in lines[0]
    assert "3 steps, 120 values" in lines[1]
    # the stream saw exactly what was written
    assert stream.getvalue() == "ingesting ifs 2026102100\n  3 steps, 120 values"
    # unknown attributes come from the real stream
    assert tee.writable() is True


def test_stamp_tee_holds_an_unfinished_line_until_a_flush(tmp_path):
    import io

    from ecmwf_widget.service import StampTee

    path = tmp_path / "service.log"
    tee = StampTee(io.StringIO(), str(path))
    tee.write("half a line")
    assert path.read_text() == ""       # the line is not finished, so it waits
    tee.flush()
    assert "half a line" in path.read_text()


def test_stamp_tee_uses_the_logs_option_of_the_CLI(tmp_path, monkeypatch, capsys):
    config = _config(tmp_path)
    log = tmp_path / "service.log"

    # `status` reads the store; give it a harmless fake so no network and no real db needed
    class FakeStore:
        def __init__(self, _path):
            pass

        def runs(self):
            return []

        def places(self):
            return []

        def count_values(self, *a, **kw):
            return 0

    monkeypatch.setattr(service_module, "ForecastStore", FakeStore)
    monkeypatch.setattr(service_module, "load_config", lambda *a, **kw: config)

    assert service_module.main(["status", "--log-file", str(log)]) == 0
    text = log.read_text()
    assert "0 run(s)" in text and re.match(r"\d{4}-", text.splitlines()[0])
