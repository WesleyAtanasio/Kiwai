"""High-level decorator and execution API."""

from __future__ import annotations

import asyncio
import functools
import inspect
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar, overload

from .errors import OperationInProgress
from .models import AcquireState
from .serialization import dumps_result, payload_digest
from .store import SQLiteStore

P = ParamSpec("P")
R = TypeVar("R")
KeyFactory = str | Callable[..., str] | None


class Kiwai:
    """Protect Python side effects from duplicate execution."""

    def __init__(
        self,
        path: str | Path = ".kiwai.db",
        *,
        namespace: str = "default",
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self.namespace = namespace.strip() or "default"
        self.store = SQLiteStore(path, busy_timeout_ms=busy_timeout_ms)

    def _resolve_key(
        self,
        function: Callable[..., Any],
        key: KeyFactory,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        digest: str,
    ) -> str:
        if isinstance(key, str):
            raw_key = key
        elif callable(key):
            raw_key = str(key(*args, **kwargs))
        else:
            raw_key = f"{function.__module__}.{function.__qualname__}:{digest[:24]}"
        return f"{self.namespace}:{raw_key}"

    def _wait_for_result(self, operation_key: str, *, timeout: float, poll_interval: float) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.store.get(operation_key)
            if record is not None and record.status.value == "succeeded":
                acquisition = self.store.acquire(
                    key=operation_key,
                    payload_hash=record.payload_hash,
                    lease_seconds=1,
                )
                if acquisition.state is AcquireState.CACHED:
                    return acquisition.result
            if record is not None and record.status.value == "failed":
                break
            time.sleep(poll_interval)
        raise OperationInProgress(f"Operation {operation_key!r} is still running in another worker.")

    @overload
    def idempotent(
        self,
        *,
        key: KeyFactory = None,
        ttl: float | None = None,
        lease: float = 300,
        cache_result: bool = True,
        wait_timeout: float = 0,
        poll_interval: float = 0.1,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

    def idempotent(
        self,
        *,
        key: KeyFactory = None,
        ttl: float | None = None,
        lease: float = 300,
        cache_result: bool = True,
        wait_timeout: float = 0,
        poll_interval: float = 0.1,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        if lease <= 0:
            raise ValueError("lease must be greater than zero")
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be greater than zero or None")
        if wait_timeout < 0:
            raise ValueError("wait_timeout cannot be negative")

        def decorator(function: Callable[P, R]) -> Callable[P, R]:
            function_name = f"{function.__module__}.{function.__qualname__}"

            if inspect.iscoroutinefunction(function):

                @functools.wraps(function)
                async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    digest = payload_digest(function_name, args, kwargs)
                    operation_key = self._resolve_key(function, key, args, kwargs, digest)
                    acquisition = self.store.acquire(
                        key=operation_key,
                        payload_hash=digest,
                        lease_seconds=lease,
                        metadata=metadata,
                    )
                    if acquisition.state is AcquireState.CACHED:
                        return acquisition.result
                    if acquisition.state is AcquireState.IN_PROGRESS:
                        if wait_timeout <= 0:
                            raise OperationInProgress(
                                f"Operation {operation_key!r} is already running in another worker."
                            )
                        return await asyncio.to_thread(
                            self._wait_for_result,
                            operation_key,
                            timeout=wait_timeout,
                            poll_interval=poll_interval,
                        )

                    assert acquisition.owner_token is not None
                    try:
                        result = await function(*args, **kwargs)
                    except BaseException as exc:
                        self.store.fail(key=operation_key, owner_token=acquisition.owner_token, error=exc)
                        raise
                    try:
                        serialized = dumps_result(result) if cache_result else None
                    except BaseException:
                        self.store.succeed(
                            key=operation_key,
                            owner_token=acquisition.owner_token,
                            result_json=None,
                            ttl_seconds=ttl,
                        )
                        raise
                    self.store.succeed(
                        key=operation_key,
                        owner_token=acquisition.owner_token,
                        result_json=serialized,
                        ttl_seconds=ttl,
                    )
                    return result

                return async_wrapper  # type: ignore[return-value]

            @functools.wraps(function)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                digest = payload_digest(function_name, args, kwargs)
                operation_key = self._resolve_key(function, key, args, kwargs, digest)
                acquisition = self.store.acquire(
                    key=operation_key,
                    payload_hash=digest,
                    lease_seconds=lease,
                    metadata=metadata,
                )
                if acquisition.state is AcquireState.CACHED:
                    return acquisition.result
                if acquisition.state is AcquireState.IN_PROGRESS:
                    if wait_timeout <= 0:
                        raise OperationInProgress(
                            f"Operation {operation_key!r} is already running in another worker."
                        )
                    return self._wait_for_result(
                        operation_key,
                        timeout=wait_timeout,
                        poll_interval=poll_interval,
                    )

                assert acquisition.owner_token is not None
                try:
                    result = function(*args, **kwargs)
                except BaseException as exc:
                    self.store.fail(key=operation_key, owner_token=acquisition.owner_token, error=exc)
                    raise
                try:
                    serialized = dumps_result(result) if cache_result else None
                except BaseException:
                    self.store.succeed(
                        key=operation_key,
                        owner_token=acquisition.owner_token,
                        result_json=None,
                        ttl_seconds=ttl,
                    )
                    raise
                self.store.succeed(
                    key=operation_key,
                    owner_token=acquisition.owner_token,
                    result_json=serialized,
                    ttl_seconds=ttl,
                )
                return result

            return sync_wrapper

        return decorator
