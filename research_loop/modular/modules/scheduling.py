"""M8: a durable FIFO scheduler for isolated experiment runs.

SQLite is the coordination boundary.  It deliberately stores no scientific
priority: the only runnable-task ordering is monotonically assigned FIFO order.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from research_loop.modular.contracts import FrozenRecord, required_text
from research_loop.ontology import ContractError, canonical, digest


ACTIVE = ("leased",)
TERMINAL = ("merged", "invalidated", "terminated")


@dataclass(frozen=True)
class TaskLease:
    run_id: str
    experiment_id: str
    task_id: str
    attempt: int
    worker_id: str
    lease_until: float
    cost_units: int
    snapshot: FrozenRecord
    dependencies: tuple[str, ...]
    resources: tuple[str, ...]


@dataclass(frozen=True)
class RunState:
    run_id: str
    experiment_id: str
    task_id: str
    attempt: int
    status: str
    snapshot_hash: str
    receipt_id: str | None


def _ids(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ContractError(f"{field} must be a list")
    result = tuple(required_text(item, field) for item in value)
    if len(set(result)) != len(result):
        raise ContractError(f"{field} contains duplicates")
    return result


def _snapshot(value: Mapping[str, Any]) -> FrozenRecord:
    if not isinstance(value, Mapping) or set(value) != {"evidence", "rules", "package"}:
        raise ContractError("snapshot must bind evidence, rules, and package")
    return FrozenRecord.from_dict(dict(value))


class FifoScheduler:
    """SQLite-backed run control; each instance may run in a separate process."""

    def __init__(self, path: Path, *, max_concurrency: int, total_budget: int) -> None:
        if type(max_concurrency) is not int or max_concurrency <= 0 or type(total_budget) is not int or total_budget <= 0:
            raise ContractError("scheduler limits must be positive integers")
        self.path, self.max_concurrency, self.total_budget = Path(path), max_concurrency, total_budget
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS scheduler_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, task_id TEXT NOT NULL, attempt INTEGER NOT NULL,
              fifo INTEGER NOT NULL, status TEXT NOT NULL, worker_id TEXT, lease_until REAL,
              cost_units INTEGER NOT NULL, snapshot TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
              dependencies TEXT NOT NULL, resources TEXT NOT NULL, receipt_id TEXT, receipt TEXT,
              termination_receipt TEXT, invalidation_reason TEXT, parent_run_id TEXT,
              UNIQUE(experiment_id, task_id, attempt), UNIQUE(receipt_id));
            CREATE TABLE IF NOT EXISTS experiments (experiment_id TEXT PRIMARY KEY, snapshot_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), reserved INTEGER NOT NULL);
            INSERT OR IGNORE INTO budget(id, reserved) VALUES(1, 0);
            """)
            existing = conn.execute("SELECT value FROM scheduler_meta WHERE key='limits'").fetchone()
            limits = canonical({"max_concurrency": max_concurrency, "total_budget": total_budget})
            if existing is None:
                conn.execute("INSERT INTO scheduler_meta(key,value) VALUES('limits',?)", (limits,))
            elif existing[0] != limits:
                raise ContractError("existing scheduler database has different hard limits")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def enqueue(self, *, experiment_id: str, task_id: str, dependencies: Sequence[str], resources: Sequence[str],
                cost_units: int, snapshot: Mapping[str, Any]) -> RunState:
        experiment_id, task_id = required_text(experiment_id, "experiment id"), required_text(task_id, "task id")
        dependencies, resources = _ids(dependencies, "dependencies"), _ids(resources, "resources")
        if type(cost_units) is not int or cost_units <= 0:
            raise ContractError("task cost must be a positive integer")
        frozen = _snapshot(snapshot); snap_hash = frozen.content_hash
        run_id = digest({"experiment_id": experiment_id, "task_id": task_id, "attempt": 1})
        with self._tx() as conn:
            row = conn.execute("SELECT snapshot_hash FROM experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO experiments VALUES(?,?)", (experiment_id, snap_hash))
            elif row[0] != snap_hash:
                raise ContractError("all arms of an experiment require the same immutable snapshot")
            fifo = conn.execute("SELECT COALESCE(MAX(fifo),0)+1 FROM runs").fetchone()[0]
            try:
                conn.execute("""INSERT INTO runs(run_id,experiment_id,task_id,attempt,fifo,status,cost_units,snapshot,snapshot_hash,dependencies,resources)
                              VALUES(?,?,?,?,?,'pending',?,?,?,?,?)""",
                             (run_id, experiment_id, task_id, 1, fifo, cost_units, frozen.encoded, snap_hash,
                              canonical(list(dependencies)), canonical(list(resources))))
            except sqlite3.IntegrityError as exc:
                raise ContractError("task already exists; recover creates later attempts") from exc
        return self.state(run_id)

    def claim_next(self, worker_id: str, *, lease_seconds: float) -> TaskLease | None:
        worker_id = required_text(worker_id, "worker id")
        if type(lease_seconds) not in {int, float} or lease_seconds <= 0:
            raise ContractError("lease duration must be positive")
        now = time.time()
        with self._tx() as conn:
            active = conn.execute("SELECT COUNT(*) FROM runs WHERE status='leased'").fetchone()[0]
            if active >= self.max_concurrency:
                return None
            budget = conn.execute("SELECT reserved FROM budget WHERE id=1").fetchone()[0]
            rows = conn.execute("SELECT * FROM runs WHERE status='pending' ORDER BY fifo ASC").fetchall()
            for row in rows:
                deps, locks = tuple(json.loads(row["dependencies"])), tuple(json.loads(row["resources"]))
                if not self._dependencies_ready(conn, row["experiment_id"], deps):
                    continue
                if self._has_lock_conflict(conn, locks):
                    continue
                if budget + row["cost_units"] > self.total_budget:
                    continue
                changed = conn.execute("UPDATE runs SET status='leased',worker_id=?,lease_until=? WHERE run_id=? AND status='pending'",
                                       (worker_id, now + float(lease_seconds), row["run_id"])).rowcount
                if changed != 1:
                    continue
                conn.execute("UPDATE budget SET reserved=reserved+? WHERE id=1", (row["cost_units"],))
                return TaskLease(row["run_id"], row["experiment_id"], row["task_id"], row["attempt"], worker_id,
                                 now + float(lease_seconds), row["cost_units"], FrozenRecord(row["snapshot"]), deps, locks)
        return None

    def expire_leases(self, *, now: float | None = None) -> tuple[str, ...]:
        """A crashed worker is unknown, never silently re-queued."""
        now = time.time() if now is None else now
        with self._tx() as conn:
            rows = conn.execute("SELECT run_id FROM runs WHERE status='leased' AND lease_until < ?", (now,)).fetchall()
            conn.execute("UPDATE runs SET status='unknown',worker_id=NULL,lease_until=NULL WHERE status='leased' AND lease_until < ?", (now,))
            return tuple(row[0] for row in rows)

    def complete(self, run_id: str, *, receipt_id: str, receipt: Mapping[str, Any], cost_units: int) -> RunState:
        run_id, receipt_id = required_text(run_id, "run id"), required_text(receipt_id, "receipt id")
        if type(cost_units) is not int or cost_units <= 0 or not isinstance(receipt, Mapping):
            raise ContractError("completion requires a receipt and positive cost")
        frozen = FrozenRecord.from_dict(dict(receipt))
        with self._tx() as conn:
            row = self._row(conn, run_id)
            if row["status"] != "leased":
                raise ContractError("only a current lease may complete")
            if cost_units != row["cost_units"]:
                raise ContractError("receipt cost must equal the reserved task cost")
            try:
                conn.execute("UPDATE runs SET status='completed_waiting',worker_id=NULL,lease_until=NULL,receipt_id=?,receipt=? WHERE run_id=?",
                             (receipt_id, frozen.encoded, run_id))
            except sqlite3.IntegrityError as exc:
                raise ContractError("receipt already belongs to another run") from exc
        return self.state(run_id)

    def merge(self, experiment_id: str) -> tuple[RunState, ...]:
        """Release a group only when every arm reached the same barrier."""
        experiment_id = required_text(experiment_id, "experiment id")
        with self._tx() as conn:
            rows = conn.execute("""SELECT r.* FROM runs r JOIN
                (SELECT task_id, MAX(attempt) attempt FROM runs WHERE experiment_id=? GROUP BY task_id) current
                ON r.task_id=current.task_id AND r.attempt=current.attempt
                WHERE r.experiment_id=? ORDER BY r.fifo""", (experiment_id, experiment_id)).fetchall()
            if not rows or any(row["status"] != "completed_waiting" for row in rows):
                raise ContractError("merge barrier requires every experiment arm to complete")
            snapshots = {row["snapshot_hash"] for row in rows}
            if len(snapshots) != 1:
                raise ContractError("merge barrier found unequal snapshots")
            conn.executemany("UPDATE runs SET status='merged' WHERE run_id=?", [(row["run_id"],) for row in rows])
        return tuple(self.state(row["run_id"]) for row in rows)

    def confirm_terminated(self, run_id: str, *, termination_receipt: Mapping[str, Any]) -> RunState:
        frozen = FrozenRecord.from_dict(dict(termination_receipt))
        with self._tx() as conn:
            row = self._row(conn, required_text(run_id, "run id"))
            if row["status"] != "unknown":
                raise ContractError("only an unknown run can be confirmed terminated")
            conn.execute("UPDATE runs SET status='terminated',termination_receipt=? WHERE run_id=?", (frozen.encoded, run_id))
        return self.state(run_id)

    def recover(self, run_id: str) -> RunState:
        with self._tx() as conn:
            old = self._row(conn, required_text(run_id, "run id"))
            if old["status"] != "terminated":
                raise ContractError("recovery requires confirmed termination")
            attempt = old["attempt"] + 1
            new_id = digest({"experiment_id": old["experiment_id"], "task_id": old["task_id"], "attempt": attempt})
            fifo = conn.execute("SELECT COALESCE(MAX(fifo),0)+1 FROM runs").fetchone()[0]
            conn.execute("""INSERT INTO runs(run_id,experiment_id,task_id,attempt,fifo,status,cost_units,snapshot,snapshot_hash,dependencies,resources,parent_run_id)
                          VALUES(?,?,?,?,?,'pending',?,?,?,?,?,?)""",
                         (new_id, old["experiment_id"], old["task_id"], attempt, fifo, old["cost_units"], old["snapshot"], old["snapshot_hash"], old["dependencies"], old["resources"], old["run_id"]))
        return self.state(new_id)

    def invalidate(self, experiment_id: str, *, subjects: Sequence[str], reason: str) -> tuple[str, ...]:
        """A new safety event stops related work but never edits frozen snapshots."""
        experiment_id, reason = required_text(experiment_id, "experiment id"), required_text(reason, "invalidation reason")
        subjects = set(_ids(subjects, "subjects"))
        with self._tx() as conn:
            rows = conn.execute("SELECT run_id,resources,status FROM runs WHERE experiment_id=?", (experiment_id,)).fetchall()
            affected = [row["run_id"] for row in rows if set(json.loads(row["resources"])) & subjects and row["status"] not in TERMINAL]
            if affected:
                conn.executemany("UPDATE runs SET status='invalidated',worker_id=NULL,lease_until=NULL,invalidation_reason=? WHERE run_id=?", [(reason, item) for item in affected])
            return tuple(affected)

    def state(self, run_id: str) -> RunState:
        with self._connect() as conn:
            row = self._row(conn, required_text(run_id, "run id"))
            return RunState(row["run_id"], row["experiment_id"], row["task_id"], row["attempt"], row["status"], row["snapshot_hash"], row["receipt_id"])

    def runs(self, experiment_id: str) -> tuple[RunState, ...]:
        with self._connect() as conn:
            return tuple(RunState(row["run_id"], row["experiment_id"], row["task_id"], row["attempt"], row["status"], row["snapshot_hash"], row["receipt_id"])
                         for row in conn.execute("SELECT * FROM runs WHERE experiment_id=? ORDER BY fifo", (experiment_id,)))

    def _tx(self):
        class Tx:
            def __init__(self, outer): self.outer, self.conn = outer, None
            def __enter__(self):
                self.conn = self.outer._connect(); self.conn.execute("BEGIN IMMEDIATE"); return self.conn
            def __exit__(self, kind, value, trace):
                self.conn.execute("ROLLBACK" if kind else "COMMIT"); self.conn.close()
        return Tx(self)

    @staticmethod
    def _row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ContractError("unknown run")
        return row

    @staticmethod
    def _has_lock_conflict(conn: sqlite3.Connection, resources: tuple[str, ...]) -> bool:
        if not resources:
            return False
        for row in conn.execute("SELECT resources FROM runs WHERE status='leased'"):
            if set(resources) & set(json.loads(row["resources"])):
                return True
        return False

    @staticmethod
    def _dependencies_ready(conn: sqlite3.Connection, experiment_id: str, dependencies: tuple[str, ...]) -> bool:
        for task_id in dependencies:
            row = conn.execute("SELECT status FROM runs WHERE experiment_id=? AND task_id=? ORDER BY attempt DESC LIMIT 1", (experiment_id, task_id)).fetchone()
            # Completion is not exposed to another arm: every lease carries its
            # start snapshot.  This permits a true dependency DAG inside a group
            # without making the all-arm merge barrier circular.
            if row is None or row[0] not in {"completed_waiting", "merged"}:
                return False
        return True
