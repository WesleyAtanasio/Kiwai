"""Public models used by Kiwai."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class OperationStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AcquireState(str, Enum):
    ACQUIRED = "acquired"
    CACHED = "cached"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True, slots=True)
class Acquisition:
    state: AcquireState
    key: str
    owner_token: str | None = None
    result: Any = None
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class OperationRecord:
    key: str
    payload_hash: str
    status: OperationStatus
    attempts: int
    created_at: float
    updated_at: float
    completed_at: float | None
    expires_at: float | None
    lease_expires_at: float | None
    error_type: str | None
    error_message: str | None
    metadata: dict[str, Any]
