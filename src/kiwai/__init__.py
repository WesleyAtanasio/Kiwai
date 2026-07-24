"""Kiwai: local-first idempotency for Python side effects."""

from .core import Kiwai
from .errors import (
    IdempotencyConflict,
    KiwaiError,
    LostLease,
    OperationInProgress,
    ResultSerializationError,
)
from .models import OperationRecord, OperationStatus
from .store import SQLiteStore

__all__ = [
    "IdempotencyConflict",
    "Kiwai",
    "KiwaiError",
    "LostLease",
    "OperationInProgress",
    "OperationRecord",
    "OperationStatus",
    "ResultSerializationError",
    "SQLiteStore",
]

__version__ = "0.1.0"
