"""Storage for extracted point forecasts.

Everything lands in a single SQLite file so the widget can read it while the
service is still writing. Values are stored in the SI unit of the GRIB
message; the display conversion happens on the way out.

Schema
------
``runs``
    One row per forecast run, with the ingest status.
``point_values``
    One row per run, place, parameter, level and forecast step.
``places``
    Snapshot of the place definitions used for a run.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import functools
import os
import sqlite3
import threading
from collections.abc import Iterable, Sequence

from .points import Place, PointValue

__all__ = ["ForecastStore", "RunInfo"]

SCHEMA_VERSION = 4


def _synchronized(method):
    """Serialise access to the connection, which is shared between threads."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclasses.dataclass(frozen=True)
class RunInfo:
    """Metadata about an ingested forecast run."""

    model: str
    run: str
    cycle: str
    time: str
    resol: str
    status: str
    ingested_at: str
    updated_at: str
    label: str = ""


class ForecastStore:
    """SQLite backed store of point forecasts.

    Safe to use from several threads: the widget serves requests on worker
    threads while the service writes on its own.
    """

    def __init__(self, path: str | os.PathLike[str]):
        self.path = os.fspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        try:
            self._create_schema()
        except Exception:
            self.connection.rollback()
            self.connection.close()
            raise

    # -- schema ----------------------------------------------------------- #

    @_synchronized
    def _create_schema(self) -> None:
        has_meta = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        if has_meta:
            row = self.connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            version = int(row[0]) if row else 0
            if version not in (3, SCHEMA_VERSION):
                raise ValueError(f"unsupported forecast schema {version}; expected 3 or {SCHEMA_VERSION}")
        self.connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS runs (
                model       TEXT NOT NULL,
                run         TEXT NOT NULL,
                cycle       TEXT NOT NULL,
                time        TEXT NOT NULL,
                label       TEXT,
                resol       TEXT NOT NULL,
                status      TEXT NOT NULL,
                ingested_at TEXT,
                updated_at  TEXT,
                PRIMARY KEY (model, run)
            );

            CREATE TABLE IF NOT EXISTS places (
                model       TEXT NOT NULL,
                run         TEXT NOT NULL,
                place_id    TEXT NOT NULL,
                name        TEXT,
                latitude    REAL,
                longitude   REAL,
                elevation   REAL,
                timezone    TEXT,
                country     TEXT,
                country_code TEXT,
                flag        TEXT,
                note        TEXT,
                PRIMARY KEY (model, run, place_id)
            );

            CREATE TABLE IF NOT EXISTS point_values (
                model    TEXT NOT NULL,
                run      TEXT NOT NULL,
                place_id TEXT NOT NULL,
                param    TEXT NOT NULL,
                level    INTEGER NOT NULL,
                step     INTEGER NOT NULL,
                value    REAL,
                units    TEXT,
                method   TEXT,
                PRIMARY KEY (model, run, place_id, param, level, step)
            );

            CREATE INDEX IF NOT EXISTS point_values_lookup
                ON point_values (model, place_id, param, level, step);
            CREATE INDEX IF NOT EXISTS point_values_run
                ON point_values (model, run);

            CREATE TABLE IF NOT EXISTS ingest_state (
                model TEXT NOT NULL,
                run TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                PRIMARY KEY (model, run)
            );
            CREATE TABLE IF NOT EXISTS ingest_jobs (
                model TEXT NOT NULL,
                run TEXT NOT NULL,
                step INTEGER NOT NULL,
                levtype TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (model, run, step, levtype)
            );
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.connection.commit()

    @contextlib.contextmanager
    def snapshot(self):
        """Keep a reader payload on one SQLite snapshot, including across processes."""
        with self._lock:
            self.connection.execute("BEGIN")
            try:
                yield
            finally:
                self.connection.rollback()

    @_synchronized
    def ingest_fingerprint(self, model: str, run: str) -> str | None:
        row = self.connection.execute(
            "SELECT fingerprint FROM ingest_state WHERE model=? AND run=?", (model, run)
        ).fetchone()
        return row[0] if row else None

    @_synchronized
    def prepare_ingest(self, model: str, run: str, fingerprint: str) -> None:
        """Invalidate incompatible values and checkpoints together on config changes."""
        if self.ingest_fingerprint(model, run) == fingerprint:
            return
        with self.connection:
            for table in ("point_values", "places", "ingest_jobs"):
                self.connection.execute(f"DELETE FROM {table} WHERE model=? AND run=?", (model, run))
            self.connection.execute(
                "INSERT OR REPLACE INTO ingest_state VALUES (?, ?, ?)", (model, run, fingerprint)
            )
            self.connection.execute(
                "UPDATE runs SET status='partial' WHERE model=? AND run=?", (model, run)
            )

    @_synchronized
    def ingest_jobs(self, model: str, run: str) -> dict[tuple[int, str], sqlite3.Row]:
        rows = self.connection.execute(
            "SELECT * FROM ingest_jobs WHERE model=? AND run=?", (model, run)
        ).fetchall()
        return {(row['step'], row['levtype']): row for row in rows}

    @_synchronized
    def finish_job(self, model: str, run: str, step: int, levtype: str,
                   values: Sequence[PointValue], *, status: str,
                   source: str = "", error: str = "") -> int:
        """Commit values and their coverage checkpoint atomically."""
        with self.connection:
            count = self.store_values(run, values, model, _commit=False)
            self.connection.execute(
                "INSERT OR REPLACE INTO ingest_jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (model, run, step, levtype, status, source, error),
            )
        return count

    # -- runs -------------------------------------------------------------- #

    @_synchronized
    def upsert_run(
        self,
        run: str,
        cycle: str,
        time: str,
        model: str = "ifs",
        resol: str = "0p1",
        status: str = "partial",
        label: str = "",
    ) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self.connection.execute(
            """
            INSERT INTO runs (model, run, cycle, time, label, resol, status, ingested_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model, run) DO UPDATE SET
                status     = excluded.status,
                label      = excluded.label,
                updated_at = excluded.updated_at
            """,
            (model, run, cycle, time, label, resol, status, now, now),
        )
        self.connection.commit()

    @_synchronized
    def set_run_status(self, run: str, status: str, model: str = "ifs") -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self.connection.execute(
            "UPDATE runs SET status = ?, updated_at = ? WHERE run = ? AND model = ?",
            (status, now, run, model),
        )
        self.connection.commit()

    @_synchronized
    def run_status(self, run: str, model: str = "ifs") -> str | None:
        row = self.connection.execute(
            "SELECT status FROM runs WHERE run = ? AND model = ?", (run, model)
        ).fetchone()
        return row["status"] if row else None

    @_synchronized
    def known_runs(self, model: str | None = None) -> list[str]:
        if model is None:
            rows = self.connection.execute("SELECT run FROM runs ORDER BY run").fetchall()
        else:
            rows = self.connection.execute(
                "SELECT run FROM runs WHERE model = ? ORDER BY run", (model,)
            ).fetchall()
        return [row["run"] for row in rows]

    @_synchronized
    def runs(self, model: str | None = None) -> list[RunInfo]:
        if model is None:
            rows = self.connection.execute("SELECT * FROM runs ORDER BY model, run").fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM runs WHERE model = ? ORDER BY run", (model,)
            ).fetchall()
        return [RunInfo(**dict(row)) for row in rows]

    @_synchronized
    def latest_run(self, model: str | None = None) -> str | None:
        if model is None:
            row = self.connection.execute(
                "SELECT run FROM runs WHERE status = 'complete' ORDER BY run DESC LIMIT 1"
            ).fetchone()
            if row:
                return row["run"]
            row = self.connection.execute(
                "SELECT run FROM runs ORDER BY run DESC LIMIT 1"
            ).fetchone()
            return row["run"] if row else None
        row = self.connection.execute(
            "SELECT run FROM runs WHERE model = ? AND status = 'complete' ORDER BY run DESC LIMIT 1",
            (model,),
        ).fetchone()
        if row:
            return row["run"]
        row = self.connection.execute(
            "SELECT run FROM runs WHERE model = ? ORDER BY run DESC LIMIT 1", (model,)
        ).fetchone()
        return row["run"] if row else None

    # -- places ------------------------------------------------------------ #

    @_synchronized
    def store_places(self, run: str, places: Sequence[Place], model: str = "ifs") -> None:
        self.connection.executemany(
            """
            INSERT INTO places (model, run, place_id, name, latitude, longitude, elevation,
                                timezone, country, country_code, flag, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model, run, place_id) DO UPDATE SET
                name         = excluded.name,
                latitude     = excluded.latitude,
                longitude    = excluded.longitude,
                elevation    = excluded.elevation,
                timezone     = excluded.timezone,
                country      = excluded.country,
                country_code = excluded.country_code,
                flag         = excluded.flag,
                note         = excluded.note
            """,
            [
                (
                    model,
                    run,
                    place.id,
                    place.name,
                    place.latitude,
                    place.longitude,
                    place.elevation,
                    place.timezone,
                    place.country,
                    place.country_code,
                    place.flag,
                    place.note,
                )
                for place in places
            ],
        )
        self.connection.commit()

    @_synchronized
    def places(self, run: str | None = None, model: str | None = None) -> list[sqlite3.Row]:
        if run is None:
            run = self.latest_run(model)
        if run is None:
            return []
        if model is None:
            return self.connection.execute(
                "SELECT * FROM places WHERE run = ? GROUP BY place_id ORDER BY place_id", (run,)
            ).fetchall()
        return self.connection.execute(
            "SELECT * FROM places WHERE run = ? AND model = ? ORDER BY place_id", (run, model)
        ).fetchall()

    # -- values ------------------------------------------------------------ #

    @_synchronized
    def store_values(
        self,
        run: str,
        values: Iterable[PointValue],
        model: str = "ifs",
        *,
        _commit: bool = True,
    ) -> int:
        rows = [
            (
                model,
                run,
                value.place_id,
                value.param,
                # Surface fields have no level; -1 marks them as such so that
                # the GRIB level (2 m, 10 m, surface) is not mistaken for a
                # pressure level.
                value.level if value.levtype == "pl" and value.level is not None else -1,
                value.step,
                value.value,
                value.units,
                value.method,
            )
            for value in values
        ]
        if not rows:
            return 0
        self.connection.executemany(
            """
            INSERT INTO point_values (model, run, place_id, param, level, step, value, units, method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model, run, place_id, param, level, step) DO UPDATE SET
                value  = excluded.value,
                units  = excluded.units,
                method = excluded.method
            """,
            rows,
        )
        if _commit:
            self.connection.commit()
        return len(rows)

    @_synchronized
    def count_values(self, run: str | None = None, model: str | None = None) -> int:
        if run is None and model is None:
            row = self.connection.execute("SELECT COUNT(*) FROM point_values").fetchone()
        elif model is None:
            row = self.connection.execute(
                "SELECT COUNT(*) FROM point_values WHERE run = ?", (run,)
            ).fetchone()
        elif run is None:
            row = self.connection.execute(
                "SELECT COUNT(*) FROM point_values WHERE model = ?", (model,)
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT COUNT(*) FROM point_values WHERE run = ? AND model = ?", (run, model)
            ).fetchone()
        return int(row[0])

    @_synchronized
    def step_counts(self, place_id: str | None = None) -> dict[tuple[str, str], tuple[int, int]]:
        """How many forecast steps each run holds, and the last one."""
        rows = self.connection.execute(
            "SELECT model, run, COUNT(DISTINCT step) AS count, MAX(step) AS last "
            "FROM point_values " + ("WHERE place_id=? " if place_id else "") + "GROUP BY model, run",
            (place_id,) if place_id else (),
        ).fetchall()
        return {
            (row["model"], row["run"]): (row["count"], row["last"])
            for row in rows
        }

    @_synchronized
    def prune_runs(self, keep: int = 3) -> int:
        """Delete the values of runs that are no longer wanted.

        The newest runs of every model are kept.
        """
        rows = self.connection.execute(
            "SELECT model, run, status FROM runs ORDER BY model, run DESC"
        ).fetchall()
        seen: dict[str, int] = {}
        stale = []
        protected = {}
        for row in rows:
            if row["status"] == "complete":
                protected.setdefault(row["model"], row["run"])
        for row in rows:
            model = row["model"]
            seen[model] = seen.get(model, 0) + 1
            if seen[model] > keep and row["run"] != protected.get(model):
                stale.append((model, row["run"]))
        if not stale:
            return 0
        for model, run in stale:
            self.connection.execute(
                "DELETE FROM point_values WHERE model = ? AND run = ?", (model, run)
            )
            self.connection.execute("DELETE FROM places WHERE model = ? AND run = ?", (model, run))
            self.connection.execute("DELETE FROM runs WHERE model = ? AND run = ?", (model, run))
            self.connection.execute("DELETE FROM ingest_state WHERE model = ? AND run = ?", (model, run))
            self.connection.execute("DELETE FROM ingest_jobs WHERE model = ? AND run = ?", (model, run))
        self.connection.commit()
        return len(stale)

    @_synchronized
    def series(
        self,
        place_id: str,
        param: str,
        *,
        level: int | None = None,
        run: str | None = None,
        model: str | None = None,
    ) -> list[sqlite3.Row]:
        """All stored values for one place and parameter, oldest run first.

        ``level`` of -1 selects the surface fields, a positive value selects
        that pressure level. ``None`` returns every level.
        """
        query = "SELECT * FROM point_values WHERE place_id = ? AND param = ?"
        args: list = [place_id, param]
        if level is not None:
            query += " AND level = ?"
            args.append(level)
        if run is not None:
            query += " AND run = ?"
            args.append(run)
        if model is not None:
            query += " AND model = ?"
            args.append(model)
        query += " ORDER BY run, step"
        return self.connection.execute(query, args).fetchall()

    @_synchronized
    def distinct_params(self, run: str | None = None, model: str | None = None) -> list[tuple[str, int]]:
        query = "SELECT DISTINCT param, level FROM point_values"
        args: list = []
        if run is not None:
            query += " WHERE run = ?"
            args.append(run)
        if model is not None:
            query += (" AND" if run is not None else " WHERE") + " model = ?"
            args.append(model)
        query += " ORDER BY param, level"
        rows = self.connection.execute(query, args).fetchall()
        return [(row["param"], row["level"]) for row in rows]

    # -- export ------------------------------------------------------------ #

    @_synchronized
    def place_values(self, model: str, run: str, place_id: str) -> list[sqlite3.Row]:
        """Fetch a product's entire place forecast in one query."""
        return self.connection.execute(
            "SELECT * FROM point_values WHERE model=? AND run=? AND place_id=? ORDER BY param, level, step",
            (model, run, place_id),
        ).fetchall()

    @_synchronized
    def export_csv(self, path: str | os.PathLike[str]) -> str:
        """Write every value to a CSV file and return its path."""
        rows = self.connection.execute(
            """
            SELECT model, run, place_id, param, level, step, value, units, method
            FROM point_values ORDER BY model, run, place_id, param, level, step
            """
        ).fetchall()
        import csv

        with open(path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["model", "run", "place_id", "param", "level", "step", "value", "units", "method"]
            )
            for row in rows:
                writer.writerow(
                    [
                        row["model"],
                        row["run"],
                        row["place_id"],
                        row["param"],
                        "" if row["level"] < 0 else row["level"],
                        row["step"],
                        row["value"],
                        row["units"],
                        row["method"],
                    ]
                )
        return os.fspath(path)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ForecastStore:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
