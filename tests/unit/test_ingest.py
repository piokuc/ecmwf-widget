"""Behavior-level coverage for planning, resumption, failover and derivation."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from ecmwf_widget import ingest, models, parameters
from ecmwf_widget import service as module
from ecmwf_widget.config import Config
from ecmwf_widget.points import Place, PointValue
from ecmwf_widget.service import Service
from ecmwf_widget.store import ForecastStore

RUN = '2026102100'


@pytest.fixture
def setup(tmp_path):
    config = Config([Place('p', 'P', 50, 10)], [], ['2t'], [], [0, 6],
                    [models.get('ifs')], 'ecmwf', ['aws'], 900,
                    str(tmp_path / 'db.sqlite'), str(tmp_path / 'grib'))
    with ForecastStore(config.database) as store:
        yield config, store, Service(config, store)


def fake_transport(monkeypatch, tmp_path, service, *, empty=False):
    calls = []
    path = tmp_path / 'step.grib'
    path.write_bytes(b'GRIB')
    def index(model, run, step, levtype):
        params = parameters.resolve(service.config.parameters)[levtype == 'pl']
        return 'aws', [SimpleNamespace(param=p, levtype=levtype) for p in params]
    def download(source, model, run, step, levtype, params, levels):
        calls.append((step, levtype))
        return str(path)
    def extract(path, places, *, params, levels, method, levtype, step):
        if empty:
            return []
        return [PointValue(place.id, p, level, step, 3 if p in ('u', '10u') else 4, 'm s-1', levtype=levtype)
                for place in places for p in params for level in (levels or [None])]
    monkeypatch.setattr(service, '_index', index)
    monkeypatch.setattr(service, '_download', download)
    monkeypatch.setattr(module, 'extract_points', extract)
    return calls


def test_model_plans_supported_steps_and_fields(setup):
    config, _, _ = setup
    config.steps = [0, 3, 144, 150, 360]
    config.parameters = ['2t', '10fg', 'z']
    ifs = ingest.plan(config, models.get('ifs'), '2026102106')
    assert sorted({job.step for job in ifs}) == [0, 3, 144]
    assert 'z' not in ifs[-1].params
    aifs = ingest.plan(config, models.get('aifs'), '2026102106')
    assert sorted({job.step for job in aifs}) == [0, 144, 150, 360]
    assert all('10fg' not in job.params for job in aifs)


def test_resume_skips_committed_jobs(setup, tmp_path, monkeypatch):
    _, store, service = setup
    calls = fake_transport(monkeypatch, tmp_path, service)
    assert not service.ingest_run(models.get('ifs'), RUN).errors
    assert store.run_status(RUN) == 'complete'
    calls.clear()
    service.ingest_run(models.get('ifs'), RUN)
    assert calls == []
    assert all(job['source'] == 'aws' for job in store.ingest_jobs('ifs', RUN).values())


def test_empty_extraction_is_not_complete(setup, tmp_path, monkeypatch):
    _, store, service = setup
    fake_transport(monkeypatch, tmp_path, service, empty=True)
    report = service.ingest_run(models.get('ifs'), RUN)
    assert report.errors
    assert store.run_status(RUN) == 'partial'


def test_missing_required_field_retries_only_incomplete_job(setup, tmp_path, monkeypatch):
    _, store, service = setup
    calls = fake_transport(monkeypatch, tmp_path, service)
    extract = module.extract_points
    monkeypatch.setattr(module, 'extract_points', lambda *a, **kw: [] if kw['step'] == 6 else extract(*a, **kw))
    service.ingest_run(models.get('ifs'), RUN)
    assert store.run_status(RUN) == 'partial'
    calls.clear()
    monkeypatch.setattr(module, 'extract_points', extract)
    service.ingest_run(models.get('ifs'), RUN)
    assert calls == [(6, 'sfc')]
    assert store.run_status(RUN) == 'complete'


def test_config_change_invalidates_values_and_checkpoints(setup, tmp_path, monkeypatch):
    config, store, service = setup
    calls = fake_transport(monkeypatch, tmp_path, service)
    service.ingest_run(models.get('ifs'), RUN)
    config.places = [dataclasses.replace(config.places[0], id='new')]
    service.places = config.all_places
    calls.clear()
    service.ingest_run(models.get('ifs'), RUN)
    assert len(calls) == 2
    assert not store.series('p', '2t', run=RUN)
    assert store.series('new', '2t', run=RUN)


def test_pressure_derived_inputs_reach_store(setup, tmp_path, monkeypatch):
    config, store, _ = setup
    config.parameters = ['wind_speed_pl', 'wind_dir_pl']
    config.pressure_levels = [500, 850]
    service = Service(config, store)
    fake_transport(monkeypatch, tmp_path, service)
    report = service.ingest_run(models.get('ifs'), RUN)
    assert not report.errors
    for level in config.pressure_levels:
        assert store.series('p', 'wind_speed_pl', run=RUN, level=level)[0]['value'] == 5
        assert store.series('p', 'wind_dir_pl', run=RUN, level=level)


def test_pressure_derivation_keeps_other_levels_when_component_missing(setup):
    config, store, _ = setup
    config.parameters = ['wind_speed_pl']
    service = Service(config, store)
    values = [PointValue('p', 'u', 500, 0, 3, 'm s-1', levtype='pl'),
              PointValue('p', 'u', 850, 0, 3, 'm s-1', levtype='pl'),
              PointValue('p', 'v', 850, 0, 4, 'm s-1', levtype='pl')]
    assert [(v.level, v.value) for v in service._derived(values, 0)] == [(850, 5)]


def test_discovery_uses_mirror_after_primary_failure(setup, monkeypatch):
    _, _, service = setup
    calls = []
    def index(url, **kwargs):
        calls.append(url)
        if 'data.ecmwf.int' in url:
            raise module.eod.OpenDataError('unavailable')
        return [SimpleNamespace(param='2t')]
    monkeypatch.setattr(module.eod, 'fetch_index', index)
    assert service._published(models.get('ifs'), RUN)
    assert len(calls) == 2
    assert service._index(models.get('ifs'), RUN, 6, 'sfc')[0] == 'aws'


def test_exhausted_downloads_report_sources(setup, monkeypatch):
    _, _, service = setup
    monkeypatch.setattr(module.eod, 'download_step', lambda *a, **kw: None)
    with pytest.raises(module.eod.OpenDataError, match=r'ecmwf.*aws'):
        service._download('ecmwf', models.get('ifs'), RUN, 0, 'sfc', ['2t'], None)


def test_empty_plan_remains_partial(setup):
    config, store, service = setup
    config.steps = [999]
    report = service.ingest_run(models.get('ifs'), RUN)
    assert report.errors and store.run_status(RUN) == 'partial'


@pytest.mark.parametrize('levtype', ['sfc', 'pl'])
def test_real_grib_decoding_derives_and_stores_wind(setup, tmp_path, monkeypatch, levtype):
    import eccodes

    config, store, _ = setup
    config.steps = [0]
    config.places = [Place('p', 'P', 0.5, 0.5)]
    config.parameters = ['wind_speed_pl' if levtype == 'pl' else 'wind_speed']
    config.pressure_levels = [850]
    service = Service(config, store)
    path = tmp_path / 'wind.grib2'
    params = ['u', 'v'] if levtype == 'pl' else ['10u', '10v']
    with path.open('wb') as handle:
        for param, value in zip(params, [3, 4], strict=True):
            message = eccodes.codes_grib_new_from_samples(f'regular_ll_{levtype}_grib2')
            try:
                for key, setting in dict(Ni=2, Nj=2, latitudeOfFirstGridPointInDegrees=1,
                                         latitudeOfLastGridPointInDegrees=0,
                                         longitudeOfFirstGridPointInDegrees=0,
                                         longitudeOfLastGridPointInDegrees=1,
                                         iDirectionIncrementInDegrees=1,
                                         jDirectionIncrementInDegrees=1).items():
                    eccodes.codes_set(message, key, setting)
                if levtype == 'pl':
                    eccodes.codes_set(message, 'level', 850)
                eccodes.codes_set(message, 'shortName', param)
                eccodes.codes_set_values(message, [value] * 4)
                eccodes.codes_write(message, handle)
            finally:
                eccodes.codes_release(message)
    monkeypatch.setattr(service, '_index', lambda *a: ('ecmwf', [SimpleNamespace(param=p, levtype=levtype) for p in params]))
    monkeypatch.setattr(service, '_download', lambda *a: str(path))
    report = service.ingest_run(models.get('ifs'), RUN)
    assert not report.errors
    rows = store.series('p', config.parameters[0], run=RUN, model='ifs')
    assert len(rows) == 1
    assert rows[0]['value'] == pytest.approx(5)
    assert rows[0]['units'] == 'm s-1'
    assert store.run_status(RUN) == 'complete'
