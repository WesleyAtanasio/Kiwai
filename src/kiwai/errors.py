"""Exceptions raised by Kiwai."""

from __future__ import annotations


class KiwaiError(RuntimeError):
    """Base exception for the package."""


class IdempotencyConflict(KiwaiError):
    """Raised when an existing key is reused with a different payload."""


class OperationInProgress(KiwaiError):
    """Raised when another worker currently owns the operation lease."""


class LostLease(KiwaiError):
    """Raised when a worker tries to finish an operation it no longer owns."""


class ResultSerializationError(KiwaiError):
    """Raised when a cached function result is not JSON serializable."""
