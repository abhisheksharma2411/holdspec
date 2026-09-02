"""Recording conformance runs so results outlive the process that produced them.

Every run and every violation is written to Postgres when one is reachable --
`docker compose up` brings one -- and to a local SQLite file otherwise, so the
reproduction path does not require Docker. The schema is the same either way, so
a query written against one works against the other.

The point is the defect corpus: a violation is stored with the exact call
sequence that produced it, which is what makes it re-runnable rather than a line
in a log.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

REPO = Path(__file__).resolve().parents[2]
SQLITE_PATH = REPO / "results" / "holdspec.sqlite"

DDL = [
    """
    CREATE TABLE IF NOT EXISTS conformance_run (
        id            {serial},
        started_at    {timestamp},
        profile       TEXT NOT NULL,
        suite         TEXT NOT NULL,
        sut           TEXT NOT NULL,
        transport     TEXT NOT NULL,
        injected_defect TEXT,
        tests         INTEGER NOT NULL,
        api_calls     INTEGER NOT NULL,
        passed        INTEGER NOT NULL,
        failed        INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS violation (
        id          {serial},
        run_id      INTEGER NOT NULL,
        test        TEXT NOT NULL,
        step_index  INTEGER NOT NULL,
        kind        TEXT NOT NULL,
        expected    TEXT NOT NULL,
        actual      TEXT NOT NULL,
        script      TEXT NOT NULL
    )
    """,
]

_PG_TYPES = {"serial": "SERIAL PRIMARY KEY", "timestamp": "TIMESTAMPTZ DEFAULT now()"}
_SQLITE_TYPES = {
    "serial": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "timestamp": "TEXT DEFAULT CURRENT_TIMESTAMP",
}


def _dsn() -> Optional[str]:
    return os.environ.get("HOLDSPEC_DATABASE_URL") or os.environ.get("DATABASE_URL")


class Store:
    """A conformance-run log, backed by Postgres or SQLite."""

    def __init__(self, conn, dialect: str):
        self.conn = conn
        self.dialect = dialect
        self._ph = "%s" if dialect == "postgres" else "?"
        types = _PG_TYPES if dialect == "postgres" else _SQLITE_TYPES
        cur = conn.cursor()
        for stmt in DDL:
            cur.execute(stmt.format(**types))
        conn.commit()

    def record(self, report, transport: str, injected_defect: str = "") -> int:
        cur = self.conn.cursor()
        ph = self._ph
        sql = (
            f"INSERT INTO conformance_run "
            f"(profile, suite, sut, transport, injected_defect, tests, api_calls, passed, failed) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})"
        )
        values = (
            report.profile, report.suite, report.sut, transport,
            injected_defect or None, report.tests, report.api_calls,
            report.passed, report.failed,
        )
        if self.dialect == "postgres":
            cur.execute(sql + " RETURNING id", values)
            run_id = cur.fetchone()[0]
        else:
            cur.execute(sql, values)
            run_id = cur.lastrowid

        for v in report.violations:
            cur.execute(
                f"INSERT INTO violation (run_id, test, step_index, kind, expected, actual, script) "
                f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                (run_id, v.test, v.step, v.kind, v.expected, v.actual, v.script()),
            )
        self.conn.commit()
        return run_id

    def defect_corpus(self) -> list:
        """Every recorded violation, with the sequence that reproduces it."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT r.profile, r.transport, r.injected_defect, v.kind, v.expected, "
            "v.actual, v.script FROM violation v JOIN conformance_run r ON r.id = v.run_id "
            "ORDER BY v.id"
        )
        cols = ["profile", "transport", "injected_defect", "kind", "expected", "actual", "script"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


@contextmanager
def open_store() -> Iterator[Store]:
    """Postgres when one is configured and reachable, SQLite otherwise."""
    dsn = _dsn()
    if dsn:
        try:
            import psycopg  # type: ignore

            with psycopg.connect(dsn) as conn:
                yield Store(conn, "postgres")
                return
        except Exception as exc:  # pragma: no cover - depends on the environment
            print(f"  (postgres unavailable: {exc}; falling back to sqlite)")
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    try:
        yield Store(conn, "sqlite")
    finally:
        conn.close()


def export_corpus(path: Path) -> int:
    with open_store() as store:
        rows = store.defect_corpus()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n")
    return len(rows)
