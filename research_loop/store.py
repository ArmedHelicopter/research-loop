"""SQLite transactions, immutable objects, FIFO queue and a hash-linked journal."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .ontology import ContractError, canonical, digest


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS objects (
                kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY (kind, id));
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS queue (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT UNIQUE NOT NULL,
                state TEXT NOT NULL, run_id TEXT);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL,
                previous TEXT NOT NULL, hash TEXT NOT NULL);
        """)

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def put(self, kind: str, key: str, body: dict[str, Any]) -> None:
        encoded = canonical(body)
        old = self.db.execute("SELECT body FROM objects WHERE kind=? AND id=?", (kind, key)).fetchone()
        if old is not None:
            if old["body"] != encoded:
                raise ContractError("immutable object already exists")
            return
        self.db.execute("INSERT INTO objects VALUES (?,?,?)", (kind, key, encoded))

    def get(self, kind: str, key: str) -> dict[str, Any]:
        row = self.db.execute("SELECT body FROM objects WHERE kind=? AND id=?", (kind, key)).fetchone()
        if row is None:
            raise ContractError(f"missing {kind}: {key}")
        return json.loads(row["body"])

    def all(self, kind: str) -> list[dict[str, Any]]:
        return [json.loads(r["body"]) for r in self.db.execute(
            "SELECT body FROM objects WHERE kind=? ORDER BY rowid", (kind,))]

    def value(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_value(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        row = self.db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row["hash"] if row else "0" * 64
        body = {"kind": kind, "payload": payload}
        self.db.execute("INSERT INTO events(body,previous,hash) VALUES (?,?,?)",
                        (canonical(body), previous, digest([previous, body])))

    def verify_journal(self) -> int:
        previous, count = "0" * 64, 0
        for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
            if row["previous"] != previous or digest([previous, json.loads(row["body"])]) != row["hash"]:
                raise ContractError("journal integrity failure")
            previous, count = row["hash"], count + 1
        return count

    def verify_seal(self, kind: str, key: str, value: dict[str, Any]) -> None:
        event_kind, id_field, hash_field = {
            "run": ("run_closed", "run_id", "record_hash"),
            "evaluation": ("trial_evaluated", "trial", "receipt_hash"),
        }[kind]
        for row in self.db.execute("SELECT body FROM events ORDER BY seq DESC"):
            event = json.loads(row["body"])
            if event["kind"] == event_kind and event["payload"].get(id_field) == key:
                if event["payload"].get(hash_field) != digest(value):
                    raise ContractError("sealed record changed")
                return
        raise ContractError("record has no completion seal")
