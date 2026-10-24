"""The SQLite store."""

from __future__ import annotations

import pytest

from ecmwf_widget.points import Place, PointValue
from ecmwf_widget.store import ForecastStore

PLACES = [
    Place(id="gliwice", name="Gliwice", latitude=50.29, longitude=18.67),
    Place(id="sniezka", name="Śnieżka", latitude=50.73617, longitude=15.73972, elevation=1603),
]


def _value(place_id, param="2t", step=0, value=280.0, level=None, levtype="sfc", units="K"):
    return PointValue(
        place_id=place_id,
        param=param,
        level=level,
        step=step,
        value=value,
        units=units,
        method="bilinear",
        levtype=levtype,
    )


@pytest.fixture
def store(tmp_path):
    with ForecastStore(tmp_path / "forecast.sqlite") as store:
        yield store


# -- runs -------------------------------------------------------------------- #

def test_a_fresh_store_is_empty(store):
    assert store.runs() == []
    assert store.run_status("2026102100") is None
    assert store.latest_run() is None
    assert store.count_values() == 0


def test_upsert_run_records_the_run(store):
    store.upsert_run("2026102100", "20261021", "00", model="ifs", status="partial")
    assert store.run_status("2026102100", model="ifs") == "partial"
    runs = store.runs()
    run, = runs
    assert run.run == "2026102100"
    assert run.cycle == "20261021"
    assert run.time == "00"
    assert run.status == "partial"


def test_upsert_run_overwrites_the_status_but_keeps_the_first_ingest(store):
    store.upsert_run("2026102100", "20261021", "00", model="ifs", status="partial")
    first = store.runs()[0].ingested_at
    store.upsert_run("2026102100", "20261021", "00", model="ifs", status="complete")
    run = store.runs()[0]
    assert run.status == "complete"
    assert run.ingested_at == first


def test_latest_run_prefers_a_complete_run(store):
    store.upsert_run("2026102106", "20261021", "06", model="ifs", status="partial")
    store.upsert_run("2026102100", "20261021", "00", model="ifs", status="complete")
    assert store.latest_run() == "2026102100"
    assert store.latest_run("ifs") == "2026102100"
    assert store.latest_run("aifs") is None


def test_known_runs_per_model(store):
    store.upsert_run("2026102100", "20261021", "00", model="ifs")
    store.upsert_run("2026102100", "20261021", "00", model="aifs")
    assert store.known_runs(model="ifs") == ["2026102100"]
    # without a model, one run per model is listed
    assert store.known_runs() == ["2026102100", "2026102100"]


# -- places ------------------------------------------------------------------ #

def test_places_are_snapped_for_a_run(store):
    store.store_places("2026102100", PLACES, model="ifs")
    rows = store.places("2026102100", model="ifs")
    assert [row["place_id"] for row in rows] == ["gliwice", "sniezka"]
    assert rows[1]["elevation"] == 1603


def test_places_default_to_the_latest_run(store):
    store.upsert_run("2026102100", "20261021", "00", model="ifs")
    store.store_places("2026102100", PLACES, model="ifs")
    assert store.places()[0]["place_id"] == "gliwice"


# -- values ------------------------------------------------------------------ #

def test_store_values_round_trip(store):
    store.upsert_run("2026102100", "20261021", "00", model="ifs")
    written = store.store_values(
        "2026102100",
        [_value("gliwice", step=0, value=280.0), _value("gliwice", step=6, value=278.0)],
        model="ifs",
    )
    assert written == 2
    assert store.count_values("2026102100", model="ifs") == 2

    rows = store.series("gliwice", "2t", run="2026102100", model="ifs")
    assert [row["step"] for row in rows] == [0, 6]
    assert rows[1]["value"] == pytest.approx(278.0)
    assert rows[1]["units"] == "K"


def test_surface_values_are_stored_with_level_minus_one(store):
    store.store_values("2026102100", [_value("gliwice", level=None)], model="ifs")
    row = store.series("gliwice", "2t")[0]
    assert row["level"] == -1


def test_pressure_values_keep_their_level(store):
    store.store_values(
        "2026102100",
        [_value("gliwice", param="t", level=850, levtype="pl", step=0)],
        model="ifs",
    )
    rows = store.series("gliwice", "t", level=850)
    assert rows[0]["value"] == pytest.approx(280.0)
    assert store.series("gliwice", "t", level=1000) == []


def test_store_values_overwrites_in_place(store):
    store.store_values("2026102100", [_value("gliwice", value=280.0)], model="ifs")
    store.store_values("2026102100", [_value("gliwice", value=281.5)], model="ifs")
    assert store.count_values() == 1
    assert store.series("gliwice", "2t")[0]["value"] == pytest.approx(281.5)


def test_duplicate_rows_collapse_into_one(store):
    written = store.store_values(
        "2026102100",
        [_value("gliwice", step=0), _value("gliwice", step=0)],
        model="ifs",
    )
    assert written == 2   # both rows were handed over
    assert store.count_values() == 1   # but they are the same primary key


def test_step_counts_and_distinct_params(store):
    store.store_values(
        "2026102100",
        [
            _value("gliwice", step=0),
            _value("gliwice", step=6),
            _value("gliwice", param="msl", step=0, value=101300.0, units="Pa"),
        ],
        model="ifs",
    )
    counts = store.step_counts()
    assert counts[("ifs", "2026102100")] == (2, 6)
    assert ("2t", -1) in store.distinct_params()


def test_store_accepts_several_threads(tmp_path):
    import threading

    with ForecastStore(tmp_path / "forecast.sqlite") as shared:
        def write(model):
            shared.upsert_run("2026102100", "20261021", "00", model=model)
            shared.store_values(
                "2026102100",
                [_value("gliwice", step=6, value=float(len(model)))],
                model=model,
            )

        threads = [threading.Thread(target=write, args=(m,)) for m in ("ifs", "ifs025", "aifs")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert shared.count_values(model="ifs") == 1
        assert shared.run_status("2026102100", model="aifs") == "partial"


# -- pruning and export --------------------------------------------------------#

def test_prune_runs_keeps_the_newest(store):
    for _index, run in enumerate(("2026102000", "2026102006", "2026102012", "2026102018")):
        store.upsert_run(run, run[:8], run[8:], model="ifs")
        store.store_values(run, [_value("gliwice", step=0)], model="ifs")
    assert store.prune_runs(keep=3) == 1
    assert store.known_runs(model="ifs") == ["2026102006", "2026102012", "2026102018"]
    assert store.count_values() == 3
    # pruning again changes nothing
    assert store.prune_runs(keep=3) == 0


def test_prune_runs_keeps_every_model(store):
    for run in ("2026102000", "2026102006", "2026102012", "2026102018"):
        store.upsert_run(run, run[:8], run[8:], model="aifs")
        store.store_values(run, [_value("gliwice")], model="aifs")
    store.prune_runs(keep=3)
    assert len(store.known_runs(model="aifs")) == 3


def test_export_csv(store, tmp_path):
    store.upsert_run("2026102100", "20261021", "00", model="ifs")
    store.store_values(
        "2026102100",
        [
            _value("gliwice", step=0, value=280.0),
            _value("gliwice", param="t", level=850, levtype="pl", step=0, value=275.0),
        ],
        model="ifs",
    )
    path = tmp_path / "forecast.csv"
    assert store.export_csv(str(path)) == str(path)
    lines = path.read_text().strip().splitlines()
    assert lines[0] == (
        "model,run,place_id,param,level,step,value,units,method"
    )
    surface = lines[1].split(",")
    assert surface[:7] == ["ifs", "2026102100", "gliwice", "2t", "", "0", "280.0"]
    pressure = lines[2].split(",")
    assert pressure[:7] == ["ifs", "2026102100", "gliwice", "t", "850", "0", "275.0"]


def test_schema_version_is_recorded(store):
    version = store.connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    assert int(version["value"]) >= 3


def test_existing_database_reopens(tmp_path):
    path = tmp_path / "forecast.sqlite"
    with ForecastStore(path) as first:
        first.upsert_run("2026102100", "20261021", "00", model="ifs")
    with ForecastStore(path) as second:
        assert second.run_status("2026102100", model="ifs") == "partial"


def test_version_three_migration_preserves_data(tmp_path):
    import sqlite3

    path = tmp_path / 'old.sqlite'
    with ForecastStore(path) as store:
        store.upsert_run('2026102100', '20261021', '00', status='complete')
        store.store_values('2026102100', [_value('gliwice')])
    with sqlite3.connect(path) as connection:
        connection.execute('DROP TABLE ingest_jobs')
        connection.execute('DROP TABLE ingest_state')
        connection.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
    with ForecastStore(path) as migrated:
        assert migrated.count_values() == 1
        assert migrated.connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4'
        assert migrated.ingest_jobs('ifs', '2026102100') == {}


def test_newer_schema_is_refused_without_relabeling(tmp_path):
    import sqlite3

    path = tmp_path / 'future.sqlite'
    with ForecastStore(path) as store:
        store.connection.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        store.connection.commit()
    with pytest.raises(ValueError, match='unsupported forecast schema 99'):
        ForecastStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '99'


def test_job_checkpoint_and_values_roll_back_together(store):
    import sqlite3

    store.connection.execute("CREATE TRIGGER fail_job BEFORE INSERT ON ingest_jobs BEGIN SELECT RAISE(ABORT, 'failure'); END")
    store.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        store.finish_job('ifs', '2026102100', 0, 'sfc', [_value('gliwice')], status='complete')
    assert store.count_values() == 0
    assert store.ingest_jobs('ifs', '2026102100') == {}


def test_pruning_protects_last_complete_run(store):
    for run, status in [('2026102100', 'complete'), ('2026102106', 'partial'), ('2026102112', 'partial')]:
        store.upsert_run(run, run[:8], run[8:], status=status)
    store.prune_runs(keep=1)
    assert store.known_runs('ifs') == ['2026102100', '2026102112']
