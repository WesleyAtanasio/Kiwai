"""SQLite-backed idempotency storage."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import IdempotencyConflict, LostLease
from .models import Acquisition, AcquireState, OperationRecord, OperationStatus
from .serialization import loads_result

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kiwai_operations (
    key TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    owner_token TEXT,
    lease_expires_at REAL,
    result_json TEXT,
    error_type TEXT,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    expires_at REAL
);
CREATE INDEX IF NOT EXISTS idx_kiwai_status ON kiwai_operations(status);
CREATE INDEX IF NOT EXISTS idx_kiwai_expires_at ON kiwai_operations(expires_at);
"""


class SQLiteStore:
    """Durable, process-safe idempotency state stored in one SQLite file."""

    def __init__(self, path: str | Path = ".kiwai.db", *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def acquire(
        self,
        *,
        key: str,
        payload_hash: str,
        lease_seconds: float,
        metadata: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> Acquisition:
        current_time = time.time() if now is None else now
        lease_expires_at = current_time + lease_seconds
        owner_token = uuid.uuid4().hex
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM kiwai_operations WHERE key = ?",
                (key,),
            ).fetchone()

            if row is None:
                connection.execute(
                    """
                    INSERT INTO kiwai_operations (
                        key, payload_hash, status, owner_token, lease_expires_at,
                        metadata_json, attempts, created_at, updated_at
                    ) VALUES (?, ?, 'running', ?, ?, ?, 1, ?, ?)
                    """,
                    (key, payload_hash, owner_token, lease_expires_at, metadata_json, current_time, current_time),
                )
                return Acquisition(AcquireState.ACQUIRED, key, owner_token=owner_token, attempts=1)

            expired_record = row["expires_at"] is not None and row["expires_at"] <= current_time
            stale_lease = row["status"] == OperationStatus.RUNNING.value and (
                row["lease_expires_at"] is None or row["lease_expires_at"] <= current_time
            )

            if expired_record:
                connection.execute(
                    """
                    UPDATE kiwai_operations
                    SET payload_hash = ?, status = 'running', owner_token = ?, lease_expires_at = ?,
                        result_json = NULL, error_type = NULL, error_message = NULL,
                        metadata_json = ?, attempts = attempts + 1, updated_at = ?,
                        completed_at = NULL, expires_at = NULL
                    WHERE key = ?
                    """,
                    (payload_hash, owner_token, lease_expires_at, metadata_json, current_time, key),
                )
                return Acquisition(
                    AcquireState.ACQUIRED,
                    key,
                    owner_token=owner_token,
                    attempts=int(row["attempts"]) + 1,
                )

            if row["payload_hash"] != payload_hash:
                raise IdempotencyConflict(
                    f"Idempotency key {key!r} is already associated with a different function payload."
                )

            if row["status"] == OperationStatus.SUCCEEDED.value:
                return Acquisition(
                    AcquireState.CACHED,
                    key,
                    result=loads_result(row["result_json"]),
                    attempts=int(row["attempts"]),
                )

            if row["status"] == OperationStatus.RUNNING.value and not stale_lease:
                return Acquisition(AcquireState.IN_PROGRESS, key, attempts=int(row["attempts"]))

            connection.execute(
                """
                UPDATE kiwai_operations
                SET status = 'running', owner_token = ?, lease_expires_at = ?,
                    result_json = NULL, error_type = NULL, error_message = NULL,
                    metadata_json = ?, attempts = attempts + 1, updated_at = ?,
                    completed_at = NULL, expires_at = NULL
                WHERE key = ?
                """,
                (owner_token, lease_expires_at, metadata_json, current_time, key),
            )
            return Acquisition(
                AcquireState.ACQUIRED,
                key,
                owner_token=owner_token,
                attempts=int(row["attempts"]) + 1,
            )

    def succeed(
        self,
        *,
        key: str,
        owner_token: str,
        result_json: str | None,
        ttl_seconds: float | None,
        now: float | None = None,
    ) -> None:
        current_time = time.time() if now is None else now
        expires_at = None if ttl_seconds is None else current_time + ttl_seconds
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE kiwai_operations
                SET status = 'succeeded', owner_token = NULL, lease_expires_at = NULL,
                    result_json = ?, error_type = NULL, error_message = NULL,
                    updated_at = ?, completed_at = ?, expires_at = ?
                WHERE key = ? AND status = 'running' AND owner_token = ?
                """,
                (result_json, current_time, current_time, expires_at, key, owner_token),
            )
            if cursor.rowcount != 1:
                raise LostLease(f"The lease for {key!r} is no longer owned by this worker.")

    def fail(
        self,
        *,
        key: str,
        owner_token: str,
        error: BaseException,
        now: float | None = None,
    ) -> None:
        current_time = time.time() if now is None else now
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE kiwai_operations
                SET status = 'failed', owner_token = NULL, lease_expires_at = NULL,
                    result_json = NULL, error_type = ?, error_message = ?,
                    updated_at = ?, completed_at = ?, expires_at = NULL
                WHERE key = ? AND status = 'running' AND owner_token = ?
                """,
                (type(error).__name__, str(error), current_time, current_time, key, owner_token),
            )
            if cursor.rowcount != 1:
                raise LostLease(f"The lease for {key!r} is no longer owned by this worker.")

    def get(self, key: str) -> OperationRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM kiwai_operations WHERE key = ?", (key,)).fetchone()
        return None if row is None else self._to_record(row)

    def list(self, *, status: OperationStatus | str | None = None, limit: int = 100) -> list[OperationRecord]:
        query = "SELECT * FROM kiwai_operations"
        parameters: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            parameters.append(status.value if isinstance(status, OperationStatus) else status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._to_record(row) for row in rows]

    def delete(self, key: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute("DELETE FROM kiwai_operations WHERE key = ?", (key,))
            return cursor.rowcount == 1

    def purge(self, *, before: float | None = None) -> int:
        threshold = time.time() if before is None else before
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                DELETE FROM kiwai_operations
                WHERE (expires_at IS NOT NULL AND expires_at <= ?)
                   OR (status = 'failed' AND updated_at <= ?)
                """,
                (threshold, threshold),
            )
            return cursor.rowcount

    @staticmethod
    def _to_record(row: sqlite3.Row) -> OperationRecord:
        return OperationRecord(
            key=row["key"],
            payload_hash=row["payload_hash"],
            status=OperationStatus(row["status"]),
            attempts=int(row["attempts"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            completed_at=None if row["completed_at"] is None else float(row["completed_at"]),
            expires_at=None if row["expires_at"] is None else float(row["expires_at"]),
            lease_expires_at=None if row["lease_expires_at"] is None else float(row["lease_expires_at"]),
            error_type=row["error_type"],
            error_message=row["error_message"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
