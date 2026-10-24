"""Product isolation, run policy and scientific missing-value contracts."""
from __future__ import annotations

import pytest

from ecmwf_widget.forecast import ForecastReader
from ecmwf_widget.points import Place, PointValue
from ecmwf_widget.store import ForecastStore


@pytest.fixture
def store(tmp_path):
    with ForecastStore(tmp_path / 'forecast.sqlite') as store:
        yield store


def seed(store, run, steps, *, model='ifs', status='complete', value=280, elevation=100):
    store.upsert_run(run, run[:8], run[8:], model=model, status=status)
    store.store_places(run, [Place('p', model, 50, 10, elevation=elevation)], model)
    store.store_values(run, [PointValue('p', '2t', None, step, value, 'K') for step in steps], model)


def test_selects_valid_time_not_density_or_lead_hours(store):
    seed(store, '2026102100', range(0, 55, 3))
    seed(store, '2026102112', [0, 240])
    reader = ForecastReader(store)
    assert reader.widget_payload()['run'] == '2026102112'
    seed(store, '2026102200', [0, 234])  # Shorter lead, later actual end time.
    assert reader.latest_run('ifs') == '2026102200'


def test_complete_run_preferred_and_partial_fallback(store):
    seed(store, '2026102100', [0, 6])
    seed(store, '2026102112', [0, 360], status='partial')
    reader = ForecastReader(store)
    assert reader.latest_run() == '2026102100'
    store.set_run_status('2026102100', 'partial')
    assert reader.latest_run() == '2026102112'


def test_model_values_and_metadata_never_mix(store):
    run = '2026102100'
    seed(store, run, [0, 6], model='ifs', value=280, elevation=100)
    seed(store, run, [0, 6], model='aifs', value=300, elevation=900)
    reader = ForecastReader(store)
    default = reader.place_forecast('p', run)
    other = reader.place_forecast('p', run, 'aifs')
    assert default['model'] == 'ifs'
    assert len(default['series']['2t']['points']) == 2
    assert default['series']['2t']['points'][0]['raw'] == 280
    assert other['series']['2t']['points'][0]['raw'] == 300
    assert other['place']['elevation'] == 900
    assert reader.widget_payload(model='aifs')['places'][0]['name'] == 'aifs'


def test_selection_requires_values_for_requested_place(store):
    seed(store, '2026102100', [0, 6])
    store.upsert_run('2026102112', '20261021', '12', status='complete')
    store.store_values('2026102112', [PointValue('other', '2t', None, 360, 290, 'K')])
    assert ForecastReader(store).widget_payload(place='p')['run'] == '2026102100'


@pytest.mark.parametrize(('totals', 'expected'), [
    ([1, None, 3, 4], [1, None, None, 1]),
    ([0, 3, 1, 2], [0, 3, None, 1]),
    ([None, None], [None, None]),
    ([0, 2, 5], [0, 2, 3]),
])
def test_accumulation_gaps_and_resets(totals, expected):
    points = [dict(step=i * 6, valid=str(i), value=value, raw=value) for i, value in enumerate(totals)]
    result = ForecastReader._increments(points)
    assert [p['value'] for p in result] == expected
    assert result[-1]['interval_end'] == points[-1]['step']


def test_irregular_accumulation_interval_is_explicit():
    result = ForecastReader._increments([dict(step=6, value=2), dict(step=24, value=8)])
    assert result[-1]['value'] == 6
    assert (result[-1]['interval_start'], result[-1]['interval_end']) == (6, 24)


def test_payload_uses_one_value_query_per_place(store):
    seed(store, '2026102100', [0, 6])
    store.store_values('2026102100', [PointValue('p', 'msl', None, 0, 101325, 'Pa')])
    statements = []
    store.connection.set_trace_callback(statements.append)
    ForecastReader(store).widget_payload()
    reads = [q for q in statements if q.startswith('SELECT * FROM point_values')]
    assert len(reads) == 1
    assert 'BEGIN' in statements and 'ROLLBACK' in statements


@pytest.mark.parametrize(('model', 'param', 'raw', 'expected'), [
    ('aifs', 'tcc', 12.43, 12.43), ('ifs', 'tcc', 0.1243, 12.43),
    ('ifs025', 'tcc', 0.5, 50), ('aifs', 'tp', 16.8, 16.8), ('ifs', 'tp', 0.0168, 16.8),
])
def test_legacy_missing_units_use_product_encoding(model, param, raw, expected):
    assert ForecastReader._convert(param, raw, '', model)[0] == pytest.approx(expected)


def test_explicit_grib_units_override_legacy_product_defaults():
    assert ForecastReader._convert('tcc', 0.5, '(0 - 1)', 'aifs')[0] == 50


def test_catalogue_time_zones_override_stale_stored_places(store):
    """The catalogue carries the time zone of a place; the store does not."""

    store.upsert_run('2026102100', '20261021', '00', status='complete')
    store.store_places('2026102100', [Place('p', 'Place', 50, 10, timezone='UTC')], 'ifs')
    store.store_values('2026102100', [PointValue('p', '2t', None, 0, 280, 'K')], 'ifs')
    reader = ForecastReader(store, catalogue=[Place('p', 'Place', 50, 10, timezone='Europe/Warsaw')])
    payload = reader.widget_payload()
    assert payload['places'][0]['timezone'] == 'Europe/Warsaw'
    assert payload['places'][0]['until_utc']
