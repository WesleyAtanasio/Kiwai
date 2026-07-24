from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from kiwai import (
    IdempotencyConflict,
    Kiwai,
    OperationInProgress,
    OperationStatus,
    ResultSerializationError,
)
from kiwai.serialization import payload_digest
from kiwai.store import SQLiteStore


def test_runs_side_effect_only_once(tmp_path: Path) -> None:
    calls: list[int] = []
    guard = Kiwai(tmp_path / "state.db")

    @guard.idempotent(key=lambda invoice_id: f"invoice:{invoice_id}")
    def send(invoice_id: int) -> dict[str, int]:
        calls.append(invoice_id)
        return {"invoice_id": invoice_id}

    assert send(42) == {"invoice_id": 42}
    assert send(42) == {"invoice_id": 42}
    assert calls == [42]


def test_same_key_with_different_payload_is_rejected(tmp_path: Path) -> None:
    guard = Kiwai(tmp_path / "state.db")

    @guard.idempotent(key="customer:welcome")
    def welcome(customer: str) -> str:
        return customer

    assert welcome("alice") == "alice"
    with pytest.raises(IdempotencyConflict):
        welcome("bob")


def test_failed_operation_can_be_retried(tmp_path: Path) -> None:
    guard = Kiwai(tmp_path / "state.db")
    attempts = 0

    @guard.idempotent(key="unstable")
    def unstable() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary")
        return "ok"

    with pytest.raises(RuntimeError):
        unstable()
    assert unstable() == "ok"
    assert attempts == 2


def test_active_lease_blocks_duplicate_worker(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.db")
    digest = payload_digest("job", (), {})
    first = store.acquire(key="job:1", payload_hash=digest, lease_seconds=10)
    second = store.acquire(key="job:1", payload_hash=digest, lease_seconds=10)
    assert first.owner_token
    assert second.state.value == "in_progress"


def test_expired_lease_is_reclaimed(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "state.db")
    digest = payload_digest("job", (), {})
    first = store.acquire(key="job:1", payload_hash=digest, lease_seconds=1, now=100)
    second = store.acquire(key="job:1", payload_hash=digest, lease_seconds=1, now=102)
    assert first.owner_token != second.owner_token
    assert second.attempts == 2


def test_ttl_allows_a_later_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    guard = Kiwai(tmp_path / "state.db")
    calls = 0
    clock = iter([100.0, 100.0, 102.0, 102.0])
    monkeypatch.setattr("kiwai.store.time.time", lambda: next(clock))

    @guard.idempotent(key="daily", ttl=1)
    def daily() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert daily() == 1
    assert daily() == 2


def test_concurrent_call_is_blocked(tmp_path: Path) -> None:
    guard = Kiwai(tmp_path / "state.db")
    started = threading.Event()
    release = threading.Event()

    @guard.idempotent(key="slow", lease=30)
    def slow() -> str:
        started.set()
        release.wait(timeout=2)
        return "done"

    thread = threading.Thread(target=slow)
    thread.start()
    assert started.wait(timeout=1)
    with pytest.raises(OperationInProgress):
        slow()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_async_functions_are_supported(tmp_path: Path) -> None:
    guard = Kiwai(tmp_path / "state.db")
    calls = 0

    @guard.idempotent(key=lambda item: f"async:{item}")
    async def work(item: int) -> dict[str, int]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"item": item}

    async def scenario() -> None:
        assert await work(7) == {"item": 7}
        assert await work(7) == {"item": 7}

    asyncio.run(scenario())
    assert calls == 1


def test_unserializable_result_is_recorded_as_success(tmp_path: Path) -> None:
    guard = Kiwai(tmp_path / "state.db")
    calls = 0

    @guard.idempotent(key="object-result")
    def returns_object() -> object:
        nonlocal calls
        calls += 1
        return object()

    with pytest.raises(ResultSerializationError):
        returns_object()
    assert returns_object() is None
    assert calls == 1
    record = guard.store.get("default:object-result")
    assert record is not None
    assert record.status is OperationStatus.SUCCEEDED


def test_cache_result_false_returns_none_on_replay(tmp_path: Path) -> None:
    guard = Kiwai(tmp_path / "state.db")
    calls = 0

    @guard.idempotent(key="fire-and-forget", cache_result=False)
    def action() -> object:
        nonlocal calls
        calls += 1
        return object()

    first = action()
    assert first is not None
    assert action() is None
    assert calls == 1
